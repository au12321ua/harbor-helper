"""Pinned directory descriptors for model-controlled local paths (Linux)."""

import os
import shutil
import stat
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory


class LocalRoot:
    def __init__(self, root):
        self.path = Path(root).absolute()
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def close(self):
        os.close(self.fd)

    def parts(self, path):
        value = Path(path)
        if value.is_absolute():
            value = value.relative_to(self.path)
        if not value.parts or any(p in {"..", "."} for p in value.parts):
            raise ValueError("Path must be inside the configured local root")
        return value.parts

    @contextmanager
    def parent(self, path):
        parts = self.parts(path)
        fd = os.dup(self.fd)
        try:
            for part in parts[:-1]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            yield fd, parts[-1]
        finally:
            os.close(fd)

    @contextmanager
    def destination(self, path):
        with self.parent(path) as (fd, name):
            # SDK performs O_EXCL creation. The parent descriptor remains pinned.
            yield Path(f"/proc/self/fd/{fd}") / name

    @contextmanager
    def upload(self, path):
        with self.parent(path) as (parent, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                with TemporaryDirectory(prefix="hh-upload-") as temporary:
                    target = Path(temporary) / "input"
                    self._copy(fd, target)
                    yield target
            finally:
                os.close(fd)

    def _copy(self, fd, target):
        mode = os.fstat(fd).st_mode
        if stat.S_ISDIR(mode):
            target.mkdir(mode=0o700)
            for name in sorted(os.listdir(fd)):
                child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                try:
                    self._copy(child, target / name)
                finally:
                    os.close(child)
        elif stat.S_ISREG(mode):
            with os.fdopen(os.dup(fd), "rb") as source, target.open("xb") as out:
                shutil.copyfileobj(source, out, 65536)
        else:
            raise ValueError("Only regular files and directories are allowed")
