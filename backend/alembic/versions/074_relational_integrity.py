"""Close tenant and lineage gaps in the value and Workspace App ledgers.

Revision ID: 074_relational_integrity
Revises: 073_workspace_app_steps

The migration is deliberately additive at the data level.  It first audits
every relation that the new composite foreign keys will enforce and refuses to
run any DDL when historical rows do not match exactly.  Operators must resolve
the reported drift explicitly; this migration never guesses a tenant, System,
scenario, installation or application identity.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "074_relational_integrity"
down_revision = "073_workspace_app_steps"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


# Candidate keys are tenant-first so every composite reference has the same
# leading discriminator as the queries and row-level authorization checks.
CANDIDATE_KEYS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("systems", "uq_systems_workspace_id", ("workspace_id", "id")),
    (
        "runs",
        "uq_runs_workspace_system_id",
        ("workspace_id", "system_id", "id"),
    ),
    (
        "control_policies",
        "uq_control_policies_ws_target_id",
        ("workspace_id", "target_id", "id"),
    ),
    (
        "value_loop_operations",
        "uq_value_loop_operations_ws_id",
        ("workspace_id", "id"),
    ),
    (
        "value_scenarios",
        "uq_value_scenarios_ws_system_id",
        ("workspace_id", "system_id", "id"),
    ),
    (
        "value_simulations",
        "uq_value_simulations_lineage_id",
        ("workspace_id", "system_id", "scenario_id", "id"),
    ),
    (
        "value_action_executions",
        "uq_value_actions_lineage_id",
        ("workspace_id", "system_id", "scenario_id", "simulation_id", "id"),
    ),
    (
        "workspace_app_installations",
        "uq_workspace_app_installations_lineage",
        ("workspace_id", "app_id", "id"),
    ),
    (
        "workspace_app_operations",
        "uq_workspace_app_operations_lineage",
        ("workspace_id", "app_id", "installation_id", "id"),
    ),
)


# table, constraint name, local columns, remote table, remote columns,
# on-delete action, deferrable, initially.
COMPOSITE_FOREIGN_KEYS: tuple[
    tuple[
        str,
        str,
        tuple[str, ...],
        str,
        tuple[str, ...],
        str,
        bool | None,
        str | None,
    ],
    ...,
] = (
    (
        "value_scenarios",
        "fk_value_scenarios_system_tenant",
        ("workspace_id", "system_id"),
        "systems",
        ("workspace_id", "id"),
        "CASCADE",
        None,
        None,
    ),
    (
        "value_scenarios",
        "fk_value_scenarios_source_run_lineage",
        ("workspace_id", "system_id", "source_run_id"),
        "runs",
        ("workspace_id", "system_id", "id"),
        "RESTRICT",
        None,
        None,
    ),
    (
        "value_scenarios",
        "fk_value_scenarios_operation_tenant",
        ("workspace_id", "operation_id"),
        "value_loop_operations",
        ("workspace_id", "id"),
        "RESTRICT",
        None,
        None,
    ),
    (
        "value_scenarios",
        "fk_value_scenarios_approval_operation_tenant",
        ("workspace_id", "approval_operation_id"),
        "value_loop_operations",
        ("workspace_id", "id"),
        "RESTRICT",
        None,
        None,
    ),
    (
        "value_simulations",
        "fk_value_simulations_scenario_lineage",
        ("workspace_id", "system_id", "scenario_id"),
        "value_scenarios",
        ("workspace_id", "system_id", "id"),
        "CASCADE",
        None,
        None,
    ),
    (
        "value_simulations",
        "fk_value_simulations_operation_tenant",
        ("workspace_id", "operation_id"),
        "value_loop_operations",
        ("workspace_id", "id"),
        "RESTRICT",
        None,
        None,
    ),
    (
        "value_action_executions",
        "fk_value_action_executions_scenario_lineage",
        ("workspace_id", "system_id", "scenario_id"),
        "value_scenarios",
        ("workspace_id", "system_id", "id"),
        "CASCADE",
        None,
        None,
    ),
    (
        "value_action_executions",
        "fk_value_action_executions_simulation_lineage",
        ("workspace_id", "system_id", "scenario_id", "simulation_id"),
        "value_simulations",
        ("workspace_id", "system_id", "scenario_id", "id"),
        "RESTRICT",
        None,
        None,
    ),
    (
        "value_action_executions",
        "fk_value_action_executions_control_policy_lineage",
        ("workspace_id", "system_id", "control_policy_id"),
        "control_policies",
        ("workspace_id", "target_id", "id"),
        "RESTRICT",
        None,
        None,
    ),
    (
        "value_action_executions",
        "fk_value_action_executions_operation_tenant",
        ("workspace_id", "operation_id"),
        "value_loop_operations",
        ("workspace_id", "id"),
        "RESTRICT",
        None,
        None,
    ),
    (
        "value_measurements",
        "fk_value_measurements_scenario_lineage",
        ("workspace_id", "system_id", "scenario_id"),
        "value_scenarios",
        ("workspace_id", "system_id", "id"),
        "CASCADE",
        None,
        None,
    ),
    (
        "value_measurements",
        "fk_value_measurements_simulation_lineage",
        ("workspace_id", "system_id", "scenario_id", "simulation_id"),
        "value_simulations",
        ("workspace_id", "system_id", "scenario_id", "id"),
        "RESTRICT",
        None,
        None,
    ),
    (
        "value_measurements",
        "fk_value_measurements_action_lineage",
        (
            "workspace_id",
            "system_id",
            "scenario_id",
            "simulation_id",
            "action_execution_id",
        ),
        "value_action_executions",
        ("workspace_id", "system_id", "scenario_id", "simulation_id", "id"),
        "RESTRICT",
        None,
        None,
    ),
    (
        "value_measurements",
        "fk_value_measurements_source_run_lineage",
        ("workspace_id", "system_id", "source_run_id"),
        "runs",
        ("workspace_id", "system_id", "id"),
        "RESTRICT",
        None,
        None,
    ),
    (
        "value_measurements",
        "fk_value_measurements_operation_tenant",
        ("workspace_id", "operation_id"),
        "value_loop_operations",
        ("workspace_id", "id"),
        "RESTRICT",
        None,
        None,
    ),
    (
        "workspace_app_operations",
        "fk_workspace_app_operations_installation_lineage",
        ("workspace_id", "app_id", "installation_id"),
        "workspace_app_installations",
        ("workspace_id", "app_id", "id"),
        "CASCADE",
        None,
        None,
    ),
    (
        "workspace_app_lifecycle_step_receipts",
        "fk_workspace_app_step_receipts_operation_lineage",
        ("workspace_id", "app_id", "installation_id", "operation_id"),
        "workspace_app_operations",
        ("workspace_id", "app_id", "installation_id", "id"),
        "CASCADE",
        None,
        None,
    ),
    # This edge deliberately closes the only cycle.  Deferral lets a scenario
    # and its selected forecast be inserted in one transaction without ever
    # accepting a forecast from another tenant, System or scenario.
    (
        "value_scenarios",
        "fk_value_scenarios_approved_simulation_lineage",
        ("workspace_id", "system_id", "id", "approved_simulation_id"),
        "value_simulations",
        ("workspace_id", "system_id", "scenario_id", "id"),
        "RESTRICT",
        True,
        "DEFERRED",
    ),
)


GLOBAL_BLUEPRINT_INDEXES: tuple[tuple[str, str], ...] = (
    ("systems", "uq_systems_global_blueprint_key"),
    ("contexts", "uq_contexts_global_blueprint_key"),
)


REDUNDANT_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "system_versions",
        "ix_system_versions_system_version",
        ("system_id", "version_number"),
    ),
    ("decisions", "ix_decisions_scenario_id", ("scenario_id",)),
)


REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "systems": ("id", "workspace_id", "blueprint_key"),
    "contexts": ("id", "workspace_id", "blueprint_key"),
    "runs": ("id", "workspace_id", "system_id"),
    "control_policies": ("id", "workspace_id", "target_id"),
    "system_versions": ("system_id", "version_number"),
    "decisions": ("scenario_id",),
    "value_loop_operations": ("id", "workspace_id"),
    "value_scenarios": (
        "id",
        "workspace_id",
        "system_id",
        "source_run_id",
        "operation_id",
        "approval_operation_id",
        "approved_simulation_id",
    ),
    "value_simulations": ("id", "workspace_id", "system_id", "scenario_id", "operation_id"),
    "value_action_executions": (
        "id",
        "workspace_id",
        "system_id",
        "scenario_id",
        "simulation_id",
        "control_policy_id",
        "operation_id",
    ),
    "value_measurements": (
        "id",
        "workspace_id",
        "system_id",
        "scenario_id",
        "simulation_id",
        "action_execution_id",
        "source_run_id",
        "operation_id",
    ),
    "workspace_app_installations": ("id", "workspace_id", "app_id"),
    "workspace_app_operations": ("id", "workspace_id", "app_id", "installation_id"),
    "workspace_app_lifecycle_step_receipts": (
        "id",
        "workspace_id",
        "app_id",
        "installation_id",
        "operation_id",
    ),
}


# Every query returns only an opaque row identity.  Counts are complete while
# examples are bounded in the report, avoiding accidental business payloads in
# migration logs.
DRIFT_QUERIES: tuple[tuple[str, str], ...] = (
    (
        "value_scenarios.system_tenant",
        """
        SELECT child.id AS entity_id
        FROM value_scenarios AS child
        WHERE NOT EXISTS (
            SELECT 1 FROM systems AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.id = child.system_id
        )
        """,
    ),
    (
        "value_scenarios.source_run_lineage",
        """
        SELECT child.id AS entity_id
        FROM value_scenarios AS child
        WHERE NOT EXISTS (
            SELECT 1 FROM runs AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.system_id = child.system_id
              AND parent.id = child.source_run_id
        )
        """,
    ),
    (
        "value_scenarios.operation_tenant",
        """
        SELECT child.id AS entity_id
        FROM value_scenarios AS child
        WHERE NOT EXISTS (
            SELECT 1 FROM value_loop_operations AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.id = child.operation_id
        )
        """,
    ),
    (
        "value_scenarios.approval_operation_tenant",
        """
        SELECT child.id AS entity_id
        FROM value_scenarios AS child
        WHERE child.approval_operation_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM value_loop_operations AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.id = child.approval_operation_id
        )
        """,
    ),
    (
        "value_scenarios.approved_simulation_lineage",
        """
        SELECT child.id AS entity_id
        FROM value_scenarios AS child
        WHERE child.approved_simulation_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM value_simulations AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.system_id = child.system_id
              AND parent.scenario_id = child.id
              AND parent.id = child.approved_simulation_id
        )
        """,
    ),
    (
        "value_simulations.scenario_lineage",
        """
        SELECT child.id AS entity_id
        FROM value_simulations AS child
        WHERE NOT EXISTS (
            SELECT 1 FROM value_scenarios AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.system_id = child.system_id
              AND parent.id = child.scenario_id
        )
        """,
    ),
    (
        "value_simulations.operation_tenant",
        """
        SELECT child.id AS entity_id
        FROM value_simulations AS child
        WHERE NOT EXISTS (
            SELECT 1 FROM value_loop_operations AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.id = child.operation_id
        )
        """,
    ),
    (
        "value_action_executions.scenario_lineage",
        """
        SELECT child.id AS entity_id
        FROM value_action_executions AS child
        WHERE NOT EXISTS (
            SELECT 1 FROM value_scenarios AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.system_id = child.system_id
              AND parent.id = child.scenario_id
        )
        """,
    ),
    (
        "value_action_executions.simulation_lineage",
        """
        SELECT child.id AS entity_id
        FROM value_action_executions AS child
        WHERE NOT EXISTS (
            SELECT 1 FROM value_simulations AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.system_id = child.system_id
              AND parent.scenario_id = child.scenario_id
              AND parent.id = child.simulation_id
        )
        """,
    ),
    (
        "value_action_executions.control_policy_lineage",
        """
        SELECT child.id AS entity_id
        FROM value_action_executions AS child
        WHERE NOT EXISTS (
            SELECT 1 FROM control_policies AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.target_id = child.system_id
              AND parent.id = child.control_policy_id
        )
        """,
    ),
    (
        "value_action_executions.operation_tenant",
        """
        SELECT child.id AS entity_id
        FROM value_action_executions AS child
        WHERE NOT EXISTS (
            SELECT 1 FROM value_loop_operations AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.id = child.operation_id
        )
        """,
    ),
    (
        "value_measurements.scenario_lineage",
        """
        SELECT child.id AS entity_id
        FROM value_measurements AS child
        WHERE NOT EXISTS (
            SELECT 1 FROM value_scenarios AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.system_id = child.system_id
              AND parent.id = child.scenario_id
        )
        """,
    ),
    (
        "value_measurements.simulation_lineage",
        """
        SELECT child.id AS entity_id
        FROM value_measurements AS child
        WHERE NOT EXISTS (
            SELECT 1 FROM value_simulations AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.system_id = child.system_id
              AND parent.scenario_id = child.scenario_id
              AND parent.id = child.simulation_id
        )
        """,
    ),
    (
        "value_measurements.action_lineage",
        """
        SELECT child.id AS entity_id
        FROM value_measurements AS child
        WHERE NOT EXISTS (
            SELECT 1 FROM value_action_executions AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.system_id = child.system_id
              AND parent.scenario_id = child.scenario_id
              AND parent.simulation_id = child.simulation_id
              AND parent.id = child.action_execution_id
        )
        """,
    ),
    (
        "value_measurements.source_run_lineage",
        """
        SELECT child.id AS entity_id
        FROM value_measurements AS child
        WHERE child.source_run_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM runs AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.system_id = child.system_id
              AND parent.id = child.source_run_id
        )
        """,
    ),
    (
        "value_measurements.operation_tenant",
        """
        SELECT child.id AS entity_id
        FROM value_measurements AS child
        WHERE NOT EXISTS (
            SELECT 1 FROM value_loop_operations AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.id = child.operation_id
        )
        """,
    ),
    (
        "workspace_app_operations.installation_lineage",
        """
        SELECT child.id AS entity_id
        FROM workspace_app_operations AS child
        WHERE NOT EXISTS (
            SELECT 1 FROM workspace_app_installations AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.app_id = child.app_id
              AND parent.id = child.installation_id
        )
        """,
    ),
    (
        "workspace_app_step_receipts.operation_lineage",
        """
        SELECT child.id AS entity_id
        FROM workspace_app_lifecycle_step_receipts AS child
        WHERE NOT EXISTS (
            SELECT 1 FROM workspace_app_operations AS parent
            WHERE parent.workspace_id = child.workspace_id
              AND parent.app_id = child.app_id
              AND parent.installation_id = child.installation_id
              AND parent.id = child.operation_id
        )
        """,
    ),
    (
        "systems.global_blueprint_key_unique",
        """
        SELECT MIN(id) AS entity_id
        FROM systems
        WHERE workspace_id IS NULL
        GROUP BY blueprint_key
        HAVING COUNT(*) > 1
        """,
    ),
    (
        "contexts.global_blueprint_key_unique",
        """
        SELECT MIN(id) AS entity_id
        FROM contexts
        WHERE workspace_id IS NULL
        GROUP BY blueprint_key
        HAVING COUNT(*) > 1
        """,
    ),
)


def _index_by_name(inspector: sa.Inspector, table_name: str) -> dict[str, dict[str, Any]]:
    return {
        str(item["name"]): item for item in inspector.get_indexes(table_name) if item.get("name")
    }


def _structural_issues(bind: Any) -> list[dict[str, Any]]:
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    issues: list[dict[str, Any]] = []
    for table_name, required in REQUIRED_COLUMNS.items():
        if table_name not in tables:
            issues.append({"kind": "missing_table", "table": table_name})
            continue
        actual = {str(column["name"]) for column in inspector.get_columns(table_name)}
        missing = sorted(set(required) - actual)
        if missing:
            issues.append(
                {
                    "kind": "missing_columns",
                    "table": table_name,
                    "columns": missing,
                }
            )

    for table_name, index_name, columns in REDUNDANT_INDEXES:
        if table_name not in tables:
            continue
        index = _index_by_name(inspector, table_name).get(index_name)
        if index is None:
            issues.append({"kind": "missing_073_index", "table": table_name, "index": index_name})
            continue
        actual_columns = tuple(str(column) for column in index.get("column_names") or ())
        if actual_columns != columns or bool(index.get("unique")):
            issues.append(
                {
                    "kind": "unexpected_073_index",
                    "table": table_name,
                    "index": index_name,
                    "columns": list(actual_columns),
                    "unique": bool(index.get("unique")),
                }
            )
    return issues


def _data_drifts(bind: Any) -> list[dict[str, Any]]:
    drifts: list[dict[str, Any]] = []
    for relation, query in DRIFT_QUERIES:
        normalized = query.strip()
        count = int(
            bind.execute(
                sa.text(f"SELECT COUNT(*) FROM ({normalized}) AS relational_drift")
            ).scalar_one()
        )
        if not count:
            continue
        examples = [
            str(value)
            for value in bind.execute(
                sa.text(
                    "SELECT entity_id "
                    f"FROM ({normalized}) AS relational_drift "
                    "ORDER BY entity_id ASC LIMIT 10"
                )
            ).scalars()
        ]
        drifts.append(
            {
                "relation": relation,
                "violation_count": count,
                "example_ids": examples,
            }
        )
    return drifts


def _preflight(bind: Any) -> None:
    structural = _structural_issues(bind)
    # Never run relation queries against a structurally incomplete schema.
    drifts = [] if structural else _data_drifts(bind)
    if not structural and not drifts:
        return
    report = {
        "event": "relational_integrity.preflight_failed",
        "revision": revision,
        "structural_issues": structural,
        "data_drifts": drifts,
        "resolution": "resolve every reported drift explicitly, then rerun the migration",
    }
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":"))
    logger.error("Relational integrity preflight failed: %s", encoded)
    raise RuntimeError(f"Relational integrity preflight failed: {encoded}")


def _group_foreign_keys() -> (
    Iterable[
        tuple[
            str,
            list[
                tuple[
                    str,
                    tuple[str, ...],
                    str,
                    tuple[str, ...],
                    str,
                    bool | None,
                    str | None,
                ]
            ],
        ]
    ]
):
    tables: dict[
        str,
        list[
            tuple[
                str,
                tuple[str, ...],
                str,
                tuple[str, ...],
                str,
                bool | None,
                str | None,
            ]
        ],
    ] = {}
    for (
        table_name,
        name,
        local_columns,
        remote_table,
        remote_columns,
        ondelete,
        deferrable,
        initially,
    ) in COMPOSITE_FOREIGN_KEYS:
        tables.setdefault(table_name, []).append(
            (
                name,
                local_columns,
                remote_table,
                remote_columns,
                ondelete,
                deferrable,
                initially,
            )
        )
    return tables.items()


def upgrade() -> None:
    bind = op.get_bind()
    _preflight(bind)

    # All parent candidate keys exist before any child reference is installed.
    for table_name, name, columns in CANDIDATE_KEYS:
        with op.batch_alter_table(table_name) as batch:
            batch.create_unique_constraint(name, list(columns))

    for table_name, constraints in _group_foreign_keys():
        with op.batch_alter_table(table_name) as batch:
            for (
                name,
                local_columns,
                remote_table,
                remote_columns,
                ondelete,
                deferrable,
                initially,
            ) in constraints:
                options: dict[str, Any] = {"ondelete": ondelete}
                if deferrable is not None:
                    options["deferrable"] = deferrable
                if initially is not None:
                    options["initially"] = initially
                batch.create_foreign_key(
                    name,
                    remote_table,
                    list(local_columns),
                    list(remote_columns),
                    **options,
                )

    predicate = sa.text("workspace_id IS NULL")
    for table_name, index_name in GLOBAL_BLUEPRINT_INDEXES:
        op.create_index(
            index_name,
            table_name,
            ["blueprint_key"],
            unique=True,
            postgresql_where=predicate,
            sqlite_where=predicate,
        )

    for table_name, index_name, _columns in REDUNDANT_INDEXES:
        op.drop_index(index_name, table_name=table_name)


def downgrade() -> None:
    # Remove child references before their candidate keys.  Reversing the
    # grouped declaration also removes the cyclic edge first.
    grouped = list(_group_foreign_keys())
    for table_name, constraints in reversed(grouped):
        with op.batch_alter_table(table_name) as batch:
            for name, *_rest in reversed(constraints):
                batch.drop_constraint(name, type_="foreignkey")

    for table_name, name, _columns in reversed(CANDIDATE_KEYS):
        with op.batch_alter_table(table_name) as batch:
            batch.drop_constraint(name, type_="unique")

    for table_name, index_name in reversed(GLOBAL_BLUEPRINT_INDEXES):
        op.drop_index(index_name, table_name=table_name)

    for table_name, index_name, columns in REDUNDANT_INDEXES:
        op.create_index(index_name, table_name, list(columns), unique=False)
