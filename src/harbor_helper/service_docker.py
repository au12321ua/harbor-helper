"""Bounded read-only Docker discovery; never return daemon diagnostics or config."""

import json
import re
import subprocess
import tempfile
import time

LIMIT = 1024 * 1024
MAX_IMAGES = 200


def _query(args):
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            ["docker", *args], stdout=output, stderr=errors
        )
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise TimeoutError from None
        if process.returncode:
            errors.seek(0)
            if b"permission denied" in errors.read(4096).lower():
                raise PermissionError
            raise RuntimeError
        output.seek(0)
        value = output.read(LIMIT + 1)
        if len(value) > LIMIT:
            raise OverflowError
        return value.decode("utf-8")


def discover_docker():
    result = {"checked_at": time.time(), "images": [], "truncated": False}
    try:
        _query(["--version"])
    except FileNotFoundError:
        return {**result, "state": "missing", "message": "服务端未安装 Docker CLI，请部署负责人安装。"}
    except (OSError, RuntimeError, TimeoutError, OverflowError, UnicodeError):
        return {**result, "state": "client_error", "message": "Docker CLI 无法运行，请部署负责人检查安装。"}
    try:
        _query(["info", "--format", "{{.ServerVersion}}"])
    except PermissionError:
        return {**result, "state": "permission_denied", "message": "Docker已安装，但服务账户没有daemon访问权限；请部署负责人检查socket权限。"}
    except (OSError, RuntimeError, TimeoutError, OverflowError, UnicodeError):
        return {**result, "state": "daemon_unavailable", "message": "Docker daemon 不可达或服务账户无权限，请部署负责人检查 daemon 和 socket 权限。"}
    try:
        text = _query(["image", "ls", "--no-trunc", "--format", "{{json .}}"])
        seen = set()
        for line in text.splitlines():
            row = json.loads(line)
            repository, tag = row.get("Repository"), row.get("Tag")
            reference = f"{repository}:{tag}" if repository and tag and "<none>" not in (repository, tag) else row.get("ID", "")
            if not isinstance(reference, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@-]{0,255}", reference):
                continue
            if reference in seen:
                continue
            seen.add(reference)
            if len(result["images"]) == MAX_IMAGES:
                result["truncated"] = True
                break
            result["images"].append({"reference": reference})
    except (OSError, RuntimeError, TimeoutError, OverflowError, UnicodeError, ValueError, TypeError, AttributeError):
        return {**result, "state": "images_unavailable", "message": "Docker 可达，但无法读取本地镜像列表；可手动填写引用并验证。"}
    return {**result, "state": "ready", "message": "Docker daemon 可达，当前服务账户可读取本地镜像。列表不证明任务兼容，保存后仍需验证。"}
