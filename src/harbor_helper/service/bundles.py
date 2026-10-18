"""Bundles service with explicit persistence dependency."""

import os
import shutil
import uuid
import zipfile
from pathlib import PurePosixPath

from harbor_helper.persistence.files import tree_digest
from harbor_helper.service.primitives import ServiceError


class Bundles:
    def __init__(self, data):
        self.data = data
        self.store = data.store

    def upload_bundle(self, archive, *, access_value=None):
        """Stage validated bundle bytes; the caller commits the bundles row."""
        limits = self.data.limits()
        archive.seek(0, 2)
        if archive.tell() > limits["max_upload_bytes"]:
            raise ServiceError("upload_limit", "Bundle upload too large", 413)
        archive.seek(0)
        bundle_id = "bundle-" + uuid.uuid4().hex[:16]
        path = self.store.root / "bundles" / bundle_id
        path.mkdir(parents=True, mode=0o700)
        try:
            with zipfile.ZipFile(archive) as z:
                entries = z.infolist()
                if (
                    len(entries) > 2000
                    or sum(e.file_size for e in entries) > limits["max_upload_bytes"]
                ):
                    raise ServiceError(
                        "upload_limit", "Expanded bundle exceeds configured limit", 413
                    )
                for entry in entries:
                    name = PurePosixPath(entry.filename)
                    mode = entry.external_attr >> 16
                    if (
                        not entry.filename
                        or name.is_absolute()
                        or ".." in name.parts
                        or "\\" in entry.filename
                        or mode & 0o170000 not in {0, 0o040000, 0o100000}
                    ):
                        raise ServiceError(
                            "unsafe_bundle", "Bundle paths, links and special files are restricted"
                        )
                    target = path / name
                    if entry.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with z.open(entry) as source, target.open("xb") as output:
                            shutil.copyfileobj(source, output)
                        target.chmod(0o700 if mode & 0o111 else 0o600)
            from harbor_helper.execution.bundles import BundleLayoutError, check_bundle

            try:
                check_bundle(path, access_value)
            except BundleLayoutError as error:
                # Only fixed layout messages are public; arbitrary validation
                # errors may contain configuration values and stay redacted.
                raise ServiceError("invalid_operation", str(error)) from None
            sha = tree_digest(path)
            # Publish durable bytes before committing the metadata pointing at them.
            for file in path.rglob("*"):
                if file.is_file():
                    with file.open("rb") as source:
                        os.fsync(source.fileno())
            directories = sorted((p for p in path.rglob("*") if p.is_dir()), reverse=True)
            for directory in [*directories, path, path.parent]:
                fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        except BaseException:
            shutil.rmtree(path, ignore_errors=True)
            raise
        return {"id": bundle_id, "digest": sha}
