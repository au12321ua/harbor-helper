"""Logical data dictionary of 01 section 4 as SQLAlchemy Core tables.

Migrations are the source of truth for the deployed schema; this metadata must
match the latest migration (checked by tests). Times are RFC 3339 text in UTC,
CPU in millicores, memory and disk in bytes, limits in seconds.
"""

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


def _id():
    return Column("id", String(40), primary_key=True)


def _ref(name, table, nullable=False, **kw):
    return Column(name, String(40), ForeignKey(f"{table}.id"), nullable=nullable, **kw)


def _time(name, nullable=False):
    return Column(name, String(32), nullable=nullable)


def _json(name, nullable=False):
    return Column(name, JSON, nullable=nullable)


# --- Identity (09) -------------------------------------------------------------

users = Table(
    "users",
    metadata,
    _id(),
    Column("username", String(64), nullable=False, unique=True),
    Column("display_name", String(128), nullable=False),
    Column("role", String(16), nullable=False),
    Column("status", String(16), nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("revision", Integer, nullable=False),
    _ref("created_by", "users", nullable=True),
    _time("created_at"),
    _time("updated_at"),
    _time("disabled_at", nullable=True),
    CheckConstraint("role IN ('admin','member')", name="role"),
    CheckConstraint("status IN ('active','disabled')", name="status"),
)

invitations = Table(
    "invitations",
    metadata,
    _id(),
    Column("token_hash", String(80), nullable=False, unique=True),
    Column("role", String(16), nullable=False),
    Column("note", String(256), nullable=False),
    # Set for a password-reset link issued to an existing account.
    _ref("target_user_id", "users", nullable=True),
    _ref("created_by", "users"),
    _time("created_at"),
    _time("expires_at"),
    _time("used_at", nullable=True),
    _ref("used_by", "users", nullable=True),
    _time("revoked_at", nullable=True),
    CheckConstraint("role IN ('admin','member')", name="role"),
)

# Web sessions are not in 01's dictionary; 09 section 4 requires server-side
# revocation, so sessions are stored by token hash like PATs.
sessions = Table(
    "sessions",
    metadata,
    _id(),
    Column("token_hash", String(80), nullable=False, unique=True),
    _ref("user_id", "users"),
    _time("created_at"),
    _time("expires_at"),
    _time("last_seen_at"),
    _time("revoked_at", nullable=True),
    Index("ix_sessions_user", "user_id"),
)

pats = Table(
    "pats",
    metadata,
    _id(),
    _ref("owner_id", "users"),
    Column("name", String(128), nullable=False),
    Column("token_hash", String(80), nullable=False, unique=True),
    Column("token_prefix", String(32), nullable=False),
    Column("scope", String(16), nullable=False),
    _time("expires_at"),
    Column("run_limit", Integer, nullable=False),
    Column("accepted_runs", Integer, nullable=False),
    Column("revision", Integer, nullable=False),
    _time("created_at"),
    _time("last_used_at", nullable=True),
    _time("revoked_at", nullable=True),
    CheckConstraint("scope IN ('read','experiment')", name="scope"),
    CheckConstraint("run_limit >= 0 AND accepted_runs >= 0", name="counts"),
    CheckConstraint("accepted_runs <= run_limit", name="limit"),
    Index("ix_pats_owner", "owner_id", "created_at"),
)

# --- Credentials and master key (09 section 4) ---------------------------------

master_key_state = Table(
    "master_key_state",
    metadata,
    Column("singleton", Integer, primary_key=True),
    Column("generation", Integer, nullable=False),
    Column("basename", String(160), nullable=False),
    Column("kcv", String(64), nullable=False),
    _time("rotated_at", nullable=True),
    CheckConstraint("singleton = 1", name="singleton"),
    CheckConstraint("generation >= 1", name="generation"),
)

credentials = Table(
    "credentials",
    metadata,
    _id(),
    Column("name", String(128), nullable=False, unique=True),
    Column("kind", String(32), nullable=False),
    Column("provider", String(64), nullable=False),
    Column("description", String(512), nullable=False),
    Column("nonce", LargeBinary, nullable=False),
    Column("encrypted_payload", LargeBinary, nullable=False),
    Column("key_version", Integer, nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("revision", Integer, nullable=False),
    _ref("created_by", "users"),
    _time("created_at"),
    _time("updated_at"),
    CheckConstraint("kind IN ('model_api_key','hub_token','generic_secret')", name="kind"),
)

# --- Catalog and preparation (02) ----------------------------------------------

datasets = Table(
    "datasets",
    metadata,
    _id(),
    Column("source_kind", String(32), nullable=False),
    Column("namespace", String(128), nullable=False),
    Column("name", String(128), nullable=False),
    Column("description", Text, nullable=False),
    Column("enabled", Boolean, nullable=False),
    _time("created_at"),
    UniqueConstraint("source_kind", "namespace", "name"),
)

dataset_versions = Table(
    "dataset_versions",
    metadata,
    _id(),
    _ref("dataset_id", "datasets"),
    Column("upstream_ref", String(256), nullable=False),
    Column("ref_kind", String(16), nullable=False),
    Column("resolved_digest", String(80), nullable=False),
    Column("materialization_digest", String(80), nullable=True),
    _json("manifest_json"),
    Column("status", String(16), nullable=False),
    _time("created_at"),
    UniqueConstraint("dataset_id", "resolved_digest"),
)

tasks = Table(
    "tasks",
    metadata,
    _id(),
    _ref("dataset_version_id", "dataset_versions"),
    Column("task_key", String(256), nullable=False),
    _json("definition_json"),
    Column("content_digest", String(80), nullable=False),
    UniqueConstraint("dataset_version_id", "task_key"),
)

task_admissions = Table(
    "task_admissions",
    metadata,
    _id(),
    _ref("task_id", "tasks"),
    Column("preparation_method_digest", String(80), nullable=False),
    Column("state", String(16), nullable=False),
    Column("revision", Integer, nullable=False),
    _json("evidence_json"),
    _ref("approved_by", "users", nullable=True),
    _time("approved_at", nullable=True),
    UniqueConstraint("task_id", "preparation_method_digest"),
    Index("ix_task_admissions_task_state", "task_id", "state"),
    CheckConstraint("state IN ('pending','admitted','first_failed','revoked')", name="state"),
)

content_availability = Table(
    "content_availability",
    metadata,
    _id(),
    Column("content_digest", String(80), nullable=False),
    Column("resource_kind", String(32), nullable=False),
    Column("availability", String(16), nullable=False),
    _json("evidence_json"),
    _time("checked_at", nullable=True),
    Column("revision", Integer, nullable=False),
    UniqueConstraint("content_digest", "resource_kind"),
    CheckConstraint("availability IN ('unknown','available','unavailable')", name="availability"),
)

operations = Table(
    "operations",
    metadata,
    _id(),
    Column("kind", String(32), nullable=False),
    _ref("owner_id", "users", nullable=True),
    _ref("pat_id", "pats", nullable=True),
    Column("resource_type", String(32), nullable=True),
    Column("resource_id", String(40), nullable=True),
    Column("status", String(16), nullable=False),
    Column("phase", String(32), nullable=True),
    _json("progress_json"),
    _json("error_json", nullable=True),
    _json("result_json", nullable=True),
    Column("revision", Integer, nullable=False),
    Column("service_epoch", String(40), nullable=True),
    Column("lease_token", String(80), nullable=True),
    _time("deadline_at", nullable=True),
    _json("process_identity_json", nullable=True),
    _time("created_at"),
    _time("updated_at"),
    _time("finished_at", nullable=True),
    Index("ix_operations_owner_created", "owner_id", "created_at", "id"),
    Index("ix_operations_created", "created_at", "id"),
    Index("ix_operations_resource", "resource_type", "resource_id"),
    CheckConstraint(
        "status IN ('accepted','running','succeeded','failed','cancelled','interrupted')",
        name="status",
    ),
)

preparations = Table(
    "preparations",
    metadata,
    _id(),
    _ref("task_id", "tasks"),
    Column("spec_digest", String(80), nullable=False),
    Column("location_id", String(64), nullable=False),
    Column("cache_state", String(16), nullable=False),
    Column("generation", Integer, nullable=False),
    _ref("active_operation_id", "operations", nullable=True),
    _ref("eviction_operation_id", "operations", nullable=True),
    _time("last_used_at", nullable=True),
    _json("last_restore_error_json", nullable=True),
    UniqueConstraint("spec_digest", "location_id"),
    Index("ix_preparations_state_used", "cache_state", "last_used_at"),
    CheckConstraint("cache_state IN ('absent','restoring','ready','stale')", name="cache_state"),
)

preparation_pins = Table(
    "preparation_pins",
    metadata,
    _id(),
    _ref("preparation_id", "preparations"),
    Column("holder_kind", String(16), nullable=False),
    Column("holder_id", String(40), nullable=False),
    _time("expires_at"),
    UniqueConstraint("preparation_id", "holder_kind", "holder_id"),
)

# --- Configuration (03) ---------------------------------------------------------

model_configs = Table(
    "model_configs",
    metadata,
    _id(),
    Column("name", String(128), nullable=False, unique=True),
    Column("enabled", Boolean, nullable=False),
    Column("current_revision", Integer, nullable=False),
    _time("created_at"),
)

model_revisions = Table(
    "model_revisions",
    metadata,
    _id(),
    _ref("model_config_id", "model_configs"),
    Column("revision", Integer, nullable=False),
    Column("provider", String(64), nullable=False),
    Column("model_id", String(256), nullable=False),
    _json("params_json"),
    _ref("credential_id", "credentials", nullable=True),
    _time("created_at"),
    UniqueConstraint("model_config_id", "revision"),
)

harness_versions = Table(
    "harness_versions",
    metadata,
    _id(),
    Column("name", String(128), nullable=False),
    Column("version", String(64), nullable=False),
    Column("content_digest", String(80), nullable=False),
    _json("schema_json"),
    Column("enabled", Boolean, nullable=False),
    _time("created_at"),
    UniqueConstraint("name", "version"),
)

attachment_versions = Table(
    "attachment_versions",
    metadata,
    _id(),
    _ref("owner_id", "users"),
    Column("name", String(128), nullable=False),
    Column("version", String(64), nullable=False),
    Column("content_digest", String(80), nullable=False),
    _json("manifest_json"),
    Column("enabled", Boolean, nullable=False),
    _time("created_at"),
    UniqueConstraint("owner_id", "name", "version"),
)

# --- Plans, submission and execution (04, 05) --------------------------------

experiment_plans = Table(
    "experiment_plans",
    metadata,
    _id(),
    _ref("owner_id", "users"),
    Column("name", String(128), nullable=False),
    Column("revision", Integer, nullable=False),
    _json("template_json"),
    _time("created_at"),
    _time("updated_at"),
    _time("archived_at", nullable=True),
)

idempotency_records = Table(
    "idempotency_records",
    metadata,
    _id(),
    Column("principal_id", String(40), nullable=False),
    Column("action", String(64), nullable=False),
    Column("key", String(128), nullable=False),
    Column("request_hash", String(80), nullable=False),
    Column("status_code", Integer, nullable=False),
    _json("response_json"),
    _time("created_at"),
    _time("expires_at"),
    UniqueConstraint("principal_id", "action", "key"),
    Index("ix_idempotency_expires", "expires_at"),
)

submission_batches = Table(
    "submission_batches",
    metadata,
    _id(),
    _ref("owner_id", "users"),
    _ref("operation_id", "operations"),
    _ref("idempotency_record_id", "idempotency_records", nullable=True),
    Column("stop_requested", Boolean, nullable=False),
    _time("created_at"),
)

runs = Table(
    "runs",
    metadata,
    _id(),
    Column("name", String(256), nullable=False),
    _ref("owner_id", "users"),
    _ref("pat_id", "pats", nullable=True),
    _ref("batch_id", "submission_batches", nullable=True),
    _ref("plan_id", "experiment_plans", nullable=True),
    Column("plan_revision", Integer, nullable=True),
    _ref("source_run_id", "runs", nullable=True),
    Column("relation", String(16), nullable=False),
    _ref("dataset_version_id", "dataset_versions"),
    _ref("operation_id", "operations"),
    Column("state", String(16), nullable=False),
    Column("stop_requested", Boolean, nullable=False),
    Column("stop_reason", String(64), nullable=True),
    Column("client_request_id", String(128), nullable=True),
    Column("concurrency", Integer, nullable=False),
    Column("artifact_state", String(16), nullable=False),
    Column("cleanup_state", String(16), nullable=False),
    Column("service_epoch", String(40), nullable=True),
    Column("lease_token", String(80), nullable=True),
    Column("queue_reason", String(64), nullable=True),
    _json("reservation_json", nullable=True),
    _json("runner_json", nullable=True),
    _time("heartbeat_at", nullable=True),
    _time("accepted_at"),
    _time("started_at", nullable=True),
    _time("finished_at", nullable=True),
    _time("deadline_at"),
    Index("ix_runs_owner_accepted", "owner_id", "accepted_at", "id"),
    Index("ix_runs_dataset_accepted", "dataset_version_id", "accepted_at", "id"),
    Index("ix_runs_accepted", "accepted_at", "id"),
    Index("ix_runs_owner_client", "owner_id", "client_request_id"),
    Index("ix_runs_state", "state"),
    CheckConstraint("relation IN ('initial','rerun','modified')", name="relation"),
    CheckConstraint(
        "state IN ('queued','preparing','running','finalizing','finished','cancelled',"
        "'interrupted')",
        name="state",
    ),
)

run_snapshots = Table(
    "run_snapshots",
    metadata,
    _ref("run_id", "runs", primary_key=True),
    Column("schema_version", Integer, nullable=False),
    _json("effective_json"),
    _json("provenance_json"),
    Column("snapshot_digest", String(80), nullable=False),
    Column("config_digest", String(80), nullable=False),
    Column("comparison_digest", String(80), nullable=False),
    _json("policy_json"),
)

trials = Table(
    "trials",
    metadata,
    _id(),
    _ref("run_id", "runs"),
    _ref("task_id", "tasks"),
    Column("repetition_index", Integer, nullable=False),
    Column("state", String(16), nullable=False),
    Column("phase", String(32), nullable=True),
    Column("reason_code", String(64), nullable=True),
    _time("execution_terminal_at", nullable=True),
    Column("result_revision", Integer, nullable=False),
    Column("artifact_state", String(16), nullable=False),
    Column("cleanup_state", String(16), nullable=False),
    UniqueConstraint("run_id", "task_id", "repetition_index"),
    Index("ix_trials_run_state", "run_id", "state"),
    CheckConstraint(
        "state IN ('queued','preparing','executing','verifying','scored','execution_error',"
        "'not_started','cancelled','interrupted')",
        name="state",
    ),
)

execution_attempts = Table(
    "execution_attempts",
    metadata,
    _id(),
    _ref("trial_id", "trials"),
    Column("attempt_index", Integer, nullable=False),
    Column("worker_id", String(64), nullable=False),
    Column("service_epoch", String(40), nullable=False),
    Column("lease_token", String(80), nullable=False),
    Column("runner_id", String(128), nullable=True),
    Column("protocol_version", Integer, nullable=True),
    _json("process_identity_json", nullable=True),
    Column("state", String(16), nullable=False),
    Column("phase", String(32), nullable=True),
    _json("steps_json", nullable=True),
    _json("executor_ref_json", nullable=True),
    _time("started_at"),
    _time("ended_at", nullable=True),
    _json("error_json", nullable=True),
    UniqueConstraint("trial_id", "attempt_index"),
)

work_items = Table(
    "work_items",
    metadata,
    _id(),
    _ref("trial_id", "trials", unique=True),
    Column("state", String(16), nullable=False),
    _time("eligible_at"),
    Column("enqueue_seq", Integer, nullable=False),
    Column("lease_token", String(80), nullable=True),
    Index("ix_work_items_state", "state", "eligible_at", "enqueue_seq"),
)

preparation_waiters = Table(
    "preparation_waiters",
    metadata,
    _id(),
    _ref("operation_id", "operations"),
    _ref("attempt_id", "execution_attempts"),
    _ref("run_id", "runs"),
    _time("deadline_at"),
    Column("state", String(16), nullable=False),
    UniqueConstraint("operation_id", "attempt_id"),
    Index("ix_preparation_waiters_op_state", "operation_id", "state"),
)

trial_results = Table(
    "trial_results",
    metadata,
    _ref("trial_id", "trials", primary_key=True),
    _ref("attempt_id", "execution_attempts"),
    Column("result_digest", String(80), nullable=False),
    Column("raw_score", Float, nullable=True),
    _json("metrics_json"),
    Column("verifier_status", String(32), nullable=True),
    Column("failure_cause", String(64), nullable=True),
    Column("exception_type", String(128), nullable=True),
    Column("reward_valid", Boolean, nullable=False),
    Column("grade_requested", Boolean, nullable=False),
    Column("retry_recommended", Boolean, nullable=False),
    _json("actual_model_json", nullable=True),
    _json("usage_json", nullable=True),
    Column("policy_version", String(32), nullable=False),
    _time("recorded_at"),
)

artifacts = Table(
    "artifacts",
    metadata,
    _id(),
    _ref("run_id", "runs"),
    _ref("trial_id", "trials", nullable=True),
    _ref("attempt_id", "execution_attempts", nullable=True),
    Column("kind", String(32), nullable=False),
    Column("relative_path", String(512), nullable=False),
    Column("storage_key", String(256), nullable=False, unique=True),
    Column("digest", String(80), nullable=True),
    Column("size_bytes", Integer, nullable=True),
    Column("status", String(16), nullable=False),
    _time("created_at"),
    _time("expires_at", nullable=True),
    Index("ix_artifacts_status_expires", "status", "expires_at"),
    Index("ix_artifacts_run", "run_id", "trial_id"),
    CheckConstraint(
        "status IN ('pending','available','failed','expired','unavailable')", name="status"
    ),
)

audit_events = Table(
    "audit_events",
    metadata,
    _id(),
    _ref("actor_user_id", "users", nullable=True),
    _ref("pat_id", "pats", nullable=True),
    Column("auth_channel", String(16), nullable=True),
    Column("action", String(64), nullable=False),
    Column("object_type", String(32), nullable=True),
    Column("object_id", String(40), nullable=True),
    Column("outcome", String(16), nullable=False),
    _json("detail_json", nullable=True),
    Column("request_id", String(40), nullable=True),
    _time("created_at"),
    Index("ix_audit_object", "object_type", "object_id", "created_at"),
    Index("ix_audit_created", "created_at", "id"),
)

provider_limits = Table(
    "provider_limits",
    metadata,
    Column("provider", String(64), primary_key=True),
    Column("max_concurrent_trials", Integer, nullable=False),
    _ref("updated_by", "users"),
    _time("updated_at"),
    CheckConstraint("max_concurrent_trials >= 1", name="max_concurrent_trials"),
)

instance = Table(
    "instance",
    metadata,
    Column("singleton", Integer, primary_key=True),
    Column("instance_id", String(40), nullable=False),
    _time("created_at"),
    CheckConstraint("singleton = 1", name="singleton"),
)

service_epochs = Table(
    "service_epochs",
    metadata,
    _id(),
    _time("started_at"),
    _json("process_identity_json"),
)
