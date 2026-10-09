"""Account-local, team/provider-bound sessions. Values never enter shared state."""

import getpass
import hashlib
import math
import os
import re
import stat
import time
import uuid
import warnings
from contextlib import contextmanager
from pathlib import Path

from harbor_helper.persistence.store import TERMINAL
from harbor_helper.security.credentials import KEY_ENV, read_key_file, runtime_secrets
from harbor_helper.security.errors import AuthError
from harbor_helper.security.files import secure_read, secure_write


def ttl_seconds(value):
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([smhd]?)", str(value))
    if not match:
        raise ValueError("TTL must be positive seconds or a duration such as 30m/8h")
    result = float(match[1]) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[match[2]]
    if not math.isfinite(result) or result <= 0:
        raise ValueError("TTL must be positive and finite")
    return result


def protected_key(path):
    info = Path(path).lstat()
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise AuthError("Key file must have mode 0600")
    return read_key_file(path)


def private_root(create=False):
    root = Path.home() / ".config" / "harbor-helper"
    if create:
        root.parent.mkdir(parents=True, exist_ok=True)
    for path in (root, root / "auth"):
        if create:
            path.mkdir(mode=0o700, exist_ok=True)
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700
            ):
                raise AuthError("Private auth directory must be owned by this account, mode 0700")
    return root


def select_team(state):
    root = private_root(create=True)
    secure_write(root / "selected-team.json", {"state": str(Path(state).resolve())})


def resolve_state(explicit=None):
    if explicit:
        return Path(explicit).expanduser().resolve()
    if os.environ.get("HARBOR_HELPER_STATE"):
        return Path(os.environ["HARBOR_HELPER_STATE"]).expanduser().resolve()
    selected = private_root() / "selected-team.json"
    if selected.exists() or selected.is_symlink():
        choice = secure_read(selected)
        if not isinstance(choice, dict) or not isinstance(choice.get("state"), str):
            raise AuthError("Invalid selected team record; pass --state explicitly")
        return Path(choice["state"]).resolve()
    for parent in (Path.cwd(), *Path.cwd().parents):
        if (parent / "pyproject.toml").is_file() and (parent / ".state/team/team.json").is_file():
            return parent / ".state/team"
    return Path.home() / ".local/state/harbor-helper"


class Auth:
    def __init__(self, state):
        self.state = Path(state).resolve()
        self.directory = (
            private_root() / "auth" / hashlib.sha256(str(self.state).encode()).hexdigest()
        )
        # Credentials must never be within a state scanned or exported as evidence.
        private = private_root()
        if private.is_relative_to(self.state) or self.state.is_relative_to(private):
            raise AuthError("Team state and private auth directory must be separate")

    def prepare(self):
        private_root(create=True)
        self.directory.mkdir(mode=0o700, exist_ok=True)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise AuthError("Private team auth directory owner/type invalid")
        if stat.S_IMODE(info.st_mode) != 0o700:
            raise AuthError("Private team auth directory must have mode 0700")

    def check_directory(self):
        private_root()
        if self.directory.exists() or self.directory.is_symlink():
            info = self.directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise AuthError("Private team auth directory owner/type invalid")
            if stat.S_IMODE(info.st_mode) != 0o700:
                raise AuthError("Private team auth directory must have mode 0700")

    def record(self, session_id=None):
        self.check_directory()
        if session_id is None:
            current = self.directory / "current.json"
            if not current.exists() and not current.is_symlink():
                raise AuthError("Not logged in; run harbor-helper auth login")
            pointer = secure_read(current)
            if not isinstance(pointer, dict) or "id" not in pointer:
                raise AuthError("Invalid private execution pointer")
            session_id = pointer["id"]
        if not isinstance(session_id, str) or not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise AuthError("Invalid private session identity")
        record = secure_read(self.directory / ("session-" + session_id + ".json"))
        if not isinstance(record, dict) or not {
            "state",
            "id",
            "kind",
            "source",
            "fingerprint",
            "endpoint",
            "expires_at",
        }.issubset(record):
            raise AuthError("Invalid private session record")
        if record["kind"] not in {"none", "cache", "reference"} or not isinstance(
            record["expires_at"], (int, float)
        ):
            raise AuthError("Invalid private session record")
        if record.get("state") != str(self.state) or record.get("id") != session_id:
            raise AuthError("Login is bound to another team")
        return record

    def value(self, record):
        if record["kind"] == "none":
            return None
        try:
            value = protected_key(Path(record["source"]))
        except (OSError, ValueError):
            raise AuthError("Login key file unavailable/invalid; restore owner-only file") from None
        if hashlib.sha256(value.encode()).hexdigest() != record["fingerprint"]:
            raise AuthError("Referenced key changed; do not replace it during unfinished tasks")
        return value

    def execution(self, endpoint, session_id=None):
        record = self.record()
        if session_id is not None and record["id"] != session_id:
            raise AuthError("Queued login was revoked; no model request sent")
        if record["endpoint"] != endpoint:
            raise AuthError(
                "Login provider endpoint differs; run auth login for this configuration"
            )
        if time.time() >= record["expires_at"]:
            raise AuthError("Login expired; run auth login (no model request sent)")
        return record, self.value(record)

    def audit_keys(self):
        self.check_directory()
        keys, unavailable = [], 0
        file = self.directory / "bindings.json"
        bindings = secure_read(file) if file.exists() else {}
        for session_id in sorted(set(bindings.values())):
            try:
                value = self.value(self.record(session_id))
                if value and value not in keys:
                    keys.append(value)
            except AuthError:
                unavailable += 1
        return keys, unavailable

    def bind(self, run_id, session_id):
        self.prepare()
        file = self.directory / "bindings.json"
        bindings = secure_read(file) if file.exists() else {}
        bindings[run_id] = session_id
        secure_write(file, bindings)

    def bound_record(self, run_id):
        self.check_directory()
        file = self.directory / "bindings.json"
        bindings = secure_read(file) if file.exists() else {}
        if run_id not in bindings:
            return None
        return self.record(bindings[run_id])

    def worker_credentials(self, run_id, endpoint):
        record = self.bound_record(run_id)
        if record is None:
            raise AuthError("Model run has no login binding; login and create a new submission")
        return self.execution(endpoint, record["id"])

    def audit_run_key(self, run_id):
        record = self.bound_record(run_id)
        if record is None:
            return None  # Compatibility: old workers/file launcher supply their runtime key.
        try:
            return self.value(record)
        except AuthError:
            # A live process may retain its own original key after external file damage.
            for key in runtime_secrets():
                if hashlib.sha256(key.encode()).hexdigest() == record["fingerprint"]:
                    return key
            raise

    def discard_unused_except(self, keep=None):
        file = self.directory / "bindings.json"
        used = set(secure_read(file).values()) if file.exists() else set()
        for file in self.directory.glob("session-*.json"):
            session_id = file.stem.removeprefix("session-")
            if session_id not in used and session_id != keep:
                record = self.record(session_id)
                if record["kind"] == "cache":
                    Path(record["source"]).unlink(missing_ok=True)
                file.unlink()

    def logout(self, store):
        if any(row["status"] not in TERMINAL for row in store.runs()):
            raise AuthError("Unfinished tasks: wait or cancel before login/logout")
        self.check_directory()
        (self.directory / "current.json").unlink(missing_ok=True)
        self.discard_unused_except()
        value = self.status()
        value.update(execution_revoked=True)
        value["detail"] = (
            "New execution revoked; used historical audit sources remain protected"
            if value.get("historical_audit_retained")
            else "New execution revoked; no used historical audit sources retained"
        )
        return value

    def login(self, store, model, ttl, key_file=None):
        if any(row["status"] not in TERMINAL for row in store.runs()):
            raise AuthError(
                "Unfinished tasks: wait for terminal states or cancel before login/logout"
            )
        if not model:
            raise AuthError("Model not configured; maintainer must configure team.json first")
        self.prepare()
        session_id = uuid.uuid4().hex
        kind, source, value = "none", None, None
        if model.get("credential_env"):
            if key_file:
                kind = "reference"
                source = str(Path(key_file).expanduser().absolute())
                if Path(source).resolve().is_relative_to(self.state):
                    raise AuthError("Key file must be outside experiment state")
                try:
                    value = protected_key(Path(source))
                except (OSError, ValueError):
                    raise AuthError(
                        "Key file unavailable/invalid; require owner-only regular file"
                    ) from None
            else:
                kind = "cache"
                with warnings.catch_warnings():
                    warnings.simplefilter("error", getpass.GetPassWarning)
                    try:
                        value = getpass.getpass("API key (hidden): ").strip()
                    except (getpass.GetPassWarning, EOFError):
                        raise AuthError(
                            "Hidden input requires an interactive terminal; use --key-file"
                        ) from None
                if not value or any(c.isspace() or ord(c) < 32 for c in value):
                    raise AuthError("Key must be one nonempty value without whitespace")
                source = str(self.directory / ("key-" + session_id))
        record = {
            "id": session_id,
            "state": str(self.state),
            "endpoint": model["endpoint"],
            "created_at": time.time(),
            "expires_at": time.time() + ttl,
            "kind": kind,
            "source": source,
            "fingerprint": hashlib.sha256(value.encode()).hexdigest() if value else None,
        }
        if kind == "cache":
            fd = os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(value + "\n")
        secure_write(self.directory / ("session-" + session_id + ".json"), record)
        self.discard_unused_except(session_id)
        secure_write(self.directory / "current.json", {"id": session_id})
        select_team(self.state)
        return self.status(model["endpoint"])

    def status(self, endpoint=None):
        history = {
            "historical_audit_retained": None,
            "detail": "Execution authorization expires/revokes separately; used audit sources retained",
        }
        try:
            self.check_directory()
            file = self.directory / "bindings.json"
            history["audit_sessions"] = len(set(secure_read(file).values())) if file.exists() else 0
            history["historical_audit_retained"] = history["audit_sessions"] > 0
            _, unavailable = self.audit_keys()
            history.update(audit_incomplete=unavailable > 0, unavailable_sources=unavailable)
        except AuthError:
            history.update(audit_incomplete=True)
        try:
            record = self.record()
            available = True
            try:
                self.value(record)
            except AuthError:
                available = False
            expired = time.time() >= record["expires_at"]
            matches = endpoint is None or record["endpoint"] == endpoint
            return {
                **history,
                "state": str(self.state),
                "logged_in": True,
                "valid": available and not expired and matches,
                "expired": expired,
                "key_available": available,
                "endpoint_matches": matches,
                "endpoint": record["endpoint"],
                "expires_at": record["expires_at"],
                "source": record["kind"],
                "authentication_verified": False,
            }
        except AuthError as error:
            return {
                **history,
                "state": str(self.state),
                "logged_in": False,
                "valid": False,
                "authentication_verified": False,
                "detail": str(error),
            }


@contextmanager
def runtime_context(state, legacy_key=None):
    """Expired sessions remain available for observation and cleanup, never execution."""
    from harbor_helper.security import credentials

    auth = Auth(state)
    old_value = os.environ.get(KEY_ENV)
    old_audit = credentials.AUDIT_SECRETS
    old_legacy = credentials.LEGACY_SECRETS
    old_legacy_env = os.environ.get(credentials.LEGACY_KEY_ENV)
    legacy_key = legacy_key or old_legacy_env
    credentials.LEGACY_SECRETS = [legacy_key] if legacy_key else []
    if legacy_key:
        os.environ[credentials.LEGACY_KEY_ENV] = legacy_key
    try:
        keys, _ = auth.audit_keys()
    except AuthError:
        keys = []
    try:
        record = auth.record()
        value = auth.value(record)
    except AuthError:
        value = None
    if value:
        os.environ[KEY_ENV] = value
    credentials.AUDIT_SECRETS = list(
        dict.fromkeys([*old_audit, *keys, *credentials.LEGACY_SECRETS])
    )
    try:
        yield
    finally:
        credentials.AUDIT_SECRETS = old_audit
        credentials.LEGACY_SECRETS = old_legacy
        if old_legacy_env is None:
            os.environ.pop(credentials.LEGACY_KEY_ENV, None)
        else:
            os.environ[credentials.LEGACY_KEY_ENV] = old_legacy_env
        if old_value is None:
            os.environ.pop(KEY_ENV, None)
        else:
            os.environ[KEY_ENV] = old_value
