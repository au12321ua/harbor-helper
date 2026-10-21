"""Immutable imports, merge provenance and additive automatic conversion."""

import json

import pytest

from harbor_helper.service.application import Application
from harbor_helper.service.management_data import initialize
from harbor_helper.service.primitives import ServiceError


def test_preview_tag_movement_does_not_change_digest_or_default(data, monkeypatch):
    app = Application(data.root)
    admin = next(u for u in data.users() if u["role"] == "admin")
    dataset = app.configuration.save("dataset", {"name": "Versions", "reference": "team/versions"})
    first, second = ("sha256:" + c * 64 for c in "bc")
    calls = []

    def hub(reference, **kwargs):
        calls.append((reference, kwargs))
        if kwargs.get("action") == "versions":
            return {
                "package": "team/versions",
                "versions": [{"digest": first, "revision": 1, "tags": ["latest"], "published": ""}],
                "truncated": False,
                "possibly_incomplete": True,
                "limit": 200,
            }
        return {
            "resolved": reference,
            "tasks": [{"name": "task", "package": "team/task", "ref": first}],
        }

    monkeypatch.setattr("harbor_helper.service.sources.source_call", hub)
    preview = app.management.preview(admin, dataset["id"], first)
    assert app.management.confirm(admin, preview["id"])["resolved"].endswith(first)
    old_default = app.configuration.ready_dataset(dataset["id"])["resolved"]
    newer = app.management.preview(admin, dataset["id"], second)
    app.management.confirm(admin, newer["id"])
    assert app.configuration.ready_dataset(dataset["id"])["resolved"] == old_default
    assert all("@latest" not in r for r, _ in calls)
    versions = next(d for d in app.management.datasets()["datasets"] if d["id"] == dataset["id"])[
        "versions"
    ]
    assert len(versions) == 2 and len({v["number"] for v in versions}) == 2
    # Missing old-source parameter records cannot become valid empty author values.
    with pytest.raises(ServiceError, match="原摘要"):
        app._freeze_author_inputs(
            {"dataset": old_default}, {"dataset_id": dataset["id"]}, check_source=False
        )
    # A converted request has only its original digest, not the new version-id field.
    # Changing today's default cannot make its known original revision unavailable.
    app.configuration.persist(
        "author_parameters",
        {
            "id": dataset["id"],
            "source": old_default,
            "values": {"A": "original"},
            "status": "checked",
        },
    )
    old_version = next(v for v in versions if v["resolved"] == old_default)
    new_version = next(v for v in versions if v["resolved"] != old_default)
    app.management.default(admin, dataset["id"], new_version["id"])
    frozen = {"dataset": old_default}
    app._freeze_author_inputs(frozen, {"dataset_id": dataset["id"]}, check_source=False)
    assert frozen["author_env"] == {"A": "original"}
    app.recycle.move(admin, "dataset_version", old_version["id"])
    before = len(calls)
    with pytest.raises(ServiceError, match="回收站"):
        app.management.preview(admin, dataset["id"], first)
    assert len(calls) == before


def test_conversion_keeps_all_original_revisions_and_merges_explicit_parameter_choice(data):
    app = Application(data.root)
    admin = next(u for u in data.users() if u["role"] == "admin")
    resolved = "team/legacy@sha256:" + "b" * 64
    with data.store.connect() as db:
        for identity in ("legacy-a", "legacy-b"):
            for version, values in ((1, {"A": identity}), (2, {"A": identity + "-new"})):
                config = {
                    "name": "ＳＡＭＥ" if identity.endswith("b") else "Same",
                    "reference": "team/legacy@1",
                    "resolved": resolved,
                    "status": "verified",
                    "enabled": True,
                    "tasks": [],
                }
                db.execute(
                    "INSERT INTO objects VALUES(?,?,?,?)",
                    ("dataset", identity, version, json.dumps(config)),
                )
                db.execute(
                    "INSERT INTO objects VALUES(?,?,?,?)",
                    (
                        "author_parameters",
                        identity,
                        version,
                        json.dumps({"source": resolved, "values": values, "status": "checked"}),
                    ),
                )
        before = [tuple(r) for r in db.execute("SELECT * FROM objects ORDER BY kind,id,version")]
        db.execute("DELETE FROM management_schema")
    initialize(data.store)
    with data.store.connect() as db:
        assert [
            tuple(r) for r in db.execute("SELECT * FROM objects ORDER BY kind,id,version")
        ] == before
        identities = [
            dict(r) for r in db.execute("SELECT * FROM dataset_identities WHERE id LIKE 'legacy-%'")
        ]
        assert len({r["name"] for r in identities}) == 2
        after = [tuple(r) for r in db.execute("SELECT * FROM dataset_sources ORDER BY id")]
    initialize(data.store)
    with data.store.connect() as db:
        assert [tuple(r) for r in db.execute("SELECT * FROM dataset_sources ORDER BY id")] == after
    preview = app.management.merge_preview(admin, "legacy-a", "legacy-b")
    with pytest.raises(ServiceError, match="参数冲突"):
        app.management.merge(admin, "legacy-a", "legacy-b", preview["revision"], {})
    app.management.merge(
        admin,
        "legacy-a",
        "legacy-b",
        preview["revision"],
        {resolved: {"id": "legacy-a", "version": 1}},
    )
    assert app.configuration.author_parameters("legacy-b", resolved)["values"] == {"A": "legacy-a"}
    assert app.configuration.ready_dataset("legacy-a")["id"] == "legacy-b"
    with data.store.connect() as db:
        versions = [m[1] for m in app.recycle.members(db, "dataset", "legacy-b")[2][1:]]
    event = app.recycle.move(admin, "dataset", "legacy-b", versions)
    with pytest.raises(ServiceError):
        app.configuration.ready_dataset("legacy-a")
    app.recycle.restore(admin, event["id"])
    with pytest.raises(ServiceError, match="默认来源版本"):
        app.configuration.ready_dataset("legacy-a")
    selected = next(d for d in app.management.datasets()["datasets"] if d["id"] == "legacy-b")[
        "versions"
    ][0]["id"]
    app.management.default(admin, "legacy-b", selected)
    assert app.configuration.ready_dataset("legacy-a")["id"] == "legacy-b"
    event = app.recycle.move(admin, "dataset", "legacy-b", versions)
    assert app.recycle.purge(admin, event["id"], "merged-purge")["state"] == "purged"
    with data.store.connect() as db:
        assert not db.execute(
            "SELECT 1 FROM objects WHERE id IN ('legacy-a','legacy-b')"
        ).fetchone()
        assert not db.execute(
            "SELECT 1 FROM dataset_sources WHERE dataset_id IN ('legacy-a','legacy-b')"
        ).fetchone()
    with pytest.raises(ServiceError):
        app.configuration.ready_dataset("legacy-a")


def test_conversion_preserves_frozen_graph_history_attachments_and_rolls_back(
    data, preparation, monkeypatch
):
    from support.attachment_support import archive

    from harbor_helper.service import management_data
    from harbor_helper.service.lifecycle import prepare_one

    app = Application(data.root)
    alice = next(u for u in data.users() if u["username"] == "alice")
    uploaded = app.attachments.write(
        alice, "attachment_create", "migration-attachment", {"name": "Original input"}, archive()
    )
    parent = app.accept(
        alice,
        {
            "agent": "oracle",
            "name": "Original graph",
            "attachment_version_id": uploaded["version"]["id"],
        },
        "migration-parent",
    )
    prepare_one(data.store)
    run = data.submission(parent["id"])["run_id"]
    child = app.accept(alice, {}, "migration-child", parent=run)
    tables = (
        "submissions",
        "runs",
        "objects",
        "attachments",
        "attachment_versions",
        "bundles",
        "operations",
        "configuration_settings",
    )

    def snapshot():
        with data.store.connect() as db:
            return {
                table: sorted([tuple(r) for r in db.execute("SELECT * FROM " + table)], key=repr)
                for table in tables
            }

    before = snapshot()
    with data.store.connect() as db:
        for table in (
            "management_schema",
            "management_names",
            "management_counters",
            "request_groups",
            "request_links",
            "dataset_identities",
            "dataset_sources",
        ):
            db.execute("DELETE FROM " + table)
    original_reserve = management_data.reserve_name

    def failed_reserve(db, kind, *args, **kwargs):
        if kind == "attachment":
            raise RuntimeError("injected conversion failure after dataset conversion")
        return original_reserve(db, kind, *args, **kwargs)

    monkeypatch.setattr(management_data, "reserve_name", failed_reserve)
    with pytest.raises(RuntimeError, match="injected"):
        initialize(data.store)
    assert snapshot() == before
    with data.store.connect() as db:
        assert not db.execute("SELECT 1 FROM dataset_identities").fetchone()
        assert not db.execute("SELECT 1 FROM management_schema").fetchone()
    monkeypatch.setattr(management_data, "reserve_name", original_reserve)
    initialize(data.store)
    assert snapshot() == before
    with data.store.connect() as db:
        links = {r["id"]: dict(r) for r in db.execute("SELECT * FROM request_links")}
        assert links[child["id"]]["source_id"] == parent["id"]
        assert links[child["id"]]["group_id"] == links[parent["id"]]["group_id"]
        assert links[child["id"]]["number"] > links[parent["id"]]["number"]
    initialize(data.store)
    assert snapshot() == before
