"""Read-only scheduler activity observation."""

import math
import time


def finite_number(value):
    """Reject booleans and numbers that cannot be represented as finite floats."""
    try:
        return type(value) in {int, float} and math.isfinite(value)
    except OverflowError:
        return False


def scheduler(app):
    from harbor_helper.execution.runs import scheduler_identity

    try:
        identity = scheduler_identity(app.store)
        if not identity:
            return {
                "state": "unavailable",
                "reason": "process_not_confirmed",
                "observed": time.time(),
            }
        heartbeat = identity.get("observed")
        valid = finite_number(heartbeat)
        ready = valid and 0 <= time.time() - heartbeat <= 10
        return {
            "state": "ready" if ready else "unknown",
            "reason": "recent_activity" if ready else "activity_unknown",
            "observed": time.time(),
            "activity_observed": heartbeat if valid else None,
        }
    except (ValueError, OSError, KeyError, TypeError):
        return {"state": "unknown", "reason": "observation_unavailable", "observed": time.time()}
