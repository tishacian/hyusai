"""Human promotion decisions bind the reviewed artifact and previous champion."""

import hashlib
import json
from datetime import datetime, timedelta

from app.core.config import settings
from app.models.decision import Decision
from app.services import ml_permissions
from app.services.ml_governance import lock_workspace, policy
from app.services.tabular_datasets import TabularError
from app.services.tabular_ml import champion_for, get_model, set_champion


def fingerprint(model):
    value = {
        "id": model.id,
        "version": model.version,
        "uri": model.model_uri,
        "runtime": model.runtime_json,
        "signature": model.signature_json,
        "artifact": (model.metrics_json or {}).get("artifact"),
        "status": model.status,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def public(decision, *, can_decide=False):
    return {
        "id": decision.id,
        "status": decision.status,
        "model_id": decision.target_id,
        "requested_by": (decision.rationale or {}).get("requested_by"),
        "created_at": decision.created_at.isoformat(),
        "expires_at": decision.expires_at.isoformat() if decision.expires_at else None,
        "can_decide": can_decide,
    }


def request(db, *, model, workspace, user):
    ml_permissions.require(db, "promote", workspace, user)
    lock_workspace(db, workspace.id)
    champion = champion_for(db, workspace_id=workspace.id, slug=model.slug)
    if not policy(db, workspace.id).promotion_requires_approval:
        ml_permissions.audit(
            db,
            action="promote",
            workspace_id=workspace.id,
            actor=user.id,
            model=model,
            before={"champion_id": getattr(champion, "id", None)},
            after={"champion_id": model.id},
        )
        return set_champion(db, model), None
    if model.status != "ready":
        raise TabularError(
            code="ML_MODEL_NOT_READY",
            message="Only a ready model can be promoted.",
            status_code=409,
        )
    now = datetime.utcnow()
    decision = Decision(
        workspace_id=workspace.id,
        scope="model",
        target_id=model.id,
        kind="ml_promotion",
        status="proposed",
        title=f"Promote {model.name[:180]} v{model.version}",
        rationale={
            "requested_by": user.id,
            "fingerprint": fingerprint(model),
            "champion_id": getattr(champion, "id", None),
        },
        created_at=now,
        expires_at=now + timedelta(days=settings.hitl_gate_ttl_days),
        expiry_action="reject",
    )
    db.add(decision)
    db.flush()
    ml_permissions.audit(
        db,
        action="promotion_requested",
        workspace_id=workspace.id,
        actor=user.id,
        model=model,
        after={"decision_id": decision.id},
    )
    db.commit()
    return model, public(decision)


def decide(db, *, workspace, user, decision_id, approve):
    ml_permissions.require(db, "promote", workspace, user)
    lock_workspace(db, workspace.id)
    decision = (
        db.query(Decision)
        .populate_existing()
        .filter_by(id=decision_id, workspace_id=workspace.id, kind="ml_promotion")
        .with_for_update()
        .first()
    )
    now = datetime.utcnow()
    if decision is None:
        raise TabularError(
            code="ML_PROMOTION_NOT_FOUND",
            message="The promotion request is unavailable.",
            status_code=404,
        )
    evidence = decision.rationale or {}
    if decision.status != "proposed" or (decision.expires_at and decision.expires_at <= now):
        raise TabularError(
            code="ML_PROMOTION_STALE",
            message="The promotion request is no longer open.",
            status_code=409,
        )
    if evidence.get("requested_by") == user.id:
        raise TabularError(
            code="ML_PROMOTION_SECOND_REVIEWER",
            message="Another reviewer must decide this promotion.",
            status_code=403,
        )
    model = get_model(db, model_id=decision.target_id, workspace_id=workspace.id)
    champion = champion_for(db, workspace_id=workspace.id, slug=model.slug)
    if approve and (
        fingerprint(model) != evidence.get("fingerprint")
        or getattr(champion, "id", None) != evidence.get("champion_id")
    ):
        raise TabularError(
            code="ML_PROMOTION_STALE",
            message="The reviewed model or champion changed; request a new review.",
            status_code=409,
        )
    decision.status = "applied" if approve else "rejected"
    decision.approved_by = decision.human_confirmed_by = user.id
    decision.approved_at = decision.human_confirmed_at = now
    if approve:
        decision.applied_at = now
        decision.applied_by = user.id
        decision.applied_patch = {"champion_id": model.id}
    ml_permissions.audit(
        db,
        action="promotion_approved" if approve else "promotion_rejected",
        workspace_id=workspace.id,
        actor=user.id,
        model=model,
        after={"decision_id": decision.id},
    )
    if approve:
        set_champion(db, model)
    else:
        db.commit()
    return public(decision)
