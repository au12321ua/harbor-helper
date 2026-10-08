import re
import shlex
from pathlib import Path

from harbor.agents.installed.opencode import OpenCode
from harbor.agents.oracle import OracleAgent


class HelperOpenCode(OpenCode):
    async def install(self, environment):
        # Use the distribution's Node/npm rather than fetching nvm from GitHub.
        # OpenCode's npm package installs its own platform binary.
        if not self._version or not re.fullmatch(r"\d+\.\d+\.\d+", self._version):
            raise ValueError("A fixed numeric opencode version is required")
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


class BundleMixin:
    """Keep task execution in Harbor; install the frozen experiment payload."""

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
            await super().run(instruction, environment, context)


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
    pass
