"""Read-only dataset catalog plus the internal registration used until M4.

Admission and local cache are reported separately (10 section 4); ``can_submit``
derives from admission and content availability, never from cache state.
"""

from sqlalchemy import insert, select

from maestro.boundaries.dataset_source import DatasetSource
from maestro.core import clock
from maestro.core.digests import digest_json
from maestro.core.errors import not_found
from maestro.core.ids import new_id
from maestro.db import schema as t
from maestro.db.engine import Database
from maestro.services import pagination

ADMITTED = "admitted"


def task_view(task, admission, availability) -> dict:
    blockers = []
    if admission is None or admission["state"] != ADMITTED:
        state = admission["state"] if admission else "pending"
        code = "TASK_ADMISSION_REVOKED" if state == "revoked" else "TASK_NOT_ADMITTED"
        blockers.append({"code": code, "admission_state": state})
    if availability is not None and availability["availability"] == "unavailable":
        blockers.append(
            {
                "code": "RESOURCE_CONTENT_UNAVAILABLE",
                "resource_kind": availability["resource_kind"],
                "expected_digest": task["content_digest"],
            }
        )
    return {
        "id": task["id"],
        "task_key": task["task_key"],
        "admission": (
            {"id": admission["id"], "state": admission["state"], "revision": admission["revision"]}
            if admission
            else None
        ),
        "content": {
            "digest": task["content_digest"],
            "availability": availability["availability"] if availability else "unknown",
            "checked_at": availability["checked_at"] if availability else None,
        },
        "can_submit": not blockers,
        "blockers": blockers,
    }


class Catalog:
    def __init__(self, db: Database):
        self.db = db

    def register_version(
        self, source: DatasetSource, namespace: str, name: str, ref: str, admit: bool, actor: str
    ) -> str:
        """Internal: record a version and (optionally) admit every task.

        Stand-in for the admin import and first preparation of M4, which will
        replace it with a real Operation and preparation evidence.
        """
        version = source.resolve(namespace, name, ref)
        at = clock.to_text(clock.now())
        with self.db.write() as conn:
            dataset = conn.execute(
                select(t.datasets.c.id).where(
                    t.datasets.c.source_kind == source.kind,
                    t.datasets.c.namespace == namespace,
                    t.datasets.c.name == name,
                )
            ).scalar()
            if dataset is None:
                dataset = new_id("ds")
                conn.execute(
                    insert(t.datasets).values(
                        id=dataset,
                        source_kind=source.kind,
                        namespace=namespace,
                        name=name,
                        description=version.description,
                        enabled=True,
                        created_at=at,
                    )
                )
            existing = conn.execute(
                select(t.dataset_versions.c.id).where(
                    t.dataset_versions.c.dataset_id == dataset,
                    t.dataset_versions.c.resolved_digest == version.resolved_digest,
                )
            ).scalar()
            if existing:
                return existing
            version_id = new_id("dsv")
            conn.execute(
                insert(t.dataset_versions).values(
                    id=version_id,
                    dataset_id=dataset,
                    upstream_ref=version.upstream_ref,
                    ref_kind=version.ref_kind,
                    resolved_digest=version.resolved_digest,
                    manifest_json={"task_count": len(version.tasks)},
                    status="ready",
                    created_at=at,
                )
            )
            for task in version.tasks:
                task_id = new_id("task")
                conn.execute(
                    insert(t.tasks).values(
                        id=task_id,
                        dataset_version_id=version_id,
                        task_key=task.task_key,
                        definition_json=task.definition,
                        content_digest=task.content_digest,
                    )
                )
                conn.execute(
                    insert(t.task_admissions).values(
                        id=new_id("adm"),
                        task_id=task_id,
                        preparation_method_digest=digest_json({"method": "fake"}),
                        state=ADMITTED if admit else "pending",
                        revision=1,
                        evidence_json={},
                        approved_by=actor if admit else None,
                        approved_at=at if admit else None,
                    )
                )
        return version_id

    def list_datasets(self, cursor: str | None, limit: int | None) -> tuple[list, str | None]:
        limit = pagination.check_limit(limit)
        query = pagination.page(
            select(t.datasets).where(t.datasets.c.enabled.is_(True)),
            t.datasets.c.created_at,
            t.datasets.c.id,
            cursor,
            limit,
            {},
        )
        with self.db.read() as conn:
            rows = list(conn.execute(query).mappings().all())
            rows, next_cursor = pagination.split(rows, limit, "created_at", {})
            result = []
            for row in rows:
                versions = conn.execute(
                    select(t.dataset_versions)
                    .where(t.dataset_versions.c.dataset_id == row["id"])
                    .order_by(t.dataset_versions.c.created_at.desc())
                ).mappings()
                result.append(
                    {
                        "id": row["id"],
                        "source_kind": row["source_kind"],
                        "namespace": row["namespace"],
                        "name": row["name"],
                        "description": row["description"],
                        "versions": [self._version(v) for v in versions],
                    }
                )
        return result, next_cursor

    @staticmethod
    def _version(row) -> dict:
        return {
            "id": row["id"],
            "dataset_id": row["dataset_id"],
            "upstream_ref": row["upstream_ref"],
            "ref_kind": row["ref_kind"],
            "resolved_digest": row["resolved_digest"],
            "status": row["status"],
            "created_at": row["created_at"],
        }

    def get_version(self, version_id: str) -> dict:
        with self.db.read() as conn:
            row = (
                conn.execute(
                    select(t.dataset_versions).where(t.dataset_versions.c.id == version_id)
                )
                .mappings()
                .first()
            )
            if row is None:
                raise not_found("Dataset version")
            tasks = self._tasks(conn, version_id)
        return {
            **self._version(row),
            "task_count": len(tasks),
            "admitted_task_count": sum(
                1 for x in tasks if x["admission"] and x["admission"]["state"] == ADMITTED
            ),
            "submittable_task_count": sum(1 for x in tasks if x["can_submit"]),
        }

    def list_tasks(self, version_id: str) -> list[dict]:
        with self.db.read() as conn:
            if not conn.execute(
                select(t.dataset_versions.c.id).where(t.dataset_versions.c.id == version_id)
            ).first():
                raise not_found("Dataset version")
            return self._tasks(conn, version_id)

    @staticmethod
    def _tasks(conn, version_id: str) -> list[dict]:
        tasks = (
            conn.execute(
                select(t.tasks)
                .where(t.tasks.c.dataset_version_id == version_id)
                .order_by(t.tasks.c.task_key)
            )
            .mappings()
            .all()
        )
        ids = [x["id"] for x in tasks]
        admissions = {
            a["task_id"]: a
            for a in conn.execute(
                select(t.task_admissions)
                .where(t.task_admissions.c.task_id.in_(ids))
                .order_by(t.task_admissions.c.revision)
            ).mappings()
        }
        availability = {
            a["content_digest"]: a
            for a in conn.execute(
                select(t.content_availability).where(
                    t.content_availability.c.content_digest.in_(
                        [x["content_digest"] for x in tasks]
                    )
                )
            ).mappings()
        }
        return [
            task_view(x, admissions.get(x["id"]), availability.get(x["content_digest"]))
            for x in tasks
        ]
