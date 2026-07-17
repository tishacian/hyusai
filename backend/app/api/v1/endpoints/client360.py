"""Client360 PDR pre-MVP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.dependencies import require_app_entitlement
from app.core.iam.roles import ADMIN_ROLE_TEMPLATES, normalize_role_template
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.action_plans import serialize_action_item
from app.services.client360_alerts import alerts_payload
from app.services.client360_chat import handle_client360_chat_query
from app.services.client360_contract import CLIENT360_INSTALLED_BASE_COLLECTION_SLUG
from app.services.client360_pdr import (
    campaign_stats,
    client360_mail_settings_payload,
    client360_scope,
    create_campaign,
    create_mail_draft,
    customer_payload,
    generate_campaign_drafts,
    list_campaigns,
    list_mapping_rules,
    list_opportunities,
    opportunity_facets,
    patch_action,
    patch_campaign,
    patch_client360_mail_settings,
    patch_mapping_rule,
    patch_opportunity,
    prepare_campaign_follow_ups,
    record_impact,
    run_opportunity_engine,
    send_mail_draft,
    serialize_campaign,
    serialize_impact_event,
    serialize_mail_draft,
    serialize_mapping_rule,
    serialize_opportunity,
    summary_payload,
    upsert_mapping_rule,
)
from app.services.client360_spl_adapter import (
    preview_archive_mvp_orphan_sources,
    sync_sources_from_collection,
)
from app.services.iam.app_entitlements import (
    CLIENT360_APP,
    WorkspaceEntitlementMutationConflictError,
    lock_workspace_for_app_entitlement_mutation,
)

router = APIRouter(dependencies=[Depends(require_app_entitlement(CLIENT360_APP))])


class MailDraftCreate(BaseModel):
    opportunity_id: str = Field(..., min_length=1)
    language: str = Field(default="fr", max_length=16)
    include_prices: bool = False


class MailDraftSend(BaseModel):
    to_email: str = Field(..., min_length=3, max_length=320)
    subject: Optional[str] = Field(default=None, max_length=255)
    body: Optional[str] = None


class Client360ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = None
    assistant_profile: Optional[str] = None


class Client360MailSettingsPatch(BaseModel):
    enabled: Optional[bool] = None
    host: Optional[str] = None
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    username: Optional[str] = None
    password: Optional[str] = None
    clear_password: Optional[bool] = None
    password_env_var: Optional[str] = None
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    ssl: Optional[bool] = None
    starttls: Optional[bool] = None
    timeout_seconds: Optional[float] = Field(default=None, ge=1, le=120)


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
    reason: str = Field(
        default="unknown",
        description="price, competitor, no_need, wrong_contact, timing, hub, technical_mismatch, bad_data, other or unknown",
    )
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


class SyncFromCollectionBody(BaseModel):
    collection_slug: str = Field(
        default=CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
        min_length=1,
        max_length=120,
    )
    dry_run: bool = False
    scope: str = Field(
        default="phase1",
        description="phase1 (Greece/Turkey + pilot techs) or all",
    )
    rehydrate_mvp: bool = Field(
        default=True,
        description="Link existing MVP pilot Client360DataSource rows to the unified collection",
    )
    include_purchase_history: bool = Field(
        default=False,
        description=(
            "Phase-2 opt-in: sync Histo_Achat purchase_history feed "
            "(also included when scope=all)"
        ),
    )


class OpportunityPatch(BaseModel):
    status: Optional[str] = None
    validation_reason: Optional[str] = None
    rejection_reason: Optional[str] = None
    notes: Optional[str] = None
    owner_label: Optional[str] = None


class CampaignSelectionCriteria(BaseModel):
    status: Optional[str] = None
    customer: Optional[str] = None
    country: Optional[str] = None
    hub: Optional[str] = None
    technology: Optional[str] = None
    part_family: Optional[str] = None
    confidence: Optional[str] = None
    limit: Optional[int] = Field(default=None, ge=1, le=500)


class CampaignCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    campaign_type: str = Field(
        ...,
        description="first_replacement, maintenance_education, renewal, cross_selling, upselling or free",
    )
    description: str = ""
    status: str = "draft"
    selection_criteria: CampaignSelectionCriteria = Field(default_factory=CampaignSelectionCriteria)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CampaignPatch(BaseModel):
    name: Optional[str] = None
    campaign_type: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    selection_criteria: Optional[CampaignSelectionCriteria] = None


class CampaignDraftsCreate(BaseModel):
    language: str = Field(default="fr", max_length=16)
    include_prices: bool = False
    limit: Optional[int] = Field(default=None, ge=1, le=500)
    follow_up: bool = False


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


@router.get("/alerts")
def client360_alerts(
    limit: int = Query(default=200, ge=1, le=500),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    return alerts_payload(db, workspace, limit=limit)


@router.post("/chat")
async def client360_chat(
    payload: Client360ChatRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Dedicated Client360 assistant.

    Fully decoupled from the general Andritz research chat: this endpoint only
    serves the Client360 application's own assistant tab and always answers
    within the Client360 PDR domain (``require_trigger=False``).
    """
    result = await handle_client360_chat_query(
        db,
        workspace,
        user,
        query=payload.query,
        assistant_profile=payload.assistant_profile,
        session_id=payload.session_id,
        require_trigger=False,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Client360 assistant is not available for this workspace.",
        )
    return result


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


@router.post("/sources/sync-from-collection")
def client360_sources_sync_from_collection(
    body: SyncFromCollectionBody,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Map Installed_base_SPL / pilot spreadsheets into Client360DataSource rows."""
    scope = (body.scope or "phase1").strip().lower()
    if scope not in {"phase1", "all"}:
        raise HTTPException(status_code=400, detail="scope must be 'phase1' or 'all'")
    try:
        result = sync_sources_from_collection(
            db,
            workspace,
            collection_slug=body.collection_slug,
            dry_run=body.dry_run,
            scope=scope,
            rehydrate_mvp=body.rehydrate_mvp,
            include_purchase_history=body.include_purchase_history,
        )
        if body.dry_run:
            result["mvp_archive_preview"] = preview_archive_mvp_orphan_sources(
                db, workspace, collection_slug=body.collection_slug
            )
            db.rollback()
        else:
            db.commit()
        return result
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/opportunities/{opportunity_id}")
def client360_opportunity_patch(
    opportunity_id: str,
    body: OpportunityPatch,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    try:
        opportunity = patch_opportunity(
            db, workspace, opportunity_id, body.model_dump(exclude_unset=True)
        )
        db.commit()
        db.refresh(opportunity)
        return {"opportunity": serialize_opportunity(opportunity)}
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/campaigns")
def client360_campaigns(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    return {"items": list_campaigns(db, workspace, status=status, limit=limit)}


@router.post("/campaigns")
def client360_campaign_create(
    body: CampaignCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        campaign = create_campaign(
            db,
            workspace,
            user,
            name=body.name,
            campaign_type=body.campaign_type,
            selection_criteria=body.selection_criteria.model_dump(exclude_none=True),
            description=body.description,
            status=body.status,
            metadata=body.metadata,
        )
        db.commit()
        db.refresh(campaign)
        return {"campaign": serialize_campaign(campaign)}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/campaigns/{campaign_id}")
def client360_campaign_patch(
    campaign_id: str,
    body: CampaignPatch,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    patch = body.model_dump(exclude_unset=True)
    if isinstance(patch.get("selection_criteria"), dict):
        patch["selection_criteria"] = {
            k: v for k, v in patch["selection_criteria"].items() if v is not None
        }
    try:
        campaign = patch_campaign(db, workspace, campaign_id, patch)
        db.commit()
        db.refresh(campaign)
        return {"campaign": serialize_campaign(campaign)}
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/campaigns/{campaign_id}/drafts")
def client360_campaign_drafts(
    campaign_id: str,
    body: CampaignDraftsCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        if body.follow_up:
            result = prepare_campaign_follow_ups(
                db,
                workspace,
                user,
                campaign_id,
                language=body.language,
                include_prices=body.include_prices,
            )
        else:
            result = generate_campaign_drafts(
                db,
                workspace,
                user,
                campaign_id,
                language=body.language,
                include_prices=body.include_prices,
                limit=body.limit,
            )
        db.commit()
        return result
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/campaigns/{campaign_id}/stats")
def client360_campaign_stats(
    campaign_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    try:
        return campaign_stats(db, workspace, campaign_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
        row = patch_mapping_rule(
            db, workspace, user, mapping_id, body.model_dump(exclude_unset=True)
        )
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


@router.get("/mail-settings")
def client360_mail_settings_get(
    workspace: Workspace = Depends(get_current_workspace),
):
    return {"mail_settings": client360_mail_settings_payload(workspace)}


@router.patch("/mail-settings")
def client360_mail_settings_patch(
    body: Client360MailSettingsPatch,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        workspace = lock_workspace_for_app_entitlement_mutation(db, workspace.id)
        membership = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == user.id,
            )
            .populate_existing()
            .first()
        )
        role = (
            normalize_role_template(membership.role_template, membership.role)
            if membership
            else None
        )
        if role not in ADMIN_ROLE_TEMPLATES:
            db.rollback()
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "WORKSPACE_PERMISSION_DENIED",
                    "message": "Workspace admin access required",
                },
            )
        payload = patch_client360_mail_settings(
            db,
            workspace,
            body.model_dump(exclude_unset=True),
        )
        db.add(workspace)
        db.commit()
        db.refresh(workspace)
        return {"mail_settings": payload}
    except WorkspaceEntitlementMutationConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/mail-drafts/{draft_id}/send")
def client360_mail_draft_send(
    draft_id: str,
    body: MailDraftSend,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        draft, action = send_mail_draft(
            db,
            workspace,
            user,
            draft_id=draft_id,
            to_email=body.to_email,
            subject=body.subject,
            body=body.body,
        )
        db.commit()
        db.refresh(draft)
        if action:
            db.refresh(action)
        return {
            "mail_draft": serialize_mail_draft(draft),
            "action": serialize_action_item(action) if action else None,
            "delivery": {"status": "sent"},
        }
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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
