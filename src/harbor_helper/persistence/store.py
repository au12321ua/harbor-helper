import fcntl
import sqlite3
from contextlib import contextmanager
from pathlib import Path

TERMINAL = {"succeeded", "failed", "cancelled"}
ACTIVE = {"starting", "running", "cancelling", "cleanup_blocked"}


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
                ("audit_status", "TEXT NOT NULL DEFAULT 'pending'"),
                ("audit_reason", "TEXT"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE runs ADD COLUMN {name} {definition}")

    @contextmanager
    def control(self):
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

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown run: {run_id}")
        return dict(row)

    def update(self, run_id, **fields):
        from harbor_helper.security.credentials import redact_value, runtime_secrets

        for name in ("reason", "audit_reason"):
            if name in fields:
                fields[name] = redact_value(fields[name], runtime_secrets())
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?",
                (*fields.values(), run_id),
            )

    def path(self, run_id):
        self.get(run_id)
        return self.root / "runs" / run_id
