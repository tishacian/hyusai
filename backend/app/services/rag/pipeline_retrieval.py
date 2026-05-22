"""HAH-like and C-HAH-like retrieval on top of DocumentService (strategy A).

Implements multi-pass retrieval inspired by ``src/customchain.py`` (HAH: initial search +
secondary search from fused context) and ``src/customchainmixedhah.py`` (C-HAH: parallel
query variants + fusion). Generation stays in the agent (OpenAI-compatible LLM).

See ``docs/rag-rd-papai-mapping.md`` for mapping vs legacy ``CustomLLMChain``.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Literal, Optional

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.services.rag.document_service import DocumentService

logger = get_logger(__name__)

# Tunables (keep latency bounded on large KBs)
HAH_FIRST_PASS_CAP = 15
HAH_PSEUDO_DOC_MAX_CHARS = 2000
HAH_SECOND_PASS_CAP = 20
CHAH_QUERY_TRUNC = 120
CHAH_MAX_WORDS_HEAD = 12
RRF_K = 60
_SPREADSHEET_LABEL_TRIGGERS_RE = re.compile(
    r"\b("
    r"diam[eè]tre|diameter|label|labell?is[ée]e?|lettre|letter|strip|strips|"
    r"trou|trous|hole|holes|def\s+strips?"
    r")\b",
    re.IGNORECASE,
)
_SPREADSHEET_LABEL_RE = re.compile(
    r"(?:\b(?:label|lettre|letter|diam[eè]tre|diameter|strip|trou|hole)\s+"
    r"(?:labell?is[ée]e?\s+)?(?:par\s+la\s+lettre\s+|sous\s+le\s+label\s+|"
    r"du\s+label\s+|de\s+la\s+lettre\s+)?)"
    r"([A-Z])\b",
    re.IGNORECASE,
)
_UPPERCASE_LABEL_TOKEN_RE = re.compile(r"\b([A-Z])\b")
_SPREADSHEET_PROTOCOL_TRIGGERS_RE = re.compile(
    r"\b("
    r"protocole|protocol|essais?|trial|trials?|tests?|production|"
    r"poids|weight|grammage|gsm|strip|strips|standard|chanvre|hemp"
    r")\b",
    re.IGNORECASE,
)
_TRIAL_CODE_RE = re.compile(
    r"\b(?:test|essai|trial|trials?\s*n[°o]?)?\s*([0-9]{1,3}[A-Z])\b",
    re.IGNORECASE,
)
_DATE_DMY_RE = re.compile(r"\b([0-3]?\d)[/-]([01]?\d)[/-](20\d{2}|19\d{2})\b")
_DATE_YMD_RE = re.compile(r"\b(20\d{2}|19\d{2})[/-]([01]?\d)[/-]([0-3]?\d)\b")


@dataclass
class RetrievalPipelineResult:
    """Unified contract for ``retrieve_for_mode``."""

    chunks: List[str]
    scores: List[float]
    pipeline: Literal[
        "naive",
        "hybrid",
        "hah_backend",
        "chah_backend",
        "fallback_hybrid",
    ]
    label: str
    reason: str
    detail: str
    # Per-chunk metadata kept in lockstep with ``chunks``/``scores`` so the
    # caller can build real citations (document title, page, docmeta keywords)
    # instead of the legacy "Policy chunk N" placeholder. ``default_factory``
    # keeps back-compat for callers that only read chunks/scores.
    metadatas: List[dict] = field(default_factory=list)


@dataclass(frozen=True)
class TableQueryPlan:
    """Provider-neutral description of a spreadsheet-oriented lookup."""

    is_table_query: bool
    labels: list[str] = field(default_factory=list)
    sheet_names: list[str] = field(default_factory=list)
    metric_terms: list[str] = field(default_factory=list)
    trial_codes: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    wants_comparison: bool = False
    variants: list[str] = field(default_factory=list)


class TableQueryPlanner:
    """Lightweight planner for table lookup/query expansion.

    This is intentionally lexical for V1: it improves routing/rerank without
    hardcoding a workspace or depending on a table-QA model.
    """

    def plan(self, question: str, query_hints: str | None = None) -> TableQueryPlan:
        q = (question or "").strip()
        labels = _spreadsheet_label_targets(q)
        sheet_names = _spreadsheet_sheet_targets(q)
        metric_terms = _spreadsheet_metric_targets(q)
        trial_codes = _trial_code_targets(q)
        dates = _date_query_variants(q)
        variants = _spreadsheet_label_query_variants(q) + _spreadsheet_protocol_query_variants(q)
        if query_hints and q:
            variants.append(f"{q}\n\nKnowledge guide hints:\n{str(query_hints)[:900]}")
        wants_comparison = bool(
            re.search(r"\b(tous|toutes|global|globalement|plusieurs|different|diff[ée]rent|compare)\b", q, re.IGNORECASE)
        )
        return TableQueryPlan(
            is_table_query=bool(
                labels
                or sheet_names
                or metric_terms
                or trial_codes
                or dates
                or _SPREADSHEET_PROTOCOL_TRIGGERS_RE.search(q or "")
            ),
            labels=labels,
            sheet_names=sheet_names,
            metric_terms=metric_terms,
            trial_codes=trial_codes,
            dates=dates,
            wants_comparison=wants_comparison,
            variants=list(dict.fromkeys(v for v in variants if v)),
        )


def _content_key(content: str) -> str:
    h = hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
    return h


def _result_content_score(r: dict[str, Any]) -> tuple[str, float]:
    content = r.get("content") or (r.get("metadata") or {}).get("content", "")
    score = float(r.get("combined_score") or r.get("score") or 0.0)
    return content.strip(), score


def _merge_rrf(result_lists: List[List[dict[str, Any]]], top_k: int) -> List[dict[str, Any]]:
    """Simple RRF merge across multiple ranked lists (same idea as hybrid fusion)."""
    agg: dict[str, float] = {}
    best_row: dict[str, dict[str, Any]] = {}
    for results in result_lists:
        for rank, r in enumerate(results):
            content, _ = _result_content_score(r)
            if not content or len(content) < 10:
                continue
            key = _content_key(content)
            contrib = 1.0 / (RRF_K + rank + 1)
            agg[key] = agg.get(key, 0.0) + contrib
            if key not in best_row:
                best_row[key] = {
                    "content": content,
                    "combined_score": float(r.get("combined_score") or r.get("score") or 0.0),
                    "metadata": r.get("metadata") or {},
                }
            # keep higher raw combined score for display
            prev = best_row[key]["combined_score"]
            cur = float(r.get("combined_score") or r.get("score") or 0.0)
            if cur > prev:
                best_row[key]["combined_score"] = cur
                best_row[key]["metadata"] = r.get("metadata") or best_row[key]["metadata"]

    ordered = sorted(agg.keys(), key=lambda k: agg[k], reverse=True)[:top_k]
    out: List[dict[str, Any]] = []
    for key in ordered:
        row = best_row[key].copy()
        row["combined_score"] = agg[key]
        row["rrf_score"] = agg[key]
        out.append(row)
    return out


def _results_to_chunks_scores(results: List[dict[str, Any]]) -> tuple[list[str], list[float]]:
    chunks: list[str] = []
    scores: list[float] = []
    for r in results:
        c, s = _result_content_score(r)
        if c:
            chunks.append(c)
            scores.append(s)
    return chunks, scores


def _results_to_chunks_scores_metas(
    results: List[dict[str, Any]],
    *,
    dedup: bool = True,
) -> tuple[list[str], list[float], list[dict]]:
    """Convert raw retrieval hits into aligned chunks/scores/metas lists.

    When ``dedup=True`` (default), identical chunk content is collapsed
    to a single entry — keeping the first (highest-ranked) occurrence.
    This protects against the common foot-gun where the same source
    document was ingested multiple times (fresh ``document_id`` each
    upload) and the UI ends up showing 4× the same snippet. RRF merges
    in ``_merge_rrf`` already dedup by content hash, so this only
    applies to the non-HAH/CHAH path (hybrid search).
    """
    chunks: list[str] = []
    scores: list[float] = []
    metas: list[dict] = []
    seen: set[str] = set()
    for r in results:
        c, s = _result_content_score(r)
        if not c:
            continue
        if dedup:
            key = _content_key(c)
            if key in seen:
                continue
            seen.add(key)
        chunks.append(c)
        scores.append(s)
        metas.append(r.get("metadata") or {})
    return chunks, scores, metas


async def retrieve_hah_like(
    doc_svc: "DocumentService",
    query: str,
    top_k: int = 5,
) -> RetrievalPipelineResult:
    """Two-pass retrieval: query → contexts → pseudo-document → second search → RRF merge.

    Mirrors the non-trivial path in ``CustomLLMChain.invoke_async`` (initial search +
    ``search_similar_texts`` on fused filtered context), adapted to ``DocumentService.search``.
    """
    q = (query or "").strip()
    if not q:
        return RetrievalPipelineResult(
            chunks=[],
            scores=[],
            pipeline="hah_backend",
            label="HAH (backend)",
            reason="Empty query",
            detail="No search performed",
            metadatas=[],
        )

    first_k = min(max(top_k * 2, top_k), HAH_FIRST_PASS_CAP)
    pass1 = await doc_svc.search(q, top_k=first_k, use_hybrid=True)
    if not pass1:
        return RetrievalPipelineResult(
            chunks=[],
            scores=[],
            pipeline="hah_backend",
            label="HAH (backend)",
            reason="First pass returned no chunks",
            detail="Pass1: hybrid search",
            metadatas=[],
        )

    parts: list[str] = []
    for r in pass1[:8]:
        c, _ = _result_content_score(r)
        if c:
            parts.append(c)
    pseudo = ". ".join(parts)[:HAH_PSEUDO_DOC_MAX_CHARS]
    pass2 = await doc_svc.search(pseudo, top_k=min(HAH_SECOND_PASS_CAP, first_k + 8), use_hybrid=True)

    merged = _merge_rrf([pass1, pass2] if pass2 else [pass1], top_k=top_k)
    chunks, scores, metas = _results_to_chunks_scores_metas(merged)
    detail = (
        f"Pass1: hybrid top_{first_k}; pseudo-doc ~{len(pseudo)} chars; "
        f"Pass2: hybrid top_{min(HAH_SECOND_PASS_CAP, first_k + 8)}; RRF merge → {len(chunks)} chunks"
    )
    logger.info("HAH-like retrieval complete", pass1=len(pass1), pass2=len(pass2), merged=len(chunks))
    return RetrievalPipelineResult(
        chunks=chunks,
        scores=scores,
        pipeline="hah_backend",
        label="HAH (backend)",
        reason="Two-pass hybrid retrieval + RRF merge (aligned with customchain invoke_async pattern)",
        detail=detail,
        metadatas=metas,
    )


def _query_variants(question: str, query_hints: str | None = None) -> list[str]:
    q = question.strip()
    variants = [q]
    if len(q) > CHAH_QUERY_TRUNC:
        variants.append(q[:CHAH_QUERY_TRUNC].rsplit(" ", 1)[0].strip() or q[:CHAH_QUERY_TRUNC])
    words = re.split(r"\s+", q)
    if len(words) > 5:
        variants.append(" ".join(words[:CHAH_MAX_WORDS_HEAD]))
    table_plan = TableQueryPlanner().plan(q, query_hints=query_hints)
    variants.extend(table_plan.variants)
    # dedupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _date_query_variants(question: str) -> list[str]:
    variants: list[str] = []
    for day, month, year in _DATE_DMY_RE.findall(question or ""):
        iso = f"{year}-{int(month):02d}-{int(day):02d}"
        variants.extend([iso, f"{iso} 00:00:00"])
    for year, month, day in _DATE_YMD_RE.findall(question or ""):
        iso = f"{year}-{int(month):02d}-{int(day):02d}"
        variants.extend([iso, f"{iso} 00:00:00"])
    return list(dict.fromkeys(variants))


def _trial_code_targets(question: str) -> list[str]:
    codes: list[str] = []
    for match in _TRIAL_CODE_RE.finditer(question or ""):
        code = match.group(1).upper()
        if code not in codes:
            codes.append(code)
    return codes


def _trial_code_number(code: str) -> str:
    match = re.match(r"^([0-9]{1,3})[A-Z]$", code.strip().upper())
    return match.group(1) if match else ""


def _spreadsheet_protocol_query_variants(question: str) -> list[str]:
    """Add variants for Excel sheets where values are found by row/column crossing.

    Many industrial trial workbooks use a protocol matrix: one row defines the
    trial columns (``trials N°`` with values such as ``2A``), while another row
    defines a metric (``Poids``, ``Speed``, ``Strip``). Dense retrieval often
    ranks generic sheets above these protocol matrices unless the query names
    the sheet. These variants are generic spreadsheet anchors, not Andritz-
    specific values.
    """
    if not question or not _SPREADSHEET_PROTOCOL_TRIGGERS_RE.search(question):
        return []

    q = question.strip()
    variants = [
        f"{q} Spreadsheet sheet Protocole essais trials N°",
        f"{q} protocol trial matrix row metric column value",
    ]
    codes = _trial_code_targets(question)
    dates = _date_query_variants(question)
    for code in codes[:4]:
        test_number = _trial_code_number(code)
        variants.extend(
            [
                f"Protocole essais trials N° {code}",
                f"Spreadsheet sheet Protocole essais {code} Poids Weight",
                f"trial {code} metric value row Poids",
            ]
        )
        if test_number:
            variants.extend(
                [
                    f"Spreadsheet sheet test {test_number} Weight Poids",
                    f"test {test_number} Weight g/m² gsm",
                    f"test {test_number} metric value row Weight",
                ]
            )
    for date in dates[:4]:
        variants.append(f"Protocole essais DATE {date}")
    if re.search(r"\b(?:geotex|customer|client)\b", question, re.IGNORECASE):
        variants.append("Protocole essais Customer GEOTEX DATE")
    if re.search(r"\b(?:chanvre|hemp)\b", question, re.IGNORECASE) and re.search(
        r"\bstrips?\b",
        question,
        re.IGNORECASE,
    ):
        variants.extend(
            [
                f"{q} spreadsheet sheet strip chanvre",
                f"{q} strip chanvre production standard",
            ]
        )
    return variants


def _spreadsheet_label_query_variants(question: str) -> list[str]:
    """Add exact-ish Excel label variants for small tabular business lookups.

    A query like "diamètre B" is semantically tiny: once a collection contains
    many spreadsheets, dense retrieval often prefers unrelated sheets that also
    contain "B" or "diameter-like" headers. The spreadsheet parser renders
    two-column definitions as ``A2=B | B2=85 | B = 85``. These variants give
    C-HAH/BM25 a chance to find that explicit table without hardcoding any
    Andritz collection or value.
    """
    if not question or not _SPREADSHEET_LABEL_TRIGGERS_RE.search(question):
        return []

    labels = _spreadsheet_label_targets(question)

    variants: list[str] = []
    for label in labels[:4]:
        variants.extend(
            [
                f"Spreadsheet sheet Def strips {label} =",
                f'Spreadsheet cell fact Def strips label "{label}" value',
                f'Spreadsheet table fact Def strips row_label "{label}" value',
                f'Spreadsheet semantic sentence Def strips label "{label}" value',
                f"Def strips label {label} value {label} =",
                f"Row A={label} B= value strip diameter label {label}",
                f"A2={label} B2 {label} =",
            ]
        )
    return variants


def _spreadsheet_label_targets(question: str) -> list[str]:
    if not question or not _SPREADSHEET_LABEL_TRIGGERS_RE.search(question):
        return []

    labels: list[str] = []
    for match in _SPREADSHEET_LABEL_RE.finditer(question):
        label = match.group(1).upper()
        if label not in labels:
            labels.append(label)
    # French voice queries often end as "diamètre B ?" where the trigger and
    # the target are separate tokens. Only fall back to single-letter tokens
    # when the query has a spreadsheet/table trigger to avoid polluting normal
    # prose searches.
    for match in _UPPERCASE_LABEL_TOKEN_RE.finditer(question):
        label = match.group(1).upper()
        if label not in labels:
            labels.append(label)
    return labels


def _spreadsheet_sheet_targets(question: str) -> list[str]:
    """Extract explicit spreadsheet sheet hints from user language.

    Keep this conservative: explicit sheets are strong constraints and should
    not be inferred from arbitrary prose. Common speech-to-text variants of
    "Def strips" are normalized because they are table names, not values.
    """
    q = question or ""
    targets: list[str] = []
    if re.search(r"\b(?:def|dev)\s*strips?\b", q, re.IGNORECASE):
        targets.append("Def strips")
    if re.search(r"\bprotocole\s+essais\b|\bprotocol\b", q, re.IGNORECASE):
        targets.append("Protocole essais")
    for test_number in {_trial_code_number(code) for code in _trial_code_targets(q)}:
        if test_number:
            targets.append(f"test {test_number}")
    return list(dict.fromkeys(targets))


def _spreadsheet_metric_targets(question: str) -> list[str]:
    q = question or ""
    targets: list[str] = []
    metric_patterns = [
        (r"\bpoids\b|\bweight\b", ["Poids", "Weight"]),
        (r"\bgrammage\b|\bgsm\b", ["Grammage", "Weight"]),
        (r"\bstrip|strips\b", ["Strip", "strips"]),
        (r"\bvitesse\b|\bspeed\b", ["Speed", "Vitesse"]),
        (r"\bpression\b|\bpressure\b", ["Pressure", "Pression"]),
    ]
    for pattern, values in metric_patterns:
        if re.search(pattern, q, re.IGNORECASE):
            targets.extend(values)
    return list(dict.fromkeys(targets))


def _spreadsheet_label_match_score(content: str, labels: list[str]) -> int:
    """Prioritise exact label→value table hits after broad spreadsheet retrieval.

    Dense/BM25 retrieval can prefer large protocol sheets because they contain
    many business terms. For a query such as "diamètre B", a small definition
    table containing ``B = 85`` is more useful than broad context. This is a
    lightweight lexical rerank, not an Andritz-specific value rule.
    """
    if not labels:
        return 0
    text = str(content or "")
    if not _is_spreadsheet_evidence(text):
        return 0

    score = 0
    for label in labels:
        if re.search(rf"\b{re.escape(label)}\s*=\s*[-+]?\d", text):
            score += 8
        if re.search(rf'label="{re.escape(label)}"\s+value="[-+]?\d', text, re.IGNORECASE):
            score += 10
        if re.search(rf'row_label="{re.escape(label)}".*?value="[-+]?\d', text, re.IGNORECASE):
            score += 8
        if re.search(
            rf'label "{re.escape(label)}" has value "[-+]?\d',
            text,
            re.IGNORECASE,
        ):
            score += 7
        if re.search(rf"\b[A-Z]+\d+\s*=\s*{re.escape(label)}\b", text) and re.search(
            r"\b[A-Z]+\d+\s*=\s*[-+]?\d",
            text,
        ):
            score += 3
    if re.search(r"\bdef\s+strips?\b", text, re.IGNORECASE):
        score += 4
    lower = text.lower()
    if "spreadsheet cell fact:" in lower:
        score += 3
    if "spreadsheet semantic sentence:" in lower:
        score += 2
    return score


def _spreadsheet_protocol_match_score(content: str, question: str) -> int:
    if not question or not _SPREADSHEET_PROTOCOL_TRIGGERS_RE.search(question):
        return 0
    text = str(content or "")
    lower = text.lower()
    if not _is_spreadsheet_evidence(text):
        return 0

    score = 0
    if re.search(r"\bprotocole\s+essais\b", lower) or re.search(r"\bprotocol\b", lower):
        if re.search(r"\bprotocole|protocol|essais?|trial|tests?\b", question, re.IGNORECASE):
            score += 7
    if "trials n" in lower or "trial" in lower:
        score += 2

    for code in _trial_code_targets(question):
        if re.search(rf"\b{re.escape(code)}\b", text, re.IGNORECASE):
            score += 6
        if re.search(rf'column_header="{re.escape(code)}"', text, re.IGNORECASE):
            score += 10
        test_number = _trial_code_number(code)
        if test_number and re.search(rf"\btest\s+{re.escape(test_number)}\b", lower):
            score += 6
            if re.search(r"\bpoids\b|\bweight\b|\bgrammage\b|\bgsm\b", lower, re.IGNORECASE):
                score += 6

    for date in _date_query_variants(question):
        if date in text:
            score += 5

    metric_terms = [
        ("poids", r"\bpoids\b|\bweight\b"),
        ("weight", r"\bpoids\b|\bweight\b"),
        ("grammage", r"\bgrammage\b|\bgsm\b"),
        ("gsm", r"\bgrammage\b|\bgsm\b"),
        ("strip", r"\bstrip|strips\b"),
        ("standard", r"\bstandard\b|\bstrip|strips\b"),
        ("chanvre", r"\bchanvre\b|\bhemp\b"),
        ("hemp", r"\bchanvre\b|\bhemp\b"),
    ]
    for query_term, content_pattern in metric_terms:
        if re.search(rf"\b{query_term}\b", question, re.IGNORECASE) and re.search(
            content_pattern,
            lower,
            re.IGNORECASE,
        ):
            score += 3

    if re.search(r"\bgeotex\b", question, re.IGNORECASE) and "geotex" in lower:
        score += 4
    if re.search(r"\bchanvre|hemp\b", question, re.IGNORECASE) and re.search(
        r"\bchanvre|hemp\b",
        lower,
        re.IGNORECASE,
    ):
        score += 4
    if "spreadsheet table fact:" in lower:
        score += 4
    if "spreadsheet cell fact:" in lower:
        score += 2
    return score


def _norm_token(value: Any) -> str:
    return str(value or "").strip().lower()


def _payload_to_result(payload: dict[str, Any], *, score: float) -> dict[str, Any]:
    content = str(payload.get("content") or "").strip()
    if not content:
        sheet = payload.get("sheet_name") or "unknown"
        row_label = payload.get("row_label") or ""
        column_header = payload.get("column_header") or ""
        value = payload.get("value") or ""
        cell_ref = payload.get("cell_ref") or payload.get("cell_range") or ""
        content = (
            f'Spreadsheet table fact: sheet="{sheet}" '
            f'cell={cell_ref} value="{value}"'
            + (f' row_label="{row_label}"' if row_label else "")
            + (f' column_header="{column_header}"' if column_header else "")
        )
    return {
        "id": str(payload.get("chunk_id") or payload.get("point_id") or _content_key(content)),
        "content": content,
        "score": score,
        "combined_score": score,
        "metadata": dict(payload),
        "table_exact_match": True,
    }


def _score_table_payload(payload: dict[str, Any], question: str, plan: TableQueryPlan) -> int:
    content = str(payload.get("content") or "")
    score = 50
    stype = _norm_token(payload.get("semantic_type"))
    sheet = _norm_token(payload.get("sheet_name"))
    row_label = _norm_token(payload.get("row_label"))
    column_header = _norm_token(payload.get("column_header"))

    if stype == "spreadsheet_cell_fact":
        score += 18
    elif stype == "spreadsheet_semantic_sentence":
        score += 16
    elif stype == "spreadsheet_table_fact":
        score += 12
    elif stype == "spreadsheet_row":
        score += 4

    sheet_targets = [_norm_token(s) for s in plan.sheet_names]
    if sheet_targets:
        if sheet in sheet_targets:
            score += 60
        else:
            score -= 20
    elif plan.labels and sheet == "def strips":
        score += 45

    for label in plan.labels:
        label_norm = _norm_token(label)
        if row_label == label_norm:
            score += 45
        if re.search(rf'\blabel="{re.escape(label)}"\s+value="[-+]?\d', content, re.IGNORECASE):
            score += 30
        if re.search(rf"\b{re.escape(label)}\s*=\s*[-+]?\d", content):
            score += 24

    for code in plan.trial_codes:
        code_norm = _norm_token(code)
        if column_header == code_norm:
            score += 55
        if re.search(rf"\b{re.escape(code)}\b", content, re.IGNORECASE):
            score += 12

    for metric in plan.metric_terms:
        metric_norm = _norm_token(metric)
        if row_label == metric_norm:
            score += 35
        if metric_norm and metric_norm in _norm_token(content):
            score += 8

    for date in plan.dates:
        if date in content:
            score += 8

    if re.search(r"\bgeotex\b", question, re.IGNORECASE) and "geotex" in _norm_token(content):
        score += 8
    if re.search(r"\bchanvre|hemp\b", question, re.IGNORECASE) and re.search(
        r"\bchanvre|hemp\b",
        content,
        re.IGNORECASE,
    ):
        score += 12

    # A query for the label "N" often collides with force-unit sheets such as
    # "N/50 mm". If an explicit Def-strips-like label lookup exists, keep
    # those unit tables behind real label-value facts.
    if plan.labels and any(label == "N" for label in plan.labels):
        if "n/50" in _norm_token(content) and sheet != "def strips":
            score -= 25
    return score


async def _exact_table_fact_candidates(
    doc_svc: "DocumentService",
    query: str,
    plan: TableQueryPlan,
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    """Fetch exact table facts by payload before dense/BM25 ranking.

    Vector search is intentionally broad; for spreadsheet lookups we often
    already know the structured keys (sheet, row label, trial column). Qdrant
    payload filtering gives those facts a deterministic path into the context.
    """
    if not plan.is_table_query or not hasattr(doc_svc, "list_table_facts"):
        return []

    payloads: list[dict[str, Any]] = []

    async def collect(**kwargs: Any) -> None:
        try:
            rows = await doc_svc.list_table_facts(limit=120, **kwargs)
        except TypeError:
            # Older/fake services in tests may not accept newly added filters.
            return
        except Exception as exc:  # pragma: no cover - defensive production guard
            logger.debug("Exact table fact lookup failed", error=str(exc), filters=kwargs)
            return
        payloads.extend(dict(row) for row in rows)

    fact_types = (
        "spreadsheet_cell_fact",
        "spreadsheet_semantic_sentence",
        "spreadsheet_table_fact",
        "spreadsheet_row",
    )

    label_sheets = plan.sheet_names
    if plan.labels and not label_sheets and _SPREADSHEET_LABEL_TRIGGERS_RE.search(query or ""):
        # Business label lookups usually live in dedicated definition sheets.
        # This is a structural hint, not a value rule: if no such sheet exists,
        # the row_label fallback below still works.
        label_sheets = ["Def strips"]

    for label in plan.labels[:4]:
        for sheet in label_sheets:
            for stype in fact_types:
                await collect(semantic_type=stype, sheet_name=sheet, row_label=label)
        for stype in fact_types[:3]:
            await collect(semantic_type=stype, row_label=label)

    for code in plan.trial_codes[:4]:
        for stype in ("spreadsheet_table_fact", "spreadsheet_row"):
            await collect(semantic_type=stype, column_header=code)
        test_number = _trial_code_number(code)
        if test_number:
            await collect(semantic_type="spreadsheet_row", sheet_name=f"test {test_number}")
            for metric in plan.metric_terms[:4]:
                await collect(
                    semantic_type="spreadsheet_table_fact",
                    sheet_name=f"test {test_number}",
                    row_label=metric,
                )

    for sheet in plan.sheet_names[:3]:
        if not plan.labels:
            await collect(semantic_type="spreadsheet_row", sheet_name=sheet, query=query[:80])

    scored: list[tuple[int, dict[str, Any]]] = []
    seen: set[str] = set()
    for payload in payloads:
        content = str(payload.get("content") or "")
        if not content:
            continue
        key = str(payload.get("chunk_id") or payload.get("point_id") or _content_key(content))
        if key in seen:
            continue
        seen.add(key)
        score = _score_table_payload(payload, query, plan)
        if score <= 35:
            continue
        scored.append((score, _payload_to_result(payload, score=min(0.999, score / 160.0))))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[: max(top_k * 2, top_k + 4)]]


def _is_spreadsheet_evidence(content: str) -> bool:
    lower = str(content or "").lower()
    return (
        "spreadsheet sheet:" in lower
        or "spreadsheet label-value fact:" in lower
        or "spreadsheet interpreted cells:" in lower
        or "spreadsheet header row:" in lower
        or "spreadsheet cell fact:" in lower
        or "spreadsheet table fact:" in lower
        or "spreadsheet semantic sentence:" in lower
        or "spreadsheet schema:" in lower
    )


def _prioritise_spreadsheet_label_matches(
    results: list[dict[str, Any]],
    question: str,
) -> list[dict[str, Any]]:
    plan = TableQueryPlanner().plan(question)
    if not plan.is_table_query:
        return results
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for index, row in enumerate(results):
        content, _ = _result_content_score(row)
        score = _spreadsheet_label_match_score(content, plan.labels)
        score += _spreadsheet_protocol_match_score(content, question)
        metadata = row.get("metadata") or {}
        if metadata:
            score += _score_table_payload(metadata, question, plan) - 50
        if row.get("table_exact_match"):
            score += 60
        ranked.append((score, -index, row))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [row for _, _, row in ranked]


def _prepend_exact_table_candidates(
    exact_rows: list[dict[str, Any]],
    ranked_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not exact_rows:
        return ranked_rows
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in [*exact_rows, *ranked_rows]:
        content, _ = _result_content_score(row)
        if not content:
            continue
        key = str((row.get("metadata") or {}).get("chunk_id") or row.get("id") or _content_key(content))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


async def retrieve_chah_like(
    doc_svc: "DocumentService",
    query: str,
    top_k: int = 5,
    query_hints: str | None = None,
) -> RetrievalPipelineResult:
    """Parallel retrieval over query variants + RRF merge (C-HAH-like).

    Inspired by composite / multi-strategy retrieval in ``customchainmixedhah`` (parallel
    plans + fusion), without importing ``src``.
    """
    q = (query or "").strip()
    if not q:
        return RetrievalPipelineResult(
            chunks=[],
            scores=[],
            pipeline="chah_backend",
            label="C-HAH (backend)",
            reason="Empty query",
            detail="No search performed",
            metadatas=[],
        )

    table_plan = TableQueryPlanner().plan(q, query_hints=query_hints)
    exact_rows = await _exact_table_fact_candidates(doc_svc, q, table_plan, top_k=top_k)
    variants = _query_variants(q, query_hints=query_hints)
    searches = [doc_svc.search(v, top_k=min(12, top_k + 7), use_hybrid=True) for v in variants]
    lists = await asyncio.gather(*searches)
    candidate_k = min(max(top_k * 4, top_k + 10), 30)
    merged = _prioritise_spreadsheet_label_matches(
        _merge_rrf(list(lists), top_k=candidate_k),
        q,
    )
    merged = _prepend_exact_table_candidates(exact_rows, merged)[:top_k]
    chunks, scores, metas = _results_to_chunks_scores_metas(merged)
    v_preview = repr(variants)[:200]
    detail = (
        f"Parallel hybrid searches: {len(variants)} query variant(s); "
        f"RRF candidate merge top_{candidate_k}; exact_table_hits={len(exact_rows)} "
        f"→ {len(chunks)} chunks. Variants: {v_preview}"
    )
    logger.info("C-HAH-like retrieval complete", variants=len(variants), merged=len(chunks))
    return RetrievalPipelineResult(
        chunks=chunks,
        scores=scores,
        pipeline="chah_backend",
        label="C-HAH (backend)",
        reason="Parallel hybrid retrieval over query variants + RRF merge",
        detail=detail,
        metadatas=metas,
    )


def _normalize_mode(mode: Optional[str]) -> str:
    return (mode or "auto").strip().lower()


async def retrieve_for_mode(
    doc_svc: Optional["DocumentService"],
    query: str,
    mode: Optional[str],
    *,
    top_k: int = 5,
    use_hybrid: bool = True,
    hah_chah_enabled: bool = True,
    query_hints: str | None = None,
) -> RetrievalPipelineResult:
    """
    Single entry for RAG retrieval by pipeline mode.

    - ``hah`` / ``chah`` : dedicated backend pipelines when ``hah_chah_enabled``.
    - Otherwise: single ``DocumentService.search`` (naive vs hybrid via ``use_hybrid``).
    """
    if doc_svc is None:
        return RetrievalPipelineResult(
            chunks=[],
            scores=[],
            pipeline="fallback_hybrid",
            label="none",
            reason="DocumentService unavailable",
            detail="RAG disabled",
            metadatas=[],
        )

    m = _normalize_mode(mode)

    if hah_chah_enabled and m in ("hah", "hah_rag", "hah rag"):
        return await retrieve_hah_like(doc_svc, query, top_k=top_k)
    if hah_chah_enabled and m in ("chah", "c-hah", "c_hah", "hahcomposite", "hah_composite"):
        return await retrieve_chah_like(doc_svc, query, top_k=top_k, query_hints=query_hints)

    table_plan = TableQueryPlanner().plan(query, query_hints=query_hints)
    exact_rows = await _exact_table_fact_candidates(doc_svc, query, table_plan, top_k=top_k)
    search_query = query
    if query_hints:
        search_query = f"{query}\n\nKnowledge guide hints:\n{str(query_hints)[:900]}"
    candidate_k = top_k
    if table_plan.is_table_query:
        candidate_k = min(max(top_k * 4, top_k + 10), 30)
    results = await doc_svc.search(search_query, top_k=candidate_k, use_hybrid=use_hybrid)
    results = _prioritise_spreadsheet_label_matches(results, query)
    results = _prepend_exact_table_candidates(exact_rows, results)[:top_k]
    chunks, scores, metas = _results_to_chunks_scores_metas(results)
    pipe: Literal["naive", "hybrid"] = "hybrid" if use_hybrid else "naive"
    return RetrievalPipelineResult(
        chunks=chunks,
        scores=scores,
        pipeline=pipe,
        label="vector_only" if not use_hybrid else "hybrid_rrf",
        reason="Standard DocumentService.search",
        detail=(
            f"use_hybrid={use_hybrid} top_k={top_k} candidate_k={candidate_k} "
            f"exact_table_hits={len(exact_rows)}"
        ),
        metadatas=metas,
    )
