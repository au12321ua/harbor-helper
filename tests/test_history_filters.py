"""History filter parity through HTTP, public SDK, CLI and official stdio MCP."""

import asyncio
import json
import sys

import httpx
import pytest
from http_support import PASSWORD, WRITE, cli

from harbor_helper.sdk import Client
from harbor_helper.security.files import secure_write


def test_history_filter_parity_across_public_entries(http_service):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    p, url, root = http_service
    bob = p.data.create_user("bob", PASSWORD)
    ids = []
    for username, prefix in (("alice", "alice"), ("bob", "bob")):
        with httpx.Client(base_url=url + "/api/v1", headers=WRITE, trust_env=False) as browser:
            assert (
                browser.post(
                    "/auth/login", json={"username": username, "password": PASSWORD}
                ).status_code
                == 200
            )
            issued = browser.post(
                "/access-credentials",
                json={"name": "history", "current_password": PASSWORD, "scopes": ["read"]},
            )
            assert issued.status_code == 201, issued.text
            if username == "alice":
                pat = issued.json()["token"]
            accepted = browser.post(
                "/submissions",
                json={"agent": "oracle"},
                headers={"Idempotency-Key": prefix + "-accepted"},
            )
            assert accepted.status_code == 202, accepted.text
            ids.append(accepted.json()["operation_id"])
            rejected = browser.post(
                "/runs/hh-nonexistent/rerun",
                json={},
                headers={"Idempotency-Key": prefix + "-rejected"},
            )
            assert rejected.status_code == 422, rejected.text
            assert rejected.json()["code"] == "invalid_operation"
            ids.append(rejected.json()["operation_id"])
    # Fixed history timestamps exercise inclusive time boundaries, including epoch zero.
    # Only fixture metadata changes; every operation above came through real HTTP decisions.
    with p.data.store.connect() as db:
        for operation_id, created in zip(ids, (-10.0, 0.0, 20.0, 30.0), strict=True):
            db.execute("UPDATE operations SET created=? WHERE id=?", (created, operation_id))
    profile_root = p.home / ".config/harbor-helper/remote"
    for directory in (
        p.home / ".config",
        p.home / ".config/harbor-helper",
        profile_root,
        profile_root / "profiles",
    ):
        directory.mkdir(mode=0o700, exist_ok=True)
    secure_write(
        profile_root / "profiles/history.json",
        {
            "url": url,
            "token": pat,
            "user": {"id": p.actor["id"]},
            "authentication": "automation",
        },
    )
    sdk = Client(url, pat)
    cases = [
        ({}, [ids[3], ids[2], ids[1], ids[0]], 4),
        ({"operation": "rerun"}, [ids[3], ids[1]], 2),
        ({"key": "alice-accepted"}, [ids[0]], 1),
        ({"operation_id": ids[1]}, [ids[1]], 1),
        ({"user_id": bob["id"]}, [ids[3], ids[2]], 2),
        ({"status": "rejected"}, [ids[3], ids[1]], 2),
        ({"status": "accepted"}, [ids[2], ids[0]], 2),
        ({"created_from": 20.0}, [ids[3], ids[2]], 2),
        ({"created_from": 0.0}, [ids[3], ids[2], ids[1]], 3),
        ({"created_to": 0.0}, [ids[1], ids[0]], 2),
        ({"created_from": 0.0, "created_to": 0.0}, [ids[1]], 1),
        ({"mine": False}, [ids[3], ids[2], ids[1], ids[0]], 4),
        ({"mine": True}, [ids[1], ids[0]], 2),
        (
            {
                "mine": True,
                "operation": "rerun",
                "status": "rejected",
                "created_from": 0.0,
                "created_to": 20.0,
            },
            [ids[1]],
            1,
        ),
        (
            {
                "user_id": bob["id"],
                "operation": "rerun",
                "key": "bob-rejected",
                "operation_id": ids[3],
                "status": "rejected",
                "created_from": 20.0,
                "created_to": 30.0,
                "limit": 1,
            },
            [ids[3]],
            1,
        ),
        ({"operation": "submit", "limit": 1, "offset": 1}, [ids[0]], 2),
        ({"operation_id": ids[1], "key": "bob-rejected"}, [], 0),
        (
            {"operation": None, "created_from": None, "created_to": None},
            [ids[3], ids[2], ids[1], ids[0]],
            4,
        ),
    ]

    def identities(value, expected, total):
        assert [item["id"] for item in value["operations"]] == expected
        assert value["total"] == total
        assert all(
            item["idem"] in {"alice-accepted", "alice-rejected", "bob-accepted", "bob-rejected"}
            for item in value["operations"]
        )

    async def check_stdio():
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "harbor_helper.commands.main",
                "mcp",
                "--profile",
                "history",
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
            tool = next(
                tool for tool in (await session.list_tools()).tools if tool.name == "history"
            )
            properties = tool.inputSchema["properties"]
            assert set(properties) == {
                "offset",
                "limit",
                "mine",
                "operation",
                "key",
                "operation_id",
                "user_id",
                "status",
                "created_from",
                "created_to",
            }
            for field, default, kind in (
                ("offset", 0, "integer"),
                ("limit", 50, "integer"),
                ("mine", False, "boolean"),
            ):
                assert properties[field]["default"] == default
                assert properties[field]["type"] == kind
            for field in (
                "operation",
                "key",
                "operation_id",
                "user_id",
                "status",
                "created_from",
                "created_to",
            ):
                assert properties[field]["default"] is None
                assert {entry["type"] for entry in properties[field]["anyOf"]} == {
                    "null",
                    "number" if field.startswith("created_") else "string",
                }
            with httpx.Client(
                base_url=url + "/api/v1",
                trust_env=False,
                headers={"Authorization": "Bearer " + pat},
            ) as http:
                for filters, expected, total in cases:
                    response = http.get(
                        "/operations",
                        params={key: value for key, value in filters.items() if value is not None},
                    )
                    assert response.status_code == 200, response.text
                    identities(response.json(), expected, total)
                    identities(sdk.history(**filters), expected, total)
                    result = await session.call_tool("history", filters)
                    assert not result.isError, result
                    assert result.content[0].type == "text"
                    value = json.loads(result.content[0].text)
                    identities(value, expected, total)
                    assert value["next_offset"] == response.json()["next_offset"]
                    args = ["service", "history", "--profile", "history"]
                    for key, selected in filters.items():
                        if selected is None or (key == "mine" and not selected):
                            continue
                        args.append("--" + key.replace("_", "-"))
                        if key != "mine":
                            args.append(str(selected))
                    cli_value, _ = cli(p, *args)
                    identities(cli_value, expected, total)
                    assert cli_value["next_offset"] == value["next_offset"]

    asyncio.run(check_stdio())
