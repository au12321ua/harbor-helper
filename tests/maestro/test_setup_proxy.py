"""The setup proxy (deployment setting, off by default): offered to the platform's image
builds and to attachment install scripts only, never to the agent or the verifier."""

import asyncio
import json

import pytest
from test_fix_prep_docker import make_spec, no_progress
from test_harbor_executor import (
    RecordingSink,
    agent_spec,
    attachment_spec,
    execute,
    make_executor,
)

from maestro.config import Settings
from maestro.core.errors import MaestroError
from maestro.execution.attachments import AttachmentStore
from maestro.execution.preparation import DockerEnvironment

PROXY = "http://172.17.0.1:7890"


def settings(tmp_path, **values) -> Settings:
    return Settings(
        data_dir=tmp_path / "data", cache_dir=tmp_path / "cache", master_key_dir=tmp_path / "k",
        **values,
    )  # fmt: skip


def test_off_by_default_and_checked_when_set(tmp_path):
    assert settings(tmp_path).check().setup_proxy_env() == {}
    env = settings(tmp_path, setup_proxy=PROXY, setup_no_proxy="localhost,10.0.0.0/8")
    assert env.check().setup_proxy_env() == {
        "HTTP_PROXY": PROXY,
        "HTTPS_PROXY": PROXY,
        "NO_PROXY": "localhost,10.0.0.0/8",
        "http_proxy": PROXY,
        "https_proxy": PROXY,
        "no_proxy": "localhost,10.0.0.0/8",
    }
    for bad in ("socks5://172.17.0.1:7890", "http://172.17.0.1", "172.17.0.1:7890"):
        with pytest.raises(MaestroError, match="setup_proxy"):
            settings(tmp_path, setup_proxy=bad).check()
    loopback = settings(tmp_path, setup_proxy="http://127.0.0.1:7890").check()
    assert any("127.0.0.1" in note for note in loopback.advice())


def test_image_builds_get_the_proxy_as_build_arguments(tmp_path):
    calls = []

    async def run(*args, timeout):
        calls.append(args)
        return 0, "", ""

    environment = DockerEnvironment(
        tmp_path / "archives", proxy_env=settings(tmp_path, setup_proxy=PROXY).setup_proxy_env()
    )
    environment._run = run
    detail = asyncio.run(environment._build(make_spec(tmp_path), "t:tmp", no_progress))
    (args,) = calls
    assert f"HTTP_PROXY={PROXY}" in args and f"https_proxy={PROXY}" in args
    assert args[args.index(f"HTTP_PROXY={PROXY}") - 1] == "--build-arg"
    assert detail == {"method": "build", "proxy": True}
    plain = DockerEnvironment(tmp_path / "archives")
    plain._run = run
    calls.clear()
    asyncio.run(plain._build(make_spec(tmp_path), "t:tmp", no_progress))
    assert not any("PROXY" in a.upper() for a in calls[0])


def test_install_scripts_get_the_proxy_and_nothing_else_does(runner_python, materials, tmp_path):
    secret = "http://user:pa55word@172.17.0.1:7890"
    env = settings(tmp_path, setup_proxy=secret).check().setup_proxy_env()
    store = AttachmentStore(tmp_path / "data")
    executor = make_executor(runner_python, materials, tmp_path, attachments=store, setup_env=env)
    execute(executor, attachment_spec(materials, tmp_path, store), RecordingSink())
    request = json.loads((tmp_path / "work" / "request.json").read_text())
    assert request["setup_env"] == env
    # Not in the agent's or the task's environment.
    assert "PROXY" not in json.dumps(request["agent"]).upper()
    assert all("proxy" not in k.lower() for k in request["task_env"])
    # A run without attachments installs nothing, so it is not sent at all.
    execute(executor, agent_spec(materials, tmp_path), RecordingSink())
    request = json.loads((tmp_path / "work" / "request.json").read_text())
    assert request["setup_env"] == {}
    # A password in the proxy address is redacted like any known secret.
    assert executor.setup_env["HTTP_PROXY"] == secret


@pytest.fixture
def runner_python(tmp_path):
    import stat
    import sys

    from test_harbor_executor import FAKE_RUNNER

    wrapper = tmp_path / "runner-python"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{FAKE_RUNNER}"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    return wrapper


@pytest.fixture
def materials(tmp_path):
    from maestro.execution.materials import TaskMaterials

    return TaskMaterials(tmp_path / "cache")
