"""Governance across role, transaction, credential and retention boundaries."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.ml_governance import MLAdmissionCounter
from app.models.tabular import MLModel, MLPrediction
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services import ml_permissions, ml_promotion, tabular_predict
from app.services.ml_governance import admit, policy, purge_predictions
from app.services.tabular_datasets import TabularError


@pytest.fixture()
def subject(db_session, monkeypatch):
    monkeypatch.setattr(settings, "ml_rbac_enforced", True)
    ws = Workspace(name="ML governance", slug="ml-gov-" + uuid4().hex, settings={})
    user = User(
        id=str(uuid4()),
        username=uuid4().hex,
        email=uuid4().hex + "@example.invalid",
        role="user",
        is_active=True,
    )
    db_session.add_all([ws, user])
    db_session.flush()
    member = WorkspaceMember(
        workspace_id=ws.id, user_id=user.id, role="admin", role_template="workspace_admin"
    )
    model = MLModel(
        workspace_id=ws.id,
        name="A",
        slug="a",
        version=1,
        task="regression",
        algo="ridge",
        target="y",
        status="ready",
        features=["x"],
    )
    db_session.add_all([member, model])
    db_session.commit()
    return ws, user, member, model


@pytest.mark.parametrize("role", sorted(ml_permissions.READ))
@pytest.mark.parametrize("action", sorted(ml_permissions.ACTIONS))
def test_role_matrix(db_session, subject, role, action):
    ws, user, member, _ = subject
    member.role_template = role
    db_session.commit()
    expected = role in ml_permissions.ACTIONS[action]
    assert ml_permissions.allowed(db_session, action, ws, user) is expected
    if expected:
        ml_permissions.require(db_session, action, ws, user)
    else:
        with pytest.raises(TabularError, match="ML_FORBIDDEN_ACTION"):
            ml_permissions.require(db_session, action, ws, user)


def test_report_mode_never_grants_membership_or_reactivates_user(db_session, subject, monkeypatch):
    ws, user, member, _ = subject
    monkeypatch.setattr(settings, "ml_rbac_enforced", False)
    user.is_active = False
    db_session.commit()
    with pytest.raises(TabularError):
        ml_permissions.require(db_session, "keys", ws, user)
    user.is_active = True
    db_session.delete(member)
    db_session.commit()
    with pytest.raises(TabularError):
        ml_permissions.require(db_session, "keys", ws, user)


def test_forged_run_context_refused(db_session, subject):
    ws, user, _, _ = subject
    with pytest.raises(TabularError):
        ml_permissions.require_context(
            db_session, "train", ws.id, {"run_id": str(uuid4()), "user_id": user.id}
        )


def test_key_expiry_network_pin_rotation(db_session, subject):
    _, user, _, model = subject
    key, secret = tabular_predict.mint_api_key(
        db_session,
        model=model,
        created_by=user.id,
        allowed_cidrs=["192.0.2.0/24"],
        pinned_version=1,
    )
    assert secret not in str(key.__dict__)
    with pytest.raises(TabularError, match="ML_KEY_NETWORK_DENIED"):
        tabular_predict.authenticate_key(db_session, secret, client_ip="198.51.100.1")
    assert (
        tabular_predict.authenticate_key(db_session, secret, client_ip="192.0.2.3")[
            0
        ].pinned_version
        == 1
    )
    _, new = tabular_predict.mint_api_key(
        db_session, model=model, rotate_key_id=key.id, overlap_hours=0
    )
    with pytest.raises(TabularError, match="ML_API_KEY_EXPIRED"):
        tabular_predict.authenticate_key(db_session, secret, client_ip="192.0.2.3")
    assert tabular_predict.authenticate_key(db_session, new)[1].id == model.id
    key.expires_at = datetime.utcnow() - timedelta(seconds=1)
    key.revoke_after = None
    db_session.commit()
    with pytest.raises(TabularError, match="ML_API_KEY_EXPIRED"):
        tabular_predict.authenticate_key(db_session, secret, client_ip="192.0.2.3")


def test_exposure_counts_lineages(db_session, subject, monkeypatch):
    ws, _, _, model = subject
    monkeypatch.setattr(settings, "ml_max_exposed_models", 1)
    tabular_predict.mint_api_key(db_session, model=model)
    sibling = MLModel(
        workspace_id=ws.id,
        name="v2",
        slug="a",
        version=2,
        task="regression",
        algo="ridge",
        target="y",
        status="ready",
    )
    other = MLModel(
        workspace_id=ws.id,
        name="B",
        slug="b",
        version=1,
        task="regression",
        algo="ridge",
        target="y",
        status="ready",
    )
    db_session.add_all([sibling, other])
    db_session.commit()
    tabular_predict.mint_api_key(db_session, model=sibling)
    with pytest.raises(TabularError, match="ML_EXPOSURE_QUOTA_EXCEEDED"):
        tabular_predict.mint_api_key(db_session, model=other)


def test_parallel_sessions_share_exact_budget(db_session, subject, monkeypatch):
    _, _, _, model = subject
    monkeypatch.setattr(settings, "ml_predict_rate_per_minute", 7)
    factory = sessionmaker(bind=db_session.get_bind())
    identifier = model.id
    now = datetime(2026, 10, 15, 12, 0, 5)

    def invoke(_):
        with factory() as db:
            try:
                admit(db, db.get(MLModel, identifier), rows=2, key_id="one-key", now=now)
                return "ok"
            except TabularError as exc:
                assert exc.status_code == 429 and exc.details["retry_after"] == 55
                return "limited"

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(invoke, range(18)))
    assert results.count("ok") == 7
    counters = db_session.query(MLAdmissionCounter).all()
    assert len(counters) == 2 and {(r.requests, r.rows) for r in counters} == {(7, 14)}


def test_partial_reservation_rolls_back(db_session, subject, monkeypatch):
    _, _, _, model = subject
    monkeypatch.setattr(settings, "ml_predict_rate_per_minute", 2)
    now = datetime(2026, 10, 15, 12, 0, 5)
    admit(db_session, model, rows=1, key_id="a", now=now)
    admit(db_session, model, rows=1, key_id="b", now=now)

    def state():
        return [
            (r.scope, r.requests, r.rows)
            for r in db_session.query(MLAdmissionCounter).order_by(MLAdmissionCounter.scope)
        ]

    before = state()
    with pytest.raises(TabularError):
        admit(db_session, model, rows=1, key_id="c", now=now)
    assert state() == before


def test_no_storage_means_no_input_feedback_or_shadow(db_session, subject):
    from app.services.tabular_monitoring import attach_feedback

    ws, user, _, model = subject
    identifier = tabular_predict.journal_call(
        db_session,
        requested=model,
        served=model,
        caller="session",
        rows=[{"x": "private-input"}],
        answers=[{"prediction": 1.0}],
        duration_ms=2,
        store=False,
    )
    row = db_session.get(MLPrediction, identifier)
    assert (
        row.payload_json == []
        and row.input_storage_allowed is False
        and row.output_json == [{"prediction": 1.0}]
    )
    with pytest.raises(TabularError, match="ML_FEEDBACK_NOT_STORED"):
        attach_feedback(
            db_session, model=model, prediction_id=row.id, label="1", labeled_by=user.id
        )
    ws.settings = {"ml": {"store_inputs": False}}
    db_session.commit()
    identifier = tabular_predict.journal_call(
        db_session,
        requested=model,
        served=model,
        caller="flow",
        rows=[{"x": 4}],
        answers=[{"prediction": 1}],
        duration_ms=1,
    )
    assert db_session.get(MLPrediction, identifier).payload_json == []


@pytest.mark.parametrize("workspace_blocks_storage", [False, True])
def test_no_storage_removes_echoed_explanation_values_without_changing_response(
    db_session, subject, monkeypatch, workspace_blocks_storage
):
    import json
    from copy import deepcopy

    from app.models.workspace_job import WorkspaceJob
    from app.services import ml_shadow

    workspace, _, _, model = subject
    if workspace_blocks_storage:
        workspace.settings = {"ml": {"store_inputs": False}}
        db_session.commit()
    sentinel = "caller-only-sensitive-sentinel"
    answers = [
        {
            "prediction": 1.0,
            "contributions": [
                {"field": "x", "value": {"nested": [sentinel]}, "typical": 0, "effect": 0.5},
            ],
        }
    ]
    original = deepcopy(answers)
    staged = []
    monkeypatch.setattr(ml_shadow, "stage", lambda *args, **kwargs: staged.append(kwargs))
    identifier = tabular_predict.journal_call(
        db_session,
        requested=model,
        served=model,
        caller="session",
        rows=[{"x": sentinel}],
        answers=answers,
        duration_ms=1,
        dataset_id="caller-dataset",
        store=workspace_blocks_storage,
    )
    row = db_session.get(MLPrediction, identifier)
    persisted = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    assert sentinel not in json.dumps(persisted, default=str)
    assert row.input_storage_allowed is False and row.dataset_id is None
    assert row.output_json == [
        {
            "prediction": 1.0,
            "contributions": [
                {"field": "x", "typical": 0, "effect": 0.5},
            ],
        }
    ]
    assert answers == original
    assert staged == []
    assert (
        db_session.query(WorkspaceJob)
        .filter_by(workspace_id=workspace.id, kind="ml_shadow")
        .count()
        == 0
    )


def test_retention_deletes_expired_only(db_session, subject):
    _, _, _, model = subject
    ids = [
        tabular_predict.journal_call(
            db_session,
            requested=model,
            served=model,
            caller="session",
            rows=[{"x": 2}],
            answers=[{"prediction": 1}],
            duration_ms=1,
        )
        for _ in range(2)
    ]
    db_session.get(MLPrediction, ids[0]).created_at = datetime.utcnow() - timedelta(days=31)
    db_session.commit()
    assert purge_predictions(db_session) == 1 and db_session.get(MLPrediction, ids[1]) is not None


def test_promotion_binds_reviewer_artifact_and_audit(db_session, subject):
    ws, user, _, model = subject
    ws.settings = {"ml": {"promotion_requires_approval": True}}
    db_session.commit()
    _, requested = ml_promotion.request(db_session, model=model, workspace=ws, user=user)
    with pytest.raises(TabularError, match="ML_PROMOTION_SECOND_REVIEWER"):
        ml_promotion.decide(
            db_session, workspace=ws, user=user, decision_id=requested["id"], approve=True
        )
    reviewer = User(
        id=str(uuid4()),
        username=uuid4().hex,
        email=uuid4().hex + "@example.invalid",
        role="user",
        is_active=True,
    )
    db_session.add(reviewer)
    db_session.flush()
    db_session.add(
        WorkspaceMember(
            workspace_id=ws.id,
            user_id=reviewer.id,
            role="member",
            role_template="workspace_reviewer",
        )
    )
    db_session.commit()
    model.model_uri = "changed"
    db_session.commit()
    with pytest.raises(TabularError, match="ML_PROMOTION_STALE"):
        ml_promotion.decide(
            db_session, workspace=ws, user=reviewer, decision_id=requested["id"], approve=True
        )
    result = ml_promotion.decide(
        db_session, workspace=ws, user=reviewer, decision_id=requested["id"], approve=False
    )
    assert result["status"] == "rejected"
    assert {r.event_type for r in db_session.query(AuditLog)} >= {
        "ml.model.promotion_requested",
        "ml.model.promotion_rejected",
    }


def test_workspace_cannot_raise_platform_budget(db_session, subject, monkeypatch):
    ws, _, _, _ = subject
    monkeypatch.setattr(settings, "ml_predict_rate_per_minute", 7)
    ws.settings = {"ml": {"predict_requests_per_minute": 99999}}
    db_session.commit()
    assert policy(db_session, ws.id).predict_requests_per_minute == 7


def test_new_portability_actions_never_use_report_mode(db_session, subject, monkeypatch):
    ws, user, member, _ = subject
    member.role_template = "workspace_contributor"
    db_session.commit()
    monkeypatch.setattr(settings, "ml_rbac_enforced", False)
    for action in ("export", "import"):
        with pytest.raises(TabularError, match="ML_FORBIDDEN_ACTION"):
            ml_permissions.require(db_session, action, ws, user)


def test_promotion_changes_champion_once_with_second_reviewer(db_session, subject):
    ws, user, _, model = subject
    ws.settings = {"ml": {"promotion_requires_approval": True}}
    reviewer = User(
        id=str(uuid4()),
        username=uuid4().hex,
        email=uuid4().hex + "@example.invalid",
        role="user",
        is_active=True,
    )
    db_session.add(reviewer)
    db_session.flush()
    db_session.add(
        WorkspaceMember(
            workspace_id=ws.id,
            user_id=reviewer.id,
            role="member",
            role_template="workspace_reviewer",
        )
    )
    db_session.commit()
    _, requested = ml_promotion.request(db_session, model=model, workspace=ws, user=user)
    assert (
        ml_promotion.decide(
            db_session, workspace=ws, user=reviewer, decision_id=requested["id"], approve=True
        )["status"]
        == "applied"
    )
    db_session.refresh(model)
    assert model.is_champion
    with pytest.raises(TabularError, match="ML_PROMOTION_STALE"):
        ml_promotion.decide(
            db_session, workspace=ws, user=reviewer, decision_id=requested["id"], approve=True
        )
    assert (
        db_session.query(AuditLog).filter_by(event_type="ml.model.promotion_approved").count() == 1
    )


def test_run_without_initiator_cannot_borrow_context_identity(db_session, subject):
    from app.models.run import Run

    ws, user, _, _ = subject
    run = Run(workspace_id=ws.id)
    db_session.add(run)
    db_session.commit()
    with pytest.raises(TabularError, match="ML_FORBIDDEN_ACTION"):
        ml_permissions.require_context(
            db_session, "train", ws.id, {"run_id": run.id, "user_id": user.id}
        )


def test_delegated_ml_uses_persisted_authority_and_still_enforces_role(
    db_session, subject, monkeypatch
):
    from app.models.run import Run
    from app.services.run_engine import execution_principal

    ws, user, member, _ = subject
    run = Run(workspace_id=ws.id, initiated_by_user_id=None)
    run.execution_principal = {"kind": "delegated_user", "user_id": user.id}
    db_session.add(run)
    db_session.commit()
    monkeypatch.setattr(execution_principal, "execution_user_id", lambda db, current: user.id)
    ctx = {"run_id": run.id, "user_id": "caller-cannot-choose"}
    assert ml_permissions.require_context(db_session, "score", ws.id, ctx).id == user.id
    assert run.initiated_by_user_id is None
    member.role_template = "workspace_viewer"
    db_session.commit()
    with pytest.raises(TabularError, match="ML_FORBIDDEN_ACTION"):
        ml_permissions.require_context(db_session, "score", ws.id, ctx)


def test_revoked_ml_delegation_never_borrows_initiator(db_session, subject, monkeypatch):
    from app.models.run import Run
    from app.services.run_engine import execution_principal

    ws, user, _, _ = subject
    run = Run(workspace_id=ws.id, initiated_by_user_id=user.id)
    run.execution_principal = {"kind": "delegated_user", "user_id": "revoked"}
    db_session.add(run)
    db_session.commit()

    def deny(db, current):
        raise execution_principal.ExecutionPrincipalError("EXECUTION_PRINCIPAL_REVOKED")

    monkeypatch.setattr(execution_principal, "execution_user_id", deny)
    with pytest.raises(TabularError, match="EXECUTION_PRINCIPAL_REVOKED"):
        ml_permissions.require_context(
            db_session, "score", ws.id, {"run_id": run.id, "user_id": user.id}
        )
