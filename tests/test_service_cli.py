"""Remote adapter boundaries: isolated HOME, fake API, no provider/Hub/Docker."""

import json
import os
import pty
import select
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from harbor_helper.commands.main import parser
from harbor_helper.commands.remote import (
    Client,
    RemoteError,
    load_profile,
    login,
    remote_root,
    service_url,
)
from harbor_helper.commands.service import dispatch as service_dispatch

PASSWORD = "fake-member-password-only"
TOKEN = "fixture-member-access-token-not-model-key"


@pytest.fixture
def api():
    calls = []
    submissions = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, body, code=200, binary=False):
            content = body if binary else json.dumps(body).encode()
            self.send_response(code)
            self.send_header(
                "Content-Type", "application/octet-stream" if binary else "application/json"
            )
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_POST(self):
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.headers.get("X-Requested-With") != "harbor-helper":
                return self.respond({"code": "header", "message": "missing write header"}, 403)
            if self.path == "/api/v1/auth/login":
                body = json.loads(data)
                if body["password"] != PASSWORD:
                    return self.respond({"code": "invalid_login", "message": "bad password"}, 401)
                return self.respond(
                    {
                        "token": TOKEN,
                        "user": {"id": "member-1", "username": body["username"], "role": "member"},
                    }
                )
            if self.headers.get("Authorization") != "Bearer " + TOKEN:
                return self.respond({"code": "login_required", "message": "Please log in"}, 401)
            body = json.loads(data)
            calls.append((self.path, body, self.headers.get("Idempotency-Key")))
            if self.path == "/api/v1/submissions":
                key = self.headers.get("Idempotency-Key")
                value = submissions.setdefault(
                    key,
                    {
                        "id": "sub-" + str(len(submissions)),
                        "status": "preparing",
                        "run_id": None,
                        "request": body,
                    },
                )
                return self.respond(value, 202)
            if self.path == "/api/v1/compare":
                return self.respond(
                    {
                        "comparable": False,
                        "reasons": ["Different dataset"],
                        "left": body["left"],
                        "right": body["right"],
                        "tasks": [],
                        "mean_task_delta": None,
                    }
                )
            return self.respond(
                {"cancel_requested": True} if self.path.endswith("/cancel") else {"ok": True}
            )

        def do_GET(self):
            if self.headers.get("Authorization") != "Bearer " + TOKEN:
                return self.respond({"code": "login_required", "message": "Please log in"}, 401)
            calls.append((self.path, None, None))
            if self.path == "/api/v1/me":
                return self.respond({"id": "member-1", "username": "alice", "role": "member"})
            if self.path == "/api/v1/runs":
                return self.respond(
                    {
                        "runs": [{"id": "hh-one", "status": "succeeded", "submitter": "bob"}],
                        "submissions": list(submissions.values()),
                    }
                )
            if self.path.startswith("/api/v1/submissions/"):
                return self.respond(next(iter(submissions.values())))
            if self.path.endswith("/logs"):
                return self.respond({"text": 'literal [bold] "log"\n', "truncated": False})
            if self.path.endswith("/report"):
                return self.respond(
                    {
                        "run_id": "hh-one",
                        "status": "succeeded",
                        "complete": True,
                        "valid_attempts": 1,
                        "expected_attempts": 1,
                        "tasks": [
                            {
                                "task": "box",
                                "valid_attempts": 1,
                                "expected_attempts": 1,
                                "mean_rewards": {"reward": 0.0},
                            }
                        ],
                    }
                )
            if "/artifacts/" in self.path:
                return self.respond(b"safe binary fixture", binary=True)
            if self.path.startswith("/api/v1/runs/"):
                return self.respond(
                    {
                        "row": {"id": "hh-one", "status": "succeeded", "submitter": "bob"},
                        "artifacts": [{"id": "file-one", "name": "result.step"}],
                        "report": None,
                    }
                )
            return self.respond({"model_profiles": [{"id": "team-profile"}]})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port), calls, submissions
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.delenv("HARBOR_HELPER_REMOTE_PROFILE", raising=False)
    monkeypatch.delenv("HARBOR_HELPER_STATE", raising=False)
    return path


def call(home, *args, code=0):
    env = {**os.environ, "HOME": str(home)}
    value = subprocess.run(
        [sys.executable, "-m", "harbor_helper.commands.main", *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert value.returncode == code, value.stderr
    assert TOKEN not in value.stdout + value.stderr
    assert PASSWORD not in value.stdout + value.stderr
    return value


def test_remote_multi_cli_profile_idempotency_and_shared_views(api, home, monkeypatch, tmp_path):
    url, calls, submissions = api
    monkeypatch.setattr("harbor_helper.commands.remote.hidden_input", lambda _: PASSWORD)
    assert login(url, "alice")["logged_in"]
    root = remote_root()
    profile = load_profile("default")
    assert profile["token"] == TOKEN
    assert (root / "profiles/default.json").stat().st_mode & 0o777 == 0o600
    assert root.stat().st_mode & 0o777 == 0o700
    assert PASSWORD not in (root / "profiles/default.json").read_text()
    # Native private auth may be broken; remote does not read it or initialize local state.
    native = root.parent / "auth"
    native.mkdir(mode=0o777)
    native.chmod(0o777)
    result = call(
        home,
        "submit",
        "--model-profile",
        "team-profile",
        "--idempotency-key",
        "retry-one",
        "--json",
    )
    accepted = json.loads(result.stdout)
    assert accepted["status"] == "preparing" and accepted["run_id"] is None
    assert json.loads(call(home, "service", "retry", "--json").stdout) == accepted
    assert len(submissions) == 1
    assert calls[0][1]["model_profile"] == "team-profile"
    assert "user_id" not in calls[0][1]
    assert accepted["id"] in call(home, "list").stdout
    assert json.loads(call(home, "status", accepted["id"], "--json").stdout)["id"] == accepted["id"]
    call(home, "cancel", accepted["id"], "--json")
    assert "bob" in call(home, "status", "hh-one").stdout
    assert json.loads(call(home, "logs", "hh-one", "--json").stdout) == 'literal [bold] "log"\n'
    assert "[bold]" in call(home, "logs", "hh-one").stdout
    assert json.loads(call(home, "report", "hh-one", "--json").stdout)["complete"]
    compare = call(home, "compare", "hh-one", "hh-two", "--json", code=2)
    assert not json.loads(compare.stdout)["comparable"]
    out = tmp_path / "download.step"
    call(home, "download", "hh-one", "file-one", "--output", str(out), "--json")
    assert out.read_bytes() == b"safe binary fixture"
    call(home, "download", "hh-one", "file-one", "--output", str(out), code=1)
    assert not (home / ".local/state/harbor-helper").exists()


def test_remote_failures_and_logout_never_become_local(api, home, monkeypatch):
    url, _, _ = api
    monkeypatch.setattr("harbor_helper.commands.remote.hidden_input", lambda _: PASSWORD)
    login(url, "alice")
    call(home, "submit", code=1)
    call(home, "service", "logout", "--json")
    assert (remote_root() / "selected.json").exists()
    assert "service login" in call(home, "submit", "--agent", "oracle", code=1).stderr
    assert not (home / ".local/state/harbor-helper").exists()
    login(url, "alice")
    # Port exists but no server accepts requests: stale profile must fail closed.
    from harbor_helper.security.files import secure_write

    secure_write(
        remote_root() / "profiles/default.json",
        {"url": "http://127.0.0.1:1", "token": TOKEN, "user": {"id": "member-1"}},
    )
    assert "no local fallback" in call(home, "list", code=1).stderr
    assert not (home / ".local/state/harbor-helper").exists()


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/key",
        "https://user:pass@host",
        "http://host?token=value",
        "http://host#frag",
        "http://host:99999",
        "http://host\n",
    ],
)
def test_invalid_url(url):
    with pytest.raises(RemoteError):
        service_url(url)


def test_profile_permission_and_local_state_guard(api, home, monkeypatch, tmp_path):
    monkeypatch.setattr("harbor_helper.commands.remote.hidden_input", lambda _: PASSWORD)
    login(api[0], "alice")
    (remote_root() / "profiles/default.json").chmod(0o644)
    call(home, "list", code=1)
    state = tmp_path / "service-state"
    state.mkdir()
    (state / "service.json").write_text("{}")
    for command in ("init", "auth", "submit"):
        args = (command, "status") if command == "auth" else (command,)
        assert (
            "authenticated API"
            in call(home, "--local", "--state", str(state), *args, code=1).stderr
        )
    assert not (state / "queue.sqlite").exists()


def test_invalid_member_token_never_saved(home, monkeypatch):
    monkeypatch.setattr("harbor_helper.commands.remote.hidden_input", lambda _: PASSWORD)
    monkeypatch.setattr(
        "harbor_helper.commands.remote.Client.request",
        lambda *args, **kwargs: {"token": "non-ascii-会话", "user": {"id": "member-1"}},
    )
    with pytest.raises(RemoteError, match="Invalid member session"):
        login("http://127.0.0.1:8000", "alice")
    assert not (remote_root() / "profiles/default.json").exists()
    assert not (remote_root() / "selected.json").exists()


def test_service_init_requires_confirmation_without_state(home, monkeypatch, tmp_path):
    values = iter([PASSWORD, "different"])
    monkeypatch.setattr("harbor_helper.commands.service.hidden_input", lambda _: next(values))
    root = tmp_path / "state"
    args = parser().parse_args(
        ["service", "init", "--root", str(root), "--master-key-file", str(tmp_path / "master")]
    )
    with pytest.raises(RemoteError, match="Passwords differ"):
        service_dispatch(args)
    assert not root.exists()


def test_service_serve_factory_host_port_no_native_auth(home, monkeypatch, tmp_path):
    from types import SimpleNamespace

    app = SimpleNamespace(state=SimpleNamespace(application=True))
    calls = []
    monkeypatch.setattr(
        "harbor_helper.service.api.create_app",
        lambda root, **kwargs: calls.append((root, kwargs)) or app,
    )
    monkeypatch.setattr("uvicorn.run", lambda value, **kwargs: calls.append((value, kwargs)))
    args = parser().parse_args(
        [
            "service",
            "serve",
            "--root",
            str(tmp_path / "service"),
            "--host",
            "0.0.0.0",
            "--port",
            "8123",
        ]
    )
    service_dispatch(args)
    assert calls[0] == (tmp_path / "service", {"setup_token_file": None, "master_key_file": None})
    assert calls[1] == (app, {"host": "0.0.0.0", "port": 8123, "access_log": False})


def test_service_init_real_tty_hidden_and_external_master(home, tmp_path):
    root, master_key = tmp_path / "service", tmp_path / "private/master"
    master, slave = pty.openpty()
    env = {**os.environ, "HOME": str(home)}
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "harbor_helper.commands.main",
            "service",
            "init",
            "--root",
            str(root),
            "--master-key-file",
            str(master_key),
            "--json",
        ],
        env=env,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
    )
    os.close(slave)
    output = b""
    sent = 0
    deadline = time.monotonic() + 15
    try:
        while process.poll() is None:
            assert time.monotonic() < deadline
            if select.select([master], [], [], 0.1)[0]:
                try:
                    output += os.read(master, 65536)
                except OSError:
                    break
            if sent == 0 and b"Initial admin password" in output:
                os.write(master, (PASSWORD + "\n").encode())
                sent += 1
            if sent == 1 and b"Confirm admin password" in output:
                os.write(master, (PASSWORD + "\n").encode())
                sent += 1
        process.wait(timeout=10)
        assert process.returncode == 0, output.decode()
        assert PASSWORD.encode() not in output
        assert master_key.stat().st_size == 32
        assert master_key.stat().st_mode & 0o777 == 0o600
        assert json.loads((root / "service.json").read_text())["master_file"] == str(master_key)
        assert not (root / "scheduler.json").exists()
    finally:
        os.close(master)
        if process.poll() is None:
            process.kill()
            process.wait()


def test_true_http_application_member_cli_persistent_preparation(api, home, tmp_path, monkeypatch):
    """Actual API/data/SQLite over TCP; scheduler disabled to prohibit Hub/worker work."""
    import uvicorn

    from harbor_helper.service.api import create_app
    from harbor_helper.service.data import ServiceData

    root = tmp_path / "http-service"
    data = ServiceData.initialize(root, tmp_path / "http-master", "admin", PASSWORD)
    from admission_fixture import synthetic_activity

    synthetic_activity(data)  # Synthetic activity only; this fixture never prepares inputs.
    data.create_user("alice", PASSWORD)
    app = create_app(root, start_scheduler=False)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    try:
        while not server.started:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        url = "http://127.0.0.1:" + str(sock.getsockname()[1])
        monkeypatch.setattr("harbor_helper.commands.remote.hidden_input", lambda _: PASSWORD)
        login(url, "alice")
        accepted = json.loads(
            call(
                home,
                "submit",
                "--agent",
                "oracle",
                "--idempotency-key",
                "actual-api-once",
                "--json",
            ).stdout
        )
        assert accepted["status"] == "preparing" and accepted["run_id"] is None
        (root / "scheduler.json").unlink()  # Remove synthetic activity; old-key/read/cancel remain available.
        assert json.loads(call(home, "service", "retry", "--json").stdout)["id"] == accepted["id"]
        listing = json.loads(call(home, "list", "--json").stdout)
        assert len(listing["submissions"]) == 1
        assert listing["submissions"][0]["submitter"] == "alice"
        cancelled = json.loads(call(home, "cancel", accepted["id"], "--json").stdout)
        assert cancelled["status"] == "cancelled"
        assert json.loads(call(home, "catalog", "--json").stdout)["default_dataset"]
        assert (
            json.loads(call(home, "service", "status", "--json").stdout)["user"]["username"]
            == "alice"
        )
        assert not data.store.runs()
        assert not (root / "scheduler.json").exists()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()


@pytest.mark.parametrize("body", [[], [TOKEN], None, TOKEN])
def test_remote_nonobject_error_is_safe_remote_error(monkeypatch, body):
    def request(*args, **kwargs):
        return httpx.Response(503, json=body)

    monkeypatch.setattr(httpx.Client, "request", request)
    with pytest.raises(RemoteError, match="HTTP 503 remote_error: Service request failed") as exc:
        Client("http://127.0.0.1:1", token=TOKEN).request("GET", "/machine/discovery")
    assert TOKEN not in str(exc.value)


@pytest.mark.parametrize("action", [None, [], {}, 42, True, "retry_same_request", TOKEN + "x" * 200])
def test_remote_error_action_type_length_and_redaction(monkeypatch, action):
    monkeypatch.setattr(
        httpx.Client, "request",
        lambda *args, **kwargs: httpx.Response(403, json={"action": action}),
    )
    with pytest.raises(RemoteError) as exc:
        Client("http://127.0.0.1:1", token=TOKEN).request("POST", "/submissions")
    detail = str(exc.value)
    assert TOKEN not in detail
    if isinstance(action, str):
        shown = detail.split("; action=", 1)[1]
        assert len(shown) <= 128
        if action == "retry_same_request":
            assert shown == action
        else:
            assert "[REDACTED]" in shown
    else:
        assert "; action=" not in detail
