"""FastAPI application: envelope, errors, authentication and static web pages.

The same HTTP service serves the built web pages and the relative ``/api/v1``
API; TLS, proxies and domains belong to the deployment environment.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from maestro import __version__
from maestro.api import routes
from maestro.api.deps import new_request_id
from maestro.application import Maestro
from maestro.core import context
from maestro.core.errors import MaestroError

log = logging.getLogger(__name__)
STATIC = Path(__file__).resolve().parent.parent / "static"


def error_response(error: MaestroError, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=error.status,
        headers=error.headers,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "stage": error.stage,
                "field_errors": [
                    {k: v for k, v in vars(f).items() if v is not None} for f in error.field_errors
                ],
                "retryable": error.retryable,
                "suggested_actions": error.suggested_actions,
            },
            "meta": {"request_id": request_id},
        },
    )


def create_app(maestro: Maestro, *, run_worker: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        if maestro.worker is not None and run_worker:
            state = maestro.schema_state()
            if state["compatible"]:
                report = maestro.worker.start_epoch()
                if report["interrupted_runs"]:
                    log.warning("interrupted runs after restart: %s", report["interrupted_runs"])
                task = asyncio.create_task(maestro.worker.run_forever())
        app.state.worker_task = task
        try:
            yield
        finally:
            if task is not None:
                await maestro.worker.stop()
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(
        title="Maestro API",
        version=__version__,
        lifespan=lifespan,
        root_path=maestro.settings.root_path,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    app.state.maestro = maestro

    @app.middleware("http")
    async def request_ids(request: Request, call_next):
        request_id = new_request_id()
        request.state.request_id = request_id
        token = context.request_id.set(request_id)
        try:
            response = await call_next(request)
        finally:
            context.request_id.reset(token)
        response.headers["X-Request-Id"] = request_id
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(MaestroError)
    async def maestro_error(request: Request, error: MaestroError):
        return error_response(error, request.state.request_id)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        from maestro.core.errors import FieldError

        fields = [
            FieldError(
                "/" + "/".join(str(p) for p in item["loc"][1:]),
                item["type"].upper(),
                item.get("msg"),
            )
            for item in error.errors()
        ]
        return error_response(
            MaestroError(
                "REQUEST_INVALID", "Request structure is invalid", 422, field_errors=fields
            ),
            request.state.request_id,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(error.status_code, "HTTP_ERROR")
        return error_response(
            MaestroError(code, str(error.detail), error.status_code), request.state.request_id
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception):
        log.exception("unhandled error", exc_info=error)
        return error_response(
            MaestroError("INTERNAL_ERROR", "Unexpected server error", 500, retryable=True),
            request.state.request_id,
        )

    for router in routes.routers():
        app.include_router(router)

    @app.get("/{path:path}", include_in_schema=False)
    async def web(path: str):
        if path.startswith("api/") or path == "api":
            raise MaestroError("NOT_FOUND", "Unknown API path", 404)
        candidate = (STATIC / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(STATIC):
            return FileResponse(candidate)
        index = STATIC / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        raise MaestroError("WEB_NOT_BUILT", "Web pages are not built", 404)

    return app
