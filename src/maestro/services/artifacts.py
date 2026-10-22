"""Artifact index queries and downloads. Retention and export arrive with M6."""

from sqlalchemy import select

from maestro.boundaries.storage import ArtifactStore
from maestro.core.errors import MaestroError, not_found
from maestro.db import schema as t
from maestro.db.engine import Database


def public_artifact(row) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "trial_id": row["trial_id"],
        "attempt_id": row["attempt_id"],
        "kind": row["kind"],
        "relative_path": row["relative_path"],
        "digest": row["digest"],
        "size_bytes": row["size_bytes"],
        "status": row["status"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
    }


class Artifacts:
    def __init__(self, db: Database, store: ArtifactStore):
        self.db = db
        self.store = store

    def for_run(self, run_id: str, trial_id: str | None = None) -> list[dict]:
        query = select(t.artifacts).where(t.artifacts.c.run_id == run_id)
        if trial_id:
            query = query.where(t.artifacts.c.trial_id == trial_id)
        with self.db.read() as conn:
            if not conn.execute(select(t.runs.c.id).where(t.runs.c.id == run_id)).first():
                raise not_found("Run")
            rows = conn.execute(query.order_by(t.artifacts.c.created_at)).mappings().all()
        return [public_artifact(r) for r in rows]

    def read(self, artifact_id: str) -> tuple[dict, bytes]:
        with self.db.read() as conn:
            row = (
                conn.execute(select(t.artifacts).where(t.artifacts.c.id == artifact_id))
                .mappings()
                .first()
            )
        if row is None:
            raise not_found("Artifact")
        if row["status"] == "expired":
            raise MaestroError("ARTIFACT_EXPIRED", "Artifact expired", 410)
        if row["status"] != "available" or not self.store.exists(row["storage_key"]):
            raise MaestroError("ARTIFACT_UNAVAILABLE", "Artifact content is not available", 409)
        return public_artifact(row), self.store.get(row["storage_key"])
