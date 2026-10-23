"""Isolated instances: fresh data, cache and master-key directories per test."""

import pytest

from maestro.application import Maestro
from maestro.config import Settings
from maestro.db import migrate
from maestro.testing.fakes import FakeDatasetSource, FakeExecutor, MemoryArtifactStore


@pytest.fixture
def settings(tmp_path):
    data, cache, keys = tmp_path / "data", tmp_path / "cache", tmp_path / "keys"
    for path in (data, cache, keys):
        path.mkdir(mode=0o700)
    # Watermarks off: tests must not depend on the host's free space (test_disk sets them).
    return Settings(
        data_dir=data,
        cache_dir=cache,
        master_key_dir=keys,
        cookie_secure=False,
        storage_accept_min_free_gb=0,
        storage_accept_min_free_percent=0,
        storage_dispatch_min_free_gb=0,
        storage_dispatch_min_free_percent=0,
    )


@pytest.fixture
def executor():
    return FakeExecutor()


@pytest.fixture
def store():
    return MemoryArtifactStore()


@pytest.fixture
def service(settings, executor, store):
    built = Maestro.build(settings, executor=executor, store=store)
    migrate.upgrade(built.db)
    built.keys.initialize()
    built.worker.poll_seconds = 0.02
    yield built
    built.db.dispose()


@pytest.fixture
def source():
    fake = FakeDatasetSource()
    fake.add("demo", "arith", "v1", ["add-01", "add-02", "mul-01"])
    return fake


@pytest.fixture
def version_id(service, source):
    return service.catalog.register_version(source, "demo", "arith", "v1", True, None)
