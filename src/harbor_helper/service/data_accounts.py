"""Accounts persistence operations sharing the service store."""

import hashlib
import json
import secrets
import time
import uuid
from typing import TYPE_CHECKING

from argon2.exceptions import Argon2Error

from harbor_helper.persistence.files import read_json
from harbor_helper.persistence.wakeup import wake_after
from harbor_helper.security.passwords import PASSWORDS
from harbor_helper.service.primitives import (
    ServiceError,
    identifier,
    public_user,
)

if TYPE_CHECKING:
    from pathlib import Path

    from harbor_helper.persistence.store import Store


class Accounts:
    if TYPE_CHECKING:
        store: Store
        root: Path

    @wake_after
    def create_user(self, username, password, role="member"):
        identifier(username)
        if (
            role not in {"member", "admin"}
            or not isinstance(password, str)
            or not 12 <= len(password) <= 512
        ):
            raise ServiceError(
                "invalid_account", "Role must be member/admin; password 12–512 characters"
            )
        user = {"id": uuid.uuid4().hex, "username": username, "role": role, "enabled": True}
        with self.store.connect() as db:
            if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                raise ServiceError("account_exists", "Account already exists", 409)
            db.execute(
                "INSERT INTO users VALUES(?,?,?,?,1)",
                (user["id"], username, PASSWORDS.hash(password), role),
            )
        return self.user(user["id"])

    def users(self):
        with self.store.connect() as db:
            return [
                public_user(r)
                for r in db.execute(
                    "SELECT u.id,u.username,u.role,u.enabled,(u.role='admin' OR COALESCE(g.granted,0)) evidence_grant FROM users u LEFT JOIN evidence_grants g ON g.user_id=u.id ORDER BY u.username"
                )
            ]

    def user(self, user_id):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT id,username,role,enabled FROM users WHERE id=?", (user_id,)
            ).fetchone()
        if row is None:
            raise ServiceError("unknown_user", "Account not found", 404)
        from harbor_helper.service.access import granted

        return {**public_user(row), "evidence_grant": granted(self, user_id)}

    @wake_after
    def update_user(self, user_id, enabled=None, password=None):
        user = self.user(user_id)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                enabled is False
                and user["role"] == "admin"
                and db.execute(
                    "SELECT COUNT(*) FROM users WHERE role='admin' AND enabled=1"
                ).fetchone()[0]
                <= 1
            ):
                raise ServiceError("last_admin", "Cannot disable the last administrator", 409)
            if enabled is not None:
                db.execute("UPDATE users SET enabled=? WHERE id=?", (int(enabled), user_id))
            if password is not None:
                if not isinstance(password, str) or not 12 <= len(password) <= 512:
                    raise ServiceError("invalid_password", "Password must be 12–512 characters")
                db.execute(
                    "UPDATE users SET password=? WHERE id=?", (PASSWORDS.hash(password), user_id)
                )
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            if password is not None or enabled is False:
                db.execute(
                    "UPDATE access_credentials SET revoked=COALESCE(revoked,?) WHERE user_id=?",
                    (time.time(), user_id),
                )
        return self.user(user_id)

    def verify_password(self, username, password):
        username = username if isinstance(username, str) and len(username) <= 64 else "invalid"
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            failure = db.execute(
                "SELECT * FROM login_failures WHERE username=?", (username,)
            ).fetchone()
        if failure and failure["attempts"] >= 5 and failure["until"] > time.time():
            raise ServiceError(
                "login_limited", "Too many login attempts; retry in five minutes", 429
            )
        try:
            if (
                row is None
                or not row["enabled"]
                or not isinstance(password, str)
                or len(password) > 512
            ):
                # Use a real Argon2 operation for nonexistent accounts, too.
                PASSWORDS.hash("invalid-login")
                raise ValueError
            PASSWORDS.verify(row["password"], password)
        except (Argon2Error, ValueError):
            with self.store.connect() as db:
                db.execute(
                    """INSERT INTO login_failures VALUES(?,1,?) ON CONFLICT(username)
                    DO UPDATE SET attempts=CASE WHEN until<? THEN 1 ELSE attempts+1 END,until=?""",
                    (username, time.time() + 300, time.time(), time.time() + 300),
                )
            raise ServiceError("invalid_login", "Invalid login", 401) from None
        with self.store.connect() as db:
            db.execute("DELETE FROM login_failures WHERE username=?", (username,))
        return self.user(row["id"])

    def login(self, username, password):
        user = self.verify_password(username, password)
        token = secrets.token_urlsafe(32)
        seconds = read_json(self.root / "service.json")["session_seconds"]
        with self.store.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            db.execute("DELETE FROM login_failures WHERE username=?", (username,))
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?)",
                (hashlib.sha256(token.encode()).hexdigest(), user["id"], time.time() + seconds),
            )
        return token, user

    def actor(self, token):
        digest = hashlib.sha256((token or "").encode()).hexdigest()
        with self.store.connect() as db:
            if (token or "").startswith("hh_pat_v1_"):
                row = db.execute(
                    """SELECT u.id,u.username,u.enabled,u.role account_role,c.id access_credential_id,c.scopes
                    FROM access_credentials c JOIN users u ON u.id=c.user_id
                    WHERE c.digest=? AND c.expires>? AND c.revoked IS NULL AND u.enabled=1""",
                    (digest, time.time()),
                ).fetchone()
                if row is not None:
                    from harbor_helper.service.access import granted

                    if "evidence" in json.loads(row["scopes"]) and not granted(self, row["id"], db):
                        raise ServiceError(
                            "login_required", "Automation authorization revoked", 401
                        )
                    db.execute(
                        "UPDATE access_credentials SET last_used=? WHERE id=?",
                        (time.time(), row["access_credential_id"]),
                    )
                    return {
                        **dict(row),
                        "enabled": True,
                        "role": "member",
                        "scopes": json.loads(row["scopes"]),
                    }
            else:
                row = db.execute(
                    """SELECT u.id,u.username,u.role,u.enabled FROM sessions s
                    JOIN users u ON u.id=s.user_id WHERE digest=? AND expires>? AND enabled=1""",
                    (digest, time.time()),
                ).fetchone()
                if row is not None:
                    return public_user(row)
        raise ServiceError("login_required", "Please log in or renew automation authorization", 401)

    def logout(self, token):
        with self.store.connect() as db:
            db.execute(
                "DELETE FROM sessions WHERE digest=?",
                (hashlib.sha256((token or "").encode()).hexdigest(),),
            )
