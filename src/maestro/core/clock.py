"""UTC time. Stored and returned as RFC 3339 strings with a ``Z`` suffix."""

from datetime import UTC, datetime, timedelta


def now() -> datetime:
    return datetime.now(UTC)


def to_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("naive datetime")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def from_text(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


__all__ = ["UTC", "datetime", "from_text", "now", "timedelta", "to_text"]
