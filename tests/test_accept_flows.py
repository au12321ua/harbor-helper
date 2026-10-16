"""Frozen plans of the four acceptance flows: submit, rerun, repair retry and recovery."""

import json

import pytest
from test_execution_recovery import configured, recovery  # noqa: F401 - shared fixture

from harbor_helper.persistence.files import read_json
from harbor_helper.service.lifecycle import prepare_one
from harbor_helper.service.primitives import ServiceError

ORIGINAL = {
    "BUILD_AGENT_IMAGE": "author/agent:original",
    "BUILD_VERIFIER_IMAGE": "author/verifier:original",
}
CHANGED = {
    "BUILD_AGENT_IMAGE": "author/agent:fixed",
    "BUILD_VERIFIER_IMAGE": "author/verifier:original",
}


@pytest.fixture
def flows(recovery):  # noqa: F811
    data, app, actor, dataset, _task = recovery
    configured(recovery)
    data.models.save_object(
        "provider",
        {
            "id": "p1",
            "name": "Provider",
            "protocol": "openai-compatible",
            "endpoint": "http://provider.invalid/v1",
        },
    )
    data.add_credential("k1", "p1", "Key", "fake-flow-key-2026")
    data.models.save_object(
        "profile",
        {
            "id": "m1",
            "name": "Model",
            "provider_id": "p1",
            "credential_id": "k1",
            "model": "test-model",
            "params": {"temperature": 0},
        },
    )
    data.create_user("bob", "flow-fixture-password-2026")
    bob = next(u for u in data.users() if u["username"] == "bob")
    request = {
        "dataset_id": dataset["id"],
        "model_profile": "m1",
        "name": "Baseline",
        "wall_seconds": 900,
    }
    accepted = app.accept(actor, request, "submit")
    prepare_one(data.store)
    parent = data.submission(accepted["id"])["run_id"]
    assert parent
    # Later team changes: current credential version and author values move on.
    data.add_credential("k1", "p1", "Key", "fake-flow-key-rotated-2026", rotate=True)
    app.configuration.save_author_parameters(dataset["id"], CHANGED)
    return data, app, actor, bob, dataset, accepted, parent


def frozen(data, submission):
    return data.submission(submission["id"])["frozen"]


def test_submit_freezes_dataset_model_and_author_inputs(flows):
    data, _app, actor, _bob, dataset, accepted, _parent = flows
    value = frozen(data, accepted)
    cfg, service = value["effective"], value["service"]
    assert cfg["agent"] == "opencode" and cfg["wall_seconds"] == 900
    assert cfg["dataset"] == dataset["resolved"]
    assert cfg["author_env"] == ORIGINAL
    assert cfg["agent_tool_preparation"] == "offline-npm-binary-v1"
    assert cfg["environment_build_timeout_multiplier"] == 10
    assert cfg["model"]["endpoint"] == "http://provider.invalid/v1"
    assert service["user_id"] == actor["id"] and service["name"] == "Baseline"
    assert service["dataset_id"] == dataset["id"]
    assert (service["credential_id"], service["credential_version"]) == ("k1", 1)
    assert service["author_input_check"] and service["attachment_lineage"] == "none"
    assert value["bundle_id"] is None
    assert "retry_changes" not in service


def test_rerun_keeps_frozen_inputs_but_current_identity_and_credential(flows):
    data, app, _actor, bob, _dataset, _accepted, parent = flows
    child = app.accept(bob, {}, "rerun", parent)
    assert app.accept(bob, {}, "rerun", parent)["id"] == child["id"]
    value = frozen(data, child)
    manifest = read_json(data.store.path(parent) / "manifest.json")
    assert value["effective"] == manifest["effective"]
    assert value["effective"]["author_env"] == ORIGINAL
    service = value["service"]
    assert service["user_id"] == bob["id"] and service["submitter"] == "bob"
    assert service["name"] == "Baseline · 重跑"
    assert service["credential_version"] == 2
    assert "retry_changes" not in service
    assert data.submission(child["id"])["parent"] == parent
    with pytest.raises(ServiceError) as error:
        app.accept(bob, {"wall_seconds": 60}, "rerun-options", parent)
    assert error.value.code == "rerun_options"


def test_retry_refreshes_author_inputs_and_records_changes(flows):
    data, app, _actor, bob, _dataset, _accepted, parent = flows
    child = app.accept(bob, {"wall_seconds": 1200}, "retry", parent, retry=True)
    value = frozen(data, child)
    cfg, service = value["effective"], value["service"]
    assert cfg["author_env"] == CHANGED and cfg["wall_seconds"] == 1200
    assert service["name"] == "Baseline · 修复重试"
    assert service["retry_changes"] == {
        "author_env": {"old": ORIGINAL, "new": CHANGED},
        "wall_seconds": {"old": 900, "new": 1200},
    }
    assert service["credential_version"] == 2
    with pytest.raises(ServiceError) as error:
        app.accept(bob, {"attempts": 2}, "retry-options", parent, retry=True)
    assert error.value.code == "retry_options"


def test_recover_reuses_failed_plan_with_current_author_inputs(flows):
    data, app, _actor, bob, _dataset, _accepted, parent = flows
    child = app.accept(bob, {}, "rerun", parent)
    with pytest.raises(ServiceError) as error:
        app.recover_submission(bob, child["id"], "too-early")
    assert error.value.code == "recovery_state"
    failed = data.submission(child["id"])
    failed["frozen"]["service"]["author_input_issues"] = [{"reason": "fixture"}]
    with data.store.connect() as db:
        db.execute(
            "UPDATE submissions SET status='failed',frozen=? WHERE id=?",
            (json.dumps(failed["frozen"]), child["id"]),
        )
    recovered = app.recover_submission(bob, child["id"], "recover")
    value = frozen(data, recovered)
    cfg, service = value["effective"], value["service"]
    assert cfg["author_env"] == CHANGED
    assert cfg["wall_seconds"] == failed["frozen"]["effective"]["wall_seconds"]
    assert service["recovered_submission"] == child["id"]
    assert service["name"] == failed["frozen"]["service"]["name"] == "Baseline · 重跑"
    assert "author_input_issues" not in service
    assert data.submission(recovered["id"])["parent"] == parent
