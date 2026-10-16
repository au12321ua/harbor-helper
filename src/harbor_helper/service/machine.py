"""Versioned, allowlisted machine views; no internal admin OpenAPI is published."""

from harbor_helper.persistence.store import TERMINAL
from harbor_helper.service.admission import readiness
from harbor_helper.service.dtos import AuditAxis, MachineState, ReportAxis, ResourceAxis, SafeReport
from harbor_helper.service.observation import scheduler
from harbor_helper.service.policy import CAPABILITIES
from harbor_helper.service.primitives import ServiceError
from harbor_helper.service.run_metadata import read_manifest
from harbor_helper.service.views import public_submission, safe_view


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
    summary = app.summary(row)
    try:
        binding = read_manifest(app.store, run_id).get("service") or {}
    except ServiceError as error:
        if error.code != "run_metadata_unavailable":
            raise
        binding = {}  # Observation only; never infer an access credential.

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
    audit = summary["audit_status"]
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
        user_id=summary["user_id"],
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
        row = db.execute(
            "SELECT id FROM submissions WHERE user_id=? AND idem=? AND operation=?",
            (user["id"], key, operation),
        ).fetchone()
    if not row:
        raise ServiceError(
            "idempotency_missing", "Key not observed; resend original body with original key", 404
        )

    return public_submission(app.data.submission(row[0]))


def discovery(app, user):

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
    if code in {"report_blocked", "audit_incomplete"}:
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


def accepted_view(user, value):
    if user.get("access_credential_id"):
        value = {
            **value,
            "diagnosis": None,
            "retry_changes": {k: {"changed": True} for k in value.get("retry_changes", {})},
        }

    return safe_view(value)
