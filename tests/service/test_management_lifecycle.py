"""Concrete preparation dependencies and recycle read boundaries."""

import json

import pytest
from support.attachment_support import archive
from support.service_support import client

from harbor_helper.service.application import Application
from harbor_helper.service.lifecycle import prepare_one
from harbor_helper.service.primitives import ServiceError


def actor(data, name):
    return next(u for u in data.users() if u["username"] == name)


def test_bundle_purge_waits_for_preparing_then_snapshot_rerun_ignores_directory(data, preparation):
    app, alice, admin = Application(data.root), actor(data, "alice"), actor(data, "admin")
    attachment = app.attachments.write(
        alice, "attachment_create", "upload", {"name": "Frozen"}, archive()
    )
    version, bundle = attachment["version"]["id"], attachment["version"]["bundle_id"]
    accepted = app.accept(alice, {"agent": "oracle", "attachment_version_id": version}, "prepare")
    event = app.recycle.move(alice, "attachment_version", version)
    assert app.recycle.purge(admin, event["id"], "purge")["state"] == "purging"
    assert (data.root / "bundles" / bundle).exists()
    prepare_one(data.store)
    run_id = data.submission(accepted["id"])["run_id"]
    assert run_id
    assert app.recycle.purge(admin, event["id"], "purge")["state"] == "purged"
    assert not (data.root / "bundles" / bundle).exists()
    child = app.accept(actor(data, "bob"), {}, "rerun", parent=run_id)
    prepare_one(data.store)
    child_run = data.submission(child["id"])["run_id"]
    assert (data.store.path(child_run) / "bundle/sdk/readme").read_bytes() == b"v1"
    (data.store.path(child_run) / "bundle/sdk/readme").unlink()
    with pytest.raises(ServiceError, match="snapshot"):
        app.accept(alice, {}, "damaged", parent=child_run)


def test_parent_purge_waits_for_preparing_child_and_all_reads_are_closed(data, preparation):
    app, alice, admin = Application(data.root), actor(data, "alice"), actor(data, "admin")
    accepted = app.accept(alice, {"agent": "oracle", "name": "Private recycled body"}, "parent")
    prepare_one(data.store)
    parent_run = data.submission(accepted["id"])["run_id"]
    data.store.update(parent_run, status="succeeded", audit_status="clean")
    child = app.accept(alice, {}, "child", parent=parent_run)
    event = app.recycle.move(alice, "request", accepted["id"])
    signed_in = client(data)
    for suffix in ("", "/logs", "/report", "/report/download", "/evidence", "/evidence/package"):
        response = signed_in.get("/api/v1/runs/" + parent_run + suffix)
        assert response.status_code == 409, (suffix, response.text)
        assert "Private recycled body" not in response.text
    assert signed_in.get("/api/v1/machine/runs/" + parent_run).status_code == 409
    assert signed_in.get("/api/v1/submissions/" + accepted["id"]).status_code == 409
    assert signed_in.get("/api/v1/submission-operations/submit/parent").status_code == 409
    history = signed_in.get("/api/v1/operations").json()
    parent_operation = next(o for o in history["operations"] if o["idem"] == "parent")
    assert "Private recycled body" not in json.dumps(parent_operation)
    assert app.recycle.purge(admin, event["id"], "purge")["state"] == "purging"
    assert data.store.path(parent_run).exists()
    prepare_one(data.store)
    assert data.submission(child["id"])["run_id"]
    assert app.recycle.purge(admin, event["id"], "purge")["state"] == "purged"
    assert not (data.root / "runs" / parent_run).exists()
    assert signed_in.get("/api/v1/runs/" + parent_run).status_code == 410
    assert app.accept(alice, {"agent": "oracle", "name": "Private recycled body"}, "parent")[
        "deleted"
    ]
    assert signed_in.get("/api/v1/submission-operations/submit/parent").json()["deleted"]
    assert child["id"] in {r["id"] for r in app.management.requests()["requests"]}


def test_active_request_recycle_is_rejected_and_batch_is_per_item(data):
    app, alice = Application(data.root), actor(data, "alice")
    pending = app.accept(alice, {"agent": "oracle"}, "pending")
    upload = app.attachments.write(
        alice, "attachment_create", "upload", {"name": "Batch"}, archive()
    )
    browser = client(data)
    response = browser.post(
        "/api/v1/management/recycle",
        headers={"X-Requested-With": "harbor-helper"},
        json={
            "items": [
                {"kind": "request", "object_id": pending["id"]},
                {"kind": "attachment_version", "object_id": upload["version"]["id"]},
            ]
        },
    )
    assert response.status_code == 200, response.text
    first, second = response.json()["results"]
    assert first["error"]["code"] == "resource_active" and first["event"] is None
    assert second["event"]["state"] == "recycled" and second["error"] is None


def test_artifact_two_stages_snapshot_download_and_retention_wins(data, preparation):
    import hashlib

    app, alice, admin = Application(data.root), actor(data, "alice"), actor(data, "admin")
    accepted = app.accept(alice, {"agent": "oracle"}, "artifact-parent")
    prepare_one(data.store)
    run = data.submission(accepted["id"])["run_id"]
    data.store.update(run, status="succeeded", audit_status="clean")
    path = data.store.path(run) / "harbor/job/trial/artifacts/output.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"private artifact")
    file_id = hashlib.sha256(
        path.relative_to(data.store.path(run)).as_posix().encode()
    ).hexdigest()[:24]
    stream, size, name = app.artifact_download(run, file_id)
    assert size == len(b"private artifact") and name == "output.txt"
    event = app.delete_artifact(admin, run, file_id)
    assert path.exists() and app.artifacts(run) == []
    with pytest.raises(ServiceError):
        app.artifact_download(run, file_id)
    app.recycle.restore(admin, event["id"])
    assert app.artifacts(run)[0]["id"] == file_id
    event = app.delete_artifact(admin, run, file_id)
    assert app.recycle.purge(admin, event["id"], "artifact-purge")["state"] == "purged"
    assert not path.exists() and stream.read() == b"private artifact"
    stream.close()
    # A separate retention deletion can expire a recycled file. Restoring it must
    # persist the unrecoverable state rather than claim success or keep offering restore.
    path.write_bytes(b"retained second file")
    other = path.with_name("retained.txt")
    path.rename(other)
    other_id = hashlib.sha256(
        other.relative_to(data.store.path(run)).as_posix().encode()
    ).hexdigest()[:24]
    event = app.delete_artifact(admin, run, other_id)
    other.unlink()
    with pytest.raises(ServiceError) as error:
        app.recycle.restore(admin, event["id"])
    assert error.value.status == 410
    assert (
        next(e for e in app.recycle.listing(admin)["items"] if e["id"] == event["id"])["state"]
        == "expired"
    )


def test_dataset_cleanup_waits_for_author_cache_inspection(data):
    from harbor_helper.persistence.files import write_json
    from harbor_helper.service.author_cache import cache_lock

    app, admin = Application(data.root), actor(data, "admin")
    dataset = app.management.datasets()["datasets"][0]
    version = dataset["versions"][0]
    cache = data.root / "author-inputs/exclusive-synthetic-cache"
    cache.mkdir(parents=True)
    write_json(cache / "source.json", {"resolved": version["resolved"]})
    event = app.recycle.move(admin, "dataset_version", version["id"])
    with cache_lock(data.store, version["resolved"]):
        assert app.recycle.purge(admin, event["id"], "cache-purge")["state"] == "purging"
        assert cache.exists()
    assert app.recycle.purge(admin, event["id"], "cache-purge")["state"] == "purged"
    assert not cache.exists()


def test_request_recycle_includes_existing_artifact_event_and_old_ids_cannot_delete(
    data, preparation
):
    import hashlib

    app, alice, admin = Application(data.root), actor(data, "alice"), actor(data, "admin")
    accepted = app.accept(alice, {"agent": "oracle"}, "artifact-overlap")
    prepare_one(data.store)
    run = data.submission(accepted["id"])["run_id"]
    data.store.update(run, status="succeeded", audit_status="clean")
    path = data.store.path(run) / "harbor/job/trial/artifacts/overlap.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"overlap")
    file_id = hashlib.sha256(
        path.relative_to(data.store.path(run)).as_posix().encode()
    ).hexdigest()[:24]
    child = app.delete_artifact(admin, run, file_id)
    parent = app.recycle.move(alice, "request", accepted["id"])
    assert parent["count"] == 2
    with pytest.raises(ServiceError):
        app.recycle.purge(admin, child["id"], "old-artifact")
    app.recycle.restore(alice, parent["id"])
    assert app.artifacts(run) == []
    app.recycle.restore(admin, child["id"])
    assert app.artifacts(run)[0]["id"] == file_id
    newer = app.delete_artifact(admin, run, file_id)
    parent = app.recycle.move(alice, "request", accepted["id"])
    assert app.recycle.purge(admin, parent["id"], "parent-purge")["state"] == "purged"
    assert not (data.root / "runs" / run).exists()
    assert (
        next(e for e in app.recycle.listing(admin)["items"] if e["id"] == newer["id"])["state"]
        == "purged"
    )
    assert app.recycle.restore(admin, child["id"])["state"] == "restored"
    with data.store.connect() as db:
        marker = db.execute(
            "SELECT state,event_id FROM recycled_objects WHERE kind='artifact' AND id=?",
            (run + ":" + file_id,),
        ).fetchone()
    assert marker["state"] == "purged" and marker["event_id"] == parent["id"]
