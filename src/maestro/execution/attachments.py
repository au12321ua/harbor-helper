"""Attachment packages (03 section 6): unpacking, checks, digest and the content store.

A package is a tar (optionally compressed) or zip archive holding ``manifest.json`` at
its root, or inside one top-level directory, plus any files; ``bootstrap.sh`` at the
root is the install script each trial runs in its own container (03 section 7).

Unpacking never lets the archive choose what is written: only regular files and
directories are accepted, names are checked part by part before anything is written,
and sizes are counted while reading, so links, devices, absolute paths, ``..`` and
archive bombs are refused rather than cleaned up afterwards. Uploading never runs the
script.

The content digest covers each file's path, SHA-256 and executable bit, so the Runner can
compare a container's copy file by file with ``sha256sum``.
"""

import io
import json
import os
import re
import shutil
import stat
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from maestro.core.digests import digest_json

MANIFEST = "manifest.json"
BOOTSTRAP = "bootstrap.sh"
MANIFEST_MAX_BYTES = 64 * 1024
EFFECTS = ("model_call", "agent_tools", "task_environment", "verifier", "scoring")
# Packages that change verification or scoring form a different scoring contract
# (03 section 6); P0 has no such contract, so they are refused at upload.
SUPPORTED_EFFECTS = ("model_call", "agent_tools", "task_environment")
# Manifest fields of the design that P0 does not implement; refused rather than ignored.
UNSUPPORTED_FIELDS = ("parameter_schema", "entrypoints", "load_order_requirements")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}")
PROVIDED = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,127}")
# Path parts the Runner can pass through ``sha256sum`` output and shell commands unquoted.
PATH_PART = re.compile(r"[A-Za-z0-9._+@-]{1,255}")
PATH_MAX = 1024
DEPTH_MAX = 32
# A long-name or pax header is read into memory whole; real ones are a few KiB.
TAR_HEADER_MAX = 64 * 1024
# Directories and refused entries count too: every entry costs memory while reading.
ENTRIES_PER_FILE = 2


class PackageError(Exception):
    """``problems`` are (JSON pointer, code, message)."""

    def __init__(self, message: str, problems: list[tuple[str, str, str]]):
        super().__init__(message)
        self.problems = problems


@dataclass
class Package:
    root: Path
    manifest: dict
    files: list[dict]
    content_digest: str
    size_bytes: int
    has_bootstrap: bool
    components: list[str] = field(default_factory=list)


def files_digest(files: list[dict]) -> str:
    return digest_json([[f["path"], f["sha256"], f["executable"]] for f in files])


def _check_path(name: str) -> str | None:
    """A relative path made of safe parts, or None. Directory entries end with '/'."""
    name = name.removesuffix("/").removeprefix("./")
    if not name or len(name) > PATH_MAX or name.startswith("/"):
        return None
    parts = name.split("/")
    if len(parts) > DEPTH_MAX:
        return None
    if any(p in {".", ".."} or not PATH_PART.fullmatch(p) for p in parts):
        return None
    return name


class _Writer:
    """Writes accepted entries below ``root``, enforcing the limits as it goes."""

    def __init__(self, root: Path, max_files: int, max_bytes: int):
        self.root = root
        self.max_files = max_files
        self.max_bytes = max_bytes
        self.files: dict[str, bool] = {}  # path -> executable
        self.dirs: set[str] = set()
        self.total = 0
        self.entries = 0
        self.problems: list[tuple[str, str, str]] = []

    def count(self) -> None:
        self.entries += 1
        if self.entries > self.max_files * ENTRIES_PER_FILE:
            self.problem("", "TOO_MANY_FILES", f"at most {self.max_files} files")
            raise PackageError("Attachment has too many entries", self.problems)

    def problem(self, path: str, code: str, message: str) -> None:
        if len(self.problems) < 50:
            self.problems.append((f"/archive/{path}", code, message))

    def directory(self, raw: str) -> None:
        self.count()
        if raw in {".", "./"}:  # the root itself, as ``tar -C dir .`` writes it
            return
        path = _check_path(raw)
        if path is None:
            self.problem(raw, "PATH", "only relative names of letters, digits and ._+@-")
        elif path in self.files:
            self.problem(path, "DUPLICATE", "a file and a directory share this name")
        else:
            self.dirs.add(path)

    def file(self, raw: str, size: int, executable: bool, stream) -> None:
        self.count()
        path = _check_path(raw)
        if path is None:
            self.problem(raw, "PATH", "only relative names of letters, digits and ._+@-")
            return
        if path in self.files or path in self.dirs:
            self.problem(path, "DUPLICATE", "the archive holds this name twice")
            return
        if len(self.files) >= self.max_files:
            self.problem(path, "TOO_MANY_FILES", f"at most {self.max_files} files")
            raise PackageError("Attachment has too many files", self.problems)
        if self.total + size > self.max_bytes:
            self.problem(path, "TOO_LARGE", f"at most {self.max_bytes} bytes unpacked")
            raise PackageError("Attachment is too large unpacked", self.problems)
        target = self.root / path
        if any(str(parent) in self.files for parent in Path(path).parents) or any(
            other.startswith(path + "/") for other in self.files
        ):
            self.problem(path, "DUPLICATE", "a file and a directory share this name")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with target.open("xb") as sink:
            while chunk := stream.read(1 << 20):
                written += len(chunk)
                if written > size or self.total + written > self.max_bytes:
                    self.problem(path, "TOO_LARGE", "longer than the archive says")
                    raise PackageError("Attachment is too large unpacked", self.problems)
                sink.write(chunk)
        self.total += written
        self.files[path] = executable
        os.chmod(target, 0o755 if executable else 0o644)


class _BoundedTarInfo(tarfile.TarInfo):
    """Refuses, before reading them, the headers ``tarfile`` would load into memory whole:
    oversized long-name and pax headers, and sparse files with their unbounded maps."""

    def _proc_member(self, tarfile_):
        if self.type in (tarfile.GNUTYPE_SPARSE,):
            raise tarfile.HeaderError("sparse files are not allowed")
        if self.type in _EXTENDED_HEADERS and self.size > TAR_HEADER_MAX:
            raise tarfile.HeaderError(f"an extended header over {TAR_HEADER_MAX} bytes")
        return super()._proc_member(tarfile_)

    def _proc_gnusparse_10(self, next, pax_headers, tarfile_):
        raise tarfile.HeaderError("sparse files are not allowed")


_EXTENDED_HEADERS = (
    tarfile.GNUTYPE_LONGNAME,
    tarfile.GNUTYPE_LONGLINK,
    tarfile.XHDTYPE,
    tarfile.XGLTYPE,
    tarfile.SOLARIS_XHDTYPE,
)


def _unpack_tar(source, writer: _Writer) -> None:
    try:
        archive = tarfile.open(  # noqa: SIM115 - closed below
            fileobj=source, mode="r:*", tarinfo=_BoundedTarInfo
        )
    except (tarfile.TarError, OSError, EOFError) as error:
        raise PackageError(f"Not a tar or zip archive: {error}", []) from None
    with archive:
        try:
            for member in archive:
                # Read as a stream: the archive keeps no list of what it has passed.
                archive.members = []
                if member.isdir():
                    writer.directory(member.name)
                elif member.isreg():
                    stream = archive.extractfile(member)
                    writer.file(member.name, member.size, bool(member.mode & 0o100), stream)
                else:
                    writer.count()
                    writer.problem(
                        member.name, "FILE_TYPE", "links and special files are not allowed"
                    )
        except (tarfile.TarError, OSError, EOFError) as error:
            raise PackageError(f"Damaged archive: {error}", writer.problems) from None


def _zip_entries(source) -> int | None:
    """The entry count the end record declares, read before the central directory is."""
    try:
        record = zipfile._EndRecData(source)
    except OSError:
        return None
    return None if record is None else record[zipfile._ECD_ENTRIES_TOTAL]


def _unpack_zip(source, writer: _Writer) -> None:
    declared = _zip_entries(source)
    if declared is not None and declared > writer.max_files * ENTRIES_PER_FILE:
        writer.problem("", "TOO_MANY_FILES", f"at most {writer.max_files} files")
        raise PackageError("Attachment has too many entries", writer.problems)
    try:
        archive = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError) as error:
        raise PackageError(f"Damaged zip archive: {error}", []) from None
    with archive:
        try:
            for info in archive.infolist():
                mode = info.external_attr >> 16
                if info.is_dir():
                    writer.directory(info.filename)
                elif stat.S_IFMT(mode) and not stat.S_ISREG(mode):  # no type bits: a file
                    writer.count()
                    writer.problem(
                        info.filename, "FILE_TYPE", "links and special files are not allowed"
                    )
                else:
                    with archive.open(info) as stream:
                        writer.file(info.filename, info.file_size, bool(mode & 0o100), stream)
        except (zipfile.BadZipFile, OSError, RuntimeError) as error:
            raise PackageError(f"Damaged zip archive: {error}", writer.problems) from None


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def describe(root: Path) -> list[dict]:
    """The files below ``root`` in path order; links and special files are refused."""
    files = []
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"not a regular file: {relative}")
        files.append(
            {
                "path": relative,
                "size": info.st_size,
                "sha256": _sha256(path),
                "executable": bool(info.st_mode & 0o100),
            }
        )
    return files


def _manifest(root: Path) -> dict:
    path = root / MANIFEST
    if not path.is_file():
        raise PackageError("The package has no manifest.json", [("/archive", "MANIFEST", "")])
    if path.stat().st_size > MANIFEST_MAX_BYTES:
        raise PackageError(
            "manifest.json is too large", [("/manifest", "TOO_LARGE", str(MANIFEST_MAX_BYTES))]
        )
    try:
        manifest = json.loads(path.read_text("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise PackageError(f"manifest.json is not JSON: {error}", []) from None
    if not isinstance(manifest, dict):
        raise PackageError("manifest.json must be an object", [("/manifest", "TYPE", "")])
    return check_manifest(manifest)


def _names(value, pattern: re.Pattern) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(x, str) and pattern.fullmatch(x) for x in value)
        and len(set(value)) == len(value)
    )


def check_manifest(manifest: dict) -> dict:
    problems: list[tuple[str, str, str]] = []

    def bad(key: str, code: str, message: str = "") -> None:
        problems.append((f"/manifest/{key}", code, message))

    known = {
        "schema_version",
        "name",
        "version",
        "description",
        "effects",
        "compatible_harnesses",
        "provides",
    }
    for key in manifest:
        if key in UNSUPPORTED_FIELDS:
            bad(key, "UNSUPPORTED", "not supported by this version of the platform")
        elif key not in known:
            bad(key, "UNKNOWN_FIELD")
    if manifest.get("schema_version") != 1:
        bad("schema_version", "ENUM", "1")
    if not isinstance(manifest.get("name"), str) or not NAME.fullmatch(manifest["name"]):
        bad("name", "PATTERN", "letters, digits and ._- (at most 64)")
    if not isinstance(manifest.get("version"), str) or not VERSION.fullmatch(manifest["version"]):
        bad("version", "PATTERN", "letters, digits and ._+- (at most 64)")
    description = manifest.get("description", "")
    if not isinstance(description, str) or len(description) > 512:
        bad("description", "LENGTH", "at most 512 characters")
    effects = manifest.get("effects")
    if not _names(effects, re.compile("|".join(EFFECTS))) or not effects:
        bad("effects", "ENUM", ", ".join(EFFECTS))
    else:
        if set(effects) - set(SUPPORTED_EFFECTS):
            bad(
                "effects",
                "UNSUPPORTED",
                "packages that change verification or scoring are not supported yet",
            )
    harnesses = manifest.get("compatible_harnesses")
    if not _names(harnesses, re.compile(r"\*|[a-z0-9][a-z0-9_.-]{0,63}")) or not harnesses:
        bad("compatible_harnesses", "INVALID", 'harness agent names, or ["*"] for any')
    provides = manifest.get("provides", {})
    if not isinstance(provides, dict) or set(provides) - {"tools", "env"}:
        bad("provides", "INVALID", '{"tools": [...], "env": [...]}')
    else:
        for kind in ("tools", "env"):
            if not _names(provides.get(kind, []), PROVIDED):
                bad(f"provides/{kind}", "INVALID", "a list of distinct names")
    if problems:
        raise PackageError("manifest.json is not valid", problems)
    return {
        "schema_version": 1,
        "name": manifest["name"],
        "version": manifest["version"],
        "description": description,
        "effects": sorted(effects),
        "compatible_harnesses": sorted(harnesses),
        "provides": {k: sorted(provides.get(k, [])) for k in ("tools", "env")},
    }


def _strip_wrapper(root: Path) -> Path:
    """Archives made from a folder hold one top-level directory; its contents are the
    package."""
    if (root / MANIFEST).exists():
        return root
    entries = list(root.iterdir())
    if len(entries) == 1 and entries[0].is_dir() and (entries[0] / MANIFEST).is_file():
        return entries[0]
    return root


class AttachmentStore:
    """Published package files under ``<data_dir>/attachments/<hex digest>``. They are
    original content (not a cache): a purge removes them, nothing else does."""

    def __init__(self, data_dir: Path):
        self.root = data_dir / "attachments"

    def receive(self):
        """A temporary file on the store's file system for an upload in progress."""
        self.root.mkdir(parents=True, exist_ok=True)
        return tempfile.NamedTemporaryFile(prefix=".receive-", dir=self.root)

    def unpack(self, source: bytes | Path, max_files: int, max_bytes: int) -> Package:
        """Unpack an archive (its bytes, or a file) into a staging directory; the caller
        publishes or discards it."""
        self.root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".upload-", dir=self.root))
        try:
            writer = _Writer(staging / "files", max_files, max_bytes)
            writer.root.mkdir()
            with io.BytesIO(source) if isinstance(source, bytes) else open(source, "rb") as handle:
                magic = handle.read(4)
                handle.seek(0)
                if magic in (b"PK\x03\x04", b"PK\x05\x06"):
                    _unpack_zip(handle, writer)
                else:
                    _unpack_tar(handle, writer)
            if writer.problems:
                raise PackageError(
                    "The archive holds entries that are not allowed", writer.problems
                )
            root = _strip_wrapper(writer.root)
            manifest = _manifest(root)
            files = describe(root)
            bootstrap = root / BOOTSTRAP
            return Package(
                root=root,
                manifest=manifest,
                files=files,
                content_digest=files_digest(files),
                size_bytes=sum(f["size"] for f in files),
                has_bootstrap=bootstrap.is_file(),
                components=sorted(p.name for p in root.iterdir() if p.is_dir()),
            )
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def discard(self, package: Package) -> None:
        """Remove what is left of the upload's staging directory."""
        staging = package.root
        while staging.parent != self.root:
            if staging.parent == staging:
                return  # not a staging directory of this store
            staging = staging.parent
        shutil.rmtree(staging, ignore_errors=True)

    def _hex(self, content_digest: str) -> str | None:
        algorithm, _, value = content_digest.partition(":")
        if algorithm != "sha256" or not re.fullmatch(r"[0-9a-f]{64}", value):
            return None
        return value

    def path_for(self, content_digest: str) -> Path | None:
        value = self._hex(content_digest)
        path = self.root / value if value else None
        return path if path is not None and path.is_dir() else None

    def verified(self, content_digest: str) -> Path | None:
        """The stored copy, only if its files still match the digest."""
        path = self.path_for(content_digest)
        if path is None:
            return None
        try:
            return path if files_digest(describe(path)) == content_digest else None
        except (OSError, ValueError):
            return None

    def publish(self, package: Package) -> None:
        """Move the staged files in under their digest; an intact copy already there wins."""
        try:
            if self.verified(package.content_digest):
                return
            target = self.root / self._hex(package.content_digest)
            if target.exists():
                self.remove(package.content_digest)
            os.rename(package.root, target)
        finally:
            self.discard(package)

    def retire(self, content_digest: str) -> Path | None:
        """Move the files out of reach in one rename; the caller deletes what it returns."""
        path = self.path_for(content_digest)
        if path is None:
            return None
        retired = Path(tempfile.mkdtemp(prefix=".remove-", dir=self.root))
        os.rename(path, retired / "files")
        return retired

    def remove(self, content_digest: str) -> None:
        retired = self.retire(content_digest)
        if retired is not None:
            shutil.rmtree(retired, ignore_errors=True)

    def discard_partial(self) -> int:
        """At start, before any upload: staging left by a process that stopped mid-way."""
        removed = 0
        for entry in self.root.iterdir() if self.root.is_dir() else []:
            if entry.name.startswith((".upload-", ".receive-", ".remove-")):
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
                removed += 1
        return removed
