"""The sentinel_ci adapter keeps the intelligence output Sentinel CI had.

``fixtures/sentinel_ci_intelligence_pin.json`` was captured from the code
before Intelligence became a neutral product (ADR 0003, D6: an adapter that
takes over existing behaviour keeps it byte for byte).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.models.intelligence import FeedArticle, FeedSource, SafetyFilter, SemanticTarget
from app.models.workspace import Workspace
from app.services.intelligence import feed_manager
from app.services.intelligence.batch import (
    _build_reference_synthesis,
    ensure_intelligence_defaults,
    get_dashboard_data,
)
from app.services.intelligence.knowledge_sync import _synthesis_markdown
from app.services.intelligence.profile import intelligence_profile

PIN = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "sentinel_ci_intelligence_pin.json").read_text(
        encoding="utf-8"
    )
)
PROFILE = intelligence_profile("sentinel_ci")
INPUTS = PIN["inputs"]
TOP_ENTITIES = [tuple(pair) for pair in INPUTS["top_entities"]]
# The fixture stores keys sorted; the markdown prints the dict in the order the
# capture built it, so that order is restated here.
RISK_COUNTS = {"low": 2, "medium": 1, "high": 2, "critical": 1}
assert RISK_COUNTS == INPUTS["risk_counts"]


def _sentinel_workspace(db_session) -> Workspace:
    workspace = Workspace(
        id="ws-pin", slug="pin-sentinel", name="Pin", mode="demo", settings={"family": "sentinel_ci"}
    )
    db_session.add(workspace)
    db_session.commit()
    return workspace


def test_collection_prompts_and_user_agent_are_unchanged():
    assert {
        "slug": PROFILE.collection_slug,
        "name": PROFILE.collection_name,
        "description": PROFILE.collection_description,
    } == PIN["collection"]
    assert PROFILE.analysis_prompt == PIN["analysis_prompt"]
    assert PROFILE.safety_prompt == PIN["safety_prompt"]
    assert {**feed_manager.RSS_REQUEST_HEADERS, "User-Agent": PROFILE.rss_user_agent} == PIN["rss_headers"]


def test_reference_brief_and_consolidated_markdown_are_unchanged():
    synthesis = _build_reference_synthesis(
        INPUTS["articles"], RISK_COUNTS, TOP_ENTITIES, PROFILE
    )
    assert synthesis == PIN["reference_synthesis"]
    assert _build_reference_synthesis([], {"low": 0}, [], PROFILE) == PIN["empty_reference_synthesis"]

    payload = {
        "kpis": INPUTS["payload_kpis"],
        "risk": RISK_COUNTS,
        "sentiment": {"neutral": 6},  # as captured
        "synthesis": synthesis,
        "articles": INPUTS["articles"],
    }
    assert _synthesis_markdown(payload, PROFILE.consolidated_title) == PIN["synthesis_markdown"]


def test_starters_and_dashboard_brief_are_unchanged(db_session):
    workspace = _sentinel_workspace(db_session)

    assert ensure_intelligence_defaults(db_session, workspace_id=workspace.id) is True
    feeds = sorted(
        (
            {"name": f.name, "url": f.url, "category": f.category, "refresh_interval": f.refresh_interval, "active": f.active}
            for f in db_session.query(FeedSource).filter(FeedSource.workspace_id == workspace.id)
        ),
        key=lambda row: row["url"],
    )
    targets = [
        {"name": t.name, "description": t.description, "keywords": t.keywords, "relevance_threshold": t.relevance_threshold, "active": t.active}
        for t in db_session.query(SemanticTarget).filter(SemanticTarget.workspace_id == workspace.id)
    ]
    filters = [
        {"name": f.name, "prompt_template": f.prompt_template, "severity": f.severity, "active": f.active}
        for f in db_session.query(SafetyFilter).filter(SafetyFilter.workspace_id == workspace.id)
    ]
    assert {"feeds": feeds, "targets": targets, "filters": filters} == PIN["defaults"]

    feed = db_session.query(FeedSource).filter(FeedSource.workspace_id == workspace.id).first()
    db_session.add(
        FeedArticle(
            id="pin-article",
            workspace_id=workspace.id,
            source_id=feed.id,
            title="Pin article",
            url="https://example.test/pin",
            content="Body",
            summary="Pin summary",
            published_at=datetime(2026, 5, 10, 8, 0, 0),
            fetched_at=datetime(2026, 5, 10, 9, 0, 0),
            embedded=True,
            relevance_score=0.5,
            safety_flag="clear",
            analysis={"risk_level": "high", "sentiment": "negative", "entities": ["Abidjan"], "key_findings": ["Finding"]},
        )
    )
    db_session.commit()

    dashboard = get_dashboard_data(db_session, workspace_id=workspace.id)
    assert dashboard["synthesis"] == PIN["dashboard_synthesis"]
    assert dashboard["knowledge_collection"]["slug"] == PIN["collection"]["slug"]
