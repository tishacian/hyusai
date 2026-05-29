"""KnowledgeGuide-driven query planning and retrieval policy.

The policy is deliberately workspace data, not code. KnowledgeGuides may carry
an optional fenced JSON block named ``agentium-retrieval-policy``. Retrieval
uses it to add query variants, boost exact domain terms, demote low-value
navigation pages, and surface clarification hints.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


_POLICY_FENCE_RE = re.compile(
    r"```(?:agentium[-_:]retrieval[-_]policy|retrieval[-_]policy)\s*(.*?)```",
    re.IGNORECASE | re.DOTALL,
)
_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9_.-]+")
_PROJECT_REF_RE = re.compile(r"\b([A-Z]{3})[\s_-]?(\d{3})\b", re.IGNORECASE)
_DEFAULT_NAVIGATION_TERMS = (
    "table of contents",
    "contents",
    "index",
    "sommaire",
    "table des matieres",
    "table des matières",
    "navigation",
    "previous",
    "next",
    "home",
    "back",
    "menu",
)


@dataclass(frozen=True)
class PolicyFacet:
    key: str
    label: str
    terms: tuple[str, ...] = ()
    clarify_when_broad: bool = False
    clarification_prompt: str | None = None


@dataclass(frozen=True)
class SourceFamilyRule:
    when_terms: tuple[str, ...] = ()
    source_families: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalPolicy:
    protected_terms: tuple[str, ...] = ()
    aliases: tuple[tuple[str, tuple[str, ...]], ...] = ()
    facets: tuple[PolicyFacet, ...] = ()
    source_family_rules: tuple[SourceFamilyRule, ...] = ()
    require_project_code_match: bool = False
    demote_navigation: bool = True
    navigation_terms: tuple[str, ...] = _DEFAULT_NAVIGATION_TERMS
    answer_instructions: tuple[str, ...] = ()
    raw_blocks: tuple[dict[str, Any], ...] = ()

    @property
    def enabled(self) -> bool:
        return bool(
            self.protected_terms
            or self.aliases
            or self.facets
            or self.source_family_rules
            or self.require_project_code_match
            or self.answer_instructions
        )


def _clean_text(value: Any, *, max_len: int = 120) -> str:
    return " ".join(str(value or "").strip().split())[:max_len]


def _clean_terms(value: Any, *, max_items: int = 80) -> tuple[str, ...]:
    raw = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []
    out: list[str] = []
    for item in raw:
        term = _clean_text(item)
        if term and term not in out:
            out.append(term)
        if len(out) >= max_items:
            break
    return tuple(out)


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _parse_policy_blocks(markdown: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for match in _POLICY_FENCE_RE.finditer(markdown or ""):
        body = match.group(1).strip()
        if not body:
            continue
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, Mapping):
            blocks.append(dict(parsed))
    return blocks


def _parse_aliases(raw: Any) -> tuple[tuple[str, tuple[str, ...]], ...]:
    aliases: list[tuple[str, tuple[str, ...]]] = []
    if isinstance(raw, Mapping):
        items = raw.items()
    elif isinstance(raw, list):
        items = []
        for item in raw:
            data = _as_mapping(item)
            term = data.get("term") or data.get("source") or data.get("key")
            variants = data.get("variants") or data.get("aliases") or data.get("expansions")
            items.append((term, variants))
    else:
        items = []

    seen: set[str] = set()
    for term_raw, variants_raw in items:
        term = _clean_text(term_raw)
        variants = _clean_terms(variants_raw, max_items=20)
        key = term.lower()
        if not term or not variants or key in seen:
            continue
        seen.add(key)
        aliases.append((term, variants))
    return tuple(aliases)


def _parse_facets(raw: Any) -> tuple[PolicyFacet, ...]:
    facets: list[PolicyFacet] = []
    for item in raw if isinstance(raw, list) else []:
        data = _as_mapping(item)
        key = _clean_text(data.get("key"), max_len=80)
        if not key:
            continue
        facets.append(
            PolicyFacet(
                key=key,
                label=_clean_text(data.get("label") or key, max_len=120),
                terms=_clean_terms(data.get("terms"), max_items=60),
                clarify_when_broad=bool(data.get("clarify_when_broad")),
                clarification_prompt=_clean_text(data.get("clarification_prompt"), max_len=240) or None,
            )
        )
    return tuple(facets)


def _parse_source_family_rules(raw: Any) -> tuple[SourceFamilyRule, ...]:
    rules: list[SourceFamilyRule] = []
    for item in raw if isinstance(raw, list) else []:
        data = _as_mapping(item)
        when_terms = _clean_terms(data.get("when_terms") or data.get("when"), max_items=40)
        source_families = _clean_terms(data.get("source_families") or data.get("families"), max_items=20)
        if when_terms and source_families:
            rules.append(SourceFamilyRule(when_terms=when_terms, source_families=source_families))
    return tuple(rules)


def retrieval_policy_from_guides(guides: list[Any]) -> RetrievalPolicy:
    protected_terms: list[str] = []
    aliases: list[tuple[str, tuple[str, ...]]] = []
    facets: list[PolicyFacet] = []
    source_family_rules: list[SourceFamilyRule] = []
    answer_instructions: list[str] = []
    navigation_terms: list[str] = list(_DEFAULT_NAVIGATION_TERMS)
    require_project_code_match = False
    demote_navigation = True
    raw_blocks: list[dict[str, Any]] = []

    for guide in guides[:8]:
        for block in _parse_policy_blocks(str(getattr(guide, "markdown", "") or "")):
            raw_blocks.append(block)
            query_planning = _as_mapping(block.get("query_planning"))
            source_quality = _as_mapping(block.get("source_quality"))
            answer_policy = _as_mapping(block.get("answer_policy"))

            for term in _clean_terms(query_planning.get("protected_terms")):
                if term not in protected_terms:
                    protected_terms.append(term)
            for alias in _parse_aliases(query_planning.get("aliases")):
                if alias[0].lower() not in {existing[0].lower() for existing in aliases}:
                    aliases.append(alias)
            facets.extend(_parse_facets(query_planning.get("facets")))
            if "require_project_code_match" in query_planning:
                require_project_code_match = bool(query_planning.get("require_project_code_match"))
            source_family_rules.extend(_parse_source_family_rules(source_quality.get("prefer_source_families")))
            if "demote_navigation" in source_quality:
                demote_navigation = bool(source_quality.get("demote_navigation"))
            for term in _clean_terms(source_quality.get("navigation_terms"), max_items=40):
                if term.lower() not in {existing.lower() for existing in navigation_terms}:
                    navigation_terms.append(term)
            for instruction in _clean_terms(answer_policy.get("instructions"), max_items=20):
                if instruction not in answer_instructions:
                    answer_instructions.append(instruction)

    return RetrievalPolicy(
        protected_terms=tuple(protected_terms),
        aliases=tuple(aliases),
        facets=tuple(facets),
        source_family_rules=tuple(source_family_rules),
        require_project_code_match=require_project_code_match,
        demote_navigation=demote_navigation,
        navigation_terms=tuple(navigation_terms),
        answer_instructions=tuple(answer_instructions),
        raw_blocks=tuple(raw_blocks),
    )


def _normalise(value: str) -> str:
    return " ".join(str(value or "").lower().replace("’", "'").split())


def _project_reference_terms(value: str) -> tuple[str, ...]:
    terms: list[str] = []
    for match in _PROJECT_REF_RE.finditer(value or ""):
        term = f"{match.group(1).upper()}{match.group(2)}"
        if term not in terms:
            terms.append(term)
    return tuple(terms)


def _term_forms(term: str) -> tuple[str, ...]:
    text = _clean_text(term)
    match = _PROJECT_REF_RE.fullmatch(text)
    if not match:
        return (text,) if text else ()
    buyer = match.group(1).upper()
    position = match.group(2)
    return (
        f"{buyer}{position}",
        f"{buyer} {position}",
        f"{buyer}-{position}",
        f"{buyer}_{position}",
    )


def _contains_term(text: str, term: str) -> bool:
    norm_text = _normalise(text)
    norm_term = _normalise(term)
    if not norm_text or not norm_term:
        return False
    if len(norm_term) <= 2:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(norm_term)}(?![a-z0-9])", norm_text))
    return norm_term in norm_text


def _contains_any_term_form(text: str, term: str) -> bool:
    return any(_contains_term(text, form) for form in _term_forms(term))


def required_terms_from_query(query: str, policy: RetrievalPolicy | None) -> tuple[str, ...]:
    if not policy or not policy.enabled:
        return ()

    required: list[str] = []
    if policy.require_project_code_match:
        required.extend(_project_reference_terms(query))

    for term in policy.protected_terms:
        if _contains_any_term_form(query, term) and term not in required:
            required.append(term)
    return tuple(required)


def query_variants_from_policy(query: str, policy: RetrievalPolicy | None) -> list[str]:
    if not policy or not policy.enabled:
        return []

    variants: list[str] = []
    q = str(query or "").strip()
    if not q:
        return []

    for term in required_terms_from_query(q, policy):
        variants.extend(_term_forms(term))

    for term in policy.protected_terms:
        if _contains_any_term_form(q, term):
            variants.append(f"{q} {term}")
            variants.append(term)

    for term, expansions in policy.aliases:
        group = (term, *expansions)
        if not any(_contains_any_term_form(q, item) for item in group):
            continue
        expanded = " ".join(item for item in group if not _contains_any_term_form(q, item))
        if expanded:
            variants.append(f"{q} {expanded}")

    out: list[str] = []
    seen: set[str] = set()
    for item in variants:
        item = item.strip()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out[:12]


def _metadata_text(metadata: Mapping[str, Any]) -> str:
    fields = (
        "document_filename",
        "document_title",
        "title",
        "source_family",
        "project_code",
        "inner_document_path",
        "archive_name",
        "section_title",
    )
    return " ".join(str(metadata.get(field) or "") for field in fields)


def _is_navigation_like(content: str, metadata: Mapping[str, Any], policy: RetrievalPolicy) -> bool:
    text = _normalise(content)
    meta_text = _normalise(_metadata_text(metadata))
    if not text:
        return False
    nav_hits = sum(1 for term in policy.navigation_terms if _contains_term(text, term) or _contains_term(meta_text, term))
    if nav_hits == 0:
        return False
    href_count = text.count("href=") + text.count("http://") + text.count("https://")
    word_count = len(_TOKEN_RE.findall(text))
    # Demote content-poor navigation pages, not HTML as a format. Rich HTML
    # manual pages with procedural text should not be penalised.
    return word_count < 120 or href_count >= 8 or nav_hits >= 3


def score_result_with_policy(
    *,
    content: str,
    metadata: Mapping[str, Any] | None,
    query: str,
    policy: RetrievalPolicy | None,
) -> int:
    if not policy or not policy.enabled:
        return 0
    metadata = metadata or {}
    haystack = f"{content}\n{_metadata_text(metadata)}"
    score = 0

    required_terms = required_terms_from_query(query, policy)
    matched_required_terms = [term for term in required_terms if _contains_any_term_form(haystack, term)]
    for term in matched_required_terms:
        score += 14

    project_terms = _project_reference_terms(query) if policy.require_project_code_match else ()
    if project_terms:
        project_code = str(metadata.get("project_code") or "")
        if project_code and not any(_contains_any_term_form(project_code, term) for term in project_terms):
            score -= 16
        elif not matched_required_terms:
            score -= 10

    for term in policy.protected_terms:
        if _contains_any_term_form(query, term) and _contains_any_term_form(haystack, term):
            score += 14

    for term, expansions in policy.aliases:
        group = (term, *expansions)
        if not any(_contains_any_term_form(query, item) for item in group):
            continue
        if any(_contains_any_term_form(haystack, item) for item in group):
            score += 6

    source_family = _normalise(str(metadata.get("source_family") or ""))
    for rule in policy.source_family_rules:
        if not any(_contains_any_term_form(query, term) for term in rule.when_terms):
            continue
        if source_family and any(source_family == _normalise(family) for family in rule.source_families):
            score += 9

    if policy.demote_navigation and _is_navigation_like(content, metadata, policy):
        score -= 18
    return score


def matched_required_terms(
    *,
    content: str,
    metadata: Mapping[str, Any] | None,
    query: str,
    policy: RetrievalPolicy | None,
) -> tuple[str, ...]:
    if not policy or not policy.enabled:
        return ()
    metadata = metadata or {}
    haystack = f"{content}\n{_metadata_text(metadata)}"
    return tuple(term for term in required_terms_from_query(query, policy) if _contains_any_term_form(haystack, term))


def rerank_results_with_policy(
    results: list[dict[str, Any]],
    query: str,
    policy: RetrievalPolicy | None,
) -> list[dict[str, Any]]:
    if not policy or not policy.enabled or not results:
        return results
    ranked: list[tuple[int, float, int, dict[str, Any]]] = []
    for index, row in enumerate(results):
        metadata = _as_mapping(row.get("metadata"))
        content = str(row.get("content") or metadata.get("content") or "")
        policy_score = score_result_with_policy(
            content=content,
            metadata=metadata,
            query=query,
            policy=policy,
        )
        if policy_score:
            metadata["retrieval_policy_score"] = policy_score
            row = {**row, "metadata": metadata}
        raw_score = float(row.get("combined_score") or row.get("score") or 0.0)
        ranked.append((policy_score, raw_score, -index, row))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [row for _, _, _, row in ranked]


def rerank_aligned_with_policy(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    *,
    query: str,
    policy: RetrievalPolicy | None,
) -> tuple[list[str], list[float], list[dict[str, Any]]]:
    if not policy or not policy.enabled or not chunks:
        return chunks, scores, metadatas
    rows: list[tuple[int, float, int, str, float, dict[str, Any]]] = []
    for index, chunk in enumerate(chunks):
        metadata = dict(metadatas[index] if index < len(metadatas) else {})
        policy_score = score_result_with_policy(
            content=chunk,
            metadata=metadata,
            query=query,
            policy=policy,
        )
        if policy_score:
            metadata["retrieval_policy_score"] = policy_score
        score = float(scores[index]) if index < len(scores) else 0.0
        rows.append((policy_score, score, -index, chunk, score, metadata))
    rows.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return (
        [row[3] for row in rows],
        [row[4] for row in rows],
        [row[5] for row in rows],
    )


def filter_aligned_to_required_terms(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    *,
    query: str,
    policy: RetrievalPolicy | None,
) -> tuple[list[str], list[float], list[dict[str, Any]], dict[str, Any]]:
    required = required_terms_from_query(query, policy)
    if not policy or not policy.require_project_code_match or not required or not chunks:
        return chunks, scores, metadatas, {
            "required_terms": list(required),
            "matched_terms": [],
            "missing_terms": list(required),
            "filtered_chunks_removed": 0,
            "enforced": False,
        }

    kept_chunks: list[str] = []
    kept_scores: list[float] = []
    kept_metadatas: list[dict[str, Any]] = []
    matched_all: list[str] = []
    for index, chunk in enumerate(chunks):
        metadata = dict(metadatas[index] if index < len(metadatas) else {})
        matched = matched_required_terms(
            content=chunk,
            metadata=metadata,
            query=query,
            policy=policy,
        )
        if not matched:
            continue
        metadata["retrieval_policy_required_terms_matched"] = list(matched)
        kept_chunks.append(chunk)
        kept_scores.append(float(scores[index]) if index < len(scores) else 0.0)
        kept_metadatas.append(metadata)
        for term in matched:
            if term not in matched_all:
                matched_all.append(term)

    missing = [term for term in required if term not in matched_all]
    if not kept_chunks:
        # For exact project questions, unrelated chunks are more harmful than
        # useful: they cause the assistant to answer from another project. Keep
        # the no-match signal and let the guide/prompt explain the failure.
        return [], [], [], {
            "required_terms": list(required),
            "matched_terms": [],
            "missing_terms": list(required),
            "filtered_chunks_removed": len(chunks),
            "enforced": True,
        }

    return kept_chunks, kept_scores, kept_metadatas, {
        "required_terms": list(required),
        "matched_terms": matched_all,
        "missing_terms": missing,
        "filtered_chunks_removed": len(chunks) - len(kept_chunks),
        "enforced": True,
    }


def clarification_from_policy(query: str, policy: RetrievalPolicy | None) -> dict[str, Any] | None:
    if not policy or not policy.facets:
        return None
    word_count = len(_TOKEN_RE.findall(query or ""))
    matched: list[PolicyFacet] = []
    for facet in policy.facets:
        if any(_contains_term(query, term) for term in facet.terms):
            matched.append(facet)

    broad_matches = [facet for facet in matched if facet.clarify_when_broad and facet.clarification_prompt]
    if broad_matches and word_count <= 8:
        facet = broad_matches[0]
        return {
            "required": True,
            "reason": "broad_query_matches_configured_facet",
            "facet": facet.key,
            "question": facet.clarification_prompt,
            "matched_facets": [item.key for item in matched],
        }
    if len(matched) >= 3 and word_count <= 10:
        labels = ", ".join(facet.label for facet in matched[:4])
        return {
            "required": True,
            "reason": "query_matches_multiple_facets",
            "question": f"Votre question peut viser plusieurs angles ({labels}). Lequel voulez-vous prioriser ?",
            "matched_facets": [item.key for item in matched],
        }
    return None


def policy_prompt(policy: RetrievalPolicy | None, clarification: dict[str, Any] | None = None) -> str:
    if not policy or not policy.enabled:
        return ""
    lines: list[str] = []
    if policy.answer_instructions:
        lines.append("KnowledgeGuide retrieval policy:")
        lines.extend(f"- {instruction}" for instruction in policy.answer_instructions[:8])
    if clarification and clarification.get("required"):
        lines.append(
            "If the retrieved evidence does not clearly resolve the ambiguity, ask this clarification first: "
            f"{clarification.get('question')}"
        )
    return "\n".join(lines)
