import copy
import fcntl
import json
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from harbor_helper.execution.config import (
    DEFAULT,
    load_team,
    reject_secrets,
    validate_effective,
)
from harbor_helper.execution.runs import job_config, safe_environment, submit
from harbor_helper.execution.sources import verify_inputs
from harbor_helper.execution.worker import cleanup, finish, tick
from harbor_helper.persistence.files import read_json, tree_digest, write_json
from harbor_helper.persistence.store import Store
from harbor_helper.results.reports import compare, report


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = Store(tmp_path / "state")
    write_json(s.root / "team.json", DEFAULT)
    write_json(s.root / "service.json", {})
    # Oracle fixtures carry no service binding; credentials are covered separately.
    monkeypatch.setattr("harbor_helper.service.data.ServiceData.run_key", lambda *_, **__: None)
    return s


def default_cfg(**changes):
    cfg = {
        **DEFAULT["presets"]["default"],
        "dataset": DEFAULT["dataset"],
        "model": DEFAULT["model"],
        "runtime_image": DEFAULT["runtime_image"],
        "runtime_image_env": DEFAULT["runtime_image_env"],
        "max_cpus_per_trial": DEFAULT["max_cpus_per_trial"],
        "max_memory_mb_per_trial": DEFAULT["max_memory_mb_per_trial"],
        "task_filter": None,
    }
    return {**cfg, **changes}


def add_run(store, name="hh-test", status="queued", concurrency=1):
    path = store.root / "runs" / name
    path.mkdir()
    tasks = path / "tasks" / "box"
    tasks.mkdir(parents=True)
    (tasks / "task.toml").write_text("fixed grader")
    cfg = default_cfg(concurrency=concurrency)
    manifest = {
        "run_id": name,
        "effective": cfg,
        "harbor_version": "0.23.0",
        "image_id": "sha256:fixed",
        "image_alias": "harbor-helper/runtime:fixed",
        "bundle_digest": None,
        "source": {
            "requested": "org/data@2",
            "resolved": "org/data@sha256:fixed",
            "tasks": [
                {
                    "package": "org/box",
                    "ref": "sha256:fixed",
                    "directory": "box",
                    "snapshot_digest": tree_digest(tasks),
                }
            ],
        },
    }
    write_json(path / "manifest.json", manifest)
    with store.connect() as db:
        db.execute(
            "INSERT INTO runs(id,status,created,concurrency) VALUES(?,?,?,?)",
            (name, status, time.time(), concurrency),
        )
    return path, manifest


def trial(path, reward=0.0, exception=None):
    p = path / "harbor" / path.name / "box__attempt"
    p.mkdir(parents=True)
    write_json(
        p / "result.json",
        {
            "task_name": "org/box",
            "trial_name": p.name,
            "verifier_result": {"rewards": {"reward": reward}},
            "exception_info": exception,
        },
    )
    return p


def test_valid_zero_is_distinct_from_exception(store):
    p, _ = add_run(store)
    trial(p)
    value = report(store, p.name)
    assert value["complete"] and value["valid_attempts"] == 1
    result = next(p.glob("harbor/*/*/result.json"))
    data = json.loads(result.read_text())
    data["exception_info"] = {"exception_type": "VerifierTimeoutError"}
    write_json(result, data)
    value = report(store, p.name)
    assert not value["complete"] and value["valid_attempts"] == 0
    assert value["tasks"][0]["mean_rewards"] is None


def test_native_oracle_nonzero_is_failure(store):
    p, _ = add_run(store)
    t = trial(p)
    (t / "agent").mkdir()
    (t / "agent" / "exit-code.txt").write_text("1")
    value = report(store, p.name)
    assert value["invalid_attempts"] == 1
    assert value["tasks"][0]["attempts"][0]["exception"]["exception_type"] == "AgentNonZeroExit"


@pytest.mark.parametrize("reward", [float("nan"), float("inf"), None, "0", True])
def test_invalid_reward_not_counted(store, reward):
    p, _ = add_run(store)
    trial(p, reward)
    assert report(store, p.name)["valid_attempts"] == 0


def test_missing_and_malformed_results_preserved(store):
    p, _ = add_run(store)
    assert report(store, p.name)["missing_attempts"] == 1
    t = trial(p)
    (t / "result.json").write_text("{broken")
    value = report(store, p.name)
    assert value["invalid_attempts"] == 1 and not value["complete"]
    assert (t / "result.json").read_text() == "{broken"


def test_comparison_rejects_scoring_and_incomplete(store):
    a, ma = add_run(store, "a", "succeeded")
    b, mb = add_run(store, "b", "succeeded")
    trial(a, 0)
    trial(b, 1)
    assert compare(store, "a", "b")["mean_task_delta"] == {"reward": 1.0}
    mb["source"]["tasks"][0]["ref"] = "sha256:different"
    write_json(b / "manifest.json", mb)
    value = compare(store, "a", "b")
    assert not value["comparable"] and value["mean_task_delta"] is None
    write_json(b / "manifest.json", ma)
    next(b.glob("harbor/*/*/result.json")).unlink()
    assert not compare(store, "a", "b")["comparable"]


def test_rerun_refuses_modified_grader(store):
    p, m = add_run(store)
    verify_inputs(p, m)
    (p / "tasks" / "box" / "task.toml").write_text("changed grader")
    with pytest.raises(ValueError, match="Fixed task snapshot"):
        submit(store, load_team(store), parent=p.name, service={"submission_id": "s"})
    assert len(store.runs()) == 1


def test_digest_rejects_symlink_and_detects_mode(tmp_path):
    f = tmp_path / "bootstrap.sh"
    f.write_text("same")
    before = tree_digest(tmp_path)
    f.chmod(0o755)
    assert tree_digest(tmp_path) != before
    (tmp_path / "link").symlink_to(f)
    with pytest.raises(ValueError, match="symlinks"):
        tree_digest(tmp_path)


@pytest.mark.parametrize(
    "cfg",
    [
        {"apiKey": "abc"},
        {"password": "abc"},
        {"endpoint": "https://user:pass@host"},
        {"endpoint": "https://host?key=abc"},
    ],
)
def test_no_literal_credentials(cfg):
    with pytest.raises(ValueError):
        reject_secrets(cfg)


def test_nonsecret_token_length_settings_are_allowed():
    reject_secrets({"max_tokens": 64, "maxOutputTokens": 128})
    with pytest.raises(ValueError):
        reject_secrets({"max_tokens": "literal-token-value"})
    with pytest.raises(ValueError):
        reject_secrets({"access_token": 64})


def test_runtime_environment_drops_other_provider_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "never-inherit")
    monkeypatch.setenv("VLLM_API_KEY", "explicit-credential")
    value = safe_environment()
    assert "OPENAI_API_KEY" not in value and "VLLM_API_KEY" not in value


def test_missing_model_no_requests(store):
    with pytest.raises(ValueError, match="Model not configured"):
        validate_effective(load_team(store), default_cfg(agent="opencode"))


def test_cap_enforced(store):
    with pytest.raises(ValueError, match="concurrency"):
        validate_effective(load_team(store), default_cfg(concurrency=2))


def test_cleanup_failure_retains_capacity(store, monkeypatch):
    p, _ = add_run(store, "broken", "running")
    add_run(store, "queued")
    write_json(p / "projects.json", ["owned-project"])
    monkeypatch.setattr(
        "harbor_helper.execution.worker.cleanup",
        lambda _: (_ for _ in ()).throw(RuntimeError("Docker unavailable")),
    )

    def no_start(*args, **kwargs):
        pytest.fail("Capacity was released before cleanup confirmation")

    monkeypatch.setattr("harbor_helper.execution.worker.subprocess.Popen", no_start)
    tick(store, {})
    assert store.get("broken")["status"] == "cleanup_blocked"
    assert store.get("queued")["status"] == "queued"


def test_cleanup_exact_project_labels(store, monkeypatch):
    p, _ = add_run(store)
    write_json(p / "projects.json", ["owned-1", "owned-2"])
    calls = []
    monkeypatch.setattr(
        "harbor_helper.execution.worker.run_command", lambda cmd: calls.append(cmd) or ""
    )
    cleanup(p)
    assert calls and all(
        any("label=com.docker.compose.project=owned-" in arg for arg in cmd) for cmd in calls
    )
    assert not any("prune" in cmd for cmd in calls)


def test_cancel_terminal_only_after_cleanup(store, monkeypatch):
    p, _ = add_run(store, status="running")
    store.update(p.name, cancel=1)
    called = []
    monkeypatch.setattr("harbor_helper.execution.worker.cleanup", lambda _: called.append(True))
    finish(store, store.get(p.name), "cancelled", "user")
    assert called and store.get(p.name)["status"] == "cancelled"


def test_old_queue_migration_preserves_rows(tmp_path):
    root = tmp_path / "old-state"
    root.mkdir()
    with sqlite3.connect(root / "queue.sqlite") as db:
        db.execute("""CREATE TABLE runs (
            id TEXT PRIMARY KEY, status TEXT, created REAL, started REAL,
            finished REAL, pid INTEGER, birth TEXT, concurrency INTEGER,
            cancel INTEGER, reason TEXT, parent TEXT)""")
        db.execute("INSERT INTO runs(id,status,created,concurrency) VALUES('old','failed',1,1)")
    migrated = Store(root)
    assert migrated.get("old")["audit_status"] == "pending"
    assert migrated.get("old")["status"] == "failed"
    assert Store(root).runs() == migrated.runs()


def test_audit_failure_releases_slot(store, monkeypatch):
    first, _ = add_run(store, "first", "running")
    add_run(store, "next")
    available = False

    class Credentials:
        def __init__(self, root):
            assert root == store.root

        def run_key(self, run_id, execution=False):
            if run_id == "first" and not available:
                raise ValueError("Bound audit source unavailable")
            return "fake-first-marker" if run_id == "first" else None

    monkeypatch.setitem(
        sys.modules, "harbor_helper.service.data", SimpleNamespace(ServiceData=Credentials)
    )
    launched = []
    monkeypatch.setattr(
        "harbor_helper.execution.worker.subprocess.Popen",
        lambda *args, **kwargs: launched.append(kwargs) or SimpleNamespace(pid=999999),
    )
    (first / "worker.log").write_text("fake-first-marker")
    tick(store, {})
    assert store.get("first")["status"] == "failed"
    assert store.get("first")["audit_status"] == "incomplete"
    assert read_json(first / "cleanup.json")["confirmed"]
    assert store.get("next")["status"] == "running" and len(launched) == 1
    assert "VLLM_API_KEY" not in launched[0]["env"]
    # Restoring audit material repairs evidence without restarting execution.
    available = True
    from harbor_helper.execution.worker import audit_finished

    assert audit_finished(store, store.get("first"))
    assert store.get("first")["status"] == "failed"
    assert store.get("first")["audit_status"] == "clean"
    assert "fake-first-marker" not in (first / "worker.log").read_text()


def test_service_submit_publication_lock_cancel_and_frozen_rerun(store, monkeypatch):
    old_path, old = add_run(store, "parent", "succeeded")
    cfg = copy.deepcopy(old["effective"])
    cfg["wall_seconds"] -= 1
    service = {"submission_id": "submission", "submitter": "current"}
    allowed = False

    def locked():
        with (store.root / "control.lock").open("a") as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            return False

    class Publication:
        def __init__(self, root):
            assert root == store.root

        def allow_publish(self, submission_id):
            assert submission_id == "submission" and locked()
            return allowed

    monkeypatch.setitem(
        sys.modules, "harbor_helper.service.data", SimpleNamespace(ServiceData=Publication)
    )

    def image(reference):
        assert not locked(), "Preparation must not reserve the queue control lock"
        return old["image_id"]

    monkeypatch.setattr("harbor_helper.execution.runs.image_identity", image)
    monkeypatch.setattr("harbor_helper.execution.runs.subprocess.run", lambda *_, **__: None)
    monkeypatch.setattr(
        "harbor_helper.execution.runs.ensure_supervisor",
        lambda *_: pytest.fail("Supervisor disabled"),
    )
    with pytest.raises(ValueError, match="cancelled"):
        submit(
            store,
            load_team(store),
            cfg,
            parent=old_path.name,
            service=service,
            run_id="new",
            start_supervisor=False,
        )
    assert not (store.root / "runs" / "new").exists()
    assert len(store.runs()) == 1
    allowed = True
    value = submit(
        store,
        load_team(store),
        cfg,
        parent=old_path.name,
        service=service,
        run_id="new",
        start_supervisor=False,
    )
    new = read_json(store.path(value["run_id"]) / "manifest.json")
    assert new["effective"] == cfg and new["service"] == service
    assert new["source"] == old["source"]


def test_service_preparation_does_not_pause_supervision(store, monkeypatch):
    from harbor_helper.execution.worker import supervise
    from harbor_helper.security import credentials

    monkeypatch.delenv(credentials.KEY_ENV, raising=False)
    entered, release = threading.Event(), threading.Event()

    def prepare(_):
        entered.set()
        assert release.wait(5)

    monkeypatch.setitem(
        sys.modules, "harbor_helper.service.lifecycle", SimpleNamespace(prepare_one=prepare)
    )
    ticked = []

    def responsive_tick(*_):
        assert entered.wait(2)
        assert not release.is_set()
        ticked.append(True)

    monkeypatch.setattr("harbor_helper.execution.worker.tick", responsive_tick)
    monkeypatch.setattr("harbor_helper.execution.worker.RedactedStream", lambda stream, _: stream)

    class Done(BaseException):
        pass

    monkeypatch.setattr(
        "harbor_helper.execution.worker.time.sleep", lambda _: (_ for _ in ()).throw(Done())
    )
    try:
        with pytest.raises(Done):
            supervise(store.root)
    finally:
        release.set()
    assert ticked == [True]


def test_opencode_config_uses_only_selected_provider_and_placeholder(store):
    p, m = add_run(store)
    m["effective"]["agent"] = "opencode"
    m["effective"]["model"] = {
        "name": "local-model",
        "endpoint": "http://localhost:8000/v1",
        "credential_env": "VLLM_API_KEY",
        "opencode_version": "1.3.9",
    }
    cfg = job_config(p, m)
    agent = cfg["agents"][0]
    assert agent["env"] == {"VLLM_API_KEY": "${VLLM_API_KEY}"}
    assert agent["kwargs"]["opencode_config"]["enabled_providers"] == ["vllm"]
    assert agent["model_name"] == "vllm/local-model"


def test_bundle_cannot_silently_override_selected_model_parameters(store):
    p, m = add_run(store)
    m["effective"]["agent"] = "opencode"
    m["effective"]["model"] = {
        "name": "selected",
        "endpoint": "https://fixture.invalid/v1",
        "credential_env": "VLLM_API_KEY",
        "opencode_version": "1.18.35",
        "parameters": {"temperature": 0, "maxOutputTokens": 128},
    }
    cfg = job_config(p, m)
    selected = cfg["agents"][0]["kwargs"]["opencode_config"]["provider"]["vllm"]["models"][
        "selected"
    ]
    assert selected["options"] == m["effective"]["model"]["parameters"]
    bundle = p / "bundle" / "config"
    bundle.mkdir(parents=True)
    write_json(
        bundle / "opencode.json",
        {"provider": {"vllm": {"models": {"selected": {"options": {"temperature": 1}}}}}},
    )
    with pytest.raises(ValueError, match="frozen model parameters"):
        job_config(p, m)
    assert m["effective"]["model"]["parameters"]["temperature"] == 0


def test_credential_redaction_keeps_frozen_inputs_intact(store):
    from harbor_helper.execution.worker import redact_files

    p, _ = add_run(store)
    token = "literal-occurrence"
    frozen = p / "tasks" / "box" / "task.toml"
    frozen.write_text(token)
    native = trial(p)
    (native / "agent").mkdir()
    output = native / "agent" / "agent.txt"
    output.write_text("Bearer " + token)
    redact_files(p, [token])
    assert output.read_text() == "Bearer [REDACTED]"
    assert frozen.read_text() == token


@pytest.mark.parametrize("field,value", [("task_name", 3), ("reward", 10**400)])
def test_malformed_trial_diagnostic_corrects_success_without_changing_evidence(store, field, value):
    p, _ = add_run(store, status="succeeded")
    native = trial(p)
    raw = read_json(native / "result.json")
    if field == "reward":
        raw["verifier_result"]["rewards"]["reward"] = value
    else:
        raw[field] = value
    write_json(native / "result.json", raw)
    before = (native / "result.json").read_bytes()
    result = report(store, p.name)
    assert not result["complete"] and result["invalid_attempts"] == 1
    assert result["unexpected_trials"][0]["exception"]["exception_type"] == "MalformedTrialResult"
    assert store.get(p.name)["status"] == "failed"
    assert (native / "result.json").read_bytes() == before


def test_native_compare_image_difference_or_unknown_is_observation(store):
    a, ma = add_run(store, "native-a", status="succeeded")
    b, mb = add_run(store, "native-b", status="succeeded")
    for path, manifest in ((a, ma), (b, mb)):
        manifest["execution_mode"] = "harbor-native"
        manifest.pop("image_id")
        manifest.pop("image_alias")
        manifest["effective"].pop("runtime_image")
        manifest["effective"].pop("runtime_image_env")
        write_json(path / "manifest.json", manifest)
    trial(a, reward=0)
    trial(b, reward=1)
    observation = b / "harbor" / b.name / "box__attempt" / "helper-environment-observed.json"
    write_json(observation, {"project": "observed", "images": [{"image_id": "sha256:different"}]})
    value = compare(store, a.name, b.name)
    assert value["comparable"] and value["mean_task_delta"] == {"reward": 1.0}
    assert value["environment_observations"]["left"] == "unknown"
    assert (
        value["environment_observations"]["right"][0]["images"][0]["image_id"] == "sha256:different"
    )


def test_unavailable_image_observation_does_not_fail_valid_score(store):
    path, _ = add_run(store, "native-unknown", status="succeeded")
    evidence = trial(path, reward=0)
    (evidence / "helper-environment-broken.json").write_text("broken observation")
    result = report(store, path.name)
    assert result["complete"] and result["environment_observations"] == [{"images": "unknown"}]


@pytest.mark.parametrize(
    "left,right,comparable",
    [
        (2, 3, False),
        (2, 2, True),
        (None, 1, True),
        (1, None, True),
        (None, None, True),
        (None, 2, False),
    ],
)
def test_comparison_uses_actual_startup_multiplier_and_preserves_history(
    store, left, right, comparable
):
    folders = []
    for name, multiplier, reward in [("a", left, 0), ("b", right, 1)]:
        folder, manifest = add_run(store, name, "succeeded")
        manifest["execution_mode"] = "harbor-native"
        if multiplier is not None:
            manifest["effective"]["environment_build_timeout_multiplier"] = multiplier
        write_json(folder / "manifest.json", manifest)
        trial(folder, reward)
        folders.append(folder)
    before = [(folder / "manifest.json").read_bytes() for folder in folders]
    value = compare(store, "a", "b")
    assert value["comparable"] is comparable
    if comparable:
        assert value["config_changes"] == {} and value["reasons"] == []
        assert value["mean_task_delta"] == {"reward": 1.0}
    else:
        assert value["config_changes"]["environment_build_timeout_multiplier"] == {
            "left": left if left is not None else 1,
            "right": right if right is not None else 1,
        }
        assert (
            "Experiment condition differs: environment_build_timeout_multiplier" in value["reasons"]
        )
        assert value["mean_task_delta"] is None
    assert before == [(folder / "manifest.json").read_bytes() for folder in folders]


@pytest.mark.parametrize(
    "right,comparable", [("in-task-npm", True), ("offline-npm-binary-v1", False)]
)
def test_tool_preparation_condition_has_legacy_semantics(store, right, comparable):
    a, _ma = add_run(store, "a", "succeeded")
    b, mb = add_run(store, "b", "succeeded")
    mb["effective"]["agent_tool_preparation"] = right
    write_json(b / "manifest.json", mb)
    trial(a, 0)
    trial(b, 1)
    before = (a / "manifest.json").read_bytes()
    value = compare(store, "a", "b")
    assert value["comparable"] is comparable
    if not comparable:
        assert value["mean_task_delta"] is None
        assert value["config_changes"]["agent_tool_preparation"] == {
            "left": "in-task-npm",
            "right": right,
        }
    assert (a / "manifest.json").read_bytes() == before
