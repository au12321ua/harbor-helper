"""scheduler behavior with isolated synthetic inputs."""

import copy
import fcntl
import json
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from core_support import add_run, default_cfg
from scheduler_support import settle

from harbor_helper.execution.audit import finish
from harbor_helper.execution.config import (
    load_team,
    validate_effective,
)
from harbor_helper.execution.resources import cleanup
from harbor_helper.execution.runs import submit
from harbor_helper.execution.sources import verify_inputs
from harbor_helper.persistence.files import read_json, write_json


def test_cap_enforced(store):
    with pytest.raises(ValueError, match="concurrency"):
        validate_effective(load_team(store), default_cfg(concurrency=2))


def test_cleanup_failure_retains_capacity(store, monkeypatch):
    p, _ = add_run(store, "broken", "running")
    add_run(store, "queued")
    write_json(p / "projects.json", ["owned-project"])
    monkeypatch.setattr(
        "harbor_helper.execution.scheduler.cleanup",
        lambda _: (_ for _ in ()).throw(RuntimeError("Docker unavailable")),
    )

    def no_start(*args, **kwargs):
        pytest.fail("Capacity was released before cleanup confirmation")

    monkeypatch.setattr("harbor_helper.execution.scheduler.subprocess.Popen", no_start)
    settle(store)
    assert store.get("broken")["status"] == "cleanup_blocked"
    assert store.get("queued")["status"] == "queued"


def test_cleanup_exact_project_labels(store, monkeypatch):
    p, _ = add_run(store)
    write_json(p / "projects.json", ["owned-1", "owned-2"])
    calls = []
    monkeypatch.setattr(
        "harbor_helper.execution.resources.run_command", lambda cmd: calls.append(cmd) or ""
    )
    cleanup(p)
    assert calls and all(
        any("label=com.docker.compose.project=owned-" in arg for arg in cmd) for cmd in calls
    )
    assert not any("prune" in cmd for cmd in calls)


def test_cancel_terminal_only_after_cleanup(store, monkeypatch):
    p, _ = add_run(store, status="running")
    store.update(p.name, cancel=1)
    called = []
    monkeypatch.setattr("harbor_helper.execution.audit.cleanup", lambda _: called.append(True))
    finish(store, store.get(p.name), "cancelled", "user")
    assert called and store.get(p.name)["status"] == "cancelled"


def test_audit_failure_releases_slot(store, monkeypatch):
    first, _ = add_run(store, "first", "running")
    add_run(store, "next")
    available = False

    class Credentials:
        def __init__(self, root):
            assert root == store.root
            from harbor_helper.security.master_key import MasterKeys

            self.master_keys = MasterKeys(store)

        def run_key(self, run_id, execution=False):
            if run_id == "first" and not available:
                raise ValueError("Bound audit source unavailable")
            return "fake-first-marker" if run_id == "first" else None

    monkeypatch.setitem(
        sys.modules, "harbor_helper.service.data", SimpleNamespace(ServiceData=Credentials)
    )
    launched = []
    monkeypatch.setattr(
        "harbor_helper.execution.scheduler.subprocess.Popen",
        lambda *args, **kwargs: (
            launched.append(kwargs) or SimpleNamespace(pid=999999, wait=lambda: None)
        ),
    )
    monkeypatch.setattr("harbor_helper.execution.scheduler.alive", lambda row: row["id"] == "next")
    (first / "worker.log").write_text("fake-first-marker")
    settle(store)
    assert store.get("first")["status"] == "failed"
    assert store.get("first")["audit_status"] == "incomplete"
    assert read_json(first / "cleanup.json")["confirmed"]
    assert store.get("next")["status"] == "running" and len(launched) == 1
    assert "VLLM_API_KEY" not in launched[0]["env"]
    # Restoring audit material repairs evidence without restarting execution.
    available = True
    from harbor_helper.execution.audit import audit_finished

    assert audit_finished(store, store.get("first"))
    assert store.get("first")["status"] == "failed"
    assert store.get("first")["audit_status"] == "clean"
    assert "fake-first-marker" not in (first / "worker.log").read_text()


def test_service_submit_publication_lock_cancel_and_frozen_rerun(store, monkeypatch):
    old_path, old = add_run(store, "parent", "succeeded")
    cfg = copy.deepcopy(old["effective"])
    cfg["wall_seconds"] -= 1
    service = {"submission_id": "submission", "submitter": "current"}
    allowed = False

    def locked():
        with (store.root / "control.lock").open("a") as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            return False

    class Publication:
        def __init__(self, root):
            assert root == store.root

        def allow_publish(self, submission_id):
            assert submission_id == "submission" and locked()
            return allowed

    monkeypatch.setitem(
        sys.modules, "harbor_helper.service.data", SimpleNamespace(ServiceData=Publication)
    )

    def unlocked_verify(*args):
        assert not locked(), "Preparation must not reserve the queue control lock"
        return verify_inputs(*args)

    monkeypatch.setattr("harbor_helper.execution.runs.verify_inputs", unlocked_verify)
    monkeypatch.setattr(
        "harbor_helper.execution.runs.ensure_supervisor",
        lambda *_: pytest.fail("Supervisor disabled"),
    )
    with pytest.raises(ValueError, match="cancelled"):
        submit(
            store,
            load_team(store),
            cfg,
            parent=old_path.name,
            service=service,
            run_id="new",
            start_supervisor=False,
        )
    assert not (store.root / "runs" / "new").exists()
    assert len(store.runs()) == 1
    allowed = True
    value = submit(
        store,
        load_team(store),
        cfg,
        parent=old_path.name,
        service=service,
        run_id="new",
        start_supervisor=False,
    )
    new = read_json(store.path(value["run_id"]) / "manifest.json")
    assert new["effective"] == cfg and new["service"] == service
    assert new["source"] == old["source"]


def test_service_preparation_does_not_pause_supervision(store, monkeypatch):
    from harbor_helper.execution.scheduler import Controller

    entered, release = threading.Event(), threading.Event()

    def prepare(_):
        entered.set()
        assert release.wait(5)

    controller = Controller(store)
    try:
        controller.preparation.submit("prepare", prepare, store)
        assert entered.wait(2)
        started = time.monotonic()
        controller.decide(changed=False)
        assert time.monotonic() - started < 1
        assert not release.is_set()
    finally:
        release.set()
        controller.close()


def test_audit_report_failure_never_publishes_clean(store, monkeypatch):
    from harbor_helper.execution.audit import audit_finished

    path, _ = add_run(store, status="failed")
    observed = []

    def fail_report(*args):
        observed.append(store.get(path.name)["audit_status"])
        raise OSError("fixture report unavailable")

    monkeypatch.setattr("harbor_helper.execution.audit.report", fail_report)
    assert not audit_finished(store, store.get(path.name))
    assert observed == ["pending"]
    assert store.get(path.name)["audit_status"] == "incomplete"
    assert not (path / "report.json").exists()


def test_scheduler_keeps_capacity_bypass_in_creation_order(store, monkeypatch):
    from harbor_helper.execution.scheduler import Controller

    add_run(store, "active", "running", concurrency=1)
    add_run(store, "large", concurrency=2)
    add_run(store, "small", concurrency=1)
    team = load_team(store)
    team.update(max_jobs=2, max_trials=2)
    write_json(store.root / "team.json", team)
    monkeypatch.setattr("harbor_helper.execution.scheduler.alive", lambda _: True)
    launched = []

    def launch(self, row):
        launched.append(row["id"])
        return True

    monkeypatch.setattr(Controller, "launch", launch)
    controller = Controller(store)
    try:
        controller.decide()
        assert launched == ["small"]
    finally:
        controller.close()


def test_full_queue_checks_authorization_after_cancellation_before_capacity(store, monkeypatch):
    from harbor_helper.execution.scheduler import Controller

    add_run(store, "active", "running")
    add_run(store, "cancelled")
    store.update("cancelled", cancel=1)
    add_run(store, "unauthorized")
    add_run(store, "valid")
    monkeypatch.setattr("harbor_helper.execution.scheduler.alive", lambda _: True)
    checked = []

    def run_key(self, key, execution=False):
        assert execution
        checked.append(key)
        if key == "unauthorized":
            raise ValueError("secret must not enter failure reason")

    monkeypatch.setattr("harbor_helper.service.data.ServiceData.run_key", run_key)
    controller = Controller(store)
    try:
        controller.decide()
        assert checked == ["unauthorized", "valid"]
        assert store.get("cancelled")["status"] == "cancelled"
        assert store.get("unauthorized")["status"] == "failed"
        assert "secret" not in store.get("unauthorized")["reason"]
        assert store.get("valid")["status"] == "queued"
    finally:
        controller.close()


def test_launch_rechecks_authorization_after_queue_selection(store, monkeypatch):
    from harbor_helper.execution.scheduler import Controller

    add_run(store)
    checked = []

    def run_key(self, key, execution=False):
        checked.append(key)
        if len(checked) == 2:
            raise ValueError("authorization changed before launch")
        return "ephemeral-key"

    monkeypatch.setattr("harbor_helper.service.data.ServiceData.run_key", run_key)
    controller = Controller(store)
    try:
        controller.decide()
        assert checked == ["hh-test", "hh-test"]
        row = store.get("hh-test")
        assert row["status"] == "failed"
        assert row["pid"] is None and row["started"] is None
        assert not (store.path("hh-test") / "worker.log").exists()
    finally:
        controller.close()


@pytest.mark.parametrize("phase", ["queue", "launch"])
@pytest.mark.parametrize("damage", ["missing", "permission", "json", "field", "type", "shape"])
def test_scheduler_isolates_record_input_errors_at_both_authorization_checks(
    store, monkeypatch, phase, damage
):
    import errno

    from harbor_helper.execution.scheduler import Controller

    folder, _ = add_run(store)
    checked = []
    errors = {
        "missing": FileNotFoundError(errno.ENOENT, "secret", str(folder / "manifest.json")),
        "permission": PermissionError(errno.EACCES, "secret", str(folder / "manifest.json")),
        "json": json.JSONDecodeError("secret", "secret", 0),
        "field": KeyError("secret"),
        "type": TypeError("secret"),
        "shape": AttributeError("secret"),
    }

    def run_key(self, key, execution=False):
        checked.append(key)
        if phase == "queue" or len(checked) == 2:
            raise errors[damage]
        return "ephemeral-key"

    monkeypatch.setattr("harbor_helper.service.data.ServiceData.run_key", run_key)
    controller = Controller(store)
    try:
        controller.decide()
        assert len(checked) == (1 if phase == "queue" else 2)
        row = store.get("hh-test")
        assert row["status"] == "failed" and row["audit_status"] == "incomplete"
        assert row["pid"] is None and row["started"] is None
        assert "secret" not in row["reason"] and "secret" not in row["audit_reason"]
        assert not (folder / "worker.log").exists()
        controller.decide()  # A subsequent pass must also keep making progress.
    finally:
        controller.close()


def test_scheduler_log_open_failure_does_not_reserve_capacity(store, monkeypatch):
    from harbor_helper.execution.scheduler import Controller

    folder, _ = add_run(store)
    (folder / "worker.log").mkdir()
    add_run(store, "next")
    launched = []
    monkeypatch.setattr(
        "harbor_helper.execution.scheduler.subprocess.Popen",
        lambda argv, **kwargs: (
            launched.append(argv[-1]) or SimpleNamespace(pid=999999, wait=lambda: None)
        ),
    )
    controller = Controller(store)
    try:
        controller.decide()
        row = store.get("hh-test")
        assert row["status"] == "failed"
        assert row["started"] is None and row["pid"] is None
        assert row["audit_status"] == "incomplete"
        assert launched == ["next"]
        assert store.get("next")["status"] == "running"
    finally:
        controller.close()


@pytest.mark.parametrize("failure", ["sqlite", "io", "fds", "global_file", "initialization"])
def test_scheduler_does_not_reclassify_global_failures_as_bad_runs(store, monkeypatch, failure):
    import errno

    from harbor_helper.execution.scheduler import Controller

    folder, _ = add_run(store)
    errors = {
        "sqlite": sqlite3.OperationalError("database unavailable"),
        "io": OSError(errno.EIO, "disk unavailable", str(folder / "manifest.json")),
        "fds": OSError(errno.EMFILE, "file descriptors exhausted", str(folder / "manifest.json")),
        "global_file": FileNotFoundError(
            errno.ENOENT, "missing global file", str(store.root / "service.json")
        ),
        "initialization": ValueError("global initialization unavailable"),
    }

    def fail(*args, **kwargs):
        raise errors[failure]

    if failure == "initialization":
        monkeypatch.setattr("harbor_helper.service.data.ServiceData.__init__", fail)
    else:
        monkeypatch.setattr("harbor_helper.service.data.ServiceData.run_key", fail)
    controller = Controller(store)
    try:
        with pytest.raises(type(errors[failure])):
            controller.decide()
        row = store.get("hh-test")
        assert row["status"] == "queued"
        assert row["started"] is None and row["pid"] is None
    finally:
        controller.close()
