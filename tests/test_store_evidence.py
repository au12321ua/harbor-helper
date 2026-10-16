"""Evidence locks validate identity before filesystem effects and retain flock semantics."""

import os
import threading

import pytest

from harbor_helper.persistence.store import Store


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "state")
    (store.root / "runs" / "valid").mkdir()
    with store.connect() as db:
        db.execute("INSERT INTO runs(id,status,created,concurrency) VALUES('valid','queued',0,1)")
    return store


@pytest.mark.parametrize(
    "reference",
    [
        "absolute",
        "../../outside/victim",
        "a/b",
        "a\\b",
        ".",
        "..",
        "",
        "missing",
        None,
        "nul\0",
        "x" * 81,
    ],
)
def test_evidence_rejects_invalid_or_unknown_run_before_creating_locks(store, tmp_path, reference):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"unchanged")
    run_id = str(outside / "victim") if reference == "absolute" else reference
    # Even a damaged database row must not make a path-like ID acceptable.
    if run_id and run_id != "missing":
        with store.connect() as db:
            db.execute(
                "INSERT INTO runs(id,status,created,concurrency) VALUES(?,'queued',0,1)", (run_id,)
            )
    with pytest.raises(ValueError), store.evidence(run_id):
        pytest.fail("invalid evidence reference acquired")
    assert not (store.root / "evidence-locks").exists()
    assert list(outside.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"unchanged"


@pytest.mark.parametrize("kind", ["symlink", "fifo", "directory", "hardlink"])
def test_evidence_rejects_nonregular_or_aliased_lock(store, tmp_path, kind):
    folder = store.root / "evidence-locks"
    folder.mkdir()
    target = tmp_path / "outside-target"
    target.write_bytes(b"unchanged")
    lock = folder / "valid.lock"
    if kind == "symlink":
        lock.symlink_to(target)
    elif kind == "fifo":
        os.mkfifo(lock)
    elif kind == "directory":
        lock.mkdir()
    else:
        os.link(target, lock)
    with pytest.raises((ValueError, OSError)), store.evidence("valid", blocking=False):
        pytest.fail("unsafe evidence lock acquired")
    assert target.read_bytes() == b"unchanged"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["outside-target", "state"]


def test_evidence_rejects_symlink_directory_and_run_path(store, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    folder = store.root / "evidence-locks"
    folder.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError), store.evidence("valid"):
        pytest.fail("symlink lock directory accepted")
    assert not list(outside.iterdir())
    folder.unlink()
    run = store.root / "runs" / "valid"
    run.rmdir()
    run.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="Invalid run path"), store.evidence("valid"):
        pytest.fail("symlink run accepted")
    assert not folder.exists()
    assert not list(outside.iterdir())


def test_evidence_lock_remains_exclusive_and_reentrant(store):
    other = Store(store.root)

    def compete():
        result = []

        def attempt():
            try:
                with other.evidence("valid", blocking=False):
                    result.append("acquired")
            except BlockingIOError:
                result.append("busy")

        thread = threading.Thread(target=attempt)
        thread.start()
        thread.join(timeout=2)
        assert not thread.is_alive()
        return result

    with store.evidence("valid"):
        with other.evidence("valid", blocking=False):
            assert compete() == ["busy"]
        assert compete() == ["busy"]  # Inner exit must not release the outer lock.
    assert compete() == ["acquired"]
