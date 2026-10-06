"""Reviewable, atomic activation of Luma model advice and the released Work pin."""

from __future__ import annotations

import copy

from app.models.skill import Skill
from app.models.system import System
from app.services import ecommerce_source_upgrade
from app.services.ecommerce_flow_sources import reviewed_source_base
from app.services.ecommerce_triage import (
    FEATURE_DATASET_SKILL,
    FEATURE_SKILL,
    SCORE_ROLE,
    validate_model,
)
from app.services.ecommerce_triage_flows import fresh_scoring, with_triage
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.skills_registry.seed import SEED_SKILLS
from app.services.systems import flow_publication


def upgrade(
    db,
    workspace,
    actor,
    *,
    plan,
    apply=False,
    expected_target_sha256=None,
    expected_scoring_target_sha256=None,
):
    model, training = validate_model(db, workspace, plan["model_id"], plan["model_version"])
    if model.system_id != plan["training_system_id"]:
        raise ValueError("CLAIM_TRIAGE_TRAINING_SYSTEM_MISMATCH")
    scorer = (
        db.query(System)
        .filter(
            System.id == plan["scoring_system_id"],
            System.workspace_id == workspace.id,
        )
        .one_or_none()
    )
    if scorer is None or (scorer.settings or {}).get("demo_role") != SCORE_ROLE:
        raise ValueError("CLAIM_TRIAGE_SYSTEM_MISMATCH")
    score_state = flow_publication.flow_state(db, system=scorer, workspace=workspace)
    if score_state["published"]["flow_sha256"] != plan["expected_scoring_flow_sha256"]:
        raise ValueError("CLAIM_TRIAGE_SCORING_FLOW_CHANGED")
    score_base = reviewed_source_base(
        score_state["published"]["flow_definition"], score_state["draft"]["flow_definition"]
    )
    score_flow = fresh_scoring(score_base, model.id, model.version)
    score_sha = canonical_flow_sha256(score_flow)
    kwargs = {
        "system_id": plan["system_id"],
        "expected_flow_sha256": plan["expected_flow_sha256"],
        "expected_release_id": plan["expected_release_id"],
        "flow_transform": lambda flow: with_triage(flow, model.id, model.version),
        "message": "Luma: native DataOps and pinned SLA-risk predictions for SAV priority; evidence and human approval govern financial decisions.",
    }
    # All membership, publication, draft and deployed release checks precede writes.
    reviewed = ecommerce_source_upgrade.upgrade(db, workspace, actor, **kwargs)
    result = {
        **reviewed,
        "scoring_flow_sha256": score_sha,
        "scoring_flow_definition": score_flow,
        "model_id": model.id,
        "model_version": model.version,
        "training_dataset_id": training.id,
    }
    if not apply:
        return result
    if (
        expected_target_sha256 != result["flow_sha256"]
        or expected_scoring_target_sha256 != score_sha
    ):
        raise ValueError("CLAIM_TRIAGE_TARGET_NOT_REVIEWED")
    model.description = (
        "Démonstration Luma : risque de résolution au-delà de 72 h, entraîné sur un historique"
        " synthétique. Variables disponibles à l'ouverture ; 25 % de test et validation croisée."
        " Conseil de priorité uniquement ; aucune autorité de remboursement ni ROI mesuré."
    )
    slugs = [FEATURE_SKILL, FEATURE_DATASET_SKILL, "ml_predict_v1"]
    for definition in SEED_SKILLS:
        if (
            definition["slug"] in slugs
            and not db.query(Skill)
            .filter(Skill.slug == definition["slug"], Skill.workspace_id.is_(None))
            .first()
        ):
            db.add(Skill(**definition, is_seeded="Y", workspace_id=None))
    db.flush()
    rows = db.query(Skill).filter(Skill.slug.in_(slugs), Skill.workspace_id.is_(None)).all()
    if len(rows) != len(slugs):
        raise ValueError("CLAIM_TRIAGE_SKILLS_MISSING")
    main = (
        db.query(System)
        .filter(System.id == plan["system_id"], System.workspace_id == workspace.id)
        .one()
    )
    main.skill_ids = list(
        dict.fromkeys(
            [
                *(main.skill_ids or []),
                *(skill.id for skill in rows if skill.slug != FEATURE_DATASET_SKILL),
            ]
        )
    )
    feature_id = next(skill.id for skill in rows if skill.slug == FEATURE_DATASET_SKILL)
    scorer.skill_ids = list(dict.fromkeys([*(scorer.skill_ids or []), feature_id]))
    # Publication locks refresh the persisted System; flush its new catalog
    # bindings before that refresh so the node's Skill remains authorized.
    db.flush()
    draft, _ = flow_publication.save_draft(
        db,
        workspace=workspace,
        system_id=scorer.id,
        flow_definition=score_flow,
        expected_revision=score_state["draft"]["revision"],
        actor=actor.email,
    )
    version, _, _ = flow_publication.publish_draft(
        db,
        workspace=workspace,
        system_id=scorer.id,
        expected_draft_revision=draft.revision,
        expected_published_version_id=score_state["published"]["version_id"],
        message="Luma: fresh bounded PostgreSQL features, native SQL preparation and pinned batch predictions.",
        breaking_change_intent="acknowledged",
        actor=actor.email,
    )
    settings = copy.deepcopy(workspace.settings or {})
    settings["ecommerce_claims"]["triage"] = {
        "model_id": model.id,
        "model_version": model.version,
        "training_system_id": model.system_id,
        "scoring_system_id": scorer.id,
        "scoring_version_id": version.id,
        "scoring_flow_sha256": score_sha,
    }
    workspace.settings = settings
    applied = ecommerce_source_upgrade.upgrade(
        db,
        workspace,
        actor,
        **kwargs,
        apply=True,
        expected_target_sha256=expected_target_sha256,
    )
    return {**result, **applied, "scoring_version_id": version.id}
