"""Public retrieval bench on a frozen HotpotQA distractor subset.

The paragraphs are ingested once into a dedicated workspace
(``python -m app.cli.seed_public_bench``); the nightly Celery beat task then
retrieves every question through ``retrieve_rag_context`` and stores recall@k
over supporting paragraphs and the share of supporting sentences found.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.retrieval_bench_run import RetrievalBenchRun
from app.models.workspace import Workspace

logger = get_logger(__name__)

PUBLIC_BENCH_NAME = "hotpotqa_distractor_200"
PUBLIC_BENCH_WORKSPACE_SLUG = "public-bench"
PUBLIC_BENCH_COLLECTION_SLUG = "hotpotqa-distractor"
PUBLIC_BENCH_PATH = (
    Path(__file__).resolve().parents[2]
    / "resources"
    / "retrieval_golden"
    / "public_hotpotqa"
    / "hotpotqa_distractor_200.json"
)
DEFAULT_K = 10


@dataclass(frozen=True)
class PublicBenchCase:
    id: str
    question: str
    answer: str
    type: str
    level: str
    supporting_files: tuple[str, ...]
    supporting_sentences: tuple[str, ...]


@lru_cache(maxsize=1)
def _load_raw() -> dict[str, Any]:
    return json.loads(PUBLIC_BENCH_PATH.read_text(encoding="utf-8"))


def paragraph_documents() -> dict[str, str]:
    return {
        p["file"]: f"# {p['title']}\n\n" + " ".join(p["sentences"]).strip() + "\n"
        for p in _load_raw()["paragraphs"]
    }


def load_public_bench_cases() -> list[PublicBenchCase]:
    raw = _load_raw()
    paragraphs = {p["title"]: p for p in raw["paragraphs"]}
    cases = []
    for item in raw["cases"]:
        files: list[str] = []
        sentences: list[str] = []
        for title, sent_id in item["supporting_facts"]:
            paragraph = paragraphs[title]
            if paragraph["file"] not in files:
                files.append(paragraph["file"])
            if 0 <= sent_id < len(paragraph["sentences"]):
                sentences.append(paragraph["sentences"][sent_id])
        cases.append(
            PublicBenchCase(
                id=item["id"],
                question=item["question"],
                answer=item["answer"],
                type=item["type"],
                level=item["level"],
                supporting_files=tuple(files),
                supporting_sentences=tuple(sentences),
            )
        )
    return cases


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _metadata_file(meta: Mapping[str, Any]) -> str:
    for key in ("document_filename", "filename", "source", "document_name"):
        value = meta.get(key)
        if value:
            return Path(str(value)).name.lower()
    return ""


def score_case(case: PublicBenchCase, context: Mapping[str, Any], k: int = DEFAULT_K) -> dict[str, Any]:
    chunks = list(context.get("chunks") or [])[:k]
    metadatas = list(context.get("metadatas") or [])[:k]
    retrieved_files = {_metadata_file(meta or {}) for meta in metadatas} - {""}
    found_files = [f for f in case.supporting_files if f.lower() in retrieved_files]
    haystack = _normalise(" ".join(str(c) for c in chunks))
    found_sentences = [s for s in case.supporting_sentences if _normalise(s) and _normalise(s) in haystack]
    return {
        "id": case.id,
        "type": case.type,
        "recall": len(found_files) / len(case.supporting_files) if case.supporting_files else 0.0,
        "supporting_fact_rate": (
            len(found_sentences) / len(case.supporting_sentences) if case.supporting_sentences else 0.0
        ),
        "retrieved": len(chunks),
    }


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def summarise(scores: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ok = [s for s in scores if "error" not in s]
    by_type: dict[str, dict[str, Any]] = {}
    for kind in sorted({s["type"] for s in ok}):
        subset = [s for s in ok if s["type"] == kind]
        by_type[kind] = {
            "cases": len(subset),
            "recall_at_k": _mean([s["recall"] for s in subset]),
            "supporting_fact_rate": _mean([s["supporting_fact_rate"] for s in subset]),
        }
    return {
        "recall_at_k": _mean([s["recall"] for s in ok]),
        "supporting_fact_rate": _mean([s["supporting_fact_rate"] for s in ok]),
        "mean_latency_ms": _mean([s["latency_ms"] for s in ok if "latency_ms" in s]),
        "error_count": len(scores) - len(ok),
        "by_type": by_type,
    }


def public_bench_workspace(db: DBSession, *, create: bool = False) -> Workspace | None:
    workspace = db.query(Workspace).filter(Workspace.slug == PUBLIC_BENCH_WORKSPACE_SLUG).first()
    if workspace is None and create:
        workspace = Workspace(name="Public retrieval bench", slug=PUBLIC_BENCH_WORKSPACE_SLUG)
        db.add(workspace)
        db.flush()
    return workspace


async def seed_public_bench(db: DBSession) -> dict[str, Any]:
    from app.services.mission_room_knowledge_sync import sync_markdown_documents_to_collection

    workspace = public_bench_workspace(db, create=True)
    return await sync_markdown_documents_to_collection(
        db,
        workspace,
        collection_slug=PUBLIC_BENCH_COLLECTION_SLUG,
        documents=paragraph_documents(),
        origin="public_bench.hotpotqa",
    )


async def run_public_bench(
    db: DBSession,
    *,
    k: int = DEFAULT_K,
    limit: int | None = None,
    latency_profile: str = "balanced",
) -> RetrievalBenchRun:
    from app.services.rag.context import retrieve_rag_context

    run = RetrievalBenchRun(
        bench=PUBLIC_BENCH_NAME,
        status="running",
        git_sha=(settings.agentium_image_revision or None),
        k=k,
        case_count=0,
        error_count=0,
        metrics={},
    )
    db.add(run)
    workspace = public_bench_workspace(db)
    if workspace is None:
        run.status = "skipped"
        run.error = "workspace_not_seeded"
        run.completed_at = datetime.utcnow()
        db.commit()
        return run
    db.commit()

    cases = load_public_bench_cases()[: limit or None]
    scores: list[dict[str, Any]] = []
    try:
        for case in cases:
            request = {
                "query": case.question,
                "context_collection": PUBLIC_BENCH_COLLECTION_SLUG,
                "latency_profile": latency_profile,
                "workspace_id": workspace.id,
                "workspace_slug": workspace.slug,
                "retrieval_profile": "chat",
            }
            started = time.perf_counter()
            try:
                context = await retrieve_rag_context(request)
            except Exception as exc:  # noqa: BLE001 - one failing case must not stop the bench
                scores.append({"id": case.id, "type": case.type, "error": str(exc)[:300]})
                continue
            score = score_case(case, context, k)
            score["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
            scores.append(score)
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        run.error = str(exc)[:2000]
    else:
        run.status = "completed"
    summary = summarise(scores)
    run.case_count = len(scores)
    run.error_count = summary["error_count"]
    run.recall_at_k = summary["recall_at_k"]
    run.supporting_fact_rate = summary["supporting_fact_rate"]
    run.mean_latency_ms = summary["mean_latency_ms"]
    run.metrics = {
        "latency_profile": latency_profile,
        "by_type": summary["by_type"],
        "errors": [s for s in scores if "error" in s][:20],
    }
    run.completed_at = datetime.utcnow()
    db.commit()
    logger.info(
        "public_bench_completed",
        run_id=run.id,
        recall_at_k=run.recall_at_k,
        supporting_fact_rate=run.supporting_fact_rate,
    )
    return run


def serialize_bench_run(run: RetrievalBenchRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "bench": run.bench,
        "status": run.status,
        "git_sha": run.git_sha,
        "k": run.k,
        "case_count": run.case_count,
        "error_count": run.error_count,
        "recall_at_k": run.recall_at_k,
        "supporting_fact_rate": run.supporting_fact_rate,
        "mean_latency_ms": run.mean_latency_ms,
        "metrics": run.metrics or {},
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }
