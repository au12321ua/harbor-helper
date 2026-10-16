"""Ops behavior against isolated production HTTP/scheduler and synthetic executions."""

import argparse
import importlib.util
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from test_automation_http import http_service  # noqa: F401
from test_service_process import Processes, wait

REPO = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


ops = module("ops")
verify = module("verify")
SHA = "a" * 40


def backup_args(base, out, kind="online"):
    return argparse.Namespace(directory=base, output=out, kind=kind, release=SHA, lock_timeout=0.1)


def restore_args(result, target):
    snapshot = Path(result["snapshot"])
    return argparse.Namespace(
        snapshot=snapshot,
        target=target,
        release=SHA,
        master_file=snapshot.with_name(snapshot.name + ".master"),
    )


def test_online_snapshot_live_writers_restore_and_ownership(http_service, tmp_path):  # noqa: F811
    p, _url, base = http_service
    # A completed zero-score fixture plus a worker deliberately held in execution.
    done = p.run_id(p.submit(idem="ops-terminal"))
    p.terminal(done)
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
        assert config["master_file"] == str(target / "private/master.key")
        assert ops.key_bytes(target / "private/master.key") == p.data._master()
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


def test_readonly_check_health_ready_and_unknown(http_service):  # noqa: F811
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
        try:
            result = ops.backup(backup_args(base, tmp_path / "backups", "offline"))
            assert result["full_state"] is True
            print("offline_writers_path=full_snapshot_verified")
        except ValueError as error:
            # On a desktop, nondumpable same-UID processes make a complete
            # writer proof unavailable. Refusal is REQUIRED, never bypass it.
            assert '"kind": "unknown"' in str(error)
            assert not list((tmp_path / "backups").glob("snapshot-*/manifest.json"))
            print("offline_writers_path=host_unknown_refused")
            result = ops.backup(backup_args(base, tmp_path / "online-backups"))
            assert result["full_state"] is False
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
        with p.data.store.connect() as db:
            db.execute("UPDATE submissions SET submitter='another-person'")
        with pytest.raises(ValueError, match="frozen ownership"):
            ops.backup(backup_args(base, tmp_path / "wrong-owner"))
    finally:
        p.close()


def test_control_lock_timeout_and_unrecorded_writer(tmp_path):
    base = tmp_path / "instance"
    base.mkdir()
    p = Processes(base)
    try:
        with p.data.store.control(), pytest.raises(ValueError, match="lock timeout"):
            ops.backup(backup_args(base, tmp_path / "busy"))
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
            assert child.stdout.readline().strip() == "ready"
            with pytest.raises(ValueError, match="writers"):
                ops.backup(backup_args(base, tmp_path / "busy-fd", "offline"))
        finally:
            child.terminate()
            child.wait(timeout=5)
    finally:
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
