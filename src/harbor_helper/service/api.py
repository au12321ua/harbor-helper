"""One HTTP application: invited team API and packaged React assets."""

import json
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError
from starlette.exceptions import HTTPException

from harbor_helper.persistence.store import Store
from harbor_helper.security.credentials import redact_value
from harbor_helper.service import access, machine
from harbor_helper.service.application import Application, admin, public_submission, safe_view
from harbor_helper.service.attachment_contracts import (
    AttachmentCreate,
    AttachmentPublish,
    AttachmentRegister,
    AttachmentResult,
    AttachmentUpdate,
    AttachmentVersionUpdate,
)
from harbor_helper.service.data import LIMITS, ServiceData, ServiceError
from harbor_helper.service.machine import AccessIssue, MachineState, RetryInput, SubmissionInput
from harbor_helper.service.setup import protected_file


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: SecretStr


class Account(Login):
    role: str = "member"


class Credential(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = ""
    provider_id: str
    label: str
    key: SecretStr


class Rotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: SecretStr


def token(request):
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get("hh_session", "")


class Setup(Login):
    setup_token: SecretStr
    team_name: str = "团队实验室"


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr
    password: SecretStr


def create_app(root, *, start_scheduler=True, setup_token_file=None, master_key_file=None):
    store = Store(root)
    private = store.root.parent / ("." + store.root.name + "-deployment")
    setup_token_file = Path(setup_token_file or private / "setup-token")
    master_key_file = Path(master_key_file or private / "master-key")
    with store.control():
        application = Application(store) if (store.root / "service.json").exists() else None
        if application is None:
            if setup_token_file.resolve().is_relative_to(store.root):
                raise ServiceError("setup_protection", "Bootstrap token must be outside state", 503)
            protected_file(setup_token_file, create=True)
    data = application.data if application else None

    @asynccontextmanager
    async def lifespan(app):
        if start_scheduler and application is not None:
            from harbor_helper.execution.runs import ensure_supervisor

            with application.store.control():
                ensure_supervisor(application.store)
        yield
        # Queue/workers deliberately survive an API restart.

    app = FastAPI(
        title="Harbor Helper",
        version="1",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.application = application

    def failure(request, code, message, status):
        return JSONResponse(
            {
                "code": code,
                "message": message,
                "request_id": getattr(request.state, "request_id", uuid.uuid4().hex),
                "retryable": status in {429, 503},
                "action": machine.error_action(code, status),
                "wait_seconds": None,
                "wait_known": False,
                "related_ids": {
                    k: redact_value(v, [token(request)])
                    for k, v in request.path_params.items()
                    if k in {"run_id", "submission_id"}
                },
                "poll_after_seconds": 2 if code in {"report_pending", "audit_pending"} else None,
            },
            status_code=status,
        )

    @app.middleware("http")
    async def boundary(request, call_next):
        nonlocal application, data
        request.state.request_id = uuid.uuid4().hex
        if application is None and (store.root / "service.json").exists():
            application = Application(store)
            data = application.data
            app.state.application = application
        if (
            request.url.path.startswith("/api/")
            and application is None
            and request.url.path not in {"/api/v1/setup", "/api/v1/health"}
        ):
            return failure(
                request, "service_not_initialized", "Complete protected website setup", 503
            )
        if request.url.path.startswith("/api/"):
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                origin = request.headers.get("origin")
                expected = str(request.base_url).rstrip("/")
                if origin and origin.rstrip("/") != expected:
                    return failure(
                        request, "invalid_origin", "Cross-origin writes are not allowed", 403
                    )
                if request.headers.get("x-requested-with") != "harbor-helper":
                    return failure(
                        request, "request_header", "X-Requested-With: harbor-helper required", 403
                    )
            size = request.headers.get("content-length")
            try:
                too_large = (
                    size
                    and int(size) > (data.limits() if data else LIMITS)["max_upload_bytes"] + 65536
                )
            except ValueError:
                too_large = True
            if too_large:
                return failure(
                    request, "request_limit", "Request exceeds configured size limit", 413
                )
        if request.url.path.startswith("/api/") and request.method not in {
            "GET",
            "HEAD",
            "OPTIONS",
        }:
            maximum = (
                (data.limits() if data else LIMITS)["max_upload_bytes"] + 65536
                if request.url.path == "/api/v1/bundles"
                or request.headers.get("content-type", "").startswith("multipart/form-data")
                else 65536
            )
            received, parts = 0, []
            async for chunk in request.stream():
                received += len(chunk)
                if received > maximum:
                    return failure(
                        request, "request_limit", "Request exceeds configured size limit", 413
                    )
                parts.append(chunk)
            # Starlette's cached request forwards this bounded body to route parsing.
            request._body = b"".join(parts)
        response = await call_next(request)
        user = getattr(request.state, "actor", None)
        if user and request.method not in {"GET", "HEAD", "OPTIONS"} and response.status_code < 400:
            with data.store.connect() as db:
                db.execute(
                    "INSERT INTO access_events(user_id,access_credential_id,action,object_id,time) VALUES(?,?,?,?,?)",
                    (
                        user["id"],
                        user.get("access_credential_id"),
                        request.scope["route"].endpoint.__name__,
                        next(iter(request.path_params.values()), ""),
                        __import__("time").time(),
                    ),
                )
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ServiceError)
    async def service_error(request, error):
        return failure(request, error.code, str(error), error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # Never echo Pydantic inputs, especially keys/passwords.
        return failure(request, "invalid_request", "Invalid request fields or value types", 422)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return failure(
            request,
            "not_found" if error.status_code == 404 else "http_error",
            "API or resource not available",
            error.status_code,
        )

    @app.exception_handler(ValueError)
    async def value_error(request, error):
        if str(error).startswith("Unknown run:"):
            return failure(request, "run_missing", "Experiment not found", 404)
        return failure(
            request, "invalid_operation", "Invalid configuration or experiment reference", 422
        )

    @app.exception_handler(Exception)
    async def internal_error(request, error):
        return failure(
            request, "service_unavailable", "Operation could not be completed safely", 503
        )

    def actor(request: Request):
        user = data.actor(token(request))
        machine.authorize(user, request.scope["route"].endpoint.__name__)
        request.state.actor = user
        return user

    def administrator(user: Annotated[dict, Depends(actor)]):
        admin(user)
        return user

    @app.post("/api/v1/access-credentials", status_code=201)
    def issue_access(request: Request, body: AccessIssue, user: Annotated[dict, Depends(actor)]):
        return access.issue(
            data,
            user,
            body.name,
            body.current_password.get_secret_value(),
            body.scopes,
            body.expires,
            access_value=token(request),
        )

    @app.get("/api/v1/access-credentials")
    def list_access(user: Annotated[dict, Depends(actor)]):
        return access.listing(data, user)

    @app.get("/api/v1/admin/access-credentials")
    def list_all_access(user: Annotated[dict, Depends(administrator)]):
        return access.listing(data, user, all_users=True)

    @app.post("/api/v1/access-credentials/{credential_id}/revoke")
    def revoke_access(credential_id: str, user: Annotated[dict, Depends(actor)]):
        return access.revoke(data, user, credential_id)

    @app.get("/api/v1/health")
    def health():
        from harbor_helper.service.admission import readiness as observe

        try:
            ready = application is not None and observe(application)["accepting"]
        except (ValueError, OSError, TypeError):
            ready = False
        return {"alive": True, "ready": ready}

    @app.get("/api/v1/readiness", response_model=machine.Readiness)
    def readiness(user: Annotated[dict, Depends(actor)]):
        from harbor_helper.service.admission import readiness as observe

        return observe(application, user["id"])

    @app.patch("/api/v1/admin/maintenance")
    def set_maintenance(
        request: Request, body: dict, user: Annotated[dict, Depends(administrator)]
    ):
        from harbor_helper.service.admission import set_maintenance as update

        if token(request) in json.dumps(body):
            raise ServiceError("maintenance_reason", "Notice must not contain credentials")
        with application.store.control():
            result = update(data, body)
            data.event(user, "set_maintenance", "admission")
            return result

    @app.get("/api/v1/machine/discovery", response_model=machine.Discovery)
    def discovery(user: Annotated[dict, Depends(actor)]):
        return machine.discovery(application, user)

    @app.get("/api/v1/machine/datasets/{dataset_id}/tasks", response_model=machine.TaskCatalog)
    def task_catalog(
        dataset_id: str, user: Annotated[dict, Depends(actor)], offset: int = 0, limit: int = 100
    ):
        if offset < 0 or not 1 <= limit <= 100:
            raise ServiceError("invalid_range", "offset >= 0; limit 1–100 required")
        value = data.object("dataset", dataset_id)
        tasks = value.get("tasks", [])
        # Use the verified metadata catalog; no task materialization or Hub download.
        return {
            "dataset_id": dataset_id,
            "version": value["version"],
            "status": value.get("status", "unknown"),
            "offset": offset,
            "tasks": [
                {k: t.get(k) for k in ("name", "package", "ref")}
                for t in tasks[offset : offset + limit]
            ],
            "next_offset": offset + limit if offset + limit < len(tasks) else None,
            "total": len(tasks),
        }

    @app.get(
        "/api/v1/submission-operations/{operation}/{key:path}",
        response_model=machine.Accepted,
        response_model_exclude_unset=True,
    )
    def lookup_submission(
        operation: machine.Operation, key: str, user: Annotated[dict, Depends(actor)]
    ):
        return machine.accepted_view(user, machine.lookup(application, user, operation, key))

    @app.get("/api/v1/machine/submissions/{submission_id}", response_model=MachineState)
    def machine_submission(submission_id: str, user: Annotated[dict, Depends(actor)]):
        return machine.submission_state(application, submission_id)

    @app.get("/api/v1/machine/runs/{run_id}", response_model=MachineState)
    def machine_run(run_id: str, user: Annotated[dict, Depends(actor)]):
        return machine.run_state(application, run_id)

    @app.get("/api/v1/machine/runs/{run_id}/report", response_model=machine.SafeReport)
    def machine_report(run_id: str, user: Annotated[dict, Depends(actor)]):
        state = machine.run_state(application, run_id)
        if state["report"]["state"] != "available":
            raise ServiceError("report_" + state["report"]["state"], state["report"]["reason"], 409)
        return machine.report_view(application.safe_report(run_id))

    @app.get("/api/v1/machine/schema")
    def machine_schema(user: Annotated[dict, Depends(actor)]):
        from fastapi.openapi.utils import get_openapi

        routes = [
            r
            for r in app.routes
            if getattr(r, "endpoint", None) and r.endpoint.__name__ in machine.SCHEMA_OPERATIONS
        ]
        schema = get_openapi(title="Harbor Helper member machine API", version="1.0", routes=routes)
        for model in (
            AttachmentCreate,
            AttachmentPublish,
            AttachmentRegister,
            machine.ErrorResponse,
        ):
            typed = model.model_json_schema(ref_template="#/components/schemas/{model}")
            definitions = typed.pop("$defs", {})
            schema.setdefault("components", {}).setdefault("schemas", {}).update(definitions)
            schema["components"]["schemas"][model.__name__] = typed
        embedded = {
            "create_attachment": "AttachmentCreate",
            "derive_attachment": "AttachmentCreate",
            "publish_attachment": "AttachmentPublish",
        }
        for route in routes:
            for method in route.methods:
                op = schema.get("paths", {}).get(route.path_format, {}).get(method.lower())
                if op is not None:
                    op["x-capability"] = machine.CAPABILITIES[route.endpoint.__name__]
                    op["security"] = [{"MemberBearer": []}]
                    op["x-operation"] = route.endpoint.__name__
                    if route.endpoint.__name__ in embedded:
                        op["x-metadata-schema"] = {
                            "$ref": "#/components/schemas/" + embedded[route.endpoint.__name__]
                        }
                    for status in ("401", "403", "404", "409", "422", "429", "503"):
                        op["responses"][status] = {
                            "description": "Safe machine error",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                                }
                            },
                        }
        schema.setdefault("components", {})["securitySchemes"] = {
            "MemberBearer": {"type": "http", "scheme": "bearer"}
        }
        return schema

    @app.get("/api/v1/setup")
    def setup_status():
        return {"initialized": (store.root / "service.json").exists()}

    @app.post("/api/v1/setup", status_code=201)
    def setup(body: Setup):
        nonlocal application, data
        if (store.root / "service.json").exists():
            raise ServiceError("already_initialized", "Website setup is already complete", 409)
        if not secrets.compare_digest(
            body.setup_token.get_secret_value(), protected_file(setup_token_file)
        ):
            raise ServiceError("setup_denied", "Deployment bootstrap credential required", 403)
        if not 1 <= len(body.team_name.strip()) <= 128:
            raise ServiceError("team_name", "Team name must be 1–128 characters")
        ServiceData.initialize(
            store, master_key_file, body.username, body.password.get_secret_value()
        )
        application = Application(store)
        data = application.data
        from harbor_helper.persistence.files import write_json

        write_json(store.root / "web.json", {"team_name": body.team_name.strip()})
        app.state.application = application
        if start_scheduler:
            from harbor_helper.execution.runs import ensure_supervisor

            with store.control():
                ensure_supervisor(store)
        return {"initialized": True}

    @app.post("/api/v1/auth/password")
    def password_change(body: PasswordChange, user: Annotated[dict, Depends(actor)]):
        session, _ = data.login(user["username"], body.current_password.get_secret_value())
        data.logout(session)
        data.update_user(user["id"], password=body.password.get_secret_value())
        return {"changed": True, "login_required": True}

    @app.post("/api/v1/auth/login")
    def login(body: Login, response: Response):
        value, user = data.login(body.username, body.password.get_secret_value())
        response.set_cookie(
            "hh_session", value, max_age=28800, httponly=True, samesite="strict", path="/"
        )
        return {"token": value, "user": user}

    @app.post("/api/v1/auth/logout")
    def logout(request: Request, response: Response, user: Annotated[dict, Depends(actor)]):
        data.logout(token(request))
        response.delete_cookie("hh_session", path="/")
        return {"logged_out": True, "tasks_continue": True}

    @app.get("/api/v1/me")
    def me(user: Annotated[dict, Depends(actor)]):
        return user

    @app.get("/api/v1/catalog")
    def catalog(user: Annotated[dict, Depends(actor)]):
        return (
            machine.discovery(application, user)
            if user.get("access_credential_id")
            else application.catalog(user["id"])
        )

    @app.get("/api/v1/usage")
    def usage(user: Annotated[dict, Depends(actor)]):
        return application.usage()

    @app.get("/api/v1/runs")
    def runs(user: Annotated[dict, Depends(actor)]):
        if user.get("access_credential_id"):
            with store.connect() as db:
                ids = [r[0] for r in db.execute("SELECT id FROM submissions ORDER BY created DESC")]
            return {
                "runs": [machine.run_state(application, r["id"]) for r in store.runs()],
                "submissions": [machine.submission_state(application, i) for i in ids],
            }
        return application.runs()

    @app.post(
        "/api/v1/submissions",
        status_code=202,
        response_model=machine.Accepted,
        response_model_exclude_unset=True,
    )
    def submit(
        request: Request,
        body: SubmissionInput,
        user: Annotated[dict, Depends(actor)],
        idempotency_key: str | None = Header(default=None),
    ):
        return machine.accepted_view(
            user,
            application.accept(
                user,
                body.model_dump(exclude_unset=True),
                idempotency_key,
                access_value=token(request),
            ),
        )

    @app.get("/api/v1/submissions/{submission_id}")
    def submission(submission_id: str, user: Annotated[dict, Depends(actor)]):
        return machine.accepted_view(user, public_submission(data.submission(submission_id)))

    @app.post(
        "/api/v1/submissions/{submission_id}/retry",
        status_code=202,
        response_model=machine.Accepted,
        response_model_exclude_unset=True,
    )
    def recover_submission(
        request: Request,
        submission_id: str,
        user: Annotated[dict, Depends(actor)],
        idempotency_key: str | None = Header(default=None),
        body: machine.EmptyInput | None = None,
    ):
        return machine.accepted_view(
            user,
            application.recover_submission(
                user, submission_id, idempotency_key, access_value=token(request)
            ),
        )

    @app.post(
        "/api/v1/submissions/{submission_id}/cancel",
        response_model=machine.Accepted,
        response_model_exclude_unset=True,
    )
    def cancel_submission(
        submission_id: str,
        user: Annotated[dict, Depends(actor)],
        body: machine.EmptyInput | None = None,
    ):
        return machine.accepted_view(user, application.cancel_submission(user, submission_id))

    @app.get("/api/v1/runs/{run_id}")
    def run(run_id: str, user: Annotated[dict, Depends(actor)]):
        return (
            machine.run_state(application, run_id)
            if user.get("access_credential_id")
            else application.detail(run_id)
        )

    @app.get("/api/v1/runs/{run_id}/report/download")
    def download_report(run_id: str, user: Annotated[dict, Depends(actor)]):
        report = application.safe_report(run_id)
        if report is not None and user.get("access_credential_id"):
            report = machine.report_view(report)
        if report is None:
            raise ServiceError("report_pending", "Report not available", 409)
        # run identifier is generated and resolved by Store; never an arbitrary filename.
        return Response(
            json.dumps(report, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{run_id}-report.json"'},
        )

    @app.get("/api/v1/runs/{run_id}/logs")
    def logs(run_id: str, user: Annotated[dict, Depends(actor)]):
        return application.logs(run_id)

    @app.get("/api/v1/runs/{run_id}/report")
    def report(run_id: str, user: Annotated[dict, Depends(actor)]):
        value = application.safe_report(run_id)
        return (
            machine.report_view(value)
            if value is not None and user.get("access_credential_id")
            else value
        )

    @app.post("/api/v1/runs/{run_id}/cancel", response_model=machine.CancelResult)
    def cancel(
        run_id: str, user: Annotated[dict, Depends(actor)], body: machine.EmptyInput | None = None
    ):
        return application.cancel_run(user, run_id)

    @app.post(
        "/api/v1/runs/{run_id}/rerun",
        status_code=202,
        response_model=machine.Accepted,
        response_model_exclude_unset=True,
    )
    def rerun(
        request: Request,
        run_id: str,
        user: Annotated[dict, Depends(actor)],
        idempotency_key: str | None = Header(default=None),
        body: machine.EmptyInput | None = None,
    ):
        return machine.accepted_view(
            user,
            application.accept(
                user, {}, idempotency_key, parent=run_id, access_value=token(request)
            ),
        )

    @app.post(
        "/api/v1/runs/{run_id}/retry",
        status_code=202,
        response_model=machine.Accepted,
        response_model_exclude_unset=True,
    )
    def retry_run(
        request: Request,
        run_id: str,
        body: RetryInput,
        user: Annotated[dict, Depends(actor)],
        idempotency_key: str | None = Header(default=None),
    ):
        return machine.accepted_view(
            user,
            application.accept(
                user,
                body.model_dump(exclude_unset=True),
                idempotency_key,
                parent=run_id,
                retry=True,
                access_value=token(request),
            ),
        )

    @app.post("/api/v1/compare")
    def compare(body: machine.CompareInput, user: Annotated[dict, Depends(actor)]):
        from harbor_helper.results.reports import compare

        body = body.model_dump()
        reports = tuple(application.safe_report(body[k]) for k in ("left", "right"))
        if any(r is None for r in reports):
            raise ServiceError("report_pending", "Both published reports are required", 409)
        value = safe_view(
            compare(application.store, body["left"], body["right"], published_reports=reports)
        )
        if user.get("access_credential_id"):
            value.pop("environment_observations", None)
            value["config_changes"] = {k: {"changed": True} for k in value["config_changes"]}
        return value

    @app.post("/api/v1/machine/compare", response_model=machine.Comparison)
    def machine_compare(body: machine.CompareInput, user: Annotated[dict, Depends(actor)]):
        value = compare(body, user)
        value.pop("environment_observations", None)
        value["config_changes"] = {k: {"changed": True} for k in value["config_changes"]}
        return value

    @app.post("/api/v1/bundles", status_code=201, response_model=machine.BundleResult)
    def upload(
        request: Request, file: Annotated[UploadFile, File()], user: Annotated[dict, Depends(actor)]
    ):
        return application.upload_bundle(file.file, access_value=token(request))

    @app.get("/api/v1/attachments", response_model=machine.AttachmentCatalog)
    def attachments(user: Annotated[dict, Depends(actor)]):
        return application.attachments.catalog()

    @app.get(
        "/api/v1/attachment-operations/{operation}/{key:path}", response_model=AttachmentResult
    )
    def attachment_lookup(operation: str, key: str, user: Annotated[dict, Depends(actor)]):
        return application.attachments.lookup(user, operation, key)

    def attachment_metadata(metadata, model):
        try:
            value = model.model_validate(json.loads(metadata)).model_dump()
        except (ValueError, ValidationError):
            raise ServiceError(
                "attachment_fields", "metadata must match the attachment operation"
            ) from None
        if not isinstance(value, dict):
            raise ServiceError("attachment_fields", "metadata must be a JSON object")
        return value

    @app.post("/api/v1/attachments", status_code=201, response_model=AttachmentResult)
    def create_attachment(
        request: Request,
        file: Annotated[UploadFile, File()],
        user: Annotated[dict, Depends(actor)],
        metadata: Annotated[str, Form()] = "{}",
        idempotency_key: str | None = Header(default=None),
    ):
        return application.attachments.write(
            user,
            "attachment_create",
            idempotency_key,
            attachment_metadata(metadata, AttachmentCreate),
            file.file,
            access_value=token(request),
        )

    @app.post(
        "/api/v1/attachments/{attachment_id}/versions",
        status_code=201,
        response_model=AttachmentResult,
    )
    def publish_attachment(
        request: Request,
        attachment_id: str,
        file: Annotated[UploadFile, File()],
        user: Annotated[dict, Depends(actor)],
        metadata: Annotated[str, Form()] = "{}",
        idempotency_key: str | None = Header(default=None),
    ):
        body = attachment_metadata(metadata, AttachmentPublish)
        if "attachment_id" in body:
            raise ServiceError("attachment_fields", "Target is supplied by path")
        return application.attachments.write(
            user,
            "attachment_publish",
            idempotency_key,
            {**body, "attachment_id": attachment_id},
            file.file,
            access_value=token(request),
        )

    @app.post(
        "/api/v1/attachment-versions/{version_id}/derive",
        status_code=201,
        response_model=AttachmentResult,
    )
    def derive_attachment(
        request: Request,
        version_id: str,
        file: Annotated[UploadFile, File()],
        user: Annotated[dict, Depends(actor)],
        metadata: Annotated[str, Form()] = "{}",
        idempotency_key: str | None = Header(default=None),
    ):
        body = attachment_metadata(metadata, AttachmentCreate)
        if "source_version_id" in body:
            raise ServiceError("attachment_fields", "Source is supplied by path")
        return application.attachments.write(
            user,
            "attachment_derive",
            idempotency_key,
            {**body, "source_version_id": version_id},
            file.file,
            access_value=token(request),
        )

    @app.post("/api/v1/attachments/register", status_code=201, response_model=AttachmentResult)
    def register_attachment(
        request: Request,
        body: AttachmentRegister,
        user: Annotated[dict, Depends(actor)],
        idempotency_key: str | None = Header(default=None),
    ):
        return application.attachments.write(
            user,
            "attachment_register",
            idempotency_key,
            body.model_dump(),
            access_value=token(request),
        )

    @app.patch("/api/v1/attachments/{attachment_id}", response_model=machine.Updated)
    def update_attachment(
        request: Request,
        attachment_id: str,
        body: AttachmentUpdate,
        user: Annotated[dict, Depends(actor)],
    ):
        return application.attachments.update(
            user, attachment_id, body.model_dump(exclude_unset=True), access_value=token(request)
        )

    @app.patch(
        "/api/v1/attachments/{attachment_id}/versions/{version_id}", response_model=machine.Updated
    )
    def update_attachment_version(
        request: Request,
        attachment_id: str,
        version_id: str,
        body: AttachmentVersionUpdate,
        user: Annotated[dict, Depends(actor)],
    ):
        return application.attachments.update(
            user, attachment_id, body.model_dump(), version_id, access_value=token(request)
        )

    @app.get("/api/v1/runs/{run_id}/artifacts/{file_id}")
    def artifact(run_id: str, file_id: str, user: Annotated[dict, Depends(actor)]):
        path = application.artifact_path(run_id, file_id)
        return FileResponse(
            path,
            media_type="application/octet-stream",
            filename=path.name,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{__import__('urllib.parse', fromlist=['quote']).quote(path.name)}"
            },
        )

    @app.delete("/api/v1/runs/{run_id}/artifacts/{file_id}")
    def delete_artifact(run_id: str, file_id: str, user: Annotated[dict, Depends(administrator)]):
        return application.delete_artifact(user, run_id, file_id)

    @app.get("/api/v1/admin/users")
    def users(user: Annotated[dict, Depends(administrator)]):
        return data.users()

    @app.post("/api/v1/admin/users", status_code=201)
    def add_user(body: Account, user: Annotated[dict, Depends(administrator)]):
        result = data.create_user(body.username, body.password.get_secret_value(), body.role)
        data.event(user, "create_account", result["id"])
        return result

    @app.patch("/api/v1/admin/users/{user_id}")
    def update_user(user_id: str, body: dict, user: Annotated[dict, Depends(administrator)]):
        if set(body) - {"enabled", "password"} or (
            "enabled" in body and type(body["enabled"]) is not bool
        ):
            raise ServiceError("invalid_account", "Supported account updates: enabled, password")
        result = data.update_user(user_id, **body)
        data.event(user, "update_account", user_id)
        return result

    @app.get("/api/v1/admin/docker")
    def docker_discovery(user: Annotated[dict, Depends(administrator)]):
        from harbor_helper.service.docker import discover_docker

        return discover_docker()

    @app.post("/api/v1/admin/datasets/{object_id}/author-inputs/check")
    def inspect_author_inputs(
        object_id: str, user: Annotated[dict, Depends(administrator)], body: dict | None = None
    ):
        if body is not None and set(body) - {"task_names"}:
            raise ServiceError("author_task_selection", "Only task_names may be specified")
        return application.configuration.inspect_author_parameters(
            object_id,
            task_names=body.get("task_names") if body and "task_names" in body else None,
            selection_supplied=bool(body is not None and "task_names" in body),
        )

    @app.put("/api/v1/admin/datasets/{object_id}/author-inputs")
    def save_author_inputs(
        object_id: str, body: dict, user: Annotated[dict, Depends(administrator)]
    ):
        if set(body) != {"values"}:
            raise ServiceError("author_input_invalid", "Use only the discovered values object")
        return application.configuration.save_author_parameters(object_id, body["values"])

    @app.post("/api/v1/admin/catalog/{kind}")
    def save_catalog(kind: str, body: dict, user: Annotated[dict, Depends(administrator)]):
        if kind != "dataset":
            raise ServiceError("catalog_kind", "Unknown catalog kind", 404)
        with store.control():
            result = application.configuration.save(kind, body)
            data.event(user, "save_" + kind, result["id"])
            return result

    @app.post("/api/v1/admin/catalog/{kind}/{object_id}/verify")
    def verify_catalog(kind: str, object_id: str, user: Annotated[dict, Depends(administrator)]):
        if kind != "dataset":
            raise ServiceError("catalog_kind", "Unknown catalog kind", 404)
        result = application.configuration.verify(kind, object_id)
        data.event(user, "verify_" + kind, object_id)
        return result

    @app.patch("/api/v1/admin/settings")
    def settings(body: dict, user: Annotated[dict, Depends(administrator)]):
        with store.control():
            return application.configuration.save_settings(body)

    @app.post("/api/v1/admin/hub")
    def hub(body: Rotation, user: Annotated[dict, Depends(administrator)]):
        with store.control():
            result = application.configuration.save_hub(body.key.get_secret_value())
            data.event(user, "rotate_hub", "team-source")
            return result

    @app.post("/api/v1/admin/hub/disable")
    def hub_disable(user: Annotated[dict, Depends(administrator)]):
        with store.control():
            result = application.configuration.save_hub(enabled=False)
            data.event(user, "disable_hub", "team-source")
            return result

    @app.get("/api/v1/admin/providers")
    def providers(user: Annotated[dict, Depends(administrator)]):
        return data.objects("provider")

    @app.post("/api/v1/admin/providers")
    def provider(body: dict, user: Annotated[dict, Depends(administrator)]):
        with application.store.control():
            result = data.save_object("provider", body)
            data.event(user, "save_provider", result["id"])
            return result

    @app.get("/api/v1/admin/model-profiles")
    def profiles(user: Annotated[dict, Depends(administrator)]):
        return data.objects("profile")

    @app.post("/api/v1/admin/model-profiles")
    def profile(body: dict, user: Annotated[dict, Depends(administrator)]):
        with application.store.control():
            result = data.save_object("profile", body)
            data.event(user, "save_model_profile", result["id"])
            return result

    @app.get("/api/v1/admin/credentials")
    def credentials(user: Annotated[dict, Depends(administrator)]):
        return data.credentials()

    @app.post("/api/v1/admin/credentials", status_code=201)
    def credential(body: Credential, user: Annotated[dict, Depends(administrator)]):
        with application.store.control():
            result = data.add_credential(
                body.id or uuid.uuid4().hex,
                body.provider_id,
                body.label,
                body.key.get_secret_value(),
            )
            data.event(user, "add_credential", result["id"])
            return result

    @app.post("/api/v1/admin/credentials/{credential_id}/rotate")
    def rotate(credential_id: str, body: Rotation, user: Annotated[dict, Depends(administrator)]):
        with application.store.control():
            old = data.credential(credential_id)
            result = data.add_credential(
                credential_id,
                old["provider_id"],
                old["label"],
                body.key.get_secret_value(),
                rotate=True,
            )
            data.prune_credentials()
            data.event(user, "rotate_credential", credential_id)
            return result

    @app.post("/api/v1/admin/credentials/{credential_id}/disable")
    def disable(credential_id: str, user: Annotated[dict, Depends(administrator)]):
        with application.store.control():
            result = data.disable_credential(credential_id)
            data.event(user, "disable_credential", credential_id)
            return result

    @app.get("/api/v1/admin/limits")
    def limits(user: Annotated[dict, Depends(administrator)]):
        return data.limits()

    @app.patch("/api/v1/admin/limits")
    def set_limits(body: dict, user: Annotated[dict, Depends(administrator)]):
        with application.store.control():
            result = data.set_limits(body)
            data.event(user, "set_limits", "global")
            return result

    static = Path(__file__).resolve().parents[1] / "static"
    if (static / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.get("/favicon.svg")
    def favicon():
        path = static / "favicon.svg"
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/svg+xml")

    @app.api_route(
        "/api/{missing:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE", "HEAD", "OPTIONS"]
    )
    def missing_api(missing: str):
        raise HTTPException(404)

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith(("api/", "assets/")) or path == "api" or "." in path:
            raise HTTPException(404)
        index = static / "index.html"
        if not index.is_file():
            raise ServiceError("frontend_not_built", "Build the packaged frontend first", 503)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app
