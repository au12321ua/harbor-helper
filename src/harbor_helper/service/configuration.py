"""Versioned web catalog consumed by immutable submissions."""

import hashlib
import json
import re
import tempfile
import time
import uuid
from typing import cast

from harbor.models.package.reference import PackageReference
from harbor.models.package.version_ref import RefType, validate_tag

from harbor_helper.execution.config import reject_secrets
from harbor_helper.persistence.files import read_json, write_json
from harbor_helper.persistence.wakeup import wake_after
from harbor_helper.security.master_key import aad, decrypt, encrypt
from harbor_helper.service.primitives import ServiceError, identifier, secret_value
from harbor_helper.service.sources import source_call


class TeamConfiguration:
    def __init__(self, data):
        self.data = data
        self.store = data.store
        with data.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS source_credentials (
                version INTEGER PRIMARY KEY, enabled INTEGER NOT NULL,
                nonce BLOB NOT NULL, ciphertext BLOB NOT NULL, updated_at REAL)""")

            columns = {row["name"] for row in db.execute("PRAGMA table_info(source_credentials)")}
            if "updated_at" not in columns:
                db.execute("ALTER TABLE source_credentials ADD COLUMN updated_at REAL")

    def settings(self):
        path = self.data.root / "web.json"
        return read_json(path) if path.exists() else {}

    @wake_after
    def save_settings(self, value):
        if set(value) - {"team_name", "default_dataset_id", "default_model_profile"}:
            raise ServiceError("settings_options", "Unknown team setting")
        if "team_name" in value and (
            not isinstance(value["team_name"], str)
            or not 1 <= len(value["team_name"].strip()) <= 128
        ):
            raise ServiceError("team_name", "Team name must be 1–128 characters")
        if value.get("default_dataset_id"):
            self.ready_dataset(value["default_dataset_id"])
        if value.get("default_model_profile"):
            self.data.object("profile", value["default_model_profile"])
        settings = {**self.settings(), **value}
        write_json(self.data.root / "web.json", settings)
        return settings

    def hub_status(self):
        with self.data.store.connect() as db:
            row = db.execute(
                "SELECT version,enabled,updated_at FROM source_credentials ORDER BY version DESC LIMIT 1"
            ).fetchone()
        return {
            "mode": "team" if row and row["enabled"] else "anonymous",
            "version": row["version"] if row else None,
            "state": "active" if row and row["enabled"] else "disabled" if row else "unset",
            "updated_at": row["updated_at"] if row else None,
        }

    @wake_after
    def save_hub(self, key=None, enabled=True):
        if not enabled:
            with self.data.store.connect() as db:
                db.execute("UPDATE source_credentials SET enabled=0, updated_at=?", (time.time(),))
            return self.hub_status()
        secret_value(key)
        with self.data.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM source_credentials"
            ).fetchone()[0]
            nonce, encrypted = encrypt(
                self.data.master_keys.current(db), cast(str, key), f"hub/{version}"
            )
            db.execute(
                "INSERT INTO source_credentials(version,enabled,nonce,ciphertext,updated_at) "
                "VALUES(?,1,?,?,?)",
                (version, nonce, encrypted, time.time()),
            )
        return self.hub_status()

    def hub_key(self, version=None):
        rows = self.data.master_keys.rows(
            "source_credentials",
            "WHERE c.version=?" if version else "ORDER BY c.version DESC LIMIT 1",
            (version,) if version else (),
        )
        row = rows[0] if rows else None
        if not row:
            self.data.master_keys.current()
            if version:
                raise ServiceError("source_auth", "Bound team Hub credential unavailable", 409)
            return None
        if not row["enabled"]:
            if version:
                raise ServiceError("source_auth", "Bound team Hub credential disabled", 409)
            return None
        return decrypt(self.data.master_keys.load(row), row, aad(row, "source_credentials"))

    def persist(self, kind, value):
        value = dict(value)
        object_id = identifier(value.pop("id", None) or uuid.uuid4().hex)
        value.pop("version", None)
        reject_secrets(value)
        with self.data.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM objects WHERE kind=? AND id=?",
                (kind, object_id),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO objects VALUES(?,?,?,?)", (kind, object_id, version, json.dumps(value))
            )
        return {**value, "id": object_id, "version": version}

    def save(self, kind, value):
        allowed = {"id", "name", "enabled", "reference"}
        if (
            set(value) - allowed
            or not isinstance(value.get("name"), str)
            or not 1 <= len(value["name"].strip()) <= 128
        ):
            raise ServiceError("catalog_options", "Use a name and supported catalog fields")
        value = {**value, "enabled": value.get("enabled", True), "status": "unverified"}
        if type(value["enabled"]) is not bool:
            raise ServiceError("catalog_options", "Enabled must be boolean")
        try:
            if not isinstance(value.get("reference"), str):
                raise TypeError
            reference = PackageReference.parse(value["reference"].strip())
            parsed = reference.parsed_ref
            if parsed.type == RefType.DIGEST:
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", parsed.value):
                    raise ValueError
            elif parsed.type == RefType.REVISION:
                if parsed.revision < 1:
                    raise ValueError
            else:
                validate_tag(parsed.value)
            value["reference"] = str(reference)
        except (ValueError, TypeError):
            raise ServiceError(
                "dataset_reference",
                "填写 owner/name，可加 @修订号（rev.1 对应 @1）、@标签或完整 @sha256:摘要；省略版本使用 latest",
            ) from None
        return self.persist(kind, value)

    def verify(self, kind, object_id):
        with self.data.store.control():
            value = self.data.object(kind, object_id)
            initial_version = value["version"]
            hub = self.hub_status()
            source_key = self.hub_key()
        try:
            value.update(source_call(value["reference"], key=source_key))
            value["source_version"] = hub["version"] if hub["mode"] == "team" else None
            value.update(status="verified", checked=time.time(), error=None)
        except ServiceError as error:
            value.update(
                status="blocked",
                checked=time.time(),
                error={"code": error.code, "message": str(error)},
            )
        with self.data.store.control():
            if (
                self.data.object(kind, object_id)["version"] != initial_version
                or self.hub_status() != hub
            ):
                raise ServiceError("configuration_changed", "配置已修改；请重新验证", 409)
            return self.persist(kind, value)

    def ready_dataset(self, object_id):
        value = self.data.object("dataset", object_id)
        if not value["enabled"] or value["status"] != "verified":
            raise ServiceError("dataset_unverified", "管理员须启用并验证数据集", 409)
        if value.get("source_version"):
            self.hub_key(value["source_version"])
        return value

    def author_parameters(self, object_id):
        values = self.data.objects("author_parameters")
        return next(
            (v for v in values if v["id"] == object_id),
            {"id": object_id, "version": 0, "values": {}, "status": "unchecked"},
        )

    def inspect_author_parameters(self, object_id, task_names=None, *, selection_supplied=False):
        from harbor_helper.execution.author_inputs import AuthorInputError, discover

        selected = self.ready_dataset(object_id)
        catalog = selected["tasks"]
        by_name = {task["name"]: task for task in catalog}
        partial = selection_supplied or task_names is not None
        names = None
        if partial:
            from harbor_helper.execution.sources import TaskSelectionError, exact_task_names

            try:
                names = exact_task_names(task_names, by_name)
            except TaskSelectionError:
                raise ServiceError(
                    "author_task_selection",
                    "请选择目录中的非空精确任务名；空列表或非法/未知名称无效",
                ) from None
            chosen = [by_name[name] for name in sorted(names)]
        else:
            chosen = catalog
        reference = selected["resolved"]
        request_scope = {
            "mode": "selected" if partial else "all",
            "tasks": chosen if partial else [],
        }
        base = self.data.root / "author-inputs"
        base.mkdir(exist_ok=True, mode=0o700)
        # Legacy keys were full-only; new keys encode scope explicitly. A selected
        # download can never create or satisfy a full-dataset cache entry.
        cache = (
            base
            / hashlib.sha256(
                json.dumps({"source": reference, "scope": request_scope}, sort_keys=True).encode()
            ).hexdigest()
        )
        if not cache.exists():
            with tempfile.TemporaryDirectory(dir=base) as tmp:
                target = __import__("pathlib").Path(tmp)
                options = {"selected_tasks": chosen} if partial else {}
                source = source_call(
                    reference,
                    key=self.hub_key(selected.get("source_version"))
                    if selected.get("source_version")
                    else None,
                    target=target / "tasks",
                    **options,
                )
                expected = {(t["name"], t["package"], t["ref"]) for t in chosen}
                actual = {(t["directory"], t["package"], t["ref"]) for t in source["tasks"]}
                if (
                    source["resolved"] != reference
                    or actual != expected
                    or len(source["tasks"]) != len(chosen)
                ):
                    raise ServiceError(
                        "author_task_selection", "下载任务与已验证目录范围/ref不匹配", 409
                    )
                write_json(target / "source.json", source)
                write_json(target / "scope.json", request_scope)
                try:
                    target.rename(cache)
                except OSError:
                    if not cache.is_dir():
                        raise
        if read_json(cache / "scope.json") != request_scope:
            raise ServiceError("author_task_selection", "作者检查缓存范围不匹配", 409)
        source = read_json(cache / "source.json")
        if source["resolved"] != reference or {
            (t["directory"], t["package"], t["ref"]) for t in source["tasks"]
        } != {(t["name"], t["package"], t["ref"]) for t in chosen}:
            raise ServiceError("author_task_selection", "缓存任务与已验证目录/ref不匹配", 409)
        scanned = []
        for task in source["tasks"]:
            try:
                discovery = discover(cache / "tasks", {**source, "tasks": [task]})
            except AuthorInputError as error:
                discovery: dict = {
                    "variables": {},
                    "fixed_names": [],
                    "blocked": error.issues,
                    "budgets": [],
                    "images": [],
                    "source": reference,
                }
            scanned.append(
                {
                    "name": task["directory"],
                    "package": task["package"],
                    "ref": task["ref"],
                    "snapshot_digest": task["snapshot_digest"],
                    "discovery": discovery,
                }
            )
        with self.data.store.control():
            current = self.ready_dataset(object_id)
            if current["resolved"] != reference or current["tasks"] != catalog:
                raise ServiceError("configuration_changed", "数据集来源已变更；请重新检查", 409)
            old = self.author_parameters(object_id)
            records = {}
            if old.get("source") == reference:
                records = {
                    r["name"]: r
                    for r in old.get("checked_tasks", [])
                    if r["name"] in by_name and r["ref"] == by_name[r["name"]]["ref"]
                }
                # Pre-scope releases only produced full discoveries. Split these
                # genuine full results so partial refresh cannot erase them.
                if not records and old.get("discovery"):
                    for task in catalog:
                        previous = old["discovery"]
                        discovery: dict = {
                            "source": reference,
                            "fixed_names": previous.get("fixed_names", []),
                        }
                        discovery["variables"] = {
                            name: [u for u in uses if u["task"] == task["package"]]
                            for name, uses in previous["variables"].items()
                            if any(u["task"] == task["package"] for u in uses)
                        }
                        for field in ("blocked", "budgets", "images"):
                            discovery[field] = [
                                item for item in previous[field] if item["task"] == task["package"]
                            ]
                        records[task["name"]] = {**task, "discovery": discovery}
            was_complete = len(records) == len(catalog)
            for record in scanned:
                if not partial or not was_complete:
                    records[record["name"]] = record
            return self._persist_author_discoveries(
                object_id,
                reference,
                catalog,
                records,
                old["values"] if old.get("source") == reference else {},
                request_scope,
                names,
            )

    def _persist_author_discoveries(
        self, object_id, reference, catalog, records, values, request_scope, requested_names
    ):
        from harbor_helper.execution.author_inputs import AuthorInputError, check_inputs

        records = dict(sorted(records.items()))
        discovery: dict = {
            "variables": {},
            "fixed_names": [],
            "blocked": [],
            "budgets": [],
            "images": [],
            "source": reference,
        }
        for record in records.values():
            part = record["discovery"]
            for name, uses in part["variables"].items():
                discovery["variables"].setdefault(name, []).extend(uses)
            for field in ("fixed_names", "blocked", "budgets", "images"):
                discovery[field].extend(part[field])
        discovery["fixed_names"] = sorted(set(discovery["fixed_names"]))
        values = {k: v for k, v in values.items() if k in discovery["variables"]}
        issues = []
        try:
            check_inputs(discovery, values)
        except AuthorInputError as error:
            issues = error.issues
        complete = len(records) == len(catalog)
        scope = {
            "mode": "all" if complete else "partial",
            "complete": complete,
            "total": len(catalog),
            "unknown": len(catalog) - len(records),
            "tasks": [
                {"name": r["name"], "package": r["package"], "ref": r["ref"]}
                for r in records.values()
            ],
        }
        blocked = any(
            item["reason"] in {"compose_discovery_failed", "task_schema_unsupported"}
            for item in issues
        )
        status = "blocked" if blocked else "missing" if issues else "checked"
        if not complete:
            status = "partial_" + status
        return self.persist(
            "author_parameters",
            {
                "id": object_id,
                "source": reference,
                "values": values,
                "discovery": discovery,
                "checked_tasks": list(records.values()),
                "scope": scope,
                "last_check_scope": request_scope,
                "requested_task_names": requested_names,
                "status": status,
                "issues": issues,
                "checked": time.time(),
            },
        )

    @wake_after
    def save_author_parameters(self, object_id, values):
        from harbor_helper.execution.author_inputs import AuthorInputError, check_inputs

        with self.data.store.control():
            selected = self.ready_dataset(object_id)
            old = self.author_parameters(object_id)
            if old.get("source") != selected["resolved"] or "discovery" not in old:
                raise ServiceError("author_inputs_unchecked", "先检查当前来源作者参数", 409)
            issues = []
            try:
                check_inputs(old["discovery"], values)
            except AuthorInputError as error:
                issues = error.issues
            except ValueError:
                raise ServiceError(
                    "author_input_invalid", "仅可填写已发现的非秘密作者参数"
                ) from None
            return self.persist(
                "author_parameters",
                {
                    **old,
                    "values": values,
                    "status": ("" if old.get("scope", {}).get("complete", True) else "partial_")
                    + ("missing" if issues else "checked"),
                    "issues": issues,
                    "checked": time.time(),
                },
            )

    def catalog(self):
        datasets = []
        for value in self.data.objects("dataset"):
            try:
                self.ready_dataset(value["id"])
                ready = True
                readiness_error = None
            except ServiceError as error:
                ready = False
                readiness_error = {"code": error.code, "message": str(error)}
            datasets.append(
                {
                    **value,
                    "ready": ready,
                    "readiness_error": readiness_error,
                    "author_parameters": self.author_parameters(value["id"]),
                }
            )
        return {
            "datasets": datasets,
            "settings": self.settings(),
            "hub": self.hub_status(),
        }
