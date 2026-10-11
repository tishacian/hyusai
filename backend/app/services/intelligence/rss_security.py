"""Security RSS sync for SENTINEL-CI OSINT live (Vague 2.2).

Whitelist feeds from ``security-feeds.json``, keyword scoring (FR/EN),
deduplication by title hash, 15-minute Redis cache.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree

import httpx

from app.core.logging import get_logger
from app.services.intelligence.cache import cache_get, cache_set

logger = get_logger(__name__)

CACHE_KEY = "intelligence:security:rss:v1"
CACHE_TTL_SECONDS = 900

FEEDS_RESOURCE = (
    Path(__file__).resolve().parents[2] / "resources" / "security" / "security-feeds.json"
)

RSS_HEADERS = {
    "User-Agent": "Agentium-SENTINEL-CI/1.0 (+https://agentium.papai.ai)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

POSITIVE_FR = {
    "cooperation",
    "accord",
    "paix",
    "stabilite",
    "investissement",
    "croissance",
    "coordination",
}
NEGATIVE_FR = {
    "attaque",
    "attentat",
    "tension",
    "crise",
    "manifestation",
    "greve",
    "incursion",
    "menace",
    "conflit",
    "insurrection",
    "terrorisme",
    "coup",
    "frontiere",
    "sahel",
    "defense",
    "militaire",
    "armee",
}
NEGATIVE_EN = {
    "attack",
    "terror",
    "conflict",
    "crisis",
    "military",
    "defense",
    "defence",
    "border",
    "sahel",
    "unrest",
    "coup",
    "insurgent",
}

_ITEM_RE = re.compile(r"<item\b[^>]*>(.*?)</item>", re.IGNORECASE | re.DOTALL)
_TITLE_RE = re.compile(r"<title(?:\s[^>]*)?>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_LINK_RE = re.compile(r"<link(?:\s[^>]*)?>(.*?)</link>", re.IGNORECASE | re.DOTALL)
_DESC_RE = re.compile(r"<description(?:\s[^>]*)?>(.*?)</description>", re.IGNORECASE | re.DOTALL)
_PUBDATE_RE = re.compile(r"<pubDate(?:\s[^>]*)?>(.*?)</pubDate>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _load_feeds_config() -> list[dict[str, Any]]:
    try:
        document = json.loads(FEEDS_RESOURCE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("rss_security.feeds_missing", path=str(FEEDS_RESOURCE))
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("rss_security.feeds_unparsable", error=str(exc))
        return []
    return list(document.get("feeds") or [])


def _strip_html(value: str) -> str:
    cleaned = _TAG_RE.sub(" ", value or "")
    return " ".join(cleaned.split())


def _parse_rss_items(xml_text: str) -> list[dict[str, str]]:
    if not xml_text:
        return []
    items: list[dict[str, str]] = []
    for block in _ITEM_RE.findall(xml_text):
        title = _strip_html(_TITLE_RE.search(block).group(1)) if _TITLE_RE.search(block) else ""
        link = _strip_html(_LINK_RE.search(block).group(1)) if _LINK_RE.search(block) else ""
        description = _strip_html(_DESC_RE.search(block).group(1)) if _DESC_RE.search(block) else ""
        pub_date = _strip_html(_PUBDATE_RE.search(block).group(1)) if _PUBDATE_RE.search(block) else ""
        if title:
            items.append(
                {
                    "title": title[:500],
                    "url": link[:1000],
                    "summary": description[:800],
                    "published_at": pub_date[:120],
                }
            )
    if items:
        return items
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    channel = root.find("channel")
    if channel is None:
        channel = root
    for entry in channel.findall("item"):
        title = (entry.findtext("title") or "").strip()
        if not title:
            continue
        items.append(
            {
                "title": title[:500],
                "url": (entry.findtext("link") or "").strip()[:1000],
                "summary": _strip_html(entry.findtext("description") or "")[:800],
                "published_at": (entry.findtext("pubDate") or "").strip()[:120],
            }
        )
    return items


def _title_hash(title: str) -> str:
    normalized = re.sub(r"\s+", " ", (title or "").strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def score_security_text(text: str) -> dict[str, Any]:
    """Score a headline/summary for security relevance (0-100)."""
    lowered = (text or "").lower()
    pos = sum(1 for token in POSITIVE_FR if token in lowered)
    neg = sum(1 for token in NEGATIVE_FR if token in lowered)
    neg += sum(1 for token in NEGATIVE_EN if token in lowered)
    if not lowered.strip():
        return {"score": 0, "tone": "stable", "risk_level": "low"}
    raw = 45 + (neg * 12) - (pos * 8)
    score = max(0, min(100, raw))
    if score >= 75:
        tone, risk = "critical", "high"
    elif score >= 55:
        tone, risk = "watch", "medium"
    elif score >= 35:
        tone, risk = "watch", "low"
    else:
        tone, risk = "stable", "low"
    return {"score": score, "tone": tone, "risk_level": risk}


def _fetch_feed(url: str, *, timeout: float = 8.0) -> list[dict[str, str]]:
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url, headers=RSS_HEADERS)
        if response.status_code != 200:
            logger.info("rss_security.feed_non_200", url=url, status=response.status_code)
            return []
        return _parse_rss_items(response.text)
    except Exception as exc:  # noqa: BLE001
        logger.info("rss_security.feed_unreachable", url=url, error=str(exc))
        return []


def _articles_to_signals(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for idx, article in enumerate(articles[:8]):
        scoring = score_security_text(f"{article.get('title')} {article.get('summary')}")
        if scoring["score"] < 30:
            continue
        signals.append(
            {
                "id": f"sig-rss-{article.get('hash') or idx}",
                "label": article.get("title") or "Signal RSS securite",
                "tone": scoring["tone"],
                "summary": article.get("summary") or article.get("title"),
                "score": scoring["score"],
                "risk_level": scoring["risk_level"],
                "sources": [article.get("feed_id") or "rss-security"],
                "url": article.get("url"),
                "feed_name": article.get("feed_name"),
            }
        )
    return signals


def sync_rss_security(*, force: bool = False) -> dict[str, Any]:
    """Fetch whitelisted security RSS feeds and cache the snapshot."""
    if not force:
        cached = cache_get(CACHE_KEY)
        if cached:
            return cached

    feeds = _load_feeds_config()
    seen_hashes: set[str] = set()
    articles: list[dict[str, Any]] = []
    for feed in feeds:
        url = feed.get("url")
        if not url:
            continue
        for item in _fetch_feed(url):
            digest = _title_hash(item.get("title") or "")
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            scoring = score_security_text(f"{item.get('title')} {item.get('summary')}")
            articles.append(
                {
                    **item,
                    "hash": digest,
                    "feed_id": feed.get("id"),
                    "feed_name": feed.get("name"),
                    "language": feed.get("language") or "fr",
                    "security_score": scoring["score"],
                    "tone": scoring["tone"],
                }
            )

    articles.sort(key=lambda row: float(row.get("security_score") or 0), reverse=True)
    signals = _articles_to_signals(articles)
    payload: dict[str, Any] = {
        "live": bool(articles),
        "source": "RFI/Jeune Afrique/Abidjan.net/Fraternite Matin",
        "source_kind": "rss_security",
        "source_badge": "LIVE" if articles else "CACHE BASELINE",
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "feeds_checked": len(feeds),
        "article_count": len(articles),
        "articles": articles[:30],
        "signals": signals,
    }
    cache_set(CACHE_KEY, payload, CACHE_TTL_SECONDS)
    return payload


def rss_security_payload(*, allow_live: bool = True) -> Optional[dict[str, Any]]:
    if not allow_live:
        return None
    cached = cache_get(CACHE_KEY)
    if cached and cached.get("live"):
        return cached
    return None
