"""Oracle run/report factories with no external execution or service credentials."""

import time

from harbor_helper.execution.config import (
    DEFAULT,
)
from harbor_helper.persistence.files import tree_digest, write_json


def make_store(tmp_path, monkeypatch):
    from harbor_helper.service.data import ServiceData

    s = ServiceData.initialize(
        tmp_path / "state", tmp_path / "private/master", "admin", "fake-test-password"
    ).store
    write_json(s.root / "team.json", DEFAULT)
    # Oracle fixtures carry no service binding; credentials are covered separately.
    monkeypatch.setattr("harbor_helper.service.data.ServiceData.run_key", lambda *_, **__: None)
    return s


def default_cfg(**changes):
    cfg = {
        "agent": "oracle",
        "attempts": 1,
        "concurrency": 1,
        "wall_seconds": 1800,
        "dataset": DEFAULT["dataset"],
        "model": DEFAULT["model"],
        "max_cpus_per_trial": DEFAULT["max_cpus_per_trial"],
        "max_memory_mb_per_trial": DEFAULT["max_memory_mb_per_trial"],
        "task_filter": None,
    }
    return {**cfg, **changes}


def add_run(store, name="hh-test", status="queued", concurrency=1):
    path = store.root / "runs" / name
    path.mkdir()
    tasks = path / "tasks" / "box"
    tasks.mkdir(parents=True)
    (tasks / "task.toml").write_text("fixed grader")
    cfg = default_cfg(concurrency=concurrency)
    manifest = {
        "run_id": name,
        "effective": cfg,
        "harbor_version": "0.23.0",
        "bundle_digest": None,
        "source": {
            "requested": "org/data@2",
            "resolved": "org/data@sha256:fixed",
            "tasks": [
                {
                    "package": "org/box",
                    "ref": "sha256:fixed",
                    "directory": "box",
                    "snapshot_digest": tree_digest(tasks),
                }
            ],
        },
    }
    write_json(path / "manifest.json", manifest)
    with store.connect() as db:
        db.execute(
            "INSERT INTO runs(id,status,created,concurrency) VALUES(?,?,?,?)",
            (name, status, time.time(), concurrency),
        )
    return path, manifest


def trial(path, reward=0.0, exception=None):
    p = path / "harbor" / path.name / "box__attempt"
    p.mkdir(parents=True)
    write_json(
        p / "result.json",
        {
            "task_name": "org/box",
            "trial_name": p.name,
            "verifier_result": {"rewards": {"reward": reward}},
            "exception_info": exception,
        },
    )
    return p
