"""Vocabulary-agnostic parser for an enumerated category in one project.

Only the request shape is deterministic: an enumeration operator, a free-form
category, and one explicit project anchor.  Equipment names, manufacturers,
models and project codes are never catalogued here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SingleProjectInventoryIntent:
    """The explicit project scope and the category written by the user."""

    project_code: str
    category: str


_PROJECT_TOKEN = r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*"
_INVENTORY_REQUEST_RE = re.compile(
    rf"""
    ^\s*
    (?:(?:please|merci\s+de|can\s+you|could\s+you)\s+)?
    (?:(?:peux-tu|pouvez-vous)\s+(?:me\s+)?)?
    (?:
        (?:quels|quelles)(?:\s+sont)?(?:\s+(?:les|des))?
        |(?:lister|listez|liste|[ée]num[ée]rer|[ée]num[ée]rez|[ée]num[èe]re)
            (?:-moi)?(?:\s+(?:moi\s+)?(?:les|des|de))?
        |(?:donne|donnez|montre|montrez)(?:-moi|\s+moi)?\s+(?:la\s+)?liste\s+(?:des?|de)?
        |inventaire(?:\s+(?:des|de|du))?
        |which(?:\s+are)?(?:\s+the)?
        |what(?:\s+are)?(?:\s+the)?
        |list(?:\s+(?:all|the|of))?
        |inventory(?:\s+of)?
        |show\s+me(?:\s+(?:all|the))?
        |give\s+me\s+(?:a|the)\s+list\s+of
    )
    \s+(?P<category>.{{1,500}}?)\s+
    (?:
        (?:du|de\s+ce|dans\s+(?:le|ce)|pour\s+(?:le|ce)|sur\s+(?:le|ce))
            \s+projet
        |(?:are\s+)?(?:for|in|of)\s+(?:the\s+)?project
    )
    \s+(?P<project_code>{_PROJECT_TOKEN})
    \s*[?!.]?\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)
_PROJECT_ANCHOR_RE = re.compile(
    rf"\b(?:projet|project)\s+(?P<project_code>{_PROJECT_TOKEN})\b",
    re.IGNORECASE,
)
_IMPLICIT_SCOPE_CONNECTOR_RE = re.compile(
    rf"\b(?:for|in|pour|dans|sur)\s+(?P<scope>{_PROJECT_TOKEN})\s+"
    rf"(?:and|et)\s+(?P<next>{_PROJECT_TOKEN})\b",
    re.IGNORECASE,
)
_LEADING_CATEGORY_DETERMINER_RE = re.compile(
    r"^(?:(?:les?|la|des?|du|the|all|of|tous|toutes|un|une|a)\s+|de\s+l['’]|l['’])+",
    re.IGNORECASE,
)

# Exact task objects are excluded without banning the same words inside a
# material category: "documents" is not equipment, while "document holders"
# remains a perfectly valid unseen category.  The same applies to "status"
# versus "status indicators" and "objective lenses".
_NON_CATEGORY_EXACT_RE = re.compile(
    r"^(?:"
    r"projets?|projects?|dossiers?|documents?|docs?|documentation|manuals?|sources?|"
    r"fichiers?|files?|collections?|corpus|"
    r"knowledge\s+base(?:\s+(?:sources?|documents?|files?))?|"
    r"base\s+de\s+connaissances(?:\s+(?:sources?|documents?|fichiers?))?|"
    r"objectifs?|objectives?|goals?|risques?|risks?|hazards?|enjeux|aims?|"
    r"statuts?|status|states?|condition|[ée]tats?|avancement|progress"
    r")$",
    re.IGNORECASE,
)
_NON_ENUMERATED_CATEGORY_PREFIX_RE = re.compile(
    r"^(?:"
    r"comment\b|how\s+to\b|pourquoi\b|why\b|"
    r"compar(?:e|er|ez|aison|aisons)\b|comparisons?\b|"
    r"diff[ée]rences?\b|differences?\b|"
    r"pr[ée]cautions?\b|precautions?\b|proc[ée]dures?\b|procedures?\b|"
    r"r[ée]sum[ée]s?\b|synth[èe]ses?\b|summaries\b|overviews?\b"
    r")",
    re.IGNORECASE,
)
_NON_ENUMERATED_QUESTION_RE = re.compile(
    r"^what\s+is\b(?!.*\bare\s+(?:for|in|of)\s+(?:the\s+)?project\b)",
    re.IGNORECASE,
)
_NON_CATEGORY_TASK_SUFFIX_RE = re.compile(
    r"(?:^|\s)(?:pr[ée]cautions?|precautions?|proc[ée]dures?|procedures?)$",
    re.IGNORECASE,
)


def _looks_like_scoped_identifier(value: str) -> bool:
    """Recognise identifiers only after an explicit scope connector."""
    raw = str(value or "").strip()
    has_letter = bool(re.search(r"[A-Za-z]", raw))
    has_digit = bool(re.search(r"\d", raw))
    return bool(raw.isdigit() or (has_letter and has_digit) or (len(raw) >= 2 and raw.isupper()))


def parse_single_project_inventory_intent(
    query: str,
) -> SingleProjectInventoryIntent | None:
    """Parse an open-ended category enumeration scoped to one project."""
    text = " ".join(str(query or "").split())
    match = _INVENTORY_REQUEST_RE.fullmatch(text)
    if not match:
        return None

    anchors = list(_PROJECT_ANCHOR_RE.finditer(text))
    if len(anchors) != 1:
        return None
    project_code = match.group("project_code")
    if anchors[0].group("project_code").casefold() != project_code.casefold():
        return None

    category = " ".join(match.group("category").strip(" ,:;-/").split())
    category = _LEADING_CATEGORY_DETERMINER_RE.sub("", category).strip()
    if (
        not category
        or not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", category)
        or _NON_ENUMERATED_QUESTION_RE.search(text)
        or _NON_CATEGORY_EXACT_RE.fullmatch(category)
        or _NON_ENUMERATED_CATEGORY_PREFIX_RE.search(category)
        or _NON_CATEGORY_TASK_SUFFIX_RE.search(category)
    ):
        return None

    # A second project can be written without repeating the word "project":
    # "pumps for ABC123 and valves for project DEF456". Detect that only in
    # the structural scope slot. Identifiers used as category qualifiers remain
    # valid ("modules for S7-300 and S7-400 for project ABC123"), as do ordinary
    # material phrases such as "pumps for oil and gas".
    implicit_scope = _IMPLICIT_SCOPE_CONNECTOR_RE.search(category)
    if (
        implicit_scope is not None
        and _looks_like_scoped_identifier(implicit_scope.group("scope"))
        and not _looks_like_scoped_identifier(implicit_scope.group("next"))
    ):
        return None

    return SingleProjectInventoryIntent(
        project_code=project_code.upper(),
        category=category.casefold(),
    )
