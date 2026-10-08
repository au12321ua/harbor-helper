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

from harbor_helper.auth import secure_read, secure_write
from harbor_helper.credentials import redact_value


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

    def request(self, method, path, *, body=None, idem=None, files=None, binary=False):
        headers = {"X-Requested-With": "harbor-helper"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if idem:
            headers["Idempotency-Key"] = idem
        try:
            with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = client.request(
                    method, self.url + "/api/v1" + path, headers=headers, json=body, files=files
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


def connection(name):
    profile = load_profile(name)
    return profile, Client(profile["url"], profile["token"])


def logout(name):
    with profile_lock() as root:
        profile, client = connection(name)
        client.request("POST", "/auth/logout", body={})
        (root / "profiles" / (name + ".json")).unlink()
        (root / ("receipt-" + name + ".json")).unlink(missing_ok=True)
        # Keep the selected marker: ordinary commands must not silently become local.
    return {
        "profile": name,
        "url": profile["url"],
        "logged_in": False,
        "detail": "Member session revoked; accepted experiments continue. Log in or use --local explicitly",
    }


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise RemoteError("Invalid service record identifier")
    return quote(value, safe="")


def write_request(name, profile, client, path, body, idem=None):
    idem = idem or uuid.uuid4().hex
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


def upload_bundle(client, bundle):
    path = Path(bundle).expanduser()
    if path.is_dir():
        from harbor_helper.runs import check_bundle

        check_bundle(path)
        with tempfile.TemporaryFile() as stream:
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                for file in sorted(path.rglob("*")):
                    if file.is_file():
                        archive.write(file, file.relative_to(path).as_posix())
            stream.seek(0)
            return client.request(
                "POST", "/bundles", files={"file": ("bundle.zip", stream, "application/zip")}
            )
    with path.open("rb") as stream:
        return client.request(
            "POST", "/bundles", files={"file": ("bundle.zip", stream, "application/zip")}
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
        if operation == "retry":
            receipt = secure_read(remote_root() / ("receipt-" + name + ".json"))
            if receipt.get("url") != profile["url"] or receipt.get("user_id") != profile[
                "user"
            ].get("id"):
                raise RemoteError("Saved operation belongs to another service/member")
            path = receipt.get("path", "")
            if not re.fullmatch(r"/submissions|/runs/[A-Za-z0-9_.-]+/rerun", path):
                raise RemoteError("Invalid saved operation")
            return write_request(
                name, profile, client, path, receipt["body"], receipt["idempotency_key"]
            )
    if cmd in {"catalog", "usage", "list"}:
        return client.request(
            "GET", {"catalog": "/catalog", "usage": "/usage", "list": "/runs"}[cmd]
        )
    if cmd == "submit":
        if args.model or args.preset not in {None, "model", "oracle"}:
            raise RemoteError(
                "Remote submit selects --model-profile, not personal --model/local presets"
            )
        body = {
            k: getattr(args, k)
            for k in ("dataset", "agent", "attempts", "concurrency", "wall_seconds", "task")
            if getattr(args, k, None) is not None
        }
        if args.agent == "oracle" or args.preset == "oracle":
            body["agent"] = "oracle"
        elif not args.model_profile:
            raise RemoteError("Choose --model-profile from catalog (or explicitly --agent oracle)")
        if args.model_profile:
            body["model_profile"] = args.model_profile
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
    if cmd in {"status", "logs", "report", "cancel", "rerun", "artifacts", "download"}:
        path = "/runs/" + identifier(args.run_id)
        if cmd == "status":
            return client.request("GET", path)
        if cmd == "rerun":
            return write_request(name, profile, client, path + "/rerun", {}, args.idempotency_key)
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
    raise RemoteError(
        "This command is local-only; use --local explicitly, or service login for remote member access"
    )


def render(command, value, json_output=False):
    from harbor_helper.presentation import render as local_render

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
    elif command in {"submit", "rerun"}:
        local_render("submission", value)
        print(f"Next: harbor-helper status {value['id']}")
    elif command == "artifacts":
        from rich.console import Console

        Console(markup=False, highlight=False).print(value)
    else:
        local_render(command, value)
