"""Read surface of the released Réclamations app; execution stays on /work."""
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.endpoints import work
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.models.claim_action import ClaimAction
from app.models.run import Run
from app.services import ecommerce_claims as claims
from app.services.connectors.generic import postgresql_claims as pg
from app.services.experience import lifecycle

router = APIRouter()


def _access(db, workspace, user):
    work._require_enabled(workspace)
    work._enforce_consume(db, user=user, workspace=workspace)
    try:
        work._resolve_for_user(db, workspace=workspace, user=user, slug="reclamations")
        return claims._config(workspace)
    except lifecycle.ExperienceError as exc:
        raise HTTPException(exc.status_code, detail=exc.payload()) from None
    except ValueError:
        raise HTTPException(404, detail={"code": "ECOMMERCE_CLAIMS_UNAVAILABLE"}) from None


@router.get("")
def queue(workspace: Workspace = Depends(get_current_workspace), user: User = Depends(get_current_user),
          db: Session = Depends(get_db)):
    config = _access(db, workspace, user)
    try:
        stage = config.get("stage_claim_ids") or config["allowed_claim_ids"]
        return pg.queue(workspace, stage)
    except pg.ClaimReadError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code}) from None


@router.get("/{claim_id}")
def dossier(claim_id: str, workspace: Workspace = Depends(get_current_workspace),
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    config = _access(db, workspace, user)
    if claim_id not in config["allowed_claim_ids"]:
        raise HTTPException(404, detail={"code": "CLAIM_NOT_FOUND"})
    try:
        result = pg.snapshot(workspace, claim_id)
        # Only genuinely ingested, readable, unchanged original sources.
        reader = SimpleNamespace(initiated_by_user_id=user.id)
        sources = claims._sources(db, workspace, reader, result, ("policy", "delivery", "refund"))
        result["sources"] = [{"document_id": (s.source_metadata or {}).get("document_id"),
                             "collection": c.slug, "filename": s.filename, "title": s.filename,
                             "sha256": ref["sha256"], "version": ref["version"], "reference": ref["document_key"]} for ref, s, c in sources]
        order_id = result["data"]["context"][0]["order_id"]
        result["receipts"] = [r.receipt for r in db.query(ClaimAction).filter(
            ClaimAction.workspace_id == workspace.id, ClaimAction.order_id == order_id,
        ).order_by(ClaimAction.created_at).all()]
        latest = db.query(Run).filter(Run.workspace_id == workspace.id, Run.initiated_by_user_id == user.id,
            Run.input_ref["claim_id"].as_string() == claim_id,
            Run.input_ref["_ingress"]["adapter"]["binding_key"].as_string() == "showcase.claims.investigate",
        ).order_by(Run.started_at.desc()).first()
        result["latest_run_id"] = latest.id if latest else None
        return result
    except pg.ClaimReadError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code}) from None
    except ValueError:
        raise HTTPException(409, detail={"code": "CLAIM_SOURCE_REVISION_CHANGED"}) from None
