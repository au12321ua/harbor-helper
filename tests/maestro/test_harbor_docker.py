"""Real Harbor Runner and Docker, Oracle tasks only (M3 and M4 exit criteria).

Opt-in: ``MAESTRO_DOCKER_TESTS=1``. Needs Docker with buildx, a local ``ubuntu:22.04``
image and the Runner environment (``uv sync --locked`` in ``runner/``, or
``MAESTRO_RUNNER_PYTHON``). No model, Hub or network request is made. Execution
resources carry a per-test instance label, prepared images live in the per-instance
``maestro-prep/<instance>`` repository; both are checked to be gone afterwards.
"""

import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest
from support import Api, create_pat, running, setup_admin, wait_operation

from maestro.application import Maestro
from maestro.boundaries.storage import LocalArtifactStore
from maestro.db import migrate
from maestro.execution.docker import DockerResources
from maestro.execution.harbor import HarborExecutor
from maestro.execution.materials import LocalTaskSource, TaskMaterials
from maestro.execution.preparation import DockerEnvironment
from maestro.services.instance import instance_id as read_instance_id

ROOT = Path(__file__).resolve().parents[2]
TASKS = Path(__file__).with_name("fixtures") / "harbor-tasks"
RUNNER = Path(os.environ.get("MAESTRO_RUNNER_PYTHON", ROOT / "runner/.venv/bin/python"))

pytestmark = pytest.mark.skipif(
    os.environ.get("MAESTRO_DOCKER_TESTS") != "1" or not RUNNER.is_file(),
    reason="set MAESTRO_DOCKER_TESTS=1 and install the Runner environment",
)


def labelled(instance_id: str) -> list[str]:
    found = []
    for kind in (["ps", "-aq"], ["network", "ls", "-q"], ["images", "-q"]):
        out = subprocess.run(
            ["docker", *kind, "--filter", f"label=io.maestro.instance_id={instance_id}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        found += [f"{kind[0]}:{x}" for x in out]
    return found


def prepared_images(instance_id: str) -> list[str]:
    out = subprocess.run(
        [
            "docker",
            "image",
            "ls",
            f"maestro-prep/{instance_id}",
            "--format",
            "{{.Repository}}:{{.Tag}}",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return sorted(out)


def remove_prepared(instance_id: str) -> None:
    refs = prepared_images(instance_id)
    if refs:
        subprocess.run(["docker", "image", "rm", *refs], capture_output=True, check=False)


def image_ids() -> set[str]:
    out = subprocess.run(
        ["docker", "images", "-q", "--no-trunc"], capture_output=True, text=True, check=True
    )
    return set(out.stdout.split())


@pytest.fixture
def harbor_service(settings):
    store = LocalArtifactStore(settings.artifacts_dir)
    executor = HarborExecutor(
        RUNNER,
        settings.work_dir,
        TaskMaterials(settings.cache_dir),
        DockerResources(),
        term_grace=30,
    )
    environment = DockerEnvironment(settings.preparation_dir)
    built = Maestro.build(
        settings,
        executor=executor,
        store=store,
        environment=environment,
        sources={"local": LocalTaskSource(TASKS)},
    )
    migrate.upgrade(built.db)
    built.keys.initialize()
    built.worker.poll_seconds = 0.1
    instance = read_instance_id(built.db)
    environment.bind(instance)
    try:
        import asyncio

        result = asyncio.run(
            built.preparer.import_and_prepare(
                {"source_kind": "local", "namespace": "local", "name": "oracle", "ref": "v1"},
                None,
            )
        )
        assert result["preparation"]["status"] == "succeeded", result
        built.version_id = result["dataset_version_id"]
        yield built
    finally:
        built.db.dispose()
        leftovers = labelled(instance)
        if leftovers:  # never leave resources behind, even when an assertion failed
            asyncio.run(DockerResources().cleanup({"io.maestro.instance_id": instance}))
        remove_prepared(instance)
        assert leftovers == []
        assert prepared_images(instance) == []


def task_ids(api: Api, version_id: str, *keys: str) -> list[str]:
    tasks = api.get(f"/api/v1/dataset-versions/{version_id}/tasks", expect=200).json()["data"]
    return [t["id"] for t in tasks if t["task_key"] in keys]


def submit(api: Api, version_id: str, keys, **body) -> dict:
    payload = {
        "name": "oracle",
        "dataset_version_id": version_id,
        "execution_mode": "oracle",
        "task_selection": {"mode": "explicit", "task_ids": task_ids(api, version_id, *keys)},
        **body,
    }
    headers = {"Idempotency-Key": uuid.uuid4().hex}
    return api.post("/api/v1/runs", json=payload, headers=headers, expect=202).json()["data"]


def wait_for(predicate, timeout=180.0, interval=0.25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not reached")


def test_oracle_run_from_submission_to_artifacts(harbor_service):
    service = harbor_service
    with running(service) as client:
        pat = create_pat(setup_admin(service, client))
        accepted = submit(pat, service.version_id, ["oracle-pass", "oracle-zero"], repetitions=2)
        operation = wait_operation(pat, accepted["operation_id"], timeout=300)
        assert operation["status"] == "succeeded"
        run_id = accepted["run_id"]
        run = pat.get(f"/api/v1/runs/{run_id}", expect=200).json()["data"]
        assert run["state"] == "finished" and run["cleanup_state"] == "complete"
        assert run["result_completeness"] == "complete"
        assert run["snapshot"]["effective"]["execution_mode"] == "oracle"
        trials = pat.get(f"/api/v1/runs/{run_id}/trials", expect=200).json()["data"]
        scores = sorted((t["task_key"], t["result"]["score"]) for t in trials)
        assert scores == [
            ("oracle-pass", 1.0),
            ("oracle-pass", 1.0),
            ("oracle-zero", 0.0),  # a real zero from the verifier, not a missing score
            ("oracle-zero", 0.0),
        ]
        for trial in trials:
            (attempt,) = trial["attempts"]
            steps = [s["step"] for s in attempt["steps"]]
            assert steps == ["starting", "environment", "agent", "collecting", "verifying"]
            assert attempt["executor_ref"]["runner_id"].startswith("harbor-0.24.0/")
        artifacts = pat.get(f"/api/v1/runs/{run_id}/artifacts", expect=200).json()["data"]
        reward = next(
            a
            for a in artifacts
            if a["relative_path"] == "verifier/reward.txt" and a["trial_id"] == trials[0]["id"]
        )
        body = pat.get(f"/api/v1/artifacts/{reward['id']}/download", expect=200)
        assert body.text.strip() == "1"
        assert {"agent/oracle.txt", "result.json", "runner/stderr.log"} <= {
            a["relative_path"] for a in artifacts
        }
        assert labelled(service.worker.instance_id) == []


def test_prepared_image_is_used_then_restored_from_its_original(harbor_service, settings):
    """M4 on the real host: first preparation is a reproducible build exported as an
    archive (U-17); Harbor runs the prepared image without building or pulling; after
    eviction a run restores exactly that image by loading the archive."""
    service = harbor_service
    instance = service.worker.instance_id or read_instance_id(service.db)
    with running(service) as client:
        admin = setup_admin(service, client)
        pat = create_pat(admin)
        tasks = {
            x["task_key"]: x
            for x in pat.get(f"/api/v1/dataset-versions/{service.version_id}/tasks").json()["data"]
        }
        task = tasks["oracle-pass"]
        image = next(
            r["digest"]
            for r in task["content"]["resources"]
            if r["resource_kind"] == "environment_image"
        )
        assert len(prepared_images(instance)) == 3
        archives = sorted(p.name for p in settings.preparation_dir.iterdir())
        assert len(archives) == 3 and all(a.endswith(".tar") for a in archives)

        before = image_ids()
        accepted = submit(pat, service.version_id, ["oracle-pass"])
        assert wait_operation(pat, accepted["operation_id"], timeout=300)["status"] == "succeeded"
        assert image_ids() == before  # Harbor neither built nor pulled anything

        preparation = task["local_preparation"]["id"]
        ref = f"maestro-prep/{instance}:{task['spec_digest'][7:]}"

        def restore_and_run():
            op = admin.post(f"/api/v1/admin/preparations/{preparation}/evict", expect=202)
            assert wait_operation(admin, op.json()["data"]["id"])["status"] == "succeeded"
            assert ref not in prepared_images(instance)
            again = submit(pat, service.version_id, ["oracle-pass"])
            assert wait_operation(pat, again["operation_id"], timeout=300)["status"] == "succeeded"
            restored = pat.get(f"/api/v1/preparations/{preparation}").json()["data"]
            assert restored["cache_state"] == "ready" and restored["image_id"] == image
            assert ref in prepared_images(instance)
            with service.db.read() as conn:
                from maestro.db import schema as t

                return (
                    conn.execute(
                        t.operations.select()
                        .where(t.operations.c.kind == "preparation_restore")
                        .order_by(t.operations.c.created_at.desc())
                    )
                    .mappings()
                    .first()
                )

        # The original archive is loaded back (U-17).
        assert restore_and_run()["status"] == "succeeded"
        # Without the original, a deterministic Dockerfile rebuilds to the same image id
        # under the reproducible settings, so the restore is accepted and re-exported.
        archive = settings.preparation_dir / f"{task['spec_digest'][7:]}.tar"
        archive.unlink()
        assert restore_and_run()["status"] == "succeeded"
        assert archive.is_file()
        assert labelled(instance) == []


def test_live_steps_and_logs_then_cancel(harbor_service):
    service = harbor_service
    with running(service) as client:
        pat = create_pat(setup_admin(service, client))
        accepted = submit(pat, service.version_id, ["oracle-slow", "oracle-pass"], concurrency=2)
        run_id = accepted["run_id"]

        def slow_trial():
            trials = pat.get(f"/api/v1/runs/{run_id}/trials", expect=200).json()["data"]
            return next(t for t in trials if t["task_key"] == "oracle-slow")

        slow = wait_for(lambda: (t := slow_trial())["phase"] == "agent" and t)
        assert slow["state"] == "executing"

        def live_log():
            artifacts = pat.get(f"/api/v1/runs/{run_id}/artifacts", expect=200).json()["data"]
            log = next(
                (
                    a
                    for a in artifacts
                    if a["trial_id"] == slow["id"] and a["relative_path"] == "agent/oracle.txt"
                ),
                None,
            )
            text = log and pat.get(f"/api/v1/artifacts/{log['id']}/download").text
            return text if text and "tick 2" in text else None

        assert "tick 1" in wait_for(live_log, timeout=60)
        assert pat.get(f"/api/v1/runs/{run_id}").json()["data"]["heartbeat_at"]
        pat.post(f"/api/v1/runs/{run_id}/cancel", expect=200)
        operation = wait_operation(pat, accepted["operation_id"], timeout=120)
        assert operation["status"] == "cancelled"
        trials = pat.get(f"/api/v1/runs/{run_id}/trials", expect=200).json()["data"]
        states = {t["task_key"]: (t["state"], t["reason_code"]) for t in trials}
        assert states == {
            "oracle-slow": ("cancelled", "USER_CANCELLED"),
            "oracle-pass": ("scored", None),
        }
        run = pat.get(f"/api/v1/runs/{run_id}", expect=200).json()["data"]
        assert run["cleanup_state"] == "complete"
        assert labelled(service.worker.instance_id) == []


def test_killed_runner_ends_trials_and_leaves_no_containers(harbor_service):
    service = harbor_service
    with running(service) as client:
        pat = create_pat(setup_admin(service, client))
        accepted = submit(pat, service.version_id, ["oracle-slow"])
        run_id = accepted["run_id"]
        wait_for(
            lambda: any(
                t["phase"] == "agent"
                for t in pat.get(f"/api/v1/runs/{run_id}/trials").json()["data"]
            )
        )
        assert labelled(service.worker.instance_id)  # the trial container is running
        with service.db.read() as conn:
            from maestro.db import schema as t

            runner = (
                conn.execute(t.runs.select().where(t.runs.c.id == run_id))
                .mappings()
                .one()["runner_json"]
            )
        os.killpg(runner["pgid"], signal.SIGKILL)
        wait_operation(pat, accepted["operation_id"], timeout=120)
        (trial,) = pat.get(f"/api/v1/runs/{run_id}/trials", expect=200).json()["data"]
        assert (trial["state"], trial["reason_code"]) == ("execution_error", "RUNNER_EXITED")
        run = pat.get(f"/api/v1/runs/{run_id}", expect=200).json()["data"]
        assert run["cleanup_state"] == "complete"
        assert labelled(service.worker.instance_id) == []


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_service_killed_mid_run_is_reconciled_on_restart(tmp_path):
    """The real failure: ``maestro serve`` dies with SIGKILL while a trial executes."""
    port = _free_port()
    config = tmp_path / "config.toml"
    config.write_text(
        f'data_dir = "{tmp_path}/data"\ncache_dir = "{tmp_path}/cache"\n'
        f'master_key_dir = "{tmp_path}/keys"\nlisten_port = {port}\ncookie_secure = false\n'
        f'runner_python = "{RUNNER}"\n'
    )
    cli = [sys.executable, "-m", "maestro.cli", "--config", str(config)]
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    env["HOME"] = str(tmp_path / "home")
    init = subprocess.run([*cli, "init"], env=env, capture_output=True, text=True, check=True)
    setup_token = init.stdout.strip().splitlines()[-1]
    subprocess.run([*cli, "dev-local-dataset", "oracle", str(TASKS)], env=env, check=True)
    base = f"http://127.0.0.1:{port}"

    def serve():
        with open(tmp_path / "serve.log", "ab") as logs:
            proc = subprocess.Popen(
                [*cli, "serve"], env=env, stdout=logs, stderr=logs, start_new_session=True
            )
        wait_for(lambda: _ready(base), timeout=30)
        return proc

    def instance_id():
        with sqlite3.connect(tmp_path / "data/app.db") as db:
            return db.execute("select instance_id from instance").fetchone()[0]

    first = serve()
    try:
        web = httpx.Client(base_url=base)
        csrf = web.post(
            "/api/v1/setup",
            json={"setup_token": setup_token, "username": "admin", "password": "x" * 16},
        ).json()["data"]["csrf_token"]
        token = web.post(
            "/api/v1/me/pats",
            json={"name": "agent", "scope": "experiment"},
            headers={"X-CSRF-Token": csrf},
        ).json()["data"]["token"]
        pat = Api(httpx.Client(base_url=base), token=token)
        version = pat.get("/api/v1/datasets").json()["data"][0]["versions"][0]["id"]
        accepted = submit(pat, version, ["oracle-slow", "oracle-pass"], concurrency=2)
        run_id = accepted["run_id"]

        def mid_run():
            trials = pat.get(f"/api/v1/runs/{run_id}/trials").json()["data"]
            phases = {t["task_key"]: (t["state"], t["phase"]) for t in trials}
            # One result confirmed, one trial still executing its agent step.
            return phases == {
                "oracle-pass": ("scored", None),
                "oracle-slow": ("executing", "agent"),
            }

        wait_for(mid_run)
        instance = instance_id()
        assert labelled(instance)
        os.killpg(first.pid, signal.SIGKILL)  # the service dies; the Runner has its own group
        first.wait(10)
        # The orphaned Runner stops itself and Harbor removes its containers.
        wait_for(lambda: not labelled(instance), timeout=60)
        second = serve()
        try:
            run = wait_for(
                lambda: (
                    (r := pat.get(f"/api/v1/runs/{run_id}").json()["data"])["state"]
                    == "interrupted"
                    and r["cleanup_state"] == "complete"
                    and r
                )
            )
            assert run["stop_reason"] == "SERVICE_RESTARTED"
            trials = pat.get(f"/api/v1/runs/{run_id}/trials").json()["data"]
            states = {t["task_key"]: (t["state"], t["reason_code"]) for t in trials}
            assert states["oracle-slow"] == ("interrupted", "SERVICE_RESTARTED")
            assert states["oracle-pass"][0] == "scored"
            assert labelled(instance) == []
            runners = subprocess.run(
                ["pgrep", "-f", "maestro_runner"], capture_output=True, text=True, check=False
            ).stdout.split()
            for pid in runners:
                cwd = Path(f"/proc/{pid}/cwd")
                assert not (cwd.exists() and str(cwd.resolve()).startswith(str(tmp_path)))
        finally:
            os.killpg(second.pid, signal.SIGTERM)
            second.wait(30)
    finally:
        if first.poll() is None:
            os.killpg(first.pid, signal.SIGKILL)
        if (tmp_path / "data/app.db").exists():
            remove_prepared(instance_id())


def _ready(base: str) -> bool:
    try:
        return httpx.get(f"{base}/health/ready", timeout=2).json().get("accepting_runs") is True
    except httpx.HTTPError:
        return False
