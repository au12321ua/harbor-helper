"""Service persistence, invited identities and explicitly bound encrypted credentials.

No request changes process-global environments. Secrets leave this module only for
an independent worker or its audit, never through public metadata.
"""

import hashlib
import json
import os
import re
import secrets
import stat
import time
import uuid
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from harbor_helper.config import DEFAULT, reject_secrets
from harbor_helper.storage import TERMINAL, Store, read_json, write_json

LIMITS = {
    "max_jobs": 1,
    "max_trials": 2,
    "max_queue": 100,
    "max_attempts": 3,
    "max_wall_seconds": 3600,
    "max_cpus_per_trial": 2,
    "max_memory_mb_per_trial": 4096,
    "max_upload_bytes": 16 * 1024 * 1024,
    "log_retention_days": 14,
    "artifact_retention_days": 7,
}
PASSWORDS = PasswordHasher()


class ServiceError(ValueError):
    def __init__(self, code, message, status=422):
        self.code, self.status = code, status
        super().__init__(message)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
        raise ServiceError("invalid_id", "Use a 1–64 character identifier (letters, digits, . _ -)")
    return value


def secret_value(value):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 16384
        or any(c.isspace() or ord(c) < 32 for c in value)
    ):
        raise ServiceError("invalid_key", "A nonempty single-line credential is required")
    return value


def public_user(row):
    return {**dict(row), "enabled": bool(row["enabled"])}


def public_object(row):
    return {**json.loads(row["config"]), "id": row["id"], "version": row["version"]}


class ServiceData:
    def __init__(self, root, *, initializing=False):
        self.store = root if isinstance(root, Store) else Store(root)
        self.root = self.store.root
        if not initializing and not (self.root / "service.json").is_file():
            raise ServiceError(
                "service_not_initialized", "Initialize a dedicated service state", 503
            )
        with self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL, role TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS sessions (
                    digest TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS login_failures (
                    username TEXT PRIMARY KEY, attempts INTEGER NOT NULL, until REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS objects (
                    kind TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL,
                    config TEXT NOT NULL, PRIMARY KEY(kind,id,version));
                CREATE TABLE IF NOT EXISTS credential_versions (
                    id TEXT NOT NULL, version INTEGER NOT NULL, provider_id TEXT NOT NULL,
                    label TEXT NOT NULL, enabled INTEGER NOT NULL, nonce BLOB NOT NULL,
                    ciphertext BLOB NOT NULL, created REAL NOT NULL, PRIMARY KEY(id,version));
                CREATE TABLE IF NOT EXISTS submissions (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, submitter TEXT NOT NULL,
                    operation TEXT NOT NULL, idem TEXT NOT NULL, request_hash TEXT NOT NULL,
                    request TEXT NOT NULL, frozen TEXT NOT NULL, target_id TEXT NOT NULL,
                    run_id TEXT, status TEXT NOT NULL, created REAL NOT NULL, error TEXT,
                    cancel INTEGER NOT NULL DEFAULT 0, parent TEXT,
                    UNIQUE(user_id,operation,idem));
                CREATE TABLE IF NOT EXISTS bundles (
                    id TEXT PRIMARY KEY, digest TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS artifact_deletions (
                    run_id TEXT NOT NULL, file_id TEXT NOT NULL, actor TEXT NOT NULL,
                    time REAL NOT NULL, PRIMARY KEY(run_id,file_id));
                CREATE TABLE IF NOT EXISTS admin_events (
                    id INTEGER PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL,
                    object_id TEXT NOT NULL, time REAL NOT NULL);
            """)

    @classmethod
    def initialize(cls, root, master_file, username, password, team=None):
        store = root if isinstance(root, Store) else Store(root)
        with store.control():
            return cls._initialize(store, master_file, username, password, team)

    @classmethod
    def _initialize(cls, store, master_file, username, password, team):
        identifier(username)
        if not isinstance(password, str) or not 12 <= len(password) <= 512:
            raise ServiceError("invalid_password", "Password must be 12–512 characters")
        master = Path(master_file).expanduser().absolute()
        if master.is_relative_to(store.root):
            raise ServiceError("master_location", "Master key must be outside service state")
        if (store.root / "service.json").exists() or (store.root / "team.json").exists():
            raise ServiceError("already_initialized", "Use a new dedicated service state", 409)
        master.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not master.exists():
            fd = os.open(master, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as file:
                file.write(secrets.token_bytes(32))
        data = cls(store, initializing=True)
        data._master(master)
        config = json.loads(json.dumps(team or DEFAULT))
        reject_secrets(config)
        config.update({key: value for key, value in LIMITS.items() if key in DEFAULT})
        write_json(store.root / "team.json", config)
        store.root.chmod(0o700)
        (store.root / "runs").chmod(0o700)
        data.create_user(username, password, "admin")
        data.set_limits(LIMITS)
        write_json(
            store.root / "service.json", {"master_file": str(master), "session_seconds": 28800}
        )
        for name in ("service.json", "team.json", "queue.sqlite", "limits.json"):
            (store.root / name).chmod(0o600)
        return data

    def _master(self, path=None):
        path = Path(path or read_json(self.root / "service.json")["master_file"])
        if path.resolve().is_relative_to(self.root) or path.is_symlink():
            raise ServiceError(
                "master_unavailable", "Protected external master key unavailable", 503
            )
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as file:
                meta = os.fstat(file.fileno())
                raw = file.read(33)
            if (
                not stat.S_ISREG(meta.st_mode)
                or meta.st_uid != os.getuid()
                or (stat.S_IMODE(meta.st_mode) & 0o077)
                or len(raw) != 32
            ):
                raise ValueError
            return raw
        except (OSError, ValueError):
            raise ServiceError(
                "master_unavailable", "Protected external master key unavailable", 503
            ) from None

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
        return user

    def users(self):
        with self.store.connect() as db:
            return [
                public_user(r)
                for r in db.execute("SELECT id,username,role,enabled FROM users ORDER BY username")
            ]

    def user(self, user_id):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT id,username,role,enabled FROM users WHERE id=?", (user_id,)
            ).fetchone()
        if row is None:
            raise ServiceError("unknown_user", "Account not found", 404)
        return public_user(row)

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
        return self.user(user_id)

    def login(self, username, password):
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
        token = secrets.token_urlsafe(32)
        seconds = read_json(self.root / "service.json")["session_seconds"]
        with self.store.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            db.execute("DELETE FROM login_failures WHERE username=?", (username,))
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?)",
                (hashlib.sha256(token.encode()).hexdigest(), row["id"], time.time() + seconds),
            )
        return token, self.user(row["id"])

    def actor(self, token):
        digest = hashlib.sha256((token or "").encode()).hexdigest()
        with self.store.connect() as db:
            row = db.execute(
                """SELECT u.id,u.username,u.role,u.enabled FROM sessions s
                JOIN users u ON u.id=s.user_id WHERE digest=? AND expires>? AND enabled=1""",
                (digest, time.time()),
            ).fetchone()
        if row is None:
            raise ServiceError("login_required", "Please log in", 401)
        return public_user(row)

    def logout(self, token):
        with self.store.connect() as db:
            db.execute(
                "DELETE FROM sessions WHERE digest=?",
                (hashlib.sha256((token or "").encode()).hexdigest(),),
            )

    def event(self, actor, action, object_id):
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO admin_events(actor,action,object_id,time) VALUES(?,?,?,?)",
                (actor["username"], action, object_id, time.time()),
            )

    def objects(self, kind):
        with self.store.connect() as db:
            rows = db.execute(
                """SELECT o.* FROM objects o JOIN
                (SELECT id,MAX(version) v FROM objects WHERE kind=? GROUP BY id) c
                ON c.id=o.id AND c.v=o.version WHERE o.kind=? ORDER BY o.id""",
                (kind, kind),
            ).fetchall()
        return [public_object(r) for r in rows]

    def object(self, kind, object_id, version=None):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM objects WHERE kind=? AND id=? "
                + ("AND version=?" if version else "ORDER BY version DESC LIMIT 1"),
                (kind, object_id, version) if version else (kind, object_id),
            ).fetchone()
        if row is None:
            raise ServiceError("unknown_configuration", "Configuration not found", 404)
        return public_object(row)

    def save_object(self, kind, value):
        object_id = identifier(value.get("id") or uuid.uuid4().hex)
        value = dict(value)
        value["id"] = object_id
        value.pop("version", None)
        reject_secrets(value)
        if kind == "provider":
            if set(value) - {"id", "name", "protocol", "endpoint", "enabled"}:
                raise ServiceError("provider_options", "Unknown provider options")
            from urllib.parse import urlparse

            url = urlparse(value.get("endpoint", ""))
            if (
                value.get("protocol") != "openai-compatible"
                or url.scheme not in {"http", "https"}
                or not url.hostname
            ):
                raise ServiceError(
                    "unsupported_provider",
                    "First release supports explicit OpenAI-compatible endpoints",
                )
        elif kind == "profile":
            if set(value) - {
                "id",
                "name",
                "provider_id",
                "credential_id",
                "model",
                "params",
                "opencode_version",
                "enabled",
            }:
                raise ServiceError("profile_options", "Unknown model profile options")
            provider = self.object("provider", value.get("provider_id"))
            credential = self.credential(value.get("credential_id"))
            if credential["provider_id"] != provider["id"]:
                raise ServiceError("credential_binding", "Credential belongs to another provider")
            if (
                not isinstance(value.get("model"), str)
                or not value["model"]
                or not isinstance(value.get("params", {}), dict)
            ):
                raise ServiceError("invalid_model", "Model ID and parameter mapping are required")
            value.setdefault("params", {})
            value.setdefault("opencode_version", "1.18.35")
            if not re.fullmatch(r"\d+\.\d+\.\d+", value["opencode_version"]):
                raise ServiceError(
                    "invalid_runtime", "A fixed numeric OpenCode version is required"
                )
        else:
            raise ServiceError("configuration_kind", "Unsupported configuration")
        value.setdefault("enabled", True)
        if type(value["enabled"]) is not bool:
            raise ServiceError("invalid_status", "enabled must be boolean")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM objects WHERE kind=? AND id=?",
                (kind, object_id),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO objects VALUES(?,?,?,?)", (kind, object_id, version, json.dumps(value))
            )
        return {**value, "version": version}

    def credential(self, credential_id, version=None):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT id,version,provider_id,label,enabled,created FROM credential_versions WHERE id=? "
                + ("AND version=?" if version else "ORDER BY version DESC LIMIT 1"),
                (credential_id, version) if version else (credential_id,),
            ).fetchone()
        if row is None:
            raise ServiceError("credential_missing", "Bound credential unavailable", 409)
        return public_user(row)

    def credentials(self):
        with self.store.connect() as db:
            ids = [
                r[0] for r in db.execute("SELECT DISTINCT id FROM credential_versions ORDER BY id")
            ]
        return [self.credential(i) for i in ids]

    def add_credential(self, credential_id, provider_id, label, key, rotate=False):
        identifier(credential_id)
        self.object("provider", provider_id)
        secret_value(key)
        if not isinstance(label, str) or not 1 <= len(label) <= 128:
            raise ServiceError("invalid_label", "Credential label must be 1–128 characters")
        master = self._master()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT * FROM credential_versions WHERE id=? ORDER BY version DESC LIMIT 1",
                (credential_id,),
            ).fetchone()
            if old and (not rotate or old["provider_id"] != provider_id):
                raise ServiceError(
                    "credential_exists",
                    "Use explicit rotation of the same credential/provider",
                    409,
                )
            if rotate and old is None:
                raise ServiceError("credential_missing", "Credential not found", 404)
            version = old["version"] + 1 if old else 1
            nonce = secrets.token_bytes(12)
            aad = f"{provider_id}/{credential_id}/{version}".encode()
            ciphertext = AESGCM(master).encrypt(nonce, key.encode(), aad)
            db.execute(
                "INSERT INTO credential_versions VALUES(?,?,?,?,1,?,?,?)",
                (credential_id, version, provider_id, label, nonce, ciphertext, time.time()),
            )
        return self.credential(credential_id)

    def disable_credential(self, credential_id):
        self.credential(credential_id)
        with self.store.connect() as db:
            db.execute("UPDATE credential_versions SET enabled=0 WHERE id=?", (credential_id,))
        return self.credential(credential_id)

    def key(self, credential_id, version, provider_id, execution=False):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM credential_versions WHERE id=? AND version=?",
                (credential_id, version),
            ).fetchone()
        if row is None or row["provider_id"] != provider_id or (execution and not row["enabled"]):
            raise ServiceError(
                "credential_unavailable", "Bound credential unavailable or disabled", 409
            )
        try:
            return (
                AESGCM(self._master())
                .decrypt(
                    row["nonce"],
                    row["ciphertext"],
                    f"{provider_id}/{credential_id}/{version}".encode(),
                )
                .decode()
            )
        except (InvalidTag, UnicodeError):
            raise ServiceError(
                "credential_unavailable", "Bound credential cannot be decrypted", 409
            ) from None

    def run_key(self, run_id, execution=False):
        manifest = read_json(self.store.path(run_id) / "manifest.json")
        binding = manifest.get("service") or {}
        if manifest["effective"]["agent"] == "oracle":
            if execution and not self.user(binding["user_id"])["enabled"]:
                raise ServiceError("member_disabled", "Submitting account is disabled", 409)
            return None
        if execution:
            if (
                not self.user(binding["user_id"])["enabled"]
                or not self.object("provider", binding["provider_id"])["enabled"]
            ):
                raise ServiceError(
                    "execution_disabled", "Submitting account or provider disabled", 409
                )
            if (
                self.object("provider", binding["provider_id"], binding["provider_version"])[
                    "endpoint"
                ]
                != manifest["effective"]["model"]["endpoint"]
            ):
                raise ServiceError("binding_mismatch", "Fixed provider binding mismatch", 409)
        return self.key(
            binding["credential_id"],
            binding["credential_version"],
            binding["provider_id"],
            execution,
        )

    def limits(self):
        path = self.root / "limits.json"
        return {**LIMITS, **(read_json(path) if path.exists() else {})}

    def set_limits(self, value):
        if set(value) - set(LIMITS):
            raise ServiceError("unknown_limit", "Unknown capacity or retention parameter")
        limits = {**self.limits(), **value}
        if any(type(v) is not int or v < 1 for v in limits.values()):
            raise ServiceError("invalid_limit", "Limits must be positive integers")
        # Avoid unlimited administrative typo-driven expansion.
        if (
            limits["max_jobs"] > 64
            or limits["max_trials"] > 128
            or limits["max_upload_bytes"] > 1024**3
        ):
            raise ServiceError("invalid_limit", "Limit exceeds first-release safety bound")
        write_json(self.root / "limits.json", limits)
        team = read_json(self.root / "team.json")
        team.update({k: v for k, v in limits.items() if k in DEFAULT})
        write_json(self.root / "team.json", team)
        return limits

    def submission(self, submission_id):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM submissions WHERE id=?", (submission_id,)).fetchone()
        if row is None:
            raise ServiceError("submission_missing", "Submission not found", 404)
        result = dict(row)
        result["request"] = json.loads(result["request"])
        result["frozen"] = json.loads(result["frozen"])
        return result

    def allow_publish(self, submission_id):
        row = self.submission(submission_id)
        return (
            not row["cancel"]
            and row["status"] == "preparing"
            and self.user(row["user_id"])["enabled"]
        )

    def dependencies(self):
        refs = set()
        with self.store.connect() as db:
            for row in db.execute("SELECT frozen FROM submissions WHERE status='preparing'"):
                binding = json.loads(row[0])["service"]
                if binding.get("credential_id"):
                    refs.add((binding["credential_id"], binding["credential_version"]))
        for row in self.store.runs():
            manifest = read_json(self.store.path(row["id"]) / "manifest.json")
            binding = manifest.get("service") or {}
            # A retained raw run is an audit dependency; archived safe views aren't.
            if binding.get("credential_id") and (
                row["status"] not in TERMINAL
                or not (self.store.path(row["id"]) / "archived.json").exists()
            ):
                refs.add((binding["credential_id"], binding["credential_version"]))
        return refs

    def prune_credentials(self):
        dependencies = self.dependencies()
        current = {(c["id"], c["version"]) for c in self.credentials()}
        count = 0
        with self.store.connect() as db:
            for row in db.execute("SELECT id,version FROM credential_versions").fetchall():
                ref = (row["id"], row["version"])
                if ref not in dependencies and ref not in current:
                    db.execute("DELETE FROM credential_versions WHERE id=? AND version=?", ref)
                    count += 1
        return {"pruned_versions": count, "retained_dependencies": len(dependencies)}
