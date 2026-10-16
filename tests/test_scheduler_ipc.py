"""Real Linux FIFO safety and notification loss/coalescing."""

import fcntl
import os
import stat
import time

import pytest

from harbor_helper.persistence.store import Store
from harbor_helper.persistence.wakeup import Mailbox, notify


def test_fifo_idle_full_duplicate_and_no_reader(tmp_path):
    notify(tmp_path)  # absent endpoint
    mailbox = Mailbox(tmp_path)
    try:
        meta = (tmp_path / "scheduler.wake").lstat()
        assert stat.S_ISFIFO(meta.st_mode) and stat.S_IMODE(meta.st_mode) == 0o600
        capacity = fcntl.fcntl(mailbox.writer, fcntl.F_GETPIPE_SZ)
        os.write(mailbox.writer, b"w" * capacity)
        started = time.monotonic()
        for _ in range(100):
            notify(tmp_path)  # full means a notification is already pending
        assert time.monotonic() - started < 1
        mailbox.drain()
        notify(tmp_path)
        assert os.read(mailbox.reader, 1) == b"w"
    finally:
        mailbox.close()
    started = time.monotonic()
    notify(tmp_path)  # ENXIO must not wait for a reader
    assert time.monotonic() - started < 0.5


@pytest.mark.parametrize("kind", ["file", "link", "permissions"])
def test_endpoint_refuses_wrong_type_or_permissions(tmp_path, kind):
    path = tmp_path / "scheduler.wake"
    if kind == "file":
        path.write_bytes(b"protected")
    elif kind == "link":
        (tmp_path / "target").write_bytes(b"protected")
        path.symlink_to(tmp_path / "target")
    else:
        os.mkfifo(path, 0o644)
    notify(tmp_path)
    with pytest.raises(ValueError, match="FIFO"):
        Mailbox(tmp_path)
    if kind != "permissions":
        assert path.read_bytes() == b"protected"


def test_control_notifies_after_release_even_on_exception(tmp_path, monkeypatch):
    store = Store(tmp_path)
    observed = []

    def check(root):
        with (root / "control.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            observed.append(True)

    monkeypatch.setattr("harbor_helper.persistence.wakeup.notify", check)
    with store.control():
        assert not observed
    with pytest.raises(ValueError), store.control():
        raise ValueError("fixture")
    with store.quiet_control():
        pass
    assert observed == [True, True]


def test_writer_exit_and_replacement_races_are_best_effort(tmp_path, monkeypatch):
    mailbox = Mailbox(tmp_path)
    try:

        def broken(*args):
            raise BrokenPipeError("reader exited")

        monkeypatch.setattr(os, "write", broken)
        notify(tmp_path)
    finally:
        mailbox.close()


def test_normal_queries_exclude_clean_history(tmp_path):
    store = Store(tmp_path)
    with store.connect() as db:
        db.executemany(
            "INSERT INTO runs(id,status,created,concurrency,audit_status) VALUES(?,?,?,?,?)",
            [(str(i), "succeeded", i, 1, "clean") for i in range(1000)]
            + [("work", "queued", 1001, 1, "pending")],
        )
    assert [r["id"] for r in store.work()] == ["work"]


def test_fifo_owner_mismatch_is_refused(tmp_path, monkeypatch):
    os.mkfifo(tmp_path / "scheduler.wake", 0o600)
    uid = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: uid + 1)
    notify(tmp_path)
    with pytest.raises(ValueError, match="FIFO"):
        Mailbox(tmp_path)
