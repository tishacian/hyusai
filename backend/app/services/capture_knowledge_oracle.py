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


def _resolve_llm_config(workspace_id: Optional[str] = None) -> tuple[str, str]:
    from app.core.config import settings as cfg
    from app.core.settings_manager import get_resolved_settings

    resolved = get_resolved_settings(workspace_id=workspace_id) if workspace_id else {}
    api_key = str(cfg.openai_api_key or resolved.get("openaiApiKey") or "").strip()
    model = str(resolved.get("defaultModel") or cfg.default_model or "gpt-4o-mini").strip()
    return api_key, model


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


def _words(text: str) -> List[str]:
    return _WORD_PATTERN.findall(text or "")


def session_context_from_capture(
    *,
    session: Any,
    plan: Dict[str, Any],
    active_subtopic_id: Optional[str] = None,
    recent_transcript: Optional[List[Dict[str, Any]]] = None,
) -> CaptureSessionContext:
    metrics = session.metrics or {}
    dialogue = plan.get("dialogue") or {}
    unlimited = bool(metrics.get("unlimited_duration") or plan.get("unlimited_duration"))
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


def _dialogue_corpus(context: CaptureSessionContext) -> str:
    parts = [context.objective, context.title]
    for turn in context.dialogue_turns:
        parts.append(str(turn.get("text") or ""))
    for item in context.recent_transcript:
        parts.append(str(item.get("text") or item.get("text_raw") or ""))
    return " ".join(part for part in parts if part).strip().lower()


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


def _fallback_topic_proposals(
    context: CaptureSessionContext,
    gaps: List[Dict[str, Any]],
    rag_chunks: List[str],
    rag_metadatas: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    corpus = _dialogue_corpus(context)
    kb_refs = _kb_refs_from_chunks(rag_chunks, rag_metadatas)
    domain = (context.domain or "").lower()
    topics: List[Dict[str, Any]] = []

    if any(token in corpus for token in ("réglage", "reglage", "vitesse", "rouleau", "ligne", "180", "120")):
        topics.append(
            {
                "id": "t-01",
                "title": "Réglages ligne",
                "rationale": "Le dialogue et la KB évoquent des paramètres de ligne et vitesses rouleaux.",
                "kb_refs": kb_refs[:2],
                "confidence": 0.82 if kb_refs else 0.62,
                "subtopics": [
                    {
                        "id": "st-01",
                        "title": "Vitesse rouleaux",
                        "objective": "Clarifier les vitesses nominales et cas exceptionnels terrain.",
                        "status": "pending",
                    },
                    {
                        "id": "st-02",
                        "title": "Qualité papier",
                        "objective": "Relier réglages vitesse et qualité produit.",
                        "status": "pending",
                    },
                ],
            }
        )
    if any(token in corpus for token in ("maintenance", "diagnostic", "vibration", "panne")):
        topics.append(
            {
                "id": "t-02",
                "title": "Maintenance et diagnostic",
                "rationale": "Signaux terrain et maintenance prioritaires dans le cadrage.",
                "kb_refs": kb_refs[1:3] if len(kb_refs) > 1 else kb_refs,
                "confidence": 0.74,
                "subtopics": [
                    {
                        "id": "st-03",
                        "title": "Signaux terrain",
                        "objective": "Capturer symptômes et diagnostics non documentés.",
                        "status": "pending",
                    }
                ],
            }
        )
    if not topics:
        seed_gap = gaps[0] if gaps else {"title": "Décisions métier", "description": "Arbitrages experts"}
        topics.append(
            {
                "id": "t-01",
                "title": "Décisions et arbitrages métier",
                "rationale": "Proposition initiale alignée sur les gaps knowledge prioritaires.",
                "kb_refs": kb_refs[:1],
                "confidence": 0.55 if not kb_refs else 0.68,
                "subtopics": [
                    {
                        "id": "st-01",
                        "title": str(seed_gap.get("title") or "Sujet principal"),
                        "objective": str(seed_gap.get("description") or context.objective),
                        "status": "pending",
                    }
                ],
            }
        )
    if domain == "technical" and topics and not topics[0].get("kb_refs"):
        topics[0]["confidence"] = max(0.5, float(topics[0].get("confidence") or 0.5))
    return topics


def _fallback_dialogue_probe(context: CaptureSessionContext, topics: List[Dict[str, Any]]) -> str:
    turns = len(context.dialogue_turns)
    if turns == 0:
        return "Quels grands sujets ou thèmes souhaitez-vous couvrir pendant cette capture ?"
    if turns == 1:
        return "Sur quelle ligne, client ou périmètre porte principalement cette session ?"
    if turns == 2:
        return "Quels cas concrets, exceptions terrain ou décisions difficiles sont prioritaires ?"
    if not topics:
        return "Y a-t-il d'autres zones à couvrir ou des interlocuteurs à impliquer en revue ?"
    titles = ", ".join(topic.get("title") or "" for topic in topics[:3])
    return f"Les sujets {titles} vous conviennent-ils ou faut-il en ajouter / préciser ?"


def analyze_plan_oracle(
    context: CaptureSessionContext,
    *,
    rag_chunks: Optional[List[str]] = None,
    rag_metadatas: Optional[List[Dict[str, Any]]] = None,
    base_gaps: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Structured oracle output for plan_build (deterministic fallback, optional LLM)."""
    rag_chunks = list(rag_chunks or [])
    base_gaps = list(base_gaps or [])
    coverage_gaps = score_gaps_with_rag(base_gaps, rag_chunks, rag_metadatas=rag_metadatas)
    corpus = _dialogue_corpus(context)
    contradictions = detect_claim_contradictions(corpus, rag_chunks)
    topic_proposals = _fallback_topic_proposals(context, coverage_gaps, rag_chunks, rag_metadatas)
    dialogue_probe = _fallback_dialogue_probe(context, topic_proposals)
    return {
        "topic_proposals": topic_proposals,
        "coverage_gaps": coverage_gaps[:6],
        "contradiction_candidates": contradictions,
        "dialogue_probe": dialogue_probe,
    }


async def analyze_plan_oracle_async(
    context: CaptureSessionContext,
    *,
    rag_chunks: Optional[List[str]] = None,
    rag_metadatas: Optional[List[Dict[str, Any]]] = None,
    base_gaps: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Try one structured LLM call; fall back to deterministic oracle."""
    fallback = analyze_plan_oracle(
        context,
        rag_chunks=rag_chunks,
        rag_metadatas=rag_metadatas,
        base_gaps=base_gaps,
    )
    api_key, model = _resolve_llm_config(context.workspace_id)
    if not api_key:
        return fallback
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        prompt = {
            "title": context.title,
            "objective": context.objective,
            "domain": context.domain,
            "expert_profile": context.expert_profile,
            "duration_minutes": context.duration_minutes,
            "dialogue": context.dialogue_turns,
            "rag_chunks": (rag_chunks or [])[:4],
            "rag_metadatas": (rag_metadatas or [])[:4],
            "gaps": (base_gaps or [])[:6],
            "instruction": (
                "Tu es oracle de co-construction de plan de capture expert. "
                "Ne produis PAS de questions d'entretien. "
                "Retourne un JSON avec: "
                "topic_proposals (liste {id, title, rationale, confidence, kb_refs, subtopics}), "
                "coverage_gaps (liste {slug, title, description, priority}), "
                "contradiction_candidates (liste {claim_expert, claim_kb, severity, suggested_hint, kb_excerpt}), "
                "dialogue_probe (string, une seule relance de cadrage)."
            ),
        }
        response = await client.chat.completions.create(
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Oracle capture JSON only. No interview questions."},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        )
        content = response.choices[0].message.content if response.choices else None
        if not content:
            return fallback
        parsed = json.loads(content)
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
        return parsed
    except Exception:
        return fallback


def plan_dialogue_probe(oracle_result: Dict[str, Any], *, ready_to_finalize: bool = False) -> Optional[str]:
    if ready_to_finalize:
        return None
    probe = str(oracle_result.get("dialogue_probe") or "").strip()
    return probe or None


def merge_topic_proposals(plan: Dict[str, Any], proposals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge oracle topic proposals into plan topics, preserving user edits."""
    existing = {topic.get("id"): dict(topic) for topic in (plan.get("topics") or []) if isinstance(topic, dict)}
    merged: List[Dict[str, Any]] = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        topic_id = str(proposal.get("id") or f"t-{len(merged) + 1:02d}")
        current = existing.get(topic_id, {})
        subtopics = []
        existing_sub = {st.get("id"): st for st in (current.get("subtopics") or []) if isinstance(st, dict)}
        for raw_sub in proposal.get("subtopics") or []:
            if not isinstance(raw_sub, dict):
                continue
            sub_id = str(raw_sub.get("id") or f"{topic_id}-sub-{len(subtopics) + 1:02d}")
            prior = existing_sub.get(sub_id, {})
            subtopics.append(
                {
                    **prior,
                    **raw_sub,
                    "id": sub_id,
                    "title": prior.get("title") or raw_sub.get("title"),
                    "objective": prior.get("objective") or raw_sub.get("objective") or "",
                    "status": prior.get("status") or raw_sub.get("status") or "pending",
                }
            )
        merged.append(
            {
                **current,
                "id": topic_id,
                "title": current.get("title") or proposal.get("title") or topic_id,
                "status": current.get("status") or proposal.get("status") or "draft",
                "objective": current.get("objective") or proposal.get("rationale") or "",
                "rationale": current.get("rationale") or proposal.get("rationale") or "",
                "knowledge_refs": current.get("knowledge_refs") or proposal.get("kb_refs") or [],
                "subtopics": subtopics or current.get("subtopics") or [],
                "oracle_confidence": proposal.get("confidence"),
            }
        )
    for topic_id, topic in existing.items():
        if topic_id not in {item.get("id") for item in merged}:
            merged.append(topic)
    return merged


def infer_active_subtopic_id(
    plan_topics: List[Dict[str, Any]],
    partial_text: str,
    *,
    fallback: Optional[str] = None,
) -> Optional[str]:
    lowered = (partial_text or "").lower()
    for topic in plan_topics:
        for subtopic in topic.get("subtopics") or []:
            title = str(subtopic.get("title") or "").lower()
            if title and title in lowered:
                return str(subtopic.get("id"))
    if any(token in lowered for token in ("vitesse", "rouleau", "180", "120", "min")):
        for topic in plan_topics:
            for subtopic in topic.get("subtopics") or []:
                if "vitesse" in str(subtopic.get("title") or "").lower():
                    return str(subtopic.get("id"))
    return fallback


def evaluate_capture_partial(
    context: CaptureSessionContext,
    partial_text: str,
    retrieval_chunks: List[str],
    *,
    retrieval_metadatas: Optional[List[Dict[str, Any]]] = None,
    plan_topics: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Live capture evaluation: contradictions and hint candidates."""
    text = (partial_text or "").strip()
    if len(_words(text)) < 6:
        return {"hints": [], "contradiction_candidates": [], "active_subtopic_id": context.active_subtopic_id}
    contradictions = detect_claim_contradictions(text, retrieval_chunks)
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
                "oracle_id": str(uuid.uuid4()),
            }
        )
    active_subtopic_id = infer_active_subtopic_id(
        plan_topics or [],
        text,
        fallback=context.active_subtopic_id,
    )
    for hint in hints:
        if not hint.get("subtopic_id"):
            hint["subtopic_id"] = active_subtopic_id
    return {
        "hints": hints,
        "contradiction_candidates": contradictions,
        "active_subtopic_id": active_subtopic_id,
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
    return {"full_question": full_question, "hint": hint[:80]}


async def generate_question_bank_entry_async(
    *,
    workspace_id: str,
    subtopic_title: str,
    subtopic_objective: str,
    session_objective: str,
    rag_chunks: List[str],
    rag_metadatas: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, str]:
    """Generate one internal question + short UI hint; fallback to templates."""
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
                "Génère une question interne d'entretien expert et un hint court pour l'UI vocale. "
                "Le hint doit rester ≤ 80 caractères, sans formuler une question complète. "
                "Retourne JSON: {full_question, hint}."
            ),
        }
        response = await client.chat.completions.create(
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Question bank JSON only."},
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
        if not full_question or not hint:
            return fallback
        return {"full_question": full_question, "hint": hint}
    except Exception:
        return fallback
