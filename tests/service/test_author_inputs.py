"""author inputs behavior with isolated synthetic inputs."""

import json

import pytest
from recovery_support import SOURCE, author_task

from harbor_helper.execution.author_inputs import AuthorInputError, check_inputs, discover
from harbor_helper.persistence.files import tree_digest


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
