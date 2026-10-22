"""Experiment executor boundary.

Per D-020 one call executes a whole run (Harbor: one Job). The executor reports
per-trial attempts, phases, results and artifacts through ``ExecutionSink``;
the platform owns trial state, scoring decisions, retries policy and leases.
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class TrialSpec:
    trial_id: str
    task_key: str
    task_definition: dict
    repetition_index: int


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    trials: tuple[TrialSpec, ...]
    concurrency: int
    effective_config: dict
    deadline_at: str


@dataclass(frozen=True)
class AttemptOutcome:
    """Executor-native outcome mapped to platform policy fields (06 section 3)."""

    raw_score: float | None
    reward_valid: bool
    failure_cause: str | None = None
    exception_type: str | None = None
    message: str | None = None
    retry_recommended: bool = False
    grade_requested: bool = True
    verifier_status: str | None = None
    metrics: dict = field(default_factory=dict)
    usage: dict | None = None
    actual_model: dict | None = None


class ExecutionSink(Protocol):
    async def attempt_started(self, trial_id: str, attempt_index: int) -> None: ...

    async def phase_changed(self, trial_id: str, attempt_index: int, phase: str) -> None: ...

    async def log(self, trial_id: str, attempt_index: int, stream: str, text: str) -> None: ...

    async def artifact(
        self, trial_id: str, attempt_index: int, kind: str, relative_path: str, data: bytes
    ) -> None: ...

    async def attempt_finished(
        self, trial_id: str, attempt_index: int, outcome: AttemptOutcome, final: bool
    ) -> None:
        """``final=False`` means the executor will retry this trial."""
        ...


class CancelToken(Protocol):
    @property
    def cancelled(self) -> bool: ...

    async def wait(self) -> None: ...


@dataclass
class ExecutionReport:
    cleanup_complete: bool
    detail: dict = field(default_factory=dict)


class Executor(Protocol):
    executor_id: str

    async def execute(
        self, spec: RunSpec, sink: ExecutionSink, cancel: CancelToken
    ) -> ExecutionReport: ...
