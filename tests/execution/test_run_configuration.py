"""run configuration behavior with isolated synthetic inputs."""

import sqlite3

import pytest
from support.core_support import add_run, default_cfg, trial

from harbor_helper.execution.config import (
    load_team,
    reject_secrets,
    validate_effective,
)
from harbor_helper.execution.runs import job_config, safe_environment, submit
from harbor_helper.execution.sources import verify_inputs
from harbor_helper.persistence.files import tree_digest, write_json
from harbor_helper.persistence.store import Store


def test_rerun_refuses_modified_grader(store):
    p, m = add_run(store)
    verify_inputs(p, m)
    (p / "tasks" / "box" / "task.toml").write_text("changed grader")
    with pytest.raises(ValueError, match="Fixed task snapshot"):
        submit(store, load_team(store), parent=p.name, service={"submission_id": "s"})
    assert len(store.runs()) == 1


def test_digest_rejects_symlink_and_detects_mode(tmp_path):
    f = tmp_path / "bootstrap.sh"
    f.write_text("same")
    before = tree_digest(tmp_path)
    f.chmod(0o755)
    assert tree_digest(tmp_path) != before
    (tmp_path / "link").symlink_to(f)
    with pytest.raises(ValueError, match="symlinks"):
        tree_digest(tmp_path)


@pytest.mark.parametrize(
    "cfg",
    [
        {"apiKey": "abc"},
        {"password": "abc"},
        {"endpoint": "https://user:pass@host"},
        {"endpoint": "https://host?key=abc"},
    ],
)
def test_no_literal_credentials(cfg):
    with pytest.raises(ValueError):
        reject_secrets(cfg)


def test_nonsecret_token_length_settings_are_allowed():
    reject_secrets({"max_tokens": 64, "maxOutputTokens": 128})
    with pytest.raises(ValueError):
        reject_secrets({"max_tokens": "literal-token-value"})
    with pytest.raises(ValueError):
        reject_secrets({"access_token": 64})


def test_runtime_environment_drops_other_provider_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "never-inherit")
    monkeypatch.setenv("VLLM_API_KEY", "explicit-credential")
    value = safe_environment()
    assert "OPENAI_API_KEY" not in value and "VLLM_API_KEY" not in value


def test_missing_model_no_requests(store):
    with pytest.raises(ValueError, match="Model not configured"):
        validate_effective(load_team(store), default_cfg(agent="opencode"))


def test_old_queue_migration_preserves_rows(tmp_path):
    root = tmp_path / "old-state"
    root.mkdir()
    with sqlite3.connect(root / "queue.sqlite") as db:
        db.execute("""CREATE TABLE runs (
            id TEXT PRIMARY KEY, status TEXT, created REAL, started REAL,
            finished REAL, pid INTEGER, birth TEXT, concurrency INTEGER,
            cancel INTEGER, reason TEXT, parent TEXT)""")
        db.execute("INSERT INTO runs(id,status,created,concurrency) VALUES('old','failed',1,1)")
    migrated = Store(root)
    assert migrated.get("old")["audit_status"] == "pending"
    assert migrated.get("old")["status"] == "failed"
    assert Store(root).runs() == migrated.runs()


def test_opencode_config_uses_only_selected_provider_and_placeholder(store):
    p, m = add_run(store)
    m["effective"]["agent"] = "opencode"
    m["effective"]["model"] = {
        "name": "local-model",
        "endpoint": "http://localhost:8000/v1",
        "credential_env": "VLLM_API_KEY",
        "opencode_version": "1.3.9",
    }
    cfg = job_config(p, m)
    agent = cfg["agents"][0]
    assert agent["env"] == {"VLLM_API_KEY": "${VLLM_API_KEY}"}
    assert agent["kwargs"]["opencode_config"]["enabled_providers"] == ["vllm"]
    assert agent["model_name"] == "vllm/local-model"


def test_bundle_cannot_silently_override_selected_model_parameters(store):
    p, m = add_run(store)
    m["effective"]["agent"] = "opencode"
    m["effective"]["model"] = {
        "name": "selected",
        "endpoint": "https://fixture.invalid/v1",
        "credential_env": "VLLM_API_KEY",
        "opencode_version": "1.18.35",
        "parameters": {"temperature": 0, "maxOutputTokens": 128},
    }
    cfg = job_config(p, m)
    selected = cfg["agents"][0]["kwargs"]["opencode_config"]["provider"]["vllm"]["models"][
        "selected"
    ]
    assert selected["options"] == m["effective"]["model"]["parameters"]
    bundle = p / "bundle" / "config"
    bundle.mkdir(parents=True)
    write_json(
        bundle / "opencode.json",
        {"provider": {"vllm": {"models": {"selected": {"options": {"temperature": 1}}}}}},
    )
    with pytest.raises(ValueError, match="Bundle config supports only"):
        job_config(p, m)
    assert m["effective"]["model"]["parameters"]["temperature"] == 0


def test_credential_redaction_keeps_frozen_inputs_intact(store):
    from harbor_helper.execution.audit import redact_files

    p, _ = add_run(store)
    token = "literal-occurrence"
    frozen = p / "tasks" / "box" / "task.toml"
    frozen.write_text(token)
    native = trial(p)
    (native / "agent").mkdir()
    output = native / "agent" / "agent.txt"
    output.write_text("Bearer " + token)
    redact_files(p, [token])
    assert output.read_text() == "Bearer [REDACTED]"
    assert frozen.read_text() == token
