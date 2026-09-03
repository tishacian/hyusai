"""Focused contract tests for workspace-owned chat execution routing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models.system import System
from app.models.workspace import Workspace
from app.services import chat_execution_policy as policy


def _policy(
    mode: str = policy.CHAT_EXECUTION_AGENTIC_DEFAULT,
    *,
    percentage: float = 100.0,
    system_type: str = policy.AGENTIC_SYSTEM_TYPE,
    variant: str = policy.AGENTIC_VARIANT,
) -> dict:
    return {
        "version": 3,
        "mode": mode,
        "target": {"system_type": system_type, "variant": variant},
        "fallback": "classic",
        "rollout": {"percentage": percentage, "salt": "andritz-agentic-v1"},
    }


def _workspace(db_session, *, workspace_id: str = "ws-policy", settings: dict | None = None):
    workspace = Workspace(
        id=workspace_id,
        name=workspace_id,
        slug=workspace_id,
        settings=settings if settings is not None else {"chat_execution": _policy()},
    )
    db_session.add(workspace)
    db_session.flush()
    return workspace


def _system(
    db_session,
    workspace: Workspace,
    *,
    system_id: str = "sys-agentic",
    system_type: str = policy.AGENTIC_SYSTEM_TYPE,
    variant: str = policy.AGENTIC_VARIANT,
    status: str = "active",
) -> System:
    system = System(
        id=system_id,
        workspace_id=workspace.id,
        name=system_id,
        objective="Execute the Agentic chat graph",
        settings={"system_type": system_type, "flow_revision": "chat-agentic-r1"},
        flow_definition={"variant": variant},
        status=status,
    )
    db_session.add(system)
    db_session.flush()
    return system


@pytest.fixture(autouse=True)
def _agentic_master_switch_on(monkeypatch):
    monkeypatch.setattr(policy.settings, "enable_agentic_chat", True)


def _resolve(db_session, workspace, **overrides):
    kwargs = {
        "requested_system_id": None,
        "session_id": "session-1",
        "answer_profile": "precise_fact",
        "context_id": None,
        "rag_mode_override": None,
    }
    kwargs.update(overrides)
    return policy.resolve_chat_execution(db_session, workspace=workspace, **kwargs)


def test_modes_apply_their_distinct_routing_contract(db_session):
    workspace = _workspace(db_session)
    target = _system(db_session, workspace)

    workspace.settings = {"chat_execution": _policy(policy.CHAT_EXECUTION_CLASSIC)}
    classic = _resolve(db_session, workspace, answer_profile="comparison")
    assert classic.route == "classic"
    assert classic.reason == "policy_classic"
    assert classic.executor_system.id == target.id

    workspace.settings = {"chat_execution": _policy(policy.CHAT_EXECUTION_HYBRID)}
    ordinary_hybrid = _resolve(db_session, workspace, answer_profile="precise_fact")
    niche_hybrid = _resolve(db_session, workspace, answer_profile="comparison")
    assert (ordinary_hybrid.route, ordinary_hybrid.reason) == (
        "classic",
        "hybrid_profile_classic",
    )
    assert (niche_hybrid.route, niche_hybrid.reason) == (
        "agentic",
        "policy_hybrid",
    )

    workspace.settings = {"chat_execution": _policy(policy.CHAT_EXECUTION_AGENTIC_DEFAULT)}
    agentic_default = _resolve(db_session, workspace, answer_profile="precise_fact")
    assert (agentic_default.route, agentic_default.reason) == (
        "agentic",
        "policy_agentic_default",
    )
    assert agentic_default.is_agentic is True


def test_generic_workspace_zero_percent_hybrid_stays_classic(db_session):
    workspace = _workspace(
        db_session,
        workspace_id="ws-acme",
        settings={
            "family": "generic",
            "chat_execution": _policy(policy.CHAT_EXECUTION_HYBRID, percentage=0),
        },
    )
    _system(db_session, workspace)
    decision = _resolve(db_session, workspace, answer_profile="comparison")
    assert decision.route == "classic"
    assert decision.reason == "rollout_cohort_classic"
    assert decision.is_agentic is False


def test_target_selection_requires_exact_active_type_variant_and_workspace(db_session):
    workspace = _workspace(db_session)
    other_workspace = _workspace(db_session, workspace_id="ws-policy-other")
    exact = _system(db_session, workspace, system_id="sys-exact")
    _system(
        db_session,
        workspace,
        system_id="sys-wrong-type",
        system_type="workspace_chat",
    )
    _system(
        db_session,
        workspace,
        system_id="sys-wrong-variant",
        variant="chat_agentic_legacy_v0",
    )
    _system(db_session, workspace, system_id="sys-paused", status="paused")
    _system(db_session, other_workspace, system_id="sys-other-workspace")

    decision = _resolve(db_session, workspace)

    assert decision.route == "agentic"
    assert decision.executor_system.id == exact.id
    assert decision.ledger()["executor_variant"] == policy.AGENTIC_VARIANT
    assert decision.ledger()["flow_revision"] == "chat-agentic-r1"


def test_policy_can_select_an_exact_declared_target_contract(db_session):
    workspace = _workspace(
        db_session,
        settings={
            "chat_execution": _policy(
                system_type="chat_agentic_v2",
                variant="chat_agentic_reasoning_v2",
            )
        },
    )
    declared = _system(
        db_session,
        workspace,
        system_id="sys-declared",
        system_type="chat_agentic_v2",
        variant="chat_agentic_reasoning_v2",
    )
    _system(db_session, workspace, system_id="sys-default-contract")

    decision = _resolve(db_session, workspace)

    assert decision.route == "agentic"
    assert decision.executor_system.id == declared.id


def test_rollout_is_stable_per_session_and_separates_cohorts(db_session):
    workspace = _workspace(
        db_session,
        settings={"chat_execution": _policy(percentage=50)},
    )
    _system(db_session, workspace)
    salt = "andritz-agentic-v1"
    below = next(
        f"session-{index}"
        for index in range(1000)
        if policy._stable_bucket(
            workspace_id=workspace.id,
            cohort_key=f"session-{index}",
            salt=salt,
        )
        < 50
    )
    above = next(
        f"session-{index}"
        for index in range(1000)
        if policy._stable_bucket(
            workspace_id=workspace.id,
            cohort_key=f"session-{index}",
            salt=salt,
        )
        >= 50
    )

    agentic_first = _resolve(db_session, workspace, session_id=below)
    agentic_again = _resolve(db_session, workspace, session_id=below)
    classic_first = _resolve(db_session, workspace, session_id=above)
    classic_again = _resolve(db_session, workspace, session_id=above)

    assert agentic_first.route == agentic_again.route == "agentic"
    assert agentic_first.rollout_bucket == agentic_again.rollout_bucket
    assert classic_first.route == classic_again.route == "classic"
    assert classic_first.reason == classic_again.reason == "rollout_cohort_classic"
    assert classic_first.rollout_bucket == classic_again.rollout_bucket


def test_explicit_agentic_system_is_a_zero_percent_operator_canary(db_session):
    workspace = _workspace(
        db_session,
        settings={"chat_execution": _policy(percentage=0)},
    )
    target = _system(db_session, workspace)

    rollout_decision = _resolve(db_session, workspace)
    forced_decision = _resolve(
        db_session,
        workspace,
        requested_system_id=target.id,
        allow_forced_agentic=True,
    )
    unprivileged_decision = _resolve(
        db_session,
        workspace,
        requested_system_id=target.id,
        allow_forced_agentic=False,
    )

    assert rollout_decision.route == "classic"
    assert rollout_decision.reason == "rollout_cohort_classic"
    assert forced_decision.route == "agentic"
    assert forced_decision.reason == "explicit_agentic_system"
    assert forced_decision.forced is True
    assert forced_decision.rollout_percentage == 0
    assert unprivileged_decision.route == "classic"
    assert unprivileged_decision.reason == "rollout_cohort_classic"


def test_explicit_target_cannot_bypass_missing_policy(db_session):
    workspace = _workspace(db_session, settings={})
    target = _system(db_session, workspace)

    decision = _resolve(
        db_session,
        workspace,
        requested_system_id=target.id,
        allow_forced_agentic=True,
    )

    assert decision.route == "classic"
    assert decision.reason == "policy_missing_or_invalid"


def test_explicit_business_system_never_enters_workspace_agentic_rollout(db_session):
    workspace = _workspace(
        db_session,
        settings={"chat_execution": _policy(percentage=100)},
    )
    _system(db_session, workspace, system_id="sys-agentic")
    business = _system(
        db_session,
        workspace,
        system_id="sys-mission-room",
        system_type="mission_room",
        variant="octocity_mission_room_v1",
    )

    decision = _resolve(
        db_session,
        workspace,
        requested_system_id=business.id,
        allow_forced_agentic=True,
    )

    assert decision.route == "classic"
    assert decision.reason == "explicit_business_system_requires_classic"
    assert decision.executor_system is None


def test_master_switch_overrides_policy_and_explicit_canary(monkeypatch):
    monkeypatch.setattr(policy.settings, "enable_agentic_chat", False)
    workspace = SimpleNamespace(
        id="ws-kill-switch",
        settings={"chat_execution": _policy(percentage=100)},
    )
    db = MagicMock()

    decision = policy.resolve_chat_execution(
        db,
        workspace=workspace,
        requested_system_id="sys-agentic",
        session_id="session-1",
        answer_profile="comparison",
    )

    assert decision.route == "classic"
    assert decision.reason == "master_kill_switch_off"
    assert decision.executor_system is None
    db.query.assert_not_called()


@pytest.mark.parametrize("rag_mode_override", ["hybrid", "chah"])
def test_andritz_rag_algorithm_override_keeps_authoritative_classic_contract(
    monkeypatch,
    rag_mode_override,
):
    """Changing the retrieval algorithm must not change the Andritz corpus."""

    monkeypatch.setattr(policy.settings, "enable_agentic_chat", False)
    workspace = SimpleNamespace(
        id="ws-andritz-rag-override",
        settings={
            "family": "andritz",
            "chat_execution": _policy(percentage=100),
        },
    )
    db = MagicMock()

    decision = policy.resolve_chat_execution(
        db,
        workspace=workspace,
        requested_system_id=None,
        session_id="session-1",
        answer_profile="precise_fact",
        rag_mode_override=rag_mode_override,
    )

    assert decision.route == "classic"
    assert decision.reason == "master_kill_switch_off"
    assert decision.retrieval_contract == policy.ANDRITZ_RETRIEVAL_CONTRACT
    db.query.assert_not_called()


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        ({"context_id": "context-user-selected"}, "explicit_context_requires_classic"),
        (
            {"rag_mode_override": "hybrid"},
            "explicit_rag_override_requires_classic",
        ),
    ],
)
def test_explicit_context_or_rag_contract_keeps_classic(db_session, overrides, expected_reason):
    workspace = _workspace(db_session)
    target = _system(db_session, workspace)

    decision = _resolve(db_session, workspace, **overrides)

    assert decision.route == "classic"
    assert decision.reason == expected_reason
    assert decision.executor_system.id == target.id


def test_missing_and_ambiguous_targets_fail_closed(db_session):
    workspace = _workspace(db_session)

    missing = _resolve(db_session, workspace)
    assert (missing.route, missing.reason) == ("classic", "agentic_target_missing")

    _system(db_session, workspace, system_id="sys-agentic-a")
    _system(db_session, workspace, system_id="sys-agentic-b")
    ambiguous = _resolve(db_session, workspace)
    assert (ambiguous.route, ambiguous.reason) == (
        "classic",
        "agentic_target_ambiguous",
    )
    assert ambiguous.executor_system is None


def test_andritz_contract_drift_keeps_classic_route_on_strict_notices_collection(db_session):
    workspace = _workspace(
        db_session,
        settings={
            "family": "andritz",
            "chat_execution": _policy(percentage=100),
            policy.ANDRITZ_MIGRATION_MARKER: {
                "revision": policy.ANDRITZ_MIGRATION_REVISION,
                "schema": 1,
                "system_id": "sys-agentic",
                "control_policy": {"id": "policy-agentic"},
            },
        },
    )
    # This is selectable by type/variant but intentionally lacks the pinned
    # 056 topology, so the Agentic contract must fail closed.
    _system(db_session, workspace)

    decision = _resolve(db_session, workspace)

    assert decision.route == "classic"
    assert decision.reason == "andritz_agentic_contract_invalid"
    assert decision.retrieval_contract == policy.ANDRITZ_RETRIEVAL_CONTRACT


def test_migration_identity_survives_family_drift_and_fails_agentic_closed(db_session):
    workspace = _workspace(
        db_session,
        settings={
            "family": "generic",
            "chat_execution": _policy(percentage=100),
            policy.ANDRITZ_MIGRATION_MARKER: {
                "revision": policy.ANDRITZ_MIGRATION_REVISION,
                "schema": 1,
                "system_id": "sys-agentic",
                "control_policy": {"id": "policy-agentic"},
            },
        },
    )
    _system(db_session, workspace)

    decision = _resolve(db_session, workspace)

    assert policy.migration_059_system_id(workspace) == "sys-agentic"
    assert decision.route == "classic"
    assert decision.reason == "andritz_agentic_contract_invalid"
    assert decision.retrieval_contract == policy.ANDRITZ_RETRIEVAL_CONTRACT


def test_explicit_andritz_context_is_not_overwritten_by_default_collection(db_session):
    workspace = _workspace(
        db_session,
        settings={
            "family": "andritz",
            "chat_execution": _policy(percentage=100),
            policy.ANDRITZ_MIGRATION_MARKER: {
                "revision": policy.ANDRITZ_MIGRATION_REVISION,
                "schema": 1,
                "system_id": "sys-agentic",
                "control_policy": {"id": "policy-agentic"},
            },
        },
    )
    _system(db_session, workspace)

    decision = _resolve(db_session, workspace, context_id="context-user-selected")

    assert decision.route == "classic"
    assert decision.retrieval_contract is None


@pytest.mark.parametrize(
    "chat_execution",
    [
        None,
        {},
        {"mode": "surprise"},
        {"mode": "agentic_default"},
        _policy(percentage=float("nan")),
        _policy(percentage=float("inf")),
    ],
)
def test_missing_or_invalid_policy_fails_closed_without_explicit_canary(db_session, chat_execution):
    settings = {} if chat_execution is None else {"chat_execution": chat_execution}
    workspace = _workspace(db_session, settings=settings)
    _system(db_session, workspace)

    decision = _resolve(db_session, workspace)

    assert decision.route == "classic"
    assert decision.reason == "policy_missing_or_invalid"
