"""results behavior with isolated synthetic inputs."""

import json

import pytest
from support.core_support import add_run, trial

from harbor_helper.persistence.files import read_json, write_json
from harbor_helper.results.reports import compare, report


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


def test_compare_image_difference_or_unknown_is_observation(store):
    a, _ = add_run(store, "native-a", status="succeeded")
    b, _ = add_run(store, "native-b", status="succeeded")
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
