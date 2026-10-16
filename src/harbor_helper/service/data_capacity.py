"""Capacity persistence operations sharing the service store."""

from harbor_helper.execution.config import DEFAULT
from harbor_helper.persistence.files import read_json, write_json
from harbor_helper.service.primitives import (
    LIMITS,
    ServiceError,
)


class Capacity:
    def limits(self):
        path = self.root / "limits.json"
        return {**LIMITS, **(read_json(path) if path.exists() else {})}

    def set_limits(self, value):
        if set(value) - set(LIMITS):
            raise ServiceError("unknown_limit", "Unknown capacity or retention parameter")
        limits = {**self.limits(), **value}
        if any(type(v) is not int or v < 1 for v in limits.values()):
            raise ServiceError("invalid_limit", "Limits must be positive integers")
        # Avoid unlimited administrative typo-driven expansion.
        if (
            limits["max_jobs"] > 64
            or limits["max_trials"] > 128
            or limits["max_upload_bytes"] > 1024**3
        ):
            raise ServiceError("invalid_limit", "Limit exceeds first-release safety bound")
        write_json(self.root / "limits.json", limits)
        team = read_json(self.root / "team.json")
        team.update({k: v for k, v in limits.items() if k in DEFAULT})
        write_json(self.root / "team.json", team)
        return limits
