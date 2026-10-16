"""Provider/profile rules with explicit metadata reads and version persistence."""

import re
import uuid
from collections.abc import Callable
from typing import cast

from harbor_helper.execution.config import reject_secrets
from harbor_helper.service.primitives import ServiceError, identifier


class Models:
    def __init__(
        self,
        *,
        read_object: Callable[[str, str], dict],
        read_credential: Callable[[str], dict],
        save_version: Callable[[str, dict], dict],
    ):
        """Use metadata only; callers retain control-lock and transaction ownership."""
        self._read_object = read_object
        self._read_credential = read_credential
        self._save_version = save_version

    def save_object(self, kind, value):
        object_id = identifier(value.get("id") or uuid.uuid4().hex)
        value = dict(value)
        value["id"] = object_id
        value.pop("version", None)
        reject_secrets(value)
        if kind == "provider":
            if set(value) - {"id", "name", "protocol", "endpoint", "enabled"}:
                raise ServiceError("provider_options", "Unknown provider options")
            from urllib.parse import urlparse

            url = urlparse(value.get("endpoint", ""))
            if (
                value.get("protocol") != "openai-compatible"
                or url.scheme not in {"http", "https"}
                or not url.hostname
            ):
                raise ServiceError(
                    "unsupported_provider",
                    "First release supports explicit OpenAI-compatible endpoints",
                )
        elif kind == "profile":
            if set(value) - {
                "id",
                "name",
                "provider_id",
                "credential_id",
                "model",
                "params",
                "opencode_version",
                "enabled",
            }:
                raise ServiceError("profile_options", "Unknown model profile options")
            provider = self._read_object("provider", cast(str, value.get("provider_id")))
            credential = self._read_credential(cast(str, value.get("credential_id")))
            if credential["provider_id"] != provider["id"]:
                raise ServiceError("credential_binding", "Credential belongs to another provider")
            if (
                not isinstance(value.get("model"), str)
                or not value["model"]
                or not isinstance(value.get("params", {}), dict)
            ):
                raise ServiceError("invalid_model", "Model ID and parameter mapping are required")
            value.setdefault("params", {})
            value.setdefault("opencode_version", "1.18.35")
            if not re.fullmatch(r"\d+\.\d+\.\d+", value["opencode_version"]):
                raise ServiceError(
                    "invalid_runtime", "A fixed numeric OpenCode version is required"
                )
        else:
            raise ServiceError("configuration_kind", "Unsupported configuration")
        value.setdefault("enabled", True)
        if type(value["enabled"]) is not bool:
            raise ServiceError("invalid_status", "enabled must be boolean")
        return self._save_version(kind, value)
