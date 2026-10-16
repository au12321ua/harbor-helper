"""Record-local observation failures; these projections never authorize execution/actions."""

import errno
import json
from pathlib import Path

from harbor_helper.persistence.files import read_json
from harbor_helper.service.primitives import ServiceError

BINDING_FIELDS = (
    "name",
    "dataset_name",
    "submitter",
    "user_id",
    "model_profile",
    "attachment_id",
    "attachment_version_id",
    "bundle_id",
    "bundle_digest",
    "attachment_lineage",
)


def local_file_error(path, error):
    return (
        error.errno
        in {errno.ENOENT, errno.ENOTDIR, errno.EISDIR, errno.EACCES, errno.EPERM, errno.ELOOP}
        and error.filename is not None
        and Path(error.filename).absolute().is_relative_to(path)
    )


def unavailable():
    return ServiceError(
        "run_metadata_unavailable", "Run metadata unavailable; evidence withheld", 409
    )


def text(value):
    if not isinstance(value, str):
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


def read_manifest(store, run_id):
    path = store.path(run_id)  # Identity/SQLite failures are not observation fallbacks.
    try:
        value = read_json(path / "manifest.json")
    except ValueError:
        raise unavailable() from None
    except OSError as error:
        if not local_file_error(path, error):
            raise
        raise unavailable() from None
    effective = value.get("effective") if isinstance(value, dict) else None
    binding = value.get("service") if isinstance(value, dict) else None
    if (
        not isinstance(effective, dict)
        or any(not text(effective.get(k)) or not effective[k] for k in ("agent", "dataset"))
        or (binding is not None and not isinstance(binding, dict))
        or any(not text(v) for k in BINDING_FIELDS if (v := (binding or {}).get(k)) is not None)
    ):
        raise unavailable()
    return value


def recovered_metadata(store, run_id):
    # Link by persisted run identity, never by a current viewer or a display name.
    with store.connect() as db:
        rows = db.execute(
            "SELECT user_id,submitter,frozen FROM submissions "
            "WHERE run_id=? OR (run_id IS NULL AND target_id=?) ORDER BY created",
            (run_id, run_id),
        ).fetchall()
    effective, binding = {}, {}
    # Ambiguous ownership is unknown; do not choose an arbitrary submission.
    if len(rows) == 1:
        row = rows[0]
        try:
            frozen = json.loads(row["frozen"])
        except (ValueError, TypeError):
            frozen = None
        if isinstance(frozen, dict):
            effective = frozen.get("effective") or {}
            binding = frozen.get("service") or {}
        if not isinstance(effective, dict):
            effective = {}
        if not isinstance(binding, dict):
            binding = {}
        binding = {k: v for k in BINDING_FIELDS if text(v := binding.get(k))}
        binding.update(user_id=row["user_id"], submitter=row["submitter"])
    else:
        binding = {}
    return {
        "effective": {
            k: v if text(v := effective.get(k)) and v else "unknown" for k in ("agent", "dataset")
        },
        "service": binding,
    }
