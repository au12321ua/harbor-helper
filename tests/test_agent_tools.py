import asyncio
import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from harbor_helper import agent_tools
from harbor_helper.agents import HelperOpenCode
from harbor_helper.storage import read_json


def registry(monkeypatch, damaged=False):
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        content = b"fixed-platform-executable"
        item = tarfile.TarInfo("package/bin/opencode")
        item.size = len(content)
        tar.addfile(item, io.BytesIO(content))
    body = archive.getvalue()
    source = "https://registry.npmjs.org/opencode-linux-x64-baseline/-/opencode-linux-x64-baseline-1.2.3.tgz"
    meta = json.dumps(
        {
            "dist": {
                "tarball": source,
                "integrity": "sha512-" + base64.b64encode(hashlib.sha512(body).digest()).decode(),
            }
        }
    ).encode()
    calls = []

    class Opener:
        def open(self, url, **kwargs):
            calls.append(url)
            return io.BytesIO(
                meta if not url.endswith(".tgz") else body + (b"damaged" if damaged else b"")
            )

    monkeypatch.setattr(agent_tools.urllib.request, "build_opener", lambda *args: Opener())
    return calls


def test_registry_integrity_and_reusable_verified_cache(tmp_path, monkeypatch, capsys):
    calls = registry(monkeypatch)
    cache = tmp_path / "cache"
    cache.mkdir()
    staging = tmp_path / "staging"
    staging.mkdir()
    agent_tools.download(cache, "1.2.3", "linux-x64-baseline", staging)
    first = json.loads(capsys.readouterr().out)
    assert not first["cache_hit"] and len(calls) == 2
    agent_tools.download(cache, "1.2.3", "linux-x64-baseline", staging)
    assert json.loads(capsys.readouterr().out)["cache_hit"] and len(calls) == 2
    (Path(first["path"]) / "opencode").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="verification"):
        agent_tools.download(cache, "1.2.3", "linux-x64-baseline", staging)
    assert len(calls) == 2  # Never execute or silently accept corrupted material.


def test_damaged_public_archive_is_not_published(tmp_path, monkeypatch):
    registry(monkeypatch, damaged=True)
    with pytest.raises(ValueError, match="integrity mismatch"):
        agent_tools.download(tmp_path, "1.2.3", "linux-x64-baseline", tmp_path)
    assert not (tmp_path / "opencode-1.2.3-linux-x64-baseline").exists()


def test_prepare_cancel_stops_child_and_removes_staging_without_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("VLLM_API_KEY", "fake-do-not-inherit")
    monkeypatch.setenv("HTTPS_PROXY", "http://user:fake-proxy-password@proxy.invalid:80")
    monkeypatch.delenv("https_proxy", raising=False)
    calls = []

    class Child:
        returncode = None

        async def communicate(self):
            await asyncio.sleep(999)

        def terminate(self):
            calls.append("terminate")
            self.returncode = -15

        async def wait(self):
            return self.returncode

    async def spawn(*args, **kwargs):
        assert "VLLM_API_KEY" not in kwargs["env"] and "HOME" not in kwargs["env"]
        assert "https_proxy" not in kwargs["env"]
        calls.append(args)
        return Child()

    monkeypatch.setattr(agent_tools.asyncio, "create_subprocess_exec", spawn)

    async def cancel():
        task = asyncio.create_task(agent_tools.prepare(tmp_path, "1.2.3", "linux-x64-baseline"))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel())
    assert calls[-1] == "terminate" and not list(tmp_path.iterdir())


def test_no_network_offline_upload_avoids_system_installer(tmp_path, monkeypatch):
    async def prepare(*args, **kwargs):
        return {"path": str(tmp_path), "cache_hit": True, "material": {"binary_sha256": "fixed"}}

    monkeypatch.setattr(agent_tools, "prepare", prepare)
    commands, uploads = [], []

    async def execute(command, **kwargs):
        commands.append(command)
        if command.startswith("command -v"):
            return SimpleNamespace(return_code=1, stdout="")
        if command.startswith("uname"):
            return SimpleNamespace(return_code=0, stdout="x86_64\nglibc\n")
        return SimpleNamespace(return_code=0, stdout="1.2.3\n")

    async def upload(**kwargs):
        uploads.append(kwargs)

    agent = object.__new__(HelperOpenCode)
    agent._version = "1.2.3"
    agent.logs_dir = tmp_path
    agent.helper_tool_cache = tmp_path
    env = SimpleNamespace(exec=execute, upload_dir=upload)
    asyncio.run(agent.install(env))
    assert uploads[0]["target_dir"] == "/installed-agent/helper-tools"
    assert not any("apt" in c or "npm" in c for c in commands)
    decision = read_json(tmp_path / "install-decision.json")
    assert decision["status"] == "completed" and decision["cache_hit"]
    assert agent._offline_tool


def test_staging_recovery_preserves_live_child_and_other_cached_tools(tmp_path):
    cache = tmp_path / "agent-tools"
    run = tmp_path / "runs/run"
    logs = run / "harbor/job/trial/agent"
    logs.mkdir(parents=True)
    live = cache / ".download-live"
    live.mkdir(parents=True)
    (live / "partial.tgz").write_bytes(b"partial")
    other = cache / "other-complete-tool"
    other.mkdir()
    from harbor_helper.storage import write_json

    write_json(
        logs / "helper-tool-staging.json",
        {
            "directory": live.name,
            "owner_pid": 101,
            "owner_pid_birth": "owner",
            "child_pid": 102,
            "child_pid_birth": "child",
        },
    )
    agent_tools.cleanup_staging(run, lambda pid: "child" if pid == 102 else None)
    assert live.exists() and other.exists()
    agent_tools.cleanup_staging(run, lambda pid: None)
    assert not live.exists() and other.exists()
    assert read_json(run / "tool-staging-cleanup.json")[0]["released"]


@pytest.mark.parametrize(
    "source,shown",
    [
        (
            "https://registry.npmjs.org/opencode-linux-x64-baseline/-/opencode-linux-x64-baseline-1.2.3.tgz",
            True,
        ),
        ("https://private.invalid/?secret=fake-never-render", False),
    ],
)
def test_tool_diagnosis_exposes_only_safe_public_provenance(tmp_path, source, shown):
    from harbor_helper.reports import trial_diagnosis
    from harbor_helper.storage import write_json

    (tmp_path / "agent").mkdir()
    write_json(
        tmp_path / "agent/install-decision.json",
        {
            "strategy": "offline-npm-binary-v1",
            "stage": "ready",
            "status": "completed",
            "preparation_seconds": 2.5,
            "material": {
                "version": "1.2.3",
                "binary_sha256": "a" * 64,
                "source": source,
                "unrecognized_secret": "fake-never-render",
            },
        },
    )
    value = trial_diagnosis({}, tmp_path, {})["agent_installation"]
    assert ("source" in value) is shown and value["preparation_seconds"] == 2.5
    assert "fake-never-render" not in str(value)
