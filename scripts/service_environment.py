"""Load only explicitly configured host transport settings before exec (same PID)."""

import json
import os
import stat
import sys
from pathlib import Path

TRANSPORT = {
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
}


def environment(base):
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ}
    env.update(HOME=str(base / "home"), PYTHONUNBUFFERED="1")
    path = base / "private/network.json"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return env
    with os.fdopen(fd) as file:
        info = os.fstat(file.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_size > 16384
        ):
            raise ValueError("private/network.json must be an owner-only regular JSON file")
        value = json.loads(file.read(16385))
    if (
        not isinstance(value, dict)
        or value.keys() - TRANSPORT
        or any(not isinstance(v, str) or any(c in v for c in "\0\r\n") for v in value.values())
    ):
        raise ValueError("private/network.json accepts only proxy and TLS certificate strings")
    return {**env, **value}


if __name__ == "__main__":
    try:
        os.execve(sys.executable, [sys.executable, *sys.argv[2:]], environment(Path(sys.argv[1])))
    except (OSError, ValueError):
        # Invalid JSON can include secrets; never echo input or parser exceptions.
        print("Service network configuration invalid; check private/network.json", file=sys.stderr)
        sys.exit(1)
