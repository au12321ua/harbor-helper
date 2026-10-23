"""Shared cache restore, failures and races: E2E-DS-04, DS-05, F-05, F-21 to F-24."""

import asyncio
import shutil
import time

from sqlalchemy import insert, select, update
from support import create_pat, invite_member, running, setup_admin, submit, wait_operation
from test_datasets import evict, import_and_prepare, import_dataset, tasks_by_key, wait_run

from maestro.db import schema as t
from maestro.services import operations


def until(condition, timeout=10.0, message="condition"):
    deadline = time.monotonic() + timeout
    while True:
        value = condition()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {message}")
        time.sleep(0.02)


def on_loop(service, callback):
    service.worker._loop.call_soon_threadsafe(callback)


def solo(service, source, client, name="solo"):
    source.add("demo", name, "v1", [name])
    admin = setup_admin(service, client)
    version_id, prepared = import_and_prepare(admin, name=name)
    assert prepared["status"] == "succeeded"
    (task,) = tasks_by_key(admin, version_id).values()
    return admin, version_id, task


def trial_attempts(service, run_id):
    with service.db.read() as conn:
        return conn.execute(
            select(t.execution_attempts.c.attempt_index, t.execution_attempts.c.error_json)
            .join(t.trials, t.trials.c.id == t.execution_attempts.c.trial_id)
            .where(t.trials.c.run_id == run_id)
            .order_by(t.execution_attempts.c.attempt_index)
        ).all()


def test_ds04_cold_cache_is_restored_once_for_concurrent_runs(service, source, environment):
    with running(service) as client:
        admin, version_id, task = solo(service, source, client)
        admission = task["admission"]
        evict(admin, task)
        member = invite_member(service, admin, "member")
        pat = create_pat(member, scope="experiment", run_limit=5)
        environment.gate = asyncio.Event()
        environment.started.clear()
        web_run = submit(member, version_id).json()["data"]
        sdk_run = submit(pat, version_id).json()["data"]
        preparation = f"/api/v1/preparations/{task['local_preparation']['id']}"

        def both_waiting():
            data = member.get(preparation).json()["data"]
            waiting = [w for w in data["waiters"] if w["state"] == "waiting"]
            return data if len(waiting) == 2 else None

        shared = until(both_waiting, message="two waiters")
        assert shared["cache_state"] == "restoring"
        assert {w["run_id"] for w in shared["waiters"]} == {web_run["run_id"], sdk_run["run_id"]}
        operation = member.get(f"/api/v1/operations/{shared['operation_id']}").json()["data"]
        assert operation["kind"] == "preparation_restore"
        assert operation["allowed_actions"] == ["view"]
        assert environment.restores == ["solo"]  # one restore for both runs
        trials = member.get(f"/api/v1/runs/{web_run['run_id']}/trials").json()["data"]
        assert trials[0]["phase"] == "restoring_cache"

        # Cancelling one waiting run leaves the shared restore to the other.
        member.post(f"/api/v1/runs/{web_run['run_id']}/cancel", expect=200)
        cancelled = wait_run(member, web_run["run_id"])
        assert cancelled["state"] == "cancelled"
        still = member.get(preparation).json()["data"]
        assert still["cache_state"] == "restoring"
        assert {w["run_id"]: w["state"] for w in still["waiters"]} == {
            web_run["run_id"]: "cancelled",
            sdk_run["run_id"]: "waiting",
        }
        on_loop(service, environment.gate.set)
        done = wait_run(pat, sdk_run["run_id"])
        assert done["counts"]["scored"] == 1
        assert environment.loads == ["solo"] and environment.builds == 1  # only the first prep
        restored = wait_operation(member, shared["operation_id"])
        assert restored["status"] == "succeeded" and restored["result"]["waiters"] == 1

        # The original configuration again: warm cache, same admission and config.
        again = submit(pat, version_id).json()["data"]
        assert again["config_digest"] == sdk_run["config_digest"]
        assert wait_run(pat, again["run_id"])["counts"]["scored"] == 1
        assert environment.restores == ["solo"]
        after = tasks_by_key(member, version_id)["solo"]
        assert after["admission"] == admission
        pats = member.get("/api/v1/me/pats").json()["data"]
        assert pats[0]["accepted_runs"] == 2


def test_f22_last_waiter_leaving_ends_the_restore(service, source, environment):
    with running(service) as client:
        admin, version_id, task = solo(service, source, client)
        evict(admin, task)
        environment.gate = asyncio.Event()
        environment.started.clear()
        run = submit(admin, version_id).json()["data"]
        preparation = f"/api/v1/preparations/{task['local_preparation']['id']}"
        restoring = until(
            lambda: (d := admin.get(preparation).json()["data"])["operation_id"] and d,
            message="restore",
        )
        admin.post(f"/api/v1/runs/{run['run_id']}/cancel", expect=200)
        op = wait_operation(admin, restoring["operation_id"])
        assert op["status"] == "cancelled"
        assert admin.get(preparation).json()["data"]["cache_state"] == "stale"
        assert wait_run(admin, run["run_id"])["counts"]["not_started"] == 1
        # A later run starts a new generation that succeeds.
        on_loop(service, environment.gate.set)
        later = submit(admin, version_id).json()["data"]
        assert wait_run(admin, later["run_id"])["counts"]["scored"] == 1
        prep = admin.get(preparation).json()["data"]
        assert prep["cache_state"] == "ready" and prep["generation"] == restoring["generation"] + 1


def test_ds05_transient_restore_failures_are_retried_attempts(service, source, environment):
    """F-05: each failed restore is an attempt; trials and admission do not change."""
    with running(service) as client:
        admin, version_id, task = solo(service, source, client)
        evict(admin, task)
        environment.fail_restore["solo"] = ["transient", "transient"]
        run = submit(admin, version_id).json()["data"]
        done = wait_run(admin, run["run_id"])
        assert done["counts"]["planned"] == 1 and done["counts"]["scored"] == 1
        attempts = trial_attempts(service, run["run_id"])
        assert [a.attempt_index for a in attempts] == [1, 2, 3]
        assert [a.error_json["code"] for a in attempts[:2]] == ["PREPARATION_RESTORE_FAILED"] * 2
        assert attempts[2].error_json is None
        with service.db.read() as conn:
            restores = (
                conn.execute(
                    select(t.operations.c.status).where(
                        t.operations.c.kind == "preparation_restore"
                    )
                )
                .scalars()
                .all()
            )
        # The first preparation, then one Operation per try (no inner retries).
        assert restores == ["succeeded", "failed", "failed", "succeeded"]
        after = tasks_by_key(admin, version_id)["solo"]
        assert after["admission"] == task["admission"] and after["can_submit"]
        assert after["local_preparation"]["last_restore_error"] is None


def test_ds05_auth_failure_points_to_the_credential_not_lost_content(service, source, environment):
    with running(service) as client:
        admin, version_id, task = solo(service, source, client)
        evict(admin, task)
        environment.fail_restore["solo"] = ["auth"]
        run = submit(admin, version_id).json()["data"]
        done = wait_run(admin, run["run_id"])
        assert done["counts"]["errors"] == 1
        (attempt,) = trial_attempts(service, run["run_id"])  # not retried
        assert attempt.error_json["code"] == "PREPARATION_RESTORE_FAILED"
        assert attempt.error_json["detail"]["kind"] == "auth"
        assert attempt.error_json["detail"]["suggested_actions"] == [
            {"type": "check_dataset_credential"}
        ]
        after = tasks_by_key(admin, version_id)["solo"]
        assert after["can_submit"]
        assert {r["availability"] for r in after["content"]["resources"]} == {"available"}
        assert after["local_preparation"]["last_restore_error"]["kind"] == "auth"


def test_ds05_exact_content_gone_blocks_new_runs_with_expected_digest(
    service, source, settings, environment
):
    with running(service) as client:
        admin, version_id, task = solo(service, source, client)
        member = invite_member(service, admin, "member")
        pat = create_pat(member, scope="experiment", run_limit=5)
        accepted = submit(pat, version_id).json()["data"]
        wait_run(pat, accepted["run_id"])
        evict(admin, task)
        # No local copy is left, the upstream no longer offers the digest.
        shutil.rmtree(settings.cache_dir / "tasks" / task["content"]["digest"][7:])
        source.gone.add(task["content"]["digest"])
        run = submit(pat, version_id).json()["data"]
        done = wait_run(pat, run["run_id"])
        assert done["counts"]["errors"] == 1
        trial = pat.get(f"/api/v1/runs/{run['run_id']}/trials").json()["data"][0]
        assert trial["reason_code"] == "RESOURCE_CONTENT_UNAVAILABLE"
        (attempt,) = trial_attempts(service, run["run_id"])
        assert attempt.error_json["detail"]["expected_digest"] == task["content"]["digest"]
        assert attempt.error_json["detail"]["resource_kind"] == "task_content"

        after = tasks_by_key(pat, version_id)["solo"]
        assert after["admission"]["state"] == "admitted"  # never revoked automatically
        (blocker,) = after["blockers"]
        assert blocker["code"] == "RESOURCE_CONTENT_UNAVAILABLE"
        assert blocker["expected_digest"] == task["content"]["digest"]
        refused = submit(pat, version_id)
        assert refused.status_code == 422
        assert refused.json()["error"]["field_errors"][0]["code"] == "RESOURCE_CONTENT_UNAVAILABLE"
        pats = member.get("/api/v1/me/pats").json()["data"]
        assert pats[0]["accepted_runs"] == 2  # refusal before acceptance charged nothing

        # Offered again: re-importing the same version re-verifies and unblocks it.
        source.gone.discard(task["content"]["digest"])
        again = import_dataset(admin, name="solo")
        assert again["result"]["existing"] is True
        assert tasks_by_key(pat, version_id)["solo"]["can_submit"]
        rerun = submit(pat, version_id).json()["data"]
        assert wait_run(pat, rerun["run_id"])["counts"]["scored"] == 1


def test_ds05_rebuild_with_different_digest_is_not_accepted(service, source, environment):
    with running(service) as client:
        admin, version_id, task = solo(service, source, client)
        image = task["content"]["resources"][1]["digest"]
        evict(admin, task)
        environment.nondeterministic.add("solo")
        environment.lose_archive(environment.ref(task["spec_digest"]))
        run = submit(admin, version_id).json()["data"]
        trial = admin.get(f"/api/v1/runs/{run['run_id']}/trials").json()["data"]
        wait_run(admin, run["run_id"])
        trial = admin.get(f"/api/v1/runs/{run['run_id']}/trials").json()["data"][0]
        assert trial["reason_code"] == "RESOURCE_CONTENT_UNAVAILABLE"
        after = tasks_by_key(admin, version_id)["solo"]
        assert after["local_preparation"]["cache_state"] == "stale"  # nothing published
        (blocker,) = after["blockers"]
        assert (blocker["resource_kind"], blocker["expected_digest"]) == (
            "environment_image",
            image,
        )


def test_ds05_local_copy_still_runs_when_upstream_lost_it(service, source, environment):
    with running(service) as client:
        admin, version_id, task = solo(service, source, client)
        evict(admin, task)
        source.gone.add(task["content"]["digest"])
        run = submit(admin, version_id).json()["data"]
        assert wait_run(admin, run["run_id"])["counts"]["scored"] == 1
        assert source.fetches.count(task["content"]["digest"]) == 1  # only the import
        assert tasks_by_key(admin, version_id)["solo"]["can_submit"]


def test_f24_a_superseded_restore_cannot_publish(service, source, environment):
    with running(service) as client:
        admin, version_id, task = solo(service, source, client)
        evict(admin, task)
        environment.gate = asyncio.Event()
        run = submit(admin, version_id).json()["data"]
        preparation = f"/api/v1/preparations/{task['local_preparation']['id']}"
        restoring = until(
            lambda: (d := admin.get(preparation).json()["data"])["operation_id"] and d,
            message="restore",
        )
        with service.db.write() as conn:  # another generation took over the key
            conn.execute(
                update(t.preparations)
                .where(t.preparations.c.id == task["local_preparation"]["id"])
                .values(generation=t.preparations.c.generation + 1)
            )
        on_loop(service, environment.gate.set)
        op = wait_operation(admin, restoring["operation_id"])
        assert op["status"] == "failed" and op["error"]["code"] == "STALE_PREPARATION_LEASE"
        # The waiting run got no answer from it and joined a fresh generation instead.
        assert wait_run(admin, run["run_id"])["counts"]["scored"] == 1
        prep = admin.get(preparation).json()["data"]
        assert prep["cache_state"] == "ready"
        assert prep["generation"] == restoring["generation"] + 2


def test_restart_during_restore_interrupts_it_and_keeps_admission(service, source, environment):
    """F-24: what a killed process left (restoring cache, running Operation, waiter,
    pin) is reconciled on start; admission and its evidence stay."""
    with running(service) as client:
        admin, version_id, task = solo(service, source, client)
        evict(admin, task)
    prep_id = task["local_preparation"]["id"]
    with service.db.write() as conn:
        op_id = operations.create(conn, "preparation_restore", owner_id=None)
        conn.execute(
            update(t.operations).where(t.operations.c.id == op_id).values(status="running")
        )
        conn.execute(
            update(t.preparations)
            .where(t.preparations.c.id == prep_id)
            .values(cache_state="restoring", active_operation_id=op_id)
        )
        conn.execute(
            insert(t.preparation_pins).values(
                id="pin_x",
                preparation_id=prep_id,
                holder_kind="run",
                holder_id="run_x",
                expires_at="2099-01-01T00:00:00Z",
            )
        )
    report = service.worker.start_epoch()
    assert report["preparation"]["interrupted_operations"] == [op_id]
    prep = service.catalog.get_preparation(prep_id)
    assert prep["cache_state"] == "stale" and prep["pins"] == []
    assert prep["last_restore_error"]["message"].startswith("Service restarted")
    assert service.operations.get(op_id)["status"] == "interrupted"
    (after,) = service.catalog.list_tasks(version_id)
    assert after["admission"] == {**task["admission"]} and after["can_submit"]
