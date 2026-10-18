"""Explicit team Hub credential and isolated, bounded Harbor input client."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

import httpx
from harbor.models.task.id import PackageTaskId

from harbor_helper.service.primitives import ServiceError


def source_error(error):
    chain = []
    while error is not None and all(error is not item for item in chain):
        chain.append(error)
        error = error.__cause__ or error.__context__
    names = {type(item).__name__ for item in chain}
    if names & {
        "NotAuthenticatedError",
        "InvalidAPIKeyError",
        "RevokedAPIKeyError",
        "ApiKeyRejectedError",
    }:
        return {
            "error": "source_auth",
            "message": "Hub 认证失败；管理员检查团队来源凭据是否有效、过期或已撤销后重新验证",
        }
    if "AuthenticationError" in names or any(
        isinstance(item, (httpx.RequestError, OSError, TimeoutError)) for item in chain
    ):
        return {
            "error": "source_network",
            "message": "无法连接 Hub 或认证服务；部署管理员检查服务的出网代理、DNS、证书与网络后重试。无需因此修改数据集版本",
        }
    return {
        "error": "source_access",
        "message": "Hub 版本或任务不可访问；管理员检查包版本与共享权限后重新验证",
    }


def source_call(reference, *, key=None, target=None, task=None, selected_tasks=None):
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
                        "selected_tasks": selected_tasks,
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
                "source_network",
                "Hub 检查超时或网络不可用；管理员检查网络后重试。数据集较大可选择任务检查作者参数",
                409,
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
    from contextlib import ExitStack

    from harbor_helper.persistence.writers import writer

    # The source helper can outlive a abruptly killed parent. Acquire its own
    # lease before any target IO, independent of inherited process descriptors.
    with ExitStack() as leases:
        _main(leases, writer)


def _main(leases, writer):
    import asyncio

    from harbor.registry.client.package import PackageDatasetClient

    from harbor_helper.execution.sources import UnsupportedDatasetError, resolve_dataset

    request = json.load(sys.stdin)
    if request.get("target"):
        target = Path(request["target"]).resolve()
        for parent in target.parents:
            if (parent / "queue.sqlite").exists():
                leases.enter_context(writer(parent))
                break

    async def execute():
        if request["target"]:
            options = {}
            if request.get("selected_tasks") is not None:
                options["selected_tasks"] = request["selected_tasks"]
            return await resolve_dataset(
                request["reference"], Path(request["target"]), request["task"], **options
            )
        metadata = await PackageDatasetClient().get_dataset_metadata(request["reference"])
        if metadata.metrics or metadata.files:
            raise UnsupportedDatasetError("Dataset-level custom metrics/files unsupported")
        if not cast(str, metadata.version).startswith("sha256:"):
            raise ValueError("Unsupported dataset")
        tasks = [
            {"name": t.name, "package": t.get_name(), "ref": t.ref}
            for t in cast(list[PackageTaskId], metadata.task_ids)
        ]
        if not tasks or any(not cast(str, t["ref"]).startswith("sha256:") for t in tasks):
            raise ValueError("Unsupported tasks")
        return {"resolved": metadata.name + "@" + cast(str, metadata.version), "tasks": tasks}

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
        if name == "TaskSelectionError":
            print(
                json.dumps(
                    {
                        "error": "author_task_selection",
                        "message": "所选任务与已验证目录的名称/ref不匹配；重新验证来源",
                    }
                )
            )
            sys.exit(1)
        if name == "UnsupportedDatasetError":
            print(
                json.dumps(
                    {
                        "error": "dataset_features_unsupported",
                        "message": "当前服务不支持数据集级metrics/files；请选择不含这些扩展的数据集。不是凭据错误。",
                    }
                )
            )
            sys.exit(1)
        print(json.dumps(source_error(error)))
        sys.exit(1)


if __name__ == "__main__":
    main()
