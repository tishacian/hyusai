"""RSS feed manager — fetch, parse, store articles"""
import uuid
from datetime import datetime
from typing import Optional

from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.services.intelligence.profile import RSS_USER_AGENT

logger = get_logger(__name__)

RSS_REQUEST_HEADERS = {
    "User-Agent": RSS_USER_AGENT,
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


async def fetch_feed(url: str, user_agent: Optional[str] = None) -> list[dict]:
    """Fetch and parse an RSS feed. Returns list of article dicts.

    ``user_agent`` is the workspace profile's (``profile.rss_user_agent``);
    without one the neutral product User-Agent is sent.
    """
    try:
        import feedparser
        import httpx
    except ImportError:
        logger.warning("feedparser or httpx not installed")
        return []

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            headers = dict(RSS_REQUEST_HEADERS)
            if user_agent:
                headers["User-Agent"] = user_agent
            resp = await client.get(url, follow_redirects=True, headers=headers)
            resp.raise_for_status()
        feed = feedparser.parse(resp.text)
    except Exception as e:
        logger.error(f"Failed to fetch feed {url}: {e}")
        return []

    articles = []
    for entry in feed.entries[:50]:
        content = ""
        if hasattr(entry, "content") and entry.content:
            content = entry.content[0].get("value", "")
        elif hasattr(entry, "summary"):
            content = entry.summary or ""

        published = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published = datetime(*entry.published_parsed[:6])
            except Exception:
                pass

        articles.append({
            "id": str(uuid.uuid4()),
            "title": getattr(entry, "title", "Untitled"),
            "url": getattr(entry, "link", ""),
            "content": content[:5000],
            "published_at": published,
        })
    return articles


def save_articles(source_id: str, articles: list[dict], workspace_id: Optional[str] = None) -> int:
    """Persist a feed's articles for one workspace. Returns the newly inserted count.

    An article is unique per (workspace, url): another workspace having the
    same URL never stops this one from keeping its own row. Without a
    workspace nothing is written.
    """
    from app.models.intelligence import FeedArticle

    if not workspace_id:
        logger.warning("intelligence.save_articles.no_workspace", source_id=source_id)
        return 0

    db = SessionLocal()
    inserted = 0
    try:
        urls = sorted({art.get("url") or "" for art in articles})
        seen: set[str] = set()
        if urls:
            seen = {
                url
                for (url,) in db.query(FeedArticle.url).filter(
                    FeedArticle.workspace_id == workspace_id,
                    FeedArticle.url.in_(urls),
                )
            }
        for art in articles:
            url = art.get("url") or ""
            if url in seen:
                continue
            seen.add(url)
            row = FeedArticle(
                id=art["id"],
                workspace_id=workspace_id,
                source_id=source_id,
                title=art["title"],
                url=url,
                content=art["content"],
                published_at=art.get("published_at"),
                fetched_at=datetime.utcnow(),
            )
            db.add(row)
            inserted += 1
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to save articles: {e}")
    finally:
        db.close()
    return inserted


def get_articles(
    db,
    source_id: str = None,
    min_relevance: float = 0.0,
    limit: int = 50,
    workspace_id: str = None,
) -> list[dict]:
    """The workspace's articles, newest first. No workspace, no articles."""
    from app.models.intelligence import FeedArticle

    if not workspace_id:
        return []
    q = (
        db.query(FeedArticle)
        .filter(FeedArticle.workspace_id == workspace_id)
        .order_by(FeedArticle.fetched_at.desc())
    )
    if source_id:
        q = q.filter(FeedArticle.source_id == source_id)
    if min_relevance > 0:
        q = q.filter(FeedArticle.relevance_score >= min_relevance)
    rows = q.limit(limit).all()
    return [
        {
            "id": r.id,
            "source_id": r.source_id,
            "title": r.title,
            "url": r.url,
            "summary": r.summary,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "relevance_score": r.relevance_score,
            "analysis": r.analysis,
            "safety_flag": r.safety_flag,
        }
        for r in rows
    ]
