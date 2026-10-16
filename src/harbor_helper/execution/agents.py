import asyncio
import re
import shlex
import time
from pathlib import Path

from harbor.agents.installed.opencode import OpenCode, OpenCodeOptions
from harbor.agents.oracle import OracleAgent
from pydantic import Field

from harbor_helper.persistence.files import write_json


class HelperOpenCodeOptions(OpenCodeOptions):
    """Declare helper kwargs at Harbor Job preflight; retain native strict options."""

    helper_tool_cache: str | None = Field(default=None, min_length=1, strict=True)


class BundledOpenCodeOptions(HelperOpenCodeOptions):
    helper_bundle: str | None = Field(default=None, min_length=1, strict=True)


class HelperOpenCode(OpenCode):
    options_model = HelperOpenCodeOptions

    def __init__(self, *args, helper_tool_cache=None, **kwargs):
        self.helper_tool_cache = Path(helper_tool_cache) if helper_tool_cache else None
        self._offline_tool = False
        super().__init__(*args, helper_tool_cache=helper_tool_cache, **kwargs)

    async def exec_as_agent(self, environment, command, **kwargs):  # ty: ignore[invalid-method-override]  # Harbor 0.23 forwarding override; preserve the existing execution signature.
        if self.helper_tool_cache:
            # Public catalog refresh/updater downloads are preparation, not inference.
            kwargs["env"] = {
                **kwargs.get("env", {}),
                "OPENCODE_DISABLE_MODELS_FETCH": "true",
                "OPENCODE_DISABLE_AUTOUPDATE": "true",
            }
        if self._offline_tool:
            command = "export PATH=/installed-agent/helper-tools:$PATH; " + command
        return await super().exec_as_agent(environment, command, **kwargs)

    async def _install_offline(self, environment, decision):
        from harbor_helper.execution.agent_tools import prepare

        target = "/installed-agent/helper-tools"
        probe = await environment.exec(
            command="uname -m; if [ -f /etc/alpine-release ] || ldd --version 2>&1 | grep -qi musl; then echo musl; else echo glibc; fi",
            timeout_sec=30,
        )
        values = (probe.stdout or "").split()
        arches = {"x86_64": "x64", "aarch64": "arm64"}
        if probe.return_code or len(values) != 2 or values[0] not in arches:
            raise RuntimeError("Cannot identify author environment ABI for fixed agent tool")
        platform = "linux-" + arches[values[0]]
        platform += (
            "-musl" if values[1] == "musl" else ("-baseline" if values[0] == "x86_64" else "")
        )
        decision["stage"] = "public_tool_preparation"
        write_json(self.logs_dir / "install-decision.json", decision)
        start = time.monotonic()
        material = await prepare(
            self.helper_tool_cache, self._version, platform, evidence_dir=self.logs_dir
        )
        decision.update(
            material=material["material"],
            cache_hit=material["cache_hit"],
            preparation_seconds=time.monotonic() - start,
            stage="offline_tool_installation",
        )
        write_json(self.logs_dir / "install-decision.json", decision)
        # Harbor's copy channel does not open the author's execution network.
        await environment.upload_dir(source_dir=Path(material["path"]), target_dir=target)
        # Preserve the author image and existing executables. Use the agent's own path.
        check = await environment.exec(
            command=f"chmod -R a+rX {target}; {target}/opencode --version; "
            'for tool in bash sh tee stdbuf; do command -v "$tool" >/dev/null 2>&1 || '
            "printf 'missing:%s\\n' \"$tool\"; done",
            user="root",
            timeout_sec=30,
        )
        output = (check.stdout or "").splitlines()
        missing = [line[8:] for line in output if line.startswith("missing:")]
        decision["missing_dependencies"] = missing
        if check.return_code or self._version not in output:
            raise RuntimeError(
                "Offline OpenCode executable failed author environment ABI/version check"
            )
        if missing:
            mode = decision["author_network_mode"]
            if mode == "no-network":
                raise RuntimeError(
                    "Offline agent runtime missing author shell/coreutils: " + ", ".join(missing)
                )
            await self.ensure_system_dependencies(environment, ("bash", "coreutils"))
        self._offline_tool = True
        decision.update(actual_version=self._version, status="completed", stage="ready")

    async def install(self, environment):
        # Historical accepted jobs keep the distribution Node/npm installer.
        # New jobs can provision the fixed platform binary outside the task network.
        if not self._version or not re.fullmatch(r"\d+\.\d+\.\d+", self._version):
            raise ValueError("A fixed numeric opencode version is required")
        started = time.monotonic()
        command = "command -v opencode >/dev/null 2>&1 && opencode --version"
        probe = await environment.exec(command=command, timeout_sec=30)
        actual = (probe.stdout or "").strip() if probe.return_code == 0 else None
        decision = {
            "expected_version": self._version,
            "previous_version": actual
            if actual and re.fullmatch(r"\d+\.\d+\.\d+", actual)
            else ("unrecognized" if actual else None),
            "reused": actual == self._version,
        }
        if actual == self._version:
            decision.update(actual_version=actual, install_seconds=time.monotonic() - started)
            write_json(self.logs_dir / "install-decision.json", decision)
            return
        mode = getattr(getattr(environment, "network_policy", None), "network_mode", None)
        decision["author_network_mode"] = getattr(mode, "value", "unknown")
        if getattr(self, "helper_tool_cache", None):
            decision.update(strategy="offline-npm-binary-v1", status="running")
            try:
                await self._install_offline(environment, decision)
            except BaseException as exc:
                decision.update(
                    status="interrupted" if isinstance(exc, asyncio.CancelledError) else "failed",
                    error_type=type(exc).__name__,
                )
                from harbor_helper.execution.agent_tools import ToolPreparationError

                if isinstance(exc, ToolPreparationError):
                    decision["preparation_error_type"] = exc.classification
                raise
            finally:
                decision["install_seconds"] = time.monotonic() - started
                write_json(self.logs_dir / "install-decision.json", decision)
            return
        # A no-network author task may legitimately ship a matching agent. Only
        # diagnose missing prerequisites after checking that reuse path above.
        check = await environment.exec(
            command='for tool in curl bash cat node npm; do command -v "$tool" >/dev/null 2>&1 || printf \'%s\\n\' "$tool"; done',
            user="root",
        )
        missing = [
            tool
            for tool in (check.stdout or "").split()
            if tool in {"curl", "bash", "cat", "node", "npm"}
        ]
        decision["missing_dependencies"] = missing
        mode = getattr(getattr(environment, "network_policy", None), "network_mode", None)
        decision["author_network_mode"] = getattr(mode, "value", "unknown")
        if missing and decision["author_network_mode"] == "no-network":
            decision.update(status="blocked", install_seconds=time.monotonic() - started)
            write_json(self.logs_dir / "install-decision.json", decision)
            raise RuntimeError(
                "Agent setup blocked: author environment network_mode=no-network; "
                "fixed OpenCode is not preinstalled and missing dependencies: "
                + ", ".join(missing)
                + ". No author network override was applied. Use the explicit repair retry action "
                "to apply offline tool preparation when the parent strategy is missing."
            )
        await self.ensure_system_dependencies(
            environment, ("curl", "bash", "coreutils", "nodejs", "npm")
        )
        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; node --version && npm --version && "
                f"npm i -g opencode-ai@{shlex.quote(self._version)} && opencode --version"
            ),
        )
        final = await environment.exec(command=command, timeout_sec=30)
        final_version = (final.stdout or "").strip()
        decision.update(
            actual_version=final_version
            if re.fullmatch(r"\d+\.\d+\.\d+", final_version)
            else "unrecognized",
            install_seconds=time.monotonic() - started,
        )
        write_json(self.logs_dir / "install-decision.json", decision)
        if final.return_code or final_version != self._version:
            raise RuntimeError("Installed opencode does not match the requested fixed version")


class BundleMixin:
    """Keep task execution in Harbor; install the frozen experiment payload."""

    logs_dir: Path

    def __init__(self, *args, helper_bundle=None, **kwargs):
        self.helper_bundle = Path(helper_bundle) if helper_bundle else None
        super().__init__(*args, **kwargs)

    async def run(self, instruction, environment, context):
        if self.helper_bundle:
            await environment.upload_dir(
                source_dir=self.helper_bundle, target_dir="/opt/harbor-helper-bundle"
            )
            command = "ls -R /opt/harbor-helper-bundle"
            if (self.helper_bundle / "bootstrap.sh").is_file():
                command += " && bash /opt/harbor-helper-bundle/bootstrap.sh"
            result = await environment.exec(
                command=command,
                user="root",
                env={
                    "PYTHONPATH": "/opt/harbor-helper-bundle/sdk",
                    "HARBOR_HELPER_BUNDLE": "/opt/harbor-helper-bundle",
                },
            )
            (self.logs_dir / "bundle-setup.txt").write_text(
                (result.stdout or "") + (result.stderr or "")
            )
            if result.return_code:
                raise RuntimeError(f"Bundle bootstrap failed with exit {result.return_code}")
        with environment.scoped_exec_env(
            {
                "PYTHONPATH": "/opt/harbor-helper-bundle/sdk",
                "HARBOR_HELPER_BUNDLE": "/opt/harbor-helper-bundle",
            }
            if self.helper_bundle
            else {}
        ):
            await super().run(instruction, environment, context)  # ty: ignore[unresolved-attribute]  # Cooperative mixin dispatch resolves run on the next Harbor agent in the MRO.


class BundledOracle(BundleMixin, OracleAgent):
    def __init__(self, *args, helper_tasks, **kwargs):
        from harbor.models.task.task import Task
        from harbor.models.trial.paths import TrialPaths

        logs_dir = Path(kwargs["logs_dir"])
        name = logs_dir.parent.name.rsplit("__", 1)[0]
        task_dir = Path(helper_tasks[name])
        kwargs.update(
            task_dir=task_dir,
            trial_paths=TrialPaths(trial_dir=logs_dir.parent),
            agent_timeout_sec=Task(task_dir).config.agent.timeout_sec,
        )
        super().__init__(*args, **kwargs)


class BundledOpenCode(BundleMixin, HelperOpenCode):
    options_model = BundledOpenCodeOptions
