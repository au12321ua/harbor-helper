from maestro.api.routes import (
    admin,
    attachments,
    catalog,
    configuration,
    identity,
    runs,
    system,
)


def routers():
    return [
        system.router,
        identity.router,
        admin.router,
        catalog.router,
        configuration.router,
        attachments.router,
        runs.router,
    ]
