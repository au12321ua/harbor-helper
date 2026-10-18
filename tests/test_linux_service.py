"""Lifecycle manager failure safety, ownership and offline backup/restore."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from harbor_helper.service.data import ServiceData


@pytest.fixture
def manager(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("linux_service", scripts / "service.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def installed(tmp_path, manager, monkeypatch):
    base = tmp_path / "instance"
    base.mkdir(mode=0o700)
    for name in ("state", "private", "home", "units", "logs", "releases", "manager"):
        (base / name).mkdir(mode=0o700)
    data = ServiceData.initialize(
        base / "state", base / "private/master.key", "admin", "Synthetic-install-password"
    )
    data.models.save_object(
        "provider",
        {
            "id": "local",
            "protocol": "openai-compatible",
            "endpoint": "http://127.0.0.1:1/v1",
            "name": "Synthetic",
        },
    )
    data.add_credential("local", "local", "Synthetic", "synthetic-never-sent")
    record = {
        "format": "harbor-helper-systemd-v1",
        "owner": "synthetic-owner",
        "directory": str(base),
        "instance": "test-install",
        "host": "127.0.0.1",
        "port": 18000,
        "runtime": True,
        "path": "/usr/bin:/bin",
        "release": "a" * 40,
        "installed": True,
    }
    (base / "releases" / record["release"]).mkdir()
    manager.ops.write_json(base / "instance.json", record)
    for part in ("http", "scheduler"):
        (base / "units" / manager.unit_name(record, part)).write_text(
            manager.unit_text(base, record, part)
        )
    calls = []

    def control(*argv):
        calls.append(argv)
        if "--property=FragmentPath" in argv:
            return str(base / "units" / argv[1])
        return ""

    monkeypatch.setattr(manager, "systemctl", control)
    # Unit-level offline filesystem coverage; actual /proc/systemd is integration-tested.
    monkeypatch.setattr(manager.ops, "writers", lambda *_: [])
    return base, record, data, calls


def test_upgrade_install_failure_retains_release_and_verified_backup(
    manager, installed, monkeypatch
):
    base, record, data, calls = installed
    monkeypatch.setattr(manager, "maintenance", lambda *_: True)

    def fail(*_):
        raise RuntimeError("synthetic install failure")

    monkeypatch.setattr(manager, "release", fail)
    backup = base.parent / "backups"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "service.py",
            "upgrade",
            "--directory",
            str(base),
            "--mode",
            "wait",
            "--backups",
            str(backup),
        ],
    )
    with pytest.raises(RuntimeError, match="synthetic install failure"):
        manager.main()
    assert json.loads((base / "instance.json").read_text()) == record
    assert data.key("local", 1, "local", True) == "synthetic-never-sent"
    checks = list(backup.glob("snapshot-*-restore-check/restore-check.json"))
    assert len(checks) == 1
    result = json.loads(checks[0].read_text())
    assert result["credentials_checked"] == 1 and result["full_state"]
    assert result["offline_validation"] == "passed"
    assert not any(call[0] == "start" for call in calls)


def test_foreign_unit_refused_before_stop(manager, installed):
    base, record, _, calls = installed
    (base / "units" / manager.unit_name(record, "http")).write_text("foreign")
    with pytest.raises(ValueError, match="ownership/content mismatch"):
        manager.validate(base, record)
    assert calls == []


def test_purge_requires_separate_exact_confirmation(manager, installed, monkeypatch):
    base, record, _, calls = installed
    monkeypatch.setattr(
        sys, "argv", ["service.py", "uninstall", "--directory", str(base), "--purge"]
    )
    with pytest.raises(ValueError, match="independent --confirm-delete"):
        manager.main()
    assert (base / "state/queue.sqlite").exists()
    assert (base / "private/master.key").exists()
    assert (base / "releases" / record["release"]).exists()
    assert not any(call[0] == "disable" for call in calls)


def test_generated_working_directory_is_absolute_unquoted(manager, installed):
    base, record, _, _ = installed
    text = manager.unit_text(base, record, "scheduler")
    line = next(line for line in text.splitlines() if line.startswith("WorkingDirectory="))
    assert line == f"WorkingDirectory={base}/releases/{record['release']}"
    assert "Restart=on-failure" in text and "KillMode=mixed" in text
