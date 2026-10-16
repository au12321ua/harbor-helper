#!/usr/bin/env python3
"""Locked local/CI verification. Runtime receives no caller credentials or Docker CLI."""

import argparse
import ctypes
import fcntl
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GENERATED = ["src/harbor_helper/static", "frontend/contracts.json", "frontend/src/generated"]
BROWSER = {
    "test_production_static_browser_credentials",
    "test_production_admission_browser",
    "test_production_browser_damaged_manifest_observation",
}


def birth(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return fields[19] if fields[0] != "Z" else None
    except (OSError, IndexError):
        return None


def owned(marker):
    result = []
    for p in Path("/proc").iterdir():
        if p.name.isdigit() and int(p.name) != os.getpid():
            try:
                if f"HH_VERIFY_RUN={marker}".encode() in (p / "environ").read_bytes().split(b"\0"):
                    identity = birth(int(p.name))
                    if identity:
                        result.append((int(p.name), identity))
            except (OSError, ProcessLookupError):
                pass
    return result


def open_pidfd(pid):
    if hasattr(os, "pidfd_open"):
        return os.pidfd_open(pid)
    libc = ctypes.CDLL(None, use_errno=True)
    call = libc.pidfd_open
    call.argtypes = [ctypes.c_int, ctypes.c_uint]
    call.restype = ctypes.c_int
    fd = call(pid, 0)
    if fd < 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
    return fd


def cleanup(marker):
    killed = []
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid, identity in owned(marker):
            try:
                fd = open_pidfd(pid)
                try:
                    if birth(pid) == identity:
                        signal.pidfd_send_signal(fd, sig)
                        killed.append({"pid": pid, "birth": identity, "signal": sig.name})
                finally:
                    os.close(fd)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 3
        while owned(marker) and time.monotonic() < deadline:
            time.sleep(0.05)
    return {"signals": killed, "remaining": owned(marker)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["full", "backend"], default="full")
    parser.add_argument(
        "--prepare", action="store_true", help="install locked dependencies and Chromium"
    )
    parser.add_argument(
        "--browsers", type=Path, required=True, help="absolute cache outside isolated HOME"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="new exclusive diagnostics directory"
    )
    parser.add_argument("--ui-port", type=int, default=4173)
    parser.add_argument("--python", choices=["3.12", "3.13"], default="3.12")
    parser.add_argument("--dependency-cache", type=Path, default=Path.home() / ".cache/uv")
    args = parser.parse_args()
    if not args.browsers.is_absolute():
        parser.error("--browsers must be absolute")
    args.output = args.output.absolute()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    scratch = Path(tempfile.mkdtemp(prefix="hh-verify-"))
    marker = uuid.uuid4().hex
    report: dict = {
        "sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "mode": args.mode,
        "commands": [],
        "git_status": subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=REPO, text=True
        ),
        "manual_excluded": [
            "frontend/qa/live-service.mjs",
            "frontend/qa/final-integration-production.mjs",
        ],
        "status": "failed",
    }
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL") if k in os.environ}
    for folder in ("home", "tmp", "cache", "config", "data", "tools"):
        (scratch / folder).mkdir(mode=0o700)
    env.update(
        HOME=str(scratch / "home"),
        TMPDIR=str(scratch / "tmp"),
        XDG_CACHE_HOME=str(scratch / "cache"),
        XDG_CONFIG_HOME=str(scratch / "config"),
        XDG_DATA_HOME=str(scratch / "data"),
        PLAYWRIGHT_BROWSERS_PATH=str(args.browsers),
        HH_VERIFY_RUN=marker,
        DOCKER_HOST="unix:///nonexistent-hh-verify-docker.sock",
        PYTHONUNBUFFERED="1",
        UV_CACHE_DIR=str(args.dependency_cache.absolute()),
        UV_PYTHON_DOWNLOADS="never",
    )
    # Resolve a narrow runtime tool PATH, excluding docker/compose, caller wrappers and profiles.
    missing_tools = []
    for name in ("uv", "node", "npm", "npx", "git", "sh", "bash", "env", "python3", "uname"):
        path = shutil.which(name)
        if not path:
            missing_tools.append(name)
            continue
        (scratch / "tools" / name).symlink_to(path)
    runtime = dict(env, PATH=f"{REPO}/.venv/bin:{scratch}/tools", HH_TEST_BROWSER="1")
    runtime.update(
        HH_UI_PORT=str(args.ui_port),
        HH_UI_OUTPUT=str(args.output / "ui"),
        UV_CACHE_DIR=str(scratch / "cache/uv"),
    )

    def run(command, cwd=REPO, prepare=False):
        entry = {"argv": command, "cwd": str(cwd)}
        report["commands"].append(entry)
        print("+", " ".join(command), flush=True)
        with (args.output / f"command-{len(report['commands']):02}.log").open("w") as log:
            child = subprocess.Popen(
                command,
                cwd=cwd,
                env=env if prepare else runtime,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            entry["exit"] = child.wait()
        if entry["exit"]:
            raise RuntimeError(f"command {len(report['commands'])} failed ({entry['exit']})")

    def interrupted(sig, frame):
        raise KeyboardInterrupt(f"signal {sig}")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    lock_path = Path("/tmp") / (
        "hh-verify-" + hashlib.sha256(str(REPO).encode()).hexdigest() + ".lock"
    )
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if missing_tools:
            raise RuntimeError("missing tools: " + ", ".join(missing_tools))
        if args.prepare:
            run(["uv", "sync", "--locked", "--group", "dev", "--python", args.python], prepare=True)
            if args.mode == "full":
                run(["npm", "ci"], REPO / "frontend", prepare=True)
                run(["npx", "playwright", "install", "chromium"], REPO / "frontend", prepare=True)
        run(
            [
                ".venv/bin/python",
                "-c",
                f"import sys; assert sys.version_info[:2] == tuple(map(int, {args.python!r}.split('.')))",
            ]
        )
        for command in (
            ["uv", "--version"],
            ["node", "--version"],
            [".venv/bin/python", "--version"],
            [".venv/bin/ruff", "--version"],
            [".venv/bin/ty", "--version"],
            [".venv/bin/ruff", "check", "src", "tests", "scripts", "tools"],
            [".venv/bin/ruff", "format", "--check", "src", "tests", "scripts", "tools"],
            [".venv/bin/ty", "check", "--python", ".venv", "--error-on-warning", "src", "tests", "scripts", "tools"],
        ):
            run(command)
        run([".venv/bin/python", "tools/browser_contract.py", "--check"])
        if args.mode == "full":
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", args.ui_port))
            run(
                [
                    "node",
                    "--input-type=module",
                    "-e",
                    'import {chromium} from "@playwright/test"; const b=await chromium.launch(); await b.close()',
                ],
                REPO / "frontend",
            )
            for task in ("test:types", "lint", "build"):
                run(["npm", "run", task], REPO / "frontend")
        drift = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", *GENERATED],
            cwd=REPO,
            text=True,
        )
        report["generated_drift"] = drift
        if drift:
            raise RuntimeError("generated static/contract differs from candidate")
        junit = args.output / "pytest.xml"
        cmd = [".venv/bin/python", "-m", "pytest", "-q", f"--junitxml={junit}"]
        if args.mode == "backend":
            cmd += [
                "-k",
                " and ".join(f"not {name}" for name in sorted(BROWSER)),
            ]
        run(cmd)
        cases = ET.parse(junit).getroot().findall(".//testcase")
        report["pytest"] = {
            "cases": len(cases),
            "skipped": sum(c.find("skipped") is not None for c in cases),
            "browser_passed": sorted(
                c.attrib["name"] for c in cases if c.attrib["name"] in BROWSER and len(c) == 0
            ),
        }
        if report["pytest"]["skipped"] or (
            args.mode == "full" and set(report["pytest"]["browser_passed"]) != BROWSER
        ):
            raise RuntimeError("skip/browser execution gate failed")
        if args.mode == "full":
            run(["npm", "run", "test:ui"], REPO / "frontend")
        report["status"] = "passed"
    except (Exception, KeyboardInterrupt) as error:  # noqa: BLE001
        report["error"] = str(error)
    finally:
        report["cleanup"] = cleanup(marker)
        if report["cleanup"]["remaining"]:
            report["status"] = "failed"
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        shutil.rmtree(scratch)
        os.close(lock_fd)
    print(json.dumps(report))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
