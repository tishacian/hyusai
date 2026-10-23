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


def test_a_teammate_sees_the_cases_attempts_with_their_author(sample, db_session):
    from app.models.workspace import WorkspaceMember

    run_id = _invoke(sample, "mine")
    other = User(id="work-other-reader", username="other-reader", role="member")
    db_session.add_all([
        other,
        WorkspaceMember(workspace_id=sample.workspace.id, user_id=other.id, role="member",
                        role_template="workspace_admin"),
    ])
    db_session.commit()
    client = helpers._client(db_session, sample.workspace, other, sample.monkeypatch)
    body = client.get(RECORDS.format(ref="prévision"), params={"namespace": "search"}).json()
    assert [a["run_id"] for a in body["attempts"]] == [run_id]
    assert body["attempts"][0]["started_by_reader"] is False
    assert body["attempts"][0]["started_by"] == sample.user.username


def test_an_outsider_sees_no_attempt(sample, db_session):
    _invoke(sample, "mine")
    outsider = User(id="work-outsider-reader", username="outsider", role="member")
    db_session.add(outsider)
    db_session.commit()
    client = helpers._client(db_session, sample.workspace, outsider, sample.monkeypatch)
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



def test_backfill_preview_links_runs_through_a_business_reader(db_session, monkeypatch):
    """The preview loads readers' providers itself: a claims Run whose release
    declares no identity is still proven, with an empty registry as in a script."""
    from app.services.ecommerce import claims
    from app.services.ecommerce import record_identity as claims_identity
    from app.services.experience import record_identity
    from scripts.preview_work_record_runs_backfill import preview

    workspace, user = helpers._seed(db_session)
    helpers._seed_binding(db_session, workspace, user)  # no identity declared on the binding
    studio = helpers._experiences_client(db_session, workspace, user)
    with monkeypatch.context() as patch:
        patch.setattr(helpers, "_pages", _action_pages)
        helpers._publish(studio, binding_key="work.reset")
    client = helpers._client(db_session, workspace, user, monkeypatch)
    run_id = _invoke(SimpleNamespace(client=client), "claims-history")
    run = db_session.get(Run, run_id)
    run.input_ref = {**run.input_ref, "claim_id": "RC-1042"}
    db_session.query(WorkRecordRun).delete()
    db_session.commit()

    monkeypatch.setattr(claims_identity, "CLAIMS_APP_SLUG", "password-reset")
    monkeypatch.setattr(claims_identity, "INVESTIGATE_BINDING", "work.reset")
    monkeypatch.setattr(claims, "_config", lambda ws: {"allowed_claim_ids": ["RC-1042"]})
    monkeypatch.setattr(record_identity, "_PROVIDERS", [])
    monkeypatch.setattr(record_identity, "_loaded", False, raising=False)

    report = preview(db_session, workspace_id=workspace.id)

    assert report["counts"] == {"would_link": 1}
    assert report["sample"][0]["run_id"] == run_id
    assert (report["sample"][0]["namespace"], report["sample"][0]["record_ref"]) == ("claim", "RC-1042")
    assert db_session.query(WorkRecordRun).count() == 0

def test_a_business_reader_can_supply_the_identity_without_republishing(db_session, monkeypatch):
    from app.services.experience import record_identity

    workspace, user = helpers._seed(db_session)
    helpers._seed_binding(db_session, workspace, user)  # no identity declared on the binding
    studio = helpers._experiences_client(db_session, workspace, user)
    with monkeypatch.context() as patch:
        patch.setattr(helpers, "_pages", _action_pages)
        helpers._publish(studio, binding_key="work.reset")
    calls = []

    def provider(ws, slug, key):
        calls.append((slug, key))
        return {"namespace": "search", "input_field": "query"} if key == "work.reset" else None

    monkeypatch.setattr(record_identity, "_PROVIDERS", [provider])
    client = helpers._client(db_session, workspace, user, monkeypatch)
    sample = SimpleNamespace(client=client)
    run_id = _invoke(sample, "provided")
    page = client.get(RECORDS.format(ref="prévision"), params={"namespace": "search"}).json()
    resolved = client.get("/work/password-reset/bindings/work.reset/resolve").json()
    assert [a["run_id"] for a in page["attempts"]] == [run_id]
    assert resolved["binding"]["record_identity"] == {"namespace": "search", "input_field": "query"}
    assert ("password-reset", "work.reset") in calls


def test_resolver_prefers_the_released_contract_and_validates_providers(monkeypatch):
    from app.services.experience import record_identity

    monkeypatch.setattr(record_identity, "_PROVIDERS", [lambda ws, slug, key: {"namespace": "Bad Space", "input_field": "x"}])
    released = {"binding_key": "k", "record_identity": {"namespace": "claim", "input_field": "claim_id"}}
    assert record_identity.resolve_record_identity(released, workspace=None, experience_slug="app") == {
        "namespace": "claim", "input_field": "claim_id",
    }
    assert record_identity.resolve_record_identity({"binding_key": "k"}, workspace=None, experience_slug="app") is None


def test_follow_up_points_back_to_the_work_case(sample, db_session):
    from app.tests.api.test_runs_summary import _client as runs_client

    run_id = _invoke(sample, "origin")
    body = runs_client(db_session, sample.workspace).get(f"/runs/{run_id}/follow-up").json()
    assert body["work_origin"] == {"experience_slug": "password-reset", "page_id": "home", "record_ref": "prévision"}


def _historic_runs(sample, db_session, count=2):
    """Runs started before the ledger existed: invoked, then unlinked."""
    ids = [_invoke(sample, f"historic-{n}") for n in range(count)]
    db_session.query(WorkRecordRun).delete()
    db_session.commit()
    return ids


def test_backfill_apply_links_each_run_once_in_its_real_order(sample, db_session):
    from datetime import datetime, timedelta

    from scripts.preview_work_record_runs_backfill import apply

    first, second = _historic_runs(sample, db_session)
    start = datetime(2026, 10, 20, 9, 0, 0)
    db_session.get(Run, first).started_at = start
    db_session.get(Run, second).started_at = start + timedelta(hours=1)
    db_session.commit()
    before = {run.id: (run.status, dict(run.input_ref or {})) for run in db_session.query(Run)}
    logged = []

    report = apply(db_session, workspace_id=sample.workspace.id, expect=2, log=logged.append)

    assert report["mode"] == "apply" and report["writes"] == 2
    rows = db_session.query(WorkRecordRun).order_by(WorkRecordRun.created_at).all()
    assert [row.run_id for row in rows] == [first, second]
    assert [row.created_at for row in rows] == [start, start + timedelta(hours=1)]
    assert {row.backfill_batch_id for row in rows} == {report["batch_id"]}
    assert {(row.record_namespace, row.record_ref) for row in rows} == {("search", "prévision")}
    assert len(logged) == 2 and all(report["batch_id"] in line for line in logged)
    # Runs are never modified.
    assert {run.id: (run.status, dict(run.input_ref or {})) for run in db_session.query(Run)} == before
    # Newest first in the reader's history, as for live attempts.
    page = sample.client.get(RECORDS.format(ref="prévision"), params={"namespace": "search"}).json()
    assert [attempt["run_id"] for attempt in page["attempts"]] == [second, first]

    again = apply(db_session, workspace_id=sample.workspace.id)
    assert again["writes"] == 0
    assert again["not_linked"] == {"already_linked": 2}
    assert db_session.query(WorkRecordRun).count() == 2


def test_backfill_apply_refuses_an_unexpected_count_and_writes_nothing(sample, db_session):
    from scripts.preview_work_record_runs_backfill import BackfillRefused, apply

    _historic_runs(sample, db_session)
    with pytest.raises(BackfillRefused):
        apply(db_session, workspace_id=sample.workspace.id, expect=38)
    db_session.rollback()
    assert db_session.query(WorkRecordRun).count() == 0
    with pytest.raises(BackfillRefused):
        apply(db_session, workspace_id="unknown-workspace")


def test_backfill_revert_removes_only_its_own_batch(sample, db_session):
    from scripts.preview_work_record_runs_backfill import apply, revert

    _historic_runs(sample, db_session)
    batch = apply(db_session, workspace_id=sample.workspace.id)["batch_id"]
    live = _invoke(sample, "live-after-backfill")  # recorded when it started
    assert db_session.query(WorkRecordRun).count() == 3

    report = revert(db_session, workspace_id=sample.workspace.id, batch_id=batch)

    assert report == {"mode": "revert", "workspace_id": sample.workspace.id, "batch_id": batch, "removed": 2}
    remaining = db_session.query(WorkRecordRun).all()
    assert [row.run_id for row in remaining] == [live]
    assert remaining[0].backfill_batch_id is None
    assert revert(db_session, workspace_id=sample.workspace.id, batch_id=batch)["removed"] == 0
    assert db_session.query(Run).count() == 3


def test_backfill_command_line_previews_by_default(sample, db_session, monkeypatch, capsys):
    import json

    from scripts import preview_work_record_runs_backfill as script

    _historic_runs(sample, db_session, count=1)
    monkeypatch.setattr(script, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    assert script.main(["--workspace-id", sample.workspace.id]) == 0
    assert json.loads(capsys.readouterr().out)["writes"] == 0
    assert db_session.query(WorkRecordRun).count() == 0
    assert script.main(["--workspace-id", sample.workspace.id, "--apply", "--expect", "5"]) == 2
    assert db_session.query(WorkRecordRun).count() == 0
    with pytest.raises(SystemExit):
        script.main(["--workspace-id", sample.workspace.id, "--expect", "1"])
