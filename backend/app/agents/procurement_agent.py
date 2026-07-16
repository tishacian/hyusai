"""RAG Agent -- Generic RAG pipeline

Full execution streaming pipeline with real-time SSE decision_step events.
"""

import asyncio
import re
import time
import unicodedata
from collections.abc import Mapping
from typing import Any, AsyncGenerator

from app.agents.base import BaseAgent
from app.core.config import settings
from app.core.logging import get_logger
from app.services.rag.conversation_anchors import has_reference

logger = get_logger(__name__)

# ── Conversation memory / follow-up handling ──────────────────────────────
#
# End users repeatedly reported "il ne suit pas la conversation": short
# follow-up / meta instructions ("détaille", "réponds plus long", "résume")
# were run as literal RAG queries — retrieving junk and losing the previous
# answer the user actually wanted expanded. We now (a) feed recent turns
# (including the previous assistant answer) into the generation prompt and
# (b) detect meta/follow-up turns so we reuse the prior context instead of
# grounding on noise, and never attach spurious sources to them.

# How many prior turns and how much text to carry into the prompt. The most
# recent assistant answer is kept in full so "détaille"/"plus long" has the
# real text to expand; older turns are length-capped to bound prompt size.
_HISTORY_MAX_TURNS = 8
_HISTORY_TURN_MAX_CHARS = 4000

# Meta / formatting / length instructions that operate on the PREVIOUS answer
# rather than introducing a new retrieval topic. Matching turns reuse the
# conversation context (no fresh grounding requirement, no sources panel).
_META_FOLLOWUP_RE = re.compile(
    r"\b("
    r"d[ée]taille[rz]?|d[ée]taill[ée]e?s?|d[ée]velopp[a-z]*|approfond[a-z]*|"
    r"r[ée]sume[rz]?|r[ée]sum[ée]|reformule[rz]?|reformul[a-z]*|"
    r"explique[rz]?|expliqu[a-z]*|pr[ée]cise[rz]?|clarifie[rz]?|"
    r"continue[rz]?|poursui[a-z]*|encore|davantage|"
    r"plus\s+(?:long|court|d[ée]taill[ée]e?s?|pr[ée]cis|simple|clair)|"
    r"moins\s+long|"
    r"r[ée]ponse\s+plus|"
    r"\d+\s*fois\s+plus|"
    r"traduis[a-z]*|reprends|r[ée][ée]cris|reecris|"
    r"expand|elaborate|summari[sz]e|rephrase|rewrite|shorter|longer|"
    r"continue|more\s+detail|in\s+detail"
    r")\b",
    re.IGNORECASE,
)

# Explicit "make it longer / more detailed" intent — relaxes brevity and
# raises the output budget so the model genuinely expands.
_LENGTH_DETAIL_RE = re.compile(
    r"\b("
    r"d[ée]taille[rz]?|d[ée]taill[ée]e?s?|d[ée]velopp[a-z]*|approfond[a-z]*|"
    r"plus\s+(?:long|d[ée]taill[ée]e?s?|complet|exhaustif)|"
    r"\d+\s*fois\s+plus|r[ée]ponse\s+plus\s+longue|"
    r"expand|elaborate|longer|more\s+detail|in\s+detail|comprehensive"
    r")\b",
    re.IGNORECASE,
)

_CITATION_RE = re.compile(r"\[(\d{1,2})\]")

_ANDRITZ_CONTACT_QUERY_RE = re.compile(
    r"\b("
    r"contact|contacter|contactez|coordonn[ée]es|support|assistance|"
    r"repr[ée]sentant|email|e-mail|mail|t[ée]l[ée]phone|phone|qui\s+appeler"
    r")\b",
    re.IGNORECASE,
)

_ANDRITZ_CONTACT_FOOTER_RE = re.compile(
    r"""
    (?:\s*(?:[-*]\s*)?)?
    (?:
        (?:
            (?:si\s+vous\s+(?:souhaitez|voulez|avez\s+besoin\s+de)[^\n.!?]{0,180})
            |(?:pour\s+(?:plus|toute|davantage)[^\n.!?]{0,180})
            |(?:for\s+(?:more|additional|further)[^\n.!?]{0,180})
            |(?:if\s+you\s+(?:need|want|would\s+like)[^\n.!?]{0,180})
        )
        (?:merci\s+de\s+|veuillez\s+|please\s+)?
        (?:contacter|contactez|contact|sollicitez|adressez-vous\s+a|reach\s+out\s+to)
        [^\n.!?]{0,240}\bandritz\b[^\n.!?]*
        |
        (?:merci\s+de\s+|veuillez\s+|please\s+)?
        (?:contacter|contactez|contact|sollicitez|adressez-vous\s+a|reach\s+out\s+to)
        [^\n.!?]{0,240}\bandritz\b[^\n.!?]{0,120}
        \b(?:information|informations|renseignement|renseignements|details|support|assistance|representant)\b
        [^\n.!?]*
    )
    (?:\s*\[\d{1,2}\])?
    [.!?]?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

_ANDRITZ_CONTACT_STREAM_TAIL_CHARS = 480

# A turn is only treated as a standalone (retrieval) question when it carries
# enough signal. Very short pronoun/instruction-only turns in an ongoing
# conversation are follow-ups even when they don't match the meta regex.
_MIN_STANDALONE_QUERY_WORDS = 4


def _conversation_history(request: dict[str, Any]) -> list[dict[str, Any]]:
    """Return prior conversation turns supplied by the chat endpoint."""
    context = request.get("context") if isinstance(request.get("context"), Mapping) else {}
    history = context.get("conversation_history") if isinstance(context, Mapping) else None
    if not isinstance(history, list):
        return []
    turns: list[dict[str, Any]] = []
    for item in history:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        # "system" turns are condensed-history summaries injected by the
        # memory manager when older turns exceed the token budget.
        if role in ("user", "assistant", "system") and content:
            turns.append({"role": role, "content": content})
    return turns


def _trimmed_history_for_prompt(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the last few turns, length-capping all but the latest answer."""
    # A leading system turn is the condensed summary of older truncated turns;
    # it must survive the turn-count cap or long sessions lose their context.
    summary_prefix = [turn for turn in history[:1] if turn["role"] == "system"]
    body = history[1:] if summary_prefix else history
    recent = summary_prefix + body[-_HISTORY_MAX_TURNS:]
    trimmed: list[dict[str, Any]] = []
    last_assistant_index = max(
        (i for i, t in enumerate(recent) if t["role"] == "assistant"),
        default=-1,
    )
    for index, turn in enumerate(recent):
        content = turn["content"]
        # Preserve the most recent assistant answer in full so an "expand"
        # follow-up has the real text to build on; cap everything else.
        if index != last_assistant_index and len(content) > _HISTORY_TURN_MAX_CHARS:
            content = content[:_HISTORY_TURN_MAX_CHARS] + " […]"
        trimmed.append({"role": turn["role"], "content": content})
    return trimmed


def _previous_assistant_answer(history: list[dict[str, Any]]) -> str:
    for turn in reversed(history):
        if turn["role"] == "assistant":
            return turn["content"]
    return ""


def _is_meta_followup(query: str, history: list[dict[str, Any]]) -> bool:
    """Detect a meta/conversational turn that refers to the previous answer.

    Conservative: only fires when there is prior conversation, and either the
    turn matches an explicit meta/length instruction or it is too short to be a
    standalone retrieval question (pronoun/instruction-only). Non-follow-up
    questions ("de quelle documentation disposes-tu ?") never match.
    """
    text = str(query or "").strip()
    if not text or not _previous_assistant_answer(history):
        return False
    # A project/machine reference makes this a standalone retrieval turn even
    # when it starts with a meta verb.  For example, ``résume`` alone should
    # reuse the previous answer, while ``résume BAO100`` must query BAO100
    # instead of silently recycling the preceding project's context.
    if has_reference(text):
        return False
    if _META_FOLLOWUP_RE.search(text):
        return True
    word_count = len(re.findall(r"\w+", text))
    if word_count < _MIN_STANDALONE_QUERY_WORDS and "?" not in text:
        return True
    return False


def _cited_source_indices(text: str) -> set[int]:
    return {int(match) for match in _CITATION_RE.findall(text or "")}


def _fold_for_policy(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in folded if not unicodedata.combining(ch)).lower()


def _query_requests_contact_info(query: str) -> bool:
    return bool(_ANDRITZ_CONTACT_QUERY_RE.search(_fold_for_policy(query)))


def _strip_andritz_contact_boilerplate(text: str, *, allow_contact_answer: bool = False) -> str:
    """Remove supplier-document contact footers from generated chat answers.

    Andritz manuals often contain public-facing closing boilerplate such as
    "contact Andritz for more information". In Agentium the users are already
    Andritz experts, so that footer is noise when copied as a final next step.
    We only strip it from the tail and keep explicit contact-answer turns.
    """

    if allow_contact_answer:
        return text
    stripped = (text or "").rstrip()
    if not stripped:
        return text or ""
    previous = None
    while stripped and stripped != previous:
        previous = stripped
        stripped = _ANDRITZ_CONTACT_FOOTER_RE.sub("", stripped).rstrip()
    return stripped


class _AndritzContactBoilerplateStreamFilter:
    """Hold a small response tail so copied contact footers never flash in chat."""

    def __init__(self, *, enabled: bool = True, tail_chars: int = _ANDRITZ_CONTACT_STREAM_TAIL_CHARS):
        self.enabled = enabled
        self.tail_chars = tail_chars
        self._tail = ""

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        if not self.enabled:
            return chunk
        self._tail += chunk
        if len(self._tail) <= self.tail_chars:
            return ""
        flush_to = len(self._tail) - self.tail_chars
        safe = self._tail[:flush_to]
        self._tail = self._tail[flush_to:]
        return safe

    def flush(self) -> str:
        if not self.enabled:
            tail = self._tail
            self._tail = ""
            return tail
        clean_tail = _strip_andritz_contact_boilerplate(self._tail)
        self._tail = ""
        return clean_tail

# Generic/placeholder document titles that carry no information for an end
# user. When the extracted title matches one of these we fall back to the
# real filename so a source card reads "spare part list ACO140 ind a.xls"
# instead of "Document1" / "Untitled document" / "Documentation".
_PLACEHOLDER_TITLE_RE = re.compile(
    r"^(?:document\s*\d*|untitled(?:\s+document)?|documentation|sans\s+titre|"
    r"nouveau\s+document|new\s+document|titre|title)$",
    re.IGNORECASE,
)

# Synthetic "analysis evidence" chunks are prefixed with a bureaucratic
# locator header ("Document analysis evidence: <type>; file=...; locator=...."
# / "Table analysis evidence: <label> = <value>; file=...; ...."). The real
# fact text follows that header. We strip the header for the UI snippet so the
# source card shows the actual passage instead of the metadata blurb.
_EVIDENCE_PREFIX_RE = re.compile(
    r"^(?:document|table)\s+analysis\s+evidence:\s*.*?\.\s+",
    re.IGNORECASE | re.DOTALL,
)

# Source rows that are advisory background (Knowledge Guides), not citable
# end-user documents. They stay in the prompt as context but are excluded from
# the numbered Sources panel so internal plumbing never reads as a citation.
_ADVISORY_SOURCE_TYPES = {"knowledge_guide"}
# Synthetic evidence rows derived from structured facts. They are useful in the
# prompt, but when a real retrieved passage exists for the same document/page
# we prefer the passage so the model and the panel see actual text.
_EVIDENCE_SOURCE_TYPES = {"document_analysis", "table_analysis"}

# Upper bound on distinct passages kept per document and overall, so one noisy
# multi-page PDF (or cross-collection copies) cannot flood the Sources panel.
_MAX_PASSAGES_PER_DOCUMENT = 3
_MAX_CITABLE_SOURCES = 8
_MAX_SYNTHESIS_CONTEXT_SOURCES = 16


def _meta_source_type(meta: dict[str, Any]) -> str:
    return str(meta.get("source_type") or meta.get("type") or "").strip().lower()


def _is_expert_fiche_meta(meta: dict[str, Any]) -> bool:
    """Validated expert-correction fiche, keyed on the capture/publish markers.

    Mirrors ``retrieval_policy.is_expert_fiche_metadata`` so the answer profile
    recognises the same authoritative sources the pin/boost act on.
    """
    if _meta_source_type(meta) == "expert_fiche":
        return True
    return str(meta.get("origin") or "").strip().lower() == "chat_correction"


def _is_advisory_meta(meta: dict[str, Any]) -> bool:
    return (
        _meta_source_type(meta) in _ADVISORY_SOURCE_TYPES
        or str(meta.get("retrieval_role") or "").strip().lower() == "advisory_context"
    )


def _is_evidence_meta(meta: dict[str, Any]) -> bool:
    return _meta_source_type(meta) in _EVIDENCE_SOURCE_TYPES


def _is_placeholder_title(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    return bool(_PLACEHOLDER_TITLE_RE.match(text))


def _filename_display(filename: Any) -> str:
    """Return a human-friendly filename, unwrapping archive-flattened names.

    Promoted archive members carry names like
    ``Manual_BBA120__Spare part list__Spare Parts List_BBA120.pdf`` where
    ``__`` joins the inner path segments. We keep the final segment so the
    card shows the real file rather than the archive path.
    """
    name = str(filename or "").strip()
    if not name:
        return ""
    for separator in ("__", "/", "\\"):
        if separator in name:
            name = name.split(separator)[-1]
    return name.strip()


def _display_title(meta: dict[str, Any]) -> str:
    """Resolve a recognizable title, falling back past known placeholders."""
    for key in ("title", "document_title"):
        value = str(meta.get(key) or "").strip()
        if value and not _is_placeholder_title(value):
            return value
    filename = _filename_display(meta.get("document_filename") or meta.get("filename"))
    if filename:
        return filename
    # Nothing better than a placeholder is available — keep it rather than the
    # generic default so at least *something* is shown.
    for key in ("title", "document_title"):
        value = str(meta.get(key) or "").strip()
        if value:
            return value
    return "Untitled document"


def _document_identity(meta: dict[str, Any]) -> str:
    """Stable identity used to collapse the same underlying file.

    The same file promoted into two collections gets distinct ``document_id``
    values, so the normalized filename is the most reliable cross-collection
    key. We only fall back to ids/paths when no filename is available.
    """
    filename = _filename_display(meta.get("document_filename") or meta.get("filename"))
    if filename:
        return f"file:{filename.lower()}"
    for key in ("document_id", "source_path", "object_key", "url"):
        value = meta.get(key)
        if value:
            return f"{key}:{value}"
    return ""


def _passage_locator(meta: dict[str, Any]) -> str:
    """Best-effort intra-document locator used to keep distinct passages."""
    for key in (
        "page",
        "cell_ref",
        "cell_range",
        "sheet_name",
        "section_path",
        "paragraph_index",
        "chunk_index",
    ):
        value = meta.get(key)
        if value not in (None, ""):
            return f"{key}={value}"
    return ""


def _clean_source_snippet(chunk: Any) -> str:
    text = str(chunk or "").strip()
    stripped = _EVIDENCE_PREFIX_RE.sub("", text, count=1).strip()
    return (stripped or text)[:200]


def _select_citation_entries(
    chunks: list[Any],
    scores: list[Any],
    metadatas: list[Any],
    *,
    max_per_document: int = _MAX_PASSAGES_PER_DOCUMENT,
    max_total: int = _MAX_CITABLE_SOURCES,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Partition retrieved chunks into citable sources and advisory context.

    - Knowledge Guides / advisory rows are routed to ``advisory`` so they never
      appear as numbered citations (item 1).
    - Citable rows are de-duplicated by (document identity, passage locator):
      true duplicates and near-identical cross-collection copies collapse while
      legitimately distinct pages survive (item 2).
    - On a collision a real retrieved passage beats a synthetic analysis-evidence
      summary, so the model and the panel get the actual text (item 4).
    """
    scores = scores or []
    metadatas = metadatas or []
    citable_raw: list[dict[str, Any]] = []
    advisory: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks or []):
        meta = dict(metadatas[index]) if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
        try:
            score = float(scores[index]) if index < len(scores) else 0.0
        except (TypeError, ValueError):
            score = 0.0
        entry = {"chunk": str(chunk or ""), "score": score, "meta": meta}
        if _is_advisory_meta(meta):
            advisory.append(entry)
        else:
            citable_raw.append(entry)

    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for entry in citable_raw:
        meta = entry["meta"]
        identity = _document_identity(meta)
        if identity:
            key = (identity, _passage_locator(meta))
        else:
            normalized = " ".join(entry["chunk"].split()).lower()[:200]
            key = (f"text:{normalized}", "")
        entry["_is_raw"] = not _is_evidence_meta(meta)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = entry
            order.append(key)
        elif (entry["_is_raw"], entry["score"]) > (existing["_is_raw"], existing["score"]):
            # Preserve the original display position but upgrade to the better
            # representation of the same passage.
            by_key[key] = entry

    deduped = [by_key[key] for key in order]
    capped: list[dict[str, Any]] = []
    per_document: dict[str, int] = {}
    for entry in deduped:
        identity = _document_identity(entry["meta"]) or f"_e{id(entry)}"
        seen = per_document.get(identity, 0)
        if seen >= max_per_document:
            continue
        per_document[identity] = seen + 1
        capped.append(entry)
        if len(capped) >= max_total:
            break
    return capped, advisory


def _source_entry_from(index: int, entry: dict[str, Any]) -> dict[str, Any]:
    meta = entry["meta"]
    source_type = str(meta.get("source_type") or meta.get("type") or "document")
    source_entry: dict[str, Any] = {
        "id": f"chunk-{index}",
        "type": source_type,
        "title": _display_title(meta),
        "snippet": _clean_source_snippet(entry["chunk"]),
        "relevance_score": entry.get("score", 0.0),
    }
    document_id = meta.get("document_id")
    if document_id:
        source_entry["document_id"] = document_id
    filename = meta.get("document_filename")
    if filename:
        source_entry["filename"] = filename
    page = meta.get("page")
    if page is not None:
        source_entry["page"] = page
    collection = meta.get("collection") or meta.get("collection_name")
    if collection:
        source_entry["collection"] = collection
        source_entry["collection_name"] = collection
    keywords = meta.get("document_extracted_keywords")
    if keywords:
        source_entry["keywords"] = list(keywords)[:5]
    author = meta.get("document_author")
    if author:
        source_entry["author"] = author
    num_pages = meta.get("document_num_pages")
    if num_pages is not None:
        source_entry["num_pages"] = num_pages
    return source_entry


def _normalise_project_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _query_references_project(query: str, project_code: str) -> bool:
    """True when the user query explicitly names this project code.

    The grounding header "— projet X" is only trustworthy when the user actually
    scoped the question to project X. Many generic pages (e.g.
    Filtration_vacuum_maintenance.html) are duplicated near-identically across
    dozens of project manuals, each tagged with its own project_code; surfacing
    one copy for a generic question and stamping it "— projet AKK200" mislabels
    generic content as project-specific. Gating on an explicit query mention
    keeps the header for project-scoped questions and drops it otherwise.
    """
    code = _normalise_project_token(project_code)
    if len(code) < 4:
        return False
    return code in _normalise_project_token(query)


def _assemble_context_and_sources(
    chunks: list[Any],
    scores: list[Any],
    metadatas: list[Any],
    *,
    allow_foundational_fallback: bool = False,
    source_display_k: int | None = None,
    query: str = "",
) -> tuple[str, list[dict[str, Any]], bool]:
    """Build the LLM context block and the user-facing sources in lockstep.

    The numbered context entries ``[1..N]`` correspond 1:1 to the returned
    ``sources`` list, so a citation marker the model emits can never point past
    the displayed panel (item 5). Advisory Knowledge Guides are appended as an
    explicitly non-citable trailing block.
    """
    try:
        display_limit = max(1, min(int(source_display_k or _MAX_CITABLE_SOURCES), 24))
    except (TypeError, ValueError):
        display_limit = _MAX_CITABLE_SOURCES
    selected, advisory = _select_citation_entries(
        chunks,
        scores,
        metadatas,
        max_total=max(display_limit, min(len(chunks or []), _MAX_SYNTHESIS_CONTEXT_SOURCES)),
    )
    citable = selected[:display_limit]
    additional = selected[display_limit:]

    # Flag-gated: surface validated expert fiches explicitly so the model can
    # identify the authoritative source. OFF keeps the header byte-for-byte.
    label_expert_fiche = bool(settings.rag_expert_fiche_pin_enabled)
    context_blocks: list[str] = []
    for idx, entry in enumerate(citable):
        meta = entry["meta"]
        header = f"[{idx + 1}] {_display_title(meta)}"
        page = meta.get("page")
        if page is not None:
            header = f"{header} (p. {page})"
        # Surface the project attribution so the model trusts that a source
        # belongs to the queried project even when the project code is not
        # repeated in the body text (e.g. a manufacturer datasheet filed under
        # a project's equipment folder). Only do so when the user actually named
        # the project: generic shared pages are duplicated across many project
        # manuals, so stamping an arbitrary copy's code on a non-scoped question
        # mislabels generic content as project-specific.
        project_code = str(meta.get("project_code") or "").strip()
        if project_code and _query_references_project(query, project_code):
            header = f"{header} — projet {project_code}"
        if label_expert_fiche and _is_expert_fiche_meta(meta):
            header = f"{header} (Fiche experte — validée)"
        context_blocks.append(f"{header}\n{entry['chunk']}")

    additional_blocks: list[str] = []
    for entry in additional:
        meta = entry["meta"]
        label = _display_title(meta)
        additional_blocks.append(f"- {label}\n{entry['chunk']}")

    advisory_blocks: list[str] = []
    for entry in advisory:
        meta = entry["meta"]
        label = _display_title(meta)
        version = meta.get("guide_version")
        if version:
            label = f"{label} (Knowledge guide v{version})"
        advisory_blocks.append(f"- {label}\n{entry['chunk']}")

    if context_blocks or advisory_blocks:
        sections = list(context_blocks)
        if additional_blocks:
            sections.append(
                "Additional retrieved context (use for synthesis, do not cite by number):\n"
                + "\n\n".join(additional_blocks)
            )
        if advisory_blocks:
            sections.append(
                "Advisory context (background only — do not cite these as sources):\n"
                + "\n\n".join(advisory_blocks)
            )
        context_text = "\n\n".join(sections)
    else:
        context_text = (
            "No document was retrieved for this turn."
            if allow_foundational_fallback
            else "No documents found in the knowledge base."
        )

    sources = [_source_entry_from(idx, entry) for idx, entry in enumerate(citable)]
    return context_text, sources, bool(citable or additional or advisory)


def _format_project_inventory_block(inventory: Any) -> str:
    """Render the exhaustive project_code facet aggregation for the prompt.

    For a transversal_inventory "which projects use <equipment>" question the
    retrieval layer attaches a deterministic, complete project list (computed by
    faceting the indexed project metadata, not sampled from the few retrieved
    excerpts). We surface it as an authoritative context block so the model can
    return the full deduplicated list instead of enumerating from excerpts.
    """
    if not isinstance(inventory, Mapping):
        return ""
    projects = inventory.get("projects")
    if not isinstance(projects, list) or not projects:
        return ""
    terms = [str(term) for term in (inventory.get("terms") or []) if str(term).strip()]
    term_label = " + ".join(terms) if terms else "l'équipement demandé"
    try:
        total = int(inventory.get("total_projects") or len(projects))
    except (TypeError, ValueError):
        total = len(projects)
    entries: list[str] = []
    for project in projects:
        if not isinstance(project, Mapping):
            continue
        code = str(project.get("project_code") or "").strip()
        if not code:
            continue
        try:
            count = int(project.get("chunk_count") or 0)
        except (TypeError, ValueError):
            count = 0
        entries.append(f"{code} ({count})" if count > 0 else code)
    if not entries:
        return ""
    return (
        f"Inventaire projets consolidé (couverture exhaustive établie sur l'ensemble "
        f"du corpus indexé pour « {term_label} ») — {total} projet(s) au total. "
        f"Liste complète ci-dessous ; le nombre entre parenthèses indique le volume "
        f"de documentation associée à chaque projet :\n" + ", ".join(entries)
    )


def _retrieval_synthesis_brief(
    chunks: list[Any],
    metadatas: list[Any],
    *,
    max_points: int = 5,
) -> str:
    """Compact extractive brief used to nudge first answers toward synthesis.

    This is intentionally deterministic and cheap: it summarizes coverage and
    gives the LLM a few readable excerpts before generation, without adding a
    second model call.
    """
    if not chunks:
        return ""
    docs: set[str] = set()
    collections: set[str] = set()
    kinds: dict[str, int] = {}
    points: list[str] = []
    metadatas = metadatas or []
    for index, chunk in enumerate(chunks):
        meta = dict(metadatas[index]) if index < len(metadatas) and isinstance(metadatas[index], Mapping) else {}
        title = _display_title(meta)
        docs.add(title)
        collection = str(meta.get("collection") or meta.get("collection_name") or "").strip()
        if collection:
            collections.add(collection)
        kind = str(meta.get("source_type") or meta.get("document_type") or meta.get("semantic_type") or "document")
        kinds[kind] = kinds.get(kind, 0) + 1
        text = " ".join(str(chunk or "").split())
        if text and len(points) < max_points:
            points.append(f"- {title}: {text[:360]}")
    kind_line = ", ".join(f"{key}: {value}" for key, value in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0])))
    lines = [
        f"Coverage: {len(chunks)} retrieved chunk(s), {len(docs)} distinct source title(s)"
        + (f", collections: {', '.join(sorted(collections))}" if collections else "")
        + ".",
        f"Retrieved source types: {kind_line or 'unknown'}.",
        "Representative content:",
        *points,
    ]
    return "\n".join(lines)

SYSTEM_PROMPT = """You are an intelligent assistant with access to a curated knowledge base.

Answer questions accurately and concisely using the retrieved context.
When the context contains relevant information, cite it specifically.
If no relevant context is available, say so clearly rather than guessing.
Do not reproduce generic supplier-document footers such as "contact Andritz for more information" as advice in the chat; Agentium users in the Andritz workspace are already Andritz experts.

Be professional, precise, and helpful."""

BALANCED_GROUNDING_APPENDIX = """Grounding policy for this turn:
- Use the retrieved context first whenever it contains the answer, and lead with the answer itself.
- If the retrieved context does not contain the answer and the user asks for advice, explanation, drafting, planning or general reasoning, you may answer from general professional knowledge.
- When you answer from general knowledge rather than from a document, mark it in one short, natural French sentence such as "Aucun document disponible ne traite ce point ; voici une analyse generale a valider :" — then give the analysis directly.
- Never use internal platform vocabulary in the answer (for example "source workspace", "workspace", "base", "collection", "chunk", "retrieval"); speak as a domain expert citing documents, not the platform.
- Do not cite sources unless they are present in the provided context.
- For document-specific facts, figures, references, project relationships or operational claims, do not invent: state plainly that the available documentation does not cover the point, then offer a concrete next step (which document or reference would let you answer).
- Keep a concise advisory tone and do not open with a source-finding preamble."""


def _grounding_policy_from_request(request: dict[str, Any]) -> dict[str, Any]:
    policy = request.get("grounding_policy")
    if isinstance(policy, dict):
        mode = str(policy.get("mode") or "strict").lower()
        return {
            **policy,
            "mode": "balanced" if mode == "balanced" else "strict",
            "allow_foundational_fallback": bool(policy.get("allow_foundational_fallback") and mode == "balanced"),
        }
    return {
        "requested_mode": "strict" if str(request.get("grounding_mode") or "").lower() == "strict" else None,
        "mode": "strict",
        "allow_foundational_fallback": False,
        "source_requirement": "workspace_required",
        "reason": "agent_default_strict",
        "fallback_disclaimer": "",
    }


def _system_prompt_with_grounding(base_prompt: str, grounding_policy: dict[str, Any]) -> str:
    if grounding_policy.get("mode") != "balanced":
        return base_prompt
    return f"{base_prompt}\n\n{BALANCED_GROUNDING_APPENDIX}"


def _build_rag_user_prompt(
    *,
    query: str,
    context_text: str,
    keyword_hint: str,
    grounding_policy: dict[str, Any],
    has_retrieved_context: bool,
    retrieval_policy_prompt: str = "",
    retrieval_constraints: dict[str, Any] | None = None,
    retrieval_summary: str = "",
    answer_policy_prompt: str = "",
    has_expert_fiche: bool = False,
) -> str:
    if grounding_policy.get("mode") == "balanced" and not has_retrieved_context:
        fallback_disclaimer = (
            grounding_policy.get("fallback_disclaimer")
            or "Je n'ai pas de source workspace sur ce point ; analyse generale a valider :"
        )
        grounding_instructions = f"""
Grounding instructions:
No workspace source was retrieved for this turn.
If the request is advisory, explanatory, drafting, planning, or general reasoning, answer from general knowledge and start with: "{fallback_disclaimer}"
If the request asks for workspace facts, documents, live/current state, numbers, security/OSINT, agenda, actions, or operational claims, do not invent; say the workspace source is missing and propose a safe next step.
Do not include citation markers like [1] because no source was retrieved."""
    elif grounding_policy.get("mode") == "balanced":
        grounding_instructions = """
Grounding instructions:
Use the workspace context as the source of factual claims and cite retrieved sources by [number] when relevant.
Do not write raw filename or chapter references in brackets such as [menu.html] or [I.2.html]; use the numeric source id instead.
You may add general advisory framing only when it is clearly separated from sourced facts.
Do not invent citations."""
    else:
        grounding_instructions = """
Grounding instructions:
Answer using the context above. Cite sources by their [number] when relevant.
Do not write raw filename or chapter references in brackets such as [menu.html] or [I.2.html]; use the numeric source id instead.
Each source may be labelled with its project (e.g. "projet AKK200"); treat that label as the authoritative project attribution even when the project code is not repeated in the body text, and do not describe such a source as generic or unrelated to that project.
If the context is not relevant or missing, say so clearly rather than guessing."""

    constraint_lines: list[str] = []
    retrieval_constraints = retrieval_constraints or {}
    missing_terms = retrieval_constraints.get("missing_terms") or []
    required_terms = retrieval_constraints.get("required_terms") or []
    if missing_terms:
        constraint_lines.append(
            "Retrieval constraint: the user asked for exact reference(s) "
            f"{', '.join(str(term) for term in required_terms)}, but no retrieved document chunk matched "
            f"{', '.join(str(term) for term in missing_terms)}."
        )
        constraint_lines.append(
            "Do not answer from other projects or similar documents as if they applied. "
            "State clearly that no indexed source was found for the exact reference, then mention any visible gap or next check."
        )
    policy_parts = [part for part in [retrieval_policy_prompt, "\n".join(constraint_lines)] if part]
    policy_body = "\n".join(policy_parts)
    policy_instructions = f"\n\n{policy_body}" if policy_body else ""

    summary_block = f"\n\nRetrieved content synthesis brief:\n{retrieval_summary}" if retrieval_summary else ""
    answer_policy_block = f"\n\n{answer_policy_prompt}" if answer_policy_prompt else ""

    # Source conflict / ambiguity posture (3 cases). The generic doc↔doc conflict
    # rule (case 1) lives in the industrial answer policy (answer_policy_prompt)
    # and the "too thin or contradictory ... name the gap" line below applies to
    # every turn. When a validated expert fiche is present (flag-gated, see
    # has_expert_fiche) the expert answer is given FIRST and any differing
    # document is flagged as outdated / to verify (case 2); conflicting fiches
    # from several experts carry equal weight and fall back to the same ambiguity
    # handling (case 3). With no fiche the block is byte-for-byte the pre-change
    # prompt (non-regression).
    answer_shaping_lines = [
        "Answer-shaping instructions:",
        "- Start with the direct factual answer or synthesis; do not open with discovery phrases such as \"I found\" or \"the documents indicate\".",
        "- Include useful evidence/citations after the answer when workspace sources exist.",
        "- For broad questions, synthesize by theme instead of listing every retrieved excerpt; use 3 to 5 key points only when useful.",
        "- If the retrieved content is too thin or contradictory, say that explicitly and name the gap.",
        "- Follow the active industrial answer profile: precise facts must stay short; summaries must be structured and complete; inventories must not be presented as exhaustive unless the evidence supports that.",
        "- Do not mention internal mechanics such as chunks, scores, vector search, model names, database names, RAG/LLM engines, confidence rates or retrieval methods in the user-facing answer.",
        "- Do not end with generic document boilerplate asking the user to contact Andritz or an Andritz representative for more information, unless the user explicitly asked for contact details.",
    ]
    if has_expert_fiche:
        answer_shaping_lines.append(
            "- Une réponse validée par un expert (fiche experte, repérable au libellé "
            "« (Fiche experte — validée) ») est présente : donne d'abord cette réponse en "
            "précisant qu'elle provient d'un expert, puis, si un document du contexte donne "
            "une autre valeur pour le même point, indique que cette documentation est "
            "obsolète / à faire vérifier "
            "(ex. : « La réponse est … (source : expert …). Par contre, la documentation "
            "indique … qui est donc à faire vérifier. »)."
        )
        answer_shaping_lines.append(
            "- Si plusieurs fiches expertes se contredisent sur le même point, elles ont le "
            "même poids : n'en privilégie aucune arbitrairement, signale le désaccord entre "
            "experts et cite chaque valeur avec sa source."
        )
    answer_shaping = "\n".join(answer_shaping_lines)

    return f"""User message:
{query}

Knowledge base context:
{context_text}{keyword_hint}{summary_block}
{policy_instructions}
{grounding_instructions}
{answer_policy_block}

{answer_shaping}"""


def _build_followup_user_prompt(*, query: str, wants_more_detail: bool) -> str:
    """Prompt for meta/follow-up turns that operate on the previous answer.

    No fresh retrieval ran for these turns, so the model must rely on the
    conversation history (provided as prior messages) instead of declaring it
    "lacks context". We never attach sources to these turns.
    """
    length_clause = (
        "Provide a substantially longer, more detailed and thorough version. "
        "Expand each point, add structure (headings/lists), examples and useful "
        "elaboration grounded in what was already established. "
        if wants_more_detail
        else "Apply the instruction faithfully. "
    )
    return f"""The user is giving a follow-up instruction about your PREVIOUS answer in this conversation (see the messages above): "{query}".

Apply it to your previous answer. {length_clause}Answer in the same language as the user.
Do NOT say that you lack context or sources — the relevant material is your own previous answer in this conversation. Do NOT ask the user to repeat their question.
Do not invent new citation markers like [1]; only reuse facts already established above."""


class OmniRAGAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            agent_id="rag",
            name="RAG Agent",
            agent_type="rag",
        )
        self._llm = None
        # Cache DocumentService instances by (workspace_slug, collection, vector_db_type)
        # so we don't rebuild retrieval helpers on every request, but still keep
        # each tenant's index isolated. A single shared instance (the pre-D8
        # behaviour) routed every workspace to the same unscoped collection and
        # never honored the per-workspace `ragVectorDBType` preset — drop-and-ask
        # uploads and chat could land in different vector stores.
        self._document_services: dict[tuple[str | None, str, str], Any] = {}

    async def initialize(self) -> None:
        self.status = "active"
        logger.info("Procurement agent initialized")

    def _get_llm(self):
        if self._llm is None:
            from app.llm.llm import LLM

            self._llm = LLM(
                provider=settings.default_provider,
                api_key=settings.openai_api_key,
            )
        return self._llm

    def _get_document_service(self, request: dict[str, Any] | None = None):
        """Return a DocumentService scoped to the request's workspace.

        Resolution order for ``vector_db_type`` / ``collection_name``:
          1. The workspace's resolved RAG preset (`get_resolved_settings`).
          2. Static defaults (`qdrant` / `documents`) — matches
             ``_get_default_settings`` and keeps upload and retrieval
             symmetric.

        ``workspace_slug`` is taken verbatim from the request so that the
        vector DB factory can prefix the collection with
        ``<slug>__``, giving the same isolation the dropzone upload path
        already uses.
        """
        from app.services.rag.document_service import DocumentService
        from app.services.rag.context import get_retrieval_profile

        request = request or {}
        workspace_slug = request.get("workspace_slug")
        profile = get_retrieval_profile(request)
        collection_name = profile.get("collection", "documents")
        vector_db_type = profile.get("vector_db", "qdrant")

        cache_key = (workspace_slug, collection_name, vector_db_type)
        svc = self._document_services.get(cache_key)
        if svc is not None:
            return svc

        try:
            svc = DocumentService(
                collection_name=collection_name,
                vector_db_type=vector_db_type,
                workspace_slug=workspace_slug,
            )
            self._document_services[cache_key] = svc
            logger.info(
                "rag_agent: DocumentService ready",
                workspace_slug=workspace_slug,
                collection=collection_name,
                vector_db=vector_db_type,
            )
            return svc
        except Exception as e:
            logger.warning(
                "Document service init failed, RAG disabled",
                error=str(e),
                workspace_slug=workspace_slug,
            )
            return None

    async def process(self, request: dict[str, Any]) -> AsyncGenerator[dict[str, Any], None]:
        query = request.get("query", "")
        rewritten = request.get("rewritten_query", query)
        prefs = request.get("agent_preferences", {}).get("model_preferences", {})
        model_name = prefs.get("model", settings.default_model)
        temperature = request.get("temperature", 0.3)
        custom_system_prompt = request.get("system_prompt")
        grounding_policy = _grounding_policy_from_request(request)
        system_prompt = _system_prompt_with_grounding(custom_system_prompt or SYSTEM_PROMPT, grounding_policy)
        pipeline_start = time.time()

        # Conversation memory: recent turns (incl. the previous assistant
        # answer) are carried into the generation prompt so follow-ups can be
        # expanded/continued. Meta/follow-up turns ("détaille", "plus long",
        # "résume") reuse that context instead of running retrieval on the
        # short instruction (which only returned junk + spurious sources).
        conversation_history = _conversation_history(request)
        prompt_history = _trimmed_history_for_prompt(conversation_history)
        is_followup = _is_meta_followup(query, conversation_history)
        wants_more_detail = bool(_LENGTH_DETAIL_RE.search(query or ""))
        if is_followup:
            logger.info(
                "rag_agent: follow-up turn — reusing conversation context, skipping retrieval",
                query=query[:120],
                history_turns=len(conversation_history),
            )

        uid = id(query)

        # ── Step 1: Query Received ──
        step_start = time.time()
        sid = f"query-received-{uid}"
        yield self._step(
            sid,
            "active",
            "query_received",
            "QueryReceiver",
            model_name,
            "Receiving and parsing query",
            f'Input: "{query[:120]}"',
        )
        await asyncio.sleep(0.03)
        is_question = any(query.strip().endswith(c) for c in ["?", "？"]) or any(
            query.lower().startswith(w)
            for w in [
                "what ",
                "which ",
                "how ",
                "who ",
                "when ",
                "where ",
                "why ",
                "is ",
                "are ",
                "can ",
                "do ",
                "does ",
            ]
        )
        intent = "Q&A / Question" if is_question else "Document / Data Processing"
        yield self._step(
            sid,
            "completed",
            "query_received",
            "QueryReceiver",
            model_name,
            "Query received",
            f"Intent: {intent} · Length: {len(query)} chars",
            duration=self._ms_since(step_start),
        )

        # ── Step 2: Query Rewrite ──
        step_start = time.time()
        sid = f"query-rewrite-{uid}"
        yield self._step(
            sid,
            "active",
            "query_rewrite",
            "QueryRewriter",
            "gpt-4o-mini",
            "Rewriting query for optimal retrieval",
            f'Original: "{query[:80]}…"',
        )

        has_rewrite = rewritten != query
        await asyncio.sleep(0.02)
        yield self._step(
            sid,
            "completed",
            "query_rewrite",
            "QueryRewriter",
            "gpt-4o-mini",
            "Query rewritten" if has_rewrite else "Query kept as-is",
            f'Rewritten: "{rewritten[:100]}"'
            if has_rewrite
            else "No rewrite needed — query already well-formed",
            duration=self._ms_since(step_start),
        )

        # ── Step 3: Embedding Generation ──
        step_start = time.time()
        sid = f"embedding-{uid}"
        yield self._step(
            sid,
            "active",
            "embedding",
            "Embedder",
            "text-embedding-3-small",
            "Generating query embeddings",
            "Dimension: 1536 · Model: text-embedding-3-small",
        )
        await asyncio.sleep(0.04)
        yield self._step(
            sid,
            "completed",
            "embedding",
            "Embedder",
            "text-embedding-3-small",
            "Query embedded",
            "Vector generated — ready for similarity search",
            duration=self._ms_since(step_start),
        )

        # ── Step 4: Knowledge Retrieval (inline or worker-backed) ──
        from app.services.rag.context import (
            await_rag_retrieval_task,
            dispatch_rag_retrieval_task,
            get_retrieval_profile,
            retrieval_event,
            retrieve_rag_context,
        )

        profile = get_retrieval_profile(request)
        rag_mode = profile.get("rag_mode")
        collections = profile.get("collections") or [profile["collection"]]
        is_multi_collection = len(collections) > 1
        doc_svc = (
            None
            if is_followup or settings.rag_retrieval_worker_enabled or is_multi_collection
            else self._get_document_service(request)
        )
        mode_label = "planner_pending"
        if is_multi_collection:
            mode_reason = f"Knowledge Scope {profile.get('knowledge_scope') or 'workspace_default'} across {len(collections)} collections"
        else:
            mode_reason = "CorpusPlanner will infer system scope and dense/sparse policy before retrieval."
        budget_line = (
            f"candidate_pool_k: {profile.get('candidate_pool_k')} · "
            f"synthesis_k: {profile.get('synthesis_k')} · "
            f"sources: {profile.get('source_display_k')}"
        )
        retriever_name = "PlannerBoundedRetriever"
        retriever_title = profile.get("scope_label") or "Budget-aware retrieval"
        method_line = (
            "Method: planner selects inventory, facts, summaries, dense and sparse layers "
            f"under latency budget · {budget_line}"
        )

        step_start = time.time()
        sid = f"kb-retrieval-{uid}"
        retrieval_task_id = None
        retrieval_fallback = False
        base_retrieval_details = {
            "collection": profile["collection"],
            "collections": collections,
            "scope": profile.get("knowledge_scope"),
            "scope_label": profile.get("scope_label"),
            "collections_touched": collections,
            "vector_db": profile["vector_db"],
            "top_k": profile["top_k"],
            "candidate_pool_k": profile.get("candidate_pool_k"),
            "synthesis_k": profile.get("synthesis_k"),
            "source_display_k": profile.get("source_display_k"),
            "retrieval_profile": profile.get("retrieval_profile"),
            "latency_profile": profile.get("latency_profile"),
            "latency_budget": profile.get("latency_budget")
            or {
                "profile": profile.get("latency_profile"),
                "deadline_seconds": profile.get("deadline_seconds"),
                "candidate_pool_k": profile.get("candidate_pool_k"),
                "top_k": profile.get("top_k"),
            },
            "pipeline": "planner_pending",
            "requested_mode": rag_mode or "auto",
            "planner_preview_mode": mode_label,
            "task_id": None,
            "grounding_mode": grounding_policy.get("mode"),
            "grounding_policy": grounding_policy,
        }
        if is_followup:
            yield self._step(
                sid,
                "active",
                "retrieve",
                "ConversationMemory",
                "Follow-up — reusing conversation context",
                "Follow-up instruction detected",
                "Reusing the previous answer instead of retrieving new documents.",
            )
        else:
            yield self._step(
                sid,
                "active",
                "retrieve",
                retriever_name,
                retriever_title,
                "Searching knowledge base",
                f"Planner pending — {mode_reason}\n{method_line}\nQuery: \"{profile['query'][:80]}…\"",
            )
            yield retrieval_event(
                "started",
                details=base_retrieval_details,
                message="Retrieval started",
            )

        if is_followup:
            # Meta/follow-up turn ("détaille", "plus long", "résume"): the
            # instruction refers to the previous answer, not a new retrieval
            # topic. Skip retrieval entirely so we neither waste latency nor
            # surface junk chunks / spurious sources; synthesis below answers
            # from the conversation history instead.
            retrieval_context = {
                "chunks": [],
                "scores": [],
                "metadatas": [],
                "pipeline": "followup_skip",
                "metrics": {"no_context": True, "followup_skip": True},
            }
        elif settings.rag_retrieval_worker_enabled:
            try:
                async_result = dispatch_rag_retrieval_task(request)
                retrieval_task_id = async_result.id
                yield retrieval_event(
                    "started",
                    details={**base_retrieval_details, "task_id": retrieval_task_id},
                    message="Retrieval worker dispatched",
                )
                retrieval_context = await await_rag_retrieval_task(
                    async_result,
                    settings.rag_retrieval_worker_timeout_seconds,
                )
                retrieval_context.setdefault("metrics", {})
                retrieval_context["metrics"]["task_id"] = retrieval_task_id
            except TimeoutError as exc:
                retrieval_fallback = True
                logger.warning("RAG retrieval worker timed out", error=str(exc))
                yield retrieval_event(
                    "timeout",
                    details={**base_retrieval_details, "task_id": retrieval_task_id},
                    message="Retrieval worker timed out; returning bounded partial context",
                )
                retrieval_context = {
                    "chunks": [],
                    "scores": [],
                    "metadatas": [],
                    "pipeline": "retrieval_timeout",
                    "label": "Retrieval deadline",
                    "reason": "Retrieval worker exceeded its latency budget.",
                    "detail": "Deep Retrieval can continue asynchronously without blocking the chat stream.",
                    "metrics": {
                        "no_context": True,
                        "fallback": True,
                        "fallback_reason": "worker_timeout",
                        "task_id": retrieval_task_id,
                        "deep_retrieval_recommended": True,
                    },
                    "deep_retrieval_recommended": True,
                }
            except Exception as exc:  # noqa: BLE001
                retrieval_fallback = True
                logger.warning("RAG retrieval worker failed", error=str(exc))
                yield retrieval_event(
                    "error",
                    details={
                        **base_retrieval_details,
                        "task_id": retrieval_task_id,
                        "error": str(exc),
                    },
                    message="Retrieval worker failed; returning bounded partial context",
                )
                retrieval_context = {
                    "chunks": [],
                    "scores": [],
                    "metadatas": [],
                    "pipeline": "retrieval_error",
                    "label": "Retrieval worker error",
                    "reason": "Retrieval worker failed before returning context.",
                    "detail": str(exc),
                    "metrics": {
                        "no_context": True,
                        "fallback": True,
                        "fallback_reason": "worker_error",
                        "task_id": retrieval_task_id,
                        "deep_retrieval_recommended": True,
                    },
                    "deep_retrieval_recommended": True,
                }
        else:
            retrieval_context = await retrieve_rag_context(request, doc_svc=doc_svc)

        retrieval_context.setdefault("metrics", {})
        retrieval_context["metrics"]["task_id"] = retrieval_task_id
        retrieval_context["metrics"]["fallback"] = bool(
            retrieval_context["metrics"].get("fallback") or retrieval_fallback
        )
        n_chunks = len(retrieval_context["chunks"])
        scores = retrieval_context.get("scores", [])
        top_score = f"{scores[0]:.3f}" if scores else "—"
        actual_pipeline = str(retrieval_context.get("pipeline") or "")
        actual_dense_policy = str(
            retrieval_context.get("dense_policy")
            or (retrieval_context.get("metrics") or {}).get("dense_policy")
            or ""
        )
        if actual_pipeline.startswith("multi_"):
            done_method = "Knowledge Scope multi-collection RRF"
        elif actual_pipeline == "hah_backend":
            done_method = "HAH layered retrieval + RRF"
        elif actual_pipeline == "chah_backend":
            done_method = "C-HAH composite retrieval + RRF"
        elif actual_pipeline == "collection_inventory":
            done_method = "SQL inventory"
        elif actual_pipeline == "dense_coarse_inventory":
            done_method = "Dense-corpus guardrail inventory"
        elif actual_dense_policy.startswith("fast_scoped_dense") or actual_pipeline == "naive":
            done_method = "Payload-filtered dense retrieval"
        elif actual_pipeline == "hybrid":
            done_method = "Budget-aware sparse+dense retrieval"
        else:
            done_method = "Planner-bounded retrieval"
        actual_retriever_name = "PlannerBoundedRetriever"
        actual_retriever_title = retrieval_context.get("label") or retriever_title
        if actual_pipeline.startswith("multi_"):
            actual_retriever_name = "KnowledgeScopeRetriever"
            actual_retriever_title = profile.get("scope_label") or "Knowledge Scope"
        elif actual_pipeline == "hah_backend":
            actual_retriever_name = "HAHBackendRetriever"
            actual_retriever_title = "HAH layered retrieval"
        elif actual_pipeline == "chah_backend":
            actual_retriever_name = "CHAHBackendRetriever"
            actual_retriever_title = "C-HAH composite retrieval"
        elif actual_pipeline in {"collection_inventory", "dense_coarse_inventory"}:
            actual_retriever_name = "InventoryRetriever"
            actual_retriever_title = "SQL inventory / diagnostics"
        elif actual_dense_policy.startswith("fast_scoped_dense") or actual_pipeline == "naive":
            actual_retriever_name = "VectorRetriever"
            actual_retriever_title = "Payload-filtered dense retrieval"
        elif actual_pipeline == "hybrid":
            actual_retriever_name = "SparseDenseRetriever"
            actual_retriever_title = "Budget-aware sparse + dense retrieval"

        done_detail = (
            f"Top score: {top_score} · {done_method}"
            if n_chunks
            else (
                "No workspace context found — balanced general fallback allowed"
                if grounding_policy.get("allow_foundational_fallback")
                else "No documents in knowledge base — using built-in rules"
            )
        )
        if n_chunks and retrieval_context.get("detail"):
            done_detail = f"{done_detail}\n{retrieval_context['detail']}"

        if is_followup:
            yield self._step(
                sid,
                "completed",
                "retrieve",
                "ConversationMemory",
                "Follow-up — reusing conversation context",
                "Using previous answer",
                "Follow-up/meta instruction — answered from conversation memory; retrieval skipped.",
                duration=self._ms_since(step_start),
            )
        else:
            yield self._step(
                sid,
                "completed",
                "retrieve",
                actual_retriever_name,
                actual_retriever_title,
                f"Retrieved {n_chunks} chunks",
                done_detail,
                duration=self._ms_since(step_start),
                scores=scores[:5],
            )
            yield retrieval_event(
                "completed" if n_chunks else "no_context",
                details={
                    **base_retrieval_details,
                    **(retrieval_context.get("metrics") or {}),
                    "task_id": retrieval_task_id,
                    "chunks_retrieved": n_chunks,
                    "pipeline": retrieval_context.get("pipeline"),
                    "grounding_mode": grounding_policy.get("mode"),
                    "grounding_policy": grounding_policy,
                },
                message=f"Retrieved {n_chunks} chunks" if n_chunks else "No retrieval context found",
                rag_context=retrieval_context,
            )

        # ── Step 5: Context Filtering & Reranking ──
        step_start = time.time()
        sid = f"context-filter-{uid}"
        yield self._step(
            sid,
            "active",
            "context_filtering",
            "ContextFilter",
            "text-embedding-3-small",
            "Filtering and reranking contexts",
            f"Evaluating {n_chunks} chunks for relevance…",
        )

        filtered_chunks = retrieval_context["chunks"]
        filtered_scores = scores
        filtered_metadatas = retrieval_context.get("metadatas", []) or []
        # Make sure we always have a metadata entry per chunk even if the
        # retrieval pipeline is an older build that never populated it —
        # sources/prompt paths below rely on index alignment.
        if len(filtered_metadatas) < len(filtered_chunks):
            filtered_metadatas = filtered_metadatas + [{}] * (
                len(filtered_chunks) - len(filtered_metadatas)
            )
        from app.services.rag.retrieval_policy import is_document_discovery_query

        # Document-discovery queries ("quels documents… ?") rely on the upstream
        # policy rerank to surface the specific content docs above generic
        # cover/index pages. A raw-similarity re-sort below would silently undo
        # that ordering, so we honour the policy score for this intent only and
        # leave every other query's ordering byte-for-byte unchanged.
        _discovery_intent = is_document_discovery_query(query)
        preserve_retrieval_order = str(retrieval_context.get("pipeline") or "").startswith(
            ("chah_", "hah_", "multi_")
        )
        try:
            threshold = max(0.0, min(1.0, float(getattr(settings, "rag_similarity_threshold", 0.1) or 0.1)))
        except (TypeError, ValueError):
            threshold = 0.1
        if preserve_retrieval_order:
            # HAH/C-HAH and multi-collection paths use RRF-like scores. Those
            # values are rank-combination weights, not similarity scores, and
            # can legitimately sit below the dense-search threshold. Filtering
            # them was dropping exact spreadsheet evidence while keeping only
            # high-scored advisory Knowledge Guides.
            before = after = n_chunks
        elif n_chunks > 0 and scores:
            before = n_chunks
            triples = list(zip(retrieval_context["chunks"], scores, filtered_metadatas))
            triples = [
                (c, s, m)
                for c, s, m in triples
                if s >= threshold or str(m.get("source_type") or m.get("type") or "") == "knowledge_guide"
            ]
            if not preserve_retrieval_order:
                if _discovery_intent:
                    # Honour the policy rerank (specific annex/operating-manual
                    # docs first), falling back to raw similarity as a tiebreaker.
                    triples.sort(
                        key=lambda x: (
                            float(x[2].get("retrieval_policy_score") or 0.0),
                            x[1],
                        ),
                        reverse=True,
                    )
                else:
                    triples.sort(key=lambda x: x[1], reverse=True)
            filtered_chunks = [c for c, _, _ in triples]
            filtered_scores = [s for _, s, _ in triples]
            filtered_metadatas = [m for _, _, m in triples]
            after = len(filtered_chunks)
        else:
            before = after = 0

        await asyncio.sleep(0.02)
        yield self._step(
            sid,
            "completed",
            "context_filtering",
            "ContextFilter",
            "text-embedding-3-small",
            "Context filtered",
            f"Kept {after}/{before} chunks · Threshold: {threshold:.2f} · Sorted by relevance",
            duration=self._ms_since(step_start),
        )

        # ── Step 6: Knowledge Synthesis ──
        step_start = time.time()
        sid = f"synthesis-prep-{uid}"
        yield self._step(
            sid,
            "active",
            "validation",
            "KnowledgeSynthesizer",
            model_name,
            "Preparing knowledge context",
            f"Assembling {after} chunks for synthesis…",
        )

        # Build a citation-friendly context block plus the user-facing sources
        # list in lockstep so citation markers always map to a displayed
        # source. Advisory Knowledge Guides are kept as background context but
        # excluded from the numbered sources; true duplicates / cross-collection
        # copies are collapsed; placeholder titles fall back to the filename.
        context_text, sources, has_citable_context = _assemble_context_and_sources(
            filtered_chunks,
            filtered_scores,
            filtered_metadatas,
            allow_foundational_fallback=bool(grounding_policy.get("allow_foundational_fallback")),
            source_display_k=int(retrieval_context.get("source_display_k") or (retrieval_context.get("metrics") or {}).get("source_display_k") or _MAX_CITABLE_SOURCES),
            query=str(query or ""),
        )
        retrieval_summary = _retrieval_synthesis_brief(filtered_chunks, filtered_metadatas)

        # Transversal inventory: prepend the exhaustive project list (computed by
        # faceting the indexed project metadata) so the model lists every project
        # instead of enumerating from the handful of retrieved excerpts. The
        # block is authoritative context, not a numbered citation.
        project_inventory_block = _format_project_inventory_block(
            retrieval_context.get("project_inventory")
            if isinstance(retrieval_context, Mapping)
            else None
        )
        if project_inventory_block:
            context_text = f"{project_inventory_block}\n\n{context_text}"
            has_citable_context = True

        # Aggregate docmeta TF-IDF keywords across the top chunks so the LLM
        # can anchor on document topics even when the user's query is fuzzy
        # ("c'est quoi ce doc ?"). We keep it short (top 10 unique) so it
        # adds zero cost to the prompt in normal cases and degrades
        # gracefully when docmeta didn't run (empty list).
        keyword_seen: set[str] = set()
        aggregated_keywords: list[str] = []
        for meta in filtered_metadatas[:5]:
            for kw in meta.get("document_extracted_keywords") or []:
                if not isinstance(kw, str):
                    continue
                normalised = kw.strip().lower()
                if not normalised or normalised in keyword_seen:
                    continue
                keyword_seen.add(normalised)
                aggregated_keywords.append(kw.strip())
                if len(aggregated_keywords) >= 10:
                    break
            if len(aggregated_keywords) >= 10:
                break

        keyword_hint = (
            f"\n\nDocument keywords (from TF-IDF over retrieved chunks): "
            f"{', '.join(aggregated_keywords)}"
            if aggregated_keywords
            else ""
        )

        # Detect a validated expert fiche in the assembled context (flag-gated)
        # so the answer profile treats it as reference truth without narrating a
        # contradiction. OFF leaves has_expert_fiche False -> prompt unchanged.
        has_expert_fiche = bool(settings.rag_expert_fiche_pin_enabled) and any(
            _is_expert_fiche_meta(meta)
            for meta in filtered_metadatas
            if isinstance(meta, Mapping)
        )

        if is_followup:
            user_prompt = _build_followup_user_prompt(
                query=query,
                wants_more_detail=wants_more_detail,
            )
        else:
            from app.services.industrial_answer_profile import answer_policy_prompt as _answer_policy_prompt

            user_prompt = _build_rag_user_prompt(
                query=query,
                context_text=context_text,
                keyword_hint=keyword_hint,
                grounding_policy=grounding_policy,
                has_retrieved_context=has_citable_context,
                retrieval_policy_prompt=str((retrieval_context.get("retrieval_policy") or {}).get("prompt") or ""),
                retrieval_constraints=retrieval_context.get("retrieval_constraints") or {},
                retrieval_summary=retrieval_summary,
                answer_policy_prompt=_answer_policy_prompt(
                    answer_policy=request.get("answer_policy") if isinstance(request.get("answer_policy"), dict) else None,
                    profile_decision=request.get("answer_profile_decision")
                    if isinstance(request.get("answer_profile_decision"), dict)
                    else None,
                    language=request.get("response_language"),
                ),
                has_expert_fiche=has_expert_fiche,
            )

        await asyncio.sleep(0.03)
        yield self._step(
            sid,
            "completed",
            "validation",
            "KnowledgeSynthesizer",
            model_name,
            "Context ready",
            f"{after} chunks · {len(context_text)} chars",
            duration=self._ms_since(step_start),
        )

        # ── Step 7: Response Generation (LLM synthesis, streamed) ──
        step_start = time.time()
        sid = f"synthesis-{uid}"
        yield self._step(
            sid,
            "active",
            "synthesis",
            "Synthesizer",
            model_name,
            "Generating response",
            f"Model: {model_name} · Temperature: {temperature} · Streaming…",
            has_text=True,
        )

        # Sources are gated and emitted ONCE, on the final chunk, after the
        # answer is known: a follow-up/meta turn never carries sources, and a
        # normal turn only keeps the sources the model actually grounded on
        # (cited [n] markers), so the panel never shows spurious citations on
        # conversational turns or when retrieval was irrelevant.
        # Explicit "make it longer/detailed" turns get a larger output budget
        # so the model can genuinely expand instead of being clipped.
        generation_kwargs: dict[str, Any] = {}
        if settings.rag_generation_adaptive_enabled:
            from app.services.rag.generation_budget import resolve_generation_budget

            budget = resolve_generation_budget(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                history=prompt_history,
                model=model_name,
                latency_profile=profile.get("latency_profile"),
                wants_more_detail=wants_more_detail,
            )
            max_output_tokens = budget.max_output_tokens
            if settings.rag_generation_frequency_penalty_enabled:
                generation_kwargs["frequency_penalty"] = budget.frequency_penalty
            logger.info(
                "Adaptive generation budget",
                rho=budget.rho,
                input_tokens=budget.input_tokens,
                max_output_tokens=budget.max_output_tokens,
                model_window=budget.model_window,
            )
        else:
            max_output_tokens = 4000 if wants_more_detail else 2000
        sequence = 0
        accumulated = ""
        stream_filter = _AndritzContactBoilerplateStreamFilter(
            enabled=not _query_requests_contact_info(query)
        )
        try:
            llm = self._get_llm()
            async for chunk_text in llm.stream_complete(
                prompt=user_prompt,
                model=model_name,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_output_tokens,
                history=prompt_history,
                **generation_kwargs,
            ):
                filtered_text = stream_filter.feed(chunk_text)
                if filtered_text:
                    sequence += 1
                    accumulated += filtered_text
                    yield {
                        "chunk_type": "text",
                        "content": filtered_text,
                        "delta": filtered_text,
                        "sequence": sequence,
                        "is_final": False,
                    }
        except Exception as e:
            logger.error("LLM generation failed", error=str(e))
            yield {"chunk_type": "error", "content": f"LLM generation error: {e}", "is_final": True}
            yield self._step(
                sid,
                "error",
                "synthesis",
                "Synthesizer",
                model_name,
                "Generation failed",
                str(e),
                duration=self._ms_since(step_start),
                has_text=True,
            )
            return

        final_filtered_text = stream_filter.flush()
        if final_filtered_text:
            sequence += 1
            accumulated += final_filtered_text
            yield {
                "chunk_type": "text",
                "content": final_filtered_text,
                "delta": final_filtered_text,
                "sequence": sequence,
                "is_final": False,
            }

        # Robustness: never surface an empty bubble ("(no response)"). gpt-5 can
        # occasionally return no output text (e.g. reasoning consumed the token
        # budget). Emit a short, honest fallback so the turn always says
        # something the user can act on.
        if not accumulated.strip():
            fallback_text = (
                "Je n'ai pas pu générer de réponse complète à l'instant. "
                "Pouvez-vous reformuler ou préciser votre demande ? "
                "Je peux aussi réessayer si vous renvoyez la question."
            )
            sequence += 1
            accumulated = fallback_text
            yield {
                "chunk_type": "text",
                "content": fallback_text,
                "delta": fallback_text,
                "sequence": sequence,
                "is_final": False,
            }
            logger.warning("rag_agent: empty generation — emitted non-empty fallback")

        final_sources = self._gate_sources(
            sources,
            accumulated,
            is_followup=is_followup,
            has_citable_context=has_citable_context,
            discovery_intent=_discovery_intent,
        )

        llm_duration_ms = self._ms_since(step_start)
        # Carry the gated sources on the (forwarded) synthesis-completed step:
        # the orchestrator drops empty-content text chunks, so the trailing
        # empty text chunk can't reliably deliver sources. Any chunk that
        # carries a non-empty ``sources`` list updates the front's panel, and
        # an empty list never overwrites it, so suppressed turns show none.
        completed_step = self._step(
            sid,
            "completed",
            "synthesis",
            "Synthesizer",
            model_name,
            "Response generated",
            f"{len(accumulated)} chars · {len(final_sources)} citations · {sequence} tokens streamed",
            duration=llm_duration_ms,
            has_text=True,
        )
        if final_sources:
            completed_step["sources"] = final_sources
        yield completed_step

        if not is_followup:
            retrieval_metrics = retrieval_context.setdefault("metrics", {})
            retrieval_metrics["llm_ms"] = llm_duration_ms
            stage_timings = retrieval_metrics.get("stage_timings")
            if not isinstance(stage_timings, dict):
                stage_timings = {}
            stage_timings["llm_ms"] = llm_duration_ms
            retrieval_total_ms = retrieval_metrics.get("duration_ms") or stage_timings.get("retrieval_ms")
            if retrieval_total_ms is not None:
                try:
                    stage_timings["total_ms"] = int(retrieval_total_ms) + int(llm_duration_ms)
                except (TypeError, ValueError):
                    stage_timings["total_ms"] = llm_duration_ms
            else:
                stage_timings.setdefault("total_ms", llm_duration_ms)
            retrieval_metrics["stage_timings"] = stage_timings
            yield retrieval_event(
                "observability",
                details={
                    **base_retrieval_details,
                    **retrieval_metrics,
                    "task_id": retrieval_task_id,
                    "chunks_retrieved": n_chunks,
                    "pipeline": retrieval_context.get("pipeline"),
                    "grounding_mode": grounding_policy.get("mode"),
                    "grounding_policy": grounding_policy,
                },
                message="Retrieval observability updated",
            )

        yield {
            "chunk_type": "text",
            "content": "",
            "is_final": True,
            "sequence": sequence + 1,
        }

        # ── Step 8: Quality Metrics ──
        step_start = time.time()
        sid = f"quality-metrics-{uid}"
        yield self._step(
            sid,
            "active",
            "evaluation",
            "ResponseEvaluator",
            "text-embedding-3-small",
            "Evaluating response quality",
            "Computing factuality, relevance, coherence, HHEM & latency…",
        )

        try:
            from app.services.metrics.evaluator import ResponseEvaluator

            evaluator = ResponseEvaluator()
            metrics = await evaluator.evaluate(
                query=query,
                response=accumulated,
                source_chunks=filtered_chunks[:5],
            )
        except Exception as e:
            logger.warning("Metrics evaluation failed", error=str(e))
            metrics = {
                "relevance": 0.0,
                "factuality": 0.0,
                "coherence": 0.0,
                "hhem": 0.0,
                "adv_hhem": 0.0,
            }

        eval_duration_ms = self._ms_since(step_start)
        pipeline_total_ms = self._ms_since(pipeline_start)
        metrics["llm_latency"] = llm_duration_ms
        metrics["total_latency"] = pipeline_total_ms

        yield self._metrics_step(sid, metrics, eval_duration_ms)

    # ── Helpers ──

    async def _retrieve_context(
        self,
        query: str,
        use_hybrid: bool = True,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.services.rag.context import retrieve_rag_context

        payload = dict(request or {})
        payload["query"] = query
        payload.setdefault("latency_profile", "fast")
        if not use_hybrid:
            payload.setdefault("rag_pipeline_mode", "naive")
        try:
            return await retrieve_rag_context(payload)
        except Exception as e:
            logger.warning("Retrieval failed", error=str(e))
            return {"chunks": [], "scores": [], "metadatas": []}

    @staticmethod
    def _gate_sources(
        sources: list[dict[str, Any]],
        answer: str,
        *,
        is_followup: bool,
        has_citable_context: bool,
        discovery_intent: bool,
    ) -> list[dict[str, Any]]:
        """Decide which sources (if any) to surface for this turn.

        Rules (the Sources panel must only appear when retrieval was actually
        used AND relevant):
        - follow-up/meta turns and turns with no citable retrieval → no panel.
        - if the model cited at least one ``[n]`` marker, keep the full list so
          the citation → panel index mapping stays intact (the front maps
          ``[n]`` to ``sources[n-1]``; subsetting would misalign it).
        - if the model cited nothing, only keep sources for explicit
          document-discovery turns ("quels documents…"); otherwise the answer
          did not ground on retrieval, so suppress the panel.
        """
        if is_followup or not has_citable_context or not sources:
            return []
        if _cited_source_indices(answer):
            return sources
        if discovery_intent:
            return sources
        return []

    @staticmethod
    def _step(
        step_id: str,
        status: str,
        step_type: str,
        component: str,
        model: str,
        title: str,
        description: str,
        duration: int = None,
        scores: list = None,
        has_text: bool = False,
    ) -> dict[str, Any]:
        step = {
            "id": step_id,
            "type": step_type,
            "component": component,
            "model": model,
            "status": status,
            "title": title,
            "description": description,
        }
        if duration is not None:
            step["duration"] = duration
        if scores:
            step["scores"] = scores
        if has_text:
            step["hasTextGeneration"] = True
        return {"chunk_type": "decision_step", "decision_step": step}

    @staticmethod
    def _metrics_step(step_id: str, metrics: dict[str, float], duration: int) -> dict[str, Any]:
        return {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": step_id,
                "type": "evaluation",
                "component": "ResponseEvaluator",
                "model": "text-embedding-3-small",
                "status": "completed",
                "title": "Response quality evaluation",
                "description": " · ".join(f"{k}: {v:.2f}" for k, v in metrics.items()),
                "duration": duration,
                "metrics": metrics,
            },
        }

    @staticmethod
    def _ms_since(start: float) -> int:
        return int((time.time() - start) * 1000)

    async def cleanup(self) -> None:
        self.status = "inactive"
