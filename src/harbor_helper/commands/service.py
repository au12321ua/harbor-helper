"""Service process and remote member login entry points."""

import os
from pathlib import Path

from harbor_helper.commands.remote import (
    RemoteError,
    login,
    selected_profile,
)
from harbor_helper.commands.remote import (
    dispatch as remote_dispatch,
)


def add_parsers(sub):
    service = sub.add_parser("service", help="Shared HTTP service / remote member login")
    operations = service.add_subparsers(dest="service_command", required=True)
    serve = operations.add_parser("serve", help="Serve API and packaged static UI over HTTP")
    serve.add_argument("--root", type=Path)
    serve.add_argument(
        "--setup-token-file", type=Path, help="Owner-only deployment bootstrap token"
    )
    serve.add_argument("--master-key-file", type=Path, help="External persistent master key")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    scheduler = operations.add_parser(
        "scheduler", help="Run the independent scheduler in foreground"
    )
    scheduler.add_argument("--root", type=Path, required=True)
    member_login = operations.add_parser(
        "login", help="Invited member login (no personal model key)"
    )
    member_login.add_argument("--url", required=True)
    member_login.add_argument("--username")
    member_login.add_argument("--profile", default="default")
    automation = operations.add_parser(
        "configure-token", help="Store automation credential privately; never pass token in argv"
    )
    automation.add_argument("--url", required=True)
    automation.add_argument("--profile", default="default")
    source = automation.add_mutually_exclusive_group()
    source.add_argument("--token-file", type=Path)
    source.add_argument("--token-stdin", action="store_true")
    for command in (
        "history",
        "status",
        "logout",
        "retry",
        "discover",
        "schema",
        "tasks",
        "lookup",
        "query",
        "report",
        "recover",
    ):
        child = operations.add_parser(command)
        child.add_argument("--profile")
        if command == "retry":
            child.add_argument("path", help="Original API path, for example /submissions")
            child.add_argument("--body", required=True, help="Original JSON body")
            child.add_argument("--idempotency-key", required=True)
        if command == "history":
            child.add_argument("--offset", type=int, default=0)
            child.add_argument("--limit", type=int, default=50)
            child.add_argument("--mine", action="store_true")
            for field in ("operation", "key", "operation-id", "user-id", "status"):
                child.add_argument("--" + field)
            child.add_argument("--created-from", type=float)
            child.add_argument("--created-to", type=float)
        if command == "tasks":
            child.add_argument("dataset_id")
            child.add_argument("--offset", type=int, default=0)
            child.add_argument("--limit", type=int, default=100)
        if command == "lookup":
            child.add_argument("operation", choices=["submit", "rerun", "retry", "recover"])
            child.add_argument("key")
        if command == "query":
            child.add_argument("record_id")
        if command == "report":
            child.add_argument("run_id")
        if command == "recover":
            child.add_argument("submission_id")
            child.add_argument("--idempotency-key", required=True)
    return [service, *operations.choices.values()]


def service_root(args):
    return Path(args.root or ".state/service").expanduser().resolve()


def dispatch(args):
    return _dispatch(args)


def _dispatch(args):
    cmd = args.service_command
    if cmd == "scheduler":
        from harbor_helper.execution.scheduler import supervise

        supervise(service_root(args))
        return {"scheduler": "stopped"}
    if cmd == "serve":
        import uvicorn

        from harbor_helper.service.api import create_app

        if not 1 <= args.port <= 65535:
            raise RemoteError("Port must be between 1 and 65535")
        root = service_root(args)
        # HTTP observes the independently managed scheduler.
        from harbor_helper.security.credentials import KEY_ENV

        inherited = {KEY_ENV: os.environ.pop(KEY_ENV, None)}
        try:
            app = create_app(
                root, setup_token_file=args.setup_token_file, master_key_file=args.master_key_file
            )
            if app.state.application is None:
                private = root.parent / ("." + root.name + "-deployment")
                print(
                    f"Website setup ready. Protected bootstrap material: {args.setup_token_file or private / 'setup-token'}"
                )
            uvicorn.run(app, host=args.host, port=args.port, access_log=False)
        finally:
            for name, value in inherited.items():
                if value is not None:
                    os.environ[name] = value
        return {
            "service": "HTTP server stopped",
            "state": str(root),
            "detail": "Accepted experiments and supervisor continue independently",
        }
    if cmd == "configure-token":
        from harbor_helper.commands.remote import configure_access

        return configure_access(args.url, args.profile, args.token_file, args.token_stdin)
    if cmd == "login":
        return login(args.url, args.username, args.profile)
    name = selected_profile(getattr(args, "profile", None) or args.remote_profile)
    if not name:
        raise RemoteError("No remote profile selected; use service login --url URL")
    return remote_dispatch(args, name)
