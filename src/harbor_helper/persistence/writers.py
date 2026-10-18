"""Shared leases for every live Store and bounded source-preparation subprocess."""

import fcntl
import os
import re
import stat
import threading
from contextlib import contextmanager
from pathlib import Path

from harbor_helper.persistence.files import read_json

_leases = {}
_mutex = threading.RLock()  # GC may finalize another Store during acquire().


def acquire(root):
    key = (os.getpid(), str(root))
    with _mutex:
        if key in _leases:
            _leases[key][1] += 1
            return key
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(
            root / "writer.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600
        )
        try:
            meta = os.fstat(fd)
            if (
                not stat.S_ISREG(meta.st_mode)
                or meta.st_uid != os.getuid()
                or meta.st_mode & 0o077
                or meta.st_nlink != 1
            ):
                raise ValueError("Writer lease requires an owned private regular file")
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            code = Path(__file__).resolve().parents[3]
            if re.fullmatch("[a-f0-9]{40}", code.name) and (code / ".installed").exists():
                path = root / "release.json"
                if not path.exists() or read_json(path).get("release") != code.name:
                    raise ValueError(
                        "Installed writer release mismatch; use explicit verified upgrade"
                    )
        except BaseException:
            os.close(fd)
            raise
        _leases[key] = [fd, 1]
    return key


def release(key):
    with _mutex:
        value = _leases[key]
        value[1] -= 1
        if not value[1]:
            os.close(value[0])
            del _leases[key]


@contextmanager
def writer(root):
    key = acquire(root)
    try:
        yield
    finally:
        release(key)
