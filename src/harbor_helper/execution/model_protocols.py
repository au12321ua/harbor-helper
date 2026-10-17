"""Explicit adapter capability contract shared by catalog, admission and jobs."""

ADAPTERS = {
    "openai-compatible": "@ai-sdk/openai-compatible",
    "openai": "@ai-sdk/openai",
    "anthropic": "@ai-sdk/anthropic",
}


def parameters(protocol, params, version):
    if protocol not in ADAPTERS:
        raise ValueError("Unsupported model protocol")
    if not isinstance(params, dict):
        raise TypeError("Model parameters must be an object")
    result = dict(params)
    if protocol != "openai-compatible":
        if version != "1.18.35":
            raise ValueError("Responses and Messages require verified OpenCode 1.18.35")
        if set(params) - {"max_output_tokens"}:
            raise ValueError(
                "This protocol supports only max_output_tokens; remove unsupported parameters"
            )
        result.setdefault("max_output_tokens", 4096)
        if type(result["max_output_tokens"]) is not int or result["max_output_tokens"] <= 0:
            raise ValueError("max_output_tokens must be a positive integer")
    return result


def bundle_config(value):
    """Only non-secret prompt/tool settings; model selection belongs to helper."""
    if not isinstance(value, dict) or set(value) - {"instructions", "permission", "tools", "agent"}:
        raise ValueError(
            "Bundle config supports only instructions, permission, tools and agent prompts/tools"
        )
    if "agent" in value:
        agents = value["agent"]
        if not isinstance(agents, dict):
            raise ValueError("Bundle agent settings must be an object")
        for settings in agents.values():
            if not isinstance(settings, dict) or set(settings) - {
                "prompt",
                "description",
                "tools",
                "permission",
                "steps",
                "disable",
                "hidden",
            }:
                raise ValueError("Bundle agent model/runtime selection is managed by helper")
    return value
