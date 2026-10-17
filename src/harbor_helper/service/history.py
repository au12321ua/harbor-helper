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
        if not conflict:
            db.execute(
                "UPDATE operations SET status=?,result=?,error=? WHERE id=?",
                (
                    "rejected" if failure else "accepted",
                    json.dumps(result),
                    json.dumps(error),
                    operation_id,
                ),
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
            where.append(field + "=?")
            params.append(value)
    if status is not None:
        where.append(
            "(status=? OR json_extract(result,'$.id') IN (SELECT id FROM submissions WHERE status=? OR run_id IN (SELECT id FROM runs WHERE status=?)))"
        )
        params.extend([status, status, status])
    for operator, timestamp in ((">=", created_from), ("<=", created_to)):
        if timestamp is not None:
            import math

            if not math.isfinite(timestamp):
                raise ServiceError("invalid_range", "Finite time range required")
            where.append("created" + operator + "?")
            params.append(timestamp)
    clause = " WHERE " + " AND ".join(where) if where else ""
    with store.connect() as db:
        total = db.execute("SELECT COUNT(*) FROM operations" + clause, params).fetchone()[0]
        rows = db.execute(
            "SELECT * FROM operations" + clause + " ORDER BY created DESC,id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    values = []
    for row in rows:
        value = dict(row)
        value.pop("request_hash")
        for field in ("request", "result", "error", "recent"):
            value[field] = json.loads(value[field]) if value[field] else None
        result = value["result"]
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
