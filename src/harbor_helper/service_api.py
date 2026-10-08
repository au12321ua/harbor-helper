"""One HTTP application: invited team API and packaged React assets."""

import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Header, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, SecretStr
from starlette.exceptions import HTTPException

from harbor_helper.service_app import Application, admin, public_submission, safe_view
from harbor_helper.service_data import ServiceError


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: SecretStr


class Account(Login):
    role: str = "member"


class Credential(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
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


def create_app(root, *, start_scheduler=True):
    application = Application(root)
    data = application.data

    @asynccontextmanager
    async def lifespan(app):
        if start_scheduler:
            from harbor_helper.runs import ensure_supervisor

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
            },
            status_code=status,
        )

    @app.middleware("http")
    async def boundary(request, call_next):
        request.state.request_id = uuid.uuid4().hex
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
                too_large = size and int(size) > data.limits()["max_upload_bytes"] + 65536
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
                data.limits()["max_upload_bytes"] + 65536
                if request.url.path == "/api/v1/bundles"
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
        return data.actor(token(request))

    def administrator(user: Annotated[dict, Depends(actor)]):
        admin(user)
        return user

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
        return application.catalog()

    @app.get("/api/v1/usage")
    def usage(user: Annotated[dict, Depends(actor)]):
        return application.usage()

    @app.get("/api/v1/runs")
    def runs(user: Annotated[dict, Depends(actor)]):
        return application.runs()

    @app.post("/api/v1/submissions", status_code=202)
    def submit(
        body: dict,
        user: Annotated[dict, Depends(actor)],
        idempotency_key: str | None = Header(default=None),
    ):
        return application.accept(user, body, idempotency_key)

    @app.get("/api/v1/submissions/{submission_id}")
    def submission(submission_id: str, user: Annotated[dict, Depends(actor)]):
        return public_submission(data.submission(submission_id))

    @app.post("/api/v1/submissions/{submission_id}/cancel")
    def cancel_submission(submission_id: str, user: Annotated[dict, Depends(actor)]):
        return application.cancel_submission(user, submission_id)

    @app.get("/api/v1/runs/{run_id}")
    def run(run_id: str, user: Annotated[dict, Depends(actor)]):
        return application.detail(run_id)

    @app.get("/api/v1/runs/{run_id}/logs")
    def logs(run_id: str, user: Annotated[dict, Depends(actor)]):
        return application.logs(run_id)

    @app.get("/api/v1/runs/{run_id}/report")
    def report(run_id: str, user: Annotated[dict, Depends(actor)]):
        return application.safe_report(run_id)

    @app.post("/api/v1/runs/{run_id}/cancel")
    def cancel(run_id: str, user: Annotated[dict, Depends(actor)]):
        return application.cancel_run(user, run_id)

    @app.post("/api/v1/runs/{run_id}/rerun", status_code=202)
    def rerun(
        run_id: str,
        user: Annotated[dict, Depends(actor)],
        idempotency_key: str | None = Header(default=None),
    ):
        return application.accept(user, {}, idempotency_key, parent=run_id)

    @app.post("/api/v1/compare")
    def compare(body: dict, user: Annotated[dict, Depends(actor)]):
        from harbor_helper.reports import compare

        if set(body) != {"left", "right"}:
            raise ServiceError("invalid_compare", "Choose left and right experiments")
        reports = tuple(application.safe_report(body[k]) for k in ("left", "right"))
        if any(r is None for r in reports):
            raise ServiceError("report_pending", "Both published reports are required", 409)
        return safe_view(
            compare(application.store, body["left"], body["right"], published_reports=reports)
        )

    @app.post("/api/v1/bundles", status_code=201)
    def upload(file: Annotated[UploadFile, File()], user: Annotated[dict, Depends(actor)]):
        return application.upload_bundle(file.file)

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
                body.id, body.provider_id, body.label, body.key.get_secret_value()
            )
            data.event(user, "add_credential", body.id)
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

    static = Path(__file__).parent / "static"
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
