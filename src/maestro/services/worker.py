"""In-process run-level worker (05, D-020) driving the executor boundary.

M2 scope: claim FIFO, per-run lease, lease-checked event commits, cancellation,
deadline and restart reconciliation, against any ``Executor``. M3 adds the real
Runner subprocess, process identity, capacity accounting and label cleanup.
"""

import asyncio
import contextlib
import logging
import math
import os
import secrets

from sqlalchemy import insert, select, update

from maestro.boundaries.executor import AttemptOutcome, Executor, RunSpec, TrialSpec
from maestro.boundaries.storage import ArtifactStore
from maestro.core import clock
from maestro.core.digests import digest_json
from maestro.core.errors import MaestroError
from maestro.core.ids import new_id
from maestro.db import schema as t
from maestro.db.engine import Database
from maestro.domain import limits
from maestro.domain.states import (
    RUN_TERMINAL,
    TRIAL_TERMINAL,
    ArtifactState,
    AttemptState,
    CleanupState,
    RunState,
    TrialState,
    trial_can_move,
)
from maestro.security.redaction import redact
from maestro.services.runs import finalize, finish_unstarted, refresh_operation

log = logging.getLogger(__name__)
POLICY_VERSION = "platform-0"
_PHASE_TO_TRIAL = {
    "preparing": TrialState.PREPARING,
    "executing": TrialState.EXECUTING,
    "verifying": TrialState.VERIFYING,
}


class StaleLease(MaestroError):
    def __init__(self):
        super().__init__("STALE_EXECUTION_LEASE", "Execution lease is no longer valid", 409)


class _Cancel:
    def __init__(self):
        self.event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self.event.is_set()

    async def wait(self) -> None:
        await self.event.wait()


def trial_outcome(outcome: AttemptOutcome) -> tuple[TrialState, str | None]:
    """Scored needs a legal number and reward_valid (06 section 1); 0 is a real score."""
    score = outcome.raw_score
    legal = isinstance(score, int | float) and not isinstance(score, bool) and math.isfinite(score)
    if outcome.reward_valid and legal:
        return TrialState.SCORED, outcome.failure_cause
    return TrialState.EXECUTION_ERROR, outcome.failure_cause or "verifier_failed"


class RunSink:
    """Commits executor events for one claimed run, each in a short transaction."""

    def __init__(self, worker: "Worker", run_id: str, lease: str):
        self.worker = worker
        self.db = worker.db
        self.run_id = run_id
        self.lease = lease
        self.attempt_ids: dict[tuple[str, int], str] = {}

    def _check(self, conn, trial_id: str):
        run = conn.execute(
            select(t.runs.c.lease_token, t.runs.c.state).where(t.runs.c.id == self.run_id)
        ).one()
        if run.lease_token != self.lease or run.state in RUN_TERMINAL:
            raise StaleLease()
        trial = (
            conn.execute(
                select(t.trials).where(t.trials.c.id == trial_id, t.trials.c.run_id == self.run_id)
            )
            .mappings()
            .first()
        )
        if trial is None:
            raise MaestroError("UNKNOWN_TRIAL", "Trial does not belong to this run", 409)
        return trial

    def _move(self, conn, trial, target: TrialState, **values) -> bool:
        if not trial_can_move(trial["state"], target):
            return False  # First accepted terminal state wins; late events are ignored.
        conn.execute(
            update(t.trials).where(t.trials.c.id == trial["id"]).values(state=target, **values)
        )
        return True

    def _attempt(self, conn, trial_id: str, attempt_index: int) -> str:
        key = (trial_id, attempt_index)
        if key not in self.attempt_ids:
            found = conn.execute(
                select(t.execution_attempts.c.id).where(
                    t.execution_attempts.c.trial_id == trial_id,
                    t.execution_attempts.c.attempt_index == attempt_index,
                )
            ).scalar()
            if found is None:
                raise MaestroError("UNKNOWN_ATTEMPT", "Attempt was never started", 409)
            self.attempt_ids[key] = found
        return self.attempt_ids[key]

    async def attempt_started(self, trial_id: str, attempt_index: int) -> None:
        with self.db.write() as conn:
            trial = self._check(conn, trial_id)
            if trial["state"] in TRIAL_TERMINAL:
                return
            attempt_id = new_id("att")
            conn.execute(
                insert(t.execution_attempts).values(
                    id=attempt_id,
                    trial_id=trial_id,
                    attempt_index=attempt_index,
                    worker_id=self.worker.worker_id,
                    service_epoch=self.worker.epoch,
                    lease_token=self.lease,
                    runner_id=self.worker.executor.executor_id,
                    state=AttemptState.STARTING,
                    started_at=clock.to_text(clock.now()),
                )
            )
            self.attempt_ids[(trial_id, attempt_index)] = attempt_id
            self._move(conn, trial, TrialState.PREPARING, phase="starting")
            refresh_operation(conn, self.run_id)

    async def phase_changed(self, trial_id: str, attempt_index: int, phase: str) -> None:
        with self.db.write() as conn:
            trial = self._check(conn, trial_id)
            attempt_id = self._attempt(conn, trial_id, attempt_index)
            conn.execute(
                update(t.execution_attempts)
                .where(t.execution_attempts.c.id == attempt_id)
                .values(
                    phase=phase,
                    state=AttemptState(phase)
                    if phase in _PHASE_TO_TRIAL
                    else AttemptState.STARTING,
                )
            )
            target = _PHASE_TO_TRIAL.get(phase)
            if target and trial["state"] != target:
                self._move(conn, trial, target, phase=phase)
            elif trial["state"] not in TRIAL_TERMINAL:
                conn.execute(update(t.trials).where(t.trials.c.id == trial_id).values(phase=phase))
            refresh_operation(conn, self.run_id)

    async def log(self, trial_id: str, attempt_index: int, stream: str, text: str) -> None:
        await self.artifact(
            trial_id, attempt_index, "log", f"{stream}.log", redact(text).encode(), append=True
        )

    async def artifact(self, trial_id, attempt_index, kind, relative_path, data, append=False):
        with self.db.read() as conn:
            self._check(conn, trial_id)
            attempt_id = self._attempt(conn, trial_id, attempt_index)
        name = relative_path.replace("/", "_").lower()
        storage_key = f"runs/{self.run_id.lower()}/{attempt_id.lower()}/{name}"
        store = self.worker.store
        if append and store.exists(storage_key):
            data = store.get(storage_key) + data
        try:
            digest, size = await asyncio.to_thread(store.put, storage_key, data)
            status = "available"
        except OSError:
            digest, size, status = None, None, "failed"
        with self.db.write() as conn:
            existing = conn.execute(
                select(t.artifacts.c.id).where(t.artifacts.c.storage_key == storage_key)
            ).scalar()
            values = {"digest": digest, "size_bytes": size, "status": status}
            if existing:
                conn.execute(
                    update(t.artifacts).where(t.artifacts.c.id == existing).values(**values)
                )
            else:
                now = clock.now()
                conn.execute(
                    insert(t.artifacts).values(
                        id=new_id("art"),
                        run_id=self.run_id,
                        trial_id=trial_id,
                        attempt_id=attempt_id,
                        kind=kind,
                        relative_path=relative_path,
                        storage_key=storage_key,
                        created_at=clock.to_text(now),
                        expires_at=clock.to_text(
                            now + clock.timedelta(days=limits.ARTIFACT_TTL_DAYS)
                        ),
                        **values,
                    )
                )
            if status == "failed":
                conn.execute(
                    update(t.trials)
                    .where(t.trials.c.id == trial_id)
                    .values(artifact_state=ArtifactState.FAILED)
                )

    async def attempt_finished(
        self, trial_id: str, attempt_index: int, outcome: AttemptOutcome, final: bool
    ) -> None:
        state, cause = trial_outcome(outcome)
        error = None
        if state != TrialState.SCORED or outcome.failure_cause:
            error = {
                "stage": "execution",
                "code": (cause or "unclassified").upper(),
                "failure_cause": cause,
                "exception_type": outcome.exception_type,
                "message": redact(outcome.message or ""),
                "reward_valid": outcome.reward_valid,
                "retry_recommended": outcome.retry_recommended,
                "grade_requested": outcome.grade_requested,
                "policy_version": POLICY_VERSION,
            }
        with self.db.write() as conn:
            trial = self._check(conn, trial_id)
            attempt_id = self._attempt(conn, trial_id, attempt_index)
            at = clock.to_text(clock.now())
            conn.execute(
                update(t.execution_attempts)
                .where(t.execution_attempts.c.id == attempt_id)
                .values(
                    state=AttemptState.COMPLETED
                    if state == TrialState.SCORED
                    else AttemptState.FAILED,
                    ended_at=at,
                    error_json=error,
                )
            )
            if trial["state"] in TRIAL_TERMINAL:
                return  # e.g. cancelled first; keep as late evidence on the attempt only
            if not final:
                # Retry: the attempt ends, the trial returns to queued (05 section 4).
                self._move(conn, trial, TrialState.QUEUED, phase="retry_wait")
                refresh_operation(conn, self.run_id)
                return
            result = {
                "trial_id": trial_id,
                "attempt_id": attempt_id,
                "raw_score": outcome.raw_score,
                "reward_valid": outcome.reward_valid,
                "failure_cause": outcome.failure_cause,
            }
            result_digest = digest_json(result)
            existing = conn.execute(
                select(t.trial_results.c.result_digest).where(
                    t.trial_results.c.trial_id == trial_id
                )
            ).scalar()
            if existing is not None:
                if existing != result_digest:
                    raise MaestroError("RESULT_CONFLICT", "Different result already recorded", 409)
                return
            conn.execute(
                insert(t.trial_results).values(
                    trial_id=trial_id,
                    attempt_id=attempt_id,
                    result_digest=result_digest,
                    raw_score=outcome.raw_score,
                    metrics_json=outcome.metrics,
                    verifier_status=outcome.verifier_status,
                    failure_cause=outcome.failure_cause,
                    exception_type=outcome.exception_type,
                    reward_valid=outcome.reward_valid,
                    grade_requested=outcome.grade_requested,
                    retry_recommended=outcome.retry_recommended,
                    actual_model_json=outcome.actual_model,
                    usage_json=outcome.usage,
                    policy_version=POLICY_VERSION,
                    recorded_at=at,
                )
            )
            artifact = (
                ArtifactState.FAILED
                if trial["artifact_state"] == ArtifactState.FAILED
                else ArtifactState.COMPLETE
            )
            self._move(
                conn,
                trial,
                state,
                phase=None,
                reason_code=None
                if state == TrialState.SCORED
                else (cause or "unclassified").upper(),
                execution_terminal_at=at,
                result_revision=trial["result_revision"] + 1,
                artifact_state=artifact,
            )
            refresh_operation(conn, self.run_id)


class Worker:
    def __init__(
        self,
        db: Database,
        executor: Executor,
        store: ArtifactStore,
        *,
        slots: int = 1,
        poll_seconds: float = 0.5,
    ):
        self.db = db
        self.executor = executor
        self.store = store
        self.slots = slots
        self.poll_seconds = poll_seconds
        self.worker_id = f"local-{os.getpid()}"
        self.epoch: str | None = None
        self.active: dict[str, tuple[asyncio.Task, _Cancel]] = {}
        self._wake = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopping = False

    # --- lifecycle -------------------------------------------------------------

    def start_epoch(self) -> dict:
        """Reconcile runs left by an earlier process (05 section 8) before any claim."""
        self.epoch = new_id("ep")
        report = {"interrupted_runs": []}
        with self.db.write() as conn:
            conn.execute(
                insert(t.service_epochs).values(
                    id=self.epoch,
                    started_at=clock.to_text(clock.now()),
                    process_identity_json={"pid": os.getpid()},
                )
            )
            stale = (
                conn.execute(
                    select(t.runs.c.id).where(
                        t.runs.c.lease_token.is_not(None),
                        t.runs.c.state.not_in([s.value for s in RUN_TERMINAL]),
                    )
                )
                .scalars()
                .all()
            )
            for run_id in stale:
                at = clock.to_text(clock.now())
                conn.execute(
                    update(t.execution_attempts)
                    .where(
                        t.execution_attempts.c.trial_id.in_(
                            select(t.trials.c.id).where(t.trials.c.run_id == run_id)
                        ),
                        t.execution_attempts.c.ended_at.is_(None),
                    )
                    .values(state=AttemptState.INTERRUPTED, ended_at=at)
                )
                conn.execute(
                    update(t.trials)
                    .where(
                        t.trials.c.run_id == run_id,
                        t.trials.c.state.in_(
                            [TrialState.PREPARING, TrialState.EXECUTING, TrialState.VERIFYING]
                        ),
                    )
                    .values(
                        state=TrialState.INTERRUPTED,
                        reason_code="SERVICE_RESTARTED",
                        execution_terminal_at=at,
                    )
                )
                finish_unstarted(conn, run_id, TrialState.NOT_STARTED, "RUN_INTERRUPTED")
                # M3 replaces this with label-based cleanup confirmation.
                finalize(conn, run_id, "SERVICE_RESTARTED", cleanup=CleanupState.PENDING)
                report["interrupted_runs"].append(run_id)
        return report

    def wake(self) -> None:
        """Safe from request threads: the event belongs to the worker's loop."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is loop:
            self._wake.set()
        else:
            loop.call_soon_threadsafe(self._wake.set)

    async def run_forever(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self.epoch is None:
            self.start_epoch()
        while not self._stopping:
            try:
                await self.tick()
            except Exception:  # keep the loop alive; failures are visible in logs
                log.exception("worker tick failed")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), self.poll_seconds)
            except TimeoutError:
                pass

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        for task, cancel in list(self.active.values()):
            cancel.event.set()
            task.cancel()
        for task, _ in list(self.active.values()):
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def tick(self) -> None:
        self._enforce_stops()
        while len(self.active) < self.slots:
            claimed = self._claim()
            if claimed is None:
                break
            run_id, lease, spec = claimed
            cancel = _Cancel()
            task = asyncio.create_task(self._execute(run_id, lease, spec, cancel))
            self.active[run_id] = (task, cancel)

    async def drain(self, timeout: float = 10) -> None:
        """Test helper: tick until nothing is queued or active."""
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            await self.tick()
            with self.db.read() as conn:
                queued = conn.execute(
                    select(t.runs.c.id).where(t.runs.c.state == RunState.QUEUED).limit(1)
                ).first()
            if not self.active and not queued:
                return
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError("worker did not drain")
            await asyncio.sleep(0.01)

    # --- claim and execution ----------------------------------------------------

    def _enforce_stops(self) -> None:
        now = clock.to_text(clock.now())
        with self.db.write() as conn:
            expired = conn.execute(
                select(t.runs.c.id, t.runs.c.lease_token).where(
                    t.runs.c.state.not_in([s.value for s in RUN_TERMINAL]),
                    t.runs.c.stop_requested.is_(False),
                    t.runs.c.deadline_at <= now,
                )
            ).all()
            for run_id, lease in expired:
                conn.execute(
                    update(t.runs)
                    .where(t.runs.c.id == run_id)
                    .values(stop_requested=True, stop_reason="RUN_DEADLINE_EXCEEDED")
                )
                if lease is None:
                    finish_unstarted(conn, run_id, TrialState.NOT_STARTED, "RUN_DEADLINE_EXCEEDED")
                    finalize(
                        conn, run_id, "RUN_DEADLINE_EXCEEDED", cleanup=CleanupState.NOT_REQUIRED
                    )
            stopping = set(
                conn.execute(
                    select(t.runs.c.id).where(
                        t.runs.c.id.in_(list(self.active)), t.runs.c.stop_requested.is_(True)
                    )
                ).scalars()
            )
        for run_id in stopping:
            self.active[run_id][1].event.set()

    def _claim(self):
        lease = secrets.token_urlsafe(24)
        with self.db.write() as conn:
            run = (
                conn.execute(
                    select(t.runs)
                    .where(
                        t.runs.c.state == RunState.QUEUED,
                        t.runs.c.stop_requested.is_(False),
                        t.runs.c.lease_token.is_(None),
                    )
                    .order_by(t.runs.c.accepted_at, t.runs.c.id)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if run is None:
                return None
            claimed = conn.execute(
                update(t.runs)
                .where(t.runs.c.id == run["id"], t.runs.c.lease_token.is_(None))
                .values(
                    lease_token=lease,
                    service_epoch=self.epoch,
                    state=RunState.PREPARING,
                    started_at=clock.to_text(clock.now()),
                )
            ).rowcount
            if claimed != 1:
                return None
            conn.execute(
                update(t.work_items)
                .where(
                    t.work_items.c.trial_id.in_(
                        select(t.trials.c.id).where(t.trials.c.run_id == run["id"])
                    )
                )
                .values(state="claimed", lease_token=lease)
            )
            snapshot = conn.execute(
                select(t.run_snapshots.c.effective_json).where(
                    t.run_snapshots.c.run_id == run["id"]
                )
            ).scalar()
            trial_rows = conn.execute(
                select(
                    t.trials.c.id,
                    t.trials.c.repetition_index,
                    t.tasks.c.task_key,
                    t.tasks.c.definition_json,
                )
                .join(t.tasks, t.tasks.c.id == t.trials.c.task_id)
                .where(t.trials.c.run_id == run["id"])
                .order_by(t.tasks.c.task_key, t.trials.c.repetition_index)
            ).all()
            refresh_operation(conn, run["id"])
        spec = RunSpec(
            run_id=run["id"],
            trials=tuple(
                TrialSpec(r.id, r.task_key, r.definition_json, r.repetition_index)
                for r in trial_rows
            ),
            concurrency=run["concurrency"],
            effective_config=snapshot,
            deadline_at=run["deadline_at"],
        )
        return run["id"], lease, spec

    async def _execute(self, run_id: str, lease: str, spec: RunSpec, cancel: _Cancel) -> None:
        sink = RunSink(self, run_id, lease)
        cleanup = CleanupState.FAILED
        close = True
        try:
            report = await self.executor.execute(spec, sink, cancel)
            cleanup = CleanupState.COMPLETE if report.cleanup_complete else CleanupState.FAILED
        except StaleLease:
            log.warning("run %s lost its lease", run_id)
        except asyncio.CancelledError:
            # Service shutdown: leave the run claimed; the next start reconciles it
            # as interrupted (05 section 8) instead of inventing an outcome here.
            close = False
            raise
        except Exception:
            log.exception("executor failed for run %s", run_id)
        finally:
            self.active.pop(run_id, None)
            if close and not self._stopping:
                self._close(run_id, lease, cleanup)
            self.wake()

    def _close(self, run_id: str, lease: str, cleanup: CleanupState) -> None:
        with self.db.write() as conn:
            run = conn.execute(select(t.runs).where(t.runs.c.id == run_id)).mappings().one()
            if run["lease_token"] != lease or run["state"] in RUN_TERMINAL:
                return
            conn.execute(
                update(t.runs).where(t.runs.c.id == run_id).values(state=RunState.FINALIZING)
            )
            reason = run["stop_reason"] if run["stop_requested"] else None
            at = clock.to_text(clock.now())
            if reason:
                finish_unstarted(conn, run_id, TrialState.NOT_STARTED, reason)
                active_target, active_reason = TrialState.CANCELLED, reason
            else:
                # The executor returned without a result for these trials.
                finish_unstarted(conn, run_id, TrialState.EXECUTION_ERROR, "EXECUTOR_NO_RESULT")
                active_target, active_reason = TrialState.EXECUTION_ERROR, "EXECUTOR_NO_RESULT"
            conn.execute(
                update(t.trials)
                .where(
                    t.trials.c.run_id == run_id,
                    t.trials.c.state.in_(
                        [TrialState.PREPARING, TrialState.EXECUTING, TrialState.VERIFYING]
                    ),
                )
                .values(state=active_target, reason_code=active_reason, execution_terminal_at=at)
            )
            conn.execute(
                update(t.execution_attempts)
                .where(
                    t.execution_attempts.c.lease_token == lease,
                    t.execution_attempts.c.ended_at.is_(None),
                )
                .values(
                    state=AttemptState.CANCELLED if reason else AttemptState.FAILED, ended_at=at
                )
            )
            conn.execute(
                update(t.trials).where(t.trials.c.run_id == run_id).values(cleanup_state=cleanup)
            )
            conn.execute(
                update(t.work_items).where(t.work_items.c.lease_token == lease).values(state="done")
            )
            finalize(conn, run_id, reason, cleanup=cleanup)
