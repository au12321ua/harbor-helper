"""Process and durable-job compatibility across the package migration.

No Docker, Hub or provider requests: Job.create exercises native validation only;
source subprocesses use a copied package with a clearly substituted Hub boundary.
"""

import asyncio
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

from support.paths import REPO

from harbor_helper.execution import agent_tools
from harbor_helper.persistence.files import read_json, write_json


def test_cli_and_harbor_paths_in_fresh_process(tmp_path):
    env = {"PATH": os.defpath, "HOME": str(tmp_path / "home"), "LANG": "C.UTF-8"}
    code = """
import asyncio
import sys
from harbor.job import Job
from harbor.models.job.config import JobConfig
from harbor_helper.execution.agents import HelperOpenCode, BundledOpenCode
from harbor_helper.execution.environments import NativeDockerEnvironment
for agent in ("HelperOpenCode", "BundledOpenCode"):
    kwargs = {"helper_tool_cache": "cache", "version": "1.18.35"}
    if agent == "BundledOpenCode": kwargs["helper_bundle"] = "bundle"
    config = JobConfig.model_validate({"job_name": "compat", "jobs_dir": "jobs",
        "tasks": [{"path": sys.argv[1]}], "agents": [{"import_path": "harbor_helper.execution.agents:" + agent,
        "model_name": "vllm/fixture", "kwargs": kwargs}]})
    asyncio.run(Job.create(config))
print("native Job options validated")
"""
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            code,
            str(REPO / "examples/harbor-helper-switch-smoke/harbor-helper-switch-answer"),
        ],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "native Job options validated" in result.stdout
    for entry in ("harbor_helper.commands.main",):
        result = subprocess.run(
            [sys.executable, "-B", "-m", entry, "service", "serve", "--help"],
            cwd=tmp_path,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "--setup-token-file" in result.stdout
        assert "RuntimeWarning" not in result.stderr
    assert not (tmp_path / "home").exists()  # Help/import never creates user credentials/state.


def test_real_downloader_module_from_unrelated_directory(tmp_path, monkeypatch):
    cache = tmp_path / "agent-tools"
    cached = cache / "opencode-1.2.3-linux-x64-baseline"
    cached.mkdir(parents=True)
    content = b"public-tool-fixture-no-execution"
    (cached / "opencode").write_bytes(content)
    write_json(
        cached / "material.json",
        {
            "version": "1.2.3",
            "platform": "linux-x64-baseline",
            "strategy": agent_tools.STRATEGY,
            "binary_sha256": hashlib.sha256(content).hexdigest(),
        },
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.chdir(tmp_path)
    value = asyncio.run(agent_tools.prepare(cache, "1.2.3", "linux-x64-baseline", logs))
    assert value["cache_hit"] and Path(value["path"]) == cached
    evidence = read_json(logs / "helper-tool-staging.json")
    assert evidence["owner_pid"] == os.getpid() and evidence["child_pid"] != os.getpid()
    assert not (cache / evidence["directory"]).exists()
    assert (cached / "opencode").read_bytes() == content
    assert not list(cache.glob(".download-*"))


def test_real_hub_client_subprocess_package_root_and_isolated_home(tmp_path):
    package = tmp_path / "harbor_helper"
    shutil.copytree(
        REPO / "src/harbor_helper",
        package,
        ignore=shutil.ignore_patterns("__pycache__", "static"),
    )
    # Only the network-facing client main is replaced. Production source_call,
    # subprocess launch, env allowlist and returned isolation gate are unchanged.
    source = package / "service/sources.py"
    text = source.read_text()
    fixture = """
def main():
    request = json.load(sys.stdin)
    from harbor.auth.constants import CREDENTIALS_PATH
    from harbor_helper.commands.remote import selected_profile
    print(json.dumps({"resolved": request["reference"], "tasks": [], "_client": {
        "home": str(Path.home()), "profile": selected_profile(),
        "stored_credentials": CREDENTIALS_PATH.exists()}}))

"""
    source.write_text(
        text.replace('if __name__ == "__main__":', fixture + 'if __name__ == "__main__":')
    )
    env = {"PATH": os.defpath, "HOME": str(tmp_path / "private-home"), "LANG": "C.UTF-8"}
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            (
                "from harbor_helper.service.sources import source_call; "
                'assert source_call("fixture/data@1") == {"resolved": "fixture/data@1", "tasks": []}; '
                'print("isolated source subprocess validated")'
            ),
        ],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "isolated source subprocess validated" in result.stdout
