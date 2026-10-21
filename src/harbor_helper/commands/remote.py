"""Terminal adapters over the public SDK."""

import getpass
import json
import re
import sys
import warnings
from pathlib import Path
from urllib.parse import quote

from harbor_helper.sdk import (
    Client,
    RemoteError,
    identifier,
    load_profile,
    profile_lock,
    profile_name,
    service_url,
    upload_bundle,
    validate_token,
)
from harbor_helper.sdk import (
    remote_root as remote_root,  # noqa: PLC0414  # Public compatibility import.
)
from harbor_helper.sdk import (
    selected_profile as selected_profile,  # noqa: PLC0414  # Public compatibility import.
)
from harbor_helper.security.files import secure_write


def hidden_input(prompt):
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except (getpass.GetPassWarning, EOFError):
            raise RemoteError("Hidden input requires an interactive terminal") from None


def login(url, username, name="default"):
    name, url = profile_name(name), service_url(url)
    if not username:
        username = input("Team username: ").strip()
    print(f"Service: {url}\nMember: {username}\nProfile: {name}", file=sys.stderr)
    password = hidden_input("Team password (hidden): ")
    value = Client(url, secrets=[password]).request(
        "POST", "/auth/login", body={"username": username, "password": password}
    )
    # Login's one secret response must not be sanitized away before private storage.
    token, user = value.get("token"), value.get("user")
    if isinstance(user, dict):
        user = {k: user[k] for k in ("id", "username", "role", "enabled") if k in user}
    if not isinstance(token, str) or not isinstance(user, dict):
        raise RemoteError("Invalid login response")
    validate_token(token)
    with profile_lock() as root:
        secure_write(
            root / "profiles" / (name + ".json"), {"url": url, "token": token, "user": user}
        )
        secure_write(root / "selected.json", {"profile": name})
    # Validate token shape/mode without ever returning its value.
    load_profile(name)
    return {"profile": name, "url": url, "user": user, "logged_in": True}


def configure_access(url, name, token_file=None, token_stdin=False):
    name, url = profile_name(name), service_url(url)
    if token_stdin:
        token = sys.stdin.readline(4097).strip()
    elif token_file:
        # Ownership/mode/symlink checks are identical to model credential files.
        from harbor_helper.security.credentials import read_key_file

        token = read_key_file(Path(token_file).expanduser())
    else:
        token = hidden_input("Automation credential (hidden): ")
    if not re.fullmatch(r"hh_pat_v1_[A-Za-z0-9_-]{43}", token):
        raise RemoteError("Invalid automation credential format")
    user = Client(url, token).request("GET", "/me")
    with profile_lock() as root:
        secure_write(
            root / "profiles" / (name + ".json"),
            {"url": url, "token": token, "user": user, "authentication": "automation"},
        )
        secure_write(root / "selected.json", {"profile": name})
    return {"profile": name, "url": url, "user": user, "configured": True}


def connection(name):
    profile = load_profile(name)
    return profile, Client(profile["url"], profile["token"])


def logout(name):
    with profile_lock() as root:
        profile, client = connection(name)
        if profile.get("authentication") != "automation":
            client.request("POST", "/auth/logout", body={})
        (root / "profiles" / (name + ".json")).unlink()
        # Keep the selected marker: ordinary commands must not silently become local.
    return {
        "profile": name,
        "url": profile["url"],
        "logged_in": False,
        "detail": "Local profile removed; revoke automation credentials in the website. Accepted experiments continue",
    }


def write_request(name, profile, client, path, body, idem=None):
    return client.write(path, body, idem)


def dispatch(args, name):
    profile, client = connection(name)
    cmd = args.command
    if cmd == "manage":
        action = args.management_command
        if action == "requests":
            return client.list_requests()
        if action == "datasets":
            return client.list_datasets()
        if action == "recycle-list":
            return client.list_recycle()
        if action == "rename-group":
            return client.rename_group(args.group_id, args.name)
        if action == "versions":
            return client.dataset_versions(args.dataset_id)
        if action == "preview":
            return client.preview_dataset(args.dataset_id, args.digest)
        if action == "confirm":
            return client.confirm_dataset(args.preview_id)
        if action == "default":
            return client.set_dataset_default(args.dataset_id, args.version_id, args.team_default)
        if action == "parameters-check":
            return client.check_dataset_parameters(args.dataset_id, args.version_id)
        if action == "parameters-save":
            return client.save_dataset_parameters(
                args.dataset_id, json.loads(args.values), args.version_id
            )
        if action == "merge-preview":
            return client.merge_datasets_preview(args.source, args.target)
        if action == "merge":
            return client.merge_datasets(
                args.source, args.target, args.revision, json.loads(args.parameter_choices)
            )
        if action == "recycle-preview":
            return client.preview_recycle(args.kind, args.object_id)
        if action == "recycle":
            return client.recycle(json.loads(args.items))
        if action == "restore":
            return client.restore(args.event_id)
        if action == "purge":
            return client.purge(args.event_id, args.idempotency_key)
    if cmd == "service":
        operation = args.service_command
        if operation == "status":
            return {"profile": name, "url": profile["url"], "user": client.request("GET", "/me")}
        if operation == "logout":
            return logout(name)
        if operation == "discover":
            return client.request("GET", "/machine/discovery")
        if operation == "schema":
            return client.request("GET", "/machine/schema")
        if operation == "tasks":
            return client.request(
                "GET",
                "/machine/datasets/"
                + identifier(args.dataset_id)
                + f"/tasks?offset={args.offset}&limit={args.limit}",
            )
        if operation == "lookup":
            return client.request(
                "GET", "/submission-operations/" + args.operation + "/" + quote(args.key, safe="")
            )
        if operation == "query":
            kind = "submissions" if args.record_id.startswith("sub-") else "runs"
            return client.request("GET", "/machine/" + kind + "/" + identifier(args.record_id))
        if operation == "report":
            return client.get_report(args.run_id)
        if operation == "recover":
            return write_request(
                name,
                profile,
                client,
                "/submissions/" + identifier(args.submission_id) + "/retry",
                {},
                args.idempotency_key,
            )
        if operation == "history":
            return client.history(
                **{
                    field: getattr(args, field)
                    for field in (
                        "offset",
                        "limit",
                        "mine",
                        "operation",
                        "key",
                        "operation_id",
                        "user_id",
                        "status",
                        "created_from",
                        "created_to",
                    )
                }
            )
        if operation == "retry":
            return client.write(args.path, json.loads(args.body), args.idempotency_key)
    if cmd == "attachments":
        action = args.attachment_command
        if action == "download":
            return client.fetch_attachment(args.version_id, args.output)
        if action == "list":
            return client.request("GET", "/attachments")
        if action == "lookup":
            return client.request(
                "GET", "/attachment-operations/" + args.operation + "/" + quote(args.key, safe="")
            )
        if action == "update":
            body = {
                k: getattr(args, k) for k in ("name", "description") if getattr(args, k) is not None
            }
            if args.enabled is not None:
                body["enabled"] = args.enabled == "true"
            path = "/attachments/" + identifier(args.attachment_id)
            if args.version_id:
                path += "/versions/" + identifier(args.version_id)
            return client.request("PATCH", path, body=body)
        path = "/attachments"
        body = (
            {"name": args.name, "description": args.description}
            if action != "publish"
            else {"notes": args.notes}
        )
        if action == "publish":
            path += "/" + identifier(args.attachment_id) + "/versions"
        if action == "derive":
            path = "/attachment-versions/" + identifier(args.source_version_id) + "/derive"
        return upload_bundle(
            client, args.file, path_url=path, metadata=body, idem=args.idempotency_key
        )
    if cmd in {"catalog", "usage", "list"}:
        return client.request(
            "GET", {"catalog": "/catalog", "usage": "/usage", "list": "/runs"}[cmd]
        )
    if cmd == "submit":
        body = {
            k: getattr(args, k)
            for k in ("dataset", "agent", "attempts", "concurrency", "wall_seconds", "task")
            if getattr(args, k, None) is not None
        }
        if args.agent != "oracle" and not args.model_profile:
            raise RemoteError("Choose --model-profile from catalog (or explicitly --agent oracle)")
        if args.model_profile:
            body["model_profile"] = args.model_profile
        if args.attachment_version_id:
            body["attachment_version_id"] = args.attachment_version_id
        return write_request(name, profile, client, "/submissions", body, args.idempotency_key)
    if cmd == "compare":
        value = client.request("POST", "/compare", body={"left": args.left, "right": args.right})
        return value, 0 if value.get("comparable") else 2
    if cmd in {"status", "cancel"} and args.run_id.startswith("sub-"):
        path = "/submissions/" + identifier(args.run_id)
        return client.request(
            "POST" if cmd == "cancel" else "GET",
            path + ("/cancel" if cmd == "cancel" else ""),
            body={} if cmd == "cancel" else None,
        )
    if cmd in {"status", "logs", "report", "cancel", "rerun", "retry", "artifacts", "download"}:
        path = "/runs/" + identifier(args.run_id)
        if cmd == "status":
            return client.request("GET", path)
        if cmd in {"rerun", "retry"}:
            return write_request(
                name,
                profile,
                client,
                path + "/" + cmd,
                {"wall_seconds": args.wall_seconds}
                if cmd == "retry" and args.wall_seconds is not None
                else {},
                args.idempotency_key,
            )
        if cmd == "logs":
            value = client.request("GET", path + "/logs")
            if value.get("truncated"):
                print("Log view is truncated; see the run's service detail", file=sys.stderr)
            return value if args.json else value["text"]
        if cmd == "cancel":
            return client.request("POST", path + "/cancel", body={})
        if cmd == "artifacts":
            return client.request("GET", path)["artifacts"]
        if cmd == "download":
            return client.download(path + "/artifacts/" + identifier(args.file_id), args.output)
        return client.request("GET", path + "/report")
    raise RemoteError("Unsupported command")


def render(command, value, json_output=False):
    from harbor_helper.results.presentation import render as local_render

    if json_output:
        print(json.dumps(value, indent=2, ensure_ascii=False))
    elif command == "list" and isinstance(value, dict):
        local_render("list", value.get("runs", []))
        from rich.console import Console
        from rich.table import Table

        table = Table("Submission", "Submitter", "Phase", "Run")
        for row in value.get("submissions", []):
            table.add_row(
                row["id"], row.get("submitter", ""), row["status"], row.get("run_id") or "—"
            )
        Console(markup=False, highlight=False).print(table)
    elif command == "status" and isinstance(value, dict) and "row" in value:
        local_render("status", value["row"])
    elif command == "report" and value is None:
        print("No published report yet; use status to inspect preparation/execution")
    elif command in {"submit", "rerun", "retry"}:
        local_render("submission", value)
        print(f"Next: harbor-helper status {value['id']}")
    elif command == "artifacts":
        from rich.console import Console

        Console(markup=False, highlight=False).print(value)
    else:
        local_render(command, value)
