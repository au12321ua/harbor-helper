"""Team-readable dataset catalog. Imports and first preparation arrive with M4."""

from fastapi import APIRouter, Depends, Request

from maestro.api.deps import maestro, ok, principal
from maestro.api.models import Dataset, DatasetVersionDetail, Envelope, Task
from maestro.services.principal import Principal

router = APIRouter(prefix="/api/v1", tags=["catalog"])


@router.get("/datasets", response_model=Envelope[list[Dataset]])
def datasets(
    request: Request,
    cursor: str | None = None,
    limit: int | None = None,
    _: Principal = Depends(principal),
):
    items, next_cursor = maestro(request).catalog.list_datasets(cursor, limit)
    return ok(request, items, next_cursor)


@router.get("/dataset-versions/{version_id}", response_model=Envelope[DatasetVersionDetail])
def version(version_id: str, request: Request, _: Principal = Depends(principal)):
    return ok(request, maestro(request).catalog.get_version(version_id))


@router.get("/dataset-versions/{version_id}/tasks", response_model=Envelope[list[Task]])
def tasks(version_id: str, request: Request, _: Principal = Depends(principal)):
    return ok(request, maestro(request).catalog.list_tasks(version_id))
