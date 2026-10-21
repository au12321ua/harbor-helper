"""Function-scoped shared fixture registration; factories live in support modules."""

import pytest
from support.core_support import make_store
from support.http_support import serve_http
from support.process_support import Processes
from support.recovery_support import make_recovery
from support.service_support import make_data, patch_preparation


@pytest.fixture
def data(tmp_path):
    return make_data(tmp_path)


@pytest.fixture
def preparation(monkeypatch):
    return patch_preparation(monkeypatch)


@pytest.fixture
def http_service(tmp_path):
    yield from serve_http(tmp_path)


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    return make_recovery(tmp_path, monkeypatch)


@pytest.fixture
def processes(tmp_path):
    p = Processes(tmp_path)
    try:
        yield p
    finally:
        p.close()


@pytest.fixture
def store(tmp_path, monkeypatch):
    return make_store(tmp_path, monkeypatch)
