"""Canonical answer service — Dify-style annotation reply, Agentium-native."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.canonical_answer import CanonicalAnswer
from app.services.audit_logger import emit_audit_event


class CanonicalAnswerError(ValueError):
    """Raised on invalid canonical-answer inputs."""


_TOKEN_RE = re.compile(r"[a-z0-9À-ÿ]+", re.IGNORECASE)


def normalize_question(question: str) -> str:
    tokens = _TOKEN_RE.findall((question or "").lower())
    return " ".join(tokens)[:2000]


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if not a_tokens or not b_tokens:
        return 0.0
    overlap = len(a_tokens & b_tokens)
    return overlap / max(len(a_tokens | b_tokens), 1)


def create_canonical_answer(
    db: DBSession,
    *,
    workspace_id: str,
    question: str,
    answer: str,
    actor: Optional[str] = None,
    source_decision_id: Optional[str] = None,
    source_feedback_id: Optional[str] = None,
    source_run_id: Optional[str] = None,
    similarity_threshold: float = 0.9,
) -> CanonicalAnswer:
    if not workspace_id:
        raise CanonicalAnswerError("workspace_id is required")
    if not question or not question.strip():
        raise CanonicalAnswerError("question is required")
    if not answer or not answer.strip():
        raise CanonicalAnswerError("answer is required")
    normalized = normalize_question(question)
    if not normalized:
        raise CanonicalAnswerError("question has no searchable tokens")

    row = CanonicalAnswer(
        id=str(uuid4()),
        workspace_id=workspace_id,
        question=question.strip(),
        answer=answer.strip(),
        normalized_question=normalized,
        source_decision_id=source_decision_id,
        source_feedback_id=source_feedback_id,
        source_run_id=source_run_id,
        similarity_threshold=max(0.5, min(1.0, float(similarity_threshold or 0.9))),
        created_by=actor or "demo-user",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    emit_audit_event(
        workspace_id=workspace_id,
        event_type="canonical_answer.created",
        actor=actor or "demo-user",
        details={
            "canonical_answer_id": row.id,
            "source_decision_id": source_decision_id,
            "source_feedback_id": source_feedback_id,
            "source_run_id": source_run_id,
            "similarity_threshold": row.similarity_threshold,
        },
        db=db,
    )
    return row


def find_canonical_answer(
    db: DBSession,
    *,
    workspace_id: str,
    query: str,
) -> Optional[Tuple[CanonicalAnswer, float]]:
    normalized = normalize_question(query)
    if not workspace_id or not normalized:
        return None
    rows = (
        db.query(CanonicalAnswer)
        .filter(CanonicalAnswer.workspace_id == workspace_id)
        .order_by(CanonicalAnswer.updated_at.desc())
        .limit(200)
        .all()
    )
    best: Optional[Tuple[CanonicalAnswer, float]] = None
    for row in rows:
        score = _similarity(normalized, row.normalized_question or "")
        if score >= float(row.similarity_threshold or 0.9):
            if best is None or score > best[1]:
                best = (row, score)
    return best


def record_hit(
    db: DBSession,
    *,
    canonical_answer: CanonicalAnswer,
    query: str,
    score: float,
    actor: Optional[str] = None,
) -> None:
    canonical_answer.hit_count = int(canonical_answer.hit_count or 0) + 1
    canonical_answer.updated_at = datetime.utcnow()
    emit_audit_event(
        workspace_id=canonical_answer.workspace_id,
        event_type="canonical_answer.hit",
        actor=actor or "demo-user",
        details={
            "canonical_answer_id": canonical_answer.id,
            "query": query[:500],
            "score": score,
            "hit_count": canonical_answer.hit_count,
        },
        db=db,
    )


def serialize_canonical_answer(row: CanonicalAnswer) -> Dict[str, Any]:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "question": row.question,
        "answer": row.answer,
        "source_decision_id": row.source_decision_id,
        "source_feedback_id": row.source_feedback_id,
        "source_run_id": row.source_run_id,
        "similarity_threshold": row.similarity_threshold,
        "hit_count": row.hit_count,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
