"""Basic redaction (09 section 5): known secret values, Maestro tokens, common headers.

This is best-effort for a trusted team; encoded or transformed secrets can escape.
"""

import base64
import json
import re
from urllib.parse import quote

from maestro.security.tokens import TOKEN_TEXT

REDACTED = "[REDACTED]"
_PATTERNS = [
    TOKEN_TEXT,
    re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+|basic\s+)?[^\s,;\"']+"),
    re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*)[^\s,;\"'&]+"),
    re.compile(r"(?i)([?&](?:api[_-]?key|access_token|token|key|sig|signature)=)[^&\s\"']+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
]


def value_variants(secret: str) -> set[str]:
    raw = secret.encode()
    return {
        secret,
        base64.b64encode(raw).decode(),
        quote(secret, safe=""),
        json.dumps(secret)[1:-1],
    }


def redact(text: str, secrets: list[str] | tuple[str, ...] = ()) -> str:
    variants = sorted(
        {v for s in secrets if s and len(s) >= 4 for v in value_variants(s)}, key=len, reverse=True
    )
    for variant in variants:
        text = text.replace(variant, REDACTED)
    for pattern in _PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.re.groups else "") + REDACTED, text)
    return text


def redact_json(value, secrets=()):
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, dict):
        return {k: redact_json(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_json(v, secrets) for v in value]
    return value
