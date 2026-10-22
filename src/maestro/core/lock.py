"""Single-instance lock: a second process must not write the same database."""

import fcntl
import os
from pathlib import Path

from maestro.core.errors import MaestroError


class InstanceLock:
    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.fd)
            self.fd = None
            raise MaestroError("INSTANCE_LOCKED", f"Another Maestro holds {self.path}", 409)
        os.ftruncate(self.fd, 0)
        os.write(self.fd, f"{os.getpid()}\n".encode())
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None
