"""Focused round-trip tests for migration 059's rollout contract."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from copy import deepcopy
from pathlib import Path

import pytest
import sqlalchemy as sa


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "059_andritz_agentic_default.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace(get_bind=lambda: None)
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_059", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return module


MIG = _load_migration()


def _schema(bind):
    metadata = sa.MetaData()
    workspaces = sa.Table(
        "workspaces",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("settings", sa.JSON(), nullable=True),
    )
    systems = sa.Table(
        "systems",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("flow_definition", sa.JSON(), nullable=False),
        sa.Column("execution_profile", sa.JSON(), nullable=True),
        sa.Column("control_policy_id", sa.String(36), nullable=True),
    )
    control_policies = sa.Table(
        "control_policies",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=False),
    )
    metadata.create_all(bind)
    return workspaces, systems, control_policies


def _valid_flow() -> dict:
    return deepcopy(
        json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "resources"
                / "flows"
                / "andritz_chat_agentic_v3.json"
            ).read_text(encoding="utf-8")
        )["flow_definition"]
    )


def test_frozen_migration_contract_rejects_missing_governance_spine():
    settings = {
        "system_type": MIG.AGENTIC_SYSTEM_TYPE,
        "flow_revision": MIG.EXPECTED_FLOW_REVISION,
    }
    flow = _valid_flow()
    assert MIG._is_expected_agentic_flow(settings, flow) is True

    permuted = deepcopy(flow)
    draft_index = next(
        index
        for index, edge in enumerate(permuted["edges"])
        if edge.get("from") == "task.generate" and edge.get("to") == "join.answer"
    )
    corrected_index = next(
        index
        for index, edge in enumerate(permuted["edges"])
        if edge.get("from") == "task.self_correct" and edge.get("to") == "join.answer"
    )
    permuted["edges"][draft_index], permuted["edges"][corrected_index] = (
        permuted["edges"][corrected_index],
        permuted["edges"][draft_index],
    )
    assert MIG._is_expected_agentic_flow(settings, permuted) is False

    removed = {
        "task.response_eval",
        "decision.verdict",
        "task.self_correct",
        "join.answer",
        "decision.egress_gate",
        "hitl.expert_review",
        "decision.deliver",
        "sink.final_answer",
    }
    flow["nodes"] = [node for node in flow["nodes"] if node.get("id") not in removed]
    flow["edges"] = [
        edge
        for edge in flow["edges"]
        if edge.get("from") not in removed and edge.get("to") not in removed
    ]

    assert MIG._is_expected_agentic_flow(settings, flow) is False


def _agentic_system(*, system_id: str, workspace_id: str) -> dict:
    return {
        "id": system_id,
        "workspace_id": workspace_id,
        "status": "active",
        "settings": {
            "system_type": MIG.AGENTIC_SYSTEM_TYPE,
            "flow_revision": MIG.EXPECTED_FLOW_REVISION,
            "unrelated": {"keep": True},
        },
        "flow_definition": _valid_flow(),
        "execution_profile": {"latency_target_ms": 2500, "max_runtime_s": 55},
        "control_policy_id": f"policy-{system_id}",
    }


def test_upgrade_recognizes_the_persisted_056_flow_artifact():
    flow_artifact = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "resources"
            / "flows"
            / "andritz_chat_agentic_v3.json"
        ).read_text(encoding="utf-8")
    )["flow_definition"]
    system = _agentic_system(system_id="sys-056", workspace_id="ws-andritz")
    system["flow_definition"] = flow_artifact
    assert MIG._is_expected_agentic_flow(system["settings"], flow_artifact) is True

    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        workspaces, systems, control_policies = _schema(bind)
        bind.execute(
            workspaces.insert().values(
                id="ws-andritz",
                settings={"family": "andritz"},
            )
        )
        bind.execute(systems.insert().values(**system))
        bind.execute(
            control_policies.insert().values(
                **_control_policy(system_id="sys-056", workspace_id="ws-andritz")
            )
        )

        MIG._apply_andritz_defaults(bind)

        workspace_settings = bind.execute(sa.select(workspaces.c.settings)).scalar_one()
        marker = workspace_settings[MIG.MIGRATION_MARKER_KEY]
        assert marker["system_id"] == "sys-056"
        assert marker["applied"]["flow_revision"] == MIG.EXPECTED_FLOW_REVISION


def _control_policy(*, system_id: str, workspace_id: str, allowlist=None) -> dict:
    return {
        "id": f"policy-{system_id}",
        "workspace_id": workspace_id,
        "scope": "system",
        "target_id": system_id,
        "extra": {
            "keep_extra": True,
            "membrane_spec": {
                "version": 1,
                "inbound": {
                    "collection_allowlist": list(allowlist or []),
                    "reject_cross_project_sources": True,
                },
                "outbound": {"expert_review_required": False},
            },
        },
    }


def test_upgrade_rollout_25_downgrade_preserves_membrane_and_unrelated_changes():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        workspaces, systems, control_policies = _schema(bind)
        previous_policy = {"version": 7, "mode": "classic"}
        previous_contract = {"collection": "legacy", "allow_workspace_fallback": True}
        bind.execute(
            workspaces.insert(),
            [
                {
                    "id": "ws-andritz",
                    "settings": {
                        "family": "andritz",
                        "branding": {"name": "Andritz"},
                        "chat_execution": previous_policy,
                    },
                },
                {
                    "id": "ws-generic",
                    "settings": {"family": "generic", "keep": "untouched"},
                },
                {"id": "ws-legacy-null", "settings": None},
            ],
        )
        target = _agentic_system(system_id="sys-agentic", workspace_id="ws-andritz")
        target["settings"]["retrieval_contract"] = previous_contract
        bind.execute(
            systems.insert(),
            [
                target,
                {
                    **_agentic_system(
                        system_id="sys-generic",
                        workspace_id="ws-generic",
                    ),
                },
            ],
        )
        bind.execute(
            control_policies.insert(),
            [
                _control_policy(
                    system_id="sys-agentic",
                    workspace_id="ws-andritz",
                    allowlist=["legacy"],
                ),
                _control_policy(
                    system_id="sys-generic",
                    workspace_id="ws-generic",
                    allowlist=["generic"],
                ),
            ],
        )

        MIG._apply_andritz_defaults(bind)

        upgraded_workspace = bind.execute(
            sa.select(workspaces.c.settings).where(workspaces.c.id == "ws-andritz")
        ).scalar_one()
        assert upgraded_workspace["chat_execution"] == MIG.CHAT_EXECUTION_POLICY
        assert upgraded_workspace["chat_execution"]["rollout"]["percentage"] == 0
        assert MIG.MIGRATION_MARKER_KEY in upgraded_workspace

        upgraded_system = bind.execute(
            sa.select(systems.c.settings, systems.c.execution_profile).where(
                systems.c.id == "sys-agentic"
            )
        ).one()
        assert upgraded_system.settings["retrieval_contract"] == MIG.RETRIEVAL_CONTRACT
        assert upgraded_system.execution_profile["max_runtime_s"] == 40
        upgraded_policy = bind.execute(
            sa.select(control_policies.c.extra).where(control_policies.c.id == "policy-sys-agentic")
        ).scalar_one()
        assert upgraded_policy["membrane_spec"]["inbound"]["collection_allowlist"] == [
            MIG.NOTICES_COLLECTION
        ]

        # Simulate unrelated configuration written after the migration.  A
        # field-level downgrade must retain it.  The staged rollout percentage
        # is expected to change operationally and must not make rollback fail.
        later_workspace = deepcopy(upgraded_workspace)
        later_workspace["chat_execution"]["rollout"]["percentage"] = 25
        later_workspace["future_workspace_setting"] = "keep"
        later_system = deepcopy(upgraded_system.settings)
        later_system["future_system_setting"] = "keep"
        later_profile = deepcopy(upgraded_system.execution_profile)
        later_profile["future_runtime_setting"] = "keep"
        later_policy = deepcopy(upgraded_policy)
        later_policy["future_policy_setting"] = "keep"
        later_policy["membrane_spec"]["inbound"]["future_inbound_setting"] = "keep"
        bind.execute(
            sa.update(workspaces)
            .where(workspaces.c.id == "ws-andritz")
            .values(settings=later_workspace)
        )
        bind.execute(
            sa.update(systems)
            .where(systems.c.id == "sys-agentic")
            .values(settings=later_system, execution_profile=later_profile)
        )
        bind.execute(
            sa.update(control_policies)
            .where(control_policies.c.id == "policy-sys-agentic")
            .values(extra=later_policy)
        )

        MIG._restore_andritz_defaults(bind)

        restored_workspace = bind.execute(
            sa.select(workspaces.c.settings).where(workspaces.c.id == "ws-andritz")
        ).scalar_one()
        assert restored_workspace["chat_execution"] == previous_policy
        assert restored_workspace["future_workspace_setting"] == "keep"
        assert restored_workspace["branding"] == {"name": "Andritz"}
        assert MIG.MIGRATION_MARKER_KEY not in restored_workspace

        restored_system = bind.execute(
            sa.select(systems.c.settings, systems.c.execution_profile).where(
                systems.c.id == "sys-agentic"
            )
        ).one()
        assert restored_system.settings["retrieval_contract"] == previous_contract
        assert restored_system.settings["future_system_setting"] == "keep"
        assert restored_system.execution_profile["max_runtime_s"] == 55
        assert restored_system.execution_profile["future_runtime_setting"] == "keep"
        restored_policy = bind.execute(
            sa.select(control_policies.c.extra).where(control_policies.c.id == "policy-sys-agentic")
        ).scalar_one()
        assert restored_policy["membrane_spec"]["inbound"]["collection_allowlist"] == ["legacy"]
        assert restored_policy["future_policy_setting"] == "keep"
        assert restored_policy["membrane_spec"]["inbound"]["future_inbound_setting"] == "keep"

        generic_workspace = bind.execute(
            sa.select(workspaces.c.settings).where(workspaces.c.id == "ws-generic")
        ).scalar_one()
        assert generic_workspace == {"family": "generic", "keep": "untouched"}
        assert (
            bind.execute(
                sa.select(workspaces.c.settings).where(workspaces.c.id == "ws-legacy-null")
            ).scalar_one()
            is None
        )


def test_family_without_target_is_left_on_classic_and_ambiguous_target_fails_closed():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        workspaces, systems, control_policies = _schema(bind)
        bind.execute(
            workspaces.insert(),
            [
                {"id": "ws-empty", "settings": {"family": "andritz", "keep": True}},
                {"id": "ws-dupe", "settings": {"family": "andritz"}},
            ],
        )
        bind.execute(
            systems.insert(),
            [
                _agentic_system(system_id="sys-a", workspace_id="ws-dupe"),
                _agentic_system(system_id="sys-b", workspace_id="ws-dupe"),
            ],
        )
        bind.execute(
            control_policies.insert(),
            [
                _control_policy(system_id="sys-a", workspace_id="ws-dupe"),
                _control_policy(system_id="sys-b", workspace_id="ws-dupe"),
            ],
        )

        with pytest.raises(RuntimeError, match="multiple active canonical"):
            MIG._apply_andritz_defaults(bind)

        empty_settings = bind.execute(
            sa.select(workspaces.c.settings).where(workspaces.c.id == "ws-empty")
        ).scalar_one()
        assert empty_settings == {"family": "andritz", "keep": True}


def test_downgrade_refuses_to_overwrite_changed_owned_policy():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        workspaces, systems, control_policies = _schema(bind)
        bind.execute(workspaces.insert().values(id="ws", settings={"family": "andritz"}))
        bind.execute(systems.insert().values(**_agentic_system(system_id="sys", workspace_id="ws")))
        bind.execute(
            control_policies.insert().values(**_control_policy(system_id="sys", workspace_id="ws"))
        )
        MIG._apply_andritz_defaults(bind)

        settings = bind.execute(sa.select(workspaces.c.settings)).scalar_one()
        settings["chat_execution"]["mode"] = "classic"
        bind.execute(sa.update(workspaces).values(settings=settings))

        with pytest.raises(RuntimeError, match="policy changed"):
            MIG._restore_andritz_defaults(bind)


def test_upgrade_refuses_cross_workspace_control_policy_binding():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        workspaces, systems, control_policies = _schema(bind)
        bind.execute(
            workspaces.insert(),
            [
                {"id": "ws-andritz", "settings": {"family": "andritz"}},
                {"id": "ws-other", "settings": {"family": "generic"}},
            ],
        )
        bind.execute(
            systems.insert().values(
                **_agentic_system(
                    system_id="sys-agentic",
                    workspace_id="ws-andritz",
                )
            )
        )
        bind.execute(
            control_policies.insert().values(
                **_control_policy(
                    system_id="sys-agentic",
                    workspace_id="ws-other",
                )
            )
        )

        with pytest.raises(RuntimeError, match="not an authoritative policy"):
            MIG._apply_andritz_defaults(bind)


@pytest.mark.parametrize("operation", ["rerun", "downgrade"])
@pytest.mark.parametrize("drift", ["workspace", "variant"])
def test_marker_refuses_system_tenant_or_identity_drift(operation, drift):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        workspaces, systems, control_policies = _schema(bind)
        bind.execute(
            workspaces.insert(),
            [
                {"id": "ws-andritz", "settings": {"family": "andritz"}},
                {"id": "ws-other", "settings": {"family": "generic"}},
            ],
        )
        bind.execute(
            systems.insert().values(
                **_agentic_system(system_id="sys-agentic", workspace_id="ws-andritz")
            )
        )
        bind.execute(
            control_policies.insert().values(
                **_control_policy(system_id="sys-agentic", workspace_id="ws-andritz")
            )
        )
        MIG._apply_andritz_defaults(bind)

        if drift == "workspace":
            bind.execute(
                sa.update(systems)
                .where(systems.c.id == "sys-agentic")
                .values(workspace_id="ws-other")
            )
            expected = "workspace"
        else:
            bind.execute(
                sa.update(systems)
                .where(systems.c.id == "sys-agentic")
                .values(flow_definition={"variant": "shadow_variant"})
            )
            expected = "canonical identity"

        action = (
            MIG._apply_andritz_defaults if operation == "rerun" else MIG._restore_andritz_defaults
        )
        with pytest.raises(RuntimeError, match=expected):
            action(bind)
