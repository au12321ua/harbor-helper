"""Offline proofs use real processes and immutable snapshot comparisons."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from ops_support import backup_args, ops

from harbor_helper.persistence.store import Store
from harbor_helper.service.data import ServiceData


@pytest.fixture
def offline(tmp_path):
    base = tmp_path / "instance"
    data = ServiceData.initialize(
        base / "state", base / "private/master", "admin", "Synthetic-backup-password"
    )
    data.store.close()
    return base, backup_args(base, tmp_path / "backups", "offline")


def spawn(code, *args, cwd=None):
    child = subprocess.Popen(
        [sys.executable, "-c", code, *map(str, args)],
        cwd=cwd,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert child.stdout and child.stdout.readline().strip() == "ready"
    return child


def stop(child):
    child.terminate()
    child.wait(timeout=5)


@pytest.mark.parametrize("kind", ["fd", "cwd", "argv", "store"])
def test_unregistered_product_and_readable_writers_refused(offline, kind):
    base, args = offline
    state = base / "state"
    prefix = "import sys,time; "
    code = {
        "fd": "f=open(sys.argv[1]+'/queue.sqlite'); ",
        "cwd": "",
        "argv": "",
        "store": "from harbor_helper.persistence.store import Store; s=Store(sys.argv[1]); ",
    }[kind]
    child = spawn(
        prefix + code + "print('ready',flush=True); time.sleep(60)",
        *([] if kind == "cwd" else [state]),
        cwd=state if kind == "cwd" else None,
    )
    try:
        with pytest.raises(ValueError, match="writers"):
            ops.backup(args)
    finally:
        stop(child)


def test_exclusive_blocks_store_before_database_write(offline):
    base, _ = offline
    state = base / "state"
    before = (state / "queue.sqlite").read_bytes()
    with ops.writer_lease(state), pytest.raises(BlockingIOError):
        Store(state)
    assert (state / "queue.sqlite").read_bytes() == before
    a, b = Store(state), Store(state)
    a.close()
    with pytest.raises(ValueError, match="writers"), ops.writer_lease(state):
        pass
    b.close()
    with ops.writer_lease(state):
        pass


def protected():
    return spawn(
        "import ctypes,time; "
        "assert ctypes.CDLL(None).prctl(4,0,0,0,0)==0; "
        "print('ready',flush=True);time.sleep(60)"
    )


def test_preexisting_protected_process_is_recorded(offline):
    _base, args = offline
    child = protected()
    try:
        # Host process churn legitimately defers a snapshot; retry the whole
        # production operation without bypassing any observation or content gate.
        import time

        for attempt in range(20):
            try:
                result = ops.backup(args)
                break
            except ValueError as error:
                if str(error) != "deferred: uninspectable process set changed" or attempt == 19:
                    raise
                time.sleep(0.05)
        manifest = json.loads((Path(result["snapshot"]) / "manifest.json").read_text())
        assert manifest["claim"] == "product_writers_stopped_and_content_stable"
        assert manifest["host_observation"]["other_uids"] == "not_observed"
        record = next(
            r for r in manifest["host_observation"]["uninspectable"] if r["pid"] == child.pid
        )
        assert record["birth"] and record["status"]["Uid"] and record["cgroup"]
    finally:
        stop(child)


@pytest.mark.parametrize("mutation", ["protected", "crossfile", "database", "journal"])
def test_mutation_in_copy_window_refused(offline, monkeypatch, mutation):
    base, args = offline
    state = base / "state"
    (state / "a-extra").write_text("before")
    original = ops.copy_stable
    children = []
    changed = False

    def copy(source, destination):
        nonlocal changed
        original(source, destination)
        # Configuration copy follows DB copy, so changing either is a cross-file race.
        if source.name == "team.json" and not changed:
            changed = True
            if mutation == "protected":
                children.append(protected())
            elif mutation == "crossfile":
                (state / "queue.sqlite").touch()
                (state / "team.json").write_text('{"changed":true}')
            elif mutation == "database":
                import sqlite3

                with sqlite3.connect(state / "queue.sqlite") as db:
                    db.execute("CREATE TABLE unexpected(value)")
            else:
                (state / "queue.sqlite-journal").write_bytes(b"journal")

    monkeypatch.setattr(ops, "copy_stable", copy)
    try:
        with pytest.raises(ValueError, match="changed|journal"):
            ops.backup(args)
        assert not list(args.output.glob("snapshot-*/manifest.json"))
    finally:
        for child in children:
            stop(child)


def test_unknown_identity_refused_and_reused_pid_rechecked(offline):
    base, args = offline
    ops.write_json(base / "http.json", {"code": "a" * 40, "pid": "invalid"})
    with pytest.raises(ValueError, match="writers"):
        ops.backup(args)
    child = spawn("import time;print('ready',flush=True);time.sleep(60)", base / "state")
    try:
        ops.write_json(
            base / "http.json", {"code": "a" * 40, "pid": child.pid, "birth": "old-birth"}
        )
        with pytest.raises(ValueError, match="writers"):
            ops.backup(args)
    finally:
        stop(child)


def test_source_subprocess_has_independent_lease_before_target_io(offline):
    base, _ = offline
    state = base / "state"
    target = state / "preparing/input"
    request = json.dumps(
        {"target": str(target), "reference": "synthetic-never-requested", "task": None}
    )
    with ops.writer_lease(state):
        child = subprocess.run(
            [sys.executable, "-m", "harbor_helper.service.sources"],
            check=False,
            input=request,
            capture_output=True,
            text=True,
            timeout=10,
        )
    assert child.returncode != 0 and "BlockingIOError" in child.stderr
    assert not target.exists()


def test_store_lease_not_inherited_by_exec(offline):
    base, _ = offline
    state = base / "state"
    store = Store(state)
    child = spawn("import time;print('ready',flush=True);time.sleep(60)")
    try:
        store.close()
        with ops.writer_lease(state):
            assert child.poll() is None
    finally:
        stop(child)


def test_store_finalization_during_acquire_does_not_deadlock(offline):
    base, _ = offline
    code = """
import gc,sys
from pathlib import Path
from harbor_helper.persistence.store import Store
from harbor_helper.persistence import writers
gc.disable()
a=Store(Path(sys.argv[1]));a.cycle=a;del a
original=writers.os.open
def collect(*args,**kwargs):
    gc.collect()
    return original(*args,**kwargs)
writers.os.open=collect
b=Store(Path(sys.argv[2]));b.close()
"""
    subprocess.run(
        [sys.executable, "-c", code, str(base / "state"), str(base / "second-state")],
        check=True,
        timeout=10,
        capture_output=True,
    )
