"""One HTTP application: invited team API and packaged React assets."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from harbor_helper.persistence.store import Store
from harbor_helper.service.application import Application
from harbor_helper.service.http import (
    access,
    attachments,
    boundary,
    configuration,
    experiments,
    session,
    spa,
    status,
)
from harbor_helper.service.http import machine as machine_routes
from harbor_helper.service.http.dependencies import Dependencies
from harbor_helper.service.primitives import ServiceError
from harbor_helper.service.setup import protected_file


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

    @asynccontextmanager
    async def lifespan(app):
        if start_scheduler and application is not None:
            from harbor_helper.execution.runs import ensure_supervisor

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
    from harbor_helper.service.contract_boundary import ContractRoute

    app.router.route_class = ContractRoute
    app.state.application = application

    deps = Dependencies(app, store)
    boundary.register(app, deps)
    access.register(app, deps)
    status.register(app, deps)
    machine_routes.register(app, deps)
    session.register(
        app,
        deps,
        setup_token_file=setup_token_file,
        master_key_file=master_key_file,
        start_scheduler=start_scheduler,
    )
    experiments.register(app, deps)
    attachments.register(app, deps)
    configuration.register(app, deps)
    spa.register(app)
    return app
