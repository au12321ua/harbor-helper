"""Authentication dependencies.

Bearer tokens are PATs only. Browser sessions use an HttpOnly cookie plus a
per-session CSRF header on unsafe methods. PATs never receive admin rights.
"""

import secrets

from fastapi import Request, Response

from maestro.application import Maestro
from maestro.core.errors import MaestroError
from maestro.security import tokens
from maestro.services.principal import Principal

COOKIE = "maestro_session"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def new_request_id() -> str:
    return "req_" + secrets.token_hex(8)


def maestro(request: Request) -> Maestro:
    return request.app.state.maestro


def client_source(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def principal(request: Request) -> Principal:
    service = maestro(request)
    header = request.headers.get("authorization")
    if header:
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise MaestroError("UNAUTHENTICATED", "Use 'Authorization: Bearer <token>'", 401)
        return service.accounts.authenticate_pat(token.strip())
    cookie = request.cookies.get(COOKIE)
    if not cookie:
        raise MaestroError("UNAUTHENTICATED", "Sign in or provide an access token", 401)
    found = service.accounts.authenticate_session(cookie)
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not tokens.same(sent, tokens.csrf_for(cookie)):
            raise MaestroError("CSRF_FAILED", "Missing or invalid CSRF token", 403)
    return found


def set_session_cookie(response: Response, service: Maestro, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=service.settings.session_hours * 3600,
        httponly=True,
        secure=service.settings.cookie_secure,
        samesite="lax",
        path=service.settings.root_path or "/",
    )


def clear_session_cookie(response: Response, service: Maestro) -> None:
    response.delete_cookie(COOKIE, path=service.settings.root_path or "/")


def ok(request: Request, data, next_cursor: str | None = None) -> dict:
    meta = {"request_id": request.state.request_id}
    if next_cursor is not None:
        meta["next_cursor"] = next_cursor
    return {"data": data, "meta": meta}
