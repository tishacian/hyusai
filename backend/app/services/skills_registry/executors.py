"""The verified executor set a workspace-defined Skill may bind to.

A workspace must never bring code. ``_REGISTRY`` in :mod:`.wrappers` is a
hardcoded dict of import-time Python callables; letting an authored row name an
arbitrary module path would turn Skill authoring into remote code execution
behind an admin role. So an authored row names a **kind** from the closed table
below and supplies parameters that must satisfy that kind's schema. The kind is
a key, never a path: an unknown kind resolves to nothing at all rather than to
whatever the string happens to import.

Binding is eager and total. :func:`bind_executor` either returns a callable the
platform verified, or raises. There is no degraded stand-in, because a Skill
that silently returns ``{"status": "degraded"}`` at run time looks like a node
that ran and produces a Flow that appears to work.

Adding a kind means adding one :class:`VerifiedExecutor` here. The two present
kinds deliberately introduce no new egress and no new credential surface: they
parameterise runtimes the platform already ships. An HTTP executor needs an
egress allowlist object that does not exist yet, and inventing one inside this
table would put the weakest boundary behind the strongest gate.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable

from jsonschema import Draft202012Validator

from app.services.skills_registry.binding import (
    SkillBindingError,
    SkillCallable,
    is_workspace_skill_slug,
)

MAX_TEMPLATE_CHARS = 8_000
MAX_PROMPT_CHARS = 32_000

_PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]{0,63})\}")

# Provider -> the seeded slug whose wrapper the platform already verified for
# that provider. A prompt template reuses one of these rather than reaching a
# model client directly, so streaming, token accounting and degraded-key
# handling stay in exactly one place.
_PROMPT_PROVIDERS = {
    "ollama": "ollama_llm_v1",
    "azure": "azure_llm_v1",
    "openai": "openai_llm_v1",
    "azure_openai": "azure_openai_llm_v1",
    "workspace": "workspace_llm_v1",
}


@dataclass(frozen=True, slots=True)
class VerifiedExecutor:
    """One runtime a workspace may parameterise, and the shape of its knobs."""

    kind: str
    summary: str
    params_schema: dict[str, Any]
    bind: Callable[[Mapping[str, Any]], SkillCallable]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "params_schema": self.params_schema,
        }


def _seeded_callable(slug: Any, *, path: str) -> SkillCallable:
    """Resolve a seeded wrapper, refusing anything that is not one."""

    from app.services.skills_registry.wrappers import resolve

    target = str(slug or "").strip()
    if is_workspace_skill_slug(target):
        # Chaining authored rows would let a workspace build a call graph the
        # verified set never reviewed, and could close a cycle.
        raise SkillBindingError(
            code="executor_target_not_seeded",
            message=f"{path} must name a seeded Skill, not a workspace-defined one.",
        )
    try:
        return resolve(target)
    except NotImplementedError as exc:
        raise SkillBindingError(
            code="executor_target_unbound",
            message=f"{path} names no verified runtime.",
        ) from exc


def _bind_registry_call(params: Mapping[str, Any]) -> SkillCallable:
    """Invoke a seeded wrapper with parameters the run cannot override."""

    inner = _seeded_callable(params.get("skill_slug"), path="params.skill_slug")
    frozen = dict(params.get("frozen_input") or {})
    pinned_collection = None
    if params.get("skill_slug") == "semantic_search_v1":
        collections = {str(frozen[key]).strip() for key in ("collection", "collection_name", "context_collection") if frozen.get(key)}
        if len(collections) > 1:
            raise SkillBindingError(code="executor_collection_conflict", message="Frozen retrieval collection aliases must agree.")
        pinned_collection = next(iter(collections), None)

    async def _run(payload: dict[str, Any], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        # Frozen last: the authored configuration is the contract, so a run must
        # not be able to substitute its own value for a pinned one.
        if pinned_collection:
            contract = dict((ctx or {}).get("retrieval_contract") or {})
            declared = contract.get("collection") or contract.get("primary_collection")
            scopes = [source.get("authoritative_collections") for source in (payload, ctx or {}, contract)]
            excluded = any(isinstance(scope, list) and pinned_collection not in scope for scope in scopes)
            if excluded or (declared and declared != pinned_collection):
                raise SkillBindingError(code="executor_collection_outside_contract",
                    message="The pinned retrieval tool conflicts with the System collection contract.")
            # Preserve narrower System controls and forbid a search widening on
            # an empty result. The native retriever enforces this contract.
            contract.update(asset_binding="authoritative", collection=pinned_collection,
                empty_bound_collection="abstain", allow_workspace_fallback=False)
            ctx = {**(ctx or {}), "retrieval_contract": contract}
        return await inner({**payload, **frozen}, ctx)

    return _run


def _render_template(template: str, payload: Mapping[str, Any]) -> str:
    """Substitute named placeholders only.

    ``str.format`` is not usable here: an authored template is admin-supplied
    but the substitution is attacker-reachable through upstream node output,
    and ``format`` resolves attribute and index access, so ``{x.__class__}``
    walks the object graph. This resolves a flat name or fails.
    """

    missing: list[str] = []

    def _substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in payload:
            missing.append(name)
            return ""
        value = payload[name]
        rendered = value if isinstance(value, str) else str(value)
        return rendered

    prompt = _PLACEHOLDER_RE.sub(_substitute, template)
    if missing:
        raise SkillBindingError(
            code="prompt_input_missing",
            message="This Skill requires " + ", ".join(sorted(set(missing))) + ".",
        )
    if len(prompt) > MAX_PROMPT_CHARS:
        raise SkillBindingError(
            code="prompt_too_large",
            message=f"The rendered prompt exceeds {MAX_PROMPT_CHARS} characters.",
        )
    return prompt


def _bind_prompt_template(params: Mapping[str, Any]) -> SkillCallable:
    """Send a frozen template, filled from the run, to a verified provider."""

    provider = str(params.get("provider") or "")
    slug = _PROMPT_PROVIDERS[provider]
    inner = _seeded_callable(slug, path="params.provider")
    template = str(params.get("template") or "")

    async def _run(payload: dict[str, Any], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        request = {"prompt": _render_template(template, payload)}
        # The engine resolves input > binding > System > workspace before its
        # membrane gate. Keep input schemas untouched: an author-pinned model
        # is execution configuration, not an extra user input.
        model = payload.get("model")
        if not isinstance(model, str) or not model.strip():
            model = params.get("model")
        if isinstance(model, str) and model.strip():
            request["model"] = model.strip()
        return await inner(request, ctx)

    return _run


VERIFIED_EXECUTORS: dict[str, VerifiedExecutor] = {
    "registry_call": VerifiedExecutor(
        kind="registry_call",
        summary="Run a catalog Skill with parameters pinned by this workspace.",
        params_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["skill_slug"],
            "properties": {
                "skill_slug": {"type": "string", "minLength": 1, "maxLength": 160},
                "frozen_input": {"type": "object"},
            },
        },
        bind=_bind_registry_call,
    ),
    "prompt_template": VerifiedExecutor(
        kind="prompt_template",
        summary="Send a fixed prompt template to a verified model provider.",
        params_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["provider", "template"],
            "properties": {
                "provider": {"enum": sorted(_PROMPT_PROVIDERS)},
                "model": {"type": "string", "minLength": 1, "maxLength": 256},
                "template": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_TEMPLATE_CHARS,
                },
            },
        },
        bind=_bind_prompt_template,
    ),
}


def validate_executor_binding(binding: Any) -> dict[str, Any]:
    """Return the canonical binding to store, or raise.

    Verification happens once at authoring time and again at every resolution.
    Doing it here as well means an unbindable Skill is refused before it can be
    referenced by a Flow, rather than discovered by a failing run.
    """

    if not isinstance(binding, Mapping):
        raise SkillBindingError(
            code="executor_required",
            message="A workspace-defined Skill must declare an executor binding.",
        )
    kind = str(binding.get("kind") or "").strip()
    executor = VERIFIED_EXECUTORS.get(kind)
    if executor is None:
        raise SkillBindingError(
            code="executor_kind_unknown",
            message=(
                "executor.kind must be one of: " + ", ".join(sorted(VERIFIED_EXECUTORS)) + "."
            ),
        )
    raw_params = binding.get("params")
    params = dict(raw_params) if isinstance(raw_params, Mapping) else {}
    errors = sorted(
        Draft202012Validator(executor.params_schema).iter_errors(params),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        path = "/".join(str(item) for item in errors[0].absolute_path)
        raise SkillBindingError(
            code="executor_params_invalid",
            message=(
                f"executor.params{'/' + path if path else ''} does not satisfy the "
                f"{kind} executor contract: {errors[0].message}"
            ),
        )
    canonical = {"kind": kind, "params": params}
    # Binding is the real acceptance test: a schema-valid ``registry_call``
    # can still name a slug with no runtime.
    executor.bind(params)
    return canonical


def bind_executor(binding: Any) -> SkillCallable:
    """Turn a stored binding into a verified callable, or raise."""

    canonical = validate_executor_binding(binding)
    return VERIFIED_EXECUTORS[canonical["kind"]].bind(canonical["params"])


def executor_runtime_status(binding: Any) -> str:
    """Return the underlying seeded runtime status for an authored binding.

    Structural validation alone is not enough: ``resolve`` intentionally
    returns registered stub callables, which are useful for diagnostics but
    must never make publication look runnable. Every verified authored
    executor ultimately delegates to one seeded wrapper, so expose that
    wrapper's real status to publication and readiness gates.
    """

    canonical = validate_executor_binding(binding)
    params = canonical["params"]
    if canonical["kind"] == "registry_call":
        target_slug = str(params["skill_slug"])
    else:
        target_slug = _PROMPT_PROVIDERS[str(params["provider"])]

    from app.services.skills_registry.wrappers import runtime_status

    return runtime_status(target_slug)


def verified_executor_catalog() -> list[dict[str, Any]]:
    """The executor choices an authoring surface may offer, in a stable order."""

    return [VERIFIED_EXECUTORS[kind].to_dict() for kind in sorted(VERIFIED_EXECUTORS)]


__all__ = [
    "VERIFIED_EXECUTORS",
    "VerifiedExecutor",
    "bind_executor",
    "executor_runtime_status",
    "validate_executor_binding",
    "verified_executor_catalog",
]
