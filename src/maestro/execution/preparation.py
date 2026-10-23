"""Docker preparation environment (02 sections 5-8, M1 TECH-03, U-17).

The platform prepares a task's image itself, without Harbor and without an agent:
a reproducible ``buildx`` build of the task's ``environment/`` directory, or a pull
of the author's image pinned to its repository digest. The result is identified by
its image id, tagged ``maestro-prep/<instance>:<spec hex>`` and exported with
``docker save`` as the recoverable original. Eviction removes only the local image.

Restore loads the original and checks the image id; only when the original is gone
does it rebuild or re-pull, and a different image id is a mismatch that is never
published. Work happens under a temporary tag, so a late or orphaned build cannot
replace a published image.
"""

import asyncio
import contextlib
import ctypes
import hashlib
import logging
import os
import re
import secrets
import shutil
import signal
from pathlib import Path

from maestro.boundaries.environment import (
    AUTH,
    MISMATCH,
    TRANSIENT,
    UNAVAILABLE,
    UNSUPPORTED,
    PreparationError,
    PreparationSpec,
    PreparedOutput,
    Progress,
)

log = logging.getLogger(__name__)

LABEL_SPEC = "io.maestro.spec_digest"
DEFAULT_BUILD_TIMEOUT = 600.0
PULL_TIMEOUT = 1800.0
SAVE_TIMEOUT = 1800.0
_AUTH = re.compile(
    r"pull access denied|unauthorized|authentication required|denied:", re.IGNORECASE
)
_MISSING = re.compile(
    r"manifest unknown|not found: manifest|manifest for .* not found", re.IGNORECASE
)


def _die_with_parent() -> None:
    """The docker client ends with the service; BuildKit then cancels the build."""
    with contextlib.suppress(OSError, AttributeError):
        ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


class DockerEnvironment:
    location_id = "local-docker"

    def __init__(self, archive_dir: Path, docker: str | None = None):
        self.archive_dir = archive_dir
        self.docker = docker or shutil.which("docker") or "docker"
        self.repository: str | None = None

    def bind(self, instance_id: str) -> None:
        """Images live under a per-instance repository, so instances never collide."""
        self.repository = f"maestro-prep/{instance_id.lower()}"

    def ref(self, spec_digest: str) -> str:
        if self.repository is None:
            raise RuntimeError("environment is not bound to an instance")
        return f"{self.repository}:{spec_digest.split(':', 1)[1]}"

    # --- docker client ---------------------------------------------------------------

    async def _run(self, *args: str, timeout: float) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            self.docker,
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            preexec_fn=_die_with_parent,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except (TimeoutError, asyncio.CancelledError) as error:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGTERM)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), 10)
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)
            if isinstance(error, asyncio.CancelledError):
                raise
            raise PreparationError(TRANSIENT, f"docker {args[0]} timed out after {timeout}s")
        return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")

    async def _image_id(self, ref: str) -> str | None:
        code, out, _ = await self._run("image", "inspect", "--format", "{{.Id}}", ref, timeout=60)
        value = out.strip()
        return value if code == 0 and value.startswith("sha256:") else None

    async def _untag(self, ref: str) -> None:
        await self._run("image", "rm", "--no-prune", ref, timeout=120)

    # --- producing an image ------------------------------------------------------------

    async def _build(self, spec: PreparationSpec, tag: str, progress: Progress) -> dict:
        env_dir = spec.task_dir / "environment"
        if not (env_dir / "Dockerfile").is_file():
            raise PreparationError(UNSUPPORTED, "the task has no environment/Dockerfile")
        await progress("building")
        timeout = max(float(spec.spec["environment"].get("build_timeout_sec") or 0), 0)
        code, _, err = await self._run(
            "buildx",
            "build",
            "--provenance=false",
            "--build-arg",
            "SOURCE_DATE_EPOCH=0",
            "--label",
            f"{LABEL_SPEC}={spec.spec_digest.split(':', 1)[1]}",
            "--output",
            f"type=docker,rewrite-timestamp=true,name={tag}",
            "-f",
            str(env_dir / "Dockerfile"),
            str(env_dir),
            timeout=timeout or DEFAULT_BUILD_TIMEOUT,
        )
        if code:
            kind = AUTH if _AUTH.search(err) else TRANSIENT
            raise PreparationError(kind, "image build failed", {"stderr_tail": err[-2000:]})
        return {"method": "build"}

    async def _pull(self, reference: str, tag: str, progress: Progress) -> dict:
        await progress("pulling")
        code, _, err = await self._run("pull", "--quiet", reference, timeout=PULL_TIMEOUT)
        if code:
            if _AUTH.search(err):
                # Docker reports "repository does not exist" and "login required" alike.
                kind = AUTH
            elif _MISSING.search(err) and "@sha256:" in reference:
                kind = UNAVAILABLE
            else:
                kind = TRANSIENT
            raise PreparationError(
                kind, f"pull of {reference} failed", {"stderr_tail": err[-2000:]}
            )
        code, out, _ = await self._run(
            "image", "inspect", "--format", "{{json .RepoDigests}}", reference, timeout=60
        )
        digests = [d for d in re.findall(r'"([^"]+@sha256:[0-9a-f]{64})"', out)]
        pinned = reference if "@sha256:" in reference else (digests[0] if digests else None)
        code, _, err = await self._run("tag", reference, tag, timeout=60)
        if code:
            raise PreparationError(TRANSIENT, "tagging the pulled image failed")
        return {"method": "pull", "reference": reference, "repo_digest": pinned}

    async def _produce(self, spec: PreparationSpec, progress: Progress, pinned: str | None):
        """Build or pull under a temporary tag; returns (temporary tag, image id, detail)."""
        environment = spec.spec.get("environment") or {}
        tag = f"{self.ref(spec.spec_digest)}-tmp-{secrets.token_hex(4)}"
        try:
            if environment.get("kind") == "build":
                detail = await self._build(spec, tag, progress)
            elif environment.get("kind") == "image":
                detail = await self._pull(pinned or environment["docker_image"], tag, progress)
            else:
                raise PreparationError(UNSUPPORTED, "the task has no supported environment")
            await progress("checking")
            image_id = await self._image_id(tag)
            if image_id is None:
                raise PreparationError(TRANSIENT, "the prepared image is not present")
        except BaseException:
            with contextlib.suppress(Exception):
                await asyncio.shield(self._untag(tag))
            raise
        return tag, image_id, detail

    async def _publish(self, tag: str, ref: str) -> None:
        code, _, err = await self._run("tag", tag, ref, timeout=60)
        await self._untag(tag)
        if code:
            raise PreparationError(TRANSIENT, "publishing the image tag failed", {"stderr": err})

    async def _export(self, ref: str, spec_digest: str, progress: Progress) -> dict:
        """``docker save`` to a temporary file, digest it, then rename into place."""
        await progress("exporting")
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        name = spec_digest.split(":", 1)[1] + ".tar"
        temporary = self.archive_dir / f".{name}.{secrets.token_hex(4)}.tmp"
        try:
            code, _, err = await self._run("save", "-o", str(temporary), ref, timeout=SAVE_TIMEOUT)
            if code:
                raise PreparationError(
                    TRANSIENT, "exporting the image failed", {"stderr": err[-500:]}
                )
            digest = await asyncio.to_thread(_file_digest, temporary)
            size = temporary.stat().st_size
            os.replace(temporary, self.archive_dir / name)
        finally:
            temporary.unlink(missing_ok=True)
        return {"name": name, "digest": digest, "size_bytes": size}

    # --- boundary -----------------------------------------------------------------------

    async def prepare(self, spec: PreparationSpec, progress: Progress) -> PreparedOutput:
        ref = self.ref(spec.spec_digest)
        tag, image_id, detail = await self._produce(spec, progress, None)
        await self._publish(tag, ref)
        archive = await self._export(ref, spec.spec_digest, progress)
        return PreparedOutput(image_id, ref, archive, detail)

    async def check(self, expected: PreparedOutput) -> bool:
        return await self._image_id(expected.image_ref) == expected.image_id

    async def _load(self, expected: PreparedOutput, progress: Progress) -> bool:
        archive = expected.archive or {}
        path = self.archive_dir / str(archive.get("name") or "")
        if not archive.get("name") or not path.is_file():
            return False
        await progress("loading")
        if await asyncio.to_thread(_file_digest, path) != archive.get("digest"):
            log.warning("preparation original %s is damaged", path.name)
            return False
        code, _, err = await self._run("load", "--quiet", "-i", str(path), timeout=SAVE_TIMEOUT)
        if code:
            raise PreparationError(TRANSIENT, "loading the original failed", {"stderr": err[-500:]})
        return await self.check(expected)

    async def restore(
        self, spec: PreparationSpec, expected: PreparedOutput, progress: Progress
    ) -> PreparedOutput:
        await progress("checking")
        if await self.check(expected):
            return expected
        if await self._load(expected, progress):
            return expected
        # The original is missing or damaged: obtain the fixed content again, but
        # only an identical image may be published (02 section 5).
        tag, image_id, detail = await self._produce(
            spec, progress, (expected.detail or {}).get("repo_digest")
        )
        if image_id != expected.image_id:
            await self._untag(tag)
            raise PreparationError(
                MISMATCH,
                "the rebuilt image differs from the prepared original",
                {"expected_digest": expected.image_id, "actual_digest": image_id},
            )
        await self._publish(tag, expected.image_ref)
        archive = await self._export(expected.image_ref, spec.spec_digest, progress)
        return PreparedOutput(image_id, expected.image_ref, archive, {**expected.detail, **detail})

    async def evict(self, expected: PreparedOutput) -> None:
        if await self._image_id(expected.image_ref) is None:
            return
        code, _, err = await self._run("image", "rm", expected.image_ref, timeout=120)
        if code and await self._image_id(expected.image_ref) is not None:
            raise PreparationError(TRANSIENT, "the image is still in use", {"stderr": err[-500:]})

    async def discard(self, expected: PreparedOutput) -> None:
        await self.evict(expected)
        name = (expected.archive or {}).get("name")
        if name:
            (self.archive_dir / name).unlink(missing_ok=True)

    async def sweep_temporary(self) -> list[str]:
        """Restart: drop temporary tags an interrupted preparation left behind."""
        if self.repository is None:
            return []
        code, out, _ = await self._run(
            "image", "ls", self.repository, "--format", "{{.Repository}}:{{.Tag}}", timeout=60
        )
        removed = []
        for ref in out.split() if code == 0 else []:
            if "-tmp-" in ref.rsplit(":", 1)[-1]:
                await self._untag(ref)
                removed.append(ref)
        return removed
