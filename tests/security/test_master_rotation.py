"""External generations: snapshot concurrency, rollback, crash and global faults.

All material is generated fake state. SIGKILL tests process recovery, not power loss.
"""

import json
import multiprocessing
import os
import signal
import time

import pytest
from fastapi.testclient import TestClient
from support.paths import REPO

from harbor_helper.security import master_key as crypto
from harbor_helper.service.api import create_app
from harbor_helper.service.configuration import TeamConfiguration
from harbor_helper.service.data import ServiceData
from harbor_helper.service.primitives import ServiceError

PASSWORD = "Fake-rotation-password-2026"
WRITE = {"X-Requested-With": "harbor-helper"}


@pytest.fixture
def vault(tmp_path):
    data = ServiceData.initialize(
        tmp_path / "state", tmp_path / "private/master", "admin", PASSWORD
    )
    data.models.save_object(
        "provider",
        {"id": "p", "protocol": "openai-compatible", "endpoint": "http://fake.invalid/v1"},
    )
    data.add_credential("k", "p", "old", "fake-old")
    data.add_credential("k", "p", "new", "fake-new", rotate=True)
    data.disable_credential("k")
    config = TeamConfiguration(data)
    config.save_hub("fake-hub-old")
    config.save_hub("fake-hub-new")
    config.save_hub(enabled=False)
    return data


def actor(data):
    return data.users()[0]


def snapshot(data):
    with data.store.connect() as db:
        return {
            t: [dict(r) for r in db.execute(f"SELECT * FROM {t}")]
            for t in ("credential_versions", "source_credentials")
        }


def test_all_versions_business_fields_and_plaintext(vault):
    before = snapshot(vault)
    old = vault.master_keys.current()
    expected = sorted(vault.notice_secrets())
    assert vault.master_keys.rotate(actor(vault), 1)["counts"] == {
        "credential_versions": 2,
        "source_credentials": 2,
    }
    after = snapshot(vault)
    assert sorted(vault.notice_secrets()) == expected
    for table in before:
        for a, b in zip(before[table], after[table], strict=True):
            assert {k: v for k, v in a.items() if k not in {"nonce", "ciphertext"}} == {
                k: v for k, v in b.items() if k not in {"nonce", "ciphertext"}
            }
            assert a["nonce"] != b["nonce"] and a["ciphertext"] != b["ciphertext"]
            with pytest.raises(ServiceError):
                crypto.decrypt(old, b, crypto.aad(b, table))
    with pytest.raises(ServiceError, match="refresh"):
        vault.master_keys.rotate(actor(vault), 1)
    assert len(list((vault.root.parent / "private").iterdir())) == 2


def test_reader_gap_uses_old_generation_after_rotation(vault, monkeypatch):
    load = vault.master_keys.load

    def gap(ref):
        monkeypatch.setattr(vault.master_keys, "load", load)
        vault.master_keys.rotate(actor(vault), 1)
        return load(ref)

    monkeypatch.setattr(vault.master_keys, "load", gap)
    assert vault.key("k", 1, "p") == "fake-old"
    assert vault.master_keys.status()["generation"] == 2


def test_rollback_bad_row_and_precise_cleanup(vault):
    folder = vault.root.parent / "private"
    marker = folder / "master-2-existing.key"
    marker.write_bytes(b"x" * 32)
    with vault.store.connect() as db:
        db.execute("UPDATE source_credentials SET ciphertext=x'00' WHERE version=1")
    before = snapshot(vault)
    with pytest.raises(ServiceError):
        vault.master_keys.rotate(actor(vault), 1)
    assert snapshot(vault) == before
    assert {p.name for p in folder.iterdir()} == {"master", marker.name}
    assert vault.master_keys.status()["generation"] == 1


def test_fsync_order_precedes_ciphertext_updates_commit(vault, monkeypatch):
    events = []
    fsync = os.fsync

    def sync(fd):
        events.append("directory" if __import__("stat").S_ISDIR(os.fstat(fd).st_mode) else "file")
        fsync(fd)

    monkeypatch.setattr(crypto.os, "fsync", sync)
    original = vault.store.connect
    from contextlib import contextmanager

    @contextmanager
    def connect():
        with original() as db:
            db.set_trace_callback(
                lambda sql: (
                    events.append("commit" if sql == "COMMIT" else "update")
                    if sql == "COMMIT" or sql.startswith("UPDATE credential_versions")
                    else None
                )
            )
            yield db

    monkeypatch.setattr(vault.store, "connect", connect)
    vault.master_keys.rotate(actor(vault), 1)
    assert (
        events.index("file")
        < events.index("directory")
        < events.index("update")
        < events.index("commit")
    )


def reader(root, stop, result):
    data = ServiceData(root)
    count = 0
    try:
        while not stop.is_set():
            assert data.key("k", 1, "p") == "fake-old"
            assert sorted(v for v in data.notice_secrets() if v != "fake-added") == [
                "fake-hub-new",
                "fake-hub-old",
                "fake-new",
                "fake-old",
            ]
            count += 1
        result.put((count, None))
    except Exception as error:  # noqa: BLE001 - return failure type from child without secrets
        result.put((count, type(error).__name__))


def writer(root, result):
    data = ServiceData(root)
    configuration = TeamConfiguration(data)
    for number in range(10):
        data.add_credential("concurrent" + str(number), "p", "writer", "fake-added")
        configuration.save_hub("fake-added")
    result.put("writer-complete")


def test_multiprocess_readers_rotations_and_writer(vault):
    context = multiprocessing.get_context("spawn")
    stop, result = context.Event(), context.Queue()
    children = [
        context.Process(target=reader, args=(str(vault.root), stop, result)) for _ in range(2)
    ]
    for child in children:
        child.start()
    time.sleep(0.6)
    writing = context.Process(target=writer, args=(str(vault.root), result))
    writing.start()
    try:
        for generation in range(1, 7):
            vault.master_keys.rotate(actor(vault), generation)
            vault.add_credential("added" + str(generation), "p", "new", "fake-added")
            # Reader batch snapshot assertion intentionally uses only the retained
            # original families below; additional writes checked independently.
            assert vault.key("added" + str(generation), 1, "p") == "fake-added"
        writing.join(15)
        assert writing.exitcode == 0
        for number in range(10):
            assert vault.key("concurrent" + str(number), 1, "p") == "fake-added"
    finally:
        if writing.is_alive():
            writing.kill()
            writing.join(5)
        stop.set()
        for child in children:
            child.join(15)
            assert child.exitcode == 0
    results = [result.get(timeout=5) for _ in range(len(children) + 1)]
    assert "writer-complete" in results
    assert all(item[0] > 0 and item[1] is None for item in results if isinstance(item, tuple))


def crash_rotation(root, boundary, ready):
    data = ServiceData(root)
    if boundary == "before":
        from contextlib import contextmanager

        original_connect = data.store.connect

        @contextmanager
        def paused_connection():
            with original_connect() as db:

                def trace(sql):
                    if sql.startswith("INSERT INTO admin_events"):
                        ready.set()
                        signal.pause()

                db.set_trace_callback(trace)
                yield db

        pytest.MonkeyPatch().setattr(data.store, "connect", paused_connection)
    else:
        original_rotate = data.master_keys.rotate

        def rotate(actor, expected):
            value = original_rotate(actor, expected)
            ready.set()
            signal.pause()
            return value

        pytest.MonkeyPatch().setattr(data.master_keys, "rotate", rotate)
    data.master_keys.rotate(actor(data), 1)


@pytest.mark.parametrize("boundary,generation", [("before", 1), ("after", 2)])
def test_actual_sigkill_recovers_atomic_generation(vault, boundary, generation):
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    child = ctx.Process(target=crash_rotation, args=(str(vault.root), boundary, ready))
    child.start()
    try:
        assert ready.wait(15)
        assert child.pid is not None
        os.kill(child.pid, signal.SIGKILL)
    finally:
        if child.is_alive():
            child.kill()
        child.join(10)
    data = ServiceData(vault.root)
    assert data.master_keys.status()["generation"] == generation
    assert data.key("k", 1, "p") == "fake-old"
    assert len(list((vault.root.parent / "private").iterdir())) == 2


def test_empty_instance_kcv_missing_active_and_no_fallback(tmp_path):
    data = ServiceData.initialize(
        tmp_path / "state", tmp_path / "private/master", "admin", PASSWORD
    )
    path = tmp_path / "private/master"
    original = path.read_bytes()
    path.write_bytes(b"x" * 32)
    with pytest.raises(crypto.MasterUnavailable):
        data.master_keys.current()
    path.write_bytes(original)
    with data.store.connect() as db:
        db.execute("DELETE FROM master_active")
    ServiceData(data.root)
    with pytest.raises(crypto.MasterUnavailable):
        data.master_keys.current()
    assert "master_file" not in json.loads((data.root / "service.json").read_text())


def test_legacy_import_and_interrupted_config_normalization(vault, monkeypatch):
    config_path = vault.root / "service.json"
    config = json.loads(config_path.read_text())
    config["master_file"] = str(vault.root.parent / "private/master")
    config_path.write_text(json.dumps(config))
    with vault.store.connect() as db:
        db.execute("DROP TABLE master_active")
    original = crypto.durable_config

    def interrupted(path, value):
        if "master_file" not in value:
            raise OSError("synthetic interruption after metadata commit")
        original(path, value)

    monkeypatch.setattr(crypto, "durable_config", interrupted)
    with pytest.raises(OSError):
        ServiceData(vault.root)
    monkeypatch.setattr(crypto, "durable_config", original)
    recovered = ServiceData(vault.root)
    assert recovered.key("k", 1, "p") == "fake-old"
    assert "master_file" not in json.loads(config_path.read_text())


def test_admin_password_cas_and_secret_response(vault):
    client = TestClient(create_app(vault.root, start_scheduler=False))
    body = {"password": PASSWORD, "expected_generation": 1}
    assert (
        client.post("/api/v1/admin/master-key/rotate", headers=WRITE, json=body).status_code == 401
    )
    vault.create_user("member", PASSWORD)
    client.post(
        "/api/v1/auth/login", headers=WRITE, json={"username": "member", "password": PASSWORD}
    )
    assert client.get("/api/v1/admin/master-key").status_code == 403
    client.post(
        "/api/v1/auth/login", headers=WRITE, json={"username": "admin", "password": PASSWORD}
    )
    assert (
        client.post(
            "/api/v1/admin/master-key/rotate", headers=WRITE, json={**body, "password": "wrong"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/admin/master-key/rotate",
            headers={**WRITE, "Origin": "https://evil.invalid"},
            json=body,
        ).status_code
        == 403
    )
    response = client.post("/api/v1/admin/master-key/rotate", headers=WRITE, json=body)
    assert response.status_code == 200
    assert response.json()["generation"] == 2
    assert all(
        value not in response.text
        for value in (PASSWORD, "fake-", "ciphertext", "basename", str(vault.root.parent))
    )
    assert (
        client.post("/api/v1/admin/master-key/rotate", headers=WRITE, json=body).status_code == 409
    )
    assert client.get("/api/v1/admin/master-key").json()["generation"] == 2
    issued = client.post(
        "/api/v1/access-credentials",
        headers=WRITE,
        json={"name": "fake-rotation-pat", "current_password": PASSWORD, "scopes": ["read"]},
    )
    assert issued.status_code == 201
    pat = issued.json()["token"]
    assert (
        client.get(
            "/api/v1/admin/master-key", headers={"Authorization": "Bearer " + pat}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/admin/master-key/rotate",
            headers={**WRITE, "Authorization": "Bearer " + pat},
            json={**body, "expected_generation": 2},
        ).status_code
        == 403
    )


def test_crypto_consumers_are_centralized():
    root = REPO
    for path in (root / "src").rglob("*.py"):
        if path.name == "master_key.py":
            continue
        assert "AESGCM" not in path.read_text(), str(path)
        assert '["master_file"]' not in path.read_text(), str(path)


@pytest.mark.parametrize("fault", ["missing", "permissions", "kcv", "active"])
def test_global_master_fault_preserves_queue_and_recovers(vault, monkeypatch, fault):
    from harbor_helper.execution.scheduler import Controller
    from harbor_helper.persistence.files import write_json
    from harbor_helper.service.admission import readiness
    from harbor_helper.service.application import Application

    vault.add_credential("k", "p", "enabled", "fake-restored", rotate=True)
    folder = vault.root / "runs/queued-fault"
    folder.mkdir()
    write_json(
        folder / "manifest.json",
        {
            "effective": {
                "agent": "opencode",
                "model": {"endpoint": "http://fake.invalid/v1", "protocol": "openai-compatible"},
            },
            "service": {
                "user_id": actor(vault)["id"],
                "provider_id": "p",
                "provider_version": 1,
                "credential_id": "k",
                "credential_version": 3,
            },
        },
    )
    with vault.store.connect() as db:
        db.execute(
            "INSERT INTO runs(id,status,created,concurrency) VALUES('queued-fault','queued',?,1)",
            (time.time(),),
        )
        saved_ref = dict(db.execute("SELECT * FROM master_active").fetchone())
    path = vault.root.parent / "private/master"
    raw = path.read_bytes()
    if fault == "missing":
        path.unlink()
    elif fault == "permissions":
        path.chmod(0o644)
    elif fault == "kcv":
        path.write_bytes(b"x" * 32)
    else:
        with vault.store.connect() as db:
            db.execute("DELETE FROM master_active")
    controller = Controller(vault.store)
    launched = []
    monkeypatch.setattr(controller, "launch", lambda row: launched.append(row["id"]))
    try:
        with pytest.raises(crypto.MasterUnavailable):
            controller.decide()
        assert vault.store.get("queued-fault")["status"] == "queued" and launched == []
        state = readiness(Application(vault.root))
        assert not state["accepting"] and state["reason"] == "master_unavailable"
        path.write_bytes(raw)
        path.chmod(0o600)
        if fault == "active":
            with vault.store.connect() as db:
                db.execute(
                    "INSERT INTO master_active VALUES(:singleton,:generation,:basename,:kcv,:rotated_at)",
                    saved_ref,
                )
        controller.decide()
        assert launched == ["queued-fault"]
    finally:
        controller.close()


def test_new_generation_collision_never_overwrites_or_removes_existing(vault, monkeypatch):
    monkeypatch.setattr(crypto.secrets, "token_hex", lambda count: "f" * 32)
    existing = vault.root.parent / "private" / ("master-2-" + "f" * 32 + ".key")
    existing.write_bytes(b"preserve-owned-by-another-operation")
    before = snapshot(vault)
    with pytest.raises(FileExistsError):
        vault.master_keys.rotate(actor(vault), 1)
    assert existing.read_bytes() == b"preserve-owned-by-another-operation"
    assert snapshot(vault) == before and vault.master_keys.status()["generation"] == 1


def test_deleted_active_table_is_global_fault_without_import_fallback(vault):
    with vault.store.connect() as db:
        db.execute("DROP TABLE master_active")
    recovered = ServiceData(vault.root)
    with pytest.raises(crypto.MasterUnavailable):
        recovered.master_keys.current()
    with pytest.raises(crypto.MasterUnavailable):
        recovered.key("k", 1, "p")
    with pytest.raises(crypto.MasterUnavailable):
        recovered.notice_secrets()
    client = TestClient(create_app(vault.root, start_scheduler=False))
    assert client.get("/api/v1/health").json() == {"alive": True, "ready": False}
    with recovered.store.connect() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='master_active'").fetchone()


@pytest.mark.parametrize("fault_at", ["authorization", "launch"])
def test_master_fault_does_not_starve_later_cancellation_or_terminal_audit(
    vault, monkeypatch, fault_at
):
    from harbor_helper.execution.scheduler import Controller
    from harbor_helper.persistence.files import write_json

    store = vault.store
    # created order is essential: the failing uncancelled run precedes all work.
    with store.connect() as db:
        for number, (name, status, cancel) in enumerate(
            [
                ("first", "queued", 0),
                ("later-cancel", "queued", 1),
                ("later-terminal", "succeeded", 0),
                ("later-queued", "queued", 0),
            ]
        ):
            db.execute(
                "INSERT INTO runs(id,status,cancel,created,concurrency) VALUES(?,?,?,?,1)",
                (name, status, cancel, time.time() + number),
            )
            folder = store.root / "runs" / name
            folder.mkdir()
            write_json(
                folder / "manifest.json",
                {"effective": {"agent": "oracle"}, "service": {"user_id": actor(vault)["id"]}},
            )
    master = vault.root.parent / "private/master"
    raw = master.read_bytes()
    controller = Controller(store)
    launched, audited, authorized = [], [], []
    original_authorized = controller.authorized

    def authorize(row):
        authorized.append(row["id"])
        return original_authorized(row)

    def launch(row):
        # Cover disappearance between the two real authorization/key checks too.
        if fault_at == "launch" and master.exists():
            master.unlink()
        assert controller.execution_environment(row) is not None
        launched.append(row["id"])
        return True

    monkeypatch.setattr(controller, "authorized", authorize)
    monkeypatch.setattr(controller, "launch", launch)
    # Record dispatch, without requiring the terminal audit itself to use a key.
    monkeypatch.setattr(
        controller.auditing, "submit", lambda key, *args: audited.append(key) or True
    )
    if fault_at == "authorization":
        master.unlink()
    try:
        for _ in range(2):
            with pytest.raises(crypto.MasterUnavailable):
                controller.decide()
            assert store.get("first")["status"] == "queued"
            assert store.get("later-queued")["status"] == "queued"
            assert store.get("later-cancel")["status"] == "cancelled"
            assert launched == []
            assert "later-terminal" in audited
        assert authorized == ["first", "first"]
        # Recovery resumes the first run through the actual environment boundary.
        master.write_bytes(raw)
        master.chmod(0o600)
        fault_at = "recovered"
        controller.decide()
        assert launched == ["first"]
        assert store.get("later-cancel")["status"] == "cancelled"
    finally:
        controller.close()
