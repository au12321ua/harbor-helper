"""Resources execution responsibility."""

import json
import os
import signal
import time
from pathlib import Path

from harbor_helper.execution.processes import process_birth, run_command
from harbor_helper.persistence.files import read_json, write_json


def cleanup(path):
    """Only exact native Compose projects recorded before starting any Trial."""
    from harbor_helper.execution.agent_tools import cleanup_staging

    cleanup_staging(path, process_birth)
    projects_file = path / "projects.json"
    if not projects_file.exists():
        write_json(path / "cleanup.json", {"confirmed": True, "projects": [], "time": time.time()})
        return  # Worker never passed Job initialization; no environment was started.
    projects = read_json(projects_file)
    from harbor_helper.execution.environments import owned_anonymous_volumes

    owned = set()
    for evidence in path.glob("harbor/*/*/helper-environment-*.json"):
        observation = read_json(evidence)
        if observation.get("project") in projects:
            owned.update(observation.get("owned_anonymous_volumes", []))
    for project in projects:
        label = f"label=com.docker.compose.project={project}"
        ids = run_command(["docker", "ps", "-aq", "--filter", label]).split()
        if ids:
            containers = json.loads(run_command(["docker", "inspect", *ids]))
            owned.update(
                owned_anonymous_volumes(
                    containers,
                    lambda reference: json.loads(run_command(["docker", "inspect", reference])),
                )
            )
            # Persist before removal, so retry/recovery can confirm anonymous mounts too.
            stamp = path / "owned-anonymous-volumes.json"
            owned.update(read_json(stamp) if stamp.exists() else [])
            write_json(stamp, sorted(owned))
            run_command(["docker", "rm", "-f", *ids])
        for kind in ("network", "volume"):
            ids = run_command(["docker", kind, "ls", "-q", "--filter", label]).split()
            if ids:
                run_command(["docker", kind, "rm", *ids])
            if run_command(["docker", kind, "ls", "-q", "--filter", label]):
                raise RuntimeError(f"Owned {kind} resources remain in project {project}")
        if run_command(["docker", "ps", "-aq", "--filter", label]):
            raise RuntimeError(f"Containers remain in owned project {project}")
    stamp = path / "owned-anonymous-volumes.json"
    owned.update(read_json(stamp) if stamp.exists() else [])
    for volume in sorted(owned):
        # Do not delete a mount now used by any other container/project.
        if run_command(["docker", "ps", "-aq", "--filter", f"volume={volume}"]):
            raise RuntimeError("Owned anonymous volume still attached; cleanup unconfirmed")
        if volume in run_command(["docker", "volume", "ls", "-q"]).split():
            run_command(["docker", "volume", "rm", volume])
        if volume in run_command(["docker", "volume", "ls", "-q"]).split():
            raise RuntimeError("Owned anonymous volume remains")
    write_json(
        path / "cleanup.json",
        {
            "confirmed": True,
            "projects": projects,
            "anonymous_volumes": sorted(owned),
            "time": time.time(),
        },
    )


def stop_group(row):
    pid = row["pid"]
    if not pid:
        return
    actual = process_birth(pid)
    if actual and actual != row["birth"]:
        raise RuntimeError("PID identity changed; refusing to kill unrelated process")
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    time.sleep(1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    # Zombie group members have stopped; non-zombie descendants must be gone.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        members = []
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
                if fields[0] != "Z" and int(fields[2]) == pid:
                    members.append(proc.name)
            except (OSError, IndexError, ValueError):
                continue
        if not members:
            return
        time.sleep(0.1)
    raise RuntimeError("Worker descendants still active; capacity retained")
