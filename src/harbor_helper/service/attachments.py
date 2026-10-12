"""Team-shared immutable input versions over the compatible bundle store.

Files are validated before the control section. A single SQLite transaction makes
bundle, identity, version and operation visible together. A killed publisher can
leave unreferenced bytes, never a selectable partial version. No library GC here.
"""

import json
import shutil
import time
import uuid

from harbor_helper.execution.runs import check_bundle
from harbor_helper.persistence.files import tree_digest
from harbor_helper.service.data import ServiceError

OPERATIONS = {"attachment_create", "attachment_publish", "attachment_derive", "attachment_register"}


class Attachments:
    def __init__(self, application):
        self.app = application
        self.store = application.store
        self.data = application.data

    def identity(self, db, attachment_id):
        row = db.execute("SELECT * FROM attachments WHERE id=?", (attachment_id,)).fetchone()
        if not row:
            raise ServiceError("attachment_missing", "Attachment not found", 404)
        return dict(row)

    def maintain(self, actor, attachment):
        if actor["role"] != "admin" and actor["id"] != attachment["creator_id"]:
            raise ServiceError(
                "attachment_forbidden", "Only creator or administrator may maintain", 403
            )

    def version(self, db, version_id):
        row = db.execute("SELECT * FROM attachment_versions WHERE id=?", (version_id,)).fetchone()
        if not row:
            raise ServiceError("attachment_version_missing", "Attachment version not found", 404)
        return dict(row)

    def public(self, db, version_id):
        version = self.version(db, version_id)
        attachment = self.identity(db, version["attachment_id"])
        for item, field in ((attachment, "creator_id"), (version, "publisher_id")):
            user = db.execute("SELECT username FROM users WHERE id=?", (item[field],)).fetchone()
            item[field.replace("_id", "")] = user[0] if user else "unknown"
            item["enabled"] = bool(item["enabled"])
        version["legacy"] = bool(version["legacy"])
        version["original_creator"] = "unknown" if version["legacy"] else attachment["creator"]
        version["availability"] = "available"
        try:
            self.validate_bundle(db, version["bundle_id"])
        except (ValueError, OSError):
            version["availability"] = "unavailable"
        return {"attachment": attachment, "version": version}

    def catalog(self):
        with self.store.connect() as db:
            identities = [
                dict(r) for r in db.execute("SELECT * FROM attachments ORDER BY created DESC")
            ]
            result = []
            for identity in identities:
                versions = [
                    self.public(db, r[0])["version"]
                    for r in db.execute(
                        "SELECT id FROM attachment_versions WHERE attachment_id=? ORDER BY number DESC",
                        (identity["id"],),
                    ).fetchall()
                ]
                first = self.public(db, versions[0]["id"])["attachment"]
                result.append({**first, "versions": versions})
            legacy = [
                dict(r)
                for r in db.execute(
                    "SELECT b.* FROM bundles b LEFT JOIN attachment_versions v ON b.id=v.bundle_id "
                    "WHERE v.id IS NULL ORDER BY b.created DESC"
                )
            ]
        return {
            "attachments": result,
            "legacy_bundles": [{**b, "creator": "unknown", "legacy": True} for b in legacy],
        }

    def validate_bundle(self, db, bundle_id, access_value=None):
        row = db.execute("SELECT digest FROM bundles WHERE id=?", (bundle_id,)).fetchone()
        if not row:
            raise ServiceError("bundle_missing", "Bundle not found", 404)
        path = self.store.root / "bundles" / bundle_id
        try:
            check_bundle(path, access_value)
            if tree_digest(path) != row["digest"]:
                raise ValueError
        except (ValueError, OSError):
            raise ServiceError(
                "attachment_unavailable", "Attachment input unavailable or unsafe", 409
            ) from None
        return row["digest"]

    def binding(self, bundle_id=None, version_id=None, *, access_value=None):
        with self.store.connect() as db:
            version = self.version(db, version_id) if version_id else None
            if not version and bundle_id:
                row = db.execute(
                    "SELECT id FROM attachment_versions WHERE bundle_id=?", (bundle_id,)
                ).fetchone()
                version = self.version(db, row[0]) if row else None
            if version:
                attachment = self.identity(db, version["attachment_id"])
                if not attachment["enabled"] or not version["enabled"]:
                    raise ServiceError("attachment_disabled", "Attachment or version disabled", 409)
                bundle_id = version["bundle_id"]
            sha = self.validate_bundle(db, bundle_id, access_value) if bundle_id else None
            return {
                "bundle_id": bundle_id,
                "bundle_digest": sha,
                "attachment_version_id": version["id"] if version else None,
                "attachment_id": version["attachment_id"] if version else None,
                "attachment_lineage": "versioned"
                if version
                else ("legacy" if bundle_id else "none"),
            }

    def lookup(self, actor, operation, idem):
        from harbor_helper.security.access_tokens import ACCESS_TOKEN_TEXT

        if isinstance(idem, str) and (ACCESS_TOKEN_TEXT.search(idem)):
            raise ServiceError("access_plaintext", "Access credential plaintext forbidden in key")
        if operation not in OPERATIONS:
            raise ServiceError("attachment_operation", "Unknown attachment operation")
        with self.store.connect() as db:
            row = db.execute(
                "SELECT version_id FROM attachment_operations WHERE user_id=? AND operation=? AND idem=?",
                (actor["id"], operation, idem),
            ).fetchone()
            if not row:
                raise ServiceError(
                    "attachment_operation_missing", "No committed operation for this key", 404
                )
            version = self.version(db, row[0])
            if operation == "attachment_publish":
                self.maintain(actor, self.identity(db, version["attachment_id"]))
            return self.public(db, row[0])

    def write(self, actor, operation, idem, body, archive=None, *, access_value=None):
        from harbor_helper.security.access_tokens import ACCESS_TOKEN_TEXT

        if isinstance(idem, str) and (
            ACCESS_TOKEN_TEXT.search(idem) or (access_value and access_value in idem)
        ):
            raise ServiceError("access_plaintext", "Access credential plaintext forbidden in key")
        from harbor_helper.service.application import digest

        if operation not in OPERATIONS:
            raise ServiceError("attachment_operation", "Unknown attachment operation")
        if not isinstance(idem, str) or not 1 <= len(idem) <= 128:
            raise ServiceError("idempotency_required", "A stable Idempotency-Key is required")
        fields = {
            "attachment_create": {"name", "description"},
            "attachment_publish": {"attachment_id", "notes"},
            "attachment_derive": {"source_version_id", "name", "description"},
            "attachment_register": {"bundle_id", "name", "description"},
        }[operation]
        if not isinstance(body, dict) or set(body) - fields:
            raise ServiceError("attachment_fields", "Unknown attachment fields")
        normalized = {k: body.get(k, "") for k in fields}
        if any(not isinstance(v, str) for v in normalized.values()):
            raise ServiceError("attachment_fields", "Attachment fields must be strings")
        if "name" in fields and not 1 <= len(normalized["name"].strip()) <= 128:
            raise ServiceError("attachment_name", "Name must be 1–128 characters")
        for k in ("description", "notes"):
            if len(normalized.get(k, "")) > 4096:
                raise ServiceError(
                    "attachment_notes", "Description/notes must be at most 4096 characters"
                )
        # Reject recognizable tokens in metadata too; never echo field values.
        from harbor_helper.security.access_tokens import ACCESS_TOKEN_TEXT

        text = json.dumps(normalized, ensure_ascii=False)
        if ACCESS_TOKEN_TEXT.search(text) or (access_value and access_value in text):
            raise ServiceError(
                "unsafe_attachment", "Attachment contains access credential plaintext"
            )
        staged = None
        committed = False
        try:
            if operation != "attachment_register":
                if archive is None:
                    raise ServiceError("attachment_file", "ZIP input required")
                staged = self.app.upload_bundle(archive, access_value=access_value, persist=False)
            with self.store.control(), self.store.connect() as db:
                if not self.data.user(actor["id"])["enabled"]:
                    raise ServiceError("member_disabled", "Account disabled", 403)
                bundle_id = staged["id"] if staged else normalized["bundle_id"]
                sha = (
                    staged["digest"]
                    if staged
                    else self.validate_bundle(db, bundle_id, access_value)
                )
                request_hash = digest({**normalized, "digest": sha})
                old = db.execute(
                    "SELECT * FROM attachment_operations WHERE user_id=? AND operation=? AND idem=?",
                    (actor["id"], operation, idem),
                ).fetchone()
                if old:
                    if old["request_hash"] != request_hash:
                        raise ServiceError(
                            "idempotency_conflict",
                            "Idempotency key reused with different input",
                            409,
                        )
                    if operation == "attachment_publish":
                        self.maintain(actor, self.identity(db, normalized["attachment_id"]))
                    return self.public(db, old["version_id"])
                source = None
                if operation == "attachment_publish":
                    attachment = self.identity(db, normalized["attachment_id"])
                    self.maintain(actor, attachment)
                    if not attachment["enabled"]:
                        raise ServiceError("attachment_disabled", "Attachment disabled", 409)
                    attachment_id = attachment["id"]
                    number = db.execute(
                        "SELECT MAX(number)+1 FROM attachment_versions WHERE attachment_id=?",
                        (attachment_id,),
                    ).fetchone()[0]
                else:
                    if operation == "attachment_derive":
                        source = self.version(db, normalized["source_version_id"])
                        self.binding(version_id=source["id"], access_value=access_value)
                    if (
                        operation == "attachment_register"
                        and db.execute(
                            "SELECT 1 FROM attachment_versions WHERE bundle_id=?", (bundle_id,)
                        ).fetchone()
                    ):
                        raise ServiceError(
                            "bundle_registered", "Legacy bundle already registered", 409
                        )
                    attachment_id, number = "att-" + uuid.uuid4().hex, 1
                    db.execute(
                        "INSERT INTO attachments VALUES(?,?,?,?,?,1)",
                        (
                            attachment_id,
                            normalized["name"],
                            normalized["description"],
                            actor["id"],
                            time.time(),
                        ),
                    )
                if staged:
                    db.execute("INSERT INTO bundles VALUES(?,?,?)", (bundle_id, sha, time.time()))
                version_id = "av-" + uuid.uuid4().hex
                db.execute(
                    "INSERT INTO attachment_versions VALUES(?,?,?,?,?,?,?,?,?,?,1)",
                    (
                        version_id,
                        attachment_id,
                        number,
                        bundle_id,
                        sha,
                        actor["id"],
                        time.time(),
                        normalized.get("notes", ""),
                        source["id"] if source else None,
                        int(operation == "attachment_register"),
                    ),
                )
                db.execute(
                    "INSERT INTO attachment_operations VALUES(?,?,?,?,?)",
                    (
                        actor["id"],
                        operation,
                        idem,
                        request_hash,
                        version_id,
                    ),
                )
            committed = True
            with self.store.connect() as db:
                return self.public(db, version_id)
        finally:
            if staged and not committed:
                shutil.rmtree(self.store.root / "bundles" / staged["id"], ignore_errors=True)

    def update(self, actor, attachment_id, body, version_id=None, *, access_value=None):
        fields = {"enabled"} if version_id else {"name", "description", "enabled"}
        if not isinstance(body, dict) or not body or set(body) - fields:
            raise ServiceError("attachment_fields", "Unsupported attachment update")
        if "enabled" in body and type(body["enabled"]) is not bool:
            raise ServiceError("attachment_fields", "enabled must be boolean")
        if "name" in body and (
            not isinstance(body["name"], str) or not 1 <= len(body["name"].strip()) <= 128
        ):
            raise ServiceError("attachment_name", "Name must be 1–128 characters")
        if "description" in body and (
            not isinstance(body["description"], str) or len(body["description"]) > 4096
        ):
            raise ServiceError("attachment_notes", "Description must be at most 4096 characters")
        from harbor_helper.security.access_tokens import ACCESS_TOKEN_TEXT

        text = json.dumps(body, ensure_ascii=False)
        if ACCESS_TOKEN_TEXT.search(text) or (access_value and access_value in text):
            raise ServiceError(
                "unsafe_attachment", "Attachment contains access credential plaintext"
            )
        with self.store.control(), self.store.connect() as db:
            attachment = self.identity(db, attachment_id)
            self.maintain(actor, attachment)
            target, table = attachment_id, "attachments"
            if version_id:
                if self.version(db, version_id)["attachment_id"] != attachment_id:
                    raise ServiceError(
                        "attachment_version_missing", "Version does not belong to attachment", 404
                    )
                target, table = version_id, "attachment_versions"
            for field, value in body.items():
                db.execute(f"UPDATE {table} SET {field}=? WHERE id=?", (value, target))
        return {"updated": True}
