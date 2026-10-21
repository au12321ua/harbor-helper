import json

import pytest

from harbor_helper.service import docker as service_docker


def test_read_only_discovery_filters_bounds_and_never_exposes_other_metadata(monkeypatch):
    calls = []

    def query(args):
        calls.append(args)
        if args[0] != "image":
            return "test-version"
        return "\n".join(
            json.dumps(
                {
                    "Repository": f"team/image{i}",
                    "Tag": "1",
                    "ID": "sha256:" + "a" * 64,
                    "Label": "secret-diagnostic",
                }
            )
            for i in range(205)
        )

    monkeypatch.setattr(service_docker, "_query", query)
    result = service_docker.discover_docker()
    assert calls == [
        ["--version"],
        ["info", "--format", "{{.ServerVersion}}"],
        ["image", "ls", "--no-trunc", "--format", "{{json .}}"],
    ]
    assert result["state"] == "ready" and result["truncated"]
    assert len(result["images"]) == 200
    assert result["images"][0] == {"reference": "team/image0:1"}
    assert "secret-diagnostic" not in json.dumps(result)


@pytest.mark.parametrize(
    "failure,step,state",
    [
        (FileNotFoundError, 0, "missing"),
        (RuntimeError, 0, "client_error"),
        (PermissionError, 1, "permission_denied"),
        (TimeoutError, 1, "daemon_unavailable"),
        (RuntimeError, 2, "images_unavailable"),
        (OverflowError, 2, "images_unavailable"),
    ],
)
def test_discovery_failure_is_actionable_without_raw_diagnostics(monkeypatch, failure, step, state):
    calls = []

    def query(args):
        calls.append(args)
        if len(calls) == step + 1:
            raise failure("secret-diagnostic")
        return "test"

    monkeypatch.setattr(service_docker, "_query", query)
    result = service_docker.discover_docker()
    assert result["state"] == state
    assert result["message"] and result["images"] == []
    assert "secret-diagnostic" not in json.dumps(result)
