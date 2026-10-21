"""Shared test factories; each call owns its mutable state."""

from fastapi.testclient import TestClient

from harbor_helper.persistence.files import tree_digest
from harbor_helper.service.api import create_app
from harbor_helper.service.application import Application
from harbor_helper.service.data import ServiceData
from harbor_helper.service.lifecycle import prepare_one
from support.admission_fixture import synthetic_activity

WRITE = {"X-Requested-With": "harbor-helper"}

PASSWORD = "Fake-test-password-2026"

KEYS = ["fake-service-key-one-2026", "fake-service-key-two-2026", "fake-service-key-three-2026"]


def initialize_accounts(tmp_path, password, users=()):
    """Create a fresh service with an external master and explicit synthetic identities."""
    data = ServiceData.initialize(
        tmp_path / "state", tmp_path / "private" / "master", "admin", password
    )
    for username in users:
        data.create_user(username, password)
    return data


def make_data(tmp_path):
    data = initialize_accounts(tmp_path, PASSWORD, ("alice", "bob"))
    for i in (1, 2):
        data.models.save_object(
            "provider",
            {
                "id": f"p{i}",
                "name": f"Provider {i}",
                "protocol": "openai-compatible",
                "endpoint": f"http://provider{i}.invalid/v1",
            },
        )
    for i, key in enumerate(KEYS, 1):
        provider = "p1" if i < 3 else "p2"
        data.add_credential(f"k{i}", provider, f"Key {i}", key)
        data.models.save_object(
            "profile",
            {
                "id": f"m{i}",
                "name": f"Model {i}",
                "provider_id": provider,
                "credential_id": f"k{i}",
                "model": "test-model",
                "params": {"temperature": 0},
            },
        )
    configure_default_dataset(data)
    synthetic_activity(data)
    return data


def configure_default_dataset(data):
    # Tests using an implicit source choose an explicit, checked synthetic default.
    from harbor_helper.service.configuration import TeamConfiguration

    configuration = TeamConfiguration(data)
    default = configuration.persist(
        "dataset",
        {
            "id": "fixture-default",
            "name": "Fixture default",
            "reference": "test/default@1",
            "enabled": True,
            "status": "verified",
            "resolved": "test/default@sha256:" + "a" * 64,
            "tasks": [{"name": "box", "package": "test/box", "ref": "sha256:fixed"}],
        },
    )
    configuration.persist(
        "author_parameters",
        {"id": default["id"], "source": default["resolved"], "values": {}, "status": "checked"},
    )
    configuration.save_settings({"default_dataset_id": default["id"]})


def client(data, username="alice"):
    c = TestClient(create_app(data.root, start_scheduler=False), raise_server_exceptions=False)
    r = c.post(
        "/api/v1/auth/login", headers=WRITE, json={"username": username, "password": PASSWORD}
    )
    assert r.status_code == 200
    return c


def patch_preparation(monkeypatch):
    async def source(dataset, target, task):
        folder = target / "box"
        folder.mkdir(parents=True)
        (folder / "task.toml").write_text('version = "1.0"\n[environment]\nbuild_timeout_sec=60\n')
        (folder / "instruction.md").write_text("fake oracle task")
        return {
            "requested": dataset,
            "resolved": dataset,
            "tasks": [
                {
                    "package": "test/box",
                    "directory": "box",
                    "ref": "sha256:fixed",
                    "snapshot_digest": tree_digest(folder),
                }
            ],
        }

    monkeypatch.setattr(
        "harbor_helper.service.sources.source_call",
        lambda reference, *, key=None, target=None, task=None: __import__("asyncio").run(
            source(reference, target, task)
        ),
    )
    monkeypatch.setattr("harbor_helper.execution.runs.subprocess.run", lambda *a, **k: None)


def accept_model(data, username="alice", profile="m1", key="same"):
    app = Application(data.root)
    actor = next(u for u in data.users() if u["username"] == username)
    return app.accept(actor, {"model_profile": profile, "dataset": "test/dataset@1"}, key)


def prepare(data, preparation, profile="m1"):
    accepted = accept_model(data, profile=profile)
    prepare_one(data.store)
    row = data.submission(accepted["id"])
    assert row["status"] == "ready", row
    return row["run_id"]
