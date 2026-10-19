"""Upgrade trust boundaries, persistent ownership, and real git metadata relationships."""

import importlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbor_helper.persistence.store import Store
from harbor_helper.persistence.upgrades import blocked, durable, enqueue, projection
from harbor_helper.service.api import create_app
from harbor_helper.service.data import ServiceData

WRITE = {"X-Requested-With": "harbor-helper"}
PASSWORD = "Synthetic-web-update-password"


@pytest.fixture
def instance(tmp_path):
    base = tmp_path / "installation"
    base.mkdir(mode=0o700)
    data = ServiceData.initialize(base / "state", base / "private/master", "admin", PASSWORD)
    data.create_user("member", PASSWORD)
    for name in ("updates", "updates/spool", "updates/results"):
        (base / name).mkdir(mode=0o700)
    durable(base / "updates/enabled.json", {"owner": "synthetic-owner", "protocol": 1})
    yield base, data
    data.store.close()


def login(base, username="admin"):
    client = TestClient(create_app(base / "state"), raise_server_exceptions=False)
    response = client.post(
        "/api/v1/auth/login", headers=WRITE, json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return client


def test_roles_origin_spool_and_idempotency(instance):
    base, data = instance
    admin, member = login(base), login(base, "member")
    body = {"action": "check", "request_id": "synthetic-request-0001", "payload": {}}
    assert member.post("/api/v1/admin/updates", json=body, headers=WRITE).status_code == 403
    assert (
        admin.post(
            "/api/v1/admin/updates",
            json=body,
            headers={**WRITE, "Origin": "https://foreign.invalid"},
        ).status_code
        == 403
    )
    one = admin.post("/api/v1/admin/updates", json=body, headers=WRITE)
    assert one.status_code == 200, one.text
    two = admin.post("/api/v1/admin/updates", json=body, headers=WRITE)
    assert one.json() == two.json()
    assert len(list((base / "updates/spool").glob("*.json"))) == 1
    assert (
        admin.post(
            "/api/v1/admin/updates",
            json={**body, "payload": {"repository": "/arbitrary"}},
            headers=WRITE,
        ).status_code
        == 422
    )
    assert member.get("/api/v1/version").status_code == 200
    assert set(TestClient(create_app(base / "state")).get("/api/v1/build").json()) == {"build"}
    data.store.close()


def test_barrier_before_construction_auth_and_missing_state(instance, monkeypatch):
    base, data = instance
    live = login(base)
    admin_token = live.cookies.get("hh_session")
    data.store.close()
    before = (base / "state/queue.sqlite").read_bytes()
    durable(
        base / "updates/journal.json",
        {"protocol": 1, "id": "owned-job", "phase": "backup", "barrier": True},
    )
    durable(base / "state/.upgrade.json", {"protocol": 1, "job": "owned-job"})

    def forbidden(*args, **kwargs):
        raise AssertionError("Store must not be constructed")

    monkeypatch.setattr("harbor_helper.service.api.Store", forbidden)

    # isinstance requires a class; use a class that always fails to construct.
    class Forbidden:
        def __init__(self, *args, **kwargs):
            forbidden()

    monkeypatch.setattr("harbor_helper.service.api.Store", Forbidden)
    client = TestClient(create_app(base / "state"))
    for method, path in [
        ("get", "/api/v1/me"),
        ("get", "/api/v1/admin/updates"),
        ("post", "/api/v1/auth/login"),
        ("get", "/api/v1/machine/discovery"),
    ]:
        response = getattr(client, method)(
            path, headers={**WRITE, "Authorization": "Bearer synthetic-pat"}
        )
        assert response.status_code == 503
        assert response.json()["code"] == "upgrade_in_progress"
    assert client.get("/api/v1/health").json() == {"alive": True, "ready": False}
    assert client.get("/api/v1/upgrade-phase").json() == {"upgrading": True, "phase": "backup"}
    assert (base / "state/queue.sqlite").read_bytes() == before
    assert (
        live.get("/api/v1/me", headers={"Cookie": "hh_session=" + (admin_token or "")}).status_code
        == 503
    )
    (base / "state").rename(base / "state-failed")
    assert create_app(base / "state").state.application is None
    with pytest.raises(ValueError, match="upgrade_in_progress"):
        Store(base / "state")
    assert not (base / "state").exists()


def test_nonterminal_maintenance_ownership_without_process(instance):
    base, _data = instance
    client = login(base)
    durable(
        base / "updates/journal.json",
        {"protocol": 1, "id": "owned-job", "phase": "waiting", "barrier": False},
    )
    assert not blocked(base / "state")
    for path, method, body in [
        ("/admin/maintenance", "patch", {"paused": False}),
        ("/admin/shutdown", "post", {"mode": "abort"}),
    ]:
        response = getattr(client, method)("/api/v1" + path, json=body, headers=WRITE)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "upgrade_in_progress"


def test_corrupt_external_journal_fails_closed(tmp_path):
    (tmp_path / "updates").mkdir(mode=0o700)
    (tmp_path / "updates/journal.json").write_text("broken")
    assert blocked(tmp_path / "state")
    assert projection(tmp_path / "state")["phase"] == "needs_manual"
    assert not (tmp_path / "state").exists()


def test_request_conflict_and_result_idempotency(instance):
    base, _data = instance
    result = enqueue(base / "state", "check", "actor", "synthetic-request-0001", {})
    path = base / "updates/spool" / (result["request_id"] + ".json")
    value = json.loads(path.read_text())
    durable(base / "updates/results" / path.name, {"request": value, "result": {}})
    path.unlink()
    assert enqueue(base / "state", "check", "actor", "synthetic-request-0001", {}) == result
    assert not path.exists()
    with pytest.raises(ValueError, match="different request"):
        enqueue(base / "state", "cancel", "actor", "synthetic-request-0001", {"job": "other"})


def test_git_relations_and_metadata_drift(tmp_path, monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    manager = importlib.import_module("update_manager")
    base = tmp_path / "instance"
    for name in ("home", "private", "updates"):
        (base / name).mkdir(mode=0o700, parents=True, exist_ok=True)
    source = tmp_path / "source"
    env = {
        "PATH": os.defpath,
        "HOME": str(base / "home"),
        "GIT_AUTHOR_NAME": "Synthetic",
        "GIT_AUTHOR_EMAIL": "synthetic@example.invalid",
        "GIT_COMMITTER_NAME": "Synthetic",
        "GIT_COMMITTER_EMAIL": "synthetic@example.invalid",
    }

    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(source), *args], env=env, text=True
        ).strip()

    source.mkdir()
    git("init", "-b", "dev")
    contract = {
        "format": 1,
        "manager_protocol": 1,
        "journal_protocol": 1,
        "barrier": True,
        "probe_protocol": 1,
        "python": ">=3.12,<3.14",
    }
    (source / "update-contract.json").write_text(json.dumps(contract))
    git("add", ".")
    git("commit", "-m", "A")
    first = git("rev-parse", "HEAD")
    (source / "change").write_text("B")
    git("add", ".")
    git("commit", "-m", "B")
    second = git("rev-parse", "HEAD")
    (base / "private/update.toml").write_text(
        "[updates]\nrepository = " + json.dumps(str(source)) + '\nbranch = "dev"\n'
    )
    (base / "private/update.toml").chmod(0o600)
    _config, _digest, clean, tip = manager.fetch(base)
    assert tip == second
    assert manager.relation(base, clean, first, second) == "update"
    assert manager.relation(base, clean, second, first) == "behind"
    assert manager.relation(base, clean, first, first) == "current"
    assert manager.relation(base, clean, "f" * 40, first) == "unknown"
    assert manager.check(base, {"release": first}, "check")["metadata"] == "passed"
    git("checkout", "--orphan", "unrelated")
    git("commit", "-m", "Unrelated")
    unrelated = git("rev-parse", "HEAD")
    git("branch", "-f", "dev", unrelated)
    manager.fetch(base)
    assert manager.relation(base, clean, first, unrelated) == "diverged"
    assert not manager.ancestor(base, clean, second, unrelated)
    assert "OPENAI_API_KEY" not in clean and clean["HOME"] == str(base / "home")
