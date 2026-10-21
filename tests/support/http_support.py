"""Shared test factories; each call owns its mutable state."""

import json
import shutil
import socket
import subprocess
import sys

import httpx

from support.paths import REPO
from support.process_support import Processes, wait

PASSWORD = "Fake-process-password-2026"

WRITE = {"X-Requested-With": "harbor-helper"}


def serve_http(tmp_path):
    p = Processes(tmp_path)
    package = p.cwd / "harbor_helper"
    shutil.copytree(REPO / "src/harbor_helper/static", package / "static")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    code = "from harbor_helper.service.api import create_app; import uvicorn; " + (
        f"uvicorn.run(create_app({str(p.data.root)!r},start_scheduler=False),host='127.0.0.1',port={port},access_log=False)"
    )
    log = (tmp_path / "http.log").open("w")
    server = subprocess.Popen(
        [sys.executable, "-c", code], cwd=p.cwd, env=p.env, stdout=log, stderr=log
    )

    def connected():
        try:
            return httpx.get(url + "/api/v1/setup", trust_env=False).status_code == 200
        except httpx.RequestError:
            return False

    try:
        wait(connected)
        p.start()
        yield p, url, tmp_path
    finally:
        server.terminate()
        server.wait(timeout=10)
        p.close()
        log.close()
        from harbor_helper.execution.processes import process_birth

        wait(
            lambda: all(
                not r["pid"] or process_birth(r["pid"]) != r["birth"] for r in p.data.store.runs()
            ),
            timeout=5,
        )
        proof = {
            "http_stopped": server.poll() is not None,
            "scheduler_stopped": p.child is None or p.child.poll() is not None,
            "worker_births_released": all(
                not r["pid"] or process_birth(r["pid"]) != r["birth"] for r in p.data.store.runs()
            ),
            "url": url,
        }
        (tmp_path / "teardown.json").write_text(json.dumps(proof, indent=2))
        assert all(
            proof[k] for k in ("http_stopped", "scheduler_stopped", "worker_births_released")
        )


def cli(p, *argv, stdin=None):
    result = subprocess.run(
        [sys.executable, "-m", "harbor_helper.commands.main", *argv, "--json"],
        cwd=p.cwd,
        env=p.env,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout), result
