import asyncio
import fcntl
import importlib.metadata
import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from harbor_helper.execution.config import HARBOR_VERSION, load_team
from harbor_helper.execution.processes import alive, process_birth, run_command, safe_environment
from harbor_helper.execution.sources import verify_inputs
from harbor_helper.persistence.files import read_json, write_json
from harbor_helper.persistence.store import ACTIVE, TERMINAL, Store
from harbor_helper.results.reports import report
from harbor_helper.security.credentials import (
    RedactedStream,
    audit_run,
    install_docker_credential_forwarding,
    legacy_secrets,
    redact_value,
    runtime_secrets,
    scrub_file,
    scrub_run,
)


def cleanup(path):
    """Only exact native Compose projects recorded before starting any Trial."""
    from harbor_helper.execution.agent_tools import cleanup_staging

    cleanup_staging(path, process_birth)
    projects_file = path / "projects.json"
    if not projects_file.exists():
        write_json(path / "cleanup.json", {"confirmed": True, "projects": [], "time": time.time()})
        return  # Worker never passed Job initialization; no environment was started.
    projects = read_json(projects_file)
    from harbor_helper.execution.environments import owned_anonymous_volumes

    owned = set()
    for evidence in path.glob("harbor/*/*/helper-environment-*.json"):
        observation = read_json(evidence)
        if observation.get("project") in projects:
            owned.update(observation.get("owned_anonymous_volumes", []))
    for project in projects:
        label = f"label=com.docker.compose.project={project}"
        ids = run_command(["docker", "ps", "-aq", "--filter", label]).split()
        if ids:
            containers = json.loads(run_command(["docker", "inspect", *ids]))
            owned.update(
                owned_anonymous_volumes(
                    containers,
                    lambda reference: json.loads(run_command(["docker", "inspect", reference])),
                )
            )
            # Persist before removal, so retry/recovery can confirm anonymous mounts too.
            stamp = path / "owned-anonymous-volumes.json"
            owned.update(read_json(stamp) if stamp.exists() else [])
            write_json(stamp, sorted(owned))
            run_command(["docker", "rm", "-f", *ids])
        for kind in ("network", "volume"):
            ids = run_command(["docker", kind, "ls", "-q", "--filter", label]).split()
            if ids:
                run_command(["docker", kind, "rm", *ids])
            if run_command(["docker", kind, "ls", "-q", "--filter", label]):
                raise RuntimeError(f"Owned {kind} resources remain in project {project}")
        if run_command(["docker", "ps", "-aq", "--filter", label]):
            raise RuntimeError(f"Containers remain in owned project {project}")
    stamp = path / "owned-anonymous-volumes.json"
    owned.update(read_json(stamp) if stamp.exists() else [])
    for volume in sorted(owned):
        # Do not delete a mount now used by any other container/project.
        if run_command(["docker", "ps", "-aq", "--filter", f"volume={volume}"]):
            raise RuntimeError("Owned anonymous volume still attached; cleanup unconfirmed")
        if volume in run_command(["docker", "volume", "ls", "-q"]).split():
            run_command(["docker", "volume", "rm", volume])
        if volume in run_command(["docker", "volume", "ls", "-q"]).split():
            raise RuntimeError("Owned anonymous volume remains")
    write_json(
        path / "cleanup.json",
        {
            "confirmed": True,
            "projects": projects,
            "anonymous_volumes": sorted(owned),
            "time": time.time(),
        },
    )


def stop_group(row):
    pid = row["pid"]
    if not pid:
        return
    actual = process_birth(pid)
    if actual and actual != row["birth"]:
        raise RuntimeError("PID identity changed; refusing to kill unrelated process")
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    time.sleep(1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    # Zombie group members have stopped; non-zombie descendants must be gone.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        members = []
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
                if fields[0] != "Z" and int(fields[2]) == pid:
                    members.append(proc.name)
            except (OSError, IndexError, ValueError):
                continue
        if not members:
            return
        time.sleep(0.1)
    raise RuntimeError("Worker descendants still active; capacity retained")


def service_mode(store):
    return (store.root / "service.json").exists()


def audit_finished(store, row):
    """Publish evidence only with a complete audit; never reserve execution capacity."""
    secrets = [] if service_mode(store) else runtime_secrets()
    audit = None
    try:
        path = store.path(row["id"])
        manifest = read_json(path / "manifest.json")
        cfg = manifest["effective"]
        if service_mode(store):
            from harbor_helper.service.data import ServiceData

            key = ServiceData(store.root).run_key(row["id"], execution=False)
        else:
            from harbor_helper.security.local_auth import Auth

            auth = Auth(store.root)
            key = auth.audit_run_key(row["id"])
            if (
                cfg["agent"] == "opencode"
                and cfg["model"].get("credential_env")
                and auth.bound_record(row["id"]) is None
                and not legacy_secrets()
            ):
                raise RuntimeError("Legacy credential audit source unavailable")
        if key and key not in secrets:
            secrets.append(key)
        if cfg["agent"] == "opencode" and cfg["model"].get("credential_env") and not secrets:
            raise RuntimeError("Credential audit source unavailable")
        redact_files(path, secrets)
        scrub_file(store.root / "supervisor.log", secrets)
        audit = audit_run(store, row["id"], secrets)
        audit["audit_complete"] = True
        write_json(path / "credential-audit.json", audit)
        if not audit["clean"]:
            raise RuntimeError("Credential audit not clean; raw evidence withheld")
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired):
        # Third-party exceptions can carry unavailable secrets. Persist a fixed,
        # actionable message rather than potentially unsafe original exception text.
        store.update(
            row["id"],
            audit_status="incomplete",
            audit_reason="Evidence audit incomplete; affected logs and artifacts withheld",
        )
        path = store.path(row["id"])
        try:
            if audit is None:
                write_json(
                    path / "credential-audit.json",
                    {"clean": False, "audit_complete": False, "reason": "Audit source unavailable"},
                )
            (path / "report.json").unlink(missing_ok=True)
        except OSError:
            pass  # Database audit_status still withholds evidence; queue keeps advancing.
        return False
    store.update(row["id"], audit_status="clean", audit_reason=None)
    report(store, row["id"])
    return True


def finish(store, row, status, reason):
    secrets = [] if service_mode(store) else runtime_secrets()
    try:
        stop_group(row)
        cleanup(store.path(row["id"]))
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired):
        store.update(
            row["id"],
            status="cleanup_blocked",
            reason="Execution resource cleanup unconfirmed; capacity retained",
        )
        return
    # Capacity release depends solely on resource cleanup. Evidence may remain
    # unavailable independently and can be audited again after restoring its key.
    store.update(
        row["id"],
        status=status,
        reason=redact_value(reason, secrets),
        finished=time.time(),
    )
    audit_finished(store, store.get(row["id"]))


def tick(store, children):
    if service_mode(store):
        with store.control():
            _tick(store, children)
        return
    from harbor_helper.security.local_auth import runtime_context

    legacy = legacy_secrets()
    with store.control(), runtime_context(store.root, legacy_key=legacy[0] if legacy else None):
        _tick(store, children)


def _tick(store, children):
    team = load_team(store)
    for row in store.runs():
        if row["status"] in TERMINAL and row["audit_status"] in {"pending", "incomplete"}:
            path = store.path(row["id"])
            stamp = path / "credential-audit.json"
            if not (path / "archived.json").exists() and (
                not stamp.exists() or time.time() - stamp.stat().st_mtime >= 5
            ):
                audit_finished(store, row)
        if row["status"] not in ACTIVE:
            continue
        path = store.path(row["id"])
        outcome = path / "outcome.json"
        cfg = read_json(path / "manifest.json")["effective"]
        if row["cancel"]:
            finish(store, row, "cancelled", "Cancelled by member")
        elif row["started"] and time.time() - row["started"] >= cfg["wall_seconds"]:
            finish(store, row, "failed", "Wall-clock budget exceeded")
        elif outcome.exists():
            value = read_json(outcome)
            finish(store, row, value["status"], value["reason"])
        elif row["status"] == "cleanup_blocked" or not alive(row):
            finish(store, row, "failed", "Worker interrupted; use rerun (not resume)")
    for pid, child in list(children.items()):
        if child.poll() is not None:
            children.pop(pid)
    active = [r for r in store.runs() if r["status"] in ACTIVE]
    slots = sum(r["concurrency"] for r in active)
    for row in store.runs():
        if row["status"] != "queued":
            continue
        if row["cancel"]:
            store.update(
                row["id"], status="cancelled", finished=time.time(), reason="Cancelled while queued"
            )
            audit_finished(store, store.get(row["id"]))
            continue
        from harbor_helper.security.credentials import KEY_ENV, LEGACY_KEY_ENV

        path = store.path(row["id"])
        cfg = read_json(path / "manifest.json")["effective"]
        environment = safe_environment()
        environment.pop(KEY_ENV, None)
        environment.pop(LEGACY_KEY_ENV, None)
        if cfg["agent"] == "opencode" or service_mode(store):
            try:
                if service_mode(store):
                    from harbor_helper.service.data import ServiceData

                    key = ServiceData(store.root).run_key(row["id"], execution=True)
                else:
                    from harbor_helper.security.local_auth import Auth

                    _, key = Auth(store.root).worker_credentials(
                        row["id"], cfg["model"]["endpoint"]
                    )
                if key:
                    environment[KEY_ENV] = key
            except ValueError:
                store.update(
                    row["id"],
                    status="failed",
                    finished=time.time(),
                    reason="Execution authorization unavailable; worker not started",
                )
                audit_finished(store, store.get(row["id"]))
                continue
        if len(active) >= team["max_jobs"] or slots + row["concurrency"] > team["max_trials"]:
            continue
        path = store.path(row["id"])
        store.update(row["id"], status="starting", started=time.time())
        with (path / "worker.log").open("a") as log:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "harbor_helper.execution.worker",
                    "run",
                    str(store.root),
                    row["id"],
                ],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                env=environment,
                close_fds=True,
                start_new_session=True,
            )
        children[child.pid] = child
        store.update(row["id"], status="running", pid=child.pid, birth=process_birth(child.pid))
        active.append(row)
        slots += row["concurrency"]


def supervise(root):
    from harbor_helper.security import credentials

    # Native auto-loaded KEY_ENV is not an explicit historical source.
    store = Store(root)
    if service_mode(store):
        os.environ.pop(credentials.KEY_ENV, None)
        os.environ.pop(credentials.LEGACY_KEY_ENV, None)
        credentials.AUDIT_SECRETS = []
    legacy = os.environ.get(credentials.LEGACY_KEY_ENV)
    credentials.LEGACY_SECRETS = [legacy] if legacy else []
    secrets = runtime_secrets()
    sys.stdout = RedactedStream(sys.stdout, secrets)
    sys.stderr = RedactedStream(sys.stderr, secrets)
    with (store.root / "supervisor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        write_json(
            store.root / "scheduler.json", {"pid": os.getpid(), "birth": process_birth(os.getpid())}
        )
        children = {}
        # Keep cancellation/recovery/wall checks responsive during Hub downloads.
        preparation_pool = ThreadPoolExecutor(max_workers=1) if service_mode(store) else None
        preparation = None
        maintained = time.monotonic()
        while True:
            try:
                if preparation_pool and (preparation is None or preparation.done()):
                    from harbor_helper.service.lifecycle import prepare_one

                    if preparation is not None:
                        completed, preparation = preparation, None
                        completed.result()
                    preparation = preparation_pool.submit(prepare_one, store)
                tick(store, children)
                if preparation_pool and time.monotonic() - maintained >= 30:
                    from harbor_helper.service.lifecycle import maintenance

                    with store.control():
                        maintenance(store)
                    maintained = time.monotonic()
            except Exception as e:  # noqa: BLE001 - persist/diagnose third-party Harbor errors
                if service_mode(store):
                    print(f"Scheduler error: {type(e).__name__}", flush=True)
                else:
                    print(f"Scheduler error: {type(e).__name__}: {e}", flush=True)
            time.sleep(0.5)


def redact_files(path, secrets):
    scrub_run(path, secrets)


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
    from harbor_helper.execution.runs import image_identity

    if (
        manifest.get("execution_mode") != "harbor-native"
        and image_identity(manifest["image_alias"]) != manifest["image_id"]
    ):
        raise RuntimeError("Fixed image alias changed; submit/rerun to restore it")
    if importlib.metadata.version("harbor") != HARBOR_VERSION:
        raise RuntimeError("Worker loaded the wrong Harbor version")
    model = manifest["effective"]["model"]
    if manifest["effective"]["agent"] == "opencode" or service_mode(store):
        if service_mode(store):
            from harbor_helper.service.data import ServiceData

            key = ServiceData(store.root).run_key(run_id, execution=True)
        else:
            from harbor_helper.security.local_auth import Auth

            _, key = Auth(store.root).worker_credentials(run_id, model["endpoint"])
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
        "status": "succeeded" if value["complete"] else "failed",
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
            if row["pid"] == os.getpid() and row["status"] == "running":
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
            if service_mode(store):
                # Do not persist provider payloads from exception strings. Complete
                # details remain available only in separately audited task evidence.
                print(f"Harbor startup/execution failed: {type(e).__name__}", flush=True)
                outcome = {"status": "failed", "reason": "Worker execution failed"}
            else:
                print(f"Harbor startup/execution failed: {type(e).__name__}: {e}", flush=True)
                outcome = {"status": "failed", "reason": f"{type(e).__name__}: {e}"}
        sys.stdout.finish()
        sys.stderr.finish()
        redact_files(path, secrets)
        outcome["reason"] = redact_value(outcome["reason"], secrets)
        write_json(path / "outcome.json", outcome)


def main():
    if sys.argv[1] == "supervise":
        supervise(sys.argv[2])
    else:
        run(sys.argv[2], sys.argv[3])


if __name__ == "__main__":
    main()
