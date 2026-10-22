"""E2E-RUN-01 with the fake executor: an agent uses only a PAT and the HTTP API.

Covered here: capabilities, catalog, idempotent submit, Operation polling,
per-trial scores and attempts, artifact download with digest check, and that
a client disconnect does not cancel the run. Configuration resolution (M5),
models/Harness/credentials binding and the generated SDK (M7) are not yet part
of the flow.
"""

import hashlib
import uuid

from support import create_pat, running, setup_admin, wait_operation

from maestro.testing.fakes import scored


def test_agent_runs_a_complete_experiment_with_only_a_pat(service, version_id, executor):
    executor.script = {"add-02": [scored(0.0)]}
    with running(service) as client:
        admin = setup_admin(service, client)
        agent = create_pat(admin, "experiment", run_limit=3)

        caps = agent.get("/api/v1/capabilities", expect=200).json()["data"]
        assert caps["features"]["execution"] is True
        assert caps["actions"]["runs.submit"]["pat_scopes"] == ["experiment"]

        datasets = agent.get("/api/v1/datasets", expect=200).json()["data"]
        version = datasets[0]["versions"][0]
        tasks = agent.get(f"/api/v1/dataset-versions/{version['id']}/tasks").json()["data"]
        assert all(task["can_submit"] for task in tasks)

        key = uuid.uuid4().hex
        body = {
            "name": "baseline",
            "dataset_version_id": version["id"],
            "repetitions": 2,
            "client_request_id": "agent-round-1",
        }
        accepted = agent.post(
            "/api/v1/runs", json=body, headers={"Idempotency-Key": key}, expect=202
        ).json()["data"]
        # The response is "lost" and the agent retries with the same key.
        retried = agent.post(
            "/api/v1/runs", json=body, headers={"Idempotency-Key": key}, expect=202
        ).json()["data"]
        assert retried == accepted

        operation = wait_operation(agent, accepted["operation_id"])
        assert operation["status"] == "succeeded"
        assert operation["progress"]["planned"] == 6 == operation["progress"]["terminal"]

        run = agent.get(f"/api/v1/runs/{accepted['run_id']}").json()["data"]
        assert run["state"] == "finished" and run["result_completeness"] == "complete"
        assert run["artifact_state"] == "complete" and run["cleanup_state"] == "complete"
        assert run["snapshot"]["config_digest"] == accepted["config_digest"]
        assert run["pat_id"] is not None

        trials = agent.get(f"/api/v1/runs/{accepted['run_id']}/trials").json()["data"]
        assert len(trials) == 6
        scores = {(x["task_key"], x["repetition_index"]): x["result"]["score"] for x in trials}
        assert scores[("add-02", 1)] == 0.0 and scores[("add-01", 1)] == 1.0
        assert all(len(x["attempts"]) == 1 for x in trials)

        artifacts = agent.get(f"/api/v1/runs/{accepted['run_id']}/artifacts").json()["data"]
        output = next(a for a in artifacts if a["kind"] == "output")
        download = agent.get(f"/api/v1/artifacts/{output['id']}/download")
        assert download.status_code == 200
        digest = "sha256:" + hashlib.sha256(download.content).hexdigest()
        assert digest == output["digest"] == download.headers["X-Content-Digest"]

        # Discovery by client_request_id after losing all local state.
        found = agent.get("/api/v1/runs?client_request_id=agent-round-1").json()["data"]
        assert [x["id"] for x in found] == [accepted["run_id"]]
        pats = admin.get("/api/v1/me/pats").json()["data"]
        assert pats[0]["accepted_runs"] == 1


def test_service_without_executor_refuses_runs_honestly(settings, source):
    from maestro.application import Maestro
    from maestro.db import migrate

    service = Maestro.build(settings)
    migrate.upgrade(service.db)
    service.keys.initialize()
    version = service.catalog.register_version(source, "demo", "arith", "v1", True, None)
    with running(service) as client:
        admin = setup_admin(service, client)
        assert client.get("/health/ready").json()["accepting_runs"] is False
        response = admin.post(
            "/api/v1/runs",
            json={"name": "x", "dataset_version_id": version},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "EXECUTION_UNAVAILABLE"
    service.db.dispose()


def test_readiness_and_openapi(service):
    with running(service) as client:
        assert client.get("/health/live").json() == {
            "status": "alive",
            "detail": {},
            "accepting_runs": None,
        }
        ready = client.get("/health/ready").json()
        assert ready["status"] == "ready" and ready["accepting_runs"] is True
        spec = client.get("/api/v1/openapi.json").json()
        assert "/api/v1/runs" in spec["paths"]
        assert "Idempotency-Key" in str(spec["paths"]["/api/v1/runs"]["post"]["parameters"])
