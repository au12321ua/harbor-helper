"""Stop intent serialization and actual scheduler lanes/process termination."""

import signal

import pytest
from fastapi.testclient import TestClient
from test_service_process import Processes, wait

from harbor_helper.persistence.files import read_json
from harbor_helper.service.admission import set_maintenance
from harbor_helper.service.api import create_app
from harbor_helper.service.primitives import ServiceError
from harbor_helper.service.shutdown import observe, request


@pytest.fixture
def instance(tmp_path):
    process = Processes(tmp_path)
    process.start()
    try:
        yield process
    finally:
        # Release intentionally held preparation before teardown.
        for name in ("prepare-hold", "worker-hold"):
            (process.data.root / name).unlink(missing_ok=True)
        process.close()


def pause(p):
    with p.data.store.control():
        set_maintenance(p.data, {"paused": True})


def test_wait_includes_preparing_queued_and_preserves_gate(instance):
    p = instance
    hold = p.data.root / "prepare-hold"
    hold.touch()
    submissions = [p.submit(idem=str(i), oracle=True) for i in range(3)]
    pause(p)
    request(p.data, "wait", {"username": "admin"})
    assert observe(p.data)["counts"]["preparing"] == 3
    assert p.child.poll() is None
    hold.unlink()
    wait(lambda: read_json(p.data.root / "shutdown.json")["phase"] == "complete")
    p.child.wait(timeout=10)
    assert p.child.returncode == 0
    assert all(p.data.submission(s["id"])["status"] == "ready" for s in submissions)
    assert all(r["status"] == "succeeded" for r in p.data.store.runs())
    p.start()
    assert observe(p.data)["maintenance"]["paused"] is True


def test_cancel_preparation_and_running_and_queued(instance):
    p = instance
    (p.data.root / "worker-hold").touch()
    one = p.submit(oracle=True)
    rid = p.run_id(one)
    wait(lambda: p.data.store.get(rid)["status"] == "running")
    two = p.submit(idem="two", oracle=True)
    p.run_id(two)
    hold = p.data.root / "prepare-hold"
    hold.touch()
    three = p.submit(idem="three", oracle=True)
    pause(p)
    request(p.data, "cancel", {"username": "admin"})
    assert observe(p.data)["intent"]["phase"] == "draining"
    # A cancelled preparation is still actual background work until the lane exits.
    assert p.child.poll() is None
    hold.unlink()
    wait(lambda: read_json(p.data.root / "shutdown.json")["phase"] == "complete")
    p.child.wait(timeout=10)
    assert p.data.submission(three["id"])["status"] == "cancelled"
    assert all(r["status"] == "cancelled" for r in p.data.store.runs())


def test_raw_sigterm_preserves_queued_and_interrupts_running(instance):
    p = instance
    (p.data.root / "worker-hold").touch()
    first = p.submit(oracle=True)
    rid = p.run_id(first)
    wait(lambda: p.data.store.get(rid)["status"] == "running")
    second = p.submit(idem="second", oracle=True)
    queued = p.run_id(second)
    p.child.send_signal(signal.SIGTERM)
    p.child.wait(timeout=15)
    assert p.data.store.get(rid)["status"] == "cancelled"
    assert p.data.store.get(queued)["status"] == "queued"
    assert observe(p.data)["maintenance"]["paused"] is False


def test_requires_explicit_gate_and_abort_never_reopens(instance):
    p = instance
    before = observe(p.data)
    with pytest.raises(ServiceError, match="Explicitly close"):
        request(p.data, "wait", {"username": "admin"})
    assert observe(p.data) == before
    pause(p)
    request(p.data, "abort", {"username": "admin"})
    assert observe(p.data)["maintenance"]["paused"]


def test_http_admin_only_and_no_scheduler_spawn(instance, monkeypatch):
    p = instance
    monkeypatch.setattr(
        "harbor_helper.execution.runs.ensure_supervisor",
        lambda _: pytest.fail("HTTP spawned scheduler"),
    )
    with TestClient(create_app(p.data.root)) as client:
        headers = {"X-Requested-With": "harbor-helper"}
        client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "Fake-process-password-2026"},
            headers=headers,
        )
        assert client.get("/api/v1/admin/shutdown").status_code == 403
        client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "Fake-process-password-2026"},
            headers=headers,
        )
        assert client.get("/api/v1/admin/shutdown").status_code == 200
        assert (
            client.post(
                "/api/v1/admin/shutdown", json={"mode": "wait"}, headers=headers
            ).status_code
            == 409
        )
