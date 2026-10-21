"""Recovery contracts with immutable author fixtures, no model or daemon requests."""

import shutil

from admission_fixture import synthetic_activity
from service_support import initialize_accounts

from harbor_helper.persistence.files import tree_digest
from harbor_helper.service.application import Application

SOURCE = "test/benchmark@sha256:" + "b" * 64
WRITE = {"X-Requested-With": "harbor-helper"}
PASSWORD = "recovery-fixture-password"


def author_task(root, *, compose=True, extra=""):
    root.mkdir(parents=True)
    (root / "task.toml").write_text(
        'version="1.0"\n[agent]\ntimeout_sec=600\n[verifier]\ntimeout_sec=180\n' + extra
    )
    if compose:
        (root / "environment").mkdir()
        (root / "environment/compose.yaml").write_text(
            "services:\n  main:\n    image: ${BUILD_AGENT_IMAGE:?required}\n"
        )
        (root / "tests").mkdir()
        (root / "tests/compose.yaml").write_text(
            "services:\n  verifier:\n    image: ${BUILD_VERIFIER_IMAGE:?required}\n"
        )
    return {
        "package": "test/answer",
        "directory": root.name,
        "ref": "sha256:" + "c" * 64,
        "snapshot_digest": tree_digest(root),
    }


def make_recovery(tmp_path, monkeypatch):
    task = tmp_path / "authors/answer"
    author_task(task)
    # Client config discovery contract is tested separately with actual Docker CLI.
    monkeypatch.setattr(
        "harbor_helper.execution.author_inputs.compose_variables",
        lambda file: [
            (
                "BUILD_AGENT_IMAGE"
                if file.parent.name == "environment"
                else "BUILD_VERIFIER_IMAGE",
                True,
                "",
            )
        ],
    )
    data = initialize_accounts(tmp_path, PASSWORD)
    synthetic_activity(data)
    app = Application(data.root)
    actor = data.users()[0]

    def source(reference, *, target=None, **kwargs):
        if target is None:
            return {
                "resolved": SOURCE,
                "tasks": [{"name": "answer", "package": "test/answer", "ref": "fixed"}],
            }
        shutil.copytree(task, target / "answer")
        return {
            "requested": reference,
            "resolved": SOURCE,
            "tasks": [
                {
                    "package": "test/answer",
                    "directory": "answer",
                    "ref": "fixed",
                    "snapshot_digest": tree_digest(target / "answer"),
                }
            ],
        }

    monkeypatch.setattr("harbor_helper.service.configuration.source_call", source)
    monkeypatch.setattr("harbor_helper.service.sources.source_call", source)
    dataset = app.configuration.save(
        "dataset", {"name": "Generic", "reference": "test/benchmark@1"}
    )
    dataset = app.configuration.verify("dataset", dataset["id"])
    return data, app, actor, dataset, task


def configured(recovery):
    _data, app, _actor, dataset, _task = recovery
    app.configuration.inspect_author_parameters(dataset["id"])
    parameters = app.configuration.save_author_parameters(
        dataset["id"],
        {
            "BUILD_AGENT_IMAGE": "author/agent:original",
            "BUILD_VERIFIER_IMAGE": "author/verifier:original",
        },
    )
    return parameters
