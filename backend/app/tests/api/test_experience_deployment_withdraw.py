"""Withdrawing an application deployment from its channel, without deleting anything."""

from __future__ import annotations

from app.core.iam.roles import WORKSPACE_VIEWER
from app.models.audit import AuditLog
from app.models.experience import ExperienceDeployment, ExperienceRelease
from app.models.system_binding import SystemBinding
from app.tests.api import test_experience_authorization as authz
from app.tests.api import test_work_api as helpers


def _setup(db_session, *, channel="live"):
    workspace, user = helpers._seed(db_session)
    helpers._seed_binding(db_session, workspace, user)
    studio = helpers._experiences_client(db_session, workspace, user)
    work = helpers._client(db_session, workspace, user)
    experience_id, release_id = helpers._publish(studio, binding_key="work.reset", channel=channel)
    return studio, work, experience_id, release_id


def _deployment(studio, experience_id, channel):
    detail = studio.get(f"/experiences/{experience_id}").json()
    return next(item for item in detail["deployments"] if item["channel"] == channel)


def _withdraw(studio, experience_id, deployment):
    return studio.post(
        f"/experiences/{experience_id}/deployments/{deployment['channel']}/withdraw",
        json={
            "expected_current_release_id": deployment["release_id"],
            "expected_deployment_updated_at": deployment["updated_at"],
        },
    )


def _work_slugs(work):
    return [row["experience"]["slug"] for row in work.get("/work").json()["experiences"]]


def test_a_withdrawn_channel_leaves_work_and_keeps_everything_else(db_session):
    studio, work, experience_id, release_id = _setup(db_session)
    assert "password-reset" in _work_slugs(work)
    before = _deployment(studio, experience_id, "live")
    releases = db_session.query(ExperienceRelease).count()
    bindings = db_session.query(SystemBinding).count()

    withdrawn = _withdraw(studio, experience_id, before)

    assert withdrawn.status_code == 200, withdrawn.text
    body = withdrawn.json()
    assert body["withdrawn_at"] and body["withdrawn_by"]
    assert body["id"] == before["id"] and body["release_id"] == release_id
    assert body["audience"] == before["audience"]
    assert "password-reset" not in _work_slugs(work)
    assert work.get("/work/password-reset").status_code == 404
    # Nothing is deleted: the deployment row, the release and the binding stay.
    assert db_session.query(ExperienceDeployment).filter_by(id=before["id"]).count() == 1
    assert db_session.query(ExperienceRelease).count() == releases
    assert db_session.query(SystemBinding).count() == bindings
    audit = db_session.query(AuditLog).filter(AuditLog.event_type == "experience.deployment_withdrawn").one()
    assert audit.details["deployment_id"] == before["id"]
    assert audit.details["release_id"] == release_id
    assert audit.details["release_number"] == 1
    assert audit.details["channel"] == "live"
    assert audit.actor


def test_a_retry_is_idempotent_and_a_stale_or_second_withdrawal_is_refused(db_session):
    studio, _work, experience_id, _release_id = _setup(db_session)
    before = _deployment(studio, experience_id, "live")
    first = _withdraw(studio, experience_id, before)
    assert _withdraw(studio, experience_id, before).json() == first.json()

    after = first.json()
    again = _withdraw(studio, experience_id, after)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "EXPERIENCE_DEPLOYMENT_WITHDRAWN"
    stale = studio.post(
        f"/experiences/{experience_id}/deployments/live/withdraw",
        json={"expected_current_release_id": "other", "expected_deployment_updated_at": after["updated_at"]},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "EXPERIENCE_DEPLOYMENT_CONFLICT"
    missing = _withdraw(studio, experience_id, {**after, "channel": "pilot"})
    assert missing.status_code == 404


def test_deploying_again_puts_the_channel_back_in_service(db_session):
    studio, work, experience_id, release_id = _setup(db_session)
    withdrawn = _withdraw(studio, experience_id, _deployment(studio, experience_id, "live")).json()
    rollback = studio.post(
        f"/experiences/{experience_id}/deployments/live/rollback",
        json={
            "release_id": release_id,
            "expected_current_release_id": release_id,
            "expected_deployment_updated_at": withdrawn["updated_at"],
        },
    )
    assert rollback.status_code == 409
    assert rollback.json()["detail"]["code"] == "EXPERIENCE_DEPLOYMENT_WITHDRAWN"

    redeployed = studio.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "live",
            "release_id": release_id,
            "expected_current_release_id": release_id,
            "expected_deployment_updated_at": withdrawn["updated_at"],
        },
    )

    assert redeployed.status_code == 201, redeployed.text
    assert redeployed.json()["withdrawn_at"] is None
    assert redeployed.json()["id"] == withdrawn["id"]
    assert "password-reset" in _work_slugs(work)


def test_withdrawing_pilot_leaves_live_in_service(db_session):
    studio, work, experience_id, release_id = _setup(db_session)
    live = _deployment(studio, experience_id, "live")
    pilot = studio.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": release_id,
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
        },
    )
    assert pilot.status_code == 201, pilot.text

    assert _withdraw(studio, experience_id, pilot.json()).status_code == 200

    assert "password-reset" in _work_slugs(work)
    assert _deployment(studio, experience_id, "live")["withdrawn_at"] is None
    assert _deployment(studio, experience_id, "live")["updated_at"] == live["updated_at"]


def test_a_viewer_cannot_withdraw(db_session):
    workspace, admin, _version = authz._seed(db_session, suffix="withdraw")
    viewer = authz._member(db_session, workspace, suffix="withdraw", role_template=WORKSPACE_VIEWER)
    experience_id = authz._ready_experience(authz._client(db_session, workspace, admin))
    client = authz._client(db_session, workspace, viewer)

    refused = client.post(
        f"/experiences/{experience_id}/deployments/live/withdraw",
        json={"expected_current_release_id": "r", "expected_deployment_updated_at": "2026-10-23T00:00:00"},
    )

    assert refused.status_code == 403
