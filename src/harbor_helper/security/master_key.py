"""Immutable external key generations and the sole credential crypto boundary.

Readers materialize ciphertext and active in one SQL statement, then release the
connection before filesystem IO. Writers obtain active only inside IMMEDIATE.
"""

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import stat
import time
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from harbor_helper.persistence.files import read_json
from harbor_helper.service.primitives import ServiceError


class MasterUnavailable(ServiceError):
    def __init__(self):
        super().__init__("master_unavailable", "Protected external master key unavailable", 503)


ACTIVE = "generation,basename,kcv,rotated_at"
SCHEMA = """CREATE TABLE master_active (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1), generation INTEGER NOT NULL,
    basename TEXT NOT NULL, kcv TEXT NOT NULL, rotated_at REAL)"""


def reference(row):
    try:
        value = {k: row[k] for k in ACTIVE.split(",")}
        if (
            type(value["generation"]) is not int
            or value["generation"] < 1
            or not isinstance(value["basename"], str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value["basename"])
            or not isinstance(value["kcv"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["kcv"])
            or (
                value["rotated_at"] is not None
                and (
                    type(value["rotated_at"]) not in (int, float)
                    or not math.isfinite(value["rotated_at"])
                    or value["rotated_at"] < 0
                )
            )
        ):
            raise ValueError
        return value
    except (KeyError, TypeError, IndexError, ValueError):
        raise MasterUnavailable() from None


def active(db):
    try:
        rows = db.execute("SELECT * FROM master_active").fetchall()
        if len(rows) != 1 or rows[0]["singleton"] != 1:
            raise MasterUnavailable()
        return reference(rows[0])
    except sqlite3.DatabaseError:
        raise MasterUnavailable() from None


def kcv(key, generation):
    return hmac.new(key, f"harbor-helper/master/{generation}".encode(), hashlib.sha256).hexdigest()


def directory(path, state):
    path, state = Path(path), Path(state).resolve()
    try:
        if not path.is_absolute() or path.is_symlink() or path.resolve().is_relative_to(state):
            raise ValueError
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        meta = os.fstat(fd)
        if (
            meta.st_uid != os.getuid()
            or stat.S_IMODE(meta.st_mode) & 0o022
            or Path(f"/proc/self/fd/{fd}").resolve().is_relative_to(state)
        ):
            os.close(fd)
            raise ValueError
        return fd
    except (OSError, ValueError):
        raise MasterUnavailable() from None


def read_key(path, state, ref):
    ref = reference(ref)
    fd = directory(path, state)
    try:
        keyfd = os.open(ref["basename"], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(keyfd, "rb") as file:
            meta = os.fstat(file.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid() or meta.st_mode & 0o077:
                raise ValueError
            raw = file.read(33)
        if len(raw) != 32 or not hmac.compare_digest(kcv(raw, ref["generation"]), ref["kcv"]):
            raise ValueError
        return raw
    except (OSError, ValueError):
        raise MasterUnavailable() from None
    finally:
        os.close(fd)


def create_key(fd, basename):
    """Never overwrite. Durability precedes any database reference publication."""
    key = secrets.token_bytes(32)
    keyfd = os.open(
        basename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
    )
    inode = os.fstat(keyfd).st_ino
    try:
        with os.fdopen(keyfd, "wb") as file:
            file.write(key)
            file.flush()
            os.fsync(file.fileno())
        os.fsync(fd)
    except BaseException:
        remove_owned(fd, basename, inode)
        raise
    return key, inode


def remove_owned(fd, basename, inode):
    try:
        meta = os.stat(basename, dir_fd=fd, follow_symlinks=False)
        if meta.st_uid == os.getuid() and meta.st_ino == inode and stat.S_ISREG(meta.st_mode):
            os.unlink(basename, dir_fd=fd)
            os.fsync(fd)
    except FileNotFoundError:
        pass


def durable_config(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(value, file)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        tmp.unlink(missing_ok=True)


def encrypt(key, plaintext, aad):
    nonce = secrets.token_bytes(12)
    return nonce, AESGCM(key).encrypt(nonce, plaintext.encode(), aad.encode())


def decrypt(key, row, aad):
    try:
        return AESGCM(key).decrypt(row["nonce"], row["ciphertext"], aad.encode()).decode()
    except (InvalidTag, UnicodeError):
        raise ServiceError(
            "credential_unavailable", "Bound credential cannot be decrypted", 409
        ) from None


def aad(row, table):
    return (
        f"hub/{row['version']}"
        if table == "source_credentials"
        else f"{row['provider_id']}/{row['id']}/{row['version']}"
    )


class MasterKeys:
    def __init__(self, store):
        self.store = store

    def initialize(self):
        """Only a missing table can import legacy master_file; existing damage is fatal.

        Config directory is durable before table commit. Retained legacy input is
        used solely for retry of an uncommitted import, then removed durably.
        """
        config = read_json(self.store.root / "service.json")
        with self.store.connect() as db:
            if "master_file" not in config:
                # Normalized config proves this is no longer an import. Missing
                # metadata remains a global fault, while the UI can still start.
                return
            db.execute("BEGIN IMMEDIATE")
            config = read_json(self.store.root / "service.json")
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='master_active'").fetchone():
                if "master_file" not in config:
                    raise MasterUnavailable()
                legacy = Path(config["master_file"])
                fd = directory(legacy.parent, self.store.root)
                try:
                    filefd = os.open(
                        legacy.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
                    )
                    with os.fdopen(filefd, "rb") as file:
                        meta = os.fstat(file.fileno())
                        if (
                            not stat.S_ISREG(meta.st_mode)
                            or meta.st_uid != os.getuid()
                            or meta.st_mode & 0o077
                        ):
                            raise MasterUnavailable()
                        raw = file.read(33)
                        if len(raw) != 32:
                            raise MasterUnavailable()
                        os.fsync(file.fileno())
                    os.fsync(fd)
                finally:
                    os.close(fd)
                reference(
                    {
                        "generation": 1,
                        "basename": legacy.name,
                        "kcv": kcv(raw, 1),
                        "rotated_at": None,
                    }
                )
                for table in ("credential_versions", "source_credentials"):
                    if db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
                        for row in db.execute(f"SELECT * FROM {table}"):
                            decrypt(raw, row, aad(row, table))
                config["master_directory"] = str(legacy.parent)
                durable_config(self.store.root / "service.json", config)
                db.execute(SCHEMA)
                db.execute(
                    "INSERT INTO master_active VALUES(1,1,?,?,NULL)", (legacy.name, kcv(raw, 1))
                )
            # Do not read files here on normal startup: faults remain a recoverable
            # global readiness error instead of preventing the admin UI from opening.
            db.commit()
            if "master_file" in config:
                config.pop("master_file")
                durable_config(self.store.root / "service.json", config)

    def load(self, ref):
        try:
            path = read_json(self.store.root / "service.json")["master_directory"]
            return read_key(path, self.store.root, ref)
        except (OSError, KeyError, ValueError):
            raise MasterUnavailable() from None

    def current(self, db=None):
        if db is not None:
            return self.load(active(db))
        with self.store.connect() as conn:
            ref = active(conn)
        return self.load(ref)

    def rows(self, table, where="", args=()):
        if table not in {"credential_versions", "source_credentials"}:
            raise ValueError("Unknown credential table")
        # LEFT JOIN preserves rows even when active was deleted. The scalar count
        # also rejects malformed multi-row active tables, without a second SELECT.
        try:
            with self.store.connect() as db:
                rows = db.execute(
                    f"SELECT c.*,m.generation,m.basename,m.kcv,m.rotated_at,(SELECT COUNT(*) FROM master_active) active_count FROM {table} c LEFT JOIN master_active m ON m.singleton=1 {where}",
                    args,
                ).fetchall()
        except sqlite3.DatabaseError:
            raise MasterUnavailable() from None
        if rows and rows[0]["active_count"] != 1:
            raise MasterUnavailable()
        return rows

    def status(self):
        with self.store.connect() as db:
            ref = active(db)
        available = True
        try:
            self.load(ref)
        except MasterUnavailable:
            available = False
        return {
            "generation": ref["generation"],
            "rotated_at": ref["rotated_at"],
            "available": available,
        }

    def rotate(self, actor, expected):
        created = None
        committed = False
        fd = None
        try:
            with self.store.control(), self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                old = active(db)
                if old["generation"] != expected:
                    raise ServiceError(
                        "master_generation_conflict",
                        "Master key changed; refresh before rotating",
                        409,
                    )
                oldkey = self.load(old)
                config = read_json(self.store.root / "service.json")
                fd = directory(config["master_directory"], self.store.root)
                name = f"master-{expected + 1}-{secrets.token_hex(16)}.key"
                newkey, inode = create_key(fd, name)
                created = (name, inode)
                counts = {}
                for table in ("credential_versions", "source_credentials"):
                    exists = db.execute(
                        "SELECT 1 FROM sqlite_master WHERE name=?", (table,)
                    ).fetchone()
                    rows = db.execute(f"SELECT * FROM {table}").fetchall() if exists else []
                    counts[table] = len(rows)
                    for row in rows:
                        label = aad(row, table)
                        plaintext = decrypt(oldkey, row, label)
                        nonce, ciphertext = encrypt(newkey, plaintext, label)
                        if (
                            decrypt(newkey, {"nonce": nonce, "ciphertext": ciphertext}, label)
                            != plaintext
                        ):
                            raise MasterUnavailable()
                        if table == "credential_versions":
                            db.execute(
                                f"UPDATE {table} SET nonce=?,ciphertext=? WHERE id=? AND version=?",
                                (nonce, ciphertext, row["id"], row["version"]),
                            )
                        else:
                            db.execute(
                                f"UPDATE {table} SET nonce=?,ciphertext=? WHERE version=?",
                                (nonce, ciphertext, row["version"]),
                            )
                rotated = time.time()
                db.execute(
                    "UPDATE master_active SET generation=?,basename=?,kcv=?,rotated_at=? WHERE singleton=1",
                    (expected + 1, name, kcv(newkey, expected + 1), rotated),
                )
                db.execute(
                    "INSERT INTO admin_events(actor,action,object_id,time) VALUES(?,?,?,?)",
                    (actor["username"], "rotate_master_key", str(expected + 1), rotated),
                )
                db.commit()
                committed = True
            return {
                "generation": expected + 1,
                "rotated_at": rotated,
                "available": True,
                "counts": counts,
            }
        finally:
            if fd is not None:
                try:
                    if created and not committed:
                        # COMMIT can report an uncertain IO outcome. Only remove
                        # after independently confirming this file is not active.
                        try:
                            with self.store.connect() as check:
                                retained = active(check)["basename"] == created[0]
                        except (sqlite3.DatabaseError, MasterUnavailable):
                            retained = True
                        if not retained:
                            remove_owned(fd, *created)
                finally:
                    os.close(fd)
