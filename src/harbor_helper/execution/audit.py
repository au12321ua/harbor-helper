"""Audit execution responsibility."""

import subprocess
import time

from harbor_helper.execution.resources import cleanup, stop_group
from harbor_helper.persistence import statuses as lifecycle_status
from harbor_helper.persistence.files import read_json, write_json
from harbor_helper.results.reports import report
from harbor_helper.security.credentials import (
    audit_run,
    redact_value,
    scrub_file,
    scrub_run,
)
from harbor_helper.security.master_key import MasterUnavailable


def audit_finished(store, row):
    with store.evidence(row["id"]):
        return _audit_finished(store, row)


def _audit_finished(store, row):
    """Publish evidence only with a complete audit; never reserve execution capacity."""
    secrets = []
    audit = None
    try:
        path = store.path(row["id"])
        manifest = read_json(path / "manifest.json")
        cfg = manifest["effective"]
        from harbor_helper.service.data import ServiceData

        key = ServiceData(store.root).run_key(row["id"], execution=False)
        if key:
            secrets.append(key)
        if cfg["agent"] == "opencode" and cfg["model"].get("credential_env") and not secrets:
            raise RuntimeError("Credential audit source unavailable")
        redact_files(path, secrets)
        scrub_file(store.root / "supervisor.log", secrets)
        audit = audit_run(store, row["id"], secrets)
        audit["audit_complete"] = True
        write_json(path / "credential-audit.json", audit)
        if not audit["clean"]:
            raise RuntimeError("Credential audit not clean; raw evidence withheld")
        report(store, row["id"])
        from harbor_helper.service.materials import inventory

        inventory(store, row["id"])
    except MasterUnavailable:
        raise
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired):
        # Third-party exceptions can carry unavailable secrets. Persist a fixed,
        # actionable message rather than potentially unsafe original exception text.
        store.update(
            row["id"],
            audit_status=lifecycle_status.INCOMPLETE,
            audit_reason="Evidence audit incomplete; affected logs and artifacts withheld",
        )
        path = store.path(row["id"])
        try:
            if audit is None:
                write_json(
                    path / "credential-audit.json",
                    {"clean": False, "audit_complete": False, "reason": "Audit source unavailable"},
                )
            (path / "report.json").unlink(missing_ok=True)
        except OSError:
            pass  # Database audit_status still withholds evidence; queue keeps advancing.
        return False
    store.update(row["id"], audit_status=lifecycle_status.CLEAN, audit_reason=None)
    return True


def finish(store, row, status, reason):
    if not row.get("finish_status"):
        store.update(row["id"], finish_status=status, finish_reason=reason)
        row = store.get(row["id"])
    try:
        stop_group(row)
        cleanup(store.path(row["id"]))
    except MasterUnavailable:
        raise
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired):
        store.update(
            row["id"],
            status=lifecycle_status.CLEANUP_BLOCKED,
            reason="Execution resource cleanup unconfirmed; capacity retained",
        )
        return
    # Capacity release depends solely on resource cleanup. Evidence may remain
    # unavailable independently and can be audited again after restoring its key.
    store.update(
        row["id"],
        status=row["finish_status"],
        reason=redact_value(row["finish_reason"], []),
        finished=time.time(),
    )
    audit_finished(store, store.get(row["id"]))


def redact_files(path, secrets):
    scrub_run(path, secrets)
