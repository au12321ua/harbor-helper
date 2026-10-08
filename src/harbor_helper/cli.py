import argparse
import asyncio
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

from harbor_helper.config import DEFAULT, HARBOR_VERSION, effective, load_team
from harbor_helper.reports import compare, report
from harbor_helper.runs import ensure_supervisor, image_identity, submit
from harbor_helper.storage import ACTIVE, TERMINAL, Store, read_json, write_json


def doctor(store, preset="default"):
    checks = []
    version = importlib.metadata.version("harbor")
    checks.append(
        {
            "check": "harbor",
            "ok": version == HARBOR_VERSION,
            "actual": version,
            "python": sys.executable,
            "fix": "uv sync --locked",
        }
    )
    for args, fix in (
        (["docker", "info"], "Start Docker and grant this account Docker access"),
        (["docker", "compose", "version"], "Install Docker Compose plugin"),
    ):
        try:
            value = subprocess.run(args, check=False, capture_output=True, timeout=30)
            ok = value.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        checks.append({"check": " ".join(args), "ok": ok, "fix": fix})
    try:
        team = load_team(store)
    except (OSError, ValueError) as e:
        checks.append(
            {
                "check": "team",
                "ok": False,
                "detail": str(e),
                "fix": "harbor-helper init; review state/team.json",
            }
        )
        return {"checks": checks, "ok": False}
    try:
        image = image_identity(team["runtime_image"])
        checks.append({"check": "runtime_image", "ok": True, "image_id": image})
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        checks.append(
            {
                "check": "runtime_image",
                "ok": False,
                "detail": str(e),
                "fix": "Maintainer: uv run python scripts/build_cad_runtime.py --cadir /path/to/CADIR",
            }
        )

    async def metadata():
        from harbor.registry.client.package import PackageDatasetClient

        return await asyncio.wait_for(
            PackageDatasetClient().get_dataset_metadata(team["dataset"]), timeout=40
        )

    try:
        source = asyncio.run(metadata())
        checks.append(
            {
                "check": "dataset_access",
                "ok": bool(source.task_ids),
                "resolved": source.name + "@" + source.version,
                "tasks": [t.model_dump(mode="json") for t in source.task_ids],
            }
        )
    except Exception as e:  # noqa: BLE001 - persist/diagnose third-party Harbor errors
        checks.append(
            {
                "check": "dataset_access",
                "ok": False,
                "detail": type(e).__name__,
                "fix": "Run project .venv/bin/harbor auth login; obtain Hub dataset access",
            }
        )
    model = team["model"]
    checks.append(
        {
            "check": "model",
            "ok": model is not None,
            "required": team["presets"].get(preset, {}).get("agent") == "opencode",
            "detail": "configured (not contacted)" if model else "A10 unverified: no model",
            "fix": "Maintainer: configure a compatible endpoint in team.json, then restart scheduler",
        }
    )
    try:
        effective(team, argparse.Namespace(preset=preset))
    except ValueError as e:
        checks.append(
            {
                "check": "preset",
                "ok": False,
                "detail": str(e),
                "fix": "Review the selected preset/model configuration",
            }
        )
    return {
        "checks": checks,
        "preset": preset,
        "ok": all(c["ok"] for c in checks if c.get("required", True)),
        "model_request_sent": False,
    }


def parser():
    p = argparse.ArgumentParser(description="Harbor experiments on a shared Linux/Docker machine")
    p.add_argument(
        "--state", default=os.environ.get("HARBOR_HELPER_STATE", "~/.local/state/harbor-helper")
    )
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Initialize team configuration once")
    init.add_argument("--config", type=Path)
    diagnose = sub.add_parser("doctor", help="Check dependencies/sources without calling a model")
    diagnose.add_argument("--preset", default="default")
    submit_p = sub.add_parser("submit", help="Freeze inputs and submit detached Harbor work")
    submit_p.add_argument("--preset", default="default")
    submit_p.add_argument("--dataset")
    submit_p.add_argument("--agent", choices=["oracle", "opencode"])
    submit_p.add_argument("--bundle", type=Path)
    submit_p.add_argument(
        "--model", help="Served model ID at the maintainer-configured compatible endpoint"
    )
    submit_p.add_argument("--task", help="Optional glob matching dataset task name")
    for k in ("attempts", "concurrency", "wall-seconds"):
        submit_p.add_argument("--" + k, type=int)
    sub.add_parser("list")
    for cmd in ("status", "logs", "cancel", "report", "rerun"):
        sp = sub.add_parser(cmd)
        sp.add_argument("run_id")
    comp = sub.add_parser("compare")
    comp.add_argument("left")
    comp.add_argument("right")
    sub.add_parser("recover", help="Restart/reconcile scheduler after a crash")
    sub.add_parser("stop", help="Stop idle scheduler so maintainer can refresh runtime credentials")
    return p


def dispatch(args):
    store = Store(args.state)
    cmd = args.command
    if cmd == "init":
        path = store.root / "team.json"
        if path.exists():
            raise ValueError("Already initialized; edit team.json explicitly")
        write_json(path, read_json(args.config) if args.config else DEFAULT)
        try:
            load_team(store)
        except Exception:
            path.unlink()
            raise
        return {"state": str(store.root), "config": str(path)}
    if cmd == "doctor":
        value = doctor(store, args.preset)
        return value, 0 if value["ok"] else 1
    if cmd == "submit":
        team = load_team(store)
        return submit(store, team, effective(team, args), args.bundle)
    if cmd == "rerun":
        return submit(store, load_team(store), parent=args.run_id)
    if cmd == "recover":
        load_team(store)
        ensure_supervisor(store)
        return {"scheduler": "reconciliation requested"}
    if cmd == "stop":
        if any(r["status"] not in TERMINAL for r in store.runs()):
            raise ValueError("Only stop idle scheduler; cancel/wait for all runs first")
        from harbor_helper.worker import process_birth

        info = store.root / "scheduler.json"
        if info.exists():
            identity = read_json(info)
            if process_birth(identity["pid"]) == identity["birth"]:
                os.kill(identity["pid"], 15)
        return {"scheduler": "idle scheduler stop requested"}
    if cmd == "list":
        ensure_supervisor(store)
        return store.runs()
    if cmd == "status":
        ensure_supervisor(store)
        return {**store.get(args.run_id), "evidence": str(store.path(args.run_id))}
    if cmd == "logs":
        path = store.path(args.run_id) / "worker.log"
        return path.read_text() if path.exists() else "Not started (queued)"
    if cmd == "cancel":
        row = store.get(args.run_id)
        if row["status"] not in TERMINAL:
            store.update(
                args.run_id, cancel=1, status="cancelling" if row["status"] in ACTIVE else "queued"
            )
            ensure_supervisor(store)
        return {
            "run_id": args.run_id,
            "cancel_requested": True,
            "detail": "Check status: terminal cancelled confirms cleanup",
        }
    if cmd == "report":
        return report(store, args.run_id)
    if cmd == "compare":
        value = compare(store, args.left, args.right)
        return value, 0 if value["comparable"] else 2
    raise ValueError(cmd)


def main():
    args = parser().parse_args()
    os.umask(0o077)
    try:
        value = dispatch(args)
        exit_code = 0
        if isinstance(value, tuple):
            value, exit_code = value
        if isinstance(value, str):
            print(value)
        else:
            print(json.dumps(value, indent=2, ensure_ascii=False))
        return exit_code
    except (ValueError, OSError, subprocess.TimeoutExpired) as e:
        print(f"harbor-helper: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
