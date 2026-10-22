"""Local PostgreSQL proof that action serialization permits credential auditing.

Set CLAIMS_POSTGRES_URL to an owned loopback test instance. Tests create and
remove a uniquely named schema; no external source or model is contacted.
"""

import os
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.audit import AuditLog
from app.models.claim_action import ClaimAction
from app.models.decision import Decision
from app.models.run import Run
from app.models.user import User
from app.models.workspace import Workspace
from app.services import audit_logger
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
            db.add(Workspace(id="claims-ws", slug="claims-ws", name="Action lock"))
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
