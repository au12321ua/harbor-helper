"""Shared application operations used by HTTP clients and the service scheduler."""

import hashlib
import json
import os
import shutil
import time
import uuid
import zipfile
from pathlib import PurePosixPath

from harbor_helper.execution.config import load_team, validate_effective
from harbor_helper.persistence.files import read_json, tree_digest
from harbor_helper.persistence.store import ACTIVE, TERMINAL
from harbor_helper.security.credentials import redact_value
from harbor_helper.service.configuration import TeamConfiguration
from harbor_helper.service.data import ServiceData, ServiceError


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


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
        "diagnosis": value.get("frozen", {}).get("service", {}).get("author_input_issues"),
        "retry_changes": value.get("frozen", {}).get("service", {}).get("retry_changes", {}),
        "execution_mode": value.get("frozen", {})
        .get("service", {})
        .get("execution_mode", "legacy-image-override"),
        "legacy_override_removed": value.get("frozen", {})
        .get("service", {})
        .get("legacy_override_removed", False),
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


def admin(actor):
    if actor["role"] != "admin":
        raise ServiceError("admin_required", "Administrator permission required", 403)


def cancel_allowed(actor, owner):
    if actor["role"] != "admin" and actor["id"] != owner:
        raise ServiceError("cancel_forbidden", "Members may cancel only their own tasks", 403)


class Application:
    def __init__(self, root):
        self.data = ServiceData(root)
        self.store = self.data.store
        self.configuration = TeamConfiguration(self.data)
        from harbor_helper.service.attachments import Attachments

        self.attachments = Attachments(self)

    def catalog(self):
        settings = self.configuration.settings()
        default_dataset = load_team(self.store)["dataset"]
        if settings.get("default_dataset_id"):
            selected = self.data.object("dataset", settings["default_dataset_id"])
            default_dataset = selected["reference"]
        return {
            **self.configuration.catalog(),
            **self.attachments.catalog(),
            "providers": self.data.objects("provider"),
            "credentials": self.data.credentials(),
            "model_profiles": self.data.objects("profile"),
            "limits": self.data.limits(),
            "default_dataset": default_dataset,
        }

    def accept(
        self, actor, request, idem, parent=None, *, retry=False, recovery=None, access_value=None
    ):
        if not isinstance(idem, str) or not 1 <= len(idem) <= 128:
            raise ServiceError("idempotency_required", "A stable Idempotency-Key is required")
        if not isinstance(request, dict) or set(request) - {
            "dataset",
            "model_profile",
            "agent",
            "bundle_id",
            "attachment_version_id",
            "attempts",
            "concurrency",
            "wall_seconds",
            "environment_build_timeout_multiplier",
            "task",
            "dataset_id",
            "name",
        }:
            raise ServiceError(
                "invalid_submission", "Unknown submission fields; identity is supplied by server"
            )
        if "bundle_id" in request and "attachment_version_id" in request:
            raise ServiceError("attachment_reference", "Choose bundle_id OR attachment_version_id")
        if parent and not retry and request:
            raise ServiceError("rerun_options", "Rerun inherits fixed inputs")
        if request.get("name") is not None and (
            not isinstance(request["name"], str) or len(request["name"]) > 128
        ):
            raise ServiceError("experiment_name", "Experiment name must be at most 128 characters")
        if retry and set(request) - {"wall_seconds"}:
            raise ServiceError("retry_options", "修复重试仅允许显式修改总时长")
        operation = (
            ("retry:" if retry else "rerun:") + parent
            if parent
            else ("recover:" + recovery if recovery else "submit")
        )
        request_hash = digest(request)
        with self.store.control():
            with self.store.connect() as db:
                old = db.execute(
                    "SELECT id,request_hash FROM submissions WHERE user_id=? AND operation=? AND idem=?",
                    (actor["id"], operation, idem),
                ).fetchone()
            if old:
                if old["request_hash"] != request_hash:
                    raise ServiceError(
                        "idempotency_conflict", "Idempotency key reused with different input", 409
                    )
                return public_submission(self.data.submission(old["id"]))
            if not self.data.user(actor["id"])["enabled"]:
                raise ServiceError("member_disabled", "Account disabled", 403)
            team = load_team(self.store)
            limits = self.data.limits()
            with self.store.connect() as db:
                preparing = db.execute(
                    "SELECT COUNT(*) FROM submissions WHERE status='preparing'"
                ).fetchone()[0]
            queued = sum(r["status"] == "queued" for r in self.store.runs())
            if preparing + queued >= limits["max_queue"]:
                raise ServiceError("queue_full", "Shared queue capacity reached", 429)
            service = {
                "user_id": actor["id"],
                "submitter": actor["username"],
                "name": request.get("name") or "",
            }
            recovery_row = self.data.submission(recovery) if recovery else None
            copy_parent = parent or (recovery_row.get("parent") if recovery_row else None)
            if recovery_row and (recovery_row["status"] != "failed" or recovery_row["run_id"]):
                raise ServiceError("recovery_state", "只能恢复尚未产生实验的失败提交", 409)
            if parent or recovery_row:
                old = (
                    read_json(self.store.path(parent) / "manifest.json")
                    if parent
                    else recovery_row["frozen"]
                )
                cfg = json.loads(json.dumps(old["effective"]))
                old_binding = old.get("service") or {}
                service.update(
                    {
                        k: v
                        for k, v in old_binding.items()
                        if k
                        not in {
                            "user_id",
                            "submitter",
                            "submission_id",
                            "name",
                            "access_credential_id",
                        }
                    }
                )
                service["name"] = ((old_binding.get("name") or parent or recovery) + " · 重跑")[
                    :128
                ]
                if cfg["agent"] == "opencode":
                    original_profile = self.data.object("profile", old_binding.get("model_profile"))
                    if not original_profile["enabled"]:
                        raise ServiceError(
                            "profile_disabled", "Original model profile disabled", 409
                        )
                    credential = self.data.credential(old_binding.get("credential_id"))
                    if (
                        not credential["enabled"]
                        or credential["provider_id"] != old_binding["provider_id"]
                    ):
                        raise ServiceError(
                            "rerun_credential", "Same credential has no usable current version", 409
                        )
                    provider = self.data.object("provider", old_binding["provider_id"])
                    if not provider["enabled"]:
                        raise ServiceError("provider_disabled", "Original provider disabled", 409)
                    self.data.key(credential["id"], credential["version"], provider["id"], True)
                    service.update(
                        {
                            k: v
                            for k, v in old_binding.items()
                            if k
                            not in {
                                "user_id",
                                "submitter",
                                "submission_id",
                                "access_credential_id",
                                "name",
                            }
                        }
                    )
                    service["credential_version"] = credential["version"]
            else:
                agent = request.get("agent") or "opencode"
                cfg = {
                    "agent": agent,
                    "dataset": request.get("dataset") or team["dataset"],
                    "attempts": request.get("attempts", 1),
                    "concurrency": request.get("concurrency", 1),
                    "wall_seconds": request.get(
                        "wall_seconds", min(1800, limits["max_wall_seconds"])
                    ),
                    "environment_build_timeout_multiplier": request.get(
                        "environment_build_timeout_multiplier", 10
                    ),
                    "task_filter": request.get("task"),
                    "model": None,
                    "max_cpus_per_trial": team["max_cpus_per_trial"],
                    "max_memory_mb_per_trial": team["max_memory_mb_per_trial"],
                }
                if agent == "opencode":
                    cfg["agent_tool_preparation"] = "offline-npm-binary-v1"
                    profile = self.data.object(
                        "profile",
                        request.get("model_profile")
                        or self.configuration.settings().get("default_model_profile"),
                    )
                    provider = self.data.object("provider", profile["provider_id"])
                    credential = self.data.credential(profile["credential_id"])
                    if (
                        not profile["enabled"]
                        or not provider["enabled"]
                        or not credential["enabled"]
                    ):
                        raise ServiceError(
                            "model_disabled", "Model profile/provider/credential disabled", 409
                        )
                    if credential["provider_id"] != provider["id"]:
                        raise ServiceError(
                            "credential_binding", "Credential provider mismatch", 409
                        )
                    self.data.key(credential["id"], credential["version"], provider["id"], True)
                    cfg["model"] = {
                        "endpoint": provider["endpoint"],
                        "name": profile["model"],
                        "declared_version": "unknown",
                        "credential_env": "VLLM_API_KEY",
                        "opencode_version": profile["opencode_version"],
                        "parameters": profile["params"],
                    }
                    service.update(
                        provider_id=provider["id"],
                        provider_version=provider["version"],
                        credential_id=credential["id"],
                        credential_version=credential["version"],
                        model_profile=profile["id"],
                        model_profile_version=profile["version"],
                    )
                elif agent != "oracle":
                    raise ServiceError(
                        "invalid_agent", "Use opencode with a model profile or explicit oracle"
                    )
            if not parent and not recovery_row:
                dataset_id = request.get("dataset_id")
                if not dataset_id and not request.get("dataset"):
                    dataset_id = self.configuration.settings().get("default_dataset_id")
                if not dataset_id and request.get("dataset"):
                    dataset_id = next(
                        (
                            d["id"]
                            for d in self.configuration.catalog()["datasets"]
                            if d["ready"]
                            and request["dataset"] in {d["reference"], d.get("resolved")}
                        ),
                        None,
                    )
                if dataset_id:
                    selected = self.configuration.ready_dataset(dataset_id)
                    if (
                        request.get("dataset_id")
                        and request.get("task")
                        and request["task"] not in {t["name"] for t in selected["tasks"]}
                    ):
                        raise ServiceError("task_selection", "Select a verified dataset task")
                    cfg.update(
                        dataset=selected["resolved"],
                    )
                    service.update(
                        dataset_id=selected["id"],
                        dataset_version=selected["version"],
                        dataset_name=selected["name"],
                        source_version=selected.get("source_version"),
                    )
                    # Recheck credential usability at acceptance; download revalidates source content.
                    if service.get("source_version"):
                        self.configuration.hub_key(service["source_version"])
                else:
                    # Remote CLI retains explicit references, but also uses explicit team Hub config.
                    status = self.configuration.hub_status()
                    service["source_version"] = (
                        status["version"] if status["mode"] == "team" else None
                    )
            if recovery_row:
                cfg = json.loads(json.dumps(recovery_row["frozen"]["effective"]))
                original = recovery_row["frozen"]["service"]
                # Retain accepted source digest and research factors; credentials still
                # pass the normal current usability checks above using original input.
                for key in ("dataset_id", "dataset_version", "dataset_name", "source_version"):
                    if key in original:
                        service[key] = original[key]
                service["recovered_submission"] = recovery
            service.pop("retry_changes", None)
            service.pop("author_input_issues", None)
            if not parent or retry:
                dataset_id = service.get("dataset_id")
                parameters = (
                    self.configuration.author_parameters(dataset_id)
                    if dataset_id
                    else {"version": 0, "values": {}}
                )
                if (
                    dataset_id
                    and not (retry or recovery)
                    and parameters.get("source") not in {None, cfg["dataset"]}
                ):
                    raise ServiceError(
                        "author_inputs_unchecked", "作者参数对应不同来源；请重新检查", 409
                    )
                cfg["author_env"] = dict(parameters["values"])
                service["author_parameters_version"] = parameters["version"]
                service["author_parameters_source"] = parameters.get("source")
                service["author_input_check"] = True
                if retry:
                    if cfg["agent"] == "opencode":
                        cfg.setdefault("agent_tool_preparation", "offline-npm-binary-v1")
                    cfg.setdefault("environment_build_timeout_multiplier", 10)
                    if "wall_seconds" in request:
                        cfg["wall_seconds"] = request["wall_seconds"]
                    service["name"] = ((old_binding.get("name") or parent) + " · 修复重试")[:128]
                    service["retry_changes"] = {
                        key: {
                            "old": old["effective"].get(key, {} if key == "author_env" else None),
                            "new": cfg.get(key),
                        }
                        for key in (
                            "author_env",
                            "agent_tool_preparation",
                            "environment_build_timeout_multiplier",
                            "wall_seconds",
                        )
                        if old["effective"].get(key, {} if key == "author_env" else None)
                        != cfg.get(key)
                    }
            service["author_input_check"] = True
            # Ordinary rerun keeps its frozen author input and does not fill old defaults.
            cfg.pop("runtime_image", None)
            cfg.pop("runtime_image_env", None)
            service["execution_mode"] = "harbor-native"
            if parent and old.get("execution_mode") != "harbor-native":
                service["legacy_override_removed"] = True
            service.pop("runtime_id", None)
            service.pop("runtime_version", None)
            validate_effective(team, cfg)
            if parent or recovery_row:
                bundle = old_binding.get("bundle_id")
                version_id = old_binding.get("attachment_version_id")
                if recovery_row:
                    bundle = bundle or old.get("bundle_id")
                binding = self.attachments.binding(bundle, version_id, access_value=access_value)
                if copy_parent:
                    parent_manifest = read_json(self.store.path(copy_parent) / "manifest.json")
                    snapshot = self.store.path(copy_parent) / "bundle"
                    if parent_manifest.get("bundle_digest") or snapshot.exists():
                        from harbor_helper.execution.runs import check_bundle

                        try:
                            check_bundle(snapshot, access_value)
                            if tree_digest(snapshot) != parent_manifest.get("bundle_digest"):
                                raise ValueError
                        except (ValueError, OSError):
                            raise ServiceError(
                                "attachment_unavailable",
                                "Parent attachment snapshot unsafe or changed",
                                409,
                            ) from None
                if not bundle and not version_id:
                    binding["attachment_lineage"] = "legacy/unknown"
                    binding["bundle_digest"] = (
                        parent_manifest.get("bundle_digest")
                        if copy_parent
                        else old_binding.get("bundle_digest")
                    )
            else:
                binding = self.attachments.binding(
                    request.get("bundle_id"),
                    request.get("attachment_version_id"),
                    access_value=access_value,
                )
            service.update(binding)
            bundle = binding["bundle_id"]
            submission_id = "sub-" + uuid.uuid4().hex[:16]
            target_id = "hh-" + uuid.uuid4().hex[:16]
            service["submission_id"] = submission_id
            frozen = {"effective": cfg, "service": service, "bundle_id": bundle}
            with self.store.connect() as db:
                db.execute(
                    """INSERT INTO submissions(id,user_id,submitter,operation,idem,request_hash,
                    request,frozen,target_id,status,created,parent) VALUES(?,?,?,?,?,?,?,?,?,'preparing',?,?)""",
                    (
                        submission_id,
                        actor["id"],
                        actor["username"],
                        operation,
                        idem,
                        request_hash,
                        json.dumps(request),
                        json.dumps(frozen),
                        target_id,
                        time.time(),
                        copy_parent,
                    ),
                )
        return public_submission(self.data.submission(submission_id))

    def recover_submission(self, actor, submission_id, idem, *, access_value=None):
        row = self.data.submission(submission_id)
        return self.accept(
            actor, row["request"], idem, recovery=submission_id, access_value=access_value
        )

    def cancel_submission(self, actor, submission_id):
        with self.store.control():
            row = self.data.submission(submission_id)
            cancel_allowed(actor, row["user_id"])
            with self.store.connect() as db:
                db.execute(
                    "UPDATE submissions SET cancel=1,status=CASE WHEN status='preparing' THEN 'cancelled' ELSE status END WHERE id=?",
                    (submission_id,),
                )
            if row["run_id"]:
                self._cancel_run(row["run_id"])
        return public_submission(self.data.submission(submission_id))

    def _cancel_run(self, run_id):
        row = self.store.get(run_id)
        if row["status"] not in TERMINAL:
            self.store.update(run_id, cancel=1)
        return {"run_id": run_id, "cancel_requested": True, "status": row["status"]}

    def cancel_run(self, actor, run_id):
        with self.store.control():
            binding = read_json(self.store.path(run_id) / "manifest.json")["service"]
            cancel_allowed(actor, binding["user_id"])
            return self._cancel_run(run_id)

    def summary(self, row):
        manifest = read_json(self.store.path(row["id"]) / "manifest.json")
        binding = manifest.get("service") or {}
        audit_status = row.get("audit_status", "pending")
        if (
            manifest["effective"]["agent"] == "opencode"
            and not (self.store.path(row["id"]) / "archived.json").exists()
        ):
            try:
                self.data.run_key(row["id"], False)
            except (ValueError, OSError):
                audit_status = "incomplete"
        return {
            "id": row["id"],
            "name": binding.get("name") or row["id"],
            "dataset_name": binding.get("dataset_name"),
            "status": row["status"],
            "created": row["created"],
            "started": row["started"],
            "finished": row["finished"],
            "parent": row["parent"],
            "submitter": binding.get("submitter", "unknown"),
            "user_id": binding.get("user_id"),
            "concurrency": row["concurrency"],
            "cancel": bool(row["cancel"]),
            "audit_status": audit_status,
            "audit_reason": "Audit source unavailable or evidence not safe"
            if audit_status == "incomplete"
            else None,
            "reason": None if audit_status == "incomplete" else row["reason"],
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
            "runs": [self.summary(r) for r in reversed(self.store.runs())],
            "submissions": [public_submission(self.data.submission(i)) for i in ids],
        }

    def safe_key(self, run_id):
        path = self.store.path(run_id)
        row = self.store.get(run_id)
        if (path / "archived.json").exists():
            raise ServiceError(
                "evidence_expired", "Raw logs and artifacts passed configured retention", 410
            )
        try:
            key = self.data.run_key(run_id, False)
        except (ValueError, OSError):
            raise ServiceError(
                "audit_incomplete", "Bound audit source unavailable; raw evidence withheld", 409
            ) from None
        if row.get("audit_status") == "incomplete":
            raise ServiceError(
                "audit_incomplete", "Evidence audit incomplete; raw evidence withheld", 409
            )
        return key

    def safe_report(self, run_id):
        path = self.store.path(run_id)
        if (path / "archived.json").exists():
            return (
                read_json(path / "safe-report.json")
                if (path / "safe-report.json").exists()
                else None
            )
        self.safe_key(run_id)
        if (
            self.store.get(run_id)["status"] not in TERMINAL
            or self.store.get(run_id).get("audit_status") != "clean"
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

    def detail(self, run_id):
        from harbor_helper.execution.runs import detail_startup_policy

        row = self.store.get(run_id)
        manifest = read_json(self.store.path(run_id) / "manifest.json")
        try:
            report = self.safe_report(run_id)
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
                        "image_id",
                        "execution_mode",
                        "legacy_override_removed",
                        "model_checkpoint_actual",
                        "hard_budgets",
                    )
                },
            },
            "artifacts": self.artifacts(run_id, allow_blocked=True),
            "report": report,
        }

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

    def artifacts(self, run_id, allow_blocked=False):
        try:
            self.safe_key(run_id)
            row = self.store.get(run_id)
            if row["status"] not in TERMINAL or row.get("audit_status") != "clean":
                raise ServiceError("audit_pending", "Artifacts await terminal safety audit", 409)
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
                values.append({"id": file_id, "name": relative, "deleted": file_id in removed})
        # Preserve deletion tombstones even after physical deletion.
        values += [
            {"id": i, "name": "Deleted artifact", "deleted": True}
            for i in removed
            if i not in {v["id"] for v in values}
        ]
        return values

    def artifact_path(self, run_id, file_id):
        self.safe_key(run_id)
        artifact = next((a for a in self.artifacts(run_id) if a["id"] == file_id), None)
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
        admin(actor)
        with self.store.control():
            row = self.store.get(run_id)
            if row["status"] not in TERMINAL:
                raise ServiceError(
                    "resource_active", "Artifact deletion awaits terminal cleanup", 409
                )
            with self.store.connect() as db:
                if db.execute(
                    "SELECT 1 FROM artifact_deletions WHERE run_id=? AND file_id=?",
                    (run_id, file_id),
                ).fetchone():
                    return {"id": file_id, "deleted": True}
            path = self.artifact_path(run_id, file_id)
            path.unlink()
            with self.store.connect() as db:
                db.execute(
                    "INSERT INTO artifact_deletions VALUES(?,?,?,?)",
                    (run_id, file_id, actor["username"], time.time()),
                )
        return {"id": file_id, "deleted": True}

    def upload_bundle(self, archive, *, access_value=None, persist=True):
        limits = self.data.limits()
        archive.seek(0, 2)
        if archive.tell() > limits["max_upload_bytes"]:
            raise ServiceError("upload_limit", "Bundle upload too large", 413)
        archive.seek(0)
        bundle_id = "bundle-" + uuid.uuid4().hex[:16]
        path = self.store.root / "bundles" / bundle_id
        path.mkdir(parents=True, mode=0o700)
        try:
            with zipfile.ZipFile(archive) as z:
                entries = z.infolist()
                if (
                    len(entries) > 2000
                    or sum(e.file_size for e in entries) > limits["max_upload_bytes"]
                ):
                    raise ServiceError(
                        "upload_limit", "Expanded bundle exceeds configured limit", 413
                    )
                for entry in entries:
                    name = PurePosixPath(entry.filename)
                    mode = entry.external_attr >> 16
                    if (
                        not entry.filename
                        or name.is_absolute()
                        or ".." in name.parts
                        or "\\" in entry.filename
                        or mode & 0o170000 not in {0, 0o040000, 0o100000}
                    ):
                        raise ServiceError(
                            "unsafe_bundle", "Bundle paths, links and special files are restricted"
                        )
                    target = path / name
                    if entry.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with z.open(entry) as source, target.open("xb") as output:
                            shutil.copyfileobj(source, output)
                        target.chmod(0o700 if mode & 0o111 else 0o600)
            from harbor_helper.execution.runs import check_bundle

            check_bundle(path, access_value)
            sha = tree_digest(path)
            # Publish durable bytes before committing the metadata pointing at them.
            for file in path.rglob("*"):
                if file.is_file():
                    with file.open("rb") as source:
                        os.fsync(source.fileno())
            directories = sorted((p for p in path.rglob("*") if p.is_dir()), reverse=True)
            for directory in [*directories, path, path.parent]:
                fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            if persist:
                with self.store.connect() as db:
                    db.execute("INSERT INTO bundles VALUES(?,?,?)", (bundle_id, sha, time.time()))
        except BaseException:
            shutil.rmtree(path, ignore_errors=True)
            raise
        return {"id": bundle_id, "digest": sha}

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
            "queued_jobs": sum(r["status"] == "queued" for r in rows),
            "by_submitter": list(by.values()),
            "cost": "unknown",
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
