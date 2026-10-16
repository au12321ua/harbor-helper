"""Web bootstrap/catalog contracts, without external requests or production state."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from admission_fixture import synthetic_activity
from fastapi.testclient import TestClient

from harbor_helper.persistence.files import read_json
from harbor_helper.service.api import create_app
from harbor_helper.service.application import Application
from harbor_helper.service.data import ServiceData
from harbor_helper.service.primitives import ServiceError

WRITE = {"X-Requested-With": "harbor-helper"}
PASSWORD = "web-fixture-password-2026"
SOURCE = "team/data@sha256:" + "b" * 64


def test_protected_setup_concurrent_and_invalid_retry(tmp_path):
    root = tmp_path / "state"
    app = create_app(root, start_scheduler=False)
    client = TestClient(app)
    assert client.get("/").status_code == 200
    assert client.get("/api/v1/setup").json() == {"initialized": False}
    assert client.get("/api/v1/catalog").status_code == 503
    token_file = tmp_path / ".state-deployment/setup-token"
    token = token_file.read_text()
    request = {"username": "admin", "password": PASSWORD, "setup_token": "invalid"}
    assert client.post("/api/v1/setup", headers=WRITE, json=request).status_code == 403
    request["setup_token"] = token
    request["password"] = "short"
    assert client.post("/api/v1/setup", headers=WRITE, json=request).status_code == 422
    assert not (root / "service.json").exists()
    request["password"] = PASSWORD
    with ThreadPoolExecutor(2) as pool:
        responses = list(
            pool.map(lambda _: client.post("/api/v1/setup", headers=WRITE, json=request), range(2))
        )
    assert sorted(r.status_code for r in responses) == [201, 409]
    data = ServiceData(root)
    assert len(data.users()) == 1
    assert not Path(read_json(root / "service.json")["master_file"]).is_relative_to(root)
    assert token not in json.dumps([r.json() for r in responses])
    assert client.post("/api/v1/setup", headers=WRITE, json=request).status_code == 409
    assert (
        client.post(
            "/api/v1/setup", headers={**WRITE, "Origin": "https://evil.invalid"}, json=request
        ).status_code
        == 403
    )


@pytest.fixture
def web(tmp_path, monkeypatch):
    data = ServiceData.initialize(
        tmp_path / "state", tmp_path / "private/master", "admin", PASSWORD
    )
    data.create_user("member", PASSWORD)
    synthetic_activity(data)
    app = Application(data.root)
    client = TestClient(create_app(data.root, start_scheduler=False))
    client.post(
        "/api/v1/auth/login", headers=WRITE, json={"username": "admin", "password": PASSWORD}
    )
    monkeypatch.setattr(
        "harbor_helper.service.configuration.source_call",
        lambda *a, **kw: {
            "resolved": SOURCE,
            "tasks": [{"name": "answer", "package": "team/answer", "ref": "sha256:" + "c" * 64}],
        },
    )
    return data, app, client


def create_catalog(web):
    _data, _app, client = web
    dataset = client.post(
        "/api/v1/admin/catalog/dataset",
        headers=WRITE,
        json={"name": "Answer", "reference": "team/data@1"},
    ).json()
    dataset = client.post(
        f"/api/v1/admin/catalog/dataset/{dataset['id']}/verify", headers=WRITE
    ).json()
    assert dataset["status"] == "verified"
    return dataset


def test_catalog_snapshot_defaults_permissions_and_edit_invalidation(web):
    data, app, client = web
    dataset = create_catalog(web)
    assert (
        client.patch(
            "/api/v1/admin/settings", headers=WRITE, json={"default_dataset_id": dataset["id"]}
        ).status_code
        == 200
    )
    actor = data.users()[1]
    request = {"dataset_id": dataset["id"], "task": "answer", "agent": "oracle", "name": "Baseline"}
    submission = app.accept(actor, request, "stable-key")
    assert app.accept(actor, request, "stable-key")["id"] == submission["id"]
    frozen = data.submission(submission["id"])["frozen"]
    assert frozen["effective"]["dataset"] == SOURCE
    assert frozen["service"]["dataset_version"] == dataset["version"]
    with pytest.raises(ServiceError, match="Select a verified"):
        app.accept(actor, {**request, "task": "wrong"}, "wrong-task")
    cli_submission = app.accept(
        actor, {"dataset": "team/data@1", "task": "a*", "agent": "oracle"}, "cli-pattern"
    )
    assert data.submission(cli_submission["id"])["frozen"]["effective"]["task_filter"] == "a*"
    edited = client.post(
        "/api/v1/admin/catalog/dataset",
        headers=WRITE,
        json={"id": dataset["id"], "name": "Answer v2", "reference": "team/data@2"},
    ).json()
    assert edited["status"] == "unverified"
    assert (
        client.post(
            "/api/v1/admin/catalog/runtime",
            headers=WRITE,
            json={"name": "Retired", "image": "python:new"},
        ).status_code
        == 404
    )
    assert not app.catalog()["datasets"][0]["ready"]
    with pytest.raises(ServiceError):
        app.accept(actor, request, "new-key")
    assert data.submission(submission["id"])["frozen"] == frozen
    client.post(
        "/api/v1/auth/login", headers=WRITE, json={"username": "member", "password": PASSWORD}
    )
    assert client.get("/api/v1/catalog").status_code == 200
    assert (
        client.post(
            "/api/v1/admin/catalog/dataset",
            headers=WRITE,
            json={"name": "evil", "reference": "team/data@1"},
        ).status_code
        == 403
    )
    assert (
        client.post("/api/v1/admin/hub", headers=WRITE, json={"key": "fake-hub-key"}).status_code
        == 403
    )


def test_hub_secret_encryption_rotation_disable_and_safe_errors(web, monkeypatch):
    data, app, client = web
    key = "fake-hub-source-key-2026"
    result = client.post("/api/v1/admin/hub", headers=WRITE, json={"key": key})
    assert result.status_code == 200
    assert key not in result.text and key not in json.dumps(app.catalog())
    with data.store.connect() as db:
        assert (
            key.encode()
            not in db.execute("SELECT ciphertext FROM source_credentials").fetchone()[0]
        )
    assert app.configuration.hub_key(1) == key
    client.post("/api/v1/admin/hub", headers=WRITE, json={"key": "fake-rotated-hub-key"})
    assert app.configuration.hub_key(1) == key
    client.post("/api/v1/admin/hub/disable", headers=WRITE)
    with pytest.raises(ServiceError):
        app.configuration.hub_key(1)
    assert app.configuration.hub_key() is None
    dataset = create_catalog(web)

    def denied(*a, **kw):
        raise ServiceError("source_access", "检查团队 Hub 权限", 409)

    monkeypatch.setattr("harbor_helper.service.configuration.source_call", denied)
    blocked = app.configuration.verify("dataset", dataset["id"])
    assert blocked["status"] == "blocked" and blocked["error"]["code"] == "source_access"
    assert not app.catalog()["datasets"][0]["ready"]


def test_password_change_revokes_all_sessions(web):
    data, _app, client = web
    _, actor = data.login("admin", PASSWORD)
    second, _ = data.login("admin", PASSWORD)
    result = client.post(
        "/api/v1/auth/password",
        headers=WRITE,
        json={"current_password": PASSWORD, "password": "changed-web-password-2026"},
    )
    assert result.status_code == 200
    assert client.get("/api/v1/me").status_code == 401
    with pytest.raises(ServiceError):
        data.actor(second)
    assert data.login("admin", "changed-web-password-2026")[1]["id"] == actor["id"]


def test_verification_does_not_overwrite_concurrent_edits(web, monkeypatch):
    data, app, _client = web
    dataset = create_catalog(web)

    def concurrent(*a, **kw):
        with data.store.control():
            app.configuration.save(
                "dataset",
                {
                    "id": dataset["id"],
                    "name": "Changed",
                    "reference": "team/data@2",
                },
            )
        return {"resolved": SOURCE, "tasks": []}

    monkeypatch.setattr("harbor_helper.service.configuration.source_call", concurrent)
    with pytest.raises(ServiceError) as caught:
        app.configuration.verify("dataset", dataset["id"])
    assert caught.value.code == "configuration_changed"
    assert data.object("dataset", dataset["id"])["reference"] == "team/data@2"


def test_automatic_model_ids_binding_edit_and_no_key_echo(web):
    data, app, client = web
    provider = client.post(
        "/api/v1/admin/providers",
        headers=WRITE,
        json={
            "name": "Provider",
            "endpoint": "https://provider.invalid/v1",
            "protocol": "openai-compatible",
        },
    )
    assert provider.status_code == 200
    provider = provider.json()
    assert provider["id"]
    credential = client.post(
        "/api/v1/admin/credentials",
        headers=WRITE,
        json={"provider_id": provider["id"], "label": "Team key", "key": "fake-model-key-2026"},
    )
    assert credential.status_code == 201
    credential = credential.json()
    profile = client.post(
        "/api/v1/admin/model-profiles",
        headers=WRITE,
        json={
            "name": "Plan",
            "provider_id": provider["id"],
            "credential_id": credential["id"],
            "model": "test-model",
            "params": {"temperature": 0.5, "max_tokens": 100},
        },
    )
    assert profile.status_code == 200
    profile = profile.json()
    assert profile["id"] and profile["version"] == 1
    updated = client.post(
        "/api/v1/admin/model-profiles",
        headers=WRITE,
        json={**profile, "name": "Edited", "params": {"temperature": 0}},
    )
    assert updated.status_code == 200 and updated.json()["version"] == 2
    assert data.object("profile", profile["id"], 1)["params"]["temperature"] == 0.5
    assert "fake-model-key-2026" not in json.dumps(app.catalog())
    other = client.post(
        "/api/v1/admin/providers",
        headers=WRITE,
        json={
            "name": "Other",
            "endpoint": "https://other.invalid/v1",
            "protocol": "openai-compatible",
        },
    ).json()
    bad = client.post(
        "/api/v1/admin/model-profiles", headers=WRITE, json={**profile, "provider_id": other["id"]}
    )
    assert bad.status_code == 422 and bad.json()["code"] == "credential_binding"


def test_hub_persistent_metadata_and_legacy_migration(web):
    data, _app, client = web
    assert client.get("/api/v1/catalog").json()["hub"]["state"] == "unset"
    saved = client.post("/api/v1/admin/hub", headers=WRITE, json={"key": "fake-metadata-pat"})
    assert saved.status_code == 200
    assert saved.json()["state"] == "active" and saved.json()["version"] == 1
    assert saved.json()["updated_at"] > 0
    assert "fake-metadata-pat" not in saved.text
    assert Application(data.root).catalog()["hub"] == saved.json()
    rotated = client.post("/api/v1/admin/hub", headers=WRITE, json={"key": "fake-next-pat"}).json()
    assert rotated["version"] == 2 and rotated["updated_at"] >= saved.json()["updated_at"]
    disabled = client.post("/api/v1/admin/hub/disable", headers=WRITE).json()
    assert disabled["state"] == "disabled" and disabled["version"] == 2
    assert Application(data.root).catalog()["hub"] == disabled
    # Recreate only the old schema in this isolated fixture to verify an upgrade.
    with data.store.connect() as db:
        db.execute("ALTER TABLE source_credentials RENAME TO old_sources")
        db.execute(
            "CREATE TABLE source_credentials(version INTEGER PRIMARY KEY, enabled INTEGER NOT NULL, nonce BLOB NOT NULL, ciphertext BLOB NOT NULL)"
        )
        db.execute(
            "INSERT INTO source_credentials SELECT version,enabled,nonce,ciphertext FROM old_sources"
        )
        db.execute("DROP TABLE old_sources")
    upgraded = Application(data.root)
    assert upgraded.catalog()["hub"]["updated_at"] is None
    assert upgraded.catalog()["hub"]["state"] == "disabled"
    assert upgraded.configuration.hub_key() is None
    next_result = upgraded.configuration.save_hub("fake-upgraded-pat")
    assert next_result["version"] == 3 and next_result["updated_at"] > 0
    assert upgraded.configuration.hub_key() == "fake-upgraded-pat"


def test_docker_discovery_admin_only(web, monkeypatch):
    _data, _app, client = web
    calls = []
    monkeypatch.setattr(
        "harbor_helper.service.docker.discover_docker",
        lambda: (
            calls.append(True)
            or {
                "state": "ready",
                "images": [],
                "checked_at": 1.0,
                "truncated": False,
                "message": "Synthetic Docker discovery",
            }
        ),
    )
    assert client.get("/api/v1/admin/docker").json()["state"] == "ready"
    assert calls == [True]
    client.post(
        "/api/v1/auth/login", headers=WRITE, json={"username": "member", "password": PASSWORD}
    )
    assert client.get("/api/v1/admin/docker").status_code == 403
    assert calls == [True]
