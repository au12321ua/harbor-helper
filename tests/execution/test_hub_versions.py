"""Exercise the actual isolated child implementation against synthetic RegistryDB."""

import io
import json
from contextlib import ExitStack

import pytest
from harbor.db.client import RegistryDB

from harbor_helper.service import sources


@pytest.mark.parametrize("count", [0, 12, 201])
def test_version_list_dataset_yanked_limit_and_truncation(monkeypatch, capsys, count):
    calls = []

    async def package(self, **kwargs):
        calls.append(kwargs)
        return {"type": "dataset"}

    async def versions(self, **kwargs):
        assert kwargs["include_yanked"] is False and kwargs["limit"] == 201
        return {"type": "dataset"}, [
            {
                "revision": i,
                "content_hash": "sha256:" + f"{i:064x}",
                "tags": ["tag"],
                "yanked_at": None,
            }
            for i in range(count)
        ]

    monkeypatch.setattr(RegistryDB, "get_package", package)
    monkeypatch.setattr(RegistryDB, "list_package_versions", versions)
    monkeypatch.setattr(
        sources.sys,
        "stdin",
        io.StringIO(json.dumps({"reference": "team/data", "target": None, "action": "versions"})),
    )
    with ExitStack() as leases:
        sources._main(leases, None)
    value = json.loads(capsys.readouterr().out)
    assert len(value["versions"]) == min(count, 200)
    assert value["truncated"] is (count > 200)
    assert value["possibly_incomplete"] is (count <= 200)
    assert calls == [{"org": "team", "name": "data"}]


def test_non_dataset_is_rejected_before_enumeration(monkeypatch, capsys):
    async def package(self, **kwargs):
        return {"type": "task"}

    monkeypatch.setattr(RegistryDB, "get_package", package)
    monkeypatch.setattr(
        sources.sys,
        "stdin",
        io.StringIO(json.dumps({"reference": "team/task", "target": None, "action": "versions"})),
    )
    with ExitStack() as leases:
        sources._main(leases, None)
    assert json.loads(capsys.readouterr().out)["error"] == "source_not_dataset"


def test_source_subprocess_uses_team_key_and_independent_home(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("HARBOR_API_KEY", "personal-key-must-not-inherit")
    monkeypatch.setenv("OPENAI_API_KEY", "personal-model-must-not-inherit")
    monkeypatch.setenv("HARBOR_HELPER_REMOTE_PROFILE", "personal")

    def child(argv, **kwargs):
        env = kwargs["env"]
        assert env["HARBOR_API_KEY"] == "fake-team-key"
        assert "OPENAI_API_KEY" not in env and "HARBOR_HELPER_REMOTE_PROFILE" not in env
        assert json.loads(kwargs["input"])["action"] == "versions"
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "versions": [],
                    "_client": {"home": env["HOME"], "profile": None, "stored_credentials": False},
                }
            ),
        )

    monkeypatch.setattr(sources.subprocess, "run", child)
    assert sources.source_call("team/data", key="fake-team-key", action="versions") == {
        "versions": []
    }


def test_yanked_versions_are_excluded_and_cannot_be_previewed(monkeypatch, capsys):
    async def package(self, **kwargs):
        return {"type": "dataset"}

    async def versions(self, **kwargs):
        return {}, [
            {
                "revision": 1,
                "content_hash": "sha256:" + "a" * 64,
                "tags": [],
                "yanked_at": "withdrawn",
            },
            {"revision": 2, "content_hash": "sha256:" + "b" * 64, "tags": [], "yanked_at": None},
        ]

    async def resolve(self, *args):
        return {"type": "dataset"}, {"yanked_at": "withdrawn"}

    monkeypatch.setattr(RegistryDB, "get_package", package)
    monkeypatch.setattr(RegistryDB, "list_package_versions", versions)
    monkeypatch.setattr(RegistryDB, "resolve_dataset_version", resolve)
    for action in ("versions", "preview"):
        monkeypatch.setattr(
            sources.sys,
            "stdin",
            io.StringIO(
                json.dumps(
                    {"reference": "team/data@sha256:" + "a" * 64, "target": None, "action": action}
                )
            ),
        )
        with ExitStack() as leases:
            sources._main(leases, None)
        value = json.loads(capsys.readouterr().out)
        if action == "versions":
            assert [v["revision"] for v in value["versions"]] == [2]
        else:
            assert value["error"] == "source_version_unavailable"
