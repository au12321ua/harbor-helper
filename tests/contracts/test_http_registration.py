"""Registration invariants shared by authorization, audit and generated contracts."""

from collections import Counter

from fastapi.testclient import TestClient

from harbor_helper.service.api import create_app
from harbor_helper.service.browser_contracts import BROWSER, MACHINE
from harbor_helper.service.contract_boundary import ContractRoute
from harbor_helper.service.policy import CAPABILITIES, SCHEMA_OPERATIONS


def test_flat_unique_contract_routes_and_last_spa(tmp_path):
    app = create_app(tmp_path / "state", start_scheduler=False)
    routes = [r for r in app.routes if getattr(r, "path", "").startswith("/api/")]
    names = [r.endpoint.__name__ for r in routes]
    assert all(count == 1 for count in Counter(names).values())
    assert set(BROWSER) <= set(names)
    assert set(MACHINE) <= set(BROWSER)
    assert SCHEMA_OPERATIONS <= set(CAPABILITIES) <= set(names)
    assert all(isinstance(r, ContractRoute) for r in routes)
    assert all(
        getattr(r.dependant.call, "__wrapped__", None) is r.endpoint
        for r in routes
        if r.endpoint.__name__ in BROWSER
    )
    assert app.routes[-1].path == "/{path:path}"
    assert app.routes[-2].path == "/api/{missing:path}"


def test_setup_refreshes_every_registered_domain_without_restart(tmp_path):
    app = create_app(tmp_path / "state", start_scheduler=False)
    client = TestClient(app)
    headers = {"X-Requested-With": "harbor-helper"}
    response = client.post(
        "/api/v1/setup",
        headers=headers,
        json={
            "username": "admin",
            "password": "isolated-fixture-password",
            "setup_token": (tmp_path / ".state-deployment/setup-token").read_text(),
        },
    )
    assert response.status_code == 201
    response = client.post(
        "/api/v1/auth/login",
        headers=headers,
        json={"username": "admin", "password": "isolated-fixture-password"},
    )
    assert response.status_code == 200
    for path in (
        "/me",
        "/readiness",
        "/catalog",
        "/runs",
        "/attachments",
        "/access-credentials",
        "/admin/users",
        "/admin/limits",
        "/machine/schema",
    ):
        response = client.get("/api/v1" + path)
        assert response.status_code == 200, (path, response.text)
    response = client.get("/api/v1/unknown")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
