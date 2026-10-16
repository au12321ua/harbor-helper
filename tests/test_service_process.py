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
        with (package / "execution/audit.py").open("a") as f:
            f.write(cleanup_fixture)
        with (package / "execution/runner.py").open("a") as f:
            f.write("async def execute" + execute_fixture)
        self.home = base / "home"
        self.home.mkdir()
        self.env = {**os.environ, "HOME": str(self.home)}
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
            [sys.executable, "-m", "harbor_helper.execution.worker", "supervise", str(self.data.root)],
            cwd=self.cwd,
            env=self.env,
            stdout=self.log,
            stderr=self.log,
            start_new_session=True,
        )
        wait(
            lambda: (
                (self.data.root / "scheduler.json").exists()
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
