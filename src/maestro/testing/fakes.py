"""Fakes for the four boundaries (C4). Used by tests and local demonstrations only."""

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from maestro.boundaries.dataset_source import SourceTask, SourceVersion
from maestro.boundaries.environment import CleanupReport, PreparationSpec, PreparedArtifact
from maestro.boundaries.executor import (
    AttemptOutcome,
    CancelToken,
    ExecutionReport,
    ExecutionSink,
    Leftover,
    RunSpec,
)
from maestro.core.digests import digest_json


class FakeDatasetSource:
    kind = "fake"

    def __init__(self):
        self.versions: dict[tuple[str, str, str], SourceVersion] = {}

    def add(self, namespace: str, name: str, ref: str, task_keys: list[str]) -> SourceVersion:
        tasks = tuple(
            SourceTask(
                task_key=key,
                content_digest=digest_json({"dataset": f"{namespace}/{name}", "task": key}),
                definition={"instruction": f"Solve {key}"},
            )
            for key in task_keys
        )
        version = SourceVersion(
            namespace=namespace,
            name=name,
            upstream_ref=ref,
            ref_kind="tag",
            resolved_digest=digest_json([t.content_digest for t in tasks]),
            tasks=tasks,
        )
        self.versions[(namespace, name, ref)] = version
        return version

    def search(self, query: str) -> list[dict]:
        return [
            {"namespace": ns, "name": n, "ref": r}
            for (ns, n, r) in self.versions
            if query in f"{ns}/{n}"
        ]

    def resolve(self, namespace: str, name: str, ref: str) -> SourceVersion:
        return self.versions[(namespace, name, ref)]

    def fetch(self, version: SourceVersion, destination: Path) -> str:
        destination.mkdir(parents=True, exist_ok=True)
        for task in version.tasks:
            (destination / f"{task.task_key}.json").write_text(digest_json(task.definition))
        return version.resolved_digest


def scored(score: float) -> AttemptOutcome:
    return AttemptOutcome(raw_score=score, reward_valid=True, verifier_status="ok")


def failed(cause: str, *, retry: bool = False, exception: str = "FakeError") -> AttemptOutcome:
    return AttemptOutcome(
        raw_score=None,
        reward_valid=False,
        failure_cause=cause,
        exception_type=exception,
        message=f"fake {cause}",
        retry_recommended=retry,
    )


@dataclass
class FakeExecutor:
    """Scripted per task key: a list of outcomes, one per attempt.

    A ``"hang"`` entry blocks until cancellation. Retries happen when an outcome
    recommends it and attempts remain, mirroring Job-internal retries (D-020).
    Cleanup and reconciliation calls are recorded instead of touching Docker.
    """

    script: dict[str, list] = field(default_factory=dict)
    default: AttemptOutcome = field(default_factory=lambda: scored(1.0))
    max_attempts: int = 3
    step_delay: float = 0.0
    executor_id: str = "fake"
    started: asyncio.Event = field(default_factory=asyncio.Event)
    on_trial: Callable | None = None
    cleaned: list = field(default_factory=list)
    reconciled: list = field(default_factory=list)
    release: bool = True

    async def execute(self, spec: RunSpec, sink: ExecutionSink, cancel: CancelToken):
        semaphore = asyncio.Semaphore(spec.concurrency)
        await sink.runner_started({"pid": 0, "runner_id": self.executor_id})

        async def run_trial(trial):
            async with semaphore:
                plan = list(self.script.get(trial.task_key, [self.default]))
                for attempt in range(1, self.max_attempts + 1):
                    if cancel.cancelled:
                        return
                    outcome = plan[min(attempt - 1, len(plan) - 1)]
                    await sink.attempt_started(trial.trial_id, attempt)
                    self.started.set()
                    for step in ("environment", "agent", "verifying"):
                        await sink.phase_changed(trial.trial_id, attempt, step)
                        if outcome == "hang" and step == "agent":
                            await cancel.wait()
                            return
                        if self.step_delay:
                            await asyncio.sleep(self.step_delay)
                        if cancel.cancelled:
                            return
                    await sink.log(
                        trial.trial_id,
                        attempt,
                        "agent/fake.txt",
                        f"attempt {attempt} of {trial.task_key}\n",
                    )
                    await sink.artifact(
                        trial.trial_id,
                        attempt,
                        "output",
                        "result.txt",
                        f"{trial.task_key}:{outcome.raw_score}".encode(),
                    )
                    retry = outcome.retry_recommended and attempt < self.max_attempts
                    await sink.attempt_finished(trial.trial_id, attempt, outcome, final=not retry)
                    if not retry:
                        return

        await asyncio.gather(*(run_trial(trial) for trial in spec.trials))
        report = await self.cleanup(spec.labels)
        return ExecutionReport(cleanup_complete=report.released)

    async def cleanup(self, labels: dict[str, str]) -> CleanupReport:
        self.cleaned.append(labels)
        return CleanupReport(released=self.release)

    async def reconcile(self, leftover: Leftover) -> CleanupReport:
        self.reconciled.append(leftover)
        return await self.cleanup(leftover.labels)


class FakeEnvironment:
    location_id = "fake-host"

    def __init__(self):
        self.ready: set[str] = set()
        self.cleaned: list[dict] = []
        self.fail_prepare: set[str] = set()

    async def prepare(self, spec: PreparationSpec) -> PreparedArtifact:
        if spec.spec_digest in self.fail_prepare:
            raise RuntimeError("fake preparation failure")
        self.ready.add(spec.spec_digest)
        return PreparedArtifact(spec.spec_digest, self.location_id, spec.spec_digest)

    async def is_ready(self, spec_digest: str) -> bool:
        return spec_digest in self.ready

    async def evict(self, spec_digest: str) -> None:
        self.ready.discard(spec_digest)

    async def cleanup(self, labels: dict[str, str]) -> CleanupReport:
        self.cleaned.append(labels)
        return CleanupReport(released=True)


class MemoryArtifactStore:
    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.fail_put = False

    def put(self, key: str, data: bytes) -> tuple[str, int]:
        if self.fail_put:
            raise OSError("fake storage failure")
        self.files[key] = data
        return "sha256:" + hashlib.sha256(data).hexdigest(), len(data)

    def get(self, key: str) -> bytes:
        return self.files[key]

    def delete(self, key: str) -> None:
        self.files.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self.files
