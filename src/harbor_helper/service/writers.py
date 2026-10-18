"""Process-lifetime writer lease and installed-release identity (internal only)."""

import fcntl
import re
from contextlib import contextmanager
from pathlib import Path

from harbor_helper.persistence.files import read_json


@contextmanager
def writer(root):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (root / "writer.lock").open("a") as lease:
        fcntl.flock(lease, fcntl.LOCK_SH | fcntl.LOCK_NB)
        code = Path(__file__).resolve().parents[3]
        if re.fullmatch("[a-f0-9]{40}", code.name) and (code / ".installed").exists():
            path = root / "release.json"
            if not path.exists() or read_json(path).get("release") != code.name:
                raise ValueError("Installed writer release mismatch; use explicit verified upgrade")
        yield
