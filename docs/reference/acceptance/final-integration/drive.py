import hashlib
import http.server
import io
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import httpx

BASE = Path(os.environ.get("HH_TASK_ROOT", "/tmp/hh-final-integration-evidence/research"))
WT = Path(os.environ.get("HH_CANDIDATE_ROOT", "/tmp/hh-final-integration"))
STATE = BASE / "state"
PRIVATE = BASE / "private"
WORK = BASE / "fixture-execution"
CAPTURE = BASE / "capture"
HOME = BASE / "home"
PASSWORD = "Fixture-only-member-password-2026"
WRITE = {"X-Requested-With": "harbor-helper"}
DATASET = "fixture/research@1"
TASK = "fixture/research-task"
KEYS = ["research-baseline-20261012", "research-v1-20261012", "research-v2-20261012"]
PROXY_FAULT = {"used": False}


def event(kind, **fields):
    with (CAPTURE / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(
            json.dumps({"time": round(time.time(), 3), "kind": kind, **fields}, ensure_ascii=False)
            + "\n"
        )


def run_cli(*args, allow_failure=False):
    env = dict(os.environ)
    env["HOME"] = str(HOME)
    result = subprocess.run(
        [sys.executable, "-m", "harbor_helper.cli", *map(str, args), "--json"],
        cwd=WT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=75,
    )
    label = " ".join(map(str, args))
    with (CAPTURE / "cli-transcript.jsonl").open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "command": label,
                    "exit_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    event("cli", command=label, exit_code=result.returncode)
    if result.returncode and not allow_failure:
        raise RuntimeError(f"CLI command failed (see cli-transcript.jsonl): {label}")
    if result.returncode:
        return None, result
    try:
        return json.loads(result.stdout), result
    except json.JSONDecodeError:
        return result.stdout, result


class Proxy(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        return

    def _forward(self):
        size = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(size) if size else None
        headers = {
            k: v
            for k, v in self.headers.items()
            if k.lower() not in {"host", "content-length", "connection", "keep-alive"}
        }
        with httpx.Client(timeout=60, trust_env=False, follow_redirects=False) as client:
            response = client.request(
                self.command,
                API_URL + self.path,
                headers=headers,
                content=body,
            )
        if (
            self.command == "POST"
            and self.path == "/api/v1/submissions"
            and not PROXY_FAULT["used"]
        ):
            PROXY_FAULT["used"] = True
            event(
                "injected_response_loss",
                method=self.command,
                path=self.path,
                upstream_status=response.status_code,
            )
            payload = json.dumps(
                {
                    "code": "fixture_gateway_timeout",
                    "message": "Fixture proxy discarded the response after upstream acceptance",
                    "action": "poll_existing",
                }
            ).encode()
            self.send_response(504)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
            self.close_connection = True
            return
        self.send_response(response.status_code)
        for k, v in response.headers.items():
            if k.lower() not in {
                "content-length",
                "transfer-encoding",
                "connection",
                "content-encoding",
            }:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(response.content)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(response.content)
        self.close_connection = True

    do_GET = _forward
    do_POST = _forward
    do_PATCH = _forward


def get_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    value = sock.getsockname()[1]
    sock.close()
    return value


def archive(answer):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("skills/fixture-research/answer.json", json.dumps({"response": answer}) + "\n")
        z.writestr("skills/fixture-research/README.md", "Fixture research attachment input.\n")
    out.seek(0)
    return out


def prepare_fixture_package():
    package = WORK / "harbor_helper"
    shutil.copytree(
        WT / "src/harbor_helper", package, ignore=shutil.ignore_patterns("__pycache__", "static")
    )
    shutil.copytree(WT / "src/harbor_helper/static", package / "static")
    with (package / "execution/sources.py").open("a") as f:
        f.write("""
async def resolve_dataset(reference, target, task_filter=None):
    from pathlib import Path
    from harbor_helper.persistence.files import tree_digest
    if target is None:
        target = Path(__file__).resolve().parents[2] / "fixture-source"
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    folder = target / "task"
    folder.mkdir(exist_ok=True)
    (folder / "task.toml").write_text('version = "1.0"\\n')
    (folder / "instruction.md").write_text(
        "Return the fixed response maple. Score is 1 only when answer.json response equals maple.\\n"
    )
    return {
        "requested": reference,
        "resolved": reference,
        "tasks": [{
            "name": "fixture/research-task",
            "package": "fixture/research-task",
            "directory": "task",
            "ref": "sha256:" + "d" * 64,
            "snapshot_digest": tree_digest(folder),
        }],
    }
""")
    with (package / "service/sources.py").open("a") as f:
        f.write("""
def source_call(reference, *, key=None, target=None, task=None, selected_tasks=None):
    import asyncio
    from harbor_helper.execution.sources import resolve_dataset
    return asyncio.run(resolve_dataset(reference, target, task))
""")
    with (package / "execution/runs.py").open("a") as f:
        f.write("""
def image_identity(reference):
    return "sha256:" + "f" * 64
_original_subprocess_run = subprocess.run
def _fixture_subprocess_run(argv, *args, **kwargs):
    if argv[:2] == ["docker", "tag"]:
        return subprocess.CompletedProcess(argv, 0)
    return _original_subprocess_run(argv, *args, **kwargs)
subprocess.run = _fixture_subprocess_run
""")
    worker_path = package / "execution/worker.py"
    worker = worker_path.read_text()
    adapter = """
async def execute(store, run_id):
    import hashlib
    import json
    from harbor_helper.persistence.files import read_json, write_json
    path = store.path(run_id)
    manifest = read_json(path / "manifest.json")
    bundle = path / "bundle"
    answer_path = bundle / "skills/fixture-research/answer.json"
    answer = json.loads(answer_path.read_text()) if answer_path.is_file() else None
    reward = 1.0 if answer == {"response": "maple"} else 0.0
    proof = {
        "adapter": "fixture-verifier-v1",
        "task": "fixture/research-task",
        "attachment_version_id": manifest.get("service", {}).get("attachment_version_id"),
        "answer_sha256": hashlib.sha256(answer_path.read_bytes()).hexdigest() if answer_path.is_file() else None,
        "reward": reward,
    }
    write_json(path / "fixture-execution.json", proof)
    trial = path / "harbor" / run_id / "task__fixture"
    trial.mkdir(parents=True, exist_ok=True)
    write_json(trial / "result.json", {
        "task_name": "fixture/research-task",
        "trial_name": "task__fixture",
        "verifier_result": {"rewards": {"reward": reward}},
        "exception_info": None,
    })
    return {"status": "succeeded", "reason": None}

"""
    marker = 'if __name__ == "__main__":'
    if marker not in worker:
        raise RuntimeError("fixture worker entrypoint marker missing")
    worker_path.write_text(worker.replace(marker, adapter + marker))


api_proc = None
worker_proc = None
proxy_server = None
http_log = None
supervisor_log = None
try:
    for directory in (BASE, BASE / "home", STATE, PRIVATE, WORK, CAPTURE):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
    (BASE / "skills").mkdir(mode=0o700, exist_ok=True)
    if not (BASE / "skills/harbor-helper-research").exists():
        shutil.copytree(
            WT / "skills/harbor-helper-research", BASE / "skills/harbor-helper-research"
        )
    event(
        "candidate",
        sha=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WT, text=True).strip(),
        skill_copy=str(BASE / "skills/harbor-helper-research/SKILL.md"),
    )

    prepare_fixture_package()
    sys.path.insert(0, str(WORK))
    from harbor_helper.service.configuration import TeamConfiguration
    from harbor_helper.service.data import ServiceData

    data = ServiceData.initialize(STATE, PRIVATE / "master.key", "fixture-admin", PASSWORD)
    member = data.create_user("fixture-member", PASSWORD, "member")
    config = TeamConfiguration(data)
    dataset = config.save(
        "dataset",
        {"id": "fixture-dataset", "name": "Fixture Research Dataset", "reference": DATASET},
    )
    dataset = config.verify("dataset", dataset["id"])
    config.save_settings(
        {"team_name": "Isolated Research Fixture", "default_dataset_id": dataset["id"]}
    )

    api_port = get_port()
    API_URL = f"http://127.0.0.1:{api_port}"
    api_code = (
        "from harbor_helper.service.api import create_app; import uvicorn; "
        f"uvicorn.run(create_app({str(STATE)!r}, start_scheduler=False), host='127.0.0.1', port={api_port}, access_log=False)"
    )
    service_env = dict(os.environ)
    service_env["HOME"] = str(HOME)
    http_log = (CAPTURE / "http-service.log").open("w")
    api_proc = subprocess.Popen(
        [sys.executable, "-c", api_code],
        cwd=WORK,
        env=service_env,
        stdout=http_log,
        stderr=http_log,
    )
    for _ in range(200):
        try:
            if httpx.get(API_URL + "/api/v1/setup", trust_env=False).status_code == 200:
                break
        except httpx.RequestError:
            time.sleep(0.05)
    else:
        raise RuntimeError("loopback service did not start")

    session = httpx.Client(base_url=API_URL, trust_env=False, headers=WRITE)
    login = session.post(
        "/api/v1/auth/login", json={"username": "fixture-member", "password": PASSWORD}
    )
    if login.status_code != 200:
        raise RuntimeError(f"fixture member login failed: {login.status_code}")

    def issue(name, scopes):
        response = session.post(
            "/api/v1/access-credentials",
            json={
                "name": name,
                "current_password": PASSWORD,
                "scopes": scopes,
            },
        )
        if response.status_code != 201:
            raise RuntimeError(f"fixture credential issue failed: {response.status_code}")
        value = response.json()
        path = PRIVATE / (name + ".pat")
        path.write_text(value["token"] + "\n")
        path.chmod(0o600)
        return value["credential"], path

    # Fixture owner creates two immutable attachment versions before read-only discovery.
    first_zip = archive("maple")
    created = session.post(
        "/api/v1/attachments",
        files={"file": ("input.zip", first_zip, "application/zip")},
        data={"metadata": json.dumps({"name": "Research input"})},
        headers={"Idempotency-Key": "fixture-attachment-create"},
    )
    if created.status_code != 201:
        raise RuntimeError(
            f"fixture attachment create failed: {created.status_code}: {created.text}"
        )
    v1 = created.json()
    second_zip = archive("birch")
    published = session.post(
        f"/api/v1/attachments/{v1['attachment']['id']}/versions",
        files={"file": ("input.zip", second_zip, "application/zip")},
        data={"metadata": json.dumps({"notes": "Version two control"})},
        headers={"Idempotency-Key": "fixture-attachment-v2"},
    )
    if published.status_code != 201:
        raise RuntimeError(
            f"fixture attachment publish failed: {published.status_code}: {published.text}"
        )
    v2 = published.json()
    read_credential, read_file = issue("research-read-only", ["read"])
    exec_credential, exec_file = issue("research-execute", ["read", "execute"])
    replacement_credential, replacement_file = issue("research-replacement", ["read", "execute"])
    event(
        "fixture_ready",
        member_id=member["id"],
        dataset_id=dataset["id"],
        attachment_id=v1["attachment"]["id"],
        attachment_versions=[v1["version"]["id"], v2["version"]["id"]],
        credential_scopes={"read": read_credential["scopes"], "execute": exec_credential["scopes"]},
    )

    proxy_port = get_port()
    proxy_server = http.server.ThreadingHTTPServer(("127.0.0.1", proxy_port), Proxy)
    proxy_thread = threading.Thread(target=proxy_server.serve_forever, daemon=True)
    proxy_thread.start()
    PROFILE_URL = f"http://127.0.0.1:{proxy_port}"

    def configure(token_path):
        value, _ = run_cli(
            "service",
            "configure-token",
            "--url",
            PROFILE_URL,
            "--token-file",
            token_path,
            "--profile",
            "research",
        )
        return value

    configured = configure(read_file)
    status, _ = run_cli("--remote-profile", "research", "service", "status")
    schema, _ = run_cli("--remote-profile", "research", "service", "schema")
    discovery, _ = run_cli("--remote-profile", "research", "service", "discover")
    tasks, _ = run_cli(
        "--remote-profile",
        "research",
        "service",
        "tasks",
        dataset["id"],
        "--offset",
        "0",
        "--limit",
        "1",
    )
    attachments, _ = run_cli("--remote-profile", "research", "attachments", "list")
    if status["user"]["id"] != member["id"]:
        raise RuntimeError("read-only profile changed member identity")
    if schema.get("info", {}).get("version") != "1.0":
        raise RuntimeError("unexpected machine schema version")
    if "execute" in discovery.get("allowed_operations", []):
        raise RuntimeError("read-only discovery unexpectedly includes submit capability")
    if tasks.get("total") != 1 or tasks["tasks"][0].get("name") != TASK:
        raise RuntimeError("task discovery did not return the fixed fixture task")
    if (
        len(attachments.get("attachments", [])) != 1
        or len(attachments["attachments"][0]["versions"]) != 2
    ):
        raise RuntimeError("attachment discovery did not return both immutable versions")
    plan = {
        "service_url": PROFILE_URL,
        "member_id": member["id"],
        "dataset_id": dataset["id"],
        "dataset_reference": DATASET,
        "task": TASK,
        "agent": "oracle",
        "score_source": "fixture-verifier-v1",
        "attempts": 1,
        "concurrency": 1,
        "wall_seconds": 120,
        "environment_build_timeout_multiplier": "service default, frozen value to verify",
        "attachment_versions": [v1["version"]["id"], v2["version"]["id"]],
        "authorization": "read-only discovery completed; separately authorized isolated Oracle submissions",
    }
    (CAPTURE / "study-plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
    (CAPTURE / "study-plan.json").chmod(0o600)
    event(
        "read_only_discovery_complete",
        contract_version=discovery["contract_version"],
        allowed_operations=discovery["allowed_operations"],
        task_count=tasks["total"],
        attachment_versions=plan["attachment_versions"],
    )

    # Start the actual candidate supervisor; only its execution adapter is fixture-only.
    supervisor_log = (CAPTURE / "supervisor.log").open("w")
    worker_proc = subprocess.Popen(
        [sys.executable, "-m", "harbor_helper.worker", "supervise", str(STATE)],
        cwd=WORK,
        env=service_env,
        stdout=supervisor_log,
        stderr=supervisor_log,
        start_new_session=True,
    )
    for _ in range(300):
        marker = STATE / "scheduler.json"
        if marker.exists() and json.loads(marker.read_text()).get("pid") == worker_proc.pid:
            break
        if worker_proc.poll() is not None:
            raise RuntimeError("fixture supervisor exited before becoming ready")
        time.sleep(0.05)
    else:
        raise RuntimeError("fixture supervisor did not become ready")

    configured_exec = configure(exec_file)
    status_exec, _ = run_cli("--remote-profile", "research", "service", "status")
    if status_exec["user"]["id"] != member["id"] or status_exec["user"]["scopes"] != [
        "execute",
        "read",
    ]:
        raise RuntimeError("execute credential changed member identity or scopes")

    def submit(index, attachment_version):
        body = {
            "dataset": DATASET,
            "agent": "oracle",
            "task": TASK,
            "attempts": 1,
            "concurrency": 1,
            "wall_seconds": 120,
        }
        if attachment_version:
            body["attachment_version_id"] = attachment_version
        record = {
            "url": PROFILE_URL,
            "member_id": member["id"],
            "operation": "submit",
            "path": "/submissions",
            "idempotency_key": KEYS[index],
            "body": body,
            "authorized_scope": "read+execute; isolated fixture Oracle",
        }
        (CAPTURE / f"request-{index + 1}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n"
        )
        (CAPTURE / f"request-{index + 1}.json").chmod(0o600)
        return run_cli(
            "--remote-profile",
            "research",
            "submit",
            "--dataset",
            DATASET,
            "--agent",
            "oracle",
            "--task",
            TASK,
            "--attempts",
            "1",
            "--concurrency",
            "1",
            "--wall-seconds",
            "120",
            *(["--attachment-version-id", attachment_version] if attachment_version else []),
            "--idempotency-key",
            KEYS[index],
            allow_failure=(index == 0),
        )

    _, failed = submit(0, None)
    if failed.returncode == 0 or not PROXY_FAULT["used"]:
        raise RuntimeError("one-shot response-loss fault did not reach the submit client")
    event(
        "submit_response_lost",
        exit_code=failed.returncode,
        stdout=failed.stdout,
        stderr=failed.stderr,
    )

    configure(replacement_file)
    replacement_status, _ = run_cli("--remote-profile", "research", "service", "status")
    if replacement_status["user"]["id"] != member["id"]:
        raise RuntimeError("replacement credential is not for the original member")
    recovered, _ = run_cli("--remote-profile", "research", "service", "lookup", "submit", KEYS[0])
    event(
        "same_member_recovery",
        submission_id=recovered["id"],
        status=recovered["status"],
        new_key_created=False,
    )

    accepted = [recovered]
    for i, attachment_version in enumerate((v1["version"]["id"], v2["version"]["id"]), start=1):
        value, _ = submit(i, attachment_version)
        accepted.append(value)
        event(
            "submission_accepted",
            index=i,
            submission_id=value["id"],
            attachment_version_id=attachment_version,
        )

    # Same production HTTP/static/scheduler, with real browser submission controls.
    browser_inputs = {
        "url": API_URL,
        "dataset_id": dataset["id"],
        "versions": [v1["version"]["id"], v2["version"]["id"]],
    }
    (CAPTURE / "browser-inputs.json").write_text(json.dumps(browser_inputs))
    browser = subprocess.run(
        ["node", str(WT / "frontend/qa/final-integration-production.mjs")],
        env={**service_env, "HH_BROWSER_URL": API_URL, "HH_BROWSER_EVIDENCE": str(CAPTURE)},
        capture_output=True,
        check=False,
        timeout=90,
    )
    (CAPTURE / "browser.stdout").write_bytes(browser.stdout)
    (CAPTURE / "browser.stderr").write_bytes(browser.stderr)
    (CAPTURE / "browser.exit").write_text(str(browser.returncode) + "\n")
    assert browser.returncode == 0, "Browser submission flow failed; see raw browser.stderr"
    browser_rows = json.loads((CAPTURE / "browser-submissions.json").read_text())
    event("production_browser_submitted", submissions=[r["id"] for r in browser_rows])
    accepted.extend(browser_rows)

    run_rows = []
    for item in accepted:
        deadline = time.monotonic() + 60
        while True:
            state, _ = run_cli("--remote-profile", "research", "service", "query", item["id"])
            rid = state.get("run_id")
            if rid:
                row, _ = run_cli("--remote-profile", "research", "service", "query", rid)
                if row.get("report", {}).get("state") in {"available", "unavailable", "blocked"}:
                    break
            elif state.get("status") in {"failed", "cancelled"}:
                raise RuntimeError(f"submission did not produce run: {item['id']}")
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"fixture run exceeded 60-second observation window: {item['id']}"
                )
            time.sleep(0.5)
        report, _ = run_cli("--remote-profile", "research", "service", "report", rid)
        run_rows.append(
            {
                "submission_id": item["id"],
                "run_id": rid,
                "submission": item,
                "state": row,
                "report": report,
            }
        )
        event(
            "run_report",
            submission_id=item["id"],
            run_id=rid,
            resource=row.get("resource"),
            audit=row.get("audit"),
            report_state=row.get("report", {}).get("state"),
        )

    comparisons = []
    for left, right in ((0, 1), (1, 2), (3, 4), (4, 5)):
        value, _ = run_cli(
            "--remote-profile",
            "research",
            "compare",
            run_rows[left]["run_id"],
            run_rows[right]["run_id"],
        )
        comparisons.append(value)
        event(
            "comparison",
            left=run_rows[left]["run_id"],
            right=run_rows[right]["run_id"],
            comparable=value.get("comparable"),
            score_delta=value.get("mean_task_delta"),
            bundle_change=value.get("bundle_change"),
        )

    summary = {
        "fixed_candidate": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=WT, text=True
        ).strip(),
        "dataset_reference": DATASET,
        "dataset_id": dataset["id"],
        "task": TASK,
        "score_source": "fixture-verifier-v1",
        "member_id": member["id"],
        "profile_rotated_after_response_loss": True,
        "read_only_discovery": {
            "contract_version": discovery["contract_version"],
            "allowed_operations": discovery["allowed_operations"],
            "task_count": tasks["total"],
            "attachment_versions": plan["attachment_versions"],
        },
        "runs": [],
        "comparisons": comparisons,
        "scope": "candidate Python service + loopback HTTP + fixture source/execution adapters; no Hub, Docker, Harbor, model or paid request",
    }
    for row in run_rows:
        report = row["report"]
        summary["runs"].append(
            {
                "submission_id": row["submission_id"],
                "run_id": row["run_id"],
                "attachment": row["submission"].get("attachment"),
                "resource": row["state"].get("resource"),
                "audit": row["state"].get("audit"),
                "report_state": row["state"].get("report", {}).get("state"),
                "score": report.get("tasks", [{}])[0].get("mean_rewards"),
                "valid_attempts": report.get("tasks", [{}])[0].get("valid_attempts"),
                "effective": row["submission"].get("request"),
            }
        )
    assert [r["score"]["reward"] for r in summary["runs"]] == [0.0, 1.0, 0.0, 0.0, 1.0, 0.0]
    assert all(c["comparable"] for c in comparisons)
    assert [c["mean_task_delta"]["reward"] for c in comparisons] == [1.0, -1.0, 1.0, -1.0]
    # Store paths are canonical; snapshot historical v1 binding before a later publication.
    from harbor_helper.persistence.store import Store

    store = Store(STATE)
    frozen_path = store.path(run_rows[1]["run_id"]) / "manifest.json"
    frozen_before = frozen_path.read_bytes()
    third = session.post(
        f"/api/v1/attachments/{v1['attachment']['id']}/versions",
        files={"file": ("input.zip", archive("later"), "application/zip")},
        data={"metadata": "{}"},
        headers={"Idempotency-Key": "late-v3"},
    )
    assert third.status_code == 201
    assert frozen_path.read_bytes() == frozen_before
    assert json.loads(frozen_before)["service"]["attachment_version_id"] == v1["version"]["id"]
    # Revoke the old credential and prove it cannot read; replacement still finds original key.
    assert (
        session.post(f"/api/v1/access-credentials/{exec_credential['id']}/revoke").status_code
        == 200
    )
    old_token = exec_file.read_text().strip()
    denied = httpx.get(
        API_URL + "/api/v1/me", headers={"Authorization": "Bearer " + old_token}, trust_env=False
    )
    assert denied.status_code == 401
    assert (
        run_cli("--remote-profile", "research", "service", "lookup", "submit", KEYS[0])[0]["id"]
        == accepted[0]["id"]
    )
    # Synthetic audit damage only after a completed fixture run: resource remains released.
    rid = run_rows[-1]["run_id"]
    store.update(rid, audit_status="incomplete")
    gate, _ = run_cli("--remote-profile", "research", "service", "query", rid)
    assert gate["resource"]["state"] == "released" and gate["report"]["state"] == "blocked"
    _, blocked = run_cli(
        "--remote-profile", "research", "service", "report", rid, allow_failure=True
    )
    assert blocked.returncode == 1
    summary["synthetic_audit_damage"] = gate
    summary["old_token_revoked"] = True
    summary["historical_v1_manifest_unchanged_after_v3"] = hashlib.sha256(frozen_before).hexdigest()
    (CAPTURE / "results.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    (CAPTURE / "results.json").chmod(0o600)
    event(
        "completed",
        run_count=len(run_rows),
        comparison_count=len(comparisons),
        scheduler_pid=worker_proc.pid,
    )

finally:
    if proxy_server:
        proxy_server.shutdown()
        proxy_server.server_close()
    for proc in (api_proc, worker_proc):
        if proc and proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
    if worker_proc:
        # Test fixture worker descendants are terminated only when they still identify as children of this isolated supervisor.
        try:
            from harbor_helper.execution.worker import process_birth
            from harbor_helper.persistence.store import Store

            for row in Store(STATE).runs():
                pid = row.get("pid")
                if pid and process_birth(pid) == row.get("birth"):
                    os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            event("worker_already_exited")
    if http_log:
        http_log.close()
    if supervisor_log:
        supervisor_log.close()
    event(
        "process_cleanup",
        api_stopped=bool(api_proc and api_proc.poll() is not None),
        supervisor_stopped=bool(worker_proc and worker_proc.poll() is not None),
        proxy_stopped=proxy_server is not None,
    )

    if worker_proc:
        deadline = time.monotonic() + 5
        while any(
            r.get("pid") and process_birth(r["pid"]) == r.get("birth") for r in Store(STATE).runs()
        ):
            if time.monotonic() > deadline:
                raise RuntimeError("Fixture worker resource birth remains after teardown")
            time.sleep(0.05)
    ports_closed = {}
    for label, port in (("api", locals().get("api_port")), ("proxy", locals().get("proxy_port"))):
        if port is not None:
            with socket.socket() as probe:
                ports_closed[label] = probe.connect_ex(("127.0.0.1", port)) != 0
    event("teardown_identity", ports_closed=ports_closed, worker_births_released=True)
    assert all(ports_closed.values())
