import argparse
import copy
import fcntl
import json
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from harbor_helper.config import DEFAULT, effective, load_team, reject_secrets
from harbor_helper.reports import compare, report
from harbor_helper.runs import job_config, safe_environment, submit
from harbor_helper.sources import verify_inputs
from harbor_helper.storage import Store, read_json, tree_digest, write_json
from harbor_helper.worker import cleanup, finish, tick


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state")
    write_json(s.root / "team.json", DEFAULT)
    return s


def add_run(store, name="hh-test", status="queued", concurrency=1):
    path = store.root / "runs" / name
    path.mkdir()
    tasks = path / "tasks" / "box"
    tasks.mkdir(parents=True)
    (tasks / "task.toml").write_text("fixed grader")
    cfg = effective(copy.deepcopy(DEFAULT), argparse.Namespace(preset="default"))
    cfg["concurrency"] = concurrency
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
        submit(store, load_team(store), parent=p.name)
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
    assert "OPENAI_API_KEY" not in value and value["VLLM_API_KEY"] == "explicit-credential"


def test_missing_model_no_requests(store):
    with pytest.raises(ValueError, match="Model not configured"):
        effective(load_team(store), argparse.Namespace(preset="model"))


def test_cap_enforced(store):
    with pytest.raises(ValueError, match="concurrency"):
        effective(load_team(store), argparse.Namespace(preset="default", concurrency=2))


def test_cleanup_failure_retains_capacity(store, monkeypatch):
    p, _ = add_run(store, "broken", "running")
    add_run(store, "queued")
    write_json(p / "projects.json", ["owned-project"])
    monkeypatch.setattr(
        "harbor_helper.worker.cleanup",
        lambda _: (_ for _ in ()).throw(RuntimeError("Docker unavailable")),
    )

    def no_start(*args, **kwargs):
        pytest.fail("Capacity was released before cleanup confirmation")

    monkeypatch.setattr("harbor_helper.worker.subprocess.Popen", no_start)
    tick(store, {})
    assert store.get("broken")["status"] == "cleanup_blocked"
    assert store.get("queued")["status"] == "queued"


def test_cleanup_exact_project_labels(store, monkeypatch):
    p, _ = add_run(store)
    write_json(p / "projects.json", ["owned-1", "owned-2"])
    calls = []
    monkeypatch.setattr("harbor_helper.worker.run_command", lambda cmd: calls.append(cmd) or "")
    cleanup(p)
    assert calls and all(
        any("label=com.docker.compose.project=owned-" in arg for arg in cmd) for cmd in calls
    )
    assert not any("prune" in cmd for cmd in calls)


def test_cancel_terminal_only_after_cleanup(store, monkeypatch):
    p, _ = add_run(store, status="running")
    store.update(p.name, cancel=1)
    called = []
    monkeypatch.setattr("harbor_helper.worker.cleanup", lambda _: called.append(True))
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


def test_service_audit_failure_releases_slot_and_does_not_use_home_auth(store, monkeypatch):
    write_json(store.root / "service.json", {})
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
        sys.modules, "harbor_helper.service_data", SimpleNamespace(ServiceData=Credentials)
    )
    monkeypatch.setattr("harbor_helper.auth.Auth", lambda *_: pytest.fail("HOME Auth in service"))
    launched = []
    monkeypatch.setattr(
        "harbor_helper.worker.subprocess.Popen",
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
    from harbor_helper.worker import audit_finished

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
        sys.modules, "harbor_helper.service_data", SimpleNamespace(ServiceData=Publication)
    )
    monkeypatch.setattr("harbor_helper.auth.Auth", lambda *_: pytest.fail("HOME Auth in service"))

    def image(reference):
        assert not locked(), "Preparation must not reserve the queue control lock"
        return old["image_id"]

    monkeypatch.setattr("harbor_helper.runs.image_identity", image)
    monkeypatch.setattr("harbor_helper.runs.subprocess.run", lambda *_, **__: None)
    monkeypatch.setattr(
        "harbor_helper.runs.ensure_supervisor", lambda *_: pytest.fail("Supervisor disabled")
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
    from harbor_helper import credentials
    from harbor_helper.worker import supervise

    write_json(store.root / "service.json", {})
    monkeypatch.setattr(credentials, "AUDIT_SECRETS", [])
    monkeypatch.setattr(credentials, "LEGACY_SECRETS", None)
    monkeypatch.delenv(credentials.KEY_ENV, raising=False)
    monkeypatch.delenv(credentials.LEGACY_KEY_ENV, raising=False)
    entered, release = threading.Event(), threading.Event()

    def prepare(_):
        entered.set()
        assert release.wait(5)

    monkeypatch.setitem(
        sys.modules, "harbor_helper.service_app", SimpleNamespace(prepare_one=prepare)
    )
    ticked = []

    def responsive_tick(*_):
        assert entered.wait(2)
        assert not release.is_set()
        ticked.append(True)

    monkeypatch.setattr("harbor_helper.worker.tick", responsive_tick)
    monkeypatch.setattr("harbor_helper.worker.RedactedStream", lambda stream, _: stream)

    class Done(BaseException):
        pass

    monkeypatch.setattr("harbor_helper.worker.time.sleep", lambda _: (_ for _ in ()).throw(Done()))
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
    from harbor_helper.worker import redact_files

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
