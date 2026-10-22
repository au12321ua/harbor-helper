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
  status: string;
  created_at: string;
}

export interface DatasetVersionDetail extends DatasetVersion {
  task_count: number;
  admitted_task_count: number;
  submittable_task_count: number;
}

export interface Dataset {
  id: string;
  source_kind: string;
  namespace: string;
  name: string;
  description: string;
  versions: DatasetVersion[];
}

export interface Task {
  id: string;
  task_key: string;
  admission: { id: string; state: string; revision: number } | null;
  content: {
    digest: string;
    availability: "unknown" | "available" | "unavailable";
    checked_at: string | null;
  };
  can_submit: boolean;
  blockers: Record<string, unknown>[];
}

export interface RunCreate {
  name: string;
  dataset_version_id: string;
  task_selection: { mode: "all_eligible" | "explicit"; task_ids?: string[] | null };
  repetitions: number;
  concurrency: number;
  client_request_id?: string | null;
}

export interface RunAccepted {
  run_id: string;
  operation_id: string;
  state: string;
  config_digest: string;
  snapshot_digest: string;
  planned_trials: number;
  links: Record<string, string>;
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
  owner: { username: string; display_name: string };
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
  status: string;
  created_at: string;
  expires_at: string | null;
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
