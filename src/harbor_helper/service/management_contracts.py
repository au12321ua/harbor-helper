"""Typed management operations shared by browser and automation clients."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Rename(Input):
    name: str = Field(max_length=128)


class Renamed(BaseModel):
    id: str
    name: str


class RequestEntry(BaseModel):
    id: str
    group_id: str
    number: int
    source_id: str | None
    relation: str
    name: str
    creator_id: str
    user_id: str
    submitter: str
    status: str
    run_id: str | None
    created: float
    display_name: str


class Requests(BaseModel):
    requests: list[RequestEntry]


class SourceVersion(BaseModel):
    id: str
    number: int
    resolved: str
    created: float
    tasks: list[dict[str, str]]
    parameters: dict[str, JsonValue]


class DatasetEntry(BaseModel):
    id: str
    source: str
    name: str
    default_version: str | None
    auto_named: int
    versions: list[SourceVersion]
    needs_merge: bool


class Datasets(BaseModel):
    datasets: list[DatasetEntry]


class RemoteVersion(BaseModel):
    revision: int
    digest: str
    tags: list[str]
    published: str


class RemoteVersions(BaseModel):
    package: str
    versions: list[RemoteVersion]
    truncated: bool
    possibly_incomplete: bool
    limit: int


class PreviewInput(Input):
    digest: str


class Preview(BaseModel):
    id: str
    dataset_id: str
    resolved: str
    tasks: list[dict[str, str]]
    listed: bool


class ConfirmInput(Input):
    preview_id: str


class Confirmed(BaseModel):
    confirmed: bool
    resolved: str


class DefaultInput(Input):
    version_id: str
    team_default: bool = False


class MergePreviewInput(Input):
    source: str
    target: str


class ParameterChoice(Input):
    id: str
    version: int


class MergeInput(MergePreviewInput):
    revision: str
    parameter_choices: dict[str, ParameterChoice] = {}


class MergePreview(BaseModel):
    source: str
    target: str
    revision: str
    versions: list[dict[str, str]]
    parameters: list[dict[str, str | int]]


class Merged(BaseModel):
    merged: bool
    target: str


Kind = Literal[
    "request", "dataset", "dataset_version", "attachment", "attachment_version", "artifact"
]


class Target(Input):
    kind: Kind
    object_id: str
    expected: list[str] | None = None


class Batch(Input):
    items: list[Target] = Field(min_length=1, max_length=100)


class RecycleEvent(BaseModel):
    id: str
    kind: str
    object_id: str
    owner_id: str
    actor_id: str
    created: float
    state: str
    cleanup: str | None
    count: int


class RecycleList(BaseModel):
    items: list[RecycleEvent]


class BatchEntry(BaseModel):
    kind: str
    object_id: str
    event: RecycleEvent | None
    error: dict[str, str | int] | None


class BatchResult(BaseModel):
    results: list[BatchEntry]


class RecyclePreview(BaseModel):
    kind: Kind
    object_id: str
    expected: list[str]


class Tombstone(BaseModel):
    id: str
    deleted: Literal[True]
    status: Literal["purged"]
    operation_id: str | None = None
    idempotency_key: str | None = None
