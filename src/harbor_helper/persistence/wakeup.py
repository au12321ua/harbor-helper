"""Bounded, payload-free local wake hints. SQLite remains the source of truth."""

import os
import stat
from functools import wraps
from pathlib import Path


def valid(meta):
    return (
        stat.S_ISFIFO(meta.st_mode)
        and meta.st_uid == os.getuid()
        and stat.S_IMODE(meta.st_mode) == 0o600
    )


def notify(root):
    """Best effort, including reader exit/full pipe races; never change business results."""
    fd = None
    try:
        path = Path(root) / "scheduler.wake"
        before = path.lstat()
        if not valid(before):
            return
        fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        after = os.fstat(fd)
        if valid(after) and (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino):
            os.write(fd, b"w")
    except OSError:
        pass
    finally:
        if fd is not None:
            os.close(fd)


class Mailbox:
    """Opened only by the supervisor.lock owner; self writer prevents idle HUP spin."""

    def __init__(self, root):
        path = Path(root) / "scheduler.wake"
        try:
            os.mkfifo(path, 0o600)
        except FileExistsError:
            pass
        before = path.lstat()
        if not valid(before):
            raise ValueError("Scheduler wake endpoint requires owner 0600 FIFO")
        self.reader = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            after = os.fstat(self.reader)
            if not valid(after) or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise ValueError("Scheduler wake endpoint changed")
            self.writer = os.open(path, os.O_WRONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            writer = os.fstat(self.writer)
            if not valid(writer) or (after.st_dev, after.st_ino) != (writer.st_dev, writer.st_ino):
                os.close(self.writer)
                raise ValueError("Scheduler wake endpoint changed")
        except BaseException:
            os.close(self.reader)
            raise

    def drain(self):
        # One bounded batch: time events and completion commits cannot be starved.
        try:
            os.read(self.reader, 65536)
        except BlockingIOError:
            pass

    def close(self):
        os.close(self.writer)
        os.close(self.reader)


def wake_after(function):
    """Notify after a direct persistence operation (outer control may coalesce it)."""

    @wraps(function)
    def wrapped(self, *args, **kwargs):
        try:
            return function(self, *args, **kwargs)
        finally:
            notify(self.store.root)

    return wrapped
