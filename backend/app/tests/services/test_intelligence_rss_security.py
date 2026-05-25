from __future__ import annotations

import json
from datetime import datetime

import pytest

from app.models.workspace import Workspace
from app.services.intelligence import cache as intel_cache
from app.services.intelligence import rss_security


SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>Tension militaire au Sahel apres une attaque frontaliere</title>
<link>https://example.test/sahel-1</link>
<description>Forces en alerte dans la region.</description>
<pubDate>Mon, 25 May 2026 12:00:00 GMT</pubDate></item>
<item><title>Accord de cooperation economique en Cote d'Ivoire</title>
<link>https://example.test/ci-1</link>
<description>Investissement et croissance.</description></item>
</channel></rss>"""


@pytest.fixture(autouse=True)
def _clear_intel_cache():
    intel_cache.clear_memory_cache()
    yield
    intel_cache.clear_memory_cache()


def test_score_security_text_prioritizes_security_keywords():
    scored = rss_security.score_security_text("Attaque militaire et tension frontiere Sahel")
    assert scored["score"] >= 55
    assert scored["tone"] in {"watch", "critical"}


def test_parse_rss_items_extracts_titles():
    items = rss_security._parse_rss_items(SAMPLE_RSS)
    assert len(items) == 2
    assert "Sahel" in items[0]["title"]


def test_sync_rss_security_deduplicates_and_caches(monkeypatch):
    seen_urls: set[str] = set()

    def fake_fetch(url: str, *, timeout: float = 8.0):
        seen_urls.add(url)
        return rss_security._parse_rss_items(SAMPLE_RSS)

    monkeypatch.setattr(rss_security, "_fetch_feed", fake_fetch)
    monkeypatch.setattr(
        rss_security,
        "_load_feeds_config",
        lambda: [{"id": "test-feed", "name": "Test", "url": "https://example.test/rss"}],
    )

    first = rss_security.sync_rss_security(force=True)
    second = rss_security.sync_rss_security(force=False)

    assert first["live"] is True
    assert first["article_count"] == 2
    assert len(first["signals"]) >= 1
    assert second["article_count"] == 2
    assert seen_urls  # fetched once on force


def test_rss_security_payload_respects_allow_live():
    payload = {
        "live": True,
        "source_badge": "LIVE",
        "signals": [{"id": "sig-1", "label": "Test"}],
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }
    intel_cache.cache_set(rss_security.CACHE_KEY, payload, 900)
    assert rss_security.rss_security_payload(allow_live=True) is not None
    assert rss_security.rss_security_payload(allow_live=False) is None
