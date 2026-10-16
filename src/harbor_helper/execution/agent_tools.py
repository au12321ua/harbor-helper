"""Public fixed agent tools, downloaded outside the task network and uploaded by Harbor.

No task images, provider configuration, keys or npm user configuration enter this process.
The cache is disposable; its manifest is evidence, not a benchmark admission requirement.
"""

import asyncio
import base64
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import IO, cast
from urllib.parse import urlsplit

from harbor_helper.persistence.files import read_json, write_json

STRATEGY = "offline-npm-binary-v1"
PLATFORMS = {"linux-x64-baseline", "linux-arm64", "linux-x64-musl", "linux-arm64-musl"}


class ToolPreparationError(RuntimeError):
    def __init__(self, classification):
        self.classification = classification
        super().__init__(
            f"Public fixed agent tool preparation failed ({classification}); task network unchanged"
        )


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verified_material(path, version, platform):
    value = read_json(path / "material.json")
    if (
        value["version"] != version
        or value["platform"] != platform
        or value["strategy"] != STRATEGY
        or digest(path / "opencode") != value["binary_sha256"]
    ):
        raise ValueError("Agent tool cache verification failed")
    return value


def download(cache, version, platform, staging):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or platform not in PLATFORMS:
        raise ValueError("Invalid fixed agent tool selection")
    cache, staging = Path(cache), Path(staging)
    name = f"opencode-{version}-{platform}"
    target = cache / name
    with (cache / (name + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.exists():
            value = verified_material(target, version, platform)
            print(json.dumps({"path": str(target), "cache_hit": True, "material": value}))
            return
        # Parent passes only anonymous HTTP(S) transport proxies, never npm config.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler())
        package = "opencode-" + platform
        with opener.open(f"https://registry.npmjs.org/{package}/{version}", timeout=30) as r:
            metadata = json.load(r)
        source = f"https://registry.npmjs.org/{package}/-/{package}-{version}.tgz"
        if metadata["dist"]["tarball"] != source:
            raise ValueError("Unexpected public agent tool source")
        integrity = metadata["dist"]["integrity"]
        if not integrity.startswith("sha512-"):
            raise ValueError("Missing SHA512 registry integrity")
        archive = staging / "package.tgz"
        h = hashlib.sha512()
        with opener.open(source, timeout=30) as r, archive.open("wb") as out:
            while block := r.read(1024 * 1024):
                h.update(block)
                out.write(block)
        if h.digest() != base64.b64decode(integrity[7:], validate=True):
            raise ValueError("Public agent package integrity mismatch")
        export = staging / "export"
        export.mkdir()
        with tarfile.open(archive) as tar:
            member = tar.getmember("package/bin/opencode")
            if not member.isfile():
                raise ValueError("Invalid agent executable")
            with (
                cast("IO[bytes]", tar.extractfile(member)) as src,
                (export / "opencode").open("wb") as out,
            ):
                shutil.copyfileobj(src, out)
        (export / "opencode").chmod(0o755)
        value = {
            "strategy": STRATEGY,
            "version": version,
            "platform": platform,
            "source": source,
            "registry_integrity": integrity,
            "archive_sha256": digest(archive),
            "binary_sha256": digest(export / "opencode"),
        }
        write_json(export / "material.json", value)
        export.rename(target)
        print(json.dumps({"path": str(target), "cache_hit": False, "material": value}))


def cleanup_staging(run_dir, process_birth):
    """Reclaim this run's interrupted download only after both process identities exit."""
    cache = run_dir.parents[1] / "agent-tools"
    entries = []
    for evidence in run_dir.glob("harbor/*/*/agent/helper-tool-staging.json"):
        try:
            value = read_json(evidence)
            if not isinstance(value, dict) or any(
                type(value.get(k)) is not int for k in ("owner_pid", "child_pid")
            ):
                continue
        except (ValueError, OSError):
            continue
        name = value.get("directory", "")
        if not re.fullmatch(r"\.download-[A-Za-z0-9_-]+", name):
            continue
        target = cache / name
        if target.exists() and not target.is_symlink():
            identities = [
                (process_birth(value[k]), value.get(k + "_birth"))
                for k in ("owner_pid", "child_pid")
            ]
            if any(
                actual is not None and (expected is None or actual == expected)
                for actual, expected in identities
            ):
                entries.append({"directory": name, "released": False})
                continue
            try:
                shutil.rmtree(target)
            except OSError:
                pass  # Cache debris must not claim that execution resources remain allocated.
        entries.append(
            {"directory": name, "released": not (target.exists() or target.is_symlink())}
        )
    if entries:
        write_json(run_dir / "tool-staging-cleanup.json", entries)


async def prepare(cache, version, platform, evidence_dir=None):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".download-", dir=cache) as staging:
        # No HOME, authenticated proxies, provider/Hub keys or credential files.
        transport = {"PATH": os.defpath, "LANG": "C.UTF-8"}
        for name in ("http_proxy", "https_proxy"):
            value = os.environ.get(name) or os.environ.get(name.upper())
            if value:
                proxy = urlsplit(value)
                if (
                    proxy.scheme in {"http", "https"}
                    and proxy.hostname
                    and not (
                        proxy.username
                        or proxy.password
                        or proxy.query
                        or proxy.fragment
                        or proxy.path not in {"", "/"}
                    )
                ):
                    transport[name] = value
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "harbor_helper.execution.agent_tools",
            str(cache),
            version,
            platform,
            staging,
            env=transport,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            if evidence_dir:
                from harbor_helper.execution.processes import process_birth

                write_json(
                    Path(evidence_dir) / "helper-tool-staging.json",
                    {
                        "directory": Path(staging).name,
                        "owner_pid": os.getpid(),
                        "owner_pid_birth": process_birth(os.getpid()),
                        "child_pid": child.pid,
                        "child_pid_birth": process_birth(child.pid),
                    },
                )
            out, _ = await child.communicate()
            if child.returncode:
                try:
                    classification = json.loads(out).get("error_type")
                except (ValueError, AttributeError):
                    classification = None
                if classification not in {
                    "HTTPError",
                    "URLError",
                    "TimeoutError",
                    "ValueError",
                    "OSError",
                    "KeyError",
                }:
                    classification = "unknown"
                raise ToolPreparationError(classification)
            return json.loads(out)
        finally:
            if child.returncode is None:
                child.terminate()
                try:
                    await asyncio.wait_for(child.wait(), timeout=5)
                except TimeoutError:
                    child.kill()
                    await child.wait()


def main():
    try:
        download(*sys.argv[1:])
    except Exception as error:  # noqa: BLE001 - public downloader boundary must never echo payloads
        # No HTTP response body, proxy URL or arbitrary exception message in evidence.
        print(json.dumps({"error_type": type(error).__name__}))
        sys.exit(1)


if __name__ == "__main__":
    main()
