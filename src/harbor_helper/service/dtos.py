"""Machine transport schemas; no runtime service dependencies."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from harbor_helper.persistence.statuses import AuditStatus, ReportStatus
from harbor_helper.service.attachment_contracts import AttachmentIdentity, AttachmentVersion

Operation = Literal["submit", "rerun", "retry", "recover"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AccessIssue(Input):
    name: str = Field(min_length=1, max_length=128)
    current_password: SecretStr
    scopes: list[Literal["read", "attachments", "execute", "cancel_own", "evidence"]] = ["read"]
    expires: float | None = None


class SubmissionInput(Input):
    dataset: str | None = None
    dataset_id: str | None = None
    model_profile: str | None = None
    agent: Literal["oracle", "opencode"] | None = None
    attachment_version_id: str | None = None
    attempts: int | None = Field(default=None, ge=1)
    concurrency: int | None = Field(default=None, ge=1)
    wall_seconds: int | None = Field(default=None, ge=1)
    environment_build_timeout_multiplier: int | None = Field(default=None, ge=1)
    task: str | None = None
    name: str | None = Field(default=None, max_length=128)


class EmptyInput(Input):
    pass


class RetryInput(Input):
    wall_seconds: int | None = Field(default=None, ge=1)


class Axis(BaseModel):
    state: str
    reason: str


class ResourceAxis(Axis):
    state: Literal["active", "released", "cleanup_blocked", "unknown"]  # ty: ignore[invalid-mutable-override]  # Pydantic response specialization; keep the strict wire schema.


class AuditAxis(Axis):
    state: AuditStatus  # ty: ignore[invalid-mutable-override]  # Pydantic response specialization; keep the strict wire schema.


class ReportAxis(Axis):
    state: ReportStatus  # ty: ignore[invalid-mutable-override]  # Pydantic response specialization; keep the strict wire schema.


class AttachmentBinding(BaseModel):
    attachment_id: str | None = None
    attachment_version_id: str | None = None
    bundle_id: str | None = None
    bundle_digest: str | None = None
    attachment_lineage: str | None = None


class MachineState(BaseModel):
    contract_version: Literal["1.0"] = "1.0"
    kind: Literal["submission", "run"]
    id: str
    status: str
    user_id: str | None = None
    access_credential_id: str | None = None
    run_id: str | None = None
    parent: str | None = None
    resource: ResourceAxis
    audit: AuditAxis
    report: ReportAxis
    poll_after_seconds: int | None = None
    report_url: str | None = None
    attachment: AttachmentBinding


class Accepted(BaseModel):
    operation_id: str | None = None
    idempotency_key: str | None = None
    id: str
    user_id: str | None = None
    access_credential_id: str | None = None
    submitter: str
    operation: str
    request: SubmissionInput | RetryInput
    run_id: str | None
    status: str
    created: float
    error: str | None
    parent: str | None
    attachment: AttachmentBinding
    diagnosis: dict | None = None
    retry_changes: dict = {}


class DatasetInfo(BaseModel):
    id: str
    name: str
    version: int
    enabled: bool
    status: str
    ready: bool
    checked: float | None = None


class ModelInfo(BaseModel):
    id: str
    version: int
    name: str | None = None
    model: str
    enabled: bool


class MaintenanceInfo(BaseModel):
    paused: bool
    reason: str
    retry_at: float | None
    updated: float | None


class Readiness(BaseModel):
    initialized: bool
    accepting: bool
    reason: str
    observed: float
    scheduler: "SchedulerInfo"
    maintenance: MaintenanceInfo
    pending: dict[str, int]


class SchedulerInfo(BaseModel):
    state: Literal["ready", "unavailable", "unknown"]
    reason: str
    observed: float
    activity_observed: float | None = None


class AttachmentEntry(AttachmentIdentity):
    versions: list[AttachmentVersion]


class Discovery(BaseModel):
    contract_version: Literal["1.0"]
    datasets: list[DatasetInfo]
    model_profiles: list[ModelInfo]
    attachments: list[AttachmentEntry]
    limits: dict[str, int]
    scheduler: SchedulerInfo
    readiness: Readiness
    allowed_operations: list[str]
    scopes: list[str]
    task_selection: dict
    schema_url: str
    cost: Literal["unknown"]
    limitations: list[str]


class TaskInfo(BaseModel):
    name: str
    package: str | None = None
    ref: str | None = None


class TaskCatalog(BaseModel):
    dataset_id: str
    version: int
    status: str
    offset: int
    tasks: list[TaskInfo]
    next_offset: int | None
    total: int


class AttemptReport(BaseModel):
    task: str
    trial: str | None = None
    valid: bool
    rewards: dict[str, float] | None = None
    failure: Literal["missing_score", "execution_failure", "unknown"] | None = None


class TaskReport(BaseModel):
    task: str
    expected_attempts: int
    valid_attempts: int
    observed_attempts: int
    mean_rewards: dict[str, float] | None
    attempts: list[AttemptReport]


class SafeReport(BaseModel):
    contract_version: Literal["1.0"] = "1.0"
    run_id: str
    status: str
    complete: bool
    expected_attempts: int
    valid_attempts: int
    invalid_attempts: int
    missing_attempts: int
    tasks: list[TaskReport]
    unexpected_trials: list[AttemptReport] = []


class CompareInput(Input):
    left: str
    right: str


class CancelResult(BaseModel):
    run_id: str
    cancel_requested: bool
    status: str


class ErrorResponse(BaseModel):
    operation_id: str | None = None
    code: str
    message: str
    request_id: str
    retryable: bool
    action: Literal[
        "retry_same_request",
        "poll_existing",
        "fix_input",
        "reauthorize",
        "contact_admin",
        "explicit_new_attempt",
    ]
    wait_seconds: int | None
    wait_known: bool
    poll_after_seconds: int | None
    related_ids: dict[str, str]


class AttachmentCatalog(BaseModel):
    attachments: list[AttachmentEntry]


class Updated(BaseModel):
    updated: bool


class MetricDelta(BaseModel):
    task: str
    left: dict[str, float]
    right: dict[str, float]
    delta: dict[str, float]


class CompareAttachment(BaseModel):
    kind: Literal["versioned", "none"]
    attachment_version_id: str | None
    bundle_id: str | None
    digest: str | None


class Changed(BaseModel):
    changed: Literal[True] = True


class Comparison(BaseModel):
    left: str
    right: str
    comparable: bool
    reasons: list[str]
    config_changes: dict[str, Changed]
    bundle_change: dict[str, str | None]
    attachment_inputs: dict[str, CompareAttachment]
    tasks: list[MetricDelta]
    mean_task_delta: dict[str, float] | None


class EvidenceGrant(Input):
    enabled: bool
