"""07 sections 2-7: expiry from execution end, reclaiming with read pins, bounded
reads, index/file reconciliation (F-09, F-12) and storage watermarks (F-10)."""

import asyncio
import uuid

import pytest
from sqlalchemy import insert, select, update

from maestro.application import Maestro
from maestro.boundaries.storage import LocalArtifactStore
from maestro.core import clock
from maestro.core.errors import MaestroError
from maestro.db import migrate
from maestro.db import schema as t
from maestro.domain.states import Role
from maestro.services.disk import GIB, DiskWatch
from maestro.services.principal import Channel, Principal
from maestro.testing.fakes import FakeExecutor


@pytest.fixture
def local(settings, source):
    """A service writing real files, for races that depend on POSIX unlink."""
    built = Maestro.build(
        settings, executor=FakeExecutor(), store=LocalArtifactStore(settings.artifacts_dir)
    )
    migrate.upgrade(built.db)
    built.keys.initialize()
    version = built.catalog.register_version(source, "demo", "arith", "v1", True, None)
    owner = make_owner(built)
    built.worker.start_epoch()
    yield built, owner, version
    built.db.dispose()


def make_owner(service) -> Principal:
    with service.db.write() as conn:
        conn.execute(
            insert(t.users).values(
                id="usr_owner",
                username="owner",
                display_name="o",
                role="admin",
                status="active",
                password_hash="x",
                revision=1,
                created_at="t",
                updated_at="t",
            )
        )
    return Principal("usr_owner", "owner", Role.ADMIN, Channel.WEB_SESSION, session_id="s")


def run(service, owner, version_id, **body) -> str:
    _, data, _ = service.runs.submit(
        owner, uuid.uuid4().hex, {"name": "r", "dataset_version_id": version_id, **body}
    )
    asyncio.run(service.worker.drain())
    return data["run_id"]


def backdate(service, artifact_id: str) -> None:
    with service.db.write() as conn:
        conn.execute(
            update(t.artifacts)
            .where(t.artifacts.c.id == artifact_id)
            .values(expires_at=clock.to_text(clock.now() - clock.timedelta(seconds=1)))
        )


def test_expiry_counts_from_execution_end_not_upload(local):
    service, owner, version = local
    run_id = run(service, owner, version)
    with service.db.read() as conn:
        rows = conn.execute(
            select(t.artifacts.c.expires_at, t.trials.c.execution_terminal_at).join(
                t.trials, t.trials.c.id == t.artifacts.c.trial_id
            )
        ).all()
        finished = conn.execute(select(t.runs.c.finished_at).where(t.runs.c.id == run_id)).scalar()
    assert rows
    for expires, ended in rows:
        assert clock.from_text(expires) - clock.from_text(ended) == clock.timedelta(days=7)
    run_level = [a for a in service.artifacts.for_run(run_id) if a["trial_id"] is None]
    for artifact in run_level:
        assert clock.from_text(artifact["expires_at"]) - clock.from_text(finished) == (
            clock.timedelta(days=7)
        )


def test_reclaim_keeps_index_scores_and_reports_expired(local):
    service, owner, version = local
    run_id = run(service, owner, version)
    before = service.runs.summary(run_id)
    trial = service.runs.trials(run_id)[0]
    for artifact in service.artifacts.for_run(run_id, trial["id"]):
        backdate(service, artifact["id"])
    assert service.artifacts.sweep()["reclaimed"] == 2
    listed = service.artifacts.for_run(run_id, trial["id"])
    assert {a["status"] for a in listed} == {"expired"}
    assert all(a["digest"] and a["status_reason"] == "RETENTION_EXPIRED" for a in listed)
    with pytest.raises(MaestroError) as error:
        service.artifacts.read(listed[0]["id"])
    assert error.value.status == 410 and error.value.code == "ARTIFACT_EXPIRED"
    again = next(x for x in service.runs.trials(run_id) if x["id"] == trial["id"])
    assert again["artifact_state"] == "expired"
    assert again["artifact_counts"] == {"available": 0, "failed": 0, "expired": 2}
    assert again["result"]["score"] == trial["result"]["score"]
    assert service.runs.summary(run_id) == before


def test_pins_hold_files_for_a_bounded_time_and_open_readers_survive(local):
    service, owner, version = local
    run_id = run(service, owner, version)
    artifact = next(a for a in service.artifacts.for_run(run_id) if a["kind"] == "output")
    meta, reader, count, total = service.artifacts.open(artifact["id"])
    backdate(service, artifact["id"])
    pin_until = clock.now() + clock.timedelta(minutes=5)
    with service.db.write() as conn:
        conn.execute(
            insert(t.artifact_pins).values(
                id="pin_a",
                artifact_id=artifact["id"],
                holder_kind="export",
                holder_id="exp_x",
                expires_at=clock.to_text(pin_until),
            )
        )
    assert service.artifacts.sweep()["reclaimed"] == 0
    with service.db.write() as conn:
        conn.execute(update(t.artifact_pins).values(expires_at=clock.to_text(clock.now())))
    assert service.artifacts.sweep()["reclaimed"] == 1
    with service.db.read() as conn:
        assert conn.execute(select(t.artifact_pins)).first() is None  # released
    # A download that opened the file before reclaiming still reads all of it.
    with reader:
        assert len(reader.read(count)) == total == meta["size_bytes"]


def test_bounded_reads_for_log_paging(local, settings):
    service, owner, version = local
    run_id = run(service, owner, version)
    log = next(a for a in service.artifacts.for_run(run_id) if a["kind"] == "log")
    _, reader, count, total = service.artifacts.open(log["id"], offset=3, length=4)
    with reader:
        assert count == 4 and reader.read(count) == b"empt" and total == log["size_bytes"]
    _, reader, count, _ = service.artifacts.open(log["id"], offset=10_000)
    reader.close()
    assert count == 0
    with pytest.raises(MaestroError) as error:
        service.artifacts.open(log["id"], length=10**9)
    assert error.value.code == "INVALID_RANGE"


def test_reconcile_marks_missing_and_removes_orphans(local, settings):
    """F-09: after a crash no index row claims a missing file, no file lacks a row."""
    service, owner, version = local
    run_id = run(service, owner, version)
    artifact = service.artifacts.for_run(run_id)[0]
    with service.db.read() as conn:
        key = conn.execute(
            select(t.artifacts.c.storage_key).where(t.artifacts.c.id == artifact["id"])
        ).scalar()
    (settings.artifacts_dir / key).unlink()
    orphan = settings.artifacts_dir / "runs" / "orphan" / "file"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"published but never indexed")
    partial = settings.artifacts_dir / "runs" / "orphan" / ".file.123.tmp"
    partial.write_bytes(b"half")
    report = service.artifacts.reconcile()
    assert report == {"missing": 1, "orphans": 1, "partial": 1}
    assert not orphan.exists() and not partial.exists()
    row = next(a for a in service.artifacts.for_run(run_id) if a["id"] == artifact["id"])
    assert row["status"] == "unavailable" and row["status_reason"] == "STORAGE_CONTENT_MISSING"
    with pytest.raises(MaestroError) as error:
        service.artifacts.read(artifact["id"])
    assert error.value.code == "ARTIFACT_UNAVAILABLE"


def test_storage_watermarks_pause_acceptance_then_dispatch(local, settings):
    """F-10: low space refuses new runs, then holds queued ones; queries and cancel work."""
    service, owner, version = local
    free = {"bytes": 100 * GIB}
    watch = DiskWatch(
        settings.data_dir,
        type(settings)(
            **{
                **settings.__dict__,
                "storage_accept_min_free_gb": 20,
                "storage_dispatch_min_free_gb": 10,
                "storage_accept_min_free_percent": 0,
                "storage_dispatch_min_free_percent": 0,
            }
        ),
        usage=lambda _: (1000 * GIB, 0, free["bytes"]),
    )
    service.runs.disk = watch
    service.worker.disk = watch
    _, queued, _ = service.runs.submit(
        owner, uuid.uuid4().hex, {"name": "r", "dataset_version_id": version}
    )
    free["bytes"] = 15 * GIB
    with pytest.raises(MaestroError) as error:
        service.runs.submit(owner, uuid.uuid4().hex, {"name": "r", "dataset_version_id": version})
    assert error.value.code == "STORAGE_LOW" and error.value.status == 503
    free["bytes"] = 5 * GIB
    asyncio.run(service.worker.tick())
    held = service.runs.get(owner, queued["run_id"])
    assert held["state"] == "queued" and held["queue_reason"] == "STORAGE_LOW"
    assert service.runs.cancel(owner, queued["run_id"])["state"] == "cancelled"
    free["bytes"] = 100 * GIB
    assert watch.accepting() and watch.dispatching()
