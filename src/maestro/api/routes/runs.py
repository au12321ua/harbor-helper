"""Runs, trials, result summaries, artifacts, exports and Operations."""

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from maestro.api.deps import maestro, ok, principal
from maestro.api.models import (
    Artifact,
    Envelope,
    Export,
    ExportCreate,
    Operation,
    RecycleEntry,
    Run,
    RunAccepted,
    RunCreate,
    RunDetail,
    RunSummary,
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
    accepted_after: str | None = None,
    accepted_before: str | None = None,
    cursor: str | None = None,
    limit: int | None = None,
    who: Principal = Depends(principal),
):
    """Newest first; deleted runs are hidden. Times are RFC 3339 UTC, ``after`` inclusive."""
    items, next_cursor = maestro(request).runs.list(
        who,
        owner_id=owner_id,
        state=state,
        dataset_version_id=dataset_version_id,
        client_request_id=client_request_id,
        accepted_after=accepted_after,
        accepted_before=accepted_before,
        cursor=cursor,
        limit=limit,
    )
    return ok(request, items, next_cursor)


@router.get("/runs/{run_id}", response_model=Envelope[RunDetail], tags=["runs"])
def get_run(run_id: str, request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).runs.get(who, run_id))


@router.get("/runs/{run_id}/summary", response_model=Envelope[RunSummary], tags=["runs"])
def summary(run_id: str, request: Request, _: Principal = Depends(principal)):
    """Counts, coverage and statistics; web pages and exports use the same computation."""
    return ok(request, maestro(request).runs.summary(run_id))


@router.delete("/runs/{run_id}", response_model=Envelope[RecycleEntry], tags=["runs"])
def delete_run(run_id: str, request: Request, who: Principal = Depends(principal)):
    """Moves a finished run to the recycle bin; queued or running runs are refused."""
    return ok(request, maestro(request).recycle.delete(who, "run", run_id))


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
def download(
    artifact_id: str,
    request: Request,
    offset: int = 0,
    length: int | None = None,
    _: Principal = Depends(principal),
):
    """Whole file, or a bounded slice with ``offset`` and ``length`` (at most 1 MiB) for
    paging logs. X-Total-Size reports the file size."""
    meta, reader, count, total = maestro(request).artifacts.open(artifact_id, offset, length)

    def chunks():
        with reader:
            left = count
            while left > 0:
                chunk = reader.read(min(left, 1 << 16))
                if not chunk:
                    return
                left -= len(chunk)
                yield chunk

    name = meta["relative_path"].rsplit("/", 1)[-1].replace('"', "")
    return StreamingResponse(
        chunks(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Content-Length": str(count),
            "X-Content-Digest": meta["digest"] or "",
            "X-Total-Size": str(total),
        },
    )


@router.delete(
    "/artifacts/{artifact_id}", response_model=Envelope[RecycleEntry], tags=["artifacts"]
)
def delete_artifact(artifact_id: str, request: Request, who: Principal = Depends(principal)):
    """Administrators only, e.g. for a confirmed leak. The file leaves the run's list;
    the recycle bin keeps the entry and, after a purge, the receipt."""
    return ok(request, maestro(request).recycle.delete(who, "artifact", artifact_id))


@router.post("/exports", response_model=Envelope[Export], status_code=202, tags=["exports"])
def create_export(body: ExportCreate, request: Request, who: Principal = Depends(principal)):
    """Accepted as an Operation; poll it or the export, then download within 24 hours."""
    service = maestro(request)
    export = service.exports.create(who, body.model_dump())
    service.maintenance.wake()
    return JSONResponse(status_code=202, content=ok(request, export))


@router.get("/exports", response_model=Envelope[list[Export]], tags=["exports"])
def list_exports(
    request: Request,
    cursor: str | None = None,
    limit: int | None = None,
    who: Principal = Depends(principal),
):
    items, next_cursor = maestro(request).exports.list(who, cursor, limit)
    return ok(request, items, next_cursor)


@router.get("/exports/{export_id}", response_model=Envelope[Export], tags=["exports"])
def get_export(export_id: str, request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).exports.get(who, export_id))


@router.get(
    "/exports/{export_id}/download",
    tags=["exports"],
    responses={200: {"content": {"application/zip": {}}}},
)
def download_export(export_id: str, request: Request, who: Principal = Depends(principal)):
    meta, path = maestro(request).exports.archive(who, export_id)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"export-{export_id}.zip",
        headers={"X-Content-Digest": meta["digest"] or ""},
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
