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
    "attachment_download": "attachment_download",
    "managed_requests": "read",
    "managed_datasets": "read",
    "rename_group": ("recycle_own", "recycle_all"),
    "recycle_list": ("recycle_own", "recycle_all"),
    "recycle_preview": ("recycle_own", "recycle_all"),
    "recycle_move": ("recycle_own", "recycle_all"),
    "recycle_restore": ("recycle_own", "recycle_all"),
    "recycle_purge": "purge",
    "dataset_versions": "datasets_manage",
    "dataset_preview": "datasets_manage",
    "dataset_confirm": "datasets_manage",
    "dataset_default": "datasets_manage",
    "dataset_merge_preview": "datasets_manage",
    "dataset_merge": "datasets_manage",
    "inspect_author_inputs": "datasets_manage",
    "save_author_inputs": "datasets_manage",
    "save_catalog": "datasets_manage",
    "verify_catalog": "datasets_manage",
    "delete_artifact": "recycle_all",
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

SCHEMA_OPERATIONS.update(
    {
        "attachment_download",
        "managed_requests",
        "rename_group",
        "managed_datasets",
        "dataset_versions",
        "dataset_preview",
        "dataset_confirm",
        "dataset_default",
        "dataset_merge_preview",
        "dataset_merge",
        "recycle_list",
        "recycle_preview",
        "recycle_move",
        "recycle_restore",
        "recycle_purge",
        "inspect_author_inputs",
        "save_author_inputs",
        "save_catalog",
    }
)


def authorize(user, operation):
    if not user.get("access_credential_id"):
        return
    if operation == "me":
        return  # Authentication identity only; no shared data or new authorization.
    needed = CAPABILITIES.get(operation)
    if needed is None:
        raise ServiceError("session_required", "This operation requires a browser session", 403)
    alternatives = {needed} if isinstance(needed, str) else set(needed)
    if not alternatives.intersection(user["scopes"]):
        raise ServiceError("scope_required", f"Automation capability required: {needed}", 403)
