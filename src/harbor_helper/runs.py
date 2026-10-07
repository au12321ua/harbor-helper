import asyncio
import importlib.metadata
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from harbor.models.job.config import JobConfig

from harbor_helper.config import HARBOR_VERSION, reject_secrets, validate_effective
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
                    "name": "Maintainer vLLM",
                    "options": {"baseURL": model["endpoint"]},
                    "models": {model["name"]: {"name": model["name"]}},
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
                    "CAD_BENCH_AGENT_IMAGE": manifest["image_alias"],
                    "CAD_BENCH_VERIFIER_IMAGE": manifest["image_alias"],
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


def submit(store, team, cfg=None, bundle=None, parent=None):
    if importlib.metadata.version("harbor") != HARBOR_VERSION:
        raise ValueError("Wrong Harbor version; install with uv sync --locked")
    run_id = "hh-" + uuid.uuid4().hex[:16]
    path = store.root / "runs" / run_id
    path.mkdir(mode=0o700)
    try:
        if parent:
            old_path = store.path(parent)
            old = read_json(old_path / "manifest.json")
            verify_inputs(old_path, old)
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
        verify_inputs(path, manifest)
        write_json(path / "manifest.json", manifest)
        write_json(path / "job.json", job_config(path, manifest))
        with store.connect() as db:
            db.execute(
                "INSERT INTO runs(id,status,created,concurrency,parent) VALUES(?,?,?,?,?)",
                (run_id, "queued", time.time(), cfg["concurrency"], parent),
            )
    except BaseException:
        shutil.rmtree(path)
        raise
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
    return {k: v for k, v in os.environ.items() if k in keep or k == "VLLM_API_KEY"}


def ensure_supervisor(store):
    with (store.root / "supervisor.log").open("a") as log:
        subprocess.Popen(
            [sys.executable, "-m", "harbor_helper.worker", "supervise", str(store.root)],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            close_fds=True,
            env=safe_environment(),
        )
