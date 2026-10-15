"""Canonical persisted/derived lifecycle vocabularies; transitions live in workers."""

from typing import Literal, get_args

RunStatus = Literal[
    "queued",
    "starting",
    "running",
    "cancelling",
    "cleanup_blocked",
    "succeeded",
    "failed",
    "cancelled",
]
SubmissionStatus = Literal["preparing", "ready", "failed", "cancelled"]
AuditStatus = Literal["pending", "clean", "incomplete"]
ReportStatus = Literal["pending", "available", "blocked", "unavailable"]
QUEUED, STARTING, RUNNING, CANCELLING, CLEANUP_BLOCKED, SUCCEEDED, FAILED, CANCELLED = get_args(
    RunStatus
)
PREPARING, READY = get_args(SubmissionStatus)[:2]
PENDING, CLEAN, INCOMPLETE = get_args(AuditStatus)
REPORT_PENDING, AVAILABLE, BLOCKED, UNAVAILABLE = get_args(ReportStatus)
TERMINAL = {SUCCEEDED, FAILED, CANCELLED}
ACTIVE = {STARTING, RUNNING, CANCELLING, CLEANUP_BLOCKED}
RUN_STATUSES = frozenset(get_args(RunStatus))
SUBMISSION_STATUSES = frozenset(get_args(SubmissionStatus))
AUDIT_STATUSES = frozenset(get_args(AuditStatus))
