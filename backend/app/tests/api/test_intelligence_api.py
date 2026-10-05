"""Intelligence endpoints serve the current workspace only, and create the watch on demand."""
from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.endpoints import intelligence as intelligence_endpoint
from app.models.capability import Capability
from app.models.intelligence import FeedArticle, FeedSource, SafetyFilter, SemanticTarget
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.intelligence.systems import INTELLIGENCE_TEMPLATE_ID
from app.services.systems.bootstrap import INTELLIGENCE_CAPABILITY_SLUG, INTELLIGENCE_SYSTEM_NAME


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(intelligence_endpoint.router, prefix="/api/v1/intelligence")
    app.dependency_overrides[intelligence_endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[intelligence_endpoint.get_current_user] = lambda: user
    app.dependency_overrides[intelligence_endpoint.get_db] = lambda: db_session
    return TestClient(app)


def _seed(db_session):
    alpha = Workspace(id="ws-alpha", slug="alpha", name="Alpha")
    beta = Workspace(id="ws-beta", slug="beta", name="Beta")
    user = User(id="user-intel", username="analyst", email="analyst@example.test", is_active=True)
    analysis = {"risk_level": "low", "sentiment": "neutral", "entities": [], "key_findings": ["k"]}
    rows = [alpha, beta, user]
    for owner, tag in ((alpha.id, "alpha"), (beta.id, "beta"), (None, "null")):
        rows += [
            FeedSource(id=f"feed-{tag}", workspace_id=owner, name=f"{tag} feed", url=f"https://{tag}.example/rss", active=True, last_fetched=datetime(2026, 10, 1)),
            SemanticTarget(id=f"target-{tag}", workspace_id=owner, name=f"{tag} target", description=tag),
            SafetyFilter(id=f"filter-{tag}", workspace_id=owner, name=f"{tag} filter", prompt_template=tag),
            FeedArticle(id=f"article-{tag}", workspace_id=owner, source_id=f"feed-{tag}", title=f"{tag} story", url=f"https://{tag}.example/a", embedded=True, analysis=analysis, fetched_at=datetime.utcnow()),
        ]
    # Pre-120 row joined to Alpha's feed but never stamped.
    rows.append(FeedArticle(id="article-unstamped", workspace_id=None, source_id="feed-alpha", title="unstamped", url="https://alpha.example/u", embedded=True, analysis=analysis, fetched_at=datetime.utcnow()))
    db_session.add_all(rows)
    db_session.commit()
    return alpha, beta, user


def test_reads_are_scoped_to_the_current_workspace(db_session):
    alpha, _beta, user = _seed(db_session)
    client = _client(db_session, alpha, user)

    assert [row["id"] for row in client.get("/api/v1/intelligence/feeds").json()["feeds"]] == ["feed-alpha"]
    assert [row["id"] for row in client.get("/api/v1/intelligence/targets").json()["targets"]] == ["target-alpha"]
    assert [row["id"] for row in client.get("/api/v1/intelligence/filters").json()["filters"]] == ["filter-alpha"]
    assert [row["id"] for row in client.get("/api/v1/intelligence/articles").json()["articles"]] == ["article-alpha"]
    # Filtering by another workspace's feed id does not reach its rows.
    assert client.get("/api/v1/intelligence/articles", params={"source_id": "feed-beta"}).json()["articles"] == []
    dashboard = client.get("/api/v1/intelligence/dashboard").json()
    assert [row["id"] for row in dashboard["articles"]] == ["article-alpha"]
    assert dashboard["kpis"]["active_feeds"] == 1
    assert dashboard["knowledge_collection"]["slug"] == "workspace-intelligence"


def test_deleting_a_feed_removes_its_articles_in_this_workspace_only(db_session):
    alpha, beta, user = _seed(db_session)

    assert _client(db_session, beta, user).delete("/api/v1/intelligence/feeds/feed-alpha").json() == {"deleted": True}
    assert db_session.query(FeedSource).filter(FeedSource.id == "feed-alpha").count() == 1

    _client(db_session, alpha, user).delete("/api/v1/intelligence/feeds/feed-alpha")
    assert db_session.query(FeedSource).filter(FeedSource.id == "feed-alpha").count() == 0
    assert db_session.query(FeedArticle).filter(FeedArticle.id == "article-alpha").count() == 0
    assert db_session.query(FeedArticle).filter(FeedArticle.id == "article-beta").count() == 1


def test_scheduler_status_is_workspace_scoped(db_session):
    alpha, _beta, user = _seed(db_session)

    body = _client(db_session, alpha, user).get("/api/v1/intelligence/scheduler").json()

    assert body["workspace_active_feeds"] == 1
    assert body["workspace_last_fetched"] == "2026-10-01T00:00:00"
    assert {"running", "enabled", "interval_seconds"} <= set(body)

    unauthenticated = FastAPI()
    unauthenticated.include_router(intelligence_endpoint.router, prefix="/api/v1/intelligence")
    unauthenticated.dependency_overrides[intelligence_endpoint.get_db] = lambda: db_session
    assert TestClient(unauthenticated).get("/api/v1/intelligence/scheduler").status_code in {401, 403}


def _capability(db_session) -> Capability:
    capability = Capability(
        slug=INTELLIGENCE_CAPABILITY_SLUG,
        name="Market Signal Brief",
        description="Intelligence brief",
        tier="universal",
        input_unit="feed_batch",
        output_unit="brief",
        skill_ids=[],
    )
    db_session.add(capability)
    db_session.commit()
    return capability


def test_watch_lists_only_marked_systems_and_creates_one_on_demand(db_session):
    alpha, beta, user = _seed(db_session)
    capability = _capability(db_session)
    db_session.add_all(
        [
            # Unrelated Systems never show up as watches, whatever their name.
            System(workspace_id=alpha.id, name="Competitive intelligence notes", capability_id=capability.id, flow_definition={}, status="active"),
            System(workspace_id=alpha.id, name="Veille", capability_id=capability.id, flow_definition={"variant": "intelligence"}, status="active"),
            System(id="sys-beta-watch", workspace_id=beta.id, name="Beta watch", capability_id=capability.id, flow_definition={"template_id": INTELLIGENCE_TEMPLATE_ID}, status="active"),
        ]
    )
    db_session.commit()
    client = _client(db_session, alpha, user)

    empty = client.get("/api/v1/intelligence/watch").json()
    created = client.post("/api/v1/intelligence/watch").json()
    again = client.post("/api/v1/intelligence/watch").json()
    listed = client.get("/api/v1/intelligence/watch").json()

    assert empty["systems"] == []
    assert empty["can_create"] is True
    assert created["created"] is True
    assert created["system"]["name"] == INTELLIGENCE_SYSTEM_NAME
    assert created["system"]["template_id"] == INTELLIGENCE_TEMPLATE_ID
    assert again == {"system": created["system"], "created": False}
    assert [row["id"] for row in listed["systems"]] == [created["system"]["id"]]
    assert db_session.query(System).filter(System.workspace_id == alpha.id, System.name == INTELLIGENCE_SYSTEM_NAME).count() == 1


def test_watch_lists_the_legacy_template_first_and_adopts_an_unmarked_seed(db_session):
    alpha, _beta, user = _seed(db_session)
    capability = _capability(db_session)
    seeded = System(workspace_id=alpha.id, name=INTELLIGENCE_SYSTEM_NAME, capability_id=capability.id, flow_definition={"variant": "intelligence", "nodes": [], "edges": []}, status="active", created_by="system:intelligence_seed")
    db_session.add(seeded)
    db_session.commit()
    client = _client(db_session, alpha, user)

    adopted = client.post("/api/v1/intelligence/watch").json()

    assert adopted["system"]["id"] == seeded.id
    assert db_session.query(System).filter(System.workspace_id == alpha.id).count() == 1

    legacy = System(workspace_id=alpha.id, name="Veille Presse", capability_id=capability.id, flow_definition={"variant": "intelligence", "template_id": "sentinel-ci-intelligence"}, status="active")
    db_session.add(legacy)
    db_session.commit()
    assert [row["id"] for row in client.get("/api/v1/intelligence/watch").json()["systems"]] == [legacy.id, seeded.id]


def test_watch_creation_needs_the_right_to_create_systems(db_session, monkeypatch):
    alpha, _beta, user = _seed(db_session)
    _capability(db_session)

    class _Denied:
        effective_allowed = False

    def deny_admin(*_args, action: str, **_kwargs):
        if action == "admin":
            raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(intelligence_endpoint, "enforce_action", deny_admin)
    monkeypatch.setattr(intelligence_endpoint, "resolve_action", lambda *_a, **_k: _Denied())
    client = _client(db_session, alpha, user)

    assert client.get("/api/v1/intelligence/watch").json()["can_create"] is False
    assert client.post("/api/v1/intelligence/watch").status_code == 403
    assert db_session.query(System).filter(System.workspace_id == alpha.id).count() == 0
