"""Chat router, request model, response language, workspace flow defaults and SSE helpers."""

import json
import re
from typing import Any, Dict, Literal, Mapping, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_workspace
from app.services.rag.project_references import using_workspace_project_scheme
from app.core.config import settings
from app.core.iam.dependencies import require_app_entitlement
from app.core.logging import get_logger
from app.core.validation import QueryValidator, ResponseValidator
from app.models.system import System
from app.models.workspace import Workspace
from app.services.chat_execution_policy import (
    AGENTIC_SYSTEM_TYPE,
    AGENTIC_VARIANT,
)
from app.services.chat_trivial_bypass import TrivialBypass
from app.services.iam.app_entitlements import CHAT_APP
from app.services.industrial_answer_profile import (
    answer_policy_for_family,
    answer_policy_prompt,
    resolve_answer_profile,
)
from app.services.workspace_features import workspace_family
from app.services.rag.decision_trace import build_trivial_retrieval_decision_trace
from app.services.systems.bootstrap import (
    WORKSPACE_CHAT_VARIANT,
    resolve_workspace_chat_source_policy,
    workspace_chat_system_id,
)


logger = get_logger(__name__)


async def _bind_workspace_project_scheme(
    workspace: Workspace = Depends(get_current_workspace),
):
    """Keep Andritz identifier grammar off unless this workspace is Andritz.

    Async on purpose, and it is not a style preference. FastAPI runs a *sync*
    generator dependency through a threadpool: the ContextVar is set in one
    worker thread and reset in another, so the endpoint never observes the
    bind and the teardown raises "Token was created in a different Context".
    An async generator runs in the request's own task, which is the only form
    that makes a ContextVar bind visible downstream.
    """
    with using_workspace_project_scheme(workspace):
        yield


router = APIRouter(
    dependencies=[
        Depends(require_app_entitlement(CHAT_APP)),
        Depends(_bind_workspace_project_scheme),
    ]
)
query_validator = QueryValidator()
response_validator = ResponseValidator()


_RETRIEVAL_OBSERVABILITY_KEYS = (
    "retrieval_scope",
    "retrieval_plan",
    "retrieval_decision_trace",
    "scope_confidence",
    "scope_reason",
    "dense_policy",
    "dense_only",
    "sparse_status",
    "sparse_backend",
    "sparse_fallback_reason",
    "retrieval_profile",
    "latency_profile",
    "latency_budget",
    "stage_timings",
    "duration_ms",
    "retrieval_elapsed_ms",
    "cross_encoder_status",
    "cross_encoder_model",
    "cross_encoder_ms",
    "cross_encoder_scored",
    "cross_encoder_filtered",
    "cross_encoder_threshold",
    "cross_encoder_budget_seconds",
    "cross_encoder_error",
    "score_threshold_applied",
    "deep_retrieval_recommended",
    "deep_job_id",
    "deep_poll_url",
    "deep_status",
)


class ChatRequest(BaseModel):
    """Chat completion request"""

    query: str
    session_id: Optional[str] = None
    # System (papAI canonical entity) the chat is scoped to — used to
    # bind the resulting Run to a System for preset resolution +
    # per-System Impact aggregation. Front sends
    # ``agent_id: this.systemId()`` from chat-panel.component.ts;
    # can be NULL for workspace-wide chats (Run is still created).
    agent_id: Optional[str] = None
    agent_preferences: Optional[Dict[str, Any]] = None
    stream: bool = True
    include_reasoning: bool = True
    include_sources: bool = True
    max_tokens: Optional[int] = 2000
    temperature: Optional[float] = 0.3
    top_k: Optional[int] = None
    candidate_pool_k: Optional[int] = None
    synthesis_k: Optional[int] = None
    source_display_k: Optional[int] = None
    latency_profile: Optional[Literal["fast", "balanced", "deep"]] = None
    retrieval_profile: Optional[str] = None
    deep_retrieval: Optional[bool] = None
    retrieval_filters: Optional[Dict[str, Any]] = None
    similarity_threshold: Optional[float] = None
    system_prompt: Optional[str] = None
    # RAG mode: auto | naive | hybrid | hah | chah — see docs/rag-rd-papai-mapping.md
    rag_pipeline_mode: Optional[str] = None
    # Per-query retrieval override (alias of rag_pipeline_mode used by the
    # cockpit chip selector — takes precedence over workspace settings).
    rag_mode_override: Optional[str] = None
    # Reasoning template (factual | analytical | comparative | causal |
    # hypothetical | trivial | auto). When unset or "auto" the orchestrator
    # runs the mode_selector heuristic.
    prompt_type: Optional[str] = None
    # Workspace-scoped Knowledge Scope aggregating one or more collections.
    knowledge_scope: Optional[str] = None
    # Optional Context row selected by the UI. When it carries an
    # ``environment_state.collection`` (or ``knowledge_scope``), retrieval is
    # grounded on that source while the session/run ledger keeps the Context
    # id for replay.
    context_id: Optional[str] = None
    # How a selected session Context interacts with Knowledge Scope retrieval:
    # ``replace`` = use session docs only, ``combine`` = search both the
    # selected Knowledge Scope and the session docs collection.
    context_mode: Optional[str] = None
    # Product-facing assistant profile. It does not bypass backend policy; it
    # carries UI/prompt intent into the Run ledger for audit and replay.
    assistant_profile: Optional[str] = None
    # Workspace chat source policy (reject_cross_project_sources, ...). Folded
    # server-side from the always-on chat System; clients never need to set it
    # and setting it only tightens retrieval filtering.
    source_policy: Optional[Dict[str, Any]] = None
    # Workspace/System-owned answer policy. Folded server-side from Flow Builder
    # and used to shape user-facing generation without changing the /chat input
    # contract expected by clients.
    answer_policy: Optional[Dict[str, Any]] = None
    answer_profile: Optional[str] = None
    answer_profile_decision: Optional[Dict[str, Any]] = None
    # Answer grounding policy requested by chat-first surfaces. ``balanced`` is
    # intentionally scoped by backend policy and may be downgraded to ``strict``
    # for workspace facts, documents, actions, or sensitive/current claims.
    grounding_mode: Optional[Literal["strict", "balanced"]] = None
    # Deep Search refinement context. These are system/UI supplied hints so the
    # async worker can preserve the shape of the fast answer without asking the
    # user to restate their intent.
    parent_message_id: Optional[str] = None
    previous_answer: Optional[str] = None
    # UI language is the chrome language selected by the user. Response language
    # is the generation contract for /chat and may be inferred from the query.
    # Retrieved evidence is kept in its original language unless the user asks
    # for translation explicitly.
    ui_locale: Optional[Literal["fr", "en"]] = None
    response_language: Optional[Literal["fr", "en"]] = None


_FR_QUERY_RE = re.compile(
    r"[àâçéèêëîïôùûüÿœæ]|"
    r"\b(?:bonjour|bonsoir|salut|merci|quel|quelle|quels|quelles|comment|pourquoi|"
    r"où|peux[\s-]?tu|pouvez[\s-]?vous|donne|donner|retrouve|retrouver|résume|resume|"
    r"explique|source|sources|fichier|fichiers|documents?|données|connais?sances?)\b",
    re.IGNORECASE,
)
_EN_QUERY_RE = re.compile(
    r"\b(?:hello|hi|thanks|thank\s+you|what|which|how|why|where|when|who|can\s+you|"
    r"could\s+you|please|show\s+me|tell\s+me|find|retrieve|summari[sz]e|explain|"
    r"give\s+me|do\s+you|does|should|about|documents?|sources?|files?|data|knowledge)\b",
    re.IGNORECASE,
)


def _normalise_response_language(value: Optional[str]) -> Optional[Literal["fr", "en"]]:
    if value == "fr" or value == "en":
        return value
    return None


def _detect_query_language(query: str) -> Optional[Literal["fr", "en"]]:
    text = str(query or "").strip()
    if not text:
        return None
    fr_hits = len(_FR_QUERY_RE.findall(text))
    en_hits = len(_EN_QUERY_RE.findall(text))
    if fr_hits and not en_hits:
        return "fr"
    if en_hits and not fr_hits:
        return "en"
    if fr_hits > en_hits:
        return "fr"
    if en_hits > fr_hits:
        return "en"
    return None


def _resolve_response_language(request: ChatRequest, query: str) -> Literal["fr", "en"]:
    explicit = _normalise_response_language(request.response_language)
    if explicit:
        return explicit
    detected = _detect_query_language(query)
    if detected:
        return detected
    return _normalise_response_language(request.ui_locale) or "fr"


def _response_language_instruction(language: str) -> str:
    if language == "en":
        return (
            "Answer in English. Keep cited excerpts, filenames, source titles, table values, "
            "and retrieved evidence in their original language. Do not translate retrieved "
            "content unless the user explicitly asks for a translation."
        )
    return (
        "Réponds en français. Conserve les extraits cités, noms de fichiers, titres de sources, "
        "valeurs de tableaux et preuves récupérées dans leur langue d’origine. Ne traduis pas "
        "le contenu récupéré sauf demande explicite de l’utilisateur."
    )


def _apply_response_language_contract(
    request_dict: Dict[str, Any],
    language: Literal["fr", "en"],
) -> None:
    request_dict["response_language"] = language
    instruction = _response_language_instruction(language)
    current_prompt = str(request_dict.get("system_prompt") or "").strip()
    if instruction in current_prompt:
        return
    request_dict["system_prompt"] = (
        f"{current_prompt}\n\n{instruction}" if current_prompt else instruction
    )


def _trivial_bypass_for_language(
    bypass: TrivialBypass,
    language: Literal["fr", "en"],
) -> TrivialBypass:
    if language != "en":
        return bypass
    english = {
        "trivial_empty": "I'm here. Tell me what you'd like to do.",
        "trivial_thanks": "You're welcome.",
        "trivial_farewell": "See you soon.",
        "trivial_ack": "Noted.",
        "trivial_greeting": "Hello, I'm listening.",
    }
    return TrivialBypass(content=english.get(bypass.reason, bypass.content), reason=bypass.reason)


def _trivial_bypass_metadata(bypass: TrivialBypass, query: str | None = None) -> dict[str, Any]:
    metadata = dict(bypass.metadata())
    metadata["retrieval_decision_trace"] = build_trivial_retrieval_decision_trace(
        reason=bypass.reason,
        query=query,
    )
    return metadata


def _resolve_system_id(
    db: Session,
    workspace_id: str,
    candidate: Optional[str],
) -> Optional[str]:
    """Validate ``candidate`` or fall back to the workspace chat System.

    Returns the id if it resolves to a real System row scoped to the
    workspace, otherwise the always-on workspace chat System when present.
    Prevents cross-workspace FK leaks
    (a malicious client sending another tenant's system_id) and
    gracefully degrades when the front sends a stale id after a
    System was deleted.
    """
    if not candidate:
        return workspace_chat_system_id(db, workspace_id)
    row = (
        db.query(System.id)
        .filter(System.id == candidate, System.workspace_id == workspace_id)
        .first()
    )
    return row[0] if row else workspace_chat_system_id(db, workspace_id)


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _chat_flow_node(flow: Dict[str, Any], node_id: str) -> Dict[str, Any]:
    nodes = flow.get("nodes")
    if not isinstance(nodes, list):
        return {}
    for node in nodes:
        if isinstance(node, Mapping) and node.get("id") == node_id:
            return dict(node)
    return {}


def _apply_workspace_chat_flow_defaults(
    db: Session,
    *,
    workspace: Workspace,
    request: ChatRequest,
) -> Optional[str]:
    """Fold editable Flow Builder chat defaults into a request.

    The Flow Builder does not replace the hardened chat endpoint. Instead it
    owns a versioned manifest whose safe defaults are read on every turn:
    profile, scope, retrieval budget, RAG mode and optional system prompt.
    User-supplied request fields always win.
    """
    requested_agent_id = request.agent_id
    resolved_system_id = _resolve_system_id(db, workspace.id, requested_agent_id)
    surface_system_id = workspace_chat_system_id(db, workspace.id)
    requested_system = None
    if requested_agent_id:
        requested_system = (
            db.query(System)
            .filter(
                System.id == requested_agent_id,
                System.workspace_id == workspace.id,
            )
            .first()
        )
    requested_flow = _as_dict(getattr(requested_system, "flow_definition", None))
    requested_settings = _as_dict(getattr(requested_system, "settings", None))
    requested_is_agentic = bool(
        requested_system
        and requested_settings.get("system_type") == AGENTIC_SYSTEM_TYPE
        and requested_flow.get("variant") == AGENTIC_VARIANT
    )
    # Explicit business Systems keep their own profile/scope/prompt defaults.
    # Only the public Workspace Chat surface and its canonical Agentic executor
    # share the Workspace Chat manifest.
    if (
        requested_system is not None
        and requested_system.id != surface_system_id
        and not requested_is_agentic
    ):
        return requested_system.id
    system_id = surface_system_id or resolved_system_id
    if not system_id:
        return None
    system = (
        db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    )
    if not system:
        return None
    flow = _as_dict(system.flow_definition)
    if flow.get("variant") != WORKSPACE_CHAT_VARIANT:
        return resolved_system_id

    # The always-on Workspace Chat System owns the public surface defaults.
    # Preserve a valid explicitly selected executor System so the routing
    # policy can use it as an operator canary; replace stale/cross-tenant ids.
    explicitly_valid = bool(requested_system and resolved_system_id == requested_system.id)
    if not explicitly_valid:
        request.agent_id = system.id
    chat = _as_dict(flow.get("chat"))
    prompt_contract = _as_dict(flow.get("prompt_contract"))
    budget_node = _as_dict(_chat_flow_node(flow, "runtime.settings_budget").get("data"))
    grounding_node = _as_dict(_chat_flow_node(flow, "skill.grounding_policy").get("data"))
    fast_answer_node = _as_dict(_chat_flow_node(flow, "skill.fast_answer").get("data"))
    node_prompt_contract = _as_dict(fast_answer_node.get("prompt_contract"))
    retrieval_defaults = _as_dict(budget_node.get("retrieval_defaults")) or _as_dict(
        chat.get("retrieval_defaults")
    )

    if not request.assistant_profile and chat.get("assistant_profile"):
        request.assistant_profile = str(chat["assistant_profile"])
    if not request.knowledge_scope and chat.get("knowledge_scope"):
        request.knowledge_scope = str(chat["knowledge_scope"])
    if request.source_policy is None:
        source_policy = resolve_workspace_chat_source_policy(db, workspace, system=system)
        if source_policy:
            request.source_policy = source_policy
    if request.latency_profile is None and retrieval_defaults.get("latency_profile") in {
        "fast",
        "balanced",
        "deep",
    }:
        request.latency_profile = retrieval_defaults["latency_profile"]  # type: ignore[assignment]
    if request.retrieval_profile is None and retrieval_defaults.get("retrieval_profile"):
        request.retrieval_profile = str(retrieval_defaults["retrieval_profile"])
    if (
        request.rag_pipeline_mode is None
        and request.rag_mode_override is None
        and retrieval_defaults.get("mode")
    ):
        request.rag_pipeline_mode = str(retrieval_defaults["mode"])
    # Fold the whole funnel together: a lone folded top_k reads as an explicit
    # user pin downstream and collapses synthesis/candidate defaults to top_k.
    for budget_key in ("top_k", "source_display_k", "synthesis_k", "candidate_pool_k"):
        if getattr(request, budget_key) is None and retrieval_defaults.get(budget_key) is not None:
            try:
                setattr(request, budget_key, int(retrieval_defaults[budget_key]))
            except (TypeError, ValueError):
                pass
    if request.prompt_type is None and prompt_contract.get("default_prompt_type"):
        request.prompt_type = str(prompt_contract["default_prompt_type"])
    if request.answer_policy is None:
        answer_policy = _as_dict(prompt_contract.get("answer_policy"))
        if not answer_policy and prompt_contract.get("answer_profiles"):
            answer_policy = {
                "key": "industrial_answer_profile_v1",
                "default_answer_profile": prompt_contract.get("default_answer_profile")
                or "precise_fact",
                "profiles": prompt_contract.get("answer_profiles"),
            }
        if not answer_policy:
            # No seeded contract. Fall back to what bootstrap seeds for this
            # family, and write it into the request so every later step of the
            # turn (classification, prompt, output guard) sees the same policy.
            # The old fallback was the industrial policy for everyone, applied
            # here and then again, independently, inside each policy helper.
            answer_policy = answer_policy_for_family(workspace_family(workspace))
        request.answer_policy = answer_policy
    if request.answer_profile_decision is None:
        policy = request.answer_policy or answer_policy_for_family(workspace_family(workspace))
        decision = resolve_answer_profile(
            request.query,
            policy,
            include_agentic_profiles=settings.enable_agentic_chat,
        )
        request.answer_profile_decision = decision.as_dict()
        request.answer_profile = decision.profile
        if decision.requires_exhaustive_retrieval:
            request.deep_retrieval = True
            request.latency_profile = "deep"
            request.retrieval_profile = "deep_async"
            if request.source_display_k is None:
                request.source_display_k = 24
            if request.synthesis_k is None:
                request.synthesis_k = 48
            if request.candidate_pool_k is None:
                request.candidate_pool_k = 200

    # Grounding config can set a default mode, but the normal resolver still
    # enforces strict guards for documents/current-state/workspace facts.
    grounding = _as_dict(grounding_node.get("grounding")) or _as_dict(chat.get("grounding"))
    if request.grounding_mode is None and grounding.get("default_mode") in {"strict", "balanced"}:
        request.grounding_mode = grounding["default_mode"]  # type: ignore[assignment]

    # The prompt is intentionally restricted to the chat flow's prompt contract.
    # It lets Flow Builder edits change the provider instruction while keeping
    # all retrieval and grounding policy guards active downstream.
    if request.system_prompt is None:
        system_prompt = node_prompt_contract.get("system_prompt") or prompt_contract.get(
            "base_system_prompt"
        )
        if isinstance(system_prompt, str) and system_prompt.strip():
            request.system_prompt = system_prompt
    if request.system_prompt:
        policy_text = answer_policy_prompt(
            answer_policy=request.answer_policy,
            profile_decision=request.answer_profile_decision,
            language=request.response_language,
        )
        if policy_text and policy_text not in request.system_prompt:
            request.system_prompt = f"{request.system_prompt.rstrip()}\n\n{policy_text}"

    return resolved_system_id or system.id


def _sse_data(payload: Any) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


def _sse_done() -> str:
    return "data: [DONE]\n\n"


def _error_chunk(
    code: str,
    content: str,
    *,
    recoverable: bool = False,
    details: Optional[Dict[str, Any]] = None,
    is_final: bool = True,
) -> Dict[str, Any]:
    return {
        "chunk_type": "error",
        "code": code,
        "content": content,
        "recoverable": recoverable,
        "details": details or {},
        "is_final": is_final,
    }


def _collect_chat_chunk(
    chunk: Dict[str, Any],
    *,
    full_content: list[str],
    decision_steps: list[Dict[str, Any]],
    state: Dict[str, Any],
) -> None:
    if chunk.get("chunk_type") == "text":
        full_content.append(chunk.get("content", ""))
    if chunk.get("reasoning_trace"):
        state["reasoning_trace"] = chunk.get("reasoning_trace")
    if chunk.get("sources"):
        state["sources"] = chunk.get("sources")
    if chunk.get("chunk_type") == "retrieval":
        details = chunk.get("details") or {}
        if chunk.get("rag_context"):
            state["rag_context"] = chunk.get("rag_context")
        if details:
            state["retrieval_metrics"] = details
        if details.get("task_id"):
            state["retrieval_worker_task_id"] = details.get("task_id")
        if details.get("fallback"):
            state["retrieval_fallback"] = details.get("fallback_reason") or True
        if details.get("scope"):
            state["knowledge_scope"] = details.get("scope")
        if details.get("collections_touched"):
            state["collections_touched"] = details.get("collections_touched")
        for key in _RETRIEVAL_OBSERVABILITY_KEYS:
            if details.get(key) is not None:
                state[key] = details.get(key)
    if chunk.get("chunk_type") == "decision_step" and chunk.get("decision_step"):
        decision_step = chunk.get("decision_step")
        existing_index = next(
            (i for i, ds in enumerate(decision_steps) if ds.get("id") == decision_step.get("id")),
            None,
        )
        if existing_index is not None:
            decision_steps[existing_index] = decision_step
        else:
            decision_steps.append(decision_step)
