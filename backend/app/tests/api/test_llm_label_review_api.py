"""The existing HITL authority is the only write path for reviewed labels."""
from uuid import uuid4

import pytest

from app.models.tabular import TabularDataset
from app.services import llm_label_review as review
from app.services.tabular_datasets import read_frame
from app.tests.api.test_runs_hitl_auth import _client, _seed_pending_run, _stub_durable_ordinary_hitl_resume  # noqa: F401
from app.tests.services.test_llm_label_review import review_case, review_body, object_store_root  # noqa: F401


def payload(case, **extra):
    return {"action": "accept", "expected_decision_id": case.decision.id,
            "label_review": review_body(case, [{"row_id": 0, "label": "billing"}]).model_dump(), **extra}


def test_existing_hitl_endpoint_atomically_approves_and_publishes_once(db_session, review_case):
    case = review_case
    client = _client(db_session, case.workspace, case.owner)
    page = client.get(f"/runs/{case.run.id}/label-review", params={
        "expected_decision_id": case.decision.id, "offset": 10, "limit": 2})
    assert page.status_code == 200, page.text
    assert [row["row_id"] for row in page.json()["rows"]] == [10, 11]
    response = client.post(f"/runs/{case.run.id}/hitl", json=payload(case))
    assert response.status_code == 200, response.text
    db_session.refresh(case.decision)
    assert case.decision.status == "accepted"
    assert case.decision.human_confirmed_by == case.owner.id
    output = review.reviewed_output(db_session, case.decision)
    assert read_frame(output)["topic"][0] == "billing"
    assert read_frame(case.source)["topic"][0] == "technical"
    assert review.training_provenance(db_session, output, "topic")["rows_reviewed"] == 48
    repeated = client.post(f"/runs/{case.run.id}/hitl", json=payload(case))
    assert repeated.status_code == 200, repeated.text
    assert db_session.query(TabularDataset).filter_by(produced_by=review.PRODUCER).count() == 1
    assert client.get(f"/runs/{case.run.id}/label-review", params={"expected_decision_id": case.decision.id}).status_code == 409


@pytest.mark.parametrize("change,status", [
    ({"label_review": None}, 409),
    ({"expected_decision_id": "stale-decision"}, 409),
    ({"label_review": {"dataset_id": "wrong", "sha256": "0" * 64, "acknowledged": True}}, 409),
    ({"label_review": {"dataset_id": "wrong", "sha256": "0" * 64, "acknowledged": False}}, 422),
])
def test_missing_confirmation_or_stale_review_cannot_approve(db_session, review_case, change, status):
    case = review_case
    response = _client(db_session, case.workspace, case.owner).post(f"/runs/{case.run.id}/hitl", json=payload(case, **change))
    assert response.status_code == status, response.text
    db_session.refresh(case.decision)
    assert case.decision.status == "proposed"
    assert db_session.query(TabularDataset).filter_by(produced_by=review.PRODUCER).count() == 0


def test_existing_approval_authority_and_workspace_isolation_are_preserved(db_session, review_case):
    case = review_case
    response = _client(db_session, case.workspace, case.other).post(f"/runs/{case.run.id}/hitl", json=payload(case))
    assert response.status_code == 403
    other_workspace, other_owner, *_ = _seed_pending_run(db_session)
    client = _client(db_session, other_workspace, other_owner)
    assert client.get(f"/runs/{case.run.id}/label-review", params={"expected_decision_id": case.decision.id}).status_code == 404
    assert client.post(f"/runs/{case.run.id}/hitl", json=payload(case)).status_code == 404
    db_session.refresh(case.decision)
    assert case.decision.status == "proposed"


def test_rejection_needs_no_review_payload_and_creates_no_dataset(db_session, review_case):
    case = review_case
    response = _client(db_session, case.workspace, case.owner).post(f"/runs/{case.run.id}/hitl", json={
        "action": "reject", "expected_decision_id": case.decision.id})
    assert response.status_code == 200, response.text
    db_session.refresh(case.decision)
    assert case.decision.status == "rejected"
    assert db_session.query(TabularDataset).filter_by(produced_by=review.PRODUCER).count() == 0


def test_retired_source_and_stale_pagination_fail_closed(db_session, review_case):
    case = review_case
    client = _client(db_session, case.workspace, case.owner)
    assert client.get(f"/runs/{case.run.id}/label-review", params={"expected_decision_id": str(uuid4())}).status_code == 409
    case.source.status = "deleted"
    db_session.commit()
    response = client.post(f"/runs/{case.run.id}/hitl", json=payload(case))
    assert response.status_code == 404, response.text
    db_session.refresh(case.decision)
    assert case.decision.status == "proposed"


def test_review_payload_cannot_be_attached_to_an_unrelated_gate(db_session, review_case):
    case = review_case
    case.decision.rationale = {"prompt_kind": "approve_write"}
    db_session.commit()
    response = _client(db_session, case.workspace, case.owner).post(f"/runs/{case.run.id}/hitl", json=payload(case))
    assert response.status_code == 409
    assert case.decision.status == "proposed"
