"""Declarative source-family facets for corpus planning.

These rules are deliberately about reusable document families, not about
specific answers or filenames. They let the planner say "this query smells like
a spare-parts-list lookup" without encoding which document should win.
KnowledgeGuide retrieval policies can add more source-family rules at runtime.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.services.rag.retrieval_policy import RetrievalPolicy


@dataclass(frozen=True)
class SourceFamilyFacet:
    key: str
    label: str
    query_terms: tuple[str, ...]
    source_terms: tuple[str, ...]
    weight: float = 4.0


DEFAULT_SOURCE_FAMILY_FACETS: tuple[SourceFamilyFacet, ...] = (
    SourceFamilyFacet(
        key="spare_parts_list",
        label="Spare parts list",
        query_terms=(
            "spare",
            "spare part",
            "spare parts",
            "spare parts list",
            "spl",
            "piece",
            "pieces",
            "part list",
            "cartridge",
            "o-ring",
            "oring",
            "joint",
            "gasket",
        ),
        source_terms=("spare", "spare part", "spare parts", "spare parts list", "part list", "spl"),
        weight=6.0,
    ),
    SourceFamilyFacet(
        key="injector_notice",
        label="Injector notice",
        query_terms=("injecteur", "injector", "cartouche", "cartridge", "autoclamped", "strip carrier", "strip-carrier"),
        source_terms=("injecteur", "injector", "cartouche", "cartridge", "autoclamped", "strip carrier", "strip-carrier"),
        weight=5.0,
    ),
    SourceFamilyFacet(
        key="pump_manual",
        label="Pump manual",
        query_terms=("pompe", "pump"),
        source_terms=("pompe", "pump", "pump manual"),
        weight=5.0,
    ),
    SourceFamilyFacet(
        key="maintenance_procedure",
        label="Maintenance procedure",
        query_terms=("maintenance", "filtration", "vacuum", "procedure de maintenance"),
        source_terms=("maintenance", "filtration", "filtering", "vacuum"),
        weight=4.0,
    ),
    SourceFamilyFacet(
        key="conveyor_manual",
        label="Conveyor manual",
        query_terms=("convoyeur", "conveyor"),
        source_terms=("convoyeur", "conveyor"),
        weight=4.0,
    ),
    SourceFamilyFacet(
        key="pneumatic_cabinet",
        label="Pneumatic cabinet",
        query_terms=("armoire", "pneumatique", "pneumatic", "cabinet", "nomenclature"),
        source_terms=("armoire", "pneumatique", "pneumatic", "cabinet", "nomenclature"),
        weight=5.0,
    ),
    SourceFamilyFacet(
        key="spreadsheet_table",
        label="Spreadsheet table",
        query_terms=("table", "feuille", "sheet", "cell", "cellule", "label", "valeur", "value", "xlsx", "excel"),
        source_terms=("spreadsheet", "table", "sheet", "xlsx", "xls", "excel"),
        weight=5.0,
    ),
    SourceFamilyFacet(
        key="operator_manual",
        label="Operator manual",
        query_terms=("manuel", "manual", "notice", "operator", "operation"),
        source_terms=("manuel", "manual", "notice", "operator", "operation"),
        weight=3.0,
    ),
)


def normalise_text(value: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    no_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(no_accents.lower().replace("'", " ").replace("_", " ").split())


def compact_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalise_text(value))


def _contains_term(text: str, term: str) -> bool:
    term_norm = normalise_text(term)
    if not text or not term_norm:
        return False
    if len(term_norm) <= 2:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(term_norm)}(?![a-z0-9])", text))
    if " " in term_norm:
        return compact_text(term_norm) in compact_text(text)
    return term_norm in text


def _policy_facets(policy: RetrievalPolicy | None) -> tuple[SourceFamilyFacet, ...]:
    if not policy or not policy.enabled:
        return ()
    facets: list[SourceFamilyFacet] = []
    for rule in policy.source_family_rules:
        for family in rule.source_families:
            key = normalise_text(family).replace(" ", "_")
            if not key:
                continue
            source_terms = tuple({family, key.replace("_", " ")})
            facets.append(
                SourceFamilyFacet(
                    key=key,
                    label=family,
                    query_terms=tuple(rule.when_terms),
                    source_terms=source_terms,
                    weight=5.0,
                )
            )
    return tuple(facets)


def source_family_facets(policy: RetrievalPolicy | None = None) -> tuple[SourceFamilyFacet, ...]:
    """Return default facets plus any runtime KnowledgeGuide policy facets."""
    by_key: dict[str, SourceFamilyFacet] = {facet.key: facet for facet in DEFAULT_SOURCE_FAMILY_FACETS}
    for facet in _policy_facets(policy):
        if facet.key not in by_key:
            by_key[facet.key] = facet
    return tuple(by_key.values())


def active_source_family_facets(
    query: str,
    policy: RetrievalPolicy | None = None,
) -> tuple[SourceFamilyFacet, ...]:
    text = normalise_text(query)
    active: list[SourceFamilyFacet] = []
    for facet in source_family_facets(policy):
        if any(_contains_term(text, term) for term in facet.query_terms):
            active.append(facet)
    return tuple(active)


def expanded_terms_for_query(query: str, policy: RetrievalPolicy | None = None) -> tuple[str, ...]:
    """Return query expansion terms from facets and KnowledgeGuide aliases."""
    terms: list[str] = []

    def add(*items: str) -> None:
        for item in items:
            cleaned = normalise_text(item)
            if cleaned and cleaned not in terms:
                terms.append(cleaned)

    for facet in active_source_family_facets(query, policy):
        add(*facet.query_terms, *facet.source_terms, facet.key.replace("_", " "))

    if policy and policy.enabled:
        query_text = normalise_text(query)
        for term, expansions in policy.aliases:
            group = (term, *expansions)
            if any(_contains_term(query_text, item) for item in group):
                add(*group)

    return tuple(terms[:80])


def score_source_family_match(
    *,
    query: str,
    row_text: str,
    metadata: Mapping[str, Any] | None = None,
    policy: RetrievalPolicy | None = None,
) -> tuple[float, list[str]]:
    """Score reusable source-family alignment for a ledger row.

    Returns a score and the matched family keys. A match means the query and
    source look aligned at the family level; it never identifies a final answer.
    """
    metadata = metadata or {}
    row_norm = normalise_text(row_text)
    metadata_family = normalise_text(metadata.get("source_family") or "").replace(" ", "_")
    score = 0.0
    matched: list[str] = []
    for facet in active_source_family_facets(query, policy):
        source_match = (
            metadata_family == facet.key
            or any(_contains_term(row_norm, term) for term in facet.source_terms)
        )
        if not source_match:
            continue
        score += facet.weight
        matched.append(facet.key)
    return score, matched
