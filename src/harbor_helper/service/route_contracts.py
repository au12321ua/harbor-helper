"""Exhaustive, shared classification of the flat HTTP application.

Handler names also key authorization and audit; they must be globally unique.
Special routes are exceptions by exact identity, never by URL prefix.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from fastapi.routing import APIRoute
from starlette.routing import BaseRoute, Mount
from starlette.staticfiles import StaticFiles

from harbor_helper.service.browser_contracts import BROWSER, MACHINE, REQUESTS


@dataclass(frozen=True)
class Exemption:
    path: str
    methods: frozenset[str]
    handler: str
    reason: str


def exception(path: str, handler: str, reason: str, methods: str = "GET") -> Exemption:
    return Exemption(
        path, frozenset(methods.split()), "harbor_helper.service.http." + handler, reason
    )


EXEMPTIONS = (
    exception(
        "/api/v1/build", "updates.register.<locals>.build_identity", "Minimal cache identity"
    ),
    exception(
        "/api/v1/upgrade-phase", "updates.register.<locals>.upgrade_phase", "Minimal upgrade status"
    ),
    exception(
        "/api/v1/runs/{run_id}/evidence/package",
        "experiments.register.<locals>.evidence_package",
        "Verified snapshot streaming",
    ),
    exception(
        "/api/v1/runs/{run_id}/evidence/files/{file_id}",
        "experiments.register.<locals>.evidence_file",
        "Verified snapshot streaming",
    ),
    exception("/api/v1/health", "status.register.<locals>.health", "Health probe"),
    exception(
        "/api/v1/machine/discovery", "machine.register.<locals>.discovery", "Machine discovery"
    ),
    exception(
        "/api/v1/machine/datasets/{dataset_id}/tasks",
        "machine.register.<locals>.task_catalog",
        "Machine pagination",
    ),
    exception(
        "/api/v1/machine/submissions/{submission_id}",
        "machine.register.<locals>.machine_submission",
        "Machine projection",
    ),
    exception(
        "/api/v1/machine/runs/{run_id}",
        "machine.register.<locals>.machine_run",
        "Machine projection",
    ),
    exception(
        "/api/v1/machine/runs/{run_id}/report",
        "machine.register.<locals>.machine_report",
        "Machine projection",
    ),
    exception(
        "/api/v1/machine/schema", "machine.register.<locals>.machine_schema", "Machine schema"
    ),
    exception(
        "/api/v1/machine/compare",
        "experiments.register.<locals>.machine_compare",
        "Machine projection",
        "POST",
    ),
    exception(
        "/api/v1/runs/{run_id}/artifacts/{file_id}",
        "experiments.register.<locals>.artifact",
        "Binary navigation",
    ),
    exception("/favicon.svg", "spa.register.<locals>.favicon", "Static file"),
    exception(
        "/api/{missing:path}",
        "spa.register.<locals>.missing_api",
        "API 404 fallback",
        "DELETE GET HEAD OPTIONS PATCH POST PUT",
    ),
    exception("/{path:path}", "spa.register.<locals>.spa", "Page fallback"),
)


def classify_http(route: APIRoute) -> str:
    """Construction-time classification, also rechecked after assembly."""
    endpoint = route.endpoint
    name = getattr(endpoint, "__name__", None)
    if not isinstance(name, str) or not route.methods:
        raise ValueError("Missing HTTP handler name/methods")
    identity = endpoint.__module__ + "." + getattr(endpoint, "__qualname__", "")
    matches = [
        item
        for item in EXEMPTIONS
        if (route.path, frozenset(route.methods), identity)
        == (item.path, item.methods, item.handler)
    ]
    if len(matches) > 1 or (matches and name in BROWSER):
        raise ValueError(f"Overlapping route classification: {name}")
    if matches:
        return "exempt"
    if name not in BROWSER:
        raise ValueError(f"Unregistered HTTP route: {name} {route.path}")
    if not route.path.startswith("/api/v1/") or len(route.methods) != 1:
        raise ValueError(f"Invalid browser path/methods: {name}")
    # A special handler cannot borrow a browser registration after an exemption changes.
    if any(item.handler == identity for item in EXEMPTIONS):
        raise ValueError(f"Changed exempt HTTP route: {name}")
    return "browser"


def browser_routes(routes: list[BaseRoute]) -> list[APIRoute]:
    """Validate every actual top-level item and return the complete browser set.

    Only the optional packaged assets mount may lack an HTTP contract. Parameter
    normalization preserves converters; it is not general path-overlap solving.
    """
    from harbor_helper.service.contract_boundary import ContractRoute

    if not set(MACHINE) <= set(BROWSER) or not set(REQUESTS) <= set(BROWSER):
        raise ValueError("Dangling machine/request browser registration")
    if len(set(EXEMPTIONS)) != len(EXEMPTIONS) or any(not e.reason for e in EXEMPTIONS):
        raise ValueError("Duplicate or unexplained exemption")
    exemption_names = [e.handler.rsplit(".", 1)[-1] for e in EXEMPTIONS]
    if len(set(exemption_names)) != len(exemption_names) or set(exemption_names) & set(BROWSER):
        raise ValueError("Overlapping exemption names")
    names: set[str] = set()
    keys: set[tuple[frozenset[str], str]] = set()
    seen_exemptions: set[str] = set()
    result = []
    assets = 0
    for route in routes:
        if type(route) is Mount:
            expected = Path(__file__).resolve().parents[1] / "static/assets"
            if (
                route.path != "/assets"
                or route.name != "assets"
                or type(route.app) is not StaticFiles
                or route.app.directory is None
                or Path(route.app.directory).resolve() != expected.resolve()
                or route.app.all_directories != [route.app.directory]
                or route.app.html
                or route.app.follow_symlink
            ):
                raise ValueError("Unregistered asset mount")
            assets += 1
            if assets > 1:
                raise ValueError("Duplicate asset mount")
            continue
        if type(route) is not ContractRoute:
            raise ValueError(f"Unsupported route type: {type(route).__name__}")
        name = getattr(route.endpoint, "__name__", "")
        if name in names:
            raise ValueError(f"Duplicate handler name: {name}")
        names.add(name)
        normalized = re.sub(r"\{[^}:]+(:[^}]+)?\}", r"{\1}", route.path)
        key = (frozenset(route.methods or ()), normalized)
        if key in keys:
            raise ValueError(f"Duplicate normalized route: {route.path}")
        keys.add(key)
        if classify_http(route) == "browser":
            if getattr(route.dependant.call, "__wrapped__", None) is not route.endpoint:
                raise ValueError(f"Missing raw output boundary: {name}")
            result.append(route)
        else:
            seen_exemptions.add(name)
    if {getattr(r.endpoint, "__name__", "") for r in result} != set(BROWSER):
        raise ValueError("Dangling browser registration")
    if seen_exemptions != set(exemption_names):
        raise ValueError("Dangling HTTP exemption")
    if [getattr(r, "path", None) for r in routes[-2:]] != ["/api/{missing:path}", "/{path:path}"]:
        raise ValueError("API/page fallbacks must be last")
    return result
