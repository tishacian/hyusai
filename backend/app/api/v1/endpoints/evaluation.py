"""Evaluation API — LLM-as-Judge scoring and history"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.db.base import get_db
from app.models.evaluation import EvaluationScore
from app.services.evaluation.judge import get_judge_service, DIMENSION_LABELS

router = APIRouter()


class EvalRequest(BaseModel):
    query: str
    response: str
    system_prompt: str = ""
    context_chunks: list[str] = []
    turn_number: int = 1
    session_id: str = None
    agent_id: str = None


@router.post("/score")
async def score_response(req: EvalRequest, db: DBSession = Depends(get_db)):
    judge = get_judge_service()
    result = await judge.evaluate(
        query=req.query,
        response=req.response,
        system_prompt=req.system_prompt,
        context_chunks=req.context_chunks,
        turn_number=req.turn_number,
        session_id=req.session_id,
        agent_id=req.agent_id,
    )

    row = EvaluationScore(
        id=result["id"],
        session_id=result["session_id"],
        agent_id=result["agent_id"],
        turn_number=result["turn_number"],
        query=result["query"],
        scores=result["scores"],
        composite_score=result["composite_score"],
        hallucination_rate=result["hallucination_rate"],
        drift_rate=result["drift_rate"],
        claim_audit=result["claim_audit"],
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()

    return result


@router.get("/history")
async def evaluation_history(agent_id: str = None, limit: int = 20, db: DBSession = Depends(get_db)):
    judge = get_judge_service()
    history = await judge.get_evaluation_history(db, agent_id=agent_id, limit=limit)
    return {"evaluations": history}


@router.get("/dimensions")
async def get_dimensions():
    return {"dimensions": DIMENSION_LABELS}


@router.get("/latest")
async def latest_evaluation(agent_id: str = None, db: DBSession = Depends(get_db)):
    q = db.query(EvaluationScore).order_by(EvaluationScore.created_at.desc())
    if agent_id:
        q = q.filter(EvaluationScore.agent_id == agent_id)
    row = q.first()
    if not row:
        return {"evaluation": None}
    return {
        "evaluation": {
            "id": row.id,
            "scores": row.scores,
            "composite_score": row.composite_score,
            "hallucination_rate": row.hallucination_rate,
            "drift_rate": row.drift_rate,
            "claim_audit": row.claim_audit,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
    }
