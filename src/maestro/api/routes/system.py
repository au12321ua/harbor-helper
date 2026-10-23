"""Health, readiness and capability discovery (10 section 3)."""

from fastapi import APIRouter, Depends, Request

from maestro import __version__
from maestro.api.deps import maestro, ok, principal
from maestro.api.models import Capabilities, Envelope, Health
from maestro.domain import limits
from maestro.execution.policy import POLICY_VERSION
from maestro.services.principal import Principal
from maestro.services.runs import EXECUTION_MODES

router = APIRouter()


def readiness(request: Request) -> dict:
    service = maestro(request)
    schema = service.schema_state()
    keys = service.keys.status()
    worker_task = getattr(request.app.state, "worker_task", None)
    executing = worker_task is not None and not worker_task.done()
    ready = schema["compatible"]
    storage = service.disk.status()
    return {
        "status": "ready" if ready else "maintenance",
        "accepting_runs": bool(
            ready and keys["available"] and executing and storage["level"] == "ok"
        ),
        "detail": {
            "storage": storage,
            "schema": schema,
            "master_key_available": keys["available"],
            "executor": service.executor.executor_id if service.executor else None,
            "worker_running": executing,
            "needs_setup": service.accounts.needs_setup() if ready else None,
        },
    }


@router.get("/health/live", response_model=Health, tags=["system"])
def live():
    return {"status": "alive"}


@router.get("/health/ready", response_model=Health, tags=["system"])
def ready(request: Request):
    state = readiness(request)
    # No sensitive details here; the authenticated system-status carries them.
    return {"status": state["status"], "accepting_runs": state["accepting_runs"]}


@router.get("/api/v1/system-status", response_model=Envelope[Health], tags=["system"])
def system_status(request: Request, _: Principal = Depends(principal)):
    return ok(request, readiness(request))


@router.get("/api/v1/capabilities", response_model=Envelope[Capabilities], tags=["system"])
def capabilities(request: Request):
    service = maestro(request)
    experiment = {"web_session": True, "pat_scopes": ["experiment"]}
    read = {"web_session": True, "pat_scopes": ["read", "experiment"]}
    admin = {"web_session": True, "pat_scopes": [], "role": "admin"}
    return ok(
        request,
        {
            "api_version": "v1",
            "service_version": __version__,
            "schema_revision": service.schema_state()["head"],
            "features": {
                "runs": True,
                "execution": service.executor is not None,
                "batches": False,
                "configuration_resolution": False,
                "plans": False,
                "attachments": False,
                "exports": True,
                "deletion": True,
                "collections": False,
                "dataset_import": True,
            },
            "limits": {**limits.as_dict(), **service.settings.effective_limits()},
            "auth": {
                "pat_header": "Authorization: Bearer <token>",
                "session_cookie": True,
                "csrf_header": "X-CSRF-Token",
            },
            "actions": {
                "runs.read": read,
                "runs.submit": experiment,
                "runs.cancel_own": experiment,
                "runs.cancel_any": admin,
                "runs.delete_own": experiment,
                "runs.delete_any": admin,
                "exports.create": read,
                "artifacts.delete": admin,
                "admin.recycle_bin": admin,
                "catalog.read": read,
                "catalog.search_source": admin,
                "datasets.import": admin,
                "operations.read": read,
                "pats.manage_own": {"web_session": True, "pat_scopes": []},
                "admin.members": admin,
                "admin.credentials": admin,
                "admin.master_key": admin,
                "admin.audit": admin,
                "admin.capacity": admin,
            },
            "execution": {
                "executor": service.executor.executor_id if service.executor else None,
                "modes": sorted(EXECUTION_MODES),
                "policy_version": POLICY_VERSION,
                "capacity": service.capacity.host.public(),
            },
        },
    )
