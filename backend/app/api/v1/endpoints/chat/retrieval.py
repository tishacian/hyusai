"""Retrieval observability, collection filters and auto deep-retrieval jobs."""

import uuid
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import Message, User
from app.models.workspace import Workspace
from app.services.collection_access import (
    bind_retrieval_identity,
    load_principal,
    require_named_collection_read,
)
from app.models.workspace_job import WorkspaceJob
from app.services.mission_room import (
    briefing_payload,
    cockpit_payload,
    news_payload,
    present_payload_for_workspace,
    source_index,
)
from app.api.v1.endpoints.chat.common import (
    _RETRIEVAL_OBSERVABILITY_KEYS,
)
from app.api.v1.endpoints.chat.sessions import (
    _apply_retrieval_budget_policy,
)


def _retrieval_metrics(state: Dict[str, Any]) -> Dict[str, Any]:
    metrics = state.get("retrieval_metrics")
    return metrics if isinstance(metrics, dict) else {}


def _retrieval_latency_profile(state: Dict[str, Any]) -> Optional[str]:
    metrics = _retrieval_metrics(state)
    for source in (state, metrics):
        value = source.get("latency_profile") if isinstance(source, dict) else None
        if value:
            return str(value)
        budget = source.get("latency_budget") if isinstance(source, dict) else None
        if isinstance(budget, dict) and budget.get("profile"):
            return str(budget["profile"])
    return None


def _retrieval_observability(state: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten key RAG diagnostics onto message/run payloads.

    ``retrieval_metrics`` remains the full raw trace. This compact snapshot is
    intentionally duplicated at the top level so SQL dashboards and run cards
    can filter on operational signals without knowing the nested shape.
    """
    metrics = _retrieval_metrics(state)
    snapshot: Dict[str, Any] = {}
    for key in _RETRIEVAL_OBSERVABILITY_KEYS:
        value = state.get(key)
        if value is None:
            value = metrics.get(key)
        if value is not None:
            snapshot[key] = value
    latency_profile = _retrieval_latency_profile(state)
    if latency_profile:
        snapshot["latency_profile"] = latency_profile
        snapshot["retrieval_latency_profile"] = latency_profile
    if snapshot:
        snapshot.setdefault("retrieval_latency_scope", "direct_chat")
    return snapshot


def _retrieval_fallback_reason(state: Dict[str, Any]) -> Optional[Any]:
    fallback = state.get("retrieval_fallback")
    if isinstance(fallback, str) and fallback:
        return fallback
    reason = _retrieval_metrics(state).get("fallback_reason")
    return reason if reason else None


def _dense_fast_degraded_reply(state: Dict[str, Any]) -> Optional[str]:
    metrics = _retrieval_metrics(state)
    dense_policy = str(state.get("dense_policy") or metrics.get("dense_policy") or "")
    fallback_reason = str(_retrieval_fallback_reason(state) or "")
    if dense_policy != "fast_scoped_dense_auto" or fallback_reason != "dense_unscoped_fast_policy":
        return None
    scope = state.get("retrieval_scope") if isinstance(state.get("retrieval_scope"), dict) else {}
    try:
        source_count = int(scope.get("source_count") or metrics.get("source_count") or 0)
    except (TypeError, ValueError):
        source_count = 0
    try:
        chunk_count = int(scope.get("chunk_count") or metrics.get("chunk_count") or 0)
    except (TypeError, ValueError):
        chunk_count = 0
    parts = [
        "Cette collection est trop dense pour une recherche globale instantanee.",
        "J'ai donc evite le balayage complet des chunks et garde Quick Ask sur un perimetre sur.",
    ]
    if source_count or chunk_count:
        parts.insert(
            1,
            f"Inventaire detecte: {source_count:,} sources et {chunk_count:,} chunks.".replace(
                ",", " "
            ),
        )
    if state.get("deep_job_id"):
        parts.append("Un Deep Retrieval est deja en file pour raffiner la reponse en arriere-plan.")
    else:
        parts.append(
            "Je lance un Deep Retrieval asynchrone pour raffiner la reponse sans bloquer le chat."
        )
    return " ".join(parts)


def _retrieval_has_grounded_context(state: Dict[str, Any]) -> Optional[bool]:
    """Tri-state evidence check from the retrieval chunk telemetry.

    Returns None when the retrieval chunk carries no usable signal — the
    grounding guard must not fire on guesswork.
    """
    metrics = _retrieval_metrics(state)
    if not metrics:
        return None
    if bool(metrics.get("no_context")):
        return False
    if "chunks_retrieved" in metrics:
        try:
            return int(metrics.get("chunks_retrieved") or 0) > 0
        except (TypeError, ValueError):
            return None
    if _retrieval_fallback_reason(state):
        return False
    return None


def _grounding_degraded_reply(
    state: Dict[str, Any],
    grounding_policy: Optional[Dict[str, Any]],
    *,
    response_language: Optional[str] = None,
    is_meta_followup: bool = False,
) -> Optional[str]:
    """Post-retrieval grounding guard.

    The grounding policy is resolved before retrieval; when strict mode meets
    an empty or failed retrieval the LLM would have to answer without
    evidence. Return the policy's disclaimer instead so the turn ends with an
    explicit "no usable sources" statement. Meta follow-ups ("résume",
    "détaille") legitimately run without fresh retrieval and are exempt.
    """
    if is_meta_followup:
        return None
    policy = grounding_policy if isinstance(grounding_policy, dict) else {}
    if str(policy.get("mode") or "").strip().lower() != "strict":
        return None
    if _retrieval_has_grounded_context(state) is not False:
        return None
    disclaimer = str(policy.get("fallback_disclaimer") or "").strip()
    if not disclaimer:
        disclaimer = (
            "Je n'ai trouvé aucune source exploitable dans le périmètre sélectionné ; "
            "je préfère ne pas répondre sans évidence documentaire."
            if (response_language or "fr") == "fr"
            else "I could not find usable sources in the selected scope; "
            "I will not answer without documentary evidence."
        )
    reason = str(_retrieval_fallback_reason(state) or "no_grounded_context")
    return f"{disclaimer} retrieval: {reason}"


def _deep_refinement_preview_text(
    *,
    content: str,
    state: Dict[str, Any],
    grounding_policy: Optional[Dict[str, Any]],
) -> str:
    if state.get("grounding_state") != "no_grounded_context":
        return content
    policy = grounding_policy if isinstance(grounding_policy, dict) else {}
    fallback = str(policy.get("fallback_disclaimer") or "").strip()
    return fallback or content


_SYSTEM_RETRIEVAL_FILTER_KEYS = {
    "collection",
    "collection_slug",
    "document_id",
    "document_filename",
    "source_kind",
    "extension",
    "status",
    "project_code",
    "archive_name",
    "language",
}


def _clean_system_retrieval_filter_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        out: list[Any] = []
        for item in value:
            cleaned = _clean_system_retrieval_filter_value(item)
            if cleaned is not None and cleaned not in out:
                out.append(cleaned)
        return out or None
    return None


def _sanitize_workspace_collection_filters(
    db: Session,
    *,
    workspace_id: str,
    retrieval_filters: Any,
) -> Dict[str, Any]:
    if not isinstance(retrieval_filters, dict):
        return {}

    from app.models.knowledge_collection import KnowledgeCollection

    sanitized = dict(retrieval_filters)
    for key in ("collection_slug", "collection"):
        raw_value = sanitized.get(key)
        if raw_value is None:
            continue
        is_many = isinstance(raw_value, (list, tuple, set))
        values = raw_value if is_many else [raw_value]
        resolved: list[str] = []
        for value in values:
            collection_ref = str(value or "").strip()
            if not collection_ref:
                continue
            collection = (
                db.query(KnowledgeCollection)
                .filter(
                    (
                        (KnowledgeCollection.slug == collection_ref)
                        | (KnowledgeCollection.id == collection_ref)
                    ),
                    KnowledgeCollection.workspace_id == workspace_id,
                )
                .first()
            )
            if collection and collection.slug not in resolved:
                resolved.append(collection.slug)
        if resolved:
            sanitized[key] = resolved if is_many else resolved[0]
        else:
            sanitized.pop(key, None)
    return sanitized


def _client_collection_refs(request_dict: Dict[str, Any]) -> list[str]:
    """Collections the client named: retrieval filters and the selected Context."""
    refs: list[str] = []
    filters = request_dict.get("retrieval_filters")
    if isinstance(filters, dict):
        for key in ("collection_slug", "collection"):
            value = filters.get(key)
            values = value if isinstance(value, (list, tuple, set)) else [value]
            refs.extend(str(item).strip() for item in values if str(item or "").strip())
    context_collection = str(request_dict.get("context_collection") or "").strip()
    if context_collection:
        refs.append(context_collection)
    return list(dict.fromkeys(refs))


def _apply_collection_access(
    db: Session,
    *,
    workspace: Workspace,
    user: Optional[User],
    request_dict: Dict[str, Any],
) -> None:
    """Carry the member into retrieval and refuse collections they cannot read.

    Call it once the client's own scope (filters, selected Context) is on the
    request and before server-owned System scopes are folded in. A collection
    the client named but cannot read answers 404, like the documents API; every
    other restricted collection is silently left out by the retrieval core
    (``collection_access.retrieval_collection_access``), which also covers
    server-owned scopes and runs without this request.
    """
    user_id = getattr(user, "id", None)
    bind_retrieval_identity(request_dict, workspace_id=workspace.id, user_id=user_id)
    refs = _client_collection_refs(request_dict)
    if not refs:
        return
    principal = load_principal(db, workspace_id=workspace.id, user_id=user_id)
    for ref in refs:
        require_named_collection_read(db, workspace=workspace, collection_ref=ref, member=principal)


def _inferred_scope_filters(state: Dict[str, Any]) -> Dict[str, Any]:
    scope = state.get("retrieval_scope")
    if not isinstance(scope, dict):
        metrics_scope = _retrieval_metrics(state).get("retrieval_scope")
        scope = metrics_scope if isinstance(metrics_scope, dict) else {}
    raw_filters = scope.get("filters") if isinstance(scope, dict) else {}
    if not isinstance(raw_filters, dict):
        return {}
    filters: Dict[str, Any] = {}
    for key, value in raw_filters.items():
        if key not in _SYSTEM_RETRIEVAL_FILTER_KEYS:
            continue
        cleaned = _clean_system_retrieval_filter_value(value)
        if cleaned is not None:
            filters[key] = cleaned
    return filters


def _merge_inferred_retrieval_filters(
    request_dict: Dict[str, Any],
    state: Dict[str, Any],
) -> tuple[Dict[str, Any], list[str]]:
    inferred = _inferred_scope_filters(state)
    if not inferred:
        return {}, []
    existing = (
        dict(request_dict.get("retrieval_filters"))
        if isinstance(request_dict.get("retrieval_filters"), dict)
        else {}
    )
    merged = dict(existing)
    forwarded: list[str] = []
    for key, value in inferred.items():
        if key in merged and _clean_system_retrieval_filter_value(merged.get(key)) is not None:
            continue
        merged[key] = value
        forwarded.append(key)
    request_dict["retrieval_filters"] = merged
    return merged, forwarded


def _should_queue_auto_deep_retrieval(request_dict: Dict[str, Any], state: Dict[str, Any]) -> bool:
    if not settings.rag_auto_deep_retrieval_enabled:
        return False
    if request_dict.get("deep_retrieval") or request_dict.get("latency_profile") == "deep":
        return False
    if state.get("deep_job_id"):
        return False

    metrics = _retrieval_metrics(state)
    dense_policy = str(state.get("dense_policy") or metrics.get("dense_policy") or "")
    fallback_reason = _retrieval_fallback_reason(state)
    recommended = bool(
        state.get("deep_retrieval_recommended")
        or metrics.get("deep_retrieval_recommended")
        or fallback_reason
        in {
            "retrieval_deadline_exceeded",
            "worker_timeout",
            "worker_error",
            "dense_unscoped_fast_policy",
        }
    )
    if not recommended:
        return False

    try:
        confidence = float(state.get("scope_confidence") or metrics.get("scope_confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    try:
        chunks_retrieved = int(metrics.get("chunks_retrieved") or 0)
    except (TypeError, ValueError):
        chunks_retrieved = 0
    no_context = bool(metrics.get("no_context") or chunks_retrieved == 0)
    degraded_reasons = {
        "retrieval_deadline_exceeded",
        "worker_timeout",
        "worker_error",
        "document_service_unavailable",
    }
    if str(fallback_reason or "") in degraded_reasons:
        return True
    if dense_policy.startswith("fast_scoped_dense") and no_context:
        return confidence < float(settings.rag_auto_deep_retrieval_min_confidence)
    if dense_policy == "fast_scoped_dense_auto":
        return bool(settings.rag_auto_deep_retrieval_dense_unscoped)
    return False


def _compact_job_text(value: Any, *, max_chars: int = 1200) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."


def _compact_job_sources(sources: Any, *, limit: int = 8) -> list[Dict[str, Any]]:
    if not isinstance(sources, list):
        return []
    allowed = (
        "id",
        "document_id",
        "title",
        "filename",
        "source",
        "source_name",
        "collection",
        "collection_name",
        "collection_slug",
        "page",
        "score",
        "source_kind",
        "extension",
        "project_code",
        "archive_name",
        "snippet",
        "content",
        "text",
        "metadata",
    )
    metadata_allowed = {
        "chunk_id",
        "chunk_index",
        "document_id",
        "document_title",
        "document_filename",
        "source_kind",
        "extension",
        "project_code",
        "archive_name",
        "language",
        "status",
        "page",
        "section",
        "section_title",
    }
    compact: list[Dict[str, Any]] = []
    for raw in sources[: max(0, limit)]:
        if not isinstance(raw, dict):
            continue
        item: Dict[str, Any] = {}
        for key in allowed:
            value = raw.get(key)
            if value is None:
                continue
            if key in {"snippet", "content", "text"}:
                item[key] = _compact_job_text(value)
            elif key == "metadata" and isinstance(value, dict):
                item[key] = {
                    meta_key: meta_value
                    for meta_key, meta_value in value.items()
                    if meta_key in metadata_allowed and meta_value is not None
                }
            elif isinstance(value, (str, int, float, bool)):
                item[key] = value
        if item:
            compact.append(item)
    return compact


def _queue_auto_deep_retrieval_job(
    *,
    db: Session,
    workspace: Workspace,
    user: Optional[User],
    request_dict: Dict[str, Any],
    state: Dict[str, Any],
    partial_answer: Optional[str] = None,
    partial_sources: Any = None,
    parent_message_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if not _should_queue_auto_deep_retrieval(request_dict, state):
        return None

    from app.models.knowledge_collection import KnowledgeCollection
    from app.services.rag.context import get_retrieval_profile
    from app.services.workspace_jobs import (
        create_workspace_job,
        dispatch_workspace_job,
        serialize_job,
    )

    payload = dict(request_dict)
    payload["latency_profile"] = "deep"
    payload["deep_retrieval"] = True
    payload["auto_deep_retrieval"] = True
    _, forwarded_filter_keys = _merge_inferred_retrieval_filters(payload, state)
    for key in ("top_k", "candidate_pool_k", "synthesis_k", "source_display_k"):
        payload.pop(key, None)
    _apply_retrieval_budget_policy(payload)
    profile = get_retrieval_profile(payload)
    collection_ref = profile.get("collection")
    collection = None
    if collection_ref:
        collection = (
            db.query(KnowledgeCollection)
            .filter(
                (
                    (KnowledgeCollection.slug == collection_ref)
                    | (KnowledgeCollection.id == collection_ref)
                ),
                KnowledgeCollection.workspace_id == workspace.id,
            )
            .first()
        )
    session_id = str(payload.get("session_id") or "")
    message_id = None
    if session_id:
        placeholder = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role="assistant",
            content="Recherche approfondie lancée pour affiner cette réponse.",
            meta_data={
                "deep_status": "queued",
                "deep_stage": "queued",
                "deep_poll_url": None,
                "parent_message_id": parent_message_id,
                "sources": [],
            },
        )
        db.add(placeholder)
        db.flush()
        message_id = placeholder.id
    compact_sources = _compact_job_sources(partial_sources)
    partial_result: Dict[str, Any] = {}
    if partial_answer and partial_answer.strip():
        answer_preview = " ".join(partial_answer.split())
        partial_result["answer_preview"] = (
            answer_preview[:3997] + "..." if len(answer_preview) > 4000 else answer_preview
        )
    if compact_sources:
        partial_result["sources_preview"] = compact_sources
    metrics = _retrieval_metrics(state)
    fallback_reason = _retrieval_fallback_reason(state)
    if metrics:
        partial_result["retrieval_summary"] = {
            "chunks_retrieved": metrics.get("chunks_retrieved"),
            "fallback_reason": fallback_reason,
            "dense_policy": state.get("dense_policy") or metrics.get("dense_policy"),
            "scope_confidence": state.get("scope_confidence") or metrics.get("scope_confidence"),
        }
    job = create_workspace_job(
        db,
        workspace,
        user,
        title=f"Deep Search · {str(payload.get('query') or '')[:96]}",
        input_ref={
            "request": payload,
            "latency_profile": "deep",
            "trigger": "auto_fast_refinement",
            "partial_result": partial_result or None,
            "parent_retrieval": {
                "dense_policy": state.get("dense_policy"),
                "scope_confidence": state.get("scope_confidence"),
                "scope_reason": state.get("scope_reason"),
                "fallback_reason": fallback_reason,
                "retrieval_scope": state.get("retrieval_scope"),
                "inferred_filters_forwarded": bool(forwarded_filter_keys),
                "forwarded_filter_keys": forwarded_filter_keys,
            },
        },
        collection_id=collection.id if collection else None,
        kind="rag_deep_retrieval",
        session_id=session_id or None,
        parent_message_id=parent_message_id,
        message_id=message_id,
        status="queued",
    )
    if message_id:
        placeholder.meta_data = {
            **(placeholder.meta_data or {}),
            "workspace_job_id": job.id,
            "deep_job_id": job.id,
            "deep_poll_url": f"/workspace-jobs/{job.id}",
        }
    db.commit()
    task_id = dispatch_workspace_job(db, workspace, job, allow_inline_fallback=False)
    db.commit()
    refreshed = db.query(WorkspaceJob).filter(WorkspaceJob.id == job.id).first() or job
    state["deep_job_id"] = refreshed.id
    state["deep_poll_url"] = f"/workspace-jobs/{refreshed.id}"
    state["deep_status"] = refreshed.status
    state["deep_retrieval_recommended"] = True
    serialized = serialize_job(refreshed)
    return {
        "deep_job_id": refreshed.id,
        "deep_task_id": task_id,
        "deep_poll_url": state["deep_poll_url"],
        "deep_status": refreshed.status,
        "deep_progress": refreshed.progress,
        "deep_stage": serialized.get("stage"),
        "message_id": message_id,
    }


def _vigie_executive_quick_reply(
    db: Session,
    workspace: Workspace,
    query: str,
    *,
    assistant_profile: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Return a generic data-driven fallback reply for vigie_executive prompts.

    This is intentionally a **safety net only**. Business-specific narratives
    (zone Nord, port, presse, agenda…) MUST be expressed as Action Manifest
    phrases in ``app.services.actions.registry`` (pack ``sentinel_ci_aya_v1``)
    and routed through ``handle_registry_chat_action`` so the executor stays
    the single source of dynamic narrative. When the resolver finds no match
    and the query is clearly a generic briefing-style ask, we return a
    consolidated 3-signal summary built from ``news_payload``/``cockpit_payload``
    (no hardcoded narrative).
    """
    if assistant_profile not in {"vigie_executive", "octave_executive"}:
        return None
    normalized = query.lower()
    trigger_terms = (
        "signal",
        "signaux",
        "attention cabinet",
        "alerte",
        "alertes",
        "synthese",
        "synthèse",
        "veille",
    )
    if not any(term in normalized for term in trigger_terms):
        return None

    news = news_payload(workspace, db)
    cockpit = cockpit_payload(workspace, db)
    briefing = briefing_payload(workspace)
    alerts = (
        news.get("executive_alerts") or news.get("signals") or cockpit.get("latest_alerts") or []
    )[:3]
    note = news.get("briefing_note") or {}
    source_health = news.get("source_health") or {}
    sources_catalog = news.get("sources") or cockpit.get("sources") or source_index()
    source_lookup = {str(item.get("id")): item for item in sources_catalog if item.get("id")}

    lines = [
        "Monsieur le Vice Premier Ministre, trois signaux méritent une attention cabinet aujourd'hui :"
    ]
    if alerts:
        for idx, alert in enumerate(alerts, start=1):
            title = alert.get("title") or "Signal à qualifier"
            impact = (
                alert.get("impact_ci") or alert.get("summary") or alert.get("why_it_matters") or ""
            )
            action = alert.get("recommended_action") or "Qualifier le signal avant décision."
            confidence = alert.get("confidence")
            confidence_txt = (
                f" Confiance {round(float(confidence) * 100)}%."
                if isinstance(confidence, (int, float))
                else ""
            )
            lines.append(f"{idx}. {title} — {impact} Action proposée : {action}.{confidence_txt}")
    else:
        for idx, bullet in enumerate(
            (note.get("bullets") or briefing.get("key_points") or [])[:3], start=1
        ):
            lines.append(f"{idx}. {bullet}")

    decisions = note.get("decisions_expected") or briefing.get("decisions_expected") or []
    if decisions:
        lines.append("")
        lines.append(
            "Décisions attendues : " + " ; ".join(str(item) for item in decisions[:3]) + "."
        )

    if source_health:
        coverage = source_health.get("coverage_label") or "sources qualifiées disponibles"
        run_id = source_health.get("last_run_id")
        lines.append("")
        lines.append(
            f"Couverture : {coverage}" + (f" · dernier run {run_id}" if run_id else "") + "."
        )

    source_ids = []
    for alert in alerts:
        source_ids.extend([str(item) for item in (alert.get("sources") or [])])
    sources = [
        {
            "title": source_lookup.get(source_id, {}).get("label") or source_id,
            "source_label": source_lookup.get(source_id, {}).get("label") or source_id,
            "kind": source_lookup.get(source_id, {}).get("kind") or "mission_room",
            "confidence": source_lookup.get(source_id, {}).get("confidence"),
        }
        for source_id in source_ids[:5]
    ]
    if not sources:
        sources = [
            {
                "title": "Mission Room SENTINEL-CI",
                "source_label": "Briefing souverain",
                "kind": "mission_room",
            }
        ]

    return present_payload_for_workspace(
        workspace,
        {
            "content": "\n".join(lines),
            "sources": sources,
            "details": {
                "live_news_used": bool(source_health.get("live_news_used")),
                "last_run_id": source_health.get("last_run_id"),
                "alert_count": len(alerts),
            },
        },
    )
