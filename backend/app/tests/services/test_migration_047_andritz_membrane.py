"""P3 tests for migration ``047_andritz_membrane_spec``.

Covers the pure helper logic (effective-policy layering, spec build, chat-System
detection, revision-id length) and an end-to-end upgrade/downgrade/idempotency
pass against the real SQLite test schema (the migration's ``op.get_bind`` is
pointed at the test session connection).
"""
from __future__ import annotations

import importlib.util
import sys
import types
import uuid
from pathlib import Path

from app.models.policy import ControlPolicy
from app.models.system import System
from app.models.workspace import Workspace
from app.services.membrane.spec import MembraneSpec, resolve_membrane_spec


def _load_migration():
    """Load the migration module by path.

    The repo's local ``backend/alembic`` directory is a namespace package that
    shadows the installed ``alembic`` distribution when ``backend`` is on
    ``sys.path`` (as it is under pytest), so ``from alembic import op`` would
    fail at import time. We temporarily stub ``alembic.op`` for the load — the
    DB-backed tests monkeypatch ``mod.op`` with the real session bind anyway,
    and the pure-function tests never touch ``op``.
    """
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "047_andritz_membrane_spec.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace(get_bind=lambda: None)
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_047", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return mod


MIG = _load_migration()


# ---------------------------------------------------------------------------
# Revision metadata — the 046 lesson: id must fit alembic_version.version_num
# ---------------------------------------------------------------------------
def test_revision_id_is_short() -> None:
    assert MIG.revision == "047_andritz_membrane"
    assert len(MIG.revision) <= 32
    assert MIG.down_revision == "046_andritz_voice_overrides"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def test_effective_source_policy_system_shadows_workspace() -> None:
    ws = {"source_policy": {"expert_review_required": True, "industrial_grounding": True}}
    sys_settings = {"source_policy": {"expert_review_required": False}}
    eff = MIG._effective_source_policy(ws, sys_settings, {})
    # System level wins for the key it sets…
    assert eff["expert_review_required"] is False
    # …while the workspace fills the keys the System leaves unset.
    assert eff["industrial_grounding"] is True


def test_effective_source_policy_falls_back_to_flow() -> None:
    ws = {"source_policy": {"require_citations": True}}
    sys_flow = {"source_policy": {"reject_cross_project_sources": True}}
    eff = MIG._effective_source_policy(ws, {}, sys_flow)
    assert eff["require_citations"] is True
    assert eff["reject_cross_project_sources"] is True


def test_is_workspace_chat_system_detection() -> None:
    assert MIG._is_workspace_chat_system({"system_type": "workspace_chat"}, {}, "x") is True
    assert MIG._is_workspace_chat_system({}, {"variant": "chat_transverse_v1"}, "x") is True
    assert MIG._is_workspace_chat_system({}, {}, "Andritz Workspace Chat") is True
    assert MIG._is_workspace_chat_system({}, {}, "Some Other System") is False


def test_build_membrane_spec_reflects_effective_and_round_trips() -> None:
    effective = {
        "industrial_grounding": True,
        "reject_cross_project_sources": True,
        "preserve_reference_types": True,
        "require_citations": True,
        "expert_review_required": False,
        "expert_fiche_correction_enabled": True,
    }
    voice_loop = {"silence_ms": 900, "min_speech_ms": 350, "max_turn_ms": 25000}
    spec_dict = MIG._build_membrane_spec(effective, voice_loop)

    # Parses back through the runtime typed spec, authoritative + faithful.
    parsed = MembraneSpec.from_dict(spec_dict)
    assert parsed.inbound.industrial_grounding is True
    assert parsed.inbound.reject_cross_project_sources is True
    assert parsed.inbound.preserve_reference_types is True
    assert parsed.provenance.require_citations is True
    assert parsed.provenance.object_store_prefix == "membrane/andritz/"
    assert parsed.outbound.expert_review_required is False
    assert parsed.valves.circuit_breaker == voice_loop
    # Enforcement-inert by default — no hard caps / hard-abort.
    assert parsed.valves.hard_abort is False
    assert parsed.valves.max_latency_ms is None

    # And a ControlPolicy carrying it resolves as authoritative.
    control = types.SimpleNamespace(extra={"membrane_spec": spec_dict})
    resolved = resolve_membrane_spec(control=control)
    assert resolved.authoritative is True
    assert resolved.outbound.expert_review_required is False


def test_build_membrane_spec_handles_empty_voice_loop() -> None:
    spec = MembraneSpec.from_dict(MIG._build_membrane_spec({}, {}))
    assert spec.valves.circuit_breaker is None
    assert spec.outbound.expert_review_required is True  # default when unset


# ---------------------------------------------------------------------------
# End-to-end upgrade / idempotency / downgrade against the real schema
# ---------------------------------------------------------------------------
def _seed_andritz(db) -> tuple[str, str]:
    ws = Workspace(
        id=str(uuid.uuid4()),
        name="Andritz",
        slug="andritz",
        settings={
            "source_policy": {
                "industrial_grounding": True,
                "reject_cross_project_sources": True,
                "preserve_reference_types": True,
                "require_citations": True,
                "expert_review_required": False,
                "expert_fiche_correction_enabled": True,
            },
            "voice_loop": {"silence_ms": 900, "min_speech_ms": 350, "max_turn_ms": 25000},
        },
    )
    db.add(ws)
    db.flush()
    chat = System(
        id=str(uuid.uuid4()),
        name="Andritz Workspace Chat",
        objective="chat",
        workspace_id=ws.id,
        settings={"system_type": "workspace_chat", "source_policy": {}},
        flow_definition={"variant": "chat_transverse_v1"},
    )
    db.add(chat)
    db.commit()
    return ws.id, chat.id


def test_upgrade_seeds_membrane_idempotent_then_downgrade(db_session, monkeypatch):
    ws_id, chat_id = _seed_andritz(db_session)
    conn = db_session.connection()
    monkeypatch.setattr(MIG, "op", types.SimpleNamespace(get_bind=lambda: conn))

    # --- upgrade -----------------------------------------------------------
    MIG.upgrade()
    db_session.expire_all()
    policies = (
        db_session.query(ControlPolicy)
        .filter(ControlPolicy.scope == "system", ControlPolicy.target_id == chat_id)
        .all()
    )
    assert len(policies) == 1
    policy = policies[0]
    spec = (policy.extra or {}).get("membrane_spec")
    assert spec is not None
    parsed = MembraneSpec.from_dict(spec)
    assert parsed.inbound.industrial_grounding is True
    assert parsed.outbound.expert_review_required is False
    assert parsed.valves.circuit_breaker == {"silence_ms": 900, "min_speech_ms": 350, "max_turn_ms": 25000}

    chat = db_session.query(System).filter(System.id == chat_id).first()
    assert chat.control_policy_id == policy.id

    # --- idempotency: re-running creates no second row --------------------
    MIG.upgrade()
    db_session.expire_all()
    again = (
        db_session.query(ControlPolicy)
        .filter(ControlPolicy.scope == "system", ControlPolicy.target_id == chat_id)
        .all()
    )
    assert len(again) == 1
    assert again[0].id == policy.id

    # --- downgrade: removes the seeded row + detaches the System ----------
    MIG.downgrade()
    db_session.expire_all()
    assert (
        db_session.query(ControlPolicy)
        .filter(ControlPolicy.scope == "system", ControlPolicy.target_id == chat_id)
        .count()
        == 0
    )
    chat = db_session.query(System).filter(System.id == chat_id).first()
    assert chat.control_policy_id is None


def test_upgrade_ignores_non_andritz(db_session, monkeypatch):
    other = Workspace(id=str(uuid.uuid4()), name="Other", slug="other-co", settings={})
    db_session.add(other)
    db_session.flush()
    sys_row = System(
        id=str(uuid.uuid4()),
        name="Other Workspace Chat",
        objective="chat",
        workspace_id=other.id,
        settings={"system_type": "workspace_chat"},
        flow_definition={},
    )
    db_session.add(sys_row)
    db_session.commit()

    conn = db_session.connection()
    monkeypatch.setattr(MIG, "op", types.SimpleNamespace(get_bind=lambda: conn))
    MIG.upgrade()
    db_session.expire_all()
    # Non-Andritz workspace gets no membrane policy and no binding.
    assert (
        db_session.query(ControlPolicy)
        .filter(ControlPolicy.target_id == sys_row.id)
        .count()
        == 0
    )
    assert db_session.query(System).filter(System.id == sys_row.id).first().control_policy_id is None
