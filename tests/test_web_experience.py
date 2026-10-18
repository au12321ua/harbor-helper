"""Database-derived evidence eligibility and readable operation history regressions."""

import pytest
from fastapi.testclient import TestClient
from test_service import PASSWORD, WRITE, client
from test_service import data as data  # noqa: PLC0414

from harbor_helper.service import access, history
from harbor_helper.service.api import create_app
from harbor_helper.service.primitives import ServiceError


def test_admin_eligibility_outputs_and_rejected_grants_preserve_pat(data):
    admin = next(u for u in data.users() if u["role"] == "admin")
    new = data.create_user("second-admin", PASSWORD, "admin")
    assert new["evidence_grant"] is True
    web = client(data, "admin")
    assert web.get("/api/v1/me").json()["evidence_grant"] is True
    assert web.get("/api/v1/access-capabilities").json()["evidence_grant"] is True
    assert data.user(admin["id"])["evidence_grant"] is True
    issuance = web.post(
        "/api/v1/access-credentials",
        headers=WRITE,
        json={
            "name": "admin-evidence",
            "current_password": PASSWORD,
            "scopes": ["read", "evidence"],
        },
    )
    assert issuance.status_code == 201
    token = issuance.json()["token"]
    with data.store.connect() as db:
        before = [tuple(r) for r in db.execute("SELECT * FROM access_events")]
    for enabled in (True, False):
        response = web.post(
            f"/api/v1/admin/users/{admin['id']}/evidence-grant",
            headers=WRITE,
            json={"enabled": enabled},
        )
        assert response.status_code == 409
        assert response.json()["code"] == "admin_evidence_inherited"
    with data.store.connect() as db:
        assert [tuple(r) for r in db.execute("SELECT * FROM access_events")] == before
        assert (
            db.execute(
                "SELECT COUNT(*) FROM evidence_grants WHERE user_id=?", (admin["id"],)
            ).fetchone()[0]
            == 0
        )
    actor = data.actor(token)
    assert actor["role"] == "member"  # PAT never inherits admin operations.
    access.require_evidence(data, actor)
    caller = TestClient(create_app(data.root, start_scheduler=False))
    caller.headers["Authorization"] = "Bearer " + token
    assert caller.get("/api/v1/admin/users").status_code == 403
    assert (
        "evidence_manifest" in caller.get("/api/v1/machine/discovery").json()["allowed_operations"]
    )
    # Eligibility uses current DB role even for stale session/PAT role snapshots.
    with data.store.connect() as db:
        db.execute("UPDATE users SET role='member' WHERE id=?", (admin["id"],))
    assert not access.granted(data, admin["id"])
    with pytest.raises(ServiceError):
        access.require_evidence(data, {**admin, "role": "admin"})
    member = next(u for u in data.users() if u["username"] == "alice")
    access.grant(data, new, member["id"], True)
    data.update_user(member["id"], enabled=False)
    assert data.user(member["id"])["evidence_grant"] is True
    assert not access.granted(data, "missing")


def test_history_username_filter_page_missing_account_and_retry(data):
    actor = next(u for u in data.users() if u["username"] == "alice")
    history.decision(
        data.store, actor, "submit", "same", "one", {}, lambda db: {"id": "sub-missing"}
    )
    with pytest.raises(ServiceError):
        history.decision(data.store, actor, "submit", "same", "two", {}, lambda db: {})
    value = history.listing(data.store, actor, status="accepted", operation="submit", limit=1)
    row = value["operations"][0]
    assert row["username"] == "alice"
    assert row["status"] == "accepted" and row["attempts"] == 2
    assert row["recent"][-1]["error"]["code"] == "idempotency_conflict"
    assert history.listing(data.store, actor, status="rejected")["total"] == 0
    with data.store.connect() as db:
        db.execute("DELETE FROM users WHERE id=?", (actor["id"],))
    assert history.listing(data.store, actor, mine=True)["operations"][0]["username"] is None
