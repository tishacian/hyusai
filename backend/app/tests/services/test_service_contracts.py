"""Real database transitions for assets, service deadlines and human publication."""

from datetime import datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import service_contracts as api
from app.core.config import settings
from app.models.run import Run
from app.models.service_contract import DeliveryReceipt, ServiceIncident
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services import governed_assets as assets
from app.services import service_promises as services
from app.services.object_store import get_object_store

NOW = datetime(2026, 10, 13, 9)


@pytest.fixture()
def setup(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    workspace = Workspace(
        id=str(uuid4()),
        name="Service test",
        slug=f"service-{uuid4().hex}",
        settings={"features": {"service_contracts": True}},
    )
    owner = User(id=str(uuid4()), username=f"owner-{uuid4().hex}")
    member = User(id=str(uuid4()), username=f"member-{uuid4().hex}")
    foreign = Workspace(id=str(uuid4()), name="Foreign", slug=f"foreign-{uuid4().hex}")
    db_session.add_all([workspace, foreign, owner, member])
    db_session.flush()
    db_session.add_all(
        [
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=owner.id,
                role="owner",
                role_template="workspace_owner",
            ),
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=member.id,
                role="member",
                role_template="workspace_contributor",
            ),
        ]
    )
    system = System(workspace_id=workspace.id, name="Delivery", status="active")
    db_session.add(system)
    db_session.commit()
    return SimpleNamespace(
        db=db_session,
        workspace=workspace,
        foreign=foreign,
        owner=owner,
        member=member,
        system=system,
    )


def asset(s, *, text="verified evidence", name="result", workspace_id=None, run_id=None):
    workspace_id = workspace_id or s.workspace.id
    raw = text.encode()
    key = f"workspaces/{workspace_id}/test/{uuid4().hex}.txt"
    get_object_store().write_bytes(key, raw)
    manifest = {
        "objects": [{"key": key, "sha256": sha256(raw).hexdigest(), "size_bytes": len(raw)}],
        "output": {"value": text},
        "evidence": [
            {"id": "source-1", "text": text, "sha256": sha256(raw).hexdigest(), "kind": "text"}
        ],
    }
    return assets.register_asset(s.db, workspace_id, "reference", name, manifest, run_id=run_id)


def contract(s, **overrides):
    definition = {"starts_on": "2026-10-13", "deadline": "17:00", **overrides}
    row = services.create_contract(
        s.db, s.workspace.id, s.system.id, s.owner.id, definition, created_by=s.owner.id
    )
    services.publish_contract(s.db, s.workspace.id, row.id, user_id=s.owner.id, now=NOW)
    return row


def window(s, **definition):
    row = contract(s, **definition)
    windows = services.tick(s.db, NOW, workspace_id=s.workspace.id)
    return row, windows[0]


def candidate(s, *, qualification=True, confidence=None, **definition):
    c, w = window(s, **definition)
    a = asset(s)
    q = (
        assets.record_qualification(
            s.db,
            s.workspace.id,
            assets.asset_ref(a),
            status="qualified",
            policy={"rubric": "v1"},
            evidence={"measured": True},
            confidence=confidence,
        )
        if qualification
        else None
    )
    attempt = services.claim_window(s.db, s.workspace.id, w.id, worker_id="worker", now=NOW)
    services.complete_attempt(
        s.db,
        s.workspace.id,
        w.id,
        fence=attempt.fence,
        lease_token=attempt.lease_token,
        candidate_ref=assets.asset_ref(a),
        now=NOW + timedelta(seconds=1),
    )
    return c, w, a, q, attempt


def review_snapshot(s, w):
    row = assets.resolve_asset_ref(s.db, s.workspace.id, w.candidate_ref)
    qualification = assets.current_qualification(s.db, s.workspace.id, row.id)
    return {
        "expected_fence": w.fence,
        "expected_asset_digest": row.digest,
        "expected_qualification_digest": qualification.digest if qualification else None,
    }


@pytest.mark.parametrize("changed", ["fence", "asset", "qualification"])
def test_review_rejects_changed_facts_before_creating_decision(setup, changed):
    from app.models.decision import Decision

    s = setup
    _, w, a, _, _ = candidate(s)
    snapshot = review_snapshot(s, w)
    if changed == "fence":
        snapshot["expected_fence"] += 1
    elif changed == "asset":
        snapshot["expected_asset_digest"] = "0" * 64
    else:
        assets.record_qualification(
            s.db,
            s.workspace.id,
            assets.asset_ref(a),
            status="review_required",
            policy={"rubric": "v2"},
            evidence={"new": True},
        )
    before = assets.current_qualification(s.db, s.workspace.id, a.id)
    with pytest.raises(assets.GovernanceError, match="SERVICE_REVIEW_STALE"):
        services.review_delivery(
            s.db,
            s.workspace.id,
            w.id,
            **snapshot,
            reviewer_user_id=s.owner.id,
            accept=True,
            qualify_candidate=True,
            note="Reviewed the displayed evidence",
            now=NOW + timedelta(seconds=2),
        )
    assert assets.current_qualification(s.db, s.workspace.id, a.id).id == before.id
    assert s.db.query(Decision).filter_by(workspace_id=s.workspace.id).count() == 0


def test_asset_versions_are_immutable_and_do_not_copy_native_bytes(setup):
    s = setup
    first = asset(s)
    keys = get_object_store().list_keys(f"workspaces/{s.workspace.id}")
    assert len(keys) == 2  # native object + small immutable manifest
    again = assets.register_asset(
        s.db, s.workspace.id, "reference", first.logical_key, first.manifest_json
    )
    assert again.id == first.id
    second = assets.register_asset(
        s.db,
        s.workspace.id,
        "reference",
        first.logical_key,
        {**first.manifest_json, "note": "new revision"},
        [assets.asset_ref(first)],
    )
    assert second.version == 2
    assert (
        assets.resolve_asset_ref(s.db, s.workspace.id, assets.asset_ref(first)).digest
        == first.digest
    )
    assert first.digest != second.digest
    s.db.commit()
    first.manifest_json = {"tampered": True}
    with pytest.raises(ValueError, match="IMMUTABLE"):
        s.db.flush()
    s.db.rollback()


def test_asset_ref_checks_tenant_version_digest_and_object_bytes(setup):
    s = setup
    row = asset(s)
    for changed in [{"workspace_id": s.foreign.id}, {"version": 99}, {"digest": "0" * 64}]:
        with pytest.raises(assets.GovernanceError):
            assets.resolve_asset_ref(s.db, s.workspace.id, {**assets.asset_ref(row), **changed})
    get_object_store().write_bytes(row.manifest_json["objects"][0]["key"], b"tampered")
    with pytest.raises(assets.GovernanceError, match="ASSET_OBJECT_CHANGED"):
        assets.resolve_asset_ref(s.db, s.workspace.id, assets.asset_ref(row))


def test_native_refs_and_parent_refs_do_not_cross_tenants(setup):
    s = setup
    other = asset(s, workspace_id=s.foreign.id)
    with pytest.raises(assets.GovernanceError, match="ASSET_SCOPE_DENIED"):
        assets.register_asset(
            s.db, s.workspace.id, "reference", "child", {}, [assets.asset_ref(other)]
        )
    with pytest.raises(assets.GovernanceError, match="ASSET_NATIVE_REF_UNAVAILABLE"):
        assets.register_asset(
            s.db,
            s.workspace.id,
            "model",
            "foreign",
            {"native_refs": [{"kind": "model", "id": "missing"}]},
        )
    with pytest.raises(assets.GovernanceError, match="ASSET_OBJECT_SCOPE_DENIED"):
        assets.register_asset(s.db, s.workspace.id, "reference", "evil", other.manifest_json)


def test_qualifications_append_and_invalidation_preserves_history(setup):
    s = setup
    row = asset(s)
    first = assets.record_qualification(
        s.db,
        s.workspace.id,
        assets.asset_ref(row),
        status="qualified",
        policy={"v": 1},
        evidence={"pass": True},
    )
    second = assets.record_qualification(
        s.db,
        s.workspace.id,
        assets.asset_ref(row),
        status="needs_requalification",
        policy={"v": 2},
        evidence={"reason": "policy_changed"},
    )
    assert (first.version, second.version) == (1, 2)
    assert first.status == "qualified"
    assert assets.current_qualification(s.db, s.workspace.id, row.id).id == second.id
    with pytest.raises(assets.GovernanceError, match="ASSET_QUALIFICATION_REQUIRED"):
        assets.validate_qualification(second, row)


def test_contract_owner_system_rbac_and_freezing(setup):
    s = setup
    with pytest.raises(assets.GovernanceError, match="SERVICE_PERMISSION_DENIED"):
        services.create_contract(
            s.db,
            s.workspace.id,
            s.system.id,
            s.owner.id,
            {"starts_on": "2026-10-13"},
            created_by=s.member.id,
        )
    with pytest.raises(assets.GovernanceError, match="SERVICE_PERMISSION_DENIED"):
        services.create_contract(
            s.db,
            s.workspace.id,
            s.system.id,
            "missing",
            {"starts_on": "2026-10-13"},
            created_by=s.owner.id,
        )
    c = contract(s)
    s.db.commit()
    c.definition_json = {**c.definition_json, "deadline": "01:00"}
    with pytest.raises(ValueError, match="IMMUTABLE_SERVICE_CONTRACT"):
        s.db.flush()
    s.db.rollback()


@pytest.mark.parametrize(
    "day,hours,deadline",
    [
        ("2026-03-29", 23, datetime(2026, 3, 29, 1)),
        ("2026-10-25", 25, datetime(2026, 10, 25, 0, 30)),
    ],
)
def test_dst_periods_are_local_dates_and_deadline_is_deterministic(setup, day, hours, deadline):
    s = setup
    contract(s, starts_on=day, ends_on=day, timezone="Europe/Paris", deadline="02:30")
    specs = list(
        services.due_windows(
            s.db, datetime.fromisoformat(day) + timedelta(hours=12), workspace_id=s.workspace.id
        )
    )
    assert len(specs) == 1
    assert (specs[0]["period_end"] - specs[0]["period_start"]).total_seconds() == hours * 3600
    assert specs[0]["deadline_at"] == deadline


def test_scheduler_deduplicates_windows_without_creating_runs(setup):
    s = setup
    contract(s)
    assert len(services.tick(s.db, NOW, workspace_id=s.workspace.id)) == 1
    assert services.tick(s.db, NOW, workspace_id=s.workspace.id) == []
    assert s.db.query(Run).filter_by(workspace_id=s.workspace.id).count() == 0
    incidents = services.watchdog(s.db, NOW + timedelta(hours=9), workspace_id=s.workspace.id)
    assert len(incidents) == 1
    assert incidents[0].code == "SERVICE_RUN_MISSING"
    assert incidents[0].owner_user_id == s.owner.id
    assert services.watchdog(s.db, NOW + timedelta(hours=10), workspace_id=s.workspace.id) == []
    assert s.db.query(ServiceIncident).filter_by(workspace_id=s.workspace.id).count() == 1


def test_fenced_lease_rejects_competing_or_expired_worker(setup):
    s = setup
    _, w = window(s)
    first = services.claim_window(
        s.db, s.workspace.id, w.id, worker_id="first", lease_seconds=10, now=NOW
    )
    with pytest.raises(assets.GovernanceError, match="SERVICE_LEASE_BUSY"):
        services.claim_window(s.db, s.workspace.id, w.id, worker_id="second", now=NOW)
    second = services.claim_window(
        s.db, s.workspace.id, w.id, worker_id="second", now=NOW + timedelta(seconds=11)
    )
    assert second.fence == first.fence + 1
    with pytest.raises(assets.GovernanceError, match="SERVICE_STALE_LEASE"):
        services.complete_attempt(
            s.db,
            s.workspace.id,
            w.id,
            fence=first.fence,
            lease_token=first.lease_token,
            error_code="FAILURE",
            now=NOW + timedelta(seconds=12),
        )


def test_retry_budget_is_cumulative_and_measured_overrun_blocks_publication(setup):
    s = setup
    _, w = window(s, budget={"max_attempts": 3, "max_cost": 5, "max_tokens": 10, "max_seconds": 30})
    first = services.claim_window(
        s.db, s.workspace.id, w.id, worker_id="first", reserve_cost=3, now=NOW
    )
    services.complete_attempt(
        s.db,
        s.workspace.id,
        w.id,
        fence=first.fence,
        lease_token=first.lease_token,
        error_code="FAILURE",
        cost=3,
        now=NOW + timedelta(seconds=1),
    )
    with pytest.raises(assets.GovernanceError, match="SERVICE_BUDGET_EXHAUSTED"):
        services.claim_window(
            s.db,
            s.workspace.id,
            w.id,
            worker_id="second",
            reserve_cost=3,
            now=NOW + timedelta(seconds=2),
        )
    second = services.claim_window(
        s.db,
        s.workspace.id,
        w.id,
        worker_id="second",
        reserve_cost=2,
        now=NOW + timedelta(seconds=2),
    )
    a = asset(s)
    result = services.complete_attempt(
        s.db,
        s.workspace.id,
        w.id,
        fence=second.fence,
        lease_token=second.lease_token,
        candidate_ref=assets.asset_ref(a),
        cost=4,
        now=NOW + timedelta(seconds=3),
    )
    assert result.status == "failed"
    assert result.cost_used == 7  # measured overspend is never hidden/clamped
    assert result.candidate_ref is None


def test_unknown_usage_remains_null_and_reservation_cannot_be_reused(setup):
    s = setup
    _, w = window(s, budget={"max_attempts": 3, "max_cost": 5, "max_tokens": 10, "max_seconds": 30})
    attempt = services.claim_window(
        s.db,
        s.workspace.id,
        w.id,
        worker_id="first",
        reserve_cost=5,
        reserve_tokens=10,
        reserve_seconds=30,
        now=NOW,
    )
    services.complete_attempt(
        s.db,
        s.workspace.id,
        w.id,
        fence=attempt.fence,
        lease_token=attempt.lease_token,
        error_code="PROVIDER_TIMEOUT",
        now=NOW + timedelta(seconds=1),
    )
    s.db.refresh(attempt)
    assert (attempt.actual_cost, attempt.actual_tokens, attempt.actual_seconds) == (
        None,
        None,
        None,
    )
    public = services.window_public(w)
    assert public["cost_used"] == public["reserved_cost"] == 5
    assert public["cost_coverage"] == public["tokens_coverage"] == "unavailable"
    assert public["measured_cost"] is None and public["measured_tokens"] is None
    with pytest.raises(assets.GovernanceError, match="SERVICE_BUDGET_EXHAUSTED"):
        services.claim_window(
            s.db,
            s.workspace.id,
            w.id,
            worker_id="retry",
            reserve_cost=0.01,
            now=NOW + timedelta(seconds=2),
        )


def test_usage_coverage_distinguishes_known_zero_and_partial_measurement(setup):
    s = setup
    _, w = window(s)
    first = services.claim_window(
        s.db, s.workspace.id, w.id, worker_id="first", reserve_cost=2, now=NOW
    )
    services.complete_attempt(
        s.db,
        s.workspace.id,
        w.id,
        fence=first.fence,
        lease_token=first.lease_token,
        error_code="FAILURE",
        cost=0,
        tokens=0,
        seconds=1,
        now=NOW + timedelta(seconds=1),
    )
    public = services.window_public(w)
    assert public["cost_coverage"] == "measured" and public["measured_cost"] == 0
    assert public["cost_used"] == public["reserved_cost"] == 2
    second = services.claim_window(
        s.db,
        s.workspace.id,
        w.id,
        worker_id="second",
        reserve_cost=2,
        now=NOW + timedelta(seconds=2),
    )
    services.complete_attempt(
        s.db,
        s.workspace.id,
        w.id,
        fence=second.fence,
        lease_token=second.lease_token,
        error_code="FAILURE",
        seconds=2,
        now=NOW + timedelta(seconds=3),
    )
    public = services.window_public(w)
    assert public["cost_coverage"] == public["tokens_coverage"] == "partial"
    assert public["measured_cost"] == 0
    assert public["cost_used"] == public["reserved_cost"] == 4
    assert public["seconds_coverage"] == "measured" and public["measured_seconds"] == 3


def test_publication_needs_current_qualification_and_real_human(setup):
    s = setup
    _, w, a, _, attempt = candidate(s, qualification=False)
    with pytest.raises(assets.GovernanceError, match="ASSET_QUALIFICATION_REQUIRED"):
        services.review_delivery(
            s.db,
            s.workspace.id,
            w.id,
            **review_snapshot(s, w),
            reviewer_user_id=s.owner.id,
            accept=True,
            now=NOW + timedelta(seconds=2),
        )
    assets.record_qualification(
        s.db, s.workspace.id, assets.asset_ref(a), status="qualified", policy={}, evidence={}
    )
    with pytest.raises(assets.GovernanceError, match="SERVICE_PERMISSION_DENIED"):
        services.review_delivery(
            s.db,
            s.workspace.id,
            w.id,
            **review_snapshot(s, w),
            reviewer_user_id="synthetic-admin",
            accept=True,
            now=NOW,
        )
    with pytest.raises(assets.GovernanceError, match="SERVICE_DECISION_REQUIRED"):
        services.publish_delivery(
            s.db,
            s.workspace.id,
            w.id,
            decision_id="none",
            fence=attempt.fence,
            lease_token=attempt.lease_token,
            now=NOW + timedelta(seconds=2),
        )


def test_delivery_receipt_is_idempotent_and_decision_bound(setup):
    s = setup
    _, w, a, q, attempt = candidate(s)
    decision = services.review_delivery(
        s.db,
        s.workspace.id,
        w.id,
        **review_snapshot(s, w),
        reviewer_user_id=s.owner.id,
        accept=True,
        now=NOW + timedelta(seconds=2),
    )
    assert decision.human_confirmed_by == s.owner.id
    kwargs = {
        "decision_id": decision.id,
        "fence": attempt.fence,
        "lease_token": attempt.lease_token,
        "now": NOW + timedelta(seconds=3),
    }
    first = services.publish_delivery(s.db, s.workspace.id, w.id, **kwargs)
    second = services.publish_delivery(s.db, s.workspace.id, w.id, **kwargs)
    assert first.id == second.id
    assert w.status == "delivered"
    assert s.db.query(DeliveryReceipt).filter_by(window_id=w.id).count() == 1
    assert services.get_receipt(s.db, s.workspace.id, first.id, user_id=s.member.id).id == first.id
    with pytest.raises(assets.GovernanceError):
        services.get_receipt(s.db, s.foreign.id, first.id, user_id=s.member.id)


def test_requalification_invalidates_old_review_and_delivered_consumption(setup):
    s = setup
    _, w, a, q, attempt = candidate(s)
    decision = services.review_delivery(
        s.db,
        s.workspace.id,
        w.id,
        **review_snapshot(s, w),
        reviewer_user_id=s.owner.id,
        accept=True,
        now=NOW + timedelta(seconds=2),
    )
    assets.record_qualification(
        s.db,
        s.workspace.id,
        assets.asset_ref(a),
        status="qualified",
        policy={"rubric": "v2"},
        evidence={"measured": True},
    )
    with pytest.raises(assets.GovernanceError, match="SERVICE_DECISION_REQUIRED"):
        services.publish_delivery(
            s.db,
            s.workspace.id,
            w.id,
            decision_id=decision.id,
            fence=attempt.fence,
            lease_token=attempt.lease_token,
            now=NOW + timedelta(seconds=3),
        )
    assert q.policy_json == {"rubric": "v1"}


def test_unknown_confidence_never_autoapproves_even_when_human_policy_optional(setup):
    s = setup
    _, w, _, _, _ = candidate(
        s, output_policy={"require_human_review": False, "min_confidence": 0.8}
    )
    with pytest.raises(assets.GovernanceError, match="SERVICE_HUMAN_REVIEW_REQUIRED"):
        services.automatic_delivery_decision(s.db, s.workspace.id, w.id, now=NOW)


def test_schema_mismatch_blocks_human_review_and_external_schema_refs_rejected(setup):
    s = setup
    _, w, _, _, _ = candidate(s, output_schema={"type": "object", "required": ["missing"]})
    with pytest.raises(assets.GovernanceError, match="SERVICE_OUTPUT_SCHEMA_MISMATCH"):
        services.review_delivery(
            s.db,
            s.workspace.id,
            w.id,
            **review_snapshot(s, w),
            reviewer_user_id=s.owner.id,
            accept=True,
            now=NOW,
        )
    with pytest.raises(assets.GovernanceError, match="SERVICE_DEFINITION_INVALID"):
        contract(s, output_schema={"$ref": "http://169.254.169.254/schema"})


def test_authorize_judge_evidence_checks_actual_persisted_text(setup):
    s = setup
    run = Run(workspace_id=s.workspace.id, system_id=s.system.id, initiated_by_user_id=s.owner.id)
    s.db.add(run)
    s.db.flush()
    a = asset(s, run_id=run.id)
    s.db.commit()  # authorization callback uses its own real session
    item = {**a.manifest_json["evidence"][0], "asset_ref": assets.asset_ref(a)}
    context = {"workspace_id": s.workspace.id, "run_id": run.id, "user_id": s.owner.id}
    assert assets.authorize_judge_evidence([item], context) == {item["id"]: item["sha256"]}
    forged = {**item, "text": "forged", "sha256": sha256(b"forged").hexdigest()}
    with pytest.raises(assets.GovernanceError, match="JUDGE_EVIDENCE_HASH_MISMATCH"):
        assets.authorize_judge_evidence([forged], context)


def test_api_rbac_owner_incidents_and_tenant_scope(setup):
    s = setup
    c, w = window(s)
    services.watchdog(s.db, NOW + timedelta(hours=9), workspace_id=s.workspace.id)
    s.db.commit()
    app = FastAPI()
    app.include_router(api.router, prefix="/service-contracts")
    app.dependency_overrides[api.get_db] = lambda: s.db
    app.dependency_overrides[api.get_current_workspace] = lambda: s.workspace
    app.dependency_overrides[api.get_current_user] = lambda: s.member
    client = TestClient(app)
    assert client.get("/service-contracts").json()["total"] == 1
    assert client.get("/service-contracts/incidents").json()["items"] == []
    assert client.post(f"/service-contracts/{c.id}/publish").status_code == 403
    assert "lease_token" not in client.get("/service-contracts/windows").text
    app.dependency_overrides[api.get_current_user] = lambda: s.owner
    assert len(client.get("/service-contracts/incidents").json()["items"]) == 1
    app.dependency_overrides[api.get_current_workspace] = lambda: s.foreign
    assert client.get(f"/service-contracts/{c.id}").status_code in {403, 404}


def test_human_can_explicitly_qualify_review_and_publish_without_llm(setup):
    s = setup
    _, w, a, _, attempt = candidate(s, qualification=False)
    decision = services.review_delivery(
        s.db,
        s.workspace.id,
        w.id,
        **review_snapshot(s, w),
        reviewer_user_id=s.owner.id,
        accept=True,
        qualify_candidate=True,
        note="Verified the source and the output manually.",
        now=NOW + timedelta(seconds=2),
    )
    qualification = assets.current_qualification(s.db, s.workspace.id, a.id)
    assert qualification.status == "qualified"
    assert qualification.confidence is None
    assert qualification.evidence_json["reviewer_user_id"] == s.owner.id
    assert qualification.evidence_json["coverage_measured"] is False
    receipt = services.publish_delivery(
        s.db,
        s.workspace.id,
        w.id,
        decision_id=decision.id,
        fence=attempt.fence,
        lease_token=attempt.lease_token,
        now=NOW + timedelta(seconds=3),
    )
    assert receipt.asset_digest == a.digest


def test_human_qualification_requires_note_and_cannot_override_rejected_asset(setup):
    s = setup
    _, w, a, _, _ = candidate(s, qualification=False)
    with pytest.raises(assets.GovernanceError, match="SERVICE_HUMAN_QUALIFICATION_NOTE_REQUIRED"):
        services.review_delivery(
            s.db,
            s.workspace.id,
            w.id,
            **review_snapshot(s, w),
            reviewer_user_id=s.owner.id,
            accept=True,
            qualify_candidate=True,
            now=NOW,
        )
    assets.record_qualification(
        s.db,
        s.workspace.id,
        assets.asset_ref(a),
        status="rejected",
        policy={},
        evidence={"failed": True},
    )
    with pytest.raises(assets.GovernanceError, match="SERVICE_REJECTED_ASSET_REQUIRES_NEW_VERSION"):
        services.review_delivery(
            s.db,
            s.workspace.id,
            w.id,
            **review_snapshot(s, w),
            reviewer_user_id=s.owner.id,
            accept=True,
            qualify_candidate=True,
            note="I checked",
            now=NOW,
        )


@pytest.mark.parametrize(
    "output",
    [
        {"technical_status": "failed"},
        {"technical_status": "incomplete"},
        {
            "technical_status": "completed",
            "coverage": {"expected": 10, "processed": 9, "failed": 1},
        },
        {"coverage": {"expected": 0, "processed": 0, "failed": 0}},
    ],
)
def test_human_cannot_override_incomplete_technical_output(setup, output):
    s = setup
    _, w = window(s)
    a = assets.register_asset(s.db, s.workspace.id, "reference", "incomplete", {"output": output})
    attempt = services.claim_window(s.db, s.workspace.id, w.id, worker_id="worker", now=NOW)
    services.complete_attempt(
        s.db,
        s.workspace.id,
        w.id,
        fence=attempt.fence,
        lease_token=attempt.lease_token,
        candidate_ref=assets.asset_ref(a),
        now=NOW + timedelta(seconds=1),
    )
    with pytest.raises(
        assets.GovernanceError, match="SERVICE_(TECHNICAL_OUTPUT|COVERAGE)_INCOMPLETE"
    ):
        services.review_delivery(
            s.db,
            s.workspace.id,
            w.id,
            **review_snapshot(s, w),
            reviewer_user_id=s.owner.id,
            accept=True,
            qualify_candidate=True,
            note="Reviewed",
            now=NOW + timedelta(seconds=2),
        )


def test_receipt_consumption_closes_after_requalification(setup):
    s = setup
    _, w, a, _, attempt = candidate(s)
    decision = services.review_delivery(
        s.db,
        s.workspace.id,
        w.id,
        **review_snapshot(s, w),
        reviewer_user_id=s.owner.id,
        accept=True,
        now=NOW + timedelta(seconds=2),
    )
    receipt = services.publish_delivery(
        s.db,
        s.workspace.id,
        w.id,
        decision_id=decision.id,
        fence=attempt.fence,
        lease_token=attempt.lease_token,
        now=NOW + timedelta(seconds=3),
    )
    assets.record_qualification(
        s.db,
        s.workspace.id,
        assets.asset_ref(a),
        status="needs_requalification",
        policy={"version": 2},
        evidence={},
    )
    with pytest.raises(assets.GovernanceError, match="ASSET_QUALIFICATION_REQUIRED"):
        services.get_receipt(s.db, s.workspace.id, receipt.id, user_id=s.owner.id)
    listing = services.list_receipts(s.db, s.workspace.id, user_id=s.owner.id)
    assert listing["items"][0]["available"] is False
    assert receipt.published_at == NOW + timedelta(seconds=3)


def test_concurrent_claims_have_one_winner(setup):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.db.base import SessionLocal

    s = setup
    _, w = window(s)
    s.db.commit()
    workspace_id, window_id = s.workspace.id, w.id
    start = Barrier(2)

    def claim(worker):
        with SessionLocal() as db:
            start.wait(timeout=5)
            try:
                row = services.claim_window(db, workspace_id, window_id, worker_id=worker, now=NOW)
                identifier = row.id
                db.commit()
                return identifier
            except assets.GovernanceError as exc:
                db.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ["first", "second"]))
    assert sum(value in {"SERVICE_LEASE_BUSY", "SERVICE_STALE_LEASE"} for value in results) == 1
    s.db.refresh(w)
    assert w.fence == 1
    assert w.attempts == 1


def test_additive_migration_upgrade_and_downgrade_match_models():
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    from app.models.service_contract import (
        AssetQualification,
        AssetVersion,
        DeliveryReceipt,
        ServiceAttempt,
        ServiceContract,
        ServiceIncident,
        ServiceWindow,
    )

    path = Path(__file__).parents[3] / "alembic" / "versions" / "126_service_contracts.py"
    spec = importlib.util.spec_from_file_location("migration_126", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "125_retrieval_bench_runs"
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        inspector = inspect(connection)
        for model in (
            AssetVersion,
            AssetQualification,
            ServiceContract,
            ServiceWindow,
            ServiceAttempt,
            DeliveryReceipt,
            ServiceIncident,
        ):
            assert {column["name"] for column in inspector.get_columns(model.__tablename__)} == {
                column.name for column in model.__table__.columns
            }
        migration.downgrade()
        assert inspect(connection).get_table_names() == []


def test_candidate_endpoint_exposes_reviewable_output_without_lease(setup):
    s = setup
    _, w, a, q, _ = candidate(s)
    s.db.commit()
    app = FastAPI()
    app.include_router(api.router, prefix="/service-contracts")
    app.dependency_overrides[api.get_db] = lambda: s.db
    app.dependency_overrides[api.get_current_workspace] = lambda: s.workspace
    app.dependency_overrides[api.get_current_user] = lambda: s.owner
    response = TestClient(app).get(f"/service-contracts/windows/{w.id}/candidate")
    assert response.status_code == 200
    assert response.json()["manifest"]["output"]["value"] == "verified evidence"
    assert response.json()["qualification"]["id"] == q.id
    assert "lease_token" not in response.text
