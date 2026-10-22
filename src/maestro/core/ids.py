"""Opaque, time-sortable identifiers: ``<prefix>_<26 Crockford base32 chars>``."""

import os
import re
import time

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
_PATTERN = re.compile(r"[a-z]{2,8}_[0-9a-hjkmnp-tv-z]{26}")


def new_id(prefix: str) -> str:
    """48-bit millisecond time followed by 80 random bits, like a ULID."""
    value = (time.time_ns() // 1_000_000) << 80 | int.from_bytes(os.urandom(10))
    chars = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return f"{prefix}_{''.join(reversed(chars))}"


def is_id(value: object, prefix: str | None = None) -> bool:
    return (
        isinstance(value, str)
        and _PATTERN.fullmatch(value) is not None
        and (prefix is None or value.startswith(prefix + "_"))
    )
