"""execution recovery behavior with isolated synthetic inputs."""

import shutil

import pytest
from fastapi.testclient import TestClient
from harbor.models.job.config import JobConfig
from support.paths import FIXTURES
from support.recovery_support import PASSWORD, SOURCE, WRITE, configured

from harbor_helper.persistence.files import read_json, tree_digest, write_json
from harbor_helper.results.reports import compare
from harbor_helper.service.api import create_app
from harbor_helper.service.application import Application
from harbor_helper.service.lifecycle import prepare_one
from harbor_helper.service.primitives import ServiceError


def test_missing_verifier_persistent_no_run_and_recovery_keeps_digest(recovery):
    data, app, actor, dataset, _task = recovery
    app.configuration.inspect_author_parameters(dataset["id"])
    app.configuration.save_author_parameters(dataset["id"], {"BUILD_AGENT_IMAGE": "author/agent:1"})
    first = app.accept(actor, {"agent": "oracle", "dataset_id": dataset["id"]}, "first")
    prepare_one(data.store)
    row = data.submission(first["id"])
    assert row["status"] == "failed" and row["run_id"] is None
    assert "author_input_missing" in row["error"] and "BUILD_VERIFIER_IMAGE" in row["error"]
    assert "runtime_missing" not in row["error"]
    assert row["frozen"]["effective"]["dataset"] == SOURCE
    assert not (data.root / "runs" / row["target_id"]).exists()
    configured(recovery)
    # Changing current source must not change the failed submission recovery's source.
    app.configuration.persist("dataset", {**dataset, "resolved": "test/other@sha256:" + "d" * 64})
    result = app.recover_submission(actor, first["id"], "recover")
    again = app.recover_submission(actor, first["id"], "recover")
    assert result["id"] == again["id"] and result["id"] != first["id"]
    prepare_one(data.store)
    run_id = data.submission(result["id"])["run_id"]
    assert read_json(data.store.path(run_id) / "manifest.json")["source"]["resolved"] == SOURCE
    assert data.submission(first["id"])["status"] == "failed"


def test_parameter_versions_do_not_reset_source_and_queue_freezes_native_job(recovery):
    data, app, actor, dataset, _task = recovery
    parameters = configured(recovery)
    before = data.object("dataset", dataset["id"])
    first = app.accept(actor, {"agent": "oracle", "dataset_id": dataset["id"]}, "first")
    changed = app.configuration.save_author_parameters(
        dataset["id"],
        {
            "BUILD_AGENT_IMAGE": "author/agent:changed",
            "BUILD_VERIFIER_IMAGE": "author/verifier:changed",
        },
    )
    assert changed["version"] > parameters["version"]
    assert data.object("dataset", dataset["id"]) == before
    assert Application(data.root).accept(actor, first["request"], "first")["id"] == first["id"]
    prepare_one(data.store)
    path = data.store.path(data.submission(first["id"])["run_id"])
    manifest, job = read_json(path / "manifest.json"), read_json(path / "job.json")
    assert manifest["effective"]["author_env"] == parameters["values"]
    assert manifest["service"]["author_parameters_version"] == parameters["version"]
    assert JobConfig.model_validate(job).environment.env == parameters["values"]


def test_repair_retry_preserves_explicit_parent_factors_and_separates_idempotency(recovery):
    data, app, actor, dataset, _task = recovery
    configured(recovery)
    first = app.accept(
        actor,
        {
            "agent": "oracle",
            "dataset_id": dataset["id"],
            "wall_seconds": 600,
            "environment_build_timeout_multiplier": 2,
        },
        "parent",
    )
    prepare_one(data.store)
    parent = data.submission(first["id"])["run_id"]
    path = data.store.path(parent)
    old = read_json(path / "manifest.json")
    old["effective"].pop("author_env")
    old["service"].pop("author_input_check")
    write_json(path / "manifest.json", old)
    before = (path / "manifest.json").read_bytes()
    exact = app.accept(actor, {}, "same", parent)
    repair = app.accept(actor, {}, "same", parent, retry=True)
    assert exact["id"] != repair["id"]
    exact_cfg = data.submission(exact["id"])["frozen"]["effective"]
    retry_cfg = data.submission(repair["id"])["frozen"]["effective"]
    assert "author_env" not in exact_cfg
    assert (
        retry_cfg["wall_seconds"] == 600 and retry_cfg["environment_build_timeout_multiplier"] == 2
    )
    for key in (
        "dataset",
        "model",
        "attempts",
        "concurrency",
        "task_filter",
        "max_cpus_per_trial",
        "max_memory_mb_per_trial",
    ):
        assert retry_cfg[key] == old["effective"][key]
    assert set(repair["retry_changes"]) == {"author_env"}
    explicit = app.accept(actor, {"wall_seconds": 1800}, "explicit", parent, retry=True)
    assert explicit["retry_changes"]["wall_seconds"] == {"old": 600, "new": 1800}
    prepare_one(data.store)
    prepare_one(data.store)
    prepare_one(data.store)
    assert (path / "manifest.json").read_bytes() == before
    assert (
        read_json(data.store.path(data.submission(repair["id"])["run_id"]) / "manifest.json")[
            "source"
        ]
        == old["source"]
    )


def test_retry_missing_multiplier_only_gets_default(recovery):
    data, app, actor, dataset, _task = recovery
    configured(recovery)
    accepted = app.accept(actor, {"agent": "oracle", "dataset_id": dataset["id"]}, "parent")
    prepare_one(data.store)
    parent = data.submission(accepted["id"])["run_id"]
    path = data.store.path(parent)
    manifest = read_json(path / "manifest.json")
    manifest["effective"].pop("environment_build_timeout_multiplier")
    write_json(path / "manifest.json", manifest)
    result = app.accept(actor, {}, "retry", parent, retry=True)
    assert result["retry_changes"]["environment_build_timeout_multiplier"] == {
        "old": None,
        "new": 10,
    }
    with pytest.raises(ServiceError, match="仅允许"):
        app.accept(actor, {"attempts": 2}, "unsupported", parent, retry=True)


def test_http_admin_whitelist_permissions_and_members_recovery(recovery):
    data, _app, _actor, dataset, _task = recovery
    client = TestClient(create_app(data.root, start_scheduler=False))
    client.post(
        "/api/v1/auth/login", headers=WRITE, json={"username": "admin", "password": PASSWORD}
    )
    base = f"/api/v1/admin/datasets/{dataset['id']}/author-inputs"
    response = client.post(base + "/check", headers=WRITE)
    assert response.status_code == 200 and response.json()["status"] == "missing"
    for name in ("UNSEEN_IMAGE", "PATH", "MAIN_IMAGE_NAME", "OPENAI_API_KEY"):
        result = client.put(base, headers=WRITE, json={"values": {name: "forbidden"}})
        assert result.status_code == 422
    assert (
        client.put(
            base,
            headers=WRITE,
            json={"values": {"BUILD_AGENT_IMAGE": "https://u:p@example.invalid"}},
        ).status_code
        == 422
    )
    data.create_user("member", PASSWORD)
    client.post(
        "/api/v1/auth/login", headers=WRITE, json={"username": "member", "password": PASSWORD}
    )
    assert client.post(base + "/check", headers=WRITE).status_code == 403


def test_compare_author_env_missing_normalizes_to_empty(recovery):
    data, app, actor, dataset, _task = recovery
    configured(recovery)
    ids = []
    for index in range(2):
        result = app.accept(actor, {"agent": "oracle", "dataset_id": dataset["id"]}, str(index))
        prepare_one(data.store)
        ids.append(data.submission(result["id"])["run_id"])
    reports = ({"complete": True, "tasks": []},) * 2
    for run_id in ids:
        data.store.update(run_id, status="succeeded")
        path = data.store.path(run_id) / "manifest.json"
        manifest = read_json(path)
        manifest["effective"].pop("author_env")
        write_json(path, manifest)
    assert (
        "author_env" not in compare(data.store, *ids, published_reports=reports)["config_changes"]
    )
    path = data.store.path(ids[1]) / "manifest.json"
    manifest = read_json(path)
    manifest["effective"]["author_env"] = {"BUILD_AGENT_IMAGE": "changed"}
    write_json(path, manifest)
    assert compare(data.store, *ids, published_reports=reports)["config_changes"]["author_env"] == {
        "left": {},
        "right": {"BUILD_AGENT_IMAGE": "changed"},
    }


def test_retry_model_only_fills_missing_strategy_preserves_research_and_identity(recovery):
    data, app, actor, dataset, _task = recovery
    configured(recovery)
    data.models.save_object(
        "provider",
        {
            "id": "provider",
            "name": "Fixture",
            "protocol": "openai-compatible",
            "endpoint": "http://provider.invalid/v1",
        },
    )
    data.add_credential("fixture-key", "provider", "Fixture", "fake-only-nonproduction-credential")
    data.models.save_object(
        "profile",
        {
            "id": "model",
            "name": "Fixture",
            "provider_id": "provider",
            "credential_id": "fixture-key",
            "model": "fixture",
            "params": {"temperature": 0},
        },
    )
    first = app.accept(
        actor, {"dataset_id": dataset["id"], "model_profile": "model"}, "model-parent"
    )
    prepare_one(data.store)
    parent = data.submission(first["id"])["run_id"]
    path = data.store.path(parent) / "manifest.json"
    old = read_json(path)
    old["effective"].pop("agent_tool_preparation")
    old["effective"].pop("environment_build_timeout_multiplier")
    write_json(path, old)
    member = data.create_user("member", PASSWORD)
    result = app.accept(member, {}, "repair", parent, retry=True)
    frozen = data.submission(result["id"])["frozen"]
    assert frozen["effective"]["agent_tool_preparation"] == "offline-npm-binary-v1"
    assert frozen["effective"]["model"] == old["effective"]["model"]
    assert frozen["service"]["user_id"] == member["id"]
    assert frozen["effective"]["environment_build_timeout_multiplier"] == 10
    old["effective"]["agent_tool_preparation"] = "in-task-npm"
    old["effective"]["environment_build_timeout_multiplier"] = 1
    write_json(path, old)
    explicit = app.accept(member, {}, "explicit", parent, retry=True)
    assert (
        data.submission(explicit["id"])["frozen"]["effective"]["agent_tool_preparation"]
        == "in-task-npm"
    )
    assert (
        data.submission(explicit["id"])["frozen"]["effective"][
            "environment_build_timeout_multiplier"
        ]
        == 1
    )


def test_discovery_failure_retains_resolved_source_without_run(recovery, monkeypatch):
    data, app, actor, dataset, _task = recovery
    from harbor_helper.execution.author_inputs import AuthorDiscoveryError

    def unavailable(*_args):
        raise AuthorDiscoveryError(
            [{"task": "test/answer", "variables": [], "reason": "compose_discovery_failed"}]
        )

    monkeypatch.setattr("harbor_helper.execution.author_inputs.discover", unavailable)
    accepted = app.accept(
        actor, {"dataset_id": dataset["id"], "agent": "oracle"}, "blocked-discovery"
    )
    prepare_one(data.store)
    failed = data.submission(accepted["id"])
    assert failed["status"] == "failed" and failed["run_id"] is None
    assert failed["frozen"]["effective"]["dataset"] == SOURCE
    assert failed["frozen"]["service"]["input_source"]["resolved"] == SOURCE
    assert (
        failed["frozen"]["service"]["author_input_issues"][0]["reason"]
        == "compose_discovery_failed"
    )


@pytest.mark.parametrize("has_policy", [True, False])
@pytest.mark.parametrize("snapshot_state", ["valid", "missing", "invalid", "tampered"])
def test_legacy_parent_detail_budgets_are_read_only(recovery, snapshot_state, has_policy):

    data, app, actor, dataset, _task = recovery
    configured(recovery)
    accepted = app.accept(actor, {"agent": "oracle", "dataset_id": dataset["id"]}, "legacy")
    prepare_one(data.store)
    run_id = data.submission(accepted["id"])["run_id"]
    root = data.store.path(run_id)
    fixture = FIXTURES / "execution_recovery"
    tasks = root / "tasks"
    shutil.rmtree(tasks)
    task_root = tasks / "generation--cylinder"
    task_root.mkdir(parents=True)
    (task_root / "task.toml").write_bytes((fixture / "cad-task.toml").read_bytes())
    if snapshot_state == "invalid":
        (task_root / "task.toml").write_text("not valid TOML")
    manifest = read_json(root / "manifest.json")
    manifest["startup_policy"] = read_json(fixture / "legacy-startup-policy.json")
    if not has_policy:
        manifest.pop("startup_policy")
    manifest["effective"]["wall_seconds"] = 600
    manifest["source"]["tasks"] = [
        {
            "package": "au12321ua/generation--cylinder",
            "directory": "generation--cylinder",
            "snapshot_digest": tree_digest(task_root),
        }
    ]
    write_json(root / "manifest.json", manifest)
    if snapshot_state == "missing":
        shutil.rmtree(task_root)
    elif snapshot_state == "tampered":
        (task_root / "task.toml").write_text("[agent]\ntimeout_sec=1\n")
    # Current dataset conditions must never substitute for the retained parent.
    app.configuration.persist("dataset", {**dataset, "resolved": "test/new@9"})
    before = {name: (root / name).read_bytes() for name in ("manifest.json", "job.json")}
    with data.store.connect() as db:
        database_before = list(db.iterdump())
    client = TestClient(create_app(data.root, start_scheduler=False))
    client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": PASSWORD}, headers=WRITE
    )
    # Login's own session writes are outside the read-only detail operation.
    with data.store.connect() as db:
        database_before = list(db.iterdump())
    response = client.get("/api/v1/runs/" + run_id)
    assert response.status_code == 200
    view = response.json()["manifest"]
    budget = view["startup_policy"]["tasks"][0]
    assert view["effective"]["wall_seconds"] == 600
    if snapshot_state == "valid":
        assert budget["agent_seconds"] == 600 and budget["verifier_seconds"] == 180
        assert 600 < budget["agent_seconds"] + budget["verifier_seconds"]
    else:
        assert budget.get("agent_seconds") is None and budget.get("verifier_seconds") is None
    if has_policy or snapshot_state == "valid":
        assert budget["author_build_timeout_sec"] == 600
    assert {name: (root / name).read_bytes() for name in before} == before
    with data.store.connect() as db:
        assert list(db.iterdump()) == database_before


def test_existing_detail_budgets_do_not_rederive(tmp_path):
    from harbor_helper.execution.runs import detail_startup_policy

    policy = {"tasks": [{"task": "task", "agent_seconds": 7, "verifier_seconds": 9}]}
    assert detail_startup_policy(tmp_path, {"startup_policy": policy}) == policy


def test_exact_rerun_missing_inputs_points_to_repair(recovery):
    data, app, actor, dataset, _task = recovery
    configured(recovery)
    accepted = app.accept(actor, {"agent": "oracle", "dataset_id": dataset["id"]}, "parent")
    prepare_one(data.store)
    parent = data.submission(accepted["id"])["run_id"]
    path = data.store.path(parent) / "manifest.json"
    manifest = read_json(path)
    manifest["effective"].pop("author_env")
    write_json(path, manifest)
    child = app.accept(actor, {}, "exact", parent=parent)
    prepare_one(data.store)
    failure = data.submission(child["id"])
    assert failure["status"] == "failed"
    assert "修复后重试" in failure["error"]
