"""Production HTTP/static wiring; reuses the existing external execution adapter.

The catalog and inherited preparation failure are explicit persisted fixtures.
No Hub, Docker or model call is evidence from this test.
"""

import json
import time

import httpx
import pytest
from support.browser_support import run_browser
from support.http_support import PASSWORD, WRITE
from support.paths import REPO
from support.process_support import wait


@pytest.mark.browser
def test_reuse_export_production_page_wiring(http_service, request):
    p, url, root = http_service
    for identity in ("source-dataset", "default-dataset"):
        p.app.configuration.persist(
            "dataset",
            {
                "id": identity,
                "name": identity,
                "reference": "fixture/data@1",
                "resolved": "fixture/data@1",
                "status": "verified",
                "enabled": True,
                "tasks": [{"name": "fixture/box", "package": "fixture/box", "ref": "sha256:fixed"}],
            },
        )
    p.app.configuration.save_settings(
        {"default_dataset_id": "default-dataset", "default_model_profile": "m3"}
    )
    with httpx.Client(base_url=url, trust_env=False, headers=WRITE) as client:
        assert (
            client.post(
                "/api/v1/auth/login", json={"username": "alice", "password": PASSWORD}
            ).status_code
            == 200
        )
        accepted = client.post(
            "/api/v1/submissions",
            headers={"Idempotency-Key": "reuse-source"},
            json={
                "dataset_id": "source-dataset",
                "model_profile": "m1",
                "name": "HTTP source",
                "agent": "opencode",
                "task": "fixture/box",
                "attempts": 1,
                "concurrency": 1,
                "wall_seconds": 700,
                "environment_build_timeout_multiplier": 7,
            },
        )
        assert accepted.status_code == 202, accepted.text
        source_submission = accepted.json()["id"]
        source = p.run_id({"id": source_submission})
        assert p.terminal(source)["status"] == "succeeded"
        wait(lambda: p.data.store.get(source)["audit_status"] == "clean")
        before = client.get(f"/api/v1/runs/{source}").json()
        # Seed a no-run inherited failure, with only the retry's public wall intent.
        # This isolates browser recovery projection from executor failure generation.
        frozen = p.data.submission(source_submission)["frozen"]
        with p.data.store.control(), p.data.store.connect() as db:
            db.execute(
                """INSERT INTO submissions
                (id,user_id,submitter,operation,idem,request_hash,request,frozen,target_id,status,created,parent,error)
                VALUES(?,?,?,?,?,?,?,?,?,'failed',?,?,?)""",
                (
                    "sub-inherited-failure",
                    p.actor["id"],
                    "alice",
                    "retry",
                    "fixture-retry",
                    "fixture-hash",
                    json.dumps({"wall_seconds": 900}),
                    json.dumps(frozen),
                    "hh-unpublished-fixture",
                    time.time(),
                    source,
                    "fixture preparation failed",
                ),
            )
        script = REPO / "frontend/qa/production/reuse-export-production.mjs"
        result = run_browser(
            request,
            script,
            env={
                **p.env,
                "HH_BROWSER_URL": url,
                "HH_BROWSER_EVIDENCE": str(root),
                "HH_SOURCE_RUN": source,
            },
            timeout=90,
        )
        (root / "browser.stdout").write_text(result.stdout)
        (root / "browser.stderr").write_text(result.stderr)
        (root / "browser.exit").write_text(str(result.returncode))
        proof = json.loads((root / "reuse-http-proof.json").read_text())
        assert proof["status"] == 202
        assert proof["accepted"]["id"] != source_submission
        assert proof["request"]["attempts"] == 1
        assert proof["request"]["wall_seconds"] == 800
        assert proof["request"]["dataset_id"] == "source-dataset"
        assert proof["request"]["model_profile"] == "m1"
        assert client.get(f"/api/v1/runs/{source}").json() == before
        new_run = p.run_id(proof["accepted"])
        assert new_run != source
        assert p.terminal(new_run)["status"] == "succeeded"
        assert proof["console_errors"] == []
