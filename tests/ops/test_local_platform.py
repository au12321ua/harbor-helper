"""Real local HTTP child lifecycle, with no Harbor/model/Docker execution."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "local_platform", Path(__file__).resolve().parents[1] / "scripts/local_platform.py"
)
assert spec is not None and spec.loader is not None
platform = importlib.util.module_from_spec(spec)
spec.loader.exec_module(platform)


@pytest.fixture
def local_instance(tmp_path, monkeypatch):
    base = tmp_path / "instance"
    for name in ("releases", "state", "home", "private", "logs"):
        (base / name).mkdir(parents=True, exist_ok=True)
    code = base / "releases" / "fixture-commit"
    (code / ".venv/bin").mkdir(parents=True)
    (code / ".venv/bin/python").symlink_to(sys.executable)
    package = code / "harbor_helper"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "commands").mkdir()
    (package / "commands" / "__init__.py").write_text("")
    (package / "commands" / "main.py").write_text(
        "import sys\n"
        "from http.server import HTTPServer, BaseHTTPRequestHandler\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        self.send_response(200); self.end_headers(); self.wfile.write(b'{}')\n"
        "port = int(sys.argv[sys.argv.index('--port') + 1])\n"
        "HTTPServer(('127.0.0.1', port), Handler).serve_forever()\n"
    )
    monkeypatch.setattr(platform, "release", lambda *_: code)
    monkeypatch.setattr(platform.subprocess, "check_output", lambda *a, **kw: "fixture-commit\n")
    yield base
    record = platform.read_record(base)
    if record and platform.matches(record):
        platform.stop(base, record, platform.environment(base))


def test_start_waits_for_exec_identity_then_reuses_and_stops_child(local_instance, monkeypatch):
    """A transient /proc mismatch must not abort startup or terminate the child."""
    base = local_instance
    real_matches = platform.matches
    checks = 0

    def delayed_identity(record):
        nonlocal checks
        checks += 1
        return checks > 3 and real_matches(record)

    monkeypatch.setattr(platform, "matches", delayed_identity)
    platform.start(base, None, platform.environment(base), None)
    record = platform.read_record(base)
    assert checks >= 4 and real_matches(record) and platform.health(record)
    platform.start(base, record, platform.environment(base), None)
    assert platform.read_record(base)["pid"] == record["pid"]
    platform.stop(base, record, platform.environment(base))
    assert platform.birth(record["pid"]) is None


def test_stop_refuses_wrong_birth_without_signalling_child(local_instance):
    base = local_instance
    platform.start(base, None, platform.environment(base), None)
    record = platform.read_record(base)
    with pytest.raises(RuntimeError, match="identity mismatch"):
        platform.stop(base, {**record, "birth": "wrong-birth"}, platform.environment(base))
    assert platform.matches(record) and platform.health(record)


def test_existing_master_missing_is_not_regenerated(local_instance):
    base = local_instance
    (base / "state/service.json").write_text(
        json.dumps({"master_file": str(base / "private/master.key")})
    )
    with pytest.raises(RuntimeError, match="master reference"):
        platform.start(base, None, platform.environment(base), None)
    assert not (base / "private/master.key").exists()


@pytest.mark.parametrize(
    ("tty", "reveal", "initialized", "expect_value"),
    [
        (True, True, False, True),
        (False, True, False, False),
        (True, False, False, False),
        (True, True, True, False),
    ],
)
def test_bootstrap_value_only_on_uninitialized_interactive_start(
    local_instance, monkeypatch, tty, reveal, initialized, expect_value
):
    import io
    import secrets

    base = local_instance
    value = secrets.token_urlsafe(32)
    token_file = base / "private/setup-token"
    token_file.write_text(value)
    token_file.chmod(0o600)
    if initialized:
        (base / "state/service.json").write_text("{}")
    output = io.StringIO()
    monkeypatch.setattr(output, "isatty", lambda: tty)
    monkeypatch.setattr(platform.sys, "stdout", output)
    platform.setup_notice(base, reveal)
    captured = output.getvalue()
    has_value = value in captured
    # Assert only redacted output/booleans so a failed check cannot log the value.
    redacted = captured.replace(value, "[REDACTED]")
    assert has_value == expect_value
    if initialized:
        assert redacted == ""
    elif not expect_value:
        assert str(token_file) in redacted and "[REDACTED]" not in redacted
    else:
        assert "[REDACTED]" in redacted
