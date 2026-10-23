"""Execute one platform run as one Harbor Job (D-020) and report it over the protocol.

Harbor's trial hooks give real-time phases; per-attempt evidence is archived in the
END hook because Harbor deletes a failed attempt's directory before an in-job retry
(M1, V-12). Live logs come from the trial directories Docker mounts on the host.

Those mounted directories are writable from inside the container (C-07 / U-16), so
everything under them is untrusted: links are never followed (a link could point at any
host file), only regular files are read, and the size limits apply while copying.
"""

import asyncio
import hashlib
import os
import shutil
import stat
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
# The per-attempt file count, per-file size and total size limits come with every run
# (``artifact_limits`` in the request, from the service's configuration).
# Skipped entries are listed so the evidence gap is visible, but a runaway task cannot
# grow the manifest (one protocol line) without bound; the rest is only counted.
MAX_LISTED_SKIPS = 200
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


def _entries(top: Path) -> list[tuple[Path, os.stat_result]]:
    """Regular files and links below ``top`` in path order, with their own (lstat) data.

    Directories are entered only when they really are directories: a link to one is
    reported, never followed. Devices, pipes and sockets are left out.
    """
    if top.is_symlink() or not top.is_dir():
        return []
    found = []
    pending = [top]
    while pending:
        try:
            with os.scandir(pending.pop()) as scan:
                entries = list(scan)
        except OSError:
            continue
        for entry in entries:
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISDIR(info.st_mode):
                pending.append(Path(entry.path))
            elif stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                found.append((Path(entry.path), info))
    return sorted(found, key=lambda item: item[0])


def _open_below(path: Path, root: Path):
    """Open a regular file for reading, or None when it is not one that lives under ``root``.

    The container can swap names between listing and opening. O_NOFOLLOW refuses a link as
    the last component, O_NONBLOCK keeps a planted pipe from blocking the Runner, and the
    descriptor's real path catches a link in any directory above the file.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return None
    handle = os.fdopen(fd, "rb")  # owns the descriptor from here on
    try:
        regular = stat.S_ISREG(os.fstat(fd).st_mode)
        inside = Path(os.readlink(f"/proc/self/fd/{fd}")).is_relative_to(root.resolve())
    except OSError:
        regular = inside = False
    if not (regular and inside):
        handle.close()
        return None
    return handle


def _copy(handle, target: Path, limit: int) -> tuple[str, int] | None:
    """Copy at most ``limit`` bytes and return (sha256, size); None, with nothing kept,
    when the file turns out to be longer."""
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    within = True
    with target.open("wb") as sink:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            size += len(chunk)
            if size > limit:
                within = False
                break
            digest.update(chunk)
            sink.write(chunk)
    if not within:
        target.unlink()
        return None
    return digest.hexdigest(), size


def _archive(source: Path, target: Path, limits: dict) -> tuple[list[dict], int]:
    """Copy a trial directory's regular files and describe them: the manifest entries and
    how many skipped entries were left off the list. ``limits`` holds ``max_files``,
    ``max_file_bytes`` and ``max_total_bytes``.

    Nothing is followed or copied as a link, and the limits apply on the way, so a runaway
    task cannot fill the disk a second time. Skipped files stay in the manifest, with a
    reason, so a missing file is never silent.
    """
    target.mkdir(parents=True, exist_ok=True)
    files: list[dict] = []
    skipped = copied = total = 0

    def skip(relative: str, size: int, reason: str) -> None:
        nonlocal skipped
        skipped += 1
        if skipped <= MAX_LISTED_SKIPS:
            files.append({"path": relative, "size": size, "skipped": True, "reason": reason})

    for path, info in _entries(source):
        relative = path.relative_to(source).as_posix()
        if stat.S_ISLNK(info.st_mode):
            skip(relative, 0, "SYMLINK")
        elif copied >= limits["max_files"]:
            skip(relative, info.st_size, "TOO_MANY_FILES")
        elif info.st_size > limits["max_file_bytes"]:
            skip(relative, info.st_size, "TOO_LARGE")
        elif total + info.st_size > limits["max_total_bytes"]:
            skip(relative, info.st_size, "TOTAL_LIMIT")
        elif (handle := _open_below(path, source)) is None:
            skip(relative, info.st_size, "UNREADABLE")
        else:
            try:
                with handle:
                    done = _copy(
                        handle,
                        target / relative,
                        min(limits["max_file_bytes"], limits["max_total_bytes"] - total),
                    )
            except OSError:
                (target / relative).unlink(missing_ok=True)
                skip(relative, info.st_size, "COPY_FAILED")
                continue
            if done is None:
                skip(relative, info.st_size, "TOO_LARGE")
                continue
            digest, size = done
            copied += 1
            total += size
            files.append({"path": relative, "size": size, "sha256": digest})
    return files, max(0, skipped - MAX_LISTED_SKIPS)


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
        self.limits = spec["artifact_limits"]
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
        archived = trial_dir.is_dir()
        files, unlisted = _archive(trial_dir, archive, self.limits) if archived else ([], 0)
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
            archive=archive.relative_to(self.out).as_posix() if archived else None,
            files=files,
            skipped_unlisted=unlisted,
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
                for path, info in _entries(root / directory):
                    if path.suffix not in LOG_SUFFIXES or stat.S_ISLNK(info.st_mode):
                        continue
                    start = self.offsets.get(path, 0)
                    size = info.st_size
                    if size < start:
                        start = 0
                    if size == start:
                        continue
                    self.offsets[path] = size
                    used = self.log_bytes[(trial_id, attempt)]
                    if used >= cap:
                        continue
                    handle = _open_below(path, root)
                    if handle is None:
                        continue
                    with handle:
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
        "artifact_limits",
    )
    missing = [key for key in required if key not in spec]
    if missing:
        raise Rejected("RUNNER_INPUT_INVALID", f"missing fields: {missing}")
    limits = spec["artifact_limits"]
    names = ("max_files", "max_file_bytes", "max_total_bytes")
    if not isinstance(limits, dict) or set(limits) != set(names):
        raise Rejected("RUNNER_INPUT_INVALID", f"artifact_limits needs exactly {list(names)}")
    for name in names:
        value = limits[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise Rejected(
                "RUNNER_INPUT_INVALID", f"artifact_limits.{name} must be a positive integer"
            )
    if limits["max_file_bytes"] > limits["max_total_bytes"]:
        raise Rejected(
            "RUNNER_INPUT_INVALID", "a single file cannot be allowed more than the total"
        )
