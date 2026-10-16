from harbor_helper.security.credentials import redact_value


def public_submission(value):
    return {
        "attachment": {
            k: value.get("frozen", {}).get("service", {}).get(k)
            for k in (
                "attachment_id",
                "attachment_version_id",
                "bundle_id",
                "bundle_digest",
                "attachment_lineage",
            )
        },
        "user_id": value.get("user_id"),
        "access_credential_id": value.get("frozen", {})
        .get("service", {})
        .get("access_credential_id"),
        "diagnosis": value.get("frozen", {}).get("service", {}).get("author_input_issues"),
        "retry_changes": value.get("frozen", {}).get("service", {}).get("retry_changes", {}),
        **{
            k: value[k]
            for k in (
                "id",
                "submitter",
                "operation",
                "request",
                "run_id",
                "status",
                "created",
                "error",
                "parent",
            )
        },
    }


def safe_view(value):
    if isinstance(value, dict):
        return {
            k: safe_view(v)
            for k, v in value.items()
            if k not in {"evidence", "artifacts", "manifest", "raw_results", "worker_log", "python"}
        }
    if isinstance(value, list):
        return [safe_view(v) for v in value]
    return redact_value(value, []) if isinstance(value, str) else value
