"""Query-adaptive dense/sparse weights for the RRF merge (RAGGER Annexe C.2).

The hybrid merge historically gave dense and sparse lists identical RRF
contributions. This module resolves per-query weights instead:

- queries carrying exact identifiers (project codes, part numbers — detected
  by the existing ``analyze_query`` patterns, deliberately NOT by
  capitalisation, which would misfire on German where every noun is
  capitalised) lean sparse;
- long or interrogative queries (WH-words in FR/EN/DE) lean dense.

Base weights come from the tenant settings ``ragVectorWeight`` /
``ragBM25Weight`` (which existed but were never consumed), falling back to
the paper defaults 0.6/0.4. Pure module: regex + arithmetic, <1 ms.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.rag.lexical_retrieval import LexicalSignals, analyze_query

_ADJUST = 0.2
_MIN_WEIGHT = 0.2
_MAX_WEIGHT = 0.8
_LONG_QUERY_TOKENS = 12

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
# WH-words FR/EN/DE; matched on the accent-folded, lowercased query.
_WH_WORDS_RE = re.compile(
    r"\b("
    r"what|which|who|where|when|why|how|"
    r"quoi|quel(?:le)?s?|qui|ou|quand|pourquoi|comment|qu'est|"
    r"was|welche[rsn]?|wer|wo|wann|warum|weshalb|wie"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FusionWeights:
    dense: float
    sparse: float
    method: str  # "weighted_rrf" | "rrf"
    reason: str

    def as_diagnostics(self) -> dict[str, object]:
        return {
            "fusion_method": self.method,
            "fusion_dense_weight": round(self.dense, 3),
            "fusion_sparse_weight": round(self.sparse, 3),
            "fusion_reason": self.reason,
        }


def _fold(text: str) -> str:
    import unicodedata

    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    ).lower()


def _clamp_and_normalise(dense: float, sparse: float) -> tuple[float, float]:
    dense = max(_MIN_WEIGHT, min(_MAX_WEIGHT, dense))
    sparse = max(_MIN_WEIGHT, min(_MAX_WEIGHT, sparse))
    total = dense + sparse
    return dense / total, sparse / total


def base_fusion_weights() -> tuple[float, float]:
    """Tenant ragVectorWeight/ragBM25Weight, paper defaults 0.6/0.4 otherwise."""
    try:
        from app.core.settings_manager import get_resolved_settings

        app_settings = get_resolved_settings()
        dense = float(app_settings.get("ragVectorWeight") or 0.6)
        sparse = float(app_settings.get("ragBM25Weight") or 0.4)
        if dense <= 0 or sparse <= 0:
            return 0.6, 0.4
        return dense, sparse
    except Exception:  # noqa: BLE001 - weights must never break retrieval.
        return 0.6, 0.4


def resolve_fusion_weights(
    query: str,
    *,
    base_dense: float | None = None,
    base_sparse: float | None = None,
    signals: LexicalSignals | None = None,
) -> FusionWeights:
    if base_dense is None or base_sparse is None:
        base_dense, base_sparse = base_fusion_weights()
    if signals is None:
        signals = analyze_query(query or "")

    dense = float(base_dense)
    sparse = float(base_sparse)
    reasons: list[str] = []

    if signals.exact_terms or signals.identifier_variants or signals.requires_exact_match:
        sparse += _ADJUST
        dense -= _ADJUST
        reasons.append("exact_identifiers")

    folded = _fold(query or "")
    token_count = len(_TOKEN_RE.findall(folded))
    if token_count > _LONG_QUERY_TOKENS or _WH_WORDS_RE.search(folded):
        dense += _ADJUST
        sparse -= _ADJUST
        reasons.append("long_or_interrogative")

    dense, sparse = _clamp_and_normalise(dense, sparse)
    return FusionWeights(
        dense=dense,
        sparse=sparse,
        method="weighted_rrf" if reasons or (base_dense, base_sparse) != (0.5, 0.5) else "rrf",
        reason="+".join(reasons) or "base_weights",
    )
