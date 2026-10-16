"""Scheduler execution responsibility."""

import fcntl
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from harbor_helper.execution.audit import audit_finished, finish
from harbor_helper.execution.config import load_team
from harbor_helper.execution.processes import alive, process_birth, safe_environment
from harbor_helper.persistence import statuses as lifecycle_status
from harbor_helper.persistence.files import read_json, write_json
from harbor_helper.persistence.store import ACTIVE, TERMINAL, Store
from harbor_helper.security.credentials import (
    RedactedStream,
    runtime_secrets,
)


def tick(store, children):
    with store.control():
        _tick(store, children)


def _tick(store, children):
    team = load_team(store)
    for row in store.runs():
        if row["status"] in TERMINAL and row["audit_status"] in {
            lifecycle_status.PENDING,
            lifecycle_status.INCOMPLETE,
        }:
            path = store.path(row["id"])
            stamp = path / "credential-audit.json"
            if not (path / "archived.json").exists() and (
                not stamp.exists() or time.time() - stamp.stat().st_mtime >= 5
            ):
                audit_finished(store, row)
        if row["status"] not in ACTIVE:
            continue
        path = store.path(row["id"])
        outcome = path / "outcome.json"
        cfg = read_json(path / "manifest.json")["effective"]
        if row["cancel"]:
            finish(store, row, lifecycle_status.CANCELLED, "Cancelled by member")
        elif row["started"] and time.time() - row["started"] >= cfg["wall_seconds"]:
            finish(store, row, lifecycle_status.FAILED, "Wall-clock budget exceeded")
        elif outcome.exists():
            value = read_json(outcome)
            finish(store, row, value["status"], value["reason"])
        elif row["status"] == lifecycle_status.CLEANUP_BLOCKED or not alive(row):
            finish(
                store, row, lifecycle_status.FAILED, "Worker interrupted; use rerun (not resume)"
            )
    for pid, child in list(children.items()):
        if child.poll() is not None:
            children.pop(pid)
    active = [r for r in store.runs() if r["status"] in ACTIVE]
    slots = sum(r["concurrency"] for r in active)
    for row in store.runs():
        if row["status"] != lifecycle_status.QUEUED:
            continue
        if row["cancel"]:
            store.update(
                row["id"],
                status=lifecycle_status.CANCELLED,
                finished=time.time(),
                reason="Cancelled while queued",
            )
            audit_finished(store, store.get(row["id"]))
            continue
        from harbor_helper.security.credentials import KEY_ENV
        from harbor_helper.service.data import ServiceData

        environment = safe_environment()
        try:
            key = ServiceData(store.root).run_key(row["id"], execution=True)
            if key:
                environment[KEY_ENV] = key
        except ValueError:
            store.update(
                row["id"],
                status=lifecycle_status.FAILED,
                finished=time.time(),
                reason="Execution authorization unavailable; worker not started",
            )
            audit_finished(store, store.get(row["id"]))
            continue
        if len(active) >= team["max_jobs"] or slots + row["concurrency"] > team["max_trials"]:
            continue
        path = store.path(row["id"])
        store.update(row["id"], status=lifecycle_status.STARTING, started=time.time())
        with (path / "worker.log").open("a") as log:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "harbor_helper.execution.worker",
                    "run",
                    str(store.root),
                    row["id"],
                ],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                env=environment,
                close_fds=True,
                start_new_session=True,
            )
        children[child.pid] = child
        store.update(
            row["id"],
            status=lifecycle_status.RUNNING,
            pid=child.pid,
            birth=process_birth(child.pid),
        )
        active.append(row)
        slots += row["concurrency"]


def supervise(root):
    from harbor_helper.security import credentials

    store = Store(root)
    os.environ.pop(credentials.KEY_ENV, None)
    secrets = runtime_secrets()
    sys.stdout = RedactedStream(sys.stdout, secrets)
    sys.stderr = RedactedStream(sys.stderr, secrets)
    with (store.root / "supervisor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        write_json(
            store.root / "scheduler.json", {"pid": os.getpid(), "birth": process_birth(os.getpid())}
        )
        children = {}
        # Keep cancellation/recovery/wall checks responsive during Hub downloads.
        preparation_pool = ThreadPoolExecutor(max_workers=1)
        preparation = None
        maintained = time.monotonic()
        while True:
            try:
                write_json(
                    store.root / "scheduler.json",
                    {
                        "pid": os.getpid(),
                        "birth": process_birth(os.getpid()),
                        "observed": time.time(),
                    },
                )
                if preparation is None or preparation.done():
                    from harbor_helper.service.lifecycle import prepare_one

                    if preparation is not None:
                        completed, preparation = preparation, None
                        completed.result()
                    preparation = preparation_pool.submit(prepare_one, store)
                tick(store, children)
                if time.monotonic() - maintained >= 30:
                    from harbor_helper.service.lifecycle import maintenance

                    with store.control():
                        maintenance(store)
                    maintained = time.monotonic()
            except Exception as e:  # noqa: BLE001 - persist/diagnose third-party Harbor errors
                print(f"Scheduler error: {type(e).__name__}", flush=True)
            time.sleep(0.5)
