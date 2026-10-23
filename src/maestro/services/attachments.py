"""Attachment versions (03 sections 2 and 6): members publish packages with fixed content.

Any member or experiment PAT may publish; everyone may read and choose any enabled
version (results are team-wide). Name and version identify a package team-wide:
publishing the same name and version again with the same content returns the existing
version, different content is a conflict (a change is a new version). The owner or an
administrator may disable it or put it in the recycle bin. Publishing never runs the
package's script: installation only happens inside accepted runs (03 section 7).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Connection, insert, select, update

from maestro.core import clock
from maestro.core.errors import FieldError, MaestroError, not_found
from maestro.core.ids import new_id
from maestro.db import schema as t
from maestro.db.engine import Database
from maestro.domain import limits
from maestro.execution.attachments import AttachmentStore, PackageError
from maestro.services import audit, deleted
from maestro.services.principal import Principal, require_experiment, require_manage_owned


def _not_purged():
    return t.attachment_versions.c.id.not_in(
        select(t.deletions.c.object_id).where(
            t.deletions.c.object_type == "attachment_version",
            t.deletions.c.state == deleted.PURGED,
        )
    )


class Attachments:
    def __init__(self, db: Database, store: AttachmentStore, adapters=None):
        self.db = db
        self.store = store
        # Harness agents the executor can run; None when there is no executor.
        self.adapters = adapters

    @staticmethod
    def _public(row, owner: str | None) -> dict:
        manifest = row["manifest_json"]
        return {
            "id": row["id"],
            "name": row["name"],
            "version": row["version"],
            "description": row["description"],
            "owner_id": row["owner_id"],
            "owner_username": owner,
            "content_digest": row["content_digest"],
            "effects": manifest["effects"],
            "compatible_harnesses": manifest["compatible_harnesses"],
            "provides": manifest["provides"],
            "has_bootstrap": row["has_bootstrap"],
            "file_count": row["file_count"],
            "size_bytes": row["size_bytes"],
            "enabled": row["enabled"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _select():
        return select(t.attachment_versions, t.users.c.username).join(
            t.users, t.users.c.id == t.attachment_versions.c.owner_id
        )

    def list(
        self, principal: Principal, name: str | None = None, include_disabled: bool = True
    ) -> list[dict]:
        query = self._select().where(
            deleted.visible(t.attachment_versions.c.id, "attachment_version")
        )
        if name:
            query = query.where(t.attachment_versions.c.name == name)
        if not include_disabled:
            query = query.where(t.attachment_versions.c.enabled.is_(True))
        query = query.order_by(t.attachment_versions.c.name, t.attachment_versions.c.created_at)
        with self.db.read() as conn:
            return [self._public(r, r["username"]) for r in conn.execute(query).mappings()]

    def _row(self, conn: Connection, attachment_id: str):
        row = (
            conn.execute(self._select().where(t.attachment_versions.c.id == attachment_id))
            .mappings()
            .first()
        )
        if row is None:
            raise not_found("Attachment")
        return row

    def get(self, principal: Principal, attachment_id: str) -> dict:
        with self.db.read() as conn:
            row = self._row(conn, attachment_id)
            deleted.refuse_purged(conn, "attachment_version", attachment_id, "Attachment")
            return {
                **self._public(row, row["username"]),
                "files": row["files_json"],
                "deletion": deleted.state(conn, "attachment_version", attachment_id),
            }

    def publish(self, principal: Principal, source: bytes | Path) -> tuple[dict, bool]:
        """``source`` is the archive or a file holding it. Returns the version and whether
        it was created now."""
        require_experiment(principal)
        try:
            package = self.store.unpack(
                source, limits.ATTACHMENT_MAX_FILES, limits.ATTACHMENT_UNPACKED_MAX_BYTES
            )
        except PackageError as error:
            raise MaestroError(
                "ATTACHMENT_INVALID",
                str(error),
                422,
                field_errors=[
                    FieldError(path, code, message) for path, code, message in error.problems
                ],
            ) from None
        manifest = package.manifest
        unknown = [
            name
            for name in manifest["compatible_harnesses"]
            if name != "*" and self.adapters is not None and name not in self.adapters
        ]
        if unknown:
            self.store.discard(package)
            raise MaestroError(
                "ATTACHMENT_INVALID",
                "The executor has no harness of this name",
                422,
                field_errors=[
                    FieldError("/manifest/compatible_harnesses", "UNSUPPORTED", name)
                    for name in unknown
                ],
            )
        attachment_id = new_id("att")
        try:
            with self.db.write() as conn:
                existing = conn.execute(
                    select(
                        t.attachment_versions.c.id, t.attachment_versions.c.content_digest
                    ).where(
                        t.attachment_versions.c.name == manifest["name"],
                        t.attachment_versions.c.version == manifest["version"],
                        _not_purged(),
                    )
                ).first()
                if existing is not None:
                    if existing.content_digest == package.content_digest:
                        attachment_id = existing.id
                        created = False
                    else:
                        raise MaestroError(
                            "ATTACHMENT_VERSION_EXISTS",
                            "This name and version hold different content; publish a new "
                            "version to change it",
                            409,
                            field_errors=[FieldError("/manifest/version", "TAKEN")],
                            suggested_actions=[
                                {
                                    "type": "publish_new_version",
                                    "attachment_id": existing.id,
                                    "content_digest": existing.content_digest,
                                    "uploaded_digest": package.content_digest,
                                }
                            ],
                        )
                else:
                    # Files go in under the write lock, so a purge of the same content
                    # cannot remove them between here and the insert.
                    self.store.publish(package)
                    conn.execute(
                        insert(t.attachment_versions).values(
                            id=attachment_id,
                            owner_id=principal.user_id,
                            name=manifest["name"],
                            version=manifest["version"],
                            description=manifest["description"],
                            content_digest=package.content_digest,
                            manifest_json=manifest,
                            files_json=package.files,
                            file_count=len(package.files),
                            size_bytes=package.size_bytes,
                            has_bootstrap=package.has_bootstrap,
                            enabled=True,
                            created_at=clock.to_text(clock.now()),
                        )
                    )
                    audit.record(
                        conn,
                        principal,
                        "attachment.publish",
                        object_type="attachment_version",
                        object_id=attachment_id,
                        detail={
                            "name": manifest["name"],
                            "version": manifest["version"],
                            "content_digest": package.content_digest,
                        },
                    )
                    created = True
        finally:
            self.store.discard(package)
        return self.get(principal, attachment_id), created

    def set_enabled(self, principal: Principal, attachment_id: str, enabled: bool) -> dict:
        with self.db.write() as conn:
            row = self._row(conn, attachment_id)
            require_manage_owned(principal, row["owner_id"])
            if deleted.state(conn, "attachment_version", attachment_id):
                raise MaestroError("ATTACHMENT_DELETED", "Attachment was deleted", 409)
            if row["enabled"] != enabled:
                conn.execute(
                    update(t.attachment_versions)
                    .where(t.attachment_versions.c.id == attachment_id)
                    .values(enabled=enabled)
                )
                audit.record(
                    conn,
                    principal,
                    f"attachment.{'enable' if enabled else 'disable'}",
                    object_type="attachment_version",
                    object_id=attachment_id,
                )
        return self.get(principal, attachment_id)
