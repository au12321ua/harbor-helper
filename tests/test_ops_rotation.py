"""Read-only snapshot/KCV/restore checks against generated private instances."""

import json
import os
import signal
import subprocess
import sys

import pytest
from test_ops import backup_args, module, ops, restore_args

from harbor_helper.service.data import ServiceData


@pytest.mark.parametrize("kind", ["online", "offline"])
def test_rotated_empty_snapshot_restores_without_source_key_directory(tmp_path, kind, monkeypatch):
    base = tmp_path / "instance"
    data = ServiceData.initialize(
        base / "state", base / "private/initial.key", "admin", "Fake-backup-password"
    )
    data.master_keys.rotate(data.users()[0], 1)
    if kind == "offline":
        data.store.close()
    result = ops.backup(backup_args(base, tmp_path / "backups", kind))
    with ops.ro_db(data.root) as db:
        ref = ops.active_reference(db)
    # Restore must read only the snapshot and supplied paired key, not the source.
    (base / "private").rename(base / "private-hidden")
    target = tmp_path / "new-target"
    restored = ops.restore(restore_args(result, target))
    assert restored["credentials_checked"] == 0
    assert (target / "private" / ref["basename"]).is_file()
    assert json.loads((target / "state/service.json").read_text())["master_directory"] == str(
        target / "private"
    )
    with ops.ro_db(target / "state") as db:
        assert ops.active_reference(db) == ref
    platform = module("local_platform")
    platform.check_master(target)
    # Even without credentials a wrong 32-byte file is rejected by KCV.
    (target / "private" / ref["basename"]).write_bytes(b"x" * 32)
    with pytest.raises(ValueError, match="KCV"):
        ops.current_master(target / "state")
    with pytest.raises(RuntimeError, match="KCV"):
        platform.check_master(target)


@pytest.mark.parametrize("damage", ["missing", "basename", "kcv"])
def test_ops_refuses_damaged_active_without_product_migration(tmp_path, damage):
    data = ServiceData.initialize(
        tmp_path / "state", tmp_path / "private/master", "admin", "Fake-backup-password"
    )
    raw = data.master_keys.current()
    with data.store.connect() as db:
        if damage == "missing":
            db.execute("DELETE FROM master_active")
        elif damage == "basename":
            db.execute("UPDATE master_active SET basename='../master'")
        else:
            db.execute("UPDATE master_active SET kcv=?", ("0" * 64,))
    before = (data.root / "queue.sqlite").read_bytes()
    with pytest.raises(ValueError):
        ops.validate_db(data.root, raw)
    assert (data.root / "queue.sqlite").read_bytes() == before


def test_read_only_hot_journal_fails_closed_then_product_recovers(tmp_path):
    data = ServiceData.initialize(
        tmp_path / "state", tmp_path / "private/master", "admin", "Fake-backup-password"
    )
    with data.store.connect() as db:
        db.execute("CREATE TABLE spill (id INTEGER PRIMARY KEY, body BLOB)")
        db.executemany("INSERT INTO spill(body) VALUES(?)", [(b"a" * 4000,)] * 256)
    master = data.master_keys.current()
    ready = tmp_path / "ready"
    code = """
import sqlite3,sys,signal
from pathlib import Path
db=sqlite3.connect(sys.argv[1]);db.execute('PRAGMA cache_size=1');db.execute('BEGIN IMMEDIATE')
db.execute("UPDATE spill SET body=zeroblob(4000)")
Path(sys.argv[2]).touch();signal.pause()
"""
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(data.root / "queue.sqlite"), str(ready)]
    )
    try:
        import time

        deadline = time.monotonic() + 10
        while not ready.exists():
            assert time.monotonic() < deadline
            time.sleep(0.01)
        os.kill(child.pid, signal.SIGKILL)
        child.wait(timeout=5)
        before = (data.root / "queue.sqlite").read_bytes()
        with pytest.raises(ValueError, match="hot journal"):
            ops.validate_db(data.root, master)
        assert (data.root / "queue.sqlite").read_bytes() == before
        with data.store.connect() as db:
            assert db.execute("SELECT body FROM spill LIMIT 1").fetchone()[0] == b"a" * 4000
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
