import argparse
import os
import sys
from pathlib import Path


def parser():
    p = argparse.ArgumentParser(description="Harbor experiments through a shared team service")
    p.add_argument("--json", action="store_true", help="Original machine-readable output")
    p.add_argument("--remote-profile", help="Use named service member profile")
    sub = p.add_subparsers(dest="command", required=True)
    mcp = sub.add_parser("mcp", help="Official MCP SDK stdio server (optional extra)")
    mcp.add_argument("--profile", required=True)
    mcp.add_argument("--upload-root", type=Path, default=Path.cwd())
    mcp.add_argument("--download-root", type=Path, default=Path.cwd())
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
    attachment_download = attachment_ops.add_parser("download")
    attachment_download.add_argument("version_id")
    attachment_download.add_argument("--output", required=True, type=Path)
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
    manage = sub.add_parser("manage", help="Shared request, dataset and recycle management")
    management_ops = manage.add_subparsers(dest="management_command", required=True)
    for action in ("requests", "datasets", "recycle-list"):
        management_ops.add_parser(action)
    rename = management_ops.add_parser("rename-group")
    rename.add_argument("group_id")
    rename.add_argument("name")
    for action in ("versions", "preview", "default", "parameters-check", "parameters-save"):
        operation = management_ops.add_parser(action)
        operation.add_argument("dataset_id")
        if action == "preview":
            operation.add_argument("digest")
        if action in {"default", "parameters-check", "parameters-save"}:
            operation.add_argument("--version-id")
        if action == "default":
            operation.add_argument("--team-default", action="store_true")
        if action == "parameters-save":
            operation.add_argument(
                "--values", required=True, help="JSON nonsecret author parameters"
            )
    confirm = management_ops.add_parser("confirm")
    confirm.add_argument("preview_id")
    for action in ("merge-preview", "merge"):
        operation = management_ops.add_parser(action)
        operation.add_argument("source")
        operation.add_argument("target")
        if action == "merge":
            operation.add_argument("revision")
            operation.add_argument("--parameter-choices", default="{}")
    for action in ("recycle-preview", "recycle"):
        operation = management_ops.add_parser(action)
        if action == "recycle-preview":
            operation.add_argument("kind")
            operation.add_argument("object_id")
        else:
            operation.add_argument("--items", required=True, help="JSON list from explicit preview")
    for action in ("restore", "purge"):
        operation = management_ops.add_parser(action)
        operation.add_argument("event_id")
        if action == "purge":
            operation.add_argument("--idempotency-key", required=True)
    from harbor_helper.commands.service import add_parsers

    service_parsers = add_parsers(sub)
    for sp in [
        *sub.choices.values(),
        *service_parsers[1:],
        *attachment_ops.choices.values(),
        *management_ops.choices.values(),
    ]:
        sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    return p


def main():
    args = parser().parse_args()
    os.umask(0o077)
    from harbor_helper.commands.remote import RemoteError, render, selected_profile
    from harbor_helper.commands.remote import dispatch as remote_dispatch

    try:
        if args.command == "mcp":
            from harbor_helper.mcp_server import serve

            serve(args.profile, args.upload_root, args.download_root)
            return 0
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
        if args.json:
            import json

            print(
                json.dumps(
                    error.as_dict()
                    if isinstance(error, RemoteError)
                    else {"code": "client_error", "message": str(error)}
                )
            )
        else:
            print(f"harbor-helper: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
