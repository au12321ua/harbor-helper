"""Service persistence, invited identities and explicitly bound encrypted credentials.

No request changes process-global environments. Secrets leave this module only for
an independent worker or its audit, never through public metadata.
"""

import json
import os
import time
from pathlib import Path

from harbor_helper.execution.config import DEFAULT, reject_secrets
from harbor_helper.persistence.files import write_json
from harbor_helper.persistence.store import Store
from harbor_helper.security.master_key import MasterKeys, create_key, directory, durable_config
from harbor_helper.service.access import initialize
from harbor_helper.service.data_accounts import Accounts
from harbor_helper.service.data_capacity import Capacity
from harbor_helper.service.data_credentials import Credentials
from harbor_helper.service.data_objects import Objects
from harbor_helper.service.data_submissionrecords import SubmissionRecords
from harbor_helper.service.model_configuration import Models
from harbor_helper.service.primitives import (
    LIMITS,
    ServiceError,
    identifier,
)


class ServiceData(Accounts, Objects, Credentials, Capacity, SubmissionRecords):
    def __init__(self, root, *, initializing=False):
        self.store = root if isinstance(root, Store) else Store(root)
        self.root = self.store.root
        if not initializing and not (self.root / "service.json").is_file():
            raise ServiceError(
                "service_not_initialized", "Initialize a dedicated service state", 503
            )
        with self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, operation TEXT NOT NULL,
                    idem TEXT NOT NULL, request_hash TEXT NOT NULL, request TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL, attempts INTEGER NOT NULL,
                    status TEXT NOT NULL, result TEXT, error TEXT, recent TEXT NOT NULL,
                    UNIQUE(user_id,operation,idem));
                CREATE TABLE IF NOT EXISTS evidence_grants (
                    user_id TEXT PRIMARY KEY, granted INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL, role TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS sessions (
                    digest TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS login_failures (
                    username TEXT PRIMARY KEY, attempts INTEGER NOT NULL, until REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS objects (
                    kind TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL,
                    config TEXT NOT NULL, PRIMARY KEY(kind,id,version));
                CREATE TABLE IF NOT EXISTS credential_versions (
                    id TEXT NOT NULL, version INTEGER NOT NULL, provider_id TEXT NOT NULL,
                    label TEXT NOT NULL, enabled INTEGER NOT NULL, nonce BLOB NOT NULL,
                    ciphertext BLOB NOT NULL, created REAL NOT NULL, PRIMARY KEY(id,version));
                CREATE TABLE IF NOT EXISTS submissions (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, submitter TEXT NOT NULL,
                    operation TEXT NOT NULL, idem TEXT NOT NULL, request_hash TEXT NOT NULL,
                    request TEXT NOT NULL, frozen TEXT NOT NULL, target_id TEXT NOT NULL,
                    run_id TEXT, status TEXT NOT NULL, created REAL NOT NULL, error TEXT,
                    cancel INTEGER NOT NULL DEFAULT 0, parent TEXT,
                    UNIQUE(user_id,operation,idem));
                CREATE INDEX IF NOT EXISTS submissions_work ON submissions(status,created);
                CREATE TABLE IF NOT EXISTS bundles (
                    id TEXT PRIMARY KEY, digest TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS attachments (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
                    creator_id TEXT NOT NULL, created REAL NOT NULL, enabled INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS attachment_versions (
                    id TEXT PRIMARY KEY, attachment_id TEXT NOT NULL, number INTEGER NOT NULL,
                    bundle_id TEXT NOT NULL UNIQUE, digest TEXT NOT NULL,
                    publisher_id TEXT NOT NULL, created REAL NOT NULL, notes TEXT NOT NULL,
                    source_version_id TEXT, legacy INTEGER NOT NULL, enabled INTEGER NOT NULL,
                    UNIQUE(attachment_id,number));
                CREATE TABLE IF NOT EXISTS attachment_operations (
                    user_id TEXT NOT NULL, operation TEXT NOT NULL, idem TEXT NOT NULL,
                    request_hash TEXT NOT NULL, version_id TEXT NOT NULL,
                    PRIMARY KEY(user_id,operation,idem));
                CREATE TABLE IF NOT EXISTS artifact_deletions (
                    run_id TEXT NOT NULL, file_id TEXT NOT NULL, actor TEXT NOT NULL,
                    time REAL NOT NULL, PRIMARY KEY(run_id,file_id));
                CREATE TABLE IF NOT EXISTS admin_events (
                    id INTEGER PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL,
                    object_id TEXT NOT NULL, time REAL NOT NULL);
            """)

        with self.store.connect() as db:
            initialize(db)

        self.master_keys = MasterKeys(self.store)
        if not initializing:
            self.master_keys.initialize()

        self.models = Models(
            read_object=self.object,
            read_credential=self.credential,
            save_version=self.save_version,
        )

    @classmethod
    def initialize(cls, root, master_file, username, password, team=None):
        store = root if isinstance(root, Store) else Store(root)
        with store.control():
            return cls._initialize(store, master_file, username, password, team)

    @classmethod
    def _initialize(cls, store, master_file, username, password, team):
        identifier(username)
        if not isinstance(password, str) or not 12 <= len(password) <= 512:
            raise ServiceError("invalid_password", "Password must be 12–512 characters")
        master = Path(master_file).expanduser().absolute()
        if master.is_relative_to(store.root):
            raise ServiceError("master_location", "Master key must be outside service state")
        if (store.root / "service.json").exists() or (store.root / "team.json").exists():
            raise ServiceError("already_initialized", "Use a new dedicated service state", 409)
        master.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not master.exists():
            fd = directory(master.parent, store.root)
            try:
                create_key(fd, master.name)
            finally:
                os.close(fd)
        data = cls(store, initializing=True)
        config = json.loads(json.dumps(team or DEFAULT))
        reject_secrets(config)
        config.update({key: value for key, value in LIMITS.items() if key in DEFAULT})
        write_json(store.root / "team.json", config)
        store.root.chmod(0o700)
        (store.root / "runs").chmod(0o700)
        data.create_user(username, password, "admin")
        data.set_limits(LIMITS)
        durable_config(
            store.root / "service.json", {"master_file": str(master), "session_seconds": 28800}
        )
        data.master_keys.initialize()
        for name in ("service.json", "team.json", "queue.sqlite", "limits.json"):
            (store.root / name).chmod(0o600)
        return data

    def event(self, actor, action, object_id):
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO admin_events(actor,action,object_id,time) VALUES(?,?,?,?)",
                (actor["username"], action, object_id, time.time()),
            )
