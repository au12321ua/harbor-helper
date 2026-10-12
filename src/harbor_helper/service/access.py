"""Member-owned automation credentials. Plaintext exists only at issuance/authentication."""

import hashlib
import json
import math
import secrets
import time
import uuid

from argon2.exceptions import Argon2Error

from harbor_helper.service.data import PASSWORDS, ServiceError

SCOPES = {"read", "attachments", "execute", "cancel_own"}
PUBLIC = "id,user_id,name,scopes,created,expires,revoked,last_used"


def initialize(db):
    db.execute("BEGIN IMMEDIATE")
    db.execute("""CREATE TABLE IF NOT EXISTS access_credentials (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL, digest TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL, scopes TEXT NOT NULL, created REAL NOT NULL,
        expires REAL NOT NULL, revoked REAL, last_used REAL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS access_events (
        id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, access_credential_id TEXT,
        action TEXT NOT NULL, object_id TEXT NOT NULL, time REAL NOT NULL)""")


def public(row):
    value = dict(row)
    value.pop("digest", None)
    value["scopes"] = json.loads(value["scopes"])
    return value


def issue(data, actor, name, password, scopes, expires, *, access_value=None):
    if actor.get("access_credential_id"):
        raise ServiceError("session_required", "Browser session required", 403)
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 128:
        raise ServiceError("invalid_name", "Credential name must be 1–128 characters")
    if not isinstance(scopes, list) or not scopes or set(scopes) - SCOPES:
        raise ServiceError("invalid_scopes", "Select fixed automation capabilities")
    from harbor_helper.security.access_tokens import ACCESS_TOKEN_TEXT

    if ACCESS_TOKEN_TEXT.search(name) or (access_value and access_value in name):
        raise ServiceError("access_plaintext", "Access credential plaintext forbidden in name")
    now = time.time()
    expires = now + 30 * 86400 if expires is None else expires
    try:
        valid_expiry = type(expires) in {int, float} and math.isfinite(expires) and expires > now
    except OverflowError:
        valid_expiry = False
    if not valid_expiry:
        raise ServiceError("invalid_expiry", "Expiry must be a finite future Unix timestamp")
    # Reuse login's password verification/rate limit; immediately remove temporary session.
    session, _ = data.login(actor["username"], password)
    data.logout(session)
    value = "hh_pat_v1_" + secrets.token_urlsafe(32)
    credential_id = uuid.uuid4().hex
    with data.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT password,enabled FROM users WHERE id=?", (actor["id"],)).fetchone()
        # Password reset/disable concurrent with verification must not mint a new credential.
        try:
            if not row or not row["enabled"]:
                raise ValueError
            PASSWORDS.verify(row["password"], password)
        except (Argon2Error, ValueError):
            raise ServiceError(
                "login_required", "Current password verification required", 401
            ) from None
        db.execute(
            "INSERT INTO access_credentials VALUES(?,?,?,?,?,?,?,NULL,NULL)",
            (
                credential_id,
                actor["id"],
                hashlib.sha256(value.encode()).hexdigest(),
                name.strip(),
                json.dumps(sorted(set(scopes))),
                now,
                expires,
            ),
        )
        db.execute(
            "INSERT INTO access_events(user_id,action,object_id,time) VALUES(?,?,?,?)",
            (actor["id"], "issue_access_credential", credential_id, now),
        )
        result = public(
            db.execute(
                f"SELECT {PUBLIC} FROM access_credentials WHERE id=?", (credential_id,)
            ).fetchone()
        )
    return {"credential": result, "token": value}


def listing(data, actor, all_users=False):
    with data.store.connect() as db:
        rows = db.execute(
            f"SELECT {PUBLIC} FROM access_credentials"
            + ("" if all_users else " WHERE user_id=?")
            + " ORDER BY created DESC",
            () if all_users else (actor["id"],),
        ).fetchall()
    return [public(r) for r in rows]


def revoke(data, actor, credential_id):
    if actor.get("access_credential_id"):
        raise ServiceError("session_required", "Browser session required", 403)
    with data.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT user_id FROM access_credentials WHERE id=?", (credential_id,)
        ).fetchone()
        if not row or (actor["role"] != "admin" and actor["id"] != row[0]):
            raise ServiceError("access_credential_missing", "Credential not found", 404)
        db.execute(
            "UPDATE access_credentials SET revoked=COALESCE(revoked,?) WHERE id=?",
            (time.time(), credential_id),
        )
        db.execute(
            "INSERT INTO access_events(user_id,action,object_id,time) VALUES(?,?,?,?)",
            (actor["id"], "revoke_access_credential", credential_id, time.time()),
        )
    return {"id": credential_id, "revoked": True}
