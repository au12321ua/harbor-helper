"""Protocols validated at catalog and admission; no upstream calls."""

import pytest

from harbor_helper.execution.model_protocols import bundle_config, parameters
from harbor_helper.service.application import Application
from harbor_helper.service.primitives import ServiceError


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
def test_native_profile_freeze_and_revalidate_after_provider_edit(data, protocol):
    provider = data.object("provider", "p1")
    data.models.save_object("provider", {**provider, "protocol": protocol})
    with pytest.raises(ServiceError, match="only max_output_tokens"):
        Application(data.root).accept(
            data.users()[0], {"dataset": "test/data@1", "model_profile": "m1"}, "old-profile"
        )
    profile = data.models.save_object("profile", {**data.object("profile", "m1"), "params": {}})
    assert profile["params"] == {"max_output_tokens": 4096}
    app = Application(data.root)
    accepted = app.accept(
        data.users()[0], {"dataset": "test/data@1", "model_profile": "m1"}, "native-new"
    )
    model = data.submission(accepted["id"])["frozen"]["effective"]["model"]
    assert model["protocol"] == protocol and model["parameters"] == {"max_output_tokens": 4096}


@pytest.mark.parametrize(
    "change", [{"endpoint": "http://other.invalid/v1"}, {"protocol": "anthropic"}]
)
def test_inherited_latest_key_refuses_changed_protocol_or_endpoint(data, preparation, change):
    from harbor_helper.service.lifecycle import prepare_one

    app = Application(data.root)
    actor = data.users()[0]
    accepted = app.accept(actor, {"dataset": "test/data@1", "model_profile": "m1"}, "original")
    prepare_one(data.store)
    rid = data.submission(accepted["id"])["run_id"]
    # Ordinary accepted runs retain their original version/endpoint.
    data.models.save_object("provider", {**data.object("provider", "p1"), **change})
    data.add_credential("k1", "p1", "changed-key", "fake-new-host-key", rotate=True)
    assert data.run_key(rid, execution=True) == "fake-service-key-one-2026"
    with pytest.raises(ServiceError) as error:
        app.accept(actor, {}, "rerun-changed", parent=rid)
    assert error.value.status == 409 and error.value.code == "provider_changed"
    # Frozen provider version tampering also fails at execution.
    from harbor_helper.persistence.files import read_json, write_json

    path = data.store.path(rid) / "manifest.json"
    manifest = read_json(path)
    manifest["service"]["provider_version"] = 2
    write_json(path, manifest)
    with pytest.raises(ServiceError, match="binding mismatch"):
        data.run_key(rid, execution=True)


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
@pytest.mark.parametrize(
    "params",
    [
        {"temperature": 0.1},
        {"max_tokens": 20},
        {"thinking": {}},
        {"max_output_tokens": 0},
        {"max_output_tokens": True},
        {"max_output_tokens": 1.5},
    ],
)
def test_native_rejects_unsupported_or_invalid_parameters(protocol, params):
    with pytest.raises(ValueError):
        parameters(protocol, params, "1.18.35")


def test_runtime_capability_scope_and_chat_not_tightened():
    assert parameters("openai-compatible", {"temperature": 0.1}, "1.2.3") == {"temperature": 0.1}
    with pytest.raises(ValueError, match="1.18.35"):
        parameters("openai", {}, "1.2.3")


@pytest.mark.parametrize(
    "value",
    [
        {"provider": {}},
        {"model": "other"},
        {"small_model": "other"},
        {"enabled_providers": []},
        {"disabled_providers": []},
        {"plugin": []},
        {"mode": {}},
        {"agent": {"build": {"model": "other"}}},
        {"agent": {"build": {"options": {"apiKey": "fake"}}}},
    ],
)
def test_bundle_rejects_model_auth_adapter_plugin_channels(value):
    with pytest.raises(ValueError):
        bundle_config(value)


def test_bundle_nonsecret_settings_supported():
    value = {
        "agent": {"build": {"prompt": "Be precise", "tools": {"bash": True}}},
        "permission": {"*": "allow"},
    }
    assert bundle_config(value) == value
