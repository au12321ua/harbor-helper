"""Attachment versions: members and experiment PATs publish, everyone reads (03 section 6).

The package is the request body itself (a tar, tar.gz or zip archive), so the web page
and the SDK send the same bytes without a form encoding.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from maestro.api.deps import maestro, ok, principal
from maestro.api.models import Attachment, EnabledChange, Envelope, RecycleEntry
from maestro.core.errors import MaestroError
from maestro.domain import limits
from maestro.services.principal import Principal

router = APIRouter(prefix="/api/v1", tags=["attachments"])

ARCHIVE_TYPES = ("application/gzip", "application/x-tar", "application/zip")


@router.get("/attachments", response_model=Envelope[list[Attachment]])
def list_attachments(
    request: Request,
    name: str | None = None,
    include_disabled: bool = True,
    who: Principal = Depends(principal),
):
    return ok(request, maestro(request).attachments.list(who, name, include_disabled))


@router.get("/attachments/{attachment_id}", response_model=Envelope[Attachment])
def get_attachment(attachment_id: str, request: Request, who: Principal = Depends(principal)):
    """With the file list."""
    return ok(request, maestro(request).attachments.get(who, attachment_id))


@router.post(
    "/attachments",
    response_model=Envelope[Attachment],
    status_code=201,
    responses={200: {"description": "This name, version and content were already published"}},
    openapi_extra={
        "requestBody": {
            "required": True,
            "description": "The package archive with manifest.json at its root",
            "content": {
                kind: {"schema": {"type": "string", "format": "binary"}} for kind in ARCHIVE_TYPES
            },
        }
    },
)
async def publish_attachment(request: Request, who: Principal = Depends(principal)):
    limit = limits.ATTACHMENT_UPLOAD_MAX_BYTES
    too_large = MaestroError("ATTACHMENT_TOO_LARGE", f"Packages are at most {limit} bytes", 413)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise too_large
    service = maestro(request).attachments
    # Spooled to disk on the store's file system: a package may be hundreds of MiB.
    with service.store.receive() as spool:
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise too_large
            spool.write(chunk)
        if size == 0:
            raise MaestroError("ATTACHMENT_INVALID", "The request body holds no package", 422)
        spool.flush()
        data, created = await run_in_threadpool(service.publish, who, Path(spool.name))
    return JSONResponse(status_code=201 if created else 200, content=ok(request, data))


@router.post("/attachments/{attachment_id}/enabled", response_model=Envelope[Attachment])
def attachment_enabled(
    attachment_id: str, body: EnabledChange, request: Request, who: Principal = Depends(principal)
):
    """The owner or an administrator; disabled versions cannot be chosen for new runs."""
    return ok(request, maestro(request).attachments.set_enabled(who, attachment_id, body.enabled))


@router.delete("/attachments/{attachment_id}", response_model=Envelope[RecycleEntry])
def delete_attachment(attachment_id: str, request: Request, who: Principal = Depends(principal)):
    """Into the recycle bin; the owner or an administrator."""
    return ok(request, maestro(request).recycle.delete(who, "attachment_version", attachment_id))
