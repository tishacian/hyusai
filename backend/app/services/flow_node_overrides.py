"""Bounded per-node authoring overrides, frozen by the canonical compiler."""
from copy import deepcopy
from collections.abc import Mapping

from app.services.skills_registry.executors import (
    MAX_TEMPLATE_CHARS, _PLACEHOLDER_RE, validate_executor_binding,
)


def override_executor(executor, config):
    """Only a template can change; provider, model and schemas remain intact."""
    result = deepcopy(executor)
    if "prompt_template_override" not in config:
        return result
    if not isinstance(executor, Mapping) or executor.get("kind") != "prompt_template":
        raise ValueError("This executor does not support a prompt template override.")
    template = config["prompt_template_override"]
    original = (executor.get("params") or {}).get("template", "")
    if not isinstance(template, str) or not template.strip() or len(template) > MAX_TEMPLATE_CHARS:
        raise ValueError("The template must contain between 1 and 8000 characters.")
    if set(_PLACEHOLDER_RE.findall(template)) != set(_PLACEHOLDER_RE.findall(original)):
        raise ValueError("A correction must preserve every named input placeholder.")
    result["params"]["template"] = template
    return validate_executor_binding(result)
