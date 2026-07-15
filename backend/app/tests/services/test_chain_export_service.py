"""Tests for ``services.chains.export_service`` — envelope shape,
flow stripping, slug rebinding, and envelope validation.

Covers:
- ``serialize_for_export`` strips ``skill_id`` from task nodes, keeps
  ``skill_slug``, and resolves system-level ``skill_slugs``.
- ``prepare_import`` rebinds known slugs against the target workspace
  and surfaces unresolved ones without failing.
- Envelope validation rejects wrong ``kind`` / wrong ``schema_version``.
"""

from __future__ import annotations

import pytest

from app.models.skill import Skill
from app.models.system import System
from app.services.chains import export_service


def _make_skill(db_session, *, slug: str, workspace_id: str | None) -> Skill:
    sk = Skill(
        id=f"sk-{slug}-{workspace_id or 'global'}",
        slug=slug,
        name=slug,
        workspace_id=workspace_id,
    )
    db_session.add(sk)
    db_session.flush()
    return sk


def _make_system(db_session, *, workspace_id: str, flow, skill_ids=None) -> System:
    s = System(
        id=f"sys-{workspace_id}",
        workspace_id=workspace_id,
        name="exp-test",
        objective="",
        flow_definition=flow,
        skill_ids=skill_ids or [],
    )
    db_session.add(s)
    db_session.flush()
    return s


def test_export_strips_skill_id_but_keeps_slug(db_session) -> None:
    sk = _make_skill(db_session, slug="llm_answer", workspace_id="ws-a")
    flow = {
        "nodes": [
            {"id": "src", "type": "source", "kind": "source"},
            {
                "id": "t1",
                "type": "llm",
                "kind": "task",
                "config": {"skill_id": sk.id, "skill_slug": "llm_answer"},
            },
            {"id": "snk", "type": "sink", "kind": "sink"},
        ],
        "edges": [],
    }
    s = _make_system(db_session, workspace_id="ws-a", flow=flow, skill_ids=[sk.id])
    env = export_service.serialize_for_export(db=db_session, system=s, exported_by="alice")
    assert env["kind"] == export_service.ENVELOPE_KIND
    assert env["schema_version"] == export_service.SCHEMA_VERSION
    task_node = [n for n in env["system"]["flow_definition"]["nodes"] if n["id"] == "t1"][0]
    assert "skill_id" not in task_node["config"]
    assert task_node["config"]["skill_slug"] == "llm_answer"
    assert env["system"]["skill_slugs"] == ["llm_answer"]


def test_import_rebinds_slugs_in_target_workspace(db_session) -> None:
    # Skill.slug is globally unique in the catalog; the receiver just
    # needs to look it up to rebind. Here we simulate a global skill
    # the target workspace can reach.
    target_sk = _make_skill(db_session, slug="llm_answer", workspace_id=None)
    envelope = {
        "kind": export_service.ENVELOPE_KIND,
        "schema_version": export_service.SCHEMA_VERSION,
        "exported_at": "2026-04-24T22:00:00Z",
        "exported_by": "alice",
        "source": {"workspace_id": "ws-a", "system_id": "sys-a"},
        "system": {
            "name": "Imported",
            "flow_definition": {
                "nodes": [
                    {"id": "src", "type": "source", "kind": "source"},
                    {
                        "id": "t1",
                        "type": "llm",
                        "kind": "task",
                        "config": {"skill_slug": "llm_answer"},
                    },
                    {"id": "snk", "type": "sink", "kind": "sink"},
                ],
                "edges": [],
            },
            "skill_slugs": ["llm_answer"],
            "execution_mode": "real_time_decision",
            "execution_profile": {},
            "coordination_pattern": "single_agent",
        },
    }
    kwargs, report = export_service.prepare_import(
        db=db_session, envelope=envelope, workspace_id="ws-b"
    )
    assert kwargs["skill_ids"] == [target_sk.id]
    task_node = [n for n in kwargs["flow_definition"]["nodes"] if n["id"] == "t1"][0]
    assert task_node["config"]["skill_id"] == target_sk.id
    assert task_node["config"]["skill_slug"] == "llm_answer"
    assert report["unresolved_skills"] == []
    assert len(report["task_node_rebinds"]) == 1


def test_import_reports_unresolved_slugs_without_failing(db_session) -> None:
    # Nothing registered for "ghost" in target workspace
    envelope = {
        "kind": export_service.ENVELOPE_KIND,
        "schema_version": export_service.SCHEMA_VERSION,
        "exported_at": "2026-04-24T22:00:00Z",
        "exported_by": "alice",
        "source": {"workspace_id": "ws-a", "system_id": "sys-a"},
        "system": {
            "name": "Imported",
            "flow_definition": {
                "nodes": [
                    {
                        "id": "t1",
                        "type": "llm",
                        "kind": "task",
                        "config": {"skill_slug": "ghost"},
                    },
                ],
                "edges": [],
            },
            "skill_slugs": ["ghost"],
            "execution_mode": "real_time_decision",
            "execution_profile": {},
            "coordination_pattern": "single_agent",
        },
    }
    kwargs, report = export_service.prepare_import(
        db=db_session, envelope=envelope, workspace_id="ws-z"
    )
    assert kwargs["skill_ids"] == []
    task_node = kwargs["flow_definition"]["nodes"][0]
    assert "skill_id" not in task_node["config"]
    assert report["unresolved_skills"] == ["ghost"]


def test_import_rejects_wrong_kind(db_session) -> None:
    envelope = {"kind": "something.else", "schema_version": 1, "system": {}}
    with pytest.raises(export_service.ChainExportError):
        export_service.prepare_import(db=db_session, envelope=envelope, workspace_id="ws-b")


def test_import_rejects_wrong_schema_version(db_session) -> None:
    envelope = {
        "kind": export_service.ENVELOPE_KIND,
        "schema_version": 99,
        "system": {"name": "x", "flow_definition": {"nodes": [], "edges": []}},
    }
    with pytest.raises(export_service.ChainExportError):
        export_service.prepare_import(db=db_session, envelope=envelope, workspace_id="ws-b")


def test_import_allows_target_name_override(db_session) -> None:
    envelope = {
        "kind": export_service.ENVELOPE_KIND,
        "schema_version": export_service.SCHEMA_VERSION,
        "system": {
            "name": "Original",
            "flow_definition": {"nodes": [], "edges": []},
            "skill_slugs": [],
            "execution_mode": "real_time_decision",
            "execution_profile": {},
            "coordination_pattern": "single_agent",
        },
    }
    kwargs, _ = export_service.prepare_import(
        db=db_session,
        envelope=envelope,
        workspace_id="ws-b",
        target_name="Cloned (copy)",
    )
    assert kwargs["name"] == "Cloned (copy)"
