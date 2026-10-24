"""Generated from openapi/maestro-v1.json by tools/generate_clients.py. Do not edit.

Every model allows fields it does not know, so a newer service adds fields without
breaking an older SDK.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class AdmissionRevocation(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    expected_revision: int
    reason: str


class AdmissionRevoked(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: str
    revision: int
    state: Literal["revoked"]


class Artifact(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    attempt_id: str | None
    created_at: str
    digest: str | None
    expires_at: Annotated[
        str | None,
        Field(
            description="When the file is reclaimed: trial (or run) end + TTL; null until it ends"
        ),
    ]
    id: str
    kind: str
    relative_path: str
    run_id: str
    size_bytes: int | None
    status: Literal[
        "pending", "available", "failed", "deleting", "expired", "unavailable", "deleted"
    ]
    status_reason: Annotated[
        str | None,
        Field(description="e.g. STORAGE_WRITE_FAILED, STORAGE_CONTENT_MISSING, RETENTION_EXPIRED"),
    ]
    trial_id: str | None


class ArtifactCounts(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    available: int
    expired: int
    failed: Annotated[int, Field(description="Not saved, or found missing from storage")]


class AttachmentFile(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    executable: bool
    path: str
    sha256: str
    size: int


class AttachmentProvides(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    env: list[str]
    tools: list[str]


class AttemptStep(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    at: str
    step: Annotated[str, Field(description="starting, environment, agent, collecting or verifying")]


class AuditEvent(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    action: str
    actor_user_id: str | None
    auth_channel: str | None
    created_at: str
    detail: dict[str, Any] | None
    id: str
    object_id: str | None
    object_type: str | None
    outcome: str
    pat_id: str | None
    request_id: str | None


class AuthorParameter(BaseModel):
    """
    Author parameter contract (03): defaults, requirement, constraints.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    default: str | None
    description: str
    hard_constraints: dict[str, Any]
    name: str
    required: bool
    sensitive: bool
    used_in: list[str]


class BatchPreview(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    blockers: list[dict[str, Any]]
    can_submit: bool
    duplicate_configs: Annotated[list[str], Field(description="Configuration digests given twice")]
    pat_quota: dict[str, int] | None
    planned_trials: int
    runs: list[dict[str, Any]]


class Capabilities(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    actions: dict[str, dict[str, Any]]
    api_version: str
    auth: dict[str, Any]
    contract_digest: Annotated[
        str,
        Field(
            description="sha256 of the OpenAPI document; clients generated from another one warn"
        ),
    ]
    execution: dict[str, Any]
    features: dict[str, bool]
    limits: dict[str, int]
    schema_revision: str
    service_version: str
    team_policy_revision: int


class CapacityUse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    cpus: float
    memory_mb: int
    slots: int


class ConfigBlocker(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    code: str
    message: str
    path: str


class ConfigResolution(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    baseline_differences: list[dict[str, Any]]
    blockers: list[ConfigBlocker]
    cache_observations: list[dict[str, Any]]
    config_digest: str | None
    created_at: str
    effective_config: dict[str, Any] | None
    excluded_tasks: list[dict[str, Any]]
    expires_at: str
    field_sources: dict[str, dict[str, Any]]
    labels: dict[str, str]
    planned_trials: int
    reference_revisions: dict[str, Any]
    request: dict[str, Any]
    required_preparation: list[dict[str, Any]]
    resolution_id: str
    warnings: list[dict[str, Any]]


class ContentResource(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    availability: Literal["unknown", "available", "unavailable"]
    checked_at: str | None
    digest: str
    resource_kind: Literal["task_content", "environment_image"]


class Credential(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    created_at: str
    created_by: str
    description: str
    enabled: bool
    id: str
    key_version: int
    kind: Literal["model_api_key", "hub_token", "generic_secret"]
    name: str
    provider: str
    revision: int
    updated_at: str


class CredentialCreate(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    description: str | None = ""
    kind: Literal["model_api_key", "hub_token", "generic_secret"]
    name: str
    provider: str
    value: str


class CredentialName(BaseModel):
    """
    A usable team credential as everyone sees it: the name, never the value.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    description: str
    id: str
    kind: str
    name: str
    provider: str


class CredentialRef(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    credential_id: str


class CredentialValue(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    expected_revision: int
    value: str


class DatasetImport(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    accept_changed_content: Annotated[
        bool | None,
        Field(description="Record a moved tag as a new version (CONTENT_REFERENCE_CHANGED)"),
    ] = False
    credential_id: str | None = None
    name: str
    namespace: str
    prepare: Annotated[
        bool | None, Field(description="Start the first preparation after the import")
    ] = True
    ref: Annotated[
        str,
        Field(description="Tag, revision or sha256 digest; always pinned to a digest"),
    ]
    source_kind: str | None = "hub"


class DatasetSource(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    available: bool
    kind: str


class DatasetVersion(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    admitted_task_count: int
    cache_ready_task_count: int
    created_at: str
    created_by: str | None
    dataset_id: str
    description: str
    id: str
    materialization_digest: str | None
    operation_id: str | None
    ref_kind: str
    resolved_digest: str
    status: Literal["ready"]
    submittable_task_count: int
    task_count: int
    upstream_ref: str


class DeletionState(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    deleted_at: str
    purged_at: str | None
    state: Annotated[
        Literal["recycled", "purged"],
        Field(description="recycled: in the recycle bin; purged: content gone, receipt kept"),
    ]


class EnabledChange(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    enabled: bool


class ExportCreate(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    artifact_kinds: list[str] | None = None
    include_artifacts: bool | None = True
    run_ids: list[str]
    task_keys: list[str] | None = None


class ExportRequest(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    artifact_kinds: list[str] | None
    include_artifacts: bool
    run_ids: list[str]
    task_keys: list[str] | None


class FieldErrorModel(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    code: str
    limit: int | float | None = None
    message: str | None = None
    path: str


class FirstPreparation(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_ids: Annotated[
        list[str] | None,
        Field(description="Default: every task without a successful first preparation"),
    ] = None


class Harness(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    agent: str
    content_digest: str
    created_at: str
    deletion: dict[str, Any] | None = None
    description: str
    enabled: bool
    id: str
    name: str
    parameter_schema: dict[str, Any]
    protocols: list[str]
    version: str


class HarnessAdapter(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    agent: str
    parameters: Annotated[
        list[str] | None,
        Field(description="Parameters a harness version may declare; null means any"),
    ] = None
    protocols: list[str]


class HarnessCreate(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    agent: Annotated[str, Field(description="Executor adapter; see /admin/harness-adapters")]
    description: str | None = ""
    name: str
    parameter_schema: dict[str, Any] | None = {"parameters": {}}
    protocols: list[Literal["openai-compatible", "openai", "anthropic"]]
    version: str


class Health(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    accepting_runs: bool | None = None
    detail: dict[str, Any] | None = {}
    status: str


class HostCapacityView(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    cpus: float
    memory_mb: int
    slots: int


class Invitation(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    created_at: str
    created_by: str
    expires_at: str
    id: str
    kind: Literal["invitation", "password_reset"]
    note: str
    role: Literal["admin", "member"]
    state: Literal["pending", "used", "revoked", "expired"]
    target_user_id: str | None
    used_at: str | None
    used_by: str | None


class DisplayName(RootModel[str]):
    root: Annotated[str, Field(max_length=1024)]


class Username(RootModel[str]):
    root: Annotated[str, Field(max_length=128)]


class InvitationAccept(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    display_name: DisplayName | None = None
    password: Annotated[str, Field(max_length=256)]
    token: Annotated[str, Field(max_length=256)]
    username: Username | None = None


class InvitationCreate(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    note: str | None = ""
    role: Literal["admin", "member"] | None = "member"
    valid_hours: int | None = None


class InvitationInfo(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    expires_at: str
    kind: Literal["invitation", "password_reset"]
    role: Literal["admin", "member"]
    username: str | None


class InvitationLookup(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    token: Annotated[str, Field(max_length=256)]


class IssuedInvitation(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    created_at: str
    created_by: str
    expires_at: str
    id: str
    kind: Literal["invitation", "password_reset"]
    note: str
    role: Literal["admin", "member"]
    state: Literal["pending", "used", "revoked", "expired"]
    target_user_id: str | None
    token: Annotated[str, Field(description="Shown once")]
    used_at: str | None
    used_by: str | None


class IssuedPat(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    accepted_runs: int
    created_at: str
    expires_at: str
    id: str
    last_used_at: str | None
    name: str
    remaining_runs: int
    revision: int
    revoked_at: str | None
    run_limit: int
    scope: Literal["read", "experiment"]
    state: Literal["active", "revoked", "expired"]
    token: Annotated[str, Field(description="Shown once; store it securely")]
    token_prefix: str


class LocalPreparation(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    cache_state: Literal["absent", "restoring", "ready", "stale"]
    id: str | None
    last_restore_error: dict[str, Any] | None
    last_used_at: str | None
    location_id: str
    operation_id: str | None
    prepared_at: str | None


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    password: Annotated[str, Field(max_length=256)]
    username: Annotated[str, Field(max_length=128)]


class MasterKeyRotation(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    expected_generation: int


class MasterKeyStatus(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    available: bool
    generation: int | None
    initialized: bool
    reencrypted_credentials: int | None = None
    rotated_at: str | None


class Me(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    auth_channel: Literal["web_session", "pat"]
    created_at: str
    disabled_at: str | None
    display_name: str
    id: str
    pat_id: str | None
    pat_scope: Literal["read", "experiment"] | None
    revision: int
    role: Literal["admin", "member"]
    status: Literal["active", "disabled"]
    username: str


class Meta(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    next_cursor: str | None = None
    request_id: str


class ModelConfigCreate(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    credential_id: str | None = None
    description: str | None = ""
    endpoint: Annotated[str, Field(description="http(s) base URL, no credentials or query")]
    model_id: str
    name: str
    params: dict[str, Any] | None = {}
    protocol: Literal["openai-compatible", "openai", "anthropic"]
    provider: Annotated[
        str, Field(description="Provider name; concurrency limits apply per provider")
    ]


class ModelConfigRevise(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    credential_id: str | None = None
    description: str | None = ""
    endpoint: Annotated[str, Field(description="http(s) base URL, no credentials or query")]
    expected_revision: int
    model_id: str
    params: dict[str, Any] | None = {}
    protocol: Literal["openai-compatible", "openai", "anthropic"]
    provider: Annotated[
        str, Field(description="Provider name; concurrency limits apply per provider")
    ]


class ModelRevision(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    created_at: str
    credential_bound: bool
    credential_id: str | None = None
    endpoint: str
    model_id: str
    params: dict[str, Any]
    protocol: str
    provider: str
    revision: int


class OperationResource(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: str
    type: str


class Owner(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    deleted: Annotated[bool, Field(description="The account was deleted; history keeps its name")]
    display_name: str
    username: str


class PasswordChange(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    current_password: Annotated[str, Field(max_length=256)]
    new_password: Annotated[str, Field(max_length=256)]


class Pat(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    accepted_runs: int
    created_at: str
    expires_at: str
    id: str
    last_used_at: str | None
    name: str
    remaining_runs: int
    revision: int
    revoked_at: str | None
    run_limit: int
    scope: Literal["read", "experiment"]
    state: Literal["active", "revoked", "expired"]
    token_prefix: str


class PatCreate(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    expires_in_days: int | None = None
    name: str
    run_limit: int | None = None
    scope: Literal["read", "experiment"]


class Plan(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    allowed_actions: list[str]
    archived_at: str | None
    copied_from: str | None
    created_at: str
    deletion: dict[str, Any] | None = None
    description: str
    id: str
    name: str
    owner_id: str
    owner_username: str | None
    revision: int
    template: dict[str, Any]
    updated_at: str


class PlanArchive(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    archived: bool


class PlanCopy(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    name: str | None = None


class PlanCreate(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    description: str | None = ""
    name: str
    template: Annotated[
        dict[str, Any] | None,
        Field(description="Fields of a configuration request (see ConfigRequest)"),
    ] = {}


class PlanUpdate(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    description: str | None = None
    expected_revision: int
    name: str | None = None
    template: dict[str, Any] | None = None


class PolicySetting(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    built_in: int
    description: str
    group: str
    max: int
    min: int
    name: str


class PreparationPin(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    holder_id: str
    holder_kind: str


class PreparationWaiter(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    operation_id: str | None
    run_id: str | None
    since: str
    state: str


class ProviderCapacity(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    in_use: int
    max_concurrent_trials: Annotated[int | None, Field(description="null means no platform limit")]
    provider: str


class ProviderLimit(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    max_concurrent_trials: Annotated[int | None, Field(description="null removes the limit")]


class PurgeRequest(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    confirm_object_id: Annotated[
        str, Field(description="Repeat the object id: purging is irreversible")
    ]


class RecycleEntry(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    deleted_at: str
    deleted_by: str
    deleted_by_username: str | None
    detail: dict[str, Any]
    id: str
    label: Annotated[str, Field(description="The object's name when it was deleted")]
    object_id: str
    object_type: Literal[
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
    owner_id: str | None
    owner_username: str | None
    purged_at: str | None
    purged_by: str | None
    state: Literal["recycled", "purged", "restored"]


class RequiredPreparation(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    action: Literal["restore_cache"]
    spec_digest: str


class RerunSelection(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    mode: Annotated[
        Literal["all", "unfinished", "explicit"] | None,
        Field(
            description="unfinished: every task with a trial not scored (the source must have ended); explicit: task_ids of the source run"
        ),
    ] = "all"
    task_ids: list[str] | None = None


class ResourceOverrides(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    cpus: int | None = None
    memory_mb: int | None = None


class RunAccepted(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    cache_observations: list[dict[str, Any]]
    config_digest: str
    excluded_tasks: list[dict[str, Any]]
    links: dict[str, str]
    operation_id: str
    planned_trials: int
    run_id: str
    snapshot_digest: str
    state: str


class RunCounts(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    active: int
    cancelled: int
    errors: int
    interrupted: int
    not_started: int
    planned: int
    queued: int
    scored: int
    terminal: int


class RunRerun(BaseModel):
    """
    A new run from the source run's snapshot; only the task set may shrink.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    client_request_id: str | None = None
    name: str | None = None
    task_selection: Annotated[RerunSelection | None, Field(validate_default=True)] = {"mode": "all"}


class RunScoring(BaseModel):
    """
    Run-list subset of the summary: a mean is never shown without its coverage.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    bench_score: Annotated[float | None, Field(description="Macro mean of per-task means")]
    excluded_error_trials: int
    mean: Annotated[
        float | None,
        Field(description="Mean of valid scores only; null with no sample"),
    ]
    metric_id: str
    pass_rate: float | None
    passed_trials: int | None
    planned_trials: int
    scored_coverage: Annotated[float | None, Field(description="scored_trials / planned_trials")]
    scored_trials: int
    stddev: Annotated[
        float | None,
        Field(description="Sample standard deviation; null below 2 samples"),
    ]
    unfinished_trials: int


class RunSnapshot(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    comparison_digest: str
    config_digest: str
    effective: dict[str, Any]
    policy: dict[str, Any]
    provenance: dict[str, Any]
    schema_version: int
    snapshot_digest: str


class ScoringContract(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    bench_aggregation: str
    contract_version: int
    count_as_failure: list[str]
    direction: Literal["higher_is_better", "lower_is_better"]
    metric_id: str
    name: str
    passed: Annotated[
        dict[str, Any] | None,
        Field(description="Explicit pass rule; null: no pass rate"),
    ]
    source: Literal["platform_default", "dataset_version"]
    task_aggregation: str
    unit: str | None


class ScoringContractInput(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    direction: Literal["higher_is_better", "lower_is_better"]
    metric_id: str | None = "reward"
    name: str | None = "Reward"
    pass_threshold: Annotated[
        float | None,
        Field(description="A trial passes when its score reaches this value; null: no pass rate"),
    ]
    unit: str | None = None


class SessionInfo(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    csrf_token: Annotated[
        str | None,
        Field(description="Send as X-CSRF-Token on unsafe requests authenticated by the cookie"),
    ]
    user: Me


class SetupRequest(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    display_name: DisplayName | None = None
    password: Annotated[str, Field(max_length=256)]
    setup_token: Annotated[str, Field(max_length=256)]
    username: Annotated[str, Field(max_length=128)]


class SetupStatus(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    needs_setup: bool


class SourceDataset(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    name: str
    namespace: str
    visibility: str | None = None


class SourceTask(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    content_digest: str
    task_key: str


class SourceVersion(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    published_at: str | None = None
    ref: str
    resolved_digest: str
    revision: int | None = None
    tags: list[str] | None = []
    yanked: bool | None = False
    yanked_reason: str | None = None


class SourceVersionDetail(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    description: str
    existing_version_id: str | None
    name: str
    namespace: str
    ref_kind: str
    resolved_digest: str
    tasks: list[SourceTask]
    upstream_ref: str


class StatusChange(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    expected_revision: int


class TaskAdmission(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    approved_at: str | None
    id: str
    revision: int
    state: Literal["pending", "admitted", "first_failed", "revoked"]


class TaskBlocker(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    admission_state: str | None = None
    code: Literal[
        "TASK_NOT_ADMITTED",
        "TASK_ADMISSION_REVOKED",
        "RESOURCE_CONTENT_UNAVAILABLE",
        "CONFIG_REQUIRED_MISSING",
        "AUTHOR_PARAMETERS_UNRESOLVED",
    ]
    evidence: dict[str, Any] | None = None
    expected_digest: str | None = None
    first_preparation_error: dict[str, Any] | None = None
    issues: list[dict[str, Any]] | None = None
    parameters: list[str] | None = None
    resource_kind: str | None = None


class TaskContent(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    availability: Literal["unknown", "available", "unavailable"]
    checked_at: str | None
    digest: str
    material_digest: str | None
    resources: list[ContentResource]


class TaskSelection(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    mode: Literal["all_eligible", "explicit"] | None = "all_eligible"
    task_ids: list[str] | None = None


class TaskSummary(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    excluded_trials: int
    failure_causes: list[str]
    mean: float | None
    partial: Annotated[bool, Field(description="Some planned repetitions have no valid score")]
    passed_trials: int | None
    planned_trials: int
    scored_trials: int
    stddev: float | None
    task_key: str


class TaskWarning(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    action: str
    code: Literal["PREPARATION_CACHE_MISS"]


class TeamPolicy(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    revision: int
    settings: list[PolicySetting]
    values: dict[str, int]


class TeamPolicyRevision(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    created_at: str
    created_by: str
    created_by_username: str
    revision: int
    values: dict[str, int]


class TeamPolicyUpdate(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    expected_revision: int
    values: dict[str, int]


class TimeoutOverrides(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    agent_sec: float | None = None
    bootstrap_sec: Annotated[
        float | None,
        Field(description="Time for each trial to install all attachments (team default)"),
    ] = None
    verifier_sec: float | None = None


class TrialResult(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    attempt_id: str
    exception_type: str | None
    failure_cause: str | None
    policy_version: str
    raw_score: Annotated[float | None, Field(description="Verifier output; null when none")]
    reward_valid: bool
    score: Annotated[
        float | None,
        Field(description="Counted score; 0 is a real zero, null is unscored"),
    ]
    verifier_status: str | None


class UsageSummary(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    known_totals: dict[str, float]
    known_trials: int
    unknown_trials: Annotated[int, Field(description="Started trials that reported no usage")]


class User(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    created_at: str
    disabled_at: str | None
    display_name: str
    id: str
    revision: int
    role: Literal["admin", "member"]
    status: Literal["active", "disabled"]
    username: str


class Attachment(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    compatible_harnesses: Annotated[
        list[str], Field(description='Harness agents, or ["*"] for any')
    ]
    content_digest: Annotated[str, Field(description="Covers every file's path, SHA-256 and mode")]
    created_at: str
    deletion: dict[str, Any] | None = None
    description: str
    effects: list[str]
    enabled: bool
    file_count: int
    files: list[AttachmentFile] | None = None
    has_bootstrap: Annotated[bool, Field(description="Has bootstrap.sh, run in each trial's setup")]
    id: str
    name: str
    owner_id: str
    owner_username: str | None
    provides: AttachmentProvides
    size_bytes: int
    version: str


class Attempt(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    attempt_index: int
    ended_at: str | None
    error: dict[str, Any] | None
    executor_ref: dict[str, Any] | None
    id: str
    phase: str | None
    started_at: str
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
    steps: Annotated[
        list[AttemptStep],
        Field(description="Step start times; a step ends when the next starts or the attempt ends"),
    ]


class BatchAccepted(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    batch_id: str
    links: dict[str, str]
    operation_id: str
    planned_trials: int
    runs: list[RunAccepted]


class CapacityOverview(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    host: HostCapacityView
    in_use: CapacityUse
    providers: list[ProviderCapacity]


class ConfigRequest(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    attachments: Annotated[
        list[str] | None,
        Field(description="Attachment version ids in load order (model runs only)"),
    ] = []
    concurrency: int | None = None
    dataset_version_id: Annotated[
        str | None, Field(description="Required unless the plan has it")
    ] = None
    execution_mode: Annotated[
        Literal["agent", "oracle"] | None,
        Field(
            description="agent: a model through a harness; oracle: each task's reference solution, a test mode never compared with model results. Required unless the plan has it"
        ),
    ] = None
    harness_params: dict[str, Any] | None = {}
    harness_version_id: str | None = None
    model_config_id: str | None = None
    model_revision: Annotated[
        int | None,
        Field(description="An earlier revision of the model configuration; unset: current"),
    ] = None
    parameters: Annotated[
        dict[str, str | CredentialRef] | None,
        Field(
            description="Author parameter values; secret ones as a credential reference",
            validate_default=True,
        ),
    ] = {}
    plan_id: Annotated[
        str | None,
        Field(description="An experiment plan; fields set here win, the plan fills in the rest"),
    ] = None
    plan_revision: Annotated[
        int | None,
        Field(description="Refuse unless the plan is still at this revision"),
    ] = None
    repetitions: int | None = None
    resources: Annotated[ResourceOverrides | None, Field(validate_default=True)] = {}
    run_deadline_hours: int | None = None
    task_selection: Annotated[TaskSelection | None, Field(validate_default=True)] = {
        "mode": "all_eligible"
    }
    timeouts: Annotated[TimeoutOverrides | None, Field(validate_default=True)] = {}


class Dataset(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    credential_id: str | None
    description: str
    id: str
    name: str
    namespace: str
    source_kind: str
    versions: list[DatasetVersion]


class DatasetVersionDetail(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    admitted_task_count: int
    cache_ready_task_count: int
    created_at: str
    created_by: str | None
    dataset_id: str
    deletion: Annotated[
        DeletionState | None,
        Field(description="Set when the version or its dataset was deleted; it still resolves"),
    ]
    description: str
    first_preparation_operation_id: str | None
    id: str
    materialization_digest: str | None
    name: str
    namespace: str
    operation_id: str | None
    ref_kind: str
    resolved_digest: str
    scoring_contract: Annotated[
        dict[str, Any],
        Field(
            description="Contract new runs freeze; source is dataset_version or platform_default"
        ),
    ]
    status: Literal["ready"]
    submittable_task_count: int
    task_count: int
    upstream_ref: str


class EnvelopeAdmissionRevoked(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: AdmissionRevoked
    meta: Meta


class EnvelopeAttachment(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: Attachment
    meta: Meta


class EnvelopeBatchAccepted(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: BatchAccepted
    meta: Meta


class EnvelopeBatchPreview(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: BatchPreview
    meta: Meta


class EnvelopeCapabilities(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: Capabilities
    meta: Meta


class EnvelopeCapacityOverview(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: CapacityOverview
    meta: Meta


class EnvelopeConfigRequest(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: ConfigRequest
    meta: Meta


class EnvelopeConfigResolution(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: ConfigResolution
    meta: Meta


class EnvelopeCredential(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: Credential
    meta: Meta


class EnvelopeDatasetVersionDetail(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: DatasetVersionDetail
    meta: Meta


class EnvelopeHarness(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: Harness
    meta: Meta


class EnvelopeHealth(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: Health
    meta: Meta


class EnvelopeInvitationInfo(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: InvitationInfo
    meta: Meta


class EnvelopeInvitation(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: Invitation
    meta: Meta


class EnvelopeIssuedInvitation(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: IssuedInvitation
    meta: Meta


class EnvelopeIssuedPat(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: IssuedPat
    meta: Meta


class EnvelopeMasterKeyStatus(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: MasterKeyStatus
    meta: Meta


class EnvelopeMe(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: Me
    meta: Meta


class EnvelopePat(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: Pat
    meta: Meta


class EnvelopePlan(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: Plan
    meta: Meta


class EnvelopeRecycleEntry(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: RecycleEntry
    meta: Meta


class EnvelopeRunAccepted(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: RunAccepted
    meta: Meta


class EnvelopeSessionInfo(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: SessionInfo
    meta: Meta


class EnvelopeSetupStatus(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: SetupStatus
    meta: Meta


class EnvelopeSourceVersionDetail(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: SourceVersionDetail
    meta: Meta


class EnvelopeTeamPolicy(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: TeamPolicy
    meta: Meta


class EnvelopeUser(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: User
    meta: Meta


class EnvelopeDict(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: dict[str, Any]
    meta: Meta


class EnvelopeListArtifact(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[Artifact]
    meta: Meta


class EnvelopeListAttachment(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[Attachment]
    meta: Meta


class EnvelopeListAuditEvent(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[AuditEvent]
    meta: Meta


class EnvelopeListCredentialName(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[CredentialName]
    meta: Meta


class EnvelopeListCredential(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[Credential]
    meta: Meta


class EnvelopeListDatasetSource(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[DatasetSource]
    meta: Meta


class EnvelopeListDataset(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[Dataset]
    meta: Meta


class EnvelopeListHarnessAdapter(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[HarnessAdapter]
    meta: Meta


class EnvelopeListHarness(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[Harness]
    meta: Meta


class EnvelopeListInvitation(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[Invitation]
    meta: Meta


class EnvelopeListPat(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[Pat]
    meta: Meta


class EnvelopeListPlan(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[Plan]
    meta: Meta


class EnvelopeListRecycleEntry(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[RecycleEntry]
    meta: Meta


class EnvelopeListSourceDataset(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[SourceDataset]
    meta: Meta


class EnvelopeListSourceVersion(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[SourceVersion]
    meta: Meta


class EnvelopeListTeamPolicyRevision(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[TeamPolicyRevision]
    meta: Meta


class EnvelopeListUser(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[User]
    meta: Meta


class ErrorBody(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    code: str
    field_errors: Annotated[list[FieldErrorModel] | None, Field(validate_default=True)] = []
    message: str
    retryable: bool | None = False
    stage: str | None = None
    suggested_actions: list[dict[str, Any]] | None = []


class ErrorResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    error: ErrorBody
    meta: Meta


class Export(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    created_at: str
    digest: str | None
    error: dict[str, Any] | None
    expires_at: str | None
    finished_at: str | None
    id: str
    links: dict[str, str]
    operation_id: str
    owner_id: str
    request: ExportRequest
    size_bytes: int | None
    state: Literal["queued", "building", "ready", "failed", "expired"]
    summary: Annotated[
        dict[str, Any] | None,
        Field(description="runs, files, missing, warnings, size_bytes and digest of the package"),
    ]


class ModelConfig(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    created_at: str
    credential_bound: bool
    credential_id: Annotated[str | None, Field(description="Administrators only")] = None
    credential_name: Annotated[str | None, Field(description="Administrators only")] = None
    credential_problem: str | None
    deletion: dict[str, Any] | None = None
    description: str
    enabled: bool
    endpoint: str
    id: str
    model_id: str
    name: str
    params: dict[str, Any]
    protocol: str
    provider: str
    revision: int
    revisions: list[ModelRevision] | None = None
    updated_at: str


class Operation(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    allowed_actions: list[str]
    created_at: str
    error: dict[str, Any] | None
    finished_at: str | None
    id: str
    kind: str
    links: dict[str, str]
    owner_id: str | None
    phase: str | None
    progress: dict[str, Any]
    resource: OperationResource | None
    result: dict[str, Any] | None
    revision: int
    status: Literal["accepted", "running", "succeeded", "failed", "cancelled", "interrupted"]
    updated_at: str


class Preparation(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    archive: dict[str, Any] | None
    cache_state: Literal["absent", "restoring", "ready", "stale"]
    generation: int
    id: str | None
    image_id: str | None
    last_restore_error: dict[str, Any] | None
    last_used_at: str | None
    location_id: str
    operation_id: str | None
    pins: list[PreparationPin]
    prepared_at: str | None
    spec_digest: str
    waiters: list[PreparationWaiter]


class Run(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    accepted_at: str
    allowed_actions: list[str]
    artifact_state: Literal["pending", "saving", "complete", "partial", "failed", "expired"]
    batch_id: str | None = None
    cleanup_state: Literal["pending", "running", "complete", "failed", "not_required"]
    client_request_id: str | None
    counts: RunCounts
    dataset_version_deletion: DeletionState | None
    dataset_version_id: str
    deadline_at: str
    deletion: Annotated[
        DeletionState | None,
        Field(description="Set when the run is in the recycle bin"),
    ]
    finished_at: str | None
    heartbeat_at: Annotated[
        str | None, Field(description="Last sign of life from the run's Runner")
    ]
    id: str
    links: dict[str, str]
    name: str
    operation_id: str
    owner: Owner
    owner_id: str
    pat_id: str | None
    plan_id: str | None = None
    plan_revision: int | None = None
    queue_reason: Annotated[
        str | None,
        Field(
            description="Why a queued run waits: CAPACITY_SLOTS, CAPACITY_CPU, CAPACITY_MEMORY or PROVIDER_LIMIT"
        ),
    ]
    relation: Literal["initial", "rerun", "modified"]
    result_completeness: Literal["none", "partial", "complete"]
    scoring: RunScoring | None
    source_run_id: str | None
    started_at: str | None
    state: Literal[
        "queued", "preparing", "running", "finalizing", "finished", "cancelled", "interrupted"
    ]
    stop_reason: str | None
    stop_requested: bool


class RunCreate(BaseModel):
    """
    Either ``resolution_id`` of a resolution made before, or the configuration inline.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    attachments: Annotated[
        list[str] | None,
        Field(description="Attachment version ids in load order (model runs only)"),
    ] = []
    client_request_id: str | None = None
    concurrency: int | None = None
    dataset_version_id: str | None = None
    execution_mode: Literal["agent", "oracle"] | None = None
    harness_params: dict[str, Any] | None = {}
    harness_version_id: str | None = None
    model_config_id: str | None = None
    model_revision: Annotated[
        int | None,
        Field(description="An earlier revision of the model configuration; unset: current"),
    ] = None
    name: str
    parameters: Annotated[
        dict[str, str | CredentialRef] | None,
        Field(
            description="Author parameter values; secret ones as a credential reference",
            validate_default=True,
        ),
    ] = {}
    plan_id: Annotated[
        str | None,
        Field(description="An experiment plan; fields set here win, the plan fills in the rest"),
    ] = None
    plan_revision: Annotated[
        int | None,
        Field(description="Refuse unless the plan is still at this revision"),
    ] = None
    repetitions: int | None = None
    resolution_id: str | None = None
    resources: Annotated[ResourceOverrides | None, Field(validate_default=True)] = {}
    run_deadline_hours: int | None = None
    source_run_id: Annotated[
        str | None,
        Field(
            description="Makes this a modified run of that run: its differences are recorded (start from GET /runs/{run_id}/request)"
        ),
    ] = None
    task_selection: Annotated[TaskSelection | None, Field(validate_default=True)] = {
        "mode": "all_eligible"
    }
    timeouts: Annotated[TimeoutOverrides | None, Field(validate_default=True)] = {}


class RunDetail(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    accepted_at: str
    allowed_actions: list[str]
    artifact_state: Literal["pending", "saving", "complete", "partial", "failed", "expired"]
    batch_id: str | None = None
    cleanup_state: Literal["pending", "running", "complete", "failed", "not_required"]
    client_request_id: str | None
    counts: RunCounts
    dataset_version_deletion: DeletionState | None
    dataset_version_id: str
    deadline_at: str
    deletion: Annotated[
        DeletionState | None,
        Field(description="Set when the run is in the recycle bin"),
    ]
    finished_at: str | None
    heartbeat_at: Annotated[
        str | None, Field(description="Last sign of life from the run's Runner")
    ]
    id: str
    links: dict[str, str]
    name: str
    operation_id: str
    owner: Owner
    owner_id: str
    pat_id: str | None
    plan_id: str | None = None
    plan_revision: int | None = None
    queue_reason: Annotated[
        str | None,
        Field(
            description="Why a queued run waits: CAPACITY_SLOTS, CAPACITY_CPU, CAPACITY_MEMORY or PROVIDER_LIMIT"
        ),
    ]
    relation: Literal["initial", "rerun", "modified"]
    result_completeness: Literal["none", "partial", "complete"]
    scoring: RunScoring | None
    snapshot: RunSnapshot
    source_run_id: str | None
    started_at: str | None
    state: Literal[
        "queued", "preparing", "running", "finalizing", "finished", "cancelled", "interrupted"
    ]
    stop_reason: str | None
    stop_requested: bool


class RunSummary(BaseModel):
    """
    06 section 5. At a terminal run planned = scored + count_as_failure + excluded +
    unfinished; while running, active and queued make up the rest.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    active_trials: int
    attempts: int
    bench_score: float | None
    bench_scored_tasks: int
    bench_task_coverage: Annotated[
        float | None, Field(description="Run tasks / tasks in the version")
    ]
    contract: ScoringContract
    count_as_failure_trials: int
    evaluation_coverage: float | None
    excluded_by_cause: dict[str, int]
    excluded_error_trials: int
    mean: float | None
    pass_rate: float | None
    passed_trials: int | None
    planned_trials: int
    queued_trials: int
    result_completeness: Literal["none", "partial", "complete"]
    retried_trials: int
    retry_count: Annotated[
        int, Field(description="Extra attempts beyond the first, over all trials")
    ]
    run_id: str
    scored_coverage: float | None
    scored_trials: int
    stddev: float | None
    task_count: int
    tasks: list[TaskSummary]
    unfinished_trials: int
    usage: UsageSummary


class Task(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    admission: TaskAdmission | None
    blockers: list[TaskBlocker]
    can_submit: bool
    content: TaskContent
    dataset_version_id: str
    id: str
    instruction: str
    local_preparation: LocalPreparation
    parameters: list[AuthorParameter]
    required_parameters: list[str] | None = []
    required_preparation: list[RequiredPreparation]
    resources: dict[str, Any]
    spec_digest: str | None
    task_key: str
    timeouts: dict[str, Any]
    warnings: list[TaskWarning]


class Trial(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    artifact_counts: ArtifactCounts
    artifact_state: Literal["pending", "saving", "complete", "partial", "failed", "expired"]
    attempts: list[Attempt]
    cleanup_state: Literal["pending", "running", "complete", "failed", "not_required"]
    id: str
    phase: str | None
    reason_code: str | None
    repetition_index: int
    result: TrialResult | None
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
    task_id: str
    task_key: str


class Batch(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    allowed_actions: list[str]
    client_request_id: str | None
    created_at: str
    id: str
    name: str
    operation_id: str
    owner_id: str
    owner_username: str | None
    pat_id: str | None
    progress: dict[str, int]
    runs: list[Run]
    status: str
    stop_requested: bool


class BatchCreate(BaseModel):
    """
    Runs accepted together, all or none; each costs one unit of PAT quota.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    client_request_id: str | None = None
    name: str
    runs: list[RunCreate]


class EnvelopeBatch(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: Batch
    meta: Meta


class EnvelopeExport(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: Export
    meta: Meta


class EnvelopeModelConfig(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: ModelConfig
    meta: Meta


class EnvelopeOperation(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: Operation
    meta: Meta


class EnvelopePreparation(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: Preparation
    meta: Meta


class EnvelopeRunDetail(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: RunDetail
    meta: Meta


class EnvelopeRunSummary(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: RunSummary
    meta: Meta


class EnvelopeRun(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: Run
    meta: Meta


class EnvelopeListBatch(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[Batch]
    meta: Meta


class EnvelopeListExport(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[Export]
    meta: Meta


class EnvelopeListModelConfig(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[ModelConfig]
    meta: Meta


class EnvelopeListOperation(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[Operation]
    meta: Meta


class EnvelopeListRun(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[Run]
    meta: Meta


class EnvelopeListTask(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[Task]
    meta: Meta


class EnvelopeListTrial(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    data: list[Trial]
    meta: Meta
