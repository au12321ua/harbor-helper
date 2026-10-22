"""Deployment configuration from ``config.toml`` (12 section 3).

Business defaults, quotas and policies live in the database; this file only holds
what must be known before the database opens.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from maestro.core.errors import MaestroError

DEFAULT_CONFIG = Path("/etc/maestro/config.toml")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    cache_dir: Path
    master_key_dir: Path
    listen_host: str = "127.0.0.1"
    listen_port: int = 8420
    root_path: str = ""
    cookie_secure: bool = True
    session_hours: int = 12
    # Execution capacity: concurrent trial slots, and CPU / memory totals for trial
    # containers (0 = the whole host). Runs reserve concurrency x per-trial resources.
    worker_slots: int = 10
    execution_cpus: float = 0
    execution_memory_mb: int = 0
    # Python of the separate Runner environment (locked Harbor); empty disables execution.
    runner_python: Path | None = None
    runner_term_grace_sec: float = 30
    cleanup_timeout_sec: float = 120

    @property
    def database(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def work_dir(self) -> Path:
        """Runner working directories: transient Harbor output until artifacts are stored."""
        return self.data_dir / "work"

    @property
    def lock_file(self) -> Path:
        return self.data_dir / "maestro.lock"

    @property
    def setup_token_file(self) -> Path:
        return self.data_dir / "setup-token"

    def check(self) -> "Settings":
        if self.runner_python is not None and not self.runner_python.is_absolute():
            raise MaestroError("CONFIG_INVALID", "runner_python must be an absolute path", 500)
        for name in ("data_dir", "cache_dir", "master_key_dir"):
            if not getattr(self, name).is_absolute():
                raise MaestroError("CONFIG_INVALID", f"{name} must be an absolute path", 500)
        data = self.data_dir.resolve()
        keys = self.master_key_dir.resolve()
        if keys.is_relative_to(data) or data.is_relative_to(keys):
            # Backups copy data_dir; the master key must travel separately (O-08).
            raise MaestroError("CONFIG_INVALID", "master_key_dir must be outside data_dir", 500)
        return self


def load(path: Path | None = None) -> Settings:
    path = path or DEFAULT_CONFIG
    try:
        raw = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise MaestroError("CONFIG_INVALID", f"Cannot read {path}: {error}", 500) from None
    known = set(Settings.__dataclass_fields__)
    unknown = set(raw) - known
    if unknown:
        raise MaestroError("CONFIG_INVALID", f"Unknown settings: {sorted(unknown)}", 500)
    values = dict(raw)
    for name in ("data_dir", "cache_dir", "master_key_dir", "runner_python"):
        if values.get(name):
            values[name] = Path(values[name])
        elif name == "runner_python":
            values.pop(name, None)
    try:
        return Settings(**values).check()
    except TypeError as error:
        raise MaestroError("CONFIG_INVALID", str(error), 500) from None
