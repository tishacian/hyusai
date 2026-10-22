"""Published prompt evidence is readable and restorable without changing releases."""

import copy

import pytest

from app.models.audit import AuditLog
from app.models.skill import Skill
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.workspace import Workspace
from app.services.flow_contracts import canonical_sha256
from app.tests.api.test_workspace_skill_authoring import _client, _create, _seed


@pytest.fixture
def history(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    result = _create(
        client,
        executor={
            "kind": "prompt_template",
            "params": {
                "provider": "openai",
                "model": "gpt-5",
                "template": "New instructions: {details}",
            },
        },
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"details": {"type": "string"}},
        },
    )
    assert result.status_code == 200, result.text
    skill = db_session.query(Skill).filter_by(slug=result.json()["slug"]).one()
    system = System(
        id="prompt-system", workspace_id=workspace.id, name="Support", flow_definition={"nodes": []}
    )
    executor = copy.deepcopy(skill.executor)
    executor["params"]["template"] = "Published instructions: {details}"
    executor["params"]["model"] = "previous-model"
    version = SystemVersion(
        id="prompt-version",
        system_id=system.id,
        workspace_id=workspace.id,
        version_number=1,
        release_kind="publish",
        flow_definition={"nodes": []},
        created_by=user.id,
        execution_contract={"nodes": {"compose": {"skill_slug": skill.slug, "executor": executor}}},
    )
    db_session.add_all([system, version])
    db_session.commit()
    return client, workspace, user, skill, system, version


def body_for(client, skill):
    listing = client.get(f"/skills/{skill.slug}/prompt-history")
    assert listing.status_code == 200, listing.text
    data = listing.json()
    entry = data["entries"][0]
    return {
        "version_id": entry["version_id"],
        "node_id": entry["node_id"],
        "template_sha256": entry["template_sha256"],
        "expected_current_sha256": data["current_sha256"],
    }


def test_restore_only_instructions_preserves_model_and_published_contract(history, db_session):
    client, workspace, user, skill, system, version = history
    contract = copy.deepcopy(version.execution_contract)
    body = body_for(client, skill)
    result = client.post(f"/skills/{skill.slug}/prompt-history/restore", json=body)
    assert result.status_code == 200, result.text
    assert result.json()["published_contracts_unchanged"] is True
    assert result.json()["executor"]["params"] == {
        "provider": "openai",
        "model": "gpt-5",
        "template": "Published instructions: {details}",
    }
    db_session.refresh(version)
    assert version.execution_contract == contract
    assert db_session.query(SystemVersion).count() == 1
    event = db_session.query(AuditLog).filter_by(event_type="skill.prompt.restored").one()
    assert event.details["after_sha256"] == canonical_sha256("Published instructions: {details}")
    assert "instructions" not in str(event.details)
    assert client.post(f"/skills/{skill.slug}/prompt-history/restore", json=body).status_code == 200
    assert db_session.query(AuditLog).filter_by(event_type="skill.prompt.restored").count() == 1


def test_audit_failure_rolls_back_restore(history, db_session, monkeypatch):
    from app.services.skills_registry import prompt_history

    client, workspace, user, skill, system, version = history
    body = body_for(client, skill)
    original = copy.deepcopy(skill.executor)
    monkeypatch.setattr(prompt_history, "emit_audit_event", lambda **kwargs: None)
    result = client.post(f"/skills/{skill.slug}/prompt-history/restore", json=body)
    assert result.status_code == 503
    db_session.refresh(skill)
    assert skill.executor == original


@pytest.mark.parametrize(
    "kind, expected", [("changed", 409), ("foreign", 404), ("missing_placeholder", 400)]
)
def test_restore_refuses_stale_foreign_or_incompatible_instructions(
    history, db_session, kind, expected
):
    client, workspace, user, skill, system, version = history
    body = body_for(client, skill)
    original = copy.deepcopy(skill.executor)
    if kind == "changed":
        body["expected_current_sha256"] = "0" * 64
    elif kind == "foreign":
        other = Workspace(id="other-ws", name="Other", slug="other")
        db_session.add(other)
        db_session.flush()
        version.workspace_id = other.id
    else:
        contract = copy.deepcopy(version.execution_contract)
        contract["nodes"]["compose"]["executor"]["params"]["template"] = "Requires {removed}"
        version.execution_contract = contract
        body["template_sha256"] = canonical_sha256("Requires {removed}")
    db_session.commit()
    result = client.post(f"/skills/{skill.slug}/prompt-history/restore", json=body)
    assert result.status_code == expected, result.text
    db_session.refresh(skill)
    assert skill.executor == original


def test_history_keeps_agent_tools_and_excludes_unpublished_snapshots(history, db_session):
    client, workspace, user, skill, system, version = history
    tool = version.execution_contract["nodes"]["compose"]
    version.execution_contract = {
        "nodes": {"agent": {"tool_contract": {"nodes": {skill.slug: tool}}}}
    }
    db_session.commit()
    data = client.get(f"/skills/{skill.slug}/prompt-history").json()
    assert data["entries"][0]["node_id"] == "agent"
    version.release_kind = "legacy_snapshot"
    db_session.commit()
    assert client.get(f"/skills/{skill.slug}/prompt-history").json()["entries"] == []
