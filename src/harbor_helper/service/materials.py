"""Persistent run-local material inventory and verified, short-lived download snapshots."""

import hashlib
import json
import stat
import tempfile
import time
import zipfile

from harbor_helper.persistence.files import read_json, write_json
from harbor_helper.persistence.store import TERMINAL
from harbor_helper.security.local_paths import LocalRoot
from harbor_helper.service.access import require_evidence
from harbor_helper.service.primitives import ServiceError

# Only explicit run inputs/outputs. Never traverse service state or native XDG stores.
SNAPSHOT_SECONDS = 30

TOP_FILES = {
    "manifest.json",
    "job.json",
    "worker.log",
    "report.json",
    "credential-audit.json",
    "projects.json",
    "trials.json",
    "worker-runtime.json",
    "outcome.json",
}
ROOTS = {"harbor", "tasks", "bundle"}
EXCLUDED = {"auth.json", "auth.db", "credentials.json", ".env", "opencode.db"}


def category(relative):
    if relative.name in {"opencode.txt", "trajectory.json"}:
        return "agent_session"
    if "artifacts" in relative.parts:
        return "artifact"
    if "verifier" in relative.parts:
        return "verification"
    if relative.parts[0] in {"tasks", "bundle"} or relative.name in {"manifest.json", "job.json"}:
        return "fixed_input"
    return "execution_log"


def inventory(store, run_id):
    """Called after terminal scrub; hashes are of the final deliverable bytes."""
    root = store.path(run_id)
    prior = read_json(root / "materials.json") if (root / "materials.json").exists() else None
    previous = {item["name"]: item for item in prior["files"]} if prior else {}
    processing = (
        read_json(root / "material-processing.json")
        if (root / "material-processing.json").exists()
        else []
    )
    files: list[dict] = []
    with_local = LocalRoot(root)
    try:
        for file in sorted(root.rglob("*")):
            relative = file.relative_to(root)
            if relative.parts[0] not in ROOTS and relative.as_posix() not in TOP_FILES:
                continue
            if any(p in EXCLUDED or p in {".config", ".local", ".cache"} for p in relative.parts):
                continue
            if file.is_symlink():
                raise ServiceError("audit_incomplete", "Symlink in material collection", 409)
            if not file.is_file():
                continue
            with with_local.parent(relative) as (fd, name):
                import os

                opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(opened, "rb") as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise ServiceError("audit_incomplete", "Nonregular material file", 409)
                    sha, size = hashlib.sha256(), 0
                    while chunk := stream.read(65536):
                        sha.update(chunk)
                        size += len(chunk)
            old = previous.pop(relative.as_posix(), None)
            files.append(
                {
                    "id": old["id"] if old else __import__("uuid").uuid4().hex,
                    "name": relative.as_posix(),
                    "category": category(relative),
                    "bytes": size,
                    "sha256": sha.hexdigest(),
                    "status": "redacted" if relative.as_posix() in processing else "original",
                    "source": "run_local",
                    "processing": "exact-secret replacement; delivered bytes differ from original"
                    if relative.as_posix() in processing
                    else None,
                }
            )
    finally:
        with_local.close()
    for old in previous.values():
        files.append({**old, "status": "missing"})
    # Event presence is not proof of complete session coverage. Report observed fields explicitly.
    session = []
    for item in files:
        if item["name"].endswith("opencode.txt"):
            valid, tool_inputs, tool_outputs = 0, 0, 0
            with (root / item["name"]).open(errors="replace") as stream:
                for line in stream:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    valid += 1
                    part = event.get("part") or {}
                    state = part.get("state") or {}
                    if event.get("type") == "tool_use":
                        tool_inputs += int("input" in state)
                        tool_outputs += int("output" in state)
            trajectory = root / item["name"]
            trajectory = trajectory.with_name("trajectory.json")
            prompt = False
            paired = True
            try:
                steps = read_json(trajectory).get("steps", [])
                prompt = any(step.get("source") == "user" and step.get("message") for step in steps)
                for step in steps:
                    returned = {
                        entry.get("source_call_id")
                        for entry in (step.get("observation") or {}).get("results", [])
                    }
                    paired &= all(
                        call.get("tool_call_id") in returned for call in step.get("tool_calls", [])
                    )
            except (OSError, ValueError, TypeError, AttributeError):
                paired = False
            final_stop = False
            with (root / item["name"]).open(errors="replace") as stream:
                for line in stream:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict) and event.get("type") == "step_finish":
                        final_stop = (event.get("part") or {}).get("reason") == "stop"
            session.append(
                {
                    "file_id": item["id"],
                    "events": valid,
                    "tool_inputs": tool_inputs,
                    "tool_outputs": tool_outputs,
                    "rendered_prompt": bool(prompt),
                    "completeness": "complete_observed_session"
                    if valid and prompt and paired and final_stop and tool_inputs == tool_outputs
                    else "partial_or_missing",
                    "scope": "rendered prompt and emitted normal message/tool events; excludes native auth/config and hidden upstream state",
                }
            )
    config = read_json(root / "manifest.json")
    if config.get("effective", {}).get("agent") == "opencode" and not session:
        session.append(
            {
                "file_id": None,
                "completeness": "missing",
                "reason": "No captured OpenCode event stream",
            }
        )
    value = {
        "run_id": run_id,
        "files": files,
        "session_coverage": session,
        "scope": "explicit run-local inputs, agent events, verifier, artifacts and execution logs",
        "limitations": [
            "native auth/config/XDG stores excluded",
            "event presence does not prove session completeness",
        ],
        "legacy": False,
    }
    write_json(root / "materials.json", value)
    return value


def manifest(application, actor, run_id):
    require_evidence(application.data, actor)
    store = application.store
    with store.evidence(run_id):
        row = store.get(run_id)
        if row["status"] not in TERMINAL:
            return {"run_id": run_id, "state": "in_progress", "files": []}
        root = store.path(run_id)
        # Inventory survives retention and deletion. Audit failures never expose the inventory.
        if row.get("audit_status") != "clean":
            raise ServiceError("audit_incomplete", "Run evidence audit incomplete", 409)
        if not (root / "archived.json").exists():
            application.safe_key(run_id)
        if not (root / "materials.json").exists() and (root / "archived.json").exists():
            return {
                "run_id": run_id,
                "state": "expired",
                "files": [],
                "legacy": True,
                "limitations": [
                    "legacy_unknown: archived before per-file inventory; lost bytes and original hashes cannot be recovered"
                ],
                "session_coverage": [],
            }
        if not (root / "materials.json").exists():
            application.safe_key(run_id)
            value = inventory(store, run_id)
            value["legacy"] = True
            for item in value["files"]:
                item["status"] = "legacy_unknown"
            write_json(root / "materials.json", value)
        value = read_json(root / "materials.json")
        with store.connect() as db:
            deleted = {
                r[0]
                for r in db.execute(
                    "SELECT file_id FROM artifact_deletions WHERE run_id=?", (run_id,)
                )
            }
        expired = (root / "archived.json").exists()
        for item in value["files"]:
            if item["status"] in {"deleted", "expired"}:
                continue
            old_id = hashlib.sha256(item["name"].encode()).hexdigest()[:24]
            if expired:
                item["status"] = "expired"
            elif old_id in deleted:
                item["status"] = "deleted"
            elif not (root / item["name"]).is_file():
                item["status"] = "missing"
        return {**value, "state": "expired" if expired else "available"}


def snapshot(application, actor, run_id, file_id=None):
    """Copy and validate under evidence lock, then stream outside every service lock."""
    store = application.store
    output = tempfile.TemporaryFile()  # noqa: SIM115  # Ownership transfers to streaming response; every failure closes it.
    try:
        with store.evidence(run_id):
            deadline = time.monotonic() + SNAPSHOT_SECONDS
            value = manifest(application, actor, run_id)
            application.safe_key(run_id)
            if value["state"] != "available":
                raise ServiceError("evidence_pending", "Evidence requires terminal CLEAN run", 409)
            selected = value["files"]
            if file_id:
                selected = [item for item in selected if item["id"] == file_id]
                if not selected:
                    raise ServiceError(
                        "evidence_file_missing", "File ID not found in this run", 404
                    )
                if selected[0]["status"] not in {"original", "redacted", "legacy_unknown"}:
                    raise ServiceError("evidence_unavailable", "File " + selected[0]["status"], 410)
            local = LocalRoot(store.path(run_id))
            try:
                archive = (
                    zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) if not file_id else None
                )
                try:
                    if archive:
                        archive.writestr("materials.json", json.dumps(value, ensure_ascii=False))
                    for item in selected:
                        if item["status"] not in {"original", "redacted", "legacy_unknown"}:
                            continue
                        import os

                        with local.parent(item["name"]) as (fd, name):
                            source_fd = os.open(
                                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
                            )
                            with os.fdopen(source_fd, "rb") as source:
                                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                                    raise ServiceError(
                                        "evidence_changed", "Evidence is not a regular file", 409
                                    )
                                target = archive.open(item["name"], "w") if archive else output
                                sha, size = hashlib.sha256(), 0
                                try:
                                    while chunk := source.read(65536):
                                        if time.monotonic() > deadline:
                                            raise ServiceError(
                                                "evidence_snapshot_busy",
                                                "资料包准备超时，请稍后重试",
                                                503,
                                            )
                                        target.write(chunk)
                                        sha.update(chunk)
                                        size += len(chunk)
                                finally:
                                    if archive:
                                        target.close()
                                if size != item["bytes"] or sha.hexdigest() != item["sha256"]:
                                    raise ServiceError(
                                        "evidence_changed", "File changed since terminal audit", 409
                                    )
                finally:
                    if archive:
                        archive.close()
            finally:
                local.close()
            with store.connect() as db:
                db.execute(
                    "INSERT INTO access_events(user_id,access_credential_id,action,object_id,time) VALUES(?,?,?,?,?)",
                    (
                        actor["id"],
                        actor.get("access_credential_id"),
                        "download_evidence",
                        run_id,
                        __import__("time").time(),
                    ),
                )
        output.seek(0)
        sha, size = hashlib.sha256(), 0
        while chunk := output.read(65536):
            sha.update(chunk)
            size += len(chunk)
        output.seek(0)
        return output, size, sha.hexdigest()
    except BaseException:
        output.close()
        raise


def tombstone(store, run_id, *, status, category_filter=None, name=None):
    path = store.path(run_id) / "materials.json"
    if not path.exists():
        return
    value = read_json(path)
    for item in value["files"]:
        if (category_filter is None or item["category"] == category_filter) and (
            name is None or item["name"] == name
        ):
            item["status"] = status
    write_json(path, value)
