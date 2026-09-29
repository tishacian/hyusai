"""L33 — GET /work/_home: rights, workspace isolation, receipts, no N+1."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import event

from app.core.iam.roles import WORKSPACE_REVIEWER
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.iam.config_service import load_iam_config
from app.tests.api.test_work_api import (
    _client,
    _experiences_client,
    _publish,
    _seed,
    _seed_binding,
)

ORIGIN = {"_ingress": {"adapter": {"origin": "experience:password-reset"}}}


def _member(db_session, workspace: Workspace, *, user_id: str, role_template: str) -> User:
    user = User(
        id=user_id,
        username=f"{user_id}@example.invalid",
        email=f"{user_id}@example.invalid",
        role="member",
    )
    db_session.add_all(
        [
            user,
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=user.id,
                role="member",
                role_template=role_template,
            ),
        ]
    )
    db_session.commit()
    return user


def _app(db_session):
    workspace, admin = _seed(db_session)
    system, _version, _binding = _seed_binding(db_session, workspace, admin)
    _publish(
        _experiences_client(db_session, workspace, admin),
        binding_key="work.reset",
        channel="live",
    )
    return workspace, admin, system


def _pause(run_id: str, *, workspace_id: str, system_id: str, owner: str, started: datetime, title: str) -> Run:
    return Run(
        id=run_id,
        workspace_id=workspace_id,
        system_id=system_id,
        initiated_by_user_id=owner,
        status="hitl_pending",
        started_at=started,
        input_ref=ORIGIN,
        checkpoints=[{"kind": "hitl_pause", "prompt": title, "decision_title": title}],
    )


def _done(run_id: str, *, workspace_id: str, system_id: str, owner: str, completed: datetime) -> Run:
    start = completed - timedelta(seconds=30)
    return Run(
        id=run_id,
        workspace_id=workspace_id,
        system_id=system_id,
        initiated_by_user_id=owner,
        status="completed",
        started_at=start,
        completed_at=completed,
        duration_ms=30_000,
        input_ref=ORIGIN,
        output_ref={"citations": [{"id": "c1"}, {"id": "c2"}]},
        checkpoints=[
            {"kind": "run_start", "t": start.isoformat()},
            {"kind": "node_start", "node_id": "a", "t": start.isoformat()},
            {"kind": "node_end", "node_id": "a", "t": (start + timedelta(seconds=4)).isoformat()},
            {"kind": "hitl_pause", "node_id": "gate", "t": (start + timedelta(seconds=4)).isoformat()},
            {"kind": "hitl_resume", "node_id": "gate", "t": (start + timedelta(seconds=24)).isoformat()},
            {"kind": "node_end", "node_id": "b", "t": (start + timedelta(seconds=30)).isoformat()},
        ],
    )


def test_home_decisions_follow_the_reader_rights_and_oldest_first(db_session) -> None:
    workspace, admin, system = _app(db_session)
    viewer = _member(db_session, workspace, user_id="home-viewer", role_template="workspace_viewer")
    db_session.add_all(
        [
            _pause("home-new", workspace_id=workspace.id, system_id=system.id, owner=viewer.id,
                   started=datetime(2026, 3, 2, 10), title="Newer"),
            _pause("home-old", workspace_id=workspace.id, system_id=system.id, owner=viewer.id,
                   started=datetime(2026, 3, 1, 10), title="Older"),
            _pause("home-admin", workspace_id=workspace.id, system_id=system.id, owner=admin.id,
                   started=datetime(2026, 2, 1, 10), title="Admin only"),
        ]
    )
    db_session.commit()

    body = _client(db_session, workspace, viewer).get("/work/_home")
    assert body.status_code == 200, body.text
    home = body.json()
    decisions = home["decisions"]
    assert decisions["count"] == 2
    assert [item["run_id"] for item in decisions["items"]] == ["home-old", "home-new"]
    assert decisions["oldest_at"] == datetime(2026, 3, 1, 10).isoformat()
    assert decisions["items"][0]["title"] == "Older"
    assert decisions["items"][0]["source"] == {"kind": "app", "slug": "password-reset", "name": "Password reset"}
    # Same count the catalogue shows this reader for the app (L17).
    catalog = _client(db_session, workspace, viewer).get("/work").json()
    assert catalog["experiences"][0]["pending_decisions"]["count"] == decisions["count"]
    # A plain member cannot review: the field is unknown, not zero.
    assert home["reviews"] is None

    admin_home = _client(db_session, workspace, admin).get("/work/_home").json()
    assert admin_home["decisions"]["count"] == 3
    assert admin_home["decisions"]["items"][0]["run_id"] == "home-admin"


def test_home_never_shows_another_workspace(db_session) -> None:
    workspace, admin, system = _app(db_session)
    other = Workspace(id="ws-home-other", slug="home-other", name="Other", settings={})
    db_session.add(other)
    db_session.commit()
    now = datetime.utcnow()
    db_session.add_all(
        [
            # Same origin and system id, foreign tenant: must never surface.
            _pause("home-foreign-pause", workspace_id=other.id, system_id=system.id, owner=admin.id,
                   started=now - timedelta(hours=1), title="Foreign"),
            _done("home-foreign-done", workspace_id=other.id, system_id=system.id, owner=admin.id,
                  completed=now - timedelta(hours=1)),
            Decision(id="home-foreign-review", workspace_id=other.id, kind="review_required",
                     status="proposed", title="Foreign review", scope="run", target_id="home-foreign-done"),
        ]
    )
    db_session.commit()

    home = _client(db_session, workspace, admin).get("/work/_home").json()
    assert home["decisions"]["count"] == 0
    assert home["agent_work"]["items"] == []
    assert home["reviews"] == {"count": 0, "oldest_at": None, "items": []}


def test_home_agent_work_is_this_week_with_measured_receipts(db_session) -> None:
    workspace, admin, system = _app(db_session)
    now = datetime.utcnow()
    db_session.add_all(
        [
            _done("home-week", workspace_id=workspace.id, system_id=system.id, owner=admin.id,
                  completed=now - timedelta(days=1)),
            _done("home-stale", workspace_id=workspace.id, system_id=system.id, owner=admin.id,
                  completed=now - timedelta(days=9)),
        ]
    )
    db_session.flush()
    db_session.add_all(
        [
            SkillInvocation(run_id="home-week", skill_slug="semantic_search_v1",
                            output_ref={"results": [{}, {}, {}]}),
            SkillInvocation(run_id="home-week", skill_slug="sap_create_po_v1",
                            output_ref={"sealed": True, "called": False}),
        ]
    )
    db_session.commit()

    items = _client(db_session, workspace, admin).get("/work/_home").json()["agent_work"]["items"]
    assert [item["run_id"] for item in items] == ["home-week"]
    assert items[0]["source"]["slug"] == "password-reset"
    # 30 s wall clock minus the 20 s the gate waited for a human.
    assert items[0]["receipt"] == {
        "steps": 2,
        "agent_ms": 10_000,
        "write": "sealed",
        "passages_read": 3,
        "passages_cited": 2,
    }


def test_home_reviews_are_for_reviewers_only(db_session) -> None:
    workspace, admin, system = _app(db_session)
    reviewer = _member(db_session, workspace, user_id="home-reviewer", role_template=WORKSPACE_REVIEWER)
    member = _member(db_session, workspace, user_id="home-member", role_template="workspace_contributor")
    now = datetime.utcnow()
    db_session.add(
        _done("home-reviewed", workspace_id=workspace.id, system_id=system.id, owner=admin.id,
              completed=now - timedelta(hours=3))
    )
    db_session.add(
        Decision(id="home-review", workspace_id=workspace.id, kind="review_required", status="proposed",
                 title="Complete the grade", scope="run", target_id="home-reviewed",
                 created_at=now - timedelta(hours=2))
    )
    db_session.commit()

    reviews = _client(db_session, workspace, reviewer).get("/work/_home").json()["reviews"]
    assert reviews["count"] == 1
    assert reviews["items"][0]["decision_id"] == "home-review"
    assert reviews["items"][0]["title"] == "Complete the grade"
    assert reviews["items"][0]["source"]["name"] == "Password reset"
    assert _client(db_session, workspace, member).get("/work/_home").json()["reviews"] is None


def test_home_query_count_does_not_grow_with_items(db_session) -> None:
    workspace, admin, system = _app(db_session)
    # A configured workspace: without an IAM row the rights engine re-reads the
    # (absent) config per resource — a pre-existing cost outside this endpoint.
    load_iam_config(db_session, workspace.id, create=True)
    db_session.commit()
    client = _client(db_session, workspace, admin)
    now = datetime.utcnow()

    def seed(prefix: str, n: int) -> None:
        for index in range(n):
            run_id = f"{prefix}-{index}"
            db_session.add(_done(run_id, workspace_id=workspace.id, system_id=system.id, owner=admin.id,
                                 completed=now - timedelta(hours=index + 1)))
            db_session.add(_pause(f"{run_id}-p", workspace_id=workspace.id, system_id=system.id,
                                  owner=admin.id, started=now - timedelta(hours=index + 1), title="Gate"))
            db_session.flush()
            db_session.add(SkillInvocation(run_id=run_id, skill_slug="semantic_search_v1",
                                           output_ref={"results": [{}]}))
        db_session.commit()

    engine = db_session.get_bind()
    statements: list[str] = []

    def count(_conn, _cursor, statement, *_args):
        statements.append(statement)

    seed("home-one", 1)
    event.listen(engine, "before_cursor_execute", count)
    try:
        assert client.get("/work/_home").status_code == 200
        few = len(statements)
        seed("home-many", 4)
        statements.clear()
        assert client.get("/work/_home").status_code == 200
        many = len(statements)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert many <= few, (few, many)
