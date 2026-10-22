"""Random bearer secrets stored only as digests.

Each kind carries a recognizable prefix so redaction can find leaked values.
High-entropy secrets need no slow hash; SHA-256 with a kind label suffices.
"""

import base64
import hashlib
import hmac
import re
import secrets

PREFIXES = {"pat": "mst_pat_", "invitation": "mst_inv_", "session": "mst_ses_", "setup": "mst_set_"}
_BODY = 43  # base64url of 32 bytes
TOKEN_TEXT = re.compile(rf"mst_(?:pat|inv|ses|set)_[A-Za-z0-9_-]{{{_BODY}}}")
PAT_DISPLAY_PREFIX = len(PREFIXES["pat"]) + 6


def generate(kind: str) -> str:
    return PREFIXES[kind] + secrets.token_urlsafe(32)


def digest(kind: str, token: str) -> str:
    return "sha256:" + hashlib.sha256(f"maestro/{kind}/{token}".encode()).hexdigest()


def well_formed(kind: str, token: object) -> bool:
    return (
        isinstance(token, str)
        and token.startswith(PREFIXES[kind])
        and len(token) == len(PREFIXES[kind]) + _BODY
        and TOKEN_TEXT.fullmatch(token) is not None
    )


def csrf_for(session_token: str) -> str:
    """Derived per session, so it never needs storage and dies with the session."""
    mac = hmac.new(session_token.encode(), b"maestro/csrf", hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
