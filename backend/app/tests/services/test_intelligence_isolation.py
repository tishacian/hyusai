"""Intelligence (News Lab) is isolated per workspace and neutral by default.

Before: articles had no workspace and were de-duplicated by URL across all
workspaces, a batch without a workspace mixed every workspace's feeds,
targets and safety prompts, the skill ran globally without a workspace, and
opening News Lab wrote world-news starters and Sentinel CI wording into any
workspace.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from app.models.intelligence import FeedArticle, FeedSource, SafetyFilter, SemanticTarget
from app.models.workspace import Workspace
from app.services.intelligence import analyzer as analyzer_module
from app.services.intelligence import batch as batch_module
from app.services.intelligence import feed_manager
from app.services.intelligence import scheduler as intel_scheduler
from app.services.intelligence.batch import get_dashboard_data, run_batch
from app.services.intelligence.feed_manager import get_articles, save_articles
from app.services.intelligence.profile import intelligence_profile
from app.services.skills_registry import wrappers

SHARED_URL = "https://news.example/shared"


def _article(url: str, title: str = "Shared story") -> dict:
    import uuid

    return {"id": str(uuid.uuid4()), "title": title, "url": url, "content": "Body", "published_at": None}


def _two_workspaces(db_session) -> tuple[Workspace, Workspace]:
    alpha = Workspace(id="ws-alpha", slug="alpha", name="Alpha")
    beta = Workspace(id="ws-beta", slug="beta", name="Beta")
    db_session.add_all([alpha, beta])
    db_session.add_all(
        [
            FeedSource(id="feed-alpha", workspace_id=alpha.id, name="Alpha feed", url="https://alpha.example/rss", active=True),
            FeedSource(id="feed-beta", workspace_id=beta.id, name="Beta feed", url="https://beta.example/rss", active=True),
            SemanticTarget(id="target-alpha", workspace_id=alpha.id, name="Alpha target", description="ALPHA-TARGET", relevance_threshold=0.1),
            SemanticTarget(id="target-beta", workspace_id=beta.id, name="Beta target", description="BETA-TARGET", relevance_threshold=0.1),
            SafetyFilter(id="filter-alpha", workspace_id=alpha.id, name="Alpha filter", prompt_template="ALPHA-RULE"),
            SafetyFilter(id="filter-beta", workspace_id=beta.id, name="Beta filter", prompt_template="BETA-RULE"),
        ]
    )
    db_session.commit()
    return alpha, beta


def test_two_workspaces_fetching_the_same_url_each_keep_their_article(db_session):
    alpha, beta = _two_workspaces(db_session)

    assert save_articles("feed-alpha", [_article(SHARED_URL)], workspace_id=alpha.id) == 1
    assert save_articles("feed-beta", [_article(SHARED_URL)], workspace_id=beta.id) == 1
    # Same workspace, same URL (again, and twice in one fetch): still one row.
    assert save_articles("feed-alpha", [_article(SHARED_URL), _article(SHARED_URL)], workspace_id=alpha.id) == 0

    rows = db_session.query(FeedArticle).filter(FeedArticle.url == SHARED_URL).all()
    assert sorted(row.workspace_id for row in rows) == [alpha.id, beta.id]


def test_articles_are_never_saved_without_a_workspace(db_session):
    assert save_articles("feed-orphan", [_article("https://orphan.example/a")]) == 0
    assert db_session.query(FeedArticle).count() == 0


def test_reads_never_return_another_workspace_or_unscoped_articles(db_session):
    alpha, beta = _two_workspaces(db_session)
    analysis = {"risk_level": "high", "sentiment": "negative", "entities": ["E"], "key_findings": ["F"]}
    db_session.add_all(
        [
            FeedArticle(id="art-alpha", workspace_id=alpha.id, source_id="feed-alpha", title="Alpha story", url="https://a", embedded=True, analysis=analysis, fetched_at=datetime.utcnow()),
            FeedArticle(id="art-beta", workspace_id=beta.id, source_id="feed-beta", title="Beta story", url="https://b", embedded=True, analysis=analysis, fetched_at=datetime.utcnow()),
            # Joined to Alpha's feed but not stamped: never served.
            FeedArticle(id="art-null", workspace_id=None, source_id="feed-alpha", title="Unscoped story", url="https://n", embedded=True, analysis=analysis, fetched_at=datetime.utcnow()),
        ]
    )
    db_session.commit()

    assert [row["id"] for row in get_articles(db_session, workspace_id=alpha.id)] == ["art-alpha"]
    assert get_articles(db_session) == []

    dashboard = get_dashboard_data(db_session, workspace_id=alpha.id)
    assert dashboard["kpis"]["total_articles"] == 1
    assert [row["id"] for row in dashboard["articles"]] == ["art-alpha"]
    assert get_dashboard_data(db_session)["articles"] == []


class _RecordingAnalyzer:
    def __init__(self) -> None:
        self.targets: list[str] = []
        self.analysis_prompts: list[str] = []
        self.safety: list[tuple[str, str]] = []

    async def compute_relevance(self, text: str, target_description: str) -> float:
        self.targets.append(target_description)
        return 0.9

    async def analyze_article(self, title, content, target_description, prompt_template=None):
        self.analysis_prompts.append(prompt_template)
        return {"entities": [], "sentiment": "neutral", "risk_level": "low", "key_findings": [title]}

    async def check_safety(self, content_summary, filter_rules, prompt_template=None):
        self.safety.append((filter_rules, prompt_template))
        return {"flag": "clear"}


async def _drain(generator) -> list[dict]:
    return [event async for event in generator]


@pytest.mark.asyncio
async def test_batch_only_reads_its_own_workspace(db_session, monkeypatch):
    alpha, beta = _two_workspaces(db_session)
    fetched: list[tuple[str, str]] = []

    async def fake_fetch(url: str, user_agent=None):
        fetched.append((url, user_agent))
        return [_article(SHARED_URL, title=f"Story from {url}")]

    recorder = _RecordingAnalyzer()
    monkeypatch.setattr(feed_manager, "fetch_feed", fake_fetch)
    monkeypatch.setattr(analyzer_module, "get_analyzer", lambda: recorder)
    monkeypatch.setattr(batch_module.settings, "intelligence_batch_safety_check_enabled", True)
    # Beta already holds the shared URL: Alpha must still get its own copy.
    save_articles("feed-beta", [_article(SHARED_URL)], workspace_id=beta.id)

    events = await _drain(run_batch(workspace_id=alpha.id))

    assert events[-1]["type"] == "batch_complete", events
    assert events[-1]["total_articles"] == 1
    assert fetched == [("https://alpha.example/rss", intelligence_profile(None).rss_user_agent)]
    assert set(recorder.targets) == {"ALPHA-TARGET"}
    assert recorder.safety == [("ALPHA-RULE", intelligence_profile(None).safety_prompt)]
    beta_row = db_session.query(FeedArticle).filter(FeedArticle.workspace_id == beta.id).one()
    db_session.refresh(beta_row)
    assert beta_row.analysis is None


@pytest.mark.asyncio
async def test_batch_without_a_workspace_is_refused(db_session, monkeypatch):
    _two_workspaces(db_session)

    async def forbidden_fetch(url: str, user_agent=None):
        raise AssertionError("a batch without a workspace must not fetch anything")

    monkeypatch.setattr(feed_manager, "fetch_feed", forbidden_fetch)

    events = await _drain(run_batch())

    assert [event["type"] for event in events] == ["batch_error"]
    assert events[0]["code"] == "workspace_required"


@pytest.mark.asyncio
async def test_generic_workspace_gets_no_starters_and_is_guided(db_session):
    showcase = Workspace(id="ws-showcase", slug="agentium-showcase", name="Showcase")
    db_session.add(showcase)
    db_session.commit()

    dashboard = get_dashboard_data(db_session, workspace_id=showcase.id)
    no_feed = await _drain(run_batch(workspace_id=showcase.id))
    db_session.add(FeedSource(id="feed-showcase", workspace_id=showcase.id, name="F", url="https://f.example/rss", active=True))
    db_session.commit()
    no_target = await _drain(run_batch(workspace_id=showcase.id))

    for model in (FeedSource, SemanticTarget, SafetyFilter):
        assert db_session.query(model).filter(model.name.contains("(default)")).count() == 0
    assert db_session.query(SemanticTarget).count() == 0
    assert no_feed[-1]["code"] == "no_feed"
    assert no_target[-1]["code"] == "no_target"
    assert dashboard["kpis"]["active_feeds"] == 0
    assert dashboard["knowledge_collection"] == {"slug": "workspace-intelligence", "name": "Workspace intelligence"}
    synthesis = dashboard["synthesis"]
    assert synthesis["knowledge_reference"]["recommended_collection"] == "workspace-intelligence"
    wording = " ".join([synthesis["title"], synthesis["summary"], *synthesis["recommended_actions"]]).lower()
    for word in ("cabinet", "hyperviseur", "aya", "sentinel", "synthese", "verifier"):
        assert word not in wording


def test_generic_profile_is_neutral():
    profile = intelligence_profile("generic")
    text = " ".join(
        [
            profile.collection_slug,
            profile.collection_name,
            profile.collection_description,
            profile.analysis_prompt,
            profile.safety_prompt,
            profile.rss_user_agent,
            profile.consolidated_title,
            profile.brief_title,
            *profile.recommended_actions,
        ]
    ).lower()
    for word in ("sentinel", "aya", "geopolitic", "cabinet", "hyperviseur"):
        assert word not in text
    assert not profile.has_starters
    # Families without an adapter get the neutral profile too.
    assert replace(intelligence_profile("industrial"), family="generic") == intelligence_profile(None)


def test_scheduler_runs_each_workspace_on_its_own(db_session, monkeypatch):
    alpha, beta = _two_workspaces(db_session)
    gone = Workspace(id="ws-gone", slug="gone", name="Gone", is_active=False)
    paused = Workspace(id="ws-paused", slug="paused", name="Paused")
    db_session.add_all(
        [
            gone,
            paused,
            FeedSource(id="feed-gone", workspace_id=gone.id, name="G", url="https://g.example/rss", active=True),
            FeedSource(id="feed-paused", workspace_id=paused.id, name="P", url="https://p.example/rss", active=False),
            FeedSource(id="feed-null", workspace_id=None, name="N", url="https://n.example/rss", active=True),
            FeedSource(id="feed-alpha-2", workspace_id=alpha.id, name="A2", url="https://a2.example/rss", active=True),
        ]
    )
    db_session.commit()
    calls: list[str | None] = []

    async def fake_run_batch(target_id=None, workspace_id=None):
        calls.append(workspace_id)
        yield {"type": "batch_complete", "analyzed": 0}

    monkeypatch.setattr(batch_module, "run_batch", fake_run_batch)

    intel_scheduler._run_batch_sync()

    assert calls == [alpha.id, beta.id]


@pytest.mark.asyncio
async def test_skill_refuses_to_run_without_a_workspace(monkeypatch):
    async def forbidden_batch(**_kwargs):
        raise AssertionError("must not run")
        yield  # pragma: no cover

    monkeypatch.setattr(batch_module, "run_batch", forbidden_batch)

    with pytest.raises(ValueError, match="workspace"):
        await wrappers._intelligence_batch_v1({"workspace_id": "ws-from-payload"}, {})
    with pytest.raises(ValueError, match="workspace"):
        await wrappers._intelligence_batch_v1({}, None)
