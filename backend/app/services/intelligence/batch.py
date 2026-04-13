"""Batch processor for scheduled RSS intelligence analysis"""
import uuid
from datetime import datetime
from typing import AsyncGenerator

from app.core.logging import get_logger
from app.db.base import SessionLocal

logger = get_logger(__name__)

# Seeded when DB has no rows so "Run Analysis" works without manual config (demo / first run).
DEFAULT_FEEDS = [
    {"name": "BBC World News (default)", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "category": "world"},
    {"name": "NYT World (default)", "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "category": "world"},
]
DEFAULT_TARGET = {
    "name": "General intelligence (default)",
    "description": (
        "World news, geopolitics, economy, technology, security, and major events "
        "relevant to enterprise risk awareness."
    ),
    "keywords": [],
    "relevance_threshold": 0.10,
}
DEFAULT_FILTER = {
    "name": "Standard safety (default)",
    "prompt_template": (
        "Flag content that is primarily illegal, graphic violence, or explicit hate speech. "
        "Allow neutral factual news reporting."
    ),
    "severity": "flag",
}


def ensure_intelligence_defaults(db) -> bool:
    """Insert default feed / target / filter if tables are empty. Returns True if anything was added."""
    from app.models.intelligence import FeedSource, SemanticTarget, SafetyFilter

    added = False
    if db.query(FeedSource).count() == 0:
        for feed in DEFAULT_FEEDS:
            db.add(
                FeedSource(
                    id=str(uuid.uuid4()),
                    name=feed["name"],
                    url=feed["url"],
                    category=feed["category"],
                    refresh_interval=3600,
                    active=True,
                )
            )
        added = True
        logger.info("Seeded default RSS feeds for intelligence batch", count=len(DEFAULT_FEEDS))
    if db.query(SemanticTarget).count() == 0:
        db.add(
            SemanticTarget(
                id=str(uuid.uuid4()),
                name=DEFAULT_TARGET["name"],
                description=DEFAULT_TARGET["description"],
                keywords=DEFAULT_TARGET["keywords"],
                relevance_threshold=DEFAULT_TARGET["relevance_threshold"],
                active=True,
            )
        )
        added = True
        logger.info("Seeded default semantic target for intelligence batch")
    else:
        default_t = db.query(SemanticTarget).filter(
            SemanticTarget.name.contains("(default)")
        ).first()
        if default_t and default_t.relevance_threshold != DEFAULT_TARGET["relevance_threshold"]:
            default_t.relevance_threshold = DEFAULT_TARGET["relevance_threshold"]
            added = True
            logger.info("Updated default target relevance_threshold", new=DEFAULT_TARGET["relevance_threshold"])
    if db.query(SafetyFilter).count() == 0:
        db.add(
            SafetyFilter(
                id=str(uuid.uuid4()),
                name=DEFAULT_FILTER["name"],
                prompt_template=DEFAULT_FILTER["prompt_template"],
                severity=DEFAULT_FILTER["severity"],
                active=True,
            )
        )
        added = True
        logger.info("Seeded default safety filter for intelligence batch")
    if added:
        db.commit()
    return added


async def run_batch(target_id: str = None) -> AsyncGenerator[dict, None]:
    """Run a full intelligence batch: fetch feeds -> analyze -> score -> store.
    Yields SSE-compatible progress events."""
    from app.models.intelligence import FeedSource, FeedArticle, SemanticTarget, SafetyFilter
    from app.services.intelligence.feed_manager import fetch_feed, save_articles
    from app.services.intelligence.analyzer import get_analyzer

    analyzer = get_analyzer()
    db = SessionLocal()
    batch_id = str(uuid.uuid4())[:8]

    try:
        ensure_intelligence_defaults(db)
        sources = db.query(FeedSource).filter(FeedSource.active == True).all()
        targets = db.query(SemanticTarget).filter(SemanticTarget.active == True).all()
        filters = db.query(SafetyFilter).filter(SafetyFilter.active == True).all()

        if not sources:
            yield {
                "type": "batch_error",
                "batch_id": batch_id,
                "message": "No active feed sources (defaults could not be created)",
            }
            return

        target_desc = " | ".join(t.description for t in targets) if targets else "general intelligence"
        filter_rules = " | ".join(f.prompt_template for f in filters) if filters else "standard safety"

        total_sources = len(sources)
        total_articles = 0
        analyzed = 0

        yield {"type": "batch_start", "batch_id": batch_id, "sources": total_sources, "targets": len(targets)}

        relevance_threshold = min((t.relevance_threshold for t in targets), default=0.25)

        for si, source in enumerate(sources):
            yield {
                "type": "batch_fetch",
                "batch_id": batch_id,
                "source": source.name,
                "progress": int((si / total_sources) * 30),
            }

            articles = await fetch_feed(source.url)
            inserted = save_articles(source.id, articles)

            source.last_fetched = datetime.utcnow()
            source.article_count = (source.article_count or 0) + inserted
            db.commit()

            total_articles += inserted

        yield {"type": "batch_fetch_done", "batch_id": batch_id, "total_articles": total_articles}

        from sqlalchemy import or_, cast, String as SAString
        unanalyzed = db.query(FeedArticle).filter(
            or_(
                FeedArticle.analysis.is_(None),
                cast(FeedArticle.analysis, SAString).contains('"skipped"'),
            )
        ).order_by(FeedArticle.fetched_at.desc()).limit(100).all()

        for ai, article in enumerate(unanalyzed):
            relevance = await analyzer.compute_relevance(
                f"{article.title} {(article.content or '')[:500]}", target_desc
            )
            article.relevance_score = relevance

            if relevance >= relevance_threshold:
                analysis = await analyzer.analyze_article(
                    article.title, article.content or "", target_desc
                )
                article.analysis = analysis
                article.embedded = True

                safety = await analyzer.check_safety(
                    f"{article.title}: {analysis.get('key_findings', [])}",
                    filter_rules,
                )
                article.safety_flag = safety.get("flag", "clear")
                article.summary = "; ".join(analysis.get("key_findings", []))
                analyzed += 1
            else:
                article.analysis = {"skipped": True, "reason": "below relevance threshold"}
                article.safety_flag = "clear"

            if (ai + 1) % 5 == 0:
                db.commit()
                yield {
                    "type": "batch_analyze",
                    "batch_id": batch_id,
                    "analyzed": analyzed,
                    "total": len(unanalyzed),
                    "progress": int(30 + ((ai + 1) / max(1, len(unanalyzed))) * 60),
                }

        db.commit()

        yield {
            "type": "batch_complete",
            "batch_id": batch_id,
            "total_articles": total_articles,
            "analyzed": analyzed,
            "progress": 100,
        }

    except Exception as e:
        logger.error(f"Batch failed: {e}")
        yield {"type": "batch_error", "batch_id": batch_id, "message": str(e)}
    finally:
        db.close()


def get_dashboard_data(db) -> dict:
    """Aggregate intelligence data for the BI dashboard."""
    from app.models.intelligence import FeedSource, FeedArticle
    from sqlalchemy import func

    ensure_intelligence_defaults(db)
    sources = db.query(FeedSource).filter(FeedSource.active == True).all()
    total_articles = db.query(func.count(FeedArticle.id)).scalar() or 0
    analyzed_count = db.query(func.count(FeedArticle.id)).filter(
        FeedArticle.embedded == True
    ).scalar() or 0

    recent = db.query(FeedArticle).filter(
        FeedArticle.analysis.isnot(None),
        FeedArticle.embedded == True,
    ).order_by(FeedArticle.fetched_at.desc()).limit(30).all()

    sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0, "mixed": 0}
    risk_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    entity_freq = {}
    articles_data = []

    for art in recent:
        analysis = art.analysis or {}
        sent = analysis.get("sentiment", "neutral")
        sentiment_counts[sent] = sentiment_counts.get(sent, 0) + 1
        risk = analysis.get("risk_level", "low")
        risk_counts[risk] = risk_counts.get(risk, 0) + 1
        for ent in analysis.get("entities", []):
            entity_freq[ent] = entity_freq.get(ent, 0) + 1
        articles_data.append({
            "id": art.id,
            "title": art.title,
            "url": art.url,
            "summary": art.summary,
            "published_at": art.published_at.isoformat() if art.published_at else None,
            "relevance_score": art.relevance_score,
            "sentiment": sent,
            "risk_level": risk,
            "safety_flag": art.safety_flag,
            "entities": analysis.get("entities", []),
        })

    top_entities = sorted(entity_freq.items(), key=lambda x: -x[1])[:15]

    return {
        "kpis": {
            "total_articles": total_articles,
            "analyzed": analyzed_count,
            "active_feeds": len(sources),
            "high_risk": risk_counts.get("high", 0) + risk_counts.get("critical", 0),
        },
        "sentiment": sentiment_counts,
        "risk": risk_counts,
        "top_entities": [{"name": e, "count": c} for e, c in top_entities],
        "articles": articles_data,
    }
