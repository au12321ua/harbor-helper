"""Runner execution responsibility."""

import asyncio
import fcntl
import importlib.metadata
import os
import sys
import time

from harbor_helper.execution.audit import redact_files
from harbor_helper.execution.config import HARBOR_VERSION
from harbor_helper.execution.sources import verify_inputs
from harbor_helper.persistence import statuses as lifecycle_status
from harbor_helper.persistence.files import read_json, write_json
from harbor_helper.persistence.store import Store
from harbor_helper.results.reports import report
from harbor_helper.security.credentials import (
    RedactedStream,
    install_docker_credential_forwarding,
    redact_value,
    runtime_secrets,
)


async def execute(store, run_id):
    from harbor.environments.docker.docker import _sanitize_docker_compose_project_name
    from harbor.job import Job
    from harbor.models.job.config import JobConfig
    from harbor.models.task.task import Task
    from harbor.trial.trial import Trial

    path = store.path(run_id)
    install_docker_credential_forwarding()
    manifest = read_json(path / "manifest.json")
    verify_inputs(path, manifest)
    if importlib.metadata.version("harbor") != HARBOR_VERSION:
        raise RuntimeError("Worker loaded the wrong Harbor version")
    model = manifest["effective"]["model"]
    from harbor_helper.service.data import ServiceData

    key = ServiceData(store.root).run_key(run_id, execution=True)
    if key:
        os.environ["VLLM_API_KEY"] = key
    elif manifest["effective"]["agent"] == "opencode" and model.get("credential_env"):
        raise RuntimeError("Model credential unavailable; worker execution refused")
    job = await Job.create(JobConfig.model_validate(read_json(path / "job.json")))
    projects, trials = [], []
    for cfg in job._trial_configs:
        from types import SimpleNamespace

        trial = SimpleNamespace(config=cfg)
        task = Task(cfg.task.path)
        sessions = [f"{cfg.trial_name}__env", Trial._separate_verifier_session_id(trial, "trial")]
        sessions += [
            Trial._separate_verifier_session_id(trial, s.name) for s in task.config.steps or []
        ]
        projects.extend(_sanitize_docker_compose_project_name(s) for s in sessions)
        trials.append({"trial_name": cfg.trial_name, "task": task.name})
    write_json(path / "projects.json", sorted(set(projects)))
    write_json(path / "trials.json", trials)
    write_json(
        path / "worker-runtime.json",
        {"python": sys.executable, "harbor_version": importlib.metadata.version("harbor")},
    )
    await job.run()
    # Do not copy raw exception text into derived reports before scrubbing it.
    redact_files(path, runtime_secrets())
    value = report(store, run_id)
    return {
        "status": lifecycle_status.SUCCEEDED if value["complete"] else lifecycle_status.FAILED,
        "reason": None if value["complete"] else "Missing/exceptional Trial reward; see report",
    }


def run(root, run_id):
    store = Store(root)
    path = store.path(run_id)
    with (path / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        # No environment work before the scheduler has persisted PID ownership.
        for _ in range(100):
            row = store.get(run_id)
            if row["pid"] == os.getpid() and row["status"] == lifecycle_status.RUNNING:
                break
            time.sleep(0.1)
        else:
            return
        secrets = runtime_secrets()
        sys.stdout = RedactedStream(sys.stdout, secrets)
        sys.stderr = RedactedStream(sys.stderr, secrets)
        try:
            outcome = asyncio.run(execute(store, run_id))
        except Exception as e:  # noqa: BLE001 - persist/diagnose third-party Harbor errors
            # Do not persist provider payloads from exception strings. Complete
            # details remain available only in separately audited task evidence.
            print(f"Harbor startup/execution failed: {type(e).__name__}", flush=True)
            outcome = {"status": lifecycle_status.FAILED, "reason": "Worker execution failed"}
        sys.stdout.finish()
        sys.stderr.finish()
        redact_files(path, secrets)
        outcome["reason"] = redact_value(outcome["reason"], secrets)
        write_json(path / "outcome.json", outcome)
        from harbor_helper.persistence.wakeup import notify

        notify(store.root)
