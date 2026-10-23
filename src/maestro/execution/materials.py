"""Task material cache, task inspection and the preparation spec (02 sections 3 and 6).

Material is stored by its upstream content digest under ``<cache_dir>/tasks/<hex>``
and checked against a second digest of the local files (``tree_digest``): the
upstream identity and the unpacked material are separate facts and never swapped.

Inspection reads ``task.toml`` without Harbor: what the platform needs before
execution (resources, timeouts, environment kind, author parameters) and the
normalized preparation spec whose digest is the cache key.
"""

import hashlib
import math
import os
import re
import shutil
import stat
import subprocess
import tempfile
import tomllib
from pathlib import Path

from maestro.boundaries.dataset_source import (
    MISMATCH,
    NOT_FOUND,
    UNSUPPORTED,
    FetchedTask,
    SourceError,
    SourceTask,
    SourceVersion,
)
from maestro.core.digests import digest_json

DEFAULT_CPUS = 1
DEFAULT_MEMORY_MB = 2048
INSTRUCTION_CHARS = 4000
# Default upper bound for a task's own build_timeout_sec (``build_timeout_max_sec`` in
# config.toml). The design names no build limit (14 section 5), and Harbor's default is
# 600 s; an hour covers large images while one build cannot hold a restore slot for longer.
MAX_BUILD_TIMEOUT = 3600.0

# How the platform prepares an environment. A change here is a new preparation
# method and needs a new admission (02 section 5).
PREPARATION_METHOD = {
    "adapter": "maestro-docker-prep/1",
    "environment_abi_version": "1",
    # Reproducible build settings (M1 TECH-03): fixed timestamps, no provenance.
    "build": {"provenance": False, "source_date_epoch": 0, "rewrite_timestamp": True},
}
PREPARATION_METHOD_DIGEST = digest_json(PREPARATION_METHOD)

_MATERIAL_NAME = re.compile(r"[0-9a-f]{64}")
_TEMPLATE = re.compile(r"\$\{([^}:]+)(?::-(.*))?\}")
_SENSITIVE = re.compile(r"(KEY|SECRET|TOKEN(?!S)|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE)
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_COMPOSE_FILES = {"docker-compose.yaml", "docker-compose.yml", "compose.yaml", "compose.yml"}
# Variables Harbor's Docker environment fills in itself.
_INFRA = {
    "MAIN_IMAGE_NAME",
    "PREBUILT_IMAGE_NAME",
    "CONTEXT_DIR",
    "CPUS",
    "MEMORY",
    "GPUS",
    "SHM_SIZE",
    "TRIAL_ID",
    "SESSION_ID",
    "HOST_VERIFIER_LOGS_PATH",
    "HOST_AGENT_LOGS_PATH",
    "HOST_ARTIFACTS_PATH",
    "ENV_VERIFIER_LOGS_PATH",
    "ENV_AGENT_LOGS_PATH",
    "ENV_ARTIFACTS_PATH",
}


def tree_digest(root: Path) -> str:
    """Names, contents and executable bits; links and special files are rejected.

    Every entry is length-framed (name length, name, kind, executable bits, content
    length, content), so no two different trees feed the hash the same bytes. Files
    are read in chunks: task content can be large."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f"symlinks are unsupported in task content: {relative}")
        mode = path.stat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError(f"special files are unsupported in task content: {relative}")
        name = os.fsencode(relative)
        kind = b"f" if stat.S_ISREG(mode) else b"d"
        digest.update(len(name).to_bytes(8, "big") + name + kind + bytes([mode & 0o111]))
        if kind == b"f":
            with path.open("rb") as handle:
                size = os.fstat(handle.fileno()).st_size
                digest.update(size.to_bytes(8, "big"))
                remaining = size
                while remaining:
                    chunk = handle.read(min(remaining, 1 << 20))
                    if not chunk:
                        raise ValueError(f"file changed while it was read: {relative}")
                    digest.update(chunk)
                    remaining -= len(chunk)
    return "sha256:" + digest.hexdigest()


def build_timeout(value, cap: float = MAX_BUILD_TIMEOUT) -> float | None:
    """The author's build time limit when it is usable, else None (the platform default
    applies). A build holds one of the few restore slots for as long as it runs, so a
    task may not ask for ``inf`` or for days: the limit is capped at ``cap``."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return min(float(value), cap)


def _hex(content_digest: str) -> str | None:
    algorithm, _, value = content_digest.partition(":")
    if algorithm != "sha256" or len(value) != 64 or not value.isalnum():
        return None
    return value.lower()


class TaskMaterials:
    def __init__(self, cache_dir: Path):
        self.root = cache_dir / "tasks"

    def staging(self) -> Path:
        """A fresh directory on the cache filesystem for one fetch."""
        self.root.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=".fetch-", dir=self.root))

    def path_for(self, content_digest: str) -> Path | None:
        value = _hex(content_digest)
        if value is None:
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

    def verified(self, content_digest: str, material_digest: str) -> Path | None:
        """The local copy, only if its files still match the recorded digest."""
        path = self.path_for(content_digest)
        if path is None:
            return None
        try:
            return path if tree_digest(path) == material_digest else None
        except (OSError, ValueError):
            return None

    def install(self, source: Path, content_digest: str, expected_material: str | None = None):
        """Copy a fetched task in under its upstream digest and return the material
        digest. A differing copy already in place is replaced by one rename."""
        value = _hex(content_digest)
        if value is None:
            raise SourceError(UNSUPPORTED, f"unsupported content digest {content_digest!r}")
        try:
            material = tree_digest(source)
        except ValueError as error:
            raise SourceError(UNSUPPORTED, str(error)) from None
        if expected_material and material != expected_material:
            raise SourceError(
                MISMATCH,
                "Task files differ from the recorded material digest",
                {"expected_digest": expected_material, "actual_digest": material},
            )
        target = self.root / value
        if self.verified(content_digest, material):
            return material
        self.root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".install-", dir=self.root))
        try:
            copy = staging / "task"
            shutil.copytree(source, copy, symlinks=True)
            if tree_digest(copy) != material:
                raise SourceError(MISMATCH, "task content changed while it was being copied")
            try:
                if target.exists():
                    os.rename(target, staging / "old")
                os.rename(copy, target)
            except OSError:
                # A concurrent install of the same digest (a double-clicked import)
                # got there first. If what it left is this very content, we are done.
                if self.verified(content_digest, material):
                    return material
                raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return material

    def sweep(self, referenced: set[str]) -> list[str]:
        """Start-up reconciliation, before any install can run: remove what a crash left
        (``.fetch-*``, ``.install-*``, ``.remove-*``) and material no task row refers
        to (a failed import copied it in). Material a task refers to stays."""
        if not self.root.is_dir():
            return []
        keep = {_hex(digest) for digest in referenced}
        removed = []
        for path in sorted(self.root.iterdir()):
            leftover = path.name.startswith((".fetch-", ".install-", ".remove-"))
            orphan = _MATERIAL_NAME.fullmatch(path.name) and path.name not in keep
            if (leftover or orphan) and path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
                removed.append(path.name)
        return removed


# --- inspection -------------------------------------------------------------------


def _env_maps(value, where=""):
    """Every ``env`` table of task.toml with its location, metadata excluded."""
    if isinstance(value, dict):
        for name, child in value.items():
            if name in {"metadata", "task"}:
                continue
            path = f"{where}.{name}" if where else name
            if name == "env" and isinstance(child, dict):
                yield path, child
            else:
                yield from _env_maps(child, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _env_maps(child, f"{where}[{index}]")


def _compose_variables(file: Path) -> list[tuple[str, bool, str]]:
    """``docker compose config --variables`` with an empty env file and environment.
    Only the client parses the file; nothing is started."""
    result = subprocess.run(
        ["docker", "compose", "--env-file", "/dev/null", "-f", str(file), "config", "--variables"],
        cwd=file.parent,
        env={"PATH": os.defpath + ":/usr/local/bin", "HOME": "/nonexistent"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    lines = result.stdout.splitlines()
    if result.returncode or not lines or not lines[0].startswith("NAME"):
        raise ValueError("compose variable discovery failed")
    header = lines[0]
    required_at = header.index("REQUIRED")
    default_at = header.index("DEFAULT VALUE")
    alternate_at = header.index("ALTERNATE VALUE")
    output = []
    for line in lines[1:]:
        name = line[:required_at].strip()
        required = line[required_at:default_at].strip()
        if not _NAME.fullmatch(name) or required not in {"true", "false"}:
            raise ValueError("unsupported compose variable line")
        output.append((name, required == "true", line[default_at:alternate_at].strip()))
    return output


def _parameters(config: dict, task_dir: Path) -> tuple[list[dict], list[dict]]:
    """Author parameters (03): environment-variable templates in task.toml and the
    variables of author compose files."""
    found: dict[str, dict] = {}
    issues: list[dict] = []

    def add(name: str, default: str | None, required: bool, used_in: str) -> None:
        entry = found.setdefault(
            name,
            {
                "name": name,
                "default": default,
                "required": required,
                "sensitive": bool(_SENSITIVE.search(name)),
                "description": "",
                "hard_constraints": {},
                "used_in": [],
            },
        )
        entry["required"] = entry["required"] or required
        if entry["default"] is None:
            entry["default"] = default
        elif default is not None and default != entry["default"]:
            issues.append({"code": "CONFLICTING_DEFAULTS", "name": name})
        entry["used_in"].append(used_in)

    for where, mapping in _env_maps(config):
        for value in mapping.values():
            match = _TEMPLATE.fullmatch(value) if isinstance(value, str) else None
            if match:
                add(match.group(1), match.group(2), match.group(2) is None, where)
    for file in sorted(task_dir.rglob("*")):
        if file.name not in _COMPOSE_FILES or not file.is_file():
            continue
        relative = file.relative_to(task_dir).as_posix()
        try:
            variables = _compose_variables(file)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            issues.append({"code": "COMPOSE_DISCOVERY_FAILED", "file": relative})
            continue
        for name, required, default in variables:
            if name in _INFRA or name.startswith("EGRESS_CONTROL_"):
                continue
            add(name, default or None, required, relative)
    return sorted(found.values(), key=lambda p: p["name"]), issues


def inspect_task(
    task_dir: Path,
    content_digest: str,
    material_digest: str,
    build_timeout_max: float = MAX_BUILD_TIMEOUT,
) -> dict:
    """The task definition the platform stores (02 section 3 step 3). The build limit it
    records is the task's own, capped at ``build_timeout_max``."""
    try:
        config = tomllib.loads((task_dir / "task.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        raise SourceError(UNSUPPORTED, f"task.toml cannot be read: {error}") from None
    environment = config.get("environment") or {}
    unsupported = []
    if environment.get("gpus"):
        unsupported.append("gpus")  # O-09: no GPU in the first release
    if (config.get("verifier") or {}).get("environment"):
        unsupported.append("separate_verifier_environment")
    steps = config.get("steps") or []
    if any(isinstance(step, dict) and step.get("environment") for step in steps):
        unsupported.append("step_environments")
    env_dir = task_dir / "environment"
    image = environment.get("docker_image")
    if image:
        kind = "image"
    elif (env_dir / "Dockerfile").is_file():
        kind = "build"
    else:
        kind = None
        unsupported.append("no_environment_definition")
    parameters, issues = _parameters(config, task_dir)
    build_limit = build_timeout(environment.get("build_timeout_sec"), build_timeout_max)
    instruction = task_dir / "instruction.md"
    definition = {
        "instruction": (
            instruction.read_text(errors="replace")[:INSTRUCTION_CHARS]
            if instruction.is_file()
            else ""
        ),
        "resources": {
            "cpus": environment.get("cpus") or DEFAULT_CPUS,
            "memory_mb": environment.get("memory_mb") or DEFAULT_MEMORY_MB,
            "storage_mb": environment.get("storage_mb"),
            # Author resource values are suggestions unless stated otherwise (02 section 3).
            "constraint_strength": "unknown",
        },
        "timeouts": {
            "agent_sec": (config.get("agent") or {}).get("timeout_sec"),
            "verifier_sec": (config.get("verifier") or {}).get("timeout_sec"),
            "build_sec": build_limit,
        },
        "network": {
            "allow_internet": environment.get("allow_internet"),
            "network_mode": environment.get("network_mode"),
        },
        "has_solution": (task_dir / "solution" / "solve.sh").is_file(),
        "parameters": parameters,
        "parameter_issues": issues,
        "unsupported": unsupported,
    }
    spec = {
        "schema_version": 1,
        "task_content_digest": content_digest,
        "materialization_digest": material_digest,
        "environment": {
            "kind": kind,
            "docker_image": image,
            "definition_digest": tree_digest(env_dir) if env_dir.is_dir() else None,
            "build_timeout_sec": build_limit,
        },
        "preparation_parameters": {},
        "preparation_method_digest": PREPARATION_METHOD_DIGEST,
        "environment_abi_version": PREPARATION_METHOD["environment_abi_version"],
    }
    definition["preparation"] = {"spec": spec, "spec_digest": digest_json(spec)}
    return definition


def configuration_blockers(definition: dict) -> list[dict]:
    """Required configuration the platform cannot supply yet. Values for author
    parameters arrive with run configuration (M5); until then a required parameter
    without a default blocks submission and names what is missing."""
    missing = [
        p["name"]
        for p in definition.get("parameters") or []
        if p["default"] is None and (p["required"] or p["sensitive"])
    ]
    blockers = []
    if missing:
        blockers.append({"code": "CONFIG_REQUIRED_MISSING", "parameters": missing})
    if definition.get("parameter_issues"):
        blockers.append(
            {"code": "AUTHOR_PARAMETERS_UNRESOLVED", "issues": definition["parameter_issues"]}
        )
    return blockers


class LocalTaskSource:
    """Every subdirectory with a ``task.toml`` is one task; the version digest is the
    digest of the task list. Development and tests only."""

    kind = "local"

    def __init__(self, root: Path):
        self.root = root

    def _tasks(self) -> list[SourceTask]:
        return [
            SourceTask(task_dir.name, tree_digest(task_dir), {"path": str(task_dir)})
            for task_dir in sorted(p for p in self.root.iterdir() if (p / "task.toml").is_file())
        ]

    async def search(self, query: str, credential: str | None) -> list[dict]:
        return []

    async def list_versions(self, namespace: str, name: str, credential: str | None) -> list:
        return []

    async def describe(self, namespace: str, name: str, ref: str, credential: str | None):
        tasks = self._tasks() if self.root.is_dir() else []
        if not tasks:
            raise SourceError(NOT_FOUND, f"no task directories under {self.root}")
        resolved = digest_json([[t.task_key, t.content_digest] for t in tasks])
        if ref.startswith("sha256:") and ref != resolved:
            raise SourceError(NOT_FOUND, "local tasks no longer match this digest")
        return SourceVersion(
            namespace=namespace,
            name=name,
            upstream_ref=ref,
            ref_kind="digest" if ref.startswith("sha256:") else "tag",
            resolved_digest=resolved,
            tasks=tuple(tasks),
            description=f"Local tasks from {self.root.name}",
        )

    async def fetch(self, task: SourceTask, destination: Path, credential: str | None):
        source = Path(task.locator["path"])
        if not source.is_dir() or tree_digest(source) != task.content_digest:
            raise SourceError(NOT_FOUND, f"local task {task.task_key} changed or is gone")
        shutil.copytree(source, destination, symlinks=True)
        return FetchedTask(destination, task.content_digest)
