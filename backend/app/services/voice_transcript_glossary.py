"""Domain-aware transcript glossary + correction for the capture voice loop.

This module powers a *correction* pass on the ``transcript.improved`` / committed
``text.final`` stages of the voice gateway. It never touches the immediate raw
``transcript.partial`` stage, so it adds no latency to what the expert sees first.

Two cooperating pieces:

* :func:`resolve_glossary` builds a hybrid :class:`Glossary` from
  (a) the workspace glossary (KB-derived, editable), (b) the active plan's
  topic / subtopic labels, and (c) distinctive terms extracted from the
  session's live retrieved chunks.
* :func:`correct_transcript_segment` applies the glossary to a transcript
  segment: a deterministic, instant Tier-1 pass (fuzzy near-homophone repair +
  acronym casing) and an optional, timeout-bounded Tier-2 LLM rewrite.

There is **no hardcoded** ``cadre -> carde`` (or any other) mapping anywhere;
every correction is derived from the resolved glossary.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Sequence

# --- Extraction primitives --------------------------------------------------

# Acronym / part-number style tokens: ALLCAPS words and alphanumeric codes such
# as BOM, JETLACE, KD724, XS1, ZCT. First char is an uppercase letter, followed
# by uppercase letters and/or digits (>= 1 more char so single letters like "I"
# are excluded).
_ACRONYM_RE = re.compile(r"[A-Z][A-Z0-9]{1,}")

# Word token (keeps accented French letters, intra-word apostrophes and hyphens).
_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9'’\-]*")

# Tokenizer that preserves separators so a corrected segment can be rebuilt
# verbatim apart from the replaced tokens.
_SEGMENT_RE = re.compile(r"[A-Za-zÀ-ÿ0-9'’\-]+|[^A-Za-zÀ-ÿ0-9'’\-]+")

# Small French + transcription stopword set used to drop non-distinctive tokens
# when extracting candidate domain nouns. Intentionally compact: it only needs
# to suppress the highest-frequency function words, not act as a full lexicon.
_STOPWORDS = frozenset(
    {
        "alors", "après", "assez", "aucun", "aussi", "autre", "avant", "avec", "avoir",
        "bien", "cela", "cette", "ceux", "chaque", "comme", "comment", "dans", "deux",
        "donc", "dont", "elle", "elles", "encore", "entre", "était", "étaient", "être",
        "fait", "faire", "faut", "fois", "hors", "ici", "jamais", "leur", "leurs",
        "lors", "mais", "même", "moins", "notre", "nous", "parce", "pour", "plus",
        "quand", "quel", "quelle", "quelles", "quels", "qui", "quoi", "sans", "sera",
        "seront", "ses", "sont", "sous", "sur", "tous", "tout", "toute", "toutes",
        "très", "trop", "une", "vers", "voici", "voilà", "vont", "votre", "vous",
        "ça", "celui", "celle", "depuis", "pendant", "puis", "selon", "ainsi", "donne",
        "passe", "valide", "été", "cet", "des", "les", "ces", "est", "que", "qu",
        "the", "and", "for", "with", "this", "that", "from", "your",
    }
)

_MIN_TERM_LEN = 4
_DEFAULT_MAX_TERMS = 120

# Tier-1 fuzzy thresholds. A token is only rewritten when it is *strongly* close
# to a single glossary term: high difflib ratio AND a short edit distance AND a
# near-identical length. These guard against rewriting unrelated tokens.
_FUZZY_RATIO_MIN = 0.8
_FUZZY_EDIT_MAX = 2
_FUZZY_LEN_DELTA_MAX = 2


def extract_acronyms(text: str) -> List[str]:
    """Return acronym / part-number style surface forms found in ``text``."""
    if not text:
        return []
    return _ACRONYM_RE.findall(text)


def _is_acronym_token(token: str) -> bool:
    return bool(token) and _ACRONYM_RE.fullmatch(token) is not None


def extract_distinctive_terms(text: str, *, min_len: int = _MIN_TERM_LEN) -> List[str]:
    """Extract candidate distinctive domain nouns from ``text``.

    Heuristic and cheap: alphabetic-ish word tokens of at least ``min_len``
    characters that are not common function words. Acronyms are handled
    separately by :func:`extract_acronyms` and excluded here.
    """
    if not text:
        return []
    out: List[str] = []
    for match in _WORD_RE.finditer(text):
        token = match.group(0)
        if _is_acronym_token(token):
            continue
        lowered = token.lower()
        if len(lowered) < min_len:
            continue
        if lowered in _STOPWORDS:
            continue
        # Require at least one letter; skip pure numbers / codes (acronym path
        # owns alphanumeric codes).
        if not any(ch.isalpha() for ch in token):
            continue
        if any(ch.isdigit() for ch in token):
            continue
        out.append(token)
    return out


# --- Glossary ---------------------------------------------------------------


@dataclass
class Glossary:
    """Resolved glossary used by the corrector.

    ``terms`` is the full ordered list of canonical surface forms (including
    acronyms). ``acronyms`` is the subset of acronym-style surface forms, used
    for casing normalization. A case-insensitive lookup is precomputed.
    """

    terms: List[str] = field(default_factory=list)
    acronyms: set = field(default_factory=set)
    _by_lower: dict = field(default_factory=dict, init=False, repr=False)
    _acronyms_by_lower: dict = field(default_factory=dict, init=False, repr=False)
    _fuzzy_terms: List[str] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        for surface in self.terms:
            self._by_lower.setdefault(surface.lower(), surface)
        for surface in self.acronyms:
            self._acronyms_by_lower.setdefault(surface.lower(), surface)
        # Non-acronym terms long enough to be fuzzy-match targets.
        acro_lower = set(self._acronyms_by_lower)
        self._fuzzy_terms = [
            surface
            for surface in self.terms
            if surface.lower() not in acro_lower and len(surface) >= _MIN_TERM_LEN
        ]

    @property
    def is_empty(self) -> bool:
        return not self.terms and not self.acronyms

    def canonical_for(self, token: str) -> Optional[str]:
        """Return the canonical surface for ``token`` if it is a known term."""
        return self._by_lower.get(token.lower())

    def acronym_for(self, token: str) -> Optional[str]:
        return self._acronyms_by_lower.get(token.lower())

    @property
    def fuzzy_terms(self) -> List[str]:
        return self._fuzzy_terms


def _coerce_workspace_terms(raw: Any) -> List[str]:
    """Accept either a list of strings or a list of ``{term/surface: ...}`` dicts."""
    out: List[str] = []
    if not isinstance(raw, (list, tuple)):
        return out
    for item in raw:
        if isinstance(item, str):
            surface = item.strip()
        elif isinstance(item, dict):
            surface = str(item.get("term") or item.get("surface") or item.get("text") or "").strip()
        else:
            surface = ""
        if surface:
            out.append(surface)
    return out


def _plan_labels(capture_session: Any) -> List[str]:
    plan = getattr(capture_session, "plan", None) or {}
    if not isinstance(plan, dict):
        return []
    labels: List[str] = []
    for topic in plan.get("topics") or []:
        if not isinstance(topic, dict):
            continue
        title = str(topic.get("title") or "").strip()
        if title:
            labels.append(title)
        for subtopic in topic.get("subtopics") or []:
            if not isinstance(subtopic, dict):
                continue
            sub_title = str(subtopic.get("title") or "").strip()
            if sub_title:
                labels.append(sub_title)
    return labels


def _resolve_max_terms(max_terms: Optional[int]) -> int:
    if max_terms is not None:
        return max(1, int(max_terms))
    try:
        from app.core.config import settings as cfg

        return max(1, int(getattr(cfg, "voice_transcript_glossary_max_terms", _DEFAULT_MAX_TERMS)))
    except Exception:
        return _DEFAULT_MAX_TERMS


def build_glossary_from_terms(
    surfaces: Iterable[str], *, max_terms: Optional[int] = None
) -> Glossary:
    """Build a :class:`Glossary` from an ordered iterable of surface forms.

    Dedupes case-insensitively (first surface wins as canonical), classifies
    acronym-style tokens, and caps the total number of terms.
    """
    cap = _resolve_max_terms(max_terms)
    terms: List[str] = []
    acronyms: set = set()
    seen: set = set()
    for surface in surfaces:
        if not surface:
            continue
        surface = surface.strip()
        if not surface:
            continue
        key = surface.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append(surface)
        if _is_acronym_token(surface):
            acronyms.add(surface)
        if len(terms) >= cap:
            break
    return Glossary(terms=terms, acronyms=acronyms)


def resolve_glossary(
    workspace: Any,
    capture_session: Any,
    live_chunks: Optional[Sequence[str]],
    *,
    max_terms: Optional[int] = None,
) -> Glossary:
    """Merge a hybrid glossary from workspace settings, plan labels and chunks.

    Order is authority-first so the cap keeps the most trustworthy terms:
    workspace glossary, then plan topic/subtopic labels, then acronyms and
    distinctive terms extracted from the live retrieved chunks. Pure and cheap.
    """
    ordered: List[str] = []

    settings_obj = getattr(workspace, "settings", None) if workspace is not None else None
    if isinstance(settings_obj, dict):
        voice_cfg = settings_obj.get("voice")
        if isinstance(voice_cfg, dict):
            ordered.extend(_coerce_workspace_terms(voice_cfg.get("transcript_glossary")))

    ordered.extend(_plan_labels(capture_session))

    chunk_acronyms: List[str] = []
    chunk_terms: List[str] = []
    for chunk in live_chunks or []:
        text = chunk if isinstance(chunk, str) else str(chunk or "")
        if not text:
            continue
        chunk_acronyms.extend(extract_acronyms(text))
        chunk_terms.extend(extract_distinctive_terms(text))
    # Acronyms before generic nouns: they are higher-value and lower-risk.
    ordered.extend(chunk_acronyms)
    ordered.extend(chunk_terms)

    return build_glossary_from_terms(ordered, max_terms=max_terms)


# --- Tier-1 deterministic correction ----------------------------------------


def _edit_distance(a: str, b: str, *, cap: int = _FUZZY_EDIT_MAX) -> int:
    """Bounded Levenshtein distance. Returns ``cap + 1`` once it provably exceeds."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        row_min = current[0]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            value = min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + cost,
            )
            current.append(value)
            if value < row_min:
                row_min = value
        if row_min > cap:
            return cap + 1
        previous = current
    return previous[-1]


def _match_case(replacement: str, original: str) -> str:
    """Carry the original token's leading-capital convention onto ``replacement``."""
    if not original or not replacement:
        return replacement
    if original.isupper() and len(original) > 1:
        return replacement.upper()
    if original[0].isupper() and not replacement[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def _is_safe_acronym(surface: str) -> bool:
    """Whether normalizing arbitrary-cased text to this acronym is safe.

    Acronyms with a digit, or length >= 3, are unambiguous domain codes. Very
    short (<= 2, no digit) acronyms are skipped to avoid colliding with short
    French function words (e.g. ``or``, ``et``).
    """
    if any(ch.isdigit() for ch in surface):
        return True
    return len(surface) >= 3


def _correct_word(token: str, glossary: Glossary) -> str:
    lowered = token.lower()

    # Already a known term (any casing that matches a non-acronym term): leave it.
    # This keeps the pass idempotent and avoids touching correct domain words.
    canonical = glossary.canonical_for(token)

    # Acronym casing normalization: bom -> BOM, kd724 -> KD724.
    acronym = glossary.acronym_for(token)
    if acronym and _is_safe_acronym(acronym):
        return acronym if token != acronym else token

    if canonical is not None:
        # Exact (case-insensitive) match to a non-acronym term -> already correct.
        return token

    if len(lowered) < _MIN_TERM_LEN:
        return token

    best_surface: Optional[str] = None
    best_ratio = 0.0
    matcher = difflib.SequenceMatcher()
    matcher.set_seq2(lowered)
    for surface in glossary.fuzzy_terms:
        target = surface.lower()
        if target == lowered:
            return token  # already correct
        if abs(len(target) - len(lowered)) > _FUZZY_LEN_DELTA_MAX:
            continue
        matcher.set_seq1(target)
        ratio = matcher.ratio()
        if ratio < _FUZZY_RATIO_MIN or ratio <= best_ratio:
            continue
        if _edit_distance(lowered, target) > _FUZZY_EDIT_MAX:
            continue
        best_ratio = ratio
        best_surface = surface

    if best_surface is not None:
        return _match_case(best_surface, token)
    return token


def correct_transcript_segment_tier1(text: str, glossary: Optional[Glossary]) -> str:
    """Deterministic, instant, network-free domain correction.

    Tokenizes ``text``, rewrites only tokens that strongly match a glossary
    term (near-homophone repair) and normalizes acronym casing. Never adds,
    drops or reorders content; idempotent.
    """
    if not text or glossary is None or glossary.is_empty:
        return text
    out: List[str] = []
    for piece in _SEGMENT_RE.findall(text):
        if _WORD_RE.fullmatch(piece):
            out.append(_correct_word(piece, glossary))
        else:
            out.append(piece)
    return "".join(out)


# --- Tier-2 optional LLM correction -----------------------------------------


async def _correct_transcript_segment_tier2(
    text: str,
    glossary: Glossary,
    *,
    tier1_result: str,
    workspace_id: Optional[str] = None,
) -> str:
    """Fast LLM rewrite constrained to glossary terms. Falls back to Tier-1."""
    try:
        from app.services.capture_knowledge_oracle import (
            _model_chat_kwargs,
            _resolve_llm_config,
        )

        api_key, model = _resolve_llm_config(workspace_id)
        if not api_key:
            return tier1_result
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        glossary_terms = list(glossary.terms)[:80]
        response = await client.chat.completions.create(
            model=model,
            **_model_chat_kwargs(model, temperature=0.0),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Tu corriges UNIQUEMENT les termes métier mal transcrits dans un "
                        "segment de parole, en t'appuyant sur le glossaire fourni. "
                        "Ne change JAMAIS le sens. N'invente RIEN. N'ajoute ni ne supprime "
                        "aucune information. Si rien n'est à corriger, renvoie le texte tel quel. "
                        "Réponds avec le seul texte corrigé, sans guillemets ni commentaire."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Glossaire métier (formes correctes): "
                        + ", ".join(glossary_terms)
                        + "\n\nSegment à corriger:\n"
                        + (tier1_result or text)
                    ),
                },
            ],
        )
        content = response.choices[0].message.content if response.choices else None
        if not content:
            return tier1_result
        corrected = content.strip().strip('"').strip()
        return corrected or tier1_result
    except Exception:
        return tier1_result


async def correct_transcript_segment(
    text: str,
    glossary: Optional[Glossary],
    *,
    llm_enabled: bool = False,
    timeout_ms: int = 1200,
    workspace_id: Optional[str] = None,
) -> str:
    """Public correction entrypoint (async).

    Always runs the deterministic Tier-1 pass. When ``llm_enabled`` is set, runs
    a Tier-2 LLM refinement under an ``asyncio.wait_for`` budget, falling back to
    the Tier-1 result on timeout or any error so the live cascade is never
    blocked.
    """
    tier1 = correct_transcript_segment_tier1(text, glossary)
    if not llm_enabled or glossary is None or glossary.is_empty or not (text or "").strip():
        return tier1
    import asyncio

    try:
        timeout_s = max(0.05, float(timeout_ms) / 1000.0)
        return await asyncio.wait_for(
            _correct_transcript_segment_tier2(
                text, glossary, tier1_result=tier1, workspace_id=workspace_id
            ),
            timeout=timeout_s,
        )
    except Exception:
        return tier1
