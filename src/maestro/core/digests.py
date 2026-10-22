"""Canonical JSON and algorithm-tagged digests (``sha256:<hex>``)."""

import hashlib
import json
import math


def canonical_json(value) -> bytes:
    """Sorted keys, no insignificant whitespace, finite numbers only."""

    def check(item):
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("non-finite number in canonical JSON")
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise TypeError("non-string key in canonical JSON")
                check(child)
        elif isinstance(item, list | tuple):
            for child in item:
                check(child)

    check(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def digest_json(value) -> str:
    return sha256_bytes(canonical_json(value))
