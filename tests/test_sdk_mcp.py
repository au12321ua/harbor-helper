"""sdk mcp behavior with isolated synthetic inputs."""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import httpx
import pytest
from http_support import PASSWORD, WRITE
from process_support import wait

from harbor_helper.sdk import Client, RemoteError
from harbor_helper.security.files import secure_write


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
            from attachment_support import archive

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
