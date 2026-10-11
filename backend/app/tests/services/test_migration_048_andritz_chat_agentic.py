"""Tests for migration ``048_andritz_chat_agentic``.

Covers the pure helpers (membrane->columns mapping, skill_id resolution) and an
end-to-end upgrade/idempotency/downgrade pass against the real SQLite test
schema (the migration's ``op.get_bind`` is pointed at the test session bind).
The flow is loaded from the pinned artifact, so the test also guards that the
artifact resolves and every task node's ``skill_id`` is filled.
"""
from __future__ import annotations

import importlib.util
import sys
import types
import uuid
from pathlib import Path

from app.models.capability import Capability
from app.models.policy import ControlPolicy
from app.models.run import Run
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace


def _load_migration():
    """Load the migration by path (alembic.op stubbed for the import).

    The repo's local ``backend/alembic`` dir shadows the installed alembic when
    ``backend`` is on ``sys.path`` (as under pytest), so ``from alembic import
    op`` would fail. The DB-backed tests monkeypatch ``mod.op`` with the real
    session bind; the pure-function tests never touch ``op``.
    """
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "048_andritz_chat_agentic.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace(get_bind=lambda: None)
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_048", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return mod


MIG = _load_migration()

# The skills the flow references that already exist in a seeded catalog (the
# four migration-owned ones — the 3 agentic skills + multi_hop_retrieve_v1 — are
# upserted by the migration itself).
_PREEXISTING = ["semantic_search_v1", "llm_rag_answer_v1", "eval_radar_v1", "claim_audit_v1"]


# ---------------------------------------------------------------------------
# Revision metadata — the 046 lesson: id must fit alembic_version.version_num
# ---------------------------------------------------------------------------
def test_revision_id_is_short() -> None:
    assert MIG.revision == "048_andritz_chat_agentic"
    assert len(MIG.revision) <= 32
    assert MIG.down_revision == "047_andritz_membrane"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def test_artifact_loads_and_has_full_dag() -> None:
    artifact = MIG._load_artifact()
    assert artifact is not None
    flow = artifact["flow_definition"]
    assert flow["variant"] == "chat_agentic_thinking_v1"
    # Phase A latency fix (2026-07-09): the two LLM judge nodes (eval_radar /
    # claim_audit) were removed from the online serving DAG (23 -> 21 nodes);
    # fork.self_eval -> join.eval is kept as an instant telemetry scaffold.
    # Flow Builder sources DAG Phase 1 (migration 055) then added two declarative
    # source-plane nodes (asset.collection + source.sftp_arrival) -> 23 nodes.
    assert len(flow["nodes"]) == 23
    assert "membrane_spec" in artifact


def test_membrane_columns_maps_valves_and_caps() -> None:
    membrane = {
        "valves": {"max_cost_per_decision": 0.15, "max_latency_ms": 45000, "mandatory_hitl_if_confidence_below": 0.35},
        "capabilities": {"allowed_skills": ["a", "b"], "allowed_models": []},
    }
    cols = MIG._membrane_columns(membrane)
    assert cols["max_cost_per_decision"] == 0.15
    assert cols["max_latency_ms"] == 45000
    assert cols["mandatory_hitl_if_confidence_below"] == 0.35
    assert cols["allowed_skills"] == ["a", "b"]
    assert cols["allowed_models"] == []


# ---------------------------------------------------------------------------
# End-to-end upgrade / idempotency / downgrade against the real schema
# ---------------------------------------------------------------------------
def _seed_prereqs(db) -> str:
    ws = Workspace(id=str(uuid.uuid4()), name="Andritz", slug="andritz", settings={})
    db.add(ws)
    db.add(Capability(id=str(uuid.uuid4()), slug="workspace_assistant", name="Workspace Assistant"))
    for slug in _PREEXISTING:
        db.add(Skill(id=str(uuid.uuid4()), slug=slug, name=slug))
    db.commit()
    return ws.id


def _bind_historical_migration_to_current_schema(db_session, monkeypatch) -> None:
    """Replay 048 while honouring required columns added by later revisions.

    Migration 048 intentionally describes the schema that existed at revision
    048 and must remain immutable.  The test suite, however, provisions the
    final ORM metadata where migration 071 made ``System.blueprint_key``
    required.  Replacing only the migration's lightweight ``systems`` table
    with the current model table lets SQLAlchemy apply that column's UUID
    default without changing 048 or weakening the final-schema constraint.
    """

    historical_tables = MIG._tables

    def tables_with_current_system_defaults():
        tables = list(historical_tables())
        tables[3] = System.__table__
        return tuple(tables)

    monkeypatch.setattr(MIG, "_tables", tables_with_current_system_defaults)
    # Resolve the session's current connection each call so it survives commits
    # issued between the upgrade, replay and downgrade phases.
    monkeypatch.setattr(
        MIG,
        "op",
        types.SimpleNamespace(get_bind=lambda: db_session.connection()),
    )


def test_upgrade_seeds_system_idempotent_then_downgrade(db_session, monkeypatch):
    ws_id = _seed_prereqs(db_session)
    _bind_historical_migration_to_current_schema(db_session, monkeypatch)

    # --- upgrade -----------------------------------------------------------
    MIG.upgrade()
    db_session.expire_all()
    systems = (
        db_session.query(System)
        .filter(System.workspace_id == ws_id, System.name == "Andritz Chat Agentic")
        .all()
    )
    assert len(systems) == 1
    system = systems[0]
    system_id = system.id  # capture PK before any delete so post-downgrade asserts stay detached-safe
    assert system.blueprint_key
    assert system.default_model == "gpt-4o-mini"
    assert system.status == "active"
    assert (system.settings or {}).get("seed_origin") == "048_andritz_chat_agentic"
    assert (system.settings or {}).get("variant") == "chat_agentic_thinking_v1"
    # Phase A latency fix (2026-07-09): dropping the two LLM judge nodes leaves
    # 6 distinct skills wired into the graph (eval_radar_v1 / claim_audit_v1 are
    # no longer node-bound, though they stay in the membrane allow-list below).
    assert len(system.skill_ids or []) == 6

    nodes = (system.flow_definition or {}).get("nodes") or []
    assert len(nodes) == 23
    unresolved = [
        n["id"] for n in nodes
        if (n.get("config") or {}).get("skill_slug") and not (n.get("config") or {}).get("skill_id")
    ]
    assert unresolved == []

    # The agentic skills + the multi-hop retrieval lane were upserted by the migration.
    for slug in ("chat_agentic_plan_v1", "chat_self_correct_v1", "response_eval_v1", "multi_hop_retrieve_v1"):
        assert db_session.query(Skill).filter(Skill.slug == slug).count() == 1

    policy = (
        db_session.query(ControlPolicy)
        .filter(ControlPolicy.scope == "system", ControlPolicy.target_id == system_id)
        .one()
    )
    assert system.control_policy_id == policy.id
    extra = policy.extra or {}
    assert extra.get("membrane_origin") == "048_andritz_chat_agentic"
    assert "membrane_spec" in extra
    # The membrane allow-list still permits all 8 skills (the two LLM judges stay
    # AVAILABLE for the offline A/B harness even though they were unwired from the
    # online serving DAG in the Phase A latency fix).
    assert len(extra["membrane_spec"]["capabilities"]["allowed_skills"]) == 8
    assert policy.max_latency_ms == 45000
    assert policy.mandatory_hitl_if_confidence_below == 0.35

    # --- idempotency: re-running creates no second System/policy ----------
    MIG.upgrade()
    db_session.expire_all()
    assert (
        db_session.query(System)
        .filter(System.workspace_id == ws_id, System.name == "Andritz Chat Agentic")
        .count()
        == 1
    )
    assert (
        db_session.query(ControlPolicy)
        .filter(ControlPolicy.scope == "system", ControlPolicy.target_id == system_id)
        .count()
        == 1
    )

    # --- downgrade: removes the seeded System + its membrane policy --------
    MIG.downgrade()
    db_session.expire_all()
    assert (
        db_session.query(System)
        .filter(System.workspace_id == ws_id, System.name == "Andritz Chat Agentic")
        .count()
        == 0
    )
    assert (
        db_session.query(ControlPolicy)
        .filter(ControlPolicy.scope == "system", ControlPolicy.target_id == system_id)
        .count()
        == 0
    )


def test_downgrade_removes_seeded_runs(db_session, monkeypatch):
    ws_id = _seed_prereqs(db_session)
    _bind_historical_migration_to_current_schema(db_session, monkeypatch)

    MIG.upgrade()
    db_session.expire_all()
    system_id = (
        db_session.query(System)
        .filter(System.workspace_id == ws_id, System.name == "Andritz Chat Agentic")
        .one()
        .id
    )
    # A run created against the seeded System must not block downgrade.
    db_session.add(Run(id=str(uuid.uuid4()), workspace_id=ws_id, system_id=system_id, input_ref={"query": "q"}))
    db_session.commit()

    MIG.downgrade()
    db_session.expire_all()
    assert db_session.query(System).filter(System.id == system_id).count() == 0
    assert db_session.query(Run).filter(Run.system_id == system_id).count() == 0
