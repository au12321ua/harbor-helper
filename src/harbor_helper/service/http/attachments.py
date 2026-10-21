import json
from typing import Annotated

from fastapi import Depends, File, Form, Header, Request, UploadFile
from pydantic import ValidationError

from harbor_helper.service import dtos
from harbor_helper.service.attachment_contracts import (
    AttachmentCreate,
    AttachmentPublish,
    AttachmentResult,
    AttachmentUpdate,
    AttachmentVersionUpdate,
)
from harbor_helper.service.http.dependencies import token
from harbor_helper.service.primitives import ServiceError


def register(app, deps):
    actor = deps.actor

    @app.get("/api/v1/attachments", response_model=dtos.AttachmentCatalog)
    def attachments(user: Annotated[dict, Depends(actor)]):
        return deps.application.attachments.catalog()

    @app.get(
        "/api/v1/attachment-operations/{operation}/{key:path}", response_model=AttachmentResult
    )
    def attachment_lookup(operation: str, key: str, user: Annotated[dict, Depends(actor)]):
        return deps.application.attachments.lookup(user, operation, key)

    @app.get("/api/v1/attachment-versions/{version_id}/download")
    def attachment_download(
        request: Request, version_id: str, user: Annotated[dict, Depends(actor)]
    ):
        from urllib.parse import quote

        from fastapi.responses import StreamingResponse
        from starlette.background import BackgroundTask

        stream, size, sha, name = deps.application.attachments.download(
            user, version_id, access_value=token(request)
        )

        def chunks():
            try:
                while chunk := stream.read(65536):
                    yield chunk
            finally:
                stream.close()

        return StreamingResponse(
            chunks(),
            media_type="application/zip",
            headers={
                "Content-Length": str(size),
                "X-Content-SHA256": sha,
                "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name),
            },
            background=BackgroundTask(stream.close),
        )

    @app.post("/api/v1/attachments", status_code=201, response_model=AttachmentResult)
    def create_attachment(
        request: Request,
        file: Annotated[UploadFile, File()],
        user: Annotated[dict, Depends(actor)],
        metadata: Annotated[str, Form()] = "{}",
        idempotency_key: str | None = Header(default=None),
    ):
        return deps.application.attachments.write(
            user,
            "attachment_create",
            idempotency_key,
            attachment_metadata(metadata, AttachmentCreate),
            file.file,
            access_value=token(request),
        )

    @app.post(
        "/api/v1/attachments/{attachment_id}/versions",
        status_code=201,
        response_model=AttachmentResult,
    )
    def publish_attachment(
        request: Request,
        attachment_id: str,
        file: Annotated[UploadFile, File()],
        user: Annotated[dict, Depends(actor)],
        metadata: Annotated[str, Form()] = "{}",
        idempotency_key: str | None = Header(default=None),
    ):
        body = attachment_metadata(metadata, AttachmentPublish)
        if "attachment_id" in body:
            raise ServiceError("attachment_fields", "Target is supplied by path")
        return deps.application.attachments.write(
            user,
            "attachment_publish",
            idempotency_key,
            {**body, "attachment_id": attachment_id},
            file.file,
            access_value=token(request),
        )

    @app.post(
        "/api/v1/attachment-versions/{version_id}/derive",
        status_code=201,
        response_model=AttachmentResult,
    )
    def derive_attachment(
        request: Request,
        version_id: str,
        file: Annotated[UploadFile, File()],
        user: Annotated[dict, Depends(actor)],
        metadata: Annotated[str, Form()] = "{}",
        idempotency_key: str | None = Header(default=None),
    ):
        body = attachment_metadata(metadata, AttachmentCreate)
        if "source_version_id" in body:
            raise ServiceError("attachment_fields", "Source is supplied by path")
        return deps.application.attachments.write(
            user,
            "attachment_derive",
            idempotency_key,
            {**body, "source_version_id": version_id},
            file.file,
            access_value=token(request),
        )

    @app.patch("/api/v1/attachments/{attachment_id}", response_model=dtos.Updated)
    def update_attachment(
        request: Request,
        attachment_id: str,
        body: AttachmentUpdate,
        user: Annotated[dict, Depends(actor)],
    ):
        return deps.application.attachments.update(
            user, attachment_id, body.model_dump(exclude_unset=True), access_value=token(request)
        )

    @app.patch(
        "/api/v1/attachments/{attachment_id}/versions/{version_id}", response_model=dtos.Updated
    )
    def update_attachment_version(
        request: Request,
        attachment_id: str,
        version_id: str,
        body: AttachmentVersionUpdate,
        user: Annotated[dict, Depends(actor)],
    ):
        return deps.application.attachments.update(
            user, attachment_id, body.model_dump(), version_id, access_value=token(request)
        )

    def attachment_metadata(metadata, model):
        try:
            value = model.model_validate(json.loads(metadata)).model_dump()
        except (ValueError, ValidationError):
            raise ServiceError(
                "attachment_fields", "metadata must match the attachment operation"
            ) from None
        if not isinstance(value, dict):
            raise ServiceError("attachment_fields", "metadata must be a JSON object")
        return value
