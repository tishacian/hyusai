"""Industrial answer profiling and response-policy guards.

This module keeps answer-shaping policy separate from retrieval routing. It is
generic enough for industrial workspaces, while Andritz can instantiate it via
the workspace chat flow definition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from app.services.rag.project_references import extract_query_project_codes

DEFAULT_INDUSTRIAL_ANSWER_PROFILES: dict[str, dict[str, Any]] = {
    "precise_fact": {
        "label": "Precise fact",
        "instructions": [
            "Answer only the asked fact.",
            "Start directly with the factual answer; do not open with a discovery or source-finding preamble.",
            "Return the value with its unit and condition when available.",
            "Do not add project history, neighbouring equipment or general context unless asked.",
        ],
    },
    "project_summary": {
        "label": "Project summary",
        "instructions": [
            "Lead with the factual project synthesis, not with how the information was found.",
            "Produce a complete structured synthesis of the available project information.",
            "Group similar facts by theme and remove repetitions.",
            "Cover objective, customer, equipment, key technical characteristics, operating data and maintenance when present.",
            "Do not produce an undifferentiated catalogue of snippets; use compact paragraphs or grouped bullets only when they clarify the answer.",
        ],
    },
    "transversal_inventory": {
        "label": "Transversal inventory",
        "requires_exhaustive_retrieval": True,
        "instructions": [
            "Return the exhaustive list identified across projects and manuals.",
            "Merge duplicates and keep equipment references when available.",
            "Do not present a partial top-results list as exhaustive.",
        ],
    },
    "equipment_detail": {
        "label": "Equipment detail",
        "instructions": [
            "Start with the concrete technical answer or conclusion before supporting details.",
            "Build a consolidated technical sheet for the requested equipment, part or procedure.",
            "Include values, units, applicability and document-backed conditions when present.",
            "Avoid a source-by-source catalogue; consolidate facts by attribute.",
            "Do not infer missing references or part numbers.",
        ],
    },
    "comparison": {
        "label": "Comparison",
        "instructions": [
            "Compare the requested projects or equipment in a concise table.",
            "Only compare dimensions that are available in the provided context.",
            "Name gaps instead of filling them by analogy.",
        ],
    },
    "table_extract": {
        "label": "Table extraction",
        "instructions": [
            "Return the requested tabular data as a compact table.",
            "Preserve the row/column structure and keep every value with its unit.",
            "Only include rows and columns supported by the provided context; do not fabricate cells.",
            "Name missing entries explicitly instead of guessing them.",
        ],
    },
    "multi_hop": {
        "label": "Multi-hop reasoning",
        "instructions": [
            "Resolve the intermediate steps before answering the final question.",
            "Lead with the consolidated answer, then state the chain of facts it relies on.",
            "Use only facts available in the provided context for every hop.",
            "If an intermediate link is unsupported, say which one is missing instead of inferring it.",
        ],
    },
    "insufficient_context": {
        "label": "Insufficient context",
        "instructions": [
            "State clearly that no exploitable documentary information is available.",
            "Do not add facts after an absence statement.",
            "Do not invent values, references, projects or part numbers.",
        ],
    },
}


# The forbidden internal vocabulary is platform-level (chunk/score/rag/llm/…),
# not domain-specific, so the universal default policy reuses it verbatim.
FORBIDDEN_INTERNAL_TERMS: list[str] = [
    "chunk",
    "chunks",
    "score",
    "score vectoriel",
    "vectoriel",
    "base vectorielle",
    "rag",
    "llm",
    "moteur llm",
    "moteur rag",
    "base indexée",
    "documents indexés",
    "occurrence",
    "occurrences",
    "taux de confiance",
    "confidence",
    "retrieval",
    "qdrant",
]


DEFAULT_INDUSTRIAL_ANSWER_POLICY: dict[str, Any] = {
    "key": "industrial_answer_profile_v1",
    "default_answer_profile": "precise_fact",
    "principles": [
        "Answer only the user question.",
        "Use documentary context as the only source for workspace/project/equipment facts.",
        "Consolidate multi-document facts into one coherent answer and remove duplicates.",
        'Start with the factual answer, not with phrases such as "I found" or "the sources indicate".',
        "Prefer concise paragraphs for direct answers; use lists only for inventories, comparisons or explicitly list-shaped requests.",
        "Never invent a value, part number, equipment reference or project relationship.",
    ],
    "forbidden_internal_terms": list(FORBIDDEN_INTERNAL_TERMS),
    "no_internal_mechanics": True,
    "no_absence_then_answer": True,
    "citation_policy": "numeric_source_ids_only",
    "profiles": DEFAULT_INDUSTRIAL_ANSWER_PROFILES,
}


# ---------------------------------------------------------------------------
# Universal default answer policy (domain-neutral) — no "project"/"equipment"
# profiles. It reuses the SAME generic shaping prompt and post-hoc guards as the
# industrial policy (``answer_policy_prompt`` / ``apply_answer_policy_to_text``)
# so every workspace inherits the proven answer hygiene without the industrial
# project concept. The industrial layer stays an explicit opt-in.
# ---------------------------------------------------------------------------
DEFAULT_NEUTRAL_ANSWER_PROFILES: dict[str, dict[str, Any]] = {
    "precise_fact": {
        "label": "Precise fact",
        "instructions": [
            "Answer only the asked fact.",
            "Start directly with the factual answer; do not open with a discovery or source-finding preamble.",
            "Return the value with its unit and condition when available.",
            "Do not add unrequested background or neighbouring context unless asked.",
        ],
    },
    "summary": {
        "label": "Summary",
        "instructions": [
            "Lead with the factual synthesis, not with how the information was found.",
            "Produce a complete structured synthesis of the available information.",
            "Group similar facts by theme and remove repetitions.",
            "Do not produce an undifferentiated catalogue of snippets; use compact paragraphs or grouped bullets only when they clarify the answer.",
        ],
    },
    "comparison": {
        "label": "Comparison",
        "instructions": [
            "Compare the requested items in a concise table.",
            "Only compare dimensions that are available in the provided context.",
            "Name gaps instead of filling them by analogy.",
        ],
    },
    "insufficient_context": {
        "label": "Insufficient context",
        "instructions": [
            "State clearly that no exploitable documentary information is available.",
            "Do not add facts after an absence statement.",
            "Do not invent values, references or identifiers.",
        ],
    },
}


DEFAULT_NEUTRAL_ANSWER_POLICY: dict[str, Any] = {
    "key": "default_answer_profile_v1",
    "default_answer_profile": "precise_fact",
    "principles": [
        "Answer only the user question.",
        "Use documentary context as the only source for workspace-specific facts.",
        "Consolidate multi-document facts into one coherent answer and remove duplicates.",
        'Start with the factual answer, not with phrases such as "I found" or "the sources indicate".',
        "Prefer concise paragraphs for direct answers; use lists only for inventories, comparisons or explicitly list-shaped requests.",
        "Never invent a value, reference or identifier.",
    ],
    "forbidden_internal_terms": list(FORBIDDEN_INTERNAL_TERMS),
    "no_internal_mechanics": True,
    "no_absence_then_answer": True,
    "citation_policy": "numeric_source_ids_only",
    "profiles": DEFAULT_NEUTRAL_ANSWER_PROFILES,
}


_PROJECT_SUMMARY_RE = re.compile(
    r"\b(r[eé]sume|synth[eè]se|summary|summari[sz]e|aper[cç]u|overview|pr[ée]sentation)\b.*\b(projet|project|manuel|manual|dossier|document)\b"
    r"|\b(projet|project|manuel|manual)\b.*\b(r[eé]sume|synth[eè]se|summary|summari[sz]e|aper[cç]u|overview)\b"
    r"|\b(d[ée]taille|d[ée]tailler|d[ée]cris|d[ée]crire|d[ée]crit|pr[ée]sente|pr[ée]senter|contenu|contient)\b.*\b(manuel|manual|projet|project|document|dossier)\b"
    # A project code already names the project object, so users should not
    # have to spell out "le projet" for the summary route.  This is the common
    # Andritz chat phrasing ("resume BAO100").
    r"|\b(r[eé]sume|synth[eè]se|summari[sz]e)\b(?:[-\s]+moi)?(?:\s+(?:le|la|the))?(?:\s+(?:projet|project|dossier))?\s+[A-Z]{2,}\d{2,}\b"
    # "tell me everything about project X": broad-knowledge requests that want a
    # structured project synthesis, not a single fact. Anchored on an explicit
    # broad-knowledge phrase + a project object (word or project code) so plain
    # factual or cross-project questions stay on their own profiles.
    r"|\b(tout\s+ce\s+que\s+tu\s+sais|tout\s+savoir|que\s+sais[-\s]?tu|que\s+sait[-\s]?on|parle[-\s]?moi|raconte[-\s]?moi|dis[-\s]?moi\s+tout|tell\s+me\s+(?:everything|all)|what\s+do\s+you\s+know)\b.*\b(projet|project|dossier|[A-Z]{2,}\d{2,})\b"
    r"|\btout\b.*\b(?:sur|about|concernant|au\s+sujet)\b.*\b(projet|project|dossier|[A-Z]{2,}\d{2,})\b",
    re.IGNORECASE,
)
_PROJECT_SUMMARY_ACTION_RE = re.compile(
    r"\b(r[eé]sum[eé]|synth[eè]se|summary|summari[sz]e|aper[cç]u|overview|"
    r"tout\s+sur|tell\s+me\s+(?:everything|all)|parle[-\s]?moi)\b",
    re.IGNORECASE,
)
_TRANSVERSAL_RE = re.compile(
    r"\b(quels|quelles|liste|list|tous|toutes|all|which)\b.*\b(projets|projects|manuels|manuals)\b"
    r"|\b(dans quels?|where)\b.*\b(projets?|projects?)\b"
    r"|\b(utilisent|using|use|retrouve|retrouve-t-on|installed|install[eé])\b.*\b(projets?|projects?)\b"
    # Imperative / declarative cross-project inventory phrasings that lack a
    # leading "quels/liste/tous/which" but still ask for the set of projects
    # qualified by a piece of equipment, e.g. "donne moi les projets avec une
    # pompe Uraca" or "les projets équipés d'une pompe X". Anchored on the
    # plural projets/projects + a possession/equipment qualifier so single-fact
    # questions ("quelle pompe dans ce projet ?") stay on precise_fact.
    r"|\b(projets|projects)\b[^?.!\n]{0,80}\b(avec|[eé]quip[eé]?s?|munis?|dot[eé]?s?|poss[eé]dant|comportant|int[eè]grant|with|having|equipped|using|qui\s+(?:ont|utilisent|poss[eè]dent|disposent|int[eè]grent))\b"
    r"|\b(liste|list|tous|toutes|all)\b.*\b(pompes?|pumps?|moteurs?|motors?|injecteurs?|buses?|nozzles?|rouleaux?|s[ée]cheurs?|dryers?|filtres?|filters?|pi[eè]ces?|parts?)\b",
    re.IGNORECASE,
)
_COMPARISON_RE = re.compile(
    r"\b(compare|comparer|comparez|comparaison[s]?|comparison[s]?|"
    r"diff[ée]rence[s]?|versus|vs\.?)\b",
    re.IGNORECASE,
)
_EQUIPMENT_DETAIL_RE = re.compile(
    r"\b(d[ée]tails?|fiche|caract[ée]ristiques?|sp[ée]cifications?|details?|datasheet)\b.*"
    r"\b([A-Z]{2,}\d{2,}|pompe|pump|moteur|motor|injecteur|buse|nozzle|rouleau|dryer|s[ée]cheur|filtre|"
    r"toile|belt|convoyeur|conveyor|palier|bearing|strip)\b",
    re.IGNORECASE,
)
# Part-identity questions ("quelle est la référence de la toile du convoyeur
# J1") open with an interrogative, so they are claimed by ``_PRECISE_FACT_RE``
# unless resolved first, even though they belong to the equipment niche. The
# ``de`` lookbehind keeps adjectival French wording ("la pression de référence
# de la pompe") on the factual profile, and the reference term must be followed
# by the part it identifies rather than appearing anywhere in the sentence.
_PART_REFERENCE_RE = re.compile(
    r"(?<!de\s)\b(?:r[ée]f[ée]rence[s]?|reference[s]?|code\s+pi[eè]ce|"
    r"part\s*(?:number|no\.?|n[°o]))\b"
    r"[^?.!\n]{0,40}?"
    r"\b(?:toile[s]?|convoyeur[s]?|conveyor|belt|palier[s]?|bearing|strip[s]?|"
    r"courroie[s]?|pi[eè]ce[s]?|part|pompe|moteur|injecteur|buse|rouleau|filtre|"
    r"[A-Z]{2,}\d{2,})\b",
    re.IGNORECASE,
)
# Tabular-extraction intent: the user wants values laid out as a table/BOM, not
# a prose fact. Anchored on strongly tabular vocabulary (``tableau`` is almost
# always a data table in this domain) or explicit "as a table" / "table of …"
# phrasings, so plain factual questions and physical objects like a
# "colonne de distillation" are NOT captured.
_TABLE_EXTRACT_RE = re.compile(
    r"\b(tableau(?:x)?|nomenclature|bill\s+of\s+materials|BOM|bar[eè]me|tableur|spreadsheet|matrice)\b"
    r"|\btabular\b"
    r"|\b(?:as|in|into|sous\s+forme\s+d[e']|sous\s+la\s+forme\s+d[e'])\s+(?:(?:an?|une?|the|le|la)\s+)?tables?\b"
    r"|\btables?\s+(?:of|des?|du|de\s+la)\b",
    re.IGNORECASE,
)
# Multi-hop intent: the answer needs an intermediate entity/condition resolved
# before the final fact. Anchored on explicit chaining signals (sequential
# markers, a second additive condition, a cross-reference "same … as", or a
# conditional aggregation over a derived set) so single-hop precise_fact
# questions are NOT cannibalised.
_MULTIHOP_RE = re.compile(
    r"\b(?:puis|ensuite|then)\b"
    r"|\b(?:ont|poss[eè]dent|disposent|utilisent|comportent|int[eè]grent|sont)\s+(?:aussi|[ée]galement)\b"
    r"|\balso\s+(?:has|have|use[sd]?|include[sd]?|feature[sd]?|equipped)\b"
    r"|\b(?:le|la|les|ce|cette|ces)\s+m[êe]mes?\b[^?.!\n]{0,40}\bque\b"
    r"|\bthe\s+same\b[^?.!\n]{0,40}\bas\b"
    r"|\b(?:pour|parmi|among|for)\b[^?.!\n]{0,90}\b(?:qui|que|dont|which|that|avec|with)\b"
    r"[^?.!\n]{0,90}\b(?:combien|quels?|quelles?|how\s+many|how\s+much|which)\b",
    re.IGNORECASE,
)
_PRECISE_FACT_RE = re.compile(
    r"^\s*(quelle?|quels?|quelles?|what|which|combien|how\s+much|how\s+many|pression|pressure|largeur|width|vitesse|speed)\b",
    re.IGNORECASE,
)
# Platform jargon: "source workspace" / "contexte workspace" leak the internal
# term to end users. The balanced grounding prompt also instructs the model to
# avoid it, but this normalises any streamed slip in the persisted answer.
_WORKSPACE_JARGON_RE = re.compile(r"\b(sources?|contexte)\s+workspace\b", re.IGNORECASE)
_ABSENCE_RE = re.compile(
    r"(je\s+n['’]ai\s+(?:pas|aucune)|aucune\s+(?:information|donn[ée]e)|no\s+(?:information|data|source))",
    re.IGNORECASE,
)
_FACT_AFTER_ABSENCE_RE = re.compile(
    r"\b(est de|utilise|comprend|inclut|is|uses|includes)\b", re.IGNORECASE
)
_DOCUMENTALIST_FIRST_SENTENCE_RE = re.compile(
    r"^\s*j['’]ai\s+trouv[ée]?\s+(?:cette|ces|des|les?)?\s*information[s]?"
    r"(?:\s+[^.:\n]{0,140})?[.:]\s*",
    re.IGNORECASE,
)
_DOCUMENTALIST_INLINE_PREAMBLE_RE = re.compile(
    r"^\s*(?:"
    r"j['’]ai\s+trouv[ée]?\s*:\s*|"
    r"j['’]ai\s+trouv[ée]?\s+que\s+|"
    r"j['’]ai\s+trouv[ée]?\s+(?=(?:la|le|les|un|une|ce|cet|cette|ces)\b|l['’])|"
    r"les?\s+(?:documents?|sources?)\s+(?:indiquent|mentionnent|pr[ée]cisent|signalent|montrent)\s+que\s+|"
    r"le\s+manuel\s+(?:indique|mentionne|pr[ée]cise|signale|montre)\s+que\s+|"
    r"d['’]apr[eè]s\s+(?:les?\s+)?(?:documents?|sources?|le\s+manuel),?\s+|"
    r"selon\s+(?:les?\s+)?(?:documents?|sources?|le\s+manuel),?\s+"
    r")",
    re.IGNORECASE,
)


def _sentence_case_start(value: str) -> str:
    stripped = value.lstrip()
    if not stripped:
        return value.strip()
    prefix = value[: len(value) - len(stripped)]
    first = stripped[0]
    if first.islower():
        stripped = first.upper() + stripped[1:]
    return f"{prefix}{stripped}".strip()


@dataclass(frozen=True)
class AnswerProfileDecision:
    profile: str
    reason: str
    requires_exhaustive_retrieval: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "reason": self.reason,
            "requires_exhaustive_retrieval": self.requires_exhaustive_retrieval,
        }


def industrial_answer_policy() -> dict[str, Any]:
    return {
        **DEFAULT_INDUSTRIAL_ANSWER_POLICY,
        "forbidden_internal_terms": list(FORBIDDEN_INTERNAL_TERMS),
        "profiles": {key: dict(value) for key, value in DEFAULT_INDUSTRIAL_ANSWER_PROFILES.items()},
    }


def default_answer_policy() -> dict[str, Any]:
    """Domain-neutral answer policy for the universal default chat orchestration.

    Carries only the universally-safe profiles (``precise_fact``, ``summary``,
    ``comparison``, ``insufficient_context``) and reuses the same generic answer
    shaping (:func:`answer_policy_prompt`) and post-hoc guards
    (:func:`apply_answer_policy_to_text`) as the industrial policy. It omits the
    industrial ``project_summary`` / ``transversal_inventory`` /
    ``equipment_detail`` profiles, so the "project" concept stays an opt-in
    industrial layer rather than leaking into every workspace.
    """
    return {
        **DEFAULT_NEUTRAL_ANSWER_POLICY,
        "forbidden_internal_terms": list(FORBIDDEN_INTERNAL_TERMS),
        "profiles": {key: dict(value) for key, value in DEFAULT_NEUTRAL_ANSWER_PROFILES.items()},
    }


def resolve_answer_profile(
    query: str,
    answer_policy: Mapping[str, Any] | None = None,
    *,
    include_agentic_profiles: bool = False,
) -> AnswerProfileDecision:
    text = str(query or "").strip()
    if not text:
        return AnswerProfileDecision("insufficient_context", "empty_query")
    if _PROJECT_SUMMARY_RE.search(text) or (
        _PROJECT_SUMMARY_ACTION_RE.search(text) and extract_query_project_codes(text)
    ):
        return AnswerProfileDecision("project_summary", "project_summary_query")
    if _COMPARISON_RE.search(text):
        return AnswerProfileDecision("comparison", "comparison_query")
    if _TRANSVERSAL_RE.search(text):
        return AnswerProfileDecision("transversal_inventory", "cross_project_inventory_query", True)
    if _EQUIPMENT_DETAIL_RE.search(text):
        return AnswerProfileDecision("equipment_detail", "equipment_detail_query")
    if _PART_REFERENCE_RE.search(text):
        return AnswerProfileDecision("equipment_detail", "part_reference_query")
    # table_extract / multi_hop only shape the answer when agentic chat routing
    # is enabled. Gating them keeps the classic prompt shaping byte-for-byte
    # unchanged while ``enable_agentic_chat`` is off (zero drift pre-enablement);
    # once enabled they both classify the intent AND arm the agentic route.
    if include_agentic_profiles:
        if _TABLE_EXTRACT_RE.search(text):
            return AnswerProfileDecision("table_extract", "table_extract_query")
        if _MULTIHOP_RE.search(text):
            return AnswerProfileDecision("multi_hop", "multi_hop_query")
    if _PRECISE_FACT_RE.search(text) or text.endswith("?"):
        return AnswerProfileDecision("precise_fact", "precise_fact_query")
    default_profile = str((answer_policy or {}).get("default_answer_profile") or "precise_fact")
    return AnswerProfileDecision(default_profile, "default_answer_profile")


def answer_policy_prompt(
    *,
    answer_policy: Mapping[str, Any] | None,
    profile_decision: Mapping[str, Any] | None,
    language: str | None = None,
) -> str:
    policy = dict(answer_policy or industrial_answer_policy())
    profiles = policy.get("profiles") if isinstance(policy.get("profiles"), Mapping) else {}
    profile_key = str(
        (profile_decision or {}).get("profile")
        or policy.get("default_answer_profile")
        or "precise_fact"
    )
    profile = profiles.get(profile_key) if isinstance(profiles, Mapping) else {}
    profile_instructions = profile.get("instructions") if isinstance(profile, Mapping) else None
    if not isinstance(profile_instructions, list):
        profile_instructions = DEFAULT_INDUSTRIAL_ANSWER_PROFILES.get(profile_key, {}).get(
            "instructions", []
        )
    principles = policy.get("principles") if isinstance(policy.get("principles"), list) else []
    forbidden = policy.get("forbidden_internal_terms")
    forbidden_terms = (
        ", ".join(str(term) for term in forbidden[:16]) if isinstance(forbidden, list) else ""
    )
    heading = (
        "Politique de réponse industrielle" if language == "fr" else "Industrial answer policy"
    )
    lines = [f"{heading}:"]
    for item in principles:
        lines.append(f"- {item}")
    lines.extend(
        [
            '- Start with the answer itself; avoid documentary preambles such as "I found", "the sources say" or "the documents mention" unless provenance is the user\'s question.',
            "- Do not turn factual answers into source-by-source lists; synthesize the answer first and keep evidence secondary.",
            # Source conflict / ambiguity (case 1): documents disagree on the asked
            # fact. The model must answer AND surface the disagreement instead of
            # silently picking one value or listing both flatly.
            '- When the sources give conflicting values for the same asked fact or configuration, do not silently pick one and do not list them flatly: lead with the most precise value, then explicitly flag the disagreement and name each conflicting value with its source (e.g. "≈ X selon [1], mais [2] indique Y pour la même configuration — à vérifier").',
            "- Never mention internal mechanics such as document counts, chunk counts, relevance scores, vector search, databases, LLM/RAG engines, confidence rates or retrieval methods.",
            "- Never say no exploitable information is available and then continue with factual project/equipment claims.",
            "- Keep citations as numeric source ids when sources exist; do not expose raw retrieval diagnostics in the answer text.",
        ]
    )
    if forbidden_terms:
        lines.append(
            f"- Forbidden internal vocabulary in the user-facing answer includes: {forbidden_terms}."
        )
    if profile_instructions:
        lines.append(
            f"Answer profile: {profile_key} ({(profile_decision or {}).get('reason') or 'default'})."
        )
        for item in profile_instructions:
            lines.append(f"- {item}")
    if profile_key == "transversal_inventory":
        lines.append(
            "- This is an exhaustive inventory question: if evidence is insufficient, say which information is documented and what remains unavailable; do not call a partial sample exhaustive."
        )
        lines.append(
            '- When the context includes a consolidated project inventory block ("Inventaire projets consolidé … couverture exhaustive"), treat that list as the complete, authoritative coverage of the indexed corpus: present the full deduplicated set of projects it contains (you may group or order by the associated documentation volume given in parentheses) and never claim the information is unavailable or that the list is partial when that block is present.'
        )
    return "\n".join(lines)


def apply_answer_policy_to_text(
    text: str,
    *,
    answer_policy: Mapping[str, Any] | None = None,
    profile_decision: Mapping[str, Any] | None = None,
) -> tuple[str, list[str]]:
    """Return user-facing text plus policy violation codes.

    The guard is deliberately conservative: it removes obvious mechanics leaks
    and flags contradictions, but it does not try to fabricate missing facts.
    """
    out = str(text or "")
    policy = answer_policy or industrial_answer_policy()
    forbidden = policy.get("forbidden_internal_terms")
    violations: list[str] = []

    # Very small local models can echo the hidden prompt after first producing
    # a useful answer.  Keep the explicit final answer when present; otherwise
    # retain the prose before the first internal section.  Requiring multiple
    # prompt markers prevents a legitimate user-facing sentence beginning with
    # a word such as "Coverage" from being truncated.
    prompt_marker_re = re.compile(
        r"(?im)^(?:Retrieved content synthesis brief|Coverage|Retrieved source types|"
        r"Representative content|Grounding instructions|Industrial answer policy|"
        r"Answer-shaping instructions|Answer profile)\s*:",
    )
    prompt_markers = list(prompt_marker_re.finditer(out))
    factual_answer_matches = list(re.finditer(r"(?im)^Factual answer\s*:\s*", out))
    if len(prompt_markers) >= 2:
        replacement = ""
        if factual_answer_matches:
            replacement = out[factual_answer_matches[-1].end() :].strip()
        if not replacement:
            replacement = out[: prompt_markers[0].start()].strip()
        if replacement:
            out = replacement
            violations.append("prompt_echo")
    if _WORKSPACE_JARGON_RE.search(out):
        violations.append("platform_jargon_workspace")
        out = _WORKSPACE_JARGON_RE.sub(lambda m: m.group(1), out)
    if re.search(r"\((?:retrieval|fallback|worker|dense|sparse)\s*:", out, flags=re.IGNORECASE):
        violations.append("internal_diagnostic_parenthetical")
        out = re.sub(
            r"\s*\((?:retrieval|fallback|worker|dense|sparse)\s*:[^)]+\)",
            "",
            out,
            flags=re.IGNORECASE,
        )
    if isinstance(forbidden, list):
        for raw in forbidden:
            term = str(raw or "").strip()
            if not term:
                continue
            if re.search(rf"\b{re.escape(term)}\b", out, flags=re.IGNORECASE):
                violations.append(f"internal_term:{term.lower()}")
                if term.lower() == "retrieval":
                    out = re.sub(r"\bretrievals?\b(?!\s*:)", "source", out, flags=re.IGNORECASE)
                else:
                    out = re.sub(rf"\b{re.escape(term)}s?\b", "source", out, flags=re.IGNORECASE)
    if _DOCUMENTALIST_FIRST_SENTENCE_RE.search(out):
        violations.append("documentalist_preamble")
        out = _DOCUMENTALIST_FIRST_SENTENCE_RE.sub("", out, count=1)
    elif _DOCUMENTALIST_INLINE_PREAMBLE_RE.search(out):
        violations.append("documentalist_preamble")
        out = _DOCUMENTALIST_INLINE_PREAMBLE_RE.sub("", out, count=1)
        out = _sentence_case_start(out)
    if _ABSENCE_RE.search(out):
        after = out[_ABSENCE_RE.search(out).end() :]  # type: ignore[union-attr]
        if _FACT_AFTER_ABSENCE_RE.search(after):
            violations.append("absence_then_answer")
            sentences = re.split(r"(?<=[.!?])\s+", out.strip())
            kept = [sentence for sentence in sentences if not _ABSENCE_RE.search(sentence)]
            out = " ".join(kept).strip() or out
    if violations:
        out = re.sub(r"\s{2,}", " ", out).strip()
    return out, sorted(set(violations))
