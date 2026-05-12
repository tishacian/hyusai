"""RSS feed manager — fetch, parse, store articles"""
import uuid
from datetime import datetime
from typing import Optional

from app.core.logging import get_logger
from app.db.base import SessionLocal

logger = get_logger(__name__)

RSS_REQUEST_HEADERS = {
    "User-Agent": "Agentium-SENTINEL-CI/1.0 (+https://agentium.papai.ai)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


async def fetch_feed(url: str) -> list[dict]:
    """Fetch and parse an RSS feed. Returns list of article dicts."""
    try:
        import feedparser
        import httpx
    except ImportError:
        logger.warning("feedparser or httpx not installed")
        return []

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, follow_redirects=True, headers=RSS_REQUEST_HEADERS)
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


def save_articles(source_id: str, articles: list[dict]) -> int:
    """Persist articles to database. Returns count of newly inserted articles."""
    from app.models.intelligence import FeedArticle

    db = SessionLocal()
    inserted = 0
    try:
        for art in articles:
            existing = db.query(FeedArticle).filter(FeedArticle.url == art["url"]).first()
            if existing:
                continue
            row = FeedArticle(
                id=art["id"],
                source_id=source_id,
                title=art["title"],
                url=art["url"],
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
    from app.models.intelligence import FeedArticle, FeedSource

    q = db.query(FeedArticle).order_by(FeedArticle.fetched_at.desc())
    if workspace_id:
        # Filter articles whose source belongs to the workspace
        q = q.join(FeedSource, FeedSource.id == FeedArticle.source_id).filter(
            FeedSource.workspace_id == workspace_id
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
