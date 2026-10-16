"""Single decision owner, durable work, FIFO wake hints and bounded slow lanes."""

import fcntl
import os
import queue
import selectors
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from harbor_helper.execution.audit import audit_finished
from harbor_helper.execution.config import load_team
from harbor_helper.execution.processes import alive, process_birth, safe_environment
from harbor_helper.execution.resources import cleanup, stop_group
from harbor_helper.persistence import statuses as status
from harbor_helper.persistence.files import read_json, write_json
from harbor_helper.persistence.store import ACTIVE, TERMINAL, Store
from harbor_helper.persistence.wakeup import Mailbox, notify
from harbor_helper.security.credentials import RedactedStream, runtime_secrets

RECONCILE_SECONDS = 60
HEARTBEAT_SECONDS = 2
ACTIVE_SECONDS = 1
RETRY_SECONDS = 5
MAINTENANCE_SECONDS = 30


class Lane:
    """No executor backlog: unassigned work stays in SQLite."""

    def __init__(self, size, completed, root):
        self.size = size
        self.pool = ThreadPoolExecutor(max_workers=size) if size else None
        self.jobs = {}
        self.completed = completed
        self.root = root

    def submit(self, key, function, *args):
        if key in self.jobs or (self.size and len(self.jobs) >= self.size):
            return False
        if self.pool:
            future = self.pool.submit(function, *args)
        else:
            # Termination has exactly one slot per active run, independent of new
            # capacity settings; never queued behind Docker cleanup or another run.
            future = Future()

            def invoke():
                try:
                    future.set_result(function(*args))
                except BaseException as error:  # noqa: BLE001 - report thread completion safely
                    future.set_exception(error)

            threading.Thread(target=invoke, daemon=True).start()
        self.jobs[key] = future

        def done(result):
            self.completed.put((self, key, result))
            notify(self.root)

        future.add_done_callback(done)
        return True

    def close(self):
        if self.pool:
            self.pool.shutdown(wait=True)


class Controller:
    def __init__(self, store):
        self.store = store
        self.completed = queue.SimpleQueue()
        self.preparation = Lane(1, self.completed, store.root)
        self.termination = Lane(0, self.completed, store.root)
        self.cleaning = Lane(4, self.completed, store.root)
        self.auditing = Lane(1, self.completed, store.root)
        self.maintenance = Lane(1, self.completed, store.root)
        self.lanes = (
            self.preparation,
            self.termination,
            self.cleaning,
            self.auditing,
            self.maintenance,
        )
        self.stopped = set()
        self.retry = {}
        self.stopping = False
        self.invalid_until = {}

    def completions(self):
        while not self.completed.empty():
            lane, key, future = self.completed.get()
            lane.jobs.pop(key, None)
            try:
                future.result()
                if lane is self.termination:
                    self.stopped.add(key)
                elif lane is self.cleaning:
                    with self.store.quiet_control():
                        row = self.store.get(key)
                        if row["status"] in ACTIVE and row["finish_status"]:
                            self.store.update(
                                key,
                                status=row["finish_status"],
                                reason=row["finish_reason"],
                                finished=time.time(),
                            )
                    self.stopped.discard(key)
            except Exception as error:  # noqa: BLE001 - third party errors can contain secrets
                print(f"Scheduler lane error: {type(error).__name__}", flush=True)
                if lane in (self.termination, self.cleaning):
                    with self.store.quiet_control():
                        self.store.update(
                            key,
                            status=status.CLEANUP_BLOCKED,
                            reason="Execution resource cleanup unconfirmed; capacity retained",
                        )
                self.retry[(lane, key)] = time.monotonic() + RETRY_SECONDS
            else:
                if lane is self.auditing:
                    self.retry[(lane, key)] = time.monotonic() + RETRY_SECONDS

    def available(self, lane, key):
        return key not in lane.jobs and time.monotonic() >= self.retry.get((lane, key), 0)

    def decide(self, *, changed=True):
        self.completions()
        if self.stopping:
            return
        store = self.store
        with store.quiet_control():
            if changed:
                rows = store.work()
            else:
                with store.connect() as db:
                    rows = [
                        dict(r)
                        for r in db.execute(
                            "SELECT * FROM runs WHERE status IN ('starting','running','cancelling','cleanup_blocked') ORDER BY created"
                        )
                    ]
            active = [r for r in rows if r["status"] in ACTIVE]
            for row in active:
                if time.monotonic() < self.invalid_until.get(row["id"], 0):
                    continue
                try:
                    self.advance(row)
                except (ValueError, OSError, KeyError):
                    # A damaged record must not prevent other cancellations/heartbeats.
                    print("Scheduler record unavailable", flush=True)
                    self.invalid_until[row["id"]] = time.monotonic() + RETRY_SECONDS
            if changed:
                team = load_team(store)
                slots = sum(r["concurrency"] for r in active)
                for row in rows:
                    if row["status"] == status.QUEUED:
                        if row["cancel"]:
                            store.update(
                                row["id"],
                                status=status.CANCELLED,
                                finished=time.time(),
                                reason="Cancelled while queued",
                            )
                            notify(store.root)
                        elif not self.authorized(row):
                            continue
                        elif (
                            len(active) < team["max_jobs"]
                            and slots + row["concurrency"] <= team["max_trials"]
                        ):
                            if self.launch(row):
                                active.append(row)
                                slots += row["concurrency"]
                    elif (
                        row["status"] in TERMINAL
                        and self.available(self.auditing, row["id"])
                        and not (store.path(row["id"]) / "archived.json").exists()
                    ):
                        self.auditing.submit(row["id"], audit_finished, store, row)
                # Queued cancellation/authorization failures require an audit pass.
                # Wake once after state changes rather than wait for reconciliation.
                with store.connect() as db:
                    has_submissions = db.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='submissions'"
                    ).fetchone()
                    preparing = (
                        db.execute(
                            "SELECT 1 FROM submissions WHERE status='preparing' LIMIT 1"
                        ).fetchone()
                        if has_submissions
                        else None
                    )
                if preparing and self.available(self.preparation, "prepare"):
                    from harbor_helper.service.lifecycle import prepare_one

                    self.preparation.submit("prepare", prepare_one, store)

    def advance(self, row):
        store, key = self.store, row["id"]
        path = store.path(key)
        if not row["finish_status"]:
            decision = None
            if row["cancel"]:
                decision = status.CANCELLED, "Cancelled by member"
            elif (
                row["started"]
                and time.time()
                >= row["started"] + read_json(path / "manifest.json")["effective"]["wall_seconds"]
            ):
                decision = status.FAILED, "Wall-clock budget exceeded"
            elif (path / "outcome.json").exists():
                outcome = read_json(path / "outcome.json")
                decision = outcome["status"], outcome["reason"]
            elif not alive(row):
                decision = status.FAILED, "Worker interrupted; use rerun (not resume)"
            if decision:
                store.update(
                    key,
                    finish_status=decision[0],
                    finish_reason=decision[1],
                    status=status.CANCELLING,
                )
                row = store.get(key)
        if not row["finish_status"]:
            return
        if key not in self.stopped:
            if self.available(self.termination, key):
                self.termination.submit(key, stop_group, row)
        elif self.available(self.cleaning, key):
            self.cleaning.submit(key, cleanup, path)

    def fail_authorization(self, key):
        self.store.update(
            key,
            status=status.FAILED,
            finished=time.time(),
            reason="Execution authorization unavailable; worker not started",
        )
        notify(self.store.root)

    def authorized(self, row):
        from harbor_helper.service.data import ServiceData

        try:
            # Check every queued candidate before capacity selection. Discard the
            # key here; launch must obtain current authorization again.
            ServiceData(self.store.root).run_key(row["id"], execution=True)
        except ValueError:
            self.fail_authorization(row["id"])
            return False
        return True

    def launch(self, row):
        from harbor_helper.security.credentials import KEY_ENV
        from harbor_helper.service.data import ServiceData

        store, key = self.store, row["id"]
        environment = safe_environment()
        try:
            credential = ServiceData(store.root).run_key(key, execution=True)
            if credential:
                environment[KEY_ENV] = credential
        except ValueError:
            self.fail_authorization(key)
            return False
        store.update(key, status=status.STARTING, started=time.time())
        with (store.path(key) / "worker.log").open("a") as log:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "harbor_helper.execution.worker",
                    "run",
                    str(store.root),
                    key,
                ],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                env=environment,
                close_fds=True,
                start_new_session=True,
            )
        store.update(key, status=status.RUNNING, pid=child.pid, birth=process_birth(child.pid))

        def exited():
            child.wait()
            notify(store.root)

        threading.Thread(target=exited, daemon=True).start()
        return True

    def busy(self):
        return any(lane.jobs for lane in self.lanes)

    def close(self):
        for lane in self.lanes:
            lane.close()


def supervise(root):
    from harbor_helper.security import credentials

    # Publish identity before Store's migrations or any control/SQLite writer wait.
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.environ.pop(credentials.KEY_ENV, None)
    secrets = runtime_secrets()
    sys.stdout = RedactedStream(sys.stdout, secrets)
    sys.stderr = RedactedStream(sys.stderr, secrets)
    with (root / "supervisor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        mailbox = Mailbox(root)
        identity = {"pid": os.getpid(), "birth": process_birth(os.getpid())}
        write_json(root / "scheduler.json", identity)
        stopping = threading.Event()

        def stop(*_):
            stopping.set()
            notify(root)

        previous = signal.signal(signal.SIGTERM, stop)
        controller = None
        try:
            store = Store(root)
            controller = Controller(store)
            with selectors.DefaultSelector() as selector:
                selector.register(mailbox.reader, selectors.EVENT_READ)
                heartbeat = active_check = reconcile = maintenance = retry_check = 0
                changed = True
                while True:
                    now = time.monotonic()
                    controller.stopping = stopping.is_set()
                    try:
                        controller.decide(changed=changed or now >= reconcile or now >= retry_check)
                        if now >= reconcile:
                            reconcile = now + RECONCILE_SECONDS
                        # Retries are timers for actual deferred work, never a global tick.
                        retry_check = min(
                            (v for v in controller.retry.values() if v > now), default=float("inf")
                        )
                        controller.retry = {k: v for k, v in controller.retry.items() if v > now}
                        if now >= maintenance and not controller.stopping:
                            from harbor_helper.service.lifecycle import maintenance as maintain

                            if (root / "service.json").exists():
                                controller.maintenance.submit("maintenance", maintain, store)
                            maintenance = now + MAINTENANCE_SECONDS
                        if now >= heartbeat:
                            write_json(
                                root / "scheduler.json", {**identity, "observed": time.time()}
                            )
                            heartbeat = now + HEARTBEAT_SECONDS
                    except Exception as error:  # noqa: BLE001 - no third party exception text
                        print(f"Scheduler error: {type(error).__name__}", flush=True)
                        reconcile = (
                            min(reconcile, now + RETRY_SECONDS)
                            if reconcile > now
                            else now + RETRY_SECONDS
                        )
                    if controller.stopping and not controller.busy():
                        break
                    active_check = now + ACTIVE_SECONDS
                    deadline = min(heartbeat, active_check, reconcile, maintenance, retry_check)
                    events = selector.select(max(0.05, deadline - time.monotonic()))
                    changed = bool(events)
                    if events:
                        mailbox.drain()
        finally:
            if controller:
                controller.close()
            signal.signal(signal.SIGTERM, previous)
            mailbox.close()
