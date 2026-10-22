"""Per-request values that services may record without threading them through calls."""

from contextvars import ContextVar

request_id: ContextVar[str | None] = ContextVar("maestro_request_id", default=None)
