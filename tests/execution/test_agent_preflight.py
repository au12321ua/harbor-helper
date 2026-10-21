"""Exercise the Job gate used by workers, before any Docker/model execution."""

import asyncio

import pytest
from harbor.environments.docker.docker import DockerEnvironment
from harbor.job import Job
from harbor.models.job.config import JobConfig
from harbor.trial.trial import Trial
from support.paths import REPO

from harbor_helper.execution.agents import BundledOpenCode, HelperOpenCode, HelperOpenCodeOptions

TASK = REPO / "examples/harbor-helper-switch-smoke/harbor-helper-switch-answer"


def config(tmp_path, bundled=False, **kwargs):
    return JobConfig.model_validate(
        {
            "job_name": "preflight",
            "jobs_dir": str(tmp_path / "jobs"),
            "tasks": [{"path": str(TASK)}],
            "agents": [
                {
                    "import_path": "harbor_helper.execution.agents:"
                    + ("BundledOpenCode" if bundled else "HelperOpenCode"),
                    "model_name": "vllm/fixture",
                    "kwargs": {"version": "1.18.35", **kwargs},
                }
            ],
        }
    )


@pytest.mark.parametrize("bundled", [False, True])
@pytest.mark.parametrize("cache", [False, True])
def test_real_job_preflight_and_trial_receive_options(tmp_path, monkeypatch, bundled, cache):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # Harbor probes the engine kernel using `docker container run` during Trial
    # construction. This test checks agent option propagation, so substitute
    # that external capability observation before constructing the real Trial.
    monkeypatch.setattr(
        DockerEnvironment, "_egress_control_kernel_support", classmethod(lambda cls: True)
    )
    kwargs = {"variant": "minimal", "opencode_config": {"enabled_providers": ["vllm"]}}
    if cache:
        kwargs["helper_tool_cache"] = str(tmp_path / "agent-tools")
    if bundled:
        kwargs["helper_bundle"] = str(tmp_path / "bundle")

    async def check():
        job = await Job.create(config(tmp_path, bundled, **kwargs))
        trial = await Trial.create(job._trial_configs[0])
        agent = trial.agent
        assert isinstance(agent, HelperOpenCode)
        assert isinstance(agent.options, HelperOpenCodeOptions)
        assert agent.helper_tool_cache == (tmp_path / "agent-tools" if cache else None)
        assert agent.options.helper_tool_cache == kwargs.get("helper_tool_cache")
        assert agent._version == "1.18.35"
        assert agent.options.variant == "minimal"
        assert agent.options.opencode_config == kwargs["opencode_config"]
        if bundled:
            assert isinstance(agent, BundledOpenCode)
            assert agent.helper_bundle == tmp_path / "bundle"

    asyncio.run(check())


@pytest.mark.parametrize("bundled", [False, True])
@pytest.mark.parametrize(
    "invalid",
    [
        {"unknown_helper_option": "invalid"},
        {"helper_tool_cache": True},
        {"helper_tool_cache": 123},
        {"helper_tool_cache": ""},
        {"variant": []},
    ],
)
def test_real_job_preflight_keeps_unknown_and_type_validation(tmp_path, bundled, invalid):
    with pytest.raises(ValueError, match="Invalid kwargs"):
        asyncio.run(Job.create(config(tmp_path, bundled, **invalid)))


def test_bundle_option_only_accepted_on_bundled_agent(tmp_path):
    with pytest.raises(ValueError, match="Unknown option 'helper_bundle'"):
        asyncio.run(Job.create(config(tmp_path, helper_bundle=str(tmp_path / "bundle"))))
    with pytest.raises(ValueError, match="Invalid kwargs"):
        asyncio.run(Job.create(config(tmp_path, True, helper_bundle=False)))
