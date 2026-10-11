"""Contract for migration 084, driven by graphs captured from the estate.

The fixtures under ``app/tests/fixtures/flow_condition_repair`` are verbatim
``flow_definition`` payloads exported from a restored copy of production before
the repair, so these tests exercise the real damage rather than a restatement
of it. The decisive assertion is that the real validator stops emitting
``decision_condition_invalid`` after the migration's rewrite — the migration is
never allowed to define its own notion of "valid".
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from app.models.workspace import Workspace
from app.services.chains.dag_validator import has_errors, validate_flow
from app.services.run_engine.condition import ConditionError
from app.services.run_engine.condition import evaluate as evaluate_condition
from app.services.run_engine.condition import validate as validate_condition
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.systems.bootstrap import (
    _expert_capture_flow_definition,
    _workspace_chat_flow_definition,
    _workspace_chat_profile,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "flow_condition_repair"

DAMAGED_FIXTURES = (
    "agentium_workspace_chat_damaged.json",
    "expert_knowledge_capture_damaged.json",
)
UNTOUCHED_FIXTURES = (
    "tender_response_analyst.json",
    "contract_risk_copilot.json",
    "nawa_shared_mailbox_creation.json",
)


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "084_decision_condition_repair.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_084", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return module


MIG = _load_migration()


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def _conditions(flow: dict[str, Any]) -> list[str]:
    return [
        branch["condition"]
        for node in flow.get("nodes") or []
        if (node.get("kind") or node.get("type")) == "decision"
        for branch in (node.get("config") or {}).get("branches") or []
        if isinstance(branch.get("condition"), str)
    ]


# --------------------------------------------------------------------------
# Placement in the revision graph
# --------------------------------------------------------------------------


def test_revision_extends_current_head() -> None:
    assert MIG.revision == "084_decision_condition_repair"
    assert MIG.down_revision == "083_workspace_skill_executor"


def test_revision_identifier_fits_the_stamp_column() -> None:
    """Guarded globally by ``test_migration_revision_identifiers`` too.

    Restated here because an over-long identifier only fails at the very end of
    a real upgrade, after the data change has already been written.
    """
    assert len(MIG.revision) <= 32


# --------------------------------------------------------------------------
# The repair map is the seed's answer, not this migration's invention
# --------------------------------------------------------------------------


def _seeded_flows() -> list[dict[str, Any]]:
    workspace = Workspace(id="ws-084", name="Repair", slug="repair")
    workspace.settings = {}
    # Empty skill stub, as in ``test_seeded_flows_validator``: the generators
    # only look skills up to stamp ``skill_id`` and keep the graph intact.
    return [
        _workspace_chat_flow_definition(_workspace_chat_profile(workspace), {}),
        _expert_capture_flow_definition({}),
    ]


def test_every_replacement_is_a_condition_the_repaired_seeds_actually_ship() -> None:
    """Pin the migration to ``bootstrap.py`` so the two cannot drift apart.

    If a seed template is re-authored, this fails and the stored rows are
    re-examined instead of silently diverging from what new workspaces get.
    """
    seeded = {c for flow in _seeded_flows() for c in _conditions(flow)}
    missing = sorted(set(MIG.CONDITION_REPAIRS.values()) - seeded)
    assert not missing, (
        "These replacements no longer appear in any repaired seed template, so "
        f"the migration would write text the seeds disagree with: {missing}"
    )


def test_the_repaired_seeds_no_longer_contain_any_damaged_condition() -> None:
    seeded = {c for flow in _seeded_flows() for c in _conditions(flow)}
    still_damaged = sorted(seeded & set(MIG.CONDITION_REPAIRS))
    assert not still_damaged, (
        "A seed template regressed to prose the migration is meant to retire: "
        f"{still_damaged}"
    )


def test_every_damaged_key_is_rejected_and_every_replacement_is_accepted() -> None:
    for damaged, replacement in MIG.CONDITION_REPAIRS.items():
        try:
            validate_condition(damaged)
        except ConditionError:
            pass
        else:  # pragma: no cover - a key the grammar accepts must not be rewritten
            raise AssertionError(
                f"{damaged!r} parses fine, so rewriting it changes working behaviour"
            )
        validate_condition(replacement)


# --------------------------------------------------------------------------
# The rewrite, against real estate graphs
# --------------------------------------------------------------------------


def test_damaged_fixtures_fail_the_validator_before_the_repair() -> None:
    for name in DAMAGED_FIXTURES:
        issues = validate_flow(_fixture(name))
        codes = {issue.code for issue in issues if issue.level == "error"}
        assert codes == {"decision_condition_invalid"}, (
            f"{name} was captured for this reason only; it now also fails on {codes}"
        )


def test_repaired_fixtures_carry_no_blocking_diagnostic() -> None:
    for name in DAMAGED_FIXTURES:
        repaired, rewritten = MIG.repair_flow(_fixture(name))
        assert rewritten > 0
        assert not has_errors(validate_flow(repaired)), (
            f"{name} still blocks publication after the repair: "
            f"{[i.code for i in validate_flow(repaired) if i.level == 'error']}"
        )


def test_repair_only_touches_decision_branch_conditions() -> None:
    for name in DAMAGED_FIXTURES:
        original = _fixture(name)
        repaired, _ = MIG.repair_flow(original)

        stripped_original = json.loads(json.dumps(original))
        stripped_repaired = json.loads(json.dumps(repaired))
        for flow in (stripped_original, stripped_repaired):
            for node in flow["nodes"]:
                if (node.get("kind") or node.get("type")) == "decision":
                    for branch in (node.get("config") or {}).get("branches") or []:
                        branch.pop("condition", None)
        assert stripped_original == stripped_repaired, (
            f"{name} changed somewhere other than a Decision branch condition"
        )


def test_repair_does_not_mutate_its_argument() -> None:
    original = _fixture(DAMAGED_FIXTURES[0])
    snapshot = json.loads(json.dumps(original))
    MIG.repair_flow(original)
    assert original == snapshot


def test_repair_is_idempotent() -> None:
    once, first = MIG.repair_flow(_fixture(DAMAGED_FIXTURES[0]))
    twice, second = MIG.repair_flow(once)
    assert second == 0
    assert twice == once


def test_graphs_with_other_defects_are_left_exactly_alone() -> None:
    """These three need an author's decision; the migration must not guess."""
    for name in UNTOUCHED_FIXTURES:
        original = _fixture(name)
        repaired, rewritten = MIG.repair_flow(original)
        assert rewritten == 0, f"{name} is not a condition defect"
        assert repaired == original


def test_repaired_branches_select_the_declared_default_when_nothing_is_bound() -> None:
    """The repair adds no routing the graph did not already declare.

    Overlay Decisions read a flat ctx (``dag._decision_ctx``), and none of these
    predicates' names is produced by the node's own predecessor, so on a payload
    that binds nothing every repaired Decision must fall on the branch it
    already names as ``default_branch``. That makes the rewrite behaviour-neutral
    today while leaving the branch selectable once ``route``,
    ``deep_search_requested`` or ``verdict`` is actually supplied.
    """
    for name in DAMAGED_FIXTURES:
        repaired, _ = MIG.repair_flow(_fixture(name))
        decisions = [
            node
            for node in repaired["nodes"]
            if (node.get("kind") or node.get("type")) == "decision"
        ]
        assert decisions, f"{name} was captured for its Decision nodes"
        for node in decisions:
            config = node["config"]
            first_match = next(
                (
                    branch["label"]
                    for branch in config["branches"]
                    if evaluate_condition(branch["condition"], {})
                ),
                None,
            )
            assert first_match == config["default_branch"], (
                f"{name}: Decision {node['id']!r} would route to {first_match!r} on an "
                f"unbound payload instead of its declared default "
                f"{config['default_branch']!r}"
            )


def test_a_matching_string_outside_a_decision_branch_is_not_rewritten() -> None:
    flow = {
        "schema_version": 3,
        "nodes": [
            {
                "id": "task",
                "kind": "task",
                # Same text, but this is documentation on a task node.
                "data": {"description": "default route"},
                "config": {"branches": [{"label": "x", "condition": "default route"}]},
            }
        ],
        "edges": [],
    }
    repaired, rewritten = MIG.repair_flow(flow)
    assert rewritten == 0
    assert repaired == flow


# --------------------------------------------------------------------------
# The migration body: three tables, one ledger, a real reversal
# --------------------------------------------------------------------------


def _schema(connection):
    metadata = sa.MetaData()
    systems = sa.Table(
        "systems",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36)),
        sa.Column("flow_definition", sa.JSON()),
    )
    versions = sa.Table(
        "system_versions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("system_id", sa.String(36), nullable=False),
        sa.Column("flow_definition", sa.JSON(), nullable=False),
        sa.Column("flow_sha256", sa.String(64)),
    )
    drafts = sa.Table(
        "system_flow_drafts",
        metadata,
        sa.Column("system_id", sa.String(36), primary_key=True),
        sa.Column("flow_definition", sa.JSON(), nullable=False),
        sa.Column("flow_sha256", sa.String(64), nullable=False),
    )
    metadata.create_all(connection)
    return systems, versions, drafts


def _bind(connection) -> None:
    """Give the migration the two DDL verbs it uses, backed by the connection."""

    def create_table(name: str, *columns: Any, **kwargs: Any) -> None:
        sa.Table(name, sa.MetaData(), *columns, **kwargs).create(connection)

    def drop_table(name: str, **_kwargs: Any) -> None:
        sa.Table(name, sa.MetaData(), autoload_with=connection).drop(connection)

    MIG.op.get_bind = lambda: connection
    MIG.op.create_table = create_table
    MIG.op.drop_table = drop_table


def _seed_estate(connection, systems, versions, drafts) -> dict[str, Any]:
    damaged = _fixture("agentium_workspace_chat_damaged.json")
    clean = _fixture("tender_response_analyst.json")
    connection.execute(
        systems.insert(),
        [
            {"id": "sys-damaged", "workspace_id": "ws", "flow_definition": damaged},
            {"id": "sys-clean", "workspace_id": "ws", "flow_definition": clean},
        ],
    )
    connection.execute(
        versions.insert(),
        [
            {
                "id": "ver-published",
                "system_id": "sys-damaged",
                "flow_definition": damaged,
                "flow_sha256": canonical_flow_sha256(damaged),
            },
            # 077 left historical snapshots without a digest; the repair must
            # cope with NULL rather than assume the column is populated.
            {
                "id": "ver-no-digest",
                "system_id": "sys-damaged",
                "flow_definition": damaged,
                "flow_sha256": None,
            },
            {
                "id": "ver-clean",
                "system_id": "sys-clean",
                "flow_definition": clean,
                "flow_sha256": canonical_flow_sha256(clean),
            },
        ],
    )
    connection.execute(
        drafts.insert(),
        [
            {
                "system_id": "sys-damaged",
                "flow_definition": damaged,
                "flow_sha256": canonical_flow_sha256(damaged),
            },
            {
                "system_id": "sys-clean",
                "flow_definition": clean,
                "flow_sha256": canonical_flow_sha256(clean),
            },
        ],
    )
    return damaged


def test_upgrade_repairs_all_three_tables_and_keeps_their_digests_agreeing() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        systems, versions, drafts = _schema(connection)
        damaged = _seed_estate(connection, systems, versions, drafts)
        _bind(connection)
        MIG.upgrade()

        expected, _ = MIG.repair_flow(damaged)
        expected_digest = canonical_flow_sha256(expected)

        system = connection.execute(
            sa.select(systems).where(systems.c.id == "sys-damaged")
        ).mappings().one()
        assert system["flow_definition"] == expected

        draft = connection.execute(
            sa.select(drafts).where(drafts.c.system_id == "sys-damaged")
        ).mappings().one()
        assert draft["flow_definition"] == expected
        assert draft["flow_sha256"] == expected_digest

        for version_id in ("ver-published", "ver-no-digest"):
            version = connection.execute(
                sa.select(versions).where(versions.c.id == version_id)
            ).mappings().one()
            assert version["flow_definition"] == expected
            # The publication gate reads a digest that contradicts its own
            # payload as drift and refuses to repair the System at all.
            assert version["flow_sha256"] == expected_digest

        # The three copies the gate compares must still be byte-identical.
        assert (
            canonical_flow_sha256(system["flow_definition"])
            == canonical_flow_sha256(draft["flow_definition"])
            == expected_digest
        )


def test_upgrade_leaves_undamaged_rows_untouched() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        systems, versions, drafts = _schema(connection)
        _seed_estate(connection, systems, versions, drafts)
        clean = _fixture("tender_response_analyst.json")
        _bind(connection)
        MIG.upgrade()

        assert connection.execute(
            sa.select(systems.c.flow_definition).where(systems.c.id == "sys-clean")
        ).scalar_one() == clean
        assert connection.execute(
            sa.select(versions.c.flow_definition).where(versions.c.id == "ver-clean")
        ).scalar_one() == clean

        ledger = sa.Table(MIG.LEDGER, sa.MetaData(), autoload_with=connection)
        touched = {
            (row["source_table"], row["row_key"])
            for row in connection.execute(sa.select(ledger)).mappings()
        }
        assert touched == {
            ("systems", "sys-damaged"),
            ("system_flow_drafts", "sys-damaged"),
            ("system_versions", "ver-published"),
            ("system_versions", "ver-no-digest"),
        }


def test_downgrade_restores_the_exact_prior_bytes_including_a_null_digest() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        systems, versions, drafts = _schema(connection)
        _seed_estate(connection, systems, versions, drafts)
        before = {
            "systems": connection.execute(sa.select(systems)).mappings().all(),
            "versions": connection.execute(sa.select(versions)).mappings().all(),
            "drafts": connection.execute(sa.select(drafts)).mappings().all(),
        }
        _bind(connection)
        MIG.upgrade()
        MIG.downgrade()

        assert connection.execute(sa.select(systems)).mappings().all() == before["systems"]
        assert connection.execute(sa.select(versions)).mappings().all() == before["versions"]
        assert connection.execute(sa.select(drafts)).mappings().all() == before["drafts"]
        # A digest that was unknown before must not come back invented.
        assert connection.execute(
            sa.select(versions.c.flow_sha256).where(versions.c.id == "ver-no-digest")
        ).scalar_one() is None
        assert not sa.inspect(connection).has_table(MIG.LEDGER)


def test_upgrade_is_idempotent_when_replayed_over_repaired_rows() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        systems, versions, drafts = _schema(connection)
        _seed_estate(connection, systems, versions, drafts)
        _bind(connection)
        MIG.upgrade()
        after_first = connection.execute(sa.select(systems)).mappings().all()

        MIG.op.drop_table(MIG.LEDGER)
        MIG.upgrade()

        assert connection.execute(sa.select(systems)).mappings().all() == after_first
        ledger = sa.Table(MIG.LEDGER, sa.MetaData(), autoload_with=connection)
        assert connection.execute(
            sa.select(sa.func.count()).select_from(ledger)
        ).scalar_one() == 0
