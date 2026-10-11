"""Unit tests for webhook HMAC verification + emit path (Phase 3)."""
from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.models.system import System
from app.models.webhook_hook import WebhookHook
from app.models.workspace import Workspace
from app.services.run_engine import triggers, webhooks
from app.tests.publication_baseline import LEGACY_FLOW_AUTHORITY


def _workspace(db, *, features=None) -> Workspace:
    ws = Workspace(
        id=str(uuid.uuid4()),
        name="Hook WS",
        slug=f"hook-{uuid.uuid4().hex[:6]}",
        settings={
            "features": {**LEGACY_FLOW_AUTHORITY["features"], **(features or {})},
        },
    )
    db.add(ws)
    db.commit()
    return ws


def _webhook_flow() -> dict:
    return {
        "schema_version": 3,
        "nodes": [
            {"id": "src.hook", "kind": "source", "type": "source.webhook"},
            {"id": "t.analyze", "kind": "task", "config": {"skill_slug": "semantic_search_v1"}},
            {"id": "snk", "kind": "sink"},
        ],
        "edges": [
            {"from": "src.hook", "to": "t.analyze", "kind": "control"},
            {"from": "t.analyze", "to": "snk", "kind": "data"},
        ],
    }


def test_verify_hmac_accepts_sha256_prefix():
    secret = "s3cret"
    body = b'{"ok":true}'
    digest = webhooks.compute_signature(secret, body)
    assert webhooks.verify_hmac_signature(secret, body, f"sha256={digest}")
    assert webhooks.verify_hmac_signature(secret, body, digest)
    assert not webhooks.verify_hmac_signature(secret, body, "sha256=deadbeef")
    assert not webhooks.verify_hmac_signature(secret, body, None)


def test_authenticate_hook_rejects_bad_signature(db_session):
    ws = _workspace(db_session)
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        name="Hook Sys",
        objective="t",
        flow_definition=_webhook_flow(),
        status="active",
    )
    db_session.add(system)
    hook = WebhookHook(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        system_id=system.id,
        name="H",
        event_type=triggers.EVENT_WEBHOOK_RECEIVED,
        secret="correct-secret",
        enabled=True,
    )
    db_session.add(hook)
    db_session.commit()

    body = b'{"a":1}'
    ok, reason = webhooks.authenticate_hook(
        db_session, hook.id, body=body, signature_header="sha256=nope"
    )
    assert ok is None
    assert reason == "invalid_signature"

    good_sig = webhooks.compute_signature(hook.secret, body)
    ok2, reason2 = webhooks.authenticate_hook(
        db_session, hook.id, body=body, signature_header=f"sha256={good_sig}"
    )
    assert ok2 is not None
    assert reason2 is None


@pytest.fixture()
def triggers_on(monkeypatch):
    monkeypatch.setattr(settings, "enable_event_triggers", True)
    yield


def test_emit_webhook_targets_hook_system(db_session, triggers_on):
    ws = _workspace(db_session)
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        name="Hook Sys",
        objective="t",
        flow_definition=_webhook_flow(),
        status="active",
        settings={"event_trigger": {"mode": "dry_run"}},
    )
    db_session.add(system)
    db_session.commit()

    results = triggers.emit_event(
        triggers.EVENT_WEBHOOK_RECEIVED,
        ws.id,
        {"job_id": "rpa-1"},
        db=db_session,
        system_id=system.id,
    )
    assert len(results) == 1
    assert results[0]["status"] == "simulated"
    assert results[0]["system_id"] == system.id


def test_workspace_opt_in_enables_triggers_without_global(db_session, monkeypatch):
    monkeypatch.setattr(settings, "enable_event_triggers", False)
    ws = _workspace(db_session, features={"enable_event_triggers": True})
    assert triggers.is_event_triggers_enabled(ws.id, db=db_session) is True

    ws2 = _workspace(db_session, features={})
    assert triggers.is_event_triggers_enabled(ws2.id, db=db_session) is False


def test_sftp_staging_emit_payload_path(db_session, triggers_on):
    """``emit_sftp_file_arrived`` accepts staging-close payloads."""
    ws = _workspace(db_session)
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        name="SFTP Sys",
        objective="t",
        flow_definition={
            "schema_version": 3,
            "nodes": [
                {"id": "src.sftp", "kind": "source", "type": "source.sftp_arrival"},
                {"id": "t.analyze", "kind": "task", "config": {"skill_slug": "semantic_search_v1"}},
                {"id": "snk", "kind": "sink"},
            ],
            "edges": [
                {"from": "src.sftp", "to": "t.analyze", "kind": "control"},
                {"from": "t.analyze", "to": "snk", "kind": "data"},
            ],
        },
        status="active",
    )
    db_session.add(system)
    db_session.commit()

    results = triggers.emit_sftp_file_arrived(
        db_session,
        workspace_id=ws.id,
        payload={
            "workspace_id": ws.id,
            "file_id": "f1",
            "filename": "doc.pdf",
            "source": "sftp_staging",
        },
    )
    assert len(results) == 1
    assert results[0]["status"] == "simulated"
