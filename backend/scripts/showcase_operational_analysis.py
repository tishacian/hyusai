"""A reproducible data → Python/Polars → LLM → check → review Showcase exercise.

Imported by the existing seed. The scoped installer can also install this one
application without reseeding the other Showcase systems or their activity.
Existing installations adopt changes through Flow draft/publish, binding
retarget, then Experience readiness/release/deploy; rerunning is not an upgrade.
"""

ROWS = [
    {"order": "NF-01", "planned_minutes": 30, "actual_minutes": 40},
    {"order": "NF-02", "planned_minutes": 40, "actual_minutes": 35},
    {"order": "NF-03", "planned_minutes": 20, "actual_minutes": 25},
    {"order": "NF-04", "planned_minutes": 30, "actual_minutes": 55},
]
EXPECTED = {
    "orders": 4,
    "planned_minutes": 120,
    "actual_minutes": 155,
    "overrun_minutes": 35,
    "late_orders": 3,
    "largest_overrun_order": "NF-04",
    "largest_overrun_minutes": 25,
}
# Pinned for reproducible managed environments, using the repository's recipe plane.
REQUIREMENTS = "polars==1.31.0"
CALCULATE_CODE = (
    """import json
import polars as pl

DEFAULT_ROWS = """
    + repr(ROWS)
    + """

def main(inputs):
    rows = inputs.get("rows", DEFAULT_ROWS)
    frame = pl.DataFrame(rows)
    required = {"order", "planned_minutes", "actual_minutes"}
    if not rows or not required.issubset(frame.columns):
        raise ValueError("Supply non-empty rows with order, planned_minutes and actual_minutes")
    if frame.select(pl.col("planned_minutes", "actual_minutes").null_count()).sum_horizontal().item() != 0:
        raise ValueError("Durations cannot be missing")
    if frame.filter((pl.col("planned_minutes") < 0) | (pl.col("actual_minutes") < 0)).height:
        raise ValueError("Durations cannot be negative")
    planned = frame["planned_minutes"].sum()
    actual = frame["actual_minutes"].sum()
    largest = frame.with_columns((pl.col("actual_minutes") - pl.col("planned_minutes")).alias("overrun")).sort(["overrun", "order"], descending=[True, False]).row(0, named=True)
    stats = {"orders": frame.height, "planned_minutes": planned, "actual_minutes": actual,
             "overrun_minutes": actual - planned,
             "late_orders": frame.filter(pl.col("actual_minutes") > pl.col("planned_minutes")).height,
             "largest_overrun_order": largest["order"], "largest_overrun_minutes": largest["overrun"]}
    return {"stats": stats, "context": ["Synthetic NorthForge exercise; no customer data or verified savings. " + json.dumps(stats)],
            "query": "Explain the operational delay using only the supplied numbers. Do not claim savings. Suggest one next investigation.",
            "showcase_seed": True}
"""
)
CHECK_CODE = (
    """def main(inputs):
    stats = inputs.get("stats") or {}
    answer = inputs.get("answer")
    if stats != """
    + repr(EXPECTED)
    + """:
        raise ValueError("The fixed NorthForge fixture no longer matches the expected result; inspect the Python inputs and version before changing the reference")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("The model returned no explanation")
    return {"stats": stats, "answer": answer, "numerical_reference_passed": True,
            "human_validated": False, "economic_impact": None, "showcase_seed": True}
"""
)


def flow_operational_analysis():
    """Exact arithmetic is checked; the check does not certify the LLM's prose."""
    stats_schema = {
        "type": "object",
        "properties": {key: {"type": "string" if isinstance(value, str) else "number"} for key, value in EXPECTED.items()},
        "required": list(EXPECTED),
    }
    return {
        "schema_version": 3,
        "nodes": [
            {
                "id": "src",
                "kind": "source",
                "label": "Synthetic work orders",
                "position": {"x": 20, "y": 160},
                "config": {
                    "input_schema": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    }
                },
            },
            {
                "id": "calculate",
                "kind": "task",
                "label": "Calculate with Python / Polars",
                "position": {"x": 280, "y": 160},
                "config": {
                    "skill_slug": "python_recipe_v1",
                    "params": {
                        "code": CALCULATE_CODE,
                        "requirements_text": REQUIREMENTS,
                        "timeout_s": 30,
                    },
                    "output_schema": {
                        "type": "object",
                        "properties": {
                            "stats": stats_schema,
                            "context": {"type": "array", "items": {"type": "string"}},
                            "query": {"type": "string"},
                        },
                        "required": ["stats", "context", "query"],
                    },
                },
            },
            {
                "id": "explain",
                "kind": "task",
                "label": "Explain the computed evidence",
                "position": {"x": 560, "y": 160},
                "config": {
                    "skill_slug": "llm_rag_answer_v1",
                    "inputs_map": {
                        "query": {"node_id": "calculate", "path": ["query"]},
                        "context": {"node_id": "calculate", "path": ["context"]},
                    },
                },
            },
            {
                "id": "check",
                "kind": "task",
                "label": "Check against the numerical reference",
                "position": {"x": 840, "y": 160},
                "config": {
                    "skill_slug": "python_recipe_v1",
                    "params": {"code": CHECK_CODE, "timeout_s": 30},
                    "inputs_map": {
                        "stats": {"node_id": "calculate", "path": ["stats"]},
                        "answer": {"node_id": "explain", "path": ["answer"]},
                    },
                    "output_schema": {
                        "type": "object",
                        "properties": {
                            "stats": stats_schema,
                            "answer": {"type": "string"},
                            "numerical_reference_passed": {"type": "boolean"},
                            "human_validated": {"type": "boolean"},
                            "showcase_seed": {"type": "boolean"},
                        },
                        "required": [
                            "stats",
                            "answer",
                            "numerical_reference_passed",
                            "human_validated",
                            "showcase_seed",
                        ],
                    },
                },
            },
            {
                "id": "allow_review",
                "kind": "decision",
                "label": "Require a successful numerical check",
                "position": {"x": 1120, "y": 160},
                "config": {
                    "inputs_map": {
                        "check_result": {"node_id": "check", "path": []},
                        "numerical_reference_passed": {"node_id": "check", "path": ["numerical_reference_passed"], "required": False},
                    },
                    # Compatibility DAG failures carry their inputs forward.
                    # A failed recipe must never become a reviewable result.
                    "branches": [{"label": "passed", "condition": "'_error' not in check_result and numerical_reference_passed == True"}],
                },
            },
            {
                "id": "review",
                "kind": "hitl",
                "label": "Review the explanation against the evidence",
                "position": {"x": 1400, "y": 160},
                "config": {
                    "prompt": "Review the explanation against the checked NorthForge figures. Accept only if its claims and proposed investigation are supported. No customer data or verified savings are demonstrated.",
                    "expires_in_days": 1,
                    "expiry_action": "reject",
                    "inputs_map": {
                        key: {"node_id": "check", "path": [key]}
                        for key in ("stats", "answer", "numerical_reference_passed", "human_validated", "economic_impact", "showcase_seed")
                    },
                },
            },
            {
                "id": "sink",
                "kind": "sink",
                "label": "Inspect result and evidence",
                "position": {"x": 1680, "y": 160},
                "config": {
                    "inputs_map": {
                        **{
                            key: {"node_id": "check", "path": [key]}
                            for key in ("stats", "answer", "numerical_reference_passed", "economic_impact", "showcase_seed")
                        },
                        "human_validated": {"node_id": "review", "path": ["approved"]},
                        "review_decision_id": {"node_id": "review", "path": ["decision_id"]},
                        "review_status": {"node_id": "review", "path": ["decision_status"]},
                        "reviewed_by": {"node_id": "review", "path": ["decided_by"]},
                    },
                    "output_schema": {
                        "type": "object",
                        "properties": {
                            "stats": stats_schema,
                            "answer": {"type": "string"},
                            "numerical_reference_passed": {"type": "boolean"},
                            "human_validated": {"type": "boolean"},
                            "showcase_seed": {"type": "boolean"},
                            "economic_impact": {"type": "null"},
                            "review_decision_id": {"type": "string"},
                            "review_status": {"type": "string"},
                            "reviewed_by": {"type": ["string", "null"]},
                        },
                        "required": [
                            "stats",
                            "answer",
                            "numerical_reference_passed",
                            "human_validated",
                            "showcase_seed",
                            "economic_impact",
                            "review_decision_id",
                            "review_status",
                            "reviewed_by",
                        ],
                    }
                },
            },
        ],
        "edges": [
            {"from": a, "to": b}
            for a, b in zip(
                ["src", "calculate", "explain", "check", "review"], ["calculate", "explain", "check", "allow_review", "sink"]
            )
        ] + [
            {"from": "allow_review", "to": "review", "kind": "branch", "branch_label": "passed"},
            {"from": "check", "to": "sink", "kind": "data"},
        ],
    }


def calculate(inputs):
    namespace = {}
    exec(compile(CALCULATE_CODE, "<showcase-operational-analysis>", "exec"), namespace)
    return namespace["main"](inputs)


def check(inputs):
    namespace = {}
    exec(compile(CHECK_CODE, "<showcase-operational-check>", "exec"), namespace)
    return namespace["main"](inputs)


def experience_document():
    translations = {"en": {}, "fr": {}}

    def copy(en, fr):
        key = "operational." + str(len(translations["en"]))
        translations["en"][key], translations["fr"][key] = en, fr
        return {"$i18n": key, "fallback": en}

    def binding(selector):
        return {"source": "run-output", "componentId": "analyze", "selector": selector}

    return {
        "i18n": translations,
        "pages": [
            {
                "id": "analysis",
                "title": copy("Operational Analysis", "Analyse opérationnelle"),
                "components": [
                    {
                        "type": "header",
                        "id": "heading",
                        "props": {
                            "title": copy(
                                "Explain an operational delay", "Expliquer un retard opérationnel"
                            ),
                            "subtitle": copy(
                                "Synthetic NorthForge exercise: 4 orders, exact calculations, one explanation. No customer data or savings.",
                                "Exercice NorthForge synthétique : 4 ordres, calculs exacts, une explication. Aucune donnée client ni économie.",
                            ),
                        },
                    },
                    {
                        "type": "action_button",
                        "id": "analyze",
                        "props": {
                            "label": copy("Analyze the example", "Analyser l’exemple"),
                            "bindingKey": "showcase.operational.analyze",
                            "input": {},
                            "afterSuccess": "stay",
                        },
                    },
                    {"type": "runtime_status", "id": "status", "props": {}},
                    {
                        "type": "kpi",
                        "id": "orders",
                        "props": {
                            "label": copy("Orders", "Ordres"),
                            "dataBinding": binding("stats.orders"),
                        },
                    },
                    {
                        "type": "kpi",
                        "id": "overrun",
                        "props": {
                            "label": copy("Net overrun (minutes)", "Dépassement net (minutes)"),
                            "dataBinding": binding("stats.overrun_minutes"),
                        },
                    },
                    {
                        "type": "kpi",
                        "id": "late",
                        "props": {
                            "label": copy("Late orders", "Ordres en retard"),
                            "dataBinding": binding("stats.late_orders"),
                        },
                    },
                    {
                        "type": "result",
                        "id": "explanation",
                        "props": {"dataBinding": binding("answer")},
                    },
                    {
                        "type": "callout",
                        "id": "meaning",
                        "props": {
                            "body": copy(
                                "Expected: 120 planned minutes, 155 actual, 35 net overrun, 3 late orders; largest overrun: NF-04, +25 minutes. Review the explanation and its evidence in the validation queue before accepting or rejecting it. A passed numerical check does not validate the model’s prose or prove savings.",
                                "Référence : 120 minutes prévues, 155 réalisées, 35 de dépassement net, 3 ordres en retard ; dépassement maximal : NF-04, +25 minutes. Examinez l’explication et ses preuves dans la file de validation avant de l’accepter ou de la refuser. Un contrôle numérique réussi ne valide ni la prose du modèle ni des économies.",
                            )
                        },
                    },
                ],
            }
        ],
    }


def ensure_experience(db, workspace, system):
    """Initial Showcase installation only; preserve all existing releases and edits."""
    from app.models.experience import Experience
    from app.services.experience import bindings, lifecycle

    if (
        workspace.slug != "agentium-showcase"
        or (workspace.settings or {}).get("features", {}).get("adoption_experience_v1") is not True
    ):
        return None
    existing = (
        db.query(Experience)
        .filter_by(workspace_id=workspace.id, slug="operational-analysis")
        .first()
    )
    if existing:
        return existing
    if not system.published_flow_version_id:
        raise ValueError(
            "Publish the Operational Analysis System before installing its Showcase application"
        )
    actor = "showcase-seed"
    key = "showcase.operational.analyze"
    try:
        bound = bindings.get_binding(db, workspace_id=workspace.id, binding_key=key)
        if bound.system_id != system.id or bound.published_flow_version_id != system.published_flow_version_id:
            raise ValueError("The existing Operational Analysis binding targets a different System or version")
    except bindings.BindingError as exc:
        if getattr(exc, "status_code", None) not in (None, 404):
            raise
        bindings.create_binding(
            db,
            workspace=workspace,
            actor=actor,
            binding_key=key,
            system_id=system.id,
            published_flow_version_id=system.published_flow_version_id,
            ingress_id="src",
            confirmation_policy="direct-safe",
            on_unavailable="unavailable",
        )
    experience, draft = lifecycle.create_experience(
        db,
        workspace=workspace,
        actor=actor,
        name="Operational Analysis",
        slug="operational-analysis",
        pattern="dashboard",
        languages=["en", "fr"],
        theme={},
        access_policy={
            "role_templates": [
                "workspace_viewer",
                "workspace_contributor",
                "workspace_reviewer",
                "workspace_admin",
                "workspace_owner",
            ]
        },
        description="Synthetic NorthForge onboarding exercise; no customer data or verified savings.",
    )
    document = experience_document()
    lifecycle.save_draft(
        db,
        workspace_id=workspace.id,
        experience_id=experience.id,
        pages=document,
        binding_keys=lifecycle.referenced_binding_keys(document),
        expected_revision=int(draft.revision),
        actor=actor,
    )
    db.flush()
    ready = lifecycle.ready_check(db, workspace=workspace, experience_id=experience.id)
    if ready["blockers"]:
        raise ValueError(f"Operational Analysis is not ready for release: {ready['blockers']}")
    _, draft, _ = lifecycle.get_experience(
        db, workspace_id=workspace.id, experience_id=experience.id
    )
    release = lifecycle.create_release(
        db,
        workspace=workspace,
        experience_id=experience.id,
        notes="Initial synthetic adoption exercise",
        expected_draft_revision=int(draft.revision),
        expected_content_sha256=draft.content_sha256,
        expected_experience_updated_at=experience.updated_at,
        expected_bindings_sha256=ready["bindings_sha256"],
        actor=actor,
    )
    lifecycle.deploy(
        db,
        workspace=workspace,
        experience_id=experience.id,
        channel="live",
        release_id=release.id,
        expected_current_release_id=None,
        expected_deployment_updated_at=None,
        audience=None,
        actor=actor,
    )
    db.commit()
    return experience


def install(db, *, apply=False):
    """Install only the fixed example; never refresh an existing published Flow.

    This is an operator seed command, not an application endpoint. It requires
    the structural Showcase marker, existing feature choices and catalogue.
    The workspace lock serializes concurrent installer invocations.
    """
    from app.models.workspace import Workspace
    from app.models.system import System
    from app.models.skill import Skill
    from app.services.seed_catalog_safety import require_showcase_workspace_for_seed
    from app.services.systems.flow_publication import initialize_new_system_publication_if_enabled, require_flow_publication

    workspace = db.query(Workspace).filter_by(slug="agentium-showcase").with_for_update(of=Workspace).one()
    require_showcase_workspace_for_seed(workspace)
    features = (workspace.settings or {}).get("features", {})
    if not all(features.get(key) is True for key in ("experience_v1", "adoption_experience_v1")):
        raise ValueError("Showcase Experience and adoption must already be enabled")
    require_flow_publication(workspace)
    key = "showcase.operational-analysis.v1"
    systems = db.query(System).filter_by(workspace_id=workspace.id).all()
    existing = [s for s in systems if s.blueprint_key == key or s.name == "Operational Analysis"]
    if len(existing) > 1:
        raise ValueError("Ambiguous Operational Analysis Systems; reconcile manually")
    system = existing[0] if existing else None
    if system and (system.settings or {}).get("showcase_seed") is not True:
        raise ValueError("An authored System already uses this name; installation refused")
    if system and not system.published_flow_version_id:
        raise ValueError("Existing System is not published; review and publish it explicitly")
    if not apply:
        return {"workspace_id": workspace.id, "system_id": system.id if system else None,
                "action": "inspect_existing" if system else "install", "applied": False}
    if system is None:
        slugs = {"python_recipe_v1", "llm_rag_answer_v1"}
        skills = db.query(Skill).filter(Skill.slug.in_(slugs), Skill.workspace_id.is_(None)).all()
        if {s.slug for s in skills} != slugs:
            raise ValueError("Required global Skills are absent; no catalogue rows were changed")
        system = System(
            workspace_id=workspace.id, blueprint_key=key, name="Operational Analysis",
            objective="Explain the fixed NorthForge work-order delay using exact calculations and their execution evidence.",
            status="active", coordination_pattern="graph", created_by="showcase-seed",
            skill_ids=[s.id for s in skills], flow_definition=flow_operational_analysis(),
            settings={"showcase_seed": True},
        )
        db.add(system)
        initialize_new_system_publication_if_enabled(db, system=system, workspace=workspace, actor="showcase-seed")
    experience = ensure_experience(db, workspace, system)
    db.commit()
    return {"workspace_id": workspace.id, "system_id": system.id,
            "published_flow_version_id": system.published_flow_version_id,
            "experience_id": experience.id, "path": "/work/operational-analysis", "applied": True}


if __name__ == "__main__":
    import argparse
    import json
    import app.models  # Register canonical ORM relationships before opening a session.
    from app.db.base import SessionLocal

    parser = argparse.ArgumentParser(description="Install only the synthetic Operational Analysis Showcase application")
    parser.add_argument("--apply", action="store_true", help="Explicitly install and publish the example; default is read-only")
    args = parser.parse_args()
    with SessionLocal() as db:
        print(json.dumps(install(db, apply=args.apply), sort_keys=True))
