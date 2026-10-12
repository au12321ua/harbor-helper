"""Recognizable access plaintext checks; request values never leave request memory."""

import os
import re

# Conservatively recognize every 43-character base64url payload.
ACCESS_TOKEN = re.compile(rb"hh_pat_v1_[A-Za-z0-9_-]{43}")
ACCESS_TOKEN_TEXT = re.compile(ACCESS_TOKEN.pattern.decode())


def check_access_tree(root, access_value=None):
    """Scan file bytes and paths, including binary/chunk-boundary matches, fail closed."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Bundle snapshot unavailable or unsafe")
    raw = access_value.encode() if access_value else None
    overlap = max(53, len(raw or b"")) - 1

    def walk(directory):
        with os.scandir(directory) as entries:
            children = list(entries)
        for entry in children:
            path = directory / entry.name
            yield path
            if entry.is_dir(follow_symlinks=False):
                yield from walk(path)

    for path in walk(root):
        if path.is_symlink():
            raise ValueError("Bundle contains unsafe access input")
        relative = path.relative_to(root).as_posix().encode()
        if ACCESS_TOKEN.search(relative) or (raw and raw in relative):
            raise ValueError("Bundle contains access credential plaintext")
        if not path.is_file():
            continue
        tail = b""
        with path.open("rb") as source:
            while chunk := source.read(65536):
                value = tail + chunk
                if ACCESS_TOKEN.search(value) or (raw and raw in value):
                    raise ValueError("Bundle contains access credential plaintext")
                tail = value[-overlap:]
