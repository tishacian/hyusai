"""The public webhook receiver states its verdict in the body, not the code."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import hooks
from app.core.config import settings
from app.models.system import System
from app.models.webhook_hook import WebhookHook
from app.models.workspace import Workspace
from app.services.run_engine import triggers, webhooks
from app.tests.publication_baseline import baseline_flow_publication

SECRET = "hook-secret"


@pytest.fixture()
def triggers_on(monkeypatch):
    monkeypatch.setattr(settings, "enable_event_triggers", True)
    yield


def _flow() -> dict[str, Any]:
    return {
        "schema_version": 3,
        "nodes": [
            {"id": "src.hook", "kind": "source", "type": "source.webhook"},
            {"id": "snk", "kind": "sink"},
        ],
        "edges": [{"from": "src.hook", "to": "snk", "kind": "control"}],
    }


def _seed(db_session, *, published: bool) -> tuple[System, WebhookHook]:
    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Hook delivery",
        slug=f"hook-delivery-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(workspace)
    db_session.commit()
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Webhook System",
        objective="deliver",
        flow_definition=_flow(),
        status="active",
    )
    db_session.add(system)
    db_session.commit()
    if published:
        baseline_flow_publication(db_session, system)
    hook = WebhookHook(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        name="Inbound",
        event_type=triggers.EVENT_WEBHOOK_RECEIVED,
        secret=SECRET,
        enabled=True,
    )
    db_session.add(hook)
    db_session.commit()
    return system, hook


def _post(db_session, hook: WebhookHook, payload: dict[str, Any], monkeypatch):
    app = FastAPI()
    app.include_router(hooks.router, prefix="/hooks")
    monkeypatch.setattr(hooks, "SessionLocal", lambda: db_session)
    # The endpoint owns its session in production; the fixture session must
    # outlive the request so the test can still read what it committed.
    monkeypatch.setattr(db_session, "close", lambda: None)
    body = json.dumps(payload).encode("utf-8")
    return TestClient(app).post(
        f"/hooks/{hook.id}",
        content=body,
        headers={
            webhooks.SIGNATURE_HEADER: f"sha256={webhooks.compute_signature(SECRET, body)}",
            "content-type": "application/json",
        },
    )


def test_an_accepted_delivery_still_answers_200_accepted(db_session, monkeypatch, triggers_on):
    _system, hook = _seed(db_session, published=True)

    response = _post(db_session, hook, {"job_id": "rpa-1"}, monkeypatch)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert [item["status"] for item in body["results"]] == ["simulated"]


def test_a_refused_delivery_answers_200_but_says_rejected(db_session, monkeypatch, triggers_on):
    system, hook = _seed(db_session, published=False)

    response = _post(db_session, hook, {"job_id": "rpa-2"}, monkeypatch)

    # 200 is deliberate: the sender's payload was fine and a non-2xx here would
    # invite a retry storm across every System the backfill has not reached.
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["results"][0]["status"] == "rejected"
    assert body["results"][0]["reason"] == "published_flow_version_invalid"
    assert body["results"][0]["system_id"] == system.id


def test_a_delivery_nothing_listens_for_is_ignored_not_rejected(db_session, monkeypatch):
    _system, hook = _seed(db_session, published=True)

    response = _post(db_session, hook, {"job_id": "rpa-3"}, monkeypatch)

    assert response.status_code == 200
    # Event triggers are off for this deployment: nothing refused the delivery.
    assert response.json() == {
        "status": "ignored",
        "hook_id": hook.id,
        "event_type": triggers.EVENT_WEBHOOK_RECEIVED,
        "results": [],
    }
