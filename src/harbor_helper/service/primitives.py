"""Service values, validation and errors; no persistence or application imports."""

import json
import re

LIMITS = {
    "max_jobs": 1,
    "max_trials": 2,
    "max_queue": 100,
    "max_pending_per_member": 10,
    "max_attempts": 3,
    "max_wall_seconds": 3600,
    "max_cpus_per_trial": 2,
    "max_memory_mb_per_trial": 4096,
    "max_upload_bytes": 16 * 1024 * 1024,
    "log_retention_days": 14,
    "artifact_retention_days": 7,
}


class ServiceError(ValueError):
    def __init__(self, code, message, status=422):
        self.code, self.status = code, status
        self.operation_id = None
        super().__init__(message)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
        raise ServiceError("invalid_id", "Use a 1–64 character identifier (letters, digits, . _ -)")
    return value


def secret_value(value):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 16384
        or any(c.isspace() or ord(c) < 32 for c in value)
    ):
        raise ServiceError("invalid_key", "A nonempty single-line credential is required")
    return value


def public_user(row):
    return {
        **dict(row),
        "enabled": bool(row["enabled"]),
        **(
            {"evidence_grant": bool(row["evidence_grant"])} if "evidence_grant" in dict(row) else {}
        ),
    }


def public_object(row):
    return {**json.loads(row["config"]), "id": row["id"], "version": row["version"]}
