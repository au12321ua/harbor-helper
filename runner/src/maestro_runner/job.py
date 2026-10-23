"""Execute one platform run as one Harbor Job (D-020) and report it over the protocol.

Harbor's trial hooks give real-time phases; per-attempt evidence is archived in the
END hook because Harbor deletes a failed attempt's directory before an in-job retry
(M1, V-12). Live logs come from the trial directories Docker mounts on the host.
"""

import asyncio
import hashlib
import os
import shutil
import traceback
from collections import defaultdict
from importlib.metadata import version
from pathlib import Path

from maestro_runner import protocol
from maestro_runner.protocol import emit

# Harbor hook -> platform step. Collection has no hook: it is the span between
# agent end and verification start (M1).
STEPS = {
    "environment-start": "environment",
    "agent-start": "agent",
    "agent-end": "collecting",
    "verification-start": "verifying",
}
LOG_DIRS = ("agent", "verifier")
LOG_SUFFIXES = (".txt", ".log")
MAX_FILES = 500
MAX_FILE_BYTES = 64 * 1024 * 1024
MESSAGE_LIMIT = 4000


class Rejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _labels_override(path: Path, labels: dict[str, str], label_build: bool, prepared: bool) -> Path:
    """Platform labels on the main service, its network and (when Harbor builds it) its image.

    Cleanup after a killed Runner finds every resource by these labels (05 section 7).
    Prepared images are never pulled: a missing one must fail, not reach a registry.
    """
    body = "".join(f"      {key}: {value}\n" for key, value in sorted(labels.items()))
    text = "services:\n  main:\n    init: true\n"
    if prepared:
        text += "    pull_policy: never\n"
    text += "    labels:\n" + body
    if label_build:
        text += "    build:\n      labels:\n" + body.replace("      ", "        ")
    text += "networks:\n  default:\n    labels:\n" + body
    path.write_text(text)
    return path


def _builds_image(task_dir: Path) -> bool:
    from harbor.models.task.config import TaskConfig as TaskFile

    config = TaskFile.model_validate_toml((task_dir / "task.toml").read_text())
    return not config.environment.docker_image


def _with_image(task_dir: Path, copy: Path, image: str) -> Path:
    """A private copy of the task whose environment uses the platform-prepared image,
    so Harbor neither builds nor pulls it (M1 TECH-03)."""
    from harbor.models.task.config import TaskConfig as TaskFile

    shutil.copytree(task_dir, copy, symlinks=True)
    config = TaskFile.model_validate_toml((copy / "task.toml").read_text())
    config.environment.docker_image = image
    (copy / "task.toml").write_text(config.model_dump_toml())
    return copy


def _manifest(root: Path) -> list[dict]:
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        if len(files) >= MAX_FILES or size > MAX_FILE_BYTES:
            files.append({"path": relative, "size": size, "skipped": True})
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        files.append({"path": relative, "size": size, "sha256": digest.hexdigest()})
    return files


def _timing(value) -> dict | None:
    if value is None:
        return None
    return {
        "started_at": value.started_at.isoformat() if value.started_at else None,
        "finished_at": value.finished_at.isoformat() if value.finished_at else None,
    }


class Execution:
    def __init__(self, spec: dict):
        self.spec = spec
        self.out = Path(spec["output_dir"])
        self.jobs_dir = self.out / "jobs"
        self.attempts_dir = self.out / "attempts"
        self.retry = spec["retry"]
        self.cancelling = False
        # Harbor trial name -> platform trial id; retries keep the trial name (V-12).
        self.bound: dict[str, str] = {}
        self.unbound: dict[str, list[str]] = {}
        self.task_by_path: dict[str, str] = {}
        self.attempt: dict[str, int] = defaultdict(int)
        self.live: set[str] = set()
        self.offsets: dict[Path, int] = {}
        self.log_bytes: dict[tuple[str, int], int] = defaultdict(int)
        self.finished = 0

    # --- configuration -----------------------------------------------------------

    def _config(self):
        from harbor.models.job.config import JobConfig, RetryConfig
        from harbor.models.trial.config import AgentConfig, EnvironmentConfig, TaskConfig

        tasks = self.spec["tasks"]
        counts = {len(task["trial_ids"]) for task in tasks}
        if len(counts) != 1:
            raise Rejected("RUNNER_INPUT_INVALID", "every task needs the same trial count")
        task_dirs = []
        prepared = 0
        for index, task in enumerate(tasks):
            path = Path(task["path"]).resolve()
            if not (path / "task.toml").is_file():
                raise Rejected("TASK_MATERIAL_MISSING", f"no task.toml for {task['task_key']}")
            if task.get("docker_image"):
                path = _with_image(path, self.out / "tasks" / str(index), task["docker_image"])
                prepared += 1
            self.task_by_path[str(path)] = task["task_key"]
            self.unbound[task["task_key"]] = list(task["trial_ids"])
            task_dirs.append(path)
        label_build = all(_builds_image(path) for path in task_dirs)
        override = _labels_override(
            self.out / "labels.compose.yaml",
            self.spec["labels"],
            label_build,
            prepared == len(tasks),
        )
        agent = self.spec["agent"]
        if not agent.get("name") and not agent.get("import_path"):
            # Harbor's default agent is oracle; never fall back to it implicitly (15 section 6).
            raise Rejected("RUNNER_INPUT_INVALID", "agent must be explicit")
        return JobConfig(
            job_name="job",
            jobs_dir=self.jobs_dir,
            n_attempts=counts.pop(),
            n_concurrent_trials=self.spec["n_concurrent_trials"],
            quiet=True,
            retry=RetryConfig(
                max_retries=self.retry["max_retries"],
                include_exceptions=None,
                exclude_exceptions=set(self.retry["exclude_exceptions"]),
                min_wait_sec=self.retry["min_wait_sec"],
                wait_multiplier=self.retry["wait_multiplier"],
                max_wait_sec=self.retry["max_wait_sec"],
            ),
            environment=EnvironmentConfig(
                type="docker", delete=True, extra_docker_compose=[override]
            ),
            agents=[AgentConfig(**agent)],
            tasks=[TaskConfig(path=path) for path in task_dirs],
        )

    def _will_retry(self, exception_type: str | None, attempt: int) -> bool:
        """Mirror of Harbor 0.24.0 TrialQueue retry rules for the settings we pass."""
        if exception_type is None or self.cancelling or exception_type == "CancelledError":
            return False
        if exception_type in self.retry["exclude_exceptions"]:
            return False
        return attempt <= self.retry["max_retries"]

    # --- hooks ---------------------------------------------------------------------

    def _trial_id(self, event) -> str:
        name = event.trial_name
        if name not in self.bound:
            task_key = self.task_by_path[str(Path(event.config.task.path).resolve())]
            self.bound[name] = self.unbound[task_key].pop(0)
        return self.bound[name]

    async def on_event(self, event) -> None:
        try:
            self._handle(event)
        except Exception:  # noqa: BLE001 - a hook failure must not break Harbor's trial
            traceback.print_exc()

    def _handle(self, event) -> None:
        kind = event.event.value
        name = event.trial_name
        trial_id = self._trial_id(event)
        if kind == "start":
            self.attempt[name] += 1
            self.live.add(name)
            emit(
                "attempt_started",
                trial_id=trial_id,
                attempt=self.attempt[name],
                harbor_trial_name=name,
                harbor_trial_id=str(event.trial_id),
            )
        elif kind in STEPS:
            emit(
                "phase_changed",
                trial_id=trial_id,
                attempt=self.attempt[name],
                step=STEPS[kind],
                harbor_at=event.timestamp.isoformat(),
            )
        elif kind == "end":
            self._finish(event, trial_id)

    def _finish(self, event, trial_id: str) -> None:
        name = event.trial_name
        attempt = self.attempt[name]
        self.tail(only=name)
        self.live.discard(name)
        result = event.result
        trial_dir = self.jobs_dir / "job" / name
        archive = self.attempts_dir / trial_id / str(attempt)
        if trial_dir.is_dir():
            shutil.copytree(trial_dir, archive, dirs_exist_ok=True, symlinks=True)
        exc = result.exception_info
        exception_type = exc.exception_type if exc else None
        rewards = result.verifier_result.rewards if result.verifier_result else None
        self.finished += 1
        emit(
            "attempt_finished",
            trial_id=trial_id,
            attempt=attempt,
            exception_type=exception_type,
            exception_message=(exc.exception_message[:MESSAGE_LIMIT] if exc else None),
            rewards=rewards,
            verifier_ran=result.verifier is not None,
            will_retry=self._will_retry(exception_type, attempt),
            archive=archive.relative_to(self.out).as_posix() if archive.is_dir() else None,
            files=_manifest(archive) if archive.is_dir() else [],
            timing={
                "environment_setup": _timing(result.environment_setup),
                "agent_setup": _timing(result.agent_setup),
                "agent_execution": _timing(result.agent_execution),
                "verifier": _timing(result.verifier),
            },
        )

    # --- live logs -------------------------------------------------------------------

    def tail(self, only: str | None = None) -> None:
        """Forward new bytes of trial log files; a retry recreates files, so offsets reset."""
        cap = self.spec["log_cap_bytes"]
        for name in sorted(self.live if only is None else {only}):
            trial_id = self.bound.get(name)
            if trial_id is None:
                continue
            attempt = self.attempt[name]
            root = self.jobs_dir / "job" / name
            for directory in LOG_DIRS:
                for path in sorted((root / directory).glob("**/*")):
                    if path.suffix not in LOG_SUFFIXES or not path.is_file():
                        continue
                    start = self.offsets.get(path, 0)
                    size = path.stat().st_size
                    if size < start:
                        start = 0
                    if size == start:
                        continue
                    self.offsets[path] = size
                    used = self.log_bytes[(trial_id, attempt)]
                    if used >= cap:
                        continue
                    with path.open("rb") as handle:
                        handle.seek(start)
                        data = handle.read(min(size - start, cap - used))
                    self.log_bytes[(trial_id, attempt)] += len(data)
                    emit(
                        "log",
                        trial_id=trial_id,
                        attempt=attempt,
                        source=path.relative_to(root).as_posix(),
                        text=data.decode("utf-8", "replace"),
                        truncated=self.log_bytes[(trial_id, attempt)] >= cap,
                    )

    async def _tail_forever(self) -> None:
        while True:
            await asyncio.sleep(self.spec["tail_interval_sec"])
            try:
                self.tail()
            except OSError:
                traceback.print_exc()

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(self.spec["heartbeat_sec"])
            emit("heartbeat", attempts_finished=self.finished, live=len(self.live))

    # --- run -------------------------------------------------------------------------

    async def run(self) -> str:
        from harbor.job import Job
        from harbor.trial.hooks import TrialEvent

        self.attempts_dir.mkdir(parents=True, exist_ok=True)
        config = self._config()
        job = await Job.create(config)
        for trial_event in TrialEvent:
            job.add_hook(trial_event, self.on_event)
        emit(
            "started",
            harbor_version=version("harbor"),
            runner_version=version("maestro-runner"),
            n_trials=len(job),
            pid=os.getpid(),
        )
        background = [
            asyncio.create_task(self._tail_forever()),
            asyncio.create_task(self._heartbeat()),
        ]
        try:
            await job.run()
            return "completed"
        except asyncio.CancelledError:
            return "cancelled"
        finally:
            for task in background:
                task.cancel()


def runner_version() -> str:
    return version("maestro-runner")


def check_spec(spec: dict) -> None:
    if spec.get("protocol_version") != protocol.PROTOCOL_VERSION:
        raise Rejected("PROTOCOL_VERSION_UNSUPPORTED", "unsupported protocol version")
    if spec.get("command") != "execute":
        raise Rejected("RUNNER_INPUT_INVALID", "unknown command")
    required = (
        "run_id",
        "output_dir",
        "agent",
        "tasks",
        "labels",
        "retry",
        "n_concurrent_trials",
        "log_cap_bytes",
        "heartbeat_sec",
        "tail_interval_sec",
    )
    missing = [key for key in required if key not in spec]
    if missing:
        raise Rejected("RUNNER_INPUT_INVALID", f"missing fields: {missing}")
