import argparse
import asyncio
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path

from harbor_helper.auth import (
    Auth,
    AuthError,
    resolve_state,
    runtime_context,
    select_team,
    ttl_seconds,
)
from harbor_helper.config import DEFAULT, HARBOR_VERSION, effective, load_team
from harbor_helper.credentials import (
    KEY_ENV,
    RedactedStream,
    audit_run,
    legacy_secrets,
    redact_value,
    runtime_secrets,
    scan_tree,
)
from harbor_helper.reports import compare, report
from harbor_helper.runs import (
    ensure_supervisor,
    image_identity,
    scheduler_identity,
    stop_supervisor,
    submit,
)
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
    p.add_argument("--state", help="Team state directory")
    p.add_argument("--json", action="store_true", help="Original machine-readable output")
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Initialize team configuration once")
    init.add_argument("--config", type=Path)
    diagnose = sub.add_parser("doctor", help="Check dependencies/sources without calling a model")
    diagnose.add_argument("--preset", default="default")
    submit_p = sub.add_parser("submit", help="Freeze inputs and submit detached Harbor work")
    submit_p.add_argument("--preset")
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
    sub.add_parser("scan", help="Scan stopped team state; safe counts only")
    auth = sub.add_parser("auth", help="Account-local team login (no provider probe)")
    commands = auth.add_subparsers(dest="auth_command", required=True)
    login = commands.add_parser("login")
    login.add_argument(
        "--key-file", type=Path, help="Reference existing owner-only file; value not copied"
    )
    login.add_argument(
        "--ttl",
        type=ttl_seconds,
        default=8 * 3600,
        help="Execution authorization duration (default 8h)",
    )
    commands.add_parser("status")
    commands.add_parser("logout")
    for sp in [*sub.choices.values(), *commands.choices.values()]:
        sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    return p


def dispatch(args):
    store = Store(args.state)
    with store.control():
        return dispatch_locked(args, store)


def dispatch_locked(args, store):
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
        select_team(store.root)
        return {"state": str(store.root), "config": str(path)}
    if cmd == "auth":
        auth = Auth(store.root)
        team = load_team(store)
        model = team["model"]
        if args.auth_command == "status":
            return auth.status(model["endpoint"] if model else None)
        if any(row["status"] not in TERMINAL for row in store.runs()):
            raise AuthError(
                "Unfinished tasks: wait for terminal states or cancel before login/logout"
            )
        if args.auth_command == "logout":
            stop_supervisor(store)
            return auth.logout(store)
        if not model:
            raise AuthError("Model not configured; maintainer must configure team.json first")
        print(
            f"Team: {store.root}\nEndpoint: {model['endpoint']}\nModel: {model['name']}\nLocal login only; provider authentication is not verified.",
            file=sys.stderr,
        )
        was_running = bool(scheduler_identity(store))
        stop_supervisor(store)
        value = auth.login(store, model, args.ttl, args.key_file)
        if was_running:
            with runtime_context(store.root):
                ensure_supervisor(store)
        return value
    if cmd == "scan":
        from harbor_helper.worker import alive

        if any(
            row["status"] not in TERMINAL or alive(row) for row in store.runs()
        ) or scheduler_identity(store):
            raise ValueError(
                "State has active writers; wait for terminal tasks, then use stop before scan"
            )
        auth = Auth(store.root)
        keys, unavailable = auth.audit_keys()
        # Pre-auth historical runs still require their explicitly supplied audit key.
        for row in store.runs():
            cfg = read_json(store.path(row["id"]) / "manifest.json")["effective"]
            if (
                cfg["agent"] == "opencode"
                and cfg["model"].get("credential_env")
                and auth.bound_record(row["id"]) is None
            ):
                if legacy_secrets():
                    keys.extend(legacy_secrets())
                else:
                    unavailable += 1
        result = scan_tree(store.root, keys)
        result.update(audit_complete=unavailable == 0, unavailable_sources=unavailable)
        result["clean"] = result["clean"] and result["audit_complete"]
        return result, 0 if result["clean"] else 1
    if cmd == "doctor":
        value = doctor(store, args.preset)
        return value, 0 if value["ok"] else 1
    if cmd == "submit":
        team = load_team(store)
        if args.preset == "oracle":
            args.preset, args.agent = "default", "oracle"
        if args.preset is None:
            args.preset = "default" if args.agent == "oracle" else "model"
        cfg = effective(team, args)
        if cfg["agent"] == "oracle" and args.agent != "oracle":
            raise ValueError("Oracle requires explicit --agent oracle (or --preset oracle)")
        return submit(store, team, cfg, args.bundle)
    if cmd == "rerun":
        return submit(store, load_team(store), parent=args.run_id)
    if cmd == "recover":
        load_team(store)
        ensure_supervisor(store)
        return {"scheduler": "reconciliation requested"}
    if cmd == "stop":
        return stop_supervisor(store)
    if cmd == "list":
        ensure_supervisor(store)
        return store.runs()
    if cmd == "status":
        ensure_supervisor(store)
        return {**store.get(args.run_id), "evidence": str(store.path(args.run_id))}
    if cmd == "logs":
        require_safe_evidence(store, args.run_id)
        path = store.path(args.run_id) / "worker.log"
        return (
            redact_value(path.read_text(), runtime_secrets())
            if path.exists()
            else "Not started (queued)"
        )
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
        require_safe_evidence(store, args.run_id, terminal_audit=True)
        return report(store, args.run_id)
    if cmd == "compare":
        require_safe_evidence(store, args.left, terminal_audit=True)
        require_safe_evidence(store, args.right, terminal_audit=True)
        value = compare(store, args.left, args.right)
        return value, 0 if value["comparable"] else 2
    raise ValueError(cmd)


def require_safe_evidence(store, run_id, terminal_audit=False):
    cfg = read_json(store.path(run_id) / "manifest.json")["effective"]
    if cfg["agent"] != "opencode" or not cfg["model"].get("credential_env"):
        return
    auth = Auth(store.root)
    record = auth.bound_record(run_id)
    if record is not None:
        auth.value(record)  # No fallback to K2 when K1 history is unavailable.
    elif not legacy_secrets():
        raise AuthError("Historical credential source unavailable; raw evidence withheld")
    if terminal_audit:
        if store.get(run_id)["status"] not in TERMINAL:
            raise AuthError("Report awaits terminal credential audit; use status/logs meanwhile")
        key = auth.value(record) if record else legacy_secrets()[0]
        if not audit_run(store, run_id, [key] if key else [])["clean"]:
            raise AuthError("Run evidence audit not clean; raw report withheld")
    # Active logs are explicitly redacted, including common encoded forms.


def main():
    args = parser().parse_args()
    os.umask(0o077)
    original_stdout, original_stderr = sys.stdout, sys.stderr
    try:
        args.state = resolve_state(args.state)
        with runtime_context(args.state, legacy_key=os.environ.get(KEY_ENV)):
            sys.stdout = RedactedStream(original_stdout, runtime_secrets())
            sys.stderr = RedactedStream(original_stderr, runtime_secrets())
            try:
                value = dispatch(args)
                exit_code = 0
                if isinstance(value, tuple):
                    value, exit_code = value
                from harbor_helper.presentation import render

                command = f"auth {args.auth_command}" if args.command == "auth" else args.command
                render(command, value, json_output=args.json)
                return exit_code
            except (ValueError, OSError, subprocess.TimeoutExpired) as error:
                print(f"harbor-helper: {error}", file=sys.stderr)
                return 1
            finally:
                sys.stdout.finish()
                sys.stderr.finish()
    except (ValueError, OSError) as error:
        print(f"harbor-helper: {error}", file=original_stderr)
        return 1
    finally:
        sys.stdout, sys.stderr = original_stdout, original_stderr


if __name__ == "__main__":
    sys.exit(main())
