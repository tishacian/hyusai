"""Generic lexical/exact-match helpers for Agentium retrieval.

The helpers in this module deliberately stay domain-neutral. Collection-specific
terms such as document type aliases belong in KnowledgeGuide policy blocks or
collection profiles; the default behaviour only understands generic metadata
fields and code-like identifiers.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

SPARSE_SCHEMA_VERSION = "metadata_v1"

DEFAULT_METADATA_FIELD_WEIGHTS: dict[str, int] = {
    "content": 1,
    "document_filename": 4,
    "document_title": 4,
    "title": 4,
    "project_code": 6,
    "machine": 5,
    "part_number": 6,
    "section": 3,
    "section_path": 3,
    "chapter": 3,
    "family": 3,
    "archive_name": 2,
    "source_path": 2,
    "inner_document_path": 2,
    "source": 2,
    "source_family": 3,
    "source_kind": 3,
    "document_type": 3,
    "extension": 2,
    "tags": 3,
}

DEFAULT_EXACT_IDENTIFIER_PATTERNS: tuple[str, ...] = (
    r"\b[A-Z]{2,}[A-Z0-9]*[\s_.-]?\d{2,}[A-Z0-9]*\b",
    r"\b[A-Z0-9]{2,}[-_][A-Z0-9]{2,}\b",
)

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9_.-]{2,}")
_WORD_RE = re.compile(r"[a-z0-9]{2,}")
_SEPARATOR_RE = re.compile(r"[\s_.-]+")
_CHAPTER_RE = re.compile(r"\b(?:chapter|chapitre|chap)\s*[_:./-]?\s*([0-9]{1,3}[A-Z]?)\b", re.IGNORECASE)
_SECTION_RE = re.compile(
    r"\b(?:sub[-_\s]?section|section|sect)\s*[_:./-]?\s*([IVXLCDM0-9]{1,6}[A-Z]?)\b",
    re.IGNORECASE,
)
_PART_NUMBER_RE = re.compile(
    r"\b(?:part\s*(?:no\.?|number)?|p/?n|ref(?:erence)?\.?|item)\s*[:#-]?\s*([A-Z0-9][A-Z0-9_.\-/ ]{2,32})",
    re.IGNORECASE,
)
_MACHINE_LABEL_RE = re.compile(
    r"\b(?:machine|equipment|equipement|model|type)\s*[:#-]?\s*([A-Z][A-Z0-9_-]{2,24}\d[A-Z0-9_-]*)\b",
    re.IGNORECASE,
)
_FAMILY_TERMS = (
    "spunlace",
    "jetlace",
    "non-wovens",
    "non wovens",
    "hydroentanglement",
    "filtration",
    "vacuum",
    "carding",
    "card",
)
_DEFAULT_STOPWORDS = {
    "and",
    "avec",
    "dans",
    "des",
    "document",
    "documents",
    "du",
    "for",
    "les",
    "pour",
    "the",
    "une",
}

@dataclass(frozen=True)
class LexicalRetrievalConfig:
    """Domain-neutral lexical retrieval settings.

    ``document_types`` maps a stable type key to aliases supplied by a profile or
    KnowledgeGuide. ``metadata_field_weights`` controls sparse text expansion.
    """

    document_types: dict[str, tuple[str, ...]] = field(default_factory=dict)
    exact_identifier_patterns: tuple[str, ...] = DEFAULT_EXACT_IDENTIFIER_PATTERNS
    metadata_field_weights: dict[str, int] = field(
        default_factory=lambda: dict(DEFAULT_METADATA_FIELD_WEIGHTS)
    )


@dataclass(frozen=True)
class LexicalSignals:
    exact_terms: tuple[str, ...] = ()
    identifier_variants: tuple[str, ...] = ()
    document_type_intents: tuple[str, ...] = ()
    document_type_aliases: tuple[str, ...] = ()
    metadata_terms: tuple[str, ...] = ()
    requires_exact_match: bool = False

    @property
    def detected(self) -> bool:
        return bool(self.exact_terms or self.document_type_intents or self.metadata_terms)


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


def fold_text(value: Any) -> str:
    text = str(value or "").replace("’", "'").strip().lower()
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def compact_identifier(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", fold_text(value)).upper()


def identifier_variants(value: str) -> tuple[str, ...]:
    """Return common separator variants for a code-like identifier."""

    raw = str(value or "").strip()
    compact = compact_identifier(raw)
    if not compact or not any(ch.isdigit() for ch in compact):
        return ()
    match = re.match(r"^([A-Z]+)([0-9].*)$", compact)
    base_variants = [compact]
    if match:
        prefix, suffix = match.groups()
        base_variants.extend(
            [
                f"{prefix} {suffix}",
                f"{prefix}-{suffix}",
                f"{prefix}_{suffix}",
                f"{prefix}.{suffix}",
            ]
        )
    else:
        separated = _SEPARATOR_RE.sub(" ", raw).strip()
        if separated:
            base_variants.append(separated.upper())
    out: list[str] = []
    for item in base_variants:
        if item and item not in out:
            out.append(item)
    return tuple(out)


def parse_lexical_config(raw: Any) -> LexicalRetrievalConfig:
    data = _as_mapping(raw)
    document_types: dict[str, tuple[str, ...]] = {}
    for key, value in _as_mapping(data.get("document_types")).items():
        type_key = fold_text(key).replace(" ", "_")
        aliases_raw = _as_mapping(value).get("aliases") if isinstance(value, Mapping) else value
        aliases: list[str] = []
        for alias in _as_sequence(aliases_raw):
            cleaned = " ".join(str(alias or "").split())
            if cleaned and cleaned not in aliases:
                aliases.append(cleaned)
        if type_key and aliases:
            document_types[type_key] = tuple(aliases)

    patterns: list[str] = []
    for item in _as_sequence(data.get("exact_identifier_patterns")):
        text = str(item or "").strip()
        if text:
            patterns.append(text)

    weights = dict(DEFAULT_METADATA_FIELD_WEIGHTS)
    for key, value in _as_mapping(data.get("metadata_fields")).items():
        try:
            weight = int(value)
        except (TypeError, ValueError):
            continue
        if weight > 0:
            weights[str(key)] = min(weight, 12)

    return LexicalRetrievalConfig(
        document_types=document_types,
        exact_identifier_patterns=tuple(patterns) or DEFAULT_EXACT_IDENTIFIER_PATTERNS,
        metadata_field_weights=weights,
    )


def merge_lexical_configs(configs: Sequence[LexicalRetrievalConfig]) -> LexicalRetrievalConfig:
    document_types: dict[str, tuple[str, ...]] = {}
    patterns: list[str] = []
    weights = dict(DEFAULT_METADATA_FIELD_WEIGHTS)
    for config in configs:
        for key, aliases in config.document_types.items():
            existing = list(document_types.get(key, ()))
            for alias in aliases:
                if alias not in existing:
                    existing.append(alias)
            if existing:
                document_types[key] = tuple(existing)
        for pattern in config.exact_identifier_patterns:
            if pattern not in patterns:
                patterns.append(pattern)
        weights.update(config.metadata_field_weights)
    return LexicalRetrievalConfig(
        document_types=document_types,
        exact_identifier_patterns=tuple(patterns) or DEFAULT_EXACT_IDENTIFIER_PATTERNS,
        metadata_field_weights=weights,
    )


def analyze_query(query: str, config: LexicalRetrievalConfig | None = None) -> LexicalSignals:
    config = config or LexicalRetrievalConfig()
    text = str(query or "")
    folded = fold_text(text)

    exact_terms: list[str] = []
    variants: list[str] = []
    for pattern in config.exact_identifier_patterns:
        try:
            matches = re.findall(pattern, text.upper(), flags=re.IGNORECASE)
        except re.error:
            continue
        for match in matches:
            raw = "".join(match) if isinstance(match, tuple) else str(match)
            compact = compact_identifier(raw)
            if len(compact) < 4 or compact in exact_terms:
                continue
            exact_terms.append(compact)
            for variant in identifier_variants(compact):
                if variant not in variants:
                    variants.append(variant)

    type_intents: list[str] = []
    type_aliases: list[str] = []
    for key, aliases in config.document_types.items():
        alias_group = (key.replace("_", " "), *aliases)
        if any(fold_text(alias) in folded for alias in alias_group if alias):
            type_intents.append(key)
            for alias in alias_group:
                if alias and alias not in type_aliases:
                    type_aliases.append(alias)

    metadata_terms: list[str] = []
    for token in _WORD_RE.findall(folded):
        if token in _DEFAULT_STOPWORDS or token in metadata_terms:
            continue
        if len(token) >= 4 or any(token in fold_text(alias) for alias in type_aliases):
            metadata_terms.append(token)
        if len(metadata_terms) >= 24:
            break

    return LexicalSignals(
        exact_terms=tuple(exact_terms),
        identifier_variants=tuple(variants),
        document_type_intents=tuple(type_intents),
        document_type_aliases=tuple(type_aliases),
        metadata_terms=tuple(metadata_terms),
        requires_exact_match=bool(exact_terms),
    )


def _string_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)] if str(value or "") else []


def metadata_search_text(payload: Mapping[str, Any], config: LexicalRetrievalConfig | None = None) -> str:
    config = config or LexicalRetrievalConfig()
    parts: list[str] = []
    for field_name, raw_weight in config.metadata_field_weights.items():
        try:
            weight = max(1, min(int(raw_weight), 12))
        except (TypeError, ValueError):
            weight = 1
        value = payload.get(field_name)
        for text in _string_values(value):
            if not text.strip():
                continue
            parts.extend([text] * weight)
            if field_name != "content":
                compact = compact_identifier(text)
                if compact and compact != fold_text(text).upper():
                    parts.append(compact)
                for token in _TOKEN_RE.findall(text):
                    parts.append(token)
                    parts.extend(identifier_variants(token))
    for aliases in config.document_types.values():
        for alias in aliases:
            if alias:
                parts.append(alias)
    return "\n".join(parts)


def _first_capture(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    value = " ".join(str(match.group(1) or "").replace("_", " ").split()).strip(" .,:;-/")
    return value or None


def _derive_family(text: str) -> str | None:
    folded = fold_text(text)
    for term in _FAMILY_TERMS:
        if fold_text(term) in folded:
            return term.replace(" ", "_")
    return None


def derived_industrial_metadata(payload: Mapping[str, Any]) -> dict[str, str]:
    """Extract generic industrial metadata hints from existing payload text.

    This intentionally stays conservative: explicit payload fields win, and
    derived values are only hints for sparse/exact retrieval, not source truth.
    """

    text = " ".join(
        str(value or "")
        for value in (
            payload.get("document_filename"),
            payload.get("document_title"),
            payload.get("title"),
            payload.get("archive_name"),
            payload.get("inner_document_path"),
            payload.get("source_path"),
            payload.get("source"),
            payload.get("section_path"),
            str(payload.get("content") or "")[:4000],
        )
    )
    search_text = f"{text} {re.sub(r'[_/.-]+', ' ', text)}"
    out: dict[str, str] = {}
    if not payload.get("chapter"):
        chapter = _first_capture(_CHAPTER_RE, search_text)
        if chapter:
            out["chapter"] = f"Chapter {chapter}"
    if not payload.get("section"):
        section = _first_capture(_SECTION_RE, search_text)
        if section:
            out["section"] = f"Section {section}"
    if not payload.get("part_number"):
        part_number = _first_capture(_PART_NUMBER_RE, search_text)
        if part_number:
            part_number = re.split(r"\.\s+(?=[A-Za-z]{3,})", part_number, maxsplit=1)[0].strip()
            out["part_number"] = part_number
    if not payload.get("machine"):
        machine = _first_capture(_MACHINE_LABEL_RE, search_text)
        if machine and compact_identifier(machine) != compact_identifier(payload.get("project_code")):
            out["machine"] = machine
    if not payload.get("family"):
        family = _derive_family(text)
        if family:
            out["family"] = family
    return out


def metadata_terms(payload: Mapping[str, Any], config: LexicalRetrievalConfig | None = None) -> tuple[str, ...]:
    config = config or LexicalRetrievalConfig()
    fields = [field for field in config.metadata_field_weights if field != "content"]
    out: list[str] = []
    for field_name in fields:
        for text in _string_values(payload.get(field_name)):
            for token in _WORD_RE.findall(fold_text(text)):
                if token not in _DEFAULT_STOPWORDS and token not in out:
                    out.append(token)
            compact = compact_identifier(text)
            if compact and compact.lower() not in out:
                out.append(compact.lower())
            for token in _TOKEN_RE.findall(text):
                for variant in identifier_variants(token):
                    lowered = fold_text(variant)
                    if lowered and lowered not in out:
                        out.append(lowered)
            if len(out) >= 160:
                return tuple(out[:160])
    return tuple(out[:160])


def metadata_identifiers(payload: Mapping[str, Any], config: LexicalRetrievalConfig | None = None) -> tuple[str, ...]:
    config = config or LexicalRetrievalConfig()
    fields = (
        "project_code",
        "machine",
        "part_number",
        "document_id",
        "archive_name",
        "document_filename",
        "document_title",
        "title",
        "source_path",
        "inner_document_path",
        "section",
        "chapter",
    )
    out: list[str] = []
    patterns = tuple(config.exact_identifier_patterns or DEFAULT_EXACT_IDENTIFIER_PATTERNS)
    for field_name in fields:
        for text in _string_values(payload.get(field_name)):
            candidates = [text]
            for pattern in patterns:
                try:
                    candidates.extend(
                        "".join(match) if isinstance(match, tuple) else str(match)
                        for match in re.findall(pattern, text.upper(), flags=re.IGNORECASE)
                    )
                except re.error:
                    continue
            for candidate in candidates:
                compact = compact_identifier(candidate)
                if len(compact) < 3:
                    continue
                for variant in (compact, *identifier_variants(compact)):
                    lowered = fold_text(variant)
                    if lowered and lowered not in out:
                        out.append(lowered)
    return tuple(out[:120])


def enrich_payload_for_lexical_sparse(
    payload: Mapping[str, Any],
    config: LexicalRetrievalConfig | None = None,
) -> dict[str, Any]:
    out = dict(payload)
    for key, value in derived_industrial_metadata(out).items():
        out.setdefault(key, value)
    out["sparse_schema_version"] = SPARSE_SCHEMA_VERSION
    out["retrieval_identifiers"] = list(metadata_identifiers(out, config))
    out["retrieval_terms"] = list(metadata_terms(out, config))
    return out


def lexical_match_details(
    *,
    content: str,
    metadata: Mapping[str, Any],
    query: str,
    config: LexicalRetrievalConfig | None = None,
) -> dict[str, Any]:
    config = config or LexicalRetrievalConfig()
    signals = analyze_query(query, config)
    haystack = fold_text(
        "\n".join(
            [
                str(content or ""),
                metadata_search_text(metadata, config),
                " ".join(_string_values(metadata.get("retrieval_identifiers"))),
                " ".join(_string_values(metadata.get("retrieval_terms"))),
            ]
        )
    )
    score = 0
    matched_exact: list[str] = []
    for term in signals.exact_terms:
        forms = [fold_text(variant) for variant in (term, *identifier_variants(term))]
        if any(form and form in haystack for form in forms):
            matched_exact.append(term)
            score += 18
    matched_types: list[str] = []
    for type_key in signals.document_type_intents:
        aliases = (type_key.replace("_", " "), *config.document_types.get(type_key, ()))
        if any(fold_text(alias) in haystack for alias in aliases if alias):
            matched_types.append(type_key)
            score += 10
    matched_terms = 0
    for term in signals.metadata_terms[:12]:
        if term and term in haystack:
            matched_terms += 1
    score += min(matched_terms, 6)

    if signals.requires_exact_match and not matched_exact:
        other_identifiers = set(_string_values(metadata.get("retrieval_identifiers")))
        if not other_identifiers:
            other_identifiers = set(metadata_identifiers(metadata, config))
        if other_identifiers:
            score -= 12

    return {
        "score": score,
        "signals_detected": signals.detected,
        "requires_exact_match": signals.requires_exact_match,
        "matched_exact_terms": matched_exact,
        "matched_document_types": matched_types,
        "matched_metadata_terms": matched_terms,
        "missing_exact_match": bool(signals.requires_exact_match and not matched_exact),
        "signals": signals,
    }
