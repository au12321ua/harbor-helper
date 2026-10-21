"""Public synchronous team-service SDK. No local execution or persistent request journal."""

import fcntl
import json
import os
import re
import stat
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

from harbor_helper.security.credentials import redact_value
from harbor_helper.security.files import secure_read


class RemoteError(ValueError):
    """Structured transport, local-boundary or service error; safe to serialize."""

    def __init__(self, message, *, status=None, fields=None, idem=None):
        super().__init__(message)
        self.status = status
        self.fields = {
            "code": "client_error",
            "message": message,
            **(fields or {}),
            "http_status": status,
        }
        if idem:
            self.fields["idempotency_key"] = idem
        self.operation_id = self.fields.get("operation_id")
        self.idempotency_key = self.fields.get("idempotency_key")
        for key, value in self.fields.items():
            setattr(self, key, value)

    def as_dict(self):
        return dict(self.fields)


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
        if idem is not None:
            from harbor_helper.security.access_tokens import ACCESS_TOKEN_TEXT

            if (
                not isinstance(idem, str)
                or not 1 <= len(idem) <= 128
                or any(ord(c) < 33 or ord(c) > 126 for c in idem)
            ):
                raise RemoteError("Invalid idempotency key")
            if ACCESS_TOKEN_TEXT.search(idem) or (self.token and self.token in idem):
                raise RemoteError("Access credential plaintext forbidden in key")
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
                "Service unavailable; no local fallback; retry the original key",
                idem=idem,
                fields={
                    "code": "communication_error",
                    "retryable": True,
                    "action": "retry_same_request",
                },
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
            raise RemoteError(
                redact_value(detail, self.secrets),
                status=response.status_code,
                fields=sanitized(value, self.secrets) if isinstance(value, dict) else {},
                idem=idem,
            )
        if binary:
            return response.content
        try:
            return sanitized(response.json(), self.secrets)
        except ValueError:
            raise RemoteError(
                "Invalid service response; no local fallback",
                fields={"code": "invalid_response"},
                idem=idem,
            ) from None

    @classmethod
    def from_profile(cls, name):
        profile = load_profile(name)
        return cls(profile["url"], profile["token"])

    def discover(self):
        return self.request("GET", "/machine/discovery")

    def list_tasks(self, dataset_id, offset=0, limit=100):
        return self.request(
            "GET",
            "/machine/datasets/" + identifier(dataset_id) + f"/tasks?offset={offset}&limit={limit}",
        )

    def list_attachments(self):
        return self.request("GET", "/attachments")

    def list_requests(self):
        return self.request("GET", "/management/requests")

    def rename_group(self, group_id, name):
        return self.request(
            "PATCH", "/management/groups/" + identifier(group_id), body={"name": name}
        )

    def register_dataset(self, name, reference):
        return self.request(
            "POST", "/admin/catalog/dataset", body={"name": name, "reference": reference}
        )

    def list_datasets(self):
        return self.request("GET", "/management/datasets")

    def dataset_versions(self, dataset_id):
        return self.request("GET", "/management/datasets/" + identifier(dataset_id) + "/versions")

    def preview_dataset(self, dataset_id, digest):
        return self.request(
            "POST",
            "/management/datasets/" + identifier(dataset_id) + "/preview",
            body={"digest": digest},
        )

    def confirm_dataset(self, preview_id):
        return self.request("POST", "/management/datasets/confirm", body={"preview_id": preview_id})

    def set_dataset_default(self, dataset_id, version_id, team_default=False):
        return self.request(
            "PUT",
            "/management/datasets/" + identifier(dataset_id) + "/default",
            body={"version_id": version_id, "team_default": team_default},
        )

    def merge_datasets_preview(self, source, target):
        return self.request(
            "POST", "/management/dataset-merge/preview", body={"source": source, "target": target}
        )

    def merge_datasets(self, source, target, revision, parameter_choices=None):
        return self.request(
            "POST",
            "/management/dataset-merge",
            body={
                "source": source,
                "target": target,
                "revision": revision,
                "parameter_choices": parameter_choices or {},
            },
        )

    def check_dataset_parameters(self, dataset_id, version_id=None, task_names=None):
        body = {"version_id": version_id}
        if task_names is not None:
            body["task_names"] = task_names
        return self.request(
            "POST", "/admin/datasets/" + identifier(dataset_id) + "/author-inputs/check", body=body
        )

    def save_dataset_parameters(self, dataset_id, values, version_id=None):
        return self.request(
            "PUT",
            "/admin/datasets/" + identifier(dataset_id) + "/author-inputs",
            body={"version_id": version_id, "values": values},
        )

    def list_recycle(self):
        return self.request("GET", "/management/recycle")

    def preview_recycle(self, kind, object_id):
        return self.request(
            "POST", "/management/recycle/preview", body={"kind": kind, "object_id": object_id}
        )

    def recycle(self, items):
        return self.request("POST", "/management/recycle", body={"items": items})

    def restore(self, event_id):
        return self.request(
            "POST", "/management/recycle/" + identifier(event_id) + "/restore", body={}
        )

    def purge(self, event_id, idempotency_key):
        return self.write(
            "/management/recycle/" + identifier(event_id) + "/purge", {}, idempotency_key
        )

    def fetch_attachment(self, version_id, output):
        return self.download("/attachment-versions/" + identifier(version_id) + "/download", output)

    def history(self, **filters):
        from urllib.parse import urlencode

        return self.request(
            "GET", "/operations?" + urlencode({k: v for k, v in filters.items() if v is not None})
        )

    def lookup_by_key(self, operation, key):
        return self.history(mine="true", operation=operation, key=key)

    def write(self, path, body, idempotency_key=None):
        idem = idempotency_key or uuid.uuid4().hex
        from harbor_helper.security.access_tokens import ACCESS_TOKEN_TEXT

        text = json.dumps([body, idem])
        if ACCESS_TOKEN_TEXT.search(text) or (self.token and self.token in text):
            raise RemoteError("Access credential plaintext forbidden in request/key")
        if (
            not isinstance(idem, str)
            or not 1 <= len(idem) <= 128
            or any(ord(c) < 33 or ord(c) > 126 for c in idem)
        ):
            raise RemoteError("Idempotency key must be 1–128 visible ASCII characters")
        result = self.request("POST", path, body=body, idem=idem)
        return {**result, "idempotency_key": idem}

    def submit(self, body, idempotency_key=None):
        return self.write("/submissions", body, idempotency_key)

    def rerun(self, run_id, idempotency_key=None):
        return self.write("/runs/" + identifier(run_id) + "/rerun", {}, idempotency_key)

    def retry(self, run_id, body=None, idempotency_key=None):
        return self.write("/runs/" + identifier(run_id) + "/retry", body or {}, idempotency_key)

    def recover(self, submission_id, idempotency_key=None):
        return self.write(
            "/submissions/" + identifier(submission_id) + "/retry", {}, idempotency_key
        )

    def cancel(self, record_id):
        kind = "submissions" if record_id.startswith("sub-") else "runs"
        return self.request("POST", "/" + kind + "/" + identifier(record_id) + "/cancel", body={})

    def get_state(self, record_id):
        kind = "submissions" if record_id.startswith("sub-") else "runs"
        return self.request("GET", "/" + kind + "/" + identifier(record_id))

    def get_report(self, run_id):
        return self.request("GET", "/runs/" + identifier(run_id) + "/report")

    def compare(self, left, right):
        return self.request("POST", "/compare", body={"left": left, "right": right})

    def get_logs(self, run_id):
        return self.request("GET", "/runs/" + identifier(run_id) + "/logs")

    def get_artifacts(self, run_id):
        return self.get_state(run_id)["artifacts"]

    def fetch_artifact(self, run_id, file_id, output):
        return self.download(
            "/runs/" + identifier(run_id) + "/artifacts/" + identifier(file_id), output
        )

    def evidence_manifest(self, run_id):
        return self.request("GET", "/runs/" + identifier(run_id) + "/evidence")

    def create_attachment(self, bundle, name, description="", idempotency_key=None):
        return upload_bundle(
            self,
            bundle,
            path_url="/attachments",
            metadata={"name": name, "description": description},
            idem=idempotency_key or uuid.uuid4().hex,
        )

    def derive_attachment(
        self, bundle, source_version_id, name, description="", idempotency_key=None
    ):
        return upload_bundle(
            self,
            bundle,
            path_url="/attachment-versions/" + identifier(source_version_id) + "/derive",
            metadata={"name": name, "description": description},
            idem=idempotency_key or uuid.uuid4().hex,
        )

    def publish_attachment(self, bundle, attachment_id, notes="", idempotency_key=None):
        return upload_bundle(
            self,
            bundle,
            path_url="/attachments/" + identifier(attachment_id) + "/versions",
            metadata={"notes": notes},
            idem=idempotency_key or uuid.uuid4().hex,
        )

    def fetch_evidence(self, run_id, output, file_id=None):
        path = (
            "/runs/"
            + identifier(run_id)
            + "/evidence/"
            + ("files/" + identifier(file_id) if file_id else "package")
        )
        return self.download(path, output)

    def download(self, path, output):
        import hashlib

        output = Path(output).absolute()
        created = False
        try:
            with (
                httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client,
                client.stream(
                    "GET",
                    self.url + "/api/v1" + path,
                    headers={"Authorization": "Bearer " + (self.token or "")},
                ) as response,
            ):
                if response.status_code != 200:
                    response.read()
                    try:
                        fields = sanitized(response.json(), self.secrets)
                    except ValueError:
                        fields = {}
                    raise RemoteError(
                        "Download rejected", status=response.status_code, fields=fields
                    )
                fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                created = True
                size, sha = 0, hashlib.sha256()
                with os.fdopen(fd, "wb") as target:
                    for chunk in response.iter_bytes(65536):
                        target.write(chunk)
                        sha.update(chunk)
                        size += len(chunk)
                expected = response.headers.get("X-Content-SHA256")
                length = response.headers.get("Content-Length")
                if (length is not None and int(length) != size) or (
                    expected and expected != sha.hexdigest()
                ):
                    raise RemoteError("Download incomplete", fields={"code": "download_incomplete"})
            return {"path": str(output), "bytes": size, "sha256": sha.hexdigest()}
        except BaseException as error:
            if created:
                output.unlink(missing_ok=True)
            if isinstance(error, httpx.RequestError):
                raise RemoteError(
                    "Download interrupted",
                    fields={"code": "communication_error", "retryable": True},
                ) from None
            raise


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise RemoteError("Invalid service record identifier")
    return quote(value, safe="")


def upload_bundle(client, bundle, *, path_url, metadata, idem):
    path = Path(bundle).expanduser()
    if path.is_dir():
        from harbor_helper.execution.bundles import check_bundle

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
                form={"metadata": json.dumps(metadata)},
                idem=idem,
            )
    with path.open("rb") as stream:
        return client.request(
            "POST",
            path_url,
            files={"file": ("bundle.zip", stream, "application/zip")},
            form={"metadata": json.dumps(metadata)},
            idem=idem,
        )
