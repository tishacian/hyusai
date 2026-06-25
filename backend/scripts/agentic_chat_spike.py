"""Offline measurement spike for an agentic research controller on the andritz chat.

Phase 0 (measurement only). ZERO change to live chat behaviour: this never wires
into the chat endpoint and never persists sessions/runs. It re-runs the *faithful*
chat pipeline (same request the chat endpoint builds via
``_apply_workspace_chat_flow_defaults`` -> orchestrator.process_request ->
``apply_answer_policy_to_text``) on a bounded corpus, self-evaluates each first
answer, simulates an escalation pass, and reports the size of the
escalation/clarification opportunity.

Run in-container (Qdrant + LLM reachable):

    cat backend/scripts/agentic_chat_spike.py | \
      ssh omnirag-demo "docker exec -i -e SPIKE_LIMIT=3 -w /app/backend agentium-backend python -"

Env knobs (used when piped through ``python -`` where argv is unavailable):
    SPIKE_LIMIT       int, first-N corpus rows (0 = all)
    SPIKE_IDS         comma-separated corpus ids to run (overrides limit)
    SPIKE_OUTPUT      JSON report path (default /tmp/agentic_spike_report.json)
    SPIKE_JSONL       per-row JSONL checkpoint path (default /tmp/agentic_spike_rows.jsonl)
    SPIKE_NO_ESCALATE 1 to skip the deep escalation pass
    SPIKE_RESUME      1 to skip ids already present in SPIKE_JSONL
    SPIKE_CASE_TIMEOUT seconds per pipeline pass (default 150)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

WORKSPACE_SLUG = "andritz"
WORKSPACE_ID = "0cce0bee-7e86-485d-95b1-672e82f16600"

# ---------------------------------------------------------------------------
# Corpus. Curated, bounded (~60) and self-contained so the script can run
# in-container via ``python -`` without the golden JSON files (absent from the
# prod image). Sources:
#   demo       -> docs/demo-andritz-qa-set-2026-06-22.md (firm PASS/FAIL labels)
#   regression -> explicit known-regression cases (D.60, CU250S-2, Etachrom, DE)
#   golden:<f> -> backend/app/resources/retrieval_golden/<f>.json (query fields)
# ground_truth: "bon" | "faible" | None (None = unlabeled, broadens weak-rate
# measurement but is excluded from the precision/recall calibration).
# ---------------------------------------------------------------------------
CORPUS: List[Dict[str, Any]] = [
    # --- Demo 22/06 PASS (ground truth = bon) ---
    {"id": "demo_pass_akk200_width_speed", "source": "demo", "lang": "fr", "ground_truth": "bon",
     "query": "Quelle est la largeur de travail et la vitesse de production du système AKK200 Nonwoven ?"},
    {"id": "demo_pass_qms12_function_en", "source": "demo", "lang": "en", "ground_truth": "bon",
     "query": "What is the Qualiscan QMS-12 system used for and how does it work?"},
    {"id": "demo_pass_injector_cartridge_cleaning", "source": "demo", "lang": "fr", "ground_truth": "bon",
     "query": "Comment dois-je nettoyer les cartouches d'injecteurs ?"},
    {"id": "demo_pass_acj200_carde", "source": "demo", "lang": "fr", "ground_truth": "bon",
     "query": "Décris la carde ACJ200 et ses principaux composants."},
    # --- Demo 22/06 documented FAIL / regressions (ground truth = faible) ---
    {"id": "demo_fail_akk200_de", "source": "demo", "lang": "de", "ground_truth": "faible",
     "query": "Wie groß sind die Arbeitsbreite und die Produktionsgeschwindigkeit des AKK200 Nonwoven-Systems?"},
    {"id": "demo_fail_cu250s2_role", "source": "demo", "lang": "fr", "ground_truth": "faible",
     "query": "Quel est le rôle et la configuration du module CU250S-2 ?"},
    {"id": "demo_fail_etachrom_spares", "source": "demo", "lang": "fr", "ground_truth": "faible",
     "query": "Quelles sont les pièces de rechange de la pompe Etachrom B ?"},
    {"id": "demo_fail_qms12_de", "source": "demo", "lang": "de", "ground_truth": "faible",
     "query": "Wozu dient das Qualiscan QMS-12 System und wie funktioniert es?"},
    {"id": "demo_fail_d60_greasing", "source": "demo", "lang": "fr", "ground_truth": "faible",
     "query": "Quelle quantité de graisse faut-il pour le palier moteur D.60 ?"},
    {"id": "demo_fail_german_generic", "source": "demo", "lang": "de", "ground_truth": "faible",
     "query": "Welche Wartung ist für die Filtration und das Vakuum im Projekt AKK200 erforderlich?"},
    # --- Explicit regression case from the brief (transversal inventory) ---
    {"id": "reg_transversal_uraca", "source": "regression", "lang": "fr", "ground_truth": None,
     "query": "Quels projets utilisent une pompe URACA ?"},
    # --- Golden: andritz_spl_dense (representative subset, distinct facts/intents) ---
    {"id": "g_dense_dci110_strip_carrier", "source": "golden:dense", "lang": "fr", "ground_truth": None,
     "query": "Comment retirer le strip-carrier d'un injecteur dans DCI110 ?"},
    {"id": "g_dense_aco140_spl", "source": "golden:dense", "lang": "fr", "ground_truth": None,
     "query": "Peux-tu retrouver la Spare Parts List du projet ACO140 ?"},
    {"id": "g_dense_bba120_spl", "source": "golden:dense", "lang": "fr", "ground_truth": None,
     "query": "Peux-tu retrouver la Spare Parts List du projet BBA120 ?"},
    {"id": "g_dense_bba120_uraca_kd724", "source": "golden:dense", "lang": "fr", "ground_truth": None,
     "query": "Quels documents existent pour la pompe HP URACA KD724 du projet BBA120 ?"},
    {"id": "g_dense_bba120_ksb_etachrom", "source": "golden:dense", "lang": "fr", "ground_truth": None,
     "query": "Quel document couvre la pompe KSB Etachrom dans BBA120 ?"},
    {"id": "g_dense_akk200_filtration_vacuum", "source": "golden:dense", "lang": "fr", "ground_truth": None,
     "query": "Quelle procedure de maintenance concerne la filtration et le vacuum dans AKK200 ?"},
    {"id": "g_dense_ara200_conveyor", "source": "golden:dense", "lang": "fr", "ground_truth": None,
     "query": "Quels documents de convoyeur sont indexes pour ARA200 ?"},
    {"id": "g_dense_ara200_pneumatic_cabinet", "source": "golden:dense", "lang": "fr", "ground_truth": None,
     "query": "Quel document decrit l'armoire pneumatique de ARA200 ?"},
    {"id": "g_dense_akk200_oring_d36", "source": "golden:dense", "lang": "fr", "ground_truth": None,
     "query": "Quel fichier source contient le joint O-ring string D. 3,6 pour AKK200 ?"},
    {"id": "g_dense_geotex_label_b", "source": "golden:dense", "lang": "fr", "ground_truth": None,
     "query": "Dans les fichiers NON-WOVENS France, que vaut le label B dans la table Def strips ?"},
    {"id": "g_dense_akk200_lm300", "source": "golden:dense", "lang": "fr", "ground_truth": None,
     "query": "Dans AKK200, je cherche la reference Filtering cartridge LM300 : quelle source faut-il ouvrir ?"},
    # --- Golden: andritz_spl_hard_intents (all 11 — the agentic-relevant axis) ---
    {"id": "g_hi_ambiguous_parts_manual", "source": "golden:hard_intents", "lang": "fr", "ground_truth": None,
     "query": "Ou se trouve le parts manual ?"},
    {"id": "g_hi_kd724_partial_ref", "source": "golden:hard_intents", "lang": "fr", "ground_truth": None,
     "query": "Quels projets utilisent la pompe KD724 ?"},
    {"id": "g_hi_compare_continental_pollrich", "source": "golden:hard_intents", "lang": "en", "ground_truth": None,
     "query": "What is the difference between the CONTINENTAL GVJS and POLLRICH GVJ1 vacuum set blowers on AKI300?"},
    {"id": "g_hi_compare_g150_s120", "source": "golden:hard_intents", "lang": "fr", "ground_truth": None,
     "query": "Quelles differences de parametres de mise en service entre les variateurs SINAMICS G150 et SINAMICS S120 ?"},
    {"id": "g_hi_php_pressure_drop", "source": "golden:hard_intents", "lang": "fr", "ground_truth": None,
     "query": "Pourquoi la pression chute-t-elle sur le groupe haute pression PHP et quel document consulter ?"},
    {"id": "g_hi_german_simotics_akk200", "source": "golden:hard_intents", "lang": "de", "ground_truth": None,
     "query": "Wo finde ich die SIMOTICS Betriebsanleitung auf Deutsch fuer das Projekt AKK200?"},
    {"id": "g_hi_exclusion_excelle", "source": "golden:hard_intents", "lang": "en", "ground_truth": None,
     "query": "Excelle S5PP6TT card operator manual in English please, not the Dutch Gebruikershandleiding."},
    {"id": "g_hi_compare_wilo_bex200", "source": "golden:hard_intents", "lang": "en", "ground_truth": None,
     "query": "Compare the Wilo Drain SP and the Wilo NOLH pump manuals available for BEX200."},
    {"id": "g_hi_lh2_identifier", "source": "golden:hard_intents", "lang": "en", "ground_truth": None,
     "query": "What does document LH2 0113 cover and which machines reference it?"},
    {"id": "g_hi_wilo_rexa_lot100", "source": "golden:hard_intents", "lang": "fr", "ground_truth": None,
     "query": "Sur LOT100, quelle pompe BP WILO equipe le vacuum set et ou est sa notice d'exploitation ?"},
    {"id": "g_hi_etachrom_bc_multiproject", "source": "golden:hard_intents", "lang": "fr", "ground_truth": None,
     "query": "Ou trouver la notice etachrom bc du circuit HP ?"},
    # --- Golden: andritz_spl_diversity (subset incl. CU250S-2 + QMS-12 DE) ---
    {"id": "g_div_g150_operating", "source": "golden:diversity", "lang": "en", "ground_truth": None,
     "query": "Where can I find the G150 speed controller operating instructions?"},
    {"id": "g_div_printable_parts_manual", "source": "golden:diversity", "lang": "fr", "ground_truth": None,
     "query": "Montre-moi les parts manuals disponibles en version imprimable."},
    {"id": "g_div_vacuum_set_blowers", "source": "golden:diversity", "lang": "en", "ground_truth": None,
     "query": "Which manuals cover the vacuum set blowers of the hydroentanglement unit?"},
    {"id": "g_div_cu250s2_vector_control", "source": "golden:diversity", "lang": "en", "ground_truth": None,
     "query": "Where is the CU250S-2 vector control unit manual referenced?"},
    {"id": "g_div_qms12_de_betriebsanleitungen", "source": "golden:diversity", "lang": "de", "ground_truth": None,
     "query": "Wo sind die Betriebsanleitungen fuer den Qualiscan QMS-12?"},
    {"id": "g_div_sinamics_s120_s150", "source": "golden:diversity", "lang": "en", "ground_truth": None,
     "query": "Find the SINAMICS S120 S150 list manual for the carding unit."},
    # --- Golden: andritz_spl_fallbacks ---
    {"id": "g_fb_vacuum_maintenance", "source": "golden:fallbacks", "lang": "fr", "ground_truth": None,
     "query": "Quelle est la procédure de maintenance du vide ?"},
    {"id": "g_fb_conveyor_cleaning", "source": "golden:fallbacks", "lang": "fr", "ground_truth": None,
     "query": "Procédure de nettoyage du convoyeur"},
    # --- Golden: andritz_spl_sparse_only (exact-identifier / lexical channel) ---
    {"id": "g_sp_uraca_kd724_exact", "source": "golden:sparse_only", "lang": "fr", "ground_truth": None,
     "query": "URACA KD724"},
    {"id": "g_sp_dci110_doc_ref", "source": "golden:sparse_only", "lang": "en", "ground_truth": None,
     "query": "DCI 110 PERFO-TE-OM-10-5"},
    {"id": "g_sp_geotex_stem", "source": "golden:sparse_only", "lang": "fr", "ground_truth": None,
     "query": "GEOTEX SPL Y25.05.22"},
    # --- Golden: andritz_spl_scope_filters (generic ask, scope sensitivity) ---
    {"id": "g_sf_generic_spare_parts", "source": "golden:scope_filters", "lang": "fr", "ground_truth": None,
     "query": "Liste des pièces de rechange"},
    {"id": "g_sf_aco150_garniture", "source": "golden:scope_filters", "lang": "fr", "ground_truth": None,
     "query": "Liste de garniture du projet ACO150"},
    {"id": "g_sf_filtration_maintenance", "source": "golden:scope_filters", "lang": "fr", "ground_truth": None,
     "query": "Procédure de maintenance de la filtration"},
    # --- Golden: andritz_spl_multilingual (FR/EN/DE same fact) ---
    {"id": "g_ml_injector_fr", "source": "golden:multilingual", "lang": "fr", "ground_truth": None,
     "query": "Comment nettoyer les cartouches d'injecteurs EXH ?"},
    {"id": "g_ml_injector_en", "source": "golden:multilingual", "lang": "en", "ground_truth": None,
     "query": "How do I clean the EXH injector cartridges?"},
    {"id": "g_ml_injector_de", "source": "golden:multilingual", "lang": "de", "ground_truth": None,
     "query": "Wie reinige ich die EXH Injektor-Kartuschen?"},
    {"id": "g_ml_akk200_de", "source": "golden:multilingual", "lang": "de", "ground_truth": None,
     "query": "Finde die Ersatzteilliste für das Projekt AKK200."},
    # --- Golden: andritz_spl_multiturn (anaphora -> conversation anchor) ---
    {"id": "g_mt_followup_akk200", "source": "golden:multiturn", "lang": "fr", "ground_truth": None,
     "query": "et pour celle-ci, quelles pièces de rechange ?",
     "conversation_history": [
         {"role": "user", "content": "Parle-moi de la machine du projet AKK200"},
         {"role": "assistant", "content": "Le projet AKK200 couvre une ligne SPL documentée dans Spare Parts List AKK200_Ind A.pdf."},
     ]},
    {"id": "g_mt_followup_switch_aco150", "source": "golden:multiturn", "lang": "fr", "ground_truth": None,
     "query": "même question pour ACO150",
     "conversation_history": [
         {"role": "user", "content": "Retrouve la Spare Parts List du projet AKK200"},
         {"role": "assistant", "content": "Voici la Spare Parts List AKK200_Ind A.pdf."},
     ]},
    {"id": "g_mt_followup_etachrom_maint", "source": "golden:multiturn", "lang": "fr", "ground_truth": None,
     "query": "et la maintenance pour cette machine ?",
     "conversation_history": [
         {"role": "user", "content": "Quels documents pour la pompe Etachrom B ?"},
         {"role": "assistant", "content": "La pompe est documentée dans Etachrom B.PDF."},
     ]},
]


# ---------------------------------------------------------------------------
# Cheap deterministic detectors (no LLM). These complement the judge: the
# live pipeline already emits the operational signals (fallback_reason,
# no_context, guardrail, cross-encoder status); the answer-side detectors
# (hedge / jargon / language contract) mirror the documented demo failure
# shapes.
# ---------------------------------------------------------------------------
_GERMAN_MARKERS = re.compile(
    r"\b(der|die|das|und|für|fuer|wie|wo|finde|ich|auf\s+deutsch|betriebsanleitung|"
    r"ersatzteilliste|reinige|kartuschen|gross|größe|gr\u00f6\u00dfe|arbeitsbreite|"
    r"produktionsgeschwindigkeit|wartung|erforderlich|dient|funktioniert|dr\u00fccke|kalibriert)\b",
    re.IGNORECASE,
)
_HEDGE_RE = re.compile(r"analyse\s+g[ée]n[ée]rale\s+[àa]\s+valider", re.IGNORECASE)
_JARGON_LEAK_RE = re.compile(r"\b(vectoriel|score\s+vectoriel|base\s+vectorielle)\b", re.IGNORECASE)
# Andritz project codes: 2-4 letters + 2-3 digits (+ optional -N), plus D.NN style.
_PROJECT_CODE_RE = re.compile(r"\b([A-Z]{2,4}\d{2,3}(?:-\d)?|D\.\d{2,3})\b")
_ANAPHORA_RE = re.compile(
    r"\b(celle?-ci|celui-ci|cette|ce\s+|cet\s+|ceux|m[êe]me\s+question|et\s+pour|"
    r"pour\s+celle|cette\s+machine|it|that|those|they|them)\b",
    re.IGNORECASE,
)
_GENERIC_PART_RE = re.compile(
    r"\b(pi[èe]ces?\s+de\s+rechange|parts?\s+manual|spare\s+parts?|liste\s+des?\s+pi[èe]ces|"
    r"ersatzteilliste|liste\s+de\s+garniture)\b",
    re.IGNORECASE,
)
_CROSS_PROJECT_RE = re.compile(
    r"\b(quels?\s+projets?|which\s+projects?|tous\s+les\s+projets?|across|sur\s+quels)\b",
    re.IGNORECASE,
)


def looks_german(query: str) -> bool:
    q = query or ""
    hits = len(_GERMAN_MARKERS.findall(q))
    return hits >= 2 or "deutsch" in q.lower() or "betriebsanleitung" in q.lower()


def assess_sufficiency(query: str, *, has_history: bool) -> Dict[str, Any]:
    """Heuristic clarification-opportunity detector (clarify workstream).

    Offline we cannot simulate the clarify->answer recovery, so we only size
    the opportunity: how many first queries are ambiguous / under-specified
    enough that a single clarifying question would plausibly help.
    """
    q = (query or "").strip()
    words = q.split()
    reasons: List[str] = []
    has_project = bool(_PROJECT_CODE_RE.search(q))
    has_anaphora = bool(_ANAPHORA_RE.search(q))
    generic_part = bool(_GENERIC_PART_RE.search(q))
    cross_project = bool(_CROSS_PROJECT_RE.search(q))

    if has_anaphora and not has_project and not has_history:
        reasons.append("anaphora_without_anchor")
    if generic_part and not has_project:
        reasons.append("generic_part_no_project")
    if cross_project and not has_project:
        reasons.append("unscoped_cross_project")
    if len(words) <= 3 and not has_project:
        reasons.append("very_short_no_anchor")
    # bare identifier with no explicit ask (e.g. "URACA KD724")
    if len(words) <= 3 and "?" not in q and not re.search(r"\b(quel|quelle|comment|where|how|what|wo|wie)\b", q, re.IGNORECASE):
        if "bare_identifier" not in reasons:
            reasons.append("bare_identifier")

    ambiguous = bool(reasons)
    # sufficiency score: 1.0 = fully specified, lower = more under-specified
    score = 1.0
    score -= 0.35 if "generic_part_no_project" in reasons else 0.0
    score -= 0.35 if "unscoped_cross_project" in reasons else 0.0
    score -= 0.3 if "anaphora_without_anchor" in reasons else 0.0
    score -= 0.2 if "very_short_no_anchor" in reasons else 0.0
    score -= 0.15 if "bare_identifier" in reasons else 0.0
    score = max(0.0, round(score, 3))
    return {
        "ambiguous": ambiguous,
        "sufficiency_score": score,
        "reasons": reasons,
        "has_project_code": has_project,
    }


# ---------------------------------------------------------------------------
# Orchestrator bootstrap. A fresh ``python -`` process never runs the FastAPI
# lifespan, so the orchestrator singleton is unset. Mirror app.main's startup
# (orchestrator + OmniRAG agent) — read-only, no servers, no schedulers.
# ---------------------------------------------------------------------------
async def bootstrap_orchestrator() -> None:
    from app.agents.orchestrator import AgentOrchestrator
    from app.agents.procurement_agent import OmniRAGAgent
    from app.api.v1.endpoints.agents import get_orchestrator, set_orchestrator

    if get_orchestrator() is not None:
        return
    orchestrator = AgentOrchestrator()
    set_orchestrator(orchestrator)
    agent = OmniRAGAgent()
    await agent.initialize()
    orchestrator.register_agent(agent)


def _extract_context_chunks(rag_context: Any, sources: Any, *, limit: int = 12) -> List[str]:
    chunks: List[str] = []
    if isinstance(rag_context, dict):
        raw = rag_context.get("chunks")
        if isinstance(raw, list):
            for item in raw[:limit]:
                if isinstance(item, str) and item.strip():
                    chunks.append(item[:1500])
    if not chunks and isinstance(sources, list):
        for item in sources[:limit]:
            if isinstance(item, dict):
                text = item.get("content") or item.get("snippet") or item.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text[:1500])
    return chunks


async def faithful_chat(db, workspace, query: str, *, deep: bool,
                        conversation_history: Optional[list] = None,
                        case_timeout: float = 150.0) -> Dict[str, Any]:
    """Re-run the chat pipeline exactly as the endpoint does (minus persistence).

    baseline -> latency_profile forced to 'balanced' (the spike baseline);
    escalation (deep=True) -> latency_profile 'deep' + deep_async retrieval.
    Returns the user-facing answer plus the operational signals the chat path
    exposes (metrics, grounding state, answer-policy violations, latency).
    """
    from app.api.v1.endpoints.agents import get_orchestrator
    from app.api.v1.endpoints.chat import (
        ChatRequest,
        _apply_response_language_contract,
        _apply_retrieval_budget_policy,
        _apply_workspace_chat_flow_defaults,
        _collect_chat_chunk,
        _grounding_degraded_reply,
        _resolve_response_language,
        resolve_grounding_policy,
    )
    from app.core.config import settings
    from app.core.settings_manager import get_resolved_settings
    from app.services.industrial_answer_profile import apply_answer_policy_to_text

    request = ChatRequest(query=query)
    _apply_workspace_chat_flow_defaults(db, workspace=workspace, request=request)

    # Spike baseline is a uniform single 'balanced' pass; escalation is 'deep'.
    # We keep the faithful answer_profile_decision / scope / system_prompt and
    # only steer the retrieval lane.
    if deep:
        request.latency_profile = "deep"
        request.deep_retrieval = True
        request.retrieval_profile = "deep_async"
        request.top_k = None
        request.source_display_k = None
        request.synthesis_k = None
        request.candidate_pool_k = None
    else:
        request.latency_profile = "balanced"
        request.deep_retrieval = False
        # let the budget policy recompute clean balanced defaults
        request.retrieval_profile = "chat"
        request.top_k = None
        request.source_display_k = None
        request.synthesis_k = None
        request.candidate_pool_k = None

    response_language = _resolve_response_language(request, query)
    request.response_language = response_language

    app_settings = get_resolved_settings(workspace_id=workspace.id)
    request_dict = request.model_dump()
    request_dict["query"] = query
    request_dict["workspace_slug"] = workspace.slug
    request_dict["workspace_id"] = workspace.id
    # ChatRequest has no ``context`` field: the chat endpoint injects the
    # anaphora anchor straight into the request_dict the orchestrator consumes
    # (mirrors chat.py request_dict["context"]["conversation_history"]).
    if conversation_history:
        request_dict["context"] = {
            "conversation_history": list(conversation_history),
            "memory_type": "long_term",
        }
    _apply_response_language_contract(request_dict, response_language)
    grounding_policy = resolve_grounding_policy(
        query=query, workspace=workspace,
        assistant_profile=request.assistant_profile,
        requested_mode=request.grounding_mode, context_id=request.context_id,
    )
    request_dict["grounding_policy"] = grounding_policy
    request_dict["grounding_mode"] = grounding_policy["mode"]
    prefs = request_dict.get("agent_preferences") or {}
    prefs.setdefault("model_preferences", {})
    prefs["model_preferences"].setdefault("model", app_settings.get("defaultModel") or settings.default_model)
    prefs["model_preferences"].setdefault("provider", app_settings.get("defaultProvider") or settings.default_provider)
    request_dict["agent_preferences"] = prefs
    if request.max_tokens is None:
        request_dict["max_tokens"] = app_settings.get("maxTokens", 2000)
    if request.temperature is None:
        request_dict["temperature"] = app_settings.get("temperature", 0.7)
    _apply_retrieval_budget_policy(request_dict)

    orchestrator = get_orchestrator()
    full_content: List[str] = []
    decision_steps: List[Dict[str, Any]] = []
    state: Dict[str, Any] = {"grounding_policy": grounding_policy}

    started = time.perf_counter()
    error: Optional[str] = None

    async def _consume() -> None:
        async for chunk in orchestrator.process_request(request_dict):
            _collect_chat_chunk(chunk, full_content=full_content,
                                decision_steps=decision_steps, state=state)
            if (chunk.get("chunk_type") == "retrieval"
                    and chunk.get("phase") != "started" and not full_content):
                reply = _grounding_degraded_reply(
                    state, grounding_policy, response_language=response_language)
                if reply:
                    state["grounding_state"] = "no_grounded_context"
                    full_content.append(reply)
                    break
            if chunk.get("is_final"):
                break

    try:
        await asyncio.wait_for(_consume(), timeout=case_timeout)
    except asyncio.TimeoutError:
        error = f"timeout_{int(case_timeout)}s"
    except Exception as exc:  # noqa: BLE001 - report every case, keep the batch moving
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    raw_answer = "".join(full_content)
    answer, violations = apply_answer_policy_to_text(
        raw_answer,
        answer_policy=request_dict.get("answer_policy") if isinstance(request_dict.get("answer_policy"), dict) else None,
        profile_decision=request_dict.get("answer_profile_decision") if isinstance(request_dict.get("answer_profile_decision"), dict) else None,
    )
    metrics = state.get("retrieval_metrics") if isinstance(state.get("retrieval_metrics"), dict) else {}
    rag_context = state.get("rag_context")
    context_chunks = _extract_context_chunks(rag_context, state.get("sources"))
    return {
        "answer": answer,
        "raw_answer": raw_answer,
        "answer_policy_violations": violations,
        "latency_ms": elapsed_ms,
        "error": error,
        "response_language": response_language,
        "latency_profile": request_dict.get("latency_profile"),
        "answer_profile": request_dict.get("answer_profile"),
        "answer_profile_decision": request_dict.get("answer_profile_decision"),
        "grounding_mode": grounding_policy.get("mode"),
        "grounding_state": state.get("grounding_state"),
        "context_chunks": context_chunks,
        "system_prompt": request_dict.get("system_prompt") or "",
        "metrics": {
            "no_context": metrics.get("no_context"),
            "fallback": metrics.get("fallback"),
            "fallback_reason": metrics.get("fallback_reason"),
            "chunks_retrieved": metrics.get("chunks_retrieved"),
            "cross_encoder_status": metrics.get("cross_encoder_status"),
            "cross_encoder_ms": metrics.get("cross_encoder_ms"),
            "sparse_status": metrics.get("sparse_status"),
            "dense_policy": metrics.get("dense_policy"),
            "scope_confidence": metrics.get("scope_confidence"),
            "exact_match_guardrail_inserted": metrics.get("exact_match_guardrail_inserted"),
            "retrieval_profile": metrics.get("retrieval_profile"),
            "latency_profile": metrics.get("latency_profile"),
        },
    }


# ---------------------------------------------------------------------------
# Verdict: combine the reusable LLM judge with the cheap deterministic signals.
# weak_threshold gates the judge composite; the deterministic hard signals
# force "faible" regardless of the judge (they mirror documented failures).
# ---------------------------------------------------------------------------
def deterministic_signals(query: str, passage: Dict[str, Any]) -> Dict[str, Any]:
    metrics = passage.get("metrics") or {}
    raw = passage.get("raw_answer") or ""
    answer = passage.get("answer") or ""
    sigs: List[str] = []
    if passage.get("error"):
        sigs.append(f"pipeline_error:{passage['error']}")
    if passage.get("grounding_state") == "no_grounded_context":
        sigs.append("grounding_no_context")
    if metrics.get("no_context"):
        sigs.append("no_context")
    if metrics.get("fallback") and metrics.get("fallback_reason"):
        sigs.append(f"fallback:{metrics.get('fallback_reason')}")
    if metrics.get("exact_match_guardrail_inserted"):
        sigs.append("exact_match_guardrail")
    if _HEDGE_RE.search(raw):
        sigs.append("hedge_analyse_generale")
    if _JARGON_LEAK_RE.search(raw):
        sigs.append("jargon_leak")
    for v in passage.get("answer_policy_violations") or []:
        sigs.append(f"policy:{v}")
    if str(metrics.get("cross_encoder_status") or "") in {"timeout", "error"}:
        sigs.append(f"xenc:{metrics.get('cross_encoder_status')}")
    if looks_german(query) and passage.get("response_language") != "de":
        sigs.append("language_contract_violation_de")
    if not answer.strip():
        sigs.append("empty_answer")
    # hard signals force weak independent of the judge
    hard = {
        "grounding_no_context", "no_context", "exact_match_guardrail",
        "hedge_analyse_generale", "jargon_leak", "language_contract_violation_de",
        "empty_answer",
    }
    hard_weak = any(s in hard or s.startswith("fallback:") or s.startswith("pipeline_error:")
                    for s in sigs)
    return {"signals": sigs, "hard_weak": hard_weak}


def _deterministic_failed_components(sigs: List[str]) -> List[str]:
    comps: set = set()
    for s in sigs:
        if s.startswith("fallback:") or s in {"grounding_no_context", "no_context", "exact_match_guardrail"} or s.startswith("xenc:"):
            comps.add("retriever")
        if s in {"hedge_analyse_generale", "jargon_leak", "language_contract_violation_de", "empty_answer"} or s.startswith("policy:"):
            comps.add("generator")
    return sorted(comps)


async def judge_passage(query: str, passage: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.evaluation.judge import get_judge_service
    svc = get_judge_service()
    return await svc.evaluate(
        query=query,
        response=passage.get("answer") or "",
        system_prompt=passage.get("system_prompt") or "",
        context_chunks=passage.get("context_chunks") or [],
    )


def build_verdict(query: str, passage: Dict[str, Any], judge: Dict[str, Any],
                  *, weak_threshold: float = 70.0) -> Dict[str, Any]:
    det = deterministic_signals(query, passage)
    composite = float(judge.get("composite_score") or 0.0)
    halluc = float(judge.get("hallucination_rate") or 0.0)
    judge_weak = composite < weak_threshold or halluc > 0.15
    weak = bool(det["hard_weak"] or judge_weak)
    failed = sorted(set((judge.get("failed_components") or []))
                    | set(_deterministic_failed_components(det["signals"])))
    primary = None
    if failed:
        primary = "retriever" if "retriever" in failed else failed[0]
    return {
        "verdict": "faible" if weak else "bon",
        "weak": weak,
        "hard_weak": det["hard_weak"],
        "judge_weak": judge_weak,
        "composite_score": composite,
        "hallucination_rate": halluc,
        "question_type": judge.get("question_type"),
        "failed_components": failed,
        "primary_failed_component": primary,
        "signals": det["signals"],
        "judge_note": judge.get("overall_note"),
    }


async def run_one(db, workspace, row: Dict[str, Any], *, escalate: bool,
                  case_timeout: float, weak_threshold: float) -> Dict[str, Any]:
    query = row["query"]
    history = row.get("conversation_history")
    suff = assess_sufficiency(query, has_history=bool(history))

    base = await faithful_chat(db, workspace, query, deep=False,
                               conversation_history=history, case_timeout=case_timeout)
    base_judge = await judge_passage(query, base)
    verdict = build_verdict(query, base, base_judge, weak_threshold=weak_threshold)

    out: Dict[str, Any] = {
        "id": row["id"],
        "source": row.get("source"),
        "lang": row.get("lang"),
        "ground_truth": row.get("ground_truth"),
        "query": query,
        "sufficiency": suff,
        "baseline": {
            "answer": base.get("answer"),
            "latency_ms": base.get("latency_ms"),
            "error": base.get("error"),
            "response_language": base.get("response_language"),
            "answer_profile": base.get("answer_profile"),
            "grounding_state": base.get("grounding_state"),
            "metrics": base.get("metrics"),
        },
        "verdict": verdict,
        "route": ("ambigu" if (verdict["weak"] and suff["ambiguous"])
                  else "faible" if verdict["weak"] else "bon"),
    }

    if escalate and verdict["weak"]:
        esc = await faithful_chat(db, workspace, query, deep=True,
                                  conversation_history=history, case_timeout=case_timeout)
        esc_judge = await judge_passage(query, esc)
        esc_verdict = build_verdict(query, esc, esc_judge, weak_threshold=weak_threshold)
        lift = round(esc_verdict["composite_score"] - verdict["composite_score"], 1)
        added_latency = (esc.get("latency_ms") or 0) - (base.get("latency_ms") or 0)
        out["escalation"] = {
            "answer": esc.get("answer"),
            "latency_ms": esc.get("latency_ms"),
            "added_latency_ms": added_latency,
            "error": esc.get("error"),
            "latency_profile": esc.get("latency_profile"),
            "metrics": esc.get("metrics"),
            "verdict": esc_verdict,
            "composite_lift": lift,
            "recovered": (not esc_verdict["weak"]),
        }
    return out


def _load_done_ids(jsonl_path: str) -> set:
    done = set()
    if jsonl_path and os.path.exists(jsonl_path):
        with open(jsonl_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(json.loads(line)["id"])
                except Exception:
                    continue
    return done


async def run_corpus(rows: List[Dict[str, Any]], *, escalate: bool, case_timeout: float,
                     weak_threshold: float, jsonl_path: str, resume: bool) -> List[Dict[str, Any]]:
    from app.db.base import SessionLocal
    from app.models.workspace import Workspace

    await bootstrap_orchestrator()
    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.slug == WORKSPACE_SLUG).first()
        if not workspace:
            raise SystemExit(f"workspace not found: {WORKSPACE_SLUG}")
        done = _load_done_ids(jsonl_path) if resume else set()
        results: List[Dict[str, Any]] = []
        # keep previously-finished rows so aggregation is complete on resume
        if resume and done:
            with open(jsonl_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            results.append(json.loads(line))
                        except Exception:
                            pass
        total = len(rows)
        for idx, row in enumerate(rows, start=1):
            if row["id"] in done:
                print(f"[{idx:03d}/{total:03d}] SKIP (done) {row['id']}", flush=True)
                continue
            try:
                res = await run_one(db, workspace, row, escalate=escalate,
                                    case_timeout=case_timeout, weak_threshold=weak_threshold)
            except Exception as exc:  # noqa: BLE001
                res = {"id": row["id"], "source": row.get("source"), "lang": row.get("lang"),
                       "ground_truth": row.get("ground_truth"), "query": row["query"],
                       "error": f"{type(exc).__name__}: {exc}"}
            results.append(res)
            if jsonl_path:
                with open(jsonl_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(res, ensure_ascii=False) + "\n")
            v = (res.get("verdict") or {})
            esc = (res.get("escalation") or {})
            tag = v.get("verdict", "?")
            extra = f" lift={esc.get('composite_lift')} recovered={esc.get('recovered')}" if esc else ""
            print(f"[{idx:03d}/{total:03d}] {tag:6s} {res['id']} "
                  f"comp={v.get('composite_score')} route={res.get('route')}{extra}", flush=True)
        return results
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Aggregation + calibration.
# ---------------------------------------------------------------------------
def _mean(xs: List[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def calibrate(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    labeled = [r for r in results
               if r.get("ground_truth") in {"bon", "faible"} and r.get("verdict")]
    points = []
    for t in range(50, 95, 5):
        tp = fp = tn = fn = 0
        for r in labeled:
            v = r["verdict"]
            pred_weak = bool(v.get("hard_weak")
                             or (v.get("composite_score", 0.0) < t)
                             or (v.get("hallucination_rate", 0.0) > 0.15))
            truth_weak = r["ground_truth"] == "faible"
            if pred_weak and truth_weak:
                tp += 1
            elif pred_weak and not truth_weak:
                fp += 1
            elif not pred_weak and not truth_weak:
                tn += 1
            else:
                fn += 1
        prec = tp / (tp + fp) if (tp + fp) else None
        rec = tp / (tp + fn) if (tp + fn) else None
        f1 = (2 * prec * rec / (prec + rec)) if (prec and rec) else None
        points.append({
            "threshold": t, "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": round(prec, 3) if prec is not None else None,
            "recall": round(rec, 3) if rec is not None else None,
            "f1": round(f1, 3) if f1 is not None else None,
        })
    # deterministic-only baseline (hard signals, no judge threshold)
    tp = fp = tn = fn = 0
    for r in labeled:
        pred = bool(r["verdict"].get("hard_weak"))
        truth = r["ground_truth"] == "faible"
        tp += int(pred and truth); fp += int(pred and not truth)
        tn += int(not pred and not truth); fn += int(not pred and truth)
    det_prec = tp / (tp + fp) if (tp + fp) else None
    det_rec = tp / (tp + fn) if (tp + fn) else None
    best = max((p for p in points if p["f1"] is not None),
               key=lambda p: p["f1"], default=None)
    return {
        "labeled_n": len(labeled),
        "labeled_bon": sum(1 for r in labeled if r["ground_truth"] == "bon"),
        "labeled_faible": sum(1 for r in labeled if r["ground_truth"] == "faible"),
        "curve": points,
        "best_threshold": best,
        "deterministic_only": {
            "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": round(det_prec, 3) if det_prec is not None else None,
            "recall": round(det_rec, 3) if det_rec is not None else None,
        },
    }


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    scored = [r for r in results if r.get("verdict")]
    errors = [r for r in results if r.get("error") and not r.get("verdict")]
    weak = [r for r in scored if r["verdict"]["weak"]]
    bon = [r for r in scored if not r["verdict"]["weak"]]
    n = len(scored)

    comp_by_fail: Dict[str, int] = {}
    primary_by_fail: Dict[str, int] = {}
    for r in weak:
        for c in r["verdict"].get("failed_components") or []:
            comp_by_fail[c] = comp_by_fail.get(c, 0) + 1
        p = r["verdict"].get("primary_failed_component")
        if p:
            primary_by_fail[p] = primary_by_fail.get(p, 0) + 1

    escalated = [r for r in weak if r.get("escalation")]
    recovered = [r for r in escalated if r["escalation"].get("recovered")]
    lifts = [r["escalation"].get("composite_lift") for r in escalated]
    added = [r["escalation"].get("added_latency_ms") for r in escalated]

    ambiguous = [r for r in scored if (r.get("sufficiency") or {}).get("ambiguous")]
    ambiguous_weak = [r for r in weak if (r.get("sufficiency") or {}).get("ambiguous")]
    routes: Dict[str, int] = {}
    for r in scored:
        routes[r.get("route", "?")] = routes.get(r.get("route", "?"), 0) + 1

    by_source: Dict[str, Dict[str, int]] = {}
    for r in scored:
        s = r.get("source", "?")
        b = by_source.setdefault(s, {"n": 0, "weak": 0})
        b["n"] += 1
        b["weak"] += int(r["verdict"]["weak"])

    base_lat = [r["baseline"].get("latency_ms") for r in scored if r.get("baseline")]
    esc_lat = [r["escalation"].get("latency_ms") for r in escalated]

    return {
        "n_scored": n,
        "n_errors": len(errors),
        "error_ids": [r["id"] for r in errors],
        "objective_1_weak": {
            "weak_count": len(weak),
            "weak_rate_pct": round(100.0 * len(weak) / n, 1) if n else None,
            "bon_count": len(bon),
            "failed_components_all": comp_by_fail,
            "primary_failed_component": primary_by_fail,
            "by_source": by_source,
        },
        "objective_2_escalation": {
            "weak_escalated": len(escalated),
            "recovered_count": len(recovered),
            "recovery_rate_pct": round(100.0 * len(recovered) / len(escalated), 1) if escalated else None,
            "mean_composite_lift": _mean(lifts),
            "mean_added_latency_ms": _mean(added),
        },
        "objective_3_clarification": {
            "ambiguous_count": len(ambiguous),
            "ambiguous_rate_pct": round(100.0 * len(ambiguous) / n, 1) if n else None,
            "ambiguous_among_weak": len(ambiguous_weak),
            "ambiguous_among_weak_pct": round(100.0 * len(ambiguous_weak) / len(weak), 1) if weak else None,
            "route_distribution": routes,
        },
        "objective_4_calibration": calibrate(results),
        "latency": {
            "mean_baseline_ms": _mean(base_lat),
            "mean_escalation_ms": _mean(esc_lat),
        },
    }


def _select_rows() -> List[Dict[str, Any]]:
    ids_env = os.environ.get("SPIKE_IDS", "").strip()
    rows = CORPUS
    if ids_env:
        wanted = {x.strip() for x in ids_env.split(",") if x.strip()}
        return [r for r in rows if r["id"] in wanted]
    try:
        limit = int(os.environ.get("SPIKE_LIMIT", "0") or "0")
    except ValueError:
        limit = 0
    return rows[:limit] if limit > 0 else rows


def main() -> None:
    output = os.environ.get("SPIKE_OUTPUT", "/tmp/agentic_spike_report.json")
    jsonl = os.environ.get("SPIKE_JSONL", "/tmp/agentic_spike_rows.jsonl")
    escalate = os.environ.get("SPIKE_NO_ESCALATE", "0") != "1"
    resume = os.environ.get("SPIKE_RESUME", "0") == "1"
    try:
        case_timeout = float(os.environ.get("SPIKE_CASE_TIMEOUT", "150"))
    except ValueError:
        case_timeout = 150.0
    try:
        weak_threshold = float(os.environ.get("SPIKE_WEAK_THRESHOLD", "70"))
    except ValueError:
        weak_threshold = 70.0

    rows = _select_rows()
    print(f"SPIKE start: {len(rows)} rows, escalate={escalate}, resume={resume}, "
          f"timeout={case_timeout}s, jsonl={jsonl}", flush=True)
    results = asyncio.run(run_corpus(
        rows, escalate=escalate, case_timeout=case_timeout,
        weak_threshold=weak_threshold, jsonl_path=jsonl, resume=resume))
    summary = summarize(results)
    report = {"workspace": WORKSPACE_SLUG, "corpus_size": len(results),
              "summary": summary, "results": results}
    with open(output, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print("===SPIKE_SUMMARY_BEGIN===", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print("===SPIKE_SUMMARY_END===", flush=True)
    print(f"report written: {output}", flush=True)


if __name__ == "__main__":
    main()

