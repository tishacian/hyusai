"""Review and activate one composed Luma System and both released Work actions."""

from __future__ import annotations

import copy

from app.models.experience import Experience
from app.models.skill import Skill
from app.models.system import System
from app.models.system_binding import SystemBinding
from app.services import ecommerce_source_upgrade
from app.services.audit_logger import emit_audit_event
from app.services.ecommerce_composition import (
    CONTEXT_SKILL,
    DATASET_SKILL,
    MODE,
    QUEUE_INGRESS,
    compose,
)
from app.services.ecommerce_flow_sources import reviewed_source_base
from app.services.ecommerce_triage import SCORE_ROLE, get_prediction_contract, validate_model
from app.services.experience import bindings, lifecycle
from app.services.flow_contracts import canonical_sha256
from app.services.skills_registry.seed import SEED_SKILLS
from app.services.systems import flow_publication

QUEUE_BINDING = "showcase.claims.refresh_queue"


def work_pages(pages):
    result = copy.deepcopy(pages)
    page = next(p for p in result["pages"] if p["id"] == "dossier")
    if any(c["id"] == "queue_refresh" for c in page["components"]):
        raise ValueError("CLAIMS_COMPOSITION_WORK_ALREADY_INSTALLED")
    page["components"].insert(
        1,
        {
            "id": "queue_refresh",
            "type": "action_button",
            "props": {
                "bindingKey": QUEUE_BINDING,
                "input": {},
                "label": {"$i18n": "claims_queue_refresh", "fallback": "Recalculer la file"},
            },
        },
    )
    result.setdefault("i18n", {}).setdefault("fr", {})["claims_queue_refresh"] = (
        "Recalculer la file"
    )
    result["i18n"].setdefault("en", {})["claims_queue_refresh"] = "Rescore the queue"
    return result


def upgrade(db, workspace, actor, *, plan, apply=False, expected_composition_sha256=None):
    model, training = validate_model(db, workspace, plan["model_id"], plan["model_version"])
    training_history_id = plan["training_system_id"]
    # A Model Center fit has no training System. The reviewed plan names the
    # previous fitted model whose historical System is being retired; this
    # does not pretend that the new fit ran in that old System.
    history_model = None
    if model.system_id is None and plan.get("training_history_model_id"):
        history_model, _ = validate_model(
            db, workspace, plan["training_history_model_id"], plan["training_history_model_version"]
        )
    if model.system_id != training_history_id and (
        model.system_id is not None
        or history_model is None
        or history_model.system_id != training_history_id
    ):
        raise ValueError("CLAIM_TRIAGE_TRAINING_SYSTEM_MISMATCH")
    authored = plan.get("configuration") or {}
    if not isinstance(authored, dict) or set(authored) - {"flow_definition", "pages", "bindings"}:
        raise ValueError("CLAIMS_COMPOSITION_CONFIGURATION_INVALID")
    extra_bindings = copy.deepcopy(authored.get("bindings") or [])
    seen_bindings = {QUEUE_BINDING, "showcase.claims.investigate"}
    for item in extra_bindings:
        if (
            not isinstance(item, dict)
            or set(item) != {"binding_key", "ingress_id"}
            or not isinstance(item["binding_key"], str)
            or not item["binding_key"]
            or not isinstance(item["ingress_id"], str)
            or not item["ingress_id"]
            or item["binding_key"] in seen_bindings
        ):
            raise ValueError("CLAIMS_COMPOSITION_CONFIGURATION_INVALID")
        seen_bindings.add(item["binding_key"])

    def configured_flow(flow):
        if "flow_definition" in authored:
            return copy.deepcopy(authored["flow_definition"])
        return compose(flow, model.id, model.version, model_slug=model.slug)

    kwargs = {
        "system_id": plan["system_id"],
        "expected_flow_sha256": plan["expected_flow_sha256"],
        "expected_release_id": plan["expected_release_id"],
        "flow_transform": configured_flow,
        "message": "Luma: one hybrid SAV System, shared PostgreSQL preparation and model scoring, scoped document inquiry and human decisions.",
    }
    reviewed = ecommerce_source_upgrade.upgrade(db, workspace, actor, **kwargs)
    experience = (
        db.query(Experience)
        .filter(Experience.workspace_id == workspace.id, Experience.slug == "reclamations")
        .one()
    )
    _, draft, _ = lifecycle.get_experience(
        db, workspace_id=workspace.id, experience_id=experience.id
    )
    pages = copy.deepcopy(authored["pages"]) if "pages" in authored else work_pages(draft.pages)
    keys = list(
        dict.fromkeys(
            [
                *(draft.binding_keys or []),
                QUEUE_BINDING,
                *(item["binding_key"] for item in extra_bindings),
            ]
        )
    )
    if (
        db.query(SystemBinding)
        .filter(
            SystemBinding.workspace_id == workspace.id,
            SystemBinding.binding_key.in_(
                [QUEUE_BINDING, *(item["binding_key"] for item in extra_bindings)]
            ),
        )
        .first()
    ):
        raise ValueError("CLAIMS_COMPOSITION_QUEUE_BINDING_EXISTS")
    legacy = []
    retirement = []
    expected_roles = {
        training_history_id: "luma-sla-training-v1",
        plan["scoring_system_id"]: SCORE_ROLE,
    }
    if (
        set(expected_roles) != {item["system_id"] for item in plan["retire"]}
        or plan["system_id"] in expected_roles
    ):
        raise ValueError("CLAIMS_COMPOSITION_RETIREMENT_SCOPE_INVALID")
    for item in plan["retire"]:
        system = (
            db.query(System)
            .filter(System.id == item["system_id"], System.workspace_id == workspace.id)
            .with_for_update(of=System)
            .one_or_none()
        )
        if system is None or (system.settings or {}).get("demo_role") != expected_roles[system.id]:
            raise ValueError("CLAIMS_COMPOSITION_RETIREMENT_SCOPE_INVALID")
        state = flow_publication.flow_state(db, system=system, workspace=workspace)
        if (
            state["published"]["flow_sha256"] != item["expected_flow_sha256"]
            or state["draft"]["flow_sha256"] != item["expected_draft_sha256"]
        ):
            raise ValueError("CLAIMS_COMPOSITION_LEGACY_FLOW_CHANGED")
        reviewed_source_base(
            state["published"]["flow_definition"], state["draft"]["flow_definition"]
        )
        if (
            db.query(SystemBinding)
            .filter(
                SystemBinding.workspace_id == workspace.id, SystemBinding.system_id == system.id
            )
            .first()
        ):
            raise ValueError("CLAIMS_COMPOSITION_LEGACY_SYSTEM_BOUND")
        legacy.append(system)
        retirement.append(
            {
                "system_id": system.id,
                "name": system.name,
                "previous_status": system.status,
                "status": "retired",
                **item,
            }
        )
    proof = {
        "flow_sha256": reviewed["flow_sha256"],
        "pages": pages,
        "binding_keys": keys,
        "system_name": "Luma — Résolution SAV hybride",
        "retire": retirement,
        "model_id": model.id,
        "model_version": model.version,
        "training_history_model_id": history_model.id if history_model else model.id,
        "queue_binding": {
            "binding_key": QUEUE_BINDING,
            "system_id": plan["system_id"],
            "ingress_id": QUEUE_INGRESS,
            "confirmation_policy": "confirm",
        },
        "additional_bindings": extra_bindings,
    }
    result = {
        **reviewed,
        **proof,
        "composition_sha256": canonical_sha256(proof),
        "training_dataset_id": training.id,
    }
    if not apply:
        return result
    if expected_composition_sha256 != result["composition_sha256"]:
        raise ValueError("CLAIMS_COMPOSITION_TARGET_NOT_REVIEWED")
    # The source upgrade only publishes/configures an app when the Flow changes.
    # Refuse an app-only/no-op plan before touching Skills, names or history;
    # otherwise the CLI could commit those partial changes with applied=False.
    if not result["changed"]:
        raise ValueError("CLAIMS_COMPOSITION_FLOW_UNCHANGED")
    slugs = {DATASET_SKILL, CONTEXT_SKILL, "sql_transform_v1", "ml_batch_score_v1"}
    slugs.update(
        node["config"]["skill_slug"]
        for node in reviewed["flow_definition"].get("nodes", [])
        if isinstance(node.get("config"), dict) and node["config"].get("skill_slug")
    )
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
        raise ValueError("CLAIMS_COMPOSITION_SKILLS_MISSING")
    main = (
        db.query(System)
        .filter(System.id == plan["system_id"], System.workspace_id == workspace.id)
        .one()
    )
    main.skill_ids = list(dict.fromkeys([*(main.skill_ids or []), *(s.id for s in rows)]))
    main.name = proof["system_name"]
    db.flush()

    def configure(db, workspace, experience, current_draft, version):
        bindings.create_binding(
            db,
            workspace=workspace,
            actor=actor.email,
            binding_key=QUEUE_BINDING,
            system_id=main.id,
            published_flow_version_id=version.id,
            ingress_id=QUEUE_INGRESS,
            confirmation_policy="confirm",
            on_unavailable="unavailable",
        )
        for item in extra_bindings:
            bindings.create_binding(
                db,
                workspace=workspace,
                actor=actor.email,
                binding_key=item["binding_key"],
                system_id=main.id,
                published_flow_version_id=version.id,
                ingress_id=item["ingress_id"],
                confirmation_policy="confirm",
                on_unavailable="unavailable",
            )
        settings = copy.deepcopy(workspace.settings or {})
        settings["ecommerce_claims"]["triage"] = {
            "composition": MODE,
            "prediction_contract": get_prediction_contract(
                {"model_id": model.id, "model_version": model.version}
            ),
            "model_id": model.id,
            "model_version": model.version,
            "training_system_id": model.system_id,
            "scoring_system_id": main.id,
            "scoring_version_id": version.id,
            "scoring_flow_sha256": reviewed["flow_sha256"],
        }
        workspace.settings = settings
        for system in legacy:
            system.status = "retired"
            system.settings = {
                **(system.settings or {}),
                "composition_parent_system_id": main.id,
                "composition_role": "training_history"
                if system.id == training_history_id
                else "bootstrap_history",
            }
        model.description = (
            f"Luma : modèle de démonstration entraîné sur {training.row_count} dossiers synthétiques."
            " Conseil de priorité dans le Flow SAV composé ; aucune autorité financière ni ROI mesuré."
        )
        emit_audit_event(
            db=db,
            workspace_id=workspace.id,
            event_type="ecommerce.composition.activated",
            actor=actor.email,
            agent_id=main.id,
            details={
                "composition_sha256": result["composition_sha256"],
                "retire": retirement,
                "model_id": model.id,
                "model_version": model.version,
            },
        )
        db.flush()
        return lifecycle.save_draft(
            db,
            workspace_id=workspace.id,
            experience_id=experience.id,
            pages=pages,
            binding_keys=keys,
            expected_revision=current_draft.revision,
            actor=actor.email,
        )

    applied = ecommerce_source_upgrade.upgrade(
        db,
        workspace,
        actor,
        **kwargs,
        apply=True,
        expected_target_sha256=reviewed["flow_sha256"],
        configure_experience=configure,
    )
    return {**result, **applied}
