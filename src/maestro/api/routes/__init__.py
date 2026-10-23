from maestro.api.routes import admin, catalog, configuration, identity, runs, system


def routers():
    return [
        system.router,
        identity.router,
        admin.router,
        catalog.router,
        configuration.router,
        runs.router,
    ]
