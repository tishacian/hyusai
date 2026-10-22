"""Business policy changes retain evidence, human authority and concurrency guards."""

import copy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.models.audit import AuditLog
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.ecommerce import claims, policy_settings
from app.services.ecommerce.resolution_policy import ResolutionPolicy, resolve_policy, same_proposal
from app.tests.services.test_ecommerce_claims import case


def configured(**changes):
    policy = resolve_policy(case(1043)[2]).model_dump()
    policy.update(changes)
    return ResolutionPolicy.model_validate(policy)


def test_alternate_document_currency_and_manager_threshold_control_the_proposal():
    snapshot, evidence, config = case(1043)
    policy = configured(
        document_key="returns-2027",
        document_version="7",
        document_sha256="b" * 64,
        currency="USD",
        manager_approval_above="20",
    )
    config["resolution_policy"] = policy.model_dump()
    snapshot["data"]["context"][0]["currency"] = "USD"
    for document in snapshot["data"]["documents"]:
        if document["document_key"] == "refund-policy-v2":
            document.update(
                document_key=policy.document_key,
                version=policy.document_version,
                sha256=policy.document_sha256,
            )
    for passage in evidence[0]["results"]:
        if passage["reference"] == "refund-policy-v2":
            passage["reference"] = policy.document_key
    proposal = claims.propose(snapshot, evidence, config)
    assert (proposal["action"], proposal["currency"], proposal["amount"]) == (
        "refund",
        "USD",
        "49.90",
    )
    assert proposal["requires_sav_manager"] is True
    assert proposal["requires_human"] is True and proposal["financial_execution"] == "simulated"
    assert proposal["resolution_policy"]["sha256"] == policy.sha256


def test_explicit_policy_requires_its_actual_document_revision_and_matching_currency():
    snapshot, evidence, config = case(1043)
    config["resolution_policy"] = configured(document_version="9").model_dump()
    with pytest.raises(ValueError, match="CLAIM_POLICY_REVISION_INVALID"):
        claims.propose(snapshot, evidence, config)
    config["resolution_policy"] = configured(currency="USD").model_dump()
    with pytest.raises(ValueError, match="CLAIM_CURRENCY_UNSUPPORTED"):
        claims.propose(snapshot, evidence, config)


@pytest.mark.parametrize(
    "change",
    [
        {"manager_approval_above": "NaN"},
        {"manager_approval_above": "-1"},
        {"manager_approval_above": "1e9"},
        {"manager_approval_above": 300},
        {"manager_approval_above": "1.001"},
        {"document_sha256": "wrong"},
        {"document_version": "2\n"},
        {"currency": "eur"},
        {"auto_approve": True},
        {"financial_execution": "live"},
    ],
)
def test_invalid_or_authority_changing_policy_fields_are_rejected(change):
    with pytest.raises(ValidationError):
        configured(**change)


def test_legacy_proposal_only_survives_the_unchanged_legacy_contract():
    snapshot, evidence, config = case(1043)
    current = claims.propose(snapshot, evidence, config)
    old = {key: value for key, value in current.items() if key != "resolution_policy"}
    assert same_proposal(old, current, config)
    # Explicitly saving the same settings must not invalidate an old approval.
    config["resolution_policy"] = resolve_policy(config).model_dump()
    assert same_proposal(old, claims.propose(snapshot, evidence, config), config)
    config["resolution_policy"]["manager_approval_above"] = "100.00"
    changed = claims.propose(snapshot, evidence, config)
    assert changed["amount"] == old["amount"]
    assert not same_proposal(old, changed, config)
    assert not same_proposal(current, changed, config)


@pytest.fixture()
def policy_workspace(db_session, monkeypatch):
    snapshot, evidence, config = case(1043)
    config.update(allowed_claim_ids=["RC-1043"], allowed_collection_slugs=["rules"])
    workspace = Workspace(
        id="policy-workspace",
        slug="policy-workspace",
        name="Policy",
        settings={"features": {"ecommerce_claims_v1": True}, "ecommerce_claims": config},
    )
    user = User(id="policy-admin", username="policy-admin", email="policy@example.invalid")
    db_session.add_all([workspace, user])
    db_session.flush()
    member = WorkspaceMember(
        workspace_id=workspace.id, user_id=user.id, role="admin", role_template="workspace_admin"
    )
    db_session.add(member)
    db_session.commit()
    snapshot_reader = Mock(return_value=snapshot)
    monkeypatch.setattr(policy_settings.pg, "snapshot", snapshot_reader)
    sources_reader = Mock(
        return_value=[
            (r, SimpleNamespace(id="source"), SimpleNamespace(slug="rules"))
            for r in snapshot["data"]["documents"]
        ]
    )
    monkeypatch.setattr(claims, "_sources", sources_reader)
    return workspace, user, member, snapshot_reader, sources_reader


def test_policy_write_reloads_contract_and_audits_in_the_same_transaction(
    db_session, policy_workspace
):
    workspace, user, _, snapshot_reader, sources_reader = policy_workspace
    initial = policy_settings.read(db_session, workspace, user)
    assert initial["source"] == "legacy_defaults" and initial["revision"] == 0
    changed = configured(manager_approval_above="25")
    result = policy_settings.update(db_session, workspace, user, changed, initial["sha256"])
    assert result["revision"] == 1 and result["sha256"] == changed.sha256
    assert result["invariants"]["human_approval_required"] is True
    assert result["invariants"]["financial_execution"] == "simulated"
    snapshot_reader.assert_called_once()
    sources_reader.assert_called_once()
    audit = (
        db_session.query(AuditLog).filter_by(event_type="claims.resolution_policy.updated").one()
    )
    assert audit.actor == user.id and audit.details["after_sha256"] == changed.sha256
    db_session.rollback()
    assert policy_settings.read(db_session, workspace, user)["sha256"] == initial["sha256"]
    assert (
        db_session.query(AuditLog).filter_by(event_type="claims.resolution_policy.updated").count()
        == 0
    )


def test_stale_editor_cannot_overwrite_a_new_policy(db_session, policy_workspace):
    workspace, user, _, snapshot_reader, _ = policy_workspace
    initial = policy_settings.read(db_session, workspace, user)
    first = policy_settings.update(
        db_session, workspace, user, configured(manager_approval_above="25"), initial["sha256"]
    )
    db_session.commit()
    with pytest.raises(policy_settings.PolicySettingsError, match="CLAIM_POLICY_CONFLICT"):
        policy_settings.update(
            db_session, workspace, user, configured(manager_approval_above="10"), initial["sha256"]
        )
    assert snapshot_reader.call_count == 1
    assert policy_settings.read(db_session, workspace, user)["sha256"] == first["sha256"]


def test_readable_policy_does_not_give_a_reviewer_write_authority(db_session, policy_workspace):
    workspace, user, member, snapshot_reader, _ = policy_workspace
    member.role_template = "workspace_reviewer"
    db_session.commit()
    current = policy_settings.read(db_session, workspace, user)
    assert current["can_configure"] is False
    with pytest.raises(policy_settings.PolicySettingsError, match="CLAIM_POLICY_ADMIN_REQUIRED"):
        policy_settings.update(db_session, workspace, user, configured(), current["sha256"])
    snapshot_reader.assert_not_called()


def test_policy_document_must_be_current_and_authorized(db_session, policy_workspace):
    workspace, user, _, _, sources_reader = policy_workspace
    initial = policy_settings.read(db_session, workspace, user)
    with pytest.raises(
        policy_settings.PolicySettingsError, match="CLAIM_POLICY_DOCUMENT_UNAVAILABLE"
    ):
        policy_settings.update(
            db_session, workspace, user, configured(document_version="99"), initial["sha256"]
        )
    sources_reader.return_value = []
    with pytest.raises(
        policy_settings.PolicySettingsError, match="CLAIM_POLICY_DOCUMENT_UNAVAILABLE"
    ):
        policy_settings.update(db_session, workspace, user, configured(), initial["sha256"])
    assert (
        db_session.query(AuditLog).filter_by(event_type="claims.resolution_policy.updated").count()
        == 0
    )


def test_changed_source_scope_during_document_check_cannot_be_saved(db_session, policy_workspace):
    workspace, user, _, snapshot_reader, _ = policy_workspace
    initial = policy_settings.read(db_session, workspace, user)
    snapshot = snapshot_reader.return_value

    def mutate_scope(*_):
        settings = copy.deepcopy(workspace.settings)
        settings["ecommerce_claims"]["allowed_collection_slugs"] = ["different"]
        workspace.settings = settings
        db_session.flush()
        return snapshot

    snapshot_reader.side_effect = mutate_scope
    with pytest.raises(policy_settings.PolicySettingsError, match="CLAIM_POLICY_CONFLICT"):
        policy_settings.update(db_session, workspace, user, configured(), initial["sha256"])


def test_changed_policy_is_rechecked_before_a_new_simulated_receipt(
    db_session, policy_workspace, monkeypatch
):
    from app.models.claim_action import ClaimAction
    from app.models.run import Run

    workspace, user, _, _, _ = policy_workspace
    proposal = claims.propose(*case(1043))
    run = Run(id="policy-stale-run", workspace_id=workspace.id, initiated_by_user_id=user.id)
    db_session.add(run)
    settings = copy.deepcopy(workspace.settings)
    settings["ecommerce_claims"]["resolution_policy"] = configured(
        manager_approval_above="20"
    ).model_dump()
    workspace.settings = settings
    db_session.commit()
    approval = Mock()
    monkeypatch.setattr(claims, "_approved_human", approval)
    with pytest.raises(ValueError, match="CLAIM_PROPOSAL_CHANGED"):
        claims._simulate(db_session, workspace, run, {}, "RC-1043", proposal)
    approval.assert_not_called()
    assert db_session.query(ClaimAction).count() == 0


def test_permission_revoked_during_document_check_prevents_policy_write(
    db_session, policy_workspace
):
    workspace, user, member, snapshot_reader, _ = policy_workspace
    initial = policy_settings.read(db_session, workspace, user)
    snapshot = snapshot_reader.return_value

    def revoke(*_):
        member.role_template = "workspace_reviewer"
        db_session.flush()
        return snapshot

    snapshot_reader.side_effect = revoke
    with pytest.raises(policy_settings.PolicySettingsError, match="CLAIM_POLICY_ADMIN_REQUIRED"):
        policy_settings.update(db_session, workspace, user, configured(), initial["sha256"])
    assert (
        db_session.query(AuditLog).filter_by(event_type="claims.resolution_policy.updated").count()
        == 0
    )


def test_identical_explicit_save_does_not_create_another_revision(db_session, policy_workspace):
    workspace, user, *_ = policy_workspace
    initial = policy_settings.read(db_session, workspace, user)
    first = policy_settings.update(db_session, workspace, user, configured(), initial["sha256"])
    db_session.commit()
    repeated = policy_settings.update(db_session, workspace, user, configured(), first["sha256"])
    assert repeated["source"] == "workspace" and repeated["revision"] == first["revision"] == 1
    assert repeated["sha256"] == initial["sha256"]
    assert (
        db_session.query(AuditLog).filter_by(event_type="claims.resolution_policy.updated").count()
        == 1
    )
