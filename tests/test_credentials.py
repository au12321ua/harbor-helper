import asyncio
import io
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from harbor.environments.docker.docker import DockerEnvironment

from harbor_helper.execution.processes import process_birth
from harbor_helper.execution.scheduler import tick
from harbor_helper.persistence.files import write_json
from harbor_helper.persistence.store import Store
from harbor_helper.security.credentials import (
    RedactedStream,
    audit_run,
    install_docker_credential_forwarding,
    read_key_file,
    scan_tree,
    scrub_file,
)

MARKER = "synthetic-private-marker-for-tests-only"


def fixture_run(root):
    store = Store(root)
    run_id = "hh-credential-test"
    path = store.root / "runs" / run_id
    path.mkdir()
    write_json(
        path / "manifest.json",
        {
            "source": {"tasks": [{"package": "fixture/box"}]},
            "effective": {
                "agent": "opencode",
                "model": {"credential_env": "VLLM_API_KEY"},
                "attempts": 1,
                "wall_seconds": 600,
            },
        },
    )
    with store.connect() as db:
        db.execute(
            "INSERT INTO runs(id,status,created,concurrency) VALUES(?,?,?,?)",
            (run_id, "running", time.time(), 1),
        )
    return store, path


def test_protected_file_rejects_modes_symlinks_and_multiline(tmp_path):
    key = tmp_path / "key"
    key.write_text(MARKER + "\n")
    key.chmod(0o600)
    assert read_key_file(key) == MARKER
    key.chmod(0o640)
    with pytest.raises(ValueError):
        read_key_file(key)
    key.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(key)
    with pytest.raises(OSError):
        read_key_file(link)
    key.write_text(MARKER + "\nsecond-value")
    with pytest.raises(ValueError):
        read_key_file(key)


@pytest.mark.parametrize("split", range(1, len(MARKER)))
def test_cross_write_and_flush_never_release_secret(split):
    target = io.StringIO()
    stream = RedactedStream(target, [MARKER])
    stream.write("before " + MARKER[:split])
    stream.flush()
    stream.write(MARKER[split:] + " after\n")
    stream.finish()
    assert target.getvalue() == "before [REDACTED] after\n"


def test_large_binary_scan_and_scrub_chunk_boundary(tmp_path):
    data = b"\x00" * 65530 + MARKER.encode() + b"\xff" * 21_000_000
    path = tmp_path / "binary"
    path.write_bytes(data)
    assert not scan_tree(tmp_path, [MARKER])["clean"]
    scrub_file(path, [MARKER])
    assert scan_tree(tmp_path, [MARKER])["clean"]
    assert path.read_bytes() == data.replace(MARKER.encode(), b"[REDACTED]")
    assert not scan_tree(tmp_path / "missing", [MARKER])["clean"]


def test_clean_container_owned_log_requires_no_write(tmp_path, monkeypatch):
    path = tmp_path / "clean.log"
    path.write_bytes(b"readable native log without credentials")
    before = path.stat()
    monkeypatch.setattr(
        "harbor_helper.security.credentials.tempfile.mkstemp",
        lambda **kwargs: pytest.fail("Clean logs must not require write access"),
    )
    scrub_file(path, [MARKER])
    assert path.stat().st_ino == before.st_ino
    assert path.stat().st_mtime_ns == before.st_mtime_ns


def test_actual_spawn_argv_contains_name_and_env_contains_value(tmp_path, monkeypatch):
    monkeypatch.setenv("VLLM_API_KEY", MARKER)
    install_docker_credential_forwarding()
    probe = tmp_path / "spawn.py"
    probe.write_text(
        "import json,os,sys\n"
        "key=os.environ['VLLM_API_KEY']\n"
        "print(json.dumps({'value_in_argv':any(key in a for a in sys.argv),"
        "'name_in_argv':'VLLM_API_KEY' in sys.argv,'env_present':bool(key)}))\n"
    )

    class ProbeEnvironment:
        session_id = "credential-probe"
        environment_dir = tmp_path
        _docker_compose_paths = ()
        _run_docker_compose_command = DockerEnvironment._run_docker_compose_command

        @staticmethod
        def runtime():
            return SimpleNamespace(
                compose=[sys.executable, str(probe)], supports_compose_project_directory=False
            )

        def _compose_env_vars(self, **kwargs):
            return dict(os.environ)

        _output_callback = lambda self: None
        _collect_buffered_output = staticmethod(DockerEnvironment._collect_buffered_output)

    env = ProbeEnvironment()
    result = asyncio.run(
        DockerEnvironment._compose_exec(
            env,
            "true",
            service="probe",
            cwd=None,
            env={"VLLM_API_KEY": MARKER},
            timeout_sec=5,
            user=None,
        )
    )
    assert json.loads(result.stdout) == {
        "value_in_argv": False,
        "name_in_argv": True,
        "env_present": True,
    }


def test_reason_is_scrubbed_before_sqlite_write(tmp_path, monkeypatch):
    monkeypatch.setenv("VLLM_API_KEY", MARKER)
    store, path = fixture_run(tmp_path / "state")
    store.update(path.name, reason="error " + MARKER)
    assert store.get(path.name)["reason"] == "error [REDACTED]"
    # Inspect fields via SQL, never mutate SQLite bytes.
    assert audit_run(store, path.name, [MARKER])["database_fields_clean"]


def test_database_is_read_by_fields_and_never_byte_rewritten(tmp_path):
    database = tmp_path / "agent.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE evidence(value TEXT)")
        db.execute("INSERT INTO evidence VALUES(?)", (MARKER,))
    before = database.read_bytes()
    scrub_file(database, [MARKER])
    assert database.read_bytes() == before
    assert not scan_tree(tmp_path, [MARKER])["clean"]


def test_unclean_frozen_inputs_withhold_report_but_release_capacity(tmp_path, monkeypatch):
    from harbor_helper.execution.config import DEFAULT

    monkeypatch.setenv("VLLM_API_KEY", MARKER)
    store, path = fixture_run(tmp_path / "state")
    write_json(store.root / "team.json", DEFAULT)
    frozen = path / "tasks" / "box.txt"
    frozen.parent.mkdir()
    frozen.write_text(MARKER)
    tick(store, {})
    assert store.get(path.name)["status"] == "failed"
    assert store.get(path.name)["audit_status"] == "incomplete"
    assert store.get(path.name)["finished"] is not None
    assert not (path / "report.json").exists()
    assert frozen.read_text() == MARKER
    assert not json.loads((path / "credential-audit.json").read_text())["clean"]


@pytest.mark.parametrize("previous", [None, "1.18.34"])
def test_fixed_opencode_installer_uses_system_node_without_nvm(tmp_path, previous):
    from harbor_helper.execution.agents import HelperOpenCode

    calls = []

    async def dependencies(env, packages):
        calls.append(packages)

    async def execute(env, command):
        calls.append(command)

    probes = iter([previous, "1.18.35"])

    async def probe(**kwargs):
        if kwargs["command"].startswith("for tool in"):
            return SimpleNamespace(stdout="", return_code=0)
        version = next(probes)
        return SimpleNamespace(stdout=version, return_code=0 if version else 1)

    agent = SimpleNamespace(
        _version="1.18.35",
        logs_dir=tmp_path,
        ensure_system_dependencies=dependencies,
        exec_as_agent=execute,
    )
    asyncio.run(HelperOpenCode.install(agent, SimpleNamespace(exec=probe)))
    assert "npm i -g opencode-ai@1.18.35" in calls[-1]
    assert "nvm" not in calls[-1]
    decision = json.loads((tmp_path / "install-decision.json").read_text())
    assert decision["previous_version"] == previous
    assert not decision["reused"]
    assert decision["actual_version"] == "1.18.35"
    agent._version = "latest"
    with pytest.raises(ValueError):
        asyncio.run(HelperOpenCode.install(agent, None))


def test_preinstalled_opencode_skips_dependency_and_npm_install(tmp_path):
    from harbor_helper.execution.agents import HelperOpenCode

    async def probe(**kwargs):
        return SimpleNamespace(stdout="1.18.35\n", return_code=0)

    async def unexpected(*args, **kwargs):
        pytest.fail("Matching preinstalled version must skip dependency/npm installation")

    agent = SimpleNamespace(
        _version="1.18.35",
        logs_dir=tmp_path,
        ensure_system_dependencies=unexpected,
        exec_as_agent=unexpected,
    )
    asyncio.run(HelperOpenCode.install(agent, SimpleNamespace(exec=probe)))
    decision = json.loads((tmp_path / "install-decision.json").read_text())
    assert decision["reused"]
    assert decision["actual_version"] == "1.18.35"


def test_opencode_rejects_wrong_version_after_install(tmp_path):
    from harbor_helper.execution.agents import HelperOpenCode

    async def probe(**kwargs):
        return SimpleNamespace(stdout="1.18.34", return_code=0)

    async def install(*args, **kwargs):
        pass

    agent = SimpleNamespace(
        _version="1.18.35",
        logs_dir=tmp_path,
        ensure_system_dependencies=install,
        exec_as_agent=install,
    )
    with pytest.raises(RuntimeError, match="fixed version"):
        asyncio.run(HelperOpenCode.install(agent, SimpleNamespace(exec=probe)))
    decision = json.loads((tmp_path / "install-decision.json").read_text())
    assert not decision["reused"]
    assert decision["actual_version"] == "1.18.34"


def test_hard_exit_scrubs_before_report_and_audits_database(tmp_path, monkeypatch):
    from harbor_helper.execution.config import DEFAULT

    store, path = fixture_run(tmp_path / "state")
    write_json(store.root / "team.json", DEFAULT)
    write_json(store.root / "service.json", {})
    monkeypatch.setattr("harbor_helper.service.data.ServiceData.run_key", lambda *_, **__: MARKER)
    native = path / "harbor" / "job" / "box"
    native.mkdir(parents=True)
    write_json(
        native / "result.json",
        {
            "task_name": "box",
            "exception_info": {"exception_message": MARKER},
            "verifier_result": {"rewards": {"reward": 0}},
        },
    )
    (path / "report.json").write_text(MARKER)
    (path / "worker.log").write_text(MARKER)
    (store.root / "supervisor.log").write_text(MARKER)
    frozen = path / "tasks" / "box.txt"
    frozen.parent.mkdir()
    frozen.write_text("unchanged task")
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True
    )
    store.update(path.name, pid=child.pid, birth=process_birth(child.pid))
    os.kill(child.pid, signal.SIGKILL)
    child.wait(timeout=5)
    assert not audit_run(store, path.name, [MARKER])["clean"]
    tick(store, {})
    assert store.get(path.name)["status"] == "failed"
    assert audit_run(store, path.name, [MARKER])["clean"]
    assert json.loads((path / "credential-audit.json").read_text())["clean"]
    assert MARKER not in (path / "report.json").read_text()
    assert frozen.read_text() == "unchanged task"
