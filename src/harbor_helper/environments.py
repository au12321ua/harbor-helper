"""Harbor Docker lifecycle with cache-preserving stop; no build/start replacement."""

import asyncio
import json
import re
import time

from harbor.environments.docker.docker import (
    DockerEnvironment,
    _sanitize_docker_compose_project_name,
)

from harbor_helper.storage import read_json, write_json


def anonymous_volumes(container):
    """Docker-generated anonymous mounts only; explicit named/external sources excluded."""
    host = container.get("HostConfig") or {}
    explicit = {m.get("Source") for m in host.get("Mounts") or [] if m.get("Source")}
    explicit.update(b.split(":", 1)[0] for b in host.get("Binds") or [] if ":" in b)
    return [
        m["Name"]
        for m in container.get("Mounts") or []
        if m.get("Type") == "volume"
        and re.fullmatch(r"[0-9a-f]{64}", m.get("Name", ""))
        and m["Name"] not in explicit
    ]


def owned_anonymous_volumes(containers, inspect):
    """Exclude volumes inherited through volumes_from, including external containers."""
    owned = set()
    for container in containers:
        inherited = set()
        for source in (container.get("HostConfig") or {}).get("VolumesFrom") or []:
            reference = source.rsplit(":", 1)[0] if source.endswith((":ro", ":rw")) else source
            for origin in inspect(reference):
                inherited.update(m.get("Name") for m in origin.get("Mounts") or [])
        owned.update(set(anonymous_volumes(container)) - inherited)
    return owned


class NativeDockerEnvironment(DockerEnvironment):
    def __init__(self, *args, **kwargs):
        if kwargs.get("keep_containers"):
            raise ValueError("Team native execution cannot keep containers")
        super().__init__(*args, **kwargs)
        if self._keep_containers:
            raise ValueError("Team native execution cannot keep containers")

    async def _observe(self):
        project = _sanitize_docker_compose_project_name(self.session_id)
        target = self.trial_paths.trial_dir / f"helper-environment-{project}.json"
        try:
            from harbor_helper.worker import run_command

            ids = await asyncio.to_thread(
                run_command,
                ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"],
            )
            containers = (
                json.loads(
                    await asyncio.to_thread(run_command, ["docker", "inspect", *ids.split()])
                )
                if ids
                else []
            )
            previous = read_json(target) if target.exists() else {}
            volumes = set(previous.get("owned_anonymous_volumes", []))
            volumes.update(
                await asyncio.to_thread(
                    owned_anonymous_volumes,
                    containers,
                    lambda reference: json.loads(run_command(["docker", "inspect", reference])),
                )
            )
            write_json(
                target,
                {
                    "project": project,
                    "observed_at": time.time(),
                    "owned_anonymous_volumes": sorted(volumes),
                    "images": [
                        {
                            "service": (c.get("Config", {}).get("Labels") or {}).get(
                                "com.docker.compose.service"
                            ),
                            "image_id": c.get("Image", "unknown"),
                            "reference": c.get("Config", {}).get("Image", "unknown"),
                        }
                        for c in containers
                    ]
                    or previous.get("images", "unknown"),
                },
            )
        except Exception:  # noqa: BLE001 - observations do not turn execution success into failure.
            self.logger.warning("Helper environment observation unavailable")

    async def _run_docker_compose_command(self, command, **kwargs):
        if command == ["down", "--rmi", "local", "--volumes", "--remove-orphans"]:
            await self._observe()  # Persist ownership before containers disappear.
            command = ["down", "--volumes", "--remove-orphans"]
        phase = command[0] if command else "unknown"
        if phase not in {"build", "pull", "up", "down"}:
            return await super()._run_docker_compose_command(command, **kwargs)
        project = _sanitize_docker_compose_project_name(self.session_id)
        target = self.trial_paths.trial_dir / f"helper-phases-{project}.json"
        started = time.monotonic()
        entry = {"phase": phase, "started_at": time.time(), "status": "running"}
        try:
            entries = read_json(target) if target.exists() else []
        except (ValueError, OSError):
            entries = []
        if not isinstance(entries, list):
            entries = []
        entries.append(entry)

        def persist():
            try:
                write_json(target, entries)
            except OSError:
                self.logger.warning("Helper Compose phase observation unavailable")

        persist()
        try:
            result = await super()._run_docker_compose_command(command, **kwargs)
            entry["status"] = "completed"
            if phase == "up":
                await self._observe()
            if phase in {"build", "up"}:
                try:
                    with (self.trial_paths.trial_dir / f"helper-compose-{project}.log").open(
                        "a"
                    ) as log:
                        log.write(f"{phase} seconds={time.monotonic() - started:.6f}\n")
                        log.write(result.stdout or "")
                        log.write("\n")
                except OSError:
                    self.logger.warning("Helper Compose timing/output observation unavailable")
            return result
        except asyncio.CancelledError:
            entry["status"] = "interrupted"
            raise
        except Exception:
            entry["status"] = "failed"
            raise
        finally:
            entry.update(seconds=time.monotonic() - started, finished_at=time.time())
            persist()
