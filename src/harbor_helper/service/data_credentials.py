"""Credentials persistence operations sharing the service store."""

import json
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING

from harbor_helper.persistence.files import read_json
from harbor_helper.persistence.store import TERMINAL
from harbor_helper.persistence.wakeup import wake_after
from harbor_helper.security.master_key import MasterKeys, MasterUnavailable, aad, decrypt, encrypt
from harbor_helper.service.primitives import (
    ServiceError,
    identifier,
    public_user,
    secret_value,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from harbor_helper.persistence.store import Store


class Credentials:
    if TYPE_CHECKING:
        store: Store
        root: Path
        object: Callable[..., dict]
        user: Callable[..., dict]
        master_keys: MasterKeys

    def credential(self, credential_id, version=None):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT id,version,provider_id,label,enabled,created FROM credential_versions WHERE id=? "
                + ("AND version=?" if version else "ORDER BY version DESC LIMIT 1"),
                (credential_id, version) if version else (credential_id,),
            ).fetchone()
        if row is None:
            raise ServiceError("credential_missing", "Bound credential unavailable", 409)
        return public_user(row)

    def credentials(self):
        with self.store.connect() as db:
            ids = [
                r[0] for r in db.execute("SELECT DISTINCT id FROM credential_versions ORDER BY id")
            ]
        return [self.credential(i) for i in ids]

    @wake_after
    def add_credential(self, credential_id, provider_id, label, key, rotate=False):
        identifier(credential_id)
        self.object("provider", provider_id)
        secret_value(key)
        if not isinstance(label, str) or not 1 <= len(label) <= 128:
            raise ServiceError("invalid_label", "Credential label must be 1–128 characters")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            master = self.master_keys.current(db)
            old = db.execute(
                "SELECT * FROM credential_versions WHERE id=? ORDER BY version DESC LIMIT 1",
                (credential_id,),
            ).fetchone()
            if old and (not rotate or old["provider_id"] != provider_id):
                raise ServiceError(
                    "credential_exists",
                    "Use explicit rotation of the same credential/provider",
                    409,
                )
            if rotate and old is None:
                raise ServiceError("credential_missing", "Credential not found", 404)
            version = old["version"] + 1 if old else 1
            nonce, ciphertext = encrypt(master, key, f"{provider_id}/{credential_id}/{version}")
            db.execute(
                "INSERT INTO credential_versions VALUES(?,?,?,?,1,?,?,?)",
                (credential_id, version, provider_id, label, nonce, ciphertext, time.time()),
            )
        return self.credential(credential_id)

    @wake_after
    def disable_credential(self, credential_id):
        self.credential(credential_id)
        with self.store.connect() as db:
            db.execute("UPDATE credential_versions SET enabled=0 WHERE id=?", (credential_id,))
        return self.credential(credential_id)

    def key(self, credential_id, version, provider_id, execution=False):
        rows = self.master_keys.rows(
            "credential_versions", "WHERE c.id=? AND c.version=?", (credential_id, version)
        )
        row = rows[0] if rows else None
        if row is None or row["provider_id"] != provider_id or (execution and not row["enabled"]):
            raise ServiceError(
                "credential_unavailable", "Bound credential unavailable or disabled", 409
            )
        return decrypt(self.master_keys.load(row), row, aad(row, "credential_versions"))

    def notice_secrets(self):
        """One statement snapshots both credential families and their active key."""
        try:
            with self.store.connect() as db:
                has_sources = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='source_credentials'"
                ).fetchone()
                source = (
                    "UNION ALL SELECT 'source_credentials',NULL,version,NULL,nonce,ciphertext FROM source_credentials"
                    if has_sources
                    else ""
                )
                rows = db.execute(f"""WITH c AS (
                    SELECT 'credential_versions' kind,id,version,provider_id,nonce,ciphertext FROM credential_versions
                    {source}) SELECT c.*,m.generation,m.basename,m.kcv,m.rotated_at,
                    (SELECT COUNT(*) FROM master_active) active_count FROM c LEFT JOIN master_active m ON m.singleton=1""").fetchall()
        except sqlite3.DatabaseError:
            raise MasterUnavailable() from None
        if not rows:
            self.master_keys.current()
            return []
        if rows[0]["active_count"] != 1:
            raise MasterUnavailable()
        master = self.master_keys.load(rows[0])
        return [decrypt(master, row, aad(row, row["kind"])) for row in rows]

    def run_key(self, run_id, execution=False):
        manifest = read_json(self.store.path(run_id) / "manifest.json")
        binding = manifest.get("service") or {}
        if manifest["effective"]["agent"] == "oracle":
            if execution and not self.user(binding["user_id"])["enabled"]:
                raise ServiceError("member_disabled", "Submitting account is disabled", 409)
            return None
        if execution:
            if (
                not self.user(binding["user_id"])["enabled"]
                or not self.object("provider", binding["provider_id"])["enabled"]
            ):
                raise ServiceError(
                    "execution_disabled", "Submitting account or provider disabled", 409
                )
            provider = self.object("provider", binding["provider_id"], binding["provider_version"])
            model = manifest["effective"]["model"]
            if (provider.get("protocol", "openai-compatible"), provider["endpoint"]) != (
                model.get("protocol", "openai-compatible"),
                model["endpoint"],
            ):
                raise ServiceError("binding_mismatch", "Fixed provider binding mismatch", 409)
        return self.key(
            binding["credential_id"],
            binding["credential_version"],
            binding["provider_id"],
            execution,
        )

    def dependencies(self):
        refs = set()
        with self.store.connect() as db:
            for row in db.execute("SELECT frozen FROM submissions WHERE status='preparing'"):
                binding = json.loads(row[0])["service"]
                if binding.get("credential_id"):
                    refs.add((binding["credential_id"], binding["credential_version"]))
        for row in self.store.runs():
            manifest = read_json(self.store.path(row["id"]) / "manifest.json")
            binding = manifest.get("service") or {}
            # A retained raw run is an audit dependency; archived safe views aren't.
            if binding.get("credential_id") and (
                row["status"] not in TERMINAL
                or not (self.store.path(row["id"]) / "archived.json").exists()
            ):
                refs.add((binding["credential_id"], binding["credential_version"]))
        return refs

    def prune_credentials(self):
        # File inspection stays outside the write transaction/control path. Merge
        # durable submissions again inside the transaction: a preparation may
        # have been accepted/published while the archive snapshot was inspected.
        dependencies = self.dependencies()
        archived = {
            row["id"]
            for row in self.store.runs()
            if row["status"] in TERMINAL and (self.store.path(row["id"]) / "archived.json").exists()
        }
        count = 0
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute(
                "SELECT target_id,frozen FROM submissions WHERE status='preparing' OR run_id IS NOT NULL"
            ):
                if row["target_id"] in archived:
                    continue
                binding = json.loads(row["frozen"])["service"]
                if binding.get("credential_id"):
                    dependencies.add((binding["credential_id"], binding["credential_version"]))
            current = {
                (row[0], row[1])
                for row in db.execute("SELECT id,MAX(version) FROM credential_versions GROUP BY id")
            }
            for row in db.execute("SELECT id,version FROM credential_versions").fetchall():
                ref = (row["id"], row["version"])
                if ref not in dependencies and ref not in current:
                    db.execute("DELETE FROM credential_versions WHERE id=? AND version=?", ref)
                    count += 1
        return {"pruned_versions": count, "retained_dependencies": len(dependencies)}
