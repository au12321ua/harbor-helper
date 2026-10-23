"""Content-addressed task material cache and a local task-directory source.

The executor finds a task's files by its content digest under
``<cache_dir>/tasks/<hex>``. M4 fills the cache from the Hub; until then the local
source registers a directory of Harbor tasks for tests and development only.
"""

import hashlib
import os
import shutil
import stat
import tempfile
import tomllib
from pathlib import Path

from maestro.boundaries.dataset_source import SourceTask, SourceVersion
from maestro.core.digests import digest_json

DEFAULT_CPUS = 1
DEFAULT_MEMORY_MB = 2048


def tree_digest(root: Path) -> str:
    """Names, contents and executable bits; links and special files are rejected."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f"symlinks are unsupported in task content: {relative}")
        mode = path.stat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError(f"special files are unsupported in task content: {relative}")
        digest.update(relative.encode() + b"\0" + str(mode & 0o111).encode() + b"\0")
        if path.is_file():
            digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


class TaskMaterials:
    def __init__(self, cache_dir: Path):
        self.root = cache_dir / "tasks"

    def path_for(self, content_digest: str) -> Path | None:
        algorithm, _, value = content_digest.partition(":")
        if algorithm != "sha256" or len(value) != 64 or not value.isalnum():
            return None
        path = self.root / value
        return path if (path / "task.toml").is_file() else None

    def remove(self, content_digest: str) -> None:
        """Retire a task's material: renamed away first so no reader sees half a tree."""
        path = self.path_for(content_digest)
        if path is None:
            return
        retired = Path(tempfile.mkdtemp(prefix=".remove-", dir=self.root))
        os.rename(path, retired / "task")
        shutil.rmtree(retired, ignore_errors=True)

    def install(self, source: Path) -> str:
        """Copy a task directory in, verified by digest, published by an atomic rename."""
        content_digest = tree_digest(source)
        if self.path_for(content_digest):
            return content_digest
        self.root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".install-", dir=self.root))
        try:
            copy = staging / "task"
            shutil.copytree(source, copy, symlinks=True)
            if tree_digest(copy) != content_digest:
                raise ValueError("task content changed while it was being copied")
            try:
                os.rename(copy, self.root / content_digest.split(":", 1)[1])
            except OSError:
                if not self.path_for(content_digest):
                    raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return content_digest


def task_definition(task_dir: Path) -> dict:
    """What the platform needs before execution: instruction and per-trial resources."""
    config = tomllib.loads((task_dir / "task.toml").read_text())
    environment = config.get("environment", {})
    instruction = task_dir / "instruction.md"
    return {
        "instruction": instruction.read_text()[:4000] if instruction.is_file() else "",
        "resources": {
            "cpus": environment.get("cpus") or DEFAULT_CPUS,
            "memory_mb": environment.get("memory_mb") or DEFAULT_MEMORY_MB,
        },
        "has_solution": (task_dir / "solution" / "solve.sh").is_file(),
    }


class LocalTaskSource:
    """Every subdirectory with a ``task.toml`` is one task. Development and tests only."""

    kind = "local"

    def __init__(self, root: Path, materials: TaskMaterials):
        self.root = root
        self.materials = materials

    def search(self, query: str) -> list[dict]:
        return []

    def resolve(self, namespace: str, name: str, ref: str) -> SourceVersion:
        tasks = []
        for task_dir in sorted(p for p in self.root.iterdir() if (p / "task.toml").is_file()):
            content_digest = self.materials.install(task_dir)
            tasks.append(SourceTask(task_dir.name, content_digest, task_definition(task_dir)))
        if not tasks:
            raise ValueError(f"no task directories under {self.root}")
        return SourceVersion(
            namespace=namespace,
            name=name,
            upstream_ref=ref,
            ref_kind="digest",
            resolved_digest=digest_json([[t.task_key, t.content_digest] for t in tasks]),
            tasks=tuple(tasks),
            description=f"Local tasks from {self.root.name}",
        )

    def fetch(self, version: SourceVersion, destination: Path) -> str:
        return version.resolved_digest
