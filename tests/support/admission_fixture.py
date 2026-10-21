"""Explicit synthetic activity for unit fixtures (not a running scheduler).

Only unit tests opting into this helper publish the test process birth and a fresh
heartbeat. Process/HTTP tests start the actual isolated scheduler instead.
"""

import os
import time

from harbor_helper.execution.processes import process_birth
from harbor_helper.persistence.files import write_json


def synthetic_activity(data):
    write_json(
        data.root / "scheduler.json",
        {"pid": os.getpid(), "birth": process_birth(os.getpid()), "observed": time.time()},
    )
