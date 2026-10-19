"""Browser update control: authenticated metadata and protected spool writes only."""

import hashlib
from importlib.metadata import version
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends

from harbor_helper.persistence.upgrades import enqueue, journal, private_json, projection
from harbor_helper.service.browser_contracts import UpdateInput


def build_digest():
    static = Path(__file__).resolve().parents[2] / "static"
    digest = hashlib.sha256()
    for path in sorted(static.rglob("*")):
        if path.is_file() and path.name != "index.html":
            digest.update(str(path.relative_to(static)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def checkout_commit(code):
    try:
        git = code / ".git"
        if git.is_file():
            git = Path(git.read_text().strip().removeprefix("gitdir: "))
        head = (git / "HEAD").read_text().strip()
        if head.startswith("ref: "):
            ref = head[5:]
            common = (
                git / (git / "commondir").read_text().strip()
                if (git / "commondir").exists()
                else git
            )
            head = (common / ref).read_text().strip()
        return head if len(head) == 40 and all(c in "0123456789abcdef" for c in head) else None
    except OSError:
        return None


def identity(root):
    code = Path(__file__).resolve().parents[4]
    installed = code / ".installed"
    release = code.name if installed.exists() else checkout_commit(code)
    # A state release lease is not proof of the code currently loaded by HTTP.
    provenance = code / ".release-source.json"
    source = private_json(provenance) if provenance.exists() else None
    return {
        "version": version("harbor-helper"),
        "release": release,
        "build": build_digest(),
        "source": source,
    }


def register(app, deps):
    actor, administrator = deps.actor, deps.administrator
    running = identity(deps.store.root)
    digest = running["build"]

    @app.get("/api/v1/build")
    def build_identity():
        return {"build": digest}

    @app.get("/api/v1/upgrade-phase")
    def upgrade_phase():
        return projection(deps.store.root)

    @app.get("/api/v1/version")
    def running_version(user: Annotated[dict, Depends(actor)]):
        return running

    @app.get("/api/v1/admin/updates")
    def update_status(user: Annotated[dict, Depends(administrator)]):
        base = deps.store.root.parent
        configured = (base / "updates/enabled.json").exists()
        results = []
        if configured:
            for path in sorted(
                (base / "updates/results").glob("*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:20]:
                value = private_json(path)
                results.append({k: v for k, v in value.items() if k != "request"})
        source = None
        path = base / "private/update.toml"
        if path.exists():
            import tomllib

            source = tomllib.loads(path.read_text())["updates"]
            parsed = urlsplit(source["repository"])
            if (
                source.get("branch") not in {"master", "dev"}
                or parsed.password
                or (parsed.username and parsed.scheme != "ssh")
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Invalid protected source configuration")
        return {
            "enabled": configured,
            "source": source,
            "job": journal(deps.store.root),
            "results": results,
        }

    @app.post("/api/v1/admin/updates")
    def update_request(body: UpdateInput, user: Annotated[dict, Depends(administrator)]):
        body = body.model_dump()
        # enqueue validates every field and never executes the supplied data.
        return enqueue(
            deps.store.root, body["action"], user["id"], body["request_id"], body["payload"]
        )
