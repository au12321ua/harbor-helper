"""External master-key generations and the only credential crypto boundary.

Ported from the ``dev`` rotation design (commit 2538538): key files live outside
the database and data directory, are never overwritten, and the database stores
only the active generation, file name and a key check value. Rotation re-encrypts
every credential and publishes the new generation in one write transaction.
Old key files are kept: the master key is the one thing Maestro never deletes.
"""

import hashlib
import hmac
import os
import re
import secrets
import stat
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Connection, func, insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from maestro.core import clock
from maestro.core.errors import MaestroError
from maestro.db import schema as t
from maestro.db.engine import Database

_NAME = re.compile(r"master-[0-9]{1,9}-[0-9a-f]{32}\.key")


class MasterKeyUnavailable(MaestroError):
    def __init__(self, detail: str = "Protected master key unavailable"):
        super().__init__("MASTER_KEY_UNAVAILABLE", detail, 503, retryable=True)


def kcv(key: bytes, generation: int) -> str:
    return hmac.new(key, f"maestro/master/{generation}".encode(), hashlib.sha256).hexdigest()


def encrypt(key: bytes, plaintext: str, aad: str) -> tuple[bytes, bytes]:
    nonce = secrets.token_bytes(12)
    return nonce, AESGCM(key).encrypt(nonce, plaintext.encode(), aad.encode())


def decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: str) -> str:
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, aad.encode()).decode()
    except (InvalidTag, UnicodeError):
        raise MaestroError(
            "CREDENTIAL_UNAVAILABLE", "Stored credential cannot be decrypted", 409
        ) from None


def credential_aad(credential_id: str, revision: int) -> str:
    # Binding identity and revision stops a ciphertext being swapped onto another row.
    return f"maestro/credential/{credential_id}/{revision}"


class MasterKeys:
    def __init__(self, db: Database, directory: Path, data_dir: Path):
        self.db = db
        self.directory = directory
        self.data_dir = data_dir

    # --- files -------------------------------------------------------------

    def _open_directory(self) -> int:
        # Reasons name the directory's problem, never key material.
        path = self.directory
        if (
            not path.is_absolute()
            or path.is_symlink()
            or path.resolve().is_relative_to(self.data_dir.resolve())
        ):
            raise MasterKeyUnavailable(
                "master_key_dir must be an absolute, non-symlink path outside data_dir"
            )
        try:
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as error:
            raise MasterKeyUnavailable(f"Cannot open master_key_dir: {error.strerror}") from None
        meta = os.fstat(fd)
        if meta.st_uid != os.getuid() or stat.S_IMODE(meta.st_mode) & 0o022:
            os.close(fd)
            raise MasterKeyUnavailable(
                "master_key_dir must be owned by the service account and not group- or "
                f"world-writable (now {stat.S_IMODE(meta.st_mode):04o})"
            )
        return fd

    def _read(self, basename: str, generation: int, expected: str) -> bytes:
        if not _NAME.fullmatch(basename):
            raise MasterKeyUnavailable()
        fd = self._open_directory()
        try:
            keyfd = os.open(basename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(keyfd, "rb") as file:
                meta = os.fstat(file.fileno())
                if (
                    not stat.S_ISREG(meta.st_mode)
                    or meta.st_uid != os.getuid()
                    or meta.st_mode & 0o077
                ):
                    raise ValueError
                raw = file.read(33)
            if len(raw) != 32 or not hmac.compare_digest(kcv(raw, generation), expected):
                raise ValueError
            return raw
        except (OSError, ValueError):
            raise MasterKeyUnavailable() from None
        finally:
            os.close(fd)

    def _create(self, fd: int, basename: str) -> tuple[bytes, int]:
        """Never overwrite; the file is durable before any reference is committed."""
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
            self._remove_owned(fd, basename, inode)
            raise
        return key, inode

    @staticmethod
    def _remove_owned(fd: int, basename: str, inode: int) -> None:
        try:
            meta = os.stat(basename, dir_fd=fd, follow_symlinks=False)
            if meta.st_ino == inode and stat.S_ISREG(meta.st_mode):
                os.unlink(basename, dir_fd=fd)
                os.fsync(fd)
        except FileNotFoundError:
            pass

    # --- state -------------------------------------------------------------

    @staticmethod
    def active(conn: Connection) -> dict:
        rows = conn.execute(select(t.master_key_state)).mappings().all()
        if len(rows) != 1:
            raise MasterKeyUnavailable("Master key state missing")
        return dict(rows[0])

    def initialize(self) -> bool:
        """Create generation 1 on an empty instance. Returns True when created."""
        with self.db.write() as conn:
            if conn.execute(select(func.count()).select_from(t.master_key_state)).scalar():
                return False
            fd = self._open_directory()
            try:
                basename = f"master-1-{secrets.token_hex(16)}.key"
                key, _ = self._create(fd, basename)
            finally:
                os.close(fd)
            conn.execute(
                insert(t.master_key_state).values(
                    singleton=1, generation=1, basename=basename, kcv=kcv(key, 1)
                )
            )
        return True

    def key_for(self, conn: Connection, generation: int) -> bytes:
        state = self.active(conn)
        if state["generation"] != generation:
            raise MasterKeyUnavailable("Credential encrypted under a retired key generation")
        return self._read(state["basename"], state["generation"], state["kcv"])

    def current(self, conn: Connection) -> tuple[int, bytes]:
        state = self.active(conn)
        return state["generation"], self._read(state["basename"], state["generation"], state["kcv"])

    def status(self) -> dict:
        with self.db.read() as conn:
            try:
                state = self.active(conn)
            except MasterKeyUnavailable:
                return {
                    "initialized": False,
                    "available": False,
                    "generation": None,
                    "rotated_at": None,
                }
        try:
            self._read(state["basename"], state["generation"], state["kcv"])
            available = True
        except MasterKeyUnavailable:
            available = False
        return {
            "initialized": True,
            "available": available,
            "generation": state["generation"],
            "rotated_at": state["rotated_at"],
        }

    def rotate(self, expected_generation: int, on_commit) -> dict:
        """Re-encrypt every credential under a new generation.

        ``on_commit(conn, generation, count)`` records the audit event inside the
        same transaction.
        """
        created: tuple[str, int] | None = None
        committed = False
        fd = None
        try:
            with self.db.write() as conn:
                old = self.active(conn)
                if old["generation"] != expected_generation:
                    raise MaestroError(
                        "MASTER_KEY_GENERATION_CONFLICT",
                        "Master key changed; refresh before rotating",
                        409,
                    )
                old_key = self._read(old["basename"], old["generation"], old["kcv"])
                fd = self._open_directory()
                generation = expected_generation + 1
                basename = f"master-{generation}-{secrets.token_hex(16)}.key"
                new_key, inode = self._create(fd, basename)
                created = (basename, inode)
                rows = conn.execute(select(t.credentials)).mappings().all()
                for row in rows:
                    aad = credential_aad(row["id"], row["revision"])
                    plaintext = decrypt(old_key, row["nonce"], row["encrypted_payload"], aad)
                    nonce, ciphertext = encrypt(new_key, plaintext, aad)
                    if decrypt(new_key, nonce, ciphertext, aad) != plaintext:
                        raise MasterKeyUnavailable("Re-encryption check failed")
                    conn.execute(
                        update(t.credentials)
                        .where(t.credentials.c.id == row["id"])
                        .values(nonce=nonce, encrypted_payload=ciphertext, key_version=generation)
                    )
                rotated_at = clock.to_text(clock.now())
                conn.execute(
                    update(t.master_key_state)
                    .where(t.master_key_state.c.singleton == 1)
                    .values(
                        generation=generation,
                        basename=basename,
                        kcv=kcv(new_key, generation),
                        rotated_at=rotated_at,
                    )
                )
                on_commit(conn, generation, len(rows))
            committed = True
            return {
                "initialized": True,
                "available": True,
                "generation": generation,
                "rotated_at": rotated_at,
                "reencrypted_credentials": len(rows),
            }
        finally:
            if fd is not None:
                try:
                    if created and not committed:
                        # COMMIT may fail with an uncertain outcome: only remove the
                        # new file after confirming it is not the active generation.
                        try:
                            with self.db.read() as check:
                                retained = self.active(check)["basename"] == created[0]
                        except (MaestroError, OSError, SQLAlchemyError):
                            retained = True
                        if not retained:
                            self._remove_owned(fd, *created)
                finally:
                    os.close(fd)
