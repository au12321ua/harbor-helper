"""Deployment-owned bootstrap material, never exposed by HTTP."""

import os
import secrets
import stat
from pathlib import Path

from harbor_helper.service.primitives import ServiceError


def protected_file(path, *, create=False):
    path = Path(path).expanduser().absolute()
    if create:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w") as file:
                file.write(secrets.token_urlsafe(32))
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd) as file:
            meta = os.fstat(file.fileno())
            value = file.read(1025).strip()
        if (
            not stat.S_ISREG(meta.st_mode)
            or meta.st_uid != os.getuid()
            or stat.S_IMODE(meta.st_mode) & 0o077
            or not 32 <= len(value) <= 1024
        ):
            raise ValueError
        return value
    except (OSError, ValueError):
        raise ServiceError(
            "setup_protection", "Deployment bootstrap file must be owner-only", 503
        ) from None
