"""Model rules run with metadata and version capabilities, without ServiceData."""

from copy import deepcopy

import pytest

from harbor_helper.service.model_configuration import Models
from harbor_helper.service.primitives import ServiceError


@pytest.fixture
def configuration():
    versions = {}
    credentials = {"key": {"id": "key", "provider_id": "provider"}}

    def read_object(kind, object_id):
        return deepcopy(versions[kind, object_id][-1])

    def save_version(kind, value):
        history = versions.setdefault((kind, value["id"]), [])
        saved = {**deepcopy(value), "version": len(history) + 1}
        history.append(saved)
        return deepcopy(saved)

    models = Models(
        read_object=read_object,
        read_credential=credentials.__getitem__,
        save_version=save_version,
    )
    for object_id in ("provider", "other"):
        models.save_object(
            "provider",
            {
                "id": object_id,
                "protocol": "openai-compatible",
                "endpoint": "https://provider.invalid/v1",
            },
        )
    return models, versions


def test_standalone_model_rules_preserve_versions_and_defaults(configuration):
    models, versions = configuration
    value = {
        "id": "profile",
        "provider_id": "provider",
        "credential_id": "key",
        "model": "test-model",
    }
    original = dict(value)
    first = models.save_object("profile", value)
    second = models.save_object("profile", {**first, "params": {"temperature": 0}})

    assert value == original
    assert first == {
        **value,
        "params": {},
        "opencode_version": "1.18.35",
        "enabled": True,
        "version": 1,
    }
    assert second == {**first, "params": {"temperature": 0}, "version": 2}
    assert versions["profile", "profile"] == [first, second]


def test_standalone_model_rules_reject_cross_provider_key_without_publishing(configuration):
    models, versions = configuration
    before = deepcopy(versions)
    with pytest.raises(ServiceError) as error:
        models.save_object(
            "profile",
            {"id": "profile", "provider_id": "other", "credential_id": "key", "model": "m"},
        )
    assert error.value.code == "credential_binding"
    assert versions == before
