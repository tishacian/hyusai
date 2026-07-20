"""Canonical Andritz project-reference parsing.

Project identifiers are source-aware.  Historical SPL references are compact
alpha-numeric tokens (for example ``BAO100`` or ``ELM001Y``), while the
Needlepunch deposit uses five-digit identifiers whose meaning comes from the
deposit directory structure.  A bare five-digit number is deliberately not a
project reference during ingestion.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Any

NEEDLEPUNCH_DEPOSIT_PREFIX = "Notices_Techniques_Needlepunch"

# Kept public so metadata helpers that look for a *second* machine reference
# can share the exact legacy grammar without defining a competing regex.
LEGACY_PROJECT_REFERENCE_RE = re.compile(
    r"(?<![A-Z0-9])([A-Z]{3})[\s_-]?(\d{2,4})([A-Z]{0,2})(?![A-Z0-9])",
    re.IGNORECASE,
)

_NEEDLEPUNCH_RANGE_RE = re.compile(r"^(\d{5})-(\d{5})$")
# The SFTP folder name is ``<five digit project code><label>``.  Most folders
# separate both parts with whitespace/punctuation, but the historical tree also
# contains canonical names such as ``61001CdFreudenberg...``.  The negative
# lookahead is the important boundary: accepting a missing separator must never
# turn the first five digits of a six-digit number into a project code.  A
# concatenated label must start with a Unicode letter; a separated label must
# start with an alphanumeric character after its separators.
_NEEDLEPUNCH_PROJECT_FOLDER_RE = re.compile(
    r"^(\d{5})(?!\d)(?:[\s_.-]+[^\W_].*|[^\W\d_].*)$"
)
_NUMERIC_PROJECT_RE = re.compile(r"(?<![A-Z0-9])(\d{5})(?![A-Z0-9])", re.IGNORECASE)

_STRONG_QUERY_WORD_RE = re.compile(
    r"\b(?:"
    r"projet|projets|project|projects|"
    r"resume|resumer|resumes|summary|summarise|summarize|synthese|"
    r"compare|comparer|comparaison|comparison|"
    r"inventaire|inventory"
    r")\b",
    re.IGNORECASE,
)
_COMPARISON_QUERY_RE = re.compile(
    r"\b(?:compare|comparer|comparaison|comparison|versus|vs\.?|entre|between)\b",
    re.IGNORECASE,
)
_MEASUREMENT_AFTER_RE = re.compile(
    r"^\s*(?:rpm|tr(?:s)?\s*/\s*min|mm|cm|kg|hz|khz|kw|mw|bar|bars|v|volts?|°\s*c)\b",
    re.IGNORECASE,
)


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in text if not unicodedata.combining(char))


def _looks_like_needlepunch_path(value: str | None) -> bool:
    """Whether a value claims to belong to the Needlepunch deposit.

    Detection is intentionally broader than validation.  A path containing the
    deposit marker with a wrong root, separator or casing must fail closed; it
    must never fall through to the permissive historical SPL grammar.
    """

    return NEEDLEPUNCH_DEPOSIT_PREFIX.casefold() in str(value or "").casefold()


def _needlepunch_reference(value: str | None) -> tuple[bool, dict[str, str]]:
    """Return ``(is_needlepunch_path, metadata)`` for one structural path.

    Once the Needlepunch prefix is present the parser is fail-closed: only the
    two immediate structural segments are considered.  Numbers found in a
    filename or a deeper part directory are never promoted to ``project_code``.
    """

    raw = str(value or "")
    if not _looks_like_needlepunch_path(raw):
        return False, {}

    # Deposit paths are stored as canonical relative POSIX paths.  Do not
    # normalise hostile or ambiguous input: accepting a backslash, empty/dot
    # segment, absolute/nested root or repeated marker would let structurally
    # unrelated numbers acquire a project identity.
    if raw != raw.strip() or "\\" in raw:
        return True, {}
    parts = raw.split("/")
    if (
        len(parts) < 4
        or any(part in {"", ".", ".."} for part in parts)
        or parts[0] != NEEDLEPUNCH_DEPOSIT_PREFIX
        or sum(
            part.casefold() == NEEDLEPUNCH_DEPOSIT_PREFIX.casefold() for part in parts
        )
        != 1
    ):
        return True, {}

    range_folder = parts[1]
    project_folder = parts[2]
    range_match = _NEEDLEPUNCH_RANGE_RE.fullmatch(range_folder)
    project_match = _NEEDLEPUNCH_PROJECT_FOLDER_RE.fullmatch(project_folder)
    if not range_match or not project_match:
        return True, {}
    lower_text, upper_text = range_match.groups()
    project_code = project_match.group(1)
    lower, upper, project = int(lower_text), int(upper_text), int(project_code)
    if lower > upper or not lower <= project <= upper:
        return True, {}
    return True, {
        "project_code": project_code,
        "project_reference_kind": "andritz_project",
        "project_code_scheme": "needlepunch_numeric5",
        "business_scope": "needlepunch",
        "project_range": f"{lower_text}-{upper_text}",
        "project_folder": project_folder,
    }


def derive_project_reference(*values: str | None) -> dict[str, str]:
    """Derive canonical project metadata from trusted source values.

    Needlepunch paths take precedence and fail closed.  If no value declares a
    Needlepunch source, the long-standing alpha-numeric grammar is preserved.
    """

    needlepunch_references: list[dict[str, str]] = []
    for value in values:
        is_needlepunch, reference = _needlepunch_reference(value)
        if not is_needlepunch:
            continue
        if not reference:
            return {}
        needlepunch_references.append(reference)
    if needlepunch_references:
        first = needlepunch_references[0]
        if any(reference != first for reference in needlepunch_references[1:]):
            return {}
        return first

    for value in values:
        match = LEGACY_PROJECT_REFERENCE_RE.search(str(value or ""))
        if not match:
            continue
        buyer = match.group(1).upper()
        position = match.group(2)
        suffix = (match.group(3) or "").upper()
        return {
            "project_code": f"{buyer}{position}{suffix}",
            "initial_buyer_code": buyer,
            "project_position": position,
            "project_reference_kind": "andritz_project",
        }
    return {}


def _normalise_known_codes(known_codes: Iterable[str] | None) -> set[str]:
    if known_codes is None:
        return set()
    if isinstance(known_codes, str):
        values: Iterable[str] = (known_codes,)
    else:
        values = known_codes
    return {str(value or "").strip().upper() for value in values if str(value or "").strip()}


def _numeric_has_strong_context(text: str, match: re.Match[str]) -> bool:
    # Explicit project labels are deliberately allowed a little punctuation,
    # but not arbitrary prose, between the label and identifier.
    before = text[max(0, match.start() - 64) : match.start()]
    after = text[match.end() : match.end() + 64]
    if re.search(r"\b(?:projet|project)\s*(?:n[°o.]?\s*)?[:#_-]?\s*$", before, re.IGNORECASE):
        return True
    if re.match(r"^\s*[-_:]?\s*(?:projet|project)\b", after, re.IGNORECASE):
        return True

    # Summary/inventory commands usually precede the identifier.  Limiting the
    # window to the current short phrase avoids interpreting unrelated numbers
    # elsewhere in a long question as projects.
    phrase_before = re.split(r"[.;!?\n]", before)[-1]
    if _STRONG_QUERY_WORD_RE.search(_fold(phrase_before)):
        return True

    # A comparison can legitimately introduce more than one project code.
    # Measurement suffixes were rejected above, so both sides remain safe.
    clause_before = re.split(r"[.;!?\n]", before)[-1]
    clause_after = re.split(r"[.;!?\n]", after)[0]
    clause = f"{clause_before} {clause_after}"
    return bool(_COMPARISON_QUERY_RE.search(_fold(clause)))


def _numeric_project_matches(text: str) -> list[re.Match[str]]:
    """Return standalone numeric5 candidates after measurement rejection.

    Candidates are deliberately not project references yet. Callers must still
    require either strong query grammar or an exact authoritative collection
    match before using them as a project scope.
    """

    query = str(text or "")
    return [
        match
        for match in _NUMERIC_PROJECT_RE.finditer(query)
        if not _MEASUREMENT_AFTER_RE.match(query[match.end() : match.end() + 24])
    ]


def numeric_project_candidates(text: str) -> tuple[str, ...]:
    """Return unvalidated standalone numeric5 tokens in source order."""

    return tuple(
        dict.fromkeys(match.group(1) for match in _numeric_project_matches(str(text or "")))
    )[:8]


def extract_query_project_codes(
    text: str,
    known_codes: Iterable[str] | None = None,
) -> list[str]:
    """Extract canonical project codes from a user query, in source order.

    Legacy references retain their existing permissive token grammar.  A
    numeric Needlepunch code must either be an exact member of ``known_codes``
    (the authoritative collection facet) or appear in strong project-oriented
    language.  Embedded numbers and obvious measurements are rejected.
    """

    query = str(text or "")
    known = _normalise_known_codes(known_codes)
    candidates: list[tuple[int, str]] = []
    for match in LEGACY_PROJECT_REFERENCE_RE.finditer(query):
        candidates.append(
            (
                match.start(),
                f"{match.group(1).upper()}{match.group(2)}{(match.group(3) or '').upper()}",
            )
        )
    for match in _numeric_project_matches(query):
        code = match.group(1)
        if code in known or _numeric_has_strong_context(query, match):
            candidates.append((match.start(), code))

    codes: list[str] = []
    for _, code in sorted(candidates, key=lambda item: item[0]):
        if code not in codes:
            codes.append(code)
    return codes[:8]


def project_reference_terms(
    text: str,
    known_codes: Iterable[str] | None = None,
) -> tuple[str, ...]:
    """Tuple form used by retrieval policy and ranking consumers."""

    return tuple(extract_query_project_codes(text, known_codes=known_codes))


__all__ = [
    "LEGACY_PROJECT_REFERENCE_RE",
    "NEEDLEPUNCH_DEPOSIT_PREFIX",
    "derive_project_reference",
    "extract_query_project_codes",
    "numeric_project_candidates",
    "project_reference_terms",
]
