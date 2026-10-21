"""operation history behavior with isolated synthetic inputs."""

import sys
from pathlib import Path

import pytest
from service_support import make_data


def test_rejected_history_redecides_and_bounds_attempts(tmp_path, monkeypatch):

    from harbor_helper.service.application import Application
    from harbor_helper.service.history import listing
    from harbor_helper.service.primitives import ServiceError

    data = make_data(tmp_path)
    app = Application(data.root)
    user = data.users()[0]
    # Use production maintenance writer; no execution or external requests.
    from harbor_helper.persistence.files import write_json

    write_json(
        data.root / "admission.json",
        {"paused": True, "reason": "fixture", "retry_at": None, "updated": 1.0},
    )
    for _ in range(40):
        with pytest.raises(ServiceError) as rejected:
            app.accept(user, {"agent": "oracle"}, "same-rejected-key")
        assert rejected.value.code == "maintenance_paused"
    history = listing(data.store, user)
    assert history["total"] == 1
    row = history["operations"][0]
    assert row["attempts"] == 40 and len(row["recent"]) == history["attempt_limit"] == 32
    assert row["summarized_attempts"] == 8
    with data.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 0
    assert data.store.runs() == []
    write_json(
        data.root / "admission.json",
        {"paused": False, "reason": "", "retry_at": None, "updated": 2.0},
    )
    accepted = app.accept(user, {"agent": "oracle"}, "same-rejected-key")
    assert accepted["operation_id"] == row["id"]
    assert app.accept(user, {"agent": "oracle"}, "same-rejected-key")["id"] == accepted["id"]
    with pytest.raises(ServiceError) as conflict:
        app.accept(user, {"agent": "oracle", "name": "changed"}, "same-rejected-key")
    assert conflict.value.code == "idempotency_conflict"
    assert listing(data.store, user)["operations"][0]["status"] == "accepted"
    assert app.accept(user, {"agent": "oracle"}, "explicit-new")["id"] != accepted["id"]
    with pytest.raises(ServiceError):
        app.accept(user, {}, "missing-parent", parent="hh-missing-target")
    rejected_target = listing(data.store, user, key="missing-parent")["operations"][0]
    assert rejected_target["request"] == {
        "body": {},
        "parent": "hh-missing-target",
        "recovery": None,
    }
    with pytest.raises(ServiceError) as unsafe:
        app.accept(user, {}, "unsafe-parent", parent="hh_pat_v1_" + "A" * 43)
    assert unsafe.value.code == "access_plaintext"
    assert listing(data.store, user, key="unsafe-parent")["total"] == 0


def test_attachment_business_rejection_is_durable_and_retriable(tmp_path):
    from attachment_support import archive

    from harbor_helper.service.application import Application
    from harbor_helper.service.history import listing
    from harbor_helper.service.primitives import ServiceError

    data = make_data(tmp_path)
    app = Application(data.root)
    user = data.users()[0]
    first = app.attachments.write(user, "attachment_create", "input", {"name": "Input"}, archive())
    aid = first["attachment"]["id"]
    app.attachments.update(user, aid, {"enabled": False})
    with pytest.raises(ServiceError) as rejected:
        app.attachments.write(
            user, "attachment_publish", "publish", {"attachment_id": aid}, archive()
        )
    assert rejected.value.code == "attachment_disabled"
    operation_id = rejected.value.operation_id
    app.attachments.update(user, aid, {"enabled": True})
    result = app.attachments.write(
        user, "attachment_publish", "publish", {"attachment_id": aid}, archive()
    )
    assert result["operation_id"] == operation_id
    assert result["version"]["number"] == 2
    entry = listing(data.store, user, operation="attachment_publish")["operations"][0]
    assert entry["request"]["attachment_id"] == aid
    assert entry["request"]["digest"] == result["version"]["digest"]
    assert (
        listing(data.store, user, operation="attachment_publish")["operations"][0]["attempts"] == 2
    )


@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
def test_operation_submission_atomic_process_death(tmp_path, phase):
    import os
    import subprocess

    from harbor_helper.service.application import Application
    from harbor_helper.service.history import listing

    data = make_data(tmp_path)
    script = tmp_path / "crash.py"
    script.write_text("""
import os,sys
from contextlib import contextmanager
from harbor_helper.service.application import Application
app=Application(sys.argv[1]);original=app.store.connect
class Proxy:
    def __init__(self, db):self.db=db;self.written=False
    def execute(self,sql,*args):
        result=self.db.execute(sql,*args)
        if sql.startswith("INSERT INTO operations"):
            self.written=True
            if sys.argv[2]=="before_commit":os._exit(71)
        return result
@contextmanager
def connection():
    with original() as db:
        proxy=Proxy(db);yield proxy
    if proxy.written and sys.argv[2]=="after_commit":os._exit(72)
app.store.connect=connection
app.accept(app.data.users()[0],{"agent":"oracle"},"crash-key")
""")
    result = subprocess.run(
        [sys.executable, str(script), str(data.root), phase],
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path / "home"),
            "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
        },
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == (71 if phase == "before_commit" else 72), result.stderr
    with data.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == int(
            phase == "after_commit"
        )
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == int(
            phase == "after_commit"
        )
    app = Application(data.root)
    user = app.data.users()[0]
    accepted = app.accept(user, {"agent": "oracle"}, "crash-key")
    assert listing(data.store, user)["operations"][0]["id"] == accepted["operation_id"]
    with data.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 1
