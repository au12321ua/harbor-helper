"""Cancellation service with explicit persistence dependency."""

from harbor_helper.persistence import statuses as lifecycle_status
from harbor_helper.persistence.files import read_json
from harbor_helper.persistence.store import TERMINAL
from harbor_helper.service.permissions import cancel_allowed
from harbor_helper.service.views import public_submission


class Cancellation:
    def __init__(self, data):
        self.data = data
        self.store = data.store

    def cancel_submission(self, actor, submission_id):
        with self.store.control():
            row = self.data.submission(submission_id)
            cancel_allowed(actor, row["user_id"])
            with self.store.connect() as db:
                db.execute(
                    f"UPDATE submissions SET cancel=1,status=CASE WHEN status={lifecycle_status.PREPARING!r} THEN {lifecycle_status.CANCELLED!r} ELSE status END WHERE id=?",
                    (submission_id,),
                )
            if row["run_id"]:
                self._cancel_run(row["run_id"])
        return public_submission(self.data.submission(submission_id))

    def _cancel_run(self, run_id):
        row = self.store.get(run_id)
        if row["status"] not in TERMINAL:
            self.store.update(run_id, cancel=1)
        return {"run_id": run_id, "cancel_requested": True, "status": row["status"]}

    def cancel_run(self, actor, run_id):
        with self.store.control():
            binding = read_json(self.store.path(run_id) / "manifest.json")["service"]
            cancel_allowed(actor, binding["user_id"])
            return self._cancel_run(run_id)
