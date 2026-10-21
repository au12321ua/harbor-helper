import secrets
from typing import Annotated

from fastapi import Depends, Request, Response

from harbor_helper.service.application import Application
from harbor_helper.service.data import ServiceData
from harbor_helper.service.http.dependencies import token
from harbor_helper.service.http.inputs import Login, PasswordChange, Setup
from harbor_helper.service.primitives import ServiceError
from harbor_helper.service.setup import protected_file


def register(app, deps, *, setup_token_file, master_key_file, start_scheduler):
    actor = deps.actor

    @app.get("/api/v1/setup")
    def setup_status():
        return {"initialized": (deps.store.root / "service.json").exists()}

    @app.post("/api/v1/setup", status_code=201)
    def setup(body: Setup):
        if (deps.store.root / "service.json").exists():
            raise ServiceError("already_initialized", "Website setup is already complete", 409)
        if not secrets.compare_digest(
            body.setup_token.get_secret_value(), protected_file(setup_token_file)
        ):
            raise ServiceError("setup_denied", "Deployment bootstrap credential required", 403)
        if not 1 <= len(body.team_name.strip()) <= 128:
            raise ServiceError("team_name", "Team name must be 1–128 characters")
        ServiceData.initialize(
            deps.store, master_key_file, body.username, body.password.get_secret_value()
        )
        deps.application = Application(deps.store)

        deps.application.configuration.save_settings({"team_name": body.team_name.strip()})
        app.state.application = deps.application
        if start_scheduler:
            from harbor_helper.execution.runs import ensure_supervisor

            ensure_supervisor(deps.store)
        return {"initialized": True}

    @app.post("/api/v1/auth/password")
    def password_change(body: PasswordChange, user: Annotated[dict, Depends(actor)]):
        session, _ = deps.data.login(user["username"], body.current_password.get_secret_value())
        deps.data.logout(session)
        deps.data.update_user(user["id"], password=body.password.get_secret_value())
        return {"changed": True, "login_required": True}

    @app.post("/api/v1/auth/login")
    def login(body: Login, response: Response):
        value, user = deps.data.login(body.username, body.password.get_secret_value())
        response.set_cookie(
            "hh_session", value, max_age=28800, httponly=True, samesite="strict", path="/"
        )
        return {"token": value, "user": user}

    @app.post("/api/v1/auth/logout")
    def logout(request: Request, response: Response, user: Annotated[dict, Depends(actor)]):
        deps.data.logout(token(request))
        response.delete_cookie("hh_session", path="/")
        return {"logged_out": True, "tasks_continue": True}

    @app.get("/api/v1/me")
    def me(user: Annotated[dict, Depends(actor)]):
        from harbor_helper.service.access import granted

        return {**user, "evidence_grant": granted(deps.data, user["id"])}
