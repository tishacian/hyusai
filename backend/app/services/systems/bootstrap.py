"""Canonical System seed hooks.

`/intelligence` is no longer a bespoke feature page: it is a real ``System``
row bound to the ``market_signal_brief`` capability, so the frontend can
use the same SystemViewComponent to render it with the intelligence-specific
facets. This module provides the idempotent seeding hook called at startup
for every existing workspace (Vague A — P0, commit 2/5).
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session as DBSession

from app.core.logging import get_logger
from app.models.capability import Capability
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace
from app.services.client360_contract import (
    CLIENT360_AGENT_ROUTING_CONTRACT,
    CLIENT360_CAPABILITY_SLUG,
    CLIENT360_MVP_CONTRACT,
    CLIENT360_SYSTEM_VARIANT,
)

logger = get_logger(__name__)


INTELLIGENCE_SYSTEM_NAME = "News Lab"
INTELLIGENCE_OBJECTIVE = (
    "Continuous market intelligence tuned to your semantic targets. "
    "The scheduler harvests RSS feeds every hour, scores articles against "
    "your targets, and surfaces decision-grade briefs."
)
INTELLIGENCE_CAPABILITY_SLUG = "market_signal_brief"
INTELLIGENCE_SKILL_SLUG = "intelligence_batch_v1"

EXPERT_CAPTURE_SYSTEM_NAME = "Expert Knowledge Capture"
EXPERT_CAPTURE_OBJECTIVE = (
    "Run guided voice-to-voice expert interviews, retrieve live Knowledge context, "
    "evaluate each answer, and produce HITL-reviewable knowledge update proposals."
)
EXPERT_CAPTURE_CAPABILITY_SLUG = "expert_knowledge_capture"
EXPERT_CAPTURE_SKILL_SLUGS = [
    "knowledge_gap_analysis_v1",
    "expert_interview_plan_v1",
    "voice_realtime_session_v1",
    "voice_realtime_transcribe_v1",
    "voice_transcribe_v1",
    "semantic_search_v1",
    "expert_answer_evaluator_v1",
    "voice_oracle_turn_v1",
    "voice_tandem_oracle_v1",
    "voice_realtime_speak_v1",
    "capture_structuring_v1",
    "voice_tts_v1",
    "audit_log_v1",
]

WORKSPACE_CHAT_SYSTEM_NAME = "Agentium Workspace Chat"
WORKSPACE_CHAT_CAPABILITY_SLUG = "workspace_assistant"
WORKSPACE_CHAT_VARIANT = "chat_transverse_v1"
WORKSPACE_CHAT_SKILL_SLUGS = [
    "chat_trivial_bypass_v1",
    "chat_action_resolver_v1",
    "chat_grounding_policy_v1",
    "semantic_search_v1",
    "llm_rag_answer_v1",
    "chain_mixed_hah_v1",
    "claim_audit_v1",
    "audit_log_v1",
]

CLIENT360_PDR_SYSTEM_NAME = "Client360 PDR"
CLIENT360_PDR_VARIANT = CLIENT360_SYSTEM_VARIANT
CLIENT360_PDR_CAPABILITY_SLUG = CLIENT360_CAPABILITY_SLUG
CLIENT360_PDR_OBJECTIVE = (
    "Identify explainable spare-parts commercial potential, prepare human-validated "
    "AI outreach drafts and track impact for Andritz Client360 PDR. The system "
    "does not claim supervised replacement prediction or automatic stock optimization."
)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _workspace_family(workspace: Workspace) -> str:
    from app.services.workspace_features import workspace_family

    family = workspace_family(workspace)
    # The opt-in industrial layer is selected by an explicit ``industrial`` family
    # stamp. ``workspace_family`` does not (yet) list it in ``KNOWN_FAMILIES`` and
    # would fall back to the "generic" heuristic, so honour the raw stamp here
    # without widening the global family vocabulary.
    if family == "generic":
        stamped = (
            str(_as_dict(getattr(workspace, "settings", None)).get("family") or "").strip().lower()
        )
        if stamped == "industrial":
            return "industrial"
    return family


# Families that opt into the industrial layer (project/equipment guardrails +
# ``industrial_answer_policy``). Andritz maps onto it via ``family == "andritz"``;
# the universal default never carries the "project" concept.
INDUSTRIAL_FAMILIES = {"andritz", "industrial"}


def _profile_by_key(settings: dict[str, Any], key: Optional[str]) -> dict[str, Any]:
    if not key:
        return {}
    for profile in _as_list(settings.get("assistant_profiles")):
        if isinstance(profile, dict) and profile.get("key") == key:
            return dict(profile)
    return {}


def _find_profile_key(settings: dict[str, Any], preferred: list[str]) -> Optional[str]:
    keys = {
        str(profile.get("key"))
        for profile in _as_list(settings.get("assistant_profiles"))
        if isinstance(profile, dict) and profile.get("key")
    }
    for key in preferred:
        if key in keys:
            return key
    default = settings.get("assistant_profile_default")
    return str(default) if isinstance(default, str) and default else None


def _default_scope(settings: dict[str, Any], profile: dict[str, Any]) -> Optional[str]:
    scoped = profile.get("default_knowledge_scope")
    if isinstance(scoped, str) and scoped:
        return scoped
    for scope in _as_list(settings.get("knowledge_scopes")):
        if isinstance(scope, dict) and scope.get("is_default") and scope.get("key"):
            return str(scope["key"])
    for scope in _as_list(settings.get("knowledge_scopes")):
        if isinstance(scope, dict) and scope.get("key"):
            return str(scope["key"])
    return None


def _scope_config(settings: dict[str, Any], key: Optional[str]) -> dict[str, Any]:
    if not key:
        return {}
    for scope in _as_list(settings.get("knowledge_scopes")):
        if isinstance(scope, dict) and scope.get("key") == key:
            return dict(scope)
    return {}


def _workspace_chat_name(workspace: Workspace, family: str) -> str:
    if family == "andritz":
        return "Andritz Workspace Chat"
    if family == "sentinel_ci":
        return "AYA Workspace Chat"
    return WORKSPACE_CHAT_SYSTEM_NAME


def _workspace_chat_objective(workspace: Workspace, family: str) -> str:
    if family == "andritz":
        return (
            "Answer Andritz workspace questions with fast, sourced industrial grounding; "
            "preserve machine, project, part and document references; offer Deep Search "
            "when higher recall is needed."
        )
    if family == "sentinel_ci":
        return (
            "Provide AYA's always-on workspace chat for sourced executive questions, "
            "mission-room actions, grounded briefings and Deep Search escalation."
        )
    workspace_label = workspace.name or workspace.slug or "the workspace"
    return (
        f"Provide the always-on chat system for {workspace_label}: fast sourced answers, "
        "workspace actions, grounding policy and optional Deep Search."
    )


def _retrieval_defaults_for_scope(scope: dict[str, Any]) -> dict[str, Any]:
    """Derive the full retrieval funnel from the scope, not just a bare top_k.

    The chat endpoint folds these values whenever the client leaves the budget
    unset (demo-safe surfaces do), so the funnel must stay coherent on its own:
    a lone explicit top_k collapses synthesis/candidate defaults to top_k.
    Multi-pass pipelines (hah/chah) fan out query variants and need candidate
    headroom plus the balanced deadline; the fast profile clamps the pool to 20
    and strangles the RRF merge.
    """
    top_k = int(scope.get("top_k") or 6)
    mode = str(scope.get("default_mode") or "auto")
    synthesis_k = max(12, top_k * 2)
    return {
        "latency_profile": "balanced" if mode in {"hah", "chah"} else "fast",
        "retrieval_profile": "chat",
        "deep_search_enabled": True,
        "top_k": top_k,
        "source_display_k": min(max(top_k, 5), 8),
        "synthesis_k": synthesis_k,
        "candidate_pool_k": max(40, synthesis_k * 3),
        "mode": mode,
    }


def _workspace_chat_profile(workspace: Workspace) -> dict[str, Any]:
    settings = _as_dict(workspace.settings)
    family = _workspace_family(workspace)
    profile_key = _find_profile_key(
        settings,
        ["andritz_spl_advisor"]
        if family == "andritz"
        else ["vigie_executive"]
        if family == "sentinel_ci"
        else [],
    )
    profile = _profile_by_key(settings, profile_key)
    scope_key = _default_scope(settings, profile)
    scope = _scope_config(settings, scope_key)
    chat = _as_dict(settings.get("chat"))
    profile_grounding = _as_dict(profile.get("grounding"))
    grounding = profile_grounding or _as_dict(chat.get("grounding"))
    actions = {
        **_as_dict(settings.get("actions")),
        **_as_dict(profile.get("actions")),
    }

    source_policy: dict[str, Any] = {
        "mode": "workspace_scoped",
        "require_citations": True,
        "preserve_user_terms": True,
        # Universally-safe reference preservation only — NO "project" (that is an
        # opt-in industrial concept layered in below for industrial families).
        "preserve_reference_types": ["document_name", "part_number", "identifier"],
    }
    if family in INDUSTRIAL_FAMILIES:
        source_policy.update(
            {
                "mode": "industrial_grounding",
                "prefer_exact_references": True,
                "preserve_reference_types": [
                    "machine",
                    "project",
                    "part_number",
                    "document_name",
                    "table_label",
                ],
                "reject_cross_project_sources": True,
            }
        )
    elif family == "sentinel_ci":
        source_policy.update(
            {
                "mode": "executive_mission_grounding",
                "prefer_qualified_sources": True,
                "advisory_actions_require_confirmation": True,
            }
        )

    return {
        "family": family,
        "surface": "chat",
        "surface_routes": ["/chat"],
        "always_on": True,
        "quick_mode_uses_system": True,
        "assistant_profile": profile_key,
        "assistant_label": profile.get("label"),
        "knowledge_scope": scope_key,
        "collection_slugs": scope.get("collection_slugs") or [],
        "grounding": grounding,
        "actions": actions,
        "source_policy": source_policy,
        "retrieval_defaults": _retrieval_defaults_for_scope(scope),
    }


def _workspace_chat_flow_definition(
    profile: dict[str, Any], skills: dict[str, Skill]
) -> dict[str, object]:
    def prompt_contract() -> dict[str, object]:
        try:
            from app.agents.procurement_agent import BALANCED_GROUNDING_APPENDIX, SYSTEM_PROMPT
            from app.services.industrial_answer_profile import (
                default_answer_policy,
                industrial_answer_policy,
            )
            from app.services.system_prompts import SYSTEM_PROMPT_TEMPLATES, SystemPromptType

            factual_template = SYSTEM_PROMPT_TEMPLATES.get(SystemPromptType.FACTUAL, "")
        except Exception:  # noqa: BLE001 - seed must never fail because prompt modules changed.
            SYSTEM_PROMPT = (
                "You are an intelligent assistant with access to a curated knowledge base.\n\n"
                "Answer questions accurately and concisely using the retrieved context.\n"
                "When the context contains relevant information, cite it specifically.\n"
                "If no relevant context is available, say so clearly rather than guessing.\n"
                'Do not reproduce generic supplier-document footers such as "contact the supplier for more information" '
                "as advice in the chat; the workspace users are already domain experts.\n\n"
                "Be professional, precise, and helpful."
            )
            BALANCED_GROUNDING_APPENDIX = (
                "Grounding policy for this turn:\n"
                "- Use retrieved workspace context first whenever it exists.\n"
                "- If no relevant workspace context is available and the user asks for advice, explanation, drafting, "
                "planning, or general reasoning, answer from general knowledge.\n"
                "- For workspace-specific facts, documents, live/current state, numbers, actions, agenda, security/OSINT, "
                "or operational claims, do not invent."
            )
            factual_template = (
                "You are an AI assistant specialized in providing precise and factual information.\n\n"
                "Context: {context}\n\nQuestion: {question}\n\n"
                "Provide a clear factual response based on the context."
            )
            from app.services.industrial_answer_profile import (
                default_answer_policy,
                industrial_answer_policy,
            )

        # The universal default carries the domain-neutral answer policy; the
        # project/equipment industrial policy is applied only for opt-in
        # industrial families (Andritz maps onto it). This keeps the "project"
        # concept out of every other workspace and the showcase.
        is_industrial = str(profile.get("family") or "") in INDUSTRIAL_FAMILIES
        answer_policy = industrial_answer_policy() if is_industrial else default_answer_policy()
        answer_shaping_instructions = [
            'Start with the direct factual answer or synthesis; do not open with discovery phrases such as "I found" or "the documents indicate".',
            "Use numeric source ids after the answer when workspace sources exist; do not emit raw filename references as citations.",
            "For broad questions, synthesize by theme instead of listing every retrieved excerpt; use 3 to 5 key points only when useful.",
            "If retrieved content is thin or contradictory, name the gap explicitly.",
            "Do not end with generic supplier/contact boilerplate unless the user asked for contacts.",
            "For precise factual questions, answer only the requested value/reference with unit and condition when available.",
            "Never expose internal retrieval mechanics, chunk counts, scores, model names or database names in the user-facing answer.",
        ]
        if is_industrial:
            # Cross-project equipment inventories are an industrial-only concern.
            answer_shaping_instructions.insert(
                6,
                "For cross-project equipment inventories, consolidate all documented matches and do not present a partial sample as exhaustive.",
            )
        return {
            "default_prompt_type": "factual",
            "default_answer_profile": answer_policy["default_answer_profile"],
            "answer_profiles": answer_policy["profiles"],
            "answer_policy": answer_policy,
            "base_system_prompt": SYSTEM_PROMPT,
            "balanced_grounding_appendix": BALANCED_GROUNDING_APPENDIX,
            "reasoning_template_factual": factual_template,
            "rag_user_prompt_builder": "app.agents.procurement_agent._build_rag_user_prompt",
            "system_prompt_builder": "app.agents.procurement_agent._system_prompt_with_grounding",
            "answer_shaping_instructions": answer_shaping_instructions,
        }

    prompts = prompt_contract()
    retrieval_defaults = _as_dict(profile.get("retrieval_defaults"))
    source_policy = _as_dict(profile.get("source_policy"))

    def node(
        node_id: str,
        *,
        kind: str,
        node_type: str,
        label: str,
        x: int,
        y: int,
        slug: Optional[str] = None,
        data: Optional[dict[str, object]] = None,
        config: Optional[dict[str, object]] = None,
        inputs: Optional[list[dict[str, object]]] = None,
        outputs: Optional[list[dict[str, object]]] = None,
    ) -> dict[str, object]:
        skill = skills.get(slug or "")
        node_config: dict[str, object] = dict(config or {})
        if slug:
            node_config["skill_slug"] = slug
            node_config["skill_id"] = skill.id if skill else None
        if data and data.get("runtime_ref") and "runtime_ref" not in node_config:
            node_config["runtime_ref"] = data["runtime_ref"]
        return {
            "id": node_id,
            "type": node_type,
            "kind": kind,
            "label": label,
            "position": {"x": x, "y": y},
            "data": data or {},
            "config": node_config,
            "inputs": inputs or [],
            "outputs": outputs or [],
        }

    nodes: list[dict[str, object]] = [
        node(
            "chat.request",
            kind="source",
            node_type="input",
            label="/chat request",
            x=40,
            y=280,
            data={
                "description": "Streaming and non-streaming chat entrypoint.",
                "surface": "/chat",
                "routes": ["/api/v1/chat/stream", "/api/v1/chat/completion"],
                "quick_mode": True,
                "input_contract": {
                    "query": "string",
                    "agent_id": "optional System id; falls back to workspace chat System",
                    "assistant_profile": profile.get("assistant_profile"),
                    "knowledge_scope": profile.get("knowledge_scope"),
                    "grounding_mode": "strict | balanced",
                    "latency_profile": "fast | balanced | deep",
                },
            },
            outputs=[{"name": "request", "schema": "ref:chat.request"}],
        ),
        node(
            "runtime.session_system_context",
            kind="task",
            node_type="tool",
            label="Resolve session, System & Context",
            x=300,
            y=280,
            data={
                "description": "Bind the turn to the chat session, workspace chat System and selected Context.",
                "runtime_ref": "chat._ensure_chat_session + chat._resolve_system_id + chat._resolve_chat_context + chat._apply_context_to_chat_request",
                "system_fallback": "workspace_chat_system_id",
                "context_mode": "replace | combine",
                "assistant_profile": profile.get("assistant_profile"),
                "knowledge_scope": profile.get("knowledge_scope"),
            },
            inputs=[{"name": "request", "schema": "ref:chat.request"}],
            outputs=[{"name": "scoped_request", "schema": "ref:chat.request.scoped"}],
        ),
        node(
            "runtime.query_validation",
            kind="task",
            node_type="guardrail",
            label="Validate query",
            x=560,
            y=280,
            data={
                "description": "Normalize and validate the user query before routing.",
                "runtime_ref": "QueryValidator.validate",
                "empty_query_path": "safe local trivial bypass",
            },
            inputs=[{"name": "scoped_request", "schema": "ref:chat.request.scoped"}],
            outputs=[{"name": "validated_query", "schema": "string"}],
        ),
        node(
            "router.fast_exit",
            kind="decision",
            node_type="router",
            label="Fast-exit router",
            x=820,
            y=280,
            data={
                "description": "Exact runtime order before full RAG orchestration.",
                "runtime_ref": "chat.chat_stream / chat.chat_completion pre-orchestrator routing",
                "routing_order": [
                    "trivial_bypass",
                    "canonical_answer_cache",
                    "workspace_action_router",
                    "rag_orchestrator",
                ],
            },
            config={
                "branches": [
                    {
                        "label": "trivial_bypass",
                        "condition": "maybe_trivial_bypass(query) && no pending action",
                    },
                    {
                        "label": "canonical_answer",
                        "condition": "no context_id and no knowledge_scope and canonical answer match",
                    },
                    {
                        "label": "workspace_action",
                        "condition": "registry/calendar/action-plan/visual/map/vigie handler matches",
                    },
                    {"label": "rag_orchestrator", "condition": "default route"},
                ],
                "default_branch": "rag_orchestrator",
                "runtime_ref": "chat.maybe_trivial_bypass + chat._canonical_answer_hit + action handlers",
            },
            inputs=[{"name": "validated_query", "schema": "string"}],
            outputs=[{"name": "route", "schema": "string"}],
        ),
        node(
            "skill.trivial_bypass",
            kind="task",
            node_type="guardrail",
            label="Trivial bypass",
            x=1080,
            y=60,
            slug="chat_trivial_bypass_v1",
            data={
                "stage": "latency_guard",
                "description": "Handle greetings/thanks/acks locally without provider or retrieval.",
                "runtime_ref": "app.services.chat_trivial_bypass.maybe_trivial_bypass",
                "guardrails": [
                    "refuses question-like text",
                    "refuses domain/document/reference terms",
                    "refuses long messages",
                ],
            },
            inputs=[{"name": "query", "schema": "string"}],
            outputs=[{"name": "bypass", "schema": "object"}],
        ),
        node(
            "runtime.canonical_answer",
            kind="task",
            node_type="tool",
            label="Canonical answer cache",
            x=1080,
            y=180,
            data={
                "description": "Return a curated answer hit only when no Context/Knowledge Scope override is selected.",
                "runtime_ref": "chat._canonical_answer_hit",
                "side_effect": "record canonical answer hit",
            },
            inputs=[{"name": "query", "schema": "string"}],
            outputs=[{"name": "canonical_answer", "schema": "object"}],
        ),
        node(
            "skill.action_resolver",
            kind="task",
            node_type="tool",
            label="Workspace action router",
            x=1080,
            y=350,
            slug="chat_action_resolver_v1",
            data={
                "stage": "actions",
                "description": "Sequentially probes action manifests and workspace-specific handlers; side effects still require their own policy.",
                "runtime_ref": "handle_registry_chat_action -> handle_calendar_chat_action -> handle_transverse_chat_action -> handle_visual_chat_query -> handle_map_chat_query -> _vigie_executive_quick_reply",
                "actions": profile.get("actions") or {},
                "handlers": [
                    "app.services.actions.handle_registry_chat_action",
                    "app.services.workspace_calendar.handle_calendar_chat_action",
                    "app.services.actions.handle_transverse_chat_action",
                    "app.services.visual_intelligence.handle_visual_chat_query",
                    "app.services.workspace_maps.handle_map_chat_query",
                    "chat._vigie_executive_quick_reply",
                ],
            },
            inputs=[{"name": "query", "schema": "string"}],
            outputs=[{"name": "action", "schema": "object"}],
        ),
        node(
            "skill.grounding_policy",
            kind="task",
            node_type="guardrail",
            label="Grounding policy",
            x=1080,
            y=520,
            slug="chat_grounding_policy_v1",
            data={
                "stage": "grounding",
                "description": "Resolve effective strict/balanced grounding from platform, workspace, assistant profile and request.",
                "runtime_ref": "app.services.chat_grounding.resolve_grounding_policy",
                "assistant_profile": profile.get("assistant_profile"),
                "knowledge_scope": profile.get("knowledge_scope"),
                "grounding": profile.get("grounding") or {},
                "source_policy": source_policy,
            },
            inputs=[{"name": "query", "schema": "string"}],
            outputs=[{"name": "policy", "schema": "object"}],
        ),
        node(
            "runtime.settings_budget",
            kind="task",
            node_type="guardrail",
            label="Settings & latency budget",
            x=1340,
            y=520,
            data={
                "description": "Apply workspace provider/model defaults and clamp retrieval fan-out for the selected latency profile.",
                "runtime_ref": "get_resolved_settings + chat._apply_retrieval_budget_policy",
                "retrieval_defaults": retrieval_defaults,
                "provider_defaults": "workspace settings defaultProvider/defaultModel, then global settings",
                "budget_policy": {
                    "fast": {"top_k_max": 8, "candidate_pool_k_max": 20, "source_display_k_max": 8},
                    "balanced": {
                        "top_k_max": 12,
                        "candidate_pool_k_max": 80,
                        "source_display_k_max": 24,
                    },
                    "deep": {
                        "top_k_max": 24,
                        "candidate_pool_k_max": 200,
                        "source_display_k_max": 24,
                    },
                },
            },
            inputs=[{"name": "policy", "schema": "object"}],
            outputs=[{"name": "budgeted_request", "schema": "object"}],
        ),
        node(
            "runtime.orchestrator",
            kind="task",
            node_type="tool",
            label="Chat orchestrator",
            x=1600,
            y=520,
            data={
                "description": "Delegates the turn to the existing orchestrator; streams decision_step, retrieval and text chunks.",
                "runtime_ref": "get_orchestrator().process_request(request_dict)",
                "chunk_types": ["decision_step", "retrieval", "text", "error"],
            },
            inputs=[{"name": "budgeted_request", "schema": "object"}],
            outputs=[{"name": "orchestrator_chunks", "schema": "array"}],
        ),
        node(
            "skill.fast_retrieval",
            kind="task",
            node_type="retrieve",
            label="Fast retrieval",
            x=1860,
            y=430,
            slug="semantic_search_v1",
            data={
                "stage": "fast_retrieval",
                "description": "Runtime retrieval performed inside the RAG agent; surfaced here as the searchable context step.",
                "runtime_ref": "app.services.rag.context.retrieve_rag_context",
                **retrieval_defaults,
            },
            inputs=[{"name": "query", "schema": "string"}],
            outputs=[{"name": "sources", "schema": "array"}],
        ),
        node(
            "runtime.prompt_assembly",
            kind="task",
            node_type="llm",
            label="Prompt assembly",
            x=1860,
            y=600,
            data={
                "description": "Build the exact system/user prompt envelope used by RAG answer generation.",
                "runtime_ref": "procurement_agent._system_prompt_with_grounding + procurement_agent._build_rag_user_prompt",
                "prompt_contract": prompts,
            },
            inputs=[{"name": "sources", "schema": "array"}],
            outputs=[{"name": "prompt", "schema": "object"}],
        ),
        node(
            "skill.fast_answer",
            kind="task",
            node_type="llm",
            label="Fast sourced answer",
            x=2120,
            y=520,
            slug="llm_rag_answer_v1",
            data={
                "stage": "direct_answer",
                "description": "Generate the direct chat answer with markdown and citations when sources exist.",
                "runtime_ref": "app.agents.procurement_agent.RAGAgent.process",
                "latency_profile": "fast",
                "require_sources": True,
                "prompt_contract": {
                    "system_prompt": prompts["base_system_prompt"],
                    "balanced_appendix": prompts["balanced_grounding_appendix"],
                    "answer_shaping_instructions": prompts["answer_shaping_instructions"],
                },
            },
            inputs=[{"name": "prompt", "schema": "object"}],
            outputs=[{"name": "answer", "schema": "string"}],
        ),
        node(
            "runtime.deep_router",
            kind="decision",
            node_type="router",
            label="Deep Search router",
            x=2380,
            y=520,
            data={
                "description": "Decide whether the fast answer is enough or should queue/manual-route to Deep Search.",
                "runtime_ref": "chat._should_queue_auto_deep_retrieval + Deep Search button payload",
            },
            config={
                "branches": [
                    {
                        "label": "fast_finalize",
                        "condition": "no deep recommendation or direct answer sufficient",
                    },
                    {
                        "label": "queue_deep_search",
                        "condition": "retrieval degraded or Deep Search requested",
                    },
                ],
                "default_branch": "fast_finalize",
                "runtime_ref": "chat._queue_auto_deep_retrieval_job",
            },
            inputs=[{"name": "answer", "schema": "string"}],
            outputs=[{"name": "route", "schema": "string"}],
        ),
        node(
            "skill.deep_search",
            kind="task",
            node_type="tool",
            label="Deep Search job",
            x=2640,
            y=660,
            slug="chain_mixed_hah_v1",
            data={
                "stage": "deep_search",
                "description": "Async deep retrieval/synthesis job; the direct answer remains fast while the user can push harder.",
                "runtime_ref": "chat._queue_auto_deep_retrieval_job + app.services.worker_deep_retrieval",
                "latency_profile": "deep",
                "manual_trigger": True,
                "auto_trigger": "only when retrieval policy recommends it",
            },
            inputs=[{"name": "query", "schema": "string"}],
            outputs=[{"name": "deep_answer", "schema": "string"}],
        ),
        node(
            "runtime.response_validation",
            kind="task",
            node_type="guardrail",
            label="Validate response",
            x=2640,
            y=400,
            data={
                "description": "Validate non-empty response and preserve markdown/source metadata for the chat renderer.",
                "runtime_ref": "ResponseValidator.validate + chat._collect_chat_chunk",
                "render_contract": "markdown_with_numeric_sources",
            },
            inputs=[{"name": "answer", "schema": "string"}],
            outputs=[{"name": "validated_answer", "schema": "string"}],
        ),
        node(
            "skill.answer_audit",
            kind="task",
            node_type="tool",
            label="Run ledger and audit",
            x=2900,
            y=520,
            slug="audit_log_v1",
            data={
                "stage": "audit",
                "description": "Persist messages, Run output_ref, retrieval metrics, selected sources and eval scheduling.",
                "runtime_ref": "chat._persist_chat_run + schedule_eval",
                "record_run": True,
                "record_sources": True,
                "record_grounding_policy": True,
                "record_retrieval_metrics": True,
            },
            inputs=[{"name": "answer", "schema": "string"}],
            outputs=[{"name": "run", "schema": "object"}],
        ),
        node(
            "skill.claim_audit",
            kind="task",
            node_type="guardrail",
            label="Async evaluation",
            x=3160,
            y=660,
            slug="claim_audit_v1",
            data={
                "description": "Best-effort quality loop attached to the persisted Run.",
                "runtime_ref": "app.services.evaluation.auto_eval.schedule_eval",
                "async": True,
            },
            inputs=[{"name": "run", "schema": "object"}],
            outputs=[{"name": "evaluation", "schema": "object"}],
        ),
        node(
            "runtime.shortcut_persist",
            kind="task",
            node_type="tool",
            label="Persist shortcut response",
            x=1340,
            y=180,
            data={
                "description": "Persist trivial, canonical or action responses with the same Run ledger contract.",
                "runtime_ref": "chat._persist_trivial_bypass_turn + chat._persist_chat_run",
                "triggers": [
                    "trivial_bypass",
                    "canonical_answer",
                    "action_registry",
                    "calendar_action",
                    "action_plan",
                    "visual_observation",
                    "map_command",
                    "vigie_quick_brief",
                ],
            },
            inputs=[{"name": "shortcut_response", "schema": "object"}],
            outputs=[{"name": "run", "schema": "object"}],
        ),
        node(
            "chat.response",
            kind="sink",
            node_type="output",
            label="Chat response",
            x=3420,
            y=520,
            data={
                "description": "Return text/SSE chunks to the chat bubble and source chips.",
                "surface": "/chat",
                "render": "markdown_with_sources",
                "response_contract": {
                    "content": "markdown",
                    "sources": "source chips and numeric citations",
                    "run_id": "Run ledger id",
                    "deep_job": "optional async refinement job",
                },
            },
            inputs=[{"name": "run", "schema": "object"}],
        ),
    ]
    edges = [
        {
            "from": "chat.request",
            "to": "runtime.session_system_context",
            "kind": "data",
            "label": "request",
        },
        {
            "from": "runtime.session_system_context",
            "to": "runtime.query_validation",
            "kind": "data",
        },
        {"from": "runtime.query_validation", "to": "router.fast_exit", "kind": "data"},
        {
            "from": "router.fast_exit",
            "to": "skill.trivial_bypass",
            "kind": "branch",
            "branch_label": "trivial_bypass",
        },
        {
            "from": "router.fast_exit",
            "to": "runtime.canonical_answer",
            "kind": "branch",
            "branch_label": "canonical_answer",
        },
        {
            "from": "router.fast_exit",
            "to": "skill.action_resolver",
            "kind": "branch",
            "branch_label": "workspace_action",
        },
        {"from": "skill.trivial_bypass", "to": "runtime.shortcut_persist", "kind": "data"},
        {"from": "runtime.canonical_answer", "to": "runtime.shortcut_persist", "kind": "data"},
        {"from": "skill.action_resolver", "to": "runtime.shortcut_persist", "kind": "data"},
        {
            "from": "router.fast_exit",
            "to": "skill.grounding_policy",
            "kind": "branch",
            "branch_label": "rag_orchestrator",
        },
        {"from": "skill.grounding_policy", "to": "runtime.settings_budget", "kind": "data"},
        {"from": "runtime.settings_budget", "to": "runtime.orchestrator", "kind": "data"},
        {
            "from": "runtime.orchestrator",
            "to": "skill.fast_retrieval",
            "kind": "data",
            "label": "retrieval chunk",
        },
        {"from": "skill.fast_retrieval", "to": "runtime.prompt_assembly", "kind": "data"},
        {"from": "runtime.prompt_assembly", "to": "skill.fast_answer", "kind": "data"},
        {"from": "skill.fast_answer", "to": "runtime.deep_router", "kind": "data"},
        {
            "from": "runtime.deep_router",
            "to": "runtime.response_validation",
            "kind": "branch",
            "branch_label": "fast_finalize",
        },
        {
            "from": "runtime.deep_router",
            "to": "skill.deep_search",
            "kind": "branch",
            "branch_label": "queue_deep_search",
        },
        {"from": "skill.deep_search", "to": "skill.answer_audit", "kind": "data"},
        {"from": "runtime.response_validation", "to": "skill.answer_audit", "kind": "data"},
        {"from": "runtime.shortcut_persist", "to": "chat.response", "kind": "data"},
        {
            "from": "skill.answer_audit",
            "to": "skill.claim_audit",
            "kind": "control",
            "label": "async eval",
        },
        {"from": "skill.answer_audit", "to": "chat.response", "kind": "data"},
    ]
    return {
        "variant": WORKSPACE_CHAT_VARIANT,
        "source": "system_seed",
        "template_id": WORKSPACE_CHAT_VARIANT,
        "template_name": "Workspace Chat Transverse",
        "schema_version": 3,
        "nodes": nodes,
        "edges": edges,
        "ui": {
            "type": "workspace_chat",
            "entry_route": "chat",
            "surface_routes": ["/chat"],
            "primary_action": "Open chat",
            "flow_builder_enabled": True,
        },
        "runtime_contract": {
            "surface": "/chat",
            "entrypoints": ["POST /api/v1/chat/stream", "POST /api/v1/chat/completion"],
            "source_of_truth": "backend/app/api/v1/endpoints/chat.py",
            "orchestrator": "app.api.v1.endpoints.agents.get_orchestrator().process_request",
            "answer_agent": "app.agents.procurement_agent.RAGAgent",
            "deep_search_worker": "app.services.worker_deep_retrieval",
            "routes_are_runtime": True,
        },
        "prompt_contract": prompts,
        "chat": profile,
        "collections": profile.get("collection_slugs") or [],
        "rag_mode": retrieval_defaults.get("mode") or "auto",
        "canonical_rag_mode": retrieval_defaults.get("mode") or "auto",
        "policy": {
            "require_citations": True,
            "enable_audit": True,
            "max_latency_ms": 8000,
            "confidence_threshold": 0.65,
        },
    }


def _find_workspace_chat_system(db: DBSession, workspace_id: str) -> Optional[System]:
    # Deterministic (oldest first) and retired-aware: archived duplicates must
    # never be resurrected, and concurrent callers must agree on the same row.
    rows = (
        db.query(System)
        .filter(System.workspace_id == workspace_id, System.status != "retired")
        .order_by(System.created_at.asc())
        .all()
    )
    for system in rows:
        flow = _as_dict(system.flow_definition)
        settings = _as_dict(getattr(system, "settings", None))
        if flow.get("variant") == WORKSPACE_CHAT_VARIANT:
            return system
        if settings.get("system_type") == "workspace_chat":
            return system
    return next((s for s in rows if s.name == WORKSPACE_CHAT_SYSTEM_NAME), None)


def _dedupe_seeded_chat_systems(db: DBSession, workspace_id: str) -> int:
    """Anti-double-seed guard: archive seed-created workspace-chat duplicates.

    The seed find-or-create has a check-then-act window, so a concurrent boot +
    ``/knowledge/scopes`` request race can insert two identical
    ``chat_transverse_v1`` systems (observed: rows 2 ms apart). Keep the oldest
    seed-created chat and ``retired`` the rest. The keep is deterministic
    (oldest, then id), so concurrent callers converge instead of retiring each
    other. Only rows the seed itself created are touched — manually-built or
    other-variant (e.g. agentic) chats are never affected.
    """
    rows = (
        db.query(System)
        .filter(
            System.workspace_id == workspace_id,
            System.status != "retired",
            System.created_by.like("system:workspace_chat_seed%"),
        )
        .order_by(System.created_at.asc(), System.id.asc())
        .all()
    )
    chat_rows = [
        s for s in rows if _as_dict(s.flow_definition).get("variant") == WORKSPACE_CHAT_VARIANT
    ]
    retired = 0
    for system in chat_rows[1:]:
        system.status = "retired"
        retired += 1
    if retired:
        logger.info(
            "workspace_chat_system.dedupe.retired",
            workspace_id=workspace_id,
            retired=retired,
            kept=chat_rows[0].id if chat_rows else None,
        )
    return retired


def workspace_chat_system_id(db: DBSession, workspace_id: str) -> Optional[str]:
    """Return the canonical always-on chat System id for a workspace."""
    system = _find_workspace_chat_system(db, workspace_id)
    return system.id if system else None


def resolve_workspace_chat_source_policy(
    db: DBSession,
    workspace: Workspace,
    *,
    system: Optional[System] = None,
) -> dict[str, Any]:
    """Resolve the effective chat ``source_policy`` for a workspace.

    Layers the workspace chat System policy (its ``settings.source_policy``,
    then its ``flow_definition.source_policy``) over the workspace-level
    ``settings.source_policy``. The System level wins (parity with ``/chat``),
    while the workspace level only fills keys the System leaves unset, so a flag
    such as ``expert_fiche_correction_enabled`` is honoured whether an operator
    sets it on the chat System or on the workspace settings (the location the
    chat frontend reads). Returns ``{}`` when neither defines a policy.

    ``system`` may be passed to avoid a redundant lookup when the caller has
    already loaded the workspace chat System.
    """
    if system is None:
        system = _find_workspace_chat_system(db, workspace.id)
    system_policy: dict[str, Any] = {}
    if system is not None:
        system_policy = _as_dict(_as_dict(system.settings).get("source_policy")) or _as_dict(
            _as_dict(system.flow_definition).get("source_policy")
        )
    workspace_policy = _as_dict(_as_dict(getattr(workspace, "settings", None)).get("source_policy"))
    return {**workspace_policy, **system_policy}


# Expert-correction source_policy keys that an admin can toggle from the UI and
# that must stay authoritative through ``resolve_workspace_chat_source_policy``
# (which lets the chat System policy SHADOW the workspace one).
EXPERT_CORRECTION_POLICY_KEYS = (
    "expert_fiche_correction_enabled",
    "expert_review_required",
)


def sync_chat_system_expert_correction_policy(
    db: DBSession,
    workspace: Workspace,
    *,
    keys: tuple[str, ...] = EXPERT_CORRECTION_POLICY_KEYS,
) -> Optional[System]:
    """Mirror the workspace expert-correction ``source_policy`` flags onto the chat System.

    ``resolve_workspace_chat_source_policy`` layers the chat System
    ``settings.source_policy`` OVER the workspace ``settings.source_policy``
    (System wins, for parity with ``/chat``). An admin toggle that wrote only the
    workspace level would therefore be silently shadowed by a System-level flag
    (exactly the state migration ``042_andritz_disable_review`` produces). This
    helper converges the two layers for the expert-correction keys — the same way
    that migration writes BOTH — so the merged backend read always matches the
    workspace-level value the frontend CTA reads.

    Only keys explicitly present in the workspace ``source_policy`` are synced, so
    unrelated settings saves never clobber an existing System-level flag. Returns
    the chat System it inspected (or ``None`` when the workspace has none).
    """
    workspace_policy = _as_dict(_as_dict(getattr(workspace, "settings", None)).get("source_policy"))
    system = _find_workspace_chat_system(db, workspace.id)
    if system is None:
        return None
    system_settings = _as_dict(system.settings)
    system_policy = _as_dict(system_settings.get("source_policy"))
    changed = False
    for key in keys:
        if key not in workspace_policy:
            continue
        if system_policy.get(key) != workspace_policy[key]:
            system_policy[key] = workspace_policy[key]
            changed = True
    if not changed:
        return system
    system_settings["source_policy"] = system_policy
    system.settings = system_settings
    db.commit()
    db.refresh(system)
    logger.info(
        "workspace_chat_system.expert_correction_policy.synced",
        workspace_id=workspace.id,
        system_id=system.id,
        source_policy={k: system_policy.get(k) for k in keys if k in system_policy},
    )
    return system


def ensure_workspace_chat_system_default(db: DBSession, workspace_id: str) -> Optional[System]:
    """Create or refresh the workspace's always-on chat System.

    This is the `/chat` backing System: the UI can keep the friendly
    "Quick ask" label while runs and Flow Builder edits are attached to a real
    System row. The helper is idempotent and only specializes the profile from
    workspace settings; it does not hardcode a document collection.
    """
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        return None

    capability = (
        db.query(Capability).filter(Capability.slug == WORKSPACE_CHAT_CAPABILITY_SLUG).first()
    )
    if not capability:
        logger.warning(
            "workspace_chat_system_seed.skip.missing_capability",
            workspace_id=workspace_id,
            slug=WORKSPACE_CHAT_CAPABILITY_SLUG,
        )
        return None

    skills = _skill_lookup(db, WORKSPACE_CHAT_SKILL_SLUGS)
    skill_ids = [skills[slug].id for slug in WORKSPACE_CHAT_SKILL_SLUGS if slug in skills]
    family = _workspace_family(workspace)
    profile = _workspace_chat_profile(workspace)
    flow_definition = _workspace_chat_flow_definition(profile, skills)
    system_settings = {
        "system_type": "workspace_chat",
        "always_on": True,
        "surface": "chat",
        "surface_routes": ["/chat"],
        "quick_mode_uses_system": True,
        "family": family,
        "assistant_profile": profile.get("assistant_profile"),
        "knowledge_scope": profile.get("knowledge_scope"),
        "retrieval_defaults": profile.get("retrieval_defaults") or {},
        "source_policy": profile.get("source_policy") or {},
    }

    existing = _find_workspace_chat_system(db, workspace_id)
    if existing:
        existing.name = _workspace_chat_name(workspace, family)
        existing.objective = existing.objective or _workspace_chat_objective(workspace, family)
        existing.capability_id = capability.id
        existing.skill_ids = skill_ids
        existing.flow_definition = flow_definition
        existing.settings = {**_as_dict(existing.settings), **system_settings}
        existing.execution_mode = "real_time_decision"
        existing.execution_profile = {
            "surface": "chat",
            "latency_profile": "fast",
            "fast_answer_target_ms": 4500,
            "deep_search": "manual_escalation",
            "durability": "run_ledger",
        }
        existing.coordination_pattern = "single_agent"
        existing.status = "active"
        existing.default_prompt_type = existing.default_prompt_type or "factual"
        existing.retrieval_mode_default = (
            _as_dict(profile.get("retrieval_defaults")).get("mode")
            or existing.retrieval_mode_default
            or "auto"
        )
        _dedupe_seeded_chat_systems(db, workspace_id)
        db.commit()
        db.refresh(existing)
        return existing

    system = System(
        workspace_id=workspace_id,
        name=_workspace_chat_name(workspace, family),
        objective=_workspace_chat_objective(workspace, family),
        capability_id=capability.id,
        skill_ids=skill_ids,
        flow_definition=flow_definition,
        settings=system_settings,
        execution_mode="real_time_decision",
        execution_profile={
            "surface": "chat",
            "latency_profile": "fast",
            "fast_answer_target_ms": 4500,
            "deep_search": "manual_escalation",
            "durability": "run_ledger",
        },
        coordination_pattern="single_agent",
        status="active",
        created_by="system:workspace_chat_seed",
        default_prompt_type="factual",
        retrieval_mode_default=_as_dict(profile.get("retrieval_defaults")).get("mode") or "auto",
    )
    db.add(system)
    db.commit()
    db.refresh(system)
    # A concurrent caller may have inserted an identical chat in the check-then-act
    # window; collapse to the deterministic keep so /systems never shows the pair.
    if _dedupe_seeded_chat_systems(db, workspace_id):
        db.commit()
    logger.info(
        "workspace_chat_system_seed.created",
        workspace_id=workspace_id,
        system_id=system.id,
        capability_id=capability.id,
        family=family,
    )
    return system


def ensure_workspace_chat_system_for_all_workspaces(db: DBSession) -> dict[str, int]:
    report = {"created": 0, "skipped": 0, "already": 0}
    workspaces = (
        db.query(Workspace)
        .filter(Workspace.is_active.is_(True), Workspace.deleted_at.is_(None))
        .all()
    )
    for ws in workspaces:
        before = 1 if _find_workspace_chat_system(db, ws.id) else 0
        system = ensure_workspace_chat_system_default(db, ws.id)
        if system is None:
            report["skipped"] += 1
        elif before == 0:
            report["created"] += 1
        else:
            report["already"] += 1
    return report


def _ensure_client360_capability(db: DBSession) -> Capability:
    capability = (
        db.query(Capability).filter(Capability.slug == CLIENT360_PDR_CAPABILITY_SLUG).first()
    )
    payload = {
        "name": "Client360 PDR Opportunity Engine",
        "description": (
            "Explainable spare-parts commercial potential, mail draft and impact tracking "
            "for Andritz Client360 PDR."
        ),
        "tier": "client",
        "industry": "industrial_nonwovens",
        "input_unit": "data_source",
        "output_unit": "opportunity",
        "skill_ids": [],
        "pricing": {"unit": "per_outcome", "unit_price": 0.0, "currency": "EUR"},
        "confidence_threshold": 0.55,
        "sla": {"latency": "interactive", "human_validation_required": True},
        "roi_model": {},
        "is_seeded": "Y",
    }
    if capability:
        for key, value in payload.items():
            setattr(capability, key, value)
        db.flush()
        return capability
    capability = Capability(slug=CLIENT360_PDR_CAPABILITY_SLUG, **payload)
    db.add(capability)
    db.flush()
    return capability


def _client360_flow_definition() -> dict[str, Any]:
    return {
        "variant": CLIENT360_PDR_VARIANT,
        "schema_version": 2,
        "source": "system_seed",
        "template_id": CLIENT360_PDR_VARIANT,
        "template_name": "Client360 PDR",
        "product_contract": CLIENT360_MVP_CONTRACT,
        "agent_routing": CLIENT360_AGENT_ROUTING_CONTRACT,
        "nodes": [
            {"id": "source.data_sources", "type": "source", "label": "SFTP / Knowledge sources"},
            {"id": "task.mapping", "type": "task", "label": "SAP material -> PDR family mapping"},
            {"id": "task.potential_engine", "type": "task", "label": "Explainable PDR potential"},
            {"id": "task.campaign_segment", "type": "task", "label": "Light campaign segment"},
            {
                "id": "agent.mail_writer",
                "type": "agent",
                "label": "Client360 PDR mail writer",
                "route_id": CLIENT360_AGENT_ROUTING_CONTRACT["mail_draft"]["route_id"],
            },
            {"id": "sink.impact_tracking", "type": "sink", "label": "Campaign impact loop"},
        ],
        "edges": [
            {"from": "source.data_sources", "to": "task.mapping"},
            {"from": "task.mapping", "to": "task.potential_engine"},
            {"from": "task.potential_engine", "to": "task.campaign_segment"},
            {"from": "task.campaign_segment", "to": "agent.mail_writer"},
            {"from": "agent.mail_writer", "to": "sink.impact_tracking"},
        ],
        "ui": {
            "type": "client360_pdr",
            "entry_route": "client360",
            "surface_routes": ["/client360"],
            "primary_action": "Open Client360 PDR",
            "flow_builder_enabled": False,
        },
        "runtime_contract": {
            "surface": "/client360",
            "entrypoints": [
                "GET /api/v1/client360/summary",
                "GET /api/v1/client360/opportunities",
                "PATCH /api/v1/client360/opportunities/{id}",
                "GET /api/v1/client360/mappings",
                "POST /api/v1/client360/engines/opportunities/run",
                "POST /api/v1/client360/mail-drafts",
                "PATCH /api/v1/client360/actions/{id}",
                "POST /api/v1/client360/actions/{id}/impact",
            ],
            "engines": [
                "source_discovery",
                "sap_pdr_mapping",
                "opportunity_generation",
                "potential_scoring",
                "mail_draft_generation",
                "impact_learning_loop",
            ],
            "prediction_policy": "explainable_potential_only",
            "email_send_policy": "manual_only",
            "model_policy": CLIENT360_AGENT_ROUTING_CONTRACT["mail_draft"][
                "model_resolution_order"
            ],
            "mvp_in_scope": CLIENT360_MVP_CONTRACT["mvp_in_scope"],
            "deferred_scope": CLIENT360_MVP_CONTRACT["deferred_scope"],
        },
    }


def _find_client360_system(db: DBSession, workspace_id: str) -> Optional[System]:
    rows = (
        db.query(System)
        .filter(System.workspace_id == workspace_id, System.status != "retired")
        .order_by(System.created_at.asc())
        .all()
    )
    for system in rows:
        flow = _as_dict(system.flow_definition)
        settings = _as_dict(getattr(system, "settings", None))
        if (
            flow.get("variant") == CLIENT360_PDR_VARIANT
            or settings.get("system_type") == "client360_pdr"
        ):
            return system
    return next((s for s in rows if s.name == CLIENT360_PDR_SYSTEM_NAME), None)


def _ensure_client360_navigation_profile(workspace: Workspace) -> None:
    settings = _as_dict(getattr(workspace, "settings", None))
    profile = _as_dict(settings.get("navigation_profile"))
    if profile.get("key") != "business_end_user":
        return
    surfaces = [
        str(item)
        for item in _as_list(profile.get("primary_surfaces"))
        if isinstance(item, str) and item.strip()
    ]
    if "client360-pdr" not in surfaces:
        insert_at = surfaces.index("chat") + 1 if "chat" in surfaces else 0
        surfaces.insert(insert_at, "client360-pdr")
    profile["primary_surfaces"] = surfaces or ["chat", "client360-pdr", "knowledge-capture"]
    profile["default_route"] = profile.get("default_route") or "/chat"
    profile["advanced_access"] = profile.get("advanced_access") or "admin_only"
    settings["navigation_profile"] = profile
    workspace.settings = settings


def ensure_client360_pdr_system_default(db: DBSession, workspace_id: str) -> Optional[System]:
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace or workspace.slug != "andritz":
        return None

    _ensure_client360_navigation_profile(workspace)
    capability = _ensure_client360_capability(db)
    flow_definition = _client360_flow_definition()
    system_settings = {
        "system_type": "client360_pdr",
        "surface": "client360",
        "surface_routes": ["/client360"],
        "family": "andritz",
        "product_contract": CLIENT360_MVP_CONTRACT,
        "agent_routing": CLIENT360_AGENT_ROUTING_CONTRACT,
        "client360_pdr_mail": {
            "ai_enabled": True,
            "route_id": CLIENT360_AGENT_ROUTING_CONTRACT["mail_draft"]["route_id"],
            "model_resolution": "agentium_system_capability_workspace",
            "manual_send_only": True,
        },
        "human_validation_required": True,
        "no_automatic_email_send": True,
        "prediction_policy": "explainable_potential_only",
        "deferred_scope": CLIENT360_MVP_CONTRACT["deferred_scope"],
    }
    existing = _find_client360_system(db, workspace_id)
    if existing:
        existing_settings = _as_dict(existing.settings)
        preserved_mail_settings = _as_dict(existing_settings.get("client360_pdr_mail"))
        merged_settings = {**existing_settings, **system_settings}
        merged_settings["client360_pdr_mail"] = {
            **_as_dict(system_settings.get("client360_pdr_mail")),
            **preserved_mail_settings,
        }
        existing.name = CLIENT360_PDR_SYSTEM_NAME
        existing.objective = CLIENT360_PDR_OBJECTIVE
        existing.capability_id = capability.id
        existing.skill_ids = []
        existing.flow_definition = flow_definition
        existing.settings = merged_settings
        existing.execution_mode = "human_augmented"
        existing.execution_profile = {
            "surface": "client360",
            "durability": "database",
            "email_send": "manual_only",
        }
        existing.coordination_pattern = "single_agent"
        existing.status = "active"
        existing.default_prompt_type = existing.default_prompt_type or "factual"
        existing.retrieval_mode_default = existing.retrieval_mode_default or "auto"
        db.commit()
        db.refresh(existing)
        return existing

    system = System(
        workspace_id=workspace_id,
        name=CLIENT360_PDR_SYSTEM_NAME,
        objective=CLIENT360_PDR_OBJECTIVE,
        capability_id=capability.id,
        skill_ids=[],
        flow_definition=flow_definition,
        settings=system_settings,
        execution_mode="human_augmented",
        execution_profile={
            "surface": "client360",
            "durability": "database",
            "email_send": "manual_only",
        },
        coordination_pattern="single_agent",
        status="active",
        created_by="system:client360_pdr_seed",
        default_prompt_type="factual",
        retrieval_mode_default="auto",
    )
    db.add(system)
    db.commit()
    db.refresh(system)
    logger.info("client360_pdr_system_seed.created", workspace_id=workspace_id, system_id=system.id)
    return system


def ensure_client360_pdr_system_for_all_workspaces(db: DBSession) -> dict[str, int]:
    report = {"created": 0, "skipped": 0, "already": 0}
    workspaces = (
        db.query(Workspace)
        .filter(Workspace.is_active.is_(True), Workspace.deleted_at.is_(None))
        .all()
    )
    for ws in workspaces:
        if ws.slug != "andritz":
            report["skipped"] += 1
            continue
        before = 1 if _find_client360_system(db, ws.id) else 0
        system = ensure_client360_pdr_system_default(db, ws.id)
        if system is None:
            report["skipped"] += 1
        elif before == 0:
            report["created"] += 1
        else:
            report["already"] += 1
    return report


def ensure_intelligence_system_default(db: DBSession, workspace_id: str) -> Optional[System]:
    """Create the workspace's default Intelligence System if missing.

    Idempotent on ``(workspace_id, capability_id, name=INTELLIGENCE_SYSTEM_NAME)``.
    Returns the (existing or newly created) System, or ``None`` if the
    required capability/skill haven't been seeded yet.
    """
    capability = (
        db.query(Capability).filter(Capability.slug == INTELLIGENCE_CAPABILITY_SLUG).first()
    )
    if not capability:
        logger.warning(
            "intel_system_seed.skip.missing_capability",
            workspace_id=workspace_id,
            slug=INTELLIGENCE_CAPABILITY_SLUG,
        )
        return None

    skill = db.query(Skill).filter(Skill.slug == INTELLIGENCE_SKILL_SLUG).first()
    skill_ids: list[str] = [skill.id] if skill else []

    existing = (
        db.query(System)
        .filter(
            System.workspace_id == workspace_id,
            System.capability_id == capability.id,
            System.name == INTELLIGENCE_SYSTEM_NAME,
        )
        .first()
    )
    if existing:
        # Lightweight refresh so flow_definition.variant stays in sync even
        # if an older seed produced a bare row.
        flow = dict(existing.flow_definition or {})
        if flow.get("variant") != "intelligence":
            flow["variant"] = "intelligence"
            flow.setdefault("nodes", [])
            flow.setdefault("edges", [])
            existing.flow_definition = flow
            db.commit()
        return existing

    flow_definition: dict[str, object] = {
        "variant": "intelligence",
        "nodes": [
            {
                "id": "source.feeds",
                "type": "source",
                "label": "RSS feeds",
            },
            {
                "id": "skill.intelligence_batch_v1",
                "type": "skill",
                "skill_slug": INTELLIGENCE_SKILL_SLUG,
                "label": "Intelligence batch",
            },
            {
                "id": "sink.brief",
                "type": "sink",
                "label": "Decision-grade brief",
            },
        ],
        "edges": [
            {"from": "source.feeds", "to": "skill.intelligence_batch_v1"},
            {"from": "skill.intelligence_batch_v1", "to": "sink.brief"},
        ],
    }

    system = System(
        workspace_id=workspace_id,
        name=INTELLIGENCE_SYSTEM_NAME,
        objective=INTELLIGENCE_OBJECTIVE,
        capability_id=capability.id,
        skill_ids=skill_ids,
        flow_definition=flow_definition,
        execution_mode="continuous_monitoring",
        coordination_pattern="single_agent",
        status="active",
        created_by="system:intelligence_seed",
        retrieval_mode_default="auto",
    )
    db.add(system)
    db.commit()
    db.refresh(system)

    logger.info(
        "intel_system_seed.created",
        workspace_id=workspace_id,
        system_id=system.id,
        capability_id=capability.id,
    )
    return system


def ensure_intelligence_system_for_all_workspaces(
    db: DBSession,
) -> dict[str, int]:
    """Ensure every active workspace has its Intelligence System seeded.

    Safe to call on every boot — the per-workspace helper is idempotent.
    Returns a small report (``{"created": N, "skipped": M}``) so the startup
    log stays readable.
    """
    report = {"created": 0, "skipped": 0, "already": 0}
    workspaces = (
        db.query(Workspace)
        .filter(Workspace.is_active.is_(True), Workspace.deleted_at.is_(None))
        .all()
    )
    for ws in workspaces:
        before = (
            db.query(System)
            .filter(
                System.workspace_id == ws.id,
                System.name == INTELLIGENCE_SYSTEM_NAME,
            )
            .count()
        )
        system = ensure_intelligence_system_default(db, ws.id)
        if system is None:
            report["skipped"] += 1
        elif before == 0:
            report["created"] += 1
        else:
            report["already"] += 1
    return report


def _skill_lookup(db: DBSession, slugs: list[str]) -> dict[str, Skill]:
    rows = db.query(Skill).filter(Skill.slug.in_(slugs)).all()
    return {skill.slug: skill for skill in rows}


def _expert_capture_flow_definition(skills: dict[str, Skill]) -> dict[str, object]:
    def task(
        node_id: str,
        *,
        slug: str,
        label: str,
        x: int,
        y: int,
        inputs_map: Optional[dict[str, str]] = None,
        outputs_map: Optional[dict[str, str]] = None,
        data: Optional[dict[str, object]] = None,
    ) -> dict[str, object]:
        skill = skills.get(slug)
        return {
            "id": node_id,
            "type": "skill",
            "kind": "task",
            "label": label,
            "position": {"x": x, "y": y},
            "data": data or {},
            "config": {
                "skill_id": skill.id if skill else None,
                "skill_slug": slug,
                "inputs_map": inputs_map or {},
                "outputs_map": outputs_map or {},
            },
        }

    nodes: list[dict[str, object]] = [
        {
            "id": "capture.session_request",
            "type": "source",
            "kind": "source",
            "label": "Capture session request",
            "position": {"x": 40, "y": 220},
            "data": {
                "menu": "Objective",
                "description": "Objective, expert profile, duration and Knowledge Context selected from /knowledge/capture.",
            },
            "outputs": [
                {"name": "objective", "schema": "string", "required": True},
                {"name": "context", "schema": "object"},
            ],
        },
        task(
            "skill.knowledge_gap_analysis",
            slug="knowledge_gap_analysis_v1",
            label="Identify tacit knowledge gaps",
            x=340,
            y=100,
            inputs_map={"objective": "session.objective", "context": "session.context"},
            outputs_map={"gaps": "capture.gaps"},
            data={"menu": "Plan", "phase": "preflight"},
        ),
        task(
            "skill.expert_interview_plan",
            slug="expert_interview_plan_v1",
            label="Build interview plan",
            x=640,
            y=100,
            inputs_map={"objective": "session.objective", "gaps": "capture.gaps"},
            outputs_map={"plan": "capture.plan"},
            data={"menu": "Plan", "phase": "preflight"},
        ),
        task(
            "skill.voice_realtime_session",
            slug="voice_realtime_session_v1",
            label="Resolve voice runtime",
            x=940,
            y=100,
            inputs_map={"provider": "system.voice_runtime.provider"},
            outputs_map={"provider": "turn.voice_provider", "events": "turn.voice_events"},
            data={
                "menu": "Voice",
                "runtime": "cascade_openai",
                "capability": "voice2voice_interaction",
            },
        ),
        task(
            "skill.voice_transcribe",
            slug="voice_realtime_transcribe_v1",
            label="Realtime / cascade transcript",
            x=1240,
            y=100,
            inputs_map={"audio_ref": "turn.audio_ref"},
            outputs_map={"transcript": "turn.transcript"},
            data={
                "menu": "Voice",
                "runtime": "cascade_openai",
                "supports": ["text.partial", "text.final", "barge_in"],
            },
        ),
        task(
            "skill.semantic_search_prefetch",
            slug="semantic_search_v1",
            label="Pseudo realtime retrieval prefetch",
            x=1540,
            y=100,
            inputs_map={
                "query": "turn.partial_transcript",
                "collection": "context.environment_state.collection",
            },
            outputs_map={"results": "turn.retrieval_refs"},
            data={"menu": "Knowledge", "mode": "chah", "top_k": 4, "timeout_ms": 2500},
        ),
        task(
            "skill.expert_answer_evaluator",
            slug="expert_answer_evaluator_v1",
            label="Evaluate answer / correction",
            x=1840,
            y=100,
            inputs_map={
                "answer": "turn.final_transcript",
                "question": "capture.current_question",
                "gap": "capture.current_gap",
            },
            outputs_map={"evaluation": "turn.evaluation"},
            data={"menu": "Evaluation", "phase": "turn"},
        ),
        task(
            "skill.voice_tandem_oracle",
            slug="voice_tandem_oracle_v1",
            label="Tandem oracle loop",
            x=2140,
            y=20,
            inputs_map={
                "partial_text": "turn.partial_transcript",
                "final_text": "turn.final_transcript",
                "evaluation": "turn.evaluation",
                "sources": "turn.retrieval_refs",
            },
            outputs_map={"events": "turn.oracle_events", "committed": "turn.oracle_committed"},
            data={
                "menu": "Voice",
                "pattern": "Realtime loop + Background oracle",
                "events": ["oracle.delta", "oracle.superseded", "oracle.action", "oracle.commit"],
            },
        ),
        task(
            "skill.voice_oracle_turn",
            slug="voice_oracle_turn_v1",
            label="Commit voice action",
            x=2440,
            y=100,
            inputs_map={
                "answer": "turn.final_transcript",
                "question": "capture.current_question",
                "gap": "capture.current_gap",
            },
            outputs_map={"action": "turn.voice_action"},
            data={"menu": "Voice", "events": ["oracle.action", "runtime.metric"]},
        ),
        {
            "id": "decision.answer_route",
            "type": "custom",
            "kind": "decision",
            "label": "Route next action",
            "position": {"x": 2740, "y": 100},
            "data": {"menu": "Conversation-only", "description": "Intent + sufficiency gate."},
            "config": {
                "branches": [
                    {
                        "label": "follow_up_required",
                        "condition": "evaluation.verdict != 'sufficient'",
                    },
                    {
                        "label": "proposal_requested",
                        "condition": "intent in ['proposal_requested', 'accept_confirmed']",
                    },
                ],
                "default_branch": "follow_up_required",
            },
        },
        task(
            "skill.voice_tts_followup",
            slug="voice_realtime_speak_v1",
            label="Speak follow-up / next question",
            x=3040,
            y=20,
            inputs_map={"text": "turn.next_prompt"},
            outputs_map={"audio_url": "turn.prompt_audio"},
            data={"menu": "Voice", "phase": "barge_in"},
        ),
        task(
            "skill.capture_structuring",
            slug="capture_structuring_v1",
            label="Create knowledge proposal",
            x=3040,
            y=210,
            inputs_map={"session": "capture.session", "events": "capture.audit_events"},
            outputs_map={"proposal": "capture.proposal"},
            data={"menu": "Proposal", "phase": "synthesis"},
        ),
        {
            "id": "hitl.proposal_review",
            "type": "policy",
            "kind": "hitl",
            "label": "HITL proposal confirmation",
            "position": {"x": 3340, "y": 210},
            "data": {
                "menu": "Governance",
                "description": "Voice confirmation, amendment, then final accept/reject.",
            },
            "config": {
                "prompt": "Validate, amend, reject, or request another capture turn before ingestion.",
                "approvers": ["expert", "operator"],
                "timeout_ms": 86_400_000,
            },
        },
        task(
            "skill.audit_log",
            slug="audit_log_v1",
            label="Persist audit trail",
            x=3640,
            y=160,
            inputs_map={"event": "capture.event"},
            outputs_map={"event_id": "capture.audit_event_id"},
            data={
                "menu": "Traceability",
                "events": [
                    "stt_partial",
                    "stt_final",
                    "retrieval_prefetch_completed",
                    "conversation_intent_detected",
                    "proposal_generated",
                    "proposal_reviewed",
                ],
            },
        ),
        {
            "id": "sink.knowledge_update",
            "type": "sink",
            "kind": "sink",
            "label": "Reviewed knowledge update",
            "position": {"x": 3640, "y": 160},
            "data": {
                "menu": "Knowledge",
                "description": "Accepted proposal ready for ingestion into the selected Knowledge collection.",
            },
            "inputs": [{"name": "proposal", "schema": "object", "required": True}],
        },
    ]
    edges = [
        {"from": "capture.session_request", "to": "skill.knowledge_gap_analysis", "kind": "data"},
        {
            "from": "skill.knowledge_gap_analysis",
            "to": "skill.expert_interview_plan",
            "kind": "data",
        },
        {
            "from": "skill.expert_interview_plan",
            "to": "skill.voice_realtime_session",
            "kind": "control",
        },
        {"from": "skill.voice_realtime_session", "to": "skill.voice_transcribe", "kind": "control"},
        {"from": "skill.voice_transcribe", "to": "skill.semantic_search_prefetch", "kind": "data"},
        {
            "from": "skill.semantic_search_prefetch",
            "to": "skill.expert_answer_evaluator",
            "kind": "data",
        },
        {
            "from": "skill.expert_answer_evaluator",
            "to": "skill.voice_tandem_oracle",
            "kind": "data",
        },
        {"from": "skill.voice_tandem_oracle", "to": "skill.voice_oracle_turn", "kind": "data"},
        {"from": "skill.voice_oracle_turn", "to": "decision.answer_route", "kind": "data"},
        {
            "from": "decision.answer_route",
            "to": "skill.voice_tts_followup",
            "kind": "branch",
            "branch_label": "follow_up_required",
        },
        {"from": "skill.voice_tts_followup", "to": "skill.audit_log", "kind": "control"},
        {
            "from": "decision.answer_route",
            "to": "skill.capture_structuring",
            "kind": "branch",
            "branch_label": "proposal_requested",
        },
        {"from": "skill.capture_structuring", "to": "hitl.proposal_review", "kind": "control"},
        {"from": "hitl.proposal_review", "to": "skill.audit_log", "kind": "control"},
        {"from": "skill.audit_log", "to": "sink.knowledge_update", "kind": "control"},
    ]
    return {
        "schema_version": 3,
        "variant": "expert_knowledge_capture",
        "source": "flow",
        "extended": True,
        "template_id": "expert-knowledge-capture-v2v",
        "template_name": "Knowledge Capture Voice2Voice",
        "nodes": nodes,
        "edges": edges,
        "collections": [],
        "rag_mode": "C-HAH",
        "canonical_rag_mode": "chah",
        "retrieval": {"mode": "chah", "top_k": 4, "timeout_ms": 2500, "non_blocking": True},
        "voice_runtime": {
            "provider": "cascade_openai",
            "capability": "voice2voice_interaction",
            "transport": "backend_ws",
            "events": [
                "text.partial",
                "text.final",
                "audio.out",
                "barge_in",
                "oracle.action",
                "runtime.metric",
            ],
        },
        "ui": {
            "type": "knowledge_capture",
            "label": "Capture console",
            "entry_route": "capture",
            "primary_action": "Start session",
            "legacy_route": "/knowledge/capture",
        },
        "policy": {
            "confidence_threshold": 0.7,
            "require_citations": True,
            "enable_audit": True,
            "max_latency_ms": 4000,
        },
        "conversation": {
            "mode": "conversation_only",
            "requires_confirmation": ["proposal", "acceptance"],
            "supports_multiple_proposals": True,
        },
    }


def ensure_expert_capture_system_default(db: DBSession, workspace_id: str) -> Optional[System]:
    capability = (
        db.query(Capability).filter(Capability.slug == EXPERT_CAPTURE_CAPABILITY_SLUG).first()
    )
    if not capability:
        logger.warning(
            "expert_capture_system_seed.skip.missing_capability",
            workspace_id=workspace_id,
            slug=EXPERT_CAPTURE_CAPABILITY_SLUG,
        )
        return None

    skills = _skill_lookup(db, EXPERT_CAPTURE_SKILL_SLUGS)
    skill_ids = [skills[slug].id for slug in EXPERT_CAPTURE_SKILL_SLUGS if slug in skills]
    flow_definition = _expert_capture_flow_definition(skills)

    # Idempotent by (workspace, capability), NOT by name: a blueprint/manual
    # capture system (e.g. "Andritz Expert Knowledge Capture System") owns the
    # capability, so keying on the generic name seeds a second, empty "Expert
    # Knowledge Capture" alongside it on every boot. Adopt the existing
    # capability system instead — preferring a non-seed (manual/blueprint) one —
    # and archive any redundant seed-created generics.
    candidates = (
        db.query(System)
        .filter(
            System.workspace_id == workspace_id,
            System.capability_id == capability.id,
            System.status != "retired",
        )
        .order_by(System.created_at.asc())
        .all()
    )

    def _is_capture_seed(s: System) -> bool:
        return str(s.created_by or "").startswith("system:expert_capture_seed")

    preferred = next((s for s in candidates if not _is_capture_seed(s)), None) or (
        candidates[0] if candidates else None
    )
    if preferred is not None:
        retired = 0
        for s in candidates:
            if s.id != preferred.id and _is_capture_seed(s):
                s.status = "retired"
                retired += 1
        existing = preferred
        flow = dict(existing.flow_definition or {})
        if flow.get("variant") != "expert_knowledge_capture":
            existing.flow_definition = flow_definition
        existing.objective = existing.objective or EXPERT_CAPTURE_OBJECTIVE
        existing.skill_ids = skill_ids
        existing.execution_mode = "human_augmented"
        existing.coordination_pattern = "single_agent"
        existing.status = "active"
        existing.retrieval_mode_default = "chah"
        db.commit()
        db.refresh(existing)
        if retired:
            logger.info(
                "expert_capture_system.dedupe.retired",
                workspace_id=workspace_id,
                retired=retired,
                kept=existing.id,
            )
        return existing

    system = System(
        workspace_id=workspace_id,
        name=EXPERT_CAPTURE_SYSTEM_NAME,
        objective=EXPERT_CAPTURE_OBJECTIVE,
        capability_id=capability.id,
        skill_ids=skill_ids,
        flow_definition=flow_definition,
        execution_mode="human_augmented",
        execution_profile={
            "runtime": "voice2voice_cascade",
            "latency_target": "perceived_realtime",
            "max_retrieval_prefetch_ms": 2500,
            "durability": "audit_events",
        },
        coordination_pattern="single_agent",
        status="active",
        created_by="system:expert_capture_seed",
        retrieval_mode_default="chah",
    )
    db.add(system)
    db.commit()
    db.refresh(system)
    logger.info(
        "expert_capture_system_seed.created",
        workspace_id=workspace_id,
        system_id=system.id,
        capability_id=capability.id,
    )
    return system


def ensure_expert_capture_system_for_all_workspaces(db: DBSession) -> dict[str, int]:
    report = {"created": 0, "skipped": 0, "already": 0}
    workspaces = (
        db.query(Workspace)
        .filter(Workspace.is_active.is_(True), Workspace.deleted_at.is_(None))
        .all()
    )
    for ws in workspaces:
        before = (
            db.query(System)
            .filter(System.workspace_id == ws.id, System.name == EXPERT_CAPTURE_SYSTEM_NAME)
            .count()
        )
        system = ensure_expert_capture_system_default(db, ws.id)
        if system is None:
            report["skipped"] += 1
        elif before == 0:
            report["created"] += 1
        else:
            report["already"] += 1
    return report
