"""Service behavior with isolated accounts, encrypted fake keys and no model calls."""

import io
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from admission_fixture import synthetic_activity
from fastapi.testclient import TestClient

from harbor_helper.execution.audit import finish
from harbor_helper.persistence.files import read_json, tree_digest
from harbor_helper.service.api import create_app
from harbor_helper.service.application import Application
from harbor_helper.service.bundles import Bundles
from harbor_helper.service.data import ServiceData
from harbor_helper.service.lifecycle import maintenance, prepare_one
from harbor_helper.service.primitives import ServiceError

WRITE = {"X-Requested-With": "harbor-helper"}
PASSWORD = "Fake-test-password-2026"
KEYS = ["fake-service-key-one-2026", "fake-service-key-two-2026", "fake-service-key-three-2026"]


@pytest.fixture
def data(tmp_path):
    data = ServiceData.initialize(
        tmp_path / "state", tmp_path / "private" / "master", "admin", PASSWORD
    )
    data.create_user("alice", PASSWORD)
    data.create_user("bob", PASSWORD)
    for i in (1, 2):
        data.models.save_object(
            "provider",
            {
                "id": f"p{i}",
                "name": f"Provider {i}",
                "protocol": "openai-compatible",
                "endpoint": f"http://provider{i}.invalid/v1",
            },
        )
    for i, key in enumerate(KEYS, 1):
        provider = "p1" if i < 3 else "p2"
        data.add_credential(f"k{i}", provider, f"Key {i}", key)
        data.models.save_object(
            "profile",
            {
                "id": f"m{i}",
                "name": f"Model {i}",
                "provider_id": provider,
                "credential_id": f"k{i}",
                "model": "test-model",
                "params": {"temperature": 0},
            },
        )
    synthetic_activity(data)
    return data


def client(data, username="alice"):
    c = TestClient(create_app(data.root, start_scheduler=False), raise_server_exceptions=False)
    r = c.post(
        "/api/v1/auth/login", headers=WRITE, json={"username": username, "password": PASSWORD}
    )
    assert r.status_code == 200
    return c


def test_new_tool_strategy_frozen_and_old_rerun_keeps_installer(data, preparation):
    app = Application(data.root)
    actor = data.users()[0]
    accepted = app.accept(actor, {"dataset": "test/data@1", "model_profile": "m1"}, "tools-new")
    frozen = data.submission(accepted["id"])["frozen"]["effective"]
    assert frozen["agent_tool_preparation"] == "offline-npm-binary-v1"
    prepare_one(data.store)
    rid = data.submission(accepted["id"])["run_id"]
    folder = data.store.path(rid)
    assert read_json(folder / "job.json")["agents"][0]["kwargs"]["helper_tool_cache"] == str(
        data.root / "agent-tools"
    )
    manifest = read_json(folder / "manifest.json")
    manifest["effective"].pop("agent_tool_preparation")
    from harbor_helper.persistence.files import write_json

    write_json(folder / "manifest.json", manifest)
    before = (folder / "manifest.json").read_bytes()
    accepted = app.accept(actor, {}, "tools-old-rerun", parent=rid)
    assert "agent_tool_preparation" not in data.submission(accepted["id"])["frozen"]["effective"]
    assert (folder / "manifest.json").read_bytes() == before


@pytest.fixture
def preparation(monkeypatch):
    async def source(dataset, target, task):
        folder = target / "box"
        folder.mkdir(parents=True)
        (folder / "task.toml").write_text('version = "1.0"\n[environment]\nbuild_timeout_sec=60\n')
        (folder / "instruction.md").write_text("fake oracle task")
        return {
            "requested": dataset,
            "resolved": dataset,
            "tasks": [
                {
                    "package": "test/box",
                    "directory": "box",
                    "ref": "sha256:fixed",
                    "snapshot_digest": tree_digest(folder),
                }
            ],
        }

    monkeypatch.setattr(
        "harbor_helper.service.sources.source_call",
        lambda reference, *, key=None, target=None, task=None: __import__("asyncio").run(
            source(reference, target, task)
        ),
    )
    monkeypatch.setattr("harbor_helper.execution.runs.subprocess.run", lambda *a, **k: None)


def accept_model(data, username="alice", profile="m1", key="same"):
    app = Application(data.root)
    actor = next(u for u in data.users() if u["username"] == username)
    return app.accept(actor, {"model_profile": profile, "dataset": "test/dataset@1"}, key)


def prepare(data, preparation, profile="m1"):
    accepted = accept_model(data, profile=profile)
    prepare_one(data.store)
    row = data.submission(accepted["id"])
    assert row["status"] == "ready", row
    return row["run_id"]


def test_invited_local_accounts_no_registration_shared_permissions(data):
    a, b, owner = client(data), client(data, "bob"), client(data, "admin")
    assert (
        TestClient(create_app(data.root, start_scheduler=False)).get("/api/v1/runs").status_code
        == 401
    )
    assert (
        b.post(
            "/api/v1/admin/users",
            headers=WRITE,
            json={"username": "stranger", "password": PASSWORD},
        ).status_code
        == 403
    )
    assert a.post("/api/v1/auth/register", headers=WRITE, json={}).status_code == 404
    request = {"agent": "oracle", "dataset": "test/data@1"}
    r = a.post("/api/v1/submissions", headers={**WRITE, "Idempotency-Key": "shared"}, json=request)
    assert r.status_code == 202
    sid = r.json()["id"]
    assert b.get(f"/api/v1/submissions/{sid}").json()["submitter"] == "alice"
    assert b.post(f"/api/v1/submissions/{sid}/cancel", headers=WRITE).status_code == 403
    assert owner.post(f"/api/v1/submissions/{sid}/cancel", headers=WRITE).status_code == 200
    assert data.submission(sid)["status"] == "cancelled"
    assert (
        a.post(
            "/api/v1/submissions",
            headers={**WRITE, "Idempotency-Key": "spoof"},
            json={**request, "user_id": "bob"},
        ).status_code
        == 422
    )


def test_credentials_encrypted_aad_no_secret_response(data, tmp_path):
    for key in KEYS:
        assert key.encode() not in (data.root / "queue.sqlite").read_bytes()
    c = client(data, "admin")
    metadata = c.get("/api/v1/admin/credentials").text
    assert all(key not in metadata for key in KEYS)
    assert "ciphertext" not in metadata and "nonce" not in metadata
    assert data.key("k1", 1, "p1") == KEYS[0]
    with pytest.raises(ServiceError):
        data.key("k1", 1, "p2")
    master = read_json(data.root / "service.json")["master_file"]
    from pathlib import Path

    original = Path(master).read_bytes()
    Path(master).write_bytes(b"x" * 32)
    with pytest.raises(ServiceError):
        data.key("k1", 1, "p1")
    Path(master).write_bytes(original)
    Path(master).chmod(0o644)
    with pytest.raises(ServiceError):
        data.key("k1", 1, "p1")
    assert (
        c.post(
            "/api/v1/admin/credentials",
            headers=WRITE,
            json={
                "id": "bad",
                "provider_id": "p1",
                "label": "bad",
                "key": KEYS[0],
                "invalid": KEYS[1],
            },
        ).status_code
        == 422
    )
    response = c.post(
        "/api/v1/auth/login",
        headers=WRITE,
        json={"username": "admin", "password": {"secret": KEYS[0]}},
    )
    assert KEYS[0] not in response.text


def test_idempotency_concurrency_and_freezing(data):
    with ThreadPoolExecutor(max_workers=6) as pool:
        ids = list(pool.map(lambda _: accept_model(data)["id"], range(6)))
    assert len(set(ids)) == 1
    actor = next(u for u in data.users() if u["username"] == "alice")
    with pytest.raises(ServiceError, match="different input"):
        Application(data.root).accept(actor, {"model_profile": "m2"}, "same")
    frozen = data.submission(ids[0])["frozen"]
    data.models.save_object(
        "provider",
        {
            "id": "p1",
            "protocol": "openai-compatible",
            "endpoint": "http://changed.invalid/v1",
            "name": "changed",
        },
    )
    data.models.save_object(
        "profile",
        {
            "id": "m1",
            "provider_id": "p1",
            "credential_id": "k1",
            "model": "changed-model",
            "params": {},
        },
    )
    data.add_credential("k1", "p1", "Key 1", "fake-rotated-key-2026", rotate=True)
    assert data.submission(ids[0])["frozen"] == frozen
    assert frozen["effective"]["model"]["endpoint"] == "http://provider1.invalid/v1"
    assert frozen["service"]["credential_version"] == 1


def test_actual_bindings_rotation_rerun_and_cancel_ownership(data, preparation):
    first = prepare(data, preparation)
    assert data.run_key(first, True) == KEYS[0]
    data.add_credential("k1", "p1", "Key 1", "fake-rotated-key-2026", rotate=True)
    bob = next(u for u in data.users() if u["username"] == "bob")
    rerun = Application(data.root).accept(bob, {}, "rerun", parent=first)
    frozen = data.submission(rerun["id"])["frozen"]
    assert frozen["service"]["credential_version"] == 2
    prepare_one(data.store)
    second = data.submission(rerun["id"])["run_id"]
    assert data.run_key(second, True) == "fake-rotated-key-2026"
    assert (
        read_json(data.store.path(first) / "manifest.json")["effective"]
        == read_json(data.store.path(second) / "manifest.json")["effective"]
    )
    app = Application(data.root)
    with pytest.raises(ServiceError):
        app.cancel_run(bob, first)
    assert app.cancel_run(bob, second)["cancel_requested"]
    data.disable_credential("k1")
    with pytest.raises(ServiceError):
        data.run_key(first, True)
    assert data.run_key(first, False) == KEYS[0]
    assert data.prune_credentials()["pruned_versions"] == 0


def test_resource_cleanup_separate_audit_and_next_capacity(data, preparation, monkeypatch):
    run_id = prepare(data, preparation)
    path = data.store.path(run_id)
    data.store.update(run_id, status="running", started=time.time())
    (path / "worker.log").write_text(KEYS[0])
    with data.store.connect() as db:
        db.execute("DELETE FROM credential_versions WHERE id='k1'")
    monkeypatch.setattr("harbor_helper.execution.audit.stop_group", lambda row: None)
    monkeypatch.setattr("harbor_helper.execution.audit.cleanup", lambda path: None)
    finish(data.store, data.store.get(run_id), "failed", "interrupted")
    row = data.store.get(run_id)
    assert row["status"] == "failed" and row["audit_status"] == "incomplete" and row["finished"]
    assert Application(data.root).usage()["active_trials"] == 0
    assert client(data, "bob").get(f"/api/v1/runs/{run_id}").status_code == 200
    assert client(data, "bob").get(f"/api/v1/runs/{run_id}/logs").status_code == 409
    assert client(data, "bob").get(f"/api/v1/runs/{run_id}/report").status_code == 409
    second = accept_model(data, profile="m2", key="second")
    assert second["status"] == "preparing"

    def blocked(path):
        raise RuntimeError("resources still present")

    monkeypatch.setattr("harbor_helper.execution.audit.cleanup", blocked)
    finish(data.store, row, "failed", "interrupted")
    assert data.store.get(run_id)["status"] == "cleanup_blocked"
    assert Application(data.root).usage()["active_trials"] == 1


def test_bundle_bounds_paths_symlinks_and_secret_names(data):
    app = Application(data.root)

    def archive(name, content=b"test", mode=None):
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w") as z:
            info = zipfile.ZipInfo(name)
            if mode:
                info.external_attr = mode << 16
            z.writestr(info, content)
        result.seek(0)
        return result

    for name in ("../escape", "/absolute", "sdk\\escape", "sdk/credential.txt"):
        with pytest.raises(ValueError):
            Bundles(app.data).upload_bundle(archive(name))
    with pytest.raises(ValueError):
        Bundles(app.data).upload_bundle(archive("sdk/link", b"target", 0o120777))
    assert Bundles(app.data).upload_bundle(archive("sdk/tool.py"))["digest"].startswith("sha256:")


def test_get_no_side_effect_security_headers_and_logout(data, preparation):
    run_id = prepare(data, preparation)
    c = client(data)
    (data.root / "scheduler.json").unlink()  # Explicitly unavailable during read-only check.
    before = (data.root / "queue.sqlite").read_bytes()
    r = c.get(f"/api/v1/runs/{run_id}")
    assert r.status_code == 200
    assert (data.root / "queue.sqlite").read_bytes() == before
    assert not (data.root / "scheduler.json").exists()
    assert r.headers["cache-control"] == "no-store"
    assert c.post("/api/v1/auth/logout").status_code == 403
    assert (
        c.post(
            "/api/v1/auth/logout", headers={**WRITE, "Origin": "http://evil.invalid"}
        ).status_code
        == 403
    )
    assert c.post("/api/v1/auth/logout", headers=WRITE).status_code == 200
    assert c.get("/api/v1/me").status_code == 401
    assert c.get("/api/v1/missing").headers["content-type"].startswith("application/json")


def test_retention_prunes_only_unreferenced_old_versions(data, preparation, monkeypatch):
    run_id = prepare(data, preparation)
    path = data.store.path(run_id)
    data.store.update(
        run_id, status="failed", audit_status="clean", finished=time.time() - 20 * 86400
    )
    (path / "worker.log").write_text("sanitized")
    data.add_credential("k1", "p1", "Key 1", "fake-new-key-2026", rotate=True)
    assert data.prune_credentials()["pruned_versions"] == 0
    maintenance(data.store)
    assert (path / "archived.json").exists()
    assert not (path / "worker.log").exists()
    with pytest.raises(ServiceError):
        data.credential("k1", 1)
    assert data.credential("k1")["version"] == 2
    with pytest.raises(ServiceError):
        Application(data.root).logs(run_id)


def test_credential_in_artifact_filename_withheld_without_holding_capacity(
    data, preparation, monkeypatch
):
    run_id = prepare(data, preparation)
    folder = data.store.path(run_id) / "harbor" / run_id / "box__attempt" / "artifacts"
    folder.mkdir(parents=True)
    (folder / KEYS[0]).write_text("otherwise safe artifact")
    monkeypatch.setattr("harbor_helper.execution.audit.stop_group", lambda row: None)
    monkeypatch.setattr("harbor_helper.execution.audit.cleanup", lambda path: None)
    finish(data.store, data.store.get(run_id), "failed", "fixture failure")
    row = data.store.get(run_id)
    assert row["status"] == "failed" and row["audit_status"] == "incomplete"
    assert Application(data.root).usage()["active_jobs"] == 0
    assert Application(data.root).detail(run_id)["artifacts"] == []


def test_admin_enabled_metadata_is_boolean_for_web_controls(data):
    member = next(u for u in data.users() if u["username"] == "bob")
    assert member["enabled"] is True
    response = client(data, "admin").patch(
        f"/api/v1/admin/users/{member['id']}", headers=WRITE, json={"enabled": False}
    )
    assert response.json()["enabled"] is False
    assert next(u for u in data.users() if u["id"] == member["id"])["enabled"] is False
    assert data.disable_credential("k2")["enabled"] is False


def test_rerun_cannot_bypass_disabled_model_profile(data, preparation):
    run_id = prepare(data, preparation)
    profile = data.object("profile", "m1")
    profile["enabled"] = False
    data.models.save_object("profile", profile)
    actor = next(u for u in data.users() if u["username"] == "bob")
    with pytest.raises(ServiceError, match="profile disabled"):
        Application(data.root).accept(actor, {}, "disabled-rerun", parent=run_id)


def test_live_log_tail_reads_only_complete_lines(data, preparation):
    run_id = prepare(data, preparation)
    path = data.store.path(run_id) / "worker.log"
    # The 256 KiB seek starts inside this fake key, with an unfinished final line.
    path.write_text("before\n" + KEYS[0] + "\n" + "line\n" * 52425 + "partial")
    text = Application(data.root).logs(run_id)["text"]
    assert set(text.splitlines()) <= {"line"}
    assert "partial" not in text


@pytest.mark.parametrize(
    "left,right,comparable", [(2, 3, False), (3, 3, True), (None, 1, True), (None, 2, False)]
)
def test_compare_api_startup_conditions(data, preparation, left, right, comparable):
    from harbor_helper.persistence.files import write_json
    from harbor_helper.results.reports import report

    c = client(data)
    runs, manifests = [], []
    for index, multiplier in enumerate((left, right)):
        request = {
            "agent": "oracle",
            "dataset": "test/dataset@1",
            "environment_build_timeout_multiplier": multiplier if multiplier is not None else 1,
        }
        accepted = c.post(
            "/api/v1/submissions",
            headers={**WRITE, "Idempotency-Key": f"compare-{index}"},
            json=request,
        )
        assert accepted.status_code == 202
        prepare_one(data.store)
        run = data.submission(accepted.json()["id"])["run_id"]
        folder = data.store.path(run)
        if multiplier is None:
            # Construct an old-format record only in this isolated fixture.
            manifest = read_json(folder / "manifest.json")
            manifest["effective"].pop("environment_build_timeout_multiplier")
            write_json(folder / "manifest.json", manifest)
        trial = folder / "harbor" / run / "box__fixture"
        trial.mkdir(parents=True)
        write_json(
            trial / "result.json",
            {
                "task_name": "test/box",
                "trial_name": "box__fixture",
                "exception_info": None,
                "verifier_result": {"rewards": {"reward": 1.0}},
            },
        )
        data.store.update(run, status="succeeded", audit_status="clean")
        report(data.store, run)
        runs.append(run)
        manifests.append((folder / "manifest.json").read_bytes())
    response = c.post("/api/v1/compare", headers=WRITE, json={"left": runs[0], "right": runs[1]})
    assert response.status_code == 200
    value = response.json()
    assert value["comparable"] is comparable
    if comparable:
        assert value["config_changes"] == {} and value["mean_task_delta"] == {"reward": 0.0}
    else:
        assert value["config_changes"]["environment_build_timeout_multiplier"] == {
            "left": left if left is not None else 1,
            "right": right,
        }
        assert (
            "Experiment condition differs: environment_build_timeout_multiplier" in value["reasons"]
        )
        assert value["mean_task_delta"] is None
    assert manifests == [(data.store.path(run) / "manifest.json").read_bytes() for run in runs]


def test_pruning_merges_submission_accepted_during_dependency_inspection(
    data, preparation, monkeypatch
):
    original = data.dependencies
    accepted = []

    def snapshot_with_race():
        refs = original()
        accepted.append(accept_model(data, key="pruning-race"))
        data.add_credential("k1", "p1", "Key 1", "fake-new-key-2026", rotate=True)
        return refs

    monkeypatch.setattr(data, "dependencies", snapshot_with_race)
    assert data.prune_credentials()["pruned_versions"] == 0
    assert accepted
    assert data.credential("k1", 1)
