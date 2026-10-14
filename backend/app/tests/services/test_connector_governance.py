"""Egress grants and proof acceptance preserve platform trust boundaries."""

import socket
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.connector_governance import ConnectorEvidence, ConnectorNetworkException
from app.models.user import User
from app.models.workspace import Workspace
from app.services.connectors import evidence_store as evidence
from app.services.connectors import network_exceptions as exceptions
from app.services.connectors import network_policy as policy
from app.services.connectors.certification import EvidenceBundle, EvidencePayload, evidence_digest
from app.tests.connectors.kit.test_certification_contract import identity


@pytest.fixture()
def actors(db_session):
    admin = User(
        id=str(uuid4()),
        username="operator",
        email="operator@example.test",
        role="admin",
        is_active=True,
    )
    member = User(
        id=str(uuid4()), username="member", email="member@example.test", role="user", is_active=True
    )
    ws = Workspace(id=str(uuid4()), name="Local bench", slug="local-bench", settings={})
    other = Workspace(id=str(uuid4()), name="Other", slug="other-bench", settings={})
    db_session.add_all([admin, member, ws, other])
    db_session.commit()
    return admin, member, ws, other


def grant(db, actors):
    admin, _, ws, _ = actors
    return exceptions.create_exception(
        db,
        user=admin,
        workspace_id=ws.id,
        cidr="10.20.30.0/24",
        ports=[5432],
        reason="Disposable database bench",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def test_scope_port_expiry_and_revocation_are_enforced(db_session, actors, monkeypatch):
    admin, _, ws, other = actors
    row = grant(db_session, actors)
    assert not exceptions.load_grants(db_session, other.id)
    grants = exceptions.load_grants(db_session, ws.id)
    monkeypatch.setattr(policy.settings, "connector_network_policy_mode", "enforce")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.20.30.4", port))
        ],
    )
    with exceptions.network_grants(grants):
        assert policy.resolve_destination("db.test", 5432).address == "10.20.30.4"
        with pytest.raises(policy.ConnectorNetworkError):
            policy.resolve_destination("db.test", 443)
        assert exceptions.approved_cidrs(5432, now=datetime.now(UTC) + timedelta(hours=2)) == ()
    with pytest.raises(policy.ConnectorNetworkError):
        policy.resolve_destination("db.test", 5432)
    exceptions.revoke_exception(db_session, user=admin, exception_id=row.id)
    assert not exceptions.load_grants(db_session, ws.id)


def test_framework_activation_cannot_use_legacy_report_mode(monkeypatch):
    monkeypatch.setattr(policy.settings, "connector_framework_enabled", True)
    monkeypatch.setattr(policy.settings, "connector_network_policy_mode", "report")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.20.30.4", port))
        ],
    )
    with pytest.raises(policy.ConnectorNetworkError, match="CONNECTOR_DESTINATION_DENIED"):
        policy.resolve_destination("db.test", 5432, mode="report")


@pytest.mark.parametrize(
    "cidr",
    [
        "0.0.0.0/0",
        "10.0.0.0/8",
        "127.0.0.1/32",
        "169.254.169.254/32",
        "::1/128",
        "fe80::/64",
        "::ffff:10.20.30.0/120",
        "93.184.216.0/24",
        "10.20.30.5/24",
    ],
)
def test_network_exceptions_cannot_approve_special_or_broad_ranges(cidr):
    with pytest.raises(exceptions.NetworkExceptionError):
        exceptions.checked_network(cidr)


def test_workspace_admin_cannot_issue_platform_exception(db_session, actors):
    _, member, ws, _ = actors
    with pytest.raises(exceptions.NetworkExceptionError, match="PLATFORM_PERMISSION_DENIED"):
        exceptions.create_exception(
            db_session,
            user=member,
            workspace_id=ws.id,
            cidr="10.20.30.0/24",
            ports=[443],
            reason="Workspace preference",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    assert db_session.query(ConnectorNetworkException).count() == 0


def test_exception_requires_atomic_audit(db_session, actors, monkeypatch):
    monkeypatch.setattr(exceptions, "emit_audit_event", lambda **kw: None)
    with pytest.raises(exceptions.NetworkExceptionError, match="CONNECTOR_AUDIT_REQUIRED"):
        grant(db_session, actors)
    assert db_session.query(ConnectorNetworkException).count() == 0


def proof(*, at=None):
    reports = [
        evidence.ProofReport(suite=name, status="passed", code="FIXTURE_ONLY", elapsed_ms=1)
        for name in ("canary", "revocation")
    ]
    payload = EvidencePayload(
        kind="canary",
        identity=identity(),
        source_revision="d" * 40,
        environment="deployed",
        environment_id="fixture-only",
        source="demo",
        completed_at=at or datetime.now(UTC) - timedelta(seconds=1),
        results=[
            dict(suite=r.suite, status=r.status, evidence_sha256=evidence.report_digest(r))
            for r in reports
        ],
    )
    return EvidenceBundle(payload=payload, sha256=evidence_digest(payload)), reports


def test_operator_acceptance_retains_proofs_and_revoke_invalidates(db_session, actors):
    admin, _, _, _ = actors
    bundle, reports = proof()
    row = evidence.accept_evidence(
        db_session, user=admin, producer="fixture-operator", bundle=bundle, reports=reports
    )
    assert row.reports == [r.model_dump(mode="json") for r in reports]
    assert (
        evidence.accept_evidence(
            db_session, user=admin, producer="fixture-operator", bundle=bundle, reports=reports
        ).digest
        == row.digest
    )
    assert evidence.trusted_bundles(db_session, "fixture_only") == (bundle,)
    evidence.revoke_evidence(db_session, user=admin, digest=row.digest)
    assert evidence.trusted_bundles(db_session, "fixture_only") == ()
    with pytest.raises(evidence.EvidenceError, match="CONNECTOR_EVIDENCE_REVOKED"):
        evidence.accept_evidence(
            db_session, user=admin, producer="fixture-operator", bundle=bundle, reports=reports
        )


@pytest.mark.parametrize("tamper", ["actor", "reports", "future", "audit"])
def test_proof_acceptance_rejects_untrusted_or_changed_reports(
    db_session, actors, monkeypatch, tamper
):
    admin, member, _, _ = actors
    bundle, reports = proof(
        at=datetime.now(UTC) + timedelta(days=1) if tamper == "future" else None
    )
    if tamper == "reports":
        reports[0] = reports[0].model_copy(update={"elapsed_ms": 2})
    if tamper == "audit":
        monkeypatch.setattr(evidence, "emit_audit_event", lambda **kw: None)
    with pytest.raises(evidence.EvidenceError):
        evidence.accept_evidence(
            db_session,
            user=member if tamper == "actor" else admin,
            producer="fixture-operator",
            bundle=bundle,
            reports=reports,
        )
    assert db_session.query(ConnectorEvidence).count() == 0


def test_reports_cannot_embed_arbitrary_logs_or_credentials():
    with pytest.raises(ValidationError):
        evidence.ProofReport(
            suite="connection", status="passed", code="OK", elapsed_ms=1, logs="password"
        )


def test_governance_api_is_disabled_by_default_and_platform_only(db_session, actors, monkeypatch):
    from app.api.v1.endpoints import connector_governance as api

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_db] = lambda: db_session
    app.dependency_overrides[api.get_current_user] = lambda: actors[1]
    client = TestClient(app)
    monkeypatch.setattr(api.settings, "connector_framework_enabled", False)
    assert client.get("/network-exceptions").status_code == 404
    monkeypatch.setattr(api.settings, "connector_framework_enabled", True)
    assert client.get("/network-exceptions").status_code == 403
    app.dependency_overrides[api.get_current_user] = lambda: actors[0]
    assert client.get("/network-exceptions").status_code == 200
    body = dict(
        cidr="10.20.30.0/24",
        ports=[True],
        reason="not a valid port",
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    )
    assert client.post("/network-exceptions", json=body).status_code == 422
