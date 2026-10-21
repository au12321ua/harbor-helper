"""Admission budgets and maintenance: isolated state, explicit synthetic unit activity."""

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from admission_fixture import synthetic_activity
from admission_support import accept, actor, pause
from automation_support import issue
from fastapi.testclient import TestClient
from service_support import WRITE, client

from harbor_helper.persistence.files import read_json, write_json
from harbor_helper.service import admission, machine
from harbor_helper.service.api import create_app
from harbor_helper.service.application import Application
from harbor_helper.service.lifecycle import prepare_one
from harbor_helper.service.primitives import ServiceError


def test_multi_pat_browser_shared_identity_quota_and_admin(data):
    data.set_limits({"max_pending_per_member": 2, "max_queue": 6})
    web, pat1, _ = issue(data, scopes=["read", "execute"])
    _, pat2, _ = issue(data, scopes=["read", "execute"])
    body = {"agent": "oracle"}

    def submit(c, key):
        return c.post("/api/v1/submissions", json=body, headers={**WRITE, "Idempotency-Key": key})

    assert submit(pat1, "a").status_code == 202
    assert submit(web, "b").status_code == 202
    full = submit(pat2, "c")
    assert full.status_code == 429 and full.json()["code"] == "member_queue_full"
    assert full.json()["wait_known"] is False and full.json()["wait_seconds"] is None
    assert submit(pat2, "a").json()["id"] == submit(web, "a").json()["id"]
    assert submit(client(data, "bob"), "bob").status_code == 202
    admin = client(data, "admin")
    assert submit(admin, "admin1").status_code == 202
    assert submit(admin, "admin2").status_code == 202
    assert submit(admin, "admin3").json()["code"] == "member_queue_full"
    counts = web.get("/api/v1/readiness").json()["pending"]
    assert counts == {
        "global_pending": 5,
        "member_pending": 2,
        "member_limit": 2,
        "global_limit": 6,
    }


def test_concurrent_unique_acceptance_and_limit_reduction(data):
    data.set_limits({"max_pending_per_member": 2})

    def attempt(key):
        try:
            return accept(data, key)["id"]
        except ServiceError as e:
            return e.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        result = list(pool.map(attempt, ["same"] * 8))
    assert len(set(result)) == 1
    with ThreadPoolExecutor(max_workers=8) as pool:
        result = list(pool.map(attempt, [str(i) for i in range(8)]))
    assert result.count("member_queue_full") == 7
    data.set_limits({"max_pending_per_member": 1})
    assert admission.pending(data, actor(data)["id"])["member_pending"] == 2
    assert attempt("new") == "member_queue_full"
    assert attempt("same") != "member_queue_full"
    accept(data, "other", "bob")


def test_target_publication_crash_dedup_and_releases(data, preparation):
    data.set_limits({"max_pending_per_member": 1})
    first = accept(data, "first")
    prepare_one(data.store)
    row = data.submission(first["id"])
    rid = row["run_id"]
    with data.store.connect() as db:
        db.execute(
            "UPDATE submissions SET status='preparing',run_id=NULL WHERE id=?", (first["id"],)
        )
    assert admission.pending(data, actor(data)["id"])["member_pending"] == 1
    assert admission.pending(data, actor(data)["id"])["global_pending"] == 1
    for status in ("running", "cleanup_blocked", "succeeded", "failed", "cancelled"):
        data.store.update(rid, status=status)
        assert admission.pending(data, actor(data)["id"]) == {
            "global_pending": 0,
            "member_pending": 0,
        }
    second = accept(data, "second")
    Application(data.root).cancel_submission(actor(data), second["id"])
    assert admission.pending(data, actor(data)["id"])["member_pending"] == 0
    third = accept(data, "third")
    with data.store.connect() as db:
        db.execute("UPDATE submissions SET status='failed' WHERE id=?", (third["id"],))
    assert admission.pending(data, actor(data)["id"])["member_pending"] == 0
    accept(data, "fourth")


def test_unknown_legacy_owner_global_capacity_and_effective_limit(data):
    data.set_limits({"max_queue": 1, "max_pending_per_member": 20})
    with data.store.connect() as db:
        db.execute(
            "INSERT INTO runs(id,status,created,concurrency) VALUES('legacy','queued',?,1)",
            (time.time(),),
        )
    folder = data.root / "runs/legacy"
    folder.mkdir()
    write_json(
        folder / "manifest.json",
        {"service": {"submitter": "alice"}, "effective": {"agent": "oracle", "dataset": "legacy"}},
    )
    assert admission.pending(data, actor(data)["id"]) == {"global_pending": 1, "member_pending": 0}
    assert (
        admission.readiness(Application(data.root), actor(data)["id"])["pending"]["member_limit"]
        == 1
    )
    with pytest.raises(ServiceError, match="Shared queue"):
        accept(data, "new")
    data.store.update("legacy", status="running")
    assert admission.pending(data, actor(data)["id"])["global_pending"] == 0
    assert Application(data.root).usage()["active_jobs"] == 1


def test_pause_restart_old_keys_scope_and_all_new_operations(data, preparation):
    app = Application(data.root)
    first = accept(data, "old")
    prepare_one(data.store)
    rid = data.submission(first["id"])["run_id"]
    failed = accept(data, "failed")
    with data.store.connect() as db:
        db.execute("UPDATE submissions SET status='failed' WHERE id=?", (failed["id"],))
    pause(data)
    data.store.update(rid, status="succeeded")
    reopened = Application(data.root)
    assert not admission.readiness(reopened)["accepting"]
    assert accept(data, "old")["id"] == first["id"]
    for opts in ({}, {"parent": rid}, {"parent": rid, "retry": True}, {"recovery": failed["id"]}):
        with pytest.raises(ServiceError) as e:
            reopened.accept(actor(data), {"agent": "oracle"} if not opts else {}, "new", **opts)
        assert e.value.code == "maintenance_paused"
    _, readonly, _ = issue(data, scopes=["read"])
    denied = readonly.post(
        "/api/v1/submissions", headers={"Idempotency-Key": "old"}, json={"agent": "oracle"}
    )
    assert denied.status_code == 403 and denied.json()["code"] == "scope_required"
    _, admin_pat, _ = issue(data, "admin", ["read", "execute"])
    assert admin_pat.patch("/api/v1/admin/maintenance", json={"paused": False}).status_code == 403
    assert admin_pat.get("/api/v1/readiness").json()["maintenance"]["paused"]
    data.root.joinpath("scheduler.json").unlink()
    assert accept(data, "old")["id"] == first["id"]
    assert machine.lookup(app, actor(data), "submit", "old")["id"] == first["id"]
    pause(data, False)
    with pytest.raises(ServiceError) as e:
        accept(data, "new")
    assert e.value.code == "scheduler_unready"
    synthetic_activity(data)
    accept(data, "new")


def test_maintenance_linearized_concurrency_cross_process_and_reopen(data):
    # Both operations acquire the same OS lock. The result admits only before pause.
    for i in range(5):
        pause(data, False)
        with ThreadPoolExecutor(max_workers=2) as pool:
            accepted = pool.submit(lambda i=i: accept(data, f"race-{i}"))
            paused = pool.submit(lambda: pause(data))
            paused.result()
            try:
                accepted.result()
            except ServiceError as e:
                assert e.code == "maintenance_paused"
        with pytest.raises(ServiceError) as e:
            accept(data, f"after-{i}")
        assert e.value.code == "maintenance_paused"
    code = "from harbor_helper.service.application import Application; from harbor_helper.service.admission import readiness; import sys,json; print(json.dumps(readiness(Application(sys.argv[1]))))"
    result = subprocess.run(
        [sys.executable, "-c", code, str(data.root)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["maintenance"]["paused"]
    assert TestClient(create_app(data.root, start_scheduler=False)).get(
        "/api/v1/health"
    ).json() == {"alive": True, "ready": False}


def test_safe_health_readiness_stale_and_corrupt_gate(data, tmp_path):
    anonymous = TestClient(create_app(data.root, start_scheduler=False))
    assert anonymous.get("/api/v1/health").json() == {"alive": True, "ready": True}
    assert anonymous.get("/api/v1/readiness").status_code == 401
    web = client(data)
    value = web.get("/api/v1/readiness").json()
    encoded = json.dumps(value)
    for secret in (str(data.root), '"pid"', '"birth"', '"config"', '"master"', '"ciphertext"'):
        assert secret not in encoded
    state = read_json(data.root / "scheduler.json")
    state["observed"] -= 20
    write_json(data.root / "scheduler.json", state)
    assert web.get("/api/v1/readiness").json()["scheduler"]["state"] == "unknown"
    assert anonymous.get("/api/v1/health").json()["ready"] is False
    state["birth"] = "not-real"
    write_json(data.root / "scheduler.json", state)
    assert web.get("/api/v1/readiness").json()["scheduler"]["state"] == "unavailable"
    synthetic_activity(data)
    (data.root / "admission.json").write_text('{"paused":"bad"}')
    with pytest.raises(ServiceError):
        accept(data, "corrupt")
    assert anonymous.get("/api/v1/health").json()["ready"] is False
    fresh = TestClient(create_app(tmp_path / "new", start_scheduler=False))
    assert fresh.get("/api/v1/health").json() == {"alive": True, "ready": False}


def test_notice_validation_and_machine_schema(data):
    admin = client(data, "admin")
    for body in (
        {"paused": "yes"},
        {"paused": True, "reason": "path /tmp/internal"},
        {"paused": True, "reason": "fake-service-key-one-2026"},
        {"paused": True, "retry_at": -1},
    ):
        assert admin.patch("/api/v1/admin/maintenance", headers=WRITE, json=body).status_code == 422
    retry = time.time() + 3600
    r = admin.patch(
        "/api/v1/admin/maintenance",
        headers=WRITE,
        json={"paused": True, "reason": "upgrade", "retry_at": retry},
    )
    assert r.status_code == 200
    member = client(data)
    assert member.get("/api/v1/readiness").json()["maintenance"]["retry_at"] == retry
    schema = member.get("/api/v1/machine/schema").json()
    assert "/api/v1/readiness" in schema["paths"]
    assert "/api/v1/admin/maintenance" not in schema["paths"]
    discovered = member.get("/api/v1/machine/discovery").json()
    assert discovered["readiness"]["maintenance"]["paused"]
    assert "no_maintenance_or_member_quota" not in discovered["limitations"]


def test_actual_preparation_failure_and_queue_cancel_release(data, preparation, monkeypatch):
    data.set_limits({"max_pending_per_member": 1})
    first = accept(data, "failed-source")
    with monkeypatch.context() as m:

        def broken(*args, **kwargs):
            raise RuntimeError("fixture-only preparation failure")

        m.setattr("harbor_helper.service.sources.source_call", broken)
        prepare_one(data.store)
    assert data.submission(first["id"])["status"] == "failed"
    assert admission.pending(data, actor(data)["id"])["member_pending"] == 0
    second = accept(data, "queued")
    prepare_one(data.store)
    rid = data.submission(second["id"])["run_id"]
    Application(data.root).cancel_run(actor(data), rid)
    # Cancellation request alone does not manufacture a terminal run state.
    assert admission.pending(data, actor(data)["id"])["member_pending"] == 1
    from scheduler_support import settle

    settle(data.store)
    assert data.store.get(rid)["status"] == "cancelled"
    assert admission.pending(data, actor(data)["id"])["member_pending"] == 0
    accept(data, "replacement")


def test_legacy_json_upgrade_preserves_schema_ciphertext_master_and_manifest(data, preparation):
    app = Application(data.root)
    app.configuration.save_hub("fake-hub-notice-key")
    accept(data, "historical")
    prepare_one(data.store)
    manifest = data.store.path(data.store.runs()[0]["id"]) / "manifest.json"
    old_bytes = manifest.read_bytes()
    legacy_limits = data.limits()
    legacy_limits.pop("max_pending_per_member")
    legacy_limits["max_queue"] = 4
    write_json(data.root / "limits.json", legacy_limits)
    master = (
        __import__("pathlib").Path(read_json(data.root / "service.json")["master_directory"])
        / "master"
    )
    key_bytes = master.read_bytes()

    def preserved():
        with data.store.connect() as db:
            return (
                [
                    tuple(r)
                    for r in db.execute(
                        "SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name"
                    )
                ],
                [tuple(r) for r in db.execute("SELECT * FROM credential_versions")],
                [tuple(r) for r in db.execute("SELECT * FROM source_credentials")],
            )

    before = preserved()
    reopened = Application(data.root)
    assert reopened.data.limits()["max_pending_per_member"] == 10
    assert admission.readiness(reopened, actor(data)["id"])["pending"]["member_limit"] == 4
    pause(data)
    assert admission.maintenance(reopened.data)["paused"]
    assert preserved() == before
    assert master.read_bytes() == key_bytes and master.stat().st_mode & 0o777 == 0o600
    assert manifest.read_bytes() == old_bytes
    # Both active and disabled Hub keys are excluded from member notices.
    with pytest.raises(ServiceError) as e:
        admission.set_maintenance(data, {"paused": True, "reason": "fake-hub-notice-key"})
    assert e.value.code == "maintenance_reason"
    app.configuration.save_hub(enabled=False)
    with pytest.raises(ServiceError):
        admission.set_maintenance(data, {"paused": True, "reason": "fake-hub-notice-key"})
