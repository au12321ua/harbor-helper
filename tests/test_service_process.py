"""Actual service scheduler/worker processes with only external execution replaced.

Fake Hub snapshots and Docker identities live in a copied package; the worker
execution adapter records key fingerprints and returns native-shaped zero-score
results without network. Production has no fixture switch.
"""

import hashlib
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harbor_helper.execution.processes import process_birth
from harbor_helper.persistence.files import read_json
from harbor_helper.service.application import Application
from harbor_helper.service.data import ServiceData
from harbor_helper.service.observation import scheduler
from harbor_helper.service.primitives import ServiceError


def wait(predicate, timeout=20):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("Service process fixture timed out")


class Processes:
    def __init__(self, base):
        self.cwd = base / "work"
        self.cwd.mkdir()
        package = self.cwd / "harbor_helper"
        shutil.copytree(
            Path(__file__).resolve().parents[1] / "src/harbor_helper",
            package,
            ignore=shutil.ignore_patterns("__pycache__", "static"),
        )
        with (package / "execution/sources.py").open("a") as f:
            f.write("""
async def resolve_dataset(reference, target, task_filter=None):
    while (target.parents[2]/"prepare-hold").exists():
        await __import__('asyncio').sleep(.05)
    target.mkdir()
    folder=target/"box";folder.mkdir()
    (folder/"task.toml").write_text('version = "1.0"\\n# fixture fixed input')
    return {"requested":reference,"resolved":reference,"tasks":[{
        "package":"fixture/box","directory":"box","ref":"sha256:fixed",
        "snapshot_digest":tree_digest(folder)}]}
""")
        with (package / "service/sources.py").open("a") as f:
            f.write("""
def source_call(reference, *, key=None, target=None, task=None):
    import asyncio
    from harbor_helper.execution.sources import resolve_dataset
    return asyncio.run(resolve_dataset(reference, target, task))
""")
        with (package / "execution/runs.py").open("a") as f:
            f.write("""
def image_identity(reference):return "sha256:"+"f"*64
_original_run=subprocess.run
def _fixture_run(argv,*args,**kwargs):
    if argv[:2]==["docker","tag"]:return subprocess.CompletedProcess(argv,0)
    return _original_run(argv,*args,**kwargs)
subprocess.run=_fixture_run
""")
        fixture = """
_original_cleanup=cleanup
def cleanup(path):
    if (path/"resource-blocked").exists():raise RuntimeError("fixture resource retained")
    return _original_cleanup(path)
async def execute(store,run_id):
    from harbor_helper.service.data import ServiceData
    key=ServiceData(store.root).run_key(run_id,execution=True)
    if key != os.environ.get("VLLM_API_KEY"):raise RuntimeError("Worker environment binding mismatch")
    path=store.path(run_id)
    cfg=read_json(path/"manifest.json")["effective"]
    write_json(path/"boundary.json",{"key_digest":__import__('hashlib').sha256((key or '').encode()).hexdigest(),
        "endpoint":(cfg.get('model') or {}).get('endpoint'),"model":(cfg.get('model') or {}).get('name')})
    (path/"worker-raw.log").write_text(key or 'oracle')
    while (store.root/"worker-hold").exists():await asyncio.sleep(.05)
    trial=path/"harbor"/run_id/"box__fixture";trial.mkdir(parents=True)
    write_json(trial/"result.json",{"task_name":"fixture/box","trial_name":"box__fixture",
        "verifier_result":{"rewards":{"reward":0.0}},"exception_info":None})
    return {"status":"succeeded","reason":None}

"""
        cleanup_fixture, execute_fixture = fixture.split("async def execute", 1)
        with (package / "execution/scheduler.py").open("a") as f:
            f.write(cleanup_fixture)
        with (package / "execution/runner.py").open("a") as f:
            f.write("async def execute" + execute_fixture)
        with (package / "execution/scheduler.py").open("a") as f:
            f.write("""
RECONCILE_SECONDS = 3600
RETRY_SECONDS = .5
HEARTBEAT_SECONDS = .2
MAINTENANCE_SECONDS = .5
_original_fixture_cleanup = cleanup
def cleanup(path):
    while (path/"cleanup-hold").exists():time.sleep(.02)
    return _original_fixture_cleanup(path)
_original_fixture_stop = stop_group
def stop_group(row):
    while (Path(__import__('sys').argv[-1])/"runs"/row["id"]/"termination-hold").exists():time.sleep(.02)
    return _original_fixture_stop(row)
_original_fixture_audit = audit_finished
def audit_finished(store,row):
    while (store.path(row['id'])/"audit-hold").exists():time.sleep(.02)
    return _original_fixture_audit(store,row)
_original_fixture_popen = subprocess.Popen
def _launch_window(*args,**kwargs):
    root=Path(args[0][-2])
    if (root/"spawn-hold").exists():
        (root/"spawn-waiting").touch()
        while (root/"spawn-hold").exists():time.sleep(.02)
    child = _original_fixture_popen(*args,**kwargs)
    if (root/"register-hold").exists():
        write_json(root/"unregistered-worker.json", {"pid":child.pid,"birth":process_birth(child.pid)})
        while (root/"register-hold").exists():time.sleep(.02)
    return child
subprocess.Popen = _launch_window
""")
        with (package / "service/lifecycle.py").open("a") as f:
            f.write("""
_original_fixture_maintenance = maintenance
def maintenance(store):
    while (store.root/"maintenance-hold").exists():time.sleep(.02)
    return _original_fixture_maintenance(store)
""")
        self.home = base / "home"
        self.home.mkdir()
        self.env = {
            k: v
            for k, v in os.environ.items()
            if k in {"PATH", "LANG", "HH_VERIFY_RUN", "DOCKER_HOST", "PLAYWRIGHT_BROWSERS_PATH"}
        }
        self.env["HOME"] = str(self.home)
        for name in (
            "PYTHONPATH",
            "VLLM_API_KEY",
            "OPENAI_API_KEY",
            "HARBOR_HELPER_LEGACY_AUDIT_KEY",
            "HARBOR_HELPER_STATE",
        ):
            self.env.pop(name, None)
        self.data = ServiceData.initialize(
            base / "state", base / "private" / "master", "admin", "Fake-process-password-2026"
        )
        self.actor = self.data.create_user("alice", "Fake-process-password-2026")
        self.keys = []
        for index in range(1, 4):
            provider = "p1" if index < 3 else "p2"
            if index in (1, 3):
                self.data.models.save_object(
                    "provider",
                    {
                        "id": provider,
                        "protocol": "openai-compatible",
                        "endpoint": f"http://{provider}.invalid/v1",
                        "name": provider,
                    },
                )
            key = f"fake-process-key-{index}-2026"
            self.keys.append(key)
            self.data.add_credential(f"k{index}", provider, f"key{index}", key)
            self.data.models.save_object(
                "profile",
                {
                    "id": f"m{index}",
                    "provider_id": provider,
                    "credential_id": f"k{index}",
                    "model": f"model{index}",
                    "params": {},
                },
            )
        self.app = Application(self.data.root)
        self.log = (base / "supervisor-output.log").open("a")
        self.child = None

    def start(self):
        self.child = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "harbor_helper.execution.worker",
                "supervise",
                str(self.data.root),
            ],
            cwd=self.cwd,
            env=self.env,
            stdout=self.log,
            stderr=self.log,
            start_new_session=True,
        )
        wait(
            lambda: (
                (self.data.root / "scheduler.json").exists()
                and self.child is not None
                and read_json(self.data.root / "scheduler.json")["pid"] == self.child.pid
                and scheduler(self.app)["state"] == "ready"
            )
        )

    def submit(self, model="m1", idem="one", oracle=False):
        return self.app.accept(
            self.actor,
            {
                "dataset": "fixture/data@1",
                **({"agent": "oracle"} if oracle else {"model_profile": model}),
            },
            idem,
        )

    def run_id(self, submission):
        return wait(lambda: self.data.submission(submission["id"])["run_id"])

    def terminal(self, run_id):
        return wait(
            lambda: (
                r
                if (r := self.data.store.get(run_id))["status"]
                in {"succeeded", "failed", "cancelled", "cleanup_blocked"}
                else None
            )
        )

    def kill_scheduler(self):
        if self.child and self.child.poll() is None:
            os.kill(self.child.pid, signal.SIGKILL)
            self.child.wait(timeout=5)

    def close(self):
        self.kill_scheduler()
        for row in self.data.store.runs():
            if row["pid"] and process_birth(row["pid"]) == row["birth"]:
                os.killpg(row["pid"], signal.SIGKILL)
        self.log.close()


@pytest.fixture
def processes(tmp_path):
    p = Processes(tmp_path)
    try:
        yield p
    finally:
        p.close()


def test_three_bound_credentials_actual_workers_no_cross_use(processes):
    p = processes
    p.data.set_limits({"max_jobs": 2, "max_trials": 2})
    p.start()
    submissions = [p.submit(f"m{i}", str(i)) for i in (1, 2, 3)]
    for i, submission in enumerate(submissions):
        run_id = p.run_id(submission)
        assert p.terminal(run_id)["status"] == "succeeded"
        wait(lambda run_id=run_id: p.data.store.get(run_id)["audit_status"] == "clean")
        path = p.data.store.path(run_id)
        proof = read_json(path / "boundary.json")
        assert proof["key_digest"] == hashlib.sha256(p.keys[i].encode()).hexdigest()
        assert proof["endpoint"] == f"http://{'p1' if i < 2 else 'p2'}.invalid/v1"
        assert proof["model"] == f"model{i + 1}"
        assert p.app.safe_report(run_id)["tasks"][0]["mean_rewards"] == {"reward": 0.0}
        assert all(key not in (path / "worker-raw.log").read_text() for key in p.keys)
    assert p.app.usage()["active_jobs"] == 0


def test_preparation_cancel_and_scheduler_restart_no_orphan(processes):
    p = processes
    hold = p.data.root / "prepare-hold"
    hold.touch()
    p.start()
    first = p.submit()
    time.sleep(0.3)
    p.app.cancel_submission(p.actor, first["id"])
    hold.unlink()
    time.sleep(0.4)
    assert p.data.submission(first["id"])["status"] == "cancelled"
    assert not p.data.store.runs()
    hold.touch()
    second = p.submit(idem="restart")
    time.sleep(0.4)
    p.kill_scheduler()
    hold.unlink()
    p.start()
    run_id = p.run_id(second)
    assert p.terminal(run_id)["status"] == "succeeded"
    assert len(p.data.store.runs()) == 1


def test_hard_worker_missing_key_releases_capacity_other_key_proceeds(processes):
    p = processes
    hold = p.data.root / "worker-hold"
    hold.touch()
    p.start()
    first = p.submit()
    second = p.submit("m2", "second")
    run_id = p.run_id(first)
    wait(lambda: (p.data.store.path(run_id) / "boundary.json").exists())
    row = p.data.store.get(run_id)
    with p.data.store.control(), p.data.store.connect() as db:
        db.execute("DELETE FROM credential_versions WHERE id='k1'")
    os.killpg(row["pid"], signal.SIGKILL)
    row = p.terminal(run_id)
    assert row["status"] == "failed"
    wait(lambda: p.data.store.get(run_id)["audit_status"] == "incomplete")
    with pytest.raises(ServiceError):
        p.app.logs(run_id)
    next_id = p.run_id(second)
    wait(lambda: (p.data.store.path(next_id) / "boundary.json").exists())
    hold.unlink()
    assert p.terminal(next_id)["status"] == "succeeded"
    assert p.app.usage()["active_jobs"] == 0
    from harbor_helper.execution.runs import stop_supervisor

    assert stop_supervisor(p.data.store)["confirmed"]


def test_wake_before_long_reconcile_capacity_and_live_worker_adoption(processes):
    p = processes
    (p.data.root / "worker-hold").touch()
    p.start()
    first = p.run_id(p.submit())
    wait(lambda: (p.data.store.path(first) / "boundary.json").exists())
    original = p.data.store.get(first)
    p.kill_scheduler()
    p.start()
    assert p.data.store.get(first)["pid"] == original["pid"]
    assert process_birth(original["pid"]) == original["birth"]
    second = p.run_id(p.submit("m2", "next"))
    assert p.data.store.get(second)["status"] == "queued"
    started = time.monotonic()
    p.data.set_limits({"max_jobs": 2, "max_trials": 2})  # direct production persistence path
    wait(lambda: (p.data.store.path(second) / "boundary.json").exists(), timeout=4)
    assert time.monotonic() - started < 4
    p.app.cancel_run(p.actor, first)
    assert p.terminal(first)["status"] == "cancelled"
    (p.data.root / "worker-hold").unlink()
    assert p.terminal(second)["status"] == "succeeded"


def test_slow_cleanup_does_not_delay_other_worker_termination_or_heartbeat(processes):
    p = processes
    p.data.set_limits({"max_jobs": 2, "max_trials": 2})
    (p.data.root / "worker-hold").touch()
    p.start()
    first = p.run_id(p.submit())
    second = p.run_id(p.submit("m2", "second"))
    wait(lambda: (p.data.store.path(second) / "boundary.json").exists())
    first_path = p.data.store.path(first)
    (first_path / "cleanup-hold").touch()
    (first_path / "audit-hold").touch()
    p.app.cancel_run(p.actor, first)
    wait(lambda: not process_birth(p.data.store.get(first)["pid"]))
    assert p.app.usage()["active_jobs"] == 2
    p.data.set_limits({"max_jobs": 1, "max_trials": 1})
    p.app.cancel_run(p.actor, second)
    started = time.monotonic()
    second_pid = p.data.store.get(second)["pid"]
    wait(lambda: not process_birth(second_pid), timeout=4)
    assert time.monotonic() - started < 4
    assert p.terminal(second)["status"] == "cancelled"
    before = read_json(p.data.root / "scheduler.json")["observed"]
    wait(lambda: read_json(p.data.root / "scheduler.json")["observed"] > before)
    assert p.data.store.get(first)["status"] == "cancelling"
    (first_path / "cleanup-hold").unlink()
    assert p.terminal(first)["status"] == "cancelled"
    assert p.app.usage()["active_jobs"] == 0  # audit still held
    assert p.data.store.get(first)["audit_status"] != "clean"
    (first_path / "audit-hold").unlink()
    wait(lambda: p.data.store.get(first)["audit_status"] == "clean")


def test_finish_decision_survives_supervisor_crash_during_cleanup(processes):
    p = processes
    (p.data.root / "worker-hold").touch()
    p.start()
    run_id = p.run_id(p.submit())
    path = p.data.store.path(run_id)
    wait(lambda: (path / "boundary.json").exists())
    (path / "cleanup-hold").touch()
    p.app.cancel_run(p.actor, run_id)
    wait(lambda: p.data.store.get(run_id)["finish_status"] == "cancelled")
    wait(lambda: not process_birth(p.data.store.get(run_id)["pid"]))
    p.kill_scheduler()
    (path / "cleanup-hold").unlink()
    p.start()
    assert p.terminal(run_id)["status"] == "cancelled"
    assert p.data.store.get(run_id)["reason"] == "Cancelled by member"


def test_unregistered_worker_handshake_refuses_execution(processes):
    p = processes
    (p.data.root / "register-hold").touch()
    p.start()
    run_id = p.run_id(p.submit())
    marker = p.data.root / "unregistered-worker.json"
    wait(marker.exists)
    identity = read_json(marker)
    assert p.data.store.get(run_id)["status"] == "starting"
    p.kill_scheduler()
    (p.data.root / "register-hold").unlink()
    try:
        wait(lambda: process_birth(identity["pid"]) != identity["birth"], timeout=13)
        assert not (p.data.store.path(run_id) / "boundary.json").exists()
        assert (
            "ownership handshake expired" in (p.data.store.path(run_id) / "worker.log").read_text()
        )
        p.start()
        assert p.terminal(run_id)["status"] == "failed"
    finally:
        if process_birth(identity["pid"]) == identity["birth"]:
            os.killpg(identity["pid"], signal.SIGKILL)


def test_graceful_stop_waits_for_maintenance_and_rejects_new_admission(processes):
    from harbor_helper.execution.runs import stop_supervisor

    p = processes
    hold = p.data.root / "maintenance-hold"
    hold.touch()
    p.start()
    time.sleep(0.7)
    with pytest.raises(ValueError, match="not confirmed"):
        stop_supervisor(p.data.store, timeout=0.3)
    assert process_birth(p.child.pid)
    with pytest.raises(ServiceError, match="stopping"):
        p.submit()
    hold.unlink()
    p.child.wait(timeout=5)
    assert stop_supervisor(p.data.store)["confirmed"]


def test_start_identity_precedes_control_and_sqlite_wait(processes):
    p = processes
    # Store constructor itself waits on this writer, after identity/FIFO publication.
    with p.data.store.connect() as db, p.data.store.control():
        db.execute("BEGIN IMMEDIATE")
        p.child = subprocess.Popen(
            [sys.executable, "-m", "harbor_helper.execution.worker", "supervise", str(p.data.root)],
            cwd=p.cwd,
            env=p.env,
            stdout=p.log,
            stderr=p.log,
            start_new_session=True,
        )
        wait(lambda: (p.data.root / "scheduler.json").exists(), timeout=3)
        identity = read_json(p.data.root / "scheduler.json")
        assert identity["pid"] == p.child.pid and "observed" not in identity
        assert scheduler(p.app)["state"] != "ready"
    wait(lambda: scheduler(p.app)["state"] == "ready")


def test_lost_notification_reconciles_durable_submission(processes):
    p = processes
    package = p.cwd / "harbor_helper"
    with (package / "execution/scheduler.py").open("a") as file:
        file.write("\nRECONCILE_SECONDS = .5\n")
    p.start()
    # Remove the published name while the reader remains alive: all producer hints
    # now disappear. The durable preparing record must still be recovered.
    (p.data.root / "scheduler.wake").unlink()
    run_id = p.run_id(p.submit())
    assert p.terminal(run_id)["status"] == "succeeded"


def test_message_storm_does_not_starve_running_cancellation(processes):
    import threading

    from harbor_helper.persistence.wakeup import notify

    p = processes
    (p.data.root / "worker-hold").touch()
    p.start()
    run_id = p.run_id(p.submit())
    wait(lambda: (p.data.store.path(run_id) / "boundary.json").exists())
    stopped = threading.Event()

    def flood():
        while not stopped.is_set():
            notify(p.data.root)

    thread = threading.Thread(target=flood)
    thread.start()
    try:
        p.app.cancel_run(p.actor, run_id)
        wait(lambda: not process_birth(p.data.store.get(run_id)["pid"]), timeout=4)
        assert p.terminal(run_id)["status"] == "cancelled"
    finally:
        stopped.set()
        thread.join(timeout=3)


def test_duplicate_supervisor_keeps_canonical_identity(processes):
    p = processes
    p.start()
    identity = read_json(p.data.root / "scheduler.json")
    duplicate = subprocess.Popen(
        [sys.executable, "-m", "harbor_helper.execution.worker", "supervise", str(p.data.root)],
        cwd=p.cwd,
        env=p.env,
        stdout=p.log,
        stderr=p.log,
    )
    duplicate.wait(timeout=4)
    assert duplicate.returncode != 0
    assert read_json(p.data.root / "scheduler.json")["pid"] == identity["pid"]


def test_wall_deadline_progresses_during_slow_audit(processes):
    from harbor_helper.persistence.files import write_json

    p = processes
    p.data.set_limits({"max_jobs": 2, "max_trials": 2})
    (p.data.root / "worker-hold").touch()
    p.start()
    first = p.run_id(p.submit())
    wait(lambda: (p.data.store.path(first) / "boundary.json").exists())
    (p.data.store.path(first) / "audit-hold").touch()
    p.app.cancel_run(p.actor, first)
    assert p.terminal(first)["status"] == "cancelled"
    second = p.run_id(p.submit("m2", "timeout"))
    wait(lambda: (p.data.store.path(second) / "boundary.json").exists())
    path = p.data.store.path(second) / "manifest.json"
    manifest = read_json(path)
    manifest["effective"]["wall_seconds"] = 0.5
    write_json(path, manifest)
    assert p.terminal(second)["reason"] == "Wall-clock budget exceeded"
    assert p.app.usage()["active_jobs"] == 0
    (p.data.store.path(first) / "audit-hold").unlink()


def test_reservation_crash_before_spawn_recovers_without_executor(processes):
    p = processes
    (p.data.root / "spawn-hold").touch()
    p.start()
    run_id = p.run_id(p.submit())
    wait(lambda: (p.data.root / "spawn-waiting").exists())
    assert p.data.store.get(run_id)["status"] == "starting"
    assert p.data.store.get(run_id)["pid"] is None
    p.kill_scheduler()
    (p.data.root / "spawn-hold").unlink()
    p.start()
    assert p.terminal(run_id)["status"] == "failed"
    assert not (p.data.store.path(run_id) / "boundary.json").exists()


def test_slow_termination_has_a_slot_for_each_existing_worker(processes):
    p = processes
    p.data.set_limits({"max_jobs": 2, "max_trials": 2})
    (p.data.root / "worker-hold").touch()
    p.start()
    first = p.run_id(p.submit())
    second = p.run_id(p.submit("m2", "second"))
    wait(lambda: (p.data.store.path(second) / "boundary.json").exists())
    hold = p.data.store.path(first) / "termination-hold"
    hold.touch()
    p.app.cancel_run(p.actor, first)
    wait(lambda: p.data.store.get(first)["finish_status"] == "cancelled")
    p.data.set_limits({"max_jobs": 1, "max_trials": 1})
    p.app.cancel_run(p.actor, second)
    wait(lambda: not process_birth(p.data.store.get(second)["pid"]), timeout=4)
    assert process_birth(p.data.store.get(first)["pid"])
    hold.unlink()
    assert p.terminal(first)["status"] == "cancelled"
    assert p.terminal(second)["status"] == "cancelled"


def test_cleanup_blocked_retries_persistent_cancel_and_holds_capacity(processes):
    from harbor_helper.persistence.wakeup import notify

    p = processes
    (p.data.root / "worker-hold").touch()
    p.start()
    first = p.run_id(p.submit())
    wait(lambda: (p.data.store.path(first) / "boundary.json").exists())
    blocked = p.data.store.path(first) / "resource-blocked"
    blocked.touch()
    p.app.cancel_run(p.actor, first)
    wait(lambda: p.data.store.get(first)["status"] == "cleanup_blocked")
    second = p.run_id(p.submit("m2", "queued-during-block"))
    assert p.data.store.get(second)["status"] == "queued"
    assert p.app.usage()["active_jobs"] == 1
    p.kill_scheduler()
    p.start()
    assert p.data.store.get(first)["finish_status"] == "cancelled"
    blocked.unlink()
    notify(p.data.root)
    wait(lambda: p.data.store.get(first)["status"] == "cancelled")
    wait(lambda: (p.data.store.path(second) / "boundary.json").exists())
    (p.data.root / "worker-hold").unlink()
    assert p.terminal(second)["status"] == "succeeded"


def test_slow_preparation_and_maintenance_leave_control_responsive(processes):
    p = processes
    maintenance = p.data.root / "maintenance-hold"
    preparation = p.data.root / "prepare-hold"
    maintenance.touch()
    (p.data.root / "worker-hold").touch()
    p.start()
    first = p.run_id(p.submit())
    wait(lambda: (p.data.store.path(first) / "boundary.json").exists())
    preparation.touch()
    second = p.submit("m2", "slow-prepare")
    time.sleep(0.3)
    assert p.data.submission(second["id"])["status"] == "preparing"
    heartbeat = read_json(p.data.root / "scheduler.json")["observed"]
    p.app.cancel_run(p.actor, first)
    wait(lambda: not process_birth(p.data.store.get(first)["pid"]), timeout=4)
    assert p.terminal(first)["status"] == "cancelled"
    wait(lambda: read_json(p.data.root / "scheduler.json")["observed"] > heartbeat)
    assert preparation.exists() and maintenance.exists()
    preparation.unlink()
    maintenance.unlink()
    (p.data.root / "worker-hold").unlink()
    assert p.terminal(p.run_id(second))["status"] == "succeeded"


@pytest.mark.parametrize("invalidation", ["credential", "member", "provider"])
def test_full_capacity_rechecks_queued_authorization_on_production_wake(processes, invalidation):
    p = processes
    hold = p.data.root / "worker-hold"
    hold.touch()
    bob = p.data.create_user("bob", "Fake-process-password-2026")

    def submit_bob(idem):
        return p.app.accept(bob, {"dataset": "fixture/data@1", "model_profile": "m3"}, idem)

    p.start()  # Fixture reconciliation is 3600s; production mutations must wake it.
    first = p.run_id(submit_bob("active"))
    wait(lambda: (p.data.store.path(first) / "boundary.json").exists())
    original = p.data.store.get(first)
    rejected = p.run_id(p.submit("m1", "will-lose-authorization"))
    unaffected = p.run_id(submit_bob("unaffected"))
    assert p.data.store.get(rejected)["status"] == "queued"
    assert p.data.store.get(unaffected)["status"] == "queued"

    provider = p.data.object("provider", "p1")
    if invalidation == "credential":
        p.data.disable_credential("k1")
    elif invalidation == "member":
        p.data.update_user(p.actor["id"], enabled=False)
    else:
        p.data.models.save_object("provider", {**provider, "enabled": False})
    wait(lambda: p.data.store.get(rejected)["status"] == "failed", timeout=4)
    row = p.data.store.get(rejected)
    assert row["pid"] is None and row["started"] is None
    assert row["reason"] == "Execution authorization unavailable; worker not started"
    path = p.data.store.path(rejected)
    assert not (path / "boundary.json").exists()
    assert not (path / "worker.log").exists()
    assert p.app.usage()["active_jobs"] == 1
    assert p.data.store.get(first)["pid"] == original["pid"]
    assert process_birth(original["pid"]) == original["birth"]
    wait(lambda: p.data.store.get(rejected)["audit_status"] == "clean")
    report = p.app.safe_report(rejected)
    assert all(key not in str(report) for key in p.keys)

    if invalidation == "credential":
        p.data.add_credential("k1", "p1", "restored", p.keys[0], rotate=True)
    elif invalidation == "member":
        p.data.update_user(p.actor["id"], enabled=True)
    else:
        p.data.models.save_object("provider", {**provider, "enabled": True})
    restored = p.run_id(p.submit("m1", "restored"))
    assert p.data.store.get(restored)["status"] == "queued"
    assert p.data.store.get(unaffected)["status"] == "queued"
    assert p.data.store.get(rejected)["status"] == "failed"
    assert p.app.usage()["active_jobs"] == 1
    hold.unlink()
    for run_id in (first, unaffected, restored):
        assert p.terminal(run_id)["status"] == "succeeded"
    assert p.data.store.get(rejected)["status"] == "failed"


@pytest.mark.parametrize("damage", ["missing", "json", "field", "type", "directory"])
def test_damaged_queued_input_does_not_block_following_worker_or_cancel(processes, damage):
    from harbor_helper.persistence.wakeup import notify

    p = processes
    hold = p.data.root / "worker-hold"
    hold.touch()
    p.start()  # Reconciliation is 3600s; use real FIFO notifications.
    active = p.run_id(p.submit("m1", "active"))
    wait(lambda: (p.data.store.path(active) / "boundary.json").exists())
    broken = p.run_id(p.submit("m1", "broken"))
    healthy = p.run_id(p.submit("m2", "healthy"))
    cancelled = p.run_id(p.submit("m3", "cancelled"))
    assert p.data.store.get(broken)["status"] == "queued"
    assert p.data.store.get(healthy)["status"] == "queued"
    observed = read_json(p.data.root / "scheduler.json")["observed"]
    folder = p.data.store.path(broken)
    manifest = folder / "manifest.json"
    if damage in {"missing", "directory"}:
        manifest.unlink()
        if damage == "directory":
            manifest.mkdir()
    elif damage == "json":
        manifest.write_text('{"fixture-secret-path-key":')
    elif damage == "field":
        manifest.write_text('{"service": {}, "effective": {}}')
    else:
        manifest.write_text("null")
    notify(p.data.root)
    p.app.cancel_run(p.actor, cancelled)
    wait(lambda: p.data.store.get(broken)["status"] == "failed", timeout=4)
    wait(lambda: p.data.store.get(cancelled)["status"] == "cancelled", timeout=4)
    wait(lambda: read_json(p.data.root / "scheduler.json")["observed"] > observed, timeout=4)
    row = p.data.store.get(broken)
    assert row["pid"] is None and row["started"] is None
    assert row["audit_status"] == "incomplete"
    assert row["reason"] == "Queued execution input unavailable; worker not started"
    assert not (folder / "boundary.json").exists()
    active_rows = [
        r
        for r in p.data.store.runs()
        if r["status"] in {"starting", "running", "cancelling", "cleanup_blocked"}
    ]
    assert [r["id"] for r in active_rows] == [active]
    assert sum(r["concurrency"] for r in active_rows) == 1
    assert p.data.store.get(healthy)["status"] == "queued"
    with pytest.raises((ServiceError, ValueError, OSError, KeyError, TypeError, AttributeError)):
        p.app.safe_report(broken)
    hold.unlink()
    assert p.terminal(active)["status"] == "succeeded"
    assert p.terminal(healthy)["status"] == "succeeded"
    row = p.data.store.get(healthy)
    assert row["started"] is not None and row["pid"] is not None
    assert (p.data.store.path(healthy) / "boundary.json").exists()
    assert p.data.store.get(broken)["status"] == "failed"
    output = (p.cwd.parent / "supervisor-output.log").read_text()
    assert "Scheduler error:" not in output
    assert "fixture-secret-path-key" not in output
    assert str(folder) not in output
    assert all(key not in output for key in p.keys)
