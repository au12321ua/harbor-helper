import asyncio
import json
import shutil
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from harbor_helper.persistence.files import tree_digest
from harbor_helper.service.api import create_app
from harbor_helper.service.application import Application
from harbor_helper.service.data import ServiceData, ServiceError
from harbor_helper.service.lifecycle import prepare_one

SOURCE = "test/scoped@sha256:" + "a" * 64
PASSWORD = "scope-fixture-password"
WRITE = {"X-Requested-With": "harbor-helper"}


@pytest.fixture
def scoped(tmp_path, monkeypatch):
    catalog = []
    for name in ("alpha", "beta", "plain"):
        root = tmp_path / "authors" / name
        root.mkdir(parents=True)
        (root / "task.toml").write_text("[agent]\ntimeout_sec=1800\n[verifier]\ntimeout_sec=1800\n")
        if name != "plain":
            (root / "environment").mkdir()
            (root / "environment/compose.yaml").write_text(
                "services:\n  main:\n    image: ${BUILD_" + name.upper() + "_IMAGE:?required}\n"
            )
        catalog.append({"name": name, "package": "test/" + name, "ref": "sha256:" + name[0] * 64})
    calls = []

    def source(reference, *, target=None, selected_tasks=None, task=None, **_kwargs):
        if target is None:
            return {"resolved": SOURCE, "tasks": catalog}
        tasks = selected_tasks if selected_tasks is not None else catalog
        if task:
            tasks = [t for t in tasks if t["name"] == task]
        calls.append([t["name"] for t in tasks])
        target.mkdir()
        identities = []
        for t in tasks:
            shutil.copytree(tmp_path / "authors" / t["name"], target / t["name"])
            identities.append(
                {
                    "directory": t["name"],
                    "package": t["package"],
                    "ref": t["ref"],
                    "snapshot_digest": tree_digest(target / t["name"]),
                }
            )
        return {"requested": reference, "resolved": SOURCE, "tasks": identities}

    monkeypatch.setattr("harbor_helper.service.configuration.source_call", source)
    monkeypatch.setattr("harbor_helper.service.sources.source_call", source)
    monkeypatch.setattr(
        "harbor_helper.execution.author_inputs.compose_variables",
        lambda file: [("BUILD_" + file.parent.parent.name.upper() + "_IMAGE", True, "")],
    )
    data = ServiceData.initialize(
        tmp_path / "state", tmp_path / "private/master", "admin", PASSWORD
    )
    app = Application(data.root)
    dataset = app.configuration.save(
        "dataset", {"id": "scope", "name": "Scoped", "reference": "test/scoped@1"}
    )
    dataset = app.configuration.verify("dataset", dataset["id"])
    return data, app, dataset, calls


def test_partial_full_cache_and_union_save_preserve_catalog(scoped):
    data, app, dataset, calls = scoped
    c = app.configuration
    first = c.inspect_author_parameters("scope", ["alpha"])
    assert first["status"] == "partial_missing" and first["scope"]["unknown"] == 2
    assert calls == [["alpha"]]
    saved = c.save_author_parameters("scope", {"BUILD_ALPHA_IMAGE": "base:a"})
    assert saved["status"] == "partial_checked"
    with pytest.raises(ServiceError):
        c.save_author_parameters("scope", {"BUILD_BETA_IMAGE": "unscanned"})
    second = c.inspect_author_parameters("scope", ["beta"])
    assert second["values"] == saved["values"] and second["scope"]["unknown"] == 1
    assert set(second["discovery"]["variables"]) == {"BUILD_ALPHA_IMAGE", "BUILD_BETA_IMAGE"}
    c.save_author_parameters("scope", {"BUILD_ALPHA_IMAGE": "base:a", "BUILD_BETA_IMAGE": "base:b"})
    full = c.inspect_author_parameters("scope")
    assert calls[-1] == ["alpha", "beta", "plain"]
    assert full["scope"]["complete"] and full["status"] == "checked"
    partial = c.inspect_author_parameters("scope", ["plain"])
    assert partial["discovery"] == full["discovery"] and partial["scope"]["complete"]
    assert partial["last_check_scope"]["mode"] == "selected"
    c.inspect_author_parameters("scope")
    assert len(calls) == 4  # full cache is reused only after a genuine full download
    assert data.object("dataset", "scope") == dataset
    caches = [
        json.loads((p / "scope.json").read_text())["mode"]
        for p in (data.root / "author-inputs").iterdir()
    ]
    assert caches.count("all") == 1 and caches.count("selected") == 3


@pytest.mark.parametrize(
    "names", [[], ["*"], ["alpha*"], ["unknown"], ["alpha", "alpha"], ["alpha"] * 51, None]
)
def test_explicit_invalid_selection_and_admin_permissions(scoped, names):
    data, _app, _dataset, calls = scoped
    client = TestClient(create_app(data.root, start_scheduler=False))
    client.post(
        "/api/v1/auth/login", headers=WRITE, json={"username": "admin", "password": PASSWORD}
    )
    url = "/api/v1/admin/datasets/scope/author-inputs/check"
    result = client.post(url, headers=WRITE, json={"task_names": names})
    assert result.status_code == 422 and result.json()["code"] == "author_task_selection"
    assert not calls
    data.create_user("member", PASSWORD)
    client.post(
        "/api/v1/auth/login", headers=WRITE, json={"username": "member", "password": PASSWORD}
    )
    assert client.post(url, headers=WRITE, json={"task_names": ["plain"]}).status_code == 403


def test_partial_preflight_does_not_skip_unscanned_requested_tasks(scoped):
    data, app, _dataset, _calls = scoped
    app.configuration.inspect_author_parameters("scope", ["alpha"])
    app.configuration.save_author_parameters("scope", {"BUILD_ALPHA_IMAGE": "base:a"})
    accepted = app.accept(data.users()[0], {"agent": "oracle", "dataset_id": "scope"}, "whole")
    prepare_one(data.store)
    failure = data.submission(accepted["id"])
    assert failure["status"] == "failed" and failure["run_id"] is None
    assert "BUILD_BETA_IMAGE" in failure["error"]
    one = app.accept(
        data.users()[0], {"agent": "oracle", "dataset_id": "scope", "task": "alpha"}, "one"
    )
    prepare_one(data.store)
    run_id = data.submission(one["id"])["run_id"]
    assert json.loads((data.store.path(run_id) / "job.json").read_text())["environment"]["env"] == {
        "BUILD_ALPHA_IMAGE": "base:a"
    }


def test_exact_source_selection_and_content_hash(monkeypatch, tmp_path):
    from harbor_helper.execution.sources import TaskSelectionError, resolve_dataset

    async def verify():
        task = SimpleNamespace(
            name="literal*name", ref="sha256:" + "b" * 64, get_name=lambda: "test/literal*name"
        )
        metadata = SimpleNamespace(
            version="sha256:" + "a" * 64,
            name="test/scoped",
            metrics=None,
            files=None,
            task_ids=[task],
        )
        downloaded = []

        async def get_metadata(_self, _reference):
            return metadata

        async def download(_self, tasks, *, output_dir, **_kwargs):
            downloaded.extend(tasks)
            root = output_dir / task.name
            root.mkdir()
            (root / "task.toml").write_text("[agent]\ntimeout_sec=7")
            return SimpleNamespace(
                results=[SimpleNamespace(content_hash=task.ref.removeprefix("sha256:"))]
            )

        monkeypatch.setattr(
            "harbor_helper.execution.sources.PackageDatasetClient.get_dataset_metadata",
            get_metadata,
        )
        monkeypatch.setattr("harbor_helper.execution.sources.TaskClient.download_tasks", download)
        entry = {"name": task.name, "package": task.get_name(), "ref": task.ref}
        result = await resolve_dataset(SOURCE, tmp_path / "exact", selected_tasks=[entry])
        assert result["tasks"][0]["directory"] == task.name and downloaded == [task]
        with pytest.raises(TaskSelectionError):
            await resolve_dataset(
                SOURCE, tmp_path / "wrong", selected_tasks=[{**entry, "name": "literal*"}]
            )
        with pytest.raises(TaskSelectionError):
            await resolve_dataset(
                SOURCE, tmp_path / "ref", selected_tasks=[{**entry, "ref": "sha256:" + "c" * 64}]
            )

        async def mismatch(*_args, **_kwargs):
            return SimpleNamespace(results=[SimpleNamespace(content_hash="wrong")])

        monkeypatch.setattr("harbor_helper.execution.sources.TaskClient.download_tasks", mismatch)
        with pytest.raises(ValueError, match="hash differs"):
            await resolve_dataset(SOURCE, tmp_path / "hash", selected_tasks=[entry])

    asyncio.run(verify())


def test_legacy_full_discovery_survives_partial_refresh(scoped):
    _data, app, _dataset, _calls = scoped
    c = app.configuration
    full = c.inspect_author_parameters("scope")
    legacy = {
        k: v for k, v in full.items() if k not in {"scope", "checked_tasks", "last_check_scope"}
    }
    c.persist("author_parameters", legacy)
    refreshed = c.inspect_author_parameters("scope", ["plain"])
    assert refreshed["scope"]["complete"]
    assert refreshed["discovery"] == full["discovery"]
    saved = c.save_author_parameters(
        "scope", {"BUILD_ALPHA_IMAGE": "base:a", "BUILD_BETA_IMAGE": "base:b"}
    )
    assert saved["status"] == "checked"
