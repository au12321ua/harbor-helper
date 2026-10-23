"""D-011 initial values. Team-adjustable policies move to the database with M5;
capabilities always report the values actually in force."""

PAT_DEFAULT_DAYS = 30
PAT_MAX_DAYS = 365
PAT_DEFAULT_RUN_LIMIT = 1000
PAT_MAX_RUN_LIMIT = 1000
INVITATION_HOURS = 72
IDEMPOTENCY_DAYS = 7
RUN_DEADLINE_HOURS = 72
RUN_MAX_TASKS = 1000
REPETITIONS_DEFAULT = 1
REPETITIONS_MAX = 20
RUN_MAX_TRIALS = 10000
RUN_DEFAULT_CONCURRENCY = 4
RUN_MAX_CONCURRENCY = 10
PAGE_DEFAULT = 50
PAGE_MAX = 200
ARTIFACT_TTL_DAYS = 7
EXPORT_MAX_RUNS = 100
EXPORT_TTL_HOURS = 24
EXPORT_PIN_MINUTES = 60
EXPORT_MAX_BYTES = 10 * 1024**3
EXPORT_MAX_ACTIVE_PER_USER = 2
LOGIN_ATTEMPTS_PER_MINUTE = 10


def as_dict() -> dict:
    return {
        name.lower(): value
        for name, value in globals().items()
        if name.isupper() and isinstance(value, int)
    }
