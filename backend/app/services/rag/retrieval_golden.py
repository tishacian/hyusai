"""Golden retrieval cases and source/evidence evaluation helpers.

Golden cases validate retrieval evidence, not generated answer prose. This
keeps the suite useful for Agentium retrieval quality without encouraging
question-to-answer hardcoding.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.seeds.retrieval_golden import DEFAULT_GOLDEN_BATCH




def _parse_expected_inventory(raw: Any) -> dict[str, Any] | None:
    """Normalise a golden case's optional positive inventory expectation.

    Returns ``None`` (evaluator no-op) for anything that is not a mapping, so a
    case without the key is entirely unaffected. Project codes are upper-cased
    and stripped to match the ``project_code`` payload values produced by the
    facet; ``expected_terms`` is preserved verbatim (compared as an ordered list
    against the facet ``terms``) and, when omitted, imposes no terms constraint.
    """
    if not isinstance(raw, Mapping):
        return None

    def _codes(key: str) -> tuple[str, ...]:
        return tuple(
            str(item).strip().upper()
            for item in raw.get(key) or ()
            if str(item).strip()
        )

    expected_terms = raw.get("expected_terms")
    return {
        "min_total_projects": max(0, int(raw.get("min_total_projects") or 0)),
        "must_include_projects": _codes("must_include_projects"),
        "must_exclude_projects": _codes("must_exclude_projects"),
        "expected_terms": tuple(str(term) for term in expected_terms)
        if expected_terms is not None
        else None,
    }


@dataclass(frozen=True)
class RetrievalGoldenCase:
    id: str
    query: str
    collection: str
    expected_sources: tuple[str, ...]
    expected_evidence_terms: tuple[str, ...]
    expected_intent: str
    forbidden_route: str | None = None
    latency_profile: str = "fast"
    min_expected_sources: int = 1
    # Query language ("fr" | "en" | "de") — documents the multilingual axis
    # and lets reporters slice pass-rates per language.
    language: str = "fr"
    # Extra retrieval filters forwarded verbatim (project_code, source_kind…)
    # to exercise scope/metadata-filtered retrieval.
    retrieval_filters: Mapping[str, Any] | None = None
    # Prior turns for multi-turn cases: the follow-up query must retrieve with
    # the conversation anchors, not the bare anaphora.
    conversation_history: tuple[Mapping[str, Any], ...] = ()
    # Diagnostics expected in context.metrics (e.g. {"sparse_status": "ok"},
    # {"cross_encoder_status": "applied"}). Compared as string equality.
    expected_diagnostics: Mapping[str, Any] | None = None
    # Sources that must NOT appear in the selected sources (cross-project
    # contamination guard).
    forbidden_sources: tuple[str, ...] = ()
    # Minimum number of DISTINCT documents required among the top-k retrieved
    # chunks (0 disables the check). Encodes diversity expectations for
    # redundancy-heavy queries: surfacing k chunks of one manual fails even if
    # the expected source matched (MMR/diversity stages are what satisfy it).
    #
    # WARNING: this counts distinct *document_filename* labels, and the Andritz
    # corpus prefixes filenames with the project/archive that owns the copy
    # (``A__ACJ200__…__g150-operating-instructions-0312-en.pdf``). So three
    # copies of the SAME manual indexed under three projects count as three
    # "distinct documents" here — vacuously satisfied by the round-robin, which
    # diversifies by ``document_id``. Use ``expected_distinct_content`` to gate
    # on real content diversity (see ``_content_key``).
    expected_distinct_documents: int = 0
    # Minimum number of DISTINCT CONTENT documents required among the top-k
    # chunks (0 disables). Grouping strips the project/archive prefix from the
    # filename so copies of one manual collapse to a single content key
    # (``_content_key``). This is the diversity signal the embedding MMR stage
    # can actually move — round-robin (which keys on ``document_id``) treats
    # per-project copies as diverse and cannot raise it.
    expected_distinct_content: int = 0
    # Ground-truth reasoning type for the Bayesian prompt classifier
    # (SystemPromptType value: factual | analytical | comparative | causal |
    # hypothetical). The classifier runs AFTER retrieval (prompt_type=="auto"),
    # so it is invisible to the retrieval scoring above — these fields drive a
    # separate, offline classifier eval (``evaluate_prompt_type_case``).
    # ``trivial`` is intentionally not a valid label: it must never be
    # auto-selected.
    expected_prompt_type: str | None = None
    # Secondary types that also count as correct (genuine borderline cases,
    # e.g. "what does X cover" reads as factual or analytical).
    acceptable_prompt_types: tuple[str, ...] = ()
    # Queries with no decisive reasoning marker (imperative retrieval commands)
    # are excluded from strict classifier accuracy and reported separately.
    prompt_type_ambiguous: bool = False
    # Score this case with the full (patterns+coherence) classifier instead of
    # the fast (patterns-only) path. The full path needs the embedder, so the
    # offline runner only honours it when embeddings are available.
    requires_coherence: bool = False
    # Answer-profile hint forwarded verbatim into the retrieval request by
    # ``to_request`` (harness-only). Setting ``transversal_inventory`` arms the
    # additive cross-project inventory facet in the live runner so a case's
    # ``expected_inventory`` can actually be evaluated. It is read ONLY by
    # ``rag.context._should_build_project_inventory``; dense_policy/intent derive
    # from the query (``corpus_planner.classify_intent``), so this never perturbs
    # the route-based assertions (``forbidden_route``).
    answer_profile: str | None = None
    # Positive expectation for the additive cross-project inventory facet
    # (``transversal_inventory`` answer-profile). When set, the evaluator reads
    # ``context["project_inventory"]`` (shape from
    # ``project_inventory.build_project_inventory``) and fails the case when the
    # exhaustive enumeration is absent or violates any sub-constraint:
    #   ``min_total_projects``    -> ``total_projects`` must be >= this floor
    #   ``must_include_projects`` -> every code must appear in the enumeration
    #   ``must_exclude_projects`` -> none of these codes may appear
    #   ``expected_terms``        -> facet ``terms`` must equal this list (omitted
    #                                -> no terms constraint)
    # ``None`` (the default) is a no-op, so every existing case is unaffected and
    # the facet is only contract-checked where a case opts in. This is the
    # POSITIVE counterpart to ``forbidden_route``: ``catalogue_inventory`` is a
    # dense_policy ROUTE (the old failure mode of answering from an inventory
    # summary instead of document evidence); ``project_inventory`` is an ADDITIVE
    # payload facet that does NOT change the route — so a case keeps both.
    expected_inventory: Mapping[str, Any] | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RetrievalGoldenCase":
        history = payload.get("conversation_history")
        return cls(
            id=str(payload["id"]),
            query=str(payload["query"]),
            collection=str(payload.get("collection") or "documents"),
            expected_sources=tuple(str(item) for item in payload.get("expected_sources") or ()),
            expected_evidence_terms=tuple(str(item) for item in payload.get("expected_evidence_terms") or ()),
            expected_intent=str(payload.get("expected_intent") or "content_search"),
            forbidden_route=str(payload.get("forbidden_route") or "") or None,
            latency_profile=str(payload.get("latency_profile") or "fast"),
            min_expected_sources=max(1, int(payload.get("min_expected_sources") or 1)),
            language=str(payload.get("language") or "fr"),
            retrieval_filters=dict(payload["retrieval_filters"])
            if isinstance(payload.get("retrieval_filters"), Mapping)
            else None,
            conversation_history=tuple(
                dict(item) for item in payload.get("conversation_history") or () if isinstance(item, Mapping)
            ),
            expected_diagnostics=dict(payload["expected_diagnostics"])
            if isinstance(payload.get("expected_diagnostics"), Mapping)
            else None,
            forbidden_sources=tuple(str(item) for item in payload.get("forbidden_sources") or ()),
            expected_distinct_documents=max(0, int(payload.get("expected_distinct_documents") or 0)),
            expected_distinct_content=max(0, int(payload.get("expected_distinct_content") or 0)),
            expected_prompt_type=str(payload["expected_prompt_type"])
            if payload.get("expected_prompt_type")
            else None,
            acceptable_prompt_types=tuple(
                str(item) for item in payload.get("acceptable_prompt_types") or ()
            ),
            prompt_type_ambiguous=bool(payload.get("prompt_type_ambiguous") or False),
            requires_coherence=bool(payload.get("requires_coherence") or False),
            answer_profile=str(payload["answer_profile"]) if payload.get("answer_profile") else None,
            expected_inventory=_parse_expected_inventory(payload.get("expected_inventory")),
        )

    def to_request(self) -> dict[str, Any]:
        request: dict[str, Any] = {
            "query": self.query,
            "context_collection": self.collection,
            "latency_profile": self.latency_profile,
        }
        if self.retrieval_filters:
            request["retrieval_filters"] = dict(self.retrieval_filters)
        if self.conversation_history:
            request["context"] = {
                "conversation_history": [dict(item) for item in self.conversation_history]
            }
        if self.answer_profile:
            # Forwarded so the live runner arms the additive inventory facet for
            # transversal_inventory cases; harness-only, no serving-path effect.
            request["answer_profile"] = self.answer_profile
        return request


def load_retrieval_golden_cases(path: str | Path | None = None) -> list[RetrievalGoldenCase]:
    target = Path(path) if path else DEFAULT_GOLDEN_BATCH
    data = json.loads(target.read_text(encoding="utf-8"))
    raw_cases = data.get("cases") if isinstance(data, Mapping) else data
    if not isinstance(raw_cases, list):
        raise ValueError(f"Golden retrieval batch {target} must contain a cases[] list")
    return [RetrievalGoldenCase.from_mapping(item) for item in raw_cases if isinstance(item, Mapping)]


def _normalise(value: Any) -> str:
    return " ".join(str(value or "").lower().replace("_", " ").replace("-", " ").split())


def _source_label(meta: Mapping[str, Any]) -> str:
    for key in ("document_filename", "filename", "source", "source_name", "title", "document_id"):
        value = meta.get(key)
        if value:
            return str(value)
    return ""


def _selected_source_labels(context: Mapping[str, Any], *, top_n: int = 5) -> list[str]:
    trace = context.get("retrieval_trace")
    if isinstance(trace, Mapping):
        selected = trace.get("selected_sources")
        if isinstance(selected, list):
            labels: list[str] = []
            for item in selected[:top_n]:
                if not isinstance(item, Mapping):
                    continue
                label = item.get("document_filename") or item.get("source") or item.get("document_id")
                if label:
                    labels.append(str(label))
            if labels:
                return labels

    labels = []
    for meta in (context.get("metadatas") or [])[:top_n]:
        if isinstance(meta, Mapping):
            label = _source_label(meta)
            if label:
                labels.append(label)
    return labels


def _context_text(context: Mapping[str, Any], *, top_n: int = 24) -> str:
    parts: list[str] = []
    for chunk in (context.get("chunks") or [])[:top_n]:
        parts.append(str(chunk or ""))
    for meta in (context.get("metadatas") or [])[:top_n]:
        if isinstance(meta, Mapping):
            parts.append(" ".join(str(value or "") for value in meta.values()))
    return _normalise(" ".join(parts))


def _distinct_document_count(context: Mapping[str, Any], *, top_n: int) -> int:
    """Distinct documents among the raw top-k chunk metadatas.

    Intentionally NOT based on retrieval_trace.selected_sources (already
    deduplicated per document): diversity must be measured on the chunks the
    generator actually receives.
    """
    documents: set[str] = set()
    for meta in (context.get("metadatas") or [])[:top_n]:
        if isinstance(meta, Mapping):
            label = _normalise(_source_label(meta))
            if label:
                documents.add(label)
    return len(documents)


def _content_key(meta: Mapping[str, Any]) -> str:
    """Content identity of a chunk, independent of which project owns the copy.

    The Andritz corpus indexes the same manual under many projects, prefixing
    the filename with the project/archive path that owns the copy:

        A__ACJ200__V.5.Vacuum set__CBI-GVC1C2C3__g150-operating-instructions-0312-en.pdf
        H__HYD100__HYD100__fichiers__…__MasterDrive_motioncontrole de.pdf

    The basename after the last ``__`` / ``/`` separator is stable across all
    copies (verified on the live collection: ``g150-operating-instructions-0312
    -en.pdf`` is identical across its 13 project copies). Grouping on it makes
    per-project duplicates collapse to one content document, so the count moves
    only when retrieval surfaces genuinely different manuals.

    ``content_sha256`` was evaluated as the key but is populated on only a
    fraction of chunks in the live payloads, so it is used as a last-resort
    tiebreaker rather than the primary signal. ``legacy_document_name`` carries
    the same basename and backs up a missing ``document_filename``.
    """
    for key in ("document_filename", "filename", "legacy_document_name", "inner_document_path", "source_path"):
        raw = meta.get(key)
        if raw:
            basename = str(raw).split("__")[-1].split("/")[-1]
            normalised = _normalise(basename)
            if normalised:
                return normalised
    sha = meta.get("content_sha256")
    if sha:
        return f"sha:{sha}"
    return _normalise(_source_label(meta))


def _distinct_content_count(context: Mapping[str, Any], *, top_n: int) -> int:
    """Distinct CONTENT documents among the raw top-k chunk metadatas.

    Same contract as ``_distinct_document_count`` but keyed on ``_content_key``
    so per-project copies of one manual collapse to a single content document.
    """
    contents: set[str] = set()
    for meta in (context.get("metadatas") or [])[:top_n]:
        if isinstance(meta, Mapping):
            key = _content_key(meta)
            if key:
                contents.add(key)
    return len(contents)


def _evaluate_inventory_expectation(
    expectation: Mapping[str, Any], context: Mapping[str, Any]
) -> dict[str, Any]:
    """Score the additive project-inventory facet against a positive expectation.

    Reads ``context["project_inventory"]`` (the payload ``rag.context`` attaches
    for transversal_inventory questions, shape from
    ``project_inventory.build_project_inventory``). A missing facet is itself a
    shortfall: opting into ``expected_inventory`` asserts the exhaustive
    enumeration is present AND satisfies every sub-constraint.
    """
    inventory = context.get("project_inventory")
    present = isinstance(inventory, Mapping) and bool(inventory)
    total: int | None = None
    project_codes: set[str] = set()
    terms: list[str] = []
    if present:
        try:
            total = int(inventory.get("total_projects"))
        except (TypeError, ValueError):
            total = None
        for entry in inventory.get("projects") or []:
            if isinstance(entry, Mapping):
                code = str(entry.get("project_code") or "").strip().upper()
                if code:
                    project_codes.add(code)
        terms = [str(term) for term in inventory.get("terms") or []]

    min_total = int(expectation.get("min_total_projects") or 0)
    must_include = list(expectation.get("must_include_projects") or ())
    must_exclude = list(expectation.get("must_exclude_projects") or ())
    expected_terms = expectation.get("expected_terms")

    missing_projects = [code for code in must_include if code not in project_codes]
    forbidden_projects = [code for code in must_exclude if code in project_codes]
    total_shortfall = min_total > 0 and (total is None or total < min_total)
    terms_mismatch = expected_terms is not None and list(expected_terms) != terms

    shortfall = (
        not present
        or total_shortfall
        or bool(missing_projects)
        or bool(forbidden_projects)
        or terms_mismatch
    )
    return {
        "present": present,
        "total_projects": total,
        "min_total_projects": min_total,
        "total_shortfall": total_shortfall,
        "missing_projects": missing_projects,
        "forbidden_projects": forbidden_projects,
        "terms": terms,
        "expected_terms": list(expected_terms) if expected_terms is not None else None,
        "terms_mismatch": terms_mismatch,
        "shortfall": shortfall,
    }


def evaluate_retrieval_golden_case(
    case: RetrievalGoldenCase,
    context: Mapping[str, Any],
    *,
    top_n: int = 5,
) -> dict[str, Any]:
    labels = _selected_source_labels(context, top_n=top_n)
    labels_text = _normalise(" ".join(labels))
    expected_sources = list(case.expected_sources)
    matched_sources = [
        source
        for source in expected_sources
        if _normalise(source) and _normalise(source) in labels_text
    ]
    context_text = _context_text(context)
    missing_evidence_terms = [
        term
        for term in case.expected_evidence_terms
        if _normalise(term) and _normalise(term) not in context_text
    ]
    metrics = context.get("metrics") if isinstance(context.get("metrics"), Mapping) else {}
    retrieval_decision_trace = context.get("retrieval_decision_trace")
    if not isinstance(retrieval_decision_trace, Mapping):
        retrieval_decision_trace = metrics.get("retrieval_decision_trace")
    dense_policy = str(metrics.get("dense_policy") or context.get("dense_policy") or "")
    forbidden_route_hit = bool(case.forbidden_route and case.forbidden_route in dense_policy)
    forbidden_source_hits = [
        source
        for source in case.forbidden_sources
        if _normalise(source) and _normalise(source) in labels_text
    ]
    diagnostic_mismatches: dict[str, Any] = {}
    if case.expected_diagnostics:
        for key, expected_value in case.expected_diagnostics.items():
            actual = metrics.get(key, context.get(key))
            if str(actual) != str(expected_value):
                diagnostic_mismatches[key] = {"expected": expected_value, "actual": actual}
    distinct_documents = _distinct_document_count(context, top_n=max(top_n, 8))
    diversity_shortfall = (
        case.expected_distinct_documents > 0
        and distinct_documents < case.expected_distinct_documents
    )
    distinct_content = _distinct_content_count(context, top_n=max(top_n, 8))
    content_diversity_shortfall = (
        case.expected_distinct_content > 0
        and distinct_content < case.expected_distinct_content
    )
    inventory_report = None
    inventory_shortfall = False
    if case.expected_inventory:
        inventory_report = _evaluate_inventory_expectation(case.expected_inventory, context)
        inventory_shortfall = bool(inventory_report["shortfall"])
    passed = (
        len(matched_sources) >= min(case.min_expected_sources, max(len(expected_sources), 1))
        and not missing_evidence_terms
        and not forbidden_route_hit
        and not forbidden_source_hits
        and not diagnostic_mismatches
        and not diversity_shortfall
        and not content_diversity_shortfall
        and not inventory_shortfall
    )
    return {
        "id": case.id,
        "language": case.language,
        "passed": passed,
        "matched_sources": matched_sources,
        "selected_sources": labels,
        "missing_sources": [source for source in expected_sources if source not in matched_sources],
        "missing_evidence_terms": missing_evidence_terms,
        "forbidden_route_hit": forbidden_route_hit,
        "forbidden_source_hits": forbidden_source_hits,
        "diagnostic_mismatches": diagnostic_mismatches,
        "distinct_documents": distinct_documents,
        "diversity_shortfall": diversity_shortfall,
        "distinct_content": distinct_content,
        "content_diversity_shortfall": content_diversity_shortfall,
        "inventory_shortfall": inventory_shortfall,
        "inventory_report": inventory_report,
        "dense_policy": dense_policy or None,
        "retrieval_decision_trace": dict(retrieval_decision_trace)
        if isinstance(retrieval_decision_trace, Mapping)
        else None,
    }


def _accept_set(case: RetrievalGoldenCase) -> set[str]:
    """Labels that count as correct for the classifier eval."""
    accepted = {label for label in case.acceptable_prompt_types if label}
    if case.expected_prompt_type:
        accepted.add(case.expected_prompt_type)
    return accepted


def evaluate_prompt_type_case(case: RetrievalGoldenCase) -> dict[str, Any] | None:
    """Score the FAST (patterns-only) prompt classifier against a golden case.

    Offline and zero-cost: no Qdrant, no LLM, no embeddings. The classifier
    runs after retrieval in production, so this is the only place its choice is
    measured against ground truth. Returns ``None`` for cases that carry no
    prompt-type annotation (the field is optional across batches).

    A case is ``correct`` when the selected type is in the accepted set
    (``expected_prompt_type`` plus ``acceptable_prompt_types``). Ambiguous
    cases (``prompt_type_ambiguous``) are evaluated but flagged so the runner
    can keep them out of strict accuracy.
    """
    from app.services.system_prompts.classifier import classify_prompt_type_fast

    accepted = _accept_set(case)
    if not accepted and not case.prompt_type_ambiguous:
        return None
    decision = classify_prompt_type_fast(case.query)
    predicted = decision.prompt_type.value
    top_posterior = max(decision.posteriors, key=decision.posteriors.get) if decision.posteriors else None
    return {
        "id": case.id,
        "language": case.language,
        "query": case.query,
        "expected_prompt_type": case.expected_prompt_type,
        "acceptable_prompt_types": list(case.acceptable_prompt_types),
        "ambiguous": case.prompt_type_ambiguous,
        "predicted": predicted,
        "top_posterior": top_posterior,
        "fallback_applied": decision.fallback_applied,
        "confidence": decision.confidence,
        "correct": predicted in accepted if accepted else None,
    }


async def evaluate_prompt_type_case_full(
    case: RetrievalGoldenCase,
    *,
    latency_profile: str = "balanced",
) -> dict[str, Any] | None:
    """Same as ``evaluate_prompt_type_case`` but via the full classifier.

    Adds the embedding-coherence signal, so it requires a reachable embedder
    (not offline). Used by the runner's optional ``--full`` pass for cases
    marked ``requires_coherence``.
    """
    from app.services.system_prompts.classifier import classify_prompt_type

    accepted = _accept_set(case)
    if not accepted and not case.prompt_type_ambiguous:
        return None
    decision = await classify_prompt_type(case.query, latency_profile=latency_profile)
    predicted = decision.prompt_type.value
    return {
        "id": case.id,
        "language": case.language,
        "query": case.query,
        "expected_prompt_type": case.expected_prompt_type,
        "acceptable_prompt_types": list(case.acceptable_prompt_types),
        "ambiguous": case.prompt_type_ambiguous,
        "predicted": predicted,
        "method": decision.method,
        "fallback_applied": decision.fallback_applied,
        "confidence": decision.confidence,
        "correct": predicted in accepted if accepted else None,
    }
