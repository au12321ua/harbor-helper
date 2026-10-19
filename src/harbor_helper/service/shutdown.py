"""Durable maintenance coordination; all decisions serialize with admission/publication."""

import time

from harbor_helper.persistence.files import read_json, write_json
from harbor_helper.persistence.store import TERMINAL
from harbor_helper.service.admission import maintenance
from harbor_helper.service.primitives import ServiceError


def intent(store):
    path = store.root / "shutdown.json"
    return read_json(path) if path.exists() else {"mode": "none", "phase": "idle", "updated": None}


def counts(store):
    with store.connect() as db:
        runs = [dict(r) for r in db.execute("SELECT id,status,audit_status FROM runs")]
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='submissions'").fetchone()
        preparing = (
            list(db.execute("SELECT target_id FROM submissions WHERE status='preparing'"))
            if exists
            else []
        )
    published = {r["id"] for r in runs}
    result = {
        key: 0
        for key in (
            "preparing",
            "queued",
            "starting",
            "running",
            "cancelling",
            "cleanup_blocked",
            "audit_incomplete",
        )
    }
    result["preparing"] = sum(r[0] not in published for r in preparing)
    for row in runs:
        if row["status"] in result:
            result[row["status"]] += 1
        if row["status"] in TERMINAL and row["audit_status"] == "incomplete":
            result["audit_incomplete"] += 1
    return result


def unfinished(store):
    return sum(v for k, v in counts(store).items() if k != "audit_incomplete")


def observe(data):
    return {
        "maintenance": maintenance(data),
        "intent": intent(data.store),
        "counts": counts(data.store),
    }


def request(data, mode, actor):
    if mode not in {"wait", "cancel", "abort"}:
        raise ServiceError("shutdown_mode", "Choose wait, cancel or abort")
    store = data.store
    with store.control():
        from harbor_helper.persistence.upgrades import ownership

        ownership(store.root)
        if not maintenance(data)["paused"]:
            raise ServiceError("maintenance_required", "Explicitly close new admissions first", 409)
        old = intent(store)
        if old["phase"] == "complete" and mode != "abort":
            return observe(data)
        if old["mode"] == "cancel" and old["phase"] == "draining" and mode == "wait":
            raise ServiceError("shutdown_irreversible", "Cancellation already requested", 409)
        value = {
            "mode": mode,
            "phase": "idle" if mode == "abort" else "draining",
            "updated": time.time(),
        }
        write_json(store.root / "shutdown.json", value)
        if mode == "cancel":
            cancel_all(store)
        data.event(actor, "shutdown_" + mode, "scheduler")
        return observe(data)


def cancel_all(store):
    """Caller holds control; preparing IO may finish, but publication rechecks cancel."""
    with store.connect() as db:
        db.execute("UPDATE submissions SET cancel=1 WHERE status='preparing'")
        db.execute(
            "UPDATE runs SET cancel=1 WHERE status NOT IN ('succeeded','failed','cancelled')"
        )


def complete(store):
    value = intent(store)
    write_json(store.root / "shutdown.json", {**value, "phase": "complete", "updated": time.time()})
