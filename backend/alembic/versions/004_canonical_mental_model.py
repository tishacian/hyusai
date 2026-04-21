"""Canonical mental-model layer: capabilities, skills, contexts, policies,
systems, runs, skill_invocations, impacts, decisions.

Revision ID: 004_canon_mental_model
Revises: 003_ws_soft_delete
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa


revision = "004_canon_mental_model"
down_revision = "003_ws_soft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- capabilities ---------------------------------------------------
    op.create_table(
        "capabilities",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tier", sa.String(length=20), nullable=True, server_default="universal"),
        sa.Column("industry", sa.String(length=80), nullable=True),
        sa.Column("input_unit", sa.String(length=60), nullable=True, server_default="request"),
        sa.Column("output_unit", sa.String(length=60), nullable=True, server_default="answer"),
        sa.Column("skill_ids", sa.JSON(), nullable=True),
        sa.Column("pricing", sa.JSON(), nullable=True),
        sa.Column("value_per_outcome", sa.Float(), nullable=True),
        sa.Column("confidence_threshold", sa.Float(), nullable=True),
        sa.Column("sla", sa.JSON(), nullable=True),
        sa.Column("roi_model", sa.JSON(), nullable=True),
        sa.Column("is_seeded", sa.String(length=1), nullable=True, server_default="N"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_capabilities_slug", "capabilities", ["slug"], unique=True)
    op.create_index("ix_capabilities_workspace_id", "capabilities", ["workspace_id"])

    # ---- skills ---------------------------------------------------------
    op.create_table(
        "skills",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=True, server_default="1"),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("type", sa.String(length=60), nullable=True, server_default="generic"),
        sa.Column("input_schema", sa.JSON(), nullable=True),
        sa.Column("output_schema", sa.JSON(), nullable=True),
        sa.Column("execution", sa.JSON(), nullable=True),
        sa.Column("pricing", sa.JSON(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("certification_level", sa.String(length=20), nullable=True, server_default="basic"),
        sa.Column("is_seeded", sa.String(length=1), nullable=True, server_default="N"),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_skills_slug", "skills", ["slug"], unique=True)
    op.create_index("ix_skills_workspace_id", "skills", ["workspace_id"])

    # ---- contexts -------------------------------------------------------
    op.create_table(
        "contexts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("system_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False, server_default="default"),
        sa.Column("version", sa.Integer(), nullable=True, server_default="1"),
        sa.Column("data_refs", sa.JSON(), nullable=True),
        sa.Column("memory_refs", sa.JSON(), nullable=True),
        sa.Column("history_refs", sa.JSON(), nullable=True),
        sa.Column("environment_state", sa.JSON(), nullable=True),
        sa.Column("business_constraints", sa.JSON(), nullable=True),
        sa.Column("permissions", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_contexts_workspace_id", "contexts", ["workspace_id"])
    op.create_index("ix_contexts_system_id", "contexts", ["system_id"])

    # ---- control_policies ----------------------------------------------
    op.create_table(
        "control_policies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False, server_default="default"),
        sa.Column("scope", sa.String(length=20), nullable=True, server_default="system"),
        sa.Column("target_id", sa.String(length=36), nullable=True),
        sa.Column("max_cost_per_decision", sa.Float(), nullable=True),
        sa.Column("max_latency_ms", sa.Float(), nullable=True),
        sa.Column("mandatory_hitl_if_confidence_below", sa.Float(), nullable=True),
        sa.Column("allowed_models", sa.JSON(), nullable=True),
        sa.Column("allowed_skills", sa.JSON(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_control_policies_workspace_id", "control_policies", ["workspace_id"])
    op.create_index("ix_control_policies_target_id", "control_policies", ["target_id"])

    # ---- adaptive_policies ---------------------------------------------
    op.create_table(
        "adaptive_policies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False, server_default="default"),
        sa.Column("enabled", sa.Boolean(), nullable=True, server_default=sa.text("0")),
        sa.Column("adaptation_level", sa.String(length=20), nullable=True, server_default="moderate"),
        sa.Column("triggers", sa.JSON(), nullable=True),
        sa.Column("allowed_actions", sa.JSON(), nullable=True),
        sa.Column("constraints", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_adaptive_policies_workspace_id", "adaptive_policies", ["workspace_id"])

    # ---- systems --------------------------------------------------------
    op.create_table(
        "systems",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False, server_default=""),
        sa.Column("capability_id", sa.String(length=36), sa.ForeignKey("capabilities.id"), nullable=True),
        sa.Column("skill_ids", sa.JSON(), nullable=True),
        sa.Column("flow_definition", sa.JSON(), nullable=True),
        sa.Column("execution_mode", sa.String(length=40), nullable=True, server_default="real_time"),
        sa.Column("coordination_pattern", sa.String(length=40), nullable=True, server_default="single_agent"),
        sa.Column("control_policy_id", sa.String(length=36), sa.ForeignKey("control_policies.id"), nullable=True),
        sa.Column("adaptive_policy_id", sa.String(length=36), sa.ForeignKey("adaptive_policies.id"), nullable=True),
        sa.Column("context_id", sa.String(length=36), sa.ForeignKey("contexts.id"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True, server_default="draft"),
        sa.Column("created_by", sa.String(length=255), nullable=True, server_default="demo-user"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_systems_workspace_id", "systems", ["workspace_id"])
    op.create_index("ix_systems_capability_id", "systems", ["capability_id"])
    op.create_index("ix_systems_status", "systems", ["status"])

    # ---- runs -----------------------------------------------------------
    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("system_id", sa.String(length=36), sa.ForeignKey("systems.id"), nullable=False),
        sa.Column("capability_id", sa.String(length=36), nullable=True),
        sa.Column("input_ref", sa.JSON(), nullable=True),
        sa.Column("output_ref", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True, server_default="pending"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("decision", sa.String(length=40), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("value_estimated", sa.Float(), nullable=True),
        sa.Column("cost_internal", sa.Float(), nullable=True),
        sa.Column("revenue_allocated", sa.Float(), nullable=True),
        sa.Column("efficiency", sa.Float(), nullable=True),
        sa.Column("checkpoints", sa.JSON(), nullable=True),
        sa.Column("retries", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("trigger", sa.String(length=40), nullable=True, server_default="manual"),
    )
    op.create_index("ix_runs_workspace_id", "runs", ["workspace_id"])
    op.create_index("ix_runs_system_id", "runs", ["system_id"])
    op.create_index("ix_runs_capability_id", "runs", ["capability_id"])
    op.create_index("ix_runs_status", "runs", ["status"])

    # ---- skill_invocations ---------------------------------------------
    op.create_table(
        "skill_invocations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("skill_id", sa.String(length=36), nullable=True),
        sa.Column("skill_slug", sa.String(length=160), nullable=True),
        sa.Column("input_ref", sa.JSON(), nullable=True),
        sa.Column("output_ref", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True, server_default="pending"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("cost", sa.Float(), nullable=True, server_default="0"),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("trace", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_skill_invocations_run_id", "skill_invocations", ["run_id"])
    op.create_index("ix_skill_invocations_skill_slug", "skill_invocations", ["skill_slug"])

    # ---- impacts --------------------------------------------------------
    op.create_table(
        "impacts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=True, server_default="capability"),
        sa.Column("target_id", sa.String(length=36), nullable=True),
        sa.Column("period", sa.String(length=20), nullable=True, server_default="qtd"),
        sa.Column("runs_count", sa.Float(), nullable=True, server_default="0"),
        sa.Column("total_cost", sa.Float(), nullable=True, server_default="0"),
        sa.Column("total_revenue", sa.Float(), nullable=True, server_default="0"),
        sa.Column("estimated_value", sa.Float(), nullable=True, server_default="0"),
        sa.Column("roi", sa.Float(), nullable=True),
        sa.Column("time_saved_minutes", sa.Float(), nullable=True, server_default="0"),
        sa.Column("breakdown", sa.JSON(), nullable=True),
        sa.Column("trend", sa.JSON(), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_impacts_workspace_id", "impacts", ["workspace_id"])
    op.create_index("ix_impacts_target_id", "impacts", ["target_id"])

    # ---- decisions ------------------------------------------------------
    op.create_table(
        "decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=True, server_default="capability"),
        sa.Column("target_id", sa.String(length=36), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=True, server_default="recommendation"),
        sa.Column("status", sa.String(length=20), nullable=True, server_default="open"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("rationale", sa.JSON(), nullable=True),
        sa.Column("impact_estimate", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_decisions_workspace_id", "decisions", ["workspace_id"])
    op.create_index("ix_decisions_target_id", "decisions", ["target_id"])


def downgrade() -> None:
    op.drop_index("ix_decisions_target_id", table_name="decisions")
    op.drop_index("ix_decisions_workspace_id", table_name="decisions")
    op.drop_table("decisions")

    op.drop_index("ix_impacts_target_id", table_name="impacts")
    op.drop_index("ix_impacts_workspace_id", table_name="impacts")
    op.drop_table("impacts")

    op.drop_index("ix_skill_invocations_skill_slug", table_name="skill_invocations")
    op.drop_index("ix_skill_invocations_run_id", table_name="skill_invocations")
    op.drop_table("skill_invocations")

    op.drop_index("ix_runs_status", table_name="runs")
    op.drop_index("ix_runs_capability_id", table_name="runs")
    op.drop_index("ix_runs_system_id", table_name="runs")
    op.drop_index("ix_runs_workspace_id", table_name="runs")
    op.drop_table("runs")

    op.drop_index("ix_systems_status", table_name="systems")
    op.drop_index("ix_systems_capability_id", table_name="systems")
    op.drop_index("ix_systems_workspace_id", table_name="systems")
    op.drop_table("systems")

    op.drop_index("ix_adaptive_policies_workspace_id", table_name="adaptive_policies")
    op.drop_table("adaptive_policies")

    op.drop_index("ix_control_policies_target_id", table_name="control_policies")
    op.drop_index("ix_control_policies_workspace_id", table_name="control_policies")
    op.drop_table("control_policies")

    op.drop_index("ix_contexts_system_id", table_name="contexts")
    op.drop_index("ix_contexts_workspace_id", table_name="contexts")
    op.drop_table("contexts")

    op.drop_index("ix_skills_workspace_id", table_name="skills")
    op.drop_index("ix_skills_slug", table_name="skills")
    op.drop_table("skills")

    op.drop_index("ix_capabilities_workspace_id", table_name="capabilities")
    op.drop_index("ix_capabilities_slug", table_name="capabilities")
    op.drop_table("capabilities")
