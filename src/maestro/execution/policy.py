"""Platform error policy (06 section 3, U-15) and the Harbor 0.24.0 adapter mapping.

The policy is the platform's and carries its own version; the adapter only names
which Harbor exception types fall under which policy rule. Exception names are
plain strings: the service never imports Harbor.
"""

import math
from dataclasses import dataclass

from maestro.boundaries.executor import AttemptOutcome
from maestro.core.digests import digest_json

POLICY_VERSION = "platform-1"
HARBOR_VERSION = "0.24.0"


@dataclass(frozen=True)
class Rule:
    cause: str
    reward_valid: bool
    retry: bool
    grade: bool


RULES = {
    "agent_exhausted_budget": Rule("agent_exhausted_budget", True, False, True),
    "agent_refused_task": Rule("agent_refused_task", True, False, True),
    "sandbox_failed": Rule("sandbox_failed", False, True, False),
    "provider_transient": Rule("model_provider_failed", False, True, True),
    "provider_permanent": Rule("model_provider_failed", False, False, True),
    "provider_auth": Rule("model_provider_failed", False, False, False),
    "harbor_failed": Rule("harbor_failed", False, False, False),
    "verifier_failed": Rule("verifier_failed", False, False, True),
    "unclassified": Rule("unclassified", False, True, True),
    "cancelled": Rule("cancelled", False, False, False),
}

# Exception class names raised by the locked Harbor version, read from its source.
HARBOR_EXCEPTIONS = {
    "AgentTimeoutError": "agent_exhausted_budget",
    "ContextLengthExceededError": "agent_exhausted_budget",
    "OutputLengthExceededError": "agent_exhausted_budget",
    "OutputTokenExceededError": "agent_exhausted_budget",
    "ContextWindowExceededError": "agent_exhausted_budget",
    "AgentSafetyRefusalError": "agent_refused_task",
    "EnvironmentStartTimeoutError": "sandbox_failed",
    "AgentSetupTimeoutError": "sandbox_failed",
    "SandboxBuildFailedError": "sandbox_failed",
    "HealthcheckError": "sandbox_failed",
    "MemoryLimitExceededError": "sandbox_failed",
    "SandboxLikelyOutOfMemoryError": "sandbox_failed",
    "ApiRateLimitError": "provider_transient",
    "ApiInternalServerError": "provider_transient",
    "ApiOverloadedError": "provider_transient",
    "ApiConnectionClosedError": "provider_transient",
    "ApiResponseStalledError": "provider_transient",
    "NetworkConnectionError": "provider_transient",
    "ApiError": "provider_permanent",
    "UnknownApiError": "provider_permanent",
    "ApiUsageLimitError": "provider_permanent",
    "AgentAuthenticationError": "provider_auth",
    "ModelNotFoundError": "provider_auth",
    "ApiProviderResourceNotFoundError": "provider_auth",
    "ServiceOperationsUnsupportedError": "harbor_failed",
    "MissingExtraError": "harbor_failed",
    "VerifierTimeoutError": "verifier_failed",
    "RewardFileNotFoundError": "verifier_failed",
    "RewardFileEmptyError": "verifier_failed",
    "VerifierOutputParseError": "verifier_failed",
    "AddTestsDirError": "verifier_failed",
    "DownloadVerifierDirError": "verifier_failed",
    "CancelledError": "cancelled",
}

MAPPING_ID = (
    f"harbor-{HARBOR_VERSION}/"
    + digest_json({"policy": POLICY_VERSION, "map": HARBOR_EXCEPTIONS})[7:19]
)

# D-011 initial values: at most 3 attempts, 5 s then 20 s back-off.
MAX_RETRIES = 2
RETRY_MIN_WAIT_SEC = 5.0
RETRY_WAIT_MULTIPLIER = 4.0
RETRY_MAX_WAIT_SEC = 20.0


def harbor_retry_config() -> dict:
    """Job-internal retry settings handed to Harbor (D-020): everything is retried
    except what the platform policy says not to, which keeps unknown exceptions
    retryable like the ``unclassified`` rule. Harbor's own default list is not used."""
    return {
        "max_retries": MAX_RETRIES,
        "exclude_exceptions": sorted(
            name for name, rule in HARBOR_EXCEPTIONS.items() if not RULES[rule].retry
        ),
        "min_wait_sec": RETRY_MIN_WAIT_SEC,
        "wait_multiplier": RETRY_WAIT_MULTIPLIER,
        "max_wait_sec": RETRY_MAX_WAIT_SEC,
    }


def legal_score(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def primary_score(rewards) -> float | None:
    """The ``reward`` key, or the only value. Scoring contracts (06 section 2) arrive in M6."""
    if not isinstance(rewards, dict) or not rewards:
        return None
    if "reward" in rewards:
        return rewards["reward"]
    if len(rewards) == 1:
        return next(iter(rewards.values()))
    return None


def harbor_outcome(
    exception_type: str | None,
    message: str | None,
    rewards,
    verifier_ran: bool,
) -> AttemptOutcome:
    raw = primary_score(rewards)
    metrics = rewards if isinstance(rewards, dict) else {}
    usable = verifier_ran and legal_score(raw)
    raw = raw if legal_score(raw) else None
    if exception_type is None:
        if usable:
            return AttemptOutcome(raw_score=raw, reward_valid=True, verifier_status="ok")
        rule = RULES["verifier_failed"]
        return AttemptOutcome(
            raw_score=raw,
            reward_valid=False,
            failure_cause=rule.cause,
            exception_type="RewardMissing",
            message="Verifier produced no usable reward",
            verifier_status="no_reward" if verifier_ran else "not_run",
            metrics=metrics,
        )
    rule = RULES[HARBOR_EXCEPTIONS.get(exception_type, "unclassified")]
    return AttemptOutcome(
        raw_score=raw,
        reward_valid=rule.reward_valid and usable,
        failure_cause=rule.cause,
        exception_type=exception_type,
        message=message,
        retry_recommended=rule.retry,
        grade_requested=rule.grade,
        verifier_status=("ok" if usable else "no_reward") if verifier_ran else "not_run",
        metrics=metrics,
    )
