import json
from typing import Annotated

from fastapi import Depends, Request

from harbor_helper.service import dtos
from harbor_helper.service.http.dependencies import token
from harbor_helper.service.primitives import ServiceError


def register(app, deps):
    actor = deps.actor
    administrator = deps.administrator

    @app.get("/api/v1/health")
    def health():
        from harbor_helper.service.admission import readiness as observe

        try:
            ready = deps.application is not None and observe(deps.application)["accepting"]
        except (ValueError, OSError, TypeError):
            ready = False
        return {"alive": True, "ready": ready}

    @app.get("/api/v1/readiness", response_model=dtos.Readiness)
    def readiness(user: Annotated[dict, Depends(actor)]):
        from harbor_helper.service.admission import readiness as observe

        return observe(deps.application, user["id"])

    @app.patch("/api/v1/admin/maintenance")
    def set_maintenance(
        request: Request, body: dict, user: Annotated[dict, Depends(administrator)]
    ):
        from harbor_helper.service.admission import set_maintenance as update

        if token(request) in json.dumps(body):
            raise ServiceError("maintenance_reason", "Notice must not contain credentials")
        with deps.application.store.control():
            result = update(deps.data, body)
            deps.data.event(user, "set_maintenance", "admission")
            return result

    @app.get("/api/v1/admin/shutdown")
    def shutdown_status(user: Annotated[dict, Depends(administrator)]):
        from harbor_helper.service.shutdown import observe

        return observe(deps.data)

    @app.post("/api/v1/admin/shutdown")
    def shutdown_request(body: dtos.ShutdownInput, user: Annotated[dict, Depends(administrator)]):
        from harbor_helper.service.shutdown import request

        return request(deps.data, body.mode, user)
