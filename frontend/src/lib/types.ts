// Mirrors src/maestro/api/models.py (the OpenAPI contract). Keep field names identical.

export type Role = "admin" | "member";
export type Scope = "read" | "experiment";

export interface FieldErrorModel {
  path: string;
  code: string;
  message?: string | null;
  limit?: number | null;
}

export interface ErrorBody {
  code: string;
  message: string;
  stage?: string | null;
  field_errors: FieldErrorModel[];
  retryable: boolean;
  suggested_actions: Record<string, unknown>[];
}

export interface Meta {
  request_id: string;
  next_cursor?: string | null;
}

export interface User {
  id: string;
  username: string;
  display_name: string;
  role: Role;
  status: "active" | "disabled";
  revision: number;
  created_at: string;
  disabled_at: string | null;
}

export interface Me extends User {
  auth_channel: "web_session" | "pat";
  pat_id: string | null;
  pat_scope: Scope | null;
}

export interface SessionInfo {
  user: Me;
  csrf_token: string | null;
}

export type InvitationKind = "invitation" | "password_reset";

export interface Invitation {
  id: string;
  role: Role;
  note: string;
  kind: InvitationKind;
  target_user_id: string | null;
  state: "pending" | "used" | "revoked" | "expired";
  created_by: string;
  created_at: string;
  expires_at: string;
  used_at: string | null;
  used_by: string | null;
}

export interface IssuedInvitation extends Invitation {
  token: string;
}

export interface InvitationInfo {
  kind: InvitationKind;
  role: Role;
  username: string | null;
  expires_at: string;
}

export interface Pat {
  id: string;
  name: string;
  scope: Scope;
  token_prefix: string;
  state: "active" | "revoked" | "expired";
  expires_at: string;
  run_limit: number;
  accepted_runs: number;
  remaining_runs: number;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  revision: number;
}

export interface IssuedPat extends Pat {
  token: string;
}

export type CredentialKind = "model_api_key" | "hub_token" | "generic_secret";

export interface Credential {
  id: string;
  name: string;
  kind: CredentialKind;
  provider: string;
  description: string;
  enabled: boolean;
  revision: number;
  key_version: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface MasterKeyStatus {
  initialized: boolean;
  available: boolean;
  generation: number | null;
  rotated_at: string | null;
  reencrypted_credentials?: number | null;
}

export interface DatasetVersion {
  id: string;
  dataset_id: string;
  upstream_ref: string;
  ref_kind: string;
  resolved_digest: string;
  materialization_digest: string | null;
  status: string;
  description: string;
  created_at: string;
  created_by: string | null;
  operation_id: string | null;
  task_count: number;
  admitted_task_count: number;
  submittable_task_count: number;
  cache_ready_task_count: number;
}

export interface DatasetVersionDetail extends DatasetVersion {
  namespace: string;
  name: string;
  first_preparation_operation_id: string | null;
  deletion: DeletionState | null;
  scoring_contract: {
    source: "dataset_version" | "platform_default";
    name: string;
    direction: "higher_is_better" | "lower_is_better";
    passed: { rule: string; threshold: number } | null;
  };
}

export interface Dataset {
  id: string;
  source_kind: string;
  namespace: string;
  name: string;
  description: string;
  credential_id: string | null;
  versions: DatasetVersion[];
}

export type Availability = "unknown" | "available" | "unavailable";
export type CacheState = "absent" | "restoring" | "ready" | "stale";

export interface LocalPreparation {
  id: string | null;
  location_id: string;
  cache_state: CacheState;
  last_restore_error: Record<string, unknown> | null;
  operation_id: string | null;
  prepared_at: string | null;
  last_used_at: string | null;
}

export interface AuthorParameter {
  name: string;
  default: string | null;
  required: boolean;
  sensitive: boolean;
  description: string;
  hard_constraints: Record<string, unknown>;
  used_in: string[];
}

export interface TaskBlocker {
  code: string;
  admission_state?: string | null;
  first_preparation_error?: Record<string, unknown> | null;
  resource_kind?: string | null;
  expected_digest?: string | null;
  evidence?: Record<string, unknown> | null;
  parameters?: string[] | null;
  issues?: Record<string, unknown>[] | null;
}

export interface Task {
  id: string;
  dataset_version_id: string;
  task_key: string;
  admission: { id: string; state: string; revision: number; approved_at: string | null } | null;
  content: {
    digest: string;
    material_digest: string | null;
    availability: Availability;
    checked_at: string | null;
    resources: {
      resource_kind: string;
      digest: string;
      availability: Availability;
      checked_at: string | null;
    }[];
  };
  local_preparation: LocalPreparation;
  spec_digest: string | null;
  resources: Record<string, unknown>;
  timeouts: Record<string, unknown>;
  parameters: AuthorParameter[];
  required_parameters: string[];
  instruction: string;
  can_submit: boolean;
  blockers: TaskBlocker[];
  warnings: { code: string; action: string }[];
  required_preparation: { action: string; spec_digest: string }[];
}

export interface Operation {
  id: string;
  kind: string;
  resource: { type: string; id: string } | null;
  owner_id: string | null;
  status: "accepted" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";
  phase: string | null;
  progress: Record<string, unknown>;
  error: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  allowed_actions: string[];
  links: Record<string, string>;
  revision: number;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}

export interface SourceDataset {
  namespace: string;
  name: string;
  visibility?: string | null;
}

export interface SourceVersion {
  ref: string;
  revision?: number | null;
  tags: string[];
  resolved_digest: string;
  published_at?: string | null;
  yanked: boolean;
}

export interface SourceVersionDetail {
  namespace: string;
  name: string;
  upstream_ref: string;
  ref_kind: string;
  resolved_digest: string;
  description: string;
  tasks: { task_key: string; content_digest: string }[];
  existing_version_id: string | null;
}

export type ExecutionMode = "agent" | "oracle";
export type ParameterValue = string | { credential_id: string };

/** A run configuration request (03): unset fields are inherited from the layer below. */
export interface ConfigRequest {
  dataset_version_id: string;
  execution_mode: ExecutionMode;
  task_selection: { mode: "all_eligible" | "explicit"; task_ids?: string[] | null };
  model_config_id?: string | null;
  harness_version_id?: string | null;
  harness_params?: Record<string, unknown>;
  repetitions?: number | null;
  concurrency?: number | null;
  run_deadline_hours?: number | null;
  resources?: { cpus?: number | null; memory_mb?: number | null };
  timeouts?: { agent_sec?: number | null; verifier_sec?: number | null };
  parameters?: Record<string, ParameterValue>;
}

export interface RunCreate {
  name: string;
  resolution_id: string;
  client_request_id?: string | null;
}

export interface ConfigBlocker {
  code: string;
  path: string;
  message: string;
  [extra: string]: unknown;
}

export interface FieldSource {
  layer: "author" | "team" | "plan" | "override" | "harness";
  source_id?: string;
  revision?: number;
}

export interface ConfigResolution {
  resolution_id: string;
  created_at: string;
  expires_at: string;
  request: ConfigRequest;
  effective_config: Record<string, unknown> & {
    tasks?: { task_key: string; cpus: number; memory_mb: number; agent_timeout_sec: number | null }[];
    repetitions?: number;
    concurrency?: number;
    run_deadline_hours?: number;
    parameters?: Record<string, { value?: string; credential_id?: string }>;
  } | null;
  field_sources: Record<string, FieldSource>;
  baseline_differences: { path: string; value: number; tasks_lower: number; tasks_higher: number }[];
  excluded_tasks: { task_id: string; task_key: string; blockers: TaskBlocker[] }[];
  required_preparation: { task_key: string; action: string; spec_digest: string }[];
  cache_observations: { task_key: string; cache_state: string; action: string | null }[];
  warnings: { code: string; path: string; message: string }[];
  blockers: ConfigBlocker[];
  config_digest: string | null;
  reference_revisions: Record<string, unknown>;
  labels: Record<string, string>;
  planned_trials: number;
}

/** A usable team credential as everyone sees it: the name, never the value. */
export interface CredentialName {
  id: string;
  name: string;
  kind: string;
  provider: string;
  description: string;
}

export type ModelProtocol = "openai-compatible" | "openai" | "anthropic";

export interface ModelConfig {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  revision: number;
  provider: string;
  protocol: ModelProtocol;
  endpoint: string;
  model_id: string;
  params: Record<string, unknown>;
  credential_bound: boolean;
  credential_problem: string | null;
  credential_id?: string | null;
  credential_name?: string | null;
  created_at: string;
  updated_at: string;
}

export interface HarnessParameterSpec {
  type: "string" | "integer" | "number" | "boolean";
  description?: string;
  default?: unknown;
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
}

export interface Harness {
  id: string;
  name: string;
  version: string;
  agent: string;
  description: string;
  protocols: ModelProtocol[];
  parameter_schema: { parameters: Record<string, HarnessParameterSpec> };
  content_digest: string;
  enabled: boolean;
  created_at: string;
}

export interface HarnessAdapter {
  agent: string;
  protocols: ModelProtocol[];
  /** Parameters a harness version may declare; null means any. */
  parameters: string[] | null;
}

export interface PolicySetting {
  name: string;
  group: "runs" | "access" | "retention";
  description: string;
  built_in: number;
  min: number;
  max: number;
}

export interface TeamPolicy {
  revision: number;
  values: Record<string, number>;
  settings: PolicySetting[];
}

export interface RunAccepted {
  run_id: string;
  operation_id: string;
  state: string;
  config_digest: string;
  snapshot_digest: string;
  planned_trials: number;
  excluded_tasks: { task_id: string; task_key: string; blockers: TaskBlocker[] }[];
  cache_observations: { task_key: string; cache_state: string; action: string | null }[];
  links: Record<string, string>;
}

export interface DeletionState {
  state: "recycled" | "purged";
  deleted_at: string;
  purged_at: string | null;
}

export interface RunScoring {
  metric_id: string;
  planned_trials: number;
  scored_trials: number;
  excluded_error_trials: number;
  unfinished_trials: number;
  passed_trials: number | null;
  mean: number | null;
  stddev: number | null;
  pass_rate: number | null;
  scored_coverage: number | null;
  bench_score: number | null;
}

export interface ScoringContract {
  contract_version: number;
  source: "platform_default" | "dataset_version";
  metric_id: string;
  name: string;
  unit: string | null;
  direction: "higher_is_better" | "lower_is_better";
  passed: { rule?: string; threshold?: number; [key: string]: unknown } | null;
  task_aggregation: string;
  bench_aggregation: string;
  count_as_failure: string[];
}

export interface TaskSummary {
  task_key: string;
  planned_trials: number;
  scored_trials: number;
  mean: number | null;
  stddev: number | null;
  passed_trials: number | null;
  partial: boolean;
  excluded_trials: number;
  failure_causes: string[];
}

export interface RunSummary {
  run_id: string;
  contract: ScoringContract;
  planned_trials: number;
  scored_trials: number;
  count_as_failure_trials: number;
  excluded_error_trials: number;
  unfinished_trials: number;
  active_trials: number;
  queued_trials: number;
  passed_trials: number | null;
  mean: number | null;
  stddev: number | null;
  pass_rate: number | null;
  scored_coverage: number | null;
  evaluation_coverage: number | null;
  bench_task_coverage: number | null;
  bench_score: number | null;
  bench_scored_tasks: number;
  task_count: number;
  result_completeness: "none" | "partial" | "complete";
  excluded_by_cause: Record<string, number>;
  attempts: number;
  retried_trials: number;
  retry_count: number;
  usage: { known_trials: number; unknown_trials: number; known_totals: Record<string, number> };
  tasks: TaskSummary[];
}

export interface RunCounts {
  planned: number;
  terminal: number;
  scored: number;
  errors: number;
  not_started: number;
  cancelled: number;
  interrupted: number;
  active: number;
  queued: number;
}

export type RunStateName =
  | "queued"
  | "preparing"
  | "running"
  | "finalizing"
  | "finished"
  | "cancelled"
  | "interrupted";

export interface Run {
  id: string;
  name: string;
  owner_id: string;
  owner: { username: string; display_name: string; deleted: boolean };
  pat_id: string | null;
  relation: "initial" | "rerun" | "modified";
  source_run_id: string | null;
  dataset_version_id: string;
  operation_id: string;
  client_request_id: string | null;
  state: RunStateName;
  result_completeness: "none" | "partial" | "complete";
  artifact_state: "pending" | "saving" | "complete" | "partial" | "failed" | "expired";
  cleanup_state: "pending" | "running" | "complete" | "failed" | "not_required";
  stop_requested: boolean;
  stop_reason: string | null;
  /** Why a queued run waits: CAPACITY_SLOTS, CAPACITY_CPU, CAPACITY_MEMORY, PROVIDER_LIMIT. */
  queue_reason: string | null;
  /** Last sign of life from the run's Runner process. */
  heartbeat_at: string | null;
  counts: RunCounts;
  /** Headline statistics; null before any summary exists. */
  scoring: RunScoring | null;
  deletion: DeletionState | null;
  dataset_version_deletion: DeletionState | null;
  accepted_at: string;
  started_at: string | null;
  finished_at: string | null;
  deadline_at: string;
  allowed_actions: string[];
  links: Record<string, string>;
}

export interface RunSnapshot {
  schema_version: number;
  effective: Record<string, unknown>;
  provenance: Record<string, unknown>;
  policy: Record<string, unknown>;
  config_digest: string;
  snapshot_digest: string;
  comparison_digest: string;
}

export interface RunDetail extends Run {
  snapshot: RunSnapshot;
}

export interface TrialResult {
  raw_score: number | null;
  reward_valid: boolean;
  score: number | null;
  failure_cause: string | null;
  exception_type: string | null;
  verifier_status: string | null;
  policy_version: string;
  attempt_id: string;
}

export interface AttemptStep {
  /** starting, environment, agent, collecting or verifying */
  step: string;
  at: string;
}

export interface Attempt {
  id: string;
  attempt_index: number;
  state: string;
  phase: string | null;
  /** Step start times; a step ends when the next one starts or the attempt ends. */
  steps: AttemptStep[];
  executor_ref: Record<string, unknown> | null;
  started_at: string;
  ended_at: string | null;
  error: Record<string, unknown> | null;
}

export interface Trial {
  id: string;
  task_id: string;
  task_key: string;
  repetition_index: number;
  state:
    | "queued"
    | "preparing"
    | "executing"
    | "verifying"
    | "scored"
    | "execution_error"
    | "not_started"
    | "cancelled"
    | "interrupted";
  phase: string | null;
  reason_code: string | null;
  artifact_state: string;
  artifact_counts: { available: number; failed: number; expired: number };
  cleanup_state: string;
  result: TrialResult | null;
  attempts: Attempt[];
}

export interface Artifact {
  id: string;
  run_id: string;
  trial_id: string | null;
  attempt_id: string | null;
  kind: string;
  relative_path: string;
  digest: string | null;
  size_bytes: number | null;
  status: "pending" | "available" | "failed" | "deleting" | "expired" | "unavailable" | "deleted";
  /** e.g. RETENTION_EXPIRED, STORAGE_CONTENT_MISSING, DELETED. */
  status_reason: string | null;
  created_at: string;
  /** Null until the trial ends; then trial end + retention. */
  expires_at: string | null;
}

export interface ExportRequest {
  run_ids: string[];
  include_artifacts: boolean;
  artifact_kinds: string[] | null;
  task_keys: string[] | null;
}

export interface Export {
  id: string;
  owner_id: string;
  operation_id: string;
  state: "queued" | "building" | "ready" | "failed" | "expired";
  request: ExportRequest;
  size_bytes: number | null;
  digest: string | null;
  /** runs, files, missing, warnings, artifact_bytes … */
  summary: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  created_at: string;
  finished_at: string | null;
  expires_at: string | null;
  links: Record<string, string>;
}

export type RecycleObjectType =
  | "run"
  | "artifact"
  | "dataset"
  | "dataset_version"
  | "credential"
  | "user"
  | "pat"
  | "model_config"
  | "harness_version";

export interface RecycleEntry {
  id: string;
  object_type: RecycleObjectType;
  object_id: string;
  label: string;
  owner_id: string | null;
  owner_username: string | null;
  state: "recycled" | "purged" | "restored";
  deleted_by: string;
  deleted_by_username: string | null;
  deleted_at: string;
  purged_by: string | null;
  purged_at: string | null;
  detail: Record<string, unknown>;
}

export interface AuditEvent {
  id: string;
  actor_user_id: string | null;
  pat_id: string | null;
  auth_channel: string | null;
  action: string;
  object_type: string | null;
  object_id: string | null;
  outcome: string;
  detail: Record<string, unknown> | null;
  request_id: string | null;
  created_at: string;
}

export interface Capabilities {
  api_version: string;
  service_version: string;
  schema_revision: string;
  features: Record<string, boolean>;
  limits: Record<string, number>;
  team_policy_revision: number;
  auth: Record<string, unknown>;
  actions: Record<string, Record<string, unknown>>;
  execution: Record<string, unknown>;
}

export interface CapacityOverview {
  host: { slots: number; cpus: number; memory_mb: number };
  in_use: { slots: number; cpus: number; memory_mb: number };
  providers: { provider: string; max_concurrent_trials: number | null; in_use: number }[];
}

export interface Health {
  status: string;
  accepting_runs?: boolean | null;
  detail: Record<string, unknown>;
}
