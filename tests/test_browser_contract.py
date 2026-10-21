"""Raw HTTP responses and offline/type generation regression tests; synthetic only."""

import importlib.util
import json
import socket
from pathlib import Path

import pytest
from service_support import client

from harbor_helper.service import browser_contracts as b
from harbor_helper.service.api import create_app
from harbor_helper.service.application import Application
from harbor_helper.service.contract_boundary import adapter
from harbor_helper.service.route_contracts import browser_routes


@pytest.mark.parametrize("defect", ["extra", "missing", "type", "state", "nested"])
def test_raw_response_defects_are_safe_503(data, monkeypatch, defect):
    original = Application.runs

    def broken(self):
        value = original(self)
        if defect == "extra":
            value["undeclared"] = "injected-private-value"
        elif defect == "missing":
            value.pop("runs")
        elif defect == "type":
            value["runs"] = "injected-private-value"
        else:
            # Browser status must come from the canonical vocabulary. No filtering.
            sample = {k: None for k in b.RunSummary.model_fields}
            sample.update(
                id="fake",
                name="fake",
                status="invalid-state",
                created=1.0,
                submitter="synthetic",
                concurrency=1,
                cancel=False,
                audit_status="pending",
                dataset="fake",
                agent="oracle",
                attachment={},
            )
            if defect == "nested":
                sample["status"] = "queued"
                sample["attachment"] = {"undeclared": "injected-private-value"}
            value["runs"] = [sample]
        return value

    monkeypatch.setattr(Application, "runs", broken)
    response = client(data).get("/api/v1/runs")
    assert response.status_code == 503
    value = response.json()
    assert value["code"] == "service_unavailable"
    assert value["retryable"] is True
    assert "injected-private-value" not in response.text
    assert "invalid-state" not in response.text
    assert set(value) == set(
        __import__(
            "harbor_helper.service.dtos", fromlist=["ErrorResponse"]
        ).ErrorResponse.model_fields
    )


def test_session_and_pat_projection_cannot_be_interchanged(data):
    from automation_support import issue

    browser, pat, _ = issue(data, scopes=["read", "execute"])
    for client_, model in ((browser, b.User), (pat, b.MachineUser)):
        value = client_.get("/api/v1/me")
        assert value.status_code == 200
        adapter(model).validate_python(value.json(), strict=True)
    with pytest.raises(ValueError):
        adapter(b.User).validate_python(pat.get("/api/v1/me").json(), strict=True)
    assert pat.get("/api/v1/admin/users").status_code == 403
    assert browser.get("/api/v1/admin/users").status_code == 403


def test_export_is_offline_deterministic_and_excludes_non_browser_routes(tmp_path, monkeypatch):
    path = Path(__file__).parents[1] / "tools/browser_contract.py"
    spec = importlib.util.spec_from_file_location("browser_contract_export", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    protected = tmp_path / "protected"
    protected.mkdir()
    sentinel = protected / "sentinel"
    sentinel.write_bytes(b"keep")
    monkeypatch.chdir(protected)
    monkeypatch.setenv("HOME", str(protected))
    monkeypatch.setenv("HARBOR_HELPER_ROOT", str(protected))

    def denied(*args, **kwargs):
        raise AssertionError("Exporter attempted network/process/lifecycle")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr("subprocess.Popen", denied)
    monkeypatch.setattr("harbor_helper.execution.runs.ensure_supervisor", denied)
    before = sorted(p.relative_to(protected) for p in protected.rglob("*"))
    one, two = module.schema(), module.schema()
    assert one == two
    assert module.types(one) == module.types(two)
    assert sentinel.read_bytes() == b"keep"
    assert sorted(p.relative_to(protected) for p in protected.rglob("*")) == before
    assert all(not r["path"].startswith("/machine") for r in one["routes"])
    assert all(r["operation"] in b.BROWSER for r in one["routes"])
    classified = browser_routes(create_app(tmp_path / "classified", start_scheduler=False).routes)
    assert {r["operation"] for r in one["routes"]} == {
        getattr(r.endpoint, "__name__", "") for r in classified
    }
    checked = json.loads((path.parents[1] / "frontend/contracts.json").read_text())
    assert one == checked


def test_all_browser_routes_have_raw_boundary(tmp_path):
    app = create_app(tmp_path / "state", start_scheduler=False)
    names = set()
    for route in browser_routes(app.routes):
        name = getattr(route.endpoint, "__name__", "")
        assert hasattr(route.dependant.call, "__wrapped__"), name
        names.add(name)
    assert names == set(b.BROWSER)


def test_legacy_open_configuration_values_are_not_narrowed(data):
    from service_support import WRITE

    http = client(data, "admin")
    for path, body in [
        (
            "/admin/providers",
            {
                "protocol": "openai-compatible",
                "endpoint": "http://fixture.invalid/v1",
                "name": {"label": "synthetic"},
            },
        ),
        (
            "/admin/model-profiles",
            {"provider_id": "p1", "credential_id": "k1", "model": "synthetic", "name": ["label"]},
        ),
    ]:
        response = http.post("/api/v1" + path, json=body, headers=WRITE)
        assert response.status_code == 200
        assert response.json()["name"] == body["name"]
    response = http.patch(
        "/api/v1/admin/settings",
        json={"default_dataset_id": False, "default_model_profile": 0},
        headers=WRITE,
    )
    assert response.status_code == 200
    assert response.json()["default_dataset_id"] is False
    assert response.json()["default_model_profile"] == 0
