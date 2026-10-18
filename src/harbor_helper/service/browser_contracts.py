"""Browser HTTP DTOs. Machine views remain separately versioned in machine.py.

Optional fields describe actual omitted keys; defaults are never inserted into responses.
Open JSON is restricted to author/model configuration and framework-owned observations.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, create_model

from harbor_helper.persistence.statuses import AuditStatus, RunStatus, SubmissionStatus
from harbor_helper.service import dtos as m
from harbor_helper.service.attachment_contracts import AttachmentResult
from harbor_helper.service.primitives import LIMITS


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Limits = create_model("Limits", __base__=DTO, **{name: (int, ...) for name in LIMITS})  # ty: ignore[no-matching-overload]  # Runtime Pydantic field tuples generate the existing limits schema.
LimitsInput = create_model(  # ty: ignore[no-matching-overload]  # Runtime Pydantic field tuples generate the existing limits schema.
    "LimitsInput",
    __base__=DTO,
    **{name: (int, Field(default_factory=lambda: None)) for name in LIMITS},
)


class User(DTO):
    evidence_grant: bool = False
    id: str
    username: str
    role: Literal["admin", "member"]
    enabled: bool


class MachineUser(User):
    access_credential_id: str
    scopes: list[str]


class Initialized(DTO):
    initialized: bool


class LoginResult(DTO):
    token: str
    user: User


class LoggedOut(DTO):
    logged_out: bool
    tasks_continue: bool


class PasswordResult(DTO):
    changed: bool
    login_required: bool


class MasterStatus(DTO):
    generation: int
    rotated_at: float | None
    available: bool


class MasterRotated(MasterStatus):
    counts: dict[str, int]


class CredentialInfo(DTO):
    id: str
    version: int
    provider_id: str
    label: str
    enabled: bool
    created: float


class Provider(DTO):
    id: str
    version: int
    # Legacy configuration accepts JSON labels; render only after narrowing.
    name: JsonValue = None
    protocol: str
    endpoint: str
    enabled: bool


class Profile(DTO):
    id: str
    version: int
    name: JsonValue = None
    provider_id: str | int | float | bool
    credential_id: str | int | float | bool
    model: str
    params: dict[str, JsonValue]
    opencode_version: str
    enabled: bool


class Settings(DTO):
    team_name: str | None = None
    # Falsy JSON values are accepted by the legacy settings business validator.
    default_dataset_id: JsonValue = None
    default_model_profile: JsonValue = None


class Hub(DTO):
    mode: Literal["team", "anonymous"]
    version: int | None
    state: Literal["active", "disabled", "unset"]
    updated_at: float | None


class Issue(DTO):
    task: str | None = None
    service: str | None = None
    variable: str | None = None
    variables: list[str] = []
    reason: str
    message: str | None = None
    file: str | None = None


class Task(DTO):
    name: str
    package: str
    ref: str
    snapshot_digest: str | None = None


class Budget(DTO):
    task: str
    agent_seconds: float | None
    verifier_seconds: float | None
    agent_timeout_sec: float | None = None
    verifier_timeout_sec: float | None = None
    environment_build_timeout_sec: float | None = None
    environment_start_timeout_sec: float | None = None


class Image(DTO):
    task: str
    role: str
    reference: str
    cached: bool | None
    image_id: str | None


class VariableUse(DTO):
    task: str
    service: str | None = None
    file: str
    required: bool
    default: str | None = None


class Discovery(DTO):
    source: str
    variables: dict[str, list[VariableUse]]
    fixed_names: list[str]
    blocked: list[Issue]
    budgets: list[Budget]
    images: list[Image]


class CheckedTask(Task):
    discovery: Discovery


class Scope(DTO):
    mode: str
    complete: bool = False
    total: int = 0
    unknown: int = 0
    tasks: list[Task]


class AuthorParameters(DTO):
    id: str
    version: int
    values: dict[str, str]
    status: str
    source: str | None = None
    discovery: Discovery | None = None
    checked_tasks: list[CheckedTask] = []
    scope: Scope | None = None
    last_check_scope: Scope | None = None
    requested_task_names: list[str] | None = None
    issues: list[Issue] = []
    checked: float | None = None


class Dataset(DTO):
    id: str
    version: int
    name: str
    enabled: bool
    reference: str
    status: str
    ready: bool = False
    resolved: str | None = None
    checked: float | None = None
    source_version: int | None = None
    error: dict[str, str] | None = None
    tasks: list[Task] = []
    author_parameters: AuthorParameters | None = None
    digest: str | None = None
    readiness_error: dict[str, str] | None = None


class CatalogDataset(Dataset):
    author_parameters: AuthorParameters  # ty: ignore[invalid-mutable-override]  # Pydantic response specialization; keep the strict wire schema.
    ready: bool
    readiness_error: dict[str, str] | None


class Catalog(DTO):
    datasets: list[CatalogDataset]
    settings: Settings
    hub: Hub
    attachments: list[m.AttachmentEntry]
    providers: list[Provider]
    credentials: list[CredentialInfo]
    model_profiles: list[Profile]
    limits: Limits
    default_dataset: str
    readiness: m.Readiness


class Accepted(DTO):
    operation_id: str | None = None
    idempotency_key: str | None = None
    id: str
    user_id: str | None
    access_credential_id: str | None
    submitter: str
    operation: m.Operation
    request: m.SubmissionInput
    run_id: str | None
    status: SubmissionStatus
    created: float
    error: str | None
    parent: str | None
    attachment: m.AttachmentBinding
    diagnosis: list[Issue] | None
    retry_changes: dict[str, dict[str, JsonValue]]


class RunSummary(DTO):
    id: str
    name: str
    dataset_name: str | None
    status: RunStatus
    created: float
    started: float | None
    finished: float | None
    parent: str | None
    submitter: str
    user_id: str | None
    concurrency: int
    cancel: bool
    audit_status: AuditStatus
    audit_reason: str | None
    reason: str | None
    dataset: str
    agent: str
    model_profile: str | None
    attachment: m.AttachmentBinding


class Runs(DTO):
    runs: list[RunSummary]
    submissions: list[Accepted]


class MachineRuns(DTO):
    runs: list[m.MachineState]
    submissions: list[m.MachineState]


class UsageRow(DTO):
    submitter: str
    submissions: int
    runs: int
    wall_seconds: float


class CancelResult(m.CancelResult):
    status: RunStatus  # ty: ignore[invalid-mutable-override]  # Pydantic response specialization; keep the strict wire schema.


class Usage(DTO):
    total_submissions: int
    total_runs: int
    active_jobs: int
    active_trials: int
    queued_jobs: int
    by_submitter: list[UsageRow]
    cost: Literal["unknown"]


class Logs(DTO):
    text: str
    truncated: bool = False


class Deleted(DTO):
    id: str
    deleted: bool


class AccessCredential(DTO):
    id: str
    user_id: str
    name: str
    scopes: list[str]
    created: float
    expires: float
    revoked: float | None
    last_used: float | None


class AccessResult(DTO):
    credential: AccessCredential
    token: str


class Revoked(DTO):
    id: str
    revoked: bool


class DockerImage(DTO):
    reference: str


class Docker(DTO):
    checked_at: float
    images: list[DockerImage]
    truncated: bool
    state: str
    message: str


class Phase(DTO):
    phase: str
    reached: bool = False
    status: str | None = None
    seconds: float | None


class Installation(DTO):
    missing_dependencies: list[str]
    reused: bool
    strategy: str | None = None
    stage: str | None = None
    status: str | None = None
    cache_hit: bool | None = None
    preparation_error_type: str | None = None
    preparation_seconds: float | None = None
    version: str | None = None
    binary_sha256: str | None = None
    source: str | None = None


class Diagnosis(DTO):
    phase: str
    model_status: str
    hint: str
    phases: list[Phase]
    compose: list[Phase] | Literal["unknown"]
    startup_multiplier: int
    agent_installation: Installation | None


class Attempt(DTO):
    task: str
    valid: bool
    rewards: dict[str, float] | None
    trial: str | None = None
    agent_exit_code: str | None = None
    framework_exception: dict[str, JsonValue] | None = None
    observed_rewards: dict[str, JsonValue] | None = None
    exception: dict[str, JsonValue] | None = None
    agent_info: dict[str, JsonValue] | None = None
    diagnosis: Diagnosis | None = None
    phase_timings: dict[str, JsonValue] = {}


class TaskReport(DTO):
    task: str
    expected_attempts: int
    valid_attempts: int
    observed_attempts: int
    mean_rewards: dict[str, float] | None
    attempts: list[Attempt]


class Report(DTO):
    run_id: str
    status: RunStatus
    reason: str | None
    complete: bool
    expected_attempts: int
    valid_attempts: int
    invalid_attempts: int
    missing_attempts: int
    source: dict[str, JsonValue]
    harbor_version: str
    environment_observations: list[dict[str, JsonValue]] | Literal["unknown"]
    tasks: list[TaskReport]
    unexpected_trials: list[Attempt]


class StartupTask(DTO):
    task: str
    agent_seconds: float | None = None
    verifier_seconds: float | None = None
    author_build_timeout_sec: float | Literal["unknown"]
    start_wait_timeout_sec: float | Literal["unknown"]
    author_network_mode: str


class StartupPolicy(DTO):
    multiplier: int
    wall_seconds: int
    scope: str
    tasks: list[StartupTask]


class Effective(DTO):
    agent: str
    dataset: str
    attempts: int
    concurrency: int
    wall_seconds: int
    environment_build_timeout_multiplier: int = 1
    task_filter: str | None
    model: dict[str, JsonValue] | None
    max_cpus_per_trial: int | float
    max_memory_mb_per_trial: int
    author_env: dict[str, str] = {}
    agent_tool_preparation: str | None = None


class Binding(DTO):
    user_id: str | None = None
    submitter: str | None = None
    submission_id: str | None = None
    name: str | None = None
    access_credential_id: str | None = None
    provider_id: str | None = None
    provider_version: int | None = None
    credential_id: str | None = None
    credential_version: int | None = None
    model_profile: str | None = None
    model_profile_version: int | None = None
    dataset_id: str | None = None
    dataset_version: int | None = None
    dataset_name: str | None = None
    source_version: int | None = None
    author_parameters_version: int | None = None
    author_parameters_source: str | None = None
    author_input_check: bool | None = None
    author_input_diagnostics: Discovery | None = None
    author_input_issues: list[Issue] | None = None
    retry_changes: dict[str, dict[str, JsonValue]] = {}
    recovered_submission: str | None = None
    attachment_id: str | None = None
    attachment_version_id: str | None = None
    bundle_id: str | None = None
    bundle_digest: str | None = None
    attachment_lineage: str | None = None


class Manifest(DTO):
    startup_policy: StartupPolicy
    effective: Effective
    source: dict[str, JsonValue]
    parent: str | None
    service: Binding | None
    bundle_digest: str | None
    model_checkpoint_actual: str | None
    hard_budgets: dict[str, int | str] | None


class FailureDiagnosis(DTO):
    code: str
    phase: str
    message: str


class Artifact(Deleted):
    name: str


class RunDetail(DTO):
    failure_diagnosis: FailureDiagnosis | None
    row: RunSummary
    manifest: Manifest
    artifacts: list[Artifact]
    report: Report | None


class Comparison(DTO):
    left: str
    right: str
    comparable: bool
    reasons: list[str]
    config_changes: dict[str, dict[str, JsonValue]]
    environment_observations: dict[str, JsonValue]
    bundle_change: dict[str, str | None]
    attachment_inputs: dict[str, m.CompareAttachment]
    tasks: list[m.MetricDelta]
    mean_task_delta: dict[str, float] | None


# Schema-only request descriptions for legacy dict handlers. Their existing business
# validators retain responsibility for acceptance, defaults and precise error codes.
class MaintenanceInput(DTO):
    paused: bool = False
    reason: str = ""
    retry_at: float | None = None


class UserUpdate(DTO):
    enabled: bool | None = None
    password: str | None = None


class AuthorCheck(DTO):
    task_names: list[str] | None = None


class AuthorSave(DTO):
    values: dict[str, str]


class DatasetInput(DTO):
    id: str | None = None
    name: str
    enabled: bool = True
    reference: str


class ProviderInput(DTO):
    id: str | None = None
    version: int | None = None
    # Legacy configuration accepts JSON labels; render only after narrowing.
    name: JsonValue = None
    protocol: str
    endpoint: str
    enabled: bool = True


class ProfileInput(DTO):
    id: str | None = None
    version: int | None = None
    name: JsonValue = None
    provider_id: str | int | float | bool
    credential_id: str | int | float | bool
    model: str
    params: dict[str, JsonValue] = {}
    opencode_version: str = "1.18.35"
    enabled: bool = True


class AccessCapabilities(DTO):
    scopes: list[str]
    evidence_grant: bool


class GrantResult(DTO):
    user_id: str
    evidence_grant: bool


class OperationRecord(DTO):
    id: str
    user_id: str
    operation: str
    idem: str
    request: dict
    created: float
    updated: float
    attempts: int
    status: str
    result: dict | None
    error: dict | None
    recent: list[dict]
    summarized_attempts: int


class OperationHistory(DTO):
    operations: list[OperationRecord]
    total: int
    offset: int
    next_offset: int | None
    attempt_limit: int


class Material(DTO):
    id: str
    name: str
    category: str
    bytes: int
    sha256: str
    status: str
    source: str
    processing: str | None


class Materials(DTO):
    run_id: str
    state: str
    files: list[Material]
    session_coverage: list[dict] = []
    scope: str | None = None
    limitations: list[str] = []
    legacy: bool = False


BROWSER = {
    "access_capabilities": AccessCapabilities,
    "evidence_grant": GrantResult,
    "operation_history": OperationHistory,
    "evidence_manifest": Materials,
    "setup_status": Initialized,
    "setup": Initialized,
    "login": LoginResult,
    "logout": LoggedOut,
    "password_change": PasswordResult,
    "me": User,
    "catalog": Catalog,
    "usage": Usage,
    "runs": Runs,
    "submission": Accepted,
    "submit": Accepted,
    "recover_submission": Accepted,
    "cancel_submission": Accepted,
    "rerun": Accepted,
    "retry_run": Accepted,
    "lookup_submission": Accepted,
    "run": RunDetail,
    "report": Report | None,
    "download_report": Report,
    "logs": Logs,
    "compare": Comparison,
    "cancel": CancelResult,
    "readiness": m.Readiness,
    "set_maintenance": m.MaintenanceInfo,
    "shutdown_status": m.ShutdownStatus,
    "shutdown_request": m.ShutdownStatus,
    "attachments": m.AttachmentCatalog,
    "attachment_lookup": AttachmentResult,
    "create_attachment": AttachmentResult,
    "publish_attachment": AttachmentResult,
    "derive_attachment": AttachmentResult,
    "update_attachment": m.Updated,
    "update_attachment_version": m.Updated,
    "delete_artifact": Deleted,
    "users": list[User],
    "add_user": User,
    "update_user": User,
    "docker_discovery": Docker,
    "inspect_author_inputs": AuthorParameters,
    "save_author_inputs": AuthorParameters,
    "save_catalog": Dataset,
    "verify_catalog": Dataset,
    "settings": Settings,
    "hub": Hub,
    "hub_disable": Hub,
    "providers": list[Provider],
    "provider": Provider,
    "profiles": list[Profile],
    "profile": Profile,
    "master_key_status": MasterStatus,
    "rotate_master_key": MasterRotated,
    "credentials": list[CredentialInfo],
    "credential": CredentialInfo,
    "rotate": CredentialInfo,
    "disable": CredentialInfo,
    "limits": Limits,
    "set_limits": Limits,
    "issue_access": AccessResult,
    "list_access": list[AccessCredential],
    "list_all_access": list[AccessCredential],
    "revoke_access": Revoked,
}
MACHINE = {"me": MachineUser, "catalog": m.Discovery}
REQUESTS = {
    "set_maintenance": MaintenanceInput,
    "shutdown_request": m.ShutdownInput,
    "update_user": UserUpdate,
    "inspect_author_inputs": AuthorCheck | None,
    "save_author_inputs": AuthorSave,
    "save_catalog": DatasetInput,
    "settings": Settings,
    "provider": ProviderInput,
    "profile": ProfileInput,
    "set_limits": LimitsInput,
}
