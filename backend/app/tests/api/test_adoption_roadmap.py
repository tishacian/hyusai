"""Adoption is personal; scope and retry safety are server contracts."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.v1.endpoints import auth, help_content, assistant
from app.models.workspace import WorkspaceMember, Workspace
from app.models.system import System
from app.models.user import User
from app.models.assistant_request import AssistantRequest
from app.models.audit import AuditLog
from app.tests.api.test_assistant_turns_api import _seed, _client, FakeToolClient
from app.services.assistant import engine


def test_operational_objective_write_uses_system_admin_guard_and_preserves_settings(db_session):
    from app.api.v1.endpoints import systems

    workspace, user = _seed(db_session)
    member = db_session.query(WorkspaceMember).filter_by(user_id=user.id).one()
    member.role = "owner"
    member.role_template = "workspace_owner"
    system = System(
        id="objective",
        workspace_id=workspace.id,
        name="Objective",
        settings={"existing_contract": {"keep": True}},
    )
    db_session.add(system)
    db_session.commit()
    app = FastAPI()
    app.include_router(systems.router, prefix="/systems")
    app.dependency_overrides[systems.get_current_workspace] = lambda: workspace
    app.dependency_overrides[systems.get_current_user] = lambda: user
    app.dependency_overrides[systems.get_db] = lambda: db_session
    client = TestClient(app)
    url = "/systems/objective/operational-objective"
    objective = dict(
        metric="completed_volume",
        target=4,
        period_start="2026-09-01",
        period_end="2026-09-08",
        owner="Ops",
        comparison_reference="Previous week",
    )
    response = client.put(url, json=objective)
    assert response.status_code == 200, response.text
    assert system.settings["existing_contract"] == {"keep": True}
    assert client.get("/systems/objective/operational-metrics").json()["can_edit"] is True
    member.role = "member"
    member.role_template = "workspace_viewer"
    db_session.commit()
    assert client.put(url, json={**objective, "target": 10}).status_code == 403
    assert client.patch("/systems/objective", json={"settings": {"operational_objective": None}}).status_code == 403
    assert client.patch("/systems/objective", json={"settings": {"operational_objective": {**objective, "target": 10}}}).status_code == 403
    assert client.patch("/systems/objective", json={"settings": {"unrelated": True}}).status_code == 200
    assert client.post("/systems", json={"name": "Unauthorized objective", "settings": {"operational_objective": objective}}).status_code == 403
    assert client.get("/systems/objective/operational-metrics").json()["can_edit"] is False
    assert system.settings["operational_objective"]["target"] == 4
    assert client.get("/systems/foreign/operational-metrics").status_code == 404


def auth_client(db, workspace, user):
    app = FastAPI()
    app.include_router(auth.router, prefix="/auth")
    app.include_router(help_content.router, prefix="/help-content")
    app.dependency_overrides[auth.get_current_user] = lambda: user
    app.dependency_overrides[auth.get_db] = lambda: db
    return TestClient(app)


def test_progress_is_per_member_and_workspace_and_never_changes_access(db_session):
    workspace, user = _seed(db_session)
    other = User(id="another", username="another@example.test")
    db_session.add_all(
        [other, WorkspaceMember(user_id=other.id, workspace_id=workspace.id, role="member")]
    )
    db_session.commit()
    client = auth_client(db_session, workspace, user)
    url = "/auth/workspaces/assistant-api/me/experience"
    assert client.get(url).json()["completed_steps"] == []
    for step in ["example", "question", "source", "source"]:
        assert (
            client.patch(url, json={"persona": "builder", "completed_step": step}).status_code
            == 200
        )
    assert client.patch(url, json={"dismissed": True}).json()["dismissed"] is True
    assert client.get(url).json()["completed_steps"] == ["example", "question", "source"]
    assert auth_client(db_session, workspace, other).get(url).json()["completed_steps"] == []
    assert client.patch(url, json={"role": "owner"}).status_code == 422
    assert client.patch(url, json={"system_ids": ["hidden"]}).status_code == 422
    assert client.patch(url, json={"session_id": "not-owned"}).status_code == 404
    assert (
        db_session.query(WorkspaceMember).filter_by(user_id=user.id).one().role_template
        == "workspace_contributor"
    )
    assert all(
        "text" not in row.details
        for row in db_session.query(AuditLog).filter_by(event_type="adoption.progress")
    )
    foreign = Workspace(id="foreign", slug="foreign", name="Foreign")
    db_session.add(foreign)
    db_session.commit()
    assert client.get("/auth/workspaces/foreign/me/experience").status_code == 403


def test_rail_labels_default_to_auto_and_first_seen_is_recorded_once(db_session):
    from datetime import datetime, timezone

    workspace, user = _seed(db_session)
    client = auth_client(db_session, workspace, user)
    url = "/auth/workspaces/assistant-api/me/experience"

    first = client.get(url).json()
    assert first["rail_labels"] == "auto"
    first_seen = first["first_seen_at"]
    assert first_seen, "the first read records when the member was first seen"
    seen_at = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
    assert abs((datetime.now(timezone.utc) - seen_at).total_seconds()) < 60
    stored = db_session.query(WorkspaceMember).filter_by(user_id=user.id).one()
    assert stored.experience_progress["first_seen_at"] == first_seen

    # Stable across reads and across writes of any other field.
    assert client.get(url).json()["first_seen_at"] == first_seen
    assert client.patch(url, json={"persona": "builder"}).json()["first_seen_at"] == first_seen
    assert client.get(url).json()["first_seen_at"] == first_seen


def test_first_seen_starts_when_the_member_joined(db_session):
    from datetime import datetime, timedelta

    workspace, user = _seed(db_session)
    member = db_session.query(WorkspaceMember).filter_by(user_id=user.id).one()
    member.joined_at = datetime(2026, 7, 1, 9, 30, 0)
    member.experience_progress = {}
    db_session.commit()
    client = auth_client(db_session, workspace, user)
    url = "/auth/workspaces/assistant-api/me/experience"

    # A long-standing member keeps their seniority: the newcomer period is
    # counted from the join date, not from the first read after a deploy.
    body = client.get(url).json()
    assert datetime.fromisoformat(body["first_seen_at"].replace("Z", "+00:00")).replace(tzinfo=None) == member.joined_at
    assert datetime.utcnow() - member.joined_at > timedelta(days=14)


def test_first_seen_is_never_overwritten_nor_accepted_from_the_client(db_session):
    workspace, user = _seed(db_session)
    member = db_session.query(WorkspaceMember).filter_by(user_id=user.id).one()
    member.experience_progress = {"persona": "executive", "first_seen_at": "2026-01-02T03:04:05Z"}
    db_session.commit()
    client = auth_client(db_session, workspace, user)
    url = "/auth/workspaces/assistant-api/me/experience"

    body = client.get(url).json()
    assert body["first_seen_at"] == "2026-01-02T03:04:05Z"
    assert body["persona"] == "executive"
    assert body["rail_labels"] == "auto"
    assert client.patch(url, json={"first_seen_at": "2030-01-01T00:00:00Z"}).status_code == 422
    assert client.get(url).json()["first_seen_at"] == "2026-01-02T03:04:05Z"


def test_rail_labels_patch_is_validated_and_leaves_other_fields_untouched(db_session):
    workspace, user = _seed(db_session)
    client = auth_client(db_session, workspace, user)
    url = "/auth/workspaces/assistant-api/me/experience"
    client.get(url)
    assert client.patch(url, json={"persona": "builder", "completed_step": "example"}).status_code == 200
    assert client.patch(url, json={"dismissed": True}).status_code == 200
    before = client.get(url).json()

    for invalid in ["sometimes", "", None, True, 1]:
        response = client.patch(url, json={"rail_labels": invalid})
        if invalid is None:
            # ``null`` means "no change", like every other optional field.
            assert response.status_code == 200
        else:
            assert response.status_code == 422, invalid
    assert client.get(url).json() == before

    for value in ["hidden", "shown", "auto"]:
        response = client.patch(url, json={"rail_labels": value})
        assert response.status_code == 200, response.text
        after = response.json()
        assert after["rail_labels"] == value
        assert {k: v for k, v in after.items() if k != "rail_labels"} == {
            k: v for k, v in before.items() if k not in {"rail_labels", "example_available"}
        }
    assert client.get(url).json()["rail_labels"] == "auto"
    audited = [
        row.details
        for row in db_session.query(AuditLog).filter_by(event_type="adoption.progress")
        if "rail_labels" in row.details
    ]
    assert [row["rail_labels"] for row in audited] == ["hidden", "shown", "auto"]


def test_all_published_help_guides_resolve_in_both_languages(db_session):
    workspace, user = _seed(db_session)
    client = auth_client(db_session, workspace, user)
    import yaml
    from pathlib import Path

    content = yaml.safe_load(
        (Path(help_content.__file__).resolve().parents[3] / "content/help_content.yaml").read_text()
    )

    def links(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "learn_more" and isinstance(item, str):
                    yield item
                else:
                    yield from links(item)
        elif isinstance(value, list):
            for item in value:
                yield from links(item)

    for link in links(content):
        assert link.startswith("/help/"), link
        for lang in ["en", "fr"]:
            response = client.get(
                "/help-content/guides/" + link.split("/")[-1], params={"language": lang}
            )
            assert response.status_code == 200, response.text
            assert response.json()["paragraphs"]
            assert response.json()["language"] == lang
    assert client.get("/help-content/guides/missing").status_code == 404


def test_assistant_retry_returns_same_response_without_calling_model_twice(db_session, monkeypatch):
    workspace, user = _seed(db_session)
    fake = FakeToolClient(
        [{"content": "No systems were run.", "tool_calls": [], "finish_reason": "stop"}]
    )
    monkeypatch.setattr(engine, "build_model_client", lambda config: fake)
    client = _client(db_session, workspace, user)
    body = {
        "text": "Find the examples",
        "surface": "pilot",
        "system_ids": [],
        "request_id": "request-123",
    }
    first = client.post("/assistant/turns", json=body)
    assert first.status_code == 200, first.text
    assert client.post("/assistant/turns", json=body).json() == first.json()
    assert len(fake.calls) == 1
    assert client.post("/assistant/turns", json={**body, "text": "different"}).status_code == 409
    assert db_session.query(AssistantRequest).one().state == "completed"


def test_scope_changes_require_a_new_conversation_and_foreign_systems_are_refused(
    db_session, monkeypatch
):
    workspace, user = _seed(db_session)
    db_session.add_all(
        [
            System(id="one", workspace_id=workspace.id, name="One"),
            System(id="two", workspace_id=workspace.id, name="Two"),
            System(id="foreign", workspace_id="elsewhere", name="Hidden"),
        ]
    )
    db_session.commit()
    monkeypatch.setattr(
        engine,
        "build_model_client",
        lambda config: FakeToolClient([{"content": "Read only", "tool_calls": []}]),
    )
    client = _client(db_session, workspace, user)
    body = {
        "text": "Explain",
        "surface": "pilot",
        "system_ids": ["one"],
        "request_id": "request-scope-one",
    }
    first = client.post("/assistant/turns", json=body)
    assert first.status_code == 200, first.text
    second = client.post(
        "/assistant/turns",
        json={
            **body,
            "system_ids": ["two"],
            "session_id": first.json()["session_id"],
            "request_id": "request-scope-two",
        },
    )
    assert second.status_code == 400, second.text
    assert (
        client.post("/assistant/turns", json={**body, "system_ids": ["foreign"]}).status_code == 404
    )
    assert (
        client.post("/assistant/turns", json={"text": "run", "surface": "pilot"}).status_code == 422
    )


def test_pending_request_never_restarts_an_uncertain_operation(db_session, monkeypatch):
    workspace, user = _seed(db_session)
    body = assistant.AssistantTurnRequest(
        text="Execute", surface="pilot", system_ids=[], request_id="pending-123"
    )
    import hashlib

    fingerprint = hashlib.sha256(body.model_dump_json(exclude={"request_id"}).encode()).hexdigest()
    db_session.add(
        AssistantRequest(
            id="receipt",
            workspace_id=workspace.id,
            user_id=user.id,
            request_id=body.request_id,
            fingerprint=fingerprint,
            state="pending",
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        engine, "build_model_client", lambda config: pytest.fail("must not call model")
    )
    response = _client(db_session, workspace, user).post("/assistant/turns", json=body.model_dump())
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "request_pending"
