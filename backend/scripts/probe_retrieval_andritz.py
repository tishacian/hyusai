"""Retrieval + answer-profile probe for the Andritz transverse chat.

Debug session e963ab. Read-only diagnostic. Run inside the backend container:

    RETRIEVAL_PROBE_LOG=/tmp/retrieval-probe-e963ab.ndjson \
      python -m scripts.probe_retrieval_andritz --workspace andritz --level 3

Levels:
  1 = answer-profile classification only (pure, no DB/corpus)
  2 = + planner-only decision (filters / scope_reason / budgets), no Qdrant/LLM
  3 = + full retrieval selected sources (hits Qdrant, no LLM)

The probe reuses the real chat flow defaults (_apply_workspace_chat_flow_defaults)
so the resolved scope/policy/budgets match a live /chat turn.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.api.v1.endpoints.chat import (
    ChatRequest,
    _apply_workspace_chat_flow_defaults,
    _resolve_system_id,
)
from app.services.industrial_answer_profile import (
    industrial_answer_policy,
    resolve_answer_profile,
)
from app.services.rag.context import get_retrieval_profile, retrieve_rag_context
from app.services.rag.corpus_planner import plan_corpus

QUERIES = [
    "Quelle pompe est utilisée dans le projet AKK200 ?",
    "Détaille le contenu du manuel AKK200.",
    "Résume le projet AKK200.",
    "Quels projets utilisent une pompe Uraca ?",
    "Donne la liste des pièces de rechange du projet AKK200.",
]

TECH_MARKERS = (
    "section_iv",
    "hydroentanglement",
    "high pressure",
    "high-pressure",
    "php",
    "jetlace",
    "drive",
)
NAV_MARKERS = (
    "menu",
    "index",
    "accueil",
    "pictures",
    "sommaire",
    "frame",
    "section_i_",
    "section_ii",
)


def _classify(names: list[str]) -> dict[str, Any]:
    low = [str(n or "").lower() for n in names]
    tech = [n for n in low if any(m in n for m in TECH_MARKERS)]
    nav = [n for n in low if any(m in n for m in NAV_MARKERS)]
    return {
        "tech_hits": len(tech),
        "nav_hits": len(nav),
        "tech_examples": tech[:5],
        "nav_examples": nav[:5],
    }


def _source_names(sources: Any) -> list[str]:
    out: list[str] = []
    if isinstance(sources, list):
        for s in sources:
            if isinstance(s, dict):
                out.append(
                    str(
                        s.get("document_filename")
                        or s.get("label")
                        or s.get("title")
                        or s.get("source")
                        or s.get("document_id")
                        or ""
                    )
                )
    return out


async def _probe_query(db, workspace: Workspace, query: str, level: int) -> dict[str, Any]:
    out: dict[str, Any] = {"query": query}

    decision = resolve_answer_profile(query, industrial_answer_policy())
    out["answer_profile"] = decision.as_dict()
    if level < 2:
        return out

    req = ChatRequest(query=query)
    system_id = _apply_workspace_chat_flow_defaults(db, workspace=workspace, request=req)
    if system_id is None:
        system_id = _resolve_system_id(db, workspace.id, None)
    out["system_id"] = system_id
    out["folded"] = {
        "knowledge_scope": req.knowledge_scope,
        "retrieval_profile": req.retrieval_profile,
        "latency_profile": req.latency_profile,
        "deep_retrieval": req.deep_retrieval,
        "answer_profile_decision": req.answer_profile_decision,
        "source_policy": req.source_policy,
    }

    request_dict = req.model_dump()
    request_dict["workspace_id"] = workspace.id
    request_dict["workspace_slug"] = workspace.slug
    if system_id:
        request_dict["system_id"] = system_id

    profile = get_retrieval_profile(request_dict)
    planner_request = dict(request_dict)
    planner_request["retrieval_filters"] = dict(profile.get("retrieval_filters") or {})
    plan = plan_corpus(
        db=db,
        profile=profile,
        query=str(profile.get("query") or query),
        request=planner_request,
    )
    doc_filter: list[str] = []
    if isinstance(plan.filters, dict):
        raw = plan.filters.get("document_filename")
        if isinstance(raw, list):
            doc_filter = [str(x) for x in raw]
    out["plan"] = {
        "collection": profile.get("collection"),
        "collections": profile.get("collections"),
        "knowledge_scope": profile.get("knowledge_scope"),
        "intent": plan.intent,
        "latency_profile": plan.latency_profile,
        "top_k": plan.top_k,
        "candidate_pool_k": plan.candidate_pool_k,
        "synthesis_k": plan.synthesis_k,
        "source_display_k": plan.source_display_k,
        "scope_confidence": plan.scope_confidence,
        "scope_reason": plan.scope_reason,
        "filters": plan.filters,
        "document_filename_count": len(doc_filter),
        "document_filename_classify": _classify(doc_filter),
    }
    if level < 3:
        return out

    ctx_request = dict(request_dict)
    try:
        context = await retrieve_rag_context(ctx_request)
        chunks = context.get("chunks") or []
        metas = context.get("metadatas") or []
        scores = context.get("scores") or []
        sample = []
        for i, ch in enumerate(chunks[:12]):
            meta = metas[i] if i < len(metas) and isinstance(metas[i], dict) else {}
            txt = ch if isinstance(ch, str) else (ch.get("text") if isinstance(ch, dict) else str(ch))
            fn = meta.get("document_filename") or meta.get("source") or meta.get("filename") or meta.get("title") or ""
            blob = (str(txt) + " " + str(fn)).lower()
            sample.append({
                "fn": str(fn)[-60:],
                "proj": meta.get("project_code"),
                "score": round(float(scores[i]), 3) if i < len(scores) and scores[i] is not None else None,
                "len": len(str(txt)),
                "akk": "akk200" in blob,
                "pump": ("pump" in blob or "pompe" in blob),
                "head": str(txt)[:160].replace("\n", " "),
            })
        metrics = context.get("metrics") if isinstance(context.get("metrics"), dict) else {}
        out["retrieval"] = {
            "pipeline": context.get("pipeline"),
            "chunk_count": len(chunks),
            "meta_keys": sorted(str(k) for k in metas[0].keys()) if metas and isinstance(metas[0], dict) else None,
            "first_meta": {str(k): str(v)[:70] for k, v in metas[0].items() if k not in ("content",)} if metas and isinstance(metas[0], dict) else None,
            "chunk_sample": sample,
            "scope_reason": metrics.get("scope_reason"),
            "candidate_counts": metrics.get("candidate_counts"),
        }
    except Exception as exc:  # noqa: BLE001 - report and keep going
        import traceback
        out["retrieval"] = {"error": f"{type(exc).__name__}: {exc}", "tb": traceback.format_exc()[-800:]}
    return out


async def _run(args: argparse.Namespace) -> None:
    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.slug == args.workspace).first()
        if not workspace:
            raise SystemExit(f"Workspace not found: {args.workspace}")
        queries = [args.query] if args.query else QUERIES
        results: list[dict[str, Any]] = []
        for q in queries:
            res = await _probe_query(db, workspace, q, args.level)
            results.append(res)
            print(json.dumps(res, ensure_ascii=False, indent=2), flush=True)

        print("\n=== SUMMARY ===", flush=True)
        for r in results:
            plan = r.get("plan") or {}
            cls = plan.get("document_filename_classify") or {}
            rcls = (r.get("retrieval") or {}).get("selected_classify") or {}
            print(
                f"- {r['query'][:46]!r:48} "
                f"profile={r['answer_profile']['profile']:20} "
                f"filterN={plan.get('document_filename_count')} "
                f"plan(nav={cls.get('nav_hits')},tech={cls.get('tech_hits')}) "
                f"sel(nav={rcls.get('nav_hits')},tech={rcls.get('tech_hits')})",
                flush=True,
            )
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default="andritz")
    parser.add_argument("--level", type=int, default=3, choices=[1, 2, 3])
    parser.add_argument("--query", default="", help="Single ad-hoc query instead of the regression set")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
