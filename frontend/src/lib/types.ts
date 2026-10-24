// Web types for the /api/v1 contract. Every type with a backend schema is an alias of the
// generated `schema.d.ts` (`npm run gen:api`, from ../openapi/maestro-v1.json), so a changed
// API that was not regenerated fails `npm run check:api` and the type check.
// Narrowings below cover only fields the backend declares as free-form JSON (dict[str, Any]).
import type { components } from "./schema";

type S = components["schemas"];

export type Role = S["User"]["role"];
export type Scope = S["Pat"]["scope"];

export type FieldErrorModel = S["FieldErrorModel"];
export type ErrorBody = S["ErrorBody"];
/** An error as the client hands it to pages: the server always sends field_errors. */
export type ApiErrorBody = ErrorBody & { field_errors: FieldErrorModel[] };
export type Meta = S["Meta"];

export type User = S["User"];
export type Me = S["Me"];
export type SessionInfo = S["SessionInfo"];
export type SetupStatus = S["SetupStatus"];

export type Invitation = S["Invitation"];
export type InvitationKind = Invitation["kind"];
export type IssuedInvitation = S["IssuedInvitation"];
export type InvitationInfo = S["InvitationInfo"];

export type Pat = S["Pat"];
export type IssuedPat = S["IssuedPat"];

export type Credential = S["Credential"];
export type CredentialKind = Credential["kind"];
export type CredentialName = S["CredentialName"];
export type MasterKeyStatus = S["MasterKeyStatus"];

export type DatasetVersion = S["DatasetVersion"];
export type Dataset = S["Dataset"];
export type DeletionState = S["DeletionState"];

// Backend: scoring_contract is dict[str, Any]; these are the keys the catalog sends.
export type DatasetVersionDetail = Omit<S["DatasetVersionDetail"], "scoring_contract"> & {
  scoring_contract: {
    source: "dataset_version" | "platform_default";
    name: string;
    direction: "higher_is_better" | "lower_is_better";
    passed: { rule: string; threshold: number } | null;
  };
};

export type Availability = S["TaskContent"]["availability"];
export type CacheState = S["LocalPreparation"]["cache_state"];
export type LocalPreparation = S["LocalPreparation"];
export type AuthorParameter = S["AuthorParameter"];
export type TaskBlocker = S["TaskBlocker"];
export type Task = S["Task"];

export type Operation = S["Operation"];
export type Preparation = S["Preparation"];

export type SourceDataset = S["SourceDataset"];
export type SourceVersion = S["SourceVersion"];
export type SourceVersionDetail = S["SourceVersionDetail"];

export type ExecutionMode = NonNullable<S["ConfigRequest"]["execution_mode"]>;
export type ParameterValue = string | { credential_id: string };

/** A run configuration request (03): unset fields are inherited from the layer below. */
export type ConfigRequest = S["ConfigRequest"];
export type RunCreate = S["RunCreate"];
export type RunRerun = S["RunRerun"];

// Backend: template is dict[str, Any] (a partial ConfigRequest, checked field by field).
export type Plan = Omit<S["Plan"], "template"> & { template: Partial<ConfigRequest> };

export type Batch = S["Batch"];
export type BatchProgress = Batch["progress"];
export type BatchAccepted = S["BatchAccepted"];
export type BatchCreate = S["BatchCreate"];

export type ConfigBlocker = S["ConfigBlocker"];

// Backend: each run row of the preview is dict[str, Any].
export type BatchPreview = Omit<S["BatchPreview"], "runs" | "pat_quota"> & {
  runs: {
    index: number;
    config_digest: string | null;
    planned_trials: number;
    labels?: Record<string, string>;
    blockers?: ConfigBlocker[];
  }[];
  pat_quota: { needed: number; left: number } | null;
};

export interface FieldSource {
  layer: "author" | "team" | "plan" | "override" | "harness";
  source_id?: string;
  revision?: number;
}

/** An attachment as a run configuration fixes it (inside the dict-typed effective config). */
export interface EffectiveAttachment {
  version_id: string;
  name: string;
  version: string;
  content_digest: string;
  effects: string[];
  provides: { tools: string[]; env: string[] };
  has_bootstrap: boolean;
}

export interface ExcludedTask {
  task_id: string;
  task_key: string;
  blockers: TaskBlocker[];
}

export interface CacheObservation {
  task_key: string;
  cache_state: string;
  action: string | null;
}

// Backend: effective_config, field_sources, the lists and request are dict[str, Any].
export type ConfigResolution = Omit<
  S["ConfigResolution"],
  | "request"
  | "effective_config"
  | "field_sources"
  | "baseline_differences"
  | "excluded_tasks"
  | "required_preparation"
  | "cache_observations"
  | "warnings"
> & {
  request: ConfigRequest;
  effective_config:
    | (Record<string, unknown> & {
        tasks?: {
          task_key: string;
          cpus: number;
          memory_mb: number;
          agent_timeout_sec: number | null;
        }[];
        repetitions?: number;
        concurrency?: number;
        run_deadline_hours?: number;
        parameters?: Record<string, { value?: string; credential_id?: string }>;
        attachments?: EffectiveAttachment[];
        bootstrap_timeout_sec?: number | null;
      })
    | null;
  field_sources: Record<string, FieldSource>;
  baseline_differences: { path: string; value: number; tasks_lower: number; tasks_higher: number }[];
  excluded_tasks: ExcludedTask[];
  required_preparation: { task_key: string; action: string; spec_digest: string }[];
  cache_observations: CacheObservation[];
  warnings: { code: string; path: string; message: string }[];
};

export type ModelProtocol = "openai-compatible" | "openai" | "anthropic";
export type ModelConfig = S["ModelConfig"];

export interface HarnessParameterSpec {
  type: "string" | "integer" | "number" | "boolean";
  description?: string;
  default?: unknown;
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
}

// Backend: parameter_schema is dict[str, Any] ({"parameters": {name: spec}}).
export type Harness = Omit<S["Harness"], "parameter_schema"> & {
  parameter_schema: { parameters: Record<string, HarnessParameterSpec> };
};
export type HarnessAdapter = S["HarnessAdapter"];

export type AttachmentFile = S["AttachmentFile"];
/** A published attachment package (03 section 6); its content never changes. */
export type Attachment = S["Attachment"];

export type PolicySetting = S["PolicySetting"];
export type TeamPolicy = S["TeamPolicy"];

// Backend: excluded_tasks and cache_observations are lists of dict[str, Any].
export type RunAccepted = Omit<S["RunAccepted"], "excluded_tasks" | "cache_observations"> & {
  excluded_tasks: ExcludedTask[];
  cache_observations: CacheObservation[];
};

export type RunScoring = S["RunScoring"];
// Backend: passed is dict[str, Any].
export type ScoringContract = S["ScoringContract"] & {
  passed: { rule?: string; threshold?: number; [key: string]: unknown } | null;
};
export type TaskSummary = S["TaskSummary"];
export type RunSummary = Omit<S["RunSummary"], "contract"> & { contract: ScoringContract };
export type RunCounts = S["RunCounts"];
export type Run = S["Run"];
export type RunStateName = Run["state"];
export type RunSnapshot = S["RunSnapshot"];
export type RunDetail = S["RunDetail"];

export type TrialResult = S["TrialResult"];
export type AttemptStep = S["AttemptStep"];
export type Attempt = S["Attempt"];
export type Trial = S["Trial"];
export type Artifact = S["Artifact"];

export type ExportRequest = S["ExportRequest"];
export type Export = S["Export"];

export type RecycleEntry = S["RecycleEntry"];
export type RecycleObjectType = RecycleEntry["object_type"];
export type AuditEvent = S["AuditEvent"];

export type Capabilities = S["Capabilities"];
export type CapacityOverview = S["CapacityOverview"];
export type Health = S["Health"];
