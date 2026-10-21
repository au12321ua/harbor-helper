"""Attachment contract tests: fake keys, isolated state, no Docker/Hub/model calls."""

import io
import json
import os
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from attachment_support import archive
from service_support import client

from harbor_helper.persistence.files import read_json, write_json
from harbor_helper.security.access_tokens import check_access_tree
from harbor_helper.security.credentials import RedactedStream, redact_value, scan_tree
from harbor_helper.service.application import Application
from harbor_helper.service.bundles import Bundles
from harbor_helper.service.lifecycle import prepare_one
from harbor_helper.service.primitives import ServiceError

PAT = "hh_pat_v1_" + "A" * 43


def actor(data, name="alice"):
    return next(u for u in data.users() if u["username"] == name)


def create(app, user, key="create", value=b"v1", name="Team input"):
    return app.attachments.write(user, "attachment_create", key, {"name": name}, archive(value))


def test_versions_permissions_derive_and_metadata(data):
    app = Application(data.root)
    alice, bob = actor(data), actor(data, "bob")
    first = create(app, alice)
    aid, vid = first["attachment"]["id"], first["version"]["id"]
    with pytest.raises(ServiceError, match="Only creator"):
        app.attachments.write(bob, "attachment_publish", "no", {"attachment_id": aid}, archive())
    second = app.attachments.write(
        alice,
        "attachment_publish",
        "v2",
        {"attachment_id": aid, "notes": "Updated"},
        archive(b"v2"),
    )
    assert (first["version"]["number"], second["version"]["number"]) == (1, 2)
    assert first["version"]["digest"] != second["version"]["digest"]
    assert (
        data.root / "bundles" / first["version"]["bundle_id"] / "sdk/readme"
    ).read_bytes() == b"v1"
    derived = app.attachments.write(
        bob, "attachment_derive", "fork", {"name": "Fork", "source_version_id": vid}, archive()
    )
    assert derived["attachment"]["creator_id"] == bob["id"]
    assert derived["version"]["source_version_id"] == vid
    with pytest.raises(ServiceError):
        app.attachments.update(bob, aid, {"enabled": False})
    app.attachments.update(
        actor(data, "admin"), aid, {"name": "Renamed", "description": "Reusable"}
    )
    assert (
        app.attachments.lookup(alice, "attachment_create", "create")["attachment"]["name"]
        == "Renamed"
    )
    assert len(app.attachments.catalog()["attachments"]) == 2


def test_semantic_idempotency_concurrency_and_target_conflict(data):
    app = Application(data.root)
    user = actor(data)
    with ThreadPoolExecutor(4) as pool:
        values = list(pool.map(lambda _: create(app, user), range(4)))
    assert len({v["version"]["id"] for v in values}) == 1
    aid = values[0]["attachment"]["id"]
    recompressed = app.attachments.write(
        user,
        "attachment_create",
        "create",
        {"description": "", "name": "Team input"},
        archive(compression=zipfile.ZIP_DEFLATED),
    )
    assert recompressed["version"]["id"] == values[0]["version"]["id"]
    with pytest.raises(ServiceError) as error:
        create(app, user, value=b"other")
    assert error.value.code == "idempotency_conflict"
    with ThreadPoolExecutor(4) as pool:
        versions = list(
            pool.map(
                lambda i: app.attachments.write(
                    user, "attachment_publish", f"publish-{i}", {"attachment_id": aid}, archive()
                ),
                range(4),
            )
        )
    assert sorted(v["version"]["number"] for v in versions) == [2, 3, 4, 5]
    other = create(app, user, "other")
    with pytest.raises(ServiceError) as error:
        app.attachments.write(
            user,
            "attachment_publish",
            "publish-0",
            {"attachment_id": other["attachment"]["id"]},
            archive(),
        )
    assert error.value.code == "idempotency_conflict"
    with pytest.raises(ServiceError) as error:
        app.attachments.lookup(actor(data, "bob"), "attachment_create", "create")
    assert error.value.status == 404
    app.attachments.update(user, aid, {"enabled": False})
    replay = app.attachments.write(
        user, "attachment_publish", "publish-0", {"attachment_id": aid}, archive()
    )
    assert replay["version"]["number"] in (2, 3, 4, 5)


def test_frozen_lineage_rerun_retry_recover_current_identity(data, preparation):
    app, alice, bob = Application(data.root), actor(data), actor(data, "bob")
    first = create(app, alice)
    vid, aid = first["version"]["id"], first["attachment"]["id"]
    accepted = app.accept(alice, {"agent": "oracle", "attachment_version_id": vid}, "submit")
    prepare_one(data.store)
    rid = data.submission(accepted["id"])["run_id"]
    assert rid
    snapshot = data.store.path(rid)
    manifest = read_json(snapshot / "manifest.json")
    assert manifest["service"]["bundle_id"] == first["version"]["bundle_id"]
    app.attachments.write(alice, "attachment_publish", "v2", {"attachment_id": aid}, archive(b"v2"))
    manifest["service"]["access_credential_id"] = "old-pat-id"
    write_json(snapshot / "manifest.json", manifest)
    before = (snapshot / "manifest.json").read_bytes()
    for retry in (False, True):
        child = app.accept(bob, {}, f"rerun-{retry}", parent=rid, retry=retry)
        binding = data.submission(child["id"])["frozen"]["service"]
        assert binding["attachment_version_id"] == vid
        assert binding["user_id"] == bob["id"] and "access_credential_id" not in binding
        with data.store.connect() as db:
            db.execute("UPDATE submissions SET status='failed' WHERE id=?", (child["id"],))
        recovered = app.recover_submission(bob, child["id"], f"recover-{retry}")
        assert recovered["attachment"]["attachment_version_id"] == vid
    assert (snapshot / "manifest.json").read_bytes() == before
    app.attachments.update(alice, aid, {"enabled": False}, vid)
    for retry in (False, True):
        with pytest.raises(ServiceError) as error:
            app.accept(bob, {}, f"disabled-{retry}", parent=rid, retry=retry)
        assert error.value.code == "attachment_disabled"
    with pytest.raises(ServiceError):
        app.recover_submission(bob, child["id"], "disabled-recovery")


@pytest.mark.parametrize(
    "filename,value",
    [
        ("sdk/text", PAT.encode()),
        ("sdk/binary", b"\x00\xff" + PAT.encode()),
        ("sdk/boundary", b"X" * (65536 - 52) + PAT.encode()),
    ],
)
def test_plaintext_format_upload_and_no_idempotency_poison(data, filename, value):
    app, user = Application(data.root), actor(data)
    with pytest.raises(ValueError, match="access credential"):
        app.attachments.write(
            user, "attachment_create", "bad", {"name": "Bad"}, archive(value, filename)
        )
    with pytest.raises(ServiceError) as error:
        app.attachments.lookup(user, "attachment_create", "bad")
    assert error.value.status == 404
    assert create(app, user, "bad")["version"]["number"] == 1


def test_request_value_and_historical_leak_paths(data, preparation):
    app, user = Application(data.root), actor(data)
    actual = "fake-current-session-value"
    with pytest.raises(ValueError):
        Bundles(app.data).upload_bundle(archive(actual.encode()), access_value=actual)
    stored = create(app, user, "stored", actual.encode())
    vid = stored["version"]["id"]
    with pytest.raises(ServiceError):
        app.accept(
            user,
            {"agent": "oracle", "attachment_version_id": vid},
            "request-check",
            access_value=actual,
        )
    accepted = app.accept(user, {"agent": "oracle", "attachment_version_id": vid}, "stored-run")
    prepare_one(data.store)
    rid = data.submission(accepted["id"])["run_id"]
    with pytest.raises(ServiceError):
        app.accept(user, {}, "rerun-check", parent=rid, access_value=actual)
    (data.root / "bundles" / stored["version"]["bundle_id"] / "sdk/readme").write_text(PAT)
    with pytest.raises(ServiceError):
        app.attachments.write(
            user,
            "attachment_derive",
            "derive-format",
            {"source_version_id": vid, "name": "Derived"},
            archive(),
        )


def test_background_revalidates_digest_and_format(data, preparation):
    app, user = Application(data.root), actor(data)
    first = create(app, user)
    accepted = app.accept(
        user, {"agent": "oracle", "attachment_version_id": first["version"]["id"]}, "prepare"
    )
    (data.root / "bundles" / first["version"]["bundle_id"] / "sdk/readme").write_text("tampered")
    prepare_one(data.store)
    assert data.submission(accepted["id"])["status"] == "failed"
    assert not data.store.runs()
    assert (
        app.attachments.lookup(user, "attachment_create", "create")["version"]["availability"]
        == "unavailable"
    )


def test_output_format_redaction_and_stream_boundaries(tmp_path):
    for split in range(1, len(PAT)):
        output = io.StringIO()
        stream = RedactedStream(output, [])
        stream.write(PAT[:split])
        stream.flush()
        stream.write(PAT[split:])
        stream.finish()
        assert PAT not in output.getvalue() and "[REDACTED]" in output.getvalue()
    assert redact_value(PAT, []) == "[REDACTED]"
    (tmp_path / "binary").write_bytes(b"\x00" + PAT.encode())
    assert not scan_tree(tmp_path, [])["clean"]
    with pytest.raises(ValueError):
        check_access_tree(tmp_path)


def test_http_member_shared_versions_lookup_and_exclusive_reference(data):
    alice, bob = client(data), client(data, "bob")
    headers = {"X-Requested-With": "harbor-helper", "Idempotency-Key": "http-create"}
    response = alice.post(
        "/api/v1/attachments",
        headers=headers,
        data={"metadata": json.dumps({"name": "HTTP shared"})},
        files={"file": ("bundle.zip", archive())},
    )
    assert response.status_code == 201, response.text
    first = response.json()
    assert bob.get("/api/v1/attachments").json()["attachments"][0]["name"] == "HTTP shared"
    assert alice.get("/api/v1/attachment-operations/attachment_create/http-create").json() == first
    assert bob.get("/api/v1/attachment-operations/attachment_create/http-create").status_code == 404
    denied = bob.post(
        f"/api/v1/attachments/{first['attachment']['id']}/versions",
        headers=headers,
        files={"file": ("bundle.zip", archive())},
    )
    assert denied.status_code == 403
    unversioned = bob.post(
        "/api/v1/submissions",
        headers=headers,
        json={"agent": "oracle", "bundle_id": first["version"]["bundle_id"]},
    )
    assert unversioned.status_code == 422
    token = alice.cookies.get("hh_session")
    leak = alice.post(
        "/api/v1/attachments",
        headers={**headers, "Idempotency-Key": "http-leak"},
        data={"metadata": json.dumps({"name": "Leak"})},
        files={"file": ("bundle.zip", archive(token.encode()))},
    )
    assert leak.status_code == 422 and token not in leak.text


def test_http_wrapped_zip_explains_layout_without_committing_and_can_retry(data):
    signed_in = client(data)
    headers = {"X-Requested-With": "harbor-helper", "Idempotency-Key": "layout-retry"}
    metadata = {"metadata": json.dumps({"name": "SDK input"})}
    failed = signed_in.post(
        "/api/v1/attachments",
        headers=headers,
        data=metadata,
        files={"file": ("input.zip", archive(name="attachments/sdk-v1/sdk/tool.py"))},
    )
    assert failed.status_code == 422
    assert failed.json()["code"] == "invalid_operation"
    assert "ZIP 根目录" in failed.json()["message"]
    assert "去掉外层目录" in failed.json()["message"]
    assert signed_in.get("/api/v1/attachments").json()["attachments"] == []
    assert not list((data.root / "bundles").iterdir())
    missing = signed_in.get("/api/v1/attachment-operations/attachment_create/layout-retry")
    assert missing.status_code == 404
    retried = signed_in.post(
        "/api/v1/attachments",
        headers=headers,
        data=metadata,
        files={"file": ("input.zip", archive(name="sdk/tool.py"))},
    )
    assert retried.status_code == 201, retried.text
    assert retried.json()["version"]["availability"] == "available"


@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
def test_process_death_atomic_visibility_and_retry(data, tmp_path, phase):
    script = tmp_path / "crash.py"
    script.write_text("""
import io, os, sys, zipfile
from contextlib import contextmanager
from harbor_helper.service.application import Application
app = Application(sys.argv[1])
user = next(u for u in app.data.users() if u["username"] == "alice")
if sys.argv[2] == "before_commit":
    original = app.store.connect
    class Proxy:
        def __init__(self, db): self.db=db
        def execute(self, sql, *args):
            result=self.db.execute(sql, *args)
            if sql.startswith("INSERT INTO attachment_operations"): os._exit(71)
            return result
    @contextmanager
    def connection():
        with original() as db: yield Proxy(db)
    app.store.connect=connection
else:
    original=app.store.connect
    class Proxy:
        def __init__(self, db): self.db=db; self.published=False
        def execute(self, sql, *args):
            result=self.db.execute(sql, *args)
            if sql.startswith("INSERT INTO operations"): self.published=True
            return result
    @contextmanager
    def connection():
        proxy=None
        with original() as db:
            proxy=Proxy(db)
            yield proxy
        if proxy.published: os._exit(72)
    app.store.connect=connection
stream=io.BytesIO()
with zipfile.ZipFile(stream,"w") as z: z.writestr("sdk/readme",b"v1")
stream.seek(0)
app.attachments.write(user,"attachment_create","crash",{"name":"Team input"},stream)
""")
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "home"),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }
    process = subprocess.run(
        [sys.executable, str(script), str(data.root), phase],
        env=env,
        check=False,
        capture_output=True,
        timeout=30,
    )
    assert process.returncode == (71 if phase == "before_commit" else 72), process.stderr
    app, user = Application(data.root), actor(data)
    with data.store.connect() as db:
        counts = [
            db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("attachments", "attachment_versions", "attachment_operations", "bundles")
        ]
    assert counts == ([0] * 4 if phase == "before_commit" else [1] * 4)
    recovered = create(app, user, "crash")
    assert recovered["version"]["number"] == 1
    with data.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 1


def test_actual_remote_cli_uses_http_version_operations_and_selection(data, tmp_path, monkeypatch):
    import socket
    import threading
    import time

    import uvicorn

    from harbor_helper.commands.remote import remote_root
    from harbor_helper.security.files import secure_write
    from harbor_helper.service.api import create_app

    home = tmp_path / "cli-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(create_app(data.root, start_scheduler=False), log_level="error")
    )
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        until = time.monotonic() + 10
        while not server.started and time.monotonic() < until:
            time.sleep(0.01)
        assert server.started
        token, user = data.login("alice", "Fake-test-password-2026")
        root = remote_root(create=True)
        secure_write(
            root / "profiles/test.json",
            {"url": f"http://127.0.0.1:{port}", "token": token, "user": user},
        )
        zip_path = tmp_path / "input.zip"
        zip_path.write_bytes(archive().getvalue())
        env = {"PATH": os.environ["PATH"], "HOME": str(home)}

        def cli(*args):
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harbor_helper.commands.main",
                    "--remote-profile",
                    "test",
                    "--json",
                    *args,
                ],
                env=env,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert process.returncode == 0, process.stderr
            assert token not in process.stdout + process.stderr
            return json.loads(process.stdout)

        first = cli(
            "attachments",
            "create",
            "--name",
            "CLI",
            "--file",
            str(zip_path),
            "--idempotency-key",
            "cli-create",
        )
        assert cli("attachments", "lookup", "attachment_create", "cli-create") == first
        aid, vid = first["attachment"]["id"], first["version"]["id"]
        second = cli(
            "attachments",
            "publish",
            aid,
            "--notes",
            "v2",
            "--file",
            str(zip_path),
            "--idempotency-key",
            "cli-publish",
        )
        assert second["version"]["number"] == 2
        assert (
            cli("attachments", "list")["attachments"][0]["versions"][0]["id"]
            == second["version"]["id"]
        )
        accepted = cli(
            "submit",
            "--agent",
            "oracle",
            "--attachment-version-id",
            vid,
            "--idempotency-key",
            "cli-submit",
        )
        assert accepted["attachment"]["attachment_version_id"] == vid
        cli("attachments", "update", aid, "--version-id", vid, "--enabled", "false")
        assert not Application(data.root).attachments.lookup(
            user, "attachment_create", "cli-create"
        )["version"]["enabled"]
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        assert not thread.is_alive()


def test_no_attachment_v1_v2_comparison_keeps_other_condition_gates(data, preparation):
    from harbor_helper.persistence.store import Store
    from harbor_helper.results.reports import compare

    app, user = Application(data.root), actor(data)
    first = create(app, user)
    second = app.attachments.write(
        user,
        "attachment_publish",
        "v2",
        {"attachment_id": first["attachment"]["id"]},
        archive(b"v2"),
    )
    run_ids = []
    for i, version in enumerate((None, first["version"]["id"], second["version"]["id"])):
        request = {"agent": "oracle"}
        if version:
            request["attachment_version_id"] = version
        accepted = app.accept(user, request, f"contrast-{i}")
        prepare_one(data.store)
        rid = data.submission(accepted["id"])["run_id"]
        assert rid
        data.store.update(rid, status="succeeded", audit_status="clean")
        run_ids.append(rid)
    baseline, v1, v2 = run_ids
    # Safe published scoring fixture, never a real-model or Docker claim.
    reports = tuple(
        {"complete": True, "tasks": [{"task": "box", "mean_rewards": {"reward": reward}}]}
        for reward in (0, 1)
    )
    for left, right in ((baseline, v1), (baseline, v2), (v1, v2)):
        result = compare(Store(data.root), left, right, published_reports=reports)
        assert result["comparable"] and result["mean_task_delta"] == {"reward": 1.0}
        assert result["bundle_change"]["left"] != result["bundle_change"]["right"]
        assert result["attachment_inputs"]["right"]["attachment_version_id"] in (
            first["version"]["id"],
            second["version"]["id"],
        )
        if left == baseline:
            assert result["attachment_inputs"]["left"]["kind"] == "none"
    path = data.store.path(v2) / "manifest.json"
    frozen = read_json(path)
    for field, changed in (("agent", "opencode"), ("attempts", 2), ("wall_seconds", 900)):
        modified = json.loads(json.dumps(frozen))
        modified["effective"][field] = changed
        write_json(path, modified)
        result = compare(data.store, baseline, v2, published_reports=reports)
        assert not result["comparable"] and result["mean_task_delta"] is None
        assert any(field in reason for reason in result["reasons"])
    modified = json.loads(json.dumps(frozen))
    modified["source"]["tasks"][0]["ref"] = "sha256:different-grader"
    write_json(path, modified)
    assert not compare(data.store, baseline, v2, published_reports=reports)["comparable"]


def test_disabled_creator_still_shared_and_current_sessions_denied(data):
    app, alice, bob = Application(data.root), actor(data), actor(data, "bob")
    record = create(app, alice)
    signed_in = client(data)
    data.update_user(alice["id"], enabled=False)
    assert (
        signed_in.get("/api/v1/attachment-operations/attachment_create/create").status_code == 401
    )
    assert (
        app.accept(
            bob, {"agent": "oracle", "attachment_version_id": record["version"]["id"]}, "reuse"
        )["status"]
        == "preparing"
    )
    published = app.attachments.write(
        actor(data, "admin"),
        "attachment_publish",
        "admin-maintain",
        {"attachment_id": record["attachment"]["id"]},
        archive(b"v2"),
    )
    assert published["version"]["number"] == 2


def test_http_types_and_key_with_slash_roundtrip(data):
    signed_in = client(data)
    headers = {"X-Requested-With": "harbor-helper", "Idempotency-Key": "a/b"}
    invalid = signed_in.post(
        "/api/v1/attachments",
        headers=headers,
        data={"metadata": '{"name":123}'},
        files={"file": ("bundle.zip", archive())},
    )
    assert invalid.status_code == 422
    created = signed_in.post(
        "/api/v1/attachments",
        headers=headers,
        data={"metadata": '{"name":"Typed"}'},
        files={"file": ("bundle.zip", archive())},
    )
    assert created.status_code == 201
    record = created.json()
    assert signed_in.get("/api/v1/attachment-operations/attachment_create/a%2Fb").json() == record
    path = f"/api/v1/attachments/{record['attachment']['id']}"
    assert signed_in.patch(path, headers=headers, json={"enabled": "false"}).status_code == 422
    assert signed_in.patch(path, headers=headers, json={"name": "Renamed"}).status_code == 200
    assert (
        signed_in.patch(
            path, headers=headers, json={"description": signed_in.cookies.get("hh_session")}
        ).status_code
        == 422
    )
