"""Run acceptance, queries and cancellation (04 sections 3 and 6).

M2 accepts a direct configuration (dataset version, task selection, repetitions,
concurrency). M5 replaces it with configuration resolutions; the acceptance
transaction itself stays: idempotency, principal and PAT re-check, admission
re-check, quota, then Run + snapshot + trials + work items + Operation + audit.
"""

from __future__ import annotations

from sqlalchemy import Connection, func, insert, select, update

from maestro.core import clock
from maestro.core.digests import digest_json
from maestro.core.errors import FieldError, MaestroError, not_found
from maestro.core.ids import new_id
from maestro.db import schema as t
from maestro.db.engine import Database
from maestro.domain import limits
from maestro.domain.scoring import compact, contract_for
from maestro.domain.states import (
    AGGREGATION_VERSION,
    RUN_TERMINAL,
    TRIAL_TERMINAL,
    ArtifactState,
    CleanupState,
    OperationStatus,
    RunState,
    TrialState,
    UserStatus,
    display_phase,
    result_completeness,
    trial_counts,
)
from maestro.execution.policy import POLICY_VERSION
from maestro.services import audit, deleted, idempotency, operations, pagination, results
from maestro.services.artifacts import stamp_expiry
from maestro.services.capacity import (
    HostCapacity,
    provider_of,
    refuse_if_never_fits,
    reservation,
)
from maestro.services.catalog import (
    ADMITTED,
    expected_image,
    load_admissions,
    load_availability,
    task_blockers,
)
from maestro.services.principal import (
    Channel,
    Principal,
    can_manage_owned,
    require_experiment,
    require_manage_owned,
)

SNAPSHOT_SCHEMA = 1
ACTION_SUBMIT = "runs.submit"
ACTION_CANCEL = "runs.cancel"
# Until model configuration (M5) only the test mode exists: Oracle runs each task's
# reference solution and never enters model comparisons (15 section 6).
EXECUTION_MODES = {"oracle"}


def _check_request(body: dict) -> dict:
    errors = []
    name = body.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 256:
        errors.append(FieldError("/name", "LENGTH", "1-256 characters"))
    version_id = body.get("dataset_version_id")
    if not isinstance(version_id, str):
        errors.append(FieldError("/dataset_version_id", "REQUIRED"))
    selection = body.get("task_selection") or {"mode": "all_eligible"}
    mode = selection.get("mode") if isinstance(selection, dict) else None
    task_ids = selection.get("task_ids") if isinstance(selection, dict) else None
    if mode not in {"all_eligible", "explicit"}:
        errors.append(FieldError("/task_selection/mode", "ENUM"))
    elif mode == "explicit" and (
        not isinstance(task_ids, list)
        or not task_ids
        or not all(isinstance(x, str) for x in task_ids)
        or len(set(task_ids)) != len(task_ids)
    ):
        errors.append(FieldError("/task_selection/task_ids", "INVALID"))
    repetitions = body.get("repetitions", limits.REPETITIONS_DEFAULT)
    if type(repetitions) is not int or not 1 <= repetitions <= limits.REPETITIONS_MAX:
        errors.append(FieldError("/repetitions", "LIMIT_EXCEEDED", limit=limits.REPETITIONS_MAX))
    concurrency = body.get("concurrency", limits.RUN_DEFAULT_CONCURRENCY)
    if type(concurrency) is not int or not 1 <= concurrency <= limits.RUN_MAX_CONCURRENCY:
        errors.append(
            FieldError("/concurrency", "LIMIT_EXCEEDED", limit=limits.RUN_MAX_CONCURRENCY)
        )
    execution_mode = body.get("execution_mode", "oracle")
    if execution_mode not in EXECUTION_MODES:
        errors.append(FieldError("/execution_mode", "ENUM"))
    client_request_id = body.get("client_request_id")
    if client_request_id is not None and (
        not isinstance(client_request_id, str) or not 1 <= len(client_request_id) <= 128
    ):
        errors.append(FieldError("/client_request_id", "LENGTH"))
    if errors:
        raise MaestroError(
            "CONFIG_VALIDATION_FAILED",
            "Invalid run request",
            422,
            stage="preflight",
            field_errors=errors,
        )
    return {
        "name": name.strip(),
        "dataset_version_id": version_id,
        "task_selection": {"mode": mode, **({"task_ids": sorted(task_ids)} if task_ids else {})},
        "repetitions": repetitions,
        "concurrency": concurrency,
        "execution_mode": execution_mode,
        "client_request_id": client_request_id,
    }


def public_run(
    row,
    counts: dict,
    principal: Principal | None,
    summary: dict | None = None,
    deletions: dict | None = None,
) -> dict:
    """``deletions`` maps 'run', 'owner' and 'dataset_version' to deletion states."""
    deletions = deletions or {}
    allowed = ["view"]
    manage = principal is not None and can_manage_owned(principal, row["owner_id"])
    if manage and row["state"] not in RUN_TERMINAL and not row["stop_requested"]:
        allowed.append("cancel")
    if manage and row["state"] in RUN_TERMINAL and not deletions.get("run"):
        allowed.append("delete")
    state = RunState(row["state"])
    return {
        "id": row["id"],
        "name": row["name"],
        "owner_id": row["owner_id"],
        # Submitter names are team-visible: results are shared, identity is kept.
        "owner": {
            "username": row["owner_username"],
            "display_name": row["owner_display_name"],
            "deleted": deletions.get("owner") is not None,
        },
        "pat_id": row["pat_id"],
        "relation": row["relation"],
        "source_run_id": row["source_run_id"],
        "dataset_version_id": row["dataset_version_id"],
        "operation_id": row["operation_id"],
        "client_request_id": row["client_request_id"],
        "state": state.value,
        "result_completeness": result_completeness(counts).value,
        "artifact_state": row["artifact_state"],
        "cleanup_state": row["cleanup_state"],
        "stop_requested": row["stop_requested"],
        "stop_reason": row["stop_reason"],
        "queue_reason": row["queue_reason"],
        "heartbeat_at": row["heartbeat_at"],
        "counts": counts,
        "scoring": compact(summary) if summary else None,
        "deletion": deletions.get("run"),
        "dataset_version_deletion": deletions.get("dataset_version"),
        "accepted_at": row["accepted_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "deadline_at": row["deadline_at"],
        "allowed_actions": allowed,
        "links": {
            "self": f"/api/v1/runs/{row['id']}",
            "trials": f"/api/v1/runs/{row['id']}/trials",
            "summary": f"/api/v1/runs/{row['id']}/summary",
            "artifacts": f"/api/v1/runs/{row['id']}/artifacts",
            "operation": f"/api/v1/operations/{row['operation_id']}",
        },
    }


def runs_with_owner():
    return select(
        t.runs,
        t.users.c.username.label("owner_username"),
        t.users.c.display_name.label("owner_display_name"),
    ).join(t.users, t.users.c.id == t.runs.c.owner_id)


def run_deletions(conn: Connection, rows) -> dict[str, dict]:
    """Per run id: its own, its owner's and its dataset version's deletion state."""
    runs = deleted.states(conn, "run", [r["id"] for r in rows])
    owners = deleted.states(conn, "user", [r["owner_id"] for r in rows])
    versions = {v: deleted.version_state(conn, v) for v in {r["dataset_version_id"] for r in rows}}
    return {
        r["id"]: {
            "run": runs.get(r["id"]),
            "owner": owners.get(r["owner_id"]),
            "dataset_version": versions.get(r["dataset_version_id"]),
        }
        for r in rows
    }


def run_counts(conn: Connection, run_id: str) -> tuple[dict, list[str]]:
    states = [
        s for (s,) in conn.execute(select(t.trials.c.state).where(t.trials.c.run_id == run_id))
    ]
    return trial_counts(states), states


def refresh_operation(conn: Connection, run_id: str) -> None:
    """Rebuild run-level progress from trial records (Operation never leads)."""
    run = conn.execute(select(t.runs).where(t.runs.c.id == run_id)).mappings().one()
    counts, states = run_counts(conn, run_id)
    state = RunState(run["state"])
    if state not in RUN_TERMINAL and state != RunState.FINALIZING and run["started_at"]:
        phase = display_phase(counts, states)
        if phase != RunState.QUEUED and phase != state:
            conn.execute(update(t.runs).where(t.runs.c.id == run_id).values(state=phase))
            state = phase
    operations.advance(
        conn,
        run["operation_id"],
        progress={k: counts[k] for k in ("planned", "terminal", "scored", "errors", "active")},
        phase={
            "queued": "queued",
            "preparing": "preparing",
            "running": "executing",
            "finalizing": "finalizing",
        }.get(state.value, state.value),
    )


class Runs:
    def __init__(self, db: Database, capacity: HostCapacity | None = None, disk=None):
        self.db = db
        self.capacity = capacity
        self.disk = disk

    # --- acceptance ------------------------------------------------------------

    def submit(
        self, principal: Principal, idempotency_key: str, body: dict
    ) -> tuple[int, dict, bool]:
        require_experiment(principal)
        key = idempotency.check_key(idempotency_key)
        request = _check_request(body)
        req_hash = idempotency.request_hash(request)
        with self.db.read() as conn:
            stored = idempotency.lookup(
                conn, principal.idempotency_principal, ACTION_SUBMIT, key, req_hash
            )
        if stored:
            return stored.status_code, stored.response, True
        if self.disk:
            self.disk.refuse_if_low()
        # Expand outside the write transaction; revisions are re-checked inside.
        with self.db.read() as conn:
            plan = self._expand(conn, request)
        with self.db.write() as conn:
            stored = idempotency.lookup(
                conn, principal.idempotency_principal, ACTION_SUBMIT, key, req_hash
            )
            if stored:
                return stored.status_code, stored.response, True
            self._recheck_principal(conn, principal)
            self._refuse_deleted_version(conn, request["dataset_version_id"])
            self._recheck_tasks(conn, plan)
            if self.capacity:
                refuse_if_never_fits(conn, self.capacity, plan["reservation"])
            if principal.channel == Channel.PAT:
                self._charge_pat(conn, principal.pat_id)
            response = self._insert_run(conn, principal, request, plan)
            idempotency.store(
                conn, principal.idempotency_principal, ACTION_SUBMIT, key, req_hash, 202, response
            )
            audit.record(
                conn,
                principal,
                "run.submit",
                object_type="run",
                object_id=response["run_id"],
                detail={"trials": response["planned_trials"]},
            )
        return 202, response, False

    def _expand(self, conn: Connection, request: dict) -> dict:
        version = (
            conn.execute(
                select(
                    t.dataset_versions,
                    t.datasets.c.namespace,
                    t.datasets.c.name,
                    t.datasets.c.source_kind,
                )
                .join(t.datasets, t.datasets.c.id == t.dataset_versions.c.dataset_id)
                .where(t.dataset_versions.c.id == request["dataset_version_id"])
            )
            .mappings()
            .first()
        )
        if version is None:
            raise MaestroError(
                "CONFIG_VALIDATION_FAILED",
                "Dataset version not found",
                422,
                stage="preflight",
                field_errors=[FieldError("/dataset_version_id", "NOT_FOUND")],
            )
        self._refuse_deleted_version(conn, version["id"])
        tasks_rows = (
            conn.execute(
                select(t.tasks)
                .where(t.tasks.c.dataset_version_id == version["id"])
                .order_by(t.tasks.c.task_key)
            )
            .mappings()
            .all()
        )
        admissions = load_admissions(conn, [r["id"] for r in tasks_rows])
        availability = load_availability(
            conn,
            [r["content_digest"] for r in tasks_rows]
            + [d for a in admissions.values() if (d := expected_image(a))],
        )
        rows, blockers = [], {}
        for task in tasks_rows:
            admission = admissions.get(task["id"])
            rows.append(
                {
                    **task,
                    "admission_id": admission["id"] if admission else None,
                    "admission_revision": admission["revision"] if admission else None,
                    "preparation_method_digest": (
                        admission["preparation_method_digest"] if admission else None
                    ),
                    "expected_image_id": expected_image(admission),
                }
            )
            blockers[task["id"]] = task_blockers(task, admission, availability)

        def blocker(row):
            found = blockers[row["id"]]
            return found[0]["code"] if found else None

        selection = request["task_selection"]
        if selection["mode"] == "all_eligible":
            chosen = [r for r in rows if blocker(r) is None]
            excluded = [
                {"task_id": r["id"], "task_key": r["task_key"], "blockers": blockers[r["id"]]}
                for r in rows
                if blocker(r)
            ]
        else:
            by_id = {r["id"]: r for r in rows}
            missing = [x for x in selection["task_ids"] if x not in by_id]
            blocked = [x for x in selection["task_ids"] if x in by_id and blocker(by_id[x])]
            if missing or blocked:
                raise MaestroError(
                    "TASKS_NOT_SUBMITTABLE",
                    "Some selected tasks are unknown or blocked",
                    422,
                    stage="preflight",
                    field_errors=[
                        FieldError("/task_selection/task_ids", "NOT_FOUND", x) for x in missing
                    ]
                    + [
                        FieldError("/task_selection/task_ids", blocker(by_id[x]), x)
                        for x in blocked
                    ],
                )
            chosen = [by_id[x] for x in selection["task_ids"]]
            excluded = []
        if not chosen:
            raise MaestroError(
                "NO_SUBMITTABLE_TASKS",
                "No submittable task in this version",
                422,
                stage="preflight",
                field_errors=[
                    FieldError("/task_selection", x["blockers"][0]["code"], x["task_key"])
                    for x in excluded
                ],
            )
        if len(chosen) > limits.RUN_MAX_TASKS or (
            len(chosen) * request["repetitions"] > limits.RUN_MAX_TRIALS
        ):
            raise MaestroError(
                "RUN_TOO_LARGE",
                "Run exceeds task or trial limits",
                413,
                stage="preflight",
            )
        tasks = [
            {
                "task_id": r["id"],
                "task_key": r["task_key"],
                "content_digest": r["content_digest"],
                "admission_id": r["admission_id"],
                "admission_revision": r["admission_revision"],
                "preparation_method_digest": r["preparation_method_digest"],
                "spec_digest": r["spec_digest"],
                "expected_image_id": r["expected_image_id"],
                "definition": r["definition_json"],
            }
            for r in sorted(chosen, key=lambda r: r["task_key"])
        ]
        effective = {
            "dataset": {
                "source_kind": version["source_kind"],
                "namespace": version["namespace"],
                "name": version["name"],
                "version_id": version["id"],
                "resolved_digest": version["resolved_digest"],
            },
            # The fixed preparation spec is part of the configuration; cache state is not.
            "tasks": [
                {k: x[k] for k in ("task_key", "content_digest", "spec_digest")} for x in tasks
            ],
            "repetitions": request["repetitions"],
            "concurrency": request["concurrency"],
            "execution_mode": request["execution_mode"],
        }
        ready = set(
            conn.execute(
                select(t.preparations.c.spec_digest).where(
                    t.preparations.c.spec_digest.in_([x["spec_digest"] for x in tasks]),
                    t.preparations.c.cache_state == "ready",
                )
            ).scalars()
        )
        observations = [
            {
                "task_key": x["task_key"],
                "cache_state": "ready" if x["spec_digest"] in ready else "cold",
                "action": None if x["spec_digest"] in ready else "restore_on_run",
            }
            for x in tasks
        ]
        return {
            "version": dict(version),
            "tasks": tasks,
            "excluded": excluded,
            "cache_observations": observations,
            "effective": effective,
            "reservation": reservation(
                request["concurrency"],
                [x["definition"] for x in tasks],
                provider_of(effective),
                len(tasks) * request["repetitions"],
            ),
        }

    @staticmethod
    def _refuse_deleted_version(conn: Connection, version_id: str) -> None:
        """Deleted datasets and versions cannot be newly referenced (07 section 8)."""
        if deleted.version_state(conn, version_id):
            raise MaestroError(
                "DATASET_VERSION_DELETED",
                "This dataset version was deleted",
                422,
                stage="preflight",
                field_errors=[FieldError("/dataset_version_id", "DELETED")],
            )

    @staticmethod
    def _recheck_principal(conn: Connection, principal: Principal) -> None:
        status = conn.execute(
            select(t.users.c.status).where(t.users.c.id == principal.user_id)
        ).scalar()
        if status != UserStatus.ACTIVE:
            raise MaestroError("UNAUTHENTICATED", "Account is disabled", 401)

    @staticmethod
    def _recheck_tasks(conn: Connection, plan: dict) -> None:
        """Admission may be revoked between expansion and acceptance (F-26)."""
        ids = [x["admission_id"] for x in plan["tasks"]]
        current = {
            r["id"]: r
            for r in conn.execute(
                select(t.task_admissions).where(t.task_admissions.c.id.in_(ids))
            ).mappings()
        }
        digests = [x["content_digest"] for x in plan["tasks"]] + [
            x["expected_image_id"] for x in plan["tasks"] if x["expected_image_id"]
        ]
        unavailable = set(
            conn.execute(
                select(t.content_availability.c.content_digest).where(
                    t.content_availability.c.content_digest.in_(digests),
                    t.content_availability.c.availability == "unavailable",
                )
            ).scalars()
        )
        changed = [
            x["task_id"]
            for x in plan["tasks"]
            if (row := current.get(x["admission_id"])) is None
            or row["state"] != ADMITTED
            or row["revision"] != x["admission_revision"]
            or x["content_digest"] in unavailable
            or x["expected_image_id"] in unavailable
        ]
        if changed:
            raise MaestroError(
                "ADMISSION_CHANGED",
                "Task admission or content changed during submission; resubmit",
                409,
                stage="acceptance",
                retryable=True,
                field_errors=[FieldError("/task_selection", "CHANGED", x) for x in changed],
            )

    @staticmethod
    def _charge_pat(conn: Connection, pat_id: str) -> None:
        now = clock.to_text(clock.now())
        charged = conn.execute(
            update(t.pats)
            .where(
                t.pats.c.id == pat_id,
                t.pats.c.revoked_at.is_(None),
                t.pats.c.expires_at > now,
                t.pats.c.accepted_runs < t.pats.c.run_limit,
            )
            .values(accepted_runs=t.pats.c.accepted_runs + 1)
        ).rowcount
        if charged == 1:
            return
        pat = conn.execute(select(t.pats).where(t.pats.c.id == pat_id)).mappings().one()
        if pat["revoked_at"]:
            raise MaestroError("PAT_REVOKED", "Access token was revoked", 401)
        if pat["expires_at"] <= now:
            raise MaestroError("PAT_EXPIRED", "Access token expired", 401)
        raise MaestroError(
            "PAT_RUN_LIMIT_REACHED",
            "This access token has no remaining run quota",
            429,
            stage="acceptance",
            suggested_actions=[{"type": "create_access_token"}],
        )

    @staticmethod
    def _insert_run(conn: Connection, principal: Principal, request: dict, plan: dict) -> dict:
        now = clock.now()
        at = clock.to_text(now)
        run_id = new_id("run")
        planned = len(plan["tasks"]) * request["repetitions"]
        op_id = operations.create(
            conn,
            "run",
            owner_id=principal.user_id,
            pat_id=principal.pat_id,
            progress={"planned": planned, "terminal": 0, "scored": 0, "errors": 0, "active": 0},
            phase="queued",
        )
        conn.execute(
            insert(t.runs).values(
                id=run_id,
                name=request["name"],
                owner_id=principal.user_id,
                pat_id=principal.pat_id,
                relation="initial",
                dataset_version_id=request["dataset_version_id"],
                operation_id=op_id,
                state=RunState.QUEUED,
                stop_requested=False,
                client_request_id=request["client_request_id"],
                concurrency=request["concurrency"],
                artifact_state=ArtifactState.PENDING,
                cleanup_state=CleanupState.PENDING,
                accepted_at=at,
                deadline_at=clock.to_text(now + clock.timedelta(hours=limits.RUN_DEADLINE_HOURS)),
            )
        )
        operations.set_resource(conn, op_id, "run", run_id)
        effective = plan["effective"]
        provenance = {
            "submitted_via": principal.channel.value,
            "task_selection": request["task_selection"],
            "excluded_tasks": plan["excluded"],
            "admissions": [
                {
                    k: x[k]
                    for k in (
                        "task_key",
                        "admission_id",
                        "admission_revision",
                        "preparation_method_digest",
                        "spec_digest",
                        "expected_image_id",
                    )
                }
                for x in plan["tasks"]
            ],
        }
        policy = {
            "aggregation_version": AGGREGATION_VERSION,
            "policy_version": POLICY_VERSION,
            "scoring": contract_for(plan["version"]["manifest_json"]),
        }
        config_digest = digest_json(effective)
        conn.execute(
            insert(t.run_snapshots).values(
                run_id=run_id,
                schema_version=SNAPSHOT_SCHEMA,
                effective_json=effective,
                provenance_json=provenance,
                snapshot_digest=digest_json(
                    {"effective": effective, "provenance": provenance, "policy": policy}
                ),
                config_digest=config_digest,
                comparison_digest=digest_json({**effective, "concurrency": None}),
                policy_json=policy,
            )
        )
        seq = conn.execute(select(func.coalesce(func.max(t.work_items.c.enqueue_seq), 0))).scalar()
        trial_rows, item_rows = [], []
        for task in plan["tasks"]:
            for repetition in range(1, request["repetitions"] + 1):
                trial_id = new_id("trl")
                seq += 1
                trial_rows.append(
                    {
                        "id": trial_id,
                        "run_id": run_id,
                        "task_id": task["task_id"],
                        "repetition_index": repetition,
                        "state": TrialState.QUEUED,
                        "result_revision": 0,
                        "artifact_state": ArtifactState.PENDING,
                        "cleanup_state": CleanupState.PENDING,
                    }
                )
                item_rows.append(
                    {
                        "id": new_id("wi"),
                        "trial_id": trial_id,
                        "state": "queued",
                        "eligible_at": at,
                        "enqueue_seq": seq,
                    }
                )
        conn.execute(insert(t.trials), trial_rows)
        conn.execute(insert(t.work_items), item_rows)
        return {
            "run_id": run_id,
            "operation_id": op_id,
            "state": RunState.QUEUED.value,
            "config_digest": config_digest,
            "snapshot_digest": digest_json(
                {"effective": effective, "provenance": provenance, "policy": policy}
            ),
            "planned_trials": planned,
            "excluded_tasks": plan["excluded"],
            # Observations only: not part of the configuration or its digest (10 section 4).
            "cache_observations": plan["cache_observations"],
            "links": {"run": f"/api/v1/runs/{run_id}", "operation": f"/api/v1/operations/{op_id}"},
        }

    # --- queries ------------------------------------------------------------

    def _row(self, conn: Connection, run_id: str):
        row = conn.execute(runs_with_owner().where(t.runs.c.id == run_id)).mappings().first()
        if row is None:
            raise not_found("Run")
        return row

    def _live_row(self, conn: Connection, run_id: str):
        """A run whose content still exists; a purged run answers 410."""
        row = self._row(conn, run_id)
        deleted.refuse_purged(conn, "run", run_id, "Run")
        return row

    def get(self, principal: Principal, run_id: str) -> dict:
        with self.db.read() as conn:
            row = self._live_row(conn, run_id)
            counts, _ = run_counts(conn, run_id)
            summary = results.summaries(conn, [run_id])[run_id]
            marks = run_deletions(conn, [row])[run_id]
            snapshot = (
                conn.execute(select(t.run_snapshots).where(t.run_snapshots.c.run_id == run_id))
                .mappings()
                .one()
            )
        return {
            **public_run(row, counts, principal, summary, marks),
            "snapshot": {
                "schema_version": snapshot["schema_version"],
                "effective": snapshot["effective_json"],
                "provenance": snapshot["provenance_json"],
                "policy": snapshot["policy_json"],
                "config_digest": snapshot["config_digest"],
                "snapshot_digest": snapshot["snapshot_digest"],
                "comparison_digest": snapshot["comparison_digest"],
            },
        }

    def list(
        self,
        principal: Principal,
        *,
        owner_id: str | None,
        state: str | None,
        dataset_version_id: str | None,
        client_request_id: str | None,
        cursor: str | None,
        limit: int | None,
        accepted_after: str | None = None,
        accepted_before: str | None = None,
    ) -> tuple[list, str | None]:
        """Deleted runs are hidden; the recycle bin lists them."""
        limit = pagination.check_limit(limit)

        def normalized(name: str, value: str | None) -> str | None:
            """Stored times have six fractional digits; compare like with like."""
            if value is None:
                return None
            try:
                return clock.to_text(clock.from_text(value))
            except ValueError:
                raise MaestroError(
                    "INVALID_TIME",
                    f"{name} must be RFC 3339 UTC like {clock.to_text(clock.now())}",
                    400,
                ) from None

        accepted_after = normalized("accepted_after", accepted_after)
        accepted_before = normalized("accepted_before", accepted_before)
        filters = {
            "owner_id": owner_id,
            "state": state,
            "dataset_version_id": dataset_version_id,
            "client_request_id": client_request_id,
            "accepted_after": accepted_after,
            "accepted_before": accepted_before,
        }
        query = runs_with_owner().where(deleted.visible(t.runs.c.id, "run"))
        for column, value in (
            (t.runs.c.owner_id, owner_id),
            (t.runs.c.state, state),
            (t.runs.c.dataset_version_id, dataset_version_id),
            (t.runs.c.client_request_id, client_request_id),
        ):
            if value is not None:
                query = query.where(column == value)
        if accepted_after is not None:
            query = query.where(t.runs.c.accepted_at >= accepted_after)
        if accepted_before is not None:
            query = query.where(t.runs.c.accepted_at < accepted_before)
        query = pagination.page(query, t.runs.c.accepted_at, t.runs.c.id, cursor, limit, filters)
        with self.db.read() as conn:
            rows = list(conn.execute(query).mappings().all())
            rows, next_cursor = pagination.split(rows, limit, "accepted_at", filters)
            ids = [r["id"] for r in rows]
            summary = results.summaries(conn, ids)
            marks = run_deletions(conn, rows)
            items = [
                public_run(
                    r, run_counts(conn, r["id"])[0], principal, summary[r["id"]], marks[r["id"]]
                )
                for r in rows
            ]
        return items, next_cursor

    def summary(self, run_id: str) -> dict:
        """06 section 5 for one run, with per-task statistics."""
        with self.db.read() as conn:
            self._live_row(conn, run_id)
            return {"run_id": run_id, **results.summaries(conn, [run_id])[run_id]}

    def trials(self, run_id: str) -> list[dict]:
        with self.db.read() as conn:
            self._live_row(conn, run_id)
            stored: dict[str, dict] = {}
            # The same files /artifacts lists: recycled and purged ones are not counted.
            for trial_id, status, n in conn.execute(
                select(t.artifacts.c.trial_id, t.artifacts.c.status, func.count())
                .where(
                    t.artifacts.c.run_id == run_id,
                    t.artifacts.c.trial_id.is_not(None),
                    deleted.visible(t.artifacts.c.id, "artifact"),
                )
                .group_by(t.artifacts.c.trial_id, t.artifacts.c.status)
            ).all():
                stored.setdefault(trial_id, {})[status] = n
            rows = (
                conn.execute(
                    select(
                        t.trials,
                        t.tasks.c.task_key,
                        t.trial_results.c.raw_score,
                        t.trial_results.c.reward_valid,
                        t.trial_results.c.failure_cause,
                        t.trial_results.c.exception_type,
                        t.trial_results.c.verifier_status,
                        t.trial_results.c.policy_version,
                        t.trial_results.c.attempt_id.label("result_attempt_id"),
                    )
                    .join(t.tasks, t.tasks.c.id == t.trials.c.task_id)
                    .outerjoin(t.trial_results, t.trial_results.c.trial_id == t.trials.c.id)
                    .where(t.trials.c.run_id == run_id)
                    .order_by(t.tasks.c.task_key, t.trials.c.repetition_index)
                )
                .mappings()
                .all()
            )
            attempts: dict[str, list] = {}
            for a in conn.execute(
                select(t.execution_attempts)
                .join(t.trials, t.trials.c.id == t.execution_attempts.c.trial_id)
                .where(t.trials.c.run_id == run_id)
                .order_by(t.execution_attempts.c.attempt_index)
            ).mappings():
                attempts.setdefault(a["trial_id"], []).append(
                    {
                        "id": a["id"],
                        "attempt_index": a["attempt_index"],
                        "state": a["state"],
                        "phase": a["phase"],
                        "steps": a["steps_json"] or [],
                        "executor_ref": a["executor_ref_json"],
                        "started_at": a["started_at"],
                        "ended_at": a["ended_at"],
                        "error": a["error_json"],
                    }
                )
        return [
            {
                "id": r["id"],
                "task_id": r["task_id"],
                "task_key": r["task_key"],
                "repetition_index": r["repetition_index"],
                "state": r["state"],
                "phase": r["phase"],
                "reason_code": r["reason_code"],
                "artifact_state": r["artifact_state"],
                "artifact_counts": {
                    "available": stored.get(r["id"], {}).get("available", 0),
                    "failed": stored.get(r["id"], {}).get("failed", 0)
                    + stored.get(r["id"], {}).get("unavailable", 0),
                    "expired": stored.get(r["id"], {}).get("expired", 0)
                    + stored.get(r["id"], {}).get("deleting", 0),
                },
                "cleanup_state": r["cleanup_state"],
                "result": None
                if r["result_attempt_id"] is None
                else {
                    # null = no score; 0.0 = a real zero. Invalid rewards stay diagnostic.
                    "raw_score": r["raw_score"],
                    "reward_valid": r["reward_valid"],
                    "score": r["raw_score"] if r["state"] == TrialState.SCORED else None,
                    "failure_cause": r["failure_cause"],
                    "exception_type": r["exception_type"],
                    "verifier_status": r["verifier_status"],
                    "policy_version": r["policy_version"],
                    "attempt_id": r["result_attempt_id"],
                },
                "attempts": attempts.get(r["id"], []),
            }
            for r in rows
        ]

    # --- cancellation ---------------------------------------------------------

    def cancel(self, principal: Principal, run_id: str) -> dict:
        """Idempotent. Unclaimed trials end at once; claimed ones via the worker."""
        with self.db.write() as conn:
            row = self._row(conn, run_id)
            require_manage_owned(principal, row["owner_id"])
            if row["state"] in RUN_TERMINAL or row["stop_requested"]:
                counts, _ = run_counts(conn, run_id)
                return public_run(row, counts, principal)
            reason = "USER_CANCELLED" if row["owner_id"] == principal.user_id else "ADMIN_CANCELLED"
            conn.execute(
                update(t.runs)
                .where(t.runs.c.id == run_id)
                .values(stop_requested=True, stop_reason=reason)
            )
            if row["lease_token"] is None:
                # Never claimed: nothing executes, so finish it here.
                finish_unstarted(conn, run_id, TrialState.NOT_STARTED, reason)
                finalize(conn, run_id, reason, cleanup=CleanupState.NOT_REQUIRED)
            audit.record(
                conn,
                principal,
                "run.cancel",
                object_type="run",
                object_id=run_id,
                detail={"reason": reason},
            )
            row = self._row(conn, run_id)
            counts, _ = run_counts(conn, run_id)
            return public_run(row, counts, principal)


def finish_unstarted(conn: Connection, run_id: str, state: TrialState, reason: str) -> None:
    at = clock.to_text(clock.now())
    conn.execute(
        update(t.trials)
        .where(t.trials.c.run_id == run_id, t.trials.c.state == TrialState.QUEUED)
        .values(
            state=state,
            reason_code=reason,
            execution_terminal_at=at,
            cleanup_state=CleanupState.NOT_REQUIRED,
        )
    )
    conn.execute(
        update(t.work_items)
        .where(
            t.work_items.c.trial_id.in_(select(t.trials.c.id).where(t.trials.c.run_id == run_id))
        )
        .values(state="done")
    )


def finalize(conn: Connection, run_id: str, stop_reason: str | None, cleanup: CleanupState):
    """Close a run whose trials are all terminal: lifecycle, Operation and dimensions."""
    from maestro.domain.states import operation_status_for, terminal_run_state

    counts, states = run_counts(conn, run_id)
    if any(s not in TRIAL_TERMINAL for s in states):
        raise RuntimeError("finalize with non-terminal trials")
    state = terminal_run_state(counts, stop_reason)
    run = conn.execute(select(t.runs).where(t.runs.c.id == run_id)).mappings().one()
    artifact_states = set(
        conn.execute(select(t.trials.c.artifact_state).where(t.trials.c.run_id == run_id)).scalars()
    )
    artifact = (
        ArtifactState.FAILED
        if artifact_states == {ArtifactState.FAILED}
        else ArtifactState.PARTIAL
        if ArtifactState.FAILED in artifact_states
        else ArtifactState.COMPLETE
    )
    at = clock.to_text(clock.now())
    conn.execute(
        update(t.runs)
        .where(t.runs.c.id == run_id)
        .values(
            state=state,
            finished_at=at,
            stop_reason=stop_reason,
            artifact_state=artifact,
            cleanup_state=cleanup,
            lease_token=None,
            queue_reason=None,
        )
    )
    stamp_expiry(conn, run_id)
    status = operation_status_for(state, counts)
    operations.advance(
        conn,
        run["operation_id"],
        status=status,
        phase=state.value,
        progress={k: counts[k] for k in ("planned", "terminal", "scored", "errors", "active")},
        result={"run_id": run_id, "state": state.value, "counts": counts},
        error=(
            {"code": "ALL_TRIALS_FAILED", "message": "No trial produced a valid score"}
            if status == OperationStatus.FAILED
            else None
        ),
    )
