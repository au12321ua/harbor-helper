"""Admission, immutable plan inheritance and transactional publication."""

import json
import time
import uuid

from harbor_helper.execution.config import load_team, validate_effective
from harbor_helper.persistence import statuses as lifecycle_status
from harbor_helper.persistence.files import digest, read_json, tree_digest
from harbor_helper.service.admission import check
from harbor_helper.service.policy import authorize
from harbor_helper.service.primitives import ServiceError
from harbor_helper.service.views import public_submission

OPERATION_SCOPES = {
    "submit": "submit",
    "rerun": "rerun",
    "retry": "retry_run",
    "recover": "recover_submission",
}
REQUEST_FIELDS = {
    "dataset",
    "model_profile",
    "agent",
    "attachment_version_id",
    "attempts",
    "concurrency",
    "wall_seconds",
    "environment_build_timeout_multiplier",
    "task",
    "dataset_id",
    "name",
}
# Inherited plans keep the original research binding but never its submitter identity.
IDENTITY_FIELDS = {"user_id", "submitter", "submission_id", "name", "access_credential_id"}


def validate_request(request, idem, operation, access_value):
    from harbor_helper.security.access_tokens import ACCESS_TOKEN_TEXT

    text = json.dumps([request, idem], ensure_ascii=False)
    if ACCESS_TOKEN_TEXT.search(text) or (access_value and access_value in text):
        raise ServiceError("access_plaintext", "Access credential plaintext forbidden in inputs")
    if not isinstance(idem, str) or not 1 <= len(idem) <= 128:
        raise ServiceError("idempotency_required", "A stable Idempotency-Key is required")
    if not isinstance(request, dict) or set(request) - REQUEST_FIELDS:
        raise ServiceError(
            "invalid_submission", "Unknown submission fields; identity is supplied by server"
        )
    if operation == "rerun" and request:
        raise ServiceError("rerun_options", "Rerun inherits fixed inputs")
    if request.get("name") is not None and (
        not isinstance(request["name"], str) or len(request["name"]) > 128
    ):
        raise ServiceError("experiment_name", "Experiment name must be at most 128 characters")
    if operation == "retry" and set(request) - {"wall_seconds"}:
        raise ServiceError("retry_options", "修复重试仅允许显式修改总时长")


class Submissions:
    def __init__(self, data, configuration, attachments):
        self.data = data
        self.store = data.store
        self.configuration = configuration
        self.attachments = attachments

    def accept(
        self, actor, request, idem, parent=None, *, retry=False, recovery=None, access_value=None
    ):
        """Freeze one submission: submit builds a plan, rerun/retry/recover inherit one."""

        operation = "retry" if retry else "rerun" if parent else "recover" if recovery else "submit"
        authorize(actor, OPERATION_SCOPES[operation])
        if not self.data.user(actor["id"])["enabled"]:
            raise ServiceError("member_disabled", "Account disabled", 403)
        validate_request(request, idem, operation, access_value)
        request_hash = (
            digest({"request": request, "parent": parent, "recovery": recovery})
            if parent or recovery
            else digest(request)
        )
        with self.store.control():
            if not self.data.user(actor["id"])["enabled"]:
                raise ServiceError("member_disabled", "Account disabled", 403)
            existing = self._existing_submission(actor, operation, idem, request_hash)
            if existing:
                return public_submission(existing)
            team = load_team(self.store)
            check(self, actor)
            service = {
                "user_id": actor["id"],
                "submitter": actor["username"],
                "name": request.get("name") or "",
            }
            if actor.get("access_credential_id"):
                service["access_credential_id"] = actor["access_credential_id"]
            if operation == "submit":
                cfg = self._new_plan(request, team, service)
                self._select_dataset(request, cfg, service)
                version_id, copy_parent = request.get("attachment_version_id"), None
            else:
                origin, copy_parent = self._origin(parent, recovery)
                cfg = self._inherit_plan(origin, service, parent or recovery)
                version_id = (origin.get("service") or {}).get("attachment_version_id")
                if recovery:
                    # Recovery repeats the failed attempt itself, so it keeps that name.
                    service["name"] = (origin.get("service") or {}).get("name", "")
                    service["recovered_submission"] = recovery
            service.pop("retry_changes", None)
            service.pop("author_input_issues", None)
            # Ordinary rerun keeps its frozen author input and does not fill old defaults.
            if operation != "rerun":
                self._freeze_author_inputs(cfg, service, check_source=operation == "submit")
            if retry:
                self._apply_retry(request, origin, cfg, service, parent)
            service["author_input_check"] = True
            validate_effective(team, cfg)
            service.update(self.attachments.binding(version_id, access_value=access_value))
            if copy_parent:
                self._check_parent_snapshot(copy_parent, access_value)
            submission_id = self._record(
                actor, operation, idem, request_hash, request, cfg, service, copy_parent
            )
        return public_submission(self.data.submission(submission_id))

    def _existing_submission(self, actor, operation, idem, request_hash):
        with self.store.connect() as db:
            old = db.execute(
                "SELECT id,request_hash FROM submissions WHERE user_id=? AND operation=? AND idem=?",
                (actor["id"], operation, idem),
            ).fetchone()
        if not old:
            return None
        if old["request_hash"] != request_hash:
            raise ServiceError(
                "idempotency_conflict", "Idempotency key reused with different input", 409
            )
        return self.data.submission(old["id"])

    def _new_plan(self, request, team, service):
        limits = self.data.limits()
        agent = request.get("agent") or "opencode"
        cfg = {
            "agent": agent,
            "dataset": request.get("dataset") or team["dataset"],
            "attempts": request.get("attempts", 1),
            "concurrency": request.get("concurrency", 1),
            "wall_seconds": request.get("wall_seconds", min(1800, limits["max_wall_seconds"])),
            "environment_build_timeout_multiplier": request.get(
                "environment_build_timeout_multiplier", 10
            ),
            "task_filter": request.get("task"),
            "model": None,
            "max_cpus_per_trial": team["max_cpus_per_trial"],
            "max_memory_mb_per_trial": team["max_memory_mb_per_trial"],
        }
        if agent == "oracle":
            return cfg
        if agent != "opencode":
            raise ServiceError(
                "invalid_agent", "Use opencode with a model profile or explicit oracle"
            )
        cfg["agent_tool_preparation"] = "offline-npm-binary-v1"
        profile = self.data.object(
            "profile",
            request.get("model_profile")
            or self.configuration.settings().get("default_model_profile"),
        )
        provider = self.data.object("provider", profile["provider_id"])
        credential = self.data.credential(profile["credential_id"])
        if not profile["enabled"] or not provider["enabled"] or not credential["enabled"]:
            raise ServiceError("model_disabled", "Model profile/provider/credential disabled", 409)
        if credential["provider_id"] != provider["id"]:
            raise ServiceError("credential_binding", "Credential provider mismatch", 409)
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
        return cfg

    def _select_dataset(self, request, cfg, service):
        dataset_id = request.get("dataset_id")
        if not dataset_id and not request.get("dataset"):
            dataset_id = self.configuration.settings().get("default_dataset_id")
        if not dataset_id and request.get("dataset"):
            dataset_id = next(
                (
                    d["id"]
                    for d in self.configuration.catalog()["datasets"]
                    if d[lifecycle_status.READY]
                    and request["dataset"] in {d["reference"], d.get("resolved")}
                ),
                None,
            )
        if not dataset_id:
            # Remote CLI retains explicit references, but also uses explicit team Hub config.
            status = self.configuration.hub_status()
            service["source_version"] = status["version"] if status["mode"] == "team" else None
            return
        selected = self.configuration.ready_dataset(dataset_id)
        if (
            request.get("dataset_id")
            and request.get("task")
            and request["task"] not in {t["name"] for t in selected["tasks"]}
        ):
            raise ServiceError("task_selection", "Select a verified dataset task")
        cfg["dataset"] = selected["resolved"]
        service.update(
            dataset_id=selected["id"],
            dataset_version=selected["version"],
            dataset_name=selected["name"],
            source_version=selected.get("source_version"),
        )
        # Recheck credential usability at acceptance; download revalidates source content.
        if service.get("source_version"):
            self.configuration.hub_key(service["source_version"])

    def _origin(self, parent, recovery):
        """Frozen input to inherit and the run whose snapshot the new run copies."""
        if parent:
            return read_json(self.store.path(parent) / "manifest.json"), parent
        row = self.data.submission(recovery)
        if row["status"] != lifecycle_status.FAILED or row["run_id"]:
            raise ServiceError("recovery_state", "只能恢复尚未产生实验的失败提交", 409)
        return row["frozen"], row.get("parent")

    def _inherit_plan(self, origin, service, label):
        cfg = json.loads(json.dumps(origin["effective"]))
        binding = origin.get("service") or {}
        service.update({k: v for k, v in binding.items() if k not in IDENTITY_FIELDS})
        service["name"] = ((binding.get("name") or label) + " · 重跑")[:128]
        if cfg["agent"] != "opencode":
            return cfg
        profile = self.data.object("profile", binding.get("model_profile"))
        if not profile["enabled"]:
            raise ServiceError("profile_disabled", "Original model profile disabled", 409)
        credential = self.data.credential(binding.get("credential_id"))
        if not credential["enabled"] or credential["provider_id"] != binding["provider_id"]:
            raise ServiceError(
                "rerun_credential", "Same credential has no usable current version", 409
            )
        provider = self.data.object("provider", binding["provider_id"])
        if not provider["enabled"]:
            raise ServiceError("provider_disabled", "Original provider disabled", 409)
        self.data.key(credential["id"], credential["version"], provider["id"], True)
        service["credential_version"] = credential["version"]
        return cfg

    def _freeze_author_inputs(self, cfg, service, *, check_source):
        dataset_id = service.get("dataset_id")
        parameters = (
            self.configuration.author_parameters(dataset_id)
            if dataset_id
            else {"version": 0, "values": {}}
        )
        if dataset_id and check_source and parameters.get("source") not in {None, cfg["dataset"]}:
            raise ServiceError("author_inputs_unchecked", "作者参数对应不同来源；请重新检查", 409)
        cfg["author_env"] = dict(parameters["values"])
        service["author_parameters_version"] = parameters["version"]
        service["author_parameters_source"] = parameters.get("source")

    def _apply_retry(self, request, origin, cfg, service, parent):
        if cfg["agent"] == "opencode":
            cfg.setdefault("agent_tool_preparation", "offline-npm-binary-v1")
        cfg.setdefault("environment_build_timeout_multiplier", 10)
        if "wall_seconds" in request:
            cfg["wall_seconds"] = request["wall_seconds"]
        binding = origin.get("service") or {}
        service["name"] = ((binding.get("name") or parent) + " · 修复重试")[:128]
        before = origin["effective"]
        service["retry_changes"] = {
            key: {"old": before.get(key, {} if key == "author_env" else None), "new": cfg.get(key)}
            for key in (
                "author_env",
                "agent_tool_preparation",
                "environment_build_timeout_multiplier",
                "wall_seconds",
            )
            if before.get(key, {} if key == "author_env" else None) != cfg.get(key)
        }

    def _check_parent_snapshot(self, run_id, access_value):
        manifest = read_json(self.store.path(run_id) / "manifest.json")
        snapshot = self.store.path(run_id) / "bundle"
        if not manifest.get("bundle_digest") and not snapshot.exists():
            return
        from harbor_helper.execution.bundles import check_bundle

        try:
            check_bundle(snapshot, access_value)
            if tree_digest(snapshot) != manifest.get("bundle_digest"):
                raise ValueError
        except (ValueError, OSError):
            raise ServiceError(
                "attachment_unavailable", "Parent attachment snapshot unsafe or changed", 409
            ) from None

    def _record(self, actor, operation, idem, request_hash, request, cfg, service, parent):
        submission_id = "sub-" + uuid.uuid4().hex[:16]
        service["submission_id"] = submission_id
        frozen = {"effective": cfg, "service": service, "bundle_id": service["bundle_id"]}
        with self.store.connect() as db:
            db.execute(
                f"""INSERT INTO submissions(id,user_id,submitter,operation,idem,request_hash,
                request,frozen,target_id,status,created,parent) VALUES(?,?,?,?,?,?,?,?,?,{lifecycle_status.PREPARING!r},?,?)""",
                (
                    submission_id,
                    actor["id"],
                    actor["username"],
                    operation,
                    idem,
                    request_hash,
                    json.dumps(request),
                    json.dumps(frozen),
                    "hh-" + uuid.uuid4().hex[:16],
                    time.time(),
                    parent,
                ),
            )
            db.execute(
                "INSERT INTO access_events(user_id,access_credential_id,action,object_id,time) VALUES(?,?,?,?,?)",
                (
                    actor["id"],
                    actor.get("access_credential_id"),
                    operation,
                    submission_id,
                    time.time(),
                ),
            )
        return submission_id

    def recover_submission(self, actor, submission_id, idem, *, access_value=None):
        row = self.data.submission(submission_id)
        return self.accept(
            actor, row["request"], idem, recovery=submission_id, access_value=access_value
        )
