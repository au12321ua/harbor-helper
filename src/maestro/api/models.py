"""Public API models. They define the OpenAPI contract shared by web and SDK."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Meta(Model):
    request_id: str
    next_cursor: str | None = None


class Envelope[T](Model):
    data: T
    meta: Meta


class FieldErrorModel(Model):
    path: str
    code: str
    message: str | None = None
    limit: int | float | None = None


class ErrorBody(Model):
    code: str
    message: str
    stage: str | None = None
    field_errors: list[FieldErrorModel] = []
    retryable: bool = False
    suggested_actions: list[dict[str, Any]] = []


class ErrorResponse(Model):
    error: ErrorBody
    meta: Meta


# --- identity -----------------------------------------------------------------

Role = Literal["admin", "member"]
Scope = Literal["read", "experiment"]


class User(Model):
    id: str
    username: str
    display_name: str
    role: Role
    status: Literal["active", "disabled"]
    revision: int
    created_at: str
    disabled_at: str | None


class Me(User):
    auth_channel: Literal["web_session", "pat"]
    pat_id: str | None
    pat_scope: Scope | None


class SessionInfo(Model):
    user: Me
    csrf_token: str | None = Field(
        description="Send as X-CSRF-Token on unsafe requests authenticated by the cookie"
    )


class SetupStatus(Model):
    needs_setup: bool


class SetupRequest(Model):
    setup_token: str
    username: str
    display_name: str | None = None
    password: str


class LoginRequest(Model):
    username: str
    password: str


class PasswordChange(Model):
    current_password: str
    new_password: str


class InvitationCreate(Model):
    role: Role = "member"
    note: str = ""
    valid_hours: int | None = None


class Invitation(Model):
    id: str
    role: Role
    note: str
    kind: Literal["invitation", "password_reset"]
    target_user_id: str | None
    state: Literal["pending", "used", "revoked", "expired"]
    created_by: str
    created_at: str
    expires_at: str
    used_at: str | None
    used_by: str | None


class IssuedInvitation(Invitation):
    token: str = Field(description="Shown once")


class InvitationLookup(Model):
    token: str


class InvitationInfo(Model):
    kind: Literal["invitation", "password_reset"]
    role: Role
    username: str | None
    expires_at: str


class InvitationAccept(Model):
    token: str
    username: str | None = None
    display_name: str | None = None
    password: str


class StatusChange(Model):
    expected_revision: int


class PatCreate(Model):
    name: str
    scope: Scope
    expires_in_days: int | None = None
    run_limit: int | None = None


class Pat(Model):
    id: str
    name: str
    scope: Scope
    token_prefix: str
    state: Literal["active", "revoked", "expired"]
    expires_at: str
    run_limit: int
    accepted_runs: int
    remaining_runs: int
    created_at: str
    last_used_at: str | None
    revoked_at: str | None
    revision: int


class IssuedPat(Pat):
    token: str = Field(description="Shown once; store it securely")


# --- credentials ----------------------------------------------------------------

CredentialKind = Literal["model_api_key", "hub_token", "generic_secret"]


class CredentialCreate(Model):
    name: str
    kind: CredentialKind
    provider: str
    description: str = ""
    value: str


class CredentialValue(Model):
    value: str
    expected_revision: int


class Credential(Model):
    id: str
    name: str
    kind: CredentialKind
    provider: str
    description: str
    enabled: bool
    revision: int
    key_version: int
    created_by: str
    created_at: str
    updated_at: str


class MasterKeyStatus(Model):
    initialized: bool
    available: bool
    generation: int | None
    rotated_at: str | None
    reencrypted_credentials: int | None = None


class MasterKeyRotation(Model):
    expected_generation: int


# --- catalog ------------------------------------------------------------------------


class DatasetVersion(Model):
    id: str
    dataset_id: str
    upstream_ref: str
    ref_kind: str
    resolved_digest: str
    status: Literal["ready"]
    created_at: str


class DeletionState(Model):
    state: Literal["recycled", "purged"] = Field(
        description="recycled: in the recycle bin; purged: content gone, receipt kept"
    )
    deleted_at: str
    purged_at: str | None


class DatasetVersionDetail(DatasetVersion):
    deletion: DeletionState | None = Field(
        description="Set when the version or its dataset was deleted; it still resolves"
    )
    task_count: int
    admitted_task_count: int
    submittable_task_count: int


class Dataset(Model):
    id: str
    source_kind: str
    namespace: str
    name: str
    description: str
    versions: list[DatasetVersion]


class TaskAdmission(Model):
    id: str
    state: Literal["pending", "admitted", "first_failed", "revoked"]
    revision: int


class TaskContent(Model):
    digest: str
    availability: Literal["unknown", "available", "unavailable"]
    checked_at: str | None


class TaskBlocker(Model):
    code: Literal["TASK_NOT_ADMITTED", "TASK_ADMISSION_REVOKED", "RESOURCE_CONTENT_UNAVAILABLE"]
    admission_state: str | None = None
    resource_kind: str | None = None
    expected_digest: str | None = None


class Task(Model):
    id: str
    task_key: str
    admission: TaskAdmission | None
    content: TaskContent
    can_submit: bool
    blockers: list[TaskBlocker]


# --- runs and operations -------------------------------------------------------------


class TaskSelection(Model):
    mode: Literal["all_eligible", "explicit"] = "all_eligible"
    task_ids: list[str] | None = None


class RunCreate(Model):
    """M2 direct configuration; M5 replaces it with a configuration resolution."""

    name: str
    dataset_version_id: str
    task_selection: TaskSelection = TaskSelection()
    repetitions: int = 1
    concurrency: int = 4
    execution_mode: Literal["oracle"] = Field(
        "oracle",
        description="Until model configuration exists only the Oracle test mode runs: each "
        "task's reference solution, never compared with model results",
    )
    client_request_id: str | None = None


class RunAccepted(Model):
    run_id: str
    operation_id: str
    state: str
    config_digest: str
    snapshot_digest: str
    planned_trials: int
    links: dict[str, str]


class RunCounts(Model):
    planned: int
    terminal: int
    scored: int
    errors: int
    not_started: int
    cancelled: int
    interrupted: int
    active: int
    queued: int


RunStateName = Literal[
    "queued", "preparing", "running", "finalizing", "finished", "cancelled", "interrupted"
]


class Owner(Model):
    username: str
    display_name: str
    deleted: bool = Field(description="The account was deleted; history keeps its name")


class RunScoring(Model):
    """Run-list subset of the summary: a mean is never shown without its coverage."""

    metric_id: str
    planned_trials: int
    scored_trials: int
    excluded_error_trials: int
    unfinished_trials: int
    passed_trials: int | None
    mean: float | None = Field(description="Mean of valid scores only; null with no sample")
    stddev: float | None = Field(description="Sample standard deviation; null below 2 samples")
    pass_rate: float | None
    scored_coverage: float | None = Field(description="scored_trials / planned_trials")
    bench_score: float | None = Field(description="Macro mean of per-task means")


class Run(Model):
    id: str
    name: str
    owner_id: str
    owner: Owner
    pat_id: str | None
    relation: Literal["initial", "rerun", "modified"]
    source_run_id: str | None
    dataset_version_id: str
    operation_id: str
    client_request_id: str | None
    state: RunStateName
    result_completeness: Literal["none", "partial", "complete"]
    artifact_state: Literal["pending", "saving", "complete", "partial", "failed", "expired"]
    cleanup_state: Literal["pending", "running", "complete", "failed", "not_required"]
    stop_requested: bool
    stop_reason: str | None
    queue_reason: str | None = Field(
        description="Why a queued run waits: CAPACITY_SLOTS, CAPACITY_CPU, CAPACITY_MEMORY "
        "or PROVIDER_LIMIT"
    )
    heartbeat_at: str | None = Field(description="Last sign of life from the run's Runner")
    counts: RunCounts
    scoring: RunScoring | None
    deletion: DeletionState | None = Field(description="Set when the run is in the recycle bin")
    dataset_version_deletion: DeletionState | None
    accepted_at: str
    started_at: str | None
    finished_at: str | None
    deadline_at: str
    allowed_actions: list[str]
    links: dict[str, str]


class RunSnapshot(Model):
    schema_version: int
    effective: dict[str, Any]
    provenance: dict[str, Any]
    policy: dict[str, Any]
    config_digest: str
    snapshot_digest: str
    comparison_digest: str


class RunDetail(Run):
    snapshot: RunSnapshot


class ScoringContract(Model):
    model_config = ConfigDict(extra="allow")

    contract_version: int
    source: Literal["platform_default", "dataset_version"]
    metric_id: str
    name: str
    unit: str | None
    direction: Literal["higher_is_better", "lower_is_better"]
    passed: dict[str, Any] | None = Field(description="Explicit pass rule; null: no pass rate")
    task_aggregation: str
    bench_aggregation: str
    count_as_failure: list[str]


class TaskSummary(Model):
    task_key: str
    planned_trials: int
    scored_trials: int
    mean: float | None
    stddev: float | None
    passed_trials: int | None
    partial: bool = Field(description="Some planned repetitions have no valid score")
    excluded_trials: int
    failure_causes: list[str]


class UsageSummary(Model):
    known_trials: int
    unknown_trials: int = Field(description="Started trials that reported no usage")
    known_totals: dict[str, float]


class RunSummary(Model):
    """06 section 5. At a terminal run planned = scored + count_as_failure + excluded +
    unfinished; while running, active and queued make up the rest."""

    run_id: str
    contract: ScoringContract
    planned_trials: int
    scored_trials: int
    count_as_failure_trials: int
    excluded_error_trials: int
    unfinished_trials: int
    active_trials: int
    queued_trials: int
    passed_trials: int | None
    mean: float | None
    stddev: float | None
    pass_rate: float | None
    scored_coverage: float | None
    evaluation_coverage: float | None
    bench_task_coverage: float | None = Field(description="Run tasks / tasks in the version")
    bench_score: float | None
    bench_scored_tasks: int
    task_count: int
    result_completeness: Literal["none", "partial", "complete"]
    excluded_by_cause: dict[str, int]
    attempts: int
    retried_trials: int
    retry_count: int = Field(description="Extra attempts beyond the first, over all trials")
    usage: UsageSummary
    tasks: list[TaskSummary]


class TrialResult(Model):
    raw_score: float | None = Field(description="Verifier output; null when none")
    reward_valid: bool
    score: float | None = Field(description="Counted score; 0 is a real zero, null is unscored")
    failure_cause: str | None
    exception_type: str | None
    verifier_status: str | None
    policy_version: str
    attempt_id: str


class AttemptStep(Model):
    step: str = Field(description="starting, environment, agent, collecting or verifying")
    at: str


class Attempt(Model):
    id: str
    attempt_index: int
    state: Literal[
        "starting",
        "preparing",
        "executing",
        "verifying",
        "completed",
        "failed",
        "cancelled",
        "interrupted",
    ]
    phase: str | None
    steps: list[AttemptStep] = Field(
        description="Step start times; a step ends when the next starts or the attempt ends"
    )
    executor_ref: dict[str, Any] | None
    started_at: str
    ended_at: str | None
    error: dict[str, Any] | None


class ArtifactCounts(Model):
    available: int
    failed: int = Field(description="Not saved, or found missing from storage")
    expired: int


class Trial(Model):
    id: str
    task_id: str
    task_key: str
    repetition_index: int
    state: Literal[
        "queued",
        "preparing",
        "executing",
        "verifying",
        "scored",
        "execution_error",
        "not_started",
        "cancelled",
        "interrupted",
    ]
    phase: str | None
    reason_code: str | None
    artifact_state: Literal["pending", "saving", "complete", "partial", "failed", "expired"]
    artifact_counts: ArtifactCounts
    cleanup_state: Literal["pending", "running", "complete", "failed", "not_required"]
    result: TrialResult | None
    attempts: list[Attempt]


class Artifact(Model):
    id: str
    run_id: str
    trial_id: str | None
    attempt_id: str | None
    kind: str
    relative_path: str
    digest: str | None
    size_bytes: int | None
    status: Literal[
        "pending", "available", "failed", "deleting", "expired", "unavailable", "deleted"
    ]
    status_reason: str | None = Field(
        description="e.g. STORAGE_WRITE_FAILED, STORAGE_CONTENT_MISSING, RETENTION_EXPIRED"
    )
    created_at: str
    expires_at: str | None = Field(
        description="When the file is reclaimed: trial (or run) end + TTL; null until it ends"
    )


class ExportCreate(Model):
    run_ids: list[str]
    include_artifacts: bool = True
    artifact_kinds: list[str] | None = None
    task_keys: list[str] | None = None


class ExportRequest(Model):
    run_ids: list[str]
    include_artifacts: bool
    artifact_kinds: list[str] | None
    task_keys: list[str] | None


class Export(Model):
    id: str
    owner_id: str
    operation_id: str
    state: Literal["queued", "building", "ready", "failed", "expired"]
    request: ExportRequest
    size_bytes: int | None
    digest: str | None
    summary: dict[str, Any] | None = Field(
        description="runs, files, missing, warnings, size_bytes and digest of the package"
    )
    error: dict[str, Any] | None
    created_at: str
    finished_at: str | None
    expires_at: str | None
    links: dict[str, str]


# --- deletion and recycle bin ---------------------------------------------------------

ObjectType = Literal["run", "artifact", "dataset", "dataset_version", "credential", "user", "pat"]


class RecycleEntry(Model):
    id: str
    object_type: ObjectType
    object_id: str
    label: str = Field(description="The object's name when it was deleted")
    owner_id: str | None
    owner_username: str | None
    state: Literal["recycled", "purged", "restored"]
    deleted_by: str
    deleted_by_username: str | None
    deleted_at: str
    purged_by: str | None
    purged_at: str | None
    detail: dict[str, Any]


class PurgeRequest(Model):
    confirm_object_id: str = Field(description="Repeat the object id: purging is irreversible")


class OperationResource(Model):
    type: str
    id: str


class Operation(Model):
    id: str
    kind: str
    resource: OperationResource | None
    owner_id: str | None
    status: Literal["accepted", "running", "succeeded", "failed", "cancelled", "interrupted"]
    phase: str | None
    progress: dict[str, Any]
    error: dict[str, Any] | None
    result: dict[str, Any] | None
    allowed_actions: list[str]
    links: dict[str, str]
    revision: int
    created_at: str
    updated_at: str
    finished_at: str | None


class AuditEvent(Model):
    id: str
    actor_user_id: str | None
    pat_id: str | None
    auth_channel: str | None
    action: str
    object_type: str | None
    object_id: str | None
    outcome: str
    detail: dict[str, Any] | None
    request_id: str | None
    created_at: str


class Capabilities(Model):
    api_version: str
    service_version: str
    schema_revision: str
    features: dict[str, bool]
    limits: dict[str, int]
    auth: dict[str, Any]
    actions: dict[str, dict[str, Any]]
    execution: dict[str, Any]


class HostCapacityView(Model):
    slots: int
    cpus: float
    memory_mb: int


class CapacityUse(Model):
    slots: int
    cpus: float
    memory_mb: int


class ProviderCapacity(Model):
    provider: str
    max_concurrent_trials: int | None = Field(description="null means no platform limit")
    in_use: int


class CapacityOverview(Model):
    host: HostCapacityView
    in_use: CapacityUse
    providers: list[ProviderCapacity]


class ProviderLimit(Model):
    max_concurrent_trials: int | None = Field(description="null removes the limit")


class Health(Model):
    status: str
    accepting_runs: bool | None = None
    detail: dict[str, Any] = {}
