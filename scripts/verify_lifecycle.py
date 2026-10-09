"""Real Hub/Docker lifecycle evidence; never modifies task or verifier inputs."""

import argparse
import concurrent.futures
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from harbor_helper.execution.worker import process_birth
from harbor_helper.persistence.files import read_json, write_json

p = argparse.ArgumentParser()
p.add_argument("--state", required=True, type=Path)
a = p.parse_args()
state = a.state.resolve()
if state.exists():
    raise SystemExit("Use a new isolated state directory")
cli = [sys.executable, "-m", "harbor_helper.commands.main", "--json", "--state", str(state)]
evidence = []


def call(*args):
    r = subprocess.run([*cli, *args], check=True, text=True, capture_output=True)
    value = json.loads(r.stdout)
    evidence.append({"command": [*cli, *args], "result": value, "at": time.time()})
    return value


def row(run_id):
    return call("status", run_id)


def wait(predicate, timeout=100):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.5)
    raise AssertionError("Condition timed out")


def owned(run_id):
    path = state / "runs" / run_id / "projects.json"
    if not path.exists():
        return []
    ids = []
    for project in read_json(path):
        out = subprocess.run(
            ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + project],
            check=True,
            text=True,
            capture_output=True,
        )
        ids += out.stdout.split()
    return ids


def submit():
    return call(
        "submit", "--agent", "oracle", "--bundle", str(bundle), "--task", "generation--box"
    )["run_id"]


call("init")
bundle = state / "candidate"
shutil.copytree(Path(__file__).resolve().parents[1] / "examples" / "bundle-probe", bundle)
bootstrap = bundle / "bootstrap.sh"
bootstrap.write_text(
    bootstrap.read_text() + "printf 'LIFECYCLE_SNAPSHOT=original\\n' > /logs/agent/lifecycle.txt\n"
    "sleep 120\n"
)
try:
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        first, second = list(pool.map(lambda _: submit(), range(2)))
    assert first != second
    wait(lambda: {row(first)["status"], row(second)["status"]} == {"running", "queued"})
    running, queued = (first, second) if row(first)["status"] == "running" else (second, first)
    original = read_json(state / "runs" / running / "manifest.json")
    call("cancel", queued)
    wait(lambda: row(queued)["status"] == "cancelled")
    assert not owned(queued)
    survivor = submit()
    wait(lambda: owned(running))
    lifecycle = lambda: list((state / "runs" / running).glob("harbor/*/*/agent/lifecycle.txt"))
    wait(lifecycle)
    assert lifecycle()[0].read_text().strip() == "LIFECYCLE_SNAPSHOT=original"
    bootstrap.write_text("#!/bin/sh\nexit 23\n")
    assert (
        state / "runs" / running / "bundle" / "bootstrap.sh"
    ).read_text() != bootstrap.read_text()
    pid = row(running)["pid"]
    os.kill(pid, signal.SIGKILL)
    wait(lambda: row(running)["status"] == "failed")
    assert not owned(running)
    assert read_json(state / "runs" / running / "cleanup.json")["confirmed"]
    wait(lambda: row(survivor)["status"] == "running")
    wait(lambda: owned(survivor))
    call("cancel", survivor)
    wait(lambda: row(survivor)["status"] == "cancelled")
    assert not owned(survivor)
    rerun = call("rerun", running)["run_id"]
    assert rerun != running
    copied = read_json(state / "runs" / rerun / "manifest.json")
    assert copied["source"] == original["source"]
    assert copied["bundle_digest"] == original["bundle_digest"]
    assert copied["effective"] == original["effective"]
    call("cancel", rerun)
    wait(lambda: row(rerun)["status"] == "cancelled")
    call("stop")
    wait(lambda: process_birth(read_json(state / "scheduler.json")["pid"]) is None)
    team = read_json(state / "team.json")
    team.update(max_jobs=2, max_trials=2)
    write_json(state / "team.json", team)
    # Restore a known payload, then prove cancelling one active Job preserves the other.
    bootstrap.write_text((state / "runs" / running / "bundle" / "bootstrap.sh").read_text())
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        one, two = list(pool.map(lambda _: submit(), range(2)))
    wait(lambda: owned(one) and owned(two))
    call("cancel", one)
    wait(lambda: row(one)["status"] == "cancelled")
    assert not owned(one)
    second_row = row(two)
    assert second_row["status"] == "running" and process_birth(second_row["pid"])
    assert owned(two)
    call("cancel", two)
    wait(lambda: row(two)["status"] == "cancelled")
    assert not owned(two)
    write_json(state / "lifecycle-evidence.json", {"passed": True, "evidence": evidence})
    print(
        json.dumps(
            {
                "passed": True,
                "state": str(state),
                "runs": [first, second, survivor, rerun, one, two],
            }
        )
    )
finally:
    # Only our own isolated installation and its explicitly identified runs.
    for r in call("list"):
        if r["status"] not in {"failed", "cancelled", "succeeded"}:
            call("cancel", r["id"])
    wait(lambda: all(r["status"] in {"failed", "cancelled", "succeeded"} for r in call("list")))
    call("stop")
    write_json(state / "commands.json", evidence)
