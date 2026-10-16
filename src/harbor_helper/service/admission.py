"""Persistent new-admission gate; callers serialize mutations with Store.control."""

import re
import time

from harbor_helper.persistence.files import read_json, write_json
from harbor_helper.persistence.wakeup import wake_after
from harbor_helper.security.access_tokens import ACCESS_TOKEN_TEXT
from harbor_helper.security.credentials import redact_value
from harbor_helper.service.observation import finite_number, scheduler
from harbor_helper.service.primitives import ServiceError

DEFAULT_MAINTENANCE = {"paused": False, "reason": "", "retry_at": None, "updated": None}


def maintenance(data):
    path = data.root / "admission.json"
    value = read_json(path) if path.exists() else DEFAULT_MAINTENANCE.copy()
    if (
        not isinstance(value, dict)
        or type(value.get("paused")) is not bool
        or not isinstance(value.get("reason"), str)
        or len(value["reason"]) > 500
        or any(
            value.get(k) is not None and not finite_number(value[k])
            for k in ("retry_at", "updated")
        )
    ):
        raise ServiceError("admission_state_unavailable", "Admission state unavailable", 503)
    return {k: value.get(k) for k in DEFAULT_MAINTENANCE}


@wake_after
def set_maintenance(data, body):
    if not isinstance(body, dict) or set(body) - {"paused", "reason", "retry_at"}:
        raise ServiceError("maintenance_options", "Unknown maintenance field")
    value = {**maintenance(data), **body}
    if type(value["paused"]) is not bool or not isinstance(value["reason"], str):
        raise ServiceError("maintenance_options", "paused boolean and reason text required")
    if not value["paused"]:
        value.update(reason="", retry_at=None)
    reason = value["reason"].strip()
    # A public notice must not become another channel for configured secrets.
    if (
        len(reason) > 500
        or ACCESS_TOKEN_TEXT.search(reason)
        or re.search(r"(?:/[\w.-]+){2,}|(?<!\w)/[\w.-]+|[A-Za-z]:[\\/]|[\x00-\x1f]", reason)
        or (reason and redact_value(reason, data.notice_secrets()) != reason)
    ):
        raise ServiceError(
            "maintenance_reason", "Use a short notice without secrets or internal paths"
        )
    retry = value["retry_at"]
    if retry is not None and (not finite_number(retry) or retry <= time.time()):
        raise ServiceError("maintenance_retry", "Retry time must be a finite future timestamp")
    value = {"paused": value["paused"], "reason": reason, "retry_at": retry, "updated": time.time()}
    write_json(data.root / "admission.json", value)
    return value


def pending(data, user_id):
    """Deduplicate the publication crash window by target, using current run state."""
    with data.store.connect() as db:
        submissions = [
            dict(r) for r in db.execute("SELECT target_id,user_id,status,cancel FROM submissions")
        ]
        runs = {r["id"]: dict(r) for r in db.execute("SELECT id,status FROM runs")}
    owners = {s["target_id"]: s["user_id"] for s in submissions}
    waiting = {
        s["target_id"]: s["user_id"]
        for s in submissions
        if s["status"] == "preparing" and not s["cancel"] and s["target_id"] not in runs
    }
    for rid, row in runs.items():
        if row["status"] != "queued":
            continue
        # Linked submissions are reliable identities. Legacy/local runs may have
        # only a manifest; never infer identity from submitter names or hashes.
        owner = owners.get(rid)
        if owner is None:
            try:
                manifest = read_json(data.store.root / "runs" / rid / "manifest.json")
                owner = (manifest.get("service") or {}).get("user_id")
            except (ValueError, OSError, AttributeError):
                owner = None
        waiting[rid] = owner
    return {
        "global_pending": len(waiting),
        "member_pending": sum(v == user_id for v in waiting.values()) if user_id else 0,
    }


def readiness(app, user_id=None):

    activity = scheduler(app)
    state = maintenance(app.data)
    allowed = not state["paused"] and activity["state"] == "ready"
    limits = app.data.limits()
    return {
        "initialized": True,
        "accepting": allowed,
        "reason": "maintenance_paused"
        if state["paused"]
        else "ready"
        if allowed
        else "scheduler_unready",
        "observed": time.time(),
        "scheduler": activity,
        "maintenance": state,
        "pending": {
            **pending(app.data, user_id),
            "member_limit": min(limits["max_pending_per_member"], limits["max_queue"]),
            "global_limit": limits["max_queue"],
        },
    }


def check(app, actor):
    state = readiness(app, actor["id"])
    if not state["accepting"]:
        code = state["reason"]
        raise ServiceError(
            code,
            "New admissions paused"
            if code == "maintenance_paused"
            else "Scheduler activity not confirmed",
            503,
        )
    counts = state["pending"]
    if counts["global_pending"] >= counts["global_limit"]:
        raise ServiceError("queue_full", "Shared queue capacity reached", 429)
    if counts["member_pending"] >= counts["member_limit"]:
        raise ServiceError("member_queue_full", "Member pending capacity reached", 429)
