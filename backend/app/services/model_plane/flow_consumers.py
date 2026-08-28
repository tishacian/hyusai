"""Which flow nodes consume which model-portal provider.

Extends the existing ``System.default_model`` index: a completion-shaped
task (``prompt`` or ``template`` in the skill schema) is a consumer even
when the System pin is empty. Caps keep a Providers-tab click cheap.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from sqlalchemy.orm import Session as DBSession

from app.services.model_plane.provider_keys import (
    canonical_provider,
    preferences_from_model,
)

COMPLETION_FIELD_NAMES = frozenset({"prompt", "template"})
COMPLETION_SLUGS = frozenset({"azure_llm_v1", "ollama_llm_v1"})
_SYSTEM_CAP = 80
_NODE_CAP = 80


def schema_is_completion_shaped(schema: Any) -> bool:
    if not isinstance(schema, Mapping):
        return False
    props = schema.get("properties")
    if not isinstance(props, Mapping):
        return False
    return any(name in COMPLETION_FIELD_NAMES for name in props)


def skill_is_completion_shaped(slug: str, schema: Any) -> bool:
    if slug in COMPLETION_SLUGS:
        return True
    return schema_is_completion_shaped(schema)


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _skill_default_model(slug: str) -> Optional[str]:
    """Same defaults the completion wrappers use when the node is silent."""
    if slug == "azure_llm_v1":
        return "gpt-4o-mini"
    if slug == "ollama_llm_v1":
        return "ollama:deepseek-r1:14b"
    return None


def _node_model(node: Mapping[str, Any], system_default: Optional[str], slug: str) -> Optional[str]:
    cfg = _as_dict(node.get("config"))
    params = _as_dict(cfg.get("params"))
    raw = params.get("model")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    imap = _as_dict(cfg.get("inputs_map"))
    model_ref = imap.get("model")
    if isinstance(model_ref, Mapping):
        path = model_ref.get("path")
        joined = ".".join(str(p) for p in path) if isinstance(path, list) else str(path or "")
        if "default_model" in joined:
            return system_default or _skill_default_model(slug)
    return system_default or _skill_default_model(slug)


def _skill_slug(node: Mapping[str, Any]) -> str:
    cfg = _as_dict(node.get("config"))
    data = _as_dict(node.get("data"))
    return str(cfg.get("skill_slug") or data.get("skill_slug") or "").strip()


def consumers_for_systems(
    systems: Iterable[Any],
    *,
    schemas_by_slug: Mapping[str, Any],
    default_provider: str,
    default_model: str,
) -> List[Dict[str, Any]]:
    """Project Systems + their flow nodes into the routing ``systems`` payload."""

    rows: List[Dict[str, Any]] = []
    for index, system in enumerate(systems):
        if index >= _SYSTEM_CAP:
            break
        flow = _as_dict(getattr(system, "flow_definition", None))
        system_default = getattr(system, "default_model", None)
        if isinstance(system_default, str):
            system_default = system_default.strip() or None
        else:
            system_default = None
        nodes_out: List[Dict[str, Any]] = []
        for node in _as_list(flow.get("nodes")):
            if len(nodes_out) >= _NODE_CAP:
                break
            if not isinstance(node, Mapping):
                continue
            kind = str(node.get("kind") or "task")
            if kind not in {"task", "llm"}:
                continue
            slug = _skill_slug(node)
            if not slug or not skill_is_completion_shaped(slug, schemas_by_slug.get(slug)):
                continue
            model = _node_model(node, system_default, slug)
            prefs = preferences_from_model(
                model,
                default_provider=default_provider,
                default_model=default_model or (system_default or ""),
            )
            nodes_out.append(
                {
                    "node_id": str(node.get("id") or ""),
                    "label": str(node.get("label") or node.get("id") or ""),
                    "skill_slug": slug,
                    "model": prefs["model"] or None,
                    "provider": canonical_provider(prefs["provider"]),
                }
            )
        rows.append(
            {
                "id": getattr(system, "id", None),
                "name": getattr(system, "name", None),
                "default_model": system_default,
                "status": getattr(system, "status", None),
                "nodes": nodes_out,
            }
        )
    return rows
