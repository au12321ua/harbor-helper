"""``maestro`` command: initialize an instance, migrate, serve, export OpenAPI.

Installation and systemd management arrive with M8 (12); these commands are
what the installer will call.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from maestro import config
from maestro.core.errors import MaestroError


def _settings(args):
    return config.load(Path(args.config) if args.config else None)


def cmd_init(args) -> int:
    """Create directories, migrate an empty database, create the master key, issue setup."""
    from maestro.application import Maestro
    from maestro.db import migrate

    settings = _settings(args)
    for path, mode in (
        (settings.data_dir, 0o700),
        (settings.cache_dir, 0o700),
        (settings.master_key_dir, 0o700),
    ):
        path.mkdir(parents=True, exist_ok=True, mode=mode)
    settings.artifacts_dir.mkdir(exist_ok=True, mode=0o700)
    service = Maestro.build(settings)
    migrate.upgrade(service.db)
    created = service.keys.initialize()
    token = service.accounts.issue_setup_token()
    print(f"database: {settings.database} (schema {migrate.current(service.db)})")
    print(f"master key: {'created' if created else 'already present'} in {settings.master_key_dir}")
    if token:
        print("One-time setup token for the first administrator (shown once):")
        print(token)
    else:
        print("An administrator already exists; setup is closed.")
    return 0


def cmd_upgrade(args) -> int:
    from maestro.db import migrate
    from maestro.db.engine import Database

    settings = _settings(args)
    db = Database.open(settings.database)
    before = migrate.current(db)
    migrate.upgrade(db)
    print(f"schema {before} -> {migrate.current(db)}")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from maestro.api.app import create_app
    from maestro.application import Maestro

    settings = _settings(args)
    executor = None
    if args.demo_executor:
        # Development only: a scripted fake executor so pages can be exercised
        # before the Harbor Runner (M3) exists. Never for real experiments.
        from maestro.testing.fakes import FakeExecutor

        executor = FakeExecutor(step_delay=1.0, executor_id="demo-fake")
        print("WARNING: demo fake executor enabled; results are not real.", file=sys.stderr)
    service = Maestro.build(settings, executor=executor)
    state = service.schema_state()
    if not state["compatible"]:
        print(
            f"Schema {state['current']} does not match {state['head']}; run 'maestro db upgrade'.",
            file=sys.stderr,
        )
    if args.demo_executor:
        from maestro.testing.fakes import FakeDatasetSource

        source = FakeDatasetSource()
        source.add("demo", "arith", "v1", ["add-01", "add-02", "mul-01"])
        if not service.catalog.list_datasets(None, None)[0]:
            service.catalog.register_version(source, "demo", "arith", "v1", True, None)
    from maestro.core.lock import InstanceLock

    with InstanceLock(settings.lock_file):
        uvicorn.run(
            create_app(service),
            host=args.host or settings.listen_host,
            port=args.port or settings.listen_port,
            proxy_headers=True,
            log_level="info",
        )
    return 0


def cmd_openapi(args) -> int:
    from maestro.api.openapi import document

    text = json.dumps(document(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text)
    else:
        sys.stdout.write(text)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="maestro")
    parser.add_argument("--config", default=os.environ.get("MAESTRO_CONFIG"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="initialize a new instance").set_defaults(func=cmd_init)
    db = sub.add_parser("db", help="database maintenance")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    db_sub.add_parser("upgrade", help="apply migrations").set_defaults(func=cmd_upgrade)
    serve = sub.add_parser("serve", help="run the HTTP service")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--demo-executor", action="store_true", help=argparse.SUPPRESS)
    serve.set_defaults(func=cmd_serve)
    openapi = sub.add_parser("openapi", help="print the public OpenAPI document")
    openapi.add_argument("--output")
    openapi.set_defaults(func=cmd_openapi)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except MaestroError as error:
        print(f"{error.code}: {error.message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
