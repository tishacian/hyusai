"""Client360 PDR pre-MVP API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.action_plans import serialize_action_item
from app.services.client360_pdr import (
    client360_scope,
    create_mail_draft,
    customer_payload,
    list_mapping_rules,
    list_opportunities,
    opportunity_facets,
    patch_action,
    patch_mapping_rule,
    patch_opportunity,
    record_impact,
    run_opportunity_engine,
    serialize_impact_event,
    serialize_mapping_rule,
    serialize_mail_draft,
    serialize_opportunity,
    summary_payload,
    upsert_mapping_rule,
)

router = APIRouter()


class MailDraftCreate(BaseModel):
    opportunity_id: str = Field(..., min_length=1)
    language: str = Field(default="fr", max_length=16)
    include_prices: bool = False


class Client360ActionPatch(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    owner_label: Optional[str] = None
    mail_draft_id: Optional[str] = None
    mail_status: Optional[str] = None
    sent_body: Optional[str] = None
    sent_at: Optional[datetime] = None
    notes: Optional[str] = None
    outcome_status: Optional[str] = None


class ImpactCreate(BaseModel):
    impact_type: str = Field(..., description="response, quote, order, lost, no_response or note")
    attribution: str = Field(default="unknown", description="direct, probable, unknown or none")
    reason: str = Field(default="unknown", description="price, competitor, no_need, wrong_contact, timing, hub, technical_mismatch, bad_data, other or unknown")
    summary: str = ""
    opportunity_id: Optional[str] = None
    mail_draft_id: Optional[str] = None
    quote_value: Optional[float] = None
    order_value: Optional[float] = None
    currency: Optional[str] = None
    occurred_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MappingRuleWrite(BaseModel):
    source_part_reference: Optional[str] = None
    source_part_label: Optional[str] = None
    source_part_family: Optional[str] = None
    source_system: str = "sap"
    technology: Optional[str] = None
    pdr_family: str = Field(..., min_length=1)
    recommended_quantity: Optional[float] = None
    periodicity_weeks: Optional[float] = None
    delivery_time_weeks: Optional[float] = None
    status: str = "candidate"
    confidence: Optional[float] = None
    notes: str = ""
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MappingRulePatch(BaseModel):
    source_part_reference: Optional[str] = None
    source_part_label: Optional[str] = None
    source_part_family: Optional[str] = None
    source_system: Optional[str] = None
    technology: Optional[str] = None
    pdr_family: Optional[str] = None
    recommended_quantity: Optional[float] = None
    periodicity_weeks: Optional[float] = None
    delivery_time_weeks: Optional[float] = None
    status: Optional[str] = None
    confidence: Optional[float] = None
    notes: Optional[str] = None
    evidence_refs: Optional[list[dict[str, Any]]] = None
    metadata: Optional[dict[str, Any]] = None


class EngineRunCreate(BaseModel):
    dry_run: bool = False


class OpportunityPatch(BaseModel):
    status: Optional[str] = None
    validation_reason: Optional[str] = None
    rejection_reason: Optional[str] = None
    notes: Optional[str] = None
    owner_label: Optional[str] = None


@router.get("/summary")
def client360_summary(
    include_mail_ai: bool = Query(default=True),
    include_workspace_candidates: bool = Query(default=True),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    return summary_payload(
        db,
        workspace,
        include_mail_ai=include_mail_ai,
        include_workspace_candidates=include_workspace_candidates,
    )


@router.get("/scope")
def client360_scope_get(
    workspace: Workspace = Depends(get_current_workspace),
):
    return {"scope": client360_scope(workspace)}


@router.get("/opportunities")
def client360_opportunities(
    status: Optional[str] = Query(default=None),
    customer: Optional[str] = Query(default=None),
    country: Optional[str] = Query(default=None),
    hub: Optional[str] = Query(default=None),
    technology: Optional[str] = Query(default=None),
    part_family: Optional[str] = Query(default=None),
    confidence: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    return {
        "items": list_opportunities(
            db,
            workspace,
            status=status,
            customer=customer,
            country=country,
            hub=hub,
            technology=technology,
            part_family=part_family,
            confidence=confidence,
            limit=limit,
        ),
        "facets": opportunity_facets(db, workspace),
    }


@router.post("/engines/opportunities/run")
def client360_opportunity_engine_run(
    body: EngineRunCreate,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    result = run_opportunity_engine(db, workspace, dry_run=body.dry_run)
    if body.dry_run:
        db.rollback()
    else:
        db.commit()
    return result


@router.patch("/opportunities/{opportunity_id}")
def client360_opportunity_patch(
    opportunity_id: str,
    body: OpportunityPatch,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    try:
        opportunity = patch_opportunity(db, workspace, opportunity_id, body.model_dump(exclude_unset=True))
        db.commit()
        db.refresh(opportunity)
        return {"opportunity": serialize_opportunity(opportunity)}
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/mappings")
def client360_mappings(
    status: Optional[str] = Query(default=None),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    return {"items": list_mapping_rules(db, workspace, status=status)}


@router.post("/mappings")
def client360_mapping_create(
    body: MappingRuleWrite,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        row = upsert_mapping_rule(db, workspace, user, body.model_dump())
        db.commit()
        db.refresh(row)
        return {"mapping": serialize_mapping_rule(row)}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/mappings/{mapping_id}")
def client360_mapping_patch(
    mapping_id: str,
    body: MappingRulePatch,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        row = patch_mapping_rule(db, workspace, user, mapping_id, body.model_dump(exclude_unset=True))
        db.commit()
        db.refresh(row)
        return {"mapping": serialize_mapping_rule(row)}
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/customers/{customer_id}")
def client360_customer(
    customer_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    return customer_payload(db, workspace, customer_id)


@router.post("/mail-drafts")
def client360_mail_draft_create(
    body: MailDraftCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        draft, action = create_mail_draft(
            db,
            workspace,
            user,
            opportunity_id=body.opportunity_id,
            language=body.language,
            include_prices=body.include_prices,
        )
        db.commit()
        db.refresh(draft)
        db.refresh(action)
        return {"mail_draft": serialize_mail_draft(draft), "action": serialize_action_item(action)}
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/actions/{action_id}")
def client360_action_patch(
    action_id: str,
    body: Client360ActionPatch,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        action = patch_action(db, workspace, user, action_id, body.model_dump(exclude_unset=True))
        db.commit()
        db.refresh(action)
        return {"action": serialize_action_item(action)}
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/actions/{action_id}/impact")
def client360_action_impact(
    action_id: str,
    body: ImpactCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        event = record_impact(
            db,
            workspace,
            user,
            action_id,
            impact_type=body.impact_type,
            attribution=body.attribution,
            reason=body.reason,
            summary=body.summary,
            opportunity_id=body.opportunity_id,
            mail_draft_id=body.mail_draft_id,
            quote_value=body.quote_value,
            order_value=body.order_value,
            currency=body.currency,
            occurred_at=body.occurred_at,
            metadata=body.metadata,
        )
        db.commit()
        db.refresh(event)
        return {"impact_event": serialize_impact_event(event)}
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
