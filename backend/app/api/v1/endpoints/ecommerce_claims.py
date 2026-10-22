"""Read surface of the released Réclamations app; execution stays on /work."""

from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.v1.endpoints import work
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.claim_action import ClaimAction
from app.models.run import Run
from app.models.user import User
from app.models.workspace import Workspace
from app.services.connectors.generic import postgresql_claims as pg
from app.services.ecommerce import claims as claims
from app.services.ecommerce import policy_settings
from app.services.ecommerce.resolution_policy import ResolutionPolicy
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
def queue(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    config = _access(db, workspace, user)
    try:
        stage = config.get("stage_claim_ids") or config["allowed_claim_ids"]
        return pg.queue(workspace, stage)
    except pg.ClaimReadError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code}) from None


@router.get("/triage")
def triage(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.ecommerce.triage import read_triage

    _access(db, workspace, user)
    return read_triage(db, workspace)


class PolicyUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy: ResolutionPolicy


@router.get("/policy")
def resolution_policy(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    return policy_settings.read(db, workspace, user)


@router.put("/policy")
def update_resolution_policy(
    body: PolicyUpdateBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    try:
        result = policy_settings.update(db, workspace, user, body.policy, body.expected_sha256)
        db.commit()
        return result
    except policy_settings.PolicySettingsError as exc:
        db.rollback()
        raise HTTPException(exc.status, detail={"code": exc.code}) from None
    except pg.ClaimReadError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, detail={"code": exc.code}) from None
    except HTTPException as exc:
        db.rollback()
        # Collection ACLs intentionally hide unreadable sources with a 404.
        # Keep that detail private and present the policy as unverifiable.
        if exc.status_code == 404:
            raise HTTPException(409, detail={"code": "CLAIM_POLICY_DOCUMENT_UNAVAILABLE"}) from None
        raise
    except ValueError:
        db.rollback()
        raise HTTPException(409, detail={"code": "CLAIM_POLICY_DOCUMENT_UNAVAILABLE"}) from None


@router.get("/{claim_id}")
def dossier(
    claim_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    config = _access(db, workspace, user)
    if claim_id not in config["allowed_claim_ids"]:
        raise HTTPException(404, detail={"code": "CLAIM_NOT_FOUND"})
    try:
        result = pg.snapshot(workspace, claim_id)
        # Only genuinely ingested, readable, unchanged original sources.
        reader = SimpleNamespace(initiated_by_user_id=user.id)
        sources = claims._sources(db, workspace, reader, result, ("policy", "delivery", "refund"))
        result["sources"] = [
            {
                "document_id": (s.source_metadata or {}).get("document_id"),
                "collection": c.slug,
                "filename": s.filename,
                "title": s.filename,
                "sha256": ref["sha256"],
                "version": ref["version"],
                "reference": ref["document_key"],
            }
            for ref, s, c in sources
        ]
        order_id = result["data"]["context"][0]["order_id"]
        result["receipts"] = [
            r.receipt
            for r in db.query(ClaimAction)
            .filter(
                ClaimAction.workspace_id == workspace.id,
                ClaimAction.order_id == order_id,
            )
            .order_by(ClaimAction.created_at)
            .all()
        ]
        latest = (
            db.query(Run)
            .filter(
                Run.workspace_id == workspace.id,
                Run.initiated_by_user_id == user.id,
                Run.input_ref["claim_id"].as_string() == claim_id,
                Run.input_ref["_ingress"]["adapter"]["binding_key"].as_string()
                == "showcase.claims.investigate",
            )
            .order_by(Run.started_at.desc())
            .first()
        )
        result["latest_run_id"] = latest.id if latest else None
        return result
    except pg.ClaimReadError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code}) from None
    except ValueError:
        raise HTTPException(409, detail={"code": "CLAIM_SOURCE_REVISION_CHANGED"}) from None
