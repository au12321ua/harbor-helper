"""Model harness adapters: platform agent input -> Harbor ``AgentConfig`` (03 section 2).

Credentials never travel through Harbor's configuration: Harbor writes the job and trial
configuration (including agent kwargs) into the trial directory, which becomes evidence.
They are not put in the Runner's environment either, where an author's compose file
could reference them. The service sends them on stdin; they stay in ``SECRETS`` and the
adapter's agent class hands them to the model client in memory.

Terminus-2 is Harbor's own agent: the model is called from this process and only shell
commands run in the task container, so the container needs no route to the model.
"""

import functools
from typing import Any

SECRETS: dict[str, str] = {}

# Model configuration parameters Terminus-2 takes as its own options; the rest go to
# every model call (litellm drops what a provider does not support).
_OPTION_PARAMS = {"temperature", "reasoning_effort", "max_thinking_tokens"}
# Harness parameters an administrator may expose for Terminus-2.
TERMINUS_PARAMETERS = {
    "max_turns",
    "parser_name",
    "enable_summarize",
    "proactive_summarization_threshold",
    "record_terminal_session",
    "tmux_pane_width",
    "tmux_pane_height",
    "interleaved_thinking",
}
ADAPTERS = {
    "terminus-2": {
        "protocols": ("anthropic", "openai", "openai-compatible"),
        "parameters": TERMINUS_PARAMETERS,
    }
}


class InputError(ValueError):
    pass


def _litellm_model(protocol: str, model_id: str) -> str:
    if protocol == "anthropic":
        return f"anthropic/{model_id}"
    if protocol in {"openai", "openai-compatible"}:
        return f"openai/{model_id}"
    raise InputError(f"unsupported protocol {protocol!r}")


def agent_config(agent: dict) -> dict[str, Any]:
    """Keyword arguments for Harbor's ``AgentConfig`` from the platform's agent input:
    ``{"adapter", "model": {protocol, endpoint, model_id, params}, "params"}``."""
    adapter = agent.get("adapter")
    if adapter not in ADAPTERS:
        raise InputError(f"unknown harness adapter {adapter!r}")
    model = agent.get("model") or {}
    protocol = model.get("protocol")
    if protocol not in ADAPTERS[adapter]["protocols"]:
        raise InputError(f"{adapter} cannot call a {protocol!r} model")
    params = agent.get("params") or {}
    unknown = set(params) - ADAPTERS[adapter]["parameters"]
    if unknown:
        raise InputError(f"unknown {adapter} parameters: {sorted(unknown)}")
    model_params = dict(model.get("params") or {})
    kwargs: dict[str, Any] = {
        **params,
        "api_base": model["endpoint"],
        "use_responses_api": protocol == "openai",
        **{k: model_params.pop(k) for k in list(model_params) if k in _OPTION_PARAMS},
    }
    if model_params:
        kwargs["llm_call_kwargs"] = model_params
    return {
        "import_path": "maestro_runner.agents:MaestroTerminus2",
        "model_name": _litellm_model(protocol, model["model_id"]),
        "kwargs": kwargs,
    }


@functools.cache
def _terminus():
    from harbor.agents.terminus_2.terminus_2 import Terminus2

    class MaestroTerminus2(Terminus2):
        """Terminus-2 whose model client gets the API key from memory."""

        def _init_llm(self, *args, **kwargs):
            key = SECRETS.get("model_api_key")
            if key:
                if args:  # positional form: llm_kwargs is the fifth argument
                    args = list(args)
                    args[4] = {**(args[4] or {}), "api_key": key}
                else:
                    kwargs["llm_kwargs"] = {**(kwargs.get("llm_kwargs") or {}), "api_key": key}
            return super()._init_llm(*args, **kwargs)

    return MaestroTerminus2


def __getattr__(name: str):
    # Harbor loads the class by import path; build it only then, after Harbor imports.
    if name == "MaestroTerminus2":
        return _terminus()
    raise AttributeError(name)
