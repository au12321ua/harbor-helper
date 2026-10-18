"""Public SDK and official stdio MCP against real HTTP; fake external execution only."""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import httpx
import pytest
from test_automation_http import PASSWORD, WRITE
from test_automation_http import (
    http_service as http_service,  # noqa: PLC0414  # Reuse isolated process fixture.
)
from test_service_process import wait

from harbor_helper.sdk import Client, RemoteError
from harbor_helper.security.files import secure_write
from harbor_helper.security.local_paths import LocalRoot


def test_sdk_stdio_and_web_share_operation_and_evidence(http_service):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    p, url, root = http_service
    web = httpx.Client(base_url=url + "/api/v1", headers=WRITE, trust_env=False)
    assert (
        web.post("/auth/login", json={"username": "alice", "password": PASSWORD}).status_code == 200
    )
    issued = web.post(
        "/access-credentials",
        json={
            "name": "sdk",
            "current_password": PASSWORD,
            "scopes": ["read", "execute", "cancel_own", "attachments"],
        },
    )
    assert issued.status_code == 201, issued.text
    pat = issued.json()["token"]
    sdk = Client(url, pat)
    assert "submit" in sdk.discover()["allowed_operations"]
    profile_root = p.home / ".config/harbor-helper/remote"
    for directory in (
        p.home / ".config",
        p.home / ".config/harbor-helper",
        profile_root,
        profile_root / "profiles",
    ):
        directory.mkdir(mode=0o700, exist_ok=True)
    secure_write(
        profile_root / "profiles/agent.json",
        {"url": url, "token": pat, "user": {"id": p.actor["id"]}, "authentication": "automation"},
    )
    accepted = sdk.submit({"agent": "oracle"}, "sdk-shared")
    assert accepted["operation_id"].startswith("op-")
    assert (
        web.post(
            "/submissions", json={"agent": "oracle"}, headers={"Idempotency-Key": "sdk-shared"}
        ).json()["operation_id"]
        == accepted["operation_id"]
    )
    assert sdk.submit({"agent": "oracle"}, "sdk-shared")["id"] == accepted["id"]
    with pytest.raises(RemoteError) as conflict:
        sdk.submit({"agent": "oracle", "name": "changed"}, "sdk-shared")
    assert conflict.value.status == 409
    assert conflict.value.operation_id == accepted["operation_id"]
    assert conflict.value.idempotency_key == "sdk-shared"

    async def mcp_roundtrip():
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "harbor_helper.commands.main",
                "mcp",
                "--profile",
                "agent",
                "--upload-root",
                str(root),
                "--download-root",
                str(root),
            ],
            cwd=str(p.cwd),
            env=p.env,
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {
                "attachment",
                "submit",
                "history",
                "get_report",
                "fetch_evidence",
                "compare",
            } <= names
            result = await session.call_tool(
                "submit", {"body": {"agent": "oracle"}, "idempotency_key": "sdk-shared"}
            )
            assert not result.isError
            assert result.content[0].type == "text"
            value = json.loads(result.content[0].text)
            assert value["operation_id"] == accepted["operation_id"]
            rejected = await session.call_tool(
                "submit",
                {"body": {"agent": "oracle", "name": "changed"}, "idempotency_key": "sdk-shared"},
            )
            assert rejected.isError
            assert rejected.content[0].type == "text"
            assert json.loads(rejected.content[0].text)["code"] == "idempotency_conflict"
            bad_path = await session.call_tool(
                "fetch_evidence", {"run_id": "fake", "output": "../escape"}
            )
            assert bad_path.isError
            history = await session.call_tool(
                "lookup_by_key", {"operation": "submit", "key": "sdk-shared"}
            )
            assert not history.isError
            assert history.content[0].type == "text"
            assert (
                json.loads(history.content[0].text)["operations"][0]["id"]
                == accepted["operation_id"]
            )
            from test_attachments import archive

            bundle = root / "mcp-input.zip"
            bundle.write_bytes(archive().getvalue())

            async def invoke(name, args):
                reply = await session.call_tool(name, args)
                assert not reply.isError, reply
                assert reply.content[0].type == "text"
                return json.loads(reply.content[0].text)

            attachment = await invoke(
                "attachment",
                {
                    "action": "create",
                    "path": "mcp-input.zip",
                    "name": "MCP input",
                    "idempotency_key": "mcp-attachment",
                },
            )
            aid = attachment["attachment"]["id"]
            published = await invoke(
                "attachment",
                {
                    "action": "publish",
                    "path": "mcp-input.zip",
                    "target_id": aid,
                    "idempotency_key": "mcp-publish",
                },
            )
            assert published["version"]["number"] == 2
            derived = await invoke(
                "attachment",
                {
                    "action": "derive",
                    "path": "mcp-input.zip",
                    "target_id": attachment["version"]["id"],
                    "name": "Derived",
                    "idempotency_key": "mcp-derive",
                },
            )
            assert derived["version"]["source_version_id"] == attachment["version"]["id"]
            uploaded = await invoke(
                "submit",
                {
                    "body": {
                        "agent": "oracle",
                        "attachment_version_id": attachment["version"]["id"],
                    },
                    "idempotency_key": "mcp-uploaded",
                },
            )
            rid_mcp = p.run_id(uploaded)
            p.terminal(rid_mcp)
            wait(lambda: p.data.store.get(rid_mcp)["audit_status"] == "clean")
            await invoke("get_state", {"record_id": rid_mcp})
            await invoke("get_report", {"run_id": rid_mcp})
            await invoke("get_logs", {"run_id": rid_mcp})
            await invoke("get_artifacts", {"run_id": rid_mcp})
            await invoke("compare", {"left": rid_mcp, "right": rid_mcp})
            hold = p.data.root / "prepare-hold"
            hold.touch()
            try:
                rerun = await invoke("rerun", {"run_id": rid_mcp, "idempotency_key": "mcp-rerun"})
                assert rerun["parent"] == rid_mcp
                await invoke("cancel", {"record_id": rerun["id"]})
                retried = await invoke(
                    "retry", {"run_id": rid_mcp, "body": {}, "idempotency_key": "mcp-retry"}
                )
                await invoke("cancel", {"record_id": retried["id"]})
            finally:
                hold.unlink(missing_ok=True)

    asyncio.run(mcp_roundtrip())
    wait(lambda: p.data.submission(accepted["id"])["run_id"])
    rid = p.data.submission(accepted["id"])["run_id"]
    wait(lambda: p.data.store.get(rid)["audit_status"] == "clean")
    assert sdk.get_report(rid) == web.get(f"/runs/{rid}/report").json()
    assert sdk.get_state(rid) == web.get(f"/runs/{rid}").json()
    assert sdk.get_logs(rid) == web.get(f"/runs/{rid}/logs").json()
    assert web.get(f"/runs/{rid}/evidence").status_code == 403
    admin = httpx.Client(base_url=url + "/api/v1", headers=WRITE, trust_env=False)
    admin.post("/auth/login", json={"username": "admin", "password": PASSWORD})
    assert admin.get(f"/runs/{rid}/evidence").status_code == 200
    assert (
        admin.post(
            f"/admin/users/{p.actor['id']}/evidence-grant", json={"enabled": True}
        ).status_code
        == 200
    )
    # Existing read PAT never expands its scopes.
    with pytest.raises(RemoteError) as denied:
        sdk.evidence_manifest(rid)
    assert denied.value.status == 403
    granted = web.post(
        "/access-credentials",
        json={"name": "evidence", "current_password": PASSWORD, "scopes": ["read", "evidence"]},
    ).json()
    evidence = Client(url, granted["token"])
    manifest = evidence.evidence_manifest(rid)
    assert manifest == web.get(f"/runs/{rid}/evidence").json()
    assert manifest["files"]
    file = manifest["files"][0]
    result = evidence.fetch_evidence(rid, root / "download.bin", file["id"])
    assert (
        result["sha256"]
        == file["sha256"]
        == hashlib.sha256((root / "download.bin").read_bytes()).hexdigest()
    )
    secure_write(
        profile_root / "profiles/agent.json",
        {
            "url": url,
            "token": granted["token"],
            "user": {"id": p.actor["id"]},
            "authentication": "automation",
        },
    )

    async def mcp_evidence():
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "harbor_helper.commands.main",
                "mcp",
                "--profile",
                "agent",
                "--download-root",
                str(root),
            ],
            cwd=str(p.cwd),
            env=p.env,
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            reply = await session.call_tool("evidence_manifest", {"run_id": rid})
            assert not reply.isError
            download = await session.call_tool(
                "fetch_evidence",
                {"run_id": rid, "file_id": file["id"], "output": "mcp-download.bin"},
            )
            assert not download.isError
            assert download.content[0].type == "text"
            assert json.loads(download.content[0].text)["sha256"] == file["sha256"]
            package = await session.call_tool(
                "fetch_evidence", {"run_id": rid, "output": "mcp-package.zip"}
            )
            assert not package.isError

    asyncio.run(mcp_evidence())
    with pytest.raises(FileExistsError):
        evidence.fetch_evidence(rid, root / "download.bin", file["id"])
    assert (
        admin.post(
            f"/admin/users/{p.actor['id']}/evidence-grant", json={"enabled": False}
        ).status_code
        == 200
    )
    assert web.get(f"/runs/{rid}/evidence").status_code == 403
    with pytest.raises(RemoteError) as revoked:
        evidence.discover()
    assert revoked.value.status == 401
    assert (
        admin.post(
            f"/admin/users/{p.actor['id']}/evidence-grant", json={"enabled": True}
        ).status_code
        == 200
    )
    with pytest.raises(RemoteError) as still_revoked:
        evidence.discover()
    assert still_revoked.value.status == 401
    assert sdk.discover()["scopes"] == ["attachments", "cancel_own", "execute", "read"]
    for file in [p.data.root / "queue.sqlite", p.data.root / "queue.sqlite-wal"]:
        if file.exists():
            assert pat.encode() not in file.read_bytes()
    web.close()
    admin.close()


def test_local_root_rejects_recursive_links_and_pins_parent(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("private")
    (root / "link").symlink_to(outside, target_is_directory=True)
    local = LocalRoot(root)
    try:
        for path in ("../outside/secret", str(outside / "secret"), "link/secret"):
            with pytest.raises((ValueError, OSError)), local.upload(path):
                pytest.fail("escaped upload")
        bundle = root / "bundle"
        bundle.mkdir()
        (bundle / "nested").symlink_to(outside)
        with pytest.raises(OSError), local.upload("bundle"):
            pytest.fail("recursive symlink accepted")
        folder = root / "target"
        folder.mkdir()
        with local.destination("target/new") as target:
            folder.rename(root / "old-target")
            folder.symlink_to(outside)
            with target.open("xb") as stream:
                stream.write(b"safe")
        assert (root / "old-target/new").read_bytes() == b"safe"
        assert not (outside / "new").exists()
    finally:
        local.close()


def test_rejected_history_redecides_and_bounds_attempts(tmp_path, monkeypatch):
    from test_service import data as data_fixture

    from harbor_helper.service.application import Application
    from harbor_helper.service.history import listing
    from harbor_helper.service.primitives import ServiceError

    data = data_fixture._get_wrapped_function()(tmp_path)
    app = Application(data.root)
    user = data.users()[0]
    # Use production maintenance writer; no execution or external requests.
    from harbor_helper.persistence.files import write_json

    write_json(
        data.root / "admission.json",
        {"paused": True, "reason": "fixture", "retry_at": None, "updated": 1.0},
    )
    for _ in range(40):
        with pytest.raises(ServiceError) as rejected:
            app.accept(user, {"agent": "oracle"}, "same-rejected-key")
        assert rejected.value.code == "maintenance_paused"
    history = listing(data.store, user)
    assert history["total"] == 1
    row = history["operations"][0]
    assert row["attempts"] == 40 and len(row["recent"]) == history["attempt_limit"] == 32
    assert row["summarized_attempts"] == 8
    with data.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 0
    assert data.store.runs() == []
    write_json(
        data.root / "admission.json",
        {"paused": False, "reason": "", "retry_at": None, "updated": 2.0},
    )
    accepted = app.accept(user, {"agent": "oracle"}, "same-rejected-key")
    assert accepted["operation_id"] == row["id"]
    assert app.accept(user, {"agent": "oracle"}, "same-rejected-key")["id"] == accepted["id"]
    with pytest.raises(ServiceError) as conflict:
        app.accept(user, {"agent": "oracle", "name": "changed"}, "same-rejected-key")
    assert conflict.value.code == "idempotency_conflict"
    assert listing(data.store, user)["operations"][0]["status"] == "accepted"
    assert app.accept(user, {"agent": "oracle"}, "explicit-new")["id"] != accepted["id"]
    with pytest.raises(ServiceError):
        app.accept(user, {}, "missing-parent", parent="hh-missing-target")
    rejected_target = listing(data.store, user, key="missing-parent")["operations"][0]
    assert rejected_target["request"] == {
        "body": {},
        "parent": "hh-missing-target",
        "recovery": None,
    }
    with pytest.raises(ServiceError) as unsafe:
        app.accept(user, {}, "unsafe-parent", parent="hh_pat_v1_" + "A" * 43)
    assert unsafe.value.code == "access_plaintext"
    assert listing(data.store, user, key="unsafe-parent")["total"] == 0


def test_attachment_business_rejection_is_durable_and_retriable(tmp_path):
    from test_attachments import archive
    from test_service import data as data_fixture

    from harbor_helper.service.application import Application
    from harbor_helper.service.history import listing
    from harbor_helper.service.primitives import ServiceError

    data = data_fixture._get_wrapped_function()(tmp_path)
    app = Application(data.root)
    user = data.users()[0]
    first = app.attachments.write(user, "attachment_create", "input", {"name": "Input"}, archive())
    aid = first["attachment"]["id"]
    app.attachments.update(user, aid, {"enabled": False})
    with pytest.raises(ServiceError) as rejected:
        app.attachments.write(
            user, "attachment_publish", "publish", {"attachment_id": aid}, archive()
        )
    assert rejected.value.code == "attachment_disabled"
    operation_id = rejected.value.operation_id
    app.attachments.update(user, aid, {"enabled": True})
    result = app.attachments.write(
        user, "attachment_publish", "publish", {"attachment_id": aid}, archive()
    )
    assert result["operation_id"] == operation_id
    assert result["version"]["number"] == 2
    entry = listing(data.store, user, operation="attachment_publish")["operations"][0]
    assert entry["request"]["attachment_id"] == aid
    assert entry["request"]["digest"] == result["version"]["digest"]
    assert (
        listing(data.store, user, operation="attachment_publish")["operations"][0]["attempts"] == 2
    )


def test_text_binary_and_gzip_secret_audit(tmp_path):
    import gzip

    from harbor_helper.security.credentials import scan_tree, scrub_run

    secret = "FAKE-TEXT-BINARY-SDK-SECRET-1234"
    text = tmp_path / "tool-output.json"
    text.write_text(json.dumps({"output": secret}))
    clean = tmp_path / "part.step"
    original = b"CAD binary\x00\xff\x01"
    clean.write_bytes(original)
    dirty = tmp_path / "dirty.bin"
    dirty_bytes = b"\x00" + secret.encode() + b"\xff"
    dirty.write_bytes(dirty_bytes)
    compressed = tmp_path / "compressed.gz"
    compressed.write_bytes(gzip.compress(secret.encode()))
    scrub_run(tmp_path, [secret])
    assert secret not in text.read_text()
    assert clean.read_bytes() == original
    assert dirty.read_bytes() == dirty_bytes
    assert gzip.decompress(compressed.read_bytes()) == secret.encode()
    assert not scan_tree(tmp_path, [secret])["clean"]
    dirty.unlink()
    assert not scan_tree(tmp_path, [secret])[
        "clean"
    ]  # compressed match independently blocks evidence
    compressed.unlink()
    assert scan_tree(tmp_path, [secret])["clean"]


def test_snapshot_releases_lock_and_survives_retention(tmp_path):
    import time

    from test_service import data as data_fixture

    from harbor_helper.service.application import Application
    from harbor_helper.service.lifecycle import maintenance
    from harbor_helper.service.materials import inventory, manifest, snapshot
    from harbor_helper.service.primitives import ServiceError

    data = data_fixture._get_wrapped_function()(tmp_path)
    admin = next(u for u in data.users() if u["role"] == "admin")
    # Oracle fixture: explicit CLEAN terminal run with valid fixed metadata.
    app = Application(data.root)
    accepted = app.accept(admin, {"agent": "oracle"}, "snapshot")
    from pytest import MonkeyPatch
    from test_service import preparation as prepare_fixture

    patch = MonkeyPatch()
    try:
        prepare_fixture._get_wrapped_function()(patch)
        from harbor_helper.service.lifecycle import prepare_one

        prepare_one(data.store)
    finally:
        patch.undo()
    rid = data.submission(accepted["id"])["run_id"]
    data.store.update(
        rid, status="succeeded", audit_status="clean", finished=time.time() - 30 * 86400
    )
    folder = data.store.path(rid) / "harbor" / rid / "fixture" / "artifacts"
    folder.mkdir(parents=True)
    payload = bytes(range(256)) * 8192
    (folder / "part.bin").write_bytes(payload)
    value = inventory(data.store, rid)
    item = next(x for x in value["files"] if x["category"] == "artifact")
    stream, size, sha = snapshot(app, admin, rid, item["id"])
    assert size == len(payload) and sha == hashlib.sha256(payload).hexdigest()
    # Maintenance must complete while the caller has not consumed a single byte.
    maintenance(data.store)
    assert stream.read() == payload
    stream.close()
    observed = manifest(app, admin, rid)
    assert observed["state"] == "expired"
    tombstone = next(x for x in observed["files"] if x["id"] == item["id"])
    assert tombstone["status"] == "expired" and tombstone["sha256"] == sha
    with pytest.raises(ServiceError) as expired:
        snapshot(app, admin, rid, item["id"])
    assert expired.value.status == 410


@pytest.mark.parametrize("kind", ["clean", "binary_secret", "gzip_secret"])
def test_nontext_audit_blocks_entire_run_and_report(tmp_path, kind):
    import gzip

    from pytest import MonkeyPatch
    from test_service import KEYS
    from test_service import data as data_fixture
    from test_service import preparation as preparation_fixture

    from harbor_helper.execution.audit import audit_finished
    from harbor_helper.service.application import Application
    from harbor_helper.service.lifecycle import prepare_one
    from harbor_helper.service.primitives import ServiceError

    data = data_fixture._get_wrapped_function()(tmp_path)
    app = Application(data.root)
    user = data.users()[0]
    accepted = app.accept(user, {"model_profile": "m1"}, "binary-audit")
    patch = MonkeyPatch()
    try:
        preparation_fixture._get_wrapped_function()(patch)
        prepare_one(data.store)
    finally:
        patch.undo()
    rid = data.submission(accepted["id"])["run_id"]
    data.store.update(rid, status="succeeded")
    path = data.store.path(rid) / "payload.bin"
    original = b"CAD\x00\xff" if kind == "clean" else b"\x00" + KEYS[0].encode() + b"\xff"
    if kind == "gzip_secret":
        path = path.with_suffix(".gz")
        original = gzip.compress(KEYS[0].encode())
    path.write_bytes(original)
    clean = audit_finished(data.store, data.store.get(rid))
    assert clean == (kind == "clean")
    assert path.read_bytes() == original
    assert data.store.get(rid)["status"] in {
        "succeeded",
        "failed",
    }  # Both are resource-released terminal states.
    if kind != "clean":
        assert data.store.get(rid)["audit_status"] == "incomplete"
        assert not (data.store.path(rid) / "report.json").exists()
        with pytest.raises(ServiceError) as blocked:
            app.safe_report(rid)
        assert blocked.value.code == "audit_incomplete"


@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
def test_operation_submission_atomic_process_death(tmp_path, phase):
    import os
    import subprocess

    from test_service import data as data_fixture

    from harbor_helper.service.application import Application
    from harbor_helper.service.history import listing

    data = data_fixture._get_wrapped_function()(tmp_path)
    script = tmp_path / "crash.py"
    script.write_text("""
import os,sys
from contextlib import contextmanager
from harbor_helper.service.application import Application
app=Application(sys.argv[1]);original=app.store.connect
class Proxy:
    def __init__(self, db):self.db=db;self.written=False
    def execute(self,sql,*args):
        result=self.db.execute(sql,*args)
        if sql.startswith("INSERT INTO operations"):
            self.written=True
            if sys.argv[2]=="before_commit":os._exit(71)
        return result
@contextmanager
def connection():
    with original() as db:
        proxy=Proxy(db);yield proxy
    if proxy.written and sys.argv[2]=="after_commit":os._exit(72)
app.store.connect=connection
app.accept(app.data.users()[0],{"agent":"oracle"},"crash-key")
""")
    result = subprocess.run(
        [sys.executable, str(script), str(data.root), phase],
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path / "home"),
            "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
        },
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == (71 if phase == "before_commit" else 72), result.stderr
    with data.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == int(
            phase == "after_commit"
        )
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == int(
            phase == "after_commit"
        )
    app = Application(data.root)
    user = app.data.users()[0]
    accepted = app.accept(user, {"agent": "oracle"}, "crash-key")
    assert listing(data.store, user)["operations"][0]["id"] == accepted["operation_id"]
    with data.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 1


@pytest.mark.parametrize("username", ["alice", "admin"])
@pytest.mark.parametrize("account_grant", [False, True])
@pytest.mark.parametrize("scopes", [None, ["read"], ["evidence"], ["read", "evidence"]])
def test_evidence_authorization_matrix(tmp_path, username, account_grant, scopes):
    from pytest import MonkeyPatch
    from test_service import PASSWORD, client
    from test_service import data as data_fixture
    from test_service import preparation as preparation_fixture

    from harbor_helper.execution.audit import audit_finished
    from harbor_helper.service.access import grant
    from harbor_helper.service.application import Application
    from harbor_helper.service.lifecycle import prepare_one

    data = data_fixture._get_wrapped_function()(tmp_path)
    admin = next(u for u in data.users() if u["role"] == "admin")
    target = next(u for u in data.users() if u["username"] == username)
    app = Application(data.root)
    submission = app.accept(admin, {"agent": "oracle"}, "matrix")
    patch = MonkeyPatch()
    try:
        preparation_fixture._get_wrapped_function()(patch)
        prepare_one(data.store)
    finally:
        patch.undo()
    rid = data.submission(submission["id"])["run_id"]
    data.store.update(rid, status="succeeded")
    assert audit_finished(data.store, data.store.get(rid))
    if username == "admin":
        from harbor_helper.service.primitives import ServiceError

        with pytest.raises(ServiceError, match="管理员默认"):
            grant(data, admin, target["id"], account_grant)
    else:
        grant(data, admin, target["id"], account_grant)
    qualified = username == "admin" or account_grant
    web = client(data, username)
    caller = web
    if scopes is not None:
        issuance = web.post(
            "/api/v1/access-credentials",
            headers=WRITE,
            json={"name": "matrix", "current_password": PASSWORD, "scopes": scopes},
        )
        if "evidence" in scopes and (not qualified or "read" not in scopes):
            assert issuance.status_code == 403
            return
        assert issuance.status_code == 201, issuance.text
        from fastapi.testclient import TestClient

        from harbor_helper.service.api import create_app

        caller = TestClient(create_app(data.root, start_scheduler=False))
        caller.headers.update({"Authorization": "Bearer " + issuance.json()["token"]})
    response = caller.get(f"/api/v1/runs/{rid}/evidence")
    permitted = qualified and (scopes is None or "evidence" in scopes)
    assert response.status_code == (200 if permitted else 403), response.text
    discovery = caller.get("/api/v1/machine/discovery").json()
    assert ("evidence_manifest" in discovery["allowed_operations"]) == permitted
    # read's pre-existing safe views remain readable regardless of account grant.
    assert caller.get(f"/api/v1/runs/{rid}/logs").status_code == 200
    assert caller.get(f"/api/v1/runs/{rid}/report").status_code == 200


def test_real_http_slow_download_and_disconnect_do_not_hold_maintenance(http_service):
    import time

    from harbor_helper.service.lifecycle import maintenance
    from harbor_helper.service.materials import inventory

    p, url, _root = http_service
    with httpx.Client(base_url=url + "/api/v1", headers=WRITE, trust_env=False) as web:
        assert (
            web.post("/auth/login", json={"username": "admin", "password": PASSWORD}).status_code
            == 200
        )
        accepted = web.post(
            "/submissions", json={"agent": "oracle"}, headers={"Idempotency-Key": "slow"}
        ).json()
        rid = p.run_id(accepted)
        p.terminal(rid)
        wait(lambda: p.data.store.get(rid)["audit_status"] == "clean")
        folder = p.data.store.path(rid) / "harbor" / rid / "fixture" / "artifacts"
        folder.mkdir(parents=True)
        payload = bytes(range(256)) * 32768
        (folder / "large.bin").write_bytes(payload)
        value = inventory(p.data.store, rid)
        file = next(f for f in value["files"] if f["name"].endswith("large.bin"))
        with web.stream("GET", f"/runs/{rid}/evidence/files/{file['id']}") as slow:
            assert slow.status_code == 200
            iterator = slow.iter_bytes(65536)
            first = next(iterator)
            # A second HTTP transfer is abandoned after headers. Server owns cleanup.
            with web.stream("GET", f"/runs/{rid}/evidence/package") as abandoned:
                assert abandoned.status_code == 200
                next(abandoned.iter_bytes(1024))
            p.data.store.update(rid, finished=time.time() - 30 * 86400)
            started = time.monotonic()
            maintenance(p.data.store)
            assert time.monotonic() - started < 3
            assert b"".join([first, *iterator]) == payload
        assert web.get(f"/runs/{rid}/evidence/files/{file['id']}").status_code == 410


def test_admin_real_http_zip_contents_and_authorization_failures(http_service):
    import io
    import zipfile

    p, url, _root = http_service
    with httpx.Client(base_url=url + "/api/v1", headers=WRITE, trust_env=False) as web:
        assert (
            web.post("/auth/login", json={"username": "admin", "password": PASSWORD}).status_code
            == 200
        )
        accepted = web.post(
            "/submissions", json={"agent": "oracle"}, headers={"Idempotency-Key": "admin-zip"}
        ).json()
        rid = p.run_id(accepted)
        p.terminal(rid)
        wait(lambda: p.data.store.get(rid)["audit_status"] == "clean")
        folder = p.data.store.path(rid) / "harbor" / rid / "fixture" / "artifacts"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "proof.txt").write_text("synthetic-content-proof")
        from harbor_helper.service.materials import inventory

        inventory(p.data.store, rid)
        manifest = web.get(f"/runs/{rid}/evidence")
        assert manifest.status_code == 200
        response = web.get(f"/runs/{rid}/evidence/package")
        assert response.status_code == 200
        assert ".zip" in response.headers["content-disposition"]
        assert zipfile.is_zipfile(io.BytesIO(response.content))
        (_root / "verified-materials.zip").write_bytes(response.content)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            packed = json.loads(archive.read("materials.json"))
            assert packed["run_id"] == rid
            file = next(f for f in packed["files"] if f["name"].endswith("proof.txt"))
            content = archive.read(file["name"])
            assert content == b"synthetic-content-proof"
            for name in archive.namelist():
                assert all(key.encode() not in archive.read(name) for key in p.keys)
            assert hashlib.sha256(content).hexdigest() == file["sha256"]
            assert all(
                not name.startswith("/") and ".." not in Path(name).parts
                for name in archive.namelist()
            )
        assert (
            web.post("/auth/login", json={"username": "alice", "password": PASSWORD}).status_code
            == 200
        )
        assert web.get(f"/runs/{rid}/evidence/package").status_code == 403
        web.cookies.clear()
        assert web.get(f"/runs/{rid}/evidence/package").status_code == 401
