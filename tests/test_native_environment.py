"""New execution contract and exact cleanup, without registry/model requests."""

import asyncio
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
from harbor.environments.docker.docker import DockerEnvironment

from harbor_helper.execution.environments import (
    NativeDockerEnvironment,
    anonymous_volumes,
    owned_anonymous_volumes,
)
from harbor_helper.execution.runs import job_config
from harbor_helper.execution.worker import cleanup
from harbor_helper.persistence.files import read_json, tree_digest, write_json
from harbor_helper.service.application import Application
from harbor_helper.service.data import ServiceData
from harbor_helper.service.lifecycle import prepare_one


def test_native_submit_and_legacy_rerun_keep_parent_snapshot(tmp_path, monkeypatch):
    data = ServiceData.initialize(
        tmp_path / "state", tmp_path / "private/master", "admin", "fake-native-password-2026"
    )
    app = Application(data.root)
    actor = data.users()[0]

    def source(reference, *, target=None, **kwargs):
        directory = target / "task"
        directory.mkdir(parents=True)
        (directory / "task.toml").write_text('version = "1.0"\n# author original input')
        return {
            "requested": reference,
            "resolved": reference,
            "tasks": [
                {
                    "package": "test/task",
                    "directory": "task",
                    "ref": "fixed",
                    "snapshot_digest": tree_digest(directory),
                }
            ],
        }

    monkeypatch.setattr("harbor_helper.service.sources.source_call", source)
    monkeypatch.setattr(
        "harbor_helper.execution.runs.image_identity", lambda _: pytest.fail("No image gate")
    )
    monkeypatch.setattr("harbor_helper.execution.runs.ensure_supervisor", lambda _: None)
    accepted = app.accept(actor, {"agent": "oracle", "dataset": "test/data@1"}, "first")
    prepare_one(data.store)
    parent = data.submission(accepted["id"])["run_id"]
    folder = data.store.path(parent)
    manifest = read_json(folder / "manifest.json")
    assert "image_id" not in manifest and "image_alias" not in manifest
    assert read_json(folder / "job.json")["environment"].get("env", {}) == {}
    assert read_json(folder / "job.json")["environment"]["import_path"].endswith(
        ":NativeDockerEnvironment"
    )
    # Historical accepted input remains unchanged while a new rerun removes the override.
    manifest.pop("execution_mode")
    manifest["image_id"] = "sha256:missing"
    manifest["effective"]["runtime_image"] = "missing:legacy"
    manifest["effective"]["runtime_image_env"] = ["CAD_BENCH_AGENT_IMAGE"]
    write_json(folder / "manifest.json", manifest)
    before = (folder / "manifest.json").read_bytes()
    accepted = app.accept(actor, {}, "rerun", parent)
    assert accepted["legacy_override_removed"]
    prepare_one(data.store)
    child = data.submission(accepted["id"])["run_id"]
    child_manifest = read_json(data.store.path(child) / "manifest.json")
    assert child_manifest["legacy_override_removed"]
    assert child_manifest["source"] == manifest["source"]
    assert (folder / "manifest.json").read_bytes() == before
    assert (
        data.store.path(child) / "tasks/task/task.toml"
    ).read_bytes() == b'version = "1.0"\n# author original input'
    assert "runtime_image" not in child_manifest["effective"]
    assert job_config(data.store.path(child), child_manifest)["environment"].get("env", {}) == {}


def test_native_adapter_preserves_build_up_and_down_volumes(monkeypatch, tmp_path):
    calls = []

    async def original(self, command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout="")

    async def observe(self):
        calls.append("observe")

    monkeypatch.setattr(DockerEnvironment, "_run_docker_compose_command", original)
    monkeypatch.setattr(NativeDockerEnvironment, "_observe", observe)
    env = object.__new__(NativeDockerEnvironment)
    env.session_id = "owned-test"
    env.trial_paths = SimpleNamespace(trial_dir=tmp_path)
    asyncio.run(
        env._run_docker_compose_command(["down", "--rmi", "local", "--volumes", "--remove-orphans"])
    )
    assert calls == ["observe", ["down", "--volumes", "--remove-orphans"]]
    assert NativeDockerEnvironment.start is DockerEnvironment.start
    assert NativeDockerEnvironment.stop is DockerEnvironment.stop
    with pytest.raises(ValueError, match="cannot keep"):
        NativeDockerEnvironment(keep_containers=True)


def test_anonymous_ownership_excludes_explicit_external_and_named():
    anonymous, external = "a" * 64, "b" * 64
    container = {
        "HostConfig": {"Binds": [external + ":/external:rw", "named:/named:rw"]},
        "Mounts": [{"Type": "volume", "Name": v} for v in (anonymous, external, "named")],
    }
    assert anonymous_volumes(container) == [anonymous]


def test_hard_exit_cleanup_persists_anonymous_and_does_not_remove_external(tmp_path, monkeypatch):
    anonymous, external = "a" * 64, "b" * 64
    write_json(tmp_path / "projects.json", ["owned"])
    volumes = {anonymous, external}
    commands = []
    container = {
        "HostConfig": {"Mounts": [{"Source": external}]},
        "Mounts": [{"Type": "volume", "Name": anonymous}, {"Type": "volume", "Name": external}],
    }

    def docker(argv):
        commands.append(argv)
        if argv[:2] == ["docker", "inspect"]:
            return json.dumps([container])
        if argv[:3] == ["docker", "ps", "-aq"]:
            return "container" if len(commands) == 1 else ""
        if argv[:3] == ["docker", "volume", "ls"] and len(argv) == 4:
            return " ".join(volumes)
        if argv[:3] == ["docker", "volume", "rm"]:
            volumes.remove(argv[3])
        return ""

    monkeypatch.setattr("harbor_helper.execution.worker.run_command", docker)
    cleanup(tmp_path)
    assert volumes == {external}
    assert read_json(tmp_path / "cleanup.json")["anonymous_volumes"] == [anonymous]
    assert read_json(tmp_path / "owned-anonymous-volumes.json") == [anonymous]
    assert not any("prune" in command or "--rmi" in command for command in commands)


def test_compose_credentials_absent_from_build_up_but_exec_forwards(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text("""import asyncio, os
from harbor.environments.docker.docker import DockerEnvironment
from harbor_helper.security.credentials import install_docker_credential_forwarding
os.environ['VLLM_API_KEY']='fake-build-marker'
os.environ['HF_TOKEN']='fake-hub-marker'
DockerEnvironment._compose_env_vars=lambda self,**kw:dict(os.environ)
async def original(self, command, **kwargs):
    env=self._compose_env_vars(include_os_env=True)
    if command[0]=='exec':
        assert env['VLLM_API_KEY']=='fake-build-marker'
        assert command==['exec','-e','VLLM_API_KEY','main','true']
    else:
        assert 'VLLM_API_KEY' not in env and 'HF_TOKEN' not in env
DockerEnvironment._run_docker_compose_command=original
install_docker_credential_forwarding()
env=object.__new__(DockerEnvironment)
for command in [['build'],['up','--wait'],['exec','-e','VLLM_API_KEY=fake-build-marker','main','true']]:
    asyncio.run(env._run_docker_compose_command(command))
""")
    result = subprocess.run(
        [sys.executable, str(probe)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_already_accepted_legacy_preparation_retains_image_contract(tmp_path, monkeypatch):
    data = ServiceData.initialize(
        tmp_path / "state", tmp_path / "private/master", "admin", "fake-native-password-2026"
    )
    app = Application(data.root)
    accepted = app.accept(data.users()[0], {"agent": "oracle", "dataset": "test/data@1"}, "old")
    original = data.submission(accepted["id"])["frozen"]
    original["service"].pop("execution_mode")
    original["effective"].update(
        runtime_image="legacy:fixed", runtime_image_env=["CAD_BENCH_AGENT_IMAGE"]
    )
    with data.store.connect() as db:
        db.execute(
            "UPDATE submissions SET frozen=? WHERE id=?", (json.dumps(original), accepted["id"])
        )

    def source(reference, *, target=None, **kwargs):
        directory = target / "task"
        directory.mkdir(parents=True)
        (directory / "task.toml").write_text('version = "1.0"\n# author input')
        return {
            "resolved": reference,
            "tasks": [
                {
                    "package": "test/task",
                    "directory": "task",
                    "ref": "fixed",
                    "snapshot_digest": tree_digest(directory),
                }
            ],
        }

    calls = []
    monkeypatch.setattr("harbor_helper.service.sources.source_call", source)
    monkeypatch.setattr(
        "harbor_helper.execution.runs.image_identity",
        lambda image: calls.append(image) or "sha256:old",
    )
    monkeypatch.setattr("harbor_helper.execution.runs.subprocess.run", lambda *a, **kw: None)
    monkeypatch.setattr("harbor_helper.execution.runs.ensure_supervisor", lambda _: None)
    prepare_one(data.store)
    assert calls == ["legacy:fixed"]
    folder = data.store.path(data.submission(accepted["id"])["run_id"])
    manifest = read_json(folder / "manifest.json")
    assert "execution_mode" not in manifest
    assert manifest["image_id"] == "sha256:old"
    assert read_json(folder / "job.json")["environment"]["env"] == {
        "CAD_BENCH_AGENT_IMAGE": "harbor-helper/runtime:old"
    }
    assert data.submission(accepted["id"])["frozen"] == original


def test_shared_volumes_from_are_not_owned():
    shared, owned = "a" * 64, "b" * 64
    container = {
        "HostConfig": {"VolumesFrom": ["external-container:ro"]},
        "Mounts": [{"Type": "volume", "Name": v} for v in (shared, owned)],
    }

    def inspect(reference):
        assert reference == "external-container"
        return [{"Mounts": [{"Type": "volume", "Name": shared}]}]

    assert owned_anonymous_volumes([container], inspect) == {owned}
