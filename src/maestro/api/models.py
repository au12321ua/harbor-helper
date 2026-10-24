"""Public API models. They define the OpenAPI contract shared by web and SDK."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


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


# Sign-in and setup bodies come from anyone who can reach the port: bound every field.
# The password limit is the policy's (security.passwords.MAX_LENGTH).
UsernameText = Annotated[str, Field(max_length=128)]
PasswordText = Annotated[str, Field(max_length=256)]
TokenText = Annotated[str, Field(max_length=256)]


class SetupRequest(Model):
    setup_token: TokenText
    username: UsernameText
    display_name: str | None = Field(None, max_length=1024)
    password: PasswordText


class LoginRequest(Model):
    username: UsernameText
    password: PasswordText


class PasswordChange(Model):
    current_password: PasswordText
    new_password: PasswordText


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
    token: TokenText


class InvitationInfo(Model):
    kind: Literal["invitation", "password_reset"]
    role: Role
    username: str | None
    expires_at: str


class InvitationAccept(Model):
    token: TokenText
    username: UsernameText | None = None
    display_name: str | None = Field(None, max_length=1024)
    password: PasswordText


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
    materialization_digest: str | None
    status: Literal["ready"]
    description: str
    created_at: str
    created_by: str | None
    operation_id: str | None
    task_count: int
    admitted_task_count: int
    submittable_task_count: int
    cache_ready_task_count: int


class DeletionState(Model):
    state: Literal["recycled", "purged"] = Field(
        description="recycled: in the recycle bin; purged: content gone, receipt kept"
    )
    deleted_at: str
    purged_at: str | None


class DatasetVersionDetail(DatasetVersion):
    namespace: str
    name: str
    first_preparation_operation_id: str | None
    scoring_contract: dict[str, Any] = Field(
        description="Contract new runs freeze; source is dataset_version or platform_default"
    )
    deletion: DeletionState | None = Field(
        description="Set when the version or its dataset was deleted; it still resolves"
    )


class Dataset(Model):
    id: str
    source_kind: str
    namespace: str
    name: str
    description: str
    credential_id: str | None
    versions: list[DatasetVersion]


class TaskAdmission(Model):
    id: str
    state: Literal["pending", "admitted", "first_failed", "revoked"]
    revision: int
    approved_at: str | None


class ContentResource(Model):
    resource_kind: Literal["task_content", "environment_image"]
    digest: str
    availability: Literal["unknown", "available", "unavailable"]
    checked_at: str | None


class TaskContent(Model):
    digest: str
    material_digest: str | None
    availability: Literal["unknown", "available", "unavailable"]
    checked_at: str | None
    resources: list[ContentResource]


class LocalPreparation(Model):
    id: str | None
    location_id: str
    cache_state: Literal["absent", "restoring", "ready", "stale"]
    last_restore_error: dict[str, Any] | None
    operation_id: str | None
    prepared_at: str | None
    last_used_at: str | None


class TaskBlocker(Model):
    code: Literal[
        "TASK_NOT_ADMITTED",
        "TASK_ADMISSION_REVOKED",
        "RESOURCE_CONTENT_UNAVAILABLE",
        "CONFIG_REQUIRED_MISSING",
        "AUTHOR_PARAMETERS_UNRESOLVED",
    ]
    admission_state: str | None = None
    first_preparation_error: dict[str, Any] | None = None
    resource_kind: str | None = None
    expected_digest: str | None = None
    evidence: dict[str, Any] | None = None
    parameters: list[str] | None = None
    issues: list[dict[str, Any]] | None = None


class TaskWarning(Model):
    code: Literal["PREPARATION_CACHE_MISS"]
    action: str


class RequiredPreparation(Model):
    action: Literal["restore_cache"]
    spec_digest: str


class AuthorParameter(Model):
    """Author parameter contract (03): defaults, requirement, constraints."""

    name: str
    default: str | None
    required: bool
    sensitive: bool
    description: str
    hard_constraints: dict[str, Any]
    used_in: list[str]


class Task(Model):
    id: str
    dataset_version_id: str
    task_key: str
    admission: TaskAdmission | None
    content: TaskContent
    local_preparation: LocalPreparation
    spec_digest: str | None
    resources: dict[str, Any]
    timeouts: dict[str, Any]
    parameters: list[AuthorParameter]
    required_parameters: list[str] = []
    instruction: str
    can_submit: bool
    blockers: list[TaskBlocker]
    warnings: list[TaskWarning]
    required_preparation: list[RequiredPreparation]


class PreparationWaiter(Model):
    run_id: str | None
    operation_id: str | None
    state: str
    since: str


class PreparationPin(Model):
    holder_kind: str
    holder_id: str


class Preparation(LocalPreparation):
    spec_digest: str
    generation: int
    image_id: str | None
    archive: dict[str, Any] | None
    waiters: list[PreparationWaiter]
    pins: list[PreparationPin]


class DatasetSource(Model):
    kind: str
    available: bool


class SourceDataset(Model):
    namespace: str
    name: str
    visibility: str | None = None


class SourceVersion(Model):
    ref: str
    revision: int | None = None
    tags: list[str] = []
    resolved_digest: str
    published_at: str | None = None
    yanked: bool = False
    yanked_reason: str | None = None


class SourceTask(Model):
    task_key: str
    content_digest: str


class SourceVersionDetail(Model):
    namespace: str
    name: str
    upstream_ref: str
    ref_kind: str
    resolved_digest: str
    description: str
    tasks: list[SourceTask]
    existing_version_id: str | None


class DatasetImport(Model):
    source_kind: str = "hub"
    namespace: str
    name: str
    ref: str = Field(description="Tag, revision or sha256 digest; always pinned to a digest")
    credential_id: str | None = None
    accept_changed_content: bool = Field(
        False, description="Record a moved tag as a new version (CONTENT_REFERENCE_CHANGED)"
    )
    prepare: bool = Field(True, description="Start the first preparation after the import")


class FirstPreparation(Model):
    task_ids: list[str] | None = Field(
        None, description="Default: every task without a successful first preparation"
    )


class ScoringContractInput(Model):
    metric_id: str = "reward"
    name: str = "Reward"
    unit: str | None = None
    direction: Literal["higher_is_better", "lower_is_better"]
    pass_threshold: float | None = Field(
        description="A trial passes when its score reaches this value; null: no pass rate"
    )


class AdmissionRevocation(Model):
    reason: str
    expected_revision: int


class AdmissionRevoked(Model):
    id: str
    state: Literal["revoked"]
    revision: int


# --- runs and operations -------------------------------------------------------------


class TaskSelection(Model):
    mode: Literal["all_eligible", "explicit"] = "all_eligible"
    task_ids: list[str] | None = None


class CredentialRef(Model):
    credential_id: str


class ResourceOverrides(Model):
    cpus: int | None = None
    memory_mb: int | None = None


class TimeoutOverrides(Model):
    agent_sec: float | None = None
    verifier_sec: float | None = None
    bootstrap_sec: float | None = Field(
        None, description="Time for each trial to install all attachments (team default)"
    )


class RunConfigFields(Model):
    """A run configuration request (03). Unset fields are inherited: author values for
    task resources, timeouts and parameters, the team policy for the rest."""

    plan_id: str | None = Field(
        None, description="An experiment plan; fields set here win, the plan fills in the rest"
    )
    plan_revision: int | None = Field(
        None, description="Refuse unless the plan is still at this revision"
    )
    task_selection: TaskSelection = TaskSelection()
    model_config_id: str | None = None
    model_revision: int | None = Field(
        None, description="An earlier revision of the model configuration; unset: current"
    )
    harness_version_id: str | None = None
    harness_params: dict[str, Any] = {}
    attachments: list[str] = Field(
        [], description="Attachment version ids in load order (model runs only)"
    )
    repetitions: int | None = None
    concurrency: int | None = None
    run_deadline_hours: int | None = None
    resources: ResourceOverrides = ResourceOverrides()
    timeouts: TimeoutOverrides = TimeoutOverrides()
    parameters: dict[str, str | CredentialRef] = Field(
        {}, description="Author parameter values; secret ones as a credential reference"
    )


class ConfigRequest(RunConfigFields):
    dataset_version_id: str | None = Field(None, description="Required unless the plan has it")
    execution_mode: Literal["agent", "oracle"] | None = Field(
        None,
        description="agent: a model through a harness; oracle: each task's reference "
        "solution, a test mode never compared with model results. Required unless the "
        "plan has it",
    )


class RunCreate(RunConfigFields):
    """Either ``resolution_id`` of a resolution made before, or the configuration inline."""

    name: str
    resolution_id: str | None = None
    dataset_version_id: str | None = None
    execution_mode: Literal["agent", "oracle"] | None = None
    client_request_id: str | None = None
    source_run_id: str | None = Field(
        None,
        description="Makes this a modified run of that run: its differences are recorded "
        "(start from GET /runs/{run_id}/request)",
    )


class PlanCreate(Model):
    name: str
    description: str = ""
    template: dict[str, Any] = Field(
        {}, description="Fields of a configuration request (see ConfigRequest)"
    )


class PlanUpdate(Model):
    expected_revision: int
    name: str | None = None
    description: str | None = None
    template: dict[str, Any] | None = None


class PlanCopy(Model):
    name: str | None = None


class PlanArchive(Model):
    archived: bool


class Plan(Model):
    id: str
    name: str
    description: str
    owner_id: str
    owner_username: str | None
    revision: int
    template: dict[str, Any]
    copied_from: str | None
    created_at: str
    updated_at: str
    archived_at: str | None
    allowed_actions: list[str]
    deletion: dict[str, Any] | None = None


class RerunSelection(Model):
    mode: Literal["all", "unfinished", "explicit"] = Field(
        "all",
        description="unfinished: every task with a trial not scored (the source must "
        "have ended); explicit: task_ids of the source run",
    )
    task_ids: list[str] | None = None


class RunRerun(Model):
    """A new run from the source run's snapshot; only the task set may shrink."""

    name: str | None = None
    task_selection: RerunSelection = RerunSelection()
    client_request_id: str | None = None


class ConfigBlocker(Model):
    model_config = ConfigDict(extra="allow")
    code: str
    path: str
    message: str


class ConfigResolution(Model):
    resolution_id: str
    created_at: str
    expires_at: str
    request: dict[str, Any]
    effective_config: dict[str, Any] | None
    field_sources: dict[str, dict[str, Any]]
    baseline_differences: list[dict[str, Any]]
    excluded_tasks: list[dict[str, Any]]
    required_preparation: list[dict[str, Any]]
    cache_observations: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    blockers: list[ConfigBlocker]
    config_digest: str | None
    reference_revisions: dict[str, Any]
    labels: dict[str, str]
    planned_trials: int


Protocol = Literal["openai-compatible", "openai", "anthropic"]


class CredentialName(Model):
    """A usable team credential as everyone sees it: the name, never the value."""

    id: str
    name: str
    kind: str
    provider: str
    description: str


class ModelConfigFields(Model):
    provider: str = Field(description="Provider name; concurrency limits apply per provider")
    protocol: Protocol
    endpoint: str = Field(description="http(s) base URL, no credentials or query")
    model_id: str
    params: dict[str, Any] = {}
    credential_id: str | None = None
    description: str = ""


class ModelConfigCreate(ModelConfigFields):
    name: str


class ModelConfigRevise(ModelConfigFields):
    expected_revision: int


class ModelRevision(Model):
    revision: int
    provider: str
    protocol: Protocol
    endpoint: str
    model_id: str
    params: dict[str, Any]
    credential_bound: bool
    credential_id: str | None = None
    created_at: str


class ModelConfig(Model):
    id: str
    name: str
    description: str
    enabled: bool
    revision: int
    provider: str
    protocol: Protocol
    endpoint: str
    model_id: str
    params: dict[str, Any]
    credential_bound: bool
    credential_problem: str | None
    credential_id: str | None = Field(None, description="Administrators only")
    credential_name: str | None = Field(None, description="Administrators only")
    created_at: str
    updated_at: str
    deletion: dict[str, Any] | None = None
    revisions: list[ModelRevision] | None = None


class HarnessCreate(Model):
    name: str
    version: str
    agent: str = Field(description="Executor adapter; see /admin/harness-adapters")
    protocols: list[Protocol]
    parameter_schema: dict[str, Any] = {"parameters": {}}
    description: str = ""


class Harness(Model):
    id: str
    name: str
    version: str
    agent: str
    description: str
    protocols: list[Protocol]
    parameter_schema: dict[str, Any]
    content_digest: str
    enabled: bool
    created_at: str
    deletion: dict[str, Any] | None = None


class HarnessAdapter(Model):
    agent: str
    protocols: list[Protocol]
    parameters: list[str] | None = Field(
        None, description="Parameters a harness version may declare; null means any"
    )


class EnabledChange(Model):
    enabled: bool


class AttachmentProvides(Model):
    tools: list[str]
    env: list[str]


class AttachmentFile(Model):
    path: str
    size: int
    sha256: str
    executable: bool


class Attachment(Model):
    id: str
    name: str
    version: str
    description: str
    owner_id: str
    owner_username: str | None
    content_digest: str = Field(description="Covers every file's path, SHA-256 and mode")
    effects: list[str]
    compatible_harnesses: list[str] = Field(description='Harness agents, or ["*"] for any')
    provides: AttachmentProvides
    has_bootstrap: bool = Field(description="Has bootstrap.sh, run in each trial's setup")
    file_count: int
    size_bytes: int
    enabled: bool
    created_at: str
    files: list[AttachmentFile] | None = None
    deletion: dict[str, Any] | None = None


class PolicySetting(Model):
    name: str
    group: str
    description: str
    built_in: int
    min: int
    max: int


class TeamPolicy(Model):
    revision: int
    values: dict[str, int]
    settings: list[PolicySetting]


class TeamPolicyUpdate(Model):
    values: dict[str, int]
    expected_revision: int


class TeamPolicyRevision(Model):
    revision: int
    values: dict[str, int]
    created_by: str
    created_by_username: str
    created_at: str


class RunAccepted(Model):
    run_id: str
    operation_id: str
    state: str
    config_digest: str
    snapshot_digest: str
    planned_trials: int
    excluded_tasks: list[dict[str, Any]]
    cache_observations: list[dict[str, Any]]
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
    plan_id: str | None = None
    plan_revision: int | None = None
    batch_id: str | None = None
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

ObjectType = Literal[
    "run",
    "artifact",
    "dataset",
    "dataset_version",
    "credential",
    "user",
    "pat",
    "model_config",
    "harness_version",
    "attachment_version",
    "experiment_plan",
]


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
    contract_digest: str = Field(
        description="sha256 of the OpenAPI document; clients generated from another one warn"
    )
    features: dict[str, bool]
    limits: dict[str, int]
    team_policy_revision: int
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


# --- batches (04 section 4) ------------------------------------------------------


class BatchCreate(Model):
    """Runs accepted together, all or none; each costs one unit of PAT quota."""

    name: str
    runs: list[RunCreate]
    client_request_id: str | None = None


class BatchAccepted(Model):
    batch_id: str
    operation_id: str
    planned_trials: int
    runs: list[RunAccepted]
    links: dict[str, str]


class BatchPreview(Model):
    runs: list[dict[str, Any]]
    planned_trials: int
    pat_quota: dict[str, int] | None
    duplicate_configs: list[str] = Field(description="Configuration digests given twice")
    blockers: list[dict[str, Any]]
    can_submit: bool


class Batch(Model):
    id: str
    name: str
    owner_id: str
    owner_username: str | None
    pat_id: str | None
    client_request_id: str | None
    stop_requested: bool
    created_at: str
    status: str
    operation_id: str
    progress: dict[str, int]
    runs: list[Run]
    allowed_actions: list[str]
