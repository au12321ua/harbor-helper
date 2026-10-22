"""Argon2id password hashing; the encoded hash records algorithm and parameters."""

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError

from maestro.core.errors import FieldError, MaestroError

_HASHER = PasswordHasher()
MIN_LENGTH = 10
MAX_LENGTH = 256

# Verified against unknown usernames so response time does not reveal accounts.
_DUMMY = _HASHER.hash("maestro-dummy-password")


def check_policy(password: object) -> str:
    if not isinstance(password, str) or not MIN_LENGTH <= len(password) <= MAX_LENGTH:
        raise MaestroError(
            "PASSWORD_POLICY",
            f"Password must be {MIN_LENGTH}-{MAX_LENGTH} characters",
            422,
            field_errors=[FieldError("/password", "LENGTH", limit=MIN_LENGTH)],
        )
    return password


def hash_password(password: str) -> str:
    return _HASHER.hash(check_policy(password))


def verify(stored: str | None, password: str) -> bool:
    try:
        return _HASHER.verify(stored or _DUMMY, password) and stored is not None
    except (Argon2Error, InvalidHashError):
        return False


def needs_rehash(stored: str) -> bool:
    return _HASHER.check_needs_rehash(stored)
