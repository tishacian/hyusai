"""Knowledge × session oracle for expert capture co-construction and live hints."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

_RPM_PATTERN = re.compile(r"(\d+)\s*/?\s*min", re.IGNORECASE)
_NUMERIC_UNIT_PATTERN = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(%|°C|°c|bar|kPa|MPa|min|rpm|/min|mm|cm|m\b|kg|t\b|hours?|h\b)",
    re.IGNORECASE,
)
_WORD_PATTERN = re.compile(r"[\wÀ-ÿ'-]+")
_SPARSE_EXACT_STOPWORDS = frozenset(
    {
        "avec",
        "dans",
        "donc",
        "elle",
        "elles",
        "pour",
        "quand",
        "selon",
        "sont",
        "this",
        "that",
        "then",
        "avec",
        "nous",
        "vous",
        "leur",
        "leurs",
        "plus",
        "moins",
        "fait",
        "faire",
        "sans",
        "apres",
        "avant",
        "entre",
        "comme",
        "case",
        "when",
        "with",
        "from",
        "they",
        "them",
    }
)


def _resolve_llm_config(workspace_id: Optional[str] = None) -> tuple[str, str]:
    from app.core.config import settings as cfg
    from app.core.settings_manager import get_resolved_settings

    resolved = get_resolved_settings(workspace_id=workspace_id) if workspace_id else {}
    api_key = str(cfg.openai_api_key or resolved.get("openaiApiKey") or "").strip()
    model = str(resolved.get("defaultModel") or cfg.default_model or "gpt-4o-mini").strip()
    return api_key, model


# Prefixes for OpenAI "thinking" models (o-series, gpt-5 family). These reject a
# custom ``temperature`` and reason by default, so the capture/voice direct calls
# below must drop temperature and pin reasoning effort low — otherwise gpt-5 both
# 400s on temperature and adds thinking latency to the live voice cascade turn.
_THINKING_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def _is_thinking_model(model: str) -> bool:
    m = (model or "").strip().lower()
    return any(m == p or m.startswith(f"{p}-") for p in _THINKING_MODEL_PREFIXES)


def _model_chat_kwargs(model: str, *, temperature: float) -> Dict[str, Any]:
    """Per-model chat-completion kwargs.

    For thinking models: omit ``temperature`` (only the default is allowed) and
    pin ``reasoning_effort`` from settings so the voice cascade stays fast. For
    standard models (gpt-4o / gpt-4.1): keep the requested temperature.
    """
    if _is_thinking_model(model):
        from app.core.config import settings as cfg

        kwargs: Dict[str, Any] = {}
        effort = getattr(cfg, "openai_reasoning_effort", None)
        if effort:
            kwargs["reasoning_effort"] = effort
        return kwargs
    return {"temperature": temperature}


def _normalize_unit(raw: str) -> str:
    unit = raw.lower().replace("°", "")
    if unit in {"min", "/min", "rpm"}:
        return "rpm"
    if unit in {"hour", "hours", "h"}:
        return "hour"
    return unit


def _parse_measure_value(raw: str) -> float:
    return float(str(raw).replace(",", "."))


def _extract_measures(text: str) -> Dict[str, List[float]]:
    measures: Dict[str, List[float]] = {}
    for match in _RPM_PATTERN.finditer(text or ""):
        unit = "rpm"
        measures.setdefault(unit, []).append(float(match.group(1)))
    for match in _NUMERIC_UNIT_PATTERN.finditer(text or ""):
        unit = _normalize_unit(match.group(2))
        if unit == "rpm":
            continue
        try:
            measures.setdefault(unit, []).append(_parse_measure_value(match.group(1)))
        except ValueError:
            continue
    return measures


def _contradiction_signature(candidate: Dict[str, Any]) -> str:
    return "|".join(
        str(candidate.get(key) or "")
        for key in ("claim_expert", "claim_kb", "unit")
    )


@dataclass
class CaptureSessionContext:
    title: str
    objective: str
    domain: str | None
    expert_profile: str | None
    duration_minutes: int
    unlimited_duration: bool
    elapsed_minutes: float | None
    workspace_id: str
    context_snapshot: dict
    dialogue_turns: list[dict]
    active_subtopic_id: str | None
    recent_transcript: list[dict]
    current_plan: list[dict] | None = None
    latest_instruction: str | None = None
    provided_seed: str | None = None


def _words(text: str) -> List[str]:
    return _WORD_PATTERN.findall(text or "")


def _content_tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _words(text)
        if len(token) >= 4 and token.lower() not in _SPARSE_EXACT_STOPWORDS
    }


def _numeric_literals(text: str) -> set[str]:
    values: set[str] = set()
    for match in re.finditer(r"\d+(?:[.,]\d+)?", text or ""):
        values.add(match.group(0).replace(",", "."))
    return values


def _phrase_hits(partial_text: str, chunk_text: str) -> List[str]:
    terms = [
        token.lower()
        for token in _words(partial_text)
        if len(token) >= 4 and token.lower() not in _SPARSE_EXACT_STOPWORDS
    ]
    chunk_lower = chunk_text.lower()
    hits: List[str] = []
    for width in (4, 3, 2):
        if len(terms) < width:
            continue
        for index in range(0, len(terms) - width + 1):
            phrase = " ".join(terms[index : index + width])
            if phrase in chunk_lower and phrase not in hits:
                hits.append(phrase)
            if len(hits) >= 4:
                return hits
    return hits


def sparse_exact_match_evidence(
    partial_text: str,
    retrieval_chunks: List[str],
    retrieval_metadatas: Optional[List[Dict[str, Any]]] = None,
    *,
    limit: int = 4,
) -> List[Dict[str, Any]]:
    """Deterministic lexical evidence used by the live oracle before any LLM call.

    The retrieval layer may already have obtained these chunks via Qdrant sparse
    search. This helper makes the exact-match signal explicit for contradiction and
    coaching logic by selecting chunks with shared measures, phrases or domain terms.
    """
    query_terms = _content_tokens(partial_text)
    query_numbers = _numeric_literals(partial_text)
    query_units = set(_extract_measures(partial_text).keys())
    if not query_terms and not query_numbers and not query_units:
        return []

    metadatas = retrieval_metadatas or []
    matches: List[Dict[str, Any]] = []
    for index, chunk in enumerate(retrieval_chunks or []):
        text = str(chunk or "").strip()
        if not text:
            continue
        chunk_terms = _content_tokens(text)
        chunk_numbers = _numeric_literals(text)
        chunk_units = set(_extract_measures(text).keys())
        shared_terms = sorted(query_terms & chunk_terms)
        shared_numbers = sorted(query_numbers & chunk_numbers)
        shared_units = sorted(query_units & chunk_units)
        phrases = _phrase_hits(partial_text, text)
        if not (shared_numbers or shared_units or phrases or len(shared_terms) >= 2):
            continue

        md = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
        score = (
            (2.0 * len(shared_numbers))
            + (2.0 * len(shared_units))
            + (1.5 * len(phrases))
            + (len(shared_terms) / max(1, len(query_terms)))
        )
        matches.append(
            {
                "rank": index + 1,
                "backend": "sparse_exact",
                "match_score": round(score, 4),
                "matched_terms": shared_terms[:10],
                "matched_numbers": shared_numbers[:6],
                "matched_units": shared_units[:6],
                "phrase_hits": phrases,
                "text": text,
                "preview": text[:360],
                "document_id": md.get("document_id") or md.get("doc_id") or md.get("id"),
                "source": md.get("source") or md.get("filename") or md.get("document_id"),
                "title": md.get("title") or md.get("filename") or md.get("source"),
                "metadata": md,
            }
        )

    matches.sort(key=lambda item: (-float(item.get("match_score") or 0.0), int(item.get("rank") or 0)))
    return matches[: max(1, int(limit or 1))]


def presentation_prompt(title: Optional[str]) -> str:
    """Invitation to present a given outline item (never an interview question)."""
    label = (title or "").strip() or "ce point"
    return f"Présentez ce que vous savez du point « {label} »."


def broad_presentation_prompt(title: Optional[str]) -> str:
    """Wide, topic-level invitation used to OPEN a topic before its subtopics."""
    label = (title or "").strip() or "ce sujet"
    return f"Présentez globalement ce que vous savez de « {label} »."


def _current_plan_for_llm(topics: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Compact outline sent to the plan oracle for iteration mode."""
    outline: List[Dict[str, Any]] = []
    for topic in topics or []:
        if not isinstance(topic, dict):
            continue
        entry: Dict[str, Any] = {
            "id": topic.get("id"),
            "title": topic.get("title"),
            "subtopics": [],
        }
        for sub in topic.get("subtopics") or []:
            if not isinstance(sub, dict):
                continue
            entry["subtopics"].append(
                {
                    "id": sub.get("id"),
                    "title": sub.get("title"),
                    "questions": [
                        {"id": point.get("id"), "title": point.get("title")}
                        for point in (sub.get("questions") or [])
                        if isinstance(point, dict) and (point.get("title") or point.get("prompt"))
                    ],
                }
            )
        outline.append(entry)
    return outline


def session_context_from_capture(
    *,
    session: Any,
    plan: Dict[str, Any],
    active_subtopic_id: Optional[str] = None,
    recent_transcript: Optional[List[Dict[str, Any]]] = None,
    current_plan: Optional[List[Dict[str, Any]]] = None,
    latest_instruction: Optional[str] = None,
) -> CaptureSessionContext:
    metrics = session.metrics or {}
    dialogue = plan.get("dialogue") or {}
    unlimited = bool(metrics.get("unlimited_duration") or plan.get("unlimited_duration"))
    seed = str(dialogue.get("provided_seed") or "").strip() or None
    return CaptureSessionContext(
        title=str(session.title or ""),
        objective=str(session.objective or plan.get("objective") or ""),
        domain=(metrics.get("capture_domain") or plan.get("capture_domain")),
        expert_profile=session.expert_profile,
        duration_minutes=int(session.duration_minutes or plan.get("duration_minutes") or 20),
        unlimited_duration=unlimited,
        elapsed_minutes=metrics.get("elapsed_minutes"),
        workspace_id=str(session.workspace_id),
        context_snapshot=dict(plan.get("context") or {}),
        dialogue_turns=list(dialogue.get("turns") or []),
        active_subtopic_id=active_subtopic_id or metrics.get("active_subtopic_id"),
        recent_transcript=list(recent_transcript or []),
        current_plan=current_plan if current_plan is not None else _current_plan_for_llm(plan.get("topics") or []),
        latest_instruction=(latest_instruction or "").strip() or None,
        provided_seed=seed,
    )


def score_gaps_with_rag(
    gaps: List[Dict[str, Any]],
    rag_chunks: List[str],
    *,
    rag_metadatas: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Boost gap priority when RAG chunks mention related concepts."""
    rag_metadatas = rag_metadatas or []
    corpus = " ".join(rag_chunks).lower()
    refs = [
        str(md.get("title") or md.get("source") or md.get("filename") or "")
        for md in rag_metadatas
        if isinstance(md, dict)
    ]
    scored: List[Dict[str, Any]] = []
    for gap in gaps:
        item = dict(gap)
        priority = float(item.get("priority") or 0.5)
        slug = str(item.get("slug") or "")
        if slug == "exception_handling" and any(token in corpus for token in ("exception", "cas", "terrain", "180")):
            priority += 0.08
        if slug == "decision_rationale" and any(token in corpus for token in ("décision", "decision", "vitesse", "réglage")):
            priority += 0.06
        if slug == "source_provenance" and refs:
            priority += 0.04
        item["priority"] = round(min(priority, 1.0), 2)
        if refs and not item.get("evidence_refs"):
            item["evidence_refs"] = refs[:5]
        scored.append(item)
    return sorted(scored, key=lambda row: row.get("priority", 0), reverse=True)


def detect_numeric_unit_contradictions(
    expert_text: str,
    kb_chunks: List[str],
) -> List[Dict[str, Any]]:
    """Compare numeric claims with units between expert speech and KB excerpts."""
    kb_text = " ".join(kb_chunks)
    expert_measures = _extract_measures(expert_text)
    kb_measures = _extract_measures(kb_text)
    contradictions: List[Dict[str, Any]] = []
    for unit, expert_values in expert_measures.items():
        kb_values = kb_measures.get(unit)
        if not kb_values or not expert_values:
            continue
        kb_nominal = min(kb_values)
        for expert_value in sorted(set(expert_values)):
            if expert_value in kb_values:
                continue
            delta_ratio = abs(expert_value - kb_nominal) / max(abs(kb_nominal), 1.0)
            if delta_ratio < 0.05:
                continue
            unit_label = unit if unit != "rpm" else "/min"
            contradictions.append(
                {
                    "claim_expert": f"{expert_value:g} {unit_label} mentionné par l'expert",
                    "claim_kb": f"valeur documentée {kb_nominal:g} {unit_label}",
                    "severity": "medium" if delta_ratio < 0.5 else "high",
                    "unit": unit,
                    "suggested_hint": (
                        f"Dans quel cas précis doit-on viser {expert_value:g} {unit_label} "
                        f"au lieu de {kb_nominal:g} {unit_label} ?"
                    ),
                    "kb_excerpt": next(
                        (chunk[:240] for chunk in kb_chunks if str(int(kb_nominal)) in chunk or f"{kb_nominal:g}" in chunk),
                        kb_chunks[0][:240] if kb_chunks else "",
                    ),
                }
            )
    return contradictions


def detect_claim_contradictions(
    expert_text: str,
    kb_chunks: List[str],
) -> List[Dict[str, Any]]:
    """Detect transcript vs KB mismatches using numeric/unit rules."""
    seen: set[str] = set()
    contradictions: List[Dict[str, Any]] = []
    rpm = detect_rpm_contradiction(expert_text, kb_chunks)
    if rpm:
        signature = _contradiction_signature(rpm)
        seen.add(signature)
        contradictions.append(rpm)
    for candidate in detect_numeric_unit_contradictions(expert_text, kb_chunks):
        signature = _contradiction_signature(candidate)
        if signature in seen:
            continue
        seen.add(signature)
        contradictions.append(candidate)
    return contradictions


def detect_rpm_contradiction(
    expert_text: str,
    kb_chunks: List[str],
) -> Optional[Dict[str, Any]]:
    """Deterministic rpm mismatch detector (120 KB vs 180 expert test case)."""
    kb_rpms: set[int] = set()
    expert_rpms: set[int] = set()
    for chunk in kb_chunks:
        for match in _RPM_PATTERN.finditer(chunk):
            kb_rpms.add(int(match.group(1)))
    for match in _RPM_PATTERN.finditer(expert_text):
        expert_rpms.add(int(match.group(1)))
    if not kb_rpms or not expert_rpms:
        return None
    kb_nominal = min(kb_rpms)
    expert_values = sorted(expert_rpms - kb_rpms)
    if not expert_values:
        return None
    expert_value = expert_values[-1]
    return {
        "claim_expert": f"{expert_value}/min mentionné par l'expert",
        "claim_kb": f"vitesse nominale {kb_nominal}/min",
        "severity": "medium",
        "suggested_hint": f"Dans quel cas précis doit-on monter à {expert_value}/min ?",
        "kb_excerpt": next((c[:240] for c in kb_chunks if str(kb_nominal) in c), kb_chunks[0][:240] if kb_chunks else ""),
    }


def _contradictions_with_exact_match_evidence(
    expert_text: str,
    rag_chunks: List[str],
    rag_metadatas: Optional[List[Dict[str, Any]]] = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    exact_matches = sparse_exact_match_evidence(expert_text, rag_chunks, rag_metadatas)
    exact_chunks = [str(item.get("text") or "") for item in exact_matches if item.get("text")]
    contradictions = detect_claim_contradictions(expert_text, exact_chunks or rag_chunks)
    if exact_matches:
        for candidate in contradictions:
            candidate["oracle_exact_matches"] = exact_matches[:2]
            candidate["exact_match_backend"] = "sparse_exact"
    return contradictions, exact_matches


def _dialogue_corpus(context: CaptureSessionContext) -> str:
    parts = [context.objective, context.title]
    for turn in context.dialogue_turns:
        parts.append(str(turn.get("text") or ""))
    for item in context.recent_transcript:
        parts.append(str(item.get("text") or item.get("text_raw") or ""))
    return " ".join(part for part in parts if part).strip().lower()


def _live_retrieval_passages(
    chunks: Optional[List[str]],
    metadatas: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Shape live retrieved passages for the assist panel (text + source metadata)."""
    metadatas = metadatas or []
    passages: List[Dict[str, Any]] = []
    for index, chunk in enumerate(chunks or []):
        text = str(chunk or "").strip()
        if not text:
            continue
        md = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
        passages.append(
            {
                "rank": index + 1,
                "text": text,
                "preview": text[:360],
                "document_id": md.get("document_id") or md.get("doc_id") or md.get("id"),
                "source_id": md.get("source_id") or md.get("source"),
                "source": md.get("source") or md.get("filename") or md.get("document_id"),
                "title": md.get("title") or md.get("filename") or md.get("source"),
                "collection": md.get("collection") or md.get("collection_name"),
                "metadata": md,
            }
        )
    return passages


def _kb_refs_from_chunks(chunks: List[str], metadatas: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    metadatas = metadatas or []
    refs: List[Dict[str, Any]] = []
    for index, chunk in enumerate(chunks[:4]):
        md = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
        refs.append(
            {
                "ref": md.get("source") or md.get("document_id") or md.get("filename") or f"chunk-{index + 1}",
                "title": md.get("title") or md.get("filename") or md.get("source"),
                "preview": str(chunk)[:200],
            }
        )
    return refs


_SUBJECT_SPLIT = re.compile(
    r"\s*(?:[,;]|\bet ensuite\b|\bpuis ensuite\b|\bensuite\b|\bpuis\b|\benfin\b|"
    r"\bainsi que\b|\bet aussi\b|\bet\b)\s*",
    re.IGNORECASE,
)
_SUBJECT_LEAD_NOISE = re.compile(
    r"^(?:on va|nous allons|je vais|on peut|on doit|il faut|je veux|on souhaite|on aimerait|"
    r"je voudrais|on commence par|commencer par|commencer|aujourd'hui|alors|donc|"
    r"décrire|decrire|présenter|presenter|parler de|parler|aborder|traiter|couvrir|"
    r"expliquer|montrer|voir|détailler|detailler|évoquer|evoquer|discuter de|discuter|"
    r"la|le|les|du|de la|de l'|des|de|"
    r"ses|son|sa|leurs|leur|notre|nos|mon|ma|mes|ce|cette|ces|un|une)\s+",
    re.IGNORECASE,
)
_SUBJECT_LEAD_ELISION = re.compile(r"^(?:l'|d'|j'|qu'|n'|c'|s')", re.IGNORECASE)
_SUBJECT_STOPWORDS = frozenset({"", "et", "ou", "puis", "ensuite", "enfin", "etc", "etc.", "cela", "ça", "ca"})


def _expressed_text(context: CaptureSessionContext) -> str:
    """Only what the expert actually said during scoping (dialogue turns).

    Deliberately excludes the objective/title and KB so the outline is grounded
    strictly in the expert's stated content.
    """
    return " ".join(
        str(turn.get("text") or "").strip()
        for turn in context.dialogue_turns
        if str(turn.get("text") or "").strip()
    ).strip()


def _subjects_from_expression(text: str) -> List[str]:
    """Extract the subjects the expert explicitly named, in stated order.

    Splits on conjunctions/punctuation and strips leading framing verbs/articles
    ("on va décrire la ...", "ensuite ses ..."). Never adds anything that was not
    in the text, so the outline cannot invent scope.
    """
    clean = (text or "").strip()
    if not clean:
        return []
    subjects: List[str] = []
    seen: set[str] = set()
    for raw_clause in _SUBJECT_SPLIT.split(clean):
        clause = (raw_clause or "").strip().strip(".!?…\"«»").strip()
        prev: Optional[str] = None
        while clause and clause != prev:
            prev = clause
            clause = _SUBJECT_LEAD_NOISE.sub("", clause, count=1).strip()
            clause = _SUBJECT_LEAD_ELISION.sub("", clause, count=1).strip()
        clause = clause.strip(".!?…\"«»'").strip()
        words = _words(clause)
        if not words:
            continue
        key = clause.lower()
        if key in _SUBJECT_STOPWORDS or key in seen:
            continue
        if len(words) == 1 and len(words[0]) <= 2:
            continue
        seen.add(key)
        subjects.append(clause[0].upper() + clause[1:])
    return subjects[:8]


def _topics_from_subjects(
    subjects: List[str],
    kb_refs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    topics: List[Dict[str, Any]] = []
    for index, subject in enumerate(subjects, start=1):
        topic_id = f"t-{index:02d}"
        subtopic_id = f"st-{index:02d}"
        topics.append(
            {
                "id": topic_id,
                "title": subject,
                "prompt": broad_presentation_prompt(subject),
                "rationale": "Sujet exprimé par l'expert pendant le cadrage.",
                "kb_refs": kb_refs[:1] if index == 1 else [],
                "confidence": 0.6,
                "subtopics": [
                    {
                        "id": subtopic_id,
                        "title": subject,
                        "objective": "",
                        "prompt": presentation_prompt(subject),
                        "status": "pending",
                    }
                ],
            }
        )
    return topics


def _fallback_topic_proposals(
    context: CaptureSessionContext,
    gaps: List[Dict[str, Any]],
    rag_chunks: List[str],
    rag_metadatas: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Derive the outline strictly from the expert's stated content.

    No keyword templates, no seed topics, no gap-derived topics: if the expert did
    not express a subject, it does not appear in the outline. ``gaps`` stays internal
    (coverage analysis) and is intentionally not used to propose topics.
    """
    subjects = _subjects_from_expression(_expressed_text(context))
    kb_refs = _kb_refs_from_chunks(rag_chunks, rag_metadatas)
    return _topics_from_subjects(subjects, kb_refs)


def _fallback_dialogue_probe(context: CaptureSessionContext, topics: List[Dict[str, Any]]) -> str:
    """Outline-building guidance: invite the expert to describe so the IA builds the
    topic tree. We only phrase a real question when something is flagrant (e.g. a
    machine is mentioned but not named)."""
    corpus = _dialogue_corpus(context)
    if not context.dialogue_turns:
        return (
            "Décrivez librement le périmètre à transmettre — la ligne, le client ou la "
            "machine concernée — et les points qui vous semblent importants. "
            "Je construis l'arborescence de sujets à partir de votre description."
        )
    if any(token in corpus for token in ("machine", "équipement", "equipement", "ligne")) and not any(
        char.isdigit() for char in corpus
    ):
        return "De quelle machine ou ligne précise parlez-vous (référence ou repère) ?"
    if not topics:
        return (
            "Continuez à décrire ce que vous voulez couvrir ; je complète l'arborescence "
            "de sujets au fur et à mesure."
        )
    titles = ", ".join(topic.get("title") or "" for topic in topics[:3])
    return (
        f"Voici l'arborescence que je propose à partir de votre description : {titles}. "
        "Complétez ou corrigez-la si besoin."
    )


def analyze_plan_oracle(
    context: CaptureSessionContext,
    *,
    rag_chunks: Optional[List[str]] = None,
    rag_metadatas: Optional[List[Dict[str, Any]]] = None,
    base_gaps: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Structured oracle output for plan_build (deterministic fallback, optional LLM)."""
    rag_chunks = list(rag_chunks or [])
    rag_metadatas = list(rag_metadatas or [])
    base_gaps = list(base_gaps or [])
    coverage_gaps = score_gaps_with_rag(base_gaps, rag_chunks, rag_metadatas=rag_metadatas)
    corpus = _dialogue_corpus(context)
    contradictions, exact_matches = _contradictions_with_exact_match_evidence(corpus, rag_chunks, rag_metadatas)
    topic_proposals = _fallback_topic_proposals(context, coverage_gaps, rag_chunks, rag_metadatas)
    dialogue_probe = _fallback_dialogue_probe(context, topic_proposals)
    return {
        "topic_proposals": topic_proposals,
        "coverage_gaps": coverage_gaps[:6],
        "contradiction_candidates": contradictions,
        "oracle_exact_matches": exact_matches,
        "dialogue_probe": dialogue_probe,
    }


def _resolve_plan_oracle_model(default_model: str) -> str:
    """Plan structuring uses a dedicated (faster) model when configured."""
    from app.core.config import settings as cfg

    override = str(getattr(cfg, "capture_plan_oracle_model", "") or "").strip()
    return override or default_model


def _resolve_finalize_llm_config(workspace_id: Optional[str] = None) -> tuple[str, str]:
    """FINAL-phase LLM config: same API key, dedicated (faster) model when configured.

    The end-of-capture pass (reformulation, grounded questions, thematic
    structuring) must not pay the workspace default model's thinking latency;
    ``capture_finalize_model`` overrides it, falling back to the default model
    when unset/empty. Live-path calls keep using ``_resolve_llm_config``.
    """
    from app.core.config import settings as cfg

    api_key, model = _resolve_llm_config(workspace_id)
    override = str(getattr(cfg, "capture_finalize_model", "") or "").strip()
    return api_key, (override or model)


async def plan_structure_llm_async(
    context: CaptureSessionContext,
    *,
    rag_chunks: Optional[List[str]] = None,
    rag_metadatas: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """One structured LLM call that organises the expert's statements into a plan.

    Returns the parsed JSON payload, or ``None`` when no LLM is configured /
    the call fails / the payload has no topic proposals. ``rag_chunks`` are
    optional: they only inform ``kb_refs`` in the prompt (never the scope), so
    callers may invoke this concurrently with retrieval and omit them.
    """
    api_key, model = _resolve_llm_config(context.workspace_id)
    if not api_key:
        return None
    model = _resolve_plan_oracle_model(model)
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        current_plan = list(context.current_plan or [])
        latest_instruction = str(context.latest_instruction or "").strip()
        iteration_mode = bool(current_plan)
        prompt = {
            "title": context.title,
            "objective": context.objective,
            "domain": context.domain,
            "expert_profile": context.expert_profile,
            "duration_minutes": context.duration_minutes,
            "provided_seed": context.provided_seed,
            "expert_statements": context.dialogue_turns,
            "current_plan": current_plan,
            "latest_instruction": latest_instruction or None,
            "rag_chunks": (rag_chunks or [])[:4],
            "rag_metadatas": (rag_metadatas or [])[:4],
            "instruction": (
                "Tu es l'oracle de co-construction d'un plan de capture de savoir expert. "
                "À partir de ce que l'expert a exprimé dans 'expert_statements' et 'provided_seed' "
                "(éclairé par 'objective' et 'domain'), ORGANISE ce contenu en un PLAN HIÉRARCHIQUE "
                "de type document — comme le sommaire d'un rapport technique : plusieurs SECTIONS "
                "de premier niveau (topic_proposals), chacune découpée en SOUS-SECTIONS (subtopics), "
                "et chaque sous-section portant quelques POINTS DE PRÉSENTATION (questions). "
                "MODE ITÉRATION : si 'current_plan' contient des rubriques, traite ce plan comme "
                "source de vérité pour les sections existantes. Applique UNIQUEMENT 'latest_instruction' "
                "comme modification ciblée ; ne régénère pas tout le plan sauf demande explicite "
                "(recommencer, tout refaire, nouveau plan, etc.). "
                "PLACEMENT : les nouveaux points vont sous la section EXISTANTE la plus spécifique "
                "sémantiquement ; pour les thèmes transverses (ex. sécurité), préfère la section "
                "dédiée (ex. « Directives de sécurité ») plutôt qu'une mention incidente ailleurs. "
                "Préserve les ids des rubriques inchangées ; ne déplace ni supprime de sections "
                "existantes sauf instruction explicite. "
                "STRUCTURE : colle strictement aux rubriques, à l'ordre et au périmètre exprimés par l'utilisateur. "
                "Si l'utilisateur donne une liste ou un plan, reprends cette structure sans inventer de sections. "
                "N'ajoute PAS de rubriques génériques comme introduction, contexte, importance, enjeux, conclusion "
                "ou recommandations si elles ne sont pas explicitement demandées. "
                "Les 'rag_chunks' servent uniquement à renseigner kb_refs (preuves), jamais à "
                "élargir le périmètre. "
                "Ne produis PAS de questions d'entretien : chaque champ 'prompt' (sur les sujets, "
                "sous-sujets ET points) est une INVITATION À PRÉSENTER (ex: \"Présentez ce que "
                "vous savez de ...\"), jamais une question posée à l'expert. "
                "Retourne un JSON avec: "
                "topic_proposals (liste {id, title, prompt, rationale, confidence, kb_refs, "
                "subtopics:[{id, title, prompt, objective, questions:[{id, title, prompt}]}]}), "
                "coverage_gaps (liste {slug, title, description, priority}), "
                "contradiction_candidates (liste {claim_expert, claim_kb, severity, suggested_hint, kb_excerpt}), "
                "dialogue_probe (string, une relance de cadrage qui invite à décrire, pas à interroger)."
            ),
        }
        system_content = (
            "Oracle capture JSON only. No interview questions. "
            "Mirror the user's requested outline, labels and order. "
            "Do not add generic sections such as introduction, context, importance or conclusion."
        )
        if iteration_mode:
            system_content += (
                " ITERATION MODE: when current_plan has topics, treat it as the source of truth "
                "for existing rubrics. Apply ONLY latest_instruction as a targeted delta; do not "
                "regenerate the full plan unless explicitly asked. PLACEMENT: new items belong "
                "under the most specific matching existing section; for cross-cutting themes "
                "(e.g. security), prefer the dedicated section over incidental mentions elsewhere. "
                "Preserve existing ids when rubrics are unchanged; do not move or delete existing "
                "sections unless explicitly instructed."
            )
        response = await client.chat.completions.create(
            model=model,
            **_model_chat_kwargs(model, temperature=0.2),
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": system_content,
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        )
        content = response.choices[0].message.content if response.choices else None
        if not content:
            return None
        parsed = json.loads(content)
        if not isinstance(parsed, dict) or not parsed.get("topic_proposals"):
            return None
        return parsed
    except Exception:
        return None


def compose_plan_oracle(
    context: CaptureSessionContext,
    parsed: Optional[Dict[str, Any]],
    *,
    rag_chunks: Optional[List[str]] = None,
    rag_metadatas: Optional[List[Dict[str, Any]]] = None,
    base_gaps: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Combine the (optional) LLM structuring with the deterministic oracle."""
    fallback = analyze_plan_oracle(
        context,
        rag_chunks=rag_chunks,
        rag_metadatas=rag_metadatas,
        base_gaps=base_gaps,
    )
    if not isinstance(parsed, dict) or not parsed.get("topic_proposals"):
        return fallback
    deterministic_contradictions = fallback.get("contradiction_candidates") or []
    llm_contradictions = parsed.get("contradiction_candidates") or []
    merged_contradictions = list(deterministic_contradictions)
    seen = {_contradiction_signature(item) for item in merged_contradictions if isinstance(item, dict)}
    for candidate in llm_contradictions:
        if not isinstance(candidate, dict):
            continue
        signature = _contradiction_signature(candidate)
        if signature in seen:
            continue
        seen.add(signature)
        merged_contradictions.append(candidate)
    parsed["contradiction_candidates"] = merged_contradictions or deterministic_contradictions
    parsed.setdefault("dialogue_probe", fallback.get("dialogue_probe"))
    parsed.setdefault("coverage_gaps", fallback.get("coverage_gaps"))
    parsed.setdefault("oracle_exact_matches", fallback.get("oracle_exact_matches"))
    return parsed


async def analyze_plan_oracle_async(
    context: CaptureSessionContext,
    *,
    rag_chunks: Optional[List[str]] = None,
    rag_metadatas: Optional[List[Dict[str, Any]]] = None,
    base_gaps: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Try one structured LLM call; fall back to deterministic oracle."""
    parsed = await plan_structure_llm_async(
        context,
        rag_chunks=rag_chunks,
        rag_metadatas=rag_metadatas,
    )
    return compose_plan_oracle(
        context,
        parsed,
        rag_chunks=rag_chunks,
        rag_metadatas=rag_metadatas,
        base_gaps=base_gaps,
    )


def plan_dialogue_probe(oracle_result: Dict[str, Any], *, ready_to_finalize: bool = False) -> Optional[str]:
    if ready_to_finalize:
        return None
    probe = str(oracle_result.get("dialogue_probe") or "").strip()
    return probe or None


def normalize_outline_points(
    sub_id: str,
    raw_points: Any,
    prior_points: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Normalize the 3rd outline level (presentation points) under a subtopic.

    Each point carries an invitation-to-present ``prompt`` (never an interview
    question). Prior edits are preserved by id. Accepts strings or dict rows.
    """
    prior_by_id = {
        str(point.get("id")): point
        for point in (prior_points or [])
        if isinstance(point, dict) and point.get("id")
    }
    normalized: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_point in enumerate(raw_points or [], start=1):
        if isinstance(raw_point, str):
            raw_point = {"title": raw_point}
        if not isinstance(raw_point, dict):
            continue
        title = str(
            raw_point.get("title") or raw_point.get("question") or raw_point.get("prompt") or ""
        ).strip()
        if not title:
            continue
        point_id = str(raw_point.get("id") or f"{sub_id}-pt-{index:02d}")
        if point_id in seen:
            point_id = f"{sub_id}-pt-{index:02d}"
        seen.add(point_id)
        prior = prior_by_id.get(point_id, {})
        prompt = str(raw_point.get("prompt") or prior.get("prompt") or presentation_prompt(title)).strip()
        normalized.append(
            {
                **prior,
                **{k: v for k, v in raw_point.items() if k != "question"},
                "id": point_id,
                "title": title,
                "prompt": prompt,
                "status": prior.get("status") or raw_point.get("status") or "pending",
            }
        )
    return normalized


_TITLE_SIMILARITY_MIN = 0.8


def _title_key(title: Any) -> str:
    return " ".join(_words(str(title or ""))).strip().lower()


def _titles_similar(a: Any, b: Any) -> bool:
    """Near-duplicate outline titles ("Maintenance des rouleaux" vs "Maintenance
    et entretien des rouleaux"). Token containment on content tokens, with an
    exact normalized comparison as fallback for very short titles."""
    key_a, key_b = _title_key(a), _title_key(b)
    if not key_a or not key_b:
        return False
    if key_a == key_b:
        return True
    tokens_a, tokens_b = _content_tokens(key_a), _content_tokens(key_b)
    if not tokens_a or not tokens_b:
        return False
    containment = len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))
    return containment >= _TITLE_SIMILARITY_MIN


def merge_topic_proposals(plan: Dict[str, Any], proposals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge oracle topic proposals into plan topics, preserving user edits.

    Iteration semantics are REPLACE, not append: the oracle regenerates the whole
    plan on each instruction (often with fresh ids and slightly reworded titles),
    so existing topics are matched by id OR by title similarity and folded into
    the regenerated outline. Leftover existing topics are only re-appended when
    no merged topic already covers the same title — this is the dedupe safety
    net against the "duplicate sections when iterating" bug.
    """
    existing_topics = [dict(topic) for topic in (plan.get("topics") or []) if isinstance(topic, dict)]
    existing_by_id = {str(topic.get("id")): topic for topic in existing_topics if topic.get("id")}
    consumed_existing: set[int] = set()

    def _match_existing(topic_id: str, title: Any) -> Dict[str, Any]:
        match = existing_by_id.get(topic_id)
        if match is not None:
            for index, topic in enumerate(existing_topics):
                if topic is match:
                    consumed_existing.add(index)
            return match
        for index, topic in enumerate(existing_topics):
            if index in consumed_existing:
                continue
            if _titles_similar(topic.get("title"), title):
                consumed_existing.add(index)
                return topic
        return {}

    merged: List[Dict[str, Any]] = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        # The LLM occasionally emits the same section twice in one response.
        if any(_titles_similar(item.get("title"), proposal.get("title")) for item in merged):
            continue
        topic_id = str(proposal.get("id") or f"t-{len(merged) + 1:02d}")
        current = _match_existing(topic_id, proposal.get("title"))
        topic_id = str(current.get("id") or topic_id)
        subtopics = []
        existing_sub = {st.get("id"): st for st in (current.get("subtopics") or []) if isinstance(st, dict)}
        existing_sub_list = [st for st in (current.get("subtopics") or []) if isinstance(st, dict)]
        for raw_sub in proposal.get("subtopics") or []:
            if not isinstance(raw_sub, dict):
                continue
            if any(_titles_similar(item.get("title"), raw_sub.get("title")) for item in subtopics):
                continue
            sub_id = str(raw_sub.get("id") or f"{topic_id}-sub-{len(subtopics) + 1:02d}")
            prior = existing_sub.get(sub_id)
            if prior is None:
                prior = next(
                    (st for st in existing_sub_list if _titles_similar(st.get("title"), raw_sub.get("title"))),
                    {},
                )
            if prior:
                sub_id = str(prior.get("id") or sub_id)
            sub_title = prior.get("title") or raw_sub.get("title")
            points = normalize_outline_points(
                sub_id,
                raw_sub.get("questions") or raw_sub.get("points"),
                prior.get("questions"),
            )
            subtopics.append(
                {
                    **prior,
                    **raw_sub,
                    "id": sub_id,
                    "title": sub_title,
                    "objective": prior.get("objective") or raw_sub.get("objective") or "",
                    "prompt": prior.get("prompt") or raw_sub.get("prompt") or presentation_prompt(sub_title),
                    "status": prior.get("status") or raw_sub.get("status") or "pending",
                    "questions": points,
                }
            )
        topic_title = current.get("title") or proposal.get("title") or topic_id
        merged.append(
            {
                **current,
                "id": topic_id,
                "title": topic_title,
                "status": current.get("status") or proposal.get("status") or "draft",
                "objective": current.get("objective") or proposal.get("rationale") or "",
                "prompt": current.get("prompt") or proposal.get("prompt") or broad_presentation_prompt(topic_title),
                "rationale": current.get("rationale") or proposal.get("rationale") or "",
                "knowledge_refs": current.get("knowledge_refs") or proposal.get("kb_refs") or [],
                "subtopics": subtopics or current.get("subtopics") or [],
                "oracle_confidence": proposal.get("confidence"),
            }
        )
    merged_ids = {str(item.get("id")) for item in merged}
    for index, topic in enumerate(existing_topics):
        if index in consumed_existing or str(topic.get("id")) in merged_ids:
            continue
        # Safety net: never re-append an existing topic the regenerated plan
        # already covers under a slightly different title (duplicate sections).
        if any(_titles_similar(item.get("title"), topic.get("title")) for item in merged):
            continue
        merged.append(topic)
    return merged


# Minimum lexical overlap score before a live section suggestion is emitted.
LIVE_SECTION_DETECT_MIN_CONFIDENCE = 0.42


def detect_active_section_from_text(
    plan_topics: List[Dict[str, Any]],
    partial_text: str,
    *,
    fallback_subtopic_id: Optional[str] = None,
    window_words: int = 40,
) -> Dict[str, Any]:
    """Lightweight plan-section detector for live capture (no LLM, no retrieval).

    Scores subtopic/topic titles against the tail of the recent transcript using
    token overlap and full-title substring matches. Returns a confidence in [0, 1].
    """
    words = _words(partial_text or "")
    if len(words) < 6:
        fallback_topic_id = _topic_id_for_subtopic(plan_topics, fallback_subtopic_id)
        return {
            "subtopic_id": fallback_subtopic_id,
            "topic_id": fallback_topic_id,
            "confidence": 0.0,
        }
    window = " ".join(words[-window_words:]).lower()
    window_tokens = _content_tokens(window)

    best_subtopic_id: Optional[str] = None
    best_topic_id: Optional[str] = None
    best_confidence = 0.0

    for topic in plan_topics:
        topic_id = str(topic.get("id") or "")
        topic_tokens = _content_tokens(str(topic.get("title") or ""))
        for subtopic in topic.get("subtopics") or []:
            subtopic_id = str(subtopic.get("id") or "")
            title = str(subtopic.get("title") or "").strip()
            if not subtopic_id or not title:
                continue
            title_lower = title.lower()
            title_tokens = _content_tokens(title_lower)
            if not title_tokens and len(title_lower) < 5:
                continue
            if len(title_lower) >= 5 and title_lower in window:
                confidence = 0.92
            else:
                overlap = title_tokens & window_tokens
                if not overlap and topic_tokens:
                    overlap = (title_tokens | topic_tokens) & window_tokens
                if not overlap:
                    continue
                confidence = len(overlap) / max(1, len(title_tokens))
                if len(overlap) < 2 and confidence < 0.55:
                    continue
            if confidence > best_confidence:
                best_confidence = confidence
                best_subtopic_id = subtopic_id
                best_topic_id = topic_id

    if best_confidence < LIVE_SECTION_DETECT_MIN_CONFIDENCE:
        fallback_topic_id = _topic_id_for_subtopic(plan_topics, fallback_subtopic_id)
        return {
            "subtopic_id": fallback_subtopic_id,
            "topic_id": fallback_topic_id,
            "confidence": 0.0,
        }
    return {
        "subtopic_id": best_subtopic_id,
        "topic_id": best_topic_id,
        "confidence": round(best_confidence, 3),
    }


def _topic_id_for_subtopic(
    plan_topics: List[Dict[str, Any]],
    subtopic_id: Optional[str],
) -> Optional[str]:
    if not subtopic_id:
        return None
    for topic in plan_topics:
        for subtopic in topic.get("subtopics") or []:
            if str(subtopic.get("id")) == subtopic_id:
                return str(topic.get("id") or "") or None
    return None


def infer_active_subtopic_id(
    plan_topics: List[Dict[str, Any]],
    partial_text: str,
    *,
    fallback: Optional[str] = None,
) -> Optional[str]:
    detected = detect_active_section_from_text(
        plan_topics,
        partial_text,
        fallback_subtopic_id=fallback,
    )
    if detected.get("confidence", 0.0) >= LIVE_SECTION_DETECT_MIN_CONFIDENCE:
        return detected.get("subtopic_id")
    return fallback


def evaluate_capture_partial(
    context: CaptureSessionContext,
    partial_text: str,
    retrieval_chunks: List[str],
    *,
    retrieval_metadatas: Optional[List[Dict[str, Any]]] = None,
    plan_topics: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Live capture evaluation: contradictions, hint candidates, and the retrieved
    passages that back the live assist panels."""
    retrieval = _live_retrieval_passages(retrieval_chunks, retrieval_metadatas)
    exact_matches = sparse_exact_match_evidence(partial_text, retrieval_chunks, retrieval_metadatas)
    text = (partial_text or "").strip()
    if len(_words(text)) < 6:
        return {
            "hints": [],
            "contradiction_candidates": [],
            "active_subtopic_id": context.active_subtopic_id,
            "active_section_confidence": 0.0,
            "active_topic_id": _topic_id_for_subtopic(plan_topics or [], context.active_subtopic_id),
            "retrieval": retrieval,
            "oracle_exact_matches": exact_matches,
        }
    contradictions, exact_matches = _contradictions_with_exact_match_evidence(
        text,
        retrieval_chunks,
        retrieval_metadatas,
    )
    hints: List[Dict[str, Any]] = []
    for candidate in contradictions:
        hint_text = str(candidate.get("suggested_hint") or "").strip()
        if not hint_text:
            continue
        hints.append(
            {
                "id": f"qb-live-{uuid.uuid4()}",
                "subtopic_id": context.active_subtopic_id,
                "full_question": hint_text,
                "hint": hint_text[:80],
                "priority": 100,
                "source": "oracle_live",
                "visibility": "hint",
                "kb_refs": _kb_refs_from_chunks(retrieval_chunks, retrieval_metadatas),
                "kb_excerpt": candidate.get("kb_excerpt"),
                "oracle_exact_matches": candidate.get("oracle_exact_matches") or exact_matches[:2],
                "exact_match_backend": candidate.get("exact_match_backend"),
                "oracle_id": str(uuid.uuid4()),
            }
        )
    section_detected = detect_active_section_from_text(
        plan_topics or [],
        text,
        fallback_subtopic_id=context.active_subtopic_id,
    )
    active_subtopic_id = section_detected.get("subtopic_id")
    active_section_confidence = float(section_detected.get("confidence") or 0.0)
    for hint in hints:
        if not hint.get("subtopic_id"):
            hint["subtopic_id"] = active_subtopic_id
    return {
        "hints": hints,
        "contradiction_candidates": contradictions,
        "active_subtopic_id": active_subtopic_id,
        "active_section_confidence": active_section_confidence,
        "active_topic_id": section_detected.get("topic_id"),
        "retrieval": retrieval,
        "oracle_exact_matches": exact_matches,
    }


def _template_question_bank_entry(
    *,
    subtopic_title: str,
    subtopic_objective: str,
    rag_chunks: Optional[List[str]] = None,
) -> Dict[str, str]:
    full_question = f"Quels éléments clés sur « {subtopic_title} » doivent être capturés ?"
    hint = (subtopic_objective or f"Angle {subtopic_title}")[:80]
    title_lower = subtopic_title.lower()
    if rag_chunks and "120" in rag_chunks[0] and "vitesse" in title_lower:
        full_question = "Quelle vitesse appliquer en cas d'exception terrain ?"
        hint = "Cas où la vitesse diffère du manuel"
    return {
        "full_question": full_question,
        "hint": hint[:80],
        "prompt": presentation_prompt(subtopic_title),
    }


async def generate_question_bank_entry_async(
    *,
    workspace_id: str,
    subtopic_title: str,
    subtopic_objective: str,
    session_objective: str,
    rag_chunks: List[str],
    rag_metadatas: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, str]:
    """Generate a presentation prompt + short UI hint (and an internal probe) for an
    outline item. Falls back to templates. The user-facing field is ``prompt`` — an
    invitation to present, never an interview question."""
    fallback = _template_question_bank_entry(
        subtopic_title=subtopic_title,
        subtopic_objective=subtopic_objective,
        rag_chunks=rag_chunks,
    )
    api_key, model = _resolve_llm_config(workspace_id)
    if not api_key:
        return fallback
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        prompt = {
            "subtopic_title": subtopic_title,
            "subtopic_objective": subtopic_objective,
            "session_objective": session_objective,
            "rag_chunks": rag_chunks[:3],
            "rag_metadatas": (rag_metadatas or [])[:3],
            "instruction": (
                "Pour ce point d'arborescence, génère: 'prompt' (invitation à présenter, "
                "ex: \"Présentez ce que vous savez du point '...'.\", jamais une question), "
                "'hint' (≤ 80 caractères, sans question complète) et 'full_question' "
                "(sonde interne, non affichée). Retourne JSON: {prompt, hint, full_question}."
            ),
        }
        response = await client.chat.completions.create(
            model=model,
            **_model_chat_kwargs(model, temperature=0.2),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Outline prompt JSON only. No interview questions in 'prompt'."},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        )
        content = response.choices[0].message.content if response.choices else None
        if not content:
            return fallback
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            return fallback
        full_question = str(parsed.get("full_question") or fallback["full_question"]).strip()
        hint = str(parsed.get("hint") or fallback["hint"]).strip()[:80]
        presentation = str(parsed.get("prompt") or fallback["prompt"]).strip()
        if not full_question or not hint:
            return fallback
        return {
            "full_question": full_question,
            "hint": hint,
            "prompt": presentation or fallback["prompt"],
        }
    except Exception:
        return fallback


# --- FINAL phase (end-of-section / end-of-capture) helpers ------------------


# Near-duplicate detection thresholds for the FINAL dedupe pass: two expert
# statements are considered the same content when the smaller statement's
# content tokens are almost fully contained in the other one.
_DEDUPE_CONTAINMENT_MIN = 0.85


def dedupe_statements(statements: List[str]) -> tuple[List[str], int]:
    """FINAL deterministic dedupe of repeated/rephrased expert statements.

    The expert often repeats or rephrases the same point across turns; the
    FINAL pass must not feed those duplicates to the reformulation (nor count
    them as distinct facts). A statement is dropped when its content tokens
    are (near-)fully contained in an already kept statement — the LONGEST
    variant wins so no substance is lost. Order of first occurrence is kept.

    Returns ``(deduped_statements, removed_count)``.
    """
    kept: List[str] = []
    # Every variant's token set per kept cluster: a new statement matching ANY
    # variant of a cluster (not just the richest one, whose extra filler tokens
    # would dilute the containment) is folded into that cluster.
    kept_variant_tokens: List[List[set[str]]] = []
    removed = 0
    for raw in statements or []:
        text = str(raw or "").strip()
        if not text:
            continue
        tokens = _content_tokens(text)
        duplicate_index: Optional[int] = None
        for index, variants in enumerate(kept_variant_tokens):
            for other_tokens in variants:
                if not tokens or not other_tokens:
                    if text.strip().lower() == kept[index].strip().lower():
                        duplicate_index = index
                        break
                    continue
                smaller, larger = (
                    (tokens, other_tokens) if len(tokens) <= len(other_tokens) else (other_tokens, tokens)
                )
                containment = len(smaller & larger) / max(1, len(smaller))
                if containment >= _DEDUPE_CONTAINMENT_MIN:
                    duplicate_index = index
                    break
            if duplicate_index is not None:
                break
        if duplicate_index is None:
            kept.append(text)
            kept_variant_tokens.append([tokens])
            continue
        removed += 1
        kept_variant_tokens[duplicate_index].append(tokens)
        # Keep the richest variant of the duplicated content.
        if len(text) > len(kept[duplicate_index]):
            kept[duplicate_index] = text
    return kept, removed


def fallback_thematic_blocks(statements: List[str], *, max_themes: int = 6) -> List[Dict[str, Any]]:
    """Deterministic thematic fallback when no LLM is configured.

    One block holding everything, titled from the first statement's leading
    words — honest (no invented structure) and keeps the FINAL pipeline alive.
    """
    clean = [str(s).strip() for s in (statements or []) if str(s).strip()]
    if not clean:
        return []
    lead_words = _words(clean[0])[:6]
    title = " ".join(lead_words) or "Synthèse de la conversation"
    return [
        {
            "id": "theme-01",
            "title": title[0].upper() + title[1:],
            "statement_indexes": list(range(len(clean))),
        }
    ]


async def derive_thematic_blocks_async(
    *,
    workspace_id: Optional[str],
    statements: List[str],
    max_themes: int = 6,
) -> List[Dict[str, Any]]:
    """FINAL thematic structuring for free conversations (no capture plan).

    Groups the expert's statements into thematic blocks with short titles so the
    report can be structured even without a plan. Returns a list of
    ``{id, title, statement_indexes}``. Falls back to a single deterministic
    block when no LLM is configured or the call fails.
    """
    clean = [str(s).strip() for s in (statements or []) if str(s).strip()]
    fallback = fallback_thematic_blocks(clean, max_themes=max_themes)
    if not clean:
        return []
    api_key, model = _resolve_finalize_llm_config(workspace_id)
    if not api_key:
        return fallback
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        payload = {
            "statements": [{"index": i, "text": s[:600]} for i, s in enumerate(clean)],
            "max_themes": max(1, int(max_themes)),
            "instruction": (
                "L'expert a parlé librement, sans plan. Regroupe ses déclarations en "
                "BLOCS THÉMATIQUES cohérents (entre 1 et max_themes), dans l'ordre "
                "naturel du discours. Chaque bloc a un TITRE court et factuel (pas de "
                "titre générique type 'Introduction'/'Conclusion') et la liste des "
                "indices de déclarations qui lui appartiennent. Chaque indice apparaît "
                "dans EXACTEMENT un bloc. Retourne un JSON "
                "{themes: [{title, statement_indexes}]}."
            ),
        }
        response = await client.chat.completions.create(
            model=model,
            **_model_chat_kwargs(model, temperature=0.2),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Thematic grouping JSON only. Every statement index assigned once."},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        )
        content = response.choices[0].message.content if response.choices else None
        if not content:
            return fallback
        parsed = json.loads(content)
        raw_themes = parsed.get("themes") if isinstance(parsed, dict) else None
        if not isinstance(raw_themes, list):
            return fallback
        themes: List[Dict[str, Any]] = []
        assigned: set[int] = set()
        for index, raw in enumerate(raw_themes, start=1):
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or "").strip()
            indexes = [
                int(i)
                for i in (raw.get("statement_indexes") or [])
                if isinstance(i, (int, float)) and 0 <= int(i) < len(clean) and int(i) not in assigned
            ]
            if not title or not indexes:
                continue
            assigned.update(indexes)
            themes.append(
                {
                    "id": f"theme-{index:02d}",
                    "title": title,
                    "statement_indexes": sorted(indexes),
                }
            )
            if len(themes) >= max(1, int(max_themes)):
                break
        leftovers = [i for i in range(len(clean)) if i not in assigned]
        if leftovers and themes:
            themes[-1]["statement_indexes"] = sorted(set(themes[-1]["statement_indexes"]) | set(leftovers))
        return themes or fallback
    except Exception:
        return fallback


def _section_label(plan_section: Optional[Dict[str, Any]]) -> str:
    if not isinstance(plan_section, dict):
        return ""
    parts = [
        str(plan_section.get("topic_title") or "").strip(),
        str(plan_section.get("subtopic_title") or plan_section.get("title") or "").strip(),
    ]
    return " / ".join(part for part in parts if part)


async def reformulate_section_async(
    *,
    workspace_id: Optional[str],
    section_label: str,
    statements: List[str],
    kb_chunks: Optional[List[str]] = None,
    static_context: Optional[str] = None,
    glossary_terms: Optional[List[str]] = None,
) -> str:
    """FINAL exhaustive LLM reformulation of one captured section.

    The heavy end-of-capture pass: restructures the expert's expression for the
    section, removes oral artifacts AND content repeated/rephrased across turns
    (dedupe), and aligns the vocabulary on the domain glossary
    (``glossary_terms`` — the Tier-2 Andritz alignment, e.g. "carte" -> "card")
    while staying faithful to the substance — it never invents facts.
    ``static_context`` (e.g. the Andritz framing) and ``kb_chunks`` only inform
    phrasing/terminology, never new content.

    Falls back to a deterministic bullet join of the statements when no LLM is
    configured, so the final phase always returns usable text.
    """
    clean_statements = [str(s).strip() for s in (statements or []) if str(s).strip()]
    fallback = "\n".join(f"- {s}" for s in clean_statements)
    if not clean_statements:
        return ""
    api_key, model = _resolve_finalize_llm_config(workspace_id)
    if not api_key:
        return fallback
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        payload = {
            "section": section_label,
            "static_context": (static_context or "").strip(),
            "expert_statements": clean_statements,
            "kb_chunks": [str(c)[:600] for c in (kb_chunks or [])[:4]],
            "domain_glossary": [str(t) for t in (glossary_terms or [])[:80]],
            "instruction": (
                "Phase FINALE de la capture : restructure et reformule de façon EXHAUSTIVE "
                "et fidèle ce que l'expert a dit sur cette section. "
                "1) RESTRUCTURATION : organise le propos en prose claire ou en puces, dans "
                "un ordre logique aligné sur l'intitulé de la section. "
                "2) DOUBLONS : l'expert se répète et reformule d'un tour à l'autre — fusionne "
                "les redites en UNE seule formulation (la plus complète), sans perdre aucun "
                "détail propre à une variante. "
                "3) VOCABULAIRE : aligne les termes sur le 'domain_glossary' (terminologie "
                "métier Andritz) : remplace les mots mal transcrits ou approximatifs par le "
                "terme canonique du glossaire quand le contexte le confirme (ex: 'carte' -> "
                "'carde'), respecte la casse des acronymes. N'applique JAMAIS un terme du "
                "glossaire si le propos ne le concerne pas. "
                "N'invente AUCUNE information, ne supprime AUCUN fait substantiel, ne change "
                "aucune valeur numérique. Le 'static_context' et les 'kb_chunks' servent "
                "uniquement à caler la terminologie, jamais à ajouter du contenu. "
                "Réponds en Markdown, sans titre de section ni méta-commentaire."
            ),
        }
        response = await client.chat.completions.create(
            model=model,
            **_model_chat_kwargs(model, temperature=0.2),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Tu es un rédacteur technique. Synthèse exhaustive et fidèle : "
                        "restructurée, dédupliquée, vocabulaire aligné sur le glossaire "
                        "métier fourni. N'invente rien."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        )
        content = response.choices[0].message.content if response.choices else None
        synthesis = (content or "").strip()
        return synthesis or fallback
    except Exception:
        return fallback


async def generate_grounded_open_questions_async(
    context: str,
    chunks: Optional[List[str]] = None,
    metadatas: Optional[List[Dict[str, Any]]] = None,
    plan_section: Optional[Dict[str, Any]] = None,
    *,
    workspace_id: Optional[str] = None,
    max_questions: int = 5,
) -> List[Dict[str, Any]]:
    """LLM open questions grounded on what the expert stated + KB chunks.

    Returns specific, answerable gaps tied to the section (not the generic
    ``_BASE_GAPS`` taxonomy). Each item is
    ``{id, text, topic_id, subtopic_id, priority, status, source, grounding_status}``.

    Returns ``[]`` when no LLM is configured so callers can keep their existing
    deterministic fallback.
    """
    statements = (context or "").strip()
    if not statements:
        return []
    api_key, model = _resolve_finalize_llm_config(workspace_id)
    if not api_key:
        return []
    topic_id = (plan_section or {}).get("topic_id") if isinstance(plan_section, dict) else None
    subtopic_id = (plan_section or {}).get("subtopic_id") if isinstance(plan_section, dict) else None
    grounding_status = "kb_grounded" if chunks else "expert_statement_grounded"
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        payload = {
            "section": _section_label(plan_section),
            "expert_statements": statements[:6000],
            "kb_chunks": [str(c)[:600] for c in (chunks or [])[:4]],
            "kb_metadatas": [m for m in (metadatas or [])[:4] if isinstance(m, dict)],
            "max_questions": max(1, int(max_questions)),
            "instruction": (
                "À partir de ce que l'expert a réellement dit ('expert_statements') et des "
                "extraits de la base de connaissances ('kb_chunks'), identifie les VRAIS trous "
                "de connaissance restants pour cette section : informations promises mais non "
                "détaillées, valeurs/conditions manquantes, exceptions évoquées sans précision, "
                "contradictions avec la base. Formule des questions SPÉCIFIQUES et répondables, "
                "ancrées sur le contenu, jamais génériques. N'invente pas de sujet hors de ce "
                "qui a été dit. Retourne un JSON {questions: [{text, priority}]} où priority est "
                "un nombre 0..1 (1 = plus pressant)."
            ),
        }
        response = await client.chat.completions.create(
            model=model,
            **_model_chat_kwargs(model, temperature=0.2),
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "Grounded open questions JSON only. Specific, answerable, no generic gaps.",
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        )
        content = response.choices[0].message.content if response.choices else None
        if not content:
            return []
        parsed = json.loads(content)
        raw_questions = parsed.get("questions") if isinstance(parsed, dict) else None
        if not isinstance(raw_questions, list):
            return []
        items: List[Dict[str, Any]] = []
        for index, raw in enumerate(raw_questions, start=1):
            if isinstance(raw, str):
                raw = {"text": raw}
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("text") or raw.get("question") or "").strip()
            if not text:
                continue
            try:
                priority = float(raw.get("priority"))
            except (TypeError, ValueError):
                priority = 0.7
            items.append(
                {
                    "id": f"grounded-{(subtopic_id or topic_id or 'sec')}-{index:02d}",
                    "text": text,
                    "topic_id": topic_id,
                    "subtopic_id": subtopic_id,
                    "priority": round(min(max(priority, 0.0), 1.0), 2),
                    "status": "open",
                    "source": "oracle_grounded",
                    "grounding_status": grounding_status,
                }
            )
            if len(items) >= max(1, int(max_questions)):
                break
        return items
    except Exception:
        return []
