"""Real CLI/scheduler/worker processes; execution boundary is a local no-network fixture.

Only the copied package's Hub download, Docker identity/tag and execute coroutine
are replaced. Queue, auth, TTL, locks, process identity, output and audit are real.
"""

import copy
import json
import os
import pty
import select
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harbor_helper.auth import Auth, AuthError, resolve_state, select_team, ttl_seconds
from harbor_helper.config import DEFAULT
from harbor_helper.storage import Store, read_json, write_json
from harbor_helper.worker import process_birth

FAKE_KEY = "fixture-K1-no-provider-123456789"
FAKE_KEY2 = "fixture-K2-no-provider-987654321"
MODEL = {
    "endpoint": "https://fixture.invalid/v1",
    "name": "fixture-model",
    "declared_version": "unknown",
    "credential_env": "VLLM_API_KEY",
    "opencode_version": "1.18.35",
}


def wait_for(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("Fixture condition timed out")


class Client:
    def __init__(self, root):
        self.root = root
        self.cwd = root / "work"
        self.cwd.mkdir()
        self.home = root / "home"
        self.home.mkdir()
        self.state = root / "team"
        self.env = {**os.environ, "HOME": str(self.home)}
        for key in ("HARBOR_HELPER_STATE", "VLLM_API_KEY", "OPENAI_API_KEY", "PYTHONPATH"):
            self.env.pop(key, None)
        # A copied fixture package makes the same safe subprocess import path work.
        package = self.cwd / "harbor_helper"
        shutil.copytree(
            Path(__file__).resolve().parents[1] / "src/harbor_helper",
            package,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        with (package / "sources.py").open("a") as output:
            output.write("""
async def resolve_dataset(reference, target, task_filter=None):
    target.mkdir()
    task = target / "generation--box"
    task.mkdir()
    (task / "task.toml").write_text("fixture input")
    return {"requested": reference, "resolved": "fixture/data@sha256:fixed", "tasks": [
        {"package": "fixture/generation--box", "directory": task.name,
         "ref": "sha256:fixed", "snapshot_digest": tree_digest(task)}]}
""")
        with (package / "runs.py").open("a") as output:
            output.write("""
def image_identity(reference):
    return "sha256:" + "f" * 64
_original_subprocess_run = subprocess.run
def _fixture_run(argv, *args, **kwargs):
    if argv[:2] == ["docker", "tag"]:
        return subprocess.CompletedProcess(argv, 0)
    return _original_subprocess_run(argv, *args, **kwargs)
subprocess.run = _fixture_run
""")
        worker = package / "worker.py"
        text = worker.read_text()
        fixture = """
async def execute(store, run_id):
    # No network/provider/Harbor execution. Native-shaped result for report regression.
    path = store.path(run_id)
    model = read_json(path / "manifest.json")["effective"]
    if model["agent"] == "opencode":
        from harbor_helper.auth import Auth
        Auth(store.root).worker_credentials(run_id, model["model"]["endpoint"])
    (path / "fixture-started").write_text("no network execution boundary")
    raw = path / "fixture-native.log"
    raw.write_text(os.environ.get("VLLM_API_KEY", "oracle"))
    while (store.root / "fixture-hold").exists():
        await asyncio.sleep(0.05)
    trial = path / "harbor" / run_id / "box__fixture"
    trial.mkdir(parents=True)
    write_json(trial / "result.json", {"task_name": "fixture/generation--box",
        "trial_name": "box__fixture", "verifier_result": {"rewards": {"reward": 0.0}},
        "exception_info": None})
    return {"status": "succeeded", "reason": None}

"""
        worker.write_text(
            text.replace('if __name__ == "__main__":', fixture + 'if __name__ == "__main__":')
        )
        team = copy.deepcopy(DEFAULT)
        team["model"] = MODEL
        config = root / "config.json"
        write_json(config, team)
        self.call("init", "--config", str(config), explicit=True)
        self.key = root / "key"
        self.key.write_text(FAKE_KEY + "\n")
        self.key.chmod(0o600)

    def command(self, *args, explicit=False):
        return [
            sys.executable,
            "-m",
            "harbor_helper.cli",
            *(["--state", str(self.state)] if explicit else []),
            *args,
        ]

    def call(self, *args, explicit=False, ok=True, human=False, env=None):
        command = self.command(*args, explicit=explicit)
        if not human:
            command.append("--json")
        result = subprocess.run(
            command,
            check=False,
            cwd=self.cwd,
            env=env or self.env,
            text=True,
            capture_output=True,
            timeout=20,
        )
        assert FAKE_KEY not in result.stdout + result.stderr
        assert FAKE_KEY2 not in result.stdout + result.stderr
        if ok:
            assert result.returncode == 0, result.stderr
        else:
            assert result.returncode != 0, result.stdout
        if human or not ok:
            return result
        return json.loads(result.stdout)

    def login(self, ttl="8h"):
        return self.call("auth", "login", "--key-file", str(self.key), "--ttl", ttl)

    def row(self, run_id):
        return Store(self.state).get(run_id)

    def terminal(self, run_id):
        return wait_for(
            lambda: (
                self.row(run_id)
                if self.row(run_id)["status"]
                in {"succeeded", "failed", "cancelled", "cleanup_blocked"}
                else None
            )
        )

    def shutdown(self):
        # Fixture-only teardown, exact owned worker/scheduler PID+birth.
        if self.state.exists():
            for row in Store(self.state).runs():
                if row["pid"] and process_birth(row["pid"]) == row["birth"]:
                    os.killpg(row["pid"], signal.SIGKILL)
            path = self.state / "scheduler.json"
            if path.exists():
                identity = read_json(path)
                if process_birth(identity["pid"]) == identity["birth"]:
                    os.kill(identity["pid"], signal.SIGKILL)
                    wait_for(lambda: process_birth(identity["pid"]) != identity["birth"])


@pytest.fixture
def client(tmp_path):
    value = Client(tmp_path)
    try:
        yield value
    finally:
        value.shutdown()


def test_reconnect_default_model_and_human_json_oracle(client):
    assert client.call("auth", "status")["logged_in"] is False
    before = list((client.state / "runs").iterdir())
    result = client.call("submit", ok=False)
    assert "auth login" in result.stderr
    assert list((client.state / "runs").iterdir()) == before
    assert not (client.state / "scheduler.json").exists()
    assert "Oracle requires" in client.call("submit", "--preset", "default", ok=False).stderr
    team = read_json(client.state / "team.json")
    team["model"] = None
    write_json(client.state / "team.json", team)
    assert "Model not configured" in client.call("submit", ok=False).stderr
    assert not list((client.state / "runs").iterdir())
    team["model"] = MODEL
    write_json(client.state / "team.json", team)
    before_key = client.key.stat()
    assert client.login()["valid"]
    assert client.key.stat().st_ino == before_key.st_ino
    assert client.key.stat().st_mtime_ns == before_key.st_mtime_ns
    run_id = client.call("submit", "--attempts", "1", "--wall-seconds", "1200")["run_id"]
    assert client.terminal(run_id)["status"] == "succeeded"
    path = client.state / "runs" / run_id
    assert read_json(path / "manifest.json")["effective"]["agent"] == "opencode"
    assert FAKE_KEY not in (path / "fixture-native.log").read_text()
    report = client.call("report", run_id)
    assert report["complete"] and report["tasks"][0]["mean_rewards"] == {"reward": 0.0}
    assert run_id in client.call("list", human=True).stdout
    assert client.call("status", run_id)["status"] == "succeeded"
    # Global --json remains active even when subcommand parser defaults are absent.
    global_result = subprocess.run(
        client.command("--json", "auth", "status"),
        check=False,
        cwd=client.cwd,
        env=client.env,
        capture_output=True,
        text=True,
    )
    assert json.loads(global_result.stdout)["valid"]
    client.call("auth", "logout")
    assert client.call("submit", ok=False).returncode == 1
    oracle = client.call("submit", "--agent", "oracle")["run_id"]
    assert client.terminal(oracle)["status"] == "succeeded"
    assert (client.state / "runs" / oracle / "fixture-native.log").read_text() == "oracle"
    client.call("stop")
    assert client.call("scan")["clean"]


def test_private_modes_binding_and_no_copied_reference(client):
    client.login()
    private = client.home / ".config/harbor-helper"
    for path in [private, private / "auth", *list((private / "auth").iterdir())]:
        assert path.stat().st_mode & 0o777 == 0o700
    for path in private.rglob("*"):
        if path.is_file():
            assert path.stat().st_mode & 0o777 == 0o600
            assert FAKE_KEY not in path.read_text()
    inside = client.state / "inside-key"
    inside.write_text(FAKE_KEY)
    inside.chmod(0o600)
    assert (
        "outside experiment state"
        in client.call("auth", "login", "--key-file", str(inside), ok=False).stderr
    )
    assert client.call("auth", "status")["valid"]
    client.key.chmod(0o644)
    assert not client.call("auth", "status")["valid"]
    client.call("submit", ok=False)
    client.key.chmod(0o600)
    team = read_json(client.state / "team.json")
    team["model"]["endpoint"] = "https://other.invalid/v1"
    write_json(client.state / "team.json", team)
    assert not client.call("auth", "status")["endpoint_matches"]
    client.call("submit", ok=False)


def test_ttl_at_dequeue_and_active_cleanup(client):
    client.login("3s")
    hold = client.state / "fixture-hold"
    hold.touch()
    first = client.call("submit")["run_id"]
    wait_for(lambda: (client.state / "runs" / first / "fixture-started").exists())
    second = client.call("submit")["run_id"]
    assert client.row(second)["status"] == "queued"
    client.call("auth", "logout", ok=False)
    client.call("auth", "login", "--key-file", str(client.key), ok=False)
    assert client.terminal(second)["status"] == "failed"
    assert "not started" in client.row(second)["reason"]
    assert not (client.state / "runs" / second / "fixture-started").exists()
    assert client.row(second)["pid"] is None
    client.call("submit", ok=False)
    assert client.call("status", first)["status"] == "running"
    assert "terminal credential audit" in client.call("report", first, ok=False).stderr
    hold.unlink()
    assert client.terminal(first)["status"] == "succeeded"
    assert client.call("report", first)["complete"]
    client.call("rerun", first, ok=False)
    client.call("stop")
    assert client.call("scan")["clean"]


def test_rotation_history_missing_source_is_scoped(client):
    client.login()
    first = client.call("submit")["run_id"]
    assert client.terminal(first)["status"] == "succeeded"
    assert client.call("auth", "logout")["historical_audit_retained"]
    history = client.call("auth", "status")
    assert not history["logged_in"] and history["historical_audit_retained"]
    assert history["audit_sessions"] == 1
    key2 = client.root / "key2"
    key2.write_text(FAKE_KEY2)
    key2.chmod(0o600)
    client.call("auth", "login", "--key-file", str(key2))
    (client.state / "runs" / first / "historical.log").write_text(FAKE_KEY)
    client.call("stop")
    matched = json.loads(client.call("scan", ok=False).stdout)
    assert matched["matched_files"] == 1 and not matched["clean"]
    (client.state / "runs" / first / "historical.log").unlink()
    client.key.unlink()
    missing = json.loads(client.call("scan", ok=False).stdout)
    assert not missing["audit_complete"] and not missing["clean"]
    client.call("logs", first, ok=False)
    assert client.call("status", first)["status"] == "succeeded"
    second = client.call("submit")["run_id"]
    assert client.terminal(second)["status"] == "succeeded"
    assert client.call("report", second)["complete"]


def test_idle_scheduler_refresh_and_stop_confirmed(client):
    client.call("recover")
    old = read_json(client.state / "scheduler.json")
    client.login()
    current = read_json(client.state / "scheduler.json")
    assert current != old and process_birth(old["pid"]) != old["birth"]
    assert process_birth(current["pid"]) == current["birth"]
    client.call("scan", ok=False)
    result = client.call("stop")
    assert result["confirmed"] and process_birth(current["pid"]) != current["birth"]
    assert client.call("scan")["clean"]


@pytest.mark.parametrize("damage", ["delete", "permissions", "replace"])
def test_hard_crash_unavailable_audit_releases_capacity_but_withholds_logs(client, damage):
    client.login()
    (client.state / "fixture-hold").touch()
    run_id = client.call("submit")["run_id"]
    wait_for(lambda: (client.state / "runs" / run_id / "fixture-started").exists())
    row = client.row(run_id)
    scheduler = read_json(client.state / "scheduler.json")
    os.kill(scheduler["pid"], signal.SIGKILL)
    wait_for(lambda: process_birth(scheduler["pid"]) != scheduler["birth"])
    os.killpg(row["pid"], signal.SIGKILL)
    wait_for(lambda: process_birth(row["pid"]) != row["birth"])
    if damage == "delete":
        client.key.unlink()
    elif damage == "permissions":
        client.key.chmod(0o644)
    else:
        client.key.write_text(FAKE_KEY2)
    client.call("recover")
    assert client.terminal(run_id)["status"] == "failed"
    assert client.row(run_id)["audit_status"] == "incomplete"
    assert not (client.state / "runs" / run_id / "report.json").exists()
    assert client.row(run_id)["finished"] is not None
    client.call("logs", run_id, ok=False)
    # Restore identity; recover now audits the original key without new execution.
    client.key.write_text(FAKE_KEY)
    client.key.chmod(0o600)
    wait_for(lambda: client.row(run_id)["audit_status"] == "clean")
    assert FAKE_KEY not in (client.state / "runs" / run_id / "fixture-native.log").read_text()
    client.call("stop")
    assert client.call("scan")["clean"]


def test_hard_crash_expired_login_can_audit(client):
    client.login("2s")
    (client.state / "fixture-hold").touch()
    run_id = client.call("submit")["run_id"]
    wait_for(lambda: (client.state / "runs" / run_id / "fixture-started").exists())
    row = client.row(run_id)
    scheduler = read_json(client.state / "scheduler.json")
    os.kill(scheduler["pid"], signal.SIGKILL)
    os.killpg(row["pid"], signal.SIGKILL)
    wait_for(lambda: process_birth(scheduler["pid"]) != scheduler["birth"])
    wait_for(lambda: client.call("auth", "status")["expired"])
    client.call("recover")
    assert client.terminal(run_id)["status"] == "failed"
    assert read_json(client.state / "runs" / run_id / "credential-audit.json")["clean"]
    assert len(list((client.state / "runs").iterdir())) == 1


def test_hidden_interactive_input(client):
    master, slave = pty.openpty()
    process = subprocess.Popen(
        client.command("auth", "login", "--json"),
        cwd=client.cwd,
        env=client.env,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
    )
    os.close(slave)
    output = b""
    try:
        deadline = time.monotonic() + 10
        while b"API key (hidden):" not in output:
            assert time.monotonic() < deadline
            if select.select([master], [], [], 0.2)[0]:
                output += os.read(master, 65536)
        assert b"Team:" in output and b"fixture.invalid" in output
        os.write(master, (FAKE_KEY + "\n").encode())
        process.wait(timeout=10)
        while select.select([master], [], [], 0.1)[0]:
            try:
                output += os.read(master, 65536)
            except OSError:
                break
        assert process.returncode == 0
        assert FAKE_KEY.encode() not in output
        assert client.call("auth", "status")["source"] == "cache"
    finally:
        os.close(master)
        if process.poll() is None:
            process.kill()


def test_state_precedence_and_team_binding(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    selected = tmp_path / "selected"
    select_team(selected)
    assert resolve_state() == selected
    monkeypatch.setenv("HARBOR_HELPER_STATE", str(tmp_path / "env"))
    assert resolve_state() == tmp_path / "env"
    assert resolve_state(tmp_path / "explicit") == tmp_path / "explicit"
    a, b = Store(tmp_path / "a"), Store(tmp_path / "b")
    key = tmp_path / "key"
    key.write_text(FAKE_KEY)
    key.chmod(0o600)
    Auth(a.root).login(a, MODEL, 60, key)
    with pytest.raises(AuthError, match="Not logged in"):
        Auth(b.root).execution(MODEL["endpoint"])


@pytest.mark.parametrize("value", ["0", "-1", "inf", "nan", "0h", "text"])
def test_invalid_ttl(value):
    with pytest.raises(ValueError):
        ttl_seconds(value)


def test_unused_sessions_removed_and_logout_revokes_stale_env(client):
    client.login()
    client.login()
    private = client.home / ".config/harbor-helper/auth"
    assert len(list(private.rglob("session-*.json"))) == 1
    assert not client.call("auth", "logout")["historical_audit_retained"]
    assert not client.call("auth", "status")["historical_audit_retained"]
    assert len(list(private.rglob("session-*.json"))) == 0
    result = client.call("submit", ok=False, env={**client.env, "VLLM_API_KEY": FAKE_KEY})
    assert "auth login" in result.stderr
    assert not list((client.state / "runs").iterdir())


def test_concurrent_submit_login_and_single_scheduler(client):
    from concurrent.futures import ThreadPoolExecutor

    client.login()
    (client.state / "fixture-hold").touch()
    with ThreadPoolExecutor(3) as pool:
        ids = list(pool.map(lambda _: client.call("submit")["run_id"], range(3)))
    assert len(set(ids)) == 3
    wait_for(lambda: sum(client.row(i)["status"] == "running" for i in ids) == 1)
    assert sum(client.row(i)["status"] == "queued" for i in ids) == 2
    private = client.home / ".config/harbor-helper/auth"
    before = list(private.rglob("session-*.json"))
    client.call("auth", "login", "--key-file", str(client.key), ok=False)
    assert list(private.rglob("session-*.json")) == before
    client.call("stop", ok=False)
    for run_id in ids:
        client.call("cancel", run_id)
    wait_for(lambda: all(client.row(i)["status"] == "cancelled" for i in ids))
    client.call("stop")
    assert client.call("scan")["clean"]


def test_scan_unreadable_file_directory_and_safe_encoded_logs(client):
    client.login()
    run_id = client.call("submit")["run_id"]
    assert client.terminal(run_id)["status"] == "succeeded"
    import base64

    worker_log = client.state / "runs" / run_id / "worker.log"
    worker_log.write_text(base64.b64encode(FAKE_KEY.encode()).decode())
    assert client.call("logs", run_id) == "[REDACTED]"
    client.call("report", run_id, ok=False)
    worker_log.write_text("[REDACTED]")
    client.call("stop")
    unreadable = client.state / "unreadable"
    unreadable.write_text("safe")
    unreadable.chmod(0o000)
    try:
        result = json.loads(client.call("scan", ok=False).stdout)
        assert result["unreadable_files"] == 1 and not result["clean"]
    finally:
        unreadable.chmod(0o600)
    directory = client.state / "hidden"
    directory.mkdir()
    (directory / "data").write_text(FAKE_KEY)
    directory.chmod(0o000)
    try:
        result = json.loads(client.call("scan", ok=False).stdout)
        assert result["unreadable_files"] == 1 and not result["clean"]
    finally:
        directory.chmod(0o700)


def test_stop_wait_and_timeout_never_report_false_success(tmp_path):
    from harbor_helper.runs import stop_supervisor

    store = Store(tmp_path / "state")
    program = "import signal,time;signal.signal(signal.SIGTERM,lambda *a:time.sleep(0.4));print('ready',flush=True);time.sleep(20)"
    child = subprocess.Popen([sys.executable, "-c", program], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        identity = {"pid": child.pid, "birth": process_birth(child.pid)}
        write_json(store.root / "scheduler.json", identity)
        with pytest.raises(ValueError, match="timed out"):
            stop_supervisor(store, timeout=0.05)
        assert process_birth(child.pid) == identity["birth"]
    finally:
        child.kill()
        child.wait()
    program = "import signal,time,sys;signal.signal(signal.SIGTERM,lambda *a:(time.sleep(0.2),sys.exit(0)));print('ready',flush=True);time.sleep(20)"
    child = subprocess.Popen([sys.executable, "-c", program], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        write_json(
            store.root / "scheduler.json", {"pid": child.pid, "birth": process_birth(child.pid)}
        )
        started = time.monotonic()
        assert stop_supervisor(store)["confirmed"]
        assert time.monotonic() - started >= 0.2
        assert process_birth(child.pid) is None
    finally:
        child.kill() if child.poll() is None else None
        child.wait()


def test_current_k2_cannot_claim_unbound_legacy_k1(client):
    from harbor_helper.auth import secure_read, secure_write

    client.login()
    first = client.call("submit")["run_id"]
    assert client.terminal(first)["status"] == "succeeded"
    client.call("auth", "logout")
    key2 = client.root / "key2"
    key2.write_text(FAKE_KEY2)
    key2.chmod(0o600)
    client.call("auth", "login", "--key-file", str(key2))
    bindings_file = next((client.home / ".config/harbor-helper/auth").glob("*/bindings.json"))
    bindings = secure_read(bindings_file)
    bindings.pop(first)
    secure_write(bindings_file, bindings)
    # Simulated pre-native-auth historical run: shared manifest is untouched.
    client.call("stop")
    value = json.loads(client.call("scan", ok=False).stdout)
    assert not value["audit_complete"] and not value["clean"]
    client.call("logs", first, ok=False)
    client.call("report", first, ok=False)
    assert client.call("status", first)["status"] == "succeeded"
    client.call("stop")
    explicit = {**client.env, "VLLM_API_KEY": FAKE_KEY}
    assert client.call("scan", env=explicit)["clean"]
    assert isinstance(client.call("logs", first, env=explicit), str)
    second = client.call("submit")["run_id"]
    assert client.terminal(second)["status"] == "succeeded"
