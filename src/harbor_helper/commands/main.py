import argparse
import os
import sys
from pathlib import Path


def parser():
    p = argparse.ArgumentParser(description="Harbor experiments through a shared team service")
    p.add_argument("--json", action="store_true", help="Original machine-readable output")
    p.add_argument("--remote-profile", help="Use named service member profile")
    sub = p.add_subparsers(dest="command", required=True)
    submit_p = sub.add_parser("submit", help="Submit an experiment to the team service")
    submit_p.add_argument("--dataset")
    submit_p.add_argument("--model-profile", help="Team model profile ID from catalog")
    submit_p.add_argument("--idempotency-key", help="Retry key for the same submission")
    submit_p.add_argument("--agent", choices=["oracle", "opencode"])
    submit_p.add_argument("--attachment-version-id", help="Immutable attachment version")
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
    for command in ("catalog", "usage"):
        sub.add_parser(command, help="Shared service metadata")
    attachments = sub.add_parser("attachments", help="Shared service attachment versions")
    attachment_ops = attachments.add_subparsers(dest="attachment_command", required=True)
    attachment_ops.add_parser("list")
    lookup = attachment_ops.add_parser("lookup")
    lookup.add_argument(
        "operation",
        choices=[
            "attachment_create",
            "attachment_publish",
            "attachment_derive",
        ],
    )
    lookup.add_argument("key")
    for action in ("create", "publish", "derive"):
        ap = attachment_ops.add_parser(action)
        ap.add_argument("--idempotency-key", required=True)
        ap.add_argument("--file", required=True, type=Path, help="ZIP or bundle directory")
        if action != "publish":
            ap.add_argument("--name", required=True)
            ap.add_argument("--description", default="")
        if action == "publish":
            ap.add_argument("attachment_id")
            ap.add_argument("--notes", default="")
        if action == "derive":
            ap.add_argument("source_version_id")
    update = attachment_ops.add_parser("update")
    update.add_argument("attachment_id")
    update.add_argument("--version-id")
    update.add_argument("--name")
    update.add_argument("--description")
    update.add_argument("--enabled", choices=["true", "false"])
    artifacts = sub.add_parser("artifacts", help="Shared service artifacts")
    artifacts.add_argument("run_id")
    download = sub.add_parser("download", help="Download safe service artifact (new file only)")
    download.add_argument("run_id")
    download.add_argument("file_id")
    download.add_argument("--output", required=True, type=Path)
    from harbor_helper.commands.service import add_parsers

    service_parsers = add_parsers(sub)
    for sp in [
        *sub.choices.values(),
        *service_parsers[1:],
        *attachment_ops.choices.values(),
    ]:
        sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    return p


def main():
    args = parser().parse_args()
    os.umask(0o077)
    from harbor_helper.commands.remote import RemoteError, render, selected_profile
    from harbor_helper.commands.remote import dispatch as remote_dispatch

    try:
        if args.command == "service":
            from harbor_helper.commands.service import dispatch as service_dispatch

            render("service " + args.service_command, service_dispatch(args), args.json)
            return 0
        profile = selected_profile(args.remote_profile)
        if not profile:
            raise RemoteError("No service profile; use service login --url URL")
        value = remote_dispatch(args, profile)
        exit_code = 0
        if isinstance(value, tuple):
            value, exit_code = value
        render(args.command, value, args.json)
        return exit_code
    except (ValueError, OSError) as error:
        print(f"harbor-helper: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
