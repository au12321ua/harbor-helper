"""Process identity and sanitized execution environment, independent of scheduler."""

import os
import subprocess
from pathlib import Path


def process_birth(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return fields[19]
    except (OSError, IndexError):
        return None


def alive(row):
    return bool(row["pid"] and row["birth"] and process_birth(row["pid"]) == row["birth"])


def run_command(argv):
    r = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise RuntimeError(f"Command failed ({argv[:3]}): {r.stderr[-800:]}")
    return r.stdout.strip()


def safe_environment():
    # Never inherit arbitrary provider keys or search neighboring secrets.
    keep = {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
    }
    return {k: v for k, v in os.environ.items() if k in keep}
