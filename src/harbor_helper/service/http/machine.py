from typing import Annotated

from fastapi import Depends

from harbor_helper.service import dtos, machine, policy
from harbor_helper.service.attachment_contracts import (
    AttachmentCreate,
    AttachmentPublish,
)
from harbor_helper.service.browser_contracts import OperationHistory
from harbor_helper.service.dtos import MachineState
from harbor_helper.service.primitives import ServiceError


def register(app, deps):
    actor = deps.actor

    @app.get("/api/v1/operations", response_model=OperationHistory)
    def operation_history(
        user: Annotated[dict, Depends(actor)],
        offset: int = 0,
        limit: int = 50,
        mine: bool = False,
        operation: str | None = None,
        key: str | None = None,
        operation_id: str | None = None,
        user_id: str | None = None,
        status: str | None = None,
        created_from: float | None = None,
        created_to: float | None = None,
    ):
        from harbor_helper.service.history import listing

        return listing(
            deps.store,
            user,
            offset=offset,
            limit=limit,
            mine=mine,
            operation=operation,
            key=key,
            operation_id=operation_id,
            user_id=user_id,
            status=status,
            created_from=created_from,
            created_to=created_to,
        )

    @app.get("/api/v1/machine/discovery", response_model=dtos.Discovery)
    def discovery(user: Annotated[dict, Depends(actor)]):
        return machine.discovery(deps.application, user)

    @app.get("/api/v1/machine/datasets/{dataset_id}/tasks", response_model=dtos.TaskCatalog)
    def task_catalog(
        dataset_id: str, user: Annotated[dict, Depends(actor)], offset: int = 0, limit: int = 100
    ):
        if offset < 0 or not 1 <= limit <= 100:
            raise ServiceError("invalid_range", "offset >= 0; limit 1–100 required")
        value = deps.data.object("dataset", dataset_id)
        tasks = value.get("tasks", [])
        # Use the verified metadata catalog; no task materialization or Hub download.
        return {
            "dataset_id": dataset_id,
            "version": value["version"],
            "status": value.get("status", "unknown"),
            "offset": offset,
            "tasks": [
                {k: t.get(k) for k in ("name", "package", "ref")}
                for t in tasks[offset : offset + limit]
            ],
            "next_offset": offset + limit if offset + limit < len(tasks) else None,
            "total": len(tasks),
        }

    @app.get(
        "/api/v1/submission-operations/{operation}/{key:path}",
        response_model=dtos.Accepted,
        response_model_exclude_unset=True,
    )
    def lookup_submission(
        operation: dtos.Operation, key: str, user: Annotated[dict, Depends(actor)]
    ):
        return machine.accepted_view(user, machine.lookup(deps.application, user, operation, key))

    @app.get("/api/v1/machine/submissions/{submission_id}", response_model=MachineState)
    def machine_submission(submission_id: str, user: Annotated[dict, Depends(actor)]):
        return machine.submission_state(deps.application, submission_id)

    @app.get("/api/v1/machine/runs/{run_id}", response_model=MachineState)
    def machine_run(run_id: str, user: Annotated[dict, Depends(actor)]):
        return machine.run_state(deps.application, run_id)

    @app.get("/api/v1/machine/runs/{run_id}/report", response_model=dtos.SafeReport)
    def machine_report(run_id: str, user: Annotated[dict, Depends(actor)]):
        state = machine.run_state(deps.application, run_id)
        if state["report"]["state"] != "available":
            raise ServiceError("report_" + state["report"]["state"], state["report"]["reason"], 409)
        return machine.report_view(deps.application.safe_report(run_id))

    @app.get("/api/v1/machine/schema")
    def machine_schema(user: Annotated[dict, Depends(actor)]):
        from fastapi.openapi.utils import get_openapi

        routes = [
            r
            for r in app.routes
            if getattr(r, "endpoint", None) and r.endpoint.__name__ in policy.SCHEMA_OPERATIONS
        ]
        schema = get_openapi(title="Harbor Helper member machine API", version="1.0", routes=routes)
        for model in (
            AttachmentCreate,
            AttachmentPublish,
            dtos.ErrorResponse,
        ):
            typed = model.model_json_schema(ref_template="#/components/schemas/{model}")
            definitions = typed.pop("$defs", {})
            schema.setdefault("components", {}).setdefault("schemas", {}).update(definitions)
            schema["components"]["schemas"][model.__name__] = typed
        embedded = {
            "create_attachment": "AttachmentCreate",
            "derive_attachment": "AttachmentCreate",
            "publish_attachment": "AttachmentPublish",
        }
        for route in routes:
            for method in route.methods:
                op = schema.get("paths", {}).get(route.path_format, {}).get(method.lower())
                if op is not None:
                    op["x-capability"] = policy.CAPABILITIES[route.endpoint.__name__]
                    op["security"] = [{"MemberBearer": []}]
                    op["x-operation"] = route.endpoint.__name__
                    if route.endpoint.__name__ in embedded:
                        op["x-metadata-schema"] = {
                            "$ref": "#/components/schemas/" + embedded[route.endpoint.__name__]
                        }
                    for status in ("401", "403", "404", "409", "422", "429", "503"):
                        op["responses"][status] = {
                            "description": "Safe machine error",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                                }
                            },
                        }
        schema.setdefault("components", {})["securitySchemes"] = {
            "MemberBearer": {"type": "http", "scheme": "bearer"}
        }
        return schema
