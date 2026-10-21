"""Actual CLI -> isolated production HTTP/scheduler/worker; only external execution is fake."""

import json
import os
import shutil
from pathlib import Path

import httpx
import pytest
from attachment_support import archive
from browser_support import run_browser
from http_support import PASSWORD, WRITE, cli
from process_support import wait


def test_noninteractive_cli_http_baseline_version_and_response_recovery(http_service):
    p, url, root = http_service
    with httpx.Client(base_url=url, trust_env=False, headers=WRITE) as browser:
        assert (
            browser.post(
                "/api/v1/auth/login", json={"username": "alice", "password": PASSWORD}
            ).status_code
            == 200
        )
        issued = browser.post(
            "/api/v1/access-credentials",
            json={
                "name": "noninteractive",
                "current_password": PASSWORD,
                "scopes": ["read", "attachments", "execute", "cancel_own"],
            },
        ).json()
        token = issued["token"]
        secret_file = root / "automation-token"
        secret_file.write_text(token)
        secret_file.chmod(0o600)
        configured, result = cli(
            p, "service", "configure-token", "--url", url, "--token-file", str(secret_file)
        )
        assert configured["configured"] and token not in result.stdout + result.stderr
        discovery, _ = cli(p, "service", "discover")
        assert (
            discovery["contract_version"] == "1.0" and "submit" in discovery["allowed_operations"]
        )
        baseline, out = cli(
            p,
            "submit",
            "--dataset",
            "fixture/data@1",
            "--agent",
            "oracle",
            "--idempotency-key",
            "baseline",
        )
        assert baseline["attachment"]["bundle_id"] is None and baseline["request"] == {
            "dataset": "fixture/data@1",
            "agent": "oracle",
        }
        recovered, _ = cli(p, "service", "lookup", "submit", "baseline")
        assert recovered["id"] == baseline["id"]
        repeated, _ = cli(
            p,
            "service",
            "retry",
            "/submissions",
            "--body",
            json.dumps(baseline["request"]),
            "--idempotency-key",
            "baseline",
        )
        assert repeated["id"] == baseline["id"]
        # Upload two immutable versions with an actual automation HTTP client.
        with httpx.Client(
            base_url=url, trust_env=False, headers={**WRITE, "Authorization": "Bearer " + token}
        ) as automation:
            first = automation.post(
                "/api/v1/attachments",
                files={"file": ("bundle.zip", archive(b"v1"))},
                data={"metadata": json.dumps({"name": "input"})},
                headers={"Idempotency-Key": "v1"},
            )
            assert first.status_code == 201, first.text
            v1 = first.json()
            second = automation.post(
                f"/api/v1/attachments/{v1['attachment']['id']}/versions",
                files={"file": ("bundle.zip", archive(b"v2"))},
                data={"metadata": "{}"},
                headers={"Idempotency-Key": "v2"},
            )
            assert second.status_code == 201, second.text
            v2 = second.json()
        candidate, _ = cli(
            p,
            "submit",
            "--dataset",
            "fixture/data@1",
            "--agent",
            "oracle",
            "--attachment-version-id",
            v1["version"]["id"],
            "--idempotency-key",
            "candidate",
        )
        candidate2, _ = cli(
            p,
            "submit",
            "--dataset",
            "fixture/data@1",
            "--agent",
            "oracle",
            "--attachment-version-id",
            v2["version"]["id"],
            "--idempotency-key",
            "candidate2",
        )
        ids = []
        for accepted in [baseline, candidate, candidate2]:
            rid = p.run_id(accepted)
            p.terminal(rid)
            ids.append(rid)
            state, _ = cli(p, "service", "query", accepted["id"])
            assert state["report"]["state"] == "available", state
            value, result = cli(p, "service", "report", rid)
            assert value["tasks"][0]["mean_rewards"] == {"reward": 0.0}
            assert token not in result.stdout + result.stderr
        comparison, _ = cli(p, "compare", ids[0], ids[1])
        assert comparison["comparable"] and comparison["bundle_change"]["left"] is None
        assert (
            comparison["attachment_inputs"]["right"]["attachment_version_id"] == v1["version"]["id"]
        )
        assert candidate2["attachment"]["attachment_version_id"] == v2["version"]["id"]
        # Same user's second credential and browser recover the same permanent member-key.
        second_token = browser.post(
            "/api/v1/access-credentials",
            json={"name": "second", "current_password": PASSWORD, "scopes": ["read", "execute"]},
        ).json()["token"]
        _, out = cli(
            p,
            "service",
            "configure-token",
            "--url",
            url,
            "--token-stdin",
            stdin=second_token + "\n",
        )
        assert second_token not in out.stdout + out.stderr
        assert cli(p, "service", "lookup", "submit", "baseline")[0]["id"] == baseline["id"]
        assert (
            browser.get("/api/v1/submission-operations/submit/baseline").json()["id"]
            == baseline["id"]
        )
        assert (
            browser.post(
                f"/api/v1/access-credentials/{issued['credential']['id']}/revoke"
            ).status_code
            == 200
        )
        # Restart HTTP compatibility covered by a fresh application instance in unit tests;
        # persisted keys survive revoked old token, evidence retention and profile changes.
        assert cli(p, "service", "lookup", "submit", "baseline")[0]["id"] == baseline["id"]
    for file in p.data.root.rglob("*"):
        if file.is_file():
            assert (
                token.encode() not in file.read_bytes()
                and second_token.encode() not in file.read_bytes()
            ), file.name
    assert token not in (root / "http.log").read_text()


@pytest.mark.browser
def test_production_static_browser_credentials(http_service, request):
    p, url, root = http_service
    # Node Playwright uses the already built UI from this production HTTP service.
    script = Path(__file__).parents[1] / "frontend/qa/automation-production.mjs"
    env = {**p.env, "HH_BROWSER_URL": url, "HH_BROWSER_EVIDENCE": str(root)}
    result = run_browser(request, script, env=env)
    assert "production credential UI passed" in result.stdout
    assert (root / "credential-ui.png").is_file()


@pytest.mark.browser
def test_production_browser_damaged_manifest_observation(http_service, request):
    from harbor_helper.persistence.wakeup import notify
    from harbor_helper.service import browser_contracts as dto

    p, url, root = http_service
    (p.data.root / "worker-hold").touch()
    active = p.run_id(p.submit("m1", "active"))
    wait(lambda: (p.data.store.path(active) / "boundary.json").exists())
    bob = p.data.create_user("bob", PASSWORD)
    broken = p.run_id(
        p.app.accept(bob, {"dataset": "fixture/data@1", "model_profile": "m2"}, "broken")
    )
    queued = p.run_id(p.submit("m3", "queued"))
    path = p.data.store.path(broken)
    (path / "manifest.json").write_bytes(b"\xfffixture-private-marker")
    notify(p.data.root)
    wait(lambda: p.data.store.get(broken)["status"] == "failed", timeout=4)
    dto.Runs.model_validate(p.app.runs())
    assert p.app.usage()["active_jobs"] == 1
    with httpx.Client(base_url=url, trust_env=False, headers=WRITE) as client:
        assert (
            client.post(
                "/api/v1/auth/login", json={"username": "alice", "password": PASSWORD}
            ).status_code
            == 200
        )
        for route, model in (("runs", dto.Runs), ("usage", dto.Usage)):
            response = client.get("/api/v1/" + route)
            assert response.status_code == 200
            model.model_validate(response.json())
            assert all(
                s not in response.text for s in (*p.keys, str(path), "fixture-private-marker")
            )
    result = run_browser(
        request,
        Path(__file__).parents[1] / "frontend/qa/damaged-observation-production.mjs",
        env={
            **p.env,
            "HH_BROWSER_URL": url,
            "HH_BROWSER_EVIDENCE": str(root),
            "HH_BROWSER_RUNS": json.dumps({"active": active, "broken": broken, "queued": queued}),
            "HH_BROWSER_FORBIDDEN": json.dumps([*p.keys, str(path), "fixture-private-marker"]),
        },
        timeout=60,
    )
    assert "production damaged observation UI passed" in result.stdout
    wait(lambda: p.data.store.get(active)["status"] == "cancelled", timeout=4)
    assert p.data.store.get(broken)["status"] == "failed"
    (p.data.root / "worker-hold").unlink()
    assert p.terminal(queued)["status"] == "succeeded"
    # Export only safe screenshots/QA JSON when explicitly requested, never the state.
    if target := os.environ.get("HH_OBSERVATION_EVIDENCE"):
        target = Path(target)
        target.mkdir(parents=True, exist_ok=True)
        for name in (
            "damaged-list.png",
            "healthy-detail.png",
            "healthy-cancelled.png",
            "damaged-browser.json",
        ):
            shutil.copyfile(root / name, target / name)
