"""Explicit file credentials, safe output, and a pinned Harbor Docker boundary."""

import base64
import functools
import json
import os
import sqlite3
import stat
import tempfile
from pathlib import Path
from urllib.parse import quote

KEY_ENV = "VLLM_API_KEY"
AUDIT_SECRETS = []
LEGACY_SECRETS = None
LEGACY_KEY_ENV = "HARBOR_HELPER_LEGACY_AUDIT_KEY"


def legacy_secrets():
    if LEGACY_SECRETS is None:
        value = os.environ.get(LEGACY_KEY_ENV) or os.environ.get(KEY_ENV)
        return [value] if value else []
    return list(LEGACY_SECRETS)


def runtime_secrets():
    return list(
        dict.fromkeys([*AUDIT_SECRETS, *([os.environ[KEY_ENV]] if os.environ.get(KEY_ENV) else [])])
    )


def redact_value(value, secrets):
    if not isinstance(value, str):
        return value
    for pattern in secret_patterns(secrets):
        value = value.replace(pattern.decode(), "[REDACTED]")
    return value


def read_key_file(path):
    # O_NONBLOCK also prevents a supplied FIFO from blocking before fstat.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        metadata = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise ValueError("Credential file must be owner-only and owned by this account")
        raw = source.read(16385)
    if len(raw) > 16384:
        raise ValueError("Invalid credential file")
    try:
        value = raw.decode("utf-8").strip()
    except UnicodeError:
        raise ValueError("Invalid credential file") from None
    if not value or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("Credential file must contain one nonempty value")
    return value


class RedactedStream:
    """Retain possible secret prefixes across writes and flush boundaries."""

    def __init__(self, stream, secrets):
        self.stream = stream
        self.secrets = [s for s in secrets if s]
        self.pending = ""

    def write(self, value):
        text = self.pending + value
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        keep = 0
        for secret in self.secrets:
            for n in range(1, min(len(secret), len(text) + 1)):
                if text.endswith(secret[:n]):
                    keep = max(keep, n)
        self.pending = text[-keep:] if keep else ""
        self.stream.write(text[:-keep] if keep else text)
        return len(value)

    def flush(self):
        # Flushing a partial secret would allow the next write to complete it.
        self.stream.flush()

    def finish(self):
        if self.pending:
            self.stream.write("[REDACTED]")
            self.pending = ""
        self.stream.flush()

    def __getattr__(self, key):
        return getattr(self.stream, key)


def secret_patterns(secrets):
    patterns = set()
    for secret in secrets:
        if not secret:
            continue
        raw = secret.encode()
        patterns.update(
            (
                raw,
                base64.b64encode(raw),
                quote(secret, safe="").encode(),
                json.dumps(secret)[1:-1].encode(),
            )
        )
    return sorted(patterns, key=len, reverse=True)


def scan_tree(root, secrets):
    """Scan every regular file, including binary/large files; never print matches."""
    patterns = secret_patterns(secrets)
    counts = {"files_scanned": 0, "matched_files": 0, "unreadable_files": 0}
    overlap = max(map(len, patterns), default=1) - 1
    root = Path(root)
    if not root.exists() or root.is_symlink():
        return {**counts, "unreadable_files": 1, "clean": False}

    def walk(directory):
        try:
            with os.scandir(directory) as entries:
                children = list(entries)
        except OSError:
            counts["unreadable_files"] += 1
            return
        for entry in children:
            path = Path(entry.path)
            try:
                if entry.is_dir(follow_symlinks=False):
                    yield from walk(path)
                else:
                    yield path
            except OSError:
                counts["unreadable_files"] += 1

    files = walk(root) if root.is_dir() else [root]
    for path in files:
        if path.is_symlink():
            counts["unreadable_files"] += 1
            continue
        if not path.is_file():
            continue
        if path.name.endswith(("-wal", "-shm", "-journal")):
            # Read the parent database through SQLite for a consistent view.
            # Unpaired sidecars are withheld rather than treated as clean.
            parent_db = Path(str(path).rsplit("-", 1)[0])
            if not parent_db.is_file():
                counts["unreadable_files"] += 1
            continue
        relative = path.relative_to(root).as_posix() if root.is_dir() else path.name
        found, tail = any(pattern in relative.encode() for pattern in patterns), b""
        try:
            with path.open("rb") as source:
                if source.read(16) == b"SQLite format 3\0":
                    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as db:
                        tables = db.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        ).fetchall()
                        for (table,) in tables:
                            quoted = table.replace('"', '""')
                            for row in db.execute(f'SELECT * FROM "{quoted}"'):
                                found |= any(
                                    p in str(value).encode() for value in row for p in patterns
                                )
                    counts["files_scanned"] += 1
                    counts["matched_files"] += int(found)
                    continue
                source.seek(0)
                while chunk := source.read(65536):
                    data = tail + chunk
                    found |= any(p in data for p in patterns)
                    tail = data[-overlap:] if overlap else b""
            counts["files_scanned"] += 1
            counts["matched_files"] += int(found)
        except (OSError, sqlite3.Error):
            counts["unreadable_files"] += 1
    return {**counts, "clean": not (counts["matched_files"] or counts["unreadable_files"])}


def scrub_file(path, secrets):
    """Streaming exact-value scrub; supports binary files and chunk boundaries."""
    patterns = secret_patterns(secrets)
    if not patterns or not path.is_file() or path.is_symlink():
        return
    if path.name.endswith(("-wal", "-shm", "-journal")):
        return
    with path.open("rb") as source:
        if source.read(16) == b"SQLite format 3\0":
            return  # Never mutate database bytes; scan fields and withhold on matches.
    if scan_tree(path, secrets)["clean"]:
        # Container-owned log directories may be readable but not writable.
        # Clean files need no replacement or temporary output in that directory.
        return
    overlap = max(map(len, patterns)) - 1
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".redact-")
    changed = False
    try:
        with path.open("rb") as source, os.fdopen(fd, "wb") as target:
            pending = b""
            while chunk := source.read(65536):
                pending += chunk
                # Only consume bytes whose possible match is fully available.
                stop, i = max(0, len(pending) - overlap), 0
                while i < stop:
                    hits = [(pending.find(p, i), p) for p in patterns]
                    hits = [(at, p) for at, p in hits if 0 <= at < stop]
                    if not hits:
                        target.write(pending[i:stop])
                        i = stop
                        break
                    at, matched = min(hits, key=lambda hit: hit[0])
                    target.write(pending[i:at] + b"[REDACTED]")
                    i = at + len(matched)
                    changed = True
                pending = pending[i:]
            for pattern in patterns:
                changed |= pattern in pending
                pending = pending.replace(pattern, b"[REDACTED]")
            target.write(pending)
        if changed:
            os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def scrub_run(path, secrets):
    # Never rewrite immutable inputs. Scan them separately before evidence handoff.
    for file in Path(path).rglob("*"):
        if file.relative_to(path).parts[0] not in {"tasks", "bundle", "manifest.json", "job.json"}:
            scrub_file(file, secrets)


def audit_run(store, run_id, secrets):
    """After writers stop: run files, shared scheduler log, and database fields."""
    result = scan_tree(store.path(run_id), secrets)
    scheduler_log = store.root / "supervisor.log"
    if scheduler_log.exists():
        other = scan_tree(scheduler_log, secrets)
        for key in ("files_scanned", "matched_files", "unreadable_files"):
            result[key] += other[key]
    fields = json.dumps(store.runs()).encode()
    result["database_fields_clean"] = not any(p in fields for p in secret_patterns(secrets))
    result["clean"] = (
        not (result["matched_files"] or result["unreadable_files"])
        and result["database_fields_clean"]
    )
    return result


def install_docker_credential_forwarding():
    """Adapt only helper workers; Harbor 0.23.0 constructs secret exec assignments."""
    from harbor.environments.docker.docker import DockerEnvironment

    original = DockerEnvironment._run_docker_compose_command
    if getattr(original, "_helper_credentials", False):
        return

    @functools.wraps(original)
    async def forward(self, command, **kwargs):
        secret = os.environ.get(KEY_ENV)
        command = list(command)
        if secret:
            assignment = f"{KEY_ENV}={secret}"
            for i, arg in enumerate(command):
                if i and command[i - 1] == "-e" and arg == assignment:
                    if self._compose_env_vars(include_os_env=True).get(KEY_ENV) != secret:
                        raise RuntimeError("Credential forwarding environment mismatch")
                    command[i] = KEY_ENV
            if any(secret in arg for arg in command):
                raise RuntimeError("Refusing credential value in Docker argv")
        return await original(self, command, **kwargs)

    forward._helper_credentials = True
    DockerEnvironment._run_docker_compose_command = forward
