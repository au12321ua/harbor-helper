import uuid

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from harbor_helper.security.credentials import redact_value
from harbor_helper.service import machine
from harbor_helper.service.application import Application
from harbor_helper.service.http.dependencies import token
from harbor_helper.service.primitives import LIMITS, ServiceError


def register(app, deps):
    def failure(request, code, message, status, operation_id=None):
        return JSONResponse(
            {
                "operation_id": operation_id,
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
        request.state.request_id = uuid.uuid4().hex
        from harbor_helper.service.history import REQUEST_ID

        REQUEST_ID.set(request.state.request_id)
        if deps.application is None and (deps.store.root / "service.json").exists():
            deps.application = Application(deps.store)
        if (
            request.url.path.startswith("/api/")
            and deps.application is None
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
                    and int(size)
                    > (deps.data.limits() if deps.data else LIMITS)["max_upload_bytes"] + 65536
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
                (deps.data.limits() if deps.data else LIMITS)["max_upload_bytes"] + 65536
                if request.headers.get("content-type", "").startswith("multipart/form-data")
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
            with deps.data.store.connect() as db:
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
        return failure(request, error.code, str(error), error.status, error.operation_id)

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
