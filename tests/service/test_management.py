"""Management invariants with independent synthetic service state; no real Hub/model."""

import pytest
from support.attachment_support import archive
from support.service_support import client

from harbor_helper.service import access
from harbor_helper.service.application import Application
from harbor_helper.service.primitives import ServiceError


def users(data):
    return {u["username"]: u for u in data.users()}


def attachment(app, actor, name="Input", key="create"):
    return app.attachments.write(actor, "attachment_create", key, {"name": name}, archive())


def test_rejected_recycle_replay_restore_and_permanent_receipt(data):
    app, actor = Application(data.root), users(data)["alice"]
    request = {"dataset_id": "missing", "agent": "oracle", "name": "Rejected intention"}
    with pytest.raises(ServiceError):
        app.accept(actor, request, "same")
    with data.store.connect() as db:
        operation_id = db.execute("SELECT id FROM operations WHERE idem='same'").fetchone()[0]
    event = app.recycle.move(actor, "request", operation_id)
    with pytest.raises(ServiceError, match="回收站"):
        app.accept(actor, request, "same")
    app.recycle.restore(actor, event["id"])
    with pytest.raises(ServiceError) as error:
        app.accept(actor, request, "same")
    assert error.value.code != "object_recycled"
    second = app.recycle.move(actor, "request", operation_id)
    assert second["id"] != event["id"]
    with pytest.raises(ServiceError):
        app.recycle.purge(users(data)["admin"], event["id"], "old-event")
    assert app.recycle.purge(users(data)["admin"], second["id"], "purge")["state"] == "purged"
    assert app.accept(actor, request, "same")["deleted"]
    with pytest.raises(ServiceError) as error:
        app.accept(actor, {**request, "name": "other"}, "same")
    assert error.value.code == "idempotency_conflict"
    with data.store.connect() as db:
        row = db.execute(
            "SELECT request,result,error,recent FROM operations WHERE id=?", (operation_id,)
        ).fetchone()
    assert "Rejected intention" not in str(tuple(row))


def test_nested_version_recycle_restore_preserves_previous_event(data):
    app, actor = Application(data.root), users(data)["alice"]
    first = attachment(app, actor)
    aid, vid = first["attachment"]["id"], first["version"]["id"]
    child = app.recycle.move(actor, "attachment_version", vid)
    parent = app.recycle.move(actor, "attachment", aid, [vid])
    with pytest.raises(ServiceError, match="并入"):
        app.recycle.restore(actor, child["id"])
    app.recycle.restore(actor, parent["id"])
    with pytest.raises(ServiceError):
        app.attachments.download(users(data)["bob"], vid)
    app.recycle.restore(actor, child["id"])
    newer = app.recycle.move(actor, "attachment_version", vid)
    with pytest.raises(ServiceError):
        app.recycle.purge(users(data)["admin"], child["id"], "stale")
    assert app.recycle.purge(users(data)["admin"], newer["id"], "purge")["state"] == "purged"
    second = app.attachments.write(
        actor, "attachment_publish", "next", {"attachment_id": aid}, archive(b"next")
    )
    assert second["version"]["number"] == 2
    assert app.attachments.lookup(actor, "attachment_create", "create")["deleted"]


def test_default_recycle_and_read_boundary_no_fallback(data):
    app, admin = Application(data.root), users(data)["admin"]
    selected = app.management.datasets()["datasets"][0]
    event = app.recycle.move(
        admin, "dataset", selected["id"], [v["id"] for v in reversed(selected["versions"])]
    )
    browser = client(data, "admin")
    response = browser.get("/api/v1/catalog")
    assert response.status_code == 200, response.text
    assert response.json()["settings"]["default_dataset_id"] is None
    with pytest.raises(ServiceError, match="默认数据集"):
        app.accept(users(data)["alice"], {"agent": "oracle"}, "no-default")
    app.recycle.restore(admin, event["id"])
    assert app.configuration.settings()["default_dataset_id"] is None


def test_scope_real_role_and_own_boundary(data):
    app = Application(data.root)
    alice, bob, admin = (users(data)[n] for n in ("alice", "bob", "admin"))
    for scope in ("datasets_manage", "recycle_all", "purge"):
        with pytest.raises(ServiceError):
            access.issue(data, alice, "forbidden", "Fake-test-password-2026", [scope], None)
    item = attachment(app, bob)
    old_admin = access.issue(
        data, admin, "old", "Fake-test-password-2026", ["read", "attachments", "cancel_own"], None
    )
    old_actor = data.actor(old_admin["token"])
    assert old_actor["role"] == "member" and old_actor["account_role"] == "admin"
    with pytest.raises(ServiceError):
        app.attachments.update(old_actor, item["attachment"]["id"], {"enabled": False})
    with pytest.raises(ServiceError):
        app.recycle.move(old_actor, "attachment_version", item["version"]["id"])
    own = access.issue(data, alice, "own", "Fake-test-password-2026", ["recycle_own"], None)
    with pytest.raises(ServiceError):
        app.recycle.move(data.actor(own["token"]), "attachment_version", item["version"]["id"])
    all_token = access.issue(
        data, admin, "all", "Fake-test-password-2026", ["recycle_all", "purge"], None
    )
    actor = data.actor(all_token["token"])
    event = app.recycle.move(actor, "attachment_version", item["version"]["id"])
    assert app.recycle.purge(actor, event["id"], "purge")["state"] == "purged"
    data.update_user(admin["id"], password="New-fake-password-2026")
    with pytest.raises(ServiceError):
        data.actor(all_token["token"])


def test_request_groups_empty_unique_and_number_high_water(data):
    app, alice = Application(data.root), users(data)["alice"]
    first = app.accept(alice, {"agent": "oracle", "name": "Alpha"}, "first")
    with pytest.raises(ServiceError, match="名称"):
        app.accept(alice, {"agent": "oracle", "name": "ＡＬＰＨＡ"}, "conflict")
    for i in range(3):
        app.accept(alice, {"agent": "oracle"}, f"unnamed-{i}")
    records = app.management.requests()["requests"]
    entry = next(r for r in records if r["id"] == first["id"])
    with pytest.raises(ServiceError):
        app.management.rename(users(data)["bob"], entry["group_id"], "No")
    assert app.management.rename(alice, entry["group_id"], "Renamed")["name"] == "Renamed"
    assert data.submission(first["id"])["frozen"]["service"]["name"] == "Alpha"
    from harbor_helper.service.history import listing

    operation = next(o for o in listing(data.store, alice)["operations"] if o["idem"] == "first")
    assert operation["request_group"]["name"] == "Renamed"
    assert operation["request"]["name"] == "Alpha"
    with data.store.connect() as db:
        db.execute("UPDATE submissions SET status='failed' WHERE id=?", (first["id"],))
    child = app.recover_submission(alice, first["id"], "recover")
    assert data.submission(child["id"])["frozen"]["service"]["name"] == "Alpha"
    with data.store.connect() as db:
        link = db.execute("SELECT * FROM request_links WHERE id=?", (child["id"],)).fetchone()
    assert link["number"] == 2 and link["group_id"] == entry["group_id"]


def test_purge_key_binds_event_and_recycled_name_remains_reserved(data):
    app, alice, admin = Application(data.root), users(data)["alice"], users(data)["admin"]
    first = attachment(app, alice, "Reserved", "one")
    aid, vid = first["attachment"]["id"], first["version"]["id"]
    one = app.recycle.move(alice, "attachment", aid, [vid])
    with pytest.raises(ServiceError, match="名称"):
        attachment(app, alice, "ＲＥＳＥＲＶＥＤ", "collision")
    second = attachment(app, alice, "Second", "two")
    two = app.recycle.move(alice, "attachment_version", second["version"]["id"])
    assert app.recycle.purge(admin, one["id"], "bound-key")["state"] == "purged"
    with pytest.raises(ServiceError) as error:
        app.recycle.purge(admin, two["id"], "bound-key")
    assert error.value.code == "idempotency_conflict"
    assert app.recycle.purge(admin, one["id"], "bound-key")["state"] == "purged"
    assert attachment(app, alice, "Reserved", "replacement")["attachment"]["id"] != aid


def test_concurrent_normalized_group_names_only_one_is_accepted(data):
    from concurrent.futures import ThreadPoolExecutor

    app, alice = Application(data.root), users(data)["alice"]

    def submit(item):
        try:
            return app.accept(
                alice, {"agent": "oracle", "name": item}, "name-" + str(len(item.encode()))
            )
        except ServiceError as error:
            return error

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(submit, ["Race", "ＲＡＣＥ"]))
    assert sum(isinstance(value, dict) for value in outcomes) == 1
    rejected = next(value for value in outcomes if isinstance(value, ServiceError))
    assert rejected.code == "name_conflict" and rejected.status == 409


def test_rejected_extension_keeps_direct_source_and_group(data):
    app, alice = Application(data.root), users(data)["alice"]
    first = app.accept(alice, {"agent": "oracle", "name": "Original"}, "source")
    with pytest.raises(ServiceError):
        app.accept(
            alice,
            {"agent": "oracle", "dataset_id": "missing", "source_request_id": first["id"]},
            "extension-rejected",
        )
    with data.store.connect() as db:
        operation = db.execute(
            "SELECT id FROM operations WHERE idem='extension-rejected'"
        ).fetchone()[0]
        source = db.execute("SELECT * FROM request_links WHERE id=?", (first["id"],)).fetchone()
        failed = db.execute("SELECT * FROM request_links WHERE id=?", (operation,)).fetchone()
    assert failed["source_id"] == first["id"]
    assert failed["group_id"] == source["group_id"] and failed["relation"] == "extension"
    assert failed["number"] > source["number"]
