"""Measure native Harbor setup/install in a fixed CAD task; never execute a model."""

import argparse
import asyncio
import os
import subprocess
import time
import uuid
from pathlib import Path

from harbor.environments.docker.docker import _sanitize_docker_compose_project_name
from harbor.models.trial.config import TrialConfig
from harbor.trial.trial import Trial

from harbor_helper.agents import HelperOpenCode
from harbor_helper.runs import safe_environment
from harbor_helper.storage import read_json, tree_digest, write_json
from harbor_helper.worker import cleanup


async def verify(args):
    if os.environ.get("VLLM_API_KEY"):
        raise ValueError("Use a credential-free process for this install-only probe")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    task = args.task.resolve()
    before = tree_digest(task)
    provenance = read_json(args.provenance)
    image_id = provenance["image_id"]
    alias = "harbor-helper/startup-image:" + image_id.removeprefix("sha256:")
    await asyncio.to_thread(subprocess.run, ["docker", "tag", image_id, alias], check=True)
    name = "hh-opencode-startup-" + uuid.uuid4().hex[:12]
    config = TrialConfig.model_validate(
        {
            "task": {"path": task},
            "trial_name": name,
            "trials_dir": output / "trials",
            "install_only": True,
            "agent": {
                "import_path": "harbor_helper.agents:HelperOpenCode",
                "model_name": "setup-only/unused",
                "kwargs": {"version": provenance["opencode_version"]},
            },
            "environment": {
                "type": "docker",
                "delete": True,
                "override_cpus": 2,
                "override_memory_mb": 4096,
                "env": {"CAD_BENCH_AGENT_IMAGE": alias, "CAD_BENCH_VERIFIER_IMAGE": alias},
            },
        }
    )
    write_json(output / "probe-config.json", config.model_dump(mode="json"))
    project = _sanitize_docker_compose_project_name(name + "__env")
    write_json(output / "projects.json", [project])
    dependencies, execute, run = (
        HelperOpenCode.ensure_system_dependencies,
        HelperOpenCode.exec_as_agent,
        HelperOpenCode.run,
    )
    calls = {"dependency_install": 0, "agent_exec_commands": [], "agent_run": 0}

    async def observe_dependencies(self, environment, packages):
        calls["dependency_install"] += 1
        return await dependencies(self, environment, packages)

    async def observe_execute(self, environment, command, **kwargs):
        calls["agent_exec_commands"].append(command)
        return await execute(self, environment, command=command, **kwargs)

    async def forbidden_run(*args, **kwargs):
        calls["agent_run"] += 1
        raise RuntimeError("Install-only probe must never invoke agent.run")

    HelperOpenCode.ensure_system_dependencies = observe_dependencies
    HelperOpenCode.exec_as_agent = observe_execute
    HelperOpenCode.run = forbidden_run
    started = time.monotonic()
    try:
        trial = await Trial.create(config)
        result = await trial.run()
    finally:
        HelperOpenCode.ensure_system_dependencies = dependencies
        HelperOpenCode.exec_as_agent = execute
        HelperOpenCode.run = run
        await asyncio.to_thread(cleanup, output)
    total = time.monotonic() - started
    decision = read_json(output / "trials" / name / "agent" / "install-decision.json")
    resources = {}
    for kind, argv in {
        "containers": ["docker", "ps", "-aq"],
        "networks": ["docker", "network", "ls", "-q"],
        "volumes": ["docker", "volume", "ls", "-q"],
    }.items():
        query = await asyncio.to_thread(
            subprocess.run,
            [*argv, "--filter", "label=com.docker.compose.project=" + project],
            check=True,
            capture_output=True,
            text=True,
        )
        resources[kind] = query.stdout.split()

    def duration(timing):
        return (timing.finished_at - timing.started_at).total_seconds() if timing else None

    after = tree_digest(task)
    value = {
        "trial": name,
        "task": str(task),
        "task_digest_before": before,
        "task_digest_after": after,
        "task_unchanged": before == after,
        "image_id": image_id,
        "runtime_alias": alias,
        "base_image_id": provenance["base_image_id"],
        "environment_setup_seconds": duration(result.environment_setup),
        "agent_setup_seconds": duration(result.agent_setup),
        "total_seconds_including_cleanup": total,
        "install_decision": decision,
        "observed_calls": calls,
        "exception_type": result.exception_info.exception_type if result.exception_info else None,
        "agent_execution_present": result.agent_execution is not None,
        "verifier_result_present": result.verifier_result is not None,
        "residual_resources": resources,
        "credentials_used": False,
        "model_requests": 0 if calls["agent_run"] == 0 else "guard_invoked",
    }
    write_json(output / "evidence.json", value)
    assert before == after and not result.exception_info
    assert decision["reused"] and decision["actual_version"] == provenance["opencode_version"]
    assert calls["dependency_install"] == 0
    assert not any("apt-get" in c or "npm i" in c for c in calls["agent_exec_commands"])
    assert calls["agent_run"] == 0 and result.agent_execution is None
    assert result.verifier_result is None and not any(resources.values())
    print(output / "evidence.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if os.environ.get("VLLM_API_KEY"):
        raise ValueError("Use a credential-free process for this install-only probe")
    allowed = safe_environment()
    os.environ.clear()
    os.environ.update(allowed)
    asyncio.run(verify(args))


if __name__ == "__main__":
    main()
