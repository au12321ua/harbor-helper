"""Real Docker spawn/forwarding probe with a synthetic credential; no model calls."""

import argparse
import asyncio
import json
import os
import shlex
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

from harbor.environments.docker.docker import DockerEnvironment

from harbor_helper.config import DEFAULT
from harbor_helper.credentials import install_docker_credential_forwarding


async def verify(output):
    marker = "synthetic-helper-credential-spawn-probe"
    os.environ["VLLM_API_KEY"] = marker
    project = "hh-credential-probe-" + uuid.uuid4().hex[:8]
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    compose = output / "compose.json"
    compose.write_text(
        json.dumps(
            {
                "services": {
                    "probe": {
                        "image": DEFAULT["runtime_image"],
                        "command": ["sleep", "120"],
                    }
                }
            }
        )
    )
    records = []
    original_spawn = asyncio.create_subprocess_exec

    async def spawn(*argv, **kwargs):
        records.append(
            {
                "value_in_argv": any(marker in arg for arg in argv),
                "name_only_in_argv": "VLLM_API_KEY" in argv,
                "env_value_correct": kwargs.get("env", {}).get("VLLM_API_KEY") == marker,
            }
        )
        return await original_spawn(*argv, **kwargs)

    class ProbeEnvironment:
        session_id = project
        environment_dir = output
        _docker_compose_paths = (compose,)
        _run_docker_compose_command = DockerEnvironment._run_docker_compose_command
        _collect_buffered_output = staticmethod(DockerEnvironment._collect_buffered_output)

        @staticmethod
        def runtime():
            return SimpleNamespace(
                compose=["docker", "compose"], supports_compose_project_directory=False
            )

        def _compose_env_vars(self, **kwargs):
            return dict(os.environ)

        _output_callback = lambda self: None

    install_docker_credential_forwarding()
    # Bind after installing the boundary wrapper.
    ProbeEnvironment._run_docker_compose_command = DockerEnvironment._run_docker_compose_command
    env = ProbeEnvironment()
    asyncio.create_subprocess_exec = spawn
    try:
        await env._run_docker_compose_command(["up", "-d"], timeout_sec=60)
        python = (
            "import os,json; print(json.dumps({'received':bool(os.environ.get('VLLM_API_KEY'))}))"
        )
        result = await DockerEnvironment._compose_exec(
            env,
            "python -c " + shlex.quote(python),
            service="probe",
            cwd=None,
            env={"VLLM_API_KEY": marker},
            timeout_sec=30,
            user=None,
        )
        received = json.loads(result.stdout)["received"]
    finally:
        await env._run_docker_compose_command(["down", "-v", "--remove-orphans"], timeout_sec=30)
        asyncio.create_subprocess_exec = original_spawn
        os.environ.pop("VLLM_API_KEY", None)
    residual = {}
    for kind, command in (
        ("containers", ["docker", "ps", "-aq"]),
        ("networks", ["docker", "network", "ls", "-q"]),
        ("volumes", ["docker", "volume", "ls", "-q"]),
    ):
        result = await asyncio.to_thread(
            subprocess.run,
            [*command, "--filter", f"label=com.docker.compose.project={project}"],
            check=True,
            capture_output=True,
            text=True,
        )
        raw = result.stdout
        residual[kind] = bool(raw.strip())
    value = {
        "real_credential_used": False,
        "model_requests": 0,
        "spawn": records,
        "received_in_container": received,
        "residual_resources": residual,
    }
    value["passed"] = (
        received
        and not any(residual.values())
        and all(not r["value_in_argv"] and r["env_value_correct"] for r in records)
        and any(r["name_only_in_argv"] for r in records)
    )
    (output / "evidence.json").write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps(value))
    return 0 if value["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    raise SystemExit(asyncio.run(verify(args.output.resolve())))
