"""Reviewed automation operation policy; unknown operations require a session."""

from harbor_helper.service.primitives import ServiceError

CAPABILITIES = {
    "evidence_manifest": "evidence",
    "evidence_package": "evidence",
    "evidence_file": "evidence",
    "operation_history": "read",
    "access_capabilities": "read",
    "logs": "read",
    "artifact": "read",
    "attachment_lookup": "attachments",
    "attachments": "read",
    "cancel": "cancel_own",
    "cancel_submission": "cancel_own",
    "catalog": "read",
    "compare": "read",
    "create_attachment": "attachments",
    "derive_attachment": "attachments",
    "discovery": "read",
    "download_report": "read",
    "lookup_submission": "execute",
    "machine_compare": "read",
    "machine_report": "read",
    "machine_run": "read",
    "machine_schema": "read",
    "machine_submission": "read",
    "me": "read",
    "publish_attachment": "attachments",
    "readiness": "read",
    "recover_submission": "execute",
    "report": "read",
    "rerun": "execute",
    "retry_run": "execute",
    "run": "read",
    "runs": "read",
    "submission": "read",
    "submit": "execute",
    "task_catalog": "read",
    "update_attachment": "attachments",
    "update_attachment_version": "attachments",
    "usage": "read",
}

SCHEMA_OPERATIONS = {
    "operation_history",
    "evidence_manifest",
    "update_attachment_version",
    "attachment_lookup",
    "machine_report",
    "machine_run",
    "derive_attachment",
    "machine_submission",
    "update_attachment",
    "create_attachment",
    "rerun",
    "cancel_submission",
    "task_catalog",
    "machine_schema",
    "discovery",
    "lookup_submission",
    "attachments",
    "retry_run",
    "readiness",
    "cancel",
    "recover_submission",
    "machine_compare",
    "publish_attachment",
    "submit",
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
