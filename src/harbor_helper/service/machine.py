"""Versioned, allowlisted machine views; no internal admin OpenAPI is published."""

import math
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from harbor_helper.persistence.files import read_json
from harbor_helper.persistence.store import TERMINAL
from harbor_helper.service.attachment_contracts import AttachmentIdentity, AttachmentVersion
from harbor_helper.service.data import ServiceError

Operation = Literal["submit", "rerun", "retry", "recover"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AccessIssue(Input):
    name: str = Field(min_length=1, max_length=128)
    current_password: SecretStr
    scopes: list[Literal["read", "attachments", "execute", "cancel_own"]] = ["read"]
    expires: float | None = None


class SubmissionInput(Input):
    dataset: str | None = None
    dataset_id: str | None = None
    model_profile: str | None = None
    agent: Literal["oracle", "opencode"] | None = None
    bundle_id: str | None = None
    attachment_version_id: str | None = None
    attempts: int | None = Field(default=None, ge=1)
    concurrency: int | None = Field(default=None, ge=1)
    wall_seconds: int | None = Field(default=None, ge=1)
    environment_build_timeout_multiplier: int | None = Field(default=None, ge=1)
    task: str | None = None
    name: str | None = Field(default=None, max_length=128)


class EmptyInput(Input):
    pass


class RetryInput(Input):
    wall_seconds: int | None = Field(default=None, ge=1)


class Axis(BaseModel):
    state: str
    reason: str


class ResourceAxis(Axis):
    state: Literal["active", "released", "cleanup_blocked", "unknown"]


class AuditAxis(Axis):
    state: Literal["pending", "clean", "incomplete"]


class ReportAxis(Axis):
    state: Literal["pending", "available", "blocked", "unavailable"]


class AttachmentBinding(BaseModel):
    attachment_id: str | None = None
    attachment_version_id: str | None = None
    bundle_id: str | None = None
    bundle_digest: str | None = None
    attachment_lineage: str | None = None


class MachineState(BaseModel):
    contract_version: Literal["1.0"] = "1.0"
    kind: Literal["submission", "run"]
    id: str
    status: str
    user_id: str | None = None
    access_credential_id: str | None = None
    run_id: str | None = None
    parent: str | None = None
    resource: ResourceAxis
    audit: AuditAxis
    report: ReportAxis
    poll_after_seconds: int | None = None
    report_url: str | None = None
    attachment: AttachmentBinding


# Every old route that an automation principal may call is listed explicitly.
# Unknown/new routes default to session-only until their capability is reviewed.
READ = {
    "me",
    "catalog",
    "usage",
    "runs",
    "submission",
    "run",
    "download_report",
    "report",
    "compare",
    "attachments",
    "discovery",
    "readiness",
    "machine_schema",
    "task_catalog",
    "lookup_submission",
    "machine_run",
    "machine_submission",
    "machine_report",
}
ATTACHMENTS = {
    "upload",
    "attachment_lookup",
    "create_attachment",
    "publish_attachment",
    "derive_attachment",
    "register_attachment",
    "update_attachment",
    "update_attachment_version",
}
EXECUTE = {"submit", "recover_submission", "rerun", "retry_run"}
CANCEL = {"cancel", "cancel_submission"}
CAPABILITIES = {
    **dict.fromkeys(READ, "read"),
    **dict.fromkeys(ATTACHMENTS, "attachments"),
    **dict.fromkeys(EXECUTE, "execute"),
    **dict.fromkeys(CANCEL, "cancel_own"),
}


def authorize(user, operation):
    if not user.get("access_credential_id"):
        return
    if operation == "me":
        return  # Authentication identity only; no shared data or new authorization.
    needed = CAPABILITIES.get(operation)
    if needed is None:
        raise ServiceError("session_required", "This operation requires a browser session", 403)
    if needed not in user["scopes"]:
        raise ServiceError("scope_required", f"Automation capability required: {needed}", 403)


def scheduler(app):
    from harbor_helper.execution.runs import scheduler_identity

    try:
        identity = scheduler_identity(app.store)
        if not identity:
            return {
                "state": "unavailable",
                "reason": "process_not_confirmed",
                "observed": time.time(),
            }
        heartbeat = identity.get("observed")
        valid = type(heartbeat) in {int, float} and math.isfinite(heartbeat)
        ready = valid and 0 <= time.time() - heartbeat <= 10
        return {
            "state": "ready" if ready else "unknown",
            "reason": "recent_activity" if ready else "activity_unknown",
            "observed": time.time(),
            "activity_observed": heartbeat if valid else None,
        }
    except (ValueError, OSError, KeyError, TypeError):
        return {"state": "unknown", "reason": "observation_unavailable", "observed": time.time()}


def attachment(binding):
    return {
        k: binding.get(k)
        for k in (
            "attachment_id",
            "attachment_version_id",
            "bundle_id",
            "bundle_digest",
            "attachment_lineage",
        )
    }


def run_state(app, run_id):
    row = app.store.get(run_id)
    manifest = read_json(app.store.path(run_id) / "manifest.json")
    binding = manifest.get("service") or {}
    status = row["status"]
    resource = (
        "active"
        if status in {"starting", "running", "cancelling"}
        else "cleanup_blocked"
        if status == "cleanup_blocked"
        else "released"
        if status in TERMINAL or status == "queued"
        else "unknown"
    )
    audit = app.summary(row)["audit_status"]
    audit = audit if audit in {"pending", "clean", "incomplete"} else "pending"
    report, reason = "blocked", "resource_unconfirmed"
    if audit == "incomplete":
        reason = "audit_incomplete"
    elif status not in TERMINAL:
        if resource == "cleanup_blocked":
            reason = "cleanup_blocked"
        elif scheduler(app)["state"] == "ready":
            report, reason = "pending", "execution_in_progress"
        else:
            reason = "execution_progress_unknown"
    elif resource == "released" and audit == "clean":
        # Call the original gate: file presence alone never publishes a report.
        try:
            value = app.safe_report(run_id)
            report, reason = (
                ("available", "safe_report")
                if value is not None
                else ("unavailable", "missing_report")
            )
        except (ServiceError, ValueError, OSError):
            reason = "safe_report_unavailable"
    elif audit == "pending":
        report, reason = (
            ("pending", "audit_in_progress")
            if scheduler(app)["state"] == "ready"
            else ("blocked", "audit_progress_unknown")
        )
    return MachineState(
        kind="run",
        id=run_id,
        status=status,
        user_id=binding.get("user_id"),
        access_credential_id=binding.get("access_credential_id"),
        run_id=run_id,
        parent=row.get("parent"),
        resource=ResourceAxis(state=resource, reason="execution_lifecycle"),
        audit=AuditAxis(state=audit, reason="original_audit"),
        report=ReportAxis(state=report, reason=reason),
        attachment=attachment(binding),
        poll_after_seconds=2 if report == "pending" else None,
        report_url=f"/api/v1/machine/runs/{run_id}/report" if report == "available" else None,
    ).model_dump()


def submission_state(app, submission_id):
    row = app.data.submission(submission_id)
    run_id = row.get("run_id")
    if not run_id:
        with app.store.connect() as db:
            if db.execute("SELECT 1 FROM runs WHERE id=?", (row["target_id"],)).fetchone():
                run_id = row["target_id"]
    if run_id:
        value = run_state(app, run_id)
        return {
            **value,
            "kind": "submission",
            "id": submission_id,
            "status": row["status"],
            "run_id": run_id,
        }
    report, reason = (
        ("unavailable", "preparation_failed")
        if row["status"] == "failed"
        else (
            ("unavailable", "cancelled_before_run")
            if row["status"] == "cancelled"
            else (
                ("pending", "preparing")
                if scheduler(app)["state"] == "ready"
                else ("blocked", "preparation_progress_unknown")
            )
        )
    )
    return MachineState(
        kind="submission",
        id=submission_id,
        status=row["status"],
        user_id=row["user_id"],
        access_credential_id=row["frozen"]["service"].get("access_credential_id"),
        parent=row.get("parent"),
        resource=ResourceAxis(state="released", reason="not_allocated"),
        audit=AuditAxis(state="pending", reason="not_started"),
        report=ReportAxis(state=report, reason=reason),
        poll_after_seconds=2 if report == "pending" else None,
        attachment=attachment(row["frozen"].get("service", {})),
    ).model_dump()


def lookup(app, user, operation, key):
    if operation not in {"submit", "rerun", "retry", "recover"} or not 1 <= len(key) <= 128:
        raise ServiceError("invalid_lookup", "Use a fixed operation and original key")
    if user.get("access_credential_id") and "execute" not in user["scopes"]:
        raise ServiceError("scope_required", "Automation capability required: execute", 403)
    with app.store.connect() as db:
        rows = db.execute(
            "SELECT id FROM submissions WHERE user_id=? AND idem=? AND "
            "(operation=? OR operation LIKE ?)",
            (user["id"], key, operation, operation + ":%"),
        ).fetchall()
    if not rows:
        raise ServiceError(
            "idempotency_missing", "Key not observed; resend original body with original key", 404
        )
    if len(rows) != 1:
        raise ServiceError(
            "legacy_key_ambiguous", "Legacy key has multiple targets; query original record ID", 409
        )
    from harbor_helper.service.application import public_submission

    return public_submission(app.data.submission(rows[0][0]))


def discovery(app, user):
    from harbor_helper.service.admission import readiness

    catalog = app.configuration.catalog()
    datasets = [
        {k: d.get(k) for k in ("id", "name", "version", "enabled", "status", "ready", "checked")}
        for d in catalog["datasets"]
    ]
    profiles = [
        {k: p.get(k) for k in ("id", "version", "name", "model", "enabled")}
        for p in app.data.objects("profile")
    ]
    scopes = user.get("scopes", ["read", "attachments", "execute", "cancel_own"])
    return {
        "contract_version": "1.0",
        "datasets": datasets,
        "model_profiles": profiles,
        **app.attachments.catalog(),
        "limits": app.data.limits(),
        "scheduler": scheduler(app),
        "readiness": readiness(app, user["id"]),
        "allowed_operations": sorted(
            k for k, v in CAPABILITIES.items() if v in scopes or k == "me"
        ),
        "scopes": scopes,
        "task_selection": {
            "catalog_url": "/api/v1/machine/datasets/{id}/tasks",
            "offset": 0,
            "limit_max": 100,
            "selector": "glob matching task name; omit for entire dataset",
        },
        "schema_url": "/api/v1/machine/schema",
        "cost": "unknown",
        "limitations": [
            "trusted_team",
            "no_admin_automation",
            "discovery_is_not_execution_readiness",
            "explicit_attachment_version_or_none",
        ],
    }


def error_action(code, status):
    if code == "idempotency_missing":
        return "retry_same_request"
    if code in {"report_blocked", "audit_incomplete", "legacy_key_ambiguous"}:
        return "contact_admin"
    if code == "report_unavailable":
        return "explicit_new_attempt"
    if code == "scope_required":
        return "reauthorize"
    if status == 401:
        return "reauthorize"
    if code in {"report_pending", "audit_pending"}:
        return "poll_existing"
    if code in {"queue_full", "service_unavailable", "source_network"} or status in {429, 503}:
        return "retry_same_request"
    if code in {"recovery_state", "rerun_state"}:
        return "explicit_new_attempt"
    if status in {403, 500} or code in {"audit_incomplete", "credential_unavailable"}:
        return "contact_admin"
    return "fix_input"


class Accepted(BaseModel):
    id: str
    user_id: str | None = None
    access_credential_id: str | None = None
    submitter: str
    operation: str
    request: SubmissionInput | RetryInput
    run_id: str | None
    status: str
    created: float
    error: str | None
    parent: str | None
    attachment: AttachmentBinding
    diagnosis: dict | None = None
    retry_changes: dict = {}
    execution_mode: str
    legacy_override_removed: bool


class DatasetInfo(BaseModel):
    id: str
    name: str
    version: int
    enabled: bool
    status: str
    ready: bool
    checked: float | None = None


class ModelInfo(BaseModel):
    id: str
    version: int
    name: str | None = None
    model: str
    enabled: bool


class MaintenanceInfo(BaseModel):
    paused: bool
    reason: str
    retry_at: float | None
    updated: float | None


class Readiness(BaseModel):
    initialized: bool
    accepting: bool
    reason: str
    observed: float
    scheduler: "SchedulerInfo"
    maintenance: MaintenanceInfo
    pending: dict[str, int]


class SchedulerInfo(BaseModel):
    state: Literal["ready", "unavailable", "unknown"]
    reason: str
    observed: float
    activity_observed: float | None = None


class AttachmentEntry(AttachmentIdentity):
    versions: list[AttachmentVersion]


class LegacyBundle(BaseModel):
    id: str
    digest: str
    created: float
    creator: Literal["unknown"]
    legacy: Literal[True]


class Discovery(BaseModel):
    contract_version: Literal["1.0"]
    datasets: list[DatasetInfo]
    model_profiles: list[ModelInfo]
    attachments: list[AttachmentEntry]
    legacy_bundles: list[LegacyBundle]
    limits: dict[str, int]
    scheduler: SchedulerInfo
    readiness: Readiness
    allowed_operations: list[str]
    scopes: list[str]
    task_selection: dict
    schema_url: str
    cost: Literal["unknown"]
    limitations: list[str]


class TaskInfo(BaseModel):
    name: str
    package: str | None = None
    ref: str | None = None


class TaskCatalog(BaseModel):
    dataset_id: str
    version: int
    status: str
    offset: int
    tasks: list[TaskInfo]
    next_offset: int | None
    total: int


class AttemptReport(BaseModel):
    task: str
    trial: str | None = None
    valid: bool
    rewards: dict[str, float] | None = None
    failure: Literal["missing_score", "execution_failure", "unknown"] | None = None


class TaskReport(BaseModel):
    task: str
    expected_attempts: int
    valid_attempts: int
    observed_attempts: int
    mean_rewards: dict[str, float] | None
    attempts: list[AttemptReport]


class SafeReport(BaseModel):
    contract_version: Literal["1.0"] = "1.0"
    run_id: str
    status: str
    complete: bool
    expected_attempts: int
    valid_attempts: int
    invalid_attempts: int
    missing_attempts: int
    tasks: list[TaskReport]
    unexpected_trials: list[AttemptReport] = []


def report_view(value):
    def attempt(a):
        exception = a.get("exception")
        missing = isinstance(exception, dict) and exception.get("exception_type") == "MissingReward"
        return {
            "task": a["task"],
            "trial": a.get("trial"),
            "valid": a["valid"],
            "rewards": a.get("rewards"),
            "failure": None
            if a["valid"]
            else "missing_score"
            if missing
            else "execution_failure"
            if exception
            else "unknown",
        }

    return SafeReport(
        **{
            k: value[k]
            for k in (
                "run_id",
                "status",
                "complete",
                "expected_attempts",
                "valid_attempts",
                "invalid_attempts",
                "missing_attempts",
            )
        },
        tasks=[
            {
                **{
                    k: t[k]
                    for k in (
                        "task",
                        "expected_attempts",
                        "valid_attempts",
                        "observed_attempts",
                        "mean_rewards",
                    )
                },
                "attempts": [attempt(a) for a in t["attempts"]],
            }
            for t in value["tasks"]
        ],
        unexpected_trials=[attempt(a) for a in value.get("unexpected_trials", [])],
    ).model_dump()


SCHEMA_OPERATIONS = {
    "discovery",
    "readiness",
    "machine_schema",
    "task_catalog",
    "lookup_submission",
    "machine_run",
    "machine_submission",
    "machine_report",
    "submit",
    "rerun",
    "retry_run",
    "recover_submission",
    "cancel",
    "cancel_submission",
    "attachments",
    "attachment_lookup",
    "create_attachment",
    "publish_attachment",
    "derive_attachment",
    "register_attachment",
    "update_attachment",
    "update_attachment_version",
    "compare",
}
CAPABILITIES["lookup_submission"] = "execute"


def accepted_view(user, value):
    if user.get("access_credential_id"):
        value = {
            **value,
            "diagnosis": None,
            "retry_changes": {k: {"changed": True} for k in value.get("retry_changes", {})},
        }
    from harbor_helper.service.application import safe_view

    return safe_view(value)


class CompareInput(Input):
    left: str
    right: str


class CancelResult(BaseModel):
    run_id: str
    cancel_requested: bool
    status: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str
    retryable: bool
    action: Literal[
        "retry_same_request",
        "poll_existing",
        "fix_input",
        "reauthorize",
        "contact_admin",
        "explicit_new_attempt",
    ]
    wait_seconds: int | None
    wait_known: bool
    poll_after_seconds: int | None
    related_ids: dict[str, str]


class AttachmentCatalog(BaseModel):
    attachments: list[AttachmentEntry]
    legacy_bundles: list[LegacyBundle]


class Updated(BaseModel):
    updated: bool


class MetricDelta(BaseModel):
    task: str
    left: dict[str, float]
    right: dict[str, float]
    delta: dict[str, float]


class CompareAttachment(BaseModel):
    kind: Literal["versioned", "legacy/unknown", "none"]
    attachment_version_id: str | None
    bundle_id: str | None
    digest: str | None


class Changed(BaseModel):
    changed: Literal[True] = True


class Comparison(BaseModel):
    left: str
    right: str
    comparable: bool
    reasons: list[str]
    config_changes: dict[str, Changed]
    bundle_change: dict[str, str | None]
    attachment_inputs: dict[str, CompareAttachment]
    tasks: list[MetricDelta]
    mean_task_delta: dict[str, float] | None


CAPABILITIES["machine_compare"] = "read"
SCHEMA_OPERATIONS.discard("compare")
SCHEMA_OPERATIONS.add("machine_compare")


class BundleResult(BaseModel):
    id: str
    digest: str


SCHEMA_OPERATIONS.add("upload")
