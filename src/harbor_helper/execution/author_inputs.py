"""Discover non-secret external author inputs from verified task snapshots.

Compose discovery runs only the client config command in a clean environment.
Nothing here starts containers, changes author files, or mutates host variables.
"""

import os
import re
import subprocess
import tomllib

import yaml
from harbor.environments.docker.compose_env import ComposeInfraEnvVars, legacy_log_mount_env_vars
from harbor.models.task.config import TaskConfig
from harbor.utils.env import get_required_host_vars, is_env_template, is_sensitive_env_key

from harbor_helper.execution.config import reject_secrets
from harbor_helper.persistence.files import tree_digest

NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
INFRA = {
    "MAIN_IMAGE_NAME",
    "CONTEXT_DIR",
    "CPUS",
    "MEMORY",
    "GPUS",
    "SHM_SIZE",
    "TRIAL_ID",
    "SESSION_ID",
    "HOST",
    "HOSTNAME",
    "USER",
    "UID",
    "GID",
    "HOME",
    "PATH",
    "PWD",
    "SHELL",
    "PYTHONPATH",
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "COMPOSE_PROJECT_NAME",
    "COMPOSE_FILE",
}
INFRA.update(name.upper() for name in ComposeInfraEnvVars.model_fields)
INFRA.update(
    legacy_log_mount_env_vars(
        [
            {"type": "bind", "source": "/unused", "target": "/logs/" + role}
            for role in ("agent", "verifier", "artifacts")
        ],
        host_value="source",
    )
)
RESERVED = re.compile(
    r"(SECRET|PASSWORD|TOKEN|API_?KEY|CREDENTIAL|PROXY)|(?:^|_)(KEY|AUTH|AUTHORIZATION)(?:_|$)|"
    r"^(EGRESS_CONTROL_|HARBOR_|HH_|XDG_|AWS_|AZURE_|GOOGLE_|OPENAI_|VLLM_|"
    r"OPENCODE_|COMPOSE_|DOCKER_|LD_|PYTHON|NPM_|NODE_|UV_)"
)


class AuthorInputError(ValueError):
    code = "author_input_missing"

    def __init__(self, issues):
        self.issues = issues
        super().__init__(
            "作者运行输入未满足；管理员在数据集页检查作者参数："
            + "; ".join(
                f"{item['task']}: {', '.join(item['variables'])} ({item['reason']})"
                for item in issues
            )
        )


class AuthorDiscoveryError(AuthorInputError):
    code = "author_input_discovery"


def permitted(name):
    return bool(
        NAME.fullmatch(name)
        and name not in INFRA
        and not RESERVED.search(name)
        and not is_sensitive_env_key(name)
    )


def validate_values(values, names=None):
    if not isinstance(values, dict) or len(values) > 128:
        raise ValueError("Author inputs must be a bounded non-secret object")
    for name, value in values.items():
        if not permitted(name) or (names is not None and name not in names):
            raise ValueError("Author input name is not in the discovered whitelist")
        if not isinstance(value, str) or len(value) > 1024 or any(ord(c) < 32 for c in value):
            raise ValueError("Author input values must be single-line text up to 1024 characters")
    reject_secrets(values)


def env_maps(value):
    if isinstance(value, dict):
        for name, child in value.items():
            if name in {"metadata", "task"}:
                continue
            if name == "env" and isinstance(child, dict):
                yield child
            else:
                yield from env_maps(child)
    elif isinstance(value, list):
        for child in value:
            yield from env_maps(child)


def compose_variables(file):
    # Explicit empty env file avoids user/project .env. Output is never logged.
    result = subprocess.run(
        ["docker", "compose", "--env-file", "/dev/null", "-f", str(file), "config", "--variables"],
        cwd=file.parent,
        env={"PATH": os.defpath + ":/usr/local/bin", "HOME": "/nonexistent"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise ValueError("Author Compose input discovery unavailable")
    lines = result.stdout.splitlines()
    if not lines or not lines[0].startswith("NAME"):
        raise ValueError("Unsupported Compose variables output")
    # Compose uses aligned columns; defaults can contain spaces.
    header = lines[0]
    required_pos = header.index("REQUIRED")
    default_pos = header.index("DEFAULT VALUE")
    alternate_pos = header.index("ALTERNATE VALUE")
    output = []
    for line in lines[1:]:
        name = line[:required_pos].strip()
        required = line[required_pos:default_pos].strip()
        if not NAME.fullmatch(name) or required not in {"true", "false"}:
            raise ValueError("Unsupported Compose variable definition")
        output.append((name, required == "true", line[default_pos:alternate_pos].strip()))
    return output


def prebuilt_images(config, label):
    observations = []
    scopes = [("agent", config["environment"])]
    if config["verifier"].get("environment"):
        scopes.append(("verifier", config["verifier"]["environment"]))
    for step in config.get("steps") or []:
        if step.get("environment"):
            scopes.append(("step:" + step["name"], step["environment"]))
        if (step.get("verifier") or {}).get("environment"):
            scopes.append(("step-verifier:" + step["name"], step["verifier"]["environment"]))
    for role, environment in scopes:
        image = environment.get("docker_image")
        if not image or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@-]{0,255}", image):
            continue
        cached = None
        identity = None
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
                env={"PATH": os.defpath + ":/usr/local/bin", "HOME": "/nonexistent"},
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0 and re.fullmatch(
                r"sha256:[a-f0-9]{64}", result.stdout.strip()
            ):
                cached, identity = True, result.stdout.strip()
            elif "No such image" in result.stderr:
                cached = False
        except (OSError, subprocess.TimeoutExpired):
            pass
        observations.append(
            {
                "task": label,
                "role": role,
                "reference": image,
                "cached": cached,
                "image_id": identity,
            }
        )
    return observations


def discover(tasks_dir, source):
    definitions, blocked, budgets, fixed_names, images = {}, [], [], set(), []
    for task in source["tasks"]:
        root = tasks_dir / task["directory"]
        if tree_digest(root) != task["snapshot_digest"]:
            raise ValueError("Fixed task snapshot changed")
        label = task["package"]
        try:
            config = TaskConfig.model_validate(
                tomllib.loads((root / "task.toml").read_text())
            ).model_dump(mode="json")
        except (ValueError, OSError):
            raise AuthorDiscoveryError(
                [{"task": label, "variables": [], "reason": "task_schema_unsupported"}]
            ) from None
        images.extend(prebuilt_images(config, label))
        maps = list(env_maps(config))
        literals = {
            k
            for mapping in maps
            for k, v in mapping.items()
            if not isinstance(v, str) or not is_env_template(v)
        }
        fixed_names.update(literals)
        for mapping in maps:
            missing = [name for name, default in get_required_host_vars(mapping) if default is None]
            if missing:
                blocked.append(
                    {
                        "task": label,
                        "variables": sorted(set(missing)),
                        "reason": "host_template_unsupported",
                    }
                )
        budgets.append(
            {
                "task": label,
                "agent_seconds": config["agent"]["timeout_sec"],
                "verifier_seconds": config["verifier"]["timeout_sec"],
            }
        )
        # Authors can define Compose in environment/, tests/ or arbitrary step dirs.
        for file in sorted(root.rglob("*")):
            if (
                file.name
                not in {"docker-compose.yaml", "docker-compose.yml", "compose.yaml", "compose.yml"}
                or file.relative_to(root).parts[0] not in {"environment", "tests", "steps"}
                or not file.is_file()
            ):
                continue
            try:
                document = yaml.safe_load(file.read_text())
            except (yaml.YAMLError, OSError):
                raise AuthorDiscoveryError(
                    [{"task": label, "variables": [], "reason": "compose_discovery_failed"}]
                ) from None
            if not isinstance(document, dict) or not isinstance(document.get("services"), dict):
                raise AuthorDiscoveryError(
                    [{"task": label, "variables": [], "reason": "compose_discovery_failed"}]
                )
            try:
                variables = compose_variables(file)
            except (ValueError, OSError, subprocess.TimeoutExpired):
                raise AuthorDiscoveryError(
                    [{"task": label, "variables": [], "reason": "compose_discovery_failed"}]
                ) from None
            for name, required, default in variables:
                if name in literals or name in INFRA or name.startswith("EGRESS_CONTROL_"):
                    continue
                if not permitted(name):
                    if required:
                        blocked.append(
                            {
                                "task": label,
                                "variables": [name],
                                "reason": "reserved_input_unsupported",
                            }
                        )
                    continue
                # Validate defaults before exposing them. Never publish remote secret values.
                try:
                    validate_values({name: default})
                except ValueError:
                    blocked.append(
                        {"task": label, "variables": [name], "reason": "unsafe_default_unsupported"}
                    )
                    continue
                definitions.setdefault(name, []).append(
                    {
                        "task": label,
                        "file": file.relative_to(root).as_posix(),
                        "required": required,
                        "default": default,
                    }
                )
    return {
        "variables": definitions,
        "fixed_names": sorted(fixed_names),
        "blocked": blocked,
        "budgets": budgets,
        "images": images,
        "source": source["resolved"],
    }


def check_inputs(discovery, values):
    validate_values(values, discovery["variables"])
    issues = list(discovery["blocked"])
    conflicts = set(values) & set(discovery.get("fixed_names", [])) & set(discovery["variables"])
    if conflicts:
        issues.append(
            {
                "task": "selected tasks",
                "variables": sorted(conflicts),
                "reason": "author_literal_conflict_submit_separately",
            }
        )
    for name, uses in discovery["variables"].items():
        if values.get(name):
            continue
        defaults = {use["default"] for use in uses}
        if len(defaults) > 1:
            issues.append(
                {
                    "task": ", ".join(sorted({u["task"] for u in uses})),
                    "variables": [name],
                    "reason": "conflicting_defaults_submit_separately",
                }
            )
        for use in uses:
            if use["required"] and not values.get(name):
                issues.append({"task": use["task"], "variables": [name], "reason": "missing"})
    if issues:
        raise AuthorInputError(issues)
