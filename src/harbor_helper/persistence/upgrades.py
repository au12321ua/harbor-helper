"""Protected, state-external upgrade protocol. No database or subprocess imports."""

import fcntl
import hashlib
import json
import os
import re
import stat
import uuid
from pathlib import Path

PROTOCOL = 1
TERMINAL = {"succeeded", "failed", "cancelled"}
PUBLIC_PHASES = {
    "queued",
    "checking",
    "preparing",
    "waiting",
    "backup",
    "adapting",
    "migrating",
    "switching",
    "verifying",
    "restoring",
    "commit_decided",
    "releasing",
    "succeeded",
    "failed",
    "cancelled",
    "needs_manual",
}


def private_json(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)) as file:
        info = os.fstat(file.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
            or info.st_size > 1048576
        ):
            raise ValueError("Upgrade metadata must be an owned private regular file")
        return json.load(file)


def durable(path, value):
    path = Path(path)
    temporary = path.with_name("." + path.name + "-" + uuid.uuid4().hex)
    try:
        with os.fdopen(
            os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as file:
            json.dump(value, file, sort_keys=True)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def journal(root):
    path = Path(root).parent / "updates/journal.json"
    return private_json(path) if path.exists() else None


def busy(root):
    value = journal(root)
    return value if value and value.get("phase") not in TERMINAL else None


def blocked(root):
    """Fail closed, including missing state between the two recovery renames."""
    root = Path(root)
    try:
        value = journal(root)
        if value and (value.get("protocol") != PROTOCOL or value.get("barrier")):
            return True
        if (root / ".upgrade.json").exists():
            return True
    except (OSError, ValueError, TypeError, KeyError):
        return True
    return False


def require_writable(root):
    if authorized(root) is None and blocked(root):
        raise ValueError("upgrade_in_progress: state is protected by an upgrade barrier")


def ownership(root):
    from harbor_helper.service.primitives import ServiceError

    value = busy(root)
    if value:
        raise ServiceError("upgrade_in_progress", "Upgrade owns maintenance: " + value["id"], 409)


def projection(root):
    try:
        value = journal(root)
        phase = value.get("phase") if value else None
        return {
            "upgrading": bool(value and phase not in TERMINAL),
            "phase": phase if phase in PUBLIC_PHASES else "needs_manual" if value else None,
        }
    except (OSError, ValueError, TypeError):
        return {"upgrading": True, "phase": "needs_manual"}


def enqueue(root, action, actor, request_id, payload):
    base = Path(root).parent
    config = base / "updates/enabled.json"
    if not config.exists():
        raise ValueError("Updates are not enabled for this installation")
    enabled = private_json(config)
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", request_id):
        raise ValueError("A stable bounded request_id is required")
    allowed = {
        "check": set(),
        "upgrade": {"check_id", "target_sha", "config_digest"},
        "cancel": {"job"},
        "cancel-all": {"job"},
    }
    if action not in allowed or set(payload) != allowed[action]:
        raise ValueError("Invalid upgrade action fields")
    if any(
        not isinstance(v, str) or len(v) > 80 or not re.fullmatch(r"[A-Za-z0-9_-]+", v)
        for v in payload.values()
    ):
        raise ValueError("Invalid upgrade reference")
    spool = base / "updates/spool"
    value = {
        "protocol": PROTOCOL,
        "instance": enabled["owner"],
        "action": action,
        "actor": actor,
        "request_id": request_id,
        "payload": payload,
    }
    identifier = hashlib.sha256((actor + "/" + request_id).encode()).hexdigest()
    path = spool / (identifier + ".json")
    with (base / "updates/request.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = base / "updates/results" / (identifier + ".json")
        previous = (
            private_json(path)
            if path.exists()
            else private_json(result).get("request")
            if result.exists()
            else None
        )
        if previous is not None and previous != value:
            raise ValueError("request_id already belongs to a different request")
        if previous is None:
            if len(list(spool.iterdir())) >= 64:
                raise ValueError("Upgrade request spool full")
            durable(path, value)
    return {"request_id": identifier}


# Only a holder of the manager's inherited exclusive writer lease can migrate live state.
# This capability is process-local and is never reachable from an HTTP request.
from contextlib import contextmanager
from contextvars import ContextVar

_authorization: ContextVar[tuple[Path, int] | None] = ContextVar("upgrade_writer", default=None)


@contextmanager
def migration_lease(root, fd):
    root = Path(root).resolve()
    actual = os.fstat(fd)
    expected = (root / "writer.lock").stat()
    if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
        raise ValueError("Migration lease identity mismatch")
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    value = _authorization.set((root, fd))
    try:
        yield
    finally:
        _authorization.reset(value)


def authorized(root):
    value = _authorization.get()
    return value[1] if value and value[0] == Path(root).resolve() else None
