"""Comparative query decomposition for multi-document recall.

A comparative query ("A vs B", "difference between A and B") is dominated by
whichever entity is more frequent in the corpus, so the second entity tends to
under-recall and its document never reaches the top-k. This module splits such
a query into two entity-focused sub-queries, runs them through the *existing*
bounded retrieval pipeline, and merges the hits back so each entity is
represented.

Design constraints:
- No new LLM call — entity extraction is purely lexical (FR/EN/DE patterns),
  and "is this comparative?" reuses the Bayesian prompt classifier.
- Bit-identical behaviour when disabled or when extraction fails: the caller
  only decomposes when ``build_comparative_plan`` returns a plan.
- Latency-scoped: deep by default, balanced behind a separate flag.

The orchestration (``augment_with_comparative_subqueries``) takes a
``retrieve`` callable so it stays decoupled from ``context.py`` internals and
unit-testable with a stub.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.services.rag.project_references import project_reference_terms

# Comparative split patterns. Each captures the two compared entities (group 1
# and group 2). Matched on the accent-folded, lower-cased query. Order matters:
# the more specific "difference between … and …" forms come before the bare
# "X vs Y" catch-all.
_SPLIT_PATTERNS: tuple[re.Pattern[str], ...] = (
    # EN: difference(s) between X and Y [on/for/in/?]
    re.compile(r"difference[s]? between\s+(.+?)\s+and\s+(.+?)(?:\s+(?:on|for|in|when|under)\b|\?|$)"),
    # EN: compare X (and|to|with|versus|vs) Y
    re.compile(r"\bcompare\s+(.+?)\s+(?:and|to|with|versus|vs\.?)\s+(.+?)(?:\s+(?:on|for|in)\b|\?|$)"),
    # FR: différence(s) … entre [le|la|les|l'] X et [le|la|les|l'] Y
    re.compile(r"difference[s]?\b.*?\bentre\s+(.+?)\s+et\s+(.+?)(?:\s+(?:sur|pour|dans)\b|\?|$)"),
    # FR: comparaison(s) entre X et Y
    re.compile(r"comparaison[s]?\b.*?\bentre\s+(.+?)\s+et\s+(.+?)(?:\s+(?:sur|pour|dans)\b|\?|$)"),
    # FR: compare(r/z) X (et|avec|versus|vs) Y
    re.compile(r"\bcompare[rz]?\s+(.+?)\s+(?:et|avec|versus|vs\.?)\s+(.+?)(?:\s+(?:sur|pour|dans)\b|\?|$)"),
    # DE: Unterschied(e) zwischen X und Y
    re.compile(r"unterschied(?:e)?\s+zwischen\s+(.+?)\s+und\s+(.+?)(?:\?|$)"),
    # DE: vergleich(e/en) X (und|mit) Y
    re.compile(r"vergleich(?:e|en)?\s+(.+?)\s+(?:und|mit)\s+(.+?)(?:\?|$)"),
    # Generic catch-all: X (vs|versus) Y — last so the specific forms win.
    re.compile(r"^(.+?)\s+(?:versus|vs\.?)\s+(.+?)(?:\?|$)"),
)

# Leading determiners/qualifiers stripped from an extracted entity so the
# entity term stays a clean identifier ("the Wilo NOLH" -> "Wilo NOLH").
_LEADING_NOISE = re.compile(
    r"^(?:the|les|le|la|l'|du|des|de la|de|d'|den|der|die|das|two)\s+",
)
_ENTITY_TAIL_NOISE = re.compile(r"\s*[?.!,;:]+\s*$")


def _fold(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", str(text or "")) if not unicodedata.combining(ch)
    ).lower()


@dataclass(frozen=True)
class ComparativePlan:
    entities: tuple[str, str]
    subqueries: tuple[str, str]
    references: tuple[str, ...] = field(default=())


def _clean_entity(raw: str) -> str:
    text = _ENTITY_TAIL_NOISE.sub("", str(raw or "").strip())
    # Strip leading determiners, possibly twice ("the the Wilo").
    for _ in range(2):
        stripped = _LEADING_NOISE.sub("", text, count=1)
        if stripped == text:
            break
        text = stripped
    return " ".join(text.split())


def parse_comparative_entities(query: str) -> tuple[str, str] | None:
    """Extract the two compared entities, or None when the query is not an
    explicit comparison or the entities are too thin to retrieve on."""
    folded = _fold(query)
    for pattern in _SPLIT_PATTERNS:
        match = pattern.search(folded)
        if not match:
            continue
        left = _clean_entity(match.group(1))
        right = _clean_entity(match.group(2))
        # Map the folded spans back to the original-cased query so the
        # sub-query preserves the user's exact identifiers (CONTINENTAL GVJS).
        left = _recover_original_case(query, folded, match.start(1), match.end(1)) or left
        right = _recover_original_case(query, folded, match.start(2), match.end(2)) or right
        left, right = _clean_entity(left), _clean_entity(right)
        if len(left) >= 2 and len(right) >= 2 and left.lower() != right.lower():
            return left, right
    return None


def _recover_original_case(original: str, folded: str, start: int, end: int) -> str:
    # _fold preserves character positions (NFKD on these scripts keeps length
    # for the Latin ranges in play here), so the folded offsets map back 1:1.
    if len(folded) == len(original) and 0 <= start < end <= len(original):
        return original[start:end].strip()
    return ""


def is_comparative_query(query: str) -> bool:
    """Whether the shared prompt classifier reads the query as comparative."""
    try:
        from app.services.system_prompts.classifier import classify_prompt_type_fast
        from app.services.system_prompts.types import SystemPromptType

        decision = classify_prompt_type_fast(query)
        if decision.prompt_type == SystemPromptType.COMPARATIVE:
            return True
        # Fall back to the argmax posterior: a decisive comparative signal that
        # lost the confidence margin still counts.
        posteriors = decision.posteriors or {}
        if posteriors:
            top = max(posteriors, key=posteriors.get)
            return top == SystemPromptType.COMPARATIVE.value
    except Exception:  # noqa: BLE001 - detection must never break retrieval.
        return False
    return False


def _build_subquery(entity: str, references: Sequence[str]) -> str:
    # When the compared entities are themselves project codes, carrying every
    # reference into both subqueries makes the corpus planner select the first
    # project twice.  Keep only the reference structurally present in this
    # entity.  If the entities are equipment names under one shared project,
    # retain the original project anchor(s) as before.
    entity_references = project_reference_terms(entity, known_codes=references)
    selected = entity_references or tuple(dict.fromkeys(references))
    refs = " ".join(
        reference
        for reference in selected
        if reference not in entity_references
    )
    return " ".join(part for part in (entity, refs) if part).strip()


def build_comparative_plan(query: str, *, latency_profile: str | None) -> ComparativePlan | None:
    """Return a decomposition plan, or None to keep current behaviour.

    Gates, in order: latency profile + flags, then the classifier confirms a
    comparative intent, then two entities parse out.
    """
    profile = str(latency_profile or "").strip().lower()
    if not settings.rag_comparative_decompose_enabled:
        return None
    if profile == "deep":
        active = True
    elif profile == "balanced":
        active = bool(settings.rag_comparative_decompose_balanced)
    else:  # fast / unknown: never decompose
        return None
    if not active:
        return None
    if not is_comparative_query(query):
        return None
    entities = parse_comparative_entities(query)
    if not entities:
        return None
    references = project_reference_terms(query)
    left, right = entities
    subqueries = (
        _build_subquery(left, references),
        _build_subquery(right, references),
    )
    return ComparativePlan(entities=entities, subqueries=subqueries, references=references)


def _content_key(text: str) -> str:
    return " ".join(_fold(text).split())[:160]


def _entity_present(entity: str, chunks: Sequence[str], metadatas: Sequence[Mapping[str, Any]]) -> bool:
    """Whether an entity's salient tokens appear in any chunk text or filename.

    Uses the entity's distinctive tokens (length ≥ 3, ignoring generic words)
    so "Wilo NOLH" matches a chunk mentioning NOLH even without "Wilo".
    """
    tokens = [tok for tok in _fold(entity).split() if len(tok) >= 3]
    if not tokens:
        return False
    distinctive = [tok for tok in tokens if tok not in _GENERIC_ENTITY_TOKENS] or tokens
    haystacks: list[str] = [_fold(c) for c in chunks]
    for meta in metadatas:
        if isinstance(meta, Mapping):
            haystacks.append(_fold(meta.get("document_filename") or meta.get("filename") or ""))
    return any(any(tok in hay for tok in distinctive) for hay in haystacks)


_GENERIC_ENTITY_TOKENS = {
    "pump", "pumps", "pompe", "pompes", "manual", "manuals", "notice", "manuel",
    "set", "blower", "blowers", "drive", "drives", "variateur", "variateurs",
    "vacuum", "available", "card", "operator", "unit", "units",
}


@dataclass(frozen=True)
class _SubResult:
    entity: str
    chunks: list[str]
    scores: list[float]
    metadatas: list[dict[str, Any]]


def merge_comparative_results(
    primary: tuple[list[str], list[float], list[dict[str, Any]]],
    sub_results: Sequence[_SubResult],
    *,
    limit: int,
) -> tuple[list[str], list[float], list[dict[str, Any]], dict[str, Any]]:
    """Union the original hits with the per-entity sub-query hits.

    RRF-style: rank position in each list contributes; identical chunk content
    is collapsed to one entry keeping its best raw score. The merged pool is
    handed to the existing rerank/threshold/diversify pipeline, so this only
    needs to surface the second entity into the candidate pool — the per-entity
    top-k guarantee is enforced later by ``ensure_entity_coverage``.
    """
    RRF_K = 60
    agg: dict[str, float] = {}
    best: dict[str, tuple[str, float, dict[str, Any]]] = {}
    order: list[str] = []

    def _ingest(chunks: Sequence[str], scores: Sequence[float], metas: Sequence[dict[str, Any]]) -> None:
        for rank, chunk in enumerate(chunks):
            text = str(chunk or "")
            if len(text) < 10:
                continue
            key = _content_key(text)
            agg[key] = agg.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
            score = float(scores[rank]) if rank < len(scores) else 0.0
            meta = metas[rank] if rank < len(metas) else {}
            if key not in best:
                best[key] = (text, score, dict(meta or {}))
                order.append(key)
            elif score > best[key][1]:
                best[key] = (text, score, best[key][2] or dict(meta or {}))

    p_chunks, p_scores, p_metas = primary
    _ingest(p_chunks, p_scores, p_metas)
    for sub in sub_results:
        _ingest(sub.chunks, sub.scores, sub.metadatas)

    ranked = sorted(order, key=lambda k: agg[k], reverse=True)
    if limit and limit > 0:
        ranked = ranked[: max(limit, len(p_chunks))]
    chunks = [best[k][0] for k in ranked]
    scores = [best[k][1] for k in ranked]
    metas = [best[k][2] for k in ranked]
    diag = {
        "comparative_subquery_hits": {sub.entity: len(sub.chunks) for sub in sub_results},
        "comparative_merged_pool": len(chunks),
    }
    return chunks, scores, metas, diag


def ensure_entity_coverage(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    *,
    plan: ComparativePlan,
    sub_results: Sequence[_SubResult],
    limit: int,
    is_exempt: Callable[[Mapping[str, Any]], bool] | None = None,
) -> tuple[list[str], list[float], list[dict[str, Any]], dict[str, Any]]:
    """Guarantee ≥1 chunk per entity in the final top-k when the entity has hits.

    For each entity absent from the current top-``limit`` but present in its
    sub-query results, promote its best sub-query chunk — replacing the
    lowest-ranked non-exempt slot when the budget is full, else appending.
    """
    exempt = is_exempt or (lambda _meta: False)
    by_entity = {sub.entity: sub for sub in sub_results}
    covered: list[str] = []
    promoted: list[str] = []
    budget = max(limit, 1)

    for entity in plan.entities:
        top_chunks = chunks[:budget]
        top_metas = metadatas[:budget]
        if _entity_present(entity, top_chunks, top_metas):
            covered.append(entity)
            continue
        sub = by_entity.get(entity)
        if not sub or not sub.chunks:
            continue  # no hits for this entity → nothing to promote, no crash
        # Best sub-query chunk not already in the list.
        present_keys = {_content_key(c) for c in chunks}
        candidate = None
        for idx, c in enumerate(sub.chunks):
            if _content_key(c) not in present_keys:
                candidate = (c, sub.scores[idx] if idx < len(sub.scores) else 0.0,
                             sub.metadatas[idx] if idx < len(sub.metadatas) else {})
                break
        if candidate is None:
            continue
        # Find a removable slot in the top-k: the lowest-ranked non-exempt
        # chunk that does not itself cover the *other* entity.
        other = next((e for e in plan.entities if e != entity), None)
        drop_at = None
        for idx in range(min(budget, len(chunks)) - 1, -1, -1):
            if exempt(metadatas[idx] or {}):
                continue
            if other and _entity_present(other, [chunks[idx]], [metadatas[idx]]):
                continue
            drop_at = idx
            break
        c, s, m = candidate
        if drop_at is not None:
            chunks.insert(drop_at, c)
            scores.insert(drop_at, s)
            metadatas.insert(drop_at, dict(m or {}))
        else:
            chunks.insert(0, c)
            scores.insert(0, s)
            metadatas.insert(0, dict(m or {}))
        promoted.append(entity)

    diag = {
        "comparative_entities_covered": covered + promoted,
        "comparative_entities_promoted": promoted,
    }
    return chunks, scores, metadatas, diag


async def augment_with_comparative_subqueries(
    *,
    plan: ComparativePlan,
    primary: tuple[list[str], list[float], list[dict[str, Any]]],
    retrieve: Callable[[str, float], Awaitable[Any]],
    deadline_seconds: float,
    pool_limit: int,
) -> tuple[list[str], list[float], list[dict[str, Any]], dict[str, Any]]:
    """Run the entity sub-queries in parallel and merge with the primary hits.

    ``retrieve(subquery, deadline)`` must return an object exposing
    ``chunks``/``scores``/``metadatas`` (the existing RetrievalPipelineResult).
    Sub-query failures degrade to "no extra hits", never an exception.
    """
    import asyncio

    max_sub = max(0, int(settings.rag_comparative_decompose_max_subqueries))
    pairs = list(zip(plan.entities, plan.subqueries))[:max_sub] if max_sub else []
    per_query_deadline = max(0.2, float(deadline_seconds))

    async def _one(entity: str, subquery: str) -> _SubResult:
        try:
            res = await asyncio.wait_for(retrieve(subquery, per_query_deadline), timeout=per_query_deadline)
        except (TimeoutError, asyncio.TimeoutError):
            return _SubResult(entity, [], [], [])
        except Exception:  # noqa: BLE001 - never break the primary retrieval.
            return _SubResult(entity, [], [], [])
        return _SubResult(
            entity,
            list(getattr(res, "chunks", []) or []),
            list(getattr(res, "scores", []) or []),
            [dict(m or {}) for m in (getattr(res, "metadatas", []) or [])],
        )

    sub_results = list(await asyncio.gather(*(_one(e, q) for e, q in pairs))) if pairs else []
    chunks, scores, metas, merge_diag = merge_comparative_results(primary, sub_results, limit=pool_limit)
    diag = {
        "comparative_decompose": True,
        "comparative_entities": list(plan.entities),
        "comparative_subqueries": list(plan.subqueries),
        **merge_diag,
        "_sub_results": sub_results,  # consumed by ensure_entity_coverage, stripped before serialisation
    }
    return chunks, scores, metas, diag
