from typing import Annotated

from fastapi import Depends, Request

from harbor_helper.service import access
from harbor_helper.service.dtos import AccessIssue
from harbor_helper.service.http.dependencies import token


def register(app, deps):
    actor = deps.actor
    administrator = deps.administrator

    @app.post("/api/v1/access-credentials", status_code=201)
    def issue_access(request: Request, body: AccessIssue, user: Annotated[dict, Depends(actor)]):
        return access.issue(
            deps.data,
            user,
            body.name,
            body.current_password.get_secret_value(),
            body.scopes,
            body.expires,
            access_value=token(request),
        )

    @app.get("/api/v1/access-credentials")
    def list_access(user: Annotated[dict, Depends(actor)]):
        return access.listing(deps.data, user)

    @app.get("/api/v1/admin/access-credentials")
    def list_all_access(user: Annotated[dict, Depends(administrator)]):
        return access.listing(deps.data, user, all_users=True)

    @app.post("/api/v1/access-credentials/{credential_id}/revoke")
    def revoke_access(credential_id: str, user: Annotated[dict, Depends(actor)]):
        return access.revoke(deps.data, user, credential_id)
