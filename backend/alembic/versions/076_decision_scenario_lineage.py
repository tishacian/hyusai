"""Bind every scenario-linked Decision to its exact tenant and System.

Revision ID: 076_decision_scenario_lineage
Revises: 075_simulation_approval_pin

The legacy Decision foreign key covered only ``scenario_id``.  A direct
database write could therefore transplant a Decision to another workspace or
System while retaining a valid ValueScenario id.  This revision replaces that
edge with a compositional tenant/scenario/System reference and refuses to
guess how any historical drift should be repaired.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "076_decision_scenario_lineage"
down_revision = "075_simulation_approval_pin"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

LEGACY_FOREIGN_KEY = "fk_decisions_scenario_id_value_scenarios"
LINEAGE_FOREIGN_KEY = "fk_decisions_scenario_lineage"
LINEAGE_CHECK = "ck_decisions_scenario_lineage_complete"
LINEAGE_CANDIDATE_KEY = "uq_value_scenarios_ws_id_system"

DECISION_COLUMNS = ("id", "workspace_id", "scenario_id", "target_id")
SCENARIO_COLUMNS = ("id", "workspace_id", "system_id")
LOCAL_LINEAGE_COLUMNS = ("workspace_id", "scenario_id", "target_id")
REMOTE_LINEAGE_COLUMNS = ("workspace_id", "id", "system_id")
LINEAGE_CHECK_SQL = (
    "scenario_id IS NULL OR "
    "(workspace_id IS NOT NULL AND target_id IS NOT NULL)"
)


def _named(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["name"]): item for item in items if item.get("name")}


def _columns(item: dict[str, Any], key: str) -> tuple[str, ...]:
    return tuple(str(column) for column in item.get(key) or ())


def _normalized_check(sqltext: object) -> str:
    return "".join(
        character
        for character in str(sqltext).lower()
        if not character.isspace() and character not in {'"', "`", "(", ")"}
    )


def _upgrade_structural_issues(bind: Any) -> list[dict[str, Any]]:
    """Verify the exact 075 contract before inspecting data or running DDL."""

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    issues: list[dict[str, Any]] = []
    required = {
        "decisions": DECISION_COLUMNS,
        "value_scenarios": SCENARIO_COLUMNS,
    }
    for table_name, columns in required.items():
        if table_name not in tables:
            issues.append({"kind": "missing_table", "table": table_name})
            continue
        actual = {str(column["name"]) for column in inspector.get_columns(table_name)}
        missing = sorted(set(columns) - actual)
        if missing:
            issues.append(
                {
                    "kind": "missing_columns",
                    "table": table_name,
                    "columns": missing,
                }
            )

    if issues:
        return issues

    legacy = _named(inspector.get_foreign_keys("decisions")).get(LEGACY_FOREIGN_KEY)
    if legacy is None:
        issues.append(
            {
                "kind": "missing_foreign_key",
                "table": "decisions",
                "constraint": LEGACY_FOREIGN_KEY,
            }
        )
    else:
        actual = {
            "local_columns": list(_columns(legacy, "constrained_columns")),
            "remote_table": str(legacy.get("referred_table")),
            "remote_columns": list(_columns(legacy, "referred_columns")),
            "ondelete": str((legacy.get("options") or {}).get("ondelete") or "").upper(),
        }
        expected = {
            "local_columns": ["scenario_id"],
            "remote_table": "value_scenarios",
            "remote_columns": ["id"],
            "ondelete": "SET NULL",
        }
        if actual != expected:
            issues.append(
                {
                    "kind": "unexpected_foreign_key",
                    "table": "decisions",
                    "constraint": LEGACY_FOREIGN_KEY,
                    "actual": actual,
                    "expected": expected,
                }
            )

    decision_uniques = _named(inspector.get_unique_constraints("decisions"))
    scenario_unique = decision_uniques.get("uq_decisions_scenario_id")
    if scenario_unique is None or _columns(scenario_unique, "column_names") != ("scenario_id",):
        issues.append(
            {
                "kind": "missing_or_unexpected_unique",
                "table": "decisions",
                "constraint": "uq_decisions_scenario_id",
            }
        )

    scenario_uniques = _named(inspector.get_unique_constraints("value_scenarios"))
    tenant_key = scenario_uniques.get("uq_value_scenarios_ws_system_id")
    if tenant_key is None or _columns(tenant_key, "column_names") != (
        "workspace_id",
        "system_id",
        "id",
    ):
        issues.append(
            {
                "kind": "missing_or_unexpected_unique",
                "table": "value_scenarios",
                "constraint": "uq_value_scenarios_ws_system_id",
            }
        )
    return issues


def _decision_lineage_drift(bind: Any) -> dict[str, Any] | None:
    query = """
        SELECT child.id AS entity_id
        FROM decisions AS child
        WHERE child.scenario_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1
            FROM value_scenarios AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.id = child.scenario_id
              AND parent.system_id = child.target_id
          )
    """.strip()
    count = int(
        bind.execute(
            sa.text(f"SELECT COUNT(*) FROM ({query}) AS decision_lineage_drift")
        ).scalar_one()
    )
    if not count:
        return None
    examples = [
        str(value)
        for value in bind.execute(
            sa.text(
                "SELECT entity_id "
                f"FROM ({query}) AS decision_lineage_drift "
                "ORDER BY entity_id ASC LIMIT 10"
            )
        ).scalars()
    ]
    return {
        "relation": "decisions.scenario_lineage",
        "violation_count": count,
        "example_ids": examples,
    }


def _preflight(bind: Any) -> None:
    structural = _upgrade_structural_issues(bind)
    drift = None if structural else _decision_lineage_drift(bind)
    if not structural and drift is None:
        return
    report = {
        "event": "decision_scenario_lineage.preflight_failed",
        "revision": revision,
        "structural_issues": structural,
        "data_drifts": [] if drift is None else [drift],
        "resolution": (
            "repair every scenario-linked Decision to the exact ValueScenario "
            "workspace and System, then rerun the migration"
        ),
    }
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":"))
    logger.error("Decision scenario lineage preflight failed: %s", encoded)
    raise RuntimeError(f"Decision scenario lineage preflight failed: {encoded}")


def _downgrade_structural_issues(bind: Any) -> list[dict[str, Any]]:
    """Fail closed if authority cannot be proven before its removal."""

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    issues: list[dict[str, Any]] = []
    if "decisions" not in tables:
        issues.append({"kind": "missing_table", "table": "decisions"})
    if "value_scenarios" not in tables:
        issues.append({"kind": "missing_table", "table": "value_scenarios"})
    if issues:
        return issues

    actual_decision_columns = {
        str(column["name"]) for column in inspector.get_columns("decisions")
    }
    missing_decision_columns = sorted(set(DECISION_COLUMNS) - actual_decision_columns)
    if missing_decision_columns:
        issues.append(
            {
                "kind": "missing_columns",
                "table": "decisions",
                "columns": missing_decision_columns,
            }
        )

    lineage = _named(inspector.get_foreign_keys("decisions")).get(LINEAGE_FOREIGN_KEY)
    lineage_ondelete = str(
        ((lineage or {}).get("options") or {}).get("ondelete") or ""
    ).upper()
    if (
        lineage is None
        or _columns(lineage, "constrained_columns") != LOCAL_LINEAGE_COLUMNS
        or str(lineage.get("referred_table")) != "value_scenarios"
        or _columns(lineage, "referred_columns") != REMOTE_LINEAGE_COLUMNS
        or lineage_ondelete != "RESTRICT"
    ):
        issues.append(
            {
                "kind": "missing_or_unexpected_foreign_key",
                "table": "decisions",
                "constraint": LINEAGE_FOREIGN_KEY,
            }
        )

    checks = _named(inspector.get_check_constraints("decisions"))
    lineage_check = checks.get(LINEAGE_CHECK)
    if lineage_check is None or _normalized_check(lineage_check.get("sqltext")) != (
        _normalized_check(LINEAGE_CHECK_SQL)
    ):
        issues.append(
            {
                "kind": "missing_check",
                "table": "decisions",
                "constraint": LINEAGE_CHECK,
            }
        )

    scenario_uniques = _named(inspector.get_unique_constraints("value_scenarios"))
    candidate = scenario_uniques.get(LINEAGE_CANDIDATE_KEY)
    if candidate is None or _columns(candidate, "column_names") != REMOTE_LINEAGE_COLUMNS:
        issues.append(
            {
                "kind": "missing_or_unexpected_unique",
                "table": "value_scenarios",
                "constraint": LINEAGE_CANDIDATE_KEY,
            }
        )
    return issues


def _assert_downgrade_safe(bind: Any) -> None:
    structural = _downgrade_structural_issues(bind)
    if structural:
        encoded = json.dumps(structural, sort_keys=True, separators=(",", ":"))
        raise RuntimeError(
            "refusing Decision scenario lineage downgrade because the active "
            f"authority cannot be verified: {encoded}"
        )

    count = int(
        bind.execute(
            sa.text("SELECT COUNT(*) FROM decisions WHERE scenario_id IS NOT NULL")
        ).scalar_one()
    )
    if count:
        examples = [
            str(value)
            for value in bind.execute(
                sa.text(
                    "SELECT id FROM decisions WHERE scenario_id IS NOT NULL "
                    "ORDER BY id ASC LIMIT 10"
                )
            ).scalars()
        ]
        raise RuntimeError(
            "refusing destructive downgrade of authoritative Decision scenario "
            f"lineage (rows={count}, example_ids={examples})"
        )


def upgrade() -> None:
    bind = op.get_bind()
    _preflight(bind)

    with op.batch_alter_table("value_scenarios") as batch:
        batch.create_unique_constraint(
            LINEAGE_CANDIDATE_KEY,
            list(REMOTE_LINEAGE_COLUMNS),
        )

    with op.batch_alter_table("decisions") as batch:
        batch.drop_constraint(LEGACY_FOREIGN_KEY, type_="foreignkey")
        batch.create_check_constraint(
            LINEAGE_CHECK,
            LINEAGE_CHECK_SQL,
        )
        batch.create_foreign_key(
            LINEAGE_FOREIGN_KEY,
            "value_scenarios",
            list(LOCAL_LINEAGE_COLUMNS),
            list(REMOTE_LINEAGE_COLUMNS),
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    bind = op.get_bind()
    _assert_downgrade_safe(bind)

    with op.batch_alter_table("decisions") as batch:
        batch.drop_constraint(LINEAGE_FOREIGN_KEY, type_="foreignkey")
        batch.drop_constraint(LINEAGE_CHECK, type_="check")
        batch.create_foreign_key(
            LEGACY_FOREIGN_KEY,
            "value_scenarios",
            ["scenario_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("value_scenarios") as batch:
        batch.drop_constraint(LINEAGE_CANDIDATE_KEY, type_="unique")
