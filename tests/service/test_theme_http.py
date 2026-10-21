"""Theme bootstrap and real production pages on an uninitialized, isolated service."""

import os
import socket
import subprocess
import sys

import httpx
import pytest
from support.browser_support import run_browser
from support.paths import REPO
from support.process_support import wait


@pytest.mark.browser
def test_theme_production_pages(tmp_path, request):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    setup = private / "setup-token"
    master = private / "master"
    state = tmp_path / "state"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = {
        k: os.environ[k]
        for k in ("PATH", "LANG", "HH_VERIFY_RUN", "PLAYWRIGHT_BROWSERS_PATH")
        if k in os.environ
    }
    home = tmp_path / "home"
    home.mkdir()
    env["HOME"] = str(home)
    code = (
        "from harbor_helper.service.api import create_app; import uvicorn; "
        f"uvicorn.run(create_app({str(state)!r}, setup_token_file={str(setup)!r}, "
        f"master_key_file={str(master)!r}), host='127.0.0.1', port={port}, access_log=False)"
    )
    with (tmp_path / "http.log").open("w") as log:
        server = subprocess.Popen([sys.executable, "-c", code], env=env, stdout=log, stderr=log)
        try:

            def ready():
                try:
                    return httpx.get(url + "/api/v1/setup", trust_env=False).status_code == 200
                except httpx.RequestError:
                    return False

            wait(ready)
            run_browser(
                request,
                REPO / "frontend/qa/production/theme-production.mjs",
                env={
                    **env,
                    "HH_THEME_URL": url,
                    "HH_THEME_PRIVATE": str(private),
                    "HH_THEME_EVIDENCE": str(tmp_path / "evidence"),
                },
                timeout=180,
            )
        finally:
            server.terminate()
            server.wait(timeout=10)
