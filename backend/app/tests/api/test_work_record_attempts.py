"""A Work record keeps every attempt it received; a reader sees their own."""

from types import SimpleNamespace

import pytest

from app.models.run import Run
from app.models.user import User
from app.models.work_record_run import WorkRecordRun
from app.services.experience import bindings as binding_service
from app.tests.api import test_work_api as helpers
from app.tests.api.test_work_latest_action_run import _action_pages

PATH = "/work/password-reset/bindings/work.reset/runs"
RECORDS = "/work/password-reset/records/{ref}/runs"


@pytest.fixture()
def sample(db_session, monkeypatch):
    workspace, user = helpers._seed(db_session)
    system, version, binding = helpers._seed_binding(db_session, workspace, user)
    binding.record_namespace = "search"
    binding.record_input_field = "query"
    db_session.commit()
    studio = helpers._experiences_client(db_session, workspace, user)
    with monkeypatch.context() as patch:
        patch.setattr(helpers, "_pages", _action_pages)
        experience_id, release_id = helpers._publish(studio, binding_key="work.reset")
    client = helpers._client(db_session, workspace, user, monkeypatch)
    return SimpleNamespace(workspace=workspace, user=user, client=client, monkeypatch=monkeypatch)


def _invoke(sample, suffix):
    response = sample.client.post(
        PATH,
        json={"payload": {"query": "prévision"}, "page_id": "home", "component_id": "reset-action"},
        headers={"Idempotency-Key": f"record-attempt-{suffix}-00000001"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_each_invocation_appends_an_attempt_to_its_record(sample, db_session):
    first = _invoke(sample, "one")
    second = _invoke(sample, "two")

    rows = db_session.query(WorkRecordRun).order_by(WorkRecordRun.created_at).all()
    assert [row.run_id for row in rows] == [first, second]
    assert {(row.record_namespace, row.record_ref, row.binding_key) for row in rows} == {
        ("search", "prévision", "work.reset")
    }

    page = sample.client.get(RECORDS.format(ref="prévision"), params={"namespace": "search"})
    assert page.status_code == 200, page.text
    body = page.json()
    assert [attempt["run_id"] for attempt in body["attempts"]] == [second, first]
    assert body["has_more"] is False
    assert body["attempts"][0]["follow_up"]["native_status"] == db_session.get(Run, second).status


def test_a_replayed_request_does_not_add_a_second_attempt(sample, db_session):
    _invoke(sample, "same")
    _invoke(sample, "same")
    assert db_session.query(WorkRecordRun).count() == 1


def test_attempts_are_paginated_newest_first(sample):
    ids = [_invoke(sample, str(n)) for n in range(3)]
    page = sample.client.get(RECORDS.format(ref="prévision"), params={"namespace": "search", "limit": 2}).json()
    rest = sample.client.get(
        RECORDS.format(ref="prévision"), params={"namespace": "search", "limit": 2, "offset": page["next_offset"]}
    ).json()
    assert [a["run_id"] for a in page["attempts"]] == ids[::-1][:2]
    assert page["has_more"] is True and page["next_offset"] == 2
    assert [a["run_id"] for a in rest["attempts"]] == ids[:1]
    assert rest["has_more"] is False and rest["next_offset"] is None


def test_another_reader_does_not_see_my_attempts(sample, db_session):
    _invoke(sample, "mine")
    other = User(id="work-other-reader", username="other-reader", role="admin")
    db_session.add(other)
    db_session.commit()
    client = helpers._client(db_session, sample.workspace, other, sample.monkeypatch)
    response = client.get(RECORDS.format(ref="prévision"), params={"namespace": "search"})
    assert response.status_code in {200, 403, 404}
    if response.status_code == 200:
        assert response.json()["attempts"] == []


def test_an_undeclared_namespace_is_refused(sample):
    response = sample.client.get(RECORDS.format(ref="x"), params={"namespace": "invoice"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "WORK_RECORD_NAMESPACE_UNKNOWN"


def test_record_identity_is_validated_and_optional():
    assert binding_service.validate_record_identity(None) is None
    assert binding_service.validate_record_identity({"namespace": "claim", "input_field": "claim_id"}) == {
        "namespace": "claim",
        "input_field": "claim_id",
    }
    for bad in ({"namespace": "Claim", "input_field": "claim_id"}, {"namespace": "claim"}, "claim"):
        with pytest.raises(binding_service.BindingError) as caught:
            binding_service.validate_record_identity(bad)
        assert caught.value.code == "BINDING_RECORD_IDENTITY_INVALID"
    identity = {"namespace": "claim", "input_field": "claim_id"}
    assert binding_service.record_ref_from_payload(identity, {"claim_id": " RC-1 "}) == "RC-1"
    assert binding_service.record_ref_from_payload(identity, {"claim_id": True}) is None
    assert binding_service.record_ref_from_payload(identity, {}) is None


def test_backfill_preview_classifies_runs_and_writes_nothing(sample, db_session):
    from scripts.preview_work_record_runs_backfill import preview

    run_id = _invoke(sample, "historic")
    db_session.query(WorkRecordRun).delete()
    db_session.commit()

    report = preview(db_session, workspace_id=sample.workspace.id)

    assert report["mode"] == "preview" and report["writes"] == 0
    assert report["counts"] == {"would_link": 1}
    assert report["sample"][0]["run_id"] == run_id
    assert report["sample"][0]["record_ref"] == "prévision"
    assert db_session.query(WorkRecordRun).count() == 0


def test_follow_up_points_back_to_the_work_case(sample, db_session):
    from app.tests.api.test_runs_summary import _client as runs_client

    run_id = _invoke(sample, "origin")
    body = runs_client(db_session, sample.workspace).get(f"/runs/{run_id}/follow-up").json()
    assert body["work_origin"] == {"experience_slug": "password-reset", "page_id": "home", "record_ref": "prévision"}
