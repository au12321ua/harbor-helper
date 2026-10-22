"""Runs, trials, artifacts and Operations."""

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse

from maestro.api.deps import maestro, ok, principal
from maestro.api.models import (
    Artifact,
    Envelope,
    Operation,
    Run,
    RunAccepted,
    RunCreate,
    RunDetail,
    Trial,
)
from maestro.core.errors import MaestroError
from maestro.services.principal import Principal

router = APIRouter(prefix="/api/v1")


@router.post("/runs", response_model=Envelope[RunAccepted], status_code=202, tags=["runs"])
def submit(
    body: RunCreate,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    who: Principal = Depends(principal),
):
    service = maestro(request)
    if service.worker is None:
        raise MaestroError(
            "EXECUTION_UNAVAILABLE",
            "No executor is configured; runs cannot be accepted",
            503,
            stage="acceptance",
            retryable=True,
        )
    status, data, replayed = service.runs.submit(who, idempotency_key, body.model_dump())
    service.worker.wake()
    # A replay returns the original response; the header lets clients tell them apart.
    headers = {"Idempotent-Replayed": "true"} if replayed else {}
    return JSONResponse(status_code=status, content=ok(request, data), headers=headers)


@router.get("/runs", response_model=Envelope[list[Run]], tags=["runs"])
def list_runs(
    request: Request,
    owner_id: str | None = None,
    state: str | None = None,
    dataset_version_id: str | None = None,
    client_request_id: str | None = None,
    cursor: str | None = None,
    limit: int | None = None,
    who: Principal = Depends(principal),
):
    items, next_cursor = maestro(request).runs.list(
        who,
        owner_id=owner_id,
        state=state,
        dataset_version_id=dataset_version_id,
        client_request_id=client_request_id,
        cursor=cursor,
        limit=limit,
    )
    return ok(request, items, next_cursor)


@router.get("/runs/{run_id}", response_model=Envelope[RunDetail], tags=["runs"])
def get_run(run_id: str, request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).runs.get(who, run_id))


@router.get("/runs/{run_id}/trials", response_model=Envelope[list[Trial]], tags=["runs"])
def trials(run_id: str, request: Request, _: Principal = Depends(principal)):
    return ok(request, maestro(request).runs.trials(run_id))


@router.post("/runs/{run_id}/cancel", response_model=Envelope[Run], tags=["runs"])
def cancel(run_id: str, request: Request, who: Principal = Depends(principal)):
    service = maestro(request)
    result = service.runs.cancel(who, run_id)
    if service.worker:
        service.worker.wake()
    return ok(request, result)


@router.get("/runs/{run_id}/artifacts", response_model=Envelope[list[Artifact]], tags=["artifacts"])
def artifacts(
    run_id: str, request: Request, trial_id: str | None = None, _: Principal = Depends(principal)
):
    return ok(request, maestro(request).artifacts.for_run(run_id, trial_id))


@router.get(
    "/artifacts/{artifact_id}/download",
    tags=["artifacts"],
    responses={200: {"content": {"application/octet-stream": {}}}},
)
def download(artifact_id: str, request: Request, _: Principal = Depends(principal)):
    meta, data = maestro(request).artifacts.read(artifact_id)
    name = meta["relative_path"].rsplit("/", 1)[-1]
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-Digest": meta["digest"] or "",
        },
    )


@router.get("/operations/{operation_id}", response_model=Envelope[Operation], tags=["operations"])
def operation(operation_id: str, request: Request, _: Principal = Depends(principal)):
    return ok(request, maestro(request).operations.get(operation_id))


@router.get("/operations", response_model=Envelope[list[Operation]], tags=["operations"])
def operations(
    request: Request,
    kind: str | None = None,
    owner_id: str | None = None,
    cursor: str | None = None,
    limit: int | None = None,
    _: Principal = Depends(principal),
):
    items, next_cursor = maestro(request).operations.list(
        kind=kind, owner_id=owner_id, cursor=cursor, limit=limit
    )
    return ok(request, items, next_cursor)
