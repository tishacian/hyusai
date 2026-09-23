"""Characterisation of every Mission Room action handler, pinned before a move.

The Mission Room handlers (Sentinel CI AYA and its Octocity OCTAVE copy) lived
in the shared action executor. They move to their pack module without any
behaviour change, and only a handful had tests of their own. This replays each
handler of both packs on a seeded workspace, with deterministic skills, and
compares the whole outcome (payload, audit event, awaiting state) with a
capture taken from the code before the move.

Regenerate the capture only for a deliberate behaviour change:
``MISSION_ROOM_CAPTURE=1 pytest app/tests/services/test_mission_room_handlers_characterization.py``
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from app.models.audit import AuditLog
from app.models.user import User
from app.services.actions import executor
from app.services.actions.registry import (
    OCTAVE_MISSION_ROOM_ACTIONS,
    OCTAVE_SECURITY_ACTIONS,
    SENTINEL_AYA_ACTIONS,
    SENTINEL_AYA_SECURITY_ACTIONS,
)
from app.services.mission_room import (
    OCTOCITY_WORKSPACE_SLUG,
    SENTINEL_WORKSPACE_SLUG,
    ensure_octocity_mission_room_workspace,
    ensure_sentinel_ci_workspace,
)

CAPTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mission_room_handlers.json"
GENERIC_HANDLERS = {
    "voice_loop_stop",
    "voice_repeat",
    "voice_rephrase",
    "voice_navigate_view",
    "voice_confirm_yes",
    "awaiting_declined",
    "noop",
}

_ISO = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _cases() -> list[tuple[str, Any]]:
    cases = []
    for pack, manifests in (
        ("sentinel", SENTINEL_AYA_ACTIONS + SENTINEL_AYA_SECURITY_ACTIONS),
        ("octave", OCTAVE_MISSION_ROOM_ACTIONS + OCTAVE_SECURITY_ACTIONS),
    ):
        for manifest in manifests:
            if manifest.handler.kind != "flow_node" or manifest.handler.name in GENERIC_HANDLERS:
                continue
            cases.append((pack, manifest))
    return cases


CASES = _cases()


def _normalise(value: Any) -> Any:
    text = json.dumps(value, ensure_ascii=False, sort_keys=False, default=str)
    text = _UUID.sub("<uuid>", _ISO.sub("<ts>", text))
    return json.loads(text)


def _fake_skill_factory(calls: list[dict[str, Any]]):
    async def fake_invoke_skill(slug: str, payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        calls.append({"slug": slug, "payload": payload})
        return {
            "status": "ready",
            "summary_markdown": f"[{slug}] synthese",
            "citations": [{"source_id": f"src-{slug}"}],
            "options": [{"label": f"{slug} option", "summary": "s", "confidence": 0.5}],
            "subject": f"[{slug}] objet",
            "body_markdown": f"[{slug}] corps",
            "priorities": [{"id": "p1", "title": "Priorite", "summary": "s"}],
            "cockpit": {"decision_sentence": "decision"},
            "next_event": {"id": "evt-next", "title": "Prochain", "time": "11:00", "location": "Lieu"},
            "sources": [],
        }

    return fake_invoke_skill


def _run(db_session, monkeypatch, pack: str, manifest) -> dict[str, Any]:
    if pack == "sentinel":
        ensure_sentinel_ci_workspace(db_session)
        slug = SENTINEL_WORKSPACE_SLUG
    else:
        ensure_octocity_mission_room_workspace(db_session)
        slug = OCTOCITY_WORKSPACE_SLUG
    db_session.commit()
    from app.models.workspace import Workspace

    workspace = db_session.query(Workspace).filter(Workspace.slug == slug).one()
    user = User(id=f"u-{pack}", username=f"{pack}-vp", email=f"{pack}@example.test", is_active=True)
    db_session.add(user)
    db_session.commit()

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(executor, "_invoke_skill", _fake_skill_factory(calls))
    monkeypatch.setattr(executor, "_flow_action_permission_denial", lambda *a, **k: None)
    text = (manifest.phrases or ("",))[0]
    result = asyncio.run(
        executor.execute_flow_action(
            db_session, workspace, user, manifest=manifest, text=text, session_id="s-1"
        )
    )
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.workspace_id == workspace.id, AuditLog.event_type == manifest.audit_event)
        .order_by(AuditLog.timestamp.desc())
        .first()
    )
    db_session.refresh(workspace)
    awaiting = executor.get_awaiting_state(db_session, workspace, session_id="s-1")
    return _normalise(
        {
            "result": result,
            "audit": audit.details if audit is not None else None,
            "awaiting": awaiting,
            "skill_calls": calls,
        }
    )


def _key(pack: str, manifest) -> str:
    return f"{pack}:{manifest.action_id}"


@pytest.mark.parametrize("pack,manifest", CASES, ids=[_key(p, m) for p, m in CASES])
def test_mission_room_handler_is_unchanged(db_session, monkeypatch, pack, manifest):
    outcome = _run(db_session, monkeypatch, pack, manifest)
    key = _key(pack, manifest)
    if os.environ.get("MISSION_ROOM_CAPTURE") == "1":
        captured = json.loads(CAPTURE.read_text(encoding="utf-8")) if CAPTURE.exists() else {}
        captured[key] = outcome
        CAPTURE.write_text(json.dumps(captured, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        return
    expected = json.loads(CAPTURE.read_text(encoding="utf-8"))[key]
    assert outcome == expected


def test_every_mission_room_handler_is_covered():
    handlers = {manifest.handler.name for _pack, manifest in CASES}
    assert len(handlers) >= 25, sorted(handlers)
