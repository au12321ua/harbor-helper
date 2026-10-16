"""Shared JSON persistence and immutable input digest helpers."""

import hashlib
import json
import os
import stat
from pathlib import Path


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def tree_digest(root):
    """Include names, contents and executable mode; reject links and special files."""
    root = Path(root)
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise ValueError(f"Snapshot symlinks are unsupported: {p.relative_to(root)}")
        mode = p.stat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError(f"Snapshot special files are unsupported: {p.relative_to(root)}")
        h.update(p.relative_to(root).as_posix().encode() + b"\0")
        h.update(str(mode & 0o111).encode() + b"\0")
        if p.is_file():
            h.update(p.read_bytes())
        h.update(b"\0")
    return "sha256:" + h.hexdigest()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
