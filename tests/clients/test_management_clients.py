"""Real HTTP, CLI, SDK and official stdio MCP against independent synthetic state."""

import asyncio
import json
import subprocess
import sys
import zipfile

import httpx
import pytest
from support.attachment_support import archive
from support.http_support import PASSWORD, WRITE

from harbor_helper.sdk import Client, RemoteError
from harbor_helper.security.files import secure_write


def test_management_clients_share_permissions_downloads_and_recycle_events(http_service):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    p, url, root = http_service
    admin = next(u for u in p.data.users() if u["role"] == "admin")
    own = p.app.attachments.write(p.actor, "attachment_create", "own", {"name": "Own"}, archive())
    other = p.app.attachments.write(
        admin, "attachment_create", "other", {"name": "Other"}, archive()
    )
    vid, other_id = own["version"]["id"], other["version"]["id"]
    profile_root = p.home / ".config/harbor-helper/remote"
    for directory in (
        p.home / ".config",
        p.home / ".config/harbor-helper",
        profile_root,
        profile_root / "profiles",
    ):
        directory.mkdir(mode=0o700, exist_ok=True)

    def credential(username, profile, scopes):
        with httpx.Client(base_url=url + "/api/v1", headers=WRITE, trust_env=False) as web:
            assert (
                web.post(
                    "/auth/login", json={"username": username, "password": PASSWORD}
                ).status_code
                == 200
            )
            response = web.post(
                "/access-credentials",
                json={"name": profile, "current_password": PASSWORD, "scopes": scopes},
            )
            assert response.status_code == 201, response.text
        token = response.json()["token"]
        secure_write(
            profile_root / f"profiles/{profile}.json",
            {"url": url, "token": token, "user": {"id": username}, "authentication": "automation"},
        )
        return Client(url, token)

    member = credential("alice", "member", ["read", "attachment_download", "recycle_own"])
    manager = credential("admin", "manager", ["read", "datasets_manage", "recycle_all", "purge"])
    old = credential("alice", "old", ["read", "attachments"])
    output = root / "sdk.zip"
    member.fetch_attachment(vid, output)
    with zipfile.ZipFile(output) as bundle:
        assert bundle.read("sdk/readme") == b"v1"
    with pytest.raises(RemoteError) as error:
        old.fetch_attachment(vid, root / "forbidden.zip")
    assert error.value.status == 403
    with pytest.raises(RemoteError) as error:
        member.preview_recycle("attachment_version", other_id)
    assert error.value.status == 403
    dataset = manager.register_dataset("Machine source", "team/machine")
    with pytest.raises(RemoteError) as error:
        member.register_dataset("Forbidden source", "team/forbidden")
    assert error.value.status == 403
    assert dataset["id"] in {d["id"] for d in manager.list_datasets()["datasets"]}

    def cli(profile, *args):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "harbor_helper.commands.main",
                "--remote-profile",
                profile,
                *args,
                "--json",
            ],
            cwd=p.cwd,
            env=p.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    assert cli("member", "manage", "requests").returncode == 0
    result = cli("old", "attachments", "download", vid, "--output", str(root / "cli-forbidden.zip"))
    assert result.returncode != 0 and not (root / "cli-forbidden.zip").exists()
    result = cli("member", "attachments", "download", vid, "--output", str(root / "cli.zip"))
    assert result.returncode == 0, result.stderr
    result = cli(
        "member",
        "manage",
        "recycle",
        "--items",
        json.dumps([{"kind": "attachment_version", "object_id": vid}]),
    )
    assert result.returncode == 0, result.stderr
    event_id = json.loads(result.stdout)["results"][0]["event"]["id"]
    with pytest.raises(RemoteError) as error:
        member.fetch_attachment(vid, root / "recycled.zip")
    assert error.value.status == 409

    async def roundtrip(profile):
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "harbor_helper.commands.main",
                "mcp",
                "--profile",
                profile,
                "--download-root",
                str(root),
            ],
            cwd=str(p.cwd),
            env=p.env,
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            assert tools["purge"].annotations is not None
            assert tools["purge"].annotations.destructiveHint
            assert {
                "dataset_versions",
                "preview_dataset",
                "confirm_dataset",
                "dataset_default",
                "dataset_parameters",
                "merge_datasets",
                "recycle",
                "restore",
                "fetch_attachment",
            } <= tools.keys()
            if profile == "member":
                restored = await session.call_tool("restore", {"event_id": event_id})
                assert not restored.isError
                downloaded = await session.call_tool(
                    "fetch_attachment", {"version_id": vid, "output": "mcp.zip"}
                )
                assert not downloaded.isError
                denied = await session.call_tool(
                    "preview_recycle", {"kind": "attachment_version", "object_id": other_id}
                )
                assert denied.isError
                denied = await session.call_tool(
                    "purge", {"event_id": event_id, "idempotency_key": "member-purge"}
                )
                assert denied.isError
                recycled = await session.call_tool(
                    "recycle", {"items": [{"kind": "attachment_version", "object_id": vid}]}
                )
                assert not recycled.isError
                assert recycled.content[0].type == "text"
                return json.loads(recycled.content[0].text)["results"][0]["event"]["id"]
            removed = await session.call_tool(
                "purge", {"event_id": current_event, "idempotency_key": "manager-purge"}
            )
            assert not removed.isError
            assert removed.content[0].type == "text"
            assert json.loads(removed.content[0].text)["state"] == "purged"

    current_event = asyncio.run(roundtrip("member"))
    assert current_event != event_id
    asyncio.run(roundtrip("manager"))
    with zipfile.ZipFile(root / "mcp.zip") as bundle:
        assert bundle.read("sdk/readme") == b"v1"
    with pytest.raises(RemoteError) as error:
        member.fetch_attachment(vid, root / "purged.zip")
    assert error.value.status == 410
