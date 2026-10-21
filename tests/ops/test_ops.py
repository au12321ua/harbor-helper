import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from ops_support import (
    REPO,
    SHA,
    backup_args,
    close_stores,
    ops,
    reopen_store,
    restore_args,
    verify,
)
from process_support import Processes, wait


def test_online_snapshot_live_writers_restore_and_ownership(http_service, tmp_path):
    p, _url, base = http_service
    # A completed zero-score fixture plus a worker deliberately held in execution.
    done = p.run_id(p.submit(idem="ops-terminal"))
    p.terminal(done)
    wait(lambda: p.data.store.get(done)["audit_status"] == "clean")
    (p.data.root / "worker-hold").touch()
    active = p.run_id(p.submit(idem="ops-active"))
    wait(lambda: p.data.store.get(active)["status"] == "running")
    # Preparing input has a real waiting preparation thread.
    (p.data.root / "prepare-hold").touch()
    preparing = p.submit(idem="ops-preparing")
    try:
        before = ops.inspect(base)
        assert before["scheduler"]["state"] == "running"
        result = ops.backup(backup_args(base, tmp_path.parent / (tmp_path.name + "-backups")))
        assert result["kind"] == "online" and result["full_state"] is False
        assert (
            active in result["active_runs"] and preparing["id"] in result["preparing_submissions"]
        )
        snapshot = Path(result["snapshot"])
        manifest = ops.read_json(snapshot / "manifest.json")
        assert done in manifest["included_runs"]
        assert not (snapshot / "state/runs" / active).exists()
        target = tmp_path / "recovered"
        restored = ops.restore(restore_args(result, target))
        assert restored["offline_validation"] == "passed"
        assert restored["credentials_checked"] == 3
        assert restored["active_runs"] == result["active_runs"]
        assert restored["automatically_startable"] is False
        assert not (target / "state/scheduler.json").exists()
        config = ops.read_json(target / "state/service.json")
        assert config["master_directory"] == str(target / "private")
        assert ops.current_master(target / "state") == p.data.master_keys.current()
        assert ops.inspect(base)["scheduler"]["state"] == "running"
        with pytest.raises(ValueError, match="writers"):
            ops.backup(
                backup_args(base, tmp_path.parent / (tmp_path.name + "-offline-busy"), "offline")
            )
    finally:
        (p.data.root / "worker-hold").unlink(missing_ok=True)
        (p.data.root / "prepare-hold").unlink(missing_ok=True)
        # Drain fixture work and observe actual worker exit before the shared
        # HTTP fixture tears down; killing then immediately sampling is racy.
        p.terminal(active)
        p.terminal(p.run_id(preparing))
        wait(
            lambda: all(
                not row["pid"] or ops.birth(row["pid"]) != row["birth"]
                for row in p.data.store.runs()
            )
        )


def test_readonly_check_health_ready_and_unknown(http_service):
    p, url, base = http_service
    # Process record follows local_platform layout/identity; source service is untouched.
    port = int(url.rsplit(":", 1)[1])
    import urllib.request

    with urllib.request.urlopen(url + "/api/v1/health") as response:
        assert json.load(response)["alive"] is True
    # Locate the fixture's actual HTTP PID by exact argv state reference.
    candidates = []
    for proc in Path("/proc").iterdir():
        if proc.name.isdigit():
            try:
                argv = (proc / "cmdline").read_bytes().decode().rstrip("\0").split("\0")
                if "uvicorn.run(create_app(" in " ".join(argv) and str(p.data.root) in " ".join(
                    argv
                ):
                    candidates.append((int(proc.name), argv))
            except OSError:
                pass
    assert len(candidates) == 1
    pid, argv = candidates[0]
    ops.write_json(
        base / "http.json",
        {"pid": pid, "birth": ops.birth(pid), "argv": argv, "code": str(p.cwd), "port": port},
    )
    originals = {
        name: ops.digest(p.data.root / name)
        for name in ("queue.sqlite", "service.json", "team.json")
    }
    check = ops.inspect(base)
    assert check["api"] == {"alive": True, "ready": True}
    from harbor_helper.service.admission import set_maintenance

    set_maintenance(p.data, {"paused": True, "reason": "ops fixture"})
    assert ops.inspect(base)["api"] == {"alive": True, "ready": False}
    record = ops.read_json(base / "http.json")
    record["birth"] = "wrong"
    ops.write_json(base / "http.json", record)
    assert ops.inspect(base)["api"] == {"alive": "unknown", "ready": "unknown"}
    assert originals == {name: ops.digest(p.data.root / name) for name in originals}


def test_offline_full_nonempty_and_rejection_paths(tmp_path):
    base = tmp_path / "instance"
    base.mkdir()
    p = Processes(base)
    try:
        p.start()
        run = p.run_id(p.submit())
        p.terminal(run)
        p.close()
        # Old PID/birth records must not reserve a different, reused process.
        # An unrelated real sleeper supplies a live PID with a different birth.
        unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
        with p.data.store.connect() as db:
            db.execute("UPDATE runs SET pid=?,birth=?", (unrelated.pid, "old-birth"))
        ops.write_json(
            base / "http.json",
            {"pid": unrelated.pid, "birth": "old-birth", "code": str(base / "releases" / SHA)},
        )
        close_stores(p)
        try:
            result = ops.backup(backup_args(base, tmp_path / "backups", "offline"))
            assert result["full_state"] is True
            assert unrelated.poll() is None
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=5)
        args = restore_args(result, tmp_path / "restored")
        assert ops.restore(args)["credentials_checked"] == 3
        with pytest.raises(ValueError, match="already exists"):
            ops.restore(args)
        wrong = tmp_path / "wrong-master"
        wrong.write_bytes(b"x" * 32)
        wrong.chmod(0o600)
        args.master_file = wrong
        args.target = tmp_path / "wrong-target"
        with pytest.raises(ValueError, match="master does not match"):
            ops.restore(args)
        original_manifest = ops.read_json(Path(result["snapshot"]) / "manifest.json")
        altered = {**original_manifest, "completed": False}
        ops.write_json(Path(result["snapshot"]) / "manifest.json", altered)
        with pytest.raises(ValueError, match="incomplete"):
            ops.restore(restore_args(result, tmp_path / "incomplete-target"))
        ops.write_json(Path(result["snapshot"]) / "manifest.json", original_manifest)
        args = restore_args(result, tmp_path / "corrupt-target")
        source = Path(result["snapshot"])
        (source / "state/team.json").write_text("{}")
        with pytest.raises(ValueError, match="digest mismatch"):
            ops.restore(args)
        assert not args.target.exists()
        (source / "state/team.json").unlink()
        (source / "state/team.json").symlink_to(base / "state/team.json")
        with pytest.raises(ValueError, match="symlink"):
            ops.restore(args)
        reopen_store(p)
        with p.data.store.connect() as db:
            db.execute("UPDATE submissions SET submitter='another-person'")
        with pytest.raises(ValueError, match="frozen ownership"):
            ops.backup(backup_args(base, tmp_path / "wrong-owner"))
    finally:
        reopen_store(p)
        p.close()


def test_control_lock_timeout_and_unrecorded_writer(tmp_path):
    base = tmp_path / "instance"
    base.mkdir()
    p = Processes(base)
    try:
        with p.data.store.control(), pytest.raises(ValueError, match="lock timeout"):
            ops.backup(backup_args(base, tmp_path / "busy"))
        close_stores(p)
        # Even with no HTTP/scheduler record an open state descriptor blocks full backup.
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                'import sys,time; f=open(sys.argv[1]); print("ready",flush=True); time.sleep(30)',
                str(p.data.root / "team.json"),
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert child.stdout is not None
            assert child.stdout.readline().strip() == "ready"
            with pytest.raises(ValueError, match="writers"):
                ops.backup(backup_args(base, tmp_path / "busy-fd", "offline"))
        finally:
            child.terminate()
            child.wait(timeout=5)
    finally:
        reopen_store(p)
        p.close()


def test_cleanup_detached_exact_marker_preserves_unrelated(tmp_path):
    marker = "test-ops-" + str(os.getpid())
    command = [sys.executable, "-c", "import time; time.sleep(30)"]
    child = subprocess.Popen(
        command, env={**os.environ, "HH_VERIFY_RUN": marker}, start_new_session=True
    )
    unrelated = subprocess.Popen(command, start_new_session=True)
    try:
        assert wait(lambda: verify.owned(marker))
        cleanup = verify.cleanup(marker)
        assert cleanup["signals"] and not cleanup["remaining"]
        child.wait(timeout=5)
        assert unrelated.poll() is None
    finally:
        for process in (child, unrelated):
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
            process.wait(timeout=5)


@pytest.mark.parametrize(
    ("command", "relative"),
    [
        ("backup", "state/service.json"),
        ("backup", "http.json"),
        ("backup", "state/control.lock"),
        ("check", "http.json"),
        ("check", "state/scheduler.json"),
        ("check", "state/queue.sqlite"),
    ],
)
def test_cli_refuses_fifo_inputs_without_blocking(tmp_path, command, relative):
    base = tmp_path / "instance"
    state = base / "state"
    state.mkdir(parents=True, mode=0o700)
    master = base / "master.key"
    master.write_bytes(b"x" * 32)
    master.chmod(0o600)
    (state / "service.json").write_text(json.dumps({"master_file": str(master)}))
    (state / "control.lock").touch()
    special = base / relative
    special.unlink(missing_ok=True)
    os.mkfifo(special, 0o600)
    output = tmp_path / "backups"
    args = [sys.executable, str(REPO / "scripts/ops.py"), command, "--directory", str(base)]
    if command == "backup":
        args += ["--output", str(output), "--release", SHA, "--kind", "online"]
    # The timeout is a regression guard only: the CLI must exit on its own.
    result = subprocess.run(args, capture_output=True, text=True, timeout=2, check=False)
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "status": "failed",
        "error_type": "NonregularFileError",
        "reason": "nonregular file refused",
    }
    assert not result.stderr
    assert special.is_fifo()
    assert not list(output.glob("snapshot-*/manifest.json"))
    assert not list(output.glob("*.master"))


def test_json_reader_refuses_fifo_replaced_during_open(tmp_path):
    source = tmp_path / "record.json"
    source.write_text("{}")
    # Exercise a real path replacement after lstat, rather than mocking fstat
    # or the resulting failure. A blocking open would time out this child.
    script = """
import os
import sys
sys.path.insert(0, sys.argv[1])
import ops
path = ops.Path(sys.argv[2])
original = os.open
def replace_then_open(target, flags):
    path.unlink()
    os.mkfifo(path, 0o600)
    return original(target, flags)
os.open = replace_then_open
try:
    ops.read_json(path)
except ops.NonregularFileError:
    print("replacement FIFO refused")
else:
    raise AssertionError("replacement FIFO accepted")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(REPO / "scripts"), str(source)],
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "replacement FIFO refused"


def test_snapshot_evidence_lock_defers_without_holding_control(processes, tmp_path):
    p = processes
    p.start()
    run_id = p.run_id(p.submit())
    p.terminal(run_id)
    wait(lambda: p.data.store.get(run_id)["audit_status"] == "clean")
    import threading

    entered, release = threading.Event(), threading.Event()

    def own_evidence():
        with p.data.store.evidence(run_id):
            entered.set()
            release.wait(5)

    thread = threading.Thread(target=own_evidence)
    thread.start()
    assert entered.wait(2)
    try:
        with pytest.raises(ValueError, match="deferred: run evidence busy"):
            ops.backup(
                backup_args(p.data.root.parent, tmp_path.parent / (tmp_path.name + "-backup-busy"))
            )
        admin = next(u for u in p.data.users() if u["role"] == "admin")
        with pytest.raises(ValueError, match="Evidence maintenance"):
            p.app.delete_artifact(admin, run_id, "fixture-file")
        with (p.data.root / "control.lock").open("a") as lock:
            __import__("fcntl").flock(
                lock, __import__("fcntl").LOCK_EX | __import__("fcntl").LOCK_NB
            )
    finally:
        release.set()
        thread.join()


def test_offline_fifo_excluded_and_holder_detected(tmp_path):
    from harbor_helper.persistence.wakeup import Mailbox

    (tmp_path / "instance").mkdir()
    p = Processes(tmp_path / "instance")
    # This fixture has no scheduler; its held FIFO is still a state writer.
    mailbox = Mailbox(p.data.root)
    reader = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os,sys,time; fd=os.open(sys.argv[1],os.O_RDONLY); time.sleep(30)",
            str(p.data.root / "scheduler.wake"),
        ]
    )
    close_stores(p)
    try:
        wait(
            lambda: any(
                r.get("pid") == reader.pid for r in ops.writers(p.data.root.parent, {"runs": []})
            )
        )
        with pytest.raises(ValueError, match="writers"):
            ops.backup(backup_args(p.data.root.parent, tmp_path / "busy-fifo", "offline"))
        reader.terminate()
        reader.wait(timeout=3)
        mailbox.close()
        result = ops.backup(backup_args(p.data.root.parent, tmp_path / "offline", "offline"))
        snapshot = Path(result["snapshot"])
        assert not (snapshot / "state/scheduler.wake").exists()
        restored = tmp_path / "restored"
        ops.restore(restore_args(result, restored))
        assert not (restored / "state/scheduler.wake").exists()
    finally:
        if reader.poll() is None:
            reader.kill()
            reader.wait()
        reopen_store(p)
        p.close()
