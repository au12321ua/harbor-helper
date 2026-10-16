import fcntl
import os
import re
import sqlite3
import stat
import threading
from contextlib import contextmanager
from pathlib import Path

from harbor_helper.persistence import statuses as lifecycle_status
from harbor_helper.persistence.statuses import ACTIVE, TERMINAL  # noqa: F401

_held_evidence = threading.local()


class Store:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.root / "runs").mkdir(exist_ok=True)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, created REAL NOT NULL,
                started REAL, finished REAL, pid INTEGER, birth TEXT,
                concurrency INTEGER NOT NULL, cancel INTEGER DEFAULT 0,
                reason TEXT, parent TEXT)""")
            # Migrate existing queues in place; execution and evidence safety are
            # independent facts. An audit failure must not reserve execution slots.
            columns = {row[1] for row in db.execute("PRAGMA table_info(runs)")}
            for name, definition in (
                ("audit_status", f"TEXT NOT NULL DEFAULT {lifecycle_status.PENDING!r}"),
                ("audit_reason", "TEXT"),
                ("finish_status", "TEXT"),
                ("finish_reason", "TEXT"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE runs ADD COLUMN {name} {definition}")
            db.execute("CREATE INDEX IF NOT EXISTS runs_work ON runs(status,audit_status,created)")

    @contextmanager
    def control(self, *, notify=True):
        try:
            with self.quiet_control():
                yield
        finally:
            if notify:
                from harbor_helper.persistence.wakeup import notify as wake

                wake(self.root)

    @contextmanager
    def quiet_control(self):
        with (self.root / "control.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "queue.sqlite", timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def runs(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM runs ORDER BY created")]

    def work(self):
        """Only actionable records; completed clean history is never a normal-loop input."""
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM runs WHERE status IN ('queued','starting','running','cancelling','cleanup_blocked') "
                    "UNION ALL SELECT * FROM runs WHERE status IN ('succeeded','failed','cancelled') "
                    "AND audit_status IN ('pending','incomplete') ORDER BY created"
                )
            ]

    @contextmanager
    def evidence(self, run_id, *, blocking=True):
        # Resolve an existing run before creating even the lock directory.
        self.path(run_id)
        # Kept outside run directories, including across archive/delete operations.
        key = (str(self.root), run_id)
        held = getattr(_held_evidence, "keys", set())
        if key in held:
            yield
            return
        folder = self.root / "evidence-locks"
        folder.mkdir(exist_ok=True, mode=0o700)
        # Pin a real directory; never follow a substituted directory or lock
        # symlink. State is trusted, but these checks also fail closed on damage.
        directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(
                run_id + ".lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
                dir_fd=directory,
            )
        finally:
            os.close(directory)
        with os.fdopen(fd, "rb", buffering=0) as lock:
            meta = os.fstat(lock.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_uid != os.getuid():
                raise ValueError("Evidence lock requires an owned regular file")
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            _held_evidence.keys = held | {key}
            try:
                yield
            finally:
                _held_evidence.keys = held

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown run: {run_id}")
        return dict(row)

    def update(self, run_id, **fields):
        from harbor_helper.security.credentials import redact_value, runtime_secrets

        for name in ("reason", "audit_reason", "finish_reason"):
            if name in fields:
                fields[name] = redact_value(fields[name], runtime_secrets())
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?",
                (*fields.values(), run_id),
            )

    def path(self, run_id):
        # Match the identity grammar used when runs are created. Check before
        # lookup or filesystem operations, including evidence-lock acquisition.
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
            raise ValueError("Invalid run identifier")
        self.get(run_id)
        path = self.root / "runs" / run_id
        if path.resolve() != path:
            raise ValueError("Invalid run path")
        return path
