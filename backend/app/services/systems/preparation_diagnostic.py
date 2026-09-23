"""What still has to be true before an automation can be called ready.

A check that was not performed is ``not_checked``. That state is not ready.
``not_applicable`` is a check we looked at and found nothing to inspect.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CHECKS = ("model", "provider", "source", "indexing", "rights", "worker")
COMPLETION_SKILLS = ("workspace_llm_v1", "azure_llm_v1", "ollama_llm_v1")
_COUNTED_AS_READY = frozenset({"ready", "not_applicable"})


def _nodes(flow: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    raw = flow.get("nodes") if isinstance(flow, Mapping) else None
    if not isinstance(raw, list):
        return []
    return [node for node in raw if isinstance(node, Mapping)]


def _skill_slugs(flow: Mapping[str, Any] | None) -> list[str]:
    slugs: list[str] = []
    for node in _nodes(flow):
        config = node.get("config") if isinstance(node.get("config"), Mapping) else {}
        slug = config.get("skill_slug")
        if isinstance(slug, str) and slug and slug not in slugs:
            slugs.append(slug)
    return slugs


def _row(name: str, status: str, detail: str | None = None) -> dict[str, Any]:
    return {"name": name, "status": status, "detail": detail}


def provider_name(routing: Mapping[str, Any] | None) -> str | None:
    """The provider ``get_routing`` named. An empty name was not a check."""

    if not isinstance(routing, Mapping):
        return None
    provider = routing.get("default_provider")
    if isinstance(provider, str) and provider.strip():
        return provider.strip()
    return None


def caller_run_right(status_code: int | None) -> bool | None:
    """Map the run authority onto the rights check.

    ``None`` means the authority allowed this caller. ``403`` is a refusal.
    Any other status did not answer the rights question, so the check stays
    unperformed.
    """

    if status_code is None:
        return True
    if status_code == 403:
        return False
    return None


def preparation_diagnostic(
    flow: Mapping[str, Any] | None,
    *,
    provider: str | None = None,
    caller_can_run: bool | None = None,
    worker_reachable: bool | None = None,
    indexed: bool | None = None,
    index_detail: str | None = None,
) -> dict[str, Any]:
    """Name the six preparation checks. Do not treat a skipped check as ready."""

    slugs = _skill_slugs(flow)
    completion = next((slug for slug in COMPLETION_SKILLS if slug in slugs), None)
    if completion:
        model = _row("model", "ready", completion)
    elif slugs:
        model = _row("model", "blocked", slugs[0])
    else:
        model = _row("model", "not_checked")

    has_source = any(node.get("kind") == "source" for node in _nodes(flow))
    has_retrieval = "semantic_search_v1" in slugs or "llm_rag_answer_v1" in slugs
    if not has_retrieval:
        indexing = _row("indexing", "not_applicable")
    elif indexed is True:
        indexing = _row("indexing", "ready", index_detail)
    elif indexed is False:
        indexing = _row("indexing", "blocked", index_detail)
    else:
        indexing = _row("indexing", "not_checked")
    if caller_can_run is True:
        rights = _row("rights", "ready")
    elif caller_can_run is False:
        rights = _row("rights", "blocked")
    else:
        rights = _row("rights", "not_checked")

    checks = [
        model,
        _row("provider", "ready", provider) if provider else _row("provider", "not_checked"),
        _row("source", "ready") if has_source else _row("source", "not_checked"),
        indexing,
        rights,
        _row("worker", "ready") if worker_reachable is True else (
            _row("worker", "blocked") if worker_reachable is False else _row("worker", "not_checked")
        ),
    ]
    names = [item["name"] for item in checks]
    if names != list(CHECKS):
        raise RuntimeError("preparation checks drifted")
    return {
        "ready": all(item["status"] in _COUNTED_AS_READY for item in checks),
        "checks": checks,
    }
