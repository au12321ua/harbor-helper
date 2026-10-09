"""Versioned web catalog consumed by immutable submissions."""

import json
import re
import secrets
import time
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from harbor_helper.config import DEFAULT, reject_secrets
from harbor_helper.service_data import ServiceError, identifier, secret_value
from harbor_helper.service_sources import source_call
from harbor_helper.storage import read_json, write_json


class TeamConfiguration:
    def __init__(self, data):
        self.data = data
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
            nonce = secrets.token_bytes(12)
            encrypted = AESGCM(self.data._master()).encrypt(
                nonce, key.encode(), f"hub/{version}".encode()
            )
            db.execute(
                "INSERT INTO source_credentials(version,enabled,nonce,ciphertext,updated_at) "
                "VALUES(?,1,?,?,?)", (version, nonce, encrypted, time.time())
            )
        return self.hub_status()

    def hub_key(self, version=None):
        with self.data.store.connect() as db:
            row = db.execute(
                "SELECT * FROM source_credentials "
                + ("WHERE version=?" if version else "ORDER BY version DESC LIMIT 1"),
                (version,) if version else (),
            ).fetchone()
        if not row:
            if version:
                raise ServiceError("source_auth", "Bound team Hub credential unavailable", 409)
            return None
        if not row["enabled"]:
            if version:
                raise ServiceError("source_auth", "Bound team Hub credential disabled", 409)
            return None
        try:
            return (
                AESGCM(self.data._master())
                .decrypt(row["nonce"], row["ciphertext"], f"hub/{row['version']}".encode())
                .decode()
            )
        except (InvalidTag, UnicodeError):
            raise ServiceError(
                "source_auth", "Team Hub credential cannot be decrypted", 409
            ) from None

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
        allowed = (
            {"id", "name", "enabled", "reference", "runtime_id"}
            if kind == "dataset"
            else {"id", "name", "enabled", "image", "image_env"}
        )
        if (
            set(value) - allowed
            or not isinstance(value.get("name"), str)
            or not 1 <= len(value["name"].strip()) <= 128
        ):
            raise ServiceError("catalog_options", "Use a name and supported catalog fields")
        value = {**value, "enabled": value.get("enabled", True), "status": "unverified"}
        if type(value["enabled"]) is not bool:
            raise ServiceError("catalog_options", "Enabled must be boolean")
        if kind == "dataset":
            if not isinstance(value.get("reference"), str) or not re.fullmatch(
                r"[\w.-]+/[\w.-]+@(?:[1-9][0-9]*|sha256:[0-9a-f]{64})", value["reference"]
            ):
                raise ServiceError("dataset_reference", "数据集须指定 owner/name@版本")
            self.data.object("runtime", value.get("runtime_id"))
        else:
            if not isinstance(value.get("image"), str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_./:@-]{0,255}", value["image"]
            ):
                raise ServiceError("runtime_image", "Use a Docker image reference")
            value.setdefault("image_env", DEFAULT["runtime_image_env"])
            if not isinstance(value["image_env"], list) or not all(
                isinstance(x, str) and re.fullmatch(r"[A-Z_][A-Z0-9_]*", x)
                for x in value["image_env"]
            ):
                raise ServiceError(
                    "runtime_environment", "Image environment names must be uppercase names"
                )
        return self.persist(kind, value)

    def verify(self, kind, object_id):
        with self.data.store.control():
            value = self.data.object(kind, object_id)
            initial_version = value["version"]
            hub = self.hub_status()
            source_key = self.hub_key() if kind == "dataset" else None
        try:
            if kind == "runtime":
                from harbor_helper.runs import image_identity

                try:
                    value["image_id"] = image_identity(value["image"])
                except (ValueError, OSError):
                    raise ServiceError(
                        "runtime_missing",
                        "镜像不可用；部署负责人加载/拉取该镜像并检查 Docker 权限，再点击验证",
                        409,
                    ) from None
            else:
                runtime = self.ready_runtime(value["runtime_id"])
                value.update(source_call(value["reference"], key=source_key))
                value["runtime_version"] = runtime["version"]
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

    def ready_runtime(self, object_id):
        value = self.data.object("runtime", object_id)
        if not value["enabled"] or value["status"] != "verified":
            raise ServiceError("runtime_unverified", "管理员须启用并验证运行环境", 409)
        return value

    def ready_dataset(self, object_id):
        value = self.data.object("dataset", object_id)
        if not value["enabled"] or value["status"] != "verified":
            raise ServiceError("dataset_unverified", "管理员须启用并验证数据集", 409)
        runtime = self.ready_runtime(value["runtime_id"])
        if runtime["version"] != value["runtime_version"]:
            raise ServiceError("dataset_stale", "运行环境已修改；管理员须重新验证数据集", 409)
        if value.get("source_version"):
            self.hub_key(value["source_version"])
        return value, runtime

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
            datasets.append({**value, "ready": ready, "readiness_error": readiness_error})
        return {
            "datasets": datasets,
            "runtimes": self.data.objects("runtime"),
            "settings": self.settings(),
            "hub": self.hub_status(),
        }
