"""Coordinate author-input discovery with explicit dataset cache deletion."""

import fcntl
import hashlib
from contextlib import contextmanager


@contextmanager
def cache_lock(store, resolved, *, blocking=True):
    folder = store.root / "author-locks"
    folder.mkdir(exist_ok=True, mode=0o700)
    name = hashlib.sha256(resolved.encode()).hexdigest()
    with (folder / name).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield
