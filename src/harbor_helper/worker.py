import asyncio
import fcntl
import importlib.metadata
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from harbor_helper.config import HARBOR_VERSION, load_team
from harbor_helper.reports import report
from harbor_helper.runs import safe_environment
from harbor_helper.sources import verify_inputs
from harbor_helper.storage import ACTIVE, Store, read_json, write_json


def process_birth(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return fields[19]
    except (OSError, IndexError):
        return None


def alive(row):
    return bool(row["pid"] and row["birth"] and process_birth(row["pid"]) == row["birth"])


def run_command(argv):
    r = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise RuntimeError(f"Command failed ({argv[:3]}): {r.stderr[-800:]}")
    return r.stdout.strip()


def cleanup(path):
    """Only exact native Compose projects recorded before starting any Trial."""
    projects_file = path / "projects.json"
    if not projects_file.exists():
        return  # Worker never passed Job initialization; no environment was started.
    projects = read_json(projects_file)
    for project in projects:
        label = f"label=com.docker.compose.project={project}"
        ids = run_command(["docker", "ps", "-aq", "--filter", label]).split()
        if ids:
            run_command(["docker", "rm", "-f", *ids])
        for kind in ("network", "volume"):
            ids = run_command(["docker", kind, "ls", "-q", "--filter", label]).split()
            if ids:
                run_command(["docker", kind, "rm", *ids])
        if run_command(["docker", "ps", "-aq", "--filter", label]):
            raise RuntimeError(f"Containers remain in owned project {project}")
    write_json(
        path / "cleanup.json", {"confirmed": True, "projects": projects, "time": time.time()}
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


def finish(store, row, status, reason):
    try:
        stop_group(row)
        cleanup(store.path(row["id"]))
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        store.update(row["id"], status="cleanup_blocked", reason=str(e))
        return
    store.update(row["id"], status=status, reason=reason, finished=time.time())
    report(store, row["id"])


def tick(store, children):
    team = load_team(store)
    for row in store.runs():
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
            continue
        if len(active) >= team["max_jobs"] or slots + row["concurrency"] > team["max_trials"]:
            continue
        path = store.path(row["id"])
        store.update(row["id"], status="starting", started=time.time())
        with (path / "worker.log").open("a") as log:
            child = subprocess.Popen(
                [sys.executable, "-m", "harbor_helper.worker", "run", str(store.root), row["id"]],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                env=safe_environment(),
                close_fds=True,
                start_new_session=True,
            )
        children[child.pid] = child
        store.update(row["id"], status="running", pid=child.pid, birth=process_birth(child.pid))
        active.append(row)
        slots += row["concurrency"]


def supervise(root):
    store = Store(root)
    with (store.root / "supervisor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        write_json(
            store.root / "scheduler.json", {"pid": os.getpid(), "birth": process_birth(os.getpid())}
        )
        children = {}
        while True:
            try:
                tick(store, children)
            except Exception as e:  # noqa: BLE001 - persist/diagnose third-party Harbor errors
                print(f"Scheduler error: {type(e).__name__}: {e}", flush=True)
            time.sleep(0.5)


def redact_files(path, secrets):
    for file in path.rglob("*"):
        if not file.is_file() or file.stat().st_size > 20_000_000:
            continue
        try:
            content = file.read_text()
        except (UnicodeError, OSError):
            continue
        updated = content
        for secret in secrets:
            updated = updated.replace(secret, "[REDACTED]")
        if content != updated:
            file.write_text(updated)


class RedactedStream:
    def __init__(self, stream, secrets):
        self.stream, self.secrets = stream, secrets

    def write(self, value):
        for secret in self.secrets:
            value = value.replace(secret, "[REDACTED]")
        return self.stream.write(value)

    def flush(self):
        self.stream.flush()

    def __getattr__(self, key):
        return getattr(self.stream, key)


async def execute(store, run_id):
    from harbor.environments.docker.docker import _sanitize_docker_compose_project_name
    from harbor.job import Job
    from harbor.models.job.config import JobConfig
    from harbor.models.task.task import Task
    from harbor.trial.trial import Trial

    path = store.path(run_id)
    manifest = read_json(path / "manifest.json")
    verify_inputs(path, manifest)
    from harbor_helper.runs import image_identity

    if image_identity(manifest["image_alias"]) != manifest["image_id"]:
        raise RuntimeError("Fixed image alias changed; submit/rerun to restore it")
    if importlib.metadata.version("harbor") != HARBOR_VERSION:
        raise RuntimeError("Worker loaded the wrong Harbor version")
    model = manifest["effective"]["model"]
    if (
        manifest["effective"]["agent"] == "opencode"
        and model.get("credential_env")
        and not os.environ.get("VLLM_API_KEY")
    ):
        raise RuntimeError("Model credential missing: set VLLM_API_KEY before starting scheduler")
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
        secrets = [v for k, v in os.environ.items() if k == "VLLM_API_KEY" and v]
        sys.stdout = RedactedStream(sys.stdout, secrets)
        sys.stderr = RedactedStream(sys.stderr, secrets)
        try:
            outcome = asyncio.run(execute(store, run_id))
        except Exception as e:  # noqa: BLE001 - persist/diagnose third-party Harbor errors
            print(f"Harbor startup/execution failed: {type(e).__name__}: {e}", flush=True)
            outcome = {"status": "failed", "reason": f"{type(e).__name__}: {e}"}
        redact_files(path, secrets)
        for secret in secrets:
            if outcome["reason"]:
                outcome["reason"] = outcome["reason"].replace(secret, "[REDACTED]")
        write_json(path / "outcome.json", outcome)


if __name__ == "__main__":
    if sys.argv[1] == "supervise":
        supervise(sys.argv[2])
    else:
        run(sys.argv[2], sys.argv[3])
