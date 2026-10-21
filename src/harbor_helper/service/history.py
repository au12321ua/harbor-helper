"""Atomic business decisions. Rejected intentions reserve no execution resources."""

import json
import time
import uuid
from contextvars import ContextVar

from harbor_helper.service.primitives import ServiceError

REQUEST_ID: ContextVar[str | None] = ContextVar("operation_request_id", default=None)

ATTEMPT_LIMIT = 32


def decision(store, actor, operation, idem, request_hash, request, perform):
    """Caller validates nonsecret bounded input before entering this transaction."""
    failure = None
    with store.control(), store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute(
            "SELECT * FROM operations WHERE user_id=? AND operation=? AND idem=?",
            (actor["id"], operation, idem),
        ).fetchone()
        operation_id = old["id"] if old else "op-" + uuid.uuid4().hex
        conflict = old and old["request_hash"] != request_hash
        recent = json.loads(old["recent"]) if old else []
        now = time.time()
        if conflict:
            failure = ServiceError(
                "idempotency_conflict", "Idempotency key reused with different input", 409
            )
            result = None
        elif old and old["status"] == "purged":
            result = json.loads(old["result"])
        elif old and operation_recycled(db, old):
            failure = ServiceError("object_recycled", "该记录在回收站，请先恢复", 409)
            result = None
        elif old and old["status"] == "accepted":
            result = json.loads(old["result"])
        else:
            db.execute("SAVEPOINT business")
            try:
                result = perform(db)
            except ValueError as error:
                db.execute("ROLLBACK TO business")
                failure = (
                    error
                    if isinstance(error, ServiceError)
                    else ServiceError(
                        "invalid_operation", "Invalid configuration or experiment reference"
                    )
                )
                result = None
            db.execute("RELEASE business")
        error = (
            {"code": failure.code, "message": str(failure), "status": failure.status}
            if failure
            else None
        )
        from harbor_helper.service.machine import error_action

        if error:
            error.update(
                action=error_action(error["code"], error["status"]),
                retryable=error["status"] in {429, 503},
                request_id=REQUEST_ID.get(),
                operation_id=operation_id,
            )
        recent.append(
            {
                "time": now,
                "request_id": REQUEST_ID.get(),
                "error": error,
                "access_credential_id": actor.get("access_credential_id"),
            }
        )
        recent = recent[-ATTEMPT_LIMIT:]
        if old:
            db.execute(
                "UPDATE operations SET updated=?,attempts=attempts+1,recent=? WHERE id=?",
                (now, json.dumps(recent), operation_id),
            )
        else:
            db.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    operation_id,
                    actor["id"],
                    operation,
                    idem,
                    request_hash,
                    json.dumps(request),
                    now,
                    now,
                    1,
                    "rejected",
                    None,
                    None,
                    json.dumps(recent),
                ),
            )
        if not conflict and not (
            old and (old["status"] == "purged" or operation_recycled(db, old))
        ):
            db.execute(
                "UPDATE operations SET status=?,result=?,error=? WHERE id=?",
                (
                    "rejected" if failure else "accepted",
                    json.dumps(result),
                    json.dumps(error),
                    operation_id,
                ),
            )
        if (
            operation in {"submit", "rerun", "retry", "recover"}
            and failure
            and not conflict
            and not (old and operation_recycled(db, old))
        ):
            from harbor_helper.service.management_data import link_request

            link_request(
                db,
                operation_id,
                actor["id"],
                request.get("name", request.get("body", {}).get("name", "")) or "",
                converting=True,
            )
        if result is not None:
            result = {**result, "operation_id": operation_id, "idempotency_key": idem}
    if failure:
        failure.operation_id = operation_id
        raise failure
    return result


def listing(
    store,
    actor,
    *,
    offset=0,
    limit=50,
    mine=False,
    operation=None,
    key=None,
    operation_id=None,
    user_id=None,
    status=None,
    created_from=None,
    created_to=None,
):
    if offset < 0 or not 1 <= limit <= 100:
        raise ServiceError("invalid_range", "offset >= 0; limit 1–100 required")
    where, params = [], []
    for field, value in (
        ("user_id", actor["id"] if mine else user_id),
        ("operation", operation),
        ("idem", key),
        ("id", operation_id),
    ):
        if value is not None:
            where.append("o." + field + "=?")
            params.append(value)
    if status is not None:
        where.append(
            "(o.status=? OR json_extract(o.result,'$.id') IN (SELECT id FROM submissions WHERE status=? OR run_id IN (SELECT id FROM runs WHERE status=?)))"
        )
        params.extend([status, status, status])
    for operator, timestamp in ((">=", created_from), ("<=", created_to)):
        if timestamp is not None:
            import math

            if not math.isfinite(timestamp):
                raise ServiceError("invalid_range", "Finite time range required")
            where.append("o.created" + operator + "?")
            params.append(timestamp)
    clause = " WHERE " + " AND ".join(where) if where else ""
    with store.connect() as db:
        total = db.execute("SELECT COUNT(*) FROM operations o" + clause, params).fetchone()[0]
        rows = db.execute(
            "SELECT o.*,u.username FROM operations o LEFT JOIN users u ON u.id=o.user_id"
            + clause
            + " ORDER BY o.created DESC,o.id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    values = []
    for row in rows:
        value = dict(row)
        value.pop("request_hash")
        for field in ("request", "result", "error", "recent"):
            value[field] = json.loads(value[field]) if value[field] else None
        with store.connect() as db:
            hidden = operation_recycled(db, row)
        if hidden:
            value.update(
                request={}, result={"id": value["id"], "status": "recycled"}, error=None, recent=[]
            )
        result = value["result"]
        if not hidden and value["status"] != "purged":
            target = result.get("id") if isinstance(result, dict) else None
            with store.connect() as db:
                group = db.execute(
                    "SELECT g.name,l.group_id,l.number,l.source_id,l.relation FROM request_links l JOIN request_groups g ON g.id=l.group_id WHERE l.id IN (?,?) ORDER BY l.number DESC LIMIT 1",
                    (target, value["id"]),
                ).fetchone()
            if group:
                value["request_group"] = dict(group)
        if (
            isinstance(result, dict)
            and isinstance(result.get("id"), str)
            and result["id"].startswith("sub-")
        ):
            with store.connect() as db:
                current = db.execute(
                    "SELECT status,run_id,error FROM submissions WHERE id=?", (result["id"],)
                ).fetchone()
            if current:
                result.update(dict(current))
        value["summarized_attempts"] = value["attempts"] - len(value["recent"])
        values.append(value)
    return {
        "operations": values,
        "total": total,
        "offset": offset,
        "next_offset": offset + limit if offset + limit < total else None,
        "attempt_limit": ATTEMPT_LIMIT,
    }


def operation_recycled(db, operation):
    from harbor_helper.service.management_data import state

    result = json.loads(operation["result"]) if operation["result"] else {}
    targets = [("request", operation["id"])]
    if isinstance(result, dict):
        if isinstance(result.get("id"), str):
            targets.append(("request", result["id"]))
        if isinstance(result.get("version"), dict):
            targets.append(("attachment_version", result["version"].get("id")))
    return any(state(db, kind, object_id) == "recycled" for kind, object_id in targets)
