"""Numeric gate boundaries; isolated fake accounts and synthetic process activity."""

import json

import pytest
from support.admission_support import accept
from support.service_support import WRITE, client

from harbor_helper.persistence.files import read_json, write_json
from harbor_helper.service import admission, observation
from harbor_helper.service.application import Application

INVALID = [True, float("nan"), float("inf"), float("-inf"), 10**400, -(10**400)]
IDS = ["bool", "nan", "inf", "negative-inf", "huge-int", "negative-huge-int"]


@pytest.mark.parametrize("value", INVALID, ids=IDS)
def test_invalid_requested_retry_is_safe_422(data, value):
    admin = client(data, "admin")
    # Raw JSON also exercises nonfinite literals rejected by the service validation.
    response = admin.patch(
        "/api/v1/admin/maintenance",
        headers={**WRITE, "Content-Type": "application/json"},
        content=json.dumps({"paused": True, "retry_at": value}),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "maintenance_retry"
    assert admission.maintenance(data) == admission.DEFAULT_MAINTENANCE


@pytest.mark.parametrize("field", ["retry_at", "updated"])
@pytest.mark.parametrize("value", INVALID, ids=IDS)
def test_corrupt_persisted_timestamp_blocks_health_and_admission(data, field, value):
    old = accept(data, "old")
    web = client(data)
    write_json(data.root / "admission.json", {**admission.DEFAULT_MAINTENANCE, field: value})
    response = web.get("/api/v1/readiness")
    assert response.status_code == 503
    assert response.json()["code"] == "admission_state_unavailable"
    assert web.get("/api/v1/health").json() == {"alive": True, "ready": False}
    response = web.post(
        "/api/v1/submissions", headers={**WRITE, "Idempotency-Key": "new"}, json={"agent": "oracle"}
    )
    assert response.status_code == 503
    assert response.json()["code"] == "admission_state_unavailable"
    assert accept(data, "old")["id"] == old["id"]


@pytest.mark.parametrize("value", INVALID, ids=IDS)
def test_invalid_scheduler_timestamp_is_unknown_and_blocks_admission(data, value):
    old = accept(data, "old")
    state = read_json(data.root / "scheduler.json")
    write_json(data.root / "scheduler.json", {**state, "observed": value})
    activity = observation.scheduler(Application(data.root))
    assert activity["state"] == "unknown"
    assert activity.get("activity_observed") is None
    web = client(data)
    assert web.get("/api/v1/readiness").json()["accepting"] is False
    assert web.get("/api/v1/health").json() == {"alive": True, "ready": False}
    response = web.post(
        "/api/v1/submissions", headers={**WRITE, "Idempotency-Key": "new"}, json={"agent": "oracle"}
    )
    assert response.status_code == 503
    assert response.json()["code"] == "scheduler_unready"
    assert accept(data, "old")["id"] == old["id"]


def test_large_representable_numbers_have_no_arbitrary_ceiling(data):
    value = 10**300
    with data.store.control():
        assert (
            admission.set_maintenance(data, {"paused": True, "retry_at": value})["retry_at"]
            == value
        )
    assert admission.maintenance(data)["retry_at"] == value
    state = read_json(data.root / "scheduler.json")
    write_json(data.root / "scheduler.json", {**state, "observed": value})
    activity = observation.scheduler(Application(data.root))
    assert activity["state"] == "unknown"
    assert activity["activity_observed"] == value
