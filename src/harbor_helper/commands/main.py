import argparse
import os
import subprocess
import sys
from pathlib import Path

from harbor_helper.commands.local import dispatch
from harbor_helper.security.credentials import (
    KEY_ENV,
    RedactedStream,
    runtime_secrets,
)
from harbor_helper.security.local_auth import (
    resolve_state,
    runtime_context,
    ttl_seconds,
)


def parser():
    p = argparse.ArgumentParser(description="Harbor experiments on a shared Linux/Docker machine")
    p.add_argument("--state", help="Team state directory")
    p.add_argument("--json", action="store_true", help="Original machine-readable output")
    p.add_argument("--remote-profile", help="Use named service member profile")
    p.add_argument("--local", action="store_true", help="Explicitly use original local CLI")
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Initialize team configuration once")
    init.add_argument("--config", type=Path)
    diagnose = sub.add_parser("doctor", help="Check dependencies/sources without calling a model")
    diagnose.add_argument("--preset", default="default")
    submit_p = sub.add_parser("submit", help="Freeze inputs and submit detached Harbor work")
    submit_p.add_argument("--preset")
    submit_p.add_argument("--dataset")
    submit_p.add_argument("--model-profile", help="Remote team model profile ID")
    submit_p.add_argument("--idempotency-key", help="Remote retry key for the same submission")
    submit_p.add_argument("--agent", choices=["oracle", "opencode"])
    submit_p.add_argument("--bundle", type=Path)
    submit_p.add_argument(
        "--model", help="Served model ID at the maintainer-configured compatible endpoint"
    )
    submit_p.add_argument("--task", help="Optional glob matching dataset task name")
    for k in ("attempts", "concurrency", "wall-seconds"):
        submit_p.add_argument("--" + k, type=int)
    sub.add_parser("list")
    for cmd in ("status", "logs", "cancel", "report", "rerun", "retry"):
        sp = sub.add_parser(cmd)
        sp.add_argument("run_id")
        if cmd in {"rerun", "retry"}:
            sp.add_argument("--idempotency-key", help="Remote retry key for same operation")
        if cmd == "retry":
            sp.add_argument("--wall-seconds", type=int, help="Explicit repair retry wall limit")
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
    for command in ("catalog", "usage"):
        sub.add_parser(command, help="Shared service metadata")
    artifacts = sub.add_parser("artifacts", help="Shared service artifacts")
    artifacts.add_argument("run_id")
    download = sub.add_parser("download", help="Download safe service artifact (new file only)")
    download.add_argument("run_id")
    download.add_argument("file_id")
    download.add_argument("--output", required=True, type=Path)
    from harbor_helper.commands.service import add_parsers

    service_parsers = add_parsers(sub)
    for sp in [*sub.choices.values(), *commands.choices.values(), *service_parsers[1:]]:
        sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    return p

    # Active logs are explicitly redacted, including common encoded forms.


def main():
    args = parser().parse_args()
    os.umask(0o077)
    original_stdout, original_stderr = sys.stdout, sys.stderr
    try:
        from harbor_helper.commands.remote import (
            RemoteError,
            selected_profile,
        )
        from harbor_helper.commands.remote import (
            dispatch as remote_dispatch,
        )
        from harbor_helper.commands.remote import (
            render as remote_render,
        )

        if args.local and args.remote_profile:
            raise RemoteError("--local and --remote-profile are mutually exclusive")
        if args.command == "service":
            from harbor_helper.commands.service import dispatch as service_dispatch

            value = service_dispatch(args)
            remote_render("service " + args.service_command, value, args.json)
            return 0
        profile = None if args.local else selected_profile(args.remote_profile)
        if profile:
            if args.state:
                raise RemoteError(
                    "--state is local; remote mode uses service profile. Use --local explicitly"
                )
            value = remote_dispatch(args, profile)
            exit_code = 0
            if isinstance(value, tuple):
                value, exit_code = value
            remote_render(args.command, value, args.json)
            return exit_code
        if args.command in {"catalog", "usage", "artifacts", "download"} or getattr(
            args, "model_profile", None
        ):
            raise RemoteError("This operation requires service login --url URL")
        args.state = resolve_state(args.state)
        if (args.state / "service.json").exists():
            raise RemoteError(
                "Service state requires authenticated API access; --local cannot use it"
            )
        with runtime_context(args.state, legacy_key=os.environ.get(KEY_ENV)):
            sys.stdout = RedactedStream(original_stdout, runtime_secrets())
            sys.stderr = RedactedStream(original_stderr, runtime_secrets())
            try:
                value = dispatch(args)
                exit_code = 0
                if isinstance(value, tuple):
                    value, exit_code = value
                from harbor_helper.results.presentation import render

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
