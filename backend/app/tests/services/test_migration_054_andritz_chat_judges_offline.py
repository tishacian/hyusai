"""Tests for migration ``054_andritz_chat_judges_offline``.

Proves the online-serving re-seed that pulls the two LLM judges
(``eval_radar_v1`` / ``claim_audit_v1``) OUT of the DAG:

* the revision chains off the (single) prior head ``053_client360_chat_merge``;
* ``upgrade`` transitions a marker-scoped System's ``flow_definition`` to the
  fixed 21-node artifact, snapshots the prior flow once, and refreshes the bound
  membrane policy;
* the transition is idempotent (a second upgrade is a no-op);
* ``downgrade`` faithfully restores the pre-054 flow + policy and resets the
  shared ``flow_revision`` marker to the prior (051) tag.
"""
from __future__ import annotations

import importlib.util
import sys
import types
import uuid
from pathlib import Path

from app.models.policy import ControlPolicy
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "054_andritz_chat_judges_offline.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace(get_bind=lambda: None)
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_054", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return mod


MIG = _load_migration()

# Skills the fixed flow references (all pre-existing by the time 054 runs).
_FLOW_SKILLS = [
    "chat_agentic_plan_v1",
    "semantic_search_v1",
    "multi_hop_retrieve_v1",
    "llm_rag_answer_v1",
    "response_eval_v1",
    "chat_self_correct_v1",
    # judges: still catalogued (available) but no longer node-bound
    "eval_radar_v1",
    "claim_audit_v1",
]


def test_revision_metadata_chains_prior_head() -> None:
    assert MIG.revision == "054_andritz_chat_judges_offline"
    assert len(MIG.revision) <= 32
    assert MIG.down_revision == "053_client360_chat_merge"


def test_artifact_is_the_judges_offline_shape() -> None:
    artifact = MIG._load_artifact()
    assert artifact is not None
    flow = artifact["flow_definition"]
    node_ids = {n["id"] for n in flow["nodes"]}
    assert "task.eval_radar" not in node_ids
    assert "task.claim_audit" not in node_ids
    # Judges-offline shape (21 nodes) + Flow Builder sources DAG Phase 1
    # (migration 055) declarative source-plane nodes (asset.collection +
    # source.sftp_arrival) -> 23 nodes; judges stay unwired.
    assert len(flow["nodes"]) == 23
    # judges stay AVAILABLE in the membrane allow-list.
    allowed = artifact["membrane_spec"]["capabilities"]["allowed_skills"]
    assert "eval_radar_v1" in allowed and "claim_audit_v1" in allowed


def _prior_flow_with_judges() -> dict:
    """A minimal stand-in for the pre-054 (23-node) flow so the downgrade
    restore is observable (a fresh test DB would otherwise already carry the
    21-node artifact)."""
    nodes = [{"id": f"n{i}", "kind": "task"} for i in range(21)]
    nodes += [{"id": "task.eval_radar", "kind": "task"},
              {"id": "task.claim_audit", "kind": "task"}]
    return {"schema_version": 3, "variant": "chat_agentic_thinking_v1", "nodes": nodes, "edges": []}


def _seed_system_with_prior_flow(db) -> tuple[str, str]:
    ws = Workspace(id=str(uuid.uuid4()), name="Andritz", slug="andritz", settings={})
    db.add(ws)
    for slug in _FLOW_SKILLS:
        db.add(Skill(id=str(uuid.uuid4()), slug=slug, name=slug))
    policy = ControlPolicy(
        id=str(uuid.uuid4()), scope="system", target_id=None,
        allowed_skills=list(_FLOW_SKILLS),
        extra={"membrane_spec": {"capabilities": {"allowed_skills": list(_FLOW_SKILLS)}}},
    )
    db.add(policy)
    db.commit()
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        name="Andritz Chat Agentic",
        objective="test",
        control_policy_id=policy.id,
        flow_definition=_prior_flow_with_judges(),
        settings={"seed_origin": "048_andritz_chat_agentic",
                  "flow_revision": "051_andritz_chat_latency_mh"},
        status="active",
    )
    db.add(system)
    db.commit()
    return system.id, policy.id


def test_upgrade_pulls_judges_then_idempotent_then_downgrade(db_session, monkeypatch):
    system_id, policy_id = _seed_system_with_prior_flow(db_session)
    monkeypatch.setattr(MIG, "op", types.SimpleNamespace(get_bind=lambda: db_session.connection()))

    # --- upgrade: flow -> judges-offline artifact (23 nodes post-Phase 1) --
    MIG.upgrade()
    db_session.expire_all()
    system = db_session.query(System).filter(System.id == system_id).one()
    nodes = (system.flow_definition or {}).get("nodes") or []
    node_ids = {n["id"] for n in nodes}
    assert len(nodes) == 23
    assert "task.eval_radar" not in node_ids and "task.claim_audit" not in node_ids
    # skill_ids resolve to the 6 node-bound skills (judges are unwired).
    assert len(system.skill_ids or []) == 6
    settings = system.settings or {}
    assert settings.get("flow_revision") == "054_andritz_chat_judges_offline"
    # the prior (23-node) flow was snapshotted for a faithful downgrade.
    backup = settings.get("flow_backup_pre_054") or {}
    assert len({n["id"] for n in backup.get("nodes", [])} & {"task.eval_radar", "task.claim_audit"}) == 2

    # --- idempotency: a second upgrade keeps the same snapshot -------------
    MIG.upgrade()
    db_session.expire_all()
    system = db_session.query(System).filter(System.id == system_id).one()
    backup2 = (system.settings or {}).get("flow_backup_pre_054") or {}
    assert {n["id"] for n in backup2.get("nodes", [])} == {n["id"] for n in backup.get("nodes", [])}

    # --- downgrade: restore the pre-054 flow + reset the shared marker -----
    MIG.downgrade()
    db_session.expire_all()
    system = db_session.query(System).filter(System.id == system_id).one()
    restored_ids = {n["id"] for n in (system.flow_definition or {}).get("nodes", [])}
    assert {"task.eval_radar", "task.claim_audit"} <= restored_ids
    settings = system.settings or {}
    assert settings.get("flow_revision") == "051_andritz_chat_latency_mh"
    assert "flow_backup_pre_054" not in settings
