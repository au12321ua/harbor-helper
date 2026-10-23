"""Artifact index, bounded reads, retention and index/file reconciliation (07).

Raw artifacts expire a fixed TTL after their trial's execution ended (run-level
artifacts: after the run finished). The index row, digest and status stay as
business metadata after the file is reclaimed. Read pins (exports) hold a file
for a bounded time; nothing holds one forever.
"""

import logging
from typing import BinaryIO

from sqlalchemy import Connection, delete, select, update

from maestro.boundaries.storage import ArtifactStore
from maestro.core import clock
from maestro.core.errors import MaestroError, not_found
from maestro.db import schema as t
from maestro.db.engine import Database
from maestro.domain import limits
from maestro.domain.states import ArtifactState
from maestro.services import deleted

log = logging.getLogger(__name__)
SWEEP_BATCH = 500
READ_MAX = 1024 * 1024


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
        "status_reason": row["status_reason"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
    }


def expiry_after(ended_at: str | None) -> str | None:
    if ended_at is None:
        return None
    return clock.to_text(clock.from_text(ended_at) + clock.timedelta(days=limits.ARTIFACT_TTL_DAYS))


def expiry_for(conn: Connection, run_id: str, trial_id: str | None) -> str | None:
    """For a file stored now: a late upload does not restart the TTL (07 section 2)."""
    if trial_id:
        ended = conn.execute(
            select(t.trials.c.execution_terminal_at).where(t.trials.c.id == trial_id)
        ).scalar()
    else:
        ended = conn.execute(select(t.runs.c.finished_at).where(t.runs.c.id == run_id)).scalar()
    return expiry_after(ended)


def stamp_expiry(conn: Connection, run_id: str, trial_id: str | None = None) -> None:
    """Set expires_at on artifacts whose owner has ended and that still have none."""
    trials = select(t.trials.c.id, t.trials.c.execution_terminal_at).where(
        t.trials.c.run_id == run_id, t.trials.c.execution_terminal_at.is_not(None)
    )
    if trial_id:
        trials = trials.where(t.trials.c.id == trial_id)
    for owner, ended in conn.execute(trials).all():
        conn.execute(
            update(t.artifacts)
            .where(t.artifacts.c.trial_id == owner, t.artifacts.c.expires_at.is_(None))
            .values(expires_at=expiry_after(ended))
        )
    if trial_id is None:
        finished = conn.execute(select(t.runs.c.finished_at).where(t.runs.c.id == run_id)).scalar()
        if finished:
            conn.execute(
                update(t.artifacts)
                .where(
                    t.artifacts.c.run_id == run_id,
                    t.artifacts.c.trial_id.is_(None),
                    t.artifacts.c.expires_at.is_(None),
                )
                .values(expires_at=expiry_after(finished))
            )


def _all_reclaimed(statuses: set[str]) -> bool:
    return "expired" in statuses and not statuses & {"available", "pending"}


def refresh_artifact_states(conn: Connection, trial_ids: set[str], run_ids: set[str]) -> None:
    """A trial (or run) whose saved files have all been reclaimed reads 'expired'."""
    for trial_id in trial_ids:
        statuses = set(
            conn.execute(
                select(t.artifacts.c.status).where(t.artifacts.c.trial_id == trial_id)
            ).scalars()
        )
        if _all_reclaimed(statuses):
            conn.execute(
                update(t.trials)
                .where(t.trials.c.id == trial_id)
                .values(artifact_state=ArtifactState.EXPIRED)
            )
    for run_id in run_ids:
        statuses = set(
            conn.execute(select(t.artifacts.c.status).where(t.artifacts.c.run_id == run_id))
            .scalars()
            .all()
        )
        if _all_reclaimed(statuses):
            conn.execute(
                update(t.runs)
                .where(t.runs.c.id == run_id)
                .values(artifact_state=ArtifactState.EXPIRED)
            )


def check_readable(row) -> None:
    status = row["status"]
    if status in {"expired", "deleting"}:
        raise MaestroError("ARTIFACT_EXPIRED", "Artifact expired; its index and digest remain", 410)
    if status == "deleted":
        raise MaestroError("ARTIFACT_DELETED", "Artifact was deleted", 410)
    if status == "pending":
        raise MaestroError(
            "ARTIFACT_NOT_READY", "Artifact is still being saved", 409, retryable=True
        )
    if status != "available":
        raise MaestroError(
            "ARTIFACT_UNAVAILABLE",
            f"Artifact content is not available ({row['status_reason'] or status})",
            409,
        )


class Artifacts:
    def __init__(self, db: Database, store: ArtifactStore):
        self.db = db
        self.store = store

    # --- queries -----------------------------------------------------------------

    def for_run(self, run_id: str, trial_id: str | None = None) -> list[dict]:
        query = select(t.artifacts).where(
            t.artifacts.c.run_id == run_id, deleted.visible(t.artifacts.c.id, "artifact")
        )
        if trial_id:
            query = query.where(t.artifacts.c.trial_id == trial_id)
        with self.db.read() as conn:
            if not conn.execute(select(t.runs.c.id).where(t.runs.c.id == run_id)).first():
                raise not_found("Run")
            deleted.refuse_purged(conn, "run", run_id, "Run")
            rows = conn.execute(query.order_by(t.artifacts.c.created_at)).mappings().all()
        return [public_artifact(r) for r in rows]

    def open(
        self, artifact_id: str, offset: int = 0, length: int | None = None
    ) -> tuple[dict, BinaryIO, int, int]:
        """Metadata, a reader positioned at ``offset``, the byte count to send and the
        total size. The reader stays valid if retention unlinks the file meanwhile."""
        if offset < 0 or (length is not None and not 1 <= length <= READ_MAX):
            raise MaestroError("INVALID_RANGE", f"offset >= 0 and length 1-{READ_MAX} bytes", 400)
        with self.db.read() as conn:
            row = self._row(conn, artifact_id)
            # A run in the recycle bin still resolves, files included; a purged run
            # has no files left and its rows are gone.
            gone = deleted.state(conn, "artifact", artifact_id)
        if gone:
            raise MaestroError("ARTIFACT_DELETED", "Artifact was deleted", 410)
        check_readable(row)
        try:
            reader = self.store.open(row["storage_key"])
        except (FileNotFoundError, KeyError):
            # Retention or a purge won the race between the index read and the open.
            with self.db.read() as conn:
                check_readable(self._row(conn, artifact_id))
            raise MaestroError(
                "ARTIFACT_UNAVAILABLE", "Artifact content is not available", 409
            ) from None
        total = row["size_bytes"] or 0
        offset = min(offset, total)
        reader.seek(offset)
        count = total - offset if length is None else min(length, total - offset)
        return public_artifact(row), reader, count, total

    @staticmethod
    def _row(conn: Connection, artifact_id: str):
        row = (
            conn.execute(select(t.artifacts).where(t.artifacts.c.id == artifact_id))
            .mappings()
            .first()
        )
        if row is None:
            raise not_found("Artifact")
        return row

    def read(self, artifact_id: str) -> tuple[dict, bytes]:
        meta, reader, count, _ = self.open(artifact_id)
        with reader:
            return meta, reader.read(count)

    # --- retention ---------------------------------------------------------------

    def sweep(self) -> dict:
        """Reclaim expired, unpinned files: mark deleting, delete, then mark expired.

        A crash between the steps leaves 'deleting', which is never downloadable and
        is finished by the next sweep.
        """
        at = clock.to_text(clock.now())
        with self.db.write() as conn:
            conn.execute(delete(t.artifact_pins).where(t.artifact_pins.c.expires_at <= at))
            rows = conn.execute(
                select(t.artifacts.c.id, t.artifacts.c.storage_key)
                .where(
                    t.artifacts.c.status.in_(["available", "deleting"]),
                    t.artifacts.c.expires_at <= at,
                    t.artifacts.c.id.not_in(select(t.artifact_pins.c.artifact_id)),
                )
                .limit(SWEEP_BATCH)
            ).all()
            if rows:
                conn.execute(
                    update(t.artifacts)
                    .where(t.artifacts.c.id.in_([r.id for r in rows]))
                    .values(status="deleting")
                )
        reclaimed, failed = [], 0
        for row in rows:
            try:
                self.store.delete(row.storage_key)
                reclaimed.append(row.id)
            except OSError:
                failed += 1
                log.warning("artifact %s could not be reclaimed; will retry", row.id)
        if reclaimed:
            with self.db.write() as conn:
                conn.execute(
                    update(t.artifacts)
                    .where(t.artifacts.c.id.in_(reclaimed), t.artifacts.c.status == "deleting")
                    .values(status="expired", status_reason="RETENTION_EXPIRED")
                )
                owners = conn.execute(
                    select(t.artifacts.c.run_id, t.artifacts.c.trial_id).where(
                        t.artifacts.c.id.in_(reclaimed)
                    )
                ).all()
                refresh_artifact_states(
                    conn, {o.trial_id for o in owners if o.trial_id}, {o.run_id for o in owners}
                )
        return {"reclaimed": len(reclaimed), "failed": failed}

    def reconcile(self) -> dict:
        """At start, before any run executes (F-09): an indexed file that is missing
        becomes unavailable; a published file nobody indexes is an orphan and goes."""
        partial = self.store.discard_partial()
        with self.db.read() as conn:
            indexed = {
                r.storage_key: (r.id, r.status)
                for r in conn.execute(
                    select(t.artifacts.c.id, t.artifacts.c.storage_key, t.artifacts.c.status)
                ).all()
            }
        missing = [
            artifact_id
            for key, (artifact_id, status) in indexed.items()
            if status == "available" and not self.store.exists(key)
        ]
        orphans = [
            key
            for key in list(self.store.keys())
            if key not in indexed or indexed[key][1] in {"expired", "deleted", "deleting"}
        ]
        for key in orphans:
            try:
                self.store.delete(key)
            except OSError:
                log.warning("orphan file %s could not be removed", key)
        if missing:
            with self.db.write() as conn:
                conn.execute(
                    update(t.artifacts)
                    .where(t.artifacts.c.id.in_(missing), t.artifacts.c.status == "available")
                    .values(status="unavailable", status_reason="STORAGE_CONTENT_MISSING")
                )
        report = {"missing": len(missing), "orphans": len(orphans), "partial": partial}
        if missing or orphans or partial:
            log.warning("artifact storage reconciliation: %s", report)
        return report
