"""Worker for asynchronous deep RAG retrieval jobs."""
from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.models.knowledge_collection import WorkerJob
from app.models.user import Message
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.knowledge_collections import update_job
from app.services.rag.context import retrieve_rag_context
from app.services.workspace_jobs import transition_job

logger = get_logger(__name__)

_MAX_SOURCE_PREVIEW = 12
_MAX_SOURCE_SNIPPET_CHARS = 1200
_MAX_SYNTHESIS_SOURCES = 8
_MAX_SYNTHESIS_CHARS = 9000
_MAX_SYNTHESIS_TOKENS = 900
_PREVIEW_METADATA_KEYS = (
    "chunk_id",
    "chunk_index",
    "document_id",
    "document_title",
    "document_filename",
    "filename",
    "source",
    "source_name",
    "collection",
    "collection_name",
    "collection_slug",
    "source_kind",
    "extension",
    "project_code",
    "archive_name",
    "language",
    "status",
    "page",
    "page_number",
    "section",
    "section_title",
)


def _compact_text(value: Any, *, max_chars: int = _MAX_SOURCE_SNIPPET_CHARS) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."


def _compact_answer_text(value: Any, *, max_chars: int = 6000) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    compacted: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if not previous_blank and compacted:
                compacted.append("")
            previous_blank = True
            continue
        compacted.append(line)
        previous_blank = False
    result = "\n".join(compacted).strip()
    if len(result) <= max_chars:
        return result
    return result[: max(0, max_chars - 3)].rstrip() + "..."


def _clean_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None and value != ""}


def _safe_float(value: Any) -> float | None:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _source_label(meta: Any) -> str | None:
    if not isinstance(meta, dict):
        return None
    for key in (
        "document_title",
        "document_filename",
        "filename",
        "source",
        "source_name",
        "document_id",
    ):
        value = meta.get(key)
        if value:
            return str(value)
    return None


def _compact_deep_retrieval_sources(
    context: dict[str, Any],
    *,
    limit: int = _MAX_SOURCE_PREVIEW,
) -> list[dict[str, Any]]:
    chunks = context.get("chunks") if isinstance(context.get("chunks"), list) else []
    scores = context.get("scores") if isinstance(context.get("scores"), list) else []
    metadatas = context.get("metadatas") if isinstance(context.get("metadatas"), list) else []
    collection = context.get("collection") if context.get("collection") else None
    preview: list[dict[str, Any]] = []
    for index, raw_chunk in enumerate(chunks[: max(0, limit)]):
        meta = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
        score = _safe_float(scores[index]) if index < len(scores) else None
        document_id = meta.get("document_id") or meta.get("id")
        filename = meta.get("document_filename") or meta.get("filename") or meta.get("source") or meta.get("source_name")
        title = meta.get("document_title") or meta.get("title") or filename or document_id
        snippet = _compact_text(raw_chunk)
        metadata = {key: meta.get(key) for key in _PREVIEW_METADATA_KEYS if meta.get(key) is not None}
        preview.append(
            _clean_dict(
                {
                    "id": meta.get("chunk_id") or f"{document_id or 'deep'}:{index}",
                    "document_id": str(document_id) if document_id else None,
                    "title": str(title) if title else None,
                    "filename": str(filename) if filename else None,
                    "snippet": snippet,
                    "content": snippet,
                    "score": score,
                    "collection": meta.get("collection") or meta.get("collection_slug") or collection,
                    "collection_name": meta.get("collection_name") or meta.get("collection") or collection,
                    "page": meta.get("page") or meta.get("page_number"),
                    "metadata": metadata,
                }
            )
        )
    return preview


def _summarize_deep_retrieval_context(context: dict[str, Any]) -> dict[str, Any]:
    chunks = context.get("chunks") if isinstance(context.get("chunks"), list) else []
    scores = context.get("scores") if isinstance(context.get("scores"), list) else []
    metadatas = context.get("metadatas") if isinstance(context.get("metadatas"), list) else []
    metrics = context.get("metrics") if isinstance(context.get("metrics"), dict) else {}
    source_counts: dict[str, int] = {}
    for meta in metadatas:
        label = _source_label(meta)
        if not label:
            continue
        source_counts[label] = source_counts.get(label, 0) + 1
    top_sources = [
        {"label": label, "chunks": count}
        for label, count in sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]
    top_score: float | None = None
    if scores:
        try:
            top_score = round(float(scores[0]), 4)
        except (TypeError, ValueError):
            top_score = None
    return {
        "chunks_retrieved": len(chunks),
        "sources_returned": len(source_counts),
        "top_sources": top_sources,
        "top_score": top_score,
        "sources_preview_count": min(len(chunks), _MAX_SOURCE_PREVIEW),
        "pipeline": context.get("pipeline"),
        "mode_label": context.get("mode_label") or context.get("label"),
        "collection": context.get("collection"),
        "dense_policy": context.get("dense_policy") or metrics.get("dense_policy"),
        "retrieval_plan": context.get("retrieval_plan") or metrics.get("retrieval_plan"),
        "scope_confidence": context.get("scope_confidence") or metrics.get("scope_confidence"),
        "fallback_reason": context.get("fallback_reason") or metrics.get("fallback_reason"),
        "duration_ms": metrics.get("duration_ms"),
    }


def _model_preferences(payload: dict[str, Any]) -> tuple[str, str]:
    from app.core.settings_manager import get_resolved_settings

    preferences = payload.get("agent_preferences")
    model_preferences = (
        preferences.get("model_preferences")
        if isinstance(preferences, dict) and isinstance(preferences.get("model_preferences"), dict)
        else {}
    )
    resolved = get_resolved_settings(
        workspace_id=str(payload.get("workspace_id") or "") or None,
        system_id=str(payload.get("agent_id") or payload.get("system_id") or "") or None,
    )
    resolved_provider = str(resolved.get("defaultProvider") or settings.default_provider or "openai").strip()
    resolved_model = str(resolved.get("defaultModel") or settings.default_model or "gpt-5").strip()
    requested_provider = str(model_preferences.get("provider") or "").strip()
    requested_model = str(model_preferences.get("model") or "").strip()

    legacy_client_defaults = {"gpt-4o", "gpt-4o-mini", "deepseek-r1:14b", ""}
    if requested_model.lower() in legacy_client_defaults and resolved_model:
        provider = resolved_provider
        model = resolved_model
    else:
        provider = requested_provider or resolved_provider
        model = requested_model
    if provider == "ollama":
        model = model or str(settings.ollama_default_model)
    else:
        model = model or resolved_model or str(settings.default_model or "gpt-5")
    return provider, model


def _extractive_deep_answer(
    query: str,
    sources_preview: list[dict[str, Any]],
    *,
    warning: str | None = None,
) -> str:
    if not sources_preview:
        base = (
            "Deep Search n'a pas retrouve de passages exploitables pour reformuler la reponse. "
            "Les sources disponibles ne permettent pas encore de conclure avec confiance."
        )
        return f"{base}\n\nNote: {warning}" if warning else base
    lines = [
        "Deep Search a retrouve des passages supplementaires. Voici une reformulation prudente fondee sur les meilleurs extraits:",
        "",
    ]
    for index, source in enumerate(sources_preview[:5], start=1):
        title = source.get("title") or source.get("filename") or source.get("document_id") or f"Source {index}"
        snippet = _compact_text(source.get("snippet") or source.get("content"), max_chars=420)
        if not snippet:
            continue
        lines.append(f"{index}. {title}: {snippet}")
    if warning:
        lines.extend(["", f"Note: synthese LLM indisponible ({warning}); affichage extractif."])
    return "\n".join(lines).strip()


def _previous_answer_from_payload(payload: dict[str, Any], metadata: dict[str, Any] | None = None) -> str:
    candidate = payload.get("previous_answer")
    if isinstance(candidate, str) and candidate.strip():
        return _compact_answer_text(candidate, max_chars=3500)
    partial_result = (metadata or {}).get("partial_result")
    if isinstance(partial_result, dict):
        candidate = partial_result.get("answer_preview")
        if isinstance(candidate, str) and candidate.strip():
            return _compact_answer_text(candidate, max_chars=3500)
    return ""


def _synthesis_prompt(
    query: str,
    sources_preview: list[dict[str, Any]],
    *,
    previous_answer: str | None = None,
) -> str:
    excerpts: list[str] = []
    budget = 0
    for index, source in enumerate(sources_preview[:_MAX_SYNTHESIS_SOURCES], start=1):
        title = str(source.get("title") or source.get("filename") or source.get("document_id") or f"Source {index}")
        page = source.get("page")
        locator = f", page {page}" if page is not None else ""
        snippet = _compact_text(source.get("snippet") or source.get("content"), max_chars=1100)
        block = f"[{index}] {title}{locator}\n{snippet}"
        if budget + len(block) > _MAX_SYNTHESIS_CHARS:
            break
        budget += len(block)
        excerpts.append(block)
    previous_block = ""
    previous = _compact_text(previous_answer, max_chars=3500) if previous_answer else ""
    if previous:
        previous_block = (
            "Reponse rapide precedente a raffiner:\n"
            f"{previous}\n\n"
            "Consigne de forme: si cette reponse etait structuree en paragraphes ou en plusieurs points, "
            "conserve cette structure et approfondis-la avec les preuves Deep Search. "
            "Ne rends pas une simple liste d'extraits.\n\n"
        )
    return (
        "Question utilisateur:\n"
        f"{query}\n\n"
        f"{previous_block}"
        "Extraits Deep Search:\n"
        f"{chr(10).join(excerpts)}\n\n"
        "Redige une reponse finale en francais si la question est en francais, sinon dans la langue de la question. "
        "Appuie-toi uniquement sur les extraits ci-dessus. Si les extraits sont insuffisants, dis-le clairement. "
        "Sois concret et cite les sources utiles avec leur numero entre crochets, par exemple [1] ou [2]. "
        "N'utilise pas de references documentaires brutes comme [menu.html] ou [I.2.html] dans la reponse; "
        "si tu veux nommer un document, ecris son nom en texte normal puis ajoute la citation numerique. "
        "Produis une vraie reponse assistant finale.\n\n"
        "Format obligatoire: Markdown lisible. Utilise des paragraphes courts et des listes a puces ou numerotees "
        "quand la reponse contient plusieurs points. Ne compacte jamais plusieurs items sous la forme "
        "\"- item - item - item\" sur une seule ligne. Termine par une ligne Sources: avec les citations "
        "numeriques principales quand des sources sont identifiables."
    )


async def _llm_deep_answer(payload: dict[str, Any], prompt: str) -> dict[str, Any]:
    from app.llm.llm import LLM

    provider, model = _model_preferences(payload)
    llm = LLM(provider=provider, api_key=settings.openai_api_key if provider == "openai" else None)
    answer = await llm.complete(
        prompt=prompt,
        model=model,
        system_prompt=(
            "You are Agentium's Deep Search synthesizer. Produce grounded, concise answers from retrieved evidence only."
        ),
        temperature=0.1,
        max_tokens=_MAX_SYNTHESIS_TOKENS,
    )
    return {"answer": _compact_answer_text(answer, max_chars=6000), "provider": provider, "model": model}


async def _synthesize_deep_answer(
    payload: dict[str, Any],
    context: dict[str, Any],
    sources_preview: list[dict[str, Any]],
) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    if not query:
        return {
            "answer": _extractive_deep_answer("", sources_preview, warning="query_missing"),
            "answer_status": "extractive_fallback",
            "synthesis_error": "query_missing",
        }
    if not sources_preview:
        return {
            "answer": _extractive_deep_answer(query, sources_preview),
            "answer_status": "no_evidence",
        }
    prompt = _synthesis_prompt(query, sources_preview, previous_answer=_previous_answer_from_payload(payload))
    timeout = max(8.0, min(25.0, float(settings.rag_deep_retrieval_deadline_seconds) * 0.25))
    try:
        llm_result = await asyncio.wait_for(_llm_deep_answer(payload, prompt), timeout=timeout)
        answer = str(llm_result.get("answer") or "").strip()
        if not answer:
            raise RuntimeError("empty_deep_answer")
        return {
            "answer": answer,
            "answer_status": "llm_synthesized",
            "answer_model": llm_result.get("model"),
            "answer_provider": llm_result.get("provider"),
        }
    except Exception as exc:  # noqa: BLE001 - deep answer should degrade to an extractive result.
        logger.warning("deep retrieval synthesis fallback", error=str(exc))
        return {
            "answer": _extractive_deep_answer(query, sources_preview, warning=str(exc)),
            "answer_status": "extractive_fallback",
            "synthesis_error": str(exc),
        }


async def _run_deep_retrieval_async(job_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        job = db.query(WorkerJob).filter(WorkerJob.id == job_id).first()
        if not job:
            raise ValueError(f"Deep retrieval job {job_id!r} not found")
        initial_result = dict(job.result or {})
        payload = dict(initial_result.get("request") or {})
        if not payload:
            raise ValueError(f"Deep retrieval job {job_id!r} has no request payload")
        payload["latency_profile"] = "deep"
        payload["deep_retrieval"] = True
        job_metadata = {key: value for key, value in initial_result.items() if key not in {"retrieval_context", "summary"}}
        previous_answer = _previous_answer_from_payload(payload, job_metadata)
        if previous_answer:
            payload["previous_answer"] = previous_answer
        prepare_result = {
            **job_metadata,
            "request": payload,
            "stage": "deep_prepare",
            "status": "running",
        }
        update_job(db, job_id, status="running", progress=10, result=prepare_result, stage="deep_prepare")
        db.commit()

    try:
        update_payload = {**job_metadata, "request": payload, "stage": "deep_retrieve", "status": "running"}
        with SessionLocal() as db:
            update_job(db, job_id, progress=35, result=update_payload, stage="deep_retrieve")
            db.commit()
        context = await asyncio.wait_for(
            retrieve_rag_context(payload),
            timeout=float(settings.rag_deep_retrieval_deadline_seconds),
        )
        sources_preview = _compact_deep_retrieval_sources(context)
        summary = _summarize_deep_retrieval_context(context)
        summarize_payload = {
            **job_metadata,
            "request": payload,
            "sources_preview": sources_preview,
            "summary": summary,
            "stage": "deep_summarize",
            "status": "running",
        }
        with SessionLocal() as db:
            update_job(db, job_id, progress=72, result=summarize_payload, stage="deep_summarize")
            db.commit()
        synthesis_payload = {
            **summarize_payload,
            "stage": "deep_synthesize",
            "status": "running",
        }
        with SessionLocal() as db:
            update_job(db, job_id, progress=88, result=synthesis_payload, stage="deep_synthesize")
            db.commit()
        answer_payload = await _synthesize_deep_answer(payload, context, sources_preview)
        result = {
            **job_metadata,
            "request": payload,
            "retrieval_context": context,
            "retrieval_context_available": True,
            "sources_preview": sources_preview,
            "summary": summary,
            **answer_payload,
            "stage": "deep_completed",
            "status": "completed",
        }
        with SessionLocal() as db:
            update_job(db, job_id, status="completed", progress=100, result=result, stage="deep_completed")
            db.commit()
        return result
    except asyncio.TimeoutError:
        partial_result = job_metadata.get("partial_result") if isinstance(job_metadata.get("partial_result"), dict) else {}
        retrieval_summary = (
            partial_result.get("retrieval_summary")
            if isinstance(partial_result.get("retrieval_summary"), dict)
            else {}
        )
        sources_preview = (
            partial_result.get("sources_preview")
            if isinstance(partial_result.get("sources_preview"), list)
            else []
        )
        summary = {
            "chunks_retrieved": retrieval_summary.get("chunks_retrieved") or 0,
            "sources_returned": None,
            "top_sources": [],
            "top_score": None,
            "pipeline": retrieval_summary.get("dense_policy") or job_metadata.get("dense_policy"),
            "mode_label": "deep_timeout",
            "collection": payload.get("collection") or payload.get("context_collection"),
            "dense_policy": retrieval_summary.get("dense_policy") or job_metadata.get("dense_policy"),
            "scope_confidence": retrieval_summary.get("scope_confidence") or job_metadata.get("scope_confidence"),
            "fallback_reason": "deep_retrieval_deadline_exceeded",
            "duration_ms": int(float(settings.rag_deep_retrieval_deadline_seconds) * 1000),
            "partial": True,
        }
        partial_answer = (
            partial_result.get("answer_preview")
            if isinstance(partial_result.get("answer_preview"), str)
            else None
        )
        result = {
            **job_metadata,
            "request": payload,
            "stage": "deep_timeout",
            "status": "completed_partial",
            "retrieval_context_available": False,
            "sources_preview": sources_preview,
            "summary": summary,
            "answer": partial_answer
            or _extractive_deep_answer(
                str(payload.get("query") or ""),
                sources_preview,
                warning="deep_retrieval_deadline_exceeded",
            ),
            "answer_status": "partial_fast_answer" if partial_answer else "extractive_fallback",
            "fallback_reason": "deep_retrieval_deadline_exceeded",
            "warning": "Deep retrieval reached its latency budget; showing the partial fast result.",
        }
        with SessionLocal() as db:
            update_job(
                db,
                job_id,
                status="completed",
                progress=100,
                result=result,
                stage="deep_timeout",
            )
            db.commit()
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("deep retrieval worker failed", job_id=job_id, error=str(exc))
        result = {
            **job_metadata,
            "request": payload,
            "stage": "deep_failed",
            "status": "failed",
            "error": str(exc),
        }
        with SessionLocal() as db:
            update_job(db, job_id, status="failed", progress=100, error=str(exc), result=result, stage="deep_failed")
            db.commit()
        return result


def run_deep_retrieval(job_id: str) -> dict[str, Any]:
    return asyncio.run(_run_deep_retrieval_async(job_id))


def _message_meta_with_deep_result(job: WorkspaceJob, result: dict[str, Any]) -> dict[str, Any]:
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    meta = {
        "workspace_job_id": job.id,
        "deep_job_id": job.id,
        "deep_poll_url": f"/workspace-jobs/{job.id}",
        "parent_message_id": job.parent_message_id,
        "deep_status": job.status,
        "deep_progress": job.progress,
        "deep_stage": result.get("stage") or job.stage,
        "deep_answer_status": result.get("answer_status"),
        "deep_answer_model": result.get("answer_model"),
        "deep_answer_provider": result.get("answer_provider"),
        "sources": result.get("sources_preview") or [],
        "deep_sources": result.get("sources_preview") or [],
        "deep_summary": {
            "chunks_retrieved": summary.get("chunks_retrieved"),
            "sources_returned": summary.get("sources_returned"),
            "top_sources": summary.get("top_sources") or [],
            "top_score": summary.get("top_score"),
            "pipeline": summary.get("pipeline"),
            "partial": bool(summary.get("partial")),
            "fallback_reason": summary.get("fallback_reason"),
        },
    }
    return {key: value for key, value in meta.items() if value is not None}


def _update_workspace_deep_message(job_id: str, result: dict[str, Any]) -> None:
    with SessionLocal() as db:
        job = db.query(WorkspaceJob).filter(WorkspaceJob.id == job_id).first()
        if not job or not job.message_id:
            return
        message = db.query(Message).filter(Message.id == job.message_id).first()
        if not message:
            return
        answer = str(result.get("answer") or "").strip()
        if answer:
            message.content = answer
        message.meta_data = {
            **(message.meta_data or {}),
            **_message_meta_with_deep_result(job, result),
        }
        db.commit()


async def _run_workspace_deep_retrieval_async(job_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        job = db.query(WorkspaceJob).filter(WorkspaceJob.id == job_id).first()
        if not job:
            raise ValueError(f"Workspace Deep retrieval job {job_id!r} not found")
        workspace = db.query(Workspace).filter(Workspace.id == job.workspace_id).first()
        if not workspace:
            raise ValueError(f"Workspace for Deep retrieval job {job_id!r} not found")
        initial_input = dict(job.input_ref or {})
        payload = dict(initial_input.get("request") or {})
        if not payload:
            raise ValueError(f"Workspace Deep retrieval job {job_id!r} has no request payload")
        payload["latency_profile"] = "deep"
        payload["deep_retrieval"] = True
        job_metadata = {key: value for key, value in initial_input.items() if key not in {"request"}}
        previous_answer = _previous_answer_from_payload(payload, job_metadata)
        if previous_answer:
            payload["previous_answer"] = previous_answer
        transition_job(
            db,
            workspace,
            job,
            "running",
            progress=10,
            stage="deep_prepare",
            result={"stage": "deep_prepare", "status": "running", "request": payload},
            user=None,
        )
        db.commit()

    try:
        with SessionLocal() as db:
            job = db.query(WorkspaceJob).filter(WorkspaceJob.id == job_id).first()
            workspace = db.query(Workspace).filter(Workspace.id == job.workspace_id).first() if job else None
            if job and workspace:
                transition_job(
                    db,
                    workspace,
                    job,
                    "running",
                    progress=35,
                    stage="deep_retrieve",
                    result={"stage": "deep_retrieve", "status": "running", "request": payload},
                    user=None,
                )
                db.commit()
        context = await asyncio.wait_for(
            retrieve_rag_context(payload),
            timeout=float(settings.rag_deep_retrieval_deadline_seconds),
        )
        sources_preview = _compact_deep_retrieval_sources(context)
        summary = _summarize_deep_retrieval_context(context)
        with SessionLocal() as db:
            job = db.query(WorkspaceJob).filter(WorkspaceJob.id == job_id).first()
            workspace = db.query(Workspace).filter(Workspace.id == job.workspace_id).first() if job else None
            if job and workspace:
                transition_job(
                    db,
                    workspace,
                    job,
                    "running",
                    progress=72,
                    stage="deep_summarize",
                    result={
                        **job_metadata,
                        "request": payload,
                        "sources_preview": sources_preview,
                        "summary": summary,
                        "stage": "deep_summarize",
                        "status": "running",
                    },
                    user=None,
                )
                db.commit()
        with SessionLocal() as db:
            job = db.query(WorkspaceJob).filter(WorkspaceJob.id == job_id).first()
            workspace = db.query(Workspace).filter(Workspace.id == job.workspace_id).first() if job else None
            if job and workspace:
                transition_job(
                    db,
                    workspace,
                    job,
                    "running",
                    progress=88,
                    stage="deep_synthesize",
                    result={
                        **job_metadata,
                        "request": payload,
                        "sources_preview": sources_preview,
                        "summary": summary,
                        "stage": "deep_synthesize",
                        "status": "running",
                    },
                    user=None,
                )
                db.commit()
        answer_payload = await _synthesize_deep_answer(payload, context, sources_preview)
        result = {
            **job_metadata,
            "request": payload,
            "retrieval_context": context,
            "retrieval_context_available": True,
            "sources_preview": sources_preview,
            "summary": summary,
            **answer_payload,
            "stage": "deep_completed",
            "status": "completed",
        }
        with SessionLocal() as db:
            job = db.query(WorkspaceJob).filter(WorkspaceJob.id == job_id).first()
            workspace = db.query(Workspace).filter(Workspace.id == job.workspace_id).first() if job else None
            if job and workspace:
                transition_job(
                    db,
                    workspace,
                    job,
                    "completed",
                    progress=100,
                    stage="deep_completed",
                    result=result,
                    user=None,
                )
                db.commit()
        _update_workspace_deep_message(job_id, result)
        return result
    except asyncio.TimeoutError:
        partial_result = job_metadata.get("partial_result") if isinstance(job_metadata.get("partial_result"), dict) else {}
        retrieval_summary = (
            partial_result.get("retrieval_summary")
            if isinstance(partial_result.get("retrieval_summary"), dict)
            else {}
        )
        sources_preview = (
            partial_result.get("sources_preview")
            if isinstance(partial_result.get("sources_preview"), list)
            else []
        )
        summary = {
            "chunks_retrieved": retrieval_summary.get("chunks_retrieved") or 0,
            "sources_returned": None,
            "top_sources": [],
            "top_score": None,
            "pipeline": retrieval_summary.get("dense_policy") or job_metadata.get("dense_policy"),
            "mode_label": "deep_timeout",
            "collection": payload.get("collection") or payload.get("context_collection"),
            "dense_policy": retrieval_summary.get("dense_policy") or job_metadata.get("dense_policy"),
            "scope_confidence": retrieval_summary.get("scope_confidence") or job_metadata.get("scope_confidence"),
            "fallback_reason": "deep_retrieval_deadline_exceeded",
            "duration_ms": int(float(settings.rag_deep_retrieval_deadline_seconds) * 1000),
            "partial": True,
        }
        partial_answer = (
            partial_result.get("answer_preview")
            if isinstance(partial_result.get("answer_preview"), str)
            else None
        )
        result = {
            **job_metadata,
            "request": payload,
            "stage": "deep_timeout",
            "status": "completed_partial",
            "retrieval_context_available": False,
            "sources_preview": sources_preview,
            "summary": summary,
            "answer": partial_answer
            or _extractive_deep_answer(
                str(payload.get("query") or ""),
                sources_preview,
                warning="deep_retrieval_deadline_exceeded",
            ),
            "answer_status": "partial_fast_answer" if partial_answer else "extractive_fallback",
            "fallback_reason": "deep_retrieval_deadline_exceeded",
            "warning": "Deep retrieval reached its latency budget; showing the partial fast result.",
        }
        with SessionLocal() as db:
            job = db.query(WorkspaceJob).filter(WorkspaceJob.id == job_id).first()
            workspace = db.query(Workspace).filter(Workspace.id == job.workspace_id).first() if job else None
            if job and workspace:
                transition_job(
                    db,
                    workspace,
                    job,
                    "completed",
                    progress=100,
                    stage="deep_timeout",
                    result=result,
                    user=None,
                )
                db.commit()
        _update_workspace_deep_message(job_id, result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("workspace deep retrieval worker failed", job_id=job_id, error=str(exc))
        result = {
            **job_metadata,
            "request": payload,
            "stage": "deep_failed",
            "status": "failed",
            "error": str(exc),
            "answer": _extractive_deep_answer(str(payload.get("query") or ""), [], warning=str(exc)),
            "answer_status": "extractive_fallback",
        }
        with SessionLocal() as db:
            job = db.query(WorkspaceJob).filter(WorkspaceJob.id == job_id).first()
            workspace = db.query(Workspace).filter(Workspace.id == job.workspace_id).first() if job else None
            if job and workspace:
                transition_job(
                    db,
                    workspace,
                    job,
                    "failed",
                    progress=100,
                    stage="deep_failed",
                    result=result,
                    error=str(exc),
                    user=None,
                )
                db.commit()
        _update_workspace_deep_message(job_id, result)
        return result


def run_workspace_deep_retrieval(job_id: str) -> dict[str, Any]:
    return asyncio.run(_run_workspace_deep_retrieval_async(job_id))
