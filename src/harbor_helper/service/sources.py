"""Explicit team Hub credential and isolated, bounded Harbor input client."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from harbor_helper.service.data import ServiceError


def source_call(reference, *, key=None, target=None, task=None):
    # Never inherit user HOME, Harbor credentials, model credentials or cloud profiles.
    with tempfile.TemporaryDirectory(prefix="hh-source-") as home:
        env = {
            k: v
            for k, v in os.environ.items()
            if k
            in {
                "PATH",
                "LANG",
                "SSL_CERT_FILE",
                "SSL_CERT_DIR",
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "NO_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
                "no_proxy",
            }
        }
        env.update(
            HOME=home, XDG_CONFIG_HOME=home, PYTHONPATH=str(Path(__file__).resolve().parents[2])
        )
        if key:
            env["HARBOR_API_KEY"] = key
        try:
            result = subprocess.run(
                [sys.executable, "-m", "harbor_helper.service.sources"],
                input=json.dumps(
                    {
                        "reference": reference,
                        "target": str(target) if target else None,
                        "task": task,
                    }
                ),
                env=env,
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
            value = json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            raise ServiceError(
                "source_network", "Hub 检查超时或网络不可用；管理员检查网络后重新验证", 409
            ) from None
        if result.returncode or "error" in value:
            raise ServiceError(
                value.get("error", "source_access"), value.get("message", "Hub 不可访问"), 409
            )
        isolation = value.pop("_client", {})
        if isolation != {"home": home, "profile": None, "stored_credentials": False}:
            raise ServiceError(
                "source_isolation", "Hub client isolation could not be confirmed", 503
            )
        return value


def main():
    import asyncio

    from harbor.registry.client.package import PackageDatasetClient

    from harbor_helper.execution.sources import resolve_dataset

    request = json.load(sys.stdin)

    async def execute():
        if request["target"]:
            return await resolve_dataset(
                request["reference"], Path(request["target"]), request["task"]
            )
        metadata = await PackageDatasetClient().get_dataset_metadata(request["reference"])
        if not metadata.version.startswith("sha256:") or metadata.metrics or metadata.files:
            raise ValueError("Unsupported dataset")
        tasks = [{"name": t.name, "package": t.get_name(), "ref": t.ref} for t in metadata.task_ids]
        if not tasks or any(not t["ref"].startswith("sha256:") for t in tasks):
            raise ValueError("Unsupported tasks")
        return {"resolved": metadata.name + "@" + metadata.version, "tasks": tasks}

    try:
        value = asyncio.run(execute())
        from harbor.auth.constants import CREDENTIALS_PATH

        from harbor_helper.commands.remote import selected_profile

        value["_client"] = {
            "home": str(Path.home()),
            "profile": selected_profile(),
            "stored_credentials": CREDENTIALS_PATH.exists(),
        }
        print(json.dumps(value))
    except Exception as error:  # noqa: BLE001 - third party exceptions must never escape
        # Use types only; remote text can carry credentials/paths.
        name = type(error).__name__
        code = (
            "source_auth"
            if name in {"NotAuthenticatedError", "InvalidAPIKeyError", "RevokedAPIKeyError"}
            else "source_access"
        )
        print(
            json.dumps(
                {
                    "error": code,
                    "message": "Hub 版本或任务不可访问；管理员检查团队来源凭据、包版本与共享权限后重新验证",
                }
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
