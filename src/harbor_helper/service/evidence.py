"""Evidence service with explicit persistence dependency."""

import hashlib
import time
from functools import wraps

from harbor_helper.persistence import statuses as lifecycle_status
from harbor_helper.persistence.files import read_json
from harbor_helper.persistence.store import ACTIVE, TERMINAL
from harbor_helper.security.credentials import redact_value
from harbor_helper.security.master_key import MasterUnavailable
from harbor_helper.service.primitives import ServiceError
from harbor_helper.service.run_metadata import local_file_error, read_manifest, recovered_metadata
from harbor_helper.service.views import public_submission, safe_view


def locked(function):
    @wraps(function)
    def wrapped(self, run_id, *args, **kwargs):
        from harbor_helper.service.management_data import available, request_id

        with self.store.connect() as db:
            available(db, "request", request_id(db, run_id))
        with self.store.evidence(run_id):
            return function(self, run_id, *args, **kwargs)

    return wrapped


class Evidence:
    def __init__(self, data):
        self.data = data
        self.store = data.store

    def summary(self, row):
        restricted = False
        try:
            manifest = read_manifest(self.store, row["id"])
        except ServiceError as error:
            if error.code != "run_metadata_unavailable":
                raise
            manifest = recovered_metadata(self.store, row["id"])
            restricted = True
        binding = manifest.get("service") or {}
        audit_status = (
            lifecycle_status.INCOMPLETE
            if restricted
            else row.get("audit_status", lifecycle_status.PENDING)
        )
        if (
            not restricted
            and manifest["effective"]["agent"] == "opencode"
            and not (self.store.path(row["id"]) / "archived.json").exists()
        ):
            try:
                self.data.run_key(row["id"], False)
            except MasterUnavailable:
                raise
            except (ValueError, KeyError, TypeError, AttributeError):
                audit_status = lifecycle_status.INCOMPLETE
            except OSError as error:
                if not local_file_error(self.store.path(row["id"]), error):
                    raise
                audit_status = lifecycle_status.INCOMPLETE
        return {
            "id": row["id"],
            "name": binding.get("name") or row["id"],
            "dataset_name": binding.get("dataset_name"),
            "status": row["status"],
            "created": row["created"],
            "started": row["started"],
            "finished": row["finished"],
            "parent": row["parent"],
            "submitter": binding.get("submitter") or "unknown",
            "user_id": binding.get("user_id"),
            "concurrency": row["concurrency"],
            "cancel": bool(row["cancel"]),
            "audit_status": audit_status,
            "audit_reason": "Run metadata unavailable; evidence withheld"
            if restricted
            else (
                "Audit source unavailable or evidence not safe"
                if audit_status == lifecycle_status.INCOMPLETE
                else None
            ),
            "reason": None if audit_status == lifecycle_status.INCOMPLETE else row["reason"],
            "dataset": manifest["effective"]["dataset"],
            "agent": manifest["effective"]["agent"],
            "model_profile": binding.get("model_profile"),
            "attachment": {
                k: binding.get(k)
                for k in (
                    "attachment_id",
                    "attachment_version_id",
                    "bundle_id",
                    "bundle_digest",
                    "attachment_lineage",
                )
            },
        }

    def runs(self):
        with self.store.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM submissions ORDER BY created DESC")]
        return {
            "runs": [
                self.summary(r)
                for r in reversed(self.store.runs())
                if self.request_visible(r["id"])
            ],
            "submissions": [
                public_submission(self.data.submission(i)) for i in ids if self.request_visible(i)
            ],
        }

    def request_visible(self, object_id):
        from harbor_helper.service.management_data import request_id, state

        with self.store.connect() as db:
            return state(db, "request", request_id(db, object_id)) == "active"

    def safe_key(self, run_id):
        path = self.store.path(run_id)
        read_manifest(self.store, run_id)
        row = self.store.get(run_id)
        if (path / "archived.json").exists():
            raise ServiceError(
                "evidence_expired", "Raw logs and artifacts passed configured retention", 410
            )
        try:
            key = self.data.run_key(run_id, False)
        except MasterUnavailable:
            raise
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ServiceError(
                "audit_incomplete", "Bound audit source unavailable; raw evidence withheld", 409
            ) from None
        except OSError as error:
            if not local_file_error(path, error):
                raise
            raise ServiceError(
                "audit_incomplete", "Bound audit source unavailable; raw evidence withheld", 409
            ) from None
        if row.get("audit_status") == lifecycle_status.INCOMPLETE:
            raise ServiceError(
                "audit_incomplete", "Evidence audit incomplete; raw evidence withheld", 409
            )
        return key

    @locked
    def safe_report(self, run_id):
        path = self.store.path(run_id)
        read_manifest(self.store, run_id)
        if (path / "archived.json").exists():
            return (
                read_json(path / "safe-report.json")
                if (path / "safe-report.json").exists()
                else None
            )
        self.safe_key(run_id)
        if (
            self.store.get(run_id)["status"] not in TERMINAL
            or self.store.get(run_id).get("audit_status") != lifecycle_status.CLEAN
        ):
            raise ServiceError(
                "report_pending", "Report awaits terminal resource and credential audit", 409
            )
        if not (path / "report.json").exists():
            return None
        # Enrich old, already audited reports in memory; original history stays byte-identical.
        from harbor_helper.results.reports import trial_diagnosis

        value = read_json(path / "report.json")
        cfg = read_json(path / "manifest.json")["effective"]
        for task in value.get("tasks", []):
            for attempt in task.get("attempts", []):
                if "diagnosis" not in attempt:
                    result = {
                        **attempt.get("phase_timings", {}),
                        "exception_info": attempt.get("framework_exception"),
                    }
                    attempt["diagnosis"] = trial_diagnosis(
                        result, path / "unavailable-legacy-phases", cfg
                    )
        # Path-bearing internal Harbor fields never leave service views.
        return safe_view(value)

    @locked
    def detail(self, run_id):
        from harbor_helper.execution.runs import detail_startup_policy

        row = self.store.get(run_id)
        manifest = read_manifest(self.store, run_id)
        try:
            report = self.safe_report(run_id)
        except MasterUnavailable:
            raise
        except ServiceError:
            report = None
        diagnosis = None
        if row["reason"] == "Wall-clock budget exceeded":
            diagnosis = {
                "code": "wall_timeout",
                "phase": "unknown",
                "message": "整体时长耗尽；包含环境、工具准备、执行与评分。最后阶段见已审计报告；不能认定已执行模型。",
            }
        return {
            "failure_diagnosis": diagnosis,
            "row": self.summary(row),
            "manifest": {
                "startup_policy": detail_startup_policy(self.store.path(run_id), manifest),
                **{
                    k: manifest.get(k)
                    for k in (
                        "effective",
                        "source",
                        "parent",
                        "service",
                        "bundle_digest",
                        "model_checkpoint_actual",
                        "hard_budgets",
                    )
                },
            },
            "artifacts": self.artifacts(run_id, allow_blocked=True),
            "report": report,
        }

    @locked
    def logs(self, run_id):
        key = self.safe_key(run_id)
        path = self.store.path(run_id) / "worker.log"
        if not path.exists():
            return {"text": ""}
        # Read bounded bytes; include enough overlap for multi-byte/secret forms.
        with path.open("rb") as file:
            file.seek(0, 2)
            length = file.tell()
            offset = max(0, length - 262144)
            file.seek(offset)
            raw = file.read()
        # Never expose a secret fragment where a bounded seek or live write cuts a line.
        if offset:
            newline = raw.find(b"\n")
            raw = raw[newline + 1 :] if newline >= 0 else b""
        if self.store.get(run_id)["status"] not in TERMINAL:
            newline = raw.rfind(b"\n")
            raw = raw[: newline + 1] if newline >= 0 else b""
        text = raw.decode("utf-8", errors="replace")
        return {"text": redact_value(text, [key] if key else []), "truncated": length > 262144}

    @locked
    def artifacts(self, run_id, allow_blocked=False):
        try:
            self.safe_key(run_id)
            row = self.store.get(run_id)
            if row["status"] not in TERMINAL or row.get("audit_status") != lifecycle_status.CLEAN:
                raise ServiceError("audit_pending", "Artifacts await terminal safety audit", 409)
        except MasterUnavailable:
            raise
        except ServiceError:
            if allow_blocked:
                return []
            raise
        path = self.store.path(run_id)
        with self.store.connect() as db:
            removed = {
                r[0]
                for r in db.execute(
                    "SELECT file_id FROM artifact_deletions WHERE run_id=?", (run_id,)
                )
            }
        values = []
        for folder in (path / "harbor").glob("*/*/artifacts"):
            for file in sorted(folder.rglob("*")):
                if (
                    not file.is_file()
                    or file.is_symlink()
                    or not file.resolve().is_relative_to(path.resolve())
                ):
                    continue
                relative = file.relative_to(path).as_posix()
                file_id = hashlib.sha256(relative.encode()).hexdigest()[:24]
                from harbor_helper.service.management_data import state

                with self.store.connect() as db:
                    hidden = state(db, "artifact", run_id + ":" + file_id) != "active"
                if not hidden:
                    values.append({"id": file_id, "name": relative, "deleted": file_id in removed})
        # Preserve deletion tombstones even after physical deletion.
        values += [
            {"id": i, "name": "Deleted artifact", "deleted": True}
            for i in removed
            if i not in {v["id"] for v in values}
        ]
        return values

    @locked
    def artifact_path(self, run_id, file_id, *, include_recycled=False):
        if not include_recycled:
            from harbor_helper.service.management_data import available

            with self.store.connect() as db:
                available(db, "artifact", run_id + ":" + file_id)
        self.safe_key(run_id)
        artifact = next((a for a in self.artifacts(run_id) if a["id"] == file_id), None)
        if include_recycled and not artifact:
            root = self.store.path(run_id)
            for candidate in root.glob("harbor/*/*/artifacts/**/*"):
                if candidate.is_file() and not candidate.is_symlink():
                    relative = candidate.relative_to(root).as_posix()
                    if hashlib.sha256(relative.encode()).hexdigest()[:24] == file_id:
                        artifact = {"name": relative, "deleted": False}
                        break
        if not artifact:
            raise ServiceError("artifact_missing", "Artifact not found", 404)
        if artifact["deleted"]:
            raise ServiceError("artifact_deleted", "Artifact was deleted", 410)
        path = self.store.path(run_id) / artifact["name"]
        if (
            not path.is_file()
            or path.is_symlink()
            or not path.resolve().is_relative_to(self.store.path(run_id))
        ):
            raise ServiceError("artifact_missing", "Artifact unavailable", 404)
        return path

    def delete_artifact(self, actor, run_id, file_id):
        from harbor_helper.service.permissions import management_admin

        management_admin(actor, "recycle_all")
        from harbor_helper.service.recycle import Recycle

        try:
            with self.store.evidence(run_id, blocking=False):
                return Recycle(self).move(actor, "artifact", run_id + ":" + file_id)
        except BlockingIOError:
            raise ServiceError(
                "evidence_busy", "Evidence maintenance active; retry later", 409
            ) from None

    def _delete_artifact(self, actor, run_id, file_id):
        row = self.store.get(run_id)
        if row["status"] not in TERMINAL:
            raise ServiceError("resource_active", "Artifact deletion awaits terminal cleanup", 409)
        with self.store.connect() as db:
            if db.execute(
                "SELECT 1 FROM artifact_deletions WHERE run_id=? AND file_id=?",
                (run_id, file_id),
            ).fetchone():
                return {"id": file_id, "deleted": True}
        path = self.artifact_path(run_id, file_id)
        from harbor_helper.service.materials import tombstone

        tombstone(
            self.store,
            run_id,
            status="deleted",
            name=path.relative_to(self.store.path(run_id)).as_posix(),
        )
        path.unlink()
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO artifact_deletions VALUES(?,?,?,?)",
                (run_id, file_id, actor["username"], time.time()),
            )
        return {"id": file_id, "deleted": True}

    def usage(self):
        rows = self.store.runs()
        with self.store.connect() as db:
            submissions = db.execute(
                "SELECT submitter,COUNT(*) n FROM submissions GROUP BY submitter"
            ).fetchall()
        by = {
            r["submitter"]: {
                "submitter": r["submitter"],
                "submissions": r["n"],
                "runs": 0,
                "wall_seconds": 0,
            }
            for r in submissions
        }
        for row in rows:
            summary = self.summary(row)
            value = by.setdefault(
                summary["submitter"],
                {"submitter": summary["submitter"], "submissions": 0, "runs": 0, "wall_seconds": 0},
            )
            value["runs"] += 1
            if row["started"]:
                value["wall_seconds"] += max(0, (row["finished"] or time.time()) - row["started"])
        return {
            "total_submissions": sum(v["submissions"] for v in by.values()),
            "total_runs": len(rows),
            "active_jobs": sum(r["status"] in ACTIVE for r in rows),
            "active_trials": sum(r["concurrency"] for r in rows if r["status"] in ACTIVE),
            "queued_jobs": sum(r["status"] == lifecycle_status.QUEUED for r in rows),
            "by_submitter": list(by.values()),
            "cost": "unknown",
        }
