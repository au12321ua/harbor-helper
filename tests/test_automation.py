"""Automation API contracts with fake identities and isolated state; no model/Hub/Docker."""

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_attachments import archive
from test_service import PASSWORD, WRITE, client
from test_service import data as service_data
from test_service import preparation as fake_preparation

from harbor_helper.persistence.files import read_json, write_json
from harbor_helper.results.reports import report
from harbor_helper.service import machine
from harbor_helper.service.api import create_app
from harbor_helper.service.application import Application, digest
from harbor_helper.service.data import ServiceError
from harbor_helper.service.lifecycle import prepare_one


@pytest.fixture
def data(tmp_path):
    return service_data.__wrapped__(tmp_path)


@pytest.fixture
def preparation(monkeypatch):
    return fake_preparation.__wrapped__(monkeypatch)


def issue(data, username="alice", scopes=None, expires=None):
    c = client(data, username)
    body = {"name": "research", "current_password": PASSWORD}
    if scopes is not None:
        body["scopes"] = scopes
    if expires is not None:
        body["expires"] = expires
    r = c.post("/api/v1/access-credentials", json=body, headers=WRITE)
    assert r.status_code == 201, r.text
    value = r.json()
    p = TestClient(create_app(data.root, start_scheduler=False), raise_server_exceptions=False)
    p.headers.update({**WRITE, "Authorization": "Bearer " + value["token"]})
    return c, p, value


def test_issue_password_once_digest_metadata_and_lifecycle(data):
    c = client(data)
    wrong = c.post(
        "/api/v1/access-credentials", json={"name": "x", "current_password": "wrong"}, headers=WRITE
    )
    assert wrong.status_code == 401 and "wrong" not in wrong.text
    c, p, value = issue(data)
    raw = value["token"]
    assert raw.startswith("hh_pat_v1_") and len(raw) == 53
    assert 29.99 * 86400 < value["credential"]["expires"] - time.time() <= 30 * 86400
    assert value["credential"]["scopes"] == ["read"]
    metadata = c.get("/api/v1/access-credentials").json()
    assert raw not in json.dumps(metadata) and "digest" not in json.dumps(metadata)
    assert p.get("/api/v1/machine/discovery").status_code == 200
    assert c.get("/api/v1/access-credentials").json()[0]["last_used"] is not None
    with data.store.connect() as db:
        row = dict(db.execute("SELECT * FROM access_credentials").fetchone())
    assert row["digest"] == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in json.dumps(row)
    bob = client(data, "bob")
    assert (
        bob.post(f"/api/v1/access-credentials/{row['id']}/revoke", headers=WRITE).status_code == 404
    )
    assert (
        c.post(f"/api/v1/access-credentials/{row['id']}/revoke", headers=WRITE).status_code == 200
    )
    assert p.get("/api/v1/me").status_code == 401
    _, expired, issued = issue(data, expires=time.time() + 1)
    with data.store.connect() as db:
        db.execute(
            "UPDATE access_credentials SET expires=? WHERE id=?",
            (time.time() - 1, issued["credential"]["id"]),
        )
    assert expired.get("/api/v1/me").status_code == 401
    _, reset, _ = issue(data)
    data.update_user(value["credential"]["user_id"], password=PASSWORD)
    assert reset.get("/api/v1/me").status_code == 401
    _, disabled, _ = issue(data)
    data.update_user(value["credential"]["user_id"], enabled=False)
    assert disabled.get("/api/v1/me").status_code == 401
    data.update_user(value["credential"]["user_id"], enabled=True)
    assert disabled.get("/api/v1/me").status_code == 401


@pytest.mark.parametrize("username", ["alice", "admin"])
def test_scope_matrix_and_admin_never_automation(data, username):
    browser, readonly, _ = issue(data, username)
    body = {"dataset": "test/data@1", "agent": "oracle"}
    assert (
        readonly.post(
            "/api/v1/submissions", json=body, headers={"Idempotency-Key": "x"}
        ).status_code
        == 403
    )
    for method, path, payload in [
        ("GET", "/api/v1/admin/users", None),
        ("GET", "/api/v1/admin/credentials", None),
        ("GET", "/api/v1/admin/access-credentials", None),
        ("POST", "/api/v1/access-credentials", {"name": "x", "current_password": PASSWORD}),
        ("POST", "/api/v1/auth/password", {"current_password": PASSWORD, "password": PASSWORD}),
        ("POST", "/api/v1/auth/logout", {}),
        ("PATCH", "/api/v1/admin/settings", {}),
    ]:
        assert readonly.request(method, path, json=payload).status_code == 403, path
    _, executor, _ = issue(data, username, ["execute"])
    accepted = executor.post(
        "/api/v1/submissions", json=body, headers={"Idempotency-Key": "execute"}
    )
    assert accepted.status_code == 202, accepted.text
    sid = accepted.json()["id"]
    assert executor.get("/api/v1/submission-operations/submit/execute").status_code == 200
    assert executor.get("/api/v1/machine/discovery").status_code == 403
    assert executor.get("/api/v1/me").status_code == 200
    assert executor.post(f"/api/v1/submissions/{sid}/cancel", json={}).status_code == 403
    _, canceler, _ = issue(data, username, ["cancel_own"])
    assert canceler.post(f"/api/v1/submissions/{sid}/cancel", json={}).status_code == 200
    _, uploader, _ = issue(data, username, ["attachments"])
    upload = uploader.post(
        "/api/v1/attachments",
        files={"file": ("bundle.zip", archive())},
        data={"metadata": json.dumps({"name": "input"})},
        headers={"Idempotency-Key": "upload"},
    )
    assert upload.status_code == 201, upload.text
    assert (
        readonly.post("/api/v1/bundles", files={"file": ("bundle.zip", archive())}).status_code
        == 403
    )
    assert uploader.post("/api/v1/submissions", json=body).status_code == 403
    if username == "admin":
        assert browser.get("/api/v1/admin/users").status_code == 200
        other = (
            client(data)
            .post("/api/v1/submissions", json=body, headers={**WRITE, "Idempotency-Key": "other"})
            .json()
        )
        assert (
            canceler.post(f"/api/v1/submissions/{other['id']}/cancel", json={}).status_code == 403
        )
        assert (
            browser.post(f"/api/v1/submissions/{other['id']}/cancel", headers=WRITE).status_code
            == 200
        )


def test_cross_credential_browser_idempotency_and_current_identity(data, preparation):
    browser, first, one = issue(data, scopes=["read", "execute"])
    _, second, two = issue(data, scopes=["read", "execute"])
    _, bob, _ = issue(data, "bob", ["read", "execute"])
    body = {"dataset": "test/data@1", "agent": "oracle"}
    response = first.post("/api/v1/submissions", json=body, headers={"Idempotency-Key": "stable"})
    accepted = response.json()
    assert response.status_code == 202, response.text
    data.set_limits({"max_queue": 1})
    for caller in [second, browser]:
        retry = caller.post(
            "/api/v1/submissions", json=body, headers={**WRITE, "Idempotency-Key": "stable"}
        )
        assert retry.status_code == 202 and retry.json()["id"] == accepted["id"]
        assert (
            caller.get("/api/v1/submission-operations/submit/stable").json()["id"] == accepted["id"]
        )
    assert bob.get("/api/v1/submission-operations/submit/stable").status_code == 404
    _, readonly, _ = issue(data)
    assert readonly.get("/api/v1/submission-operations/submit/stable").status_code == 403
    conflict = second.post(
        "/api/v1/submissions",
        json={**body, "name": "different"},
        headers={"Idempotency-Key": "stable"},
    )
    assert conflict.status_code == 409 and conflict.json()["action"] == "fix_input"
    queue = second.post("/api/v1/submissions", json=body, headers={"Idempotency-Key": "new"})
    assert queue.status_code == 429 and queue.json()["wait_known"] is False
    prepare_one(data.store)
    rid = data.submission(accepted["id"])["run_id"]
    data.set_limits({"max_queue": 10})
    before = (data.store.path(rid) / "manifest.json").read_bytes()
    assert (
        second.post(
            f"/api/v1/runs/{rid}/rerun",
            json={"attachment_version_id": "other"},
            headers={"Idempotency-Key": "illegal-change"},
        ).status_code
        == 422
    )
    child = second.post(
        f"/api/v1/runs/{rid}/rerun", json={}, headers={"Idempotency-Key": "new-rerun"}
    )
    assert child.status_code == 202, child.text
    assert child.json()["access_credential_id"] == two["credential"]["id"]
    assert accepted["access_credential_id"] == one["credential"]["id"]
    assert (data.store.path(rid) / "manifest.json").read_bytes() == before
    assert (
        second.get("/api/v1/submission-operations/rerun/new-rerun").json()["id"]
        == child.json()["id"]
    )
    browser_child = browser.post(
        f"/api/v1/runs/{rid}/rerun", json={}, headers={**WRITE, "Idempotency-Key": "web"}
    )
    assert browser_child.json()["access_credential_id"] is None
    frozen = data.submission(child.json()["id"])["frozen"]
    assert one["token"] not in json.dumps(frozen) and two["token"] not in json.dumps(frozen)
    with data.store.connect() as db:
        events = db.execute(
            "SELECT user_id,access_credential_id FROM access_events WHERE object_id=?",
            (child.json()["id"],),
        ).fetchall()
    assert events and events[0]["access_credential_id"] == two["credential"]["id"]


def test_fixed_operation_target_conflict_and_legacy_lookup(data, preparation):
    app = Application(data.root)
    actor = data.users()[0]
    runs = []
    for key in ("one", "two"):
        accepted = app.accept(actor, {"dataset": "test/data@1", "agent": "oracle"}, key)
        prepare_one(data.store)
        runs.append(data.submission(accepted["id"])["run_id"])
    first = app.accept(actor, {}, "rerun", parent=runs[0])
    with pytest.raises(ServiceError) as error:
        app.accept(actor, {}, "rerun", parent=runs[1])
    assert error.value.code == "idempotency_conflict"
    with data.store.connect() as db:
        db.execute(
            "UPDATE submissions SET operation=?,request_hash=? WHERE id=?",
            ("rerun:" + runs[0], digest({}), first["id"]),
        )
    assert app.accept(actor, {}, "rerun", parent=runs[0])["id"] == first["id"]
    assert machine.lookup(app, actor, "rerun", "rerun")["id"] == first["id"]


def test_schema_safe_discovery_tasks_and_strict_input(data):
    _c, p, _value = issue(data, scopes=["read", "execute"])
    schema = p.get("/api/v1/machine/schema")
    assert schema.status_code == 200, schema.text
    assert "/api/v1/admin" not in schema.text and "AccessIssue" not in schema.text
    assert schema.json()["paths"]["/api/v1/submissions"]["post"]["x-capability"] == "execute"
    assert (
        "SubmissionInput" in schema.text
        and "SafeReport" in schema.text
        and "MachineState" in schema.text
    )
    discovery = p.get("/api/v1/machine/discovery")
    assert discovery.status_code == 200, discovery.text
    for bad in ["ciphertext", "credential_id", str(data.root), "pid", "fake-service-key"]:
        assert bad not in discovery.text
    # Catalog is the already verified metadata; reading it never materializes tasks.
    config = Application(data.root).configuration
    config.persist(
        "dataset",
        {
            "id": "catalog",
            "name": "catalog",
            "enabled": True,
            "status": "verified",
            "reference": "test/data@1",
            "tasks": [
                {"name": str(i), "package": "test/box", "ref": "sha256:fixed"} for i in range(3)
            ],
        },
    )
    result = p.get("/api/v1/machine/datasets/catalog/tasks?limit=2").json()
    assert len(result["tasks"]) == 2 and result["next_offset"] == 2
    assert p.get("/api/v1/machine/datasets/catalog/tasks?limit=101").status_code == 422
    for body in [
        {"agent": "oracle", "attempts": True},
        {"agent": "oracle", "access_credential_id": "spoof"},
    ]:
        assert (
            p.post("/api/v1/submissions", json=body, headers={"Idempotency-Key": "bad"}).status_code
            == 422
        )
    for code, status, action in [
        ("idempotency_conflict", 409, "fix_input"),
        ("idempotency_missing", 404, "retry_same_request"),
        ("login_required", 401, "reauthorize"),
        ("report_pending", 409, "poll_existing"),
        ("audit_incomplete", 409, "contact_admin"),
    ]:
        assert machine.error_action(code, status) == action


def finished(data, preparation, reward=0.0, failure=False):
    app = Application(data.root)
    accepted = app.accept(data.users()[0], {"dataset": "test/data@1", "agent": "oracle"}, "report")
    prepare_one(data.store)
    rid = data.submission(accepted["id"])["run_id"]
    folder = data.store.path(rid) / "harbor" / rid / "box__fixture"
    folder.mkdir(parents=True)
    write_json(
        folder / "result.json",
        {
            "task_name": "test/box",
            "trial_name": "box__fixture",
            "exception_info": {
                "exception_type": "ExecutionError",
                "exception_message": "private /host/private key hidden",
                "traceback": "unsafe",
            }
            if failure
            else None,
            "verifier_result": {"rewards": {"reward": reward}} if reward is not None else None,
        },
    )
    data.store.update(rid, status="failed" if failure else "succeeded", audit_status="clean")
    report(data.store, rid)
    return app, accepted, rid


@pytest.mark.parametrize(
    "reward,failure,expected",
    [(0.0, False, None), (None, False, "missing_score"), (1.0, True, "execution_failure")],
)
def test_three_axes_report_scores_and_evidence_boundary(
    data, preparation, reward, failure, expected
):
    app, accepted, rid = finished(data, preparation, reward, failure)
    state = machine.run_state(app, rid)
    assert state["resource"]["state"] == "released" and state["audit"]["state"] == "clean"
    assert state["report"]["state"] == "available"
    _, p, _ = issue(data)
    response = p.get(state["report_url"])
    assert response.status_code == 200, response.text
    value = response.json()["tasks"][0]["attempts"][0]
    assert value["failure"] == expected
    assert value["rewards"] == ({"reward": 0.0} if reward == 0.0 and not failure else None)
    for bad in ["traceback", "private", str(data.root), "framework_exception", "exception_message"]:
        assert bad not in response.text
    data.store.update(rid, audit_status="incomplete")
    assert machine.run_state(app, rid)["report"]["state"] == "blocked"
    assert p.get(state["report_url"]).status_code == 409
    data.store.update(rid, audit_status="pending")
    assert machine.run_state(app, rid)["report"]["reason"] == "audit_progress_unknown"
    data.store.update(rid, status="cleanup_blocked")
    assert machine.run_state(app, rid)["resource"]["state"] == "cleanup_blocked"
    assert p.get(state["report_url"]).status_code == 409
    data.store.update(rid, status="succeeded", audit_status="clean")
    (data.store.path(rid) / "report.json").unlink()
    assert machine.run_state(app, rid)["report"]["state"] == "unavailable"
    assert machine.submission_state(app, accepted["id"])["report"]["state"] == "unavailable"
    assert p.get(state["report_url"]).json()["action"] == "explicit_new_attempt"


def test_machine_unknown_no_extra_capacity_and_scheduler_observation(data, preparation):
    app, _accepted, rid = finished(data, preparation)
    data.store.update(rid, status="unrecognized")
    assert machine.run_state(app, rid)["resource"]["state"] == "unknown"
    assert app.usage()["active_jobs"] == 0
    write_json(
        data.root / "scheduler.json",
        {
            "pid": os.getpid(),
            "birth": __import__(
                "harbor_helper.execution.processes", fromlist=["process_birth"]
            ).process_birth(os.getpid()),
            "observed": time.time() - 50,
        },
    )
    assert machine.scheduler(app)["state"] == "unknown"
    row = read_json(data.root / "scheduler.json")
    row["observed"] = time.time()
    write_json(data.root / "scheduler.json", row)
    assert machine.scheduler(app)["state"] == "ready"
    row["birth"] = 0
    write_json(data.root / "scheduler.json", row)
    assert machine.scheduler(app)["state"] == "unavailable"


def test_access_plaintext_rejected_upload_and_parent_snapshot(data, preparation):
    _, p, value = issue(data, scopes=["read", "attachments", "execute"])
    for content in [
        value["token"].encode(),
        b"binary\x00" + value["token"].encode(),
        b"hh_pat_v1_" + b"B" * 43,
    ]:
        response = p.post(
            "/api/v1/attachments",
            files={"file": ("bundle.zip", archive(content))},
            data={"metadata": json.dumps({"name": "unsafe"})},
            headers={"Idempotency-Key": "unsafe"},
        )
        assert response.status_code == 422 and value["token"] not in response.text
    _app, _accepted, rid = finished(data, preparation)
    snapshot = data.store.path(rid) / "bundle"
    snapshot.mkdir(exist_ok=True)
    (snapshot / "sdk").mkdir()
    (snapshot / "sdk" / "token").write_text(value["token"])
    response = p.post(
        f"/api/v1/runs/{rid}/rerun", json={}, headers={"Idempotency-Key": "unsafe-rerun"}
    )
    assert response.status_code == 409 and value["token"] not in response.text


def test_recover_retry_new_current_credential_and_permanent_keys(data, preparation):
    browser, p, one = issue(data, scopes=["read", "execute"])
    _, current, two = issue(data, scopes=["read", "execute"])
    body = {"dataset": "test/data@1", "agent": "oracle"}
    first = p.post("/api/v1/submissions", json=body, headers={"Idempotency-Key": "original"}).json()
    with data.store.connect() as db:
        db.execute(
            "UPDATE submissions SET status='failed',error='source_access' WHERE id=?",
            (first["id"],),
        )
    state = current.get(f"/api/v1/machine/submissions/{first['id']}").json()
    assert (
        state["resource"]["state"] == "released"
        and state["report"]["reason"] == "preparation_failed"
    )
    recovery = current.post(
        f"/api/v1/submissions/{first['id']}/retry", json={}, headers={"Idempotency-Key": "recover"}
    )
    assert recovery.status_code == 202, recovery.text
    recovered = recovery.json()
    assert recovered["access_credential_id"] == two["credential"]["id"]
    assert (
        current.get("/api/v1/submission-operations/recover/recover").json()["id"] == recovered["id"]
    )
    # Matching precedes changed original recovery state and changed capacity.
    with data.store.connect() as db:
        db.execute("UPDATE submissions SET status='cancelled' WHERE id=?", (first["id"],))
    data.set_limits({"max_queue": 1})
    assert (
        current.post(
            f"/api/v1/submissions/{first['id']}/retry",
            json={},
            headers={"Idempotency-Key": "recover"},
        ).json()["id"]
        == recovered["id"]
    )
    prepare_one(data.store)
    rid = data.submission(recovered["id"])["run_id"]
    data.set_limits({"max_queue": 10})
    retry = current.post(
        f"/api/v1/runs/{rid}/retry",
        json={"wall_seconds": 1900},
        headers={"Idempotency-Key": "repair"},
    )
    assert retry.status_code == 202, retry.text
    assert retry.json()["access_credential_id"] == two["credential"]["id"]
    assert (
        current.get("/api/v1/submission-operations/retry/repair").json()["id"] == retry.json()["id"]
    )
    assert (
        current.post(
            f"/api/v1/runs/{rid}/retry",
            json={"wall_seconds": 1800},
            headers={"Idempotency-Key": "repair"},
        ).status_code
        == 409
    )
    browser.post(f"/api/v1/access-credentials/{one['credential']['id']}/revoke", headers=WRITE)
    # A fresh app instance authenticates current credential and resolves old member-key.
    reopened = TestClient(create_app(data.root, start_scheduler=False))
    reopened.headers.update({"Authorization": "Bearer " + two["token"]})
    assert reopened.get("/api/v1/submission-operations/submit/original").json()["id"] == first["id"]
    assert p.get("/api/v1/submission-operations/submit/original").status_code == 401
    data.store.update(rid, status="succeeded", audit_status="clean")
    # Archived safety summaries retain normal report gate; parent raw evidence can disappear.
    write_json(data.store.path(rid) / "archived.json", {"expired": True})
    assert (
        reopened.get("/api/v1/submission-operations/recover/recover").json()["id"]
        == recovered["id"]
    )
    cancelled = browser.post(
        "/api/v1/submissions",
        json=body,
        headers={**WRITE, "Idempotency-Key": "cancelled-before-run"},
    ).json()
    browser.post(f"/api/v1/submissions/{cancelled['id']}/cancel", headers=WRITE)
    assert (
        machine.submission_state(Application(data.root), cancelled["id"])["report"]["reason"]
        == "cancelled_before_run"
    )


def test_concurrent_cross_credentials_fixed_key_and_admin_own_boundary(data, preparation):
    _browser, p, one = issue(data, scopes=["read", "execute", "attachments"])
    _, q, _ = issue(data, scopes=["read", "execute"])
    body = {"dataset": "test/data@1", "agent": "oracle"}
    with ThreadPoolExecutor(4) as pool:
        rows = list(
            pool.map(
                lambda i: (p if i % 2 else q).post(
                    "/api/v1/submissions", json=body, headers={"Idempotency-Key": "concurrent"}
                ),
                range(4),
            )
        )
    assert all(r.status_code == 202 for r in rows)
    assert len({r.json()["id"] for r in rows}) == 1
    prepare_one(data.store)
    rid = data.submission(rows[0].json()["id"])["run_id"]
    adminbrowser, adminpat, _ = issue(
        data, "admin", ["read", "execute", "attachments", "cancel_own"]
    )
    assert adminpat.post(f"/api/v1/runs/{rid}/cancel", json={}).status_code == 403
    assert adminbrowser.post(f"/api/v1/runs/{rid}/cancel", headers=WRITE).status_code == 200
    published = p.post(
        "/api/v1/attachments",
        files={"file": ("bundle.zip", archive())},
        data={"metadata": json.dumps({"name": "alice"})},
        headers={"Idempotency-Key": "alice-library"},
    ).json()
    aid = published["attachment"]["id"]
    assert adminpat.patch(f"/api/v1/attachments/{aid}", json={"enabled": False}).status_code == 403
    assert (
        adminbrowser.patch(
            f"/api/v1/attachments/{aid}", json={"enabled": False}, headers=WRITE
        ).status_code
        == 200
    )
    assert (
        adminbrowser.post(
            f"/api/v1/access-credentials/{one['credential']['id']}/revoke", headers=WRITE
        ).status_code
        == 200
    )
    assert p.get("/api/v1/me").status_code == 401
    assert adminpat.get("/api/v1/admin/access-credentials").status_code == 403
    assert adminbrowser.get("/api/v1/admin/access-credentials").status_code == 200


def test_issued_credential_never_persisted_in_request_key_or_metadata(data):
    browser, p, value = issue(data, scopes=["read", "execute", "attachments"])
    raw = value["token"]
    body = {"agent": "oracle", "dataset": "test/data@1"}
    assert (
        p.post(
            "/api/v1/submissions", json={**body, "name": raw}, headers={"Idempotency-Key": "name"}
        ).status_code
        == 422
    )
    assert (
        p.post("/api/v1/submissions", json=body, headers={"Idempotency-Key": raw}).status_code
        == 422
    )
    assert (
        browser.post(
            "/api/v1/access-credentials",
            json={"name": raw, "current_password": PASSWORD},
            headers=WRITE,
        ).status_code
        == 422
    )
    assert (
        p.post(
            "/api/v1/attachments",
            files={"file": ("bundle.zip", archive())},
            data={"metadata": json.dumps({"name": "x"})},
            headers={"Idempotency-Key": raw},
        ).status_code
        == 422
    )
    for file in data.root.rglob("*"):
        if file.is_file():
            assert raw.encode() not in file.read_bytes(), file.name


def test_all_machine_schema_operations_have_types_permissions_and_safe_errors(data):
    _, p, _ = issue(data)
    schema = p.get("/api/v1/machine/schema").json()
    operations = []
    for item in schema["paths"].values():
        for operation in item.values():
            operations.append(operation["x-operation"])
            assert operation["x-capability"] in {"read", "attachments", "execute", "cancel_own"}
            assert operation["responses"]["403"]["content"]["application/json"]["schema"][
                "$ref"
            ].endswith("ErrorResponse")
            success = next(v for k, v in operation["responses"].items() if k.startswith("2"))
            # Schema endpoint returns OpenAPI itself; every business output is typed.
            if operation["x-operation"] != "machine_schema":
                assert success["content"]["application/json"]["schema"]
    assert set(operations) == machine.SCHEMA_OPERATIONS
    attachment = schema["paths"]["/api/v1/attachments"]["post"]
    assert attachment["x-metadata-schema"]["$ref"].endswith("AttachmentCreate")
    assert schema["components"]["schemas"]["ResourceAxis"]["properties"]["state"]["enum"] == [
        "active",
        "released",
        "cleanup_blocked",
        "unknown",
    ]
