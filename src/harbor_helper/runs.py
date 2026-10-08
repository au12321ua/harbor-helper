import asyncio
import importlib.metadata
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from copy import deepcopy
from pathlib import Path

from harbor.models.job.config import JobConfig

from harbor_helper.config import DEFAULT, HARBOR_VERSION, reject_secrets, validate_effective
from harbor_helper.sources import resolve_dataset, verify_inputs
from harbor_helper.storage import read_json, tree_digest, write_json


def image_identity(reference):
    r = subprocess.run(
        ["docker", "image", "inspect", reference, "--format", "{{.Id}}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode:
        raise ValueError("Runtime image unavailable: load/build the configured image first")
    return r.stdout.strip()


def check_bundle(path):
    allowed = {"skills", "sdk", "config", "bootstrap.sh"}
    if {p.name for p in path.iterdir()} - allowed:
        raise ValueError("Bundle supports skills/, sdk/, config/opencode.json, bootstrap.sh")
    tree_digest(path)
    config_dir = path / "config"
    if config_dir.exists() and {p.name for p in config_dir.iterdir()} - {"opencode.json"}:
        raise ValueError("Bundle config supports opencode.json only")
    cfg = config_dir / "opencode.json"
    if cfg.exists():
        reject_secrets(read_json(cfg))
    for p in path.rglob("*"):
        if p.is_file() and (
            p.name.startswith(".env")
            or any(s in p.name.lower() for s in ("secret", "credential", ".pem"))
        ):
            raise ValueError("Credential files cannot be bundled")


def job_config(run_dir, manifest):
    cfg = manifest["effective"]
    agent = {"name": cfg["agent"], "kwargs": {}, "skills": []}
    if manifest["bundle_digest"]:
        agent.pop("name")
        agent["import_path"] = "harbor_helper.agents:" + (
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
            agent["import_path"] = "harbor_helper.agents:HelperOpenCode"
        model = cfg["model"]
        agent["model_name"] = "vllm/" + model["name"]
        agent["kwargs"]["version"] = model["opencode_version"]
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
            "retry": {"max_retries": 0},
            "environment": {
                "type": "docker",
                "delete": True,
                "override_cpus": cfg["max_cpus_per_trial"],
                "override_memory_mb": cfg["max_memory_mb_per_trial"],
                "env": {
                    k: manifest["image_alias"]
                    for k in cfg.get("runtime_image_env", DEFAULT["runtime_image_env"])
                },
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
    service=None,
    run_id=None,
    start_supervisor=True,
):
    from harbor_helper.auth import Auth

    if parent and (service is None or cfg is None):
        cfg = read_json(store.path(parent) / "manifest.json")["effective"]
    validate_effective(team, cfg)
    session = None
    if cfg["agent"] == "opencode" and service is None:
        session, _ = Auth(store.root).execution(cfg["model"]["endpoint"])

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
            if service is None:
                cfg = old["effective"]
            validate_effective(team, cfg)
            for name in ("tasks", "bundle"):
                if (old_path / name).exists():
                    shutil.copytree(old_path / name, path / name)
            source, digest, image = old["source"], old["bundle_digest"], old["image_id"]
            if image_identity(image) != image:
                raise ValueError("Fixed runtime image unavailable")
        else:
            validate_effective(team, cfg)
            source = asyncio.run(
                resolve_dataset(cfg["dataset"], path / "tasks", cfg["task_filter"])
            )
            digest = None
            if bundle:
                bundle = Path(bundle).expanduser().resolve()
                check_bundle(bundle)
                shutil.copytree(bundle, path / "bundle")
                digest = tree_digest(path / "bundle")
            image = image_identity(cfg["runtime_image"])
        alias = "harbor-helper/runtime:" + image.removeprefix("sha256:")
        subprocess.run(["docker", "tag", image, alias], check=True, timeout=30)
        manifest = {
            "run_id": run_id,
            "parent": parent,
            "created": time.time(),
            "effective": cfg,
            "source": source,
            "bundle_digest": digest,
            "image_id": image,
            "image_alias": alias,
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
        if service is not None:
            manifest["service"] = service
        verify_inputs(path, manifest)
        write_json(path / "manifest.json", manifest)
        write_json(path / "job.json", job_config(path, manifest))
        if session:
            Auth(store.root).bind(run_id, session["id"])

        def publish():
            if service is not None:
                from harbor_helper.service_data import ServiceData

                if not ServiceData(store.root).allow_publish(service["submission_id"]):
                    raise ValueError("Submission cancelled before queue publication")
            with store.connect() as db:
                db.execute(
                    "INSERT INTO runs(id,status,created,concurrency,parent) VALUES(?,?,?,?,?)",
                    (run_id, "queued", time.time(), cfg["concurrency"], parent),
                )

        # Network preparation above is deliberately outside the shared queue lock.
        # The local CLI already holds this lock; do not acquire a second flock.
        if service is not None:
            with store.control():
                publish()
        else:
            publish()
    except BaseException:
        shutil.rmtree(path)
        raise
    if start_supervisor:
        ensure_supervisor(store)
    return {
        "run_id": run_id,
        "state": str(store.root),
        "status_command": f"harbor-helper --state {store.root} status {run_id}",
    }


def safe_environment():
    # Never inherit arbitrary provider keys or search neighboring secrets.
    keep = {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
    }
    from harbor_helper.credentials import KEY_ENV, LEGACY_KEY_ENV

    return {k: v for k, v in os.environ.items() if k in keep or k in {KEY_ENV, LEGACY_KEY_ENV}}


def scheduler_identity(store):
    from harbor_helper.worker import process_birth

    path = store.root / "scheduler.json"
    if path.exists():
        identity = read_json(path)
        if identity.get("birth") and process_birth(identity["pid"]) == identity["birth"]:
            return identity
    return None


def stop_supervisor(store, timeout=10):
    from harbor_helper.storage import TERMINAL
    from harbor_helper.worker import process_birth

    if any(row["status"] not in TERMINAL for row in store.runs()):
        raise ValueError("Only stop idle scheduler; cancel/wait for all tasks first")
    if (store.root / "service.json").exists():
        with store.connect() as db:
            if db.execute("SELECT 1 FROM submissions WHERE status='preparing' LIMIT 1").fetchone():
                raise ValueError("Input preparation active; wait before stopping scheduler")
    identity = scheduler_identity(store)
    if identity:
        try:
            os.kill(identity["pid"], 15)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + timeout
        while process_birth(identity["pid"]) == identity["birth"]:
            if time.monotonic() >= deadline:
                raise ValueError("Scheduler stop timed out; original PID/birth still active")
            time.sleep(0.05)
        if scheduler_identity(store):
            raise ValueError("Another scheduler is active; stop not confirmed")
    return {"scheduler": "stopped", "confirmed": True}


def ensure_supervisor(store):
    if scheduler_identity(store):
        return
    environment = safe_environment()
    if (store.root / "service.json").exists():
        from harbor_helper.credentials import KEY_ENV, LEGACY_KEY_ENV

        environment.pop(KEY_ENV, None)
        environment.pop(LEGACY_KEY_ENV, None)
    with (store.root / "supervisor.log").open("a") as log:
        subprocess.Popen(
            [sys.executable, "-m", "harbor_helper.worker", "supervise", str(store.root)],
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
