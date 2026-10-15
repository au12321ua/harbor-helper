"""Typed v1 attachment HTTP payloads; shared business validation stays in Attachments."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AttachmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AttachmentCreate(AttachmentInput):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=4096)


class AttachmentPublish(AttachmentInput):
    notes: str = Field(default="", max_length=4096)


class AttachmentUpdate(AttachmentInput):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4096)
    enabled: bool | None = None


class AttachmentVersionUpdate(AttachmentInput):
    enabled: bool


class AttachmentIdentity(BaseModel):
    id: str
    name: str
    description: str
    creator_id: str
    creator: str
    created: float
    enabled: bool


class AttachmentVersion(BaseModel):
    id: str
    attachment_id: str
    number: int
    bundle_id: str
    digest: str
    publisher_id: str
    publisher: str
    created: float
    notes: str
    source_version_id: str | None
    enabled: bool
    availability: Literal["available", "unavailable"]


class AttachmentResult(BaseModel):
    attachment: AttachmentIdentity
    version: AttachmentVersion
