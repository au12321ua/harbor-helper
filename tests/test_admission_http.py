"""Real HTTP/CLI plus scheduler drain; external source/execution remain fixture adapters."""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from test_automation_http import PASSWORD, WRITE
from test_automation_http import http_service as production_http_fixture
from test_service_process import wait

from harbor_helper.service.observation import scheduler


@pytest.fixture
def http_service(tmp_path):
    yield from production_http_fixture._get_wrapped_function()(tmp_path)


def cli(p, *argv, code=0):
    result = subprocess.run(
        [sys.executable, "-m", "harbor_helper.commands.main", *argv, "--json"],
        cwd=p.cwd,
        env=p.env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    with (p.cwd.parent / "admission-cli.jsonl").open("a") as log:
        log.write(
            json.dumps(
                {
                    "argv": list(argv),
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit": result.returncode,
                }
            )
            + "\n"
        )
    assert result.returncode == code, result.stderr
    return (json.loads(result.stdout) if code == 0 else None), result


def test_pause_two_http_processes_cli_drain_and_unready_old_key(http_service):
    p, url, root = http_service
    assert scheduler(p.app)["state"] == "ready"
    hold = p.data.root / "prepare-hold"
    hold.touch()
    with (
        httpx.Client(base_url=url, trust_env=False, headers=WRITE) as member,
        httpx.Client(base_url=url, trust_env=False, headers=WRITE) as admin,
    ):
        for browser, name in ((member, "alice"), (admin, "admin")):
            assert (
                browser.post(
                    "/api/v1/auth/login", json={"username": name, "password": PASSWORD}
                ).status_code
                == 200
            )
        token = member.post(
            "/api/v1/access-credentials",
            json={
                "name": "admission cli",
                "current_password": PASSWORD,
                "scopes": ["read", "execute"],
            },
        ).json()["token"]
        token_path = root / "fake-pat"
        token_path.write_text(token)
        token_path.chmod(0o600)
        cli(p, "service", "configure-token", "--url", url, "--token-file", str(token_path))
        accepted, _ = cli(
            p,
            "submit",
            "--agent",
            "oracle",
            "--dataset",
            "fixture/data@1",
            "--idempotency-key",
            "drain",
        )
        # A second actual API process loads the same state once, before the pause.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url2 = f"http://127.0.0.1:{port}"
        code = f"from harbor_helper.service.api import create_app; import uvicorn; uvicorn.run(create_app({str(p.data.root)!r},start_scheduler=False),host='127.0.0.1',port={port},access_log=False)"
        log = (root / "http2.log").open("w")
        api2 = subprocess.Popen(
            [sys.executable, "-c", code], cwd=p.cwd, env=p.env, stdout=log, stderr=log
        )

        def connected():
            try:
                return httpx.get(url2 + "/api/v1/health", trust_env=False).status_code == 200
            except httpx.RequestError:
                return False

        try:
            wait(connected)
            with httpx.Client(
                base_url=url2,
                trust_env=False,
                headers={**WRITE, "Authorization": "Bearer " + token},
            ) as second:
                assert second.get("/api/v1/readiness").json()["accepting"]
                assert (
                    admin.patch(
                        "/api/v1/admin/maintenance",
                        json={"paused": True, "reason": "fixture drain"},
                    ).status_code
                    == 200
                )
                assert not second.get("/api/v1/readiness").json()["accepting"]
                new = second.post(
                    "/api/v1/submissions",
                    json={"agent": "oracle"},
                    headers={"Idempotency-Key": "new"},
                )
                assert new.status_code == 503 and new.json()["code"] == "maintenance_paused"
                old = second.post(
                    "/api/v1/submissions",
                    json=accepted["request"],
                    headers={"Idempotency-Key": "drain"},
                )
                assert old.status_code == 202 and old.json()["id"] == accepted["id"]
                recovered, _ = cli(
                    p,
                    "service",
                    "retry",
                    "/submissions",
                    "--body",
                    json.dumps(accepted["request"]),
                    "--idempotency-key",
                    "drain",
                )
                assert recovered["id"] == accepted["id"]
                hold.unlink()
                rid = p.run_id(accepted)
                assert p.terminal(rid)["status"] == "succeeded"
                wait(lambda: p.data.store.get(rid)["audit_status"] == "clean")
                report, _ = cli(p, "service", "report", rid)
                assert report["tasks"][0]["mean_rewards"] == {"reward": 0.0}
                assert len(p.data.store.runs()) == 1
                _, rejected = cli(
                    p, "submit", "--agent", "oracle", "--idempotency-key", "denied-cli", code=1
                )
                assert json.loads(rejected.stdout)["code"] == "maintenance_paused"
                assert token not in rejected.stdout + rejected.stderr
                assert second.get("/api/v1/readiness").json()["maintenance"]["paused"]
                # Actual process birth becomes unavailable when the scheduler stops.
                p.kill_scheduler()
                unavailable = second.get("/api/v1/readiness").json()
                assert unavailable["scheduler"]["state"] == "unavailable"
                assert (
                    second.post(
                        "/api/v1/submissions",
                        json=accepted["request"],
                        headers={"Idempotency-Key": "drain"},
                    ).json()["id"]
                    == accepted["id"]
                )
                assert (
                    admin.patch("/api/v1/admin/maintenance", json={"paused": False}).status_code
                    == 200
                )
                assert (
                    second.post(
                        "/api/v1/submissions",
                        json={"agent": "oracle"},
                        headers={"Idempotency-Key": "new"},
                    ).json()["code"]
                    == "scheduler_unready"
                )
                p.start()
                assert second.get("/api/v1/readiness").json()["accepting"]
                resumed = second.post(
                    "/api/v1/submissions",
                    json={"agent": "oracle"},
                    headers={"Idempotency-Key": "new"},
                )
                assert resumed.status_code == 202
                next_id = p.run_id(resumed.json())
                assert p.terminal(next_id)["status"] == "succeeded"
                wait(lambda: p.data.store.get(next_id)["audit_status"] == "clean")
                assert token not in json.dumps(unavailable)
        finally:
            api2.terminate()
            api2.wait(timeout=10)
            log.close()


@pytest.mark.skipif(
    os.environ.get("HH_TEST_BROWSER") != "1", reason="Opt-in production UI with Playwright Chromium"
)
def test_production_admission_browser(http_service):
    p, url, root = http_service
    script = Path(__file__).parents[1] / "frontend/qa/admission-production.mjs"
    result = subprocess.run(
        ["node", str(script)],
        env={**p.env, "HH_BROWSER_URL": url, "HH_BROWSER_EVIDENCE": str(root)},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    # Retain original safe browser output for audit (no token issuance in this script).
    (root / "browser.stdout").write_text(result.stdout)
    (root / "browser.stderr").write_text(result.stderr)
    (root / "browser.exit").write_text(str(result.returncode))
    assert result.returncode == 0, result.stderr
    assert "production admission UI passed" in result.stdout
    assert (root / "admission-admin.png").is_file()
    assert (root / "admission-member-mobile.png").is_file()
