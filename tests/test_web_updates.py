"""Upgrade trust boundaries, persistent ownership, and real git metadata relationships."""

import importlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbor_helper.persistence.store import Store
from harbor_helper.persistence.upgrades import blocked, durable, enqueue, projection
from harbor_helper.service.api import create_app
from harbor_helper.service.data import ServiceData

WRITE = {"X-Requested-With": "harbor-helper"}
PASSWORD = "Synthetic-web-update-password"


@pytest.fixture
def instance(tmp_path):
    base = tmp_path / "installation"
    base.mkdir(mode=0o700)
    data = ServiceData.initialize(base / "state", base / "private/master", "admin", PASSWORD)
    data.create_user("member", PASSWORD)
    for name in ("updates", "updates/spool", "updates/results"):
        (base / name).mkdir(mode=0o700)
    durable(base / "updates/enabled.json", {"owner": "synthetic-owner", "protocol": 1})
    yield base, data
    data.store.close()


def login(base, username="admin"):
    client = TestClient(create_app(base / "state"), raise_server_exceptions=False)
    response = client.post(
        "/api/v1/auth/login", headers=WRITE, json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return client


def test_roles_origin_spool_and_idempotency(instance):
    base, data = instance
    admin, member = login(base), login(base, "member")
    body = {"action": "check", "request_id": "synthetic-request-0001", "payload": {}}
    assert member.post("/api/v1/admin/updates", json=body, headers=WRITE).status_code == 403
    assert (
        admin.post(
            "/api/v1/admin/updates",
            json=body,
            headers={**WRITE, "Origin": "https://foreign.invalid"},
        ).status_code
        == 403
    )
    one = admin.post("/api/v1/admin/updates", json=body, headers=WRITE)
    assert one.status_code == 200, one.text
    two = admin.post("/api/v1/admin/updates", json=body, headers=WRITE)
    assert one.json() == two.json()
    assert len(list((base / "updates/spool").glob("*.json"))) == 1
    assert (
        admin.post(
            "/api/v1/admin/updates",
            json={**body, "payload": {"repository": "/arbitrary"}},
            headers=WRITE,
        ).status_code
        == 422
    )
    assert member.get("/api/v1/version").status_code == 200
    assert set(TestClient(create_app(base / "state")).get("/api/v1/build").json()) == {"build"}
    data.store.close()


def test_barrier_before_construction_auth_and_missing_state(instance, monkeypatch):
    base, data = instance
    live = login(base)
    admin_token = live.cookies.get("hh_session")
    data.store.close()
    before = (base / "state/queue.sqlite").read_bytes()
    durable(
        base / "updates/journal.json",
        {"protocol": 1, "id": "owned-job", "phase": "backup", "barrier": True},
    )
    durable(base / "state/.upgrade.json", {"protocol": 1, "job": "owned-job"})

    def forbidden(*args, **kwargs):
        raise AssertionError("Store must not be constructed")

    monkeypatch.setattr("harbor_helper.service.api.Store", forbidden)

    # isinstance requires a class; use a class that always fails to construct.
    class Forbidden:
        def __init__(self, *args, **kwargs):
            forbidden()

    monkeypatch.setattr("harbor_helper.service.api.Store", Forbidden)
    client = TestClient(create_app(base / "state"))
    for method, path in [
        ("get", "/api/v1/me"),
        ("get", "/api/v1/admin/updates"),
        ("post", "/api/v1/auth/login"),
        ("get", "/api/v1/machine/discovery"),
    ]:
        response = getattr(client, method)(
            path, headers={**WRITE, "Authorization": "Bearer synthetic-pat"}
        )
        assert response.status_code == 503
        assert response.json()["code"] == "upgrade_in_progress"
    assert client.get("/api/v1/health").json() == {"alive": True, "ready": False}
    assert client.get("/api/v1/upgrade-phase").json() == {"upgrading": True, "phase": "backup"}
    assert (base / "state/queue.sqlite").read_bytes() == before
    assert (
        live.get("/api/v1/me", headers={"Cookie": "hh_session=" + (admin_token or "")}).status_code
        == 503
    )
    (base / "state").rename(base / "state-failed")
    assert create_app(base / "state").state.application is None
    with pytest.raises(ValueError, match="upgrade_in_progress"):
        Store(base / "state")
    assert not (base / "state").exists()


def test_nonterminal_maintenance_ownership_without_process(instance):
    base, _data = instance
    client = login(base)
    durable(
        base / "updates/journal.json",
        {"protocol": 1, "id": "owned-job", "phase": "waiting", "barrier": False},
    )
    assert not blocked(base / "state")
    for path, method, body in [
        ("/admin/maintenance", "patch", {"paused": False}),
        ("/admin/shutdown", "post", {"mode": "abort"}),
    ]:
        response = getattr(client, method)("/api/v1" + path, json=body, headers=WRITE)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "upgrade_in_progress"


def test_corrupt_external_journal_fails_closed(tmp_path):
    (tmp_path / "updates").mkdir(mode=0o700)
    (tmp_path / "updates/journal.json").write_text("broken")
    assert blocked(tmp_path / "state")
    assert projection(tmp_path / "state")["phase"] == "needs_manual"
    assert not (tmp_path / "state").exists()


def test_request_conflict_and_result_idempotency(instance):
    base, _data = instance
    result = enqueue(base / "state", "check", "actor", "synthetic-request-0001", {})
    path = base / "updates/spool" / (result["request_id"] + ".json")
    value = json.loads(path.read_text())
    durable(base / "updates/results" / path.name, {"request": value, "result": {}})
    path.unlink()
    assert enqueue(base / "state", "check", "actor", "synthetic-request-0001", {}) == result
    assert not path.exists()
    with pytest.raises(ValueError, match="different request"):
        enqueue(base / "state", "cancel", "actor", "synthetic-request-0001", {"job": "other"})


def test_git_relations_and_metadata_drift(tmp_path, monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    manager = importlib.import_module("update_manager")
    base = tmp_path / "instance"
    for name in ("home", "private", "updates"):
        (base / name).mkdir(mode=0o700, parents=True, exist_ok=True)
    source = tmp_path / "source"
    env = {
        "PATH": os.defpath,
        "HOME": str(base / "home"),
        "GIT_AUTHOR_NAME": "Synthetic",
        "GIT_AUTHOR_EMAIL": "synthetic@example.invalid",
        "GIT_COMMITTER_NAME": "Synthetic",
        "GIT_COMMITTER_EMAIL": "synthetic@example.invalid",
    }

    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(source), *args], env=env, text=True
        ).strip()

    source.mkdir()
    git("init", "-b", "dev")
    contract = {
        "format": 1,
        "manager_protocol": 1,
        "journal_protocol": 1,
        "barrier": True,
        "probe_protocol": 1,
        "python": ">=3.12,<3.14",
    }
    (source / "update-contract.json").write_text(json.dumps(contract))
    (source / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.12,<3.14"\n')
    git("add", ".")
    git("commit", "-m", "A")
    first = git("rev-parse", "HEAD")
    (source / "change").write_text("B")
    git("add", ".")
    git("commit", "-m", "B")
    second = git("rev-parse", "HEAD")
    (base / "private/update.toml").write_text(
        "[updates]\nrepository = " + json.dumps(str(source)) + '\nbranch = "dev"\n'
    )
    (base / "private/update.toml").chmod(0o600)
    _config, _digest, clean, tip = manager.fetch(base)
    assert tip == second
    assert manager.relation(base, clean, first, second) == "update"
    assert manager.relation(base, clean, second, first) == "behind"
    assert manager.relation(base, clean, first, first) == "current"
    assert manager.relation(base, clean, "f" * 40, first) == "unknown"
    assert manager.check(base, {"release": first}, "check")["metadata"] == "passed"
    git("checkout", "--orphan", "unrelated")
    git("commit", "-m", "Unrelated")
    unrelated = git("rev-parse", "HEAD")
    git("branch", "-f", "dev", unrelated)
    manager.fetch(base)
    assert manager.relation(base, clean, first, unrelated) == "diverged"
    assert not manager.ancestor(base, clean, second, unrelated)
    assert "OPENAI_API_KEY" not in clean and clean["HOME"] == str(base / "home")


def test_journal_write_failure_does_not_poison_recovery(instance, monkeypatch):
    base, _data = instance
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    manager = importlib.import_module("update_manager")
    value = {"protocol": 1, "id": "job", "phase": "backup"}
    manager.save(base, value)
    before = value.copy()
    with pytest.raises(TypeError):
        manager.save(base, value, unserializable={("synthetic", "identity")})
    assert value == before
    assert json.loads((base / "updates/journal.json").read_text()) == before
    manager.save(base, value, phase="needs_manual")
    assert json.loads((base / "updates/journal.json").read_text())["phase"] == "needs_manual"


def test_dangling_barrier_is_not_treated_as_absence(tmp_path):
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    (root / ".upgrade.json").symlink_to(tmp_path / "missing-marker")
    assert blocked(root)
    with pytest.raises(ValueError, match="upgrade_in_progress"):
        Store(root)
    assert not (root / "queue.sqlite").exists()


@pytest.mark.parametrize("window", ["rename_old_pending", "rename_new_pending"])
def test_journalled_rename_recovery_preserves_original_paths(instance, monkeypatch, window):
    import shutil
    from types import SimpleNamespace

    base, data = instance
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    manager = importlib.import_module("update_manager")
    data.store.close()
    release = "a" * 40
    manager.protocol.durable(base / "state/release.json", {"release": release})
    record = {
        "release": release,
        "instance": "fixture",
        "owner": "fixture",
        "directory": str(base),
        "format": "harbor-helper-systemd-v1",
    }
    manager.protocol.durable(base / "instance.json", record)
    value = {
        "protocol": 1,
        "id": "synthetic-restore",
        "phase": "backup",
        "barrier": True,
        "commit_decided": False,
        "original_record": record,
        "source_release": release,
        "target": "b" * 40,
        "original_units": {"http": "inactive", "scheduler": "inactive"},
        "original_files": {"admission.json": None, "shutdown.json": None},
    }
    durable(base / "state/.upgrade.json", {"protocol": 1, "job": value["id"]})
    monkeypatch.setattr(manager.ops, "writers", lambda *_: [])
    monkeypatch.setattr(manager.ops, "execution_quiescence", lambda *_: {})
    monkeypatch.setattr(manager.ops, "host_processes", lambda *_: {"uninspectable": []})
    output = base.parent / "snapshots"
    saved = manager.ops.backup(
        SimpleNamespace(
            directory=base, output=output, release=release, kind="offline", lock_timeout=1
        )
    )
    snap = Path(saved["snapshot"])
    value.update(
        snapshot=str(snap),
        private_inventory=manager.ops.inventory(base / "private"),
        live_baseline=manager.ops.state_inventory(base / "state"),
    )
    original_db = (base / "state/queue.sqlite").read_bytes()
    with manager.ops.ro_db(base / "state") as db:
        original_rows = {
            table: [dict(row) for row in db.execute(f'SELECT * FROM "{table}"')]
            for table in manager.ops.schema(db)
        }
    original_config = (base / "state/service.json").read_bytes()
    stage = base / ("state-restore-" + value["id"])
    shutil.copytree(snap / "state", stage)
    durable(stage / ".upgrade.json", {"protocol": 1, "job": value["id"]})
    value["restore_baseline"] = manager.ops.state_inventory(stage)
    value["restore_step"] = window
    manager.save(base, value)
    if window == "rename_new_pending":
        (base / "state").rename(base / ("state-failed-" + value["id"]))
        assert blocked(base / "state")
    manager.save(base, value)
    monkeypatch.setattr(manager.host, "stop", lambda *_: None)
    monkeypatch.setattr(manager.host, "units", lambda *_: None)
    monkeypatch.setattr(manager, "start_original", lambda *_: None)

    def actual_application(_base, _value, lease, _release):
        assert (base / "state/queue.sqlite").read_bytes() == original_db
        with manager.protocol.migration_lease(base / "state", lease.fileno()):
            app = create_app(base / "state")
            app.state.application.store.close()

    monkeypatch.setattr(manager, "target_validate", actual_application)
    monkeypatch.setattr(manager, "ready", lambda *_: None)
    manager.rollback(base, value)
    with manager.ops.ro_db(base / "state") as db:
        assert {
            table: [dict(row) for row in db.execute(f'SELECT * FROM "{table}"')]
            for table in original_rows
        } == original_rows
    assert (base / "state/service.json").read_bytes() == original_config
    assert (base / ("state-failed-" + value["id"]) / "queue.sqlite").read_bytes() == original_db
    assert not blocked(base / "state")
    assert value["recovered"] and value["commit_decided"]
    with pytest.raises(ValueError, match="must never be rolled back"):
        manager.rollback(base, value)


def test_offline_copy_probe_and_exclusive_live_application_validation(instance, monkeypatch):
    import sys
    from types import SimpleNamespace

    base, data = instance
    data.models.save_object(
        "provider",
        {"id": "p1", "protocol": "openai-compatible", "endpoint": "http://never.invalid/v1"},
    )
    data.add_credential("k1", "p1", "synthetic", "never-transmitted")
    data.store.close()
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    manager = importlib.import_module("update_manager")
    monkeypatch.setattr(manager.ops, "writers", lambda *_: [])
    monkeypatch.setattr(manager.ops, "execution_quiescence", lambda *_: {})
    monkeypatch.setattr(manager.ops, "host_processes", lambda *_: {"uninspectable": []})
    saved = manager.ops.backup(
        SimpleNamespace(
            directory=base,
            output=base.parent / "backups",
            release="a" * 40,
            kind="offline",
            lock_timeout=1,
        )
    )
    snapshot = Path(saved["snapshot"])
    folder = base / "updates/probe-test"
    manager.ops.copy_stable(snapshot / "state", folder / "state")
    (folder / "private").mkdir(mode=0o700)
    with manager.ops.ro_db(folder / "state") as db:
        basename = manager.ops.active_reference(db)["basename"]
    manager.ops.write_key(
        folder / "private" / basename,
        manager.ops.key_bytes(snapshot.parent / (snapshot.name + ".master")),
    )
    before = manager.ops.state_inventory(base / "state")
    output = manager.command(
        [
            sys.executable,
            str(scripts / "update_probe.py"),
            "--root",
            str(folder / "state"),
            "--release",
            "b" * 40,
            "--original",
            str(base / "state"),
            "--master-directory",
            str(folder / "private"),
            "--complete",
        ],
        env=manager.environment(base),
    )
    assert json.loads(output)["counts"]["credentials"] == 1
    assert manager.ops.state_inventory(base / "state") == before
    durable(
        base / "updates/journal.json",
        {"protocol": 1, "id": "live-job", "phase": "migrating", "barrier": True},
    )
    durable(base / "state/.upgrade.json", {"protocol": 1, "job": "live-job"})
    with manager.ops.writer_lease(base / "state") as lease:
        output = manager.command(
            [
                sys.executable,
                str(scripts / "update_probe.py"),
                "--root",
                str(base / "state"),
                "--release",
                "a" * 40,
                "--lease-fd",
                str(lease.fileno()),
                "--complete",
            ],
            env=manager.environment(base),
            pass_fds=(lease.fileno(),),
        )
    assert json.loads(output)["complete"] is True
    assert blocked(base / "state")


@pytest.mark.parametrize("operation", ["socket", "subprocess", "original-read"])
def test_probe_audit_guard_rejects_external_effects(instance, monkeypatch, operation):
    import sys

    base, data = instance
    data.store.close()
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    manager = importlib.import_module("update_manager")
    before = manager.ops.state_inventory(base / "state")
    operations = {
        "socket": "import socket; socket.create_connection(('127.0.0.1', 9), timeout=1)",
        "subprocess": "import subprocess; subprocess.run(['/bin/true'], check=True)",
        "original-read": "open(" + repr(str(base / "state/service.json")) + ").read()",
    }
    code = (
        """import runpy,sys
sys.path.insert(0, SCRIPT_DIRECTORY)
import harbor_helper.service.application as module
operation_code, root, master, kind = sys.argv[1:]
original=module.Application
class Injected(original):
    def __init__(self,*args,**kwargs):
        exec(operation_code)
        super().__init__(*args,**kwargs)
module.Application=Injected
sys.argv=['update_probe.py','--root',root,'--release','a'*40]
if kind=='original-read':
    sys.argv += ['--original',ORIGINAL_STATE,'--master-directory',master]
runpy.run_path(PROBE_PATH,run_name='__main__')
""".replace("SCRIPT_DIRECTORY", repr(str(scripts)))
        .replace("ORIGINAL_STATE", repr(str(base / "state")))
        .replace("PROBE_PATH", repr(str(scripts / "update_probe.py")))
    )
    root = base / "state"
    if operation == "original-read":
        import shutil

        root = base / "updates/guard-state"
        shutil.copytree(base / "state", root)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            operations[operation],
            str(root),
            str(base / "private"),
            operation,
        ],
        env=manager.environment(base),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1
    assert json.loads(result.stderr) == {"failed": "PermissionError"}
    assert manager.ops.state_inventory(base / "state") == before


def test_automation_credential_cannot_check_upgrade_or_read_admin_journal(instance):
    from harbor_helper.service.access import issue

    base, data = instance
    actor = next(user for user in data.users() if user["username"] == "admin")
    credential = issue(data, actor, "synthetic automation", PASSWORD, ["read", "execute"], None)
    client = TestClient(create_app(base / "state"))
    headers = {**WRITE, "Authorization": "Bearer " + credential["token"]}
    response = client.post(
        "/api/v1/admin/updates",
        headers=headers,
        json={"action": "check", "request_id": "synthetic-pat-check-0001", "payload": {}},
    )
    assert response.status_code == 403 and response.json()["code"] == "session_required"
    assert client.get("/api/v1/admin/updates", headers=headers).status_code == 403
    assert not list((base / "updates/spool").iterdir())


@pytest.mark.parametrize(
    "phase,barrier,committed",
    [("preparing", False, False), ("migrating", True, False), ("succeeded", False, True)],
)
def test_restart_never_reexecutes_journalled_upgrade(
    instance, monkeypatch, phase, barrier, committed
):
    base, _data = instance
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    manager = importlib.import_module("update_manager")
    record = {"owner": "synthetic-owner", "release": "a" * 40}
    durable(base / "instance.json", record)
    queued = enqueue(
        base / "state",
        "upgrade",
        "actor",
        "synthetic-restart-request",
        {"check_id": "c" * 64, "target_sha": "b" * 40, "config_digest": "d" * 64},
    )
    value = {
        "protocol": 1,
        "id": queued["request_id"],
        "phase": phase,
        "barrier": barrier,
        "commit_decided": committed,
        "manager_activation_pending": False,
    }
    durable(base / "updates/journal.json", value)
    monkeypatch.setattr(manager.host, "validate", lambda *_: None)

    def forbidden(*_):
        raise AssertionError("Journalled upgrade was executed twice")

    monkeypatch.setattr(manager, "upgrade", forbidden)
    manager.run(base)
    result = json.loads((base / "updates/results" / (queued["request_id"] + ".json")).read_text())
    assert result["result"]["job"] == queued["request_id"]
    assert result["result"]["phase"] == (
        "succeeded" if committed else "needs_manual" if barrier else "failed"
    )
    assert not list((base / "updates/spool").iterdir())
    restored = json.loads((base / "updates/journal.json").read_text())
    assert restored["commit_decided"] == committed
    if phase == "migrating":
        assert restored["interrupted_phase"] == "migrating"
        manager.run(base)
        assert (
            json.loads((base / "updates/journal.json").read_text())["interrupted_phase"]
            == "migrating"
        )
