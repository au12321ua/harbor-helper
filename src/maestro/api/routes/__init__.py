from maestro.api.routes import admin, catalog, identity, runs, system


def routers():
    return [system.router, identity.router, admin.router, catalog.router, runs.router]
