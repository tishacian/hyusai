"""A reproducible data → Python/Polars → LLM → check exercise for the Showcase.

Imported by the existing seed, which owns locking and version reconciliation.
This module creates no rows and performs no external calls.
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
                "id": "sink",
                "kind": "sink",
                "label": "Inspect result and evidence",
                "position": {"x": 1120, "y": 160},
                "config": {
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
                    }
                },
            },
        ],
        "edges": [
            {"from": a, "to": b}
            for a, b in zip(
                ["src", "calculate", "explain", "check"], ["calculate", "explain", "check", "sink"]
            )
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
                                "Expected: 120 planned minutes, 155 actual, 35 net overrun, 3 late orders; largest overrun: NF-04, +25 minutes. A passed numerical check does not validate the model’s prose or prove savings.",
                                "Référence : 120 minutes prévues, 155 réalisées, 35 de dépassement net, 3 ordres en retard ; dépassement maximal : NF-04, +25 minutes. Un contrôle numérique réussi ne valide ni la prose du modèle ni des économies.",
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
        bindings.get_binding(db, workspace_id=workspace.id, binding_key=key)
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
