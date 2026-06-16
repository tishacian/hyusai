"""Runtime manifest projection for Flow Builder.

The Flow Builder is useful only if its blocks are tied to live runtime
contracts. This module projects ``System.flow_definition`` into a compact
operator-facing manifest: nodes, runtime references, bound skills, editable
parameter groups and whether the graph currently drives a real surface.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from sqlalchemy.orm import Session as DBSession

from app.models.run import Run
from app.models.skill import Skill
from app.models.system import System
from app.services.skills_registry import runtime_status
from app.services.systems.bootstrap import WORKSPACE_CHAT_VARIANT


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _compact(value: Any, *, max_chars: int = 360) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        import json

        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= max_chars else text[: max(0, max_chars - 1)].rstrip() + "…"


def _reasoning_template_catalog() -> List[Dict[str, Any]]:
    """Expose the reasoning template registry in manifest-friendly form."""
    try:
        from app.services.system_prompts import SYSTEM_PROMPT_TEMPLATES, SystemPromptType
    except Exception:  # noqa: BLE001 - manifest must remain available if registry import drifts.
        return []

    rows: List[Dict[str, Any]] = []
    for prompt_type in SystemPromptType:
        template = SYSTEM_PROMPT_TEMPLATES.get(prompt_type)
        if not template:
            continue
        rows.append(
            {
                "key": prompt_type.value,
                "label": prompt_type.value.replace("_", " ").title(),
                "template": template,
                "source": "backend/app/services/system_prompts/prompts.py",
            }
        )
    return rows


def _selected_reasoning_template(prompt_type: Any, catalog: List[Dict[str, Any]]) -> Dict[str, Any]:
    key = str(prompt_type or "factual")
    for row in catalog:
        if row.get("key") == key:
            return row
    return {"key": key, "label": key.replace("_", " ").title(), "template": "", "source": "flow.prompt_contract"}


def _grounded_system_prompt_preview(
    *,
    base_prompt: Any,
    grounding: Mapping[str, Any],
    appendix: Any,
) -> str:
    base = str(base_prompt or "")
    if not base:
        return ""
    if str(grounding.get("default_mode") or grounding.get("mode") or "").lower() != "balanced":
        return base
    appendix_text = str(appendix or "")
    if not appendix_text:
        return base
    return f"{base}\n\n{appendix_text}"


def _skill_lookup(db: DBSession, slugs: Iterable[str]) -> Dict[str, Skill]:
    clean = sorted({slug for slug in slugs if slug})
    if not clean:
        return {}
    rows = db.query(Skill).filter(Skill.slug.in_(clean)).all()
    return {row.slug: row for row in rows}


def _node_type_label(node: Mapping[str, Any], cfg: Mapping[str, Any]) -> str:
    kind = str(node.get("kind") or "task")
    if cfg.get("skill_slug"):
        return "skill"
    if cfg.get("runtime_ref") or _as_dict(node.get("data")).get("runtime_ref"):
        return "runtime"
    if kind == "decision":
        return "router"
    if kind in {"source", "sink"}:
        return kind
    return str(node.get("type") or kind)


def _editable_fields_from_schema(skill: Optional[Skill]) -> List[Dict[str, Any]]:
    if not skill:
        return []
    schema = _as_dict(skill.input_schema)
    properties = _as_dict(schema.get("properties"))
    required = set(_as_list(schema.get("required")))
    fields: List[Dict[str, Any]] = []
    for key, raw_def in properties.items():
        definition = _as_dict(raw_def)
        fields.append(
            {
                "key": key,
                "source": "skill.input_schema",
                "type": definition.get("type") or "string",
                "required": key in required,
                "description": definition.get("description"),
                "enum": definition.get("enum") if isinstance(definition.get("enum"), list) else None,
            }
        )
    return fields


def _editable_fields_from_node(node: Mapping[str, Any]) -> List[Dict[str, Any]]:
    data = _as_dict(node.get("data"))
    cfg = _as_dict(node.get("config"))
    fields: List[Dict[str, Any]] = []

    def add(key: str, source: str, field_type: str = "object", value: Any = None) -> None:
        fields.append(
            {
                "key": key,
                "source": source,
                "type": field_type,
                "required": False,
                "current_value": value,
            }
        )

    if cfg.get("branches") is not None:
        add("branches", "node.config", "array", cfg.get("branches"))
        add("default_branch", "node.config", "string", cfg.get("default_branch"))
    if data.get("retrieval_defaults") is not None:
        retrieval = _as_dict(data.get("retrieval_defaults"))
        for key in ("latency_profile", "retrieval_profile", "mode", "top_k"):
            add(f"retrieval_defaults.{key}", "node.data", "string" if key != "top_k" else "integer", retrieval.get(key))
    if data.get("grounding") is not None:
        add("grounding", "node.data", "object", data.get("grounding"))
    if data.get("source_policy") is not None:
        add("source_policy", "node.data", "object", data.get("source_policy"))
    prompt_contract = _as_dict(data.get("prompt_contract"))
    if prompt_contract:
        for key in (
            "system_prompt",
            "default_prompt_type",
            "base_system_prompt",
            "balanced_grounding_appendix",
            "balanced_appendix",
            "reasoning_template_factual",
            "rag_user_prompt_builder",
            "system_prompt_builder",
            "answer_shaping_instructions",
        ):
            if prompt_contract.get(key) is not None:
                field_type = "array" if isinstance(prompt_contract.get(key), list) else "text"
                add(f"prompt_contract.{key}", "node.data", field_type, prompt_contract.get(key))
    return fields


def _unit_for_node(node: Mapping[str, Any], skills: Mapping[str, Skill]) -> Dict[str, Any]:
    data = _as_dict(node.get("data"))
    cfg = _as_dict(node.get("config"))
    skill_slug = str(cfg.get("skill_slug") or data.get("skill_slug") or "")
    skill = skills.get(skill_slug)
    runtime_ref = cfg.get("runtime_ref") or data.get("runtime_ref")
    kind = str(node.get("kind") or "task")
    label = str(node.get("label") or node.get("id") or "node")
    fields = _editable_fields_from_node(node)
    fields.extend(_editable_fields_from_schema(skill))
    status = runtime_status(skill_slug) if skill_slug else ("bound" if runtime_ref else "manifest_only")
    operational = bool(skill_slug and status == "bound") or bool(runtime_ref)
    return {
        "id": node.get("id"),
        "label": label,
        "kind": kind,
        "node_type": node.get("type"),
        "unit_type": _node_type_label(node, cfg),
        "description": data.get("description") or (skill.description if skill else None) or _compact(runtime_ref),
        "runtime_ref": runtime_ref,
        "skill_slug": skill_slug or None,
        "skill_id": skill.id if skill else cfg.get("skill_id"),
        "runtime_status": status,
        "operational": operational,
        "prompt_contract": data.get("prompt_contract") or None,
        "editable_fields": fields,
        "parameter_count": len(fields),
        "position": node.get("position") or {},
        "implementation": {
            "source": "skill_registry" if skill_slug else "runtime_ref" if runtime_ref else "flow_manifest",
            "execution": skill.execution if skill else {},
            "input_schema": skill.input_schema if skill else {},
            "output_schema": skill.output_schema if skill else {},
        },
    }


def _effective_chat_config(flow: Mapping[str, Any]) -> Dict[str, Any]:
    chat = _as_dict(flow.get("chat"))
    prompt_contract = _as_dict(flow.get("prompt_contract"))
    nodes = _as_list(flow.get("nodes"))
    by_id = {str(node.get("id")): _as_dict(node) for node in nodes if isinstance(node, Mapping)}
    budget_node = by_id.get("runtime.settings_budget", {})
    grounding_node = by_id.get("skill.grounding_policy", {})
    retrieval_node = by_id.get("skill.fast_retrieval", {})
    prompt_node = by_id.get("runtime.prompt_assembly", {})
    answer_node = by_id.get("skill.fast_answer", {})
    budget_data = _as_dict(budget_node.get("data"))
    grounding_data = _as_dict(grounding_node.get("data"))
    retrieval_data = _as_dict(retrieval_node.get("data"))
    prompt_data = _as_dict(prompt_node.get("data"))
    answer_data = _as_dict(answer_node.get("data"))
    node_prompt_contract = _as_dict(answer_data.get("prompt_contract"))
    prompt_node_contract = _as_dict(prompt_data.get("prompt_contract"))
    retrieval_defaults = budget_data.get("retrieval_defaults") or chat.get("retrieval_defaults") or {}
    grounding = grounding_data.get("grounding") or chat.get("grounding") or {}
    source_policy = grounding_data.get("source_policy") or chat.get("source_policy") or {}
    system_prompt = node_prompt_contract.get("system_prompt") or prompt_contract.get("base_system_prompt")
    grounding_appendix = (
        node_prompt_contract.get("balanced_appendix")
        or prompt_node_contract.get("balanced_grounding_appendix")
        or prompt_contract.get("balanced_grounding_appendix")
    )
    answer_shaping = (
        node_prompt_contract.get("answer_shaping_instructions")
        or prompt_node_contract.get("answer_shaping_instructions")
        or prompt_contract.get("answer_shaping_instructions")
        or []
    )
    prompt_type = prompt_contract.get("default_prompt_type")
    reasoning_templates = _reasoning_template_catalog()
    selected_template = _selected_reasoning_template(prompt_type, reasoning_templates)

    citation_instructions = [
        "Use workspace context as the source of factual claims when retrieved sources exist.",
        "Cite retrieved sources by numeric source id such as [1].",
        "Do not emit raw filenames or chapter names as citation markers.",
        "Do not invent citations.",
    ]
    missing_source_instructions = [
        "If context is missing for workspace-specific facts, say that the workspace source is missing.",
        "Do not answer from other projects or similar documents as if they applied.",
        "Offer a safe next check or name the visible gap.",
    ]

    return {
        "assistant_profile": chat.get("assistant_profile"),
        "knowledge_scope": chat.get("knowledge_scope"),
        "collection_slugs": chat.get("collection_slugs") or [],
        "retrieval_defaults": retrieval_defaults,
        "grounding": grounding,
        "source_policy": source_policy,
        "system_prompt": system_prompt,
        "prompt_type": prompt_type,
        "retrieval_config": {
            "value": retrieval_defaults,
            "runtime_read_path": "nodes.runtime.settings_budget.data.retrieval_defaults",
            "fallback_path": "flow.chat.retrieval_defaults",
            "node_id": "runtime.settings_budget",
            "runtime_effect": "chat request defaults: latency_profile, retrieval_profile, mode, top_k",
            "retrieval_runtime_ref": retrieval_data.get("runtime_ref") or "app.services.rag.context.retrieve_rag_context",
        },
        "grounding_policy": {
            "value": grounding,
            "runtime_read_path": "nodes.skill.grounding_policy.data.grounding",
            "fallback_path": "flow.chat.grounding",
            "node_id": "skill.grounding_policy",
            "runtime_effect": "default grounding mode; strict guards still enforced downstream",
        },
        "source_policy_config": {
            "value": source_policy,
            "runtime_read_path": "nodes.skill.grounding_policy.data.source_policy",
            "fallback_path": "flow.chat.source_policy",
            "node_id": "skill.grounding_policy",
            "runtime_effect": "industrial/source selection constraints consumed by retrieval policy",
        },
        "prompt_stack": {
            "system_prompt": system_prompt,
            "base_system_prompt": prompt_contract.get("base_system_prompt"),
            "grounding_appendix": grounding_appendix,
            "effective_system_prompt_preview": _grounded_system_prompt_preview(
                base_prompt=system_prompt,
                grounding=_as_dict(grounding),
                appendix=grounding_appendix,
            ),
            "default_prompt_type": prompt_type,
            "selected_reasoning_template": selected_template,
            "available_reasoning_templates": reasoning_templates,
            "rag_user_prompt_contract": {
                "builder": prompt_contract.get("rag_user_prompt_builder")
                or prompt_node_contract.get("rag_user_prompt_builder")
                or "app.agents.procurement_agent._build_rag_user_prompt",
                "context_slots": [
                    "query",
                    "context_text",
                    "keyword_hint",
                    "retrieval_policy_prompt",
                    "retrieval_constraints",
                    "retrieval_summary",
                ],
                "citation_instructions": citation_instructions,
                "missing_source_instructions": missing_source_instructions,
                "answer_shaping_instructions": answer_shaping,
            },
            "runtime_read_fields": [
                "nodes.skill.fast_answer.data.prompt_contract.system_prompt",
                "flow.prompt_contract.default_prompt_type",
            ],
            "manifest_only_fields": [
                "flow.prompt_contract.balanced_grounding_appendix",
                "flow.prompt_contract.answer_shaping_instructions",
                "nodes.runtime.prompt_assembly.data.prompt_contract",
            ],
        },
        "runtime_builders": {
            "chat_defaults": "app.api.v1.endpoints.chat._apply_workspace_chat_flow_defaults",
            "grounding_policy_from_request": "app.agents.procurement_agent._grounding_policy_from_request",
            "system_prompt_builder": prompt_contract.get("system_prompt_builder")
            or prompt_node_contract.get("system_prompt_builder")
            or "app.agents.procurement_agent._system_prompt_with_grounding",
            "rag_user_prompt_builder": prompt_contract.get("rag_user_prompt_builder")
            or prompt_node_contract.get("rag_user_prompt_builder")
            or "app.agents.procurement_agent._build_rag_user_prompt",
            "answer_agent": answer_data.get("runtime_ref") or "app.agents.procurement_agent.OmniRAGAgent.process",
            "retrieval_context": retrieval_data.get("runtime_ref") or "app.services.rag.context.retrieve_rag_context",
            "reasoning_template_registry": "backend/app/services/system_prompts/prompts.py",
        },
    }


def _trace_from_payload(payload: Any) -> Dict[str, Any] | None:
    data = _as_dict(payload)
    trace = data.get("retrieval_decision_trace")
    if isinstance(trace, Mapping):
        return dict(trace)
    metrics = data.get("retrieval_metrics")
    if isinstance(metrics, Mapping) and isinstance(metrics.get("retrieval_decision_trace"), Mapping):
        return dict(metrics["retrieval_decision_trace"])
    return None


def _latest_retrieval_decision_trace(db: DBSession, system: System) -> Dict[str, Any] | None:
    run = (
        db.query(Run)
        .filter(Run.system_id == system.id)
        .order_by(Run.started_at.desc())
        .first()
    )
    if not run:
        return None
    trace = _trace_from_payload(run.output_ref)
    if trace:
        return {
            "run_id": run.id,
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "trace": trace,
        }
    return None


def serialize_flow_manifest(db: DBSession, system: System) -> Dict[str, Any]:
    """Return the runtime manifest backing the Flow Builder UI."""
    flow = _as_dict(system.flow_definition)
    nodes = [node for node in _as_list(flow.get("nodes")) if isinstance(node, Mapping)]
    edges = [edge for edge in _as_list(flow.get("edges")) if isinstance(edge, Mapping)]
    skill_slugs = [
        str(_as_dict(node.get("config")).get("skill_slug") or _as_dict(node.get("data")).get("skill_slug") or "")
        for node in nodes
    ]
    skills = _skill_lookup(db, skill_slugs)
    units = [_unit_for_node(node, skills) for node in nodes]
    sync_mode = "chat_runtime" if flow.get("variant") == WORKSPACE_CHAT_VARIANT else "run_engine_dag"
    live_surface = flow.get("ui", {}).get("entry_route") if isinstance(flow.get("ui"), Mapping) else None
    latest_retrieval_decision = _latest_retrieval_decision_trace(db, system) if sync_mode == "chat_runtime" else None
    return {
        "system_id": system.id,
        "system_name": system.name,
        "variant": flow.get("variant"),
        "schema_version": flow.get("schema_version"),
        "source": flow.get("source"),
        "runtime_mode": sync_mode,
        "operational_sync": sync_mode == "chat_runtime",
        "live_surface": f"/{live_surface}" if live_surface else None,
        "runtime_contract": flow.get("runtime_contract") or {},
        "prompt_contract": flow.get("prompt_contract") or {},
        "effective_config": _effective_chat_config(flow) if sync_mode == "chat_runtime" else {},
        "latest_retrieval_decision": latest_retrieval_decision,
        "unit_catalog": units,
        "summary": {
            "nodes": len(nodes),
            "edges": len(edges),
            "operational_units": sum(1 for unit in units if unit["operational"]),
            "runtime_refs": sum(1 for unit in units if unit.get("runtime_ref")),
            "skill_units": sum(1 for unit in units if unit.get("skill_slug")),
            "editable_parameters": sum(int(unit.get("parameter_count") or 0) for unit in units),
        },
        "sync_controls": {
            "chat_reads_flow_overrides": sync_mode == "chat_runtime",
            "flow_definition_persists_on_save": True,
            "versioned": True,
            "runtime_note": (
                "The /chat endpoint reads safe defaults from this flow on each turn."
                if sync_mode == "chat_runtime"
                else "Runs execute this DAG through the run_engine when triggered from the System."
            ),
        },
    }
