"""SubmissionRecords persistence operations sharing the service store."""

import json
from typing import TYPE_CHECKING

from harbor_helper.service.primitives import (
    ServiceError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from harbor_helper.persistence.store import Store


class SubmissionRecords:
    if TYPE_CHECKING:
        store: Store
        user: Callable[..., dict]


    def submission(self, submission_id):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM submissions WHERE id=?", (submission_id,)).fetchone()
        if row is None:
            raise ServiceError("submission_missing", "Submission not found", 404)
        result = dict(row)
        result["request"] = json.loads(result["request"])
        result["frozen"] = json.loads(result["frozen"])
        return result

    def allow_publish(self, submission_id):
        row = self.submission(submission_id)
        return (
            not row["cancel"]
            and row["status"] == "preparing"
            and self.user(row["user_id"])["enabled"]
        )
