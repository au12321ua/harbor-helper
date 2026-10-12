"""Bounded skill workflow verification; uses repository isolated HTTP fixture only.

Run with env -i, isolated HOME, PYTHONPATH=src:tests, existing dev Python:
python -m pytest -q -p no:cacheprovider <this file> --basetemp <fresh path>
No real Hub/Docker/model execution. Not a runtime helper shipped in the skill.
"""

import json
import shutil
import subprocess
import sys

import httpx
import pytest
from test_attachments import archive
from test_automation_http import PASSWORD, WRITE
from test_automation_http import http_service as http_service_fixture
from test_service_process import wait


@pytest.fixture
def http_service(tmp_path):
    yield from http_service_fixture.__wrapped__(tmp_path)


def test_research_workflow(http_service):
    p, url, root = http_service
    outputs = []

    def cli(*args, stdin=None, ok=True):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "harbor_helper.cli",
                "--remote-profile",
                "research",
                *args,
                "--json",
            ],
            cwd=p.cwd,
            env=p.env,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        outputs.append(result.stdout + result.stderr)
        assert (result.returncode == 0) == ok, result.stderr
        return json.loads(result.stdout) if ok else result.stderr

    p.app.configuration.persist(
        "dataset",
        {
            "id": "catalog",
            "name": "catalog",
            "enabled": True,
            "status": "verified",
            "reference": "fixture/data@1",
            "resolved": "fixture/data@1",
            "tasks": [
                {"name": n, "package": "fixture/box", "ref": "sha256:fixed"}
                for n in ["box", "other"]
            ],
        },
    )
    with httpx.Client(base_url=url, headers=WRITE, trust_env=False) as browser:
        assert (
            browser.post(
                "/api/v1/auth/login", json={"username": "alice", "password": PASSWORD}
            ).status_code
            == 200
        )

        def issue(scopes):
            response = browser.post(
                "/api/v1/access-credentials",
                json={
                    "name": "isolated research",
                    "current_password": PASSWORD,
                    "scopes": scopes,
                },
            )
            assert response.status_code == 201
            return response.json()

        issued = issue(["read", "execute", "attachments", "cancel_own"])
        token = issued["token"]
        secret = root / "access-token"
        secret.write_text(token)
        secret.chmod(0o600)
        assert cli(
            "service",
            "configure-token",
            "--url",
            url,
            "--token-file",
            str(secret),
            "--profile",
            "research",
        )["configured"]
        secret.chmod(0o644)
        cli(
            "service",
            "configure-token",
            "--url",
            url,
            "--token-file",
            str(secret),
            "--profile",
            "research",
            ok=False,
        )
        secret.chmod(0o600)
        link = root / "token-link"
        link.symlink_to(secret)
        cli(
            "service",
            "configure-token",
            "--url",
            url,
            "--token-file",
            str(link),
            "--profile",
            "research",
            ok=False,
        )
        identity = cli("service", "status")["user"]
        assert cli("service", "schema")["info"]["version"] == "1.0"
        discovery = cli("service", "discover")
        assert discovery["contract_version"] == "1.0" and discovery["cost"] == "unknown"
        first = cli("service", "tasks", "catalog", "--offset", "0", "--limit", "1")
        assert first["next_offset"] == 1 and len(first["tasks"]) == 1
        assert (
            cli("service", "tasks", "catalog", "--offset", "1", "--limit", "1")["next_offset"]
            is None
        )
        headers = {**WRITE, "Authorization": "Bearer " + token}
        with httpx.Client(base_url=url, headers=headers, trust_env=False) as api:
            v1 = api.post(
                "/api/v1/attachments",
                files={"file": ("bundle.zip", archive(b"v1"))},
                data={"metadata": '{"name":"study"}'},
                headers={"Idempotency-Key": "attachment-v1"},
            )
            assert v1.status_code == 201
            v1 = v1.json()
            v2 = api.post(
                f"/api/v1/attachments/{v1['attachment']['id']}/versions",
                files={"file": ("bundle.zip", archive(b"v2"))},
                data={"metadata": "{}"},
                headers={"Idempotency-Key": "attachment-v2"},
            )
            assert v2.status_code == 201
            v2 = v2.json()
            body = {
                "dataset": "fixture/data@1",
                "agent": "oracle",
                "task": "box",
                "attempts": 1,
                "concurrency": 1,
                "wall_seconds": 120,
            }
            args = [
                "submit",
                "--dataset",
                body["dataset"],
                "--agent",
                "oracle",
                "--task",
                "box",
                "--attempts",
                "1",
                "--concurrency",
                "1",
                "--wall-seconds",
                "120",
            ]
            receipts = root / "operation-records"
            receipts.mkdir(mode=0o700)
            # Unknown key: keep original key and body, then simulate discarding successful response.
            unknown = api.get("/api/v1/submission-operations/submit/STUDY-baseline")
            assert unknown.status_code == 404 and unknown.json()["action"] == "retry_same_request"
            cli(*args, "--idempotency-key", "STUDY-baseline")
            receipt_path = p.home / ".config/harbor-helper/remote/receipt-research.json"
            saved = json.loads(receipt_path.read_text())
            assert saved["body"] == body and saved["user_id"] == identity["id"]
            assert saved["path"] == "/submissions" and saved["idempotency_key"] == "STUDY-baseline"
            shutil.copyfile(receipt_path, receipts / "baseline.json")
            baseline = cli("service", "lookup", "submit", "STUDY-baseline")
            assert cli("service", "retry")["id"] == baseline["id"]
            conflict = api.post(
                "/api/v1/submissions",
                json={**body, "wall_seconds": 121},
                headers={"Idempotency-Key": "STUDY-baseline"},
            )
            assert conflict.status_code == 409 and conflict.json()["action"] == "fix_input"
            assert cli("service", "lookup", "submit", "STUDY-baseline")["id"] == baseline["id"]
            accepted = [baseline]
            for label, version in [("v1", v1), ("v2", v2)]:
                accepted.append(
                    cli(
                        *args,
                        "--attachment-version-id",
                        version["version"]["id"],
                        "--idempotency-key",
                        "STUDY-" + label,
                    )
                )
                shutil.copyfile(receipt_path, receipts / (label + ".json"))
            with p.data.store.connect() as db:
                assert db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 3
            p.start()
            runs = []
            for item in accepted:
                rid = p.run_id(item)
                p.terminal(rid)
                # Finite actual poll budget; exact state is observed, not inferred from terminal.
                state = wait(
                    lambda item=item: (
                        s
                        if (s := cli("service", "query", item["id"]))["report"]["state"]
                        == "available"
                        else None
                    ),
                    timeout=15,
                )
                assert (
                    state["resource"]["state"] == "released" and state["audit"]["state"] == "clean"
                )
                report = cli("service", "report", rid)
                attempt = report["tasks"][0]["attempts"][0]
                assert (
                    attempt["valid"]
                    and attempt["rewards"] == {"reward": 0.0}
                    and attempt["failure"] is None
                )
                runs.append(rid)
            for left, right in [(runs[0], runs[1]), (runs[1], runs[2])]:
                comparison = cli("compare", left, right)
                assert comparison["comparable"] and not comparison["reasons"]
                assert comparison["bundle_change"]["left"] != comparison["bundle_change"]["right"]
            assert (
                cli("compare", runs[1], runs[2])["attachment_inputs"]["right"][
                    "attachment_version_id"
                ]
                == v2["version"]["id"]
            )
            # Isolated terminal records: unavailable and blocked are explicit errors, not empty reports.
            p.kill_scheduler()
            p.data.store.update(runs[0], audit_status="incomplete")
            assert cli("service", "query", runs[0])["report"]["state"] == "blocked"
            assert "contact_admin" in cli("service", "report", runs[0], ok=False)
            p.data.store.update(runs[0], audit_status="clean")
            (p.data.store.path(runs[0]) / "report.json").unlink()
            assert cli("service", "query", runs[0])["report"]["state"] == "unavailable"
            assert "explicit_new_attempt" in cli("service", "report", runs[0], ok=False)
        readonly = issue(["read"])
        cli(
            "service",
            "configure-token",
            "--url",
            url,
            "--token-stdin",
            "--profile",
            "research",
            stdin=readonly["token"] + "\n",
        )
        assert "reauthorize" in cli(*args, "--idempotency-key", "DENIED", ok=False)
        with p.data.store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 3
        assert (
            browser.post(
                f"/api/v1/access-credentials/{readonly['credential']['id']}/revoke"
            ).status_code
            == 200
        )
        assert "reauthorize" in cli("service", "discover", ok=False)
        replacement = issue(["read", "execute"])
        cli(
            "service",
            "configure-token",
            "--url",
            url,
            "--token-stdin",
            "--profile",
            "research",
            stdin=replacement["token"] + "\n",
        )
        assert cli("service", "lookup", "submit", "STUDY-baseline")["id"] == baseline["id"]
        for raw in [token, readonly["token"], replacement["token"]]:
            assert raw not in "".join(outputs)
            assert all(
                raw.encode() not in file.read_bytes()
                for file in p.data.root.rglob("*")
                if file.is_file()
            )
            assert raw not in (root / "http.log").read_text()
