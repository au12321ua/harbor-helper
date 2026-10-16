from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from harbor_helper.service.primitives import ServiceError


def register(app):
    static = Path(__file__).resolve().parents[2] / "static"
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
