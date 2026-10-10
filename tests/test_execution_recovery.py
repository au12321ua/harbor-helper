"""Recovery contracts with immutable author fixtures, no model or daemon requests."""

import json
import shutil

import pytest
from fastapi.testclient import TestClient
from harbor.models.job.config import JobConfig

from harbor_helper.execution.author_inputs import AuthorInputError, check_inputs, discover
from harbor_helper.persistence.files import read_json, tree_digest, write_json
from harbor_helper.results.reports import compare
from harbor_helper.service.api import create_app
from harbor_helper.service.application import Application
from harbor_helper.service.data import ServiceData, ServiceError
from harbor_helper.service.lifecycle import prepare_one

SOURCE = "test/benchmark@sha256:" + "b" * 64
WRITE = {"X-Requested-With": "harbor-helper"}
PASSWORD = "recovery-fixture-password"


def author_task(root, *, compose=True, extra=""):
    root.mkdir(parents=True)
    (root / "task.toml").write_text(
        'version="1.0"\n[agent]\ntimeout_sec=600\n[verifier]\ntimeout_sec=180\n' + extra
    )
    if compose:
        (root / "environment").mkdir()
        (root / "environment/compose.yaml").write_text(
            "services:\n  main:\n    image: ${BUILD_AGENT_IMAGE:?required}\n"
        )
        (root / "tests").mkdir()
        (root / "tests/compose.yaml").write_text(
            "services:\n  verifier:\n    image: ${BUILD_VERIFIER_IMAGE:?required}\n"
        )
    return {
        "package": "test/answer",
        "directory": root.name,
        "ref": "sha256:" + "c" * 64,
        "snapshot_digest": tree_digest(root),
    }


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    task = tmp_path / "authors/answer"
    author_task(task)
    # Client config discovery contract is tested separately with actual Docker CLI.
    monkeypatch.setattr(
        "harbor_helper.execution.author_inputs.compose_variables",
        lambda file: [
            (
                "BUILD_AGENT_IMAGE"
                if file.parent.name == "environment"
                else "BUILD_VERIFIER_IMAGE",
                True,
                "",
            )
        ],
    )
    data = ServiceData.initialize(
        tmp_path / "state", tmp_path / "private/master", "admin", PASSWORD
    )
    app = Application(data.root)
    actor = data.users()[0]

    def source(reference, *, target=None, **kwargs):
        if target is None:
            return {
                "resolved": SOURCE,
                "tasks": [{"name": "answer", "package": "test/answer", "ref": "fixed"}],
            }
        shutil.copytree(task, target / "answer")
        return {
            "requested": reference,
            "resolved": SOURCE,
            "tasks": [
                {
                    "package": "test/answer",
                    "directory": "answer",
                    "ref": "fixed",
                    "snapshot_digest": tree_digest(target / "answer"),
                }
            ],
        }

    monkeypatch.setattr("harbor_helper.service.configuration.source_call", source)
    monkeypatch.setattr("harbor_helper.service.sources.source_call", source)
    dataset = app.configuration.save(
        "dataset", {"name": "Generic", "reference": "test/benchmark@1"}
    )
    dataset = app.configuration.verify("dataset", dataset["id"])
    return data, app, actor, dataset, task


def configured(recovery):
    _data, app, _actor, dataset, _task = recovery
    app.configuration.inspect_author_parameters(dataset["id"])
    parameters = app.configuration.save_author_parameters(
        dataset["id"],
        {
            "BUILD_AGENT_IMAGE": "author/agent:original",
            "BUILD_VERIFIER_IMAGE": "author/verifier:original",
        },
    )
    return parameters


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


def test_generic_no_compose_and_host_templates(tmp_path):
    source = {"resolved": SOURCE, "tasks": [author_task(tmp_path / "answer", compose=False)]}
    discovery = discover(tmp_path, source)
    assert discovery["variables"] == {} and discovery["blocked"] == []
    check_inputs(discovery, {})
    assert discovery["budgets"][0]["agent_seconds"] == 600
    source["tasks"] = [
        author_task(
            tmp_path / "templated",
            compose=False,
            extra='[environment.env]\nNEEDS="${HOST_INPUT}"\nDEFAULT="${OPTIONAL:-safe}"\n',
        )
    ]
    with pytest.raises(AuthorInputError, match="HOST_INPUT"):
        check_inputs(discover(tmp_path, source), {})


def test_compose_steps_literal_and_reserved_protection(tmp_path, monkeypatch):
    source = {
        "resolved": SOURCE,
        "tasks": [author_task(tmp_path / "answer", extra='[environment.env]\nFIXED="literal"\n')],
    }
    monkeypatch.setattr(
        "harbor_helper.execution.author_inputs.compose_variables",
        lambda _: [
            ("FIXED", True, ""),
            ("MAIN_IMAGE_NAME", True, ""),
            ("BUILD_INPUT", True, ""),
            ("API_TOKEN", True, "never-expose-default"),
        ],
    )
    discovery = discover(tmp_path, source)
    assert set(discovery["variables"]) == {"BUILD_INPUT"}
    assert "never-expose-default" not in json.dumps(discovery)
    assert any(issue["variables"] == ["API_TOKEN"] for issue in discovery["blocked"])
    with pytest.raises(ValueError, match="whitelist"):
        check_inputs(discovery, {"FIXED": "override"})


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


def test_no_compose_legacy_schema_empty_env_no_client_calls(tmp_path, monkeypatch):
    task = tmp_path / "public"
    task.mkdir()
    (task / "task.toml").write_text(
        'version="1.0"\n[environment]\nallow_internet=true\n[environment.env]\n[verifier]\ntimeout_sec=900.0\n[verifier.env]\n[solution.env]\n[agent]\ntimeout_sec=900.0\n'
    )
    monkeypatch.setattr(
        "harbor_helper.execution.author_inputs.compose_variables",
        lambda _: pytest.fail("No Compose must not call client"),
    )
    value = discover(
        tmp_path,
        {
            "resolved": SOURCE,
            "tasks": [
                {
                    "package": "public/task",
                    "directory": "public",
                    "snapshot_digest": tree_digest(task),
                }
            ],
        },
    )
    check_inputs(value, {})
    assert value["variables"] == {} and value["budgets"][0] == {
        "task": "public/task",
        "agent_seconds": 900,
        "verifier_seconds": 900,
    }


@pytest.mark.parametrize(
    "section", ["environment.env", "verifier.env", "solution.env", "steps.verifier.env"]
)
def test_missing_host_templates_cover_oracle_verifier_steps(tmp_path, section):
    text = 'version="1.0"\n'
    if section.startswith("steps."):
        text += '[[steps]]\nname="first"\n'
    text += f'[{section}]\nEXTERNAL="${{HOST_REQUIRED}}"\n'
    task = tmp_path / "task"
    task.mkdir()
    (task / "task.toml").write_text(text)
    value = discover(
        tmp_path,
        {
            "resolved": SOURCE,
            "tasks": [
                {"package": "test/task", "directory": "task", "snapshot_digest": tree_digest(task)}
            ],
        },
    )
    with pytest.raises(AuthorInputError, match="HOST_REQUIRED"):
        check_inputs(value, {})


def test_real_compose_client_discovers_required_and_defaults(tmp_path, monkeypatch):
    # Assert exact client argv, isolation and column interpretation without a daemon.
    from types import SimpleNamespace

    from harbor_helper.execution.author_inputs import compose_variables

    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert "DOCKER_HOST" not in kwargs["env"] and "CAD_BENCH_AGENT_IMAGE" not in kwargs["env"]
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "NAME                REQUIRED            DEFAULT VALUE       ALTERNATE VALUE\n"
                "BUILD_IMAGE         true                                    \n"
                "BUILD_MODE          false               development         \n"
            ),
        )

    monkeypatch.setattr("harbor_helper.execution.author_inputs.subprocess.run", run)
    file = tmp_path / "docker-compose.yaml"
    assert compose_variables(file) == [
        ("BUILD_IMAGE", True, ""),
        ("BUILD_MODE", False, "development"),
    ]
    assert calls[0][0][1:] == [
        "compose",
        "--env-file",
        "/dev/null",
        "-f",
        str(file),
        "config",
        "--variables",
    ]


def test_compose_failure_is_explicit_and_infra_list_comes_from_harbor(tmp_path, monkeypatch):
    from harbor_helper.execution.author_inputs import INFRA

    assert {
        "PREBUILT_IMAGE_NAME",
        "ENV_AGENT_LOGS_PATH",
        "HOST_AGENT_LOGS_PATH",
        "ENV_VERIFIER_LOGS_PATH",
        "HOST_ARTIFACTS_PATH",
    } <= INFRA
    source = {"resolved": SOURCE, "tasks": [author_task(tmp_path / "task")]}
    monkeypatch.setattr(
        "harbor_helper.execution.author_inputs.compose_variables",
        lambda _: (_ for _ in ()).throw(ValueError("private raw output")),
    )
    with pytest.raises(AuthorInputError, match="compose_discovery_failed") as raised:
        discover(tmp_path, source)
    assert raised.value.code == "author_input_discovery" and "private raw output" not in str(
        raised.value
    )


def test_retry_model_only_fills_missing_strategy_preserves_research_and_identity(recovery):
    data, app, actor, dataset, _task = recovery
    configured(recovery)
    data.save_object(
        "provider",
        {
            "id": "provider",
            "name": "Fixture",
            "protocol": "openai-compatible",
            "endpoint": "http://provider.invalid/v1",
        },
    )
    data.add_credential("fixture-key", "provider", "Fixture", "fake-only-nonproduction-credential")
    data.save_object(
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


def test_conflicting_same_name_literals_requires_separate_tasks(tmp_path, monkeypatch):
    first = author_task(tmp_path / "external")
    second = author_task(
        tmp_path / "fixed", compose=False, extra='[environment.env]\nBUILD_IMAGE="author-fixed"\n'
    )
    monkeypatch.setattr(
        "harbor_helper.execution.author_inputs.compose_variables",
        lambda _: [("BUILD_IMAGE", True, "")],
    )
    both = discover(tmp_path, {"resolved": SOURCE, "tasks": [first, second]})
    assert "BUILD_IMAGE" in both["variables"]
    with pytest.raises(AuthorInputError, match="submit_separately"):
        check_inputs(both, {"BUILD_IMAGE": "configured"})
    single = discover(tmp_path, {"resolved": SOURCE, "tasks": [first]})
    check_inputs(single, {"BUILD_IMAGE": "configured"})
    fixed = discover(tmp_path, {"resolved": SOURCE, "tasks": [second]})
    assert fixed["variables"] == {}
    check_inputs(fixed, {})


def test_unsupported_dataset_features_have_specific_safe_code(monkeypatch, capsys):
    import io
    import sys
    from types import SimpleNamespace

    from harbor_helper.service.sources import main

    async def metadata(*_args):
        return SimpleNamespace(metrics=["custom"], files=[], version="sha256:fixed")

    monkeypatch.setattr(
        "harbor.registry.client.package.PackageDatasetClient.get_dataset_metadata", metadata
    )
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"reference": "test/data@1", "target": None, "task": None})),
    )
    with pytest.raises(SystemExit):
        main()
    value = json.loads(capsys.readouterr().out)
    assert value["error"] == "dataset_features_unsupported"
    assert "metrics/files" in value["message"] and "不是凭据错误" in value["message"]


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
