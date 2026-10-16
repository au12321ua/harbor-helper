"""Credentials persistence operations sharing the service store."""

import json
import os
import secrets
import stat
import time
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from harbor_helper.persistence.files import read_json
from harbor_helper.persistence.store import TERMINAL
from harbor_helper.service.primitives import (
    ServiceError,
    identifier,
    public_user,
    secret_value,
)


class Credentials:
    def _master(self, path=None):
        path = Path(path or read_json(self.root / "service.json")["master_file"])
        if path.resolve().is_relative_to(self.root) or path.is_symlink():
            raise ServiceError(
                "master_unavailable", "Protected external master key unavailable", 503
            )
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as file:
                meta = os.fstat(file.fileno())
                raw = file.read(33)
            if (
                not stat.S_ISREG(meta.st_mode)
                or meta.st_uid != os.getuid()
                or (stat.S_IMODE(meta.st_mode) & 0o077)
                or len(raw) != 32
            ):
                raise ValueError
            return raw
        except (OSError, ValueError):
            raise ServiceError(
                "master_unavailable", "Protected external master key unavailable", 503
            ) from None

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

    def add_credential(self, credential_id, provider_id, label, key, rotate=False):
        identifier(credential_id)
        self.object("provider", provider_id)
        secret_value(key)
        if not isinstance(label, str) or not 1 <= len(label) <= 128:
            raise ServiceError("invalid_label", "Credential label must be 1–128 characters")
        master = self._master()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
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
            nonce = secrets.token_bytes(12)
            aad = f"{provider_id}/{credential_id}/{version}".encode()
            ciphertext = AESGCM(master).encrypt(nonce, key.encode(), aad)
            db.execute(
                "INSERT INTO credential_versions VALUES(?,?,?,?,1,?,?,?)",
                (credential_id, version, provider_id, label, nonce, ciphertext, time.time()),
            )
        return self.credential(credential_id)

    def disable_credential(self, credential_id):
        self.credential(credential_id)
        with self.store.connect() as db:
            db.execute("UPDATE credential_versions SET enabled=0 WHERE id=?", (credential_id,))
        return self.credential(credential_id)

    def key(self, credential_id, version, provider_id, execution=False):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM credential_versions WHERE id=? AND version=?",
                (credential_id, version),
            ).fetchone()
        if row is None or row["provider_id"] != provider_id or (execution and not row["enabled"]):
            raise ServiceError(
                "credential_unavailable", "Bound credential unavailable or disabled", 409
            )
        try:
            return (
                AESGCM(self._master())
                .decrypt(
                    row["nonce"],
                    row["ciphertext"],
                    f"{provider_id}/{credential_id}/{version}".encode(),
                )
                .decode()
            )
        except (InvalidTag, UnicodeError):
            raise ServiceError(
                "credential_unavailable", "Bound credential cannot be decrypted", 409
            ) from None

    def notice_secrets(self):
        """Known team keys for validating a public maintenance notice, never metadata."""
        with self.store.connect() as db:
            credentials = db.execute(
                "SELECT id,version,provider_id FROM credential_versions"
            ).fetchall()
            has_sources = db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='source_credentials'"
            ).fetchone()
            sources = (
                db.execute("SELECT * FROM source_credentials").fetchall() if has_sources else []
            )
        values = [self.key(r["id"], r["version"], r["provider_id"]) for r in credentials]
        try:
            for row in sources:
                values.append(
                    AESGCM(self._master())
                    .decrypt(row["nonce"], row["ciphertext"], f"hub/{row['version']}".encode())
                    .decode()
                )
        except (InvalidTag, UnicodeError):
            raise ServiceError(
                "admission_state_unavailable", "Notice safety unavailable", 503
            ) from None
        return values

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
            if (
                self.object("provider", binding["provider_id"], binding["provider_version"])[
                    "endpoint"
                ]
                != manifest["effective"]["model"]["endpoint"]
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
        dependencies = self.dependencies()
        current = {(c["id"], c["version"]) for c in self.credentials()}
        count = 0
        with self.store.connect() as db:
            for row in db.execute("SELECT id,version FROM credential_versions").fetchall():
                ref = (row["id"], row["version"])
                if ref not in dependencies and ref not in current:
                    db.execute("DELETE FROM credential_versions WHERE id=? AND version=?", ref)
                    count += 1
        return {"pruned_versions": count, "retained_dependencies": len(dependencies)}
