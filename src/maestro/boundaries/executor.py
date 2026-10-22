"""Experiment executor boundary.

Per D-020 one call executes a whole run (Harbor: one Job). The executor reports
per-trial attempts, steps, results and artifacts through ``ExecutionSink``;
the platform owns trial state, scoring decisions, retry policy and leases.
"""

from dataclasses import dataclass, field
from typing import Protocol

from maestro.boundaries.environment import CleanupReport

# Steps an attempt reports, and the trial phase each one implies (05 section 4).
# Collection has no upstream event in Harbor 0.24.0: it spans agent end to verification.
STEPS = {
    "environment": "preparing",
    "agent": "executing",
    "collecting": "executing",
    "verifying": "verifying",
}


@dataclass(frozen=True)
class TrialSpec:
    trial_id: str
    task_key: str
    task_definition: dict
    repetition_index: int
    content_digest: str = ""


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    trials: tuple[TrialSpec, ...]
    concurrency: int
    effective_config: dict
    deadline_at: str
    labels: dict[str, str] = field(default_factory=dict)


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
    async def runner_started(self, identity: dict) -> None:
        """Persist the process identity before anything else, for restart reconciliation."""
        ...

    async def heartbeat(self) -> None: ...

    async def attempt_started(
        self, trial_id: str, attempt_index: int, detail: dict | None = None
    ) -> None: ...

    async def phase_changed(self, trial_id: str, attempt_index: int, step: str) -> None:
        """``step`` is a key of ``STEPS``."""
        ...

    async def log(self, trial_id: str, attempt_index: int, source: str, text: str) -> None: ...

    async def artifact(
        self, trial_id: str, attempt_index: int, kind: str, relative_path: str, data: bytes
    ) -> None: ...

    async def run_artifact(self, kind: str, relative_path: str, data: bytes) -> None: ...

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
    failure_code: str | None = None
    """Why trials still without a result ended, e.g. RUNNER_PROTOCOL_ERROR."""
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Leftover:
    """A run an earlier service process left claimed (05 section 8)."""

    run_id: str
    labels: dict[str, str]
    runner: dict | None


class Executor(Protocol):
    executor_id: str

    async def execute(
        self, spec: RunSpec, sink: ExecutionSink, cancel: CancelToken
    ) -> ExecutionReport: ...

    async def cleanup(self, labels: dict[str, str]) -> CleanupReport:
        """Remove every execution resource carrying these labels and confirm release."""
        ...

    async def reconcile(self, leftover: Leftover) -> CleanupReport:
        """Stop a leftover Runner if it is provably ours, then clean its resources."""
        ...
