"""Fail-closed route coverage, including registration bypasses; synthetic only."""

import copy
import importlib.util
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from harbor_helper.service import route_contracts as registry
from harbor_helper.service.api import create_app
from harbor_helper.service.browser_contracts import BROWSER, MACHINE, REQUESTS
from harbor_helper.service.contract_boundary import ContractRoute, validate_output
from harbor_helper.service.primitives import ServiceError


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path / "state", start_scheduler=False)


def endpoint():
    return {"secret": "never-return"}


async def async_endpoint():
    return {"secret": "never-return"}


@pytest.mark.parametrize("handler", [endpoint, async_endpoint])
def test_constructor_rejects_undocumented_sync_and_async(handler):
    with pytest.raises(ValueError, match="Unregistered"):
        ContractRoute("/api/v1/new", handler, methods=["GET"])


@pytest.mark.parametrize("defect", ["removed", "renamed", "multi", "prefix", "exempt-path", "exempt-method", "converter", "identity"])
def test_constructor_rejects_changed_contract(app, monkeypatch, defect):
    route = next(r for r in registry.browser_routes(app.routes) if getattr(r.endpoint, "__name__", "") == "runs")
    handler, path, methods = route.endpoint, route.path, ["GET"]
    if defect == "removed":
        monkeypatch.delitem(BROWSER, "runs")
    elif defect == "renamed":
        handler = copy.copy(endpoint)
    elif defect == "multi":
        methods = ["GET", "POST"]
    elif defect == "prefix":
        path = "/other"
    else:
        route = app.routes[-2] if defect == "converter" else next(r for r in app.routes if getattr(r, "path", "") == "/api/v1/health")
        handler, path = route.endpoint, route.path
        if defect == "exempt-path":
            path += "/renamed"
        elif defect == "exempt-method":
            methods = ["POST"]
        elif defect == "converter":
            path = "/api/{missing}"
            methods = list(route.methods or ())
        else:
            handler = endpoint
            monkeypatch.setattr(handler, "__name__", "health")
    with pytest.raises(ValueError):
        ContractRoute(path, handler, methods=methods)


@pytest.mark.parametrize("escape", ["include", "mount", "websocket", "route", "api", "subclass"])
def test_assembly_rejects_every_unsupported_top_level_type(app, escape):
    if escape == "include":
        router = APIRouter()
        router.add_api_route("/new", endpoint)
        app.include_router(router)
    elif escape == "mount":
        app.mount("/api/v1/sub", FastAPI())
    elif escape == "websocket":
        app.routes.append(WebSocketRoute("/socket", endpoint))
    elif escape == "route":
        app.routes.append(Route("/new", endpoint))
    elif escape == "api":
        app.routes.append(APIRoute("/api/v1/new", endpoint))
    else:
        class Unexpected(ContractRoute):
            pass

        route = registry.browser_routes(app.routes)[0]
        app.routes.append(Unexpected(route.path, route.endpoint, methods=list(route.methods or ())))
    with pytest.raises(ValueError, match="Unsupported route type|Unregistered asset mount"):
        registry.browser_routes(app.routes)


@pytest.mark.parametrize("defect", ["name", "path", "multi", "unwrapped", "fallback", "missing-browser", "missing-exempt", "unknown"])
def test_assembly_rechecks_bypasses(app, monkeypatch, defect):
    route = registry.browser_routes(app.routes)[0]
    if defect == "name":
        app.routes.insert(0, copy.copy(route))
    elif defect == "path":
        first, second = [r for r in registry.browser_routes(app.routes) if r.methods == {"GET"}][:2]
        first.path, second.path = "/api/v1/test/{one:path}", "/api/v1/test/{two:path}"
    elif defect == "multi":
        route.methods = {"GET", "POST"}
    elif defect == "unwrapped":
        route.dependant.call = route.endpoint
    elif defect == "fallback":
        app.routes[-1], app.routes[-2] = app.routes[-2], app.routes[-1]
    elif defect == "missing-browser":
        app.routes.remove(route)
    elif defect == "missing-exempt":
        app.routes.pop()
    else:
        monkeypatch.delitem(BROWSER, getattr(route.endpoint, "__name__", ""))
    with pytest.raises(ValueError):
        registry.browser_routes(app.routes)


@pytest.mark.parametrize("defect", ["duplicate", "overlap", "dangling", "machine", "request"])
def test_registry_itself_must_be_closed(app, monkeypatch, defect):
    if defect == "duplicate":
        monkeypatch.setattr(registry, "EXEMPTIONS", registry.EXEMPTIONS + (registry.EXEMPTIONS[0],))
    elif defect == "overlap":
        monkeypatch.setitem(BROWSER, "health", dict)
    elif defect == "dangling":
        item = replace(registry.EXEMPTIONS[0], path="/absent", handler="fixture.absent")
        monkeypatch.setattr(registry, "EXEMPTIONS", registry.EXEMPTIONS + (item,))
    else:
        monkeypatch.setitem(MACHINE if defect == "machine" else REQUESTS, "absent", dict)
    with pytest.raises(ValueError):
        registry.browser_routes(app.routes)


def test_normalization_preserves_converter(app):
    first, second = [r for r in registry.browser_routes(app.routes) if r.methods == {"GET"}][:2]
    first.path, second.path = "/api/v1/test/{one:path}", "/api/v1/test/{two}"
    assert registry.browser_routes(app.routes)


@pytest.mark.parametrize("defect", ["path", "name", "directory", "app", "duplicate", "html", "symlink"])
def test_asset_mount_is_exact(app, tmp_path, defect):
    existing = next(r for r in app.routes if type(r) is Mount)
    app.routes.remove(existing)
    route = copy.copy(existing)
    route.app = copy.copy(existing.app)
    if defect == "path":
        route.path = "/other"
    elif defect == "name":
        route.name = "other"
    elif defect == "directory":
        route.app = StaticFiles(directory=tmp_path)
    elif defect == "app":
        route.app = FastAPI()
    elif defect == "html":
        route.app.html = True
    elif defect == "symlink":
        route.app.follow_symlink = True
    if defect == "duplicate":
        app.routes.insert(0, copy.copy(route))
    app.routes.insert(0, route)
    with pytest.raises(ValueError):
        registry.browser_routes(app.routes)


def test_assets_can_be_absent(app):
    app.routes[:] = [r for r in app.routes if type(r) is not Mount]
    assert len(registry.browser_routes(app.routes)) == len(BROWSER)


def test_unknown_output_model_is_safe():
    with pytest.raises(ServiceError) as caught:
        validate_output("unregistered", {"secret": "never-return"})
    assert caught.value.status == 503


def test_export_independently_rejects_bypassed_create_app(app, monkeypatch):
    path = Path(__file__).parents[1] / "tools/browser_contract.py"
    spec = importlib.util.spec_from_file_location("export_escape", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app.routes.insert(0, APIRoute("/api/v1/escape", endpoint))
    monkeypatch.setattr(module, "create_app", lambda *a, **kw: app)
    with pytest.raises(ValueError, match="Unsupported route type"):
        module.schema()


def test_runtime_guard_survives_optimized_python(tmp_path):
    code = '''
from harbor_helper.service.contract_boundary import ContractRoute
try:
    ContractRoute('/api/v1/escape', lambda: {'secret': 'never-return'})
except ValueError:
    pass
else:
    raise RuntimeError('optimized Python bypassed constructor')
from harbor_helper.service.api import create_app
from harbor_helper.service.route_contracts import browser_routes
from starlette.routing import Route
from pathlib import Path
app = create_app(Path(__import__('sys').argv[1]) / 'state', start_scheduler=False)
app.routes.append(Route('/escape', lambda: None))
try:
    browser_routes(app.routes)
except ValueError:
    pass
else:
    raise RuntimeError('optimized Python bypassed assembly')
'''
    result = subprocess.run([sys.executable, "-O", "-c", code, str(tmp_path)], env=dict(os.environ), capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_create_app_runs_final_coverage_check(tmp_path, monkeypatch):
    from harbor_helper.service.http import spa

    original = spa.register

    def bypass(app):
        original(app)
        app.routes.append(APIRoute("/api/v1/escape", endpoint))

    monkeypatch.setattr(spa, "register", bypass)
    with pytest.raises(ValueError, match="Unsupported route type"):
        create_app(tmp_path / "state", start_scheduler=False)


def test_registered_name_cannot_be_borrowed(app):
    original = registry.browser_routes(app.routes)[0]
    borrowed = ContractRoute("/api/v1/borrowed", original.endpoint, methods=["GET"])
    app.routes.insert(0, borrowed)
    with pytest.raises(ValueError, match="Duplicate handler name"):
        registry.browser_routes(app.routes)
