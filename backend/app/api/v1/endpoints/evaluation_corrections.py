"""Propose and explicitly review draft-only corrections; never publish here."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.services.evaluation import corrections
from app.services.systems.flow_publication import FlowPublicationError

router = APIRouter()


from app.services.evaluation.corrections import CorrectionBody


class ApplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_draft_revision: int = Field(ge=1)
    reviewed_proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _execute(db, operation):
    try:
        result = operation()
        db.commit()
        return result
    except FlowPublicationError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, exc.payload()) from exc
    except Exception:
        db.rollback()
        raise


@router.get("")
def list_for_run(run_id: str, db: Session = Depends(get_db), user=Depends(get_current_user), workspace=Depends(get_current_workspace)):
    return _execute(db, lambda: {"corrections": [corrections.serialize(row) for row in corrections.list_proposals(db, user=user, workspace=workspace, run_id=run_id)]})


@router.get("/context")
def context(run_id: str, node_id: str, evaluation_id: str,
            db: Session = Depends(get_db), user=Depends(get_current_user), workspace=Depends(get_current_workspace)):
    return _execute(db, lambda: corrections.context_payload(db, user=user, workspace=workspace, run_id=run_id, node_id=node_id, evaluation_id=evaluation_id))


@router.post("")
def propose(body: CorrectionBody, db: Session = Depends(get_db), user=Depends(get_current_user), workspace=Depends(get_current_workspace)):
    return _execute(db, lambda: corrections.serialize(corrections.create_proposal(db, user=user, workspace=workspace, **body.model_dump())))


@router.get("/{proposal_id}")
def get(proposal_id: str, db: Session = Depends(get_db), user=Depends(get_current_user), workspace=Depends(get_current_workspace)):
    return _execute(db, lambda: corrections.serialize(corrections.get_proposal(db, user=user, workspace=workspace, proposal_id=proposal_id)))


@router.post("/{proposal_id}/apply")
def apply(proposal_id: str, body: ApplyBody, db: Session = Depends(get_db), user=Depends(get_current_user), workspace=Depends(get_current_workspace)):
    return _execute(db, lambda: corrections.serialize(corrections.apply_proposal(db, user=user, workspace=workspace, proposal_id=proposal_id, **body.model_dump())))
