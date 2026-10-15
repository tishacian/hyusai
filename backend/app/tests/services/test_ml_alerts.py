"""Alert transactions, safe delivery and replay use only local stubs."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.audit import AuditLog
from app.models.ml_operations import MLAlert, MLAlertChannel, MLAlertDelivery, MLAlertSource
from app.models.workspace import WorkspaceMember
from app.services import ml_alerts as service
from app.tests.services.test_ml_operations import case as mlops_case  # noqa: F401
from app.tests.services.test_ml_operations import client


@pytest.fixture(name="case")
def _case(request):
    return request.getfixturevalue("mlops_case")


def channel(db, case, kind="email"):
    row = MLAlertChannel(
        workspace_id=case.workspace.id,
        kind=kind,
        name="Test",
        enabled=True,
        destination_email="local@example.invalid" if kind == "email" else None,
        webhook_url_ref="secret://workspace/url" if kind == "webhook" else None,
        signing_key_ref="secret://workspace/hmac" if kind == "webhook" else None,
        created_by=case.admin.id,
    )
    db.add(row)
    db.flush()
    return row


def alert(db, case, **kwargs):
    return service.emit_alert(
        db,
        model=case.model,
        event_type="monitor_failed",
        state="failed",
        source_id=kwargs.pop("source_id", "run-1"),
        **kwargs,
    )


def test_transitions_throttle_recovery_and_no_external_io(db_session, case):
    channel(db_session, case)
    assert (
        service.monitor_transition(db_session, model=case.model, badge="ok", source_id="first")
        is None
    )
    service.monitor_transition(db_session, model=case.model, badge="watch", source_id="second")
    assert (
        service.monitor_transition(db_session, model=case.model, badge="watch", source_id="third")
        is None
    )
    service.monitor_transition(db_session, model=case.model, badge="alert", source_id="fourth")
    service.monitor_transition(db_session, model=case.model, badge="ok", source_id="fifth")
    db_session.commit()
    assert db_session.query(MLAlert).count() == 3
    assert db_session.query(MLAlertDelivery).count() == 3
    assert db_session.query(AuditLog).filter_by(event_type="ml.alert.created").count() == 3


def test_rollback_loses_alert_audit_and_delivery_together(db_session, case):
    channel(db_session, case)
    alert(db_session, case)
    db_session.rollback()
    assert db_session.query(MLAlert).count() == 0
    assert db_session.query(MLAlertDelivery).count() == 0
    assert db_session.query(AuditLog).filter_by(event_type="ml.alert.created").count() == 0


def test_same_source_is_idempotent_across_throttle_windows(db_session, case):
    now = datetime(2026, 10, 15, 10)
    first = alert(db_session, case, now=now)
    second = alert(db_session, case, now=now + timedelta(days=1))
    assert first.id == second.id
    third = alert(db_session, case, now=now, source_id="run-2")
    assert third.id == first.id
    db_session.flush()
    assert db_session.query(MLAlertSource).count() == 2


def test_active_lease_not_reclaimed_and_expired_lease_replayed(db_session, case):
    now = datetime.utcnow()
    channel(db_session, case)
    alert(db_session, case, now=now)
    db_session.commit()
    first = service.claim_delivery(db_session, now=now)
    db_session.commit()
    assert service.claim_delivery(db_session, now=now + timedelta(seconds=1)) is None
    second = service.claim_delivery(db_session, now=now + timedelta(seconds=91))
    assert first["id"] == second["id"] and first["token"] != second["token"]
    assert db_session.get(MLAlertDelivery, first["id"]).attempts == 2


def test_retry_keeps_safe_error_and_bounded_attempts(db_session, case, monkeypatch):
    channel(db_session, case)
    alert(db_session, case)
    db_session.commit()
    monkeypatch.setitem(settings.__dict__, "ml_alert_max_attempts", 2)

    def failed(db, row):
        raise ValueError("secret-url-credential")

    now = datetime.utcnow()
    assert service.deliver_pending(SessionLocal, limit=1, sender=failed, now=now) == 0
    db_session.expire_all()
    row = db_session.query(MLAlertDelivery).one()
    assert row.status == "retry" and row.error_code == "ML_ALERT_DELIVERY_FAILED"
    assert (
        service.deliver_pending(
            SessionLocal, limit=1, sender=failed, now=now + timedelta(seconds=121)
        )
        == 0
    )
    db_session.expire_all()
    assert row.status == "failed" and row.attempts == 2
    assert "secret-url" not in json.dumps([r.details for r in db_session.query(AuditLog).all()])


def test_successful_delivery_is_not_repeated(db_session, case):
    channel(db_session, case)
    alert(db_session, case)
    db_session.commit()
    calls = []

    def delivered(db, row):
        calls.append(row.id)

    assert service.deliver_pending(SessionLocal, sender=delivered, limit=2) == 1
    assert service.deliver_pending(SessionLocal, sender=delivered, limit=2) == 0
    assert len(calls) == 1


def test_revoked_channel_owner_stops_send(db_session, case):
    channel(db_session, case)
    alert(db_session, case)
    db_session.commit()
    db_session.query(WorkspaceMember).filter_by(user_id=case.admin.id).delete()
    db_session.commit()
    assert (
        service.send_delivery(db_session, db_session.query(MLAlertDelivery).one())
        == "ML_ALERT_OWNER_REVOKED"
    )


def test_webhook_hmac_signs_timestamp_and_exact_body(db_session, case, monkeypatch):
    channel(db_session, case, "webhook")
    alert(db_session, case)
    db_session.commit()
    calls = []
    monkeypatch.setattr(
        service,
        "_secret",
        lambda db, c, ref: (
            "k" * 32 if ref.endswith("hmac") else "https://receiver.invalid/alerts?hidden=token"
        ),
    )

    def receive(method, url, **kwargs):
        calls.append((method, url, kwargs))

    assert (
        service.send_delivery(
            db_session, db_session.query(MLAlertDelivery).one(), http_request=receive
        )
        is None
    )
    method, url, kwargs = calls[0]
    headers = kwargs["headers"]
    wanted = hmac.new(
        b"k" * 32,
        headers["X-Agentium-Timestamp"].encode() + b"." + kwargs["content"],
        hashlib.sha256,
    ).hexdigest()
    assert headers["X-Agentium-Signature"] == "sha256=" + wanted
    assert json.loads(kwargs["content"])["id"] == headers["X-Agentium-Delivery"]
    assert b"hidden" not in kwargs["content"] and b"key" not in kwargs["content"]


def test_email_uses_existing_config_with_local_test_transport(db_session, case, monkeypatch):
    from app.services import email

    channel(db_session, case)
    alert(db_session, case)
    db_session.commit()
    messages = []
    config = email.SmtpDeliveryConfig(
        host="localhost", username="test", password="fixture", from_email="local@example.invalid"
    )
    monkeypatch.setattr(email, "_default_delivery_config", lambda: config)
    assert (
        service.send_delivery(
            db_session,
            db_session.query(MLAlertDelivery).one(),
            smtp_sender=lambda **kwargs: messages.append(kwargs) or True,
        )
        is None
    )
    assert len(messages) == 1 and messages[0]["config"] is config
    assert "fixture" not in messages[0]["text"]


@pytest.mark.parametrize(
    "destination",
    [
        "http://example.com/a",
        "https://127.0.0.1/a",
        "https://169.254.169.254/latest/meta-data",
        "https://10.0.0.1/a",
    ],
)
def test_webhook_rejects_ssrf_even_legacy_report_mode(monkeypatch, destination):
    from app.services.connectors.network_policy import ConnectorNetworkError

    monkeypatch.setattr(settings, "connector_framework_enabled", False)
    monkeypatch.setattr(settings, "connector_network_policy_mode", "report")
    with pytest.raises((ConnectorNetworkError, ValueError)):
        service._send_webhook(
            "POST", destination, deadline_at="", headers={}, content=b"{}", max_bytes=100
        )


def test_webhook_dns_pinned_no_redirect_and_response_bounded(monkeypatch):
    from app.services.connectors import http_transport, network_policy

    calls = []

    def resolve(host, port, **kwargs):
        calls.append((host, port, kwargs))
        return network_policy.Destination(host, "8.8.8.8", port)

    monkeypatch.setattr(network_policy, "resolve_destination", resolve)

    def client(url, destination, **kwargs):
        assert destination.address == "8.8.8.8"
        return httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(302, headers={"Location": "https://127.0.0.1/"})
            )
        )

    monkeypatch.setattr(http_transport, "pinned_client", client)
    with pytest.raises(ValueError, match="HTTP_FAILED"):
        service._send_webhook(
            "POST",
            "https://receiver.invalid/alerts",
            deadline_at="",
            headers={},
            content=b"{}",
            max_bytes=100,
        )
    assert calls == [("receiver.invalid", 443, {"mode": "enforce"})]


def test_channel_api_refuses_plaintext_and_nonworkspace_secrets(db_session, case):
    c = client(db_session, case)
    for ref in ("https://secret-url.invalid/a", "secret://platform/url", "secret://user/owner/url"):
        r = c.post(
            "/ml-operations/channels",
            json={
                "name": "x",
                "kind": "webhook",
                "webhook_url_ref": ref,
                "signing_key_ref": "secret://workspace/key",
            },
        )
        assert r.status_code == 422
    r = c.post(
        "/ml-operations/channels",
        json={
            "name": "x",
            "kind": "email",
            "destination_email": "x@example.invalid\nBcc: evil@example.invalid",
        },
    )
    assert r.status_code == 422
    r = c.post(
        "/ml-operations/channels",
        json={
            "name": "x",
            "kind": "webhook",
            "webhook_url_ref": "secret://workspace/url",
            "signing_key_ref": "secret://workspace/key",
        },
    )
    assert r.status_code == 200, r.text
    assert "secret://workspace/url" in r.text
    assert client(db_session, case, case.reader).get("/ml-operations/channels").status_code == 403


def test_alerts_workspace_scope_and_acknowledgement(db_session, case):
    own = alert(db_session, case)
    service.emit_alert(
        db_session, model=case.other, event_type="quota_reached", state="requests", source_id="hour"
    )
    db_session.commit()
    c = client(db_session, case)
    assert [row["id"] for row in c.get("/ml-operations/alerts").json()["items"]] == [own.id]
    assert c.post("/ml-operations/alerts/" + own.id + "/acknowledge").status_code == 200
    assert c.post("/ml-operations/alerts/" + own.id + "/acknowledge").status_code == 200
    assert db_session.query(AuditLog).filter_by(event_type="ml.alert.acknowledged").count() == 1


def test_monitor_failure_scanner_is_durable_and_bounded(db_session, case):
    from app.models.run import Run
    from app.models.system import System

    system = System(
        id=str(uuid4()),
        workspace_id=case.workspace.id,
        name="Monitor",
        settings={"ml_monitoring_model_id": case.model.id},
    )
    db_session.add(system)
    db_session.flush()
    for _ in range(3):
        db_session.add(
            Run(
                id=str(uuid4()),
                workspace_id=case.workspace.id,
                system_id=system.id,
                status="failed",
            )
        )
    db_session.commit()
    assert service.scan_monitor_failures(db_session, limit=2) == 2
    db_session.commit()
    assert service.scan_monitor_failures(db_session, limit=2) == 1
    db_session.commit()
    assert service.scan_monitor_failures(db_session, limit=2) == 0
