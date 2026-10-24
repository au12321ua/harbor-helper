"""Regressions for the findings of the independent M5 review (2026-10-24)."""

import gzip
import io
import json
import resource
import shutil
import tarfile
import uuid
import zipfile

import pytest
from support import invite_member, running, setup_admin, submit, wait_operation
from test_attachments import manifest, package, publish, tar_package
from test_batches import batch_body, post_batch
from test_configuration import error
from test_reruns import rerun

from maestro.core.errors import MaestroError
from maestro.execution.agents import endpoint_problem
from maestro.execution.attachments import AttachmentStore, PackageError


class _Low:
    def refuse_if_low(self, work="runs"):
        raise MaestroError("STORAGE_LOW", "low", 503)


# --- idempotency: a retry finds its answer even after what it relied on changed ----------


def test_a_retry_replays_after_the_plan_changed_or_was_archived(service, version_id):
    with running(service, run_worker=False) as client:
        admin = setup_admin(service, client)
        template = {"dataset_version_id": version_id, "execution_mode": "oracle"}
        plan = admin.post(
            "/api/v1/plans", json={"name": "p", "template": template}, expect=201
        ).json()["data"]
        body = {"name": "from plan", "plan_id": plan["id"]}
        key = uuid.uuid4().hex
        first = admin.post("/api/v1/runs", json=body, headers={"Idempotency-Key": key})
        assert first.status_code == 202, first.text
        admin.put(
            f"/api/v1/plans/{plan['id']}",
            json={"expected_revision": 1, "template": {**template, "repetitions": 2}},
            expect=200,
        )
        again = admin.post("/api/v1/runs", json=body, headers={"Idempotency-Key": key})
        assert again.status_code == 202, again.text
        assert again.json()["data"]["run_id"] == first.json()["data"]["run_id"]
        admin.post(f"/api/v1/plans/{plan['id']}/archive", json={"archived": True}, expect=200)
        again = admin.post("/api/v1/runs", json=body, headers={"Idempotency-Key": key})
        assert again.json()["data"]["run_id"] == first.json()["data"]["run_id"]


def test_batch_and_rerun_retries_replay_after_limits_and_sources_changed(
    service, version_id, executor
):
    with running(service) as client:
        admin = setup_admin(service, client)
        oracle = {"execution_mode": "oracle"}
        body = batch_body(version_id, oracle, oracle)
        accepted = post_batch(admin, body, key="batch-key").json()["data"]
        wait_operation(admin, accepted["operation_id"])
        admin.put(
            "/api/v1/admin/team-policy",
            json={"expected_revision": 0, "values": {"batch_max_runs": 1}},
            expect=200,
        )
        again = post_batch(admin, body, key="batch-key")
        assert again.status_code == 202, again.text
        assert again.json()["data"]["batch_id"] == accepted["batch_id"]

        source = accepted["runs"][0]["run_id"]
        first = rerun(admin, source, expect=202, key="rerun-key")
        admin.delete(f"/api/v1/runs/{source}", expect=200)
        again = rerun(admin, source, expect=202, key="rerun-key")
        assert again.json()["data"]["run_id"] == first.json()["data"]["run_id"]


def test_fields_beside_a_resolution_id_are_refused(service, version_id):
    with running(service, run_worker=False) as client:
        admin = setup_admin(service, client)
        found = admin.post(
            "/api/v1/config-resolutions",
            json={"dataset_version_id": version_id, "execution_mode": "oracle"},
            expect=201,
        ).json()["data"]
        response = admin.post(
            "/api/v1/runs",
            json={"name": "x", "resolution_id": found["resolution_id"], "repetitions": 3},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert error(response) == (422, "CONFIG_VALIDATION_FAILED")
        assert response.json()["error"]["field_errors"][0]["path"] == "/repetitions"


# --- reruns and batches --------------------------------------------------------------------


def test_a_rerun_respects_the_storage_watermark(service, version_id):
    with running(service, run_worker=False) as client:
        admin = setup_admin(service, client)
        source = submit(admin, version_id).json()["data"]["run_id"]
        admin.post(f"/api/v1/runs/{source}/cancel", expect=200)
        service.runs.disk = _Low()
        assert error(rerun(admin, source)) == (503, "STORAGE_LOW")


def test_a_batch_shows_its_members_deletion_and_ignores_cancel_once_ended(
    service, version_id, executor
):
    with running(service) as client:
        admin = setup_admin(service, client)
        oracle = {"execution_mode": "oracle"}
        accepted = post_batch(admin, batch_body(version_id, oracle, oracle)).json()["data"]
        wait_operation(admin, accepted["operation_id"])
        batch_url = f"/api/v1/run-batches/{accepted['batch_id']}"

        cancelled = admin.post(f"{batch_url}/cancel", expect=200).json()["data"]
        assert cancelled["stop_requested"] is False
        assert cancelled["status"] == "succeeded"

        member = accepted["runs"][0]["run_id"]
        admin.delete(f"/api/v1/runs/{member}", expect=200)
        batch = admin.get(batch_url, expect=200).json()["data"]
        shown = {r["id"]: r for r in batch["runs"]}[member]
        assert shown["deletion"]["state"] == "recycled"
        assert "rerun" not in shown["allowed_actions"]
        assert batch["progress"]["deleted_runs"] == 1


# --- configuration ---------------------------------------------------------------------


def test_plan_templates_check_task_ids_and_agent_only_fields(service):
    with running(service, run_worker=False) as client:
        admin = setup_admin(service, client)
        member = invite_member(service, admin, "member")
        response = member.post(
            "/api/v1/plans",
            json={
                "name": "p",
                "template": {"task_selection": {"mode": "all_eligible", "task_ids": 5}},
            },
        )
        assert error(response) == (422, "CONFIG_VALIDATION_FAILED")
        plan = member.post(
            "/api/v1/plans",
            json={"name": "q", "template": {"harness_params": {"max_turns": 5}}},
            expect=201,
        ).json()["data"]
        assert plan["template"] == {"harness_params": {"max_turns": 5}}
        plan = member.post(
            "/api/v1/plans", json={"name": "r", "template": {"model_revision": 3}}, expect=201
        ).json()["data"]
        assert plan["template"] == {"model_revision": 3}


def test_an_endpoint_with_a_key_in_its_path_is_refused():
    assert endpoint_problem("https://gw.example.test/sk-proj-ABCDEFGHIJKLMNOPQRSTUV/v1")
    assert endpoint_problem("https://gw.example.test/v1;key=x")
    assert endpoint_problem("https://gw.example.test/v1") is None


# --- attachments -----------------------------------------------------------------------------


def _manifest_tar(**fields) -> bytes:
    return tar_package({"manifest.json": json.dumps({**manifest(), **fields}).encode()})


def test_a_long_name_header_is_refused_before_it_is_read(tmp_path):
    size = 64 * 1024 * 1024
    info = tarfile.TarInfo("././@LongLink")
    info.type = tarfile.GNUTYPE_LONGNAME
    info.size = size
    path = tmp_path / "bomb.tar.gz"
    with gzip.open(path, "wb", compresslevel=1) as sink:
        sink.write(info.tobuf(format=tarfile.GNU_FORMAT))
        for _ in range(size >> 20):
            sink.write(b"a" * (1 << 20))
        sink.write(b"\0" * 1024)
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    with pytest.raises(PackageError):
        AttachmentStore(tmp_path / "data").unpack(path, max_files=20, max_bytes=10_000)
    assert resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before < 32 * 1024


def test_directories_and_refused_entries_count_toward_the_file_limit(tmp_path):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as archive:
        for index in range(100):
            info = tarfile.TarInfo(f"d{index}")
            info.type = tarfile.DIRTYPE
            archive.addfile(info)
    with pytest.raises(PackageError, match="too many entries"):
        AttachmentStore(tmp_path / "a").unpack(raw.getvalue(), max_files=20, max_bytes=10_000)

    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        for index in range(100):
            archive.writestr(f"d{index}/", b"")
    with pytest.raises(PackageError, match="too many entries"):
        AttachmentStore(tmp_path / "b").unpack(raw.getvalue(), max_files=20, max_bytes=10_000)


def test_odd_manifests_are_invalid_not_internal_errors(service):
    with running(service, run_worker=False) as client:
        admin = setup_admin(service, client)
        for data in (
            _manifest_tar(effects=[{}]),
            _manifest_tar(provides={"tools": [[1]]}),
            tar_package({"manifest.json": b'{"x":' + b"[" * 30000 + b"]" * 30000 + b"}"}),
        ):
            assert error(publish(admin, data)) == (422, "ATTACHMENT_INVALID")


def test_publishing_again_repairs_missing_files_and_refuses_a_recycled_version(service):
    with running(service, run_worker=False) as client:
        admin = setup_admin(service, client)
        created = publish(admin, package(), expect=201).json()["data"]
        stored = service.settings.data_dir / "attachments" / created["content_digest"].split(":")[1]
        shutil.rmtree(stored)
        publish(admin, package(), expect=200)
        assert stored.is_dir()

        admin.delete(f"/api/v1/attachments/{created['id']}", expect=200)
        assert error(publish(admin, package())) == (409, "ATTACHMENT_DELETED")


def test_low_disk_refuses_an_upload_before_it_is_stored(service):
    with running(service, run_worker=False) as client:
        admin = setup_admin(service, client)
        service.disk = _Low()
        assert error(publish(admin, package())) == (503, "STORAGE_LOW")
