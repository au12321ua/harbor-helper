from typing import Annotated

from fastapi import Depends, Header

from harbor_helper.service import management_contracts as c
from harbor_helper.service.primitives import ServiceError


def register(app, deps):
    actor = deps.actor

    @app.get("/api/v1/management/requests")
    def managed_requests(user: Annotated[dict, Depends(actor)]):
        return deps.application.management.requests()

    @app.patch("/api/v1/management/groups/{group_id}")
    def rename_group(group_id: str, body: c.Rename, user: Annotated[dict, Depends(actor)]):
        return deps.application.management.rename(user, group_id, body.name)

    @app.get("/api/v1/management/datasets")
    def managed_datasets(user: Annotated[dict, Depends(actor)]):
        return deps.application.management.datasets()

    @app.get("/api/v1/management/datasets/{dataset_id}/versions")
    def dataset_versions(dataset_id: str, user: Annotated[dict, Depends(actor)]):
        return deps.application.management.versions(user, dataset_id)

    @app.post("/api/v1/management/datasets/{dataset_id}/preview")
    def dataset_preview(
        dataset_id: str, body: c.PreviewInput, user: Annotated[dict, Depends(actor)]
    ):
        return deps.application.management.preview(user, dataset_id, body.digest)

    @app.post("/api/v1/management/datasets/confirm")
    def dataset_confirm(body: c.ConfirmInput, user: Annotated[dict, Depends(actor)]):
        return deps.application.management.confirm(user, body.preview_id)

    @app.put("/api/v1/management/datasets/{dataset_id}/default")
    def dataset_default(
        dataset_id: str, body: c.DefaultInput, user: Annotated[dict, Depends(actor)]
    ):
        return deps.application.management.default(
            user, dataset_id, body.version_id, body.team_default
        )

    @app.post("/api/v1/management/dataset-merge/preview")
    def dataset_merge_preview(body: c.MergePreviewInput, user: Annotated[dict, Depends(actor)]):
        return deps.application.management.merge_preview(user, body.source, body.target)

    @app.post("/api/v1/management/dataset-merge")
    def dataset_merge(body: c.MergeInput, user: Annotated[dict, Depends(actor)]):
        return deps.application.management.merge(
            user,
            body.source,
            body.target,
            body.revision,
            {k: v.model_dump() for k, v in body.parameter_choices.items()},
        )

    @app.get("/api/v1/management/recycle")
    def recycle_list(user: Annotated[dict, Depends(actor)]):
        return deps.application.recycle.listing(user)

    @app.post("/api/v1/management/recycle/preview")
    def recycle_preview(body: c.Target, user: Annotated[dict, Depends(actor)]):
        with deps.store.connect() as db:
            object_id, owner, members = deps.application.recycle.members(
                db, body.kind, body.object_id
            )
            deps.application.recycle.allowed(user, owner, body.kind)
        return {"kind": body.kind, "object_id": object_id, "expected": [m[1] for m in members[1:]]}

    @app.post("/api/v1/management/recycle")
    def recycle_move(body: c.Batch, user: Annotated[dict, Depends(actor)]):
        results = []
        for item in body.items:
            result = {"kind": item.kind, "object_id": item.object_id, "event": None, "error": None}
            try:
                result["event"] = deps.application.recycle.move(
                    user, item.kind, item.object_id, item.expected
                )
            except ServiceError as error:
                result["error"] = {
                    "code": error.code,
                    "message": str(error),
                    "status": error.status,
                }
            results.append(result)
        return {"results": results}

    @app.post("/api/v1/management/recycle/{event_id}/restore")
    def recycle_restore(event_id: str, user: Annotated[dict, Depends(actor)]):
        return deps.application.recycle.restore(user, event_id)

    @app.post("/api/v1/management/recycle/{event_id}/purge")
    def recycle_purge(
        event_id: str,
        user: Annotated[dict, Depends(actor)],
        idempotency_key: str | None = Header(default=None),
    ):
        return deps.application.recycle.purge(user, event_id, idempotency_key)
