"""Owner-only private client records; no service master-key lifecycle."""

import json
import os
import stat
import uuid
from pathlib import Path

from harbor_helper.security.errors import AuthError


def secure_read(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise AuthError("Private auth record owner/type invalid")
            if stat.S_IMODE(info.st_mode) != 0o600:
                raise AuthError("Private auth record must have mode 0600")
            return json.loads(stream.read(1024 * 1024))
    except (OSError, ValueError) as error:
        if isinstance(error, AuthError):
            raise
        raise AuthError("Private auth record unavailable or invalid") from None


def secure_write(path, value):
    path = Path(path)
    temporary = path.parent / (".write-" + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
