"""KnowledgeGuide-driven query planning and retrieval policy.

The policy is deliberately workspace data, not code. KnowledgeGuides may carry
an optional fenced JSON block named ``agentium-retrieval-policy``. Retrieval
uses it to add query variants, boost exact domain terms, demote low-value
navigation pages, and surface clarification hints.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.services.rag.lexical_retrieval import (
    LexicalRetrievalConfig,
    lexical_match_details,
    merge_lexical_configs,
    parse_lexical_config,
)

logger = get_logger(__name__)

_POLICY_FENCE_RE = re.compile(
    r"```(?:agentium[-_:]retrieval[-_]policy|retrieval[-_]policy)\s*(.*?)```",
    re.IGNORECASE | re.DOTALL,
)
_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9_.-]+")
_PROJECT_REF_RE = re.compile(r"\b([A-Z]{3})[\s_-]?(\d{3})\b", re.IGNORECASE)
_DIMENSION_REF_RE = re.compile(
    r"\b(?:d|dia|diameter|diametre|diamètre)\.?\s*\d+(?:[,.]\d+)?\b",
    re.IGNORECASE,
)
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
_VALIDATED_PROVENANCE_VALUES = {
    "accepted",
    "approved",
    "certified",
    "official",
    "published",
    "ready",
    "reviewed",
    "trusted",
    "validated",
    "verified",
}
_PROVENANCE_KEYS = (
    "status",
    "review_status",
    "validation_status",
    "publication_status",
    "source_status",
    "source_quality",
    "provenance_status",
    "trust_level",
)
_EVIDENCE_STOPWORDS = {
    "a",
    "afin",
    "and",
    "as",
    "au",
    "aux",
    "avec",
    "ce",
    "ces",
    "cet",
    "cette",
    "comment",
    "dans",
    "de",
    "des",
    "dois",
    "dois-je",
    "du",
    "en",
    "est",
    "et",
    "fichier",
    "fichiers",
    "for",
    "faut",
    "il",
    "in",
    "je",
    "la",
    "le",
    "les",
    "of",
    "on",
    "ou",
    "où",
    "parle",
    "parlent",
    "pour",
    "procedure",
    "procedures",
    "procédure",
    "procédures",
    "que",
    "quel",
    "quelle",
    "quels",
    "quelles",
    "contient",
    "contain",
    "contains",
    "source",
    "sources",
    "the",
    "to",
    "trouve",
    "trouver",
    "quelle",
    "which",
}


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
    lexical_config: LexicalRetrievalConfig = field(default_factory=LexicalRetrievalConfig)
    require_project_code_match: bool = False
    # Rollout switch for workspace source policies: when True, the project-code
    # filter runs in shadow mode — it reports what it would remove without
    # touching the results (collections not yet backfilled with project_code
    # payloads must not lose evidence).
    cross_project_log_only: bool = False
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
            or self.lexical_config.document_types
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
    lexical_configs: list[LexicalRetrievalConfig] = []
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
            lexical_block = _as_mapping(block.get("lexical_retrieval"))

            for term in _clean_terms(query_planning.get("protected_terms")):
                if term not in protected_terms:
                    protected_terms.append(term)
            for alias in _parse_aliases(query_planning.get("aliases")):
                if alias[0].lower() not in {existing[0].lower() for existing in aliases}:
                    aliases.append(alias)
            facets.extend(_parse_facets(query_planning.get("facets")))
            if "require_project_code_match" in query_planning:
                require_project_code_match = bool(query_planning.get("require_project_code_match"))
            if lexical_block:
                lexical_configs.append(parse_lexical_config(lexical_block))
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
        lexical_config=merge_lexical_configs(lexical_configs) if lexical_configs else LexicalRetrievalConfig(),
        require_project_code_match=require_project_code_match,
        demote_navigation=demote_navigation,
        navigation_terms=tuple(navigation_terms),
        answer_instructions=tuple(answer_instructions),
        raw_blocks=tuple(raw_blocks),
    )


def _normalise(value: str) -> str:
    return " ".join(str(value or "").lower().replace("’", "'").split())


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


# Document-discovery intent: queries that ask *which/what* documents exist or to
# retrieve a list/source, rather than ordinary factual questions. Patterns run on
# accent-stripped, lowercased text so "indexés" == "indexes" and "quel" matches
# regardless of diacritics. Kept deliberately precise to avoid catching factual
# queries such as "comment nettoyer…" or "que vaut le label…".
_DISCOVERY_INTENT_PATTERNS = (
    # FR: "quel document", "quels documents", "quelle source", "quel ... fichier"
    re.compile(r"\bquel(?:s|le|les)?\b(?:\s+\S+){0,3}?\s+(?:documents?|sources?|fichiers?)\b"),
    # FR: "liste des documents", "liste de sources", EN-ish "liste of files"
    re.compile(r"\bliste\s+(?:des?|du|of)\s+(?:documents?|sources?|fichiers?|files?)\b"),
    # FR: "documents … indexés / indexes / indexer"
    re.compile(r"\bdocuments?\b(?:\s+\S+){0,5}?\s+index(?:e|es|er|ed)?\b"),
    # FR: "retrouve(r/z) la liste / les documents / les sources"
    re.compile(r"\bretrouve(?:r|z)?\b(?:\s+\S+){0,4}?\s+(?:liste|documents?|sources?|fichiers?)\b"),
    # EN: "which document(s)", "what document(s)"
    re.compile(r"\b(?:which|what)\s+documents?\b"),
    # EN: "list of documents / sources / files"
    re.compile(r"\blist\s+of\s+(?:documents?|sources?|files?)\b"),
    # EN: "find the … document / list / source"
    re.compile(r"\bfind\s+the\b(?:\s+\S+){0,5}?\s+(?:documents?|sources?|list)\b"),
)

# Under discovery intent only, prefer specific content families over generic
# cover/index frames, and lightly demote obvious generic cover/index pages.
_DISCOVERY_PREFERRED_FAMILIES = ("annex", "operating_manual", "maintenance")
_DISCOVERY_GENERIC_MARKERS = (
    "printable version",
    "part's manual",
    "parts manual",
    "part s manual",
)


def is_document_discovery_query(query: str) -> bool:
    """Detect "which/what documents exist / list / retrieve" style queries.

    Pure helper with no policy dependency so callers can gate ranking tweaks on
    it. Returns ``False`` for ordinary factual questions.
    """
    text = _strip_accents(_normalise(query))
    if not text:
        return False
    return any(pattern.search(text) for pattern in _DISCOVERY_INTENT_PATTERNS)


def _is_generic_cover_like(metadata: Mapping[str, Any]) -> bool:
    """Identify obvious generic cover/index pages by title/filename markers."""
    meta_text = _strip_accents(_normalise(_metadata_text(metadata)))
    if not meta_text:
        return False
    return any(marker in meta_text for marker in _DISCOVERY_GENERIC_MARKERS)


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


def _fold_evidence(value: Any) -> str:
    text = _strip_accents(str(value or "")).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _contains_evidence_form(folded_haystack: str, form: str) -> bool:
    folded = _fold_evidence(form)
    if not folded or not folded_haystack:
        return False
    if len(folded) <= 2:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(folded)}(?![a-z0-9])", folded_haystack))
    return folded in folded_haystack


def _add_evidence_group(
    groups: list[tuple[str, tuple[str, ...]]],
    seen: set[str],
    label: str,
    forms: Sequence[str],
) -> None:
    clean_label = _clean_text(label, max_len=80)
    clean_forms = tuple(form for form in _clean_terms(forms, max_items=24) if form)
    key = _fold_evidence(clean_label)
    if not clean_label or not clean_forms or not key or key in seen:
        return
    seen.add(key)
    groups.append((clean_label, clean_forms))


def _technical_token_forms(token: str) -> tuple[str, ...]:
    clean = _clean_text(token, max_len=80)
    if not clean:
        return ()
    forms = [clean]
    compact_match = re.fullmatch(r"([A-Za-zÀ-ÿ]+)(\d+(?:[,.]\d+)?)", clean)
    if compact_match:
        prefix = compact_match.group(1)
        number = compact_match.group(2)
        forms.extend(
            (
                f"{prefix} {number}",
                f"{prefix}-{number}",
                f"{prefix}_{number}",
            )
        )
    return tuple(forms)


def evidence_groups_from_query(
    query: str,
    policy: RetrievalPolicy | None = None,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Extract generic evidence groups that a strong result should cover.

    This is deliberately query-driven: no golden case ids, expected sources, or
    expected answers. KnowledgeGuide aliases enrich the groups when available;
    otherwise technical tokens and dimensions still provide a small signal.
    """
    q = str(query or "")
    if not q.strip():
        return ()

    groups: list[tuple[str, tuple[str, ...]]] = []
    seen: set[str] = set()

    for match in _DIMENSION_REF_RE.finditer(q):
        value = match.group(0)
        compact = re.sub(r"\s+", " ", value.replace(",", "."))
        numeric = re.search(r"\d+(?:[,.]\d+)?", value)
        number = numeric.group(0).replace(",", ".") if numeric else ""
        _add_evidence_group(
            groups,
            seen,
            value,
            (
                value,
                compact,
                compact.replace(".", ","),
                compact.replace(" ", ""),
                f"diameter {number}" if number else "",
                f"diametre {number}" if number else "",
            ),
        )

    for term in _project_reference_terms(q):
        _add_evidence_group(groups, seen, term, _term_forms(term))

    if policy:
        for term in policy.protected_terms:
            if _contains_any_term_form(q, term):
                forms: list[str] = list(_term_forms(term))
                for alias_term, expansions in policy.aliases:
                    alias_group = (alias_term, *expansions)
                    if any(_contains_any_term_form(term, item) or _contains_any_term_form(item, term) for item in alias_group):
                        forms.extend(alias_group)
                _add_evidence_group(groups, seen, term, tuple(forms))

        for term, expansions in policy.aliases:
            group = (term, *expansions)
            if any(_contains_any_term_form(q, item) for item in group):
                _add_evidence_group(groups, seen, term, group)

    raw_tokens = _TOKEN_RE.findall(q)
    folded_tokens: list[tuple[str, str]] = []
    for token in raw_tokens:
        folded = _fold_evidence(token)
        if not folded or folded in _EVIDENCE_STOPWORDS:
            continue
        if len(folded) < 4 and not any(ch.isdigit() for ch in folded):
            continue
        if folded.isdigit() and len(folded) < 3:
            continue
        folded_tokens.append((token, folded))
        _add_evidence_group(groups, seen, token, _technical_token_forms(token))
        if len(groups) >= 14:
            return tuple(groups)

    for index in range(len(folded_tokens) - 1):
        first_raw, first_folded = folded_tokens[index]
        second_raw, second_folded = folded_tokens[index + 1]
        if first_folded in _EVIDENCE_STOPWORDS or second_folded in _EVIDENCE_STOPWORDS:
            continue
        if not (len(first_folded) >= 4 or len(second_folded) >= 4):
            continue
        phrase = f"{first_raw} {second_raw}"
        _add_evidence_group(groups, seen, phrase, (phrase, f"{first_raw}-{second_raw}"))
        if len(groups) >= 14:
            break

    return tuple(groups)


def evidence_coverage_details(
    *,
    content: str,
    metadata: Mapping[str, Any] | None,
    query: str,
    policy: RetrievalPolicy | None = None,
) -> dict[str, Any]:
    groups = evidence_groups_from_query(query, policy)
    if not groups:
        return {
            "score": 0,
            "coverage": 0.0,
            "matched": [],
            "missing": [],
            "groups": [],
        }
    metadata = metadata or {}
    haystack = f"{content}\n{_metadata_text(metadata)}\n{metadata.get('content') or ''}"
    folded_haystack = _fold_evidence(haystack)
    matched: list[str] = []
    missing: list[str] = []
    for label, forms in groups:
        if any(_contains_evidence_form(folded_haystack, form) for form in forms):
            matched.append(label)
        else:
            missing.append(label)

    coverage = len(matched) / max(len(groups), 1)
    score = len(matched) * 5
    if len(groups) >= 2 and coverage >= 0.75:
        score += 8
    if len(groups) >= 3 and coverage >= 0.95:
        score += 6
    if len(missing) >= 3 and coverage < 0.35:
        score -= 4
    return {
        "score": score,
        "coverage": coverage,
        "matched": matched,
        "missing": missing,
        "groups": [label for label, _ in groups],
    }


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
    is_document_discovery: bool = False,
) -> int:
    metadata = metadata or {}
    haystack = f"{content}\n{_metadata_text(metadata)}"
    score = provenance_boost_score(metadata)
    lexical_details = lexical_match_details(
        content=content,
        metadata=metadata,
        query=query,
        config=policy.lexical_config if policy else None,
    )
    score += int(lexical_details.get("score") or 0)
    evidence_details = evidence_coverage_details(
        content=content,
        metadata=metadata,
        query=query,
        policy=policy,
    )
    score += int(evidence_details.get("score") or 0)

    if not policy or not policy.enabled:
        return score

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

    # Discovery-intent adjustments are fully gated behind ``is_document_discovery``
    # so non-discovery queries score byte-for-byte as before.
    discovery_preferred = is_document_discovery and source_family in _DISCOVERY_PREFERRED_FAMILIES
    if is_document_discovery:
        if discovery_preferred:
            # Surface the specific content docs (annex/operating_manual/...) the
            # query is asking to enumerate, comparable in weight to a required-
            # term match (+14) so they clear generic cover pages.
            score += 12
        elif _is_generic_cover_like(metadata):
            # Lightly demote obvious cover/index frames ("printable version",
            # "Part's Manual") without erasing a legitimate project match.
            score -= 10

    # Demote content-poor navigation pages, but never demote a preferred content
    # family under discovery intent (e.g. a content HTML page like conveyor.html),
    # otherwise the navigation rule would push it below generic index pages.
    if policy.demote_navigation and _is_navigation_like(content, metadata, policy) and not discovery_preferred:
        score -= 18
    return score


def provenance_boost_score(metadata: Mapping[str, Any] | None) -> int:
    """Small deterministic trust boost for reviewed/official sources.

    This is intentionally weaker than domain-policy boosts such as exact
    project-code matches. It is mainly a tiebreaker so validated workspace
    sources outrank generic copies when semantic scores are close.
    """
    metadata = metadata or {}
    boost = 0
    for key in _PROVENANCE_KEYS:
        value = metadata.get(key)
        values = value if isinstance(value, (list, tuple, set)) else [value]
        if any(str(item or "").strip().lower() in _VALIDATED_PROVENANCE_VALUES for item in values):
            boost += 4
            break
    source_kind = str(metadata.get("source_kind") or metadata.get("source_type") or "").strip().lower()
    source_family = str(metadata.get("source_family") or "").strip().lower()
    if source_kind in {"official", "manual", "notice", "pdf"} or source_family in {"official", "validated_source"}:
        boost += 2
    return min(boost, 6)


def is_expert_fiche_metadata(metadata: Mapping[str, Any] | None) -> bool:
    """Identify validated expert-correction fiches from their ingest metadata.

    Keyed on the markers stamped at capture/publish time (plan Volet 2):
    ``source_type == "expert_fiche"`` or ``origin == "chat_correction"``.
    """
    metadata = metadata or {}
    if str(metadata.get("source_type") or "").strip().lower() == "expert_fiche":
        return True
    return str(metadata.get("origin") or "").strip().lower() == "chat_correction"


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
    if not results:
        return results
    is_document_discovery = is_document_discovery_query(query)
    ranked: list[tuple[int, int, float, int, dict[str, Any]]] = []
    has_policy_ranking = bool(policy and policy.enabled)
    has_provenance_boost = False
    # Flag read once (cheap gating): 0 keeps the OFF path byte-for-byte identical.
    expert_fiche_boost = int(settings.rag_expert_fiche_boost) if settings.rag_expert_fiche_boost_enabled else 0
    has_expert_fiche_boost = False
    # Hard pin (flag-gated, default OFF): a validated expert fiche present among
    # the candidates is ordered ahead of regular documents regardless of score.
    # OFF keeps is_fiche=0 for every row, so the sort key is unchanged.
    pin_enabled = bool(settings.rag_expert_fiche_pin_enabled)
    has_expert_fiche_pin = False
    for index, row in enumerate(results):
        metadata = _as_mapping(row.get("metadata"))
        content = str(row.get("content") or metadata.get("content") or "")
        lexical_details = lexical_match_details(
            content=content,
            metadata=metadata,
            query=query,
            config=policy.lexical_config if policy else None,
        )
        policy_score = score_result_with_policy(
            content=content,
            metadata=metadata,
            query=query,
            policy=policy,
            is_document_discovery=is_document_discovery,
        )
        evidence_details = evidence_coverage_details(
            content=content,
            metadata=metadata,
            query=query,
            policy=policy,
        )
        has_provenance_boost = has_provenance_boost or bool(provenance_boost_score(metadata))
        if lexical_details.get("signals_detected"):
            lexical_score = int(lexical_details.get("score") or 0)
            metadata["retrieval_lexical_score"] = int(lexical_details.get("score") or 0)
            metadata["retrieval_exact_terms_matched"] = list(lexical_details.get("matched_exact_terms") or [])
            metadata["retrieval_document_types_matched"] = list(lexical_details.get("matched_document_types") or [])
            metadata["retrieval_exact_match_missing"] = bool(lexical_details.get("missing_exact_match"))
            row = {**row, "metadata": metadata}
            if lexical_score:
                has_policy_ranking = True
        if evidence_details.get("groups"):
            metadata["retrieval_evidence_terms"] = list(evidence_details.get("groups") or [])
            metadata["retrieval_evidence_terms_matched"] = list(evidence_details.get("matched") or [])
            metadata["retrieval_evidence_terms_missing"] = list(evidence_details.get("missing") or [])
            metadata["retrieval_evidence_coverage"] = float(evidence_details.get("coverage") or 0.0)
            if int(evidence_details.get("score") or 0) > 0:
                has_policy_ranking = True
        if expert_fiche_boost and is_expert_fiche_metadata(metadata):
            policy_score += expert_fiche_boost
            metadata["expert_fiche_boost_applied"] = True
            has_expert_fiche_boost = True
            row = {**row, "metadata": metadata}
        is_fiche = 0
        if pin_enabled and is_expert_fiche_metadata(metadata):
            is_fiche = 1
            metadata["expert_fiche_pinned"] = True
            has_expert_fiche_pin = True
            row = {**row, "metadata": metadata}
        if policy_score:
            metadata["retrieval_policy_score"] = policy_score
            row = {**row, "metadata": metadata}
        raw_score = float(row.get("combined_score") or row.get("score") or 0.0)
        ranked.append((is_fiche, policy_score, raw_score, -index, row))
    if (
        not has_policy_ranking
        and not has_provenance_boost
        and not has_expert_fiche_boost
        and not has_expert_fiche_pin
    ):
        return results
    if pin_enabled:
        # is_fiche leads the key so fiches pin to the top; ties keep the prior order.
        ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)
    else:
        ranked.sort(key=lambda item: (item[1], item[2], item[3]), reverse=True)
    return [row for *_, row in ranked]


def rerank_aligned_with_policy(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    *,
    query: str,
    policy: RetrievalPolicy | None,
) -> tuple[list[str], list[float], list[dict[str, Any]]]:
    if not chunks:
        return chunks, scores, metadatas
    is_document_discovery = is_document_discovery_query(query)
    rows: list[tuple[int, int, float, int, str, float, dict[str, Any]]] = []
    has_policy_ranking = bool(policy and policy.enabled)
    has_provenance_boost = False
    # Flag read once (cheap gating): 0 keeps the OFF path byte-for-byte identical.
    expert_fiche_boost = int(settings.rag_expert_fiche_boost) if settings.rag_expert_fiche_boost_enabled else 0
    has_expert_fiche_boost = False
    # Hard pin (flag-gated, default OFF): a validated expert fiche present among
    # the candidates is ordered ahead of regular documents regardless of score.
    # OFF keeps is_fiche=0 for every row, so the sort key is unchanged.
    pin_enabled = bool(settings.rag_expert_fiche_pin_enabled)
    has_expert_fiche_pin = False
    for index, chunk in enumerate(chunks):
        metadata = dict(metadatas[index] if index < len(metadatas) else {})
        lexical_details = lexical_match_details(
            content=chunk,
            metadata=metadata,
            query=query,
            config=policy.lexical_config if policy else None,
        )
        policy_score = score_result_with_policy(
            content=chunk,
            metadata=metadata,
            query=query,
            policy=policy,
            is_document_discovery=is_document_discovery,
        )
        evidence_details = evidence_coverage_details(
            content=chunk,
            metadata=metadata,
            query=query,
            policy=policy,
        )
        has_provenance_boost = has_provenance_boost or bool(provenance_boost_score(metadata))
        if lexical_details.get("signals_detected"):
            lexical_score = int(lexical_details.get("score") or 0)
            metadata["retrieval_lexical_score"] = int(lexical_details.get("score") or 0)
            metadata["retrieval_exact_terms_matched"] = list(lexical_details.get("matched_exact_terms") or [])
            metadata["retrieval_document_types_matched"] = list(lexical_details.get("matched_document_types") or [])
            metadata["retrieval_exact_match_missing"] = bool(lexical_details.get("missing_exact_match"))
            if lexical_score:
                has_policy_ranking = True
        if evidence_details.get("groups"):
            metadata["retrieval_evidence_terms"] = list(evidence_details.get("groups") or [])
            metadata["retrieval_evidence_terms_matched"] = list(evidence_details.get("matched") or [])
            metadata["retrieval_evidence_terms_missing"] = list(evidence_details.get("missing") or [])
            metadata["retrieval_evidence_coverage"] = float(evidence_details.get("coverage") or 0.0)
            if int(evidence_details.get("score") or 0) > 0:
                has_policy_ranking = True
        if expert_fiche_boost and is_expert_fiche_metadata(metadata):
            policy_score += expert_fiche_boost
            metadata["expert_fiche_boost_applied"] = True
            has_expert_fiche_boost = True
        is_fiche = 0
        if pin_enabled and is_expert_fiche_metadata(metadata):
            is_fiche = 1
            metadata["expert_fiche_pinned"] = True
            has_expert_fiche_pin = True
        if policy_score:
            metadata["retrieval_policy_score"] = policy_score
        score = float(scores[index]) if index < len(scores) else 0.0
        rows.append((is_fiche, policy_score, score, -index, chunk, score, metadata))
    if (
        not has_policy_ranking
        and not has_provenance_boost
        and not has_expert_fiche_boost
        and not has_expert_fiche_pin
    ):
        return chunks, scores, metadatas
    if pin_enabled:
        # is_fiche leads the key so fiches pin to the top; ties keep the prior order.
        rows.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)
    else:
        rows.sort(key=lambda item: (item[1], item[2], item[3]), reverse=True)
    return (
        [row[4] for row in rows],
        [row[5] for row in rows],
        [row[6] for row in rows],
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
    if policy.cross_project_log_only:
        # Shadow mode: report what enforcement would remove, change nothing.
        would_remove = len(chunks) - len(kept_chunks)
        if would_remove:
            logger.warning(
                "cross-project filter (log-only) would remove chunks",
                required_terms=list(required),
                would_remove=would_remove,
                kept=len(kept_chunks),
            )
        return chunks, scores, metadatas, {
            "required_terms": list(required),
            "matched_terms": matched_all,
            "missing_terms": missing,
            "filtered_chunks_removed": 0,
            "would_remove": would_remove,
            "enforced": False,
            "log_only": True,
        }
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
