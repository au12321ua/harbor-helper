"""evidence workflow behavior with isolated synthetic inputs."""

import hashlib
import json

import pytest
from support.http_support import WRITE
from support.service_support import make_data, patch_preparation

from harbor_helper.security.local_paths import LocalRoot


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

    from harbor_helper.service.application import Application
    from harbor_helper.service.lifecycle import maintenance
    from harbor_helper.service.materials import inventory, manifest, snapshot
    from harbor_helper.service.primitives import ServiceError

    data = make_data(tmp_path)
    admin = next(u for u in data.users() if u["role"] == "admin")
    # Oracle fixture: explicit CLEAN terminal run with valid fixed metadata.
    app = Application(data.root)
    accepted = app.accept(admin, {"agent": "oracle"}, "snapshot")
    from pytest import MonkeyPatch

    patch = MonkeyPatch()
    try:
        patch_preparation(patch)
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
    from support.service_support import KEYS

    from harbor_helper.execution.audit import audit_finished
    from harbor_helper.service.application import Application
    from harbor_helper.service.lifecycle import prepare_one
    from harbor_helper.service.primitives import ServiceError

    data = make_data(tmp_path)
    app = Application(data.root)
    user = data.users()[0]
    accepted = app.accept(user, {"model_profile": "m1"}, "binary-audit")
    patch = MonkeyPatch()
    try:
        patch_preparation(patch)
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


@pytest.mark.parametrize("username", ["alice", "admin"])
@pytest.mark.parametrize("account_grant", [False, True])
@pytest.mark.parametrize("scopes", [None, ["read"], ["evidence"], ["read", "evidence"]])
def test_evidence_authorization_matrix(tmp_path, username, account_grant, scopes):
    from pytest import MonkeyPatch
    from support.service_support import PASSWORD, client

    from harbor_helper.execution.audit import audit_finished
    from harbor_helper.service.access import grant
    from harbor_helper.service.application import Application
    from harbor_helper.service.lifecycle import prepare_one

    data = make_data(tmp_path)
    admin = next(u for u in data.users() if u["role"] == "admin")
    target = next(u for u in data.users() if u["username"] == username)
    app = Application(data.root)
    submission = app.accept(admin, {"agent": "oracle"}, "matrix")
    patch = MonkeyPatch()
    try:
        patch_preparation(patch)
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
