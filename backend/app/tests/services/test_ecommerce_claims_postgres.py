"""Local PostgreSQL proof that action serialization permits credential auditing.

Set CLAIMS_POSTGRES_URL to an owned loopback test instance. Tests create and
remove a uniquely named schema; no external source or model is contacted.
"""

import os
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.audit import AuditLog
from app.models.claim_action import ClaimAction
from app.models.claim_trial import ClaimTrial
from app.models.decision import Decision
from app.models.run import Run
from app.models.user import User
from app.models.workspace import Workspace
from app.services import audit_logger, claims_benchmark
from app.services.ecommerce import claims
from app.tests.services.test_ecommerce_claims import case


@pytest.fixture()
def pg(monkeypatch):
    url = os.getenv("CLAIMS_POSTGRES_URL")
    if not url:
        pytest.skip("CLAIMS_POSTGRES_URL required for owned PostgreSQL qualification")
    assert make_url(url).host in {"127.0.0.1", "localhost"}
    schema = "claims_lock_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        connect_args={
            "options": f"-csearch_path={schema} -clock_timeout=250 -cstatement_timeout=2000"
        },
    )
    try:
        Base.metadata.create_all(engine)
        monkeypatch.setattr(audit_logger, "SessionLocal", sessionmaker(engine))
        with Session(engine) as db:
            db.add(
                Workspace(
                    id="claims-ws",
                    slug="claims-ws",
                    name="Action lock",
                    settings={
                        "features": {"ecommerce_claims_v1": True},
                        "ecommerce_claims": {
                            **case(1043)[2],
                            "allowed_claim_ids": ["RC-1043"],
                            "allowed_collection_slugs": ["rules"],
                        },
                    },
                )
            )
            db.add(User(id="claims-user", username="claims-user"))
            db.flush()
            db.add(
                Run(id="claims-run", workspace_id="claims-ws", initiated_by_user_id="claims-user")
            )
            db.add(
                Decision(
                    id="claims-decision",
                    workspace_id="claims-ws",
                    scope="run",
                    target_id="claims-run",
                    kind="hitl_approval",
                    title="Approved",
                    status="accepted",
                    human_confirmed_by="claims-user",
                    human_confirmed_at=datetime.utcnow(),
                )
            )
            db.commit()
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def audit_credential_resolution():
    # registry._audit_resolution uses this independent-session path, with the
    # same workspace foreign key, before the PostgreSQL reader can connect.
    return audit_logger.emit_audit_event(
        workspace_id="claims-ws", event_type="secret.resolved", actor="connector:postgresql"
    )


def test_exclusive_workspace_lock_reproduces_the_audit_foreign_key_wait(pg):
    with Session(pg) as holder:
        holder.query(Workspace).filter_by(id="claims-ws").with_for_update().one()
        # The fixture's 250ms lock timeout bounds a wait which production did
        # not bound. The audit transaction cannot finish while this lock stays.
        assert audit_credential_resolution() is None
        assert holder.in_transaction()
    with Session(pg) as db:
        assert db.query(AuditLog).count() == 0


def test_action_lock_allows_audit_but_still_serializes_action_writers(pg, monkeypatch):
    proposal = claims.propose(*case(1043))

    def snapshot(*_args):
        assert audit_credential_resolution() is not None
        return {"provenance": {"snapshot_sha256": "snap"}}

    monkeypatch.setattr(claims.pg, "snapshot", snapshot)
    monkeypatch.setattr(claims, "_sources", lambda *_args: [])
    with Session(pg) as holder:
        workspace, run = holder.get(Workspace, "claims-ws"), holder.get(Run, "claims-run")
        monkeypatch.setattr(
            claims, "_approved_human", lambda *_args: holder.get(Decision, "claims-decision")
        )
        receipt = claims._simulate(holder, workspace, run, {}, "RC-1043", proposal)
        assert receipt["status"] == "simulated" and receipt["external_payment_called"] is False
        with Session(pg) as observer:
            assert observer.query(AuditLog).count() == 1
            assert observer.query(ClaimAction).count() == 0  # still uncommitted
            with pytest.raises(OperationalError) as blocked:
                observer.query(Workspace).filter_by(id=workspace.id).with_for_update(
                    key_share=True
                ).one()
            assert blocked.value.orig.pgcode == "55P03"
        holder.commit()
    with Session(pg) as db:
        assert db.query(ClaimAction).count() == 1
        assert db.query(AuditLog).count() == 1


@pytest.mark.parametrize("transition", ["start", "finish"])
def test_benchmark_transition_allows_audit_and_preserves_serialization(pg, monkeypatch, transition):
    snapshot = {
        "provenance": {"snapshot_sha256": "benchmark-snapshot"},
        "data": {"documents": [{"document_key": "loss", "knowledge_source_id": "proof"}]},
    }
    expected = {"action": "refund", "amount": "49.90", "references": ["loss"]}

    def audited_snapshot(*_args):
        assert audit_credential_resolution() is not None
        return snapshot

    monkeypatch.setattr(claims_benchmark.pg, "snapshot", audited_snapshot)
    monkeypatch.setattr(
        claims, "_sources", lambda *_args: [(None, SimpleNamespace(id="proof"), None)]
    )
    with Session(pg) as db:
        workspace = db.get(Workspace, "claims-ws")
        workspace.settings = {
            "features": {"ecommerce_claims_v1": True},
            "ecommerce_claims": {
                "allowed_claim_ids": ["RC-1043"],
                "allowed_collection_slugs": ["rules"],
                "policy_sha256": "a" * 64,
                "benchmark": {
                    "version": "lock-test-v1",
                    "hourly_eur": "40.00",
                    "snapshot_sha256": {"RC-1043": "benchmark-snapshot"},
                    "pairs": [
                        {
                            "pair_id": "pair-1",
                            "first_condition": "manual",
                            "manual_claim_id": "RC-1043",
                            "manual_expected": expected,
                        }
                    ],
                },
            },
        }
        db.commit()
        if transition == "finish":
            row = claims_benchmark.start(
                db, workspace, db.get(User, "claims-user"), "pair-1", "manual"
            )
            trial_id = row.id
            db.commit()

    with Session(pg) as holder:
        workspace, user = holder.get(Workspace, "claims-ws"), holder.get(User, "claims-user")
        if transition == "start":
            row = claims_benchmark.start(holder, workspace, user, "pair-1", "manual")
        else:
            row = claims_benchmark.event(holder, workspace, user, trial_id, "finish", 1, expected)
        with Session(pg) as observer:
            # The independent audit has committed; the benchmark transition has not.
            assert observer.query(AuditLog).count() == (1 if transition == "start" else 2)
            visible = observer.query(ClaimTrial).one_or_none()
            assert visible is None if transition == "start" else visible.state == "active"
            with pytest.raises(OperationalError) as blocked:
                claims_benchmark._lock(observer, observer.get(Workspace, workspace.id))
            assert blocked.value.orig.pgcode == "55P03"
        holder.commit()
        assert row.state == ("active" if transition == "start" else "finished")
        # Serialization still protects both concurrent sessions and sequential replay.
        reason = "SESSION_ALREADY_ACTIVE" if transition == "start" else "CASE_ALREADY_USED"
        with pytest.raises(ValueError, match=reason):
            claims_benchmark.start(holder, workspace, user, "pair-1", "manual")
    with Session(pg) as db:
        assert db.query(ClaimTrial).count() == 1
