import asyncio
from types import SimpleNamespace

import pytest
from admission_fixture import synthetic_activity
from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.task.config import NetworkMode, NetworkPolicy

from harbor_helper.execution.agents import HelperOpenCode
from harbor_helper.execution.config import DEFAULT, validate_effective
from harbor_helper.execution.environments import NativeDockerEnvironment
from harbor_helper.persistence.files import read_json, tree_digest
from harbor_helper.results.reports import trial_diagnosis
from harbor_helper.service.application import Application
from harbor_helper.service.data import ServiceData
from harbor_helper.service.lifecycle import prepare_one


def test_policy_frozen_and_legacy_rerun_preserved(tmp_path, monkeypatch):
    data = ServiceData.initialize(
        tmp_path / "state", tmp_path / "private/master", "admin", "fake-startup-password-2026"
    )
    synthetic_activity(data)
    app, actor = Application(data.root), data.users()[0]

    def source(reference, *, target, **kwargs):
        task = target / "box"
        task.mkdir(parents=True)
        (task / "task.toml").write_text(
            '[environment]\nbuild_timeout_sec=30\nnetwork_mode="no-network"\n'
        )
        return {
            "resolved": reference,
            "tasks": [
                {"directory": "box", "package": "test/box", "snapshot_digest": tree_digest(task)}
            ],
        }

    monkeypatch.setattr("harbor_helper.service.sources.source_call", source)
    monkeypatch.setattr("harbor_helper.execution.runs.ensure_supervisor", lambda _: None)
    accepted = app.accept(
        actor,
        {"agent": "oracle", "dataset": "test/data@1", "environment_build_timeout_multiplier": 2},
        "policy",
    )
    assert (
        data.submission(accepted["id"])["frozen"]["effective"][
            "environment_build_timeout_multiplier"
        ]
        == 2
    )
    prepare_one(data.store)
    parent = data.submission(accepted["id"])["run_id"]
    folder = data.store.path(parent)
    before = (folder / "tasks/box/task.toml").read_bytes()
    assert read_json(folder / "job.json")["environment_build_timeout_multiplier"] == 2
    policy = read_json(folder / "manifest.json")["startup_policy"]
    assert policy["tasks"][0]["author_build_timeout_sec"] == 30
    assert policy["tasks"][0]["start_wait_timeout_sec"] == 60
    assert policy["tasks"][0]["author_network_mode"] == "no-network"
    assert app.detail(parent)["manifest"]["startup_policy"] == policy
    again = app.accept(actor, {}, "rerun-policy", parent)
    assert (
        data.submission(again["id"])["frozen"]["effective"]["environment_build_timeout_multiplier"]
        == 2
    )
    assert (folder / "tasks/box/task.toml").read_bytes() == before
    # Simulate a genuinely old accepted parent: its absent option stays absent.
    manifest = read_json(folder / "manifest.json")
    manifest["effective"].pop("environment_build_timeout_multiplier")
    from harbor_helper.persistence.files import write_json

    write_json(folder / "manifest.json", manifest)
    old_bytes = (folder / "manifest.json").read_bytes()
    legacy = app.accept(actor, {}, "old-rerun", parent)
    assert (
        "environment_build_timeout_multiplier"
        not in data.submission(legacy["id"])["frozen"]["effective"]
    )
    assert (folder / "manifest.json").read_bytes() == old_bytes


@pytest.mark.parametrize("value", [True, 0, -1, float("nan"), float("inf"), "10"])
def test_invalid_multiplier(value):
    cfg = {"agent": "oracle", "attempts": 1, "concurrency": 1, "wall_seconds": 1800}
    cfg.update(
        dataset=DEFAULT["dataset"],
        model=None,
        max_cpus_per_trial=2,
        max_memory_mb_per_trial=4096,
        environment_build_timeout_multiplier=value,
    )
    with pytest.raises(ValueError, match="multiplier"):
        validate_effective(DEFAULT, cfg)


@pytest.mark.parametrize(
    "failure,status", [(asyncio.CancelledError, "interrupted"), (RuntimeError, "failed")]
)
def test_compose_failure_records_phase_without_secret(tmp_path, monkeypatch, failure, status):
    async def original(self, command, **kwargs):
        assert read_json(tmp_path / "helper-phases-owned.json")[0]["status"] == "running"
        raise failure("secret-output-never-copied")

    monkeypatch.setattr(DockerEnvironment, "_run_docker_compose_command", original)
    env = object.__new__(NativeDockerEnvironment)
    env.session_id = "owned"
    env.trial_paths = SimpleNamespace(trial_dir=tmp_path)
    with pytest.raises(failure):
        asyncio.run(env._run_docker_compose_command(["build"]))
    phase = read_json(tmp_path / "helper-phases-owned.json")[0]
    assert phase["status"] == status and phase["seconds"] >= 0
    assert "secret-output-never-copied" not in str(phase)


def test_setup_no_network_has_preinstalled_path_and_missing_diagnosis(tmp_path):
    class Environment:
        network_policy = NetworkPolicy(network_mode=NetworkMode.NO_NETWORK)

        def __init__(self, installed):
            self.installed = installed
            self.commands = []

        async def exec(self, command, **kwargs):
            self.commands.append(command)
            if command.startswith("command -v opencode"):
                return SimpleNamespace(
                    stdout="1.2.3" if self.installed else "", return_code=0 if self.installed else 1
                )
            return SimpleNamespace(stdout="node\nnpm\n", return_code=0)

    agent = object.__new__(HelperOpenCode)
    agent._version = "1.2.3"
    agent.logs_dir = tmp_path
    environment = Environment(True)
    asyncio.run(agent.install(environment))
    assert read_json(tmp_path / "install-decision.json")["reused"]
    assert len(environment.commands) == 1
    environment = Environment(False)
    with pytest.raises(RuntimeError, match="network_mode=no-network.*node, npm"):
        asyncio.run(agent.install(environment))
    decision = read_json(tmp_path / "install-decision.json")
    assert decision["missing_dependencies"] == ["node", "npm"] and decision["status"] == "blocked"
    assert not any("apt-get" in command for command in environment.commands)


def test_diagnosis_distinguishes_unreached_from_zero_and_does_not_copy_raw(tmp_path):
    result = {
        "environment_setup": {
            "started_at": "2026-10-09T11:20:29+00:00",
            "finished_at": "2026-10-09T11:20:59+00:00",
        },
        "exception_info": {
            "exception_type": "EnvironmentStartTimeoutError",
            "exception_message": "private-raw-diagnostic",
        },
    }
    diagnosis = trial_diagnosis(result, tmp_path, {"environment_build_timeout_multiplier": 2})
    assert diagnosis["phase"] == "environment_setup"
    assert diagnosis["phases"][0]["seconds"] == 30
    assert not diagnosis["phases"][1]["reached"] and diagnosis["phases"][1]["seconds"] is None
    assert diagnosis["compose"] == "unknown" and "private-raw" not in str(diagnosis)


def test_legacy_safe_report_enrichment_is_read_only(tmp_path):
    from harbor_helper.persistence.files import write_json

    data = ServiceData.initialize(
        tmp_path / "state", tmp_path / "private/master", "admin", "fake-startup-password-2026"
    )
    synthetic_activity(data)
    app = Application(data.root)
    run = "hh-legacy"
    folder = data.root / "runs" / run
    folder.mkdir(parents=True)
    write_json(
        folder / "manifest.json",
        {"effective": {"agent": "oracle", "dataset": "fixture/data@1", "wall_seconds": 600}},
    )
    write_json(
        folder / "report.json",
        {
            "tasks": [
                {
                    "attempts": [
                        {
                            "phase_timings": {
                                "environment_setup": {
                                    "started_at": "2026-10-09T11:20:29Z",
                                    "finished_at": "2026-10-09T11:20:59Z",
                                },
                                "agent_setup": "unknown",
                                "agent_execution": "unknown",
                                "verifier": "unknown",
                            },
                            "framework_exception": {
                                "exception_type": "EnvironmentStartTimeoutError"
                            },
                        }
                    ]
                }
            ]
        },
    )
    with data.store.connect() as db:
        db.execute(
            "INSERT INTO runs(id,status,created,concurrency,audit_status) VALUES(?,?,?,?,?)",
            (run, "failed", 1, 1, "clean"),
        )
    before = (folder / "report.json").read_bytes()
    safe = app.safe_report(run)
    diagnosis = safe["tasks"][0]["attempts"][0]["diagnosis"]
    assert diagnosis["phase"] == "environment_setup" and diagnosis["startup_multiplier"] == 1
    assert all(not phase["reached"] for phase in diagnosis["phases"][1:])
    assert (folder / "report.json").read_bytes() == before
