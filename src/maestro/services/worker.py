"""In-process run-level worker (05, D-020) driving the executor boundary.

The worker is the single scheduling coordinator: it claims queued runs in FIFO order
when capacity allows, holds a per-run lease, commits executor events in short
lease-checked transactions, enforces cancellation and deadlines, and on start
reconciles whatever an earlier process left behind (05 section 8).
"""

import asyncio
import contextlib
import hashlib
import logging
import os
import secrets

from sqlalchemy import insert, null, select, update

from maestro.boundaries.executor import (
    STEPS,
    AttemptOutcome,
    Executor,
    Leftover,
    RunSpec,
    TrialSpec,
)
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
    TRIAL_ACTIVE,
    TRIAL_TERMINAL,
    ArtifactState,
    AttemptState,
    CleanupState,
    RunState,
    TrialState,
    trial_can_move,
)
from maestro.execution.docker import LABEL_INSTANCE, LABEL_RUN
from maestro.execution.policy import POLICY_VERSION, legal_score
from maestro.security.redaction import redact
from maestro.services.capacity import HostCapacity, provider_of, reservation, waiting_reason
from maestro.services.instance import instance_id
from maestro.services.runs import finalize, finish_unstarted, refresh_operation

log = logging.getLogger(__name__)
CLAIM_SCAN = 200
CLEANUP_RETRY_SECONDS = 300.0


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
    if outcome.reward_valid and legal_score(outcome.raw_score):
        return TrialState.SCORED, outcome.failure_cause
    return TrialState.EXECUTION_ERROR, outcome.failure_cause or "verifier_failed"


def storage_key(run_id: str, owner: str, relative_path: str) -> str:
    """Opaque and stable per path, so a final copy replaces the live log it continues."""
    name = hashlib.sha256(relative_path.encode()).hexdigest()[:32]
    return f"runs/{run_id.lower()}/{owner.lower()}/{name}"


class RunSink:
    """Commits executor events for one claimed run, each in a short transaction."""

    def __init__(self, worker: "Worker", run_id: str, lease: str):
        self.worker = worker
        self.db = worker.db
        self.run_id = run_id
        self.lease = lease
        self.attempt_ids: dict[tuple[str, int], str] = {}

    def _check_run(self, conn):
        run = conn.execute(
            select(t.runs.c.lease_token, t.runs.c.state).where(t.runs.c.id == self.run_id)
        ).one()
        if run.lease_token != self.lease or run.state in RUN_TERMINAL:
            raise StaleLease()

    def _check(self, conn, trial_id: str):
        self._check_run(conn)
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

    async def runner_started(self, identity: dict) -> None:
        with self.db.write() as conn:
            self._check_run(conn)
            conn.execute(
                update(t.runs)
                .where(t.runs.c.id == self.run_id)
                .values(runner_json=identity, heartbeat_at=clock.to_text(clock.now()))
            )

    async def heartbeat(self) -> None:
        with self.db.write() as conn:
            self._check_run(conn)
            conn.execute(
                update(t.runs)
                .where(t.runs.c.id == self.run_id)
                .values(heartbeat_at=clock.to_text(clock.now()))
            )

    async def attempt_started(
        self, trial_id: str, attempt_index: int, detail: dict | None = None
    ) -> None:
        with self.db.write() as conn:
            trial = self._check(conn, trial_id)
            if trial["state"] in TRIAL_TERMINAL:
                return
            attempt_id = new_id("att")
            at = clock.to_text(clock.now())
            conn.execute(
                insert(t.execution_attempts).values(
                    id=attempt_id,
                    trial_id=trial_id,
                    attempt_index=attempt_index,
                    worker_id=self.worker.worker_id,
                    service_epoch=self.worker.epoch,
                    lease_token=self.lease,
                    runner_id=(detail or {}).get("runner_id") or self.worker.executor.executor_id,
                    executor_ref_json=detail,
                    state=AttemptState.STARTING,
                    phase="starting",
                    steps_json=[{"step": "starting", "at": at}],
                    started_at=at,
                )
            )
            self.attempt_ids[(trial_id, attempt_index)] = attempt_id
            self._move(conn, trial, TrialState.PREPARING, phase="starting")
            refresh_operation(conn, self.run_id)

    async def phase_changed(self, trial_id: str, attempt_index: int, step: str) -> None:
        target = TrialState(STEPS[step])
        with self.db.write() as conn:
            trial = self._check(conn, trial_id)
            attempt_id = self._attempt(conn, trial_id, attempt_index)
            steps = conn.execute(
                select(t.execution_attempts.c.steps_json).where(
                    t.execution_attempts.c.id == attempt_id
                )
            ).scalar()
            conn.execute(
                update(t.execution_attempts)
                .where(t.execution_attempts.c.id == attempt_id)
                .values(
                    phase=step,
                    state=AttemptState(target.value),
                    steps_json=[*(steps or []), {"step": step, "at": clock.to_text(clock.now())}],
                )
            )
            if trial["state"] != target:
                self._move(conn, trial, target, phase=step)
            elif trial["state"] not in TRIAL_TERMINAL:
                conn.execute(update(t.trials).where(t.trials.c.id == trial_id).values(phase=step))
            refresh_operation(conn, self.run_id)

    async def log(self, trial_id: str, attempt_index: int, source: str, text: str) -> None:
        await self.artifact(
            trial_id, attempt_index, "log", source, redact(text).encode(), append=True
        )

    async def artifact(self, trial_id, attempt_index, kind, relative_path, data, append=False):
        with self.db.read() as conn:
            self._check(conn, trial_id)
            attempt_id = self._attempt(conn, trial_id, attempt_index)
        await self._store(
            storage_key(self.run_id, attempt_id, relative_path),
            {"trial_id": trial_id, "attempt_id": attempt_id},
            kind,
            relative_path,
            data,
            append,
        )

    async def run_artifact(self, kind: str, relative_path: str, data: bytes) -> None:
        await self._store(
            storage_key(self.run_id, "run", relative_path),
            {"trial_id": None, "attempt_id": None},
            kind,
            relative_path,
            data,
            False,
        )

    async def _store(self, key, owner, kind, relative_path, data, append) -> None:
        store = self.worker.store
        if append and store.exists(key):
            data = store.get(key) + data
        try:
            digest, size = await asyncio.to_thread(store.put, key, data)
            status = "available"
        except OSError:
            digest, size, status = None, None, "failed"
        with self.db.write() as conn:
            existing = conn.execute(
                select(t.artifacts.c.id).where(t.artifacts.c.storage_key == key)
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
                        kind=kind,
                        relative_path=relative_path,
                        storage_key=key,
                        created_at=clock.to_text(now),
                        expires_at=clock.to_text(
                            now + clock.timedelta(days=limits.ARTIFACT_TTL_DAYS)
                        ),
                        **owner,
                        **values,
                    )
                )
            if status == "failed" and owner["trial_id"]:
                conn.execute(
                    update(t.trials)
                    .where(t.trials.c.id == owner["trial_id"])
                    .values(artifact_state=ArtifactState.FAILED)
                )

    async def attempt_finished(
        self, trial_id: str, attempt_index: int, outcome: AttemptOutcome, final: bool
    ) -> None:
        cancelled = outcome.failure_cause == "cancelled"
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
                    state=AttemptState.CANCELLED
                    if cancelled
                    else AttemptState.COMPLETED
                    if state == TrialState.SCORED
                    else AttemptState.FAILED,
                    phase=None,
                    ended_at=at,
                    error_json=error,
                )
            )
            if cancelled or trial["state"] in TRIAL_TERMINAL:
                # A cancelled attempt is closed by the run's stop; a late result after a
                # terminal state stays as evidence on the attempt only.
                return
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
        capacity: HostCapacity,
        *,
        poll_seconds: float = 0.5,
        cleanup_retry_seconds: float = CLEANUP_RETRY_SECONDS,
    ):
        self.db = db
        self.executor = executor
        self.store = store
        self.capacity = capacity
        self.poll_seconds = poll_seconds
        self.cleanup_retry_seconds = cleanup_retry_seconds
        self.worker_id = f"local-{os.getpid()}"
        self.epoch: str | None = None
        self.instance_id: str | None = None
        self.leftovers: list[Leftover] = []
        self.active: dict[str, tuple[asyncio.Task, _Cancel]] = {}
        self._wake = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopping = False
        self._last_cleanup_retry = 0.0

    def labels(self, run_id: str | None = None) -> dict[str, str]:
        labels = {LABEL_INSTANCE: self.instance_id}
        if run_id:
            labels[LABEL_RUN] = run_id.lower()
        return labels

    # --- lifecycle -------------------------------------------------------------

    def start_epoch(self) -> dict:
        """Close out runs an earlier process left claimed (05 section 8) before any claim.

        Database part only; ``recover`` then stops leftover Runners and cleans by label.
        """
        self.instance_id = instance_id(self.db)
        self.epoch = new_id("ep")
        report = {"interrupted_runs": [], "requeued_runs": [], "completed_runs": []}
        leftovers = []
        with self.db.write() as conn:
            conn.execute(
                insert(t.service_epochs).values(
                    id=self.epoch,
                    started_at=clock.to_text(clock.now()),
                    process_identity_json={"pid": os.getpid(), "instance_id": self.instance_id},
                )
            )
            stale = (
                conn.execute(
                    select(t.runs.c.id, t.runs.c.runner_json, t.runs.c.stop_reason).where(
                        t.runs.c.lease_token.is_not(None),
                        t.runs.c.state.not_in([s.value for s in RUN_TERMINAL]),
                    )
                )
                .mappings()
                .all()
            )
            for run in stale:
                run_id = run["id"]
                leftovers.append(Leftover(run_id, self.labels(run_id), run["runner_json"]))
                trial_states = set(
                    conn.execute(
                        select(t.trials.c.state).where(t.trials.c.run_id == run_id)
                    ).scalars()
                )
                started = conn.execute(
                    select(t.execution_attempts.c.id)
                    .join(t.trials, t.trials.c.id == t.execution_attempts.c.trial_id)
                    .where(t.trials.c.run_id == run_id)
                    .limit(1)
                ).first()
                if started is None and not run["stop_reason"]:
                    # Nothing ever ran: the run keeps its place in the queue (05 section 8.5).
                    conn.execute(
                        update(t.runs)
                        .where(t.runs.c.id == run_id)
                        .values(
                            state=RunState.QUEUED,
                            lease_token=None,
                            service_epoch=None,
                            started_at=None,
                            runner_json=null(),  # SQL NULL, not a JSON null
                            heartbeat_at=None,
                            reservation_json=null(),
                            cleanup_state=CleanupState.PENDING,
                        )
                    )
                    conn.execute(
                        update(t.work_items)
                        .where(
                            t.work_items.c.trial_id.in_(
                                select(t.trials.c.id).where(t.trials.c.run_id == run_id)
                            )
                        )
                        .values(state="queued", lease_token=None)
                    )
                    refresh_operation(conn, run_id)
                    report["requeued_runs"].append(run_id)
                    continue
                if trial_states <= {s.value for s in TRIAL_TERMINAL}:
                    # Every result was already confirmed; only cleanup remained.
                    finalize(conn, run_id, run["stop_reason"], cleanup=CleanupState.PENDING)
                    report["completed_runs"].append(run_id)
                    continue
                at = clock.to_text(clock.now())
                conn.execute(
                    update(t.execution_attempts)
                    .where(
                        t.execution_attempts.c.trial_id.in_(
                            select(t.trials.c.id).where(t.trials.c.run_id == run_id)
                        ),
                        t.execution_attempts.c.ended_at.is_(None),
                    )
                    .values(state=AttemptState.INTERRUPTED, phase=None, ended_at=at)
                )
                interrupted = list(TRIAL_ACTIVE) + [TrialState.QUEUED]
                conn.execute(
                    update(t.trials)
                    .where(
                        t.trials.c.run_id == run_id,
                        t.trials.c.state.in_(interrupted),
                        t.trials.c.id.in_(select(t.execution_attempts.c.trial_id)),
                    )
                    .values(
                        state=TrialState.INTERRUPTED,
                        phase=None,
                        reason_code="SERVICE_RESTARTED",
                        execution_terminal_at=at,
                    )
                )
                finish_unstarted(conn, run_id, TrialState.NOT_STARTED, "RUN_INTERRUPTED")
                conn.execute(
                    update(t.trials)
                    .where(
                        t.trials.c.run_id == run_id,
                        t.trials.c.cleanup_state != CleanupState.NOT_REQUIRED,
                    )
                    .values(cleanup_state=CleanupState.PENDING)
                )
                finalize(conn, run_id, "SERVICE_RESTARTED", cleanup=CleanupState.PENDING)
                report["interrupted_runs"].append(run_id)
        self.leftovers = leftovers
        return report

    async def recover(self) -> dict:
        """Stop leftover Runners that are provably ours and clean their resources by label;
        then sweep anything else this instance labelled. Nothing is active yet."""
        released = {}
        for leftover in self.leftovers:
            report = await self.executor.reconcile(leftover)
            released[leftover.run_id] = report.released
            self._set_cleanup(leftover.run_id, report.released)
        sweep = await self.executor.cleanup(self.labels())
        self.leftovers = []
        result = {"runs": released, "sweep_released": sweep.released}
        if self.epoch:
            with self.db.write() as conn:
                conn.execute(
                    update(t.service_epochs)
                    .where(t.service_epochs.c.id == self.epoch)
                    .values(
                        process_identity_json={
                            "pid": os.getpid(),
                            "instance_id": self.instance_id,
                            "recovery": result,
                        }
                    )
                )
        if released or not sweep.released:
            log.warning("restart reconciliation: %s", result)
        return result

    def _set_cleanup(self, run_id: str, released: bool) -> None:
        state = CleanupState.COMPLETE if released else CleanupState.FAILED
        with self.db.write() as conn:
            run = conn.execute(
                select(t.runs.c.lease_token, t.runs.c.state).where(t.runs.c.id == run_id)
            ).one()
            if run.lease_token is not None or run.state not in RUN_TERMINAL:
                return  # requeued or reclaimed; its next execution owns cleanup
            conn.execute(update(t.runs).where(t.runs.c.id == run_id).values(cleanup_state=state))
            conn.execute(
                update(t.trials)
                .where(
                    t.trials.c.run_id == run_id,
                    t.trials.c.cleanup_state != CleanupState.NOT_REQUIRED,
                )
                .values(cleanup_state=state)
            )

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
        try:
            await self.recover()
        except Exception:
            log.exception("restart reconciliation failed")
        self._last_cleanup_retry = self._loop.time()
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
        await self._retry_cleanups()
        while True:
            claimed = self._claim()
            if claimed is None:
                break
            run_id, lease, spec = claimed
            cancel = _Cancel()
            task = asyncio.create_task(self._execute(run_id, lease, spec, cancel))
            self.active[run_id] = (task, cancel)

    async def drain(self, timeout: float = 10) -> None:
        """Test helper: tick until nothing is queued or active."""
        self._loop = asyncio.get_running_loop()
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

    async def _retry_cleanups(self) -> None:
        """Resources not confirmed released keep their capacity; retry them periodically."""
        loop = asyncio.get_running_loop()
        if loop.time() - self._last_cleanup_retry < self.cleanup_retry_seconds:
            return
        self._last_cleanup_retry = loop.time()
        with self.db.read() as conn:
            pending = (
                conn.execute(
                    select(t.runs.c.id).where(
                        t.runs.c.lease_token.is_(None),
                        t.runs.c.state.in_([s.value for s in RUN_TERMINAL]),
                        t.runs.c.cleanup_state.in_([CleanupState.PENDING, CleanupState.FAILED]),
                        t.runs.c.reservation_json.is_not(None),
                    )
                )
                .scalars()
                .all()
            )
        for run_id in pending:
            report = await self.executor.cleanup(self.labels(run_id))
            self._set_cleanup(run_id, report.released)

    def _claim(self):
        """First queued run that fits current capacity; later small runs may pass a
        large one that does not fit yet (05 section 3). Waiting runs show why."""
        lease = secrets.token_urlsafe(24)
        with self.db.write() as conn:
            queued = (
                conn.execute(
                    select(t.runs.c.id, t.runs.c.concurrency, t.runs.c.queue_reason)
                    .where(
                        t.runs.c.state == RunState.QUEUED,
                        t.runs.c.stop_requested.is_(False),
                        t.runs.c.lease_token.is_(None),
                    )
                    .order_by(t.runs.c.accepted_at, t.runs.c.id)
                    .limit(CLAIM_SCAN)
                )
                .mappings()
                .all()
            )
            chosen = None
            for run in queued:
                need = self._reservation(conn, run["id"], run["concurrency"])
                reason = waiting_reason(conn, self.capacity, need)
                if reason is None:
                    chosen = (run, need)
                    break
                if run["queue_reason"] != reason:
                    conn.execute(
                        update(t.runs).where(t.runs.c.id == run["id"]).values(queue_reason=reason)
                    )
            if chosen is None:
                return None
            run, need = chosen
            conn.execute(
                update(t.runs)
                .where(t.runs.c.id == run["id"])
                .values(
                    lease_token=lease,
                    service_epoch=self.epoch,
                    state=RunState.PREPARING,
                    started_at=clock.to_text(clock.now()),
                    queue_reason=None,
                    reservation_json=need,
                    cleanup_state=CleanupState.PENDING,
                )
            )
            conn.execute(
                update(t.work_items)
                .where(
                    t.work_items.c.trial_id.in_(
                        select(t.trials.c.id).where(t.trials.c.run_id == run["id"])
                    )
                )
                .values(state="claimed", lease_token=lease)
            )
            row = conn.execute(select(t.runs).where(t.runs.c.id == run["id"])).mappings().one()
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
                    t.tasks.c.content_digest,
                )
                .join(t.tasks, t.tasks.c.id == t.trials.c.task_id)
                .where(t.trials.c.run_id == run["id"])
                .order_by(t.tasks.c.task_key, t.trials.c.repetition_index)
            ).all()
            refresh_operation(conn, run["id"])
        spec = RunSpec(
            run_id=row["id"],
            trials=tuple(
                TrialSpec(r.id, r.task_key, r.definition_json, r.repetition_index, r.content_digest)
                for r in trial_rows
            ),
            concurrency=row["concurrency"],
            effective_config=snapshot,
            deadline_at=row["deadline_at"],
            labels=self.labels(row["id"]),
        )
        return row["id"], lease, spec

    @staticmethod
    def _reservation(conn, run_id: str, concurrency: int) -> dict:
        definitions = (
            conn.execute(
                select(t.tasks.c.definition_json)
                .where(
                    t.tasks.c.id.in_(select(t.trials.c.task_id).where(t.trials.c.run_id == run_id))
                )
                .distinct()
            )
            .scalars()
            .all()
        )
        trial_count = conn.execute(select(t.trials.c.id).where(t.trials.c.run_id == run_id)).all()
        effective = conn.execute(
            select(t.run_snapshots.c.effective_json).where(t.run_snapshots.c.run_id == run_id)
        ).scalar()
        return reservation(concurrency, definitions, provider_of(effective), len(trial_count))

    async def _execute(self, run_id: str, lease: str, spec: RunSpec, cancel: _Cancel) -> None:
        sink = RunSink(self, run_id, lease)
        cleanup = CleanupState.FAILED
        failure = "EXECUTOR_FAILED"
        close = True
        try:
            report = await self.executor.execute(spec, sink, cancel)
            cleanup = CleanupState.COMPLETE if report.cleanup_complete else CleanupState.FAILED
            failure = report.failure_code
            if report.detail:
                log.info("run %s executor report: %s", run_id, report.detail)
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
                self._close(run_id, lease, cleanup, failure)
            self.wake()

    def _close(self, run_id: str, lease: str, cleanup: CleanupState, failure: str | None) -> None:
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
                active_target, active_reason = TrialState.CANCELLED, reason
            else:
                # The executor returned without a result for these trials.
                active_target = TrialState.EXECUTION_ERROR
                active_reason = failure or "EXECUTOR_NO_RESULT"
            # Trials that already ran (e.g. waiting for a retry) end like active ones;
            # only never-started trials become not_started.
            conn.execute(
                update(t.trials)
                .where(
                    t.trials.c.run_id == run_id,
                    t.trials.c.state.in_([*TRIAL_ACTIVE, TrialState.QUEUED]),
                    t.trials.c.id.in_(select(t.execution_attempts.c.trial_id)),
                )
                .values(
                    state=active_target,
                    phase=None,
                    reason_code=active_reason,
                    execution_terminal_at=at,
                )
            )
            if reason:
                finish_unstarted(conn, run_id, TrialState.NOT_STARTED, reason)
            else:
                finish_unstarted(conn, run_id, active_target, active_reason)
            conn.execute(
                update(t.execution_attempts)
                .where(
                    t.execution_attempts.c.lease_token == lease,
                    t.execution_attempts.c.ended_at.is_(None),
                )
                .values(
                    state=AttemptState.CANCELLED if reason else AttemptState.FAILED,
                    phase=None,
                    ended_at=at,
                )
            )
            conn.execute(
                update(t.trials)
                .where(
                    t.trials.c.run_id == run_id,
                    t.trials.c.cleanup_state != CleanupState.NOT_REQUIRED,
                )
                .values(cleanup_state=cleanup)
            )
            conn.execute(
                update(t.work_items).where(t.work_items.c.lease_token == lease).values(state="done")
            )
            finalize(conn, run_id, reason, cleanup=cleanup)
