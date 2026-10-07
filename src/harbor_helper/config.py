import re
from urllib.parse import urlparse

from harbor_helper.storage import read_json

HARBOR_VERSION = "0.23.0"
DEFAULT = {
    "dataset": "au12321ua/cad-bench@2",
    "runtime_image": "cad-bench/cad-runtime:cff490d90b2410ad29e2",
    "max_jobs": 1,
    "max_trials": 1,
    "max_attempts": 3,
    "max_wall_seconds": 3600,
    "max_cpus_per_trial": 2,
    "max_memory_mb_per_trial": 4096,
    "presets": {
        "default": {"agent": "oracle", "attempts": 1, "concurrency": 1, "wall_seconds": 1800},
        "model": {"agent": "opencode", "attempts": 1, "concurrency": 1, "wall_seconds": 1800},
    },
    "model": None,
}


def reject_secrets(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if re.search(r"(password|secret|token|api.?key|authorization)", k, re.IGNORECASE):
                raise ValueError(f"Literal credentials are forbidden in configuration: {k}")
            reject_secrets(v)
    elif isinstance(value, list):
        for v in value:
            reject_secrets(v)
    elif isinstance(value, str):
        if re.search(r"sk-(?:proj-)?[A-Za-z0-9_-]{16,}", value):
            raise ValueError("Credential-like value forbidden in snapshot")
        if "://" in value:
            url = urlparse(value)
            if url.username or url.password or url.query:
                raise ValueError("URL credentials/query forbidden; use runtime environment")


def load_team(store):
    team = read_json(store.root / "team.json")
    reject_secrets(team)
    unknown = set(team) - set(DEFAULT)
    if unknown:
        raise ValueError(f"Unknown team options: {sorted(unknown)}")
    for key in (
        "max_jobs",
        "max_trials",
        "max_attempts",
        "max_wall_seconds",
        "max_cpus_per_trial",
        "max_memory_mb_per_trial",
    ):
        if type(team.get(key)) is not int or team[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    return team


def effective(team, args):
    preset = args.preset
    if preset not in team["presets"]:
        raise ValueError(f"Unknown preset: {preset}")
    cfg = dict(team["presets"][preset])
    if set(cfg) - {"agent", "attempts", "concurrency", "wall_seconds"}:
        raise ValueError("Unknown preset option")
    cfg.update(
        dataset=team["dataset"],
        model=team["model"],
        runtime_image=team["runtime_image"],
        max_cpus_per_trial=team["max_cpus_per_trial"],
        max_memory_mb_per_trial=team["max_memory_mb_per_trial"],
    )
    for k in ("agent", "attempts", "concurrency", "wall_seconds", "dataset"):
        if getattr(args, k, None) is not None:
            cfg[k] = getattr(args, k)
    cfg["task_filter"] = getattr(args, "task", None)
    validate_effective(team, cfg)
    return cfg


def validate_effective(team, cfg):
    for key, limit in (
        ("attempts", "max_attempts"),
        ("concurrency", "max_trials"),
        ("wall_seconds", "max_wall_seconds"),
    ):
        if type(cfg[key]) is not int or not 1 <= cfg[key] <= team[limit]:
            raise ValueError(f"{key} must be between 1 and {team[limit]}")
    if cfg["agent"] not in {"oracle", "opencode"}:
        raise ValueError("Supported agents: oracle, opencode")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+@(?:[1-9][0-9]*|sha256:[0-9a-f]{64})", cfg["dataset"]):
        raise ValueError("Dataset must be a package pinned to numeric revision or sha256 digest")
    if cfg["agent"] == "opencode":
        model = cfg["model"]
        if not model:
            raise ValueError("Model not configured: maintainer must set model in team.json")
        if set(model) - {
            "endpoint",
            "name",
            "declared_version",
            "credential_env",
            "opencode_version",
        }:
            raise ValueError("Unknown model option")
        url = urlparse(model.get("endpoint", ""))
        if url.scheme not in {"http", "https"} or not url.hostname:
            raise ValueError("Set the maintainer's vLLM http(s) endpoint")
        if not model.get("name") or not model.get("opencode_version"):
            raise ValueError("Set model.name and fixed model.opencode_version")
        key = model.get("credential_env")
        if key and (key != "VLLM_API_KEY"):
            raise ValueError("Use explicit VLLM_API_KEY runtime credential reference")
    reject_secrets(cfg)
