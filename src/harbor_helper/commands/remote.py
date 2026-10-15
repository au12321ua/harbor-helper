"""Member-token HTTP client. Remote failures never dispatch local experiments."""

import fcntl
import getpass
import json
import os
import re
import stat
import sys
import tempfile
import uuid
import warnings
import zipfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

from harbor_helper.security.credentials import redact_value
from harbor_helper.security.files import secure_read, secure_write


class RemoteError(ValueError):
    pass


def hidden_input(prompt):
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except (getpass.GetPassWarning, EOFError):
            raise RemoteError("Hidden input requires an interactive terminal") from None


def profile_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
        raise RemoteError("Profile name must be 1–64 letters, digits, dots, underscores or hyphens")
    return value


def service_url(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (ValueError, TypeError):
        raise RemoteError(
            "Service URL must be an HTTP(S) address without credentials/query"
        ) from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or any(c.isspace() or ord(c) < 32 for c in value)
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise RemoteError("Service URL must be an HTTP(S) address without credentials/query")
    return value.rstrip("/")


def remote_root(create=False):
    app = Path.home() / ".config/harbor-helper"
    if create:
        app.parent.mkdir(parents=True, exist_ok=True)
    for path in (app, app / "remote", app / "remote/profiles"):
        if create:
            path.mkdir(mode=0o700, exist_ok=True)
        if path.exists() or path.is_symlink():
            meta = path.lstat()
            if (
                not stat.S_ISDIR(meta.st_mode)
                or meta.st_uid != os.getuid()
                or stat.S_IMODE(meta.st_mode) != 0o700
            ):
                raise RemoteError("Remote profile directories must be account-owned, mode 0700")
    return app / "remote"


@contextmanager
def profile_lock():
    root = remote_root(create=True)
    fd = os.open(root / "control.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield root


def selected_profile(explicit=None):
    if explicit:
        return profile_name(explicit)
    if os.environ.get("HARBOR_HELPER_REMOTE_PROFILE"):
        return profile_name(os.environ["HARBOR_HELPER_REMOTE_PROFILE"])
    pointer = remote_root() / "selected.json"
    if pointer.exists() or pointer.is_symlink():
        value = secure_read(pointer)
        if not isinstance(value, dict):
            raise RemoteError("Invalid selected remote profile")
        return profile_name(value.get("profile"))
    return None


def load_profile(name):
    name = profile_name(name)
    path = remote_root() / "profiles" / (name + ".json")
    if not path.exists() and not path.is_symlink():
        raise RemoteError("Remote profile not logged in; use service login --url URL")
    value = secure_read(path)
    if not isinstance(value, dict) or not isinstance(value.get("user"), dict):
        raise RemoteError("Invalid remote profile; log in again")
    validate_token(value.get("token"))
    value["url"] = service_url(value.get("url"))
    return value


def validate_token(token):
    if (
        not isinstance(token, str)
        or not 1 <= len(token) <= 4096
        or any(ord(c) < 33 or ord(c) > 126 for c in token)
    ):
        raise RemoteError("Invalid member session; log in again")


def sanitized(value, secrets):
    if isinstance(value, str):
        return redact_value(value, secrets)
    if isinstance(value, list):
        return [sanitized(v, secrets) for v in value]
    if isinstance(value, dict):
        return {redact_value(k, secrets): sanitized(v, secrets) for k, v in value.items()}
    return value


class Client:
    def __init__(self, url, token=None, secrets=()):
        self.url = service_url(url)
        self.token = token
        self.secrets = [*secrets, *([token] if token else [])]

    def request(self, method, path, *, body=None, idem=None, files=None, form=None, binary=False):
        headers = {"X-Requested-With": "harbor-helper"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if idem:
            headers["Idempotency-Key"] = idem
        try:
            with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = client.request(
                    method,
                    self.url + "/api/v1" + path,
                    headers=headers,
                    json=body,
                    files=files,
                    data=form,
                )
        except httpx.RequestError:
            raise RemoteError(
                "Service unavailable; no local fallback. Retry the same idempotency key for writes"
            ) from None
        if not 200 <= response.status_code < 300:
            try:
                value = response.json()
            except ValueError:
                value = {}
            code = value.get("code", "remote_error") if isinstance(value, dict) else "remote_error"
            message = (
                value.get("message", "Service request failed")
                if isinstance(value, dict)
                else "Service request failed"
            )
            request_id = value.get("request_id") if isinstance(value, dict) else None
            detail = f"HTTP {response.status_code} {str(code)[:128]}: {str(message)[:2048]}"
            action = value.get("action") if isinstance(value, dict) else None
            if isinstance(action, str) and action:
                detail += f"; action={redact_value(action, self.secrets)[:128]}"
            if request_id:
                detail += f" (request {str(request_id)[:128]})"
            raise RemoteError(redact_value(detail, self.secrets))
        if binary:
            return response.content
        try:
            return sanitized(response.json(), self.secrets)
        except ValueError:
            raise RemoteError("Invalid service response; no local fallback") from None


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
        (root / ("receipt-" + name + ".json")).unlink(missing_ok=True)
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
        (root / ("receipt-" + name + ".json")).unlink(missing_ok=True)
        # Keep the selected marker: ordinary commands must not silently become local.
    return {
        "profile": name,
        "url": profile["url"],
        "logged_in": False,
        "detail": "Local profile removed; revoke automation credentials in the website. Accepted experiments continue",
    }


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise RemoteError("Invalid service record identifier")
    return quote(value, safe="")


def write_request(name, profile, client, path, body, idem=None):
    idem = idem or uuid.uuid4().hex
    from harbor_helper.security.access_tokens import ACCESS_TOKEN_TEXT

    text = json.dumps([body, idem])
    if ACCESS_TOKEN_TEXT.search(text) or (client.token and client.token in text):
        raise RemoteError("Access credential plaintext forbidden in request/key")
    if not 1 <= len(idem) <= 128 or any(ord(c) < 33 or ord(c) > 126 for c in idem):
        raise RemoteError("Idempotency key must be 1–128 visible ASCII characters")
    with profile_lock() as root:
        secure_write(
            root / ("receipt-" + name + ".json"),
            {
                "url": profile["url"],
                "user_id": profile["user"].get("id"),
                "path": path,
                "body": body,
                "idempotency_key": idem,
            },
        )
    print(f"Idempotency-Key: {idem}; use service retry for this same operation", file=sys.stderr)
    return client.request("POST", path, body=body, idem=idem)


def upload_bundle(client, bundle, *, path_url="/bundles", metadata=None, idem=None):
    path = Path(bundle).expanduser()
    if path.is_dir():
        from harbor_helper.execution.runs import check_bundle

        check_bundle(path, client.token)
        with tempfile.TemporaryFile() as stream:
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                for file in sorted(path.rglob("*")):
                    if file.is_file():
                        archive.write(file, file.relative_to(path).as_posix())
            stream.seek(0)
            return client.request(
                "POST",
                path_url,
                files={"file": ("bundle.zip", stream, "application/zip")},
                form={"metadata": json.dumps(metadata)} if metadata is not None else None,
                idem=idem,
            )
    with path.open("rb") as stream:
        return client.request(
            "POST",
            path_url,
            files={"file": ("bundle.zip", stream, "application/zip")},
            form={"metadata": json.dumps(metadata)} if metadata is not None else None,
            idem=idem,
        )


def dispatch(args, name):
    profile, client = connection(name)
    cmd = args.command
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
            return client.request("GET", "/machine/runs/" + identifier(args.run_id) + "/report")
        if operation == "recover":
            return write_request(
                name,
                profile,
                client,
                "/submissions/" + identifier(args.submission_id) + "/retry",
                {},
                args.idempotency_key,
            )
        if operation == "retry":
            receipt = secure_read(remote_root() / ("receipt-" + name + ".json"))
            if receipt.get("url") != profile["url"] or receipt.get("user_id") != profile[
                "user"
            ].get("id"):
                raise RemoteError("Saved operation belongs to another service/member")
            path = receipt.get("path", "")
            if not re.fullmatch(
                r"/submissions|/submissions/[A-Za-z0-9_.-]+/retry|/runs/[A-Za-z0-9_.-]+/(?:rerun|retry)",
                path,
            ):
                raise RemoteError("Invalid saved operation")
            return write_request(
                name, profile, client, path, receipt["body"], receipt["idempotency_key"]
            )
    if cmd == "attachments":
        action = args.attachment_command
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
        if action == "register":
            return client.request(
                "POST",
                "/attachments/register",
                idem=args.idempotency_key,
                body={
                    "bundle_id": args.bundle_id,
                    "name": args.name,
                    "description": args.description,
                },
            )
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
        if args.bundle:
            body["bundle_id"] = upload_bundle(client, args.bundle)["id"]
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
            return value["text"]
        if cmd == "cancel":
            return client.request("POST", path + "/cancel", body={})
        if cmd == "artifacts":
            return client.request("GET", path)["artifacts"]
        if cmd == "download":
            content = client.request(
                "GET", path + "/artifacts/" + identifier(args.file_id), binary=True
            )
            output = Path(args.output).expanduser()
            fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as file:
                file.write(content)
            return {
                "run_id": args.run_id,
                "file_id": args.file_id,
                "output": str(output),
                "bytes": len(content),
            }
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
