import importlib.metadata
import math
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
import uuid
from copy import deepcopy
from pathlib import Path
from typing import cast

from harbor.models.job.config import JobConfig

from harbor_helper.execution.bundles import check_bundle
from harbor_helper.execution.config import (
    HARBOR_VERSION,
    validate_effective,
)
from harbor_helper.execution.processes import safe_environment
from harbor_helper.execution.sources import verify_inputs
from harbor_helper.persistence import statuses as lifecycle_status
from harbor_helper.persistence.files import read_json, tree_digest, write_json


def startup_policy(run_dir, manifest, *, verify_snapshot=False):
    """Describe frozen author budgets without changing or exporting author env values."""
    from harbor.models.task.config import TaskConfig

    multiplier = manifest["effective"].get("environment_build_timeout_multiplier", 1)
    tasks = []
    for task in manifest["source"]["tasks"]:
        try:
            if (
                verify_snapshot
                and tree_digest(run_dir / "tasks" / task["directory"]) != task["snapshot_digest"]
            ):
                raise ValueError("Fixed task snapshot changed")
            task_config = TaskConfig.model_validate(
                tomllib.loads((run_dir / "tasks" / task["directory"] / "task.toml").read_text())
            )
            base = task_config.environment.build_timeout_sec
            network = task_config.environment.network_mode.value
            if type(base) not in {int, float} or not math.isfinite(base) or base <= 0:
                raise ValueError("Unrecognized author startup budget")
            network = network if network in {"public", "no-network", "allowlist"} else "unknown"
            wait = base * multiplier
            tasks.append(
                {
                    "task": task["package"].split("/", 1)[-1],
                    "agent_seconds": task_config.agent.timeout_sec,
                    "verifier_seconds": task_config.verifier.timeout_sec,
                    "author_build_timeout_sec": base,
                    "start_wait_timeout_sec": wait
                    if math.isfinite(wait)
                    else "exceeds finite range",
                    "author_network_mode": network,
                }
            )
        except (ValueError, TypeError, KeyError, OSError):
            tasks.append(
                {
                    "task": task["package"].split("/", 1)[-1],
                    "author_build_timeout_sec": "unknown",
                    "start_wait_timeout_sec": "unknown",
                    "author_network_mode": "unknown",
                }
            )
    return {
        "multiplier": multiplier,
        "wall_seconds": manifest["effective"]["wall_seconds"],
        "scope": "Harbor environment.start (build/pull/up); agent setup and inference unchanged",
        "tasks": tasks,
    }


def detail_startup_policy(run_dir, manifest):
    """Enrich missing legacy budgets in memory from the parent's verified snapshot."""
    policy = manifest.get("startup_policy")
    if not policy:
        return startup_policy(run_dir, manifest, verify_snapshot=True)
    policy = deepcopy(policy)
    tasks = policy.get("tasks", [])
    if any("agent_seconds" not in task or "verifier_seconds" not in task for task in tasks):
        derived = {
            task["task"]: task
            for task in startup_policy(run_dir, manifest, verify_snapshot=True)["tasks"]
        }
        for task in tasks:
            budget = derived.get(task.get("task"), {})
            for field in ("agent_seconds", "verifier_seconds"):
                if field not in task:
                    task[field] = budget.get(field)
    return policy


def job_config(run_dir, manifest):
    cfg = manifest["effective"]
    agent = {"name": cfg["agent"], "kwargs": {}, "skills": []}
    if manifest["bundle_digest"]:
        agent.pop("name")
        agent["import_path"] = "harbor_helper.execution.agents:" + (
            "BundledOracle" if cfg["agent"] == "oracle" else "BundledOpenCode"
        )
        agent["kwargs"]["helper_bundle"] = str(run_dir / "bundle")
        if cfg["agent"] == "oracle":
            agent["kwargs"]["helper_tasks"] = {
                t["directory"]: str(run_dir / "tasks" / t["directory"])
                for t in manifest["source"]["tasks"]
            }
        skills = run_dir / "bundle" / "skills"
        if skills.exists():
            agent["skills"] = [str(p) for p in sorted(skills.iterdir()) if p.is_dir()]
    if cfg["agent"] == "opencode":
        if "name" in agent:
            agent.pop("name")
            agent["import_path"] = "harbor_helper.execution.agents:HelperOpenCode"
        model = cfg["model"]
        agent["model_name"] = "vllm/" + model["name"]
        agent["kwargs"]["version"] = model["opencode_version"]
        if cfg.get("agent_tool_preparation") == "offline-npm-binary-v1":
            agent["kwargs"]["helper_tool_cache"] = str(run_dir.parents[1] / "agent-tools")
        agent["extra_allowed_hosts"] = [
            __import__("urllib.parse", fromlist=["urlparse"]).urlparse(model["endpoint"]).hostname
        ]
        custom = {
            "enabled_providers": ["vllm"],
            "provider": {
                "vllm": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "Maintainer OpenAI-compatible service",
                    "options": {"baseURL": model["endpoint"]},
                    "models": {
                        model["name"]: {
                            "name": model["name"],
                            "options": deepcopy(model.get("parameters", {})),
                        }
                    },
                }
            },
        }
        if model.get("credential_env"):
            custom["provider"]["vllm"]["options"]["apiKey"] = "{env:VLLM_API_KEY}"
            agent["env"] = {"VLLM_API_KEY": "${VLLM_API_KEY}"}
        bundle_cfg = run_dir / "bundle" / "config" / "opencode.json"
        if bundle_cfg.exists():
            from harbor.agents.installed.opencode import OpenCode

            custom = OpenCode._deep_merge(custom, read_json(bundle_cfg))
            # A bundle cannot redirect the maintainer's endpoint/model selection.
            if custom["provider"]["vllm"]["options"]["baseURL"] != model["endpoint"]:
                raise ValueError("Bundle cannot override model endpoint")
            if custom["provider"]["vllm"]["models"][model["name"]].get("options", {}) != model.get(
                "parameters", {}
            ):
                raise ValueError("Bundle cannot override frozen model parameters")
            custom["enabled_providers"] = ["vllm"]
        agent["kwargs"]["opencode_config"] = custom
    return JobConfig.model_validate(
        {
            "job_name": manifest["run_id"],
            "jobs_dir": str(run_dir / "harbor"),
            "n_attempts": cfg["attempts"],
            "n_concurrent_trials": cfg["concurrency"],
            "quiet": True,
            **(
                {
                    "environment_build_timeout_multiplier": cfg[
                        "environment_build_timeout_multiplier"
                    ]
                }
                if "environment_build_timeout_multiplier" in cfg
                else {}
            ),
            "retry": {"max_retries": 0},
            "environment": {
                "type": "docker",
                "import_path": "harbor_helper.execution.environments:NativeDockerEnvironment",
                "delete": True,
                "override_cpus": cfg["max_cpus_per_trial"],
                "override_memory_mb": cfg["max_memory_mb_per_trial"],
                "env": dict(cfg.get("author_env", {})),
            },
            "agents": [agent],
            "tasks": [
                {
                    "path": str(run_dir / "tasks" / t["directory"]),
                    "source": manifest["source"]["resolved"],
                }
                for t in manifest["source"]["tasks"]
            ],
        }
    ).model_dump(mode="json")


def submit(
    store,
    team,
    cfg=None,
    bundle=None,
    parent=None,
    *,
    service,
    run_id=None,
    start_supervisor=True,
):
    if parent and cfg is None:
        cfg = read_json(store.path(parent) / "manifest.json")["effective"]
    cfg = cast(dict, cfg)  # Frozen configuration is validated by validate_effective.
    validate_effective(team, cfg)

    if importlib.metadata.version("harbor") != HARBOR_VERSION:
        raise ValueError("Wrong Harbor version; install with uv sync --locked")
    run_id = run_id or "hh-" + uuid.uuid4().hex[:16]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("Invalid run identifier")
    path = store.root / "runs" / run_id
    path.mkdir(mode=0o700)
    try:
        if parent:
            old_path = store.path(parent)
            old = read_json(old_path / "manifest.json")
            verify_inputs(old_path, old)
            validate_effective(team, cfg)
            for name in ("tasks", "bundle"):
                if (old_path / name).exists():
                    shutil.copytree(old_path / name, path / name)
            if (path / "bundle").exists():
                check_bundle(path / "bundle")
            source, digest = old["source"], old["bundle_digest"]
        else:
            validate_effective(team, cfg)
            from harbor_helper.service.configuration import TeamConfiguration
            from harbor_helper.service.data import ServiceData
            from harbor_helper.service.sources import source_call

            config = TeamConfiguration(ServiceData(store))
            key = (
                config.hub_key(service["source_version"]) if service.get("source_version") else None
            )
            source = source_call(
                cfg["dataset"], key=key, target=path / "tasks", task=cfg["task_filter"]
            )
            digest = None
            if bundle:
                bundle = Path(bundle).expanduser().resolve()
                check_bundle(bundle)
                shutil.copytree(bundle, path / "bundle")
                check_bundle(path / "bundle")
                digest = tree_digest(path / "bundle")
                if service.get("bundle_digest") and service["bundle_digest"] != digest:
                    raise ValueError("Fixed bundle snapshot unavailable or changed")
        if service.get("author_input_check"):
            from harbor_helper.execution.author_inputs import (
                AuthorInputError,
                check_inputs,
                discover,
            )

            # Retain immutable source for recovery even when preparation yields no run.
            from harbor_helper.service.data import ServiceData

            with store.connect() as db:
                frozen = ServiceData(store).submission(service["submission_id"])["frozen"]
                frozen["effective"]["dataset"] = source["resolved"]
                frozen["service"]["input_source"] = source
                db.execute(
                    "UPDATE submissions SET frozen=? WHERE id=?",
                    (__import__("json").dumps(frozen), service["submission_id"]),
                )
            try:
                discovery = discover(path / "tasks", source)
                # Freeze only the whitelist consumed by this selected snapshot.
                values = {
                    k: v
                    for k, v in cfg.get("author_env", {}).items()
                    if k in discovery["variables"]
                }
                fixed = set(discovery["fixed_names"]) & set(values)
                if fixed:
                    raise AuthorInputError(
                        [
                            {
                                "task": "selected tasks",
                                "variables": sorted(fixed),
                                "reason": "author_literal_protected",
                            }
                        ]
                    )
                if (
                    not service.get("dataset_id")
                    and any(
                        use["required"] for uses in discovery["variables"].values() for use in uses
                    )
                    and not values
                ):
                    raise AuthorInputError(
                        [
                            {
                                "task": use["task"],
                                "variables": [name],
                                "reason": "dataset_registration_required",
                            }
                            for name, uses in discovery["variables"].items()
                            for use in uses
                            if use["required"]
                        ]
                    )
                check_inputs(discovery, values)
            except AuthorInputError as error:
                with store.connect() as db:
                    frozen["service"]["author_input_issues"] = error.issues
                    db.execute(
                        "UPDATE submissions SET frozen=? WHERE id=?",
                        (__import__("json").dumps(frozen), service["submission_id"]),
                    )
                raise
            cfg["author_env"] = values
            service.pop("author_input_issues", None)
            service["author_input_diagnostics"] = discovery
            if parent and "retry_changes" in service:
                old_env = old["effective"].get("author_env", {})
                service["retry_changes"].pop("author_env", None)
                if old_env != values:
                    service["retry_changes"]["author_env"] = {"old": old_env, "new": values}
            with store.connect() as db:
                frozen["effective"] = cfg
                frozen["service"] = service
                db.execute(
                    "UPDATE submissions SET frozen=? WHERE id=?",
                    (__import__("json").dumps(frozen), service["submission_id"]),
                )
        manifest = {
            "run_id": run_id,
            "parent": parent,
            "created": time.time(),
            "effective": cfg,
            "source": source,
            "bundle_digest": digest,
            "harbor_version": HARBOR_VERSION,
            "helper_version": importlib.metadata.version("harbor-helper"),
            "python": sys.executable,
            "model_checkpoint_actual": "unknown",
            "hard_budgets": {
                "wall_seconds": cfg["wall_seconds"],
                "attempts": cfg["attempts"],
                "tokens": "unsupported",
                "cost": "unsupported",
            },
        }
        manifest["service"] = service
        if "environment_build_timeout_multiplier" in cfg:
            manifest["startup_policy"] = startup_policy(path, manifest)
        verify_inputs(path, manifest)
        write_json(path / "manifest.json", manifest)
        write_json(path / "job.json", job_config(path, manifest))
        from harbor_helper.service.data import ServiceData

        # Network preparation above is deliberately outside the shared queue lock.
        with store.control():
            if not ServiceData(store.root).allow_publish(service["submission_id"]):
                raise ValueError("Submission cancelled before queue publication")
            with store.connect() as db:
                db.execute(
                    "INSERT INTO runs(id,status,created,concurrency,parent) VALUES(?,?,?,?,?)",
                    (run_id, lifecycle_status.QUEUED, time.time(), cfg["concurrency"], parent),
                )
    except BaseException:
        shutil.rmtree(path)
        raise
    if start_supervisor:
        ensure_supervisor(store)
    return {"run_id": run_id}


def scheduler_identity(store):
    from harbor_helper.execution.processes import process_birth

    path = store.root / "scheduler.json"
    if path.exists():
        identity = read_json(path)
        if identity.get("birth") and process_birth(identity["pid"]) == identity["birth"]:
            return identity
    return None


def stop_supervisor(store, timeout=10):
    from harbor_helper.execution.processes import process_birth

    with store.control():
        with store.connect() as db:
            if db.execute(
                "SELECT 1 FROM runs WHERE status IN ('queued','starting','running','cancelling','cleanup_blocked') LIMIT 1"
            ).fetchone():
                raise ValueError("Only stop idle scheduler; cancel/wait for all tasks first")
            if db.execute("SELECT 1 FROM submissions WHERE status='preparing' LIMIT 1").fetchone():
                raise ValueError("Input preparation active; wait before stopping scheduler")
        identity = scheduler_identity(store)
        if identity:
            write_json(store.root / "scheduler-stop.json", identity)
            try:
                os.kill(identity["pid"], 15)
            except ProcessLookupError:
                pass
    if identity:
        deadline = time.monotonic() + timeout
        while process_birth(identity["pid"]) == identity["birth"]:
            if time.monotonic() >= deadline:
                raise ValueError(
                    "Scheduler stop not confirmed; in-flight work or original PID/birth still active"
                )
            time.sleep(0.05)
        if scheduler_identity(store):
            raise ValueError("Another scheduler is active; stop not confirmed")
    return {"scheduler": "stopped", "confirmed": True}


def ensure_supervisor(store):
    identity = scheduler_identity(store)
    marker = store.root / "scheduler-stop.json"
    if (
        identity
        and marker.exists()
        and all(read_json(marker).get(k) == identity[k] for k in ("pid", "birth"))
    ):
        raise ValueError("Scheduler stopping; retry after shutdown completes")
    if identity:
        return
    environment = safe_environment()
    with (store.root / "supervisor.log").open("a") as log:
        subprocess.Popen(
            [sys.executable, "-m", "harbor_helper.execution.worker", "supervise", str(store.root)],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            close_fds=True,
            env=environment,
        )

    deadline = time.monotonic() + 10
    while not scheduler_identity(store):
        if time.monotonic() >= deadline:
            raise ValueError("Scheduler did not become ready; use recover and inspect diagnostics")
        time.sleep(0.05)
