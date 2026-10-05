"""Batch processor for scheduled RSS intelligence analysis"""
import uuid
from datetime import datetime
from typing import AsyncGenerator

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.services.intelligence.profile import (
    IntelligenceProfile,
    intelligence_profile,
    profile_for_workspace_id,
)

logger = get_logger(__name__)

def _risk_rank(level: str | None) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(level or "low", 1)


def _build_reference_synthesis(
    articles: list[dict],
    risk_counts: dict,
    top_entities: list[tuple[str, int]],
    profile: IntelligenceProfile | None = None,
) -> dict:
    """Build a deterministic, source-backed brief from the dashboard rows.

    This is intentionally not an LLM summary: it gives the system a reliable
    baseline artifact that can later be promoted to Knowledge or consumed by
    the Mission Room even when external model providers are disabled. Its
    wording and target collection come from the workspace profile.
    """
    profile = profile or intelligence_profile(None)
    ranked = sorted(
        articles,
        key=lambda a: (
            _risk_rank(a.get("risk_level")),
            float(a.get("relevance_score") or 0),
            a.get("published_at") or "",
        ),
        reverse=True,
    )
    focus = ranked[:5]
    high_count = risk_counts.get("high", 0) + risk_counts.get("critical", 0)
    entities = [name for name, _count in top_entities[:6]]
    if focus:
        titles = "; ".join(a.get("title") or "Untitled" for a in focus[:3])
        summary = profile.brief_summary(len(articles), high_count, titles)
    else:
        summary = (
            "No articles analysed yet. Trigger an RSS analysis to produce the reference synthesis."
        )
    return {
        "title": profile.brief_title,
        "summary": summary,
        "key_findings": [
            (a.get("summary") or a.get("title") or "").strip()
            for a in focus
            if (a.get("summary") or a.get("title"))
        ][:5],
        "recommended_actions": list(profile.recommended_actions),
        "entities": entities,
        "source_articles": [
            {
                "id": a.get("id"),
                "title": a.get("title"),
                "url": a.get("url"),
                "risk_level": a.get("risk_level"),
                "relevance_score": a.get("relevance_score"),
            }
            for a in focus
        ],
        "knowledge_reference": {
            "recommended_collection": profile.collection_slug,
            "status": "candidate",
            "promotion_policy": "human_review_required",
        },
    }


def ensure_intelligence_defaults(db, workspace_id: str = None) -> bool:
    """Insert the family's starter feed / target / filter when the workspace has none.

    A generic workspace has no starters: News Lab opens empty and guides the
    user to add a feed and a target. A family adapter may declare starters
    (``DEFAULT_FEEDS`` / ``DEFAULT_TARGET`` / ``DEFAULT_FILTER``). Nothing is
    ever written without a workspace.
    """
    from app.models.intelligence import FeedSource, SemanticTarget, SafetyFilter

    if not workspace_id:
        return False
    profile = profile_for_workspace_id(db, workspace_id)
    if not profile.has_starters:
        return False

    added = False
    feeds_q = db.query(FeedSource).filter(FeedSource.workspace_id == workspace_id)
    targets_q = db.query(SemanticTarget).filter(SemanticTarget.workspace_id == workspace_id)
    filters_q = db.query(SafetyFilter).filter(SafetyFilter.workspace_id == workspace_id)

    if profile.default_feeds and feeds_q.count() == 0:
        for feed in profile.default_feeds:
            db.add(
                FeedSource(
                    id=str(uuid.uuid4()),
                    workspace_id=workspace_id,
                    name=feed["name"],
                    url=feed["url"],
                    category=feed["category"],
                    refresh_interval=3600,
                    active=True,
                )
            )
        added = True
        logger.info("Seeded default RSS feeds for intelligence batch", count=len(profile.default_feeds), workspace_id=workspace_id)
    default_target = profile.default_target
    if default_target and targets_q.count() == 0:
        db.add(
            SemanticTarget(
                id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                name=default_target["name"],
                description=default_target["description"],
                keywords=list(default_target["keywords"]),
                relevance_threshold=default_target["relevance_threshold"],
                active=True,
            )
        )
        added = True
        logger.info("Seeded default semantic target for intelligence batch", workspace_id=workspace_id)
    elif default_target:
        default_t = (
            db.query(SemanticTarget)
            .filter(
                SemanticTarget.name.contains("(default)"),
                SemanticTarget.workspace_id == workspace_id,
            )
            .first()
        )
        if default_t and default_t.relevance_threshold != default_target["relevance_threshold"]:
            default_t.relevance_threshold = default_target["relevance_threshold"]
            added = True
            logger.info("Updated default target relevance_threshold", new=default_target["relevance_threshold"], workspace_id=workspace_id)
    default_filter = profile.default_filter
    if default_filter and filters_q.count() == 0:
        db.add(
            SafetyFilter(
                id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                name=default_filter["name"],
                prompt_template=default_filter["prompt_template"],
                severity=default_filter["severity"],
                active=True,
            )
        )
        added = True
        logger.info("Seeded default safety filter for intelligence batch", workspace_id=workspace_id)
    if added:
        db.commit()
    return added


async def run_batch(target_id: str = None, workspace_id: str = None) -> AsyncGenerator[dict, None]:
    """Run one workspace's intelligence batch: fetch feeds -> analyze -> score -> store.

    Yields SSE-compatible progress events. Only the workspace's own feeds,
    targets, safety filters and articles take part; a batch without a
    workspace is refused rather than run over every workspace at once.
    """
    from app.models.intelligence import FeedSource, FeedArticle, SemanticTarget, SafetyFilter
    from app.services.intelligence.feed_manager import fetch_feed, save_articles
    from app.services.intelligence.analyzer import get_analyzer

    batch_id = str(uuid.uuid4())[:8]
    if not workspace_id:
        yield {
            "type": "batch_error",
            "batch_id": batch_id,
            "code": "workspace_required",
            "message": "An intelligence batch runs for one workspace; none was given.",
        }
        return

    analyzer = get_analyzer()
    db = SessionLocal()

    try:
        profile = profile_for_workspace_id(db, workspace_id)
        ensure_intelligence_defaults(db, workspace_id=workspace_id)
        sources = (
            db.query(FeedSource)
            .filter(FeedSource.active == True, FeedSource.workspace_id == workspace_id)  # noqa: E712
            .all()
        )
        targets = (
            db.query(SemanticTarget)
            .filter(SemanticTarget.active == True, SemanticTarget.workspace_id == workspace_id)  # noqa: E712
            .all()
        )
        filters = (
            db.query(SafetyFilter)
            .filter(SafetyFilter.active == True, SafetyFilter.workspace_id == workspace_id)  # noqa: E712
            .all()
        )

        if not sources:
            yield {
                "type": "batch_error",
                "batch_id": batch_id,
                "code": "no_feed",
                "message": "No active feed in this workspace. Add a feed to start the watch.",
            }
            return
        if not targets:
            yield {
                "type": "batch_error",
                "batch_id": batch_id,
                "code": "no_target",
                "message": "No active target in this workspace. Add a target to tune the watch.",
            }
            return

        target_desc = " | ".join(t.description for t in targets)
        filter_rules = " | ".join(f.prompt_template for f in filters) if filters else "standard safety"

        total_sources = len(sources)
        total_articles = 0
        analyzed = 0

        max_articles = max(1, int(settings.intelligence_batch_max_articles or 20))

        yield {
            "type": "batch_start",
            "batch_id": batch_id,
            "sources": total_sources,
            "targets": len(targets),
            "max_articles": max_articles,
            "retry_skipped": bool(settings.intelligence_batch_retry_skipped),
        }

        relevance_threshold = min((t.relevance_threshold for t in targets), default=0.25)

        for si, source in enumerate(sources):
            yield {
                "type": "batch_fetch",
                "batch_id": batch_id,
                "source": source.name,
                "progress": int((si / total_sources) * 30),
            }

            articles = await fetch_feed(source.url, user_agent=profile.rss_user_agent)
            inserted = save_articles(source.id, articles, workspace_id=workspace_id)

            source.last_fetched = datetime.utcnow()
            source.article_count = (source.article_count or 0) + inserted
            db.commit()

            total_articles += inserted

        yield {"type": "batch_fetch_done", "batch_id": batch_id, "total_articles": total_articles}

        unanalyzed_q = db.query(FeedArticle).filter(FeedArticle.analysis.is_(None))
        if settings.intelligence_batch_retry_skipped:
            from sqlalchemy import or_, cast, String as SAString

            unanalyzed_q = db.query(FeedArticle).filter(
                or_(
                    FeedArticle.analysis.is_(None),
                    cast(FeedArticle.analysis, SAString).contains('"skipped"'),
                )
            )
        unanalyzed_q = unanalyzed_q.filter(FeedArticle.workspace_id == workspace_id)
        unanalyzed = unanalyzed_q.order_by(FeedArticle.fetched_at.desc()).limit(max_articles).all()

        for ai, article in enumerate(unanalyzed):
            relevance = await analyzer.compute_relevance(
                f"{article.title} {(article.content or '')[:500]}", target_desc
            )
            article.relevance_score = float(relevance or 0.0)

            if relevance >= relevance_threshold:
                analysis = await analyzer.analyze_article(
                    article.title,
                    article.content or "",
                    target_desc,
                    prompt_template=profile.analysis_prompt,
                )
                article.analysis = analysis
                article.embedded = True

                if settings.intelligence_batch_safety_check_enabled:
                    safety = await analyzer.check_safety(
                        f"{article.title}: {analysis.get('key_findings', [])}",
                        filter_rules,
                        prompt_template=profile.safety_prompt,
                    )
                else:
                    safety = {"flag": "clear", "reason": "safety LLM disabled for scheduled batch"}
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


def get_dashboard_data(db, workspace_id: str = None) -> dict:
    """Aggregate one workspace's intelligence data for the BI dashboard.

    Only rows stamped with the workspace are read; without a workspace the
    dashboard is empty rather than global.
    """
    from app.models.intelligence import FeedSource, FeedArticle

    profile = profile_for_workspace_id(db, workspace_id)
    if workspace_id:
        ensure_intelligence_defaults(db, workspace_id=workspace_id)
        sources = (
            db.query(FeedSource)
            .filter(FeedSource.active == True, FeedSource.workspace_id == workspace_id)  # noqa: E712
            .all()
        )
        articles_q = db.query(FeedArticle).filter(FeedArticle.workspace_id == workspace_id)
        total_articles = articles_q.count() or 0
        analyzed_count = articles_q.filter(FeedArticle.embedded == True).count() or 0  # noqa: E712
        recent = (
            articles_q.filter(
                FeedArticle.analysis.isnot(None),
                FeedArticle.embedded == True,  # noqa: E712
            )
            .order_by(FeedArticle.fetched_at.desc())
            .limit(30)
            .all()
        )
    else:
        sources, total_articles, analyzed_count, recent = [], 0, 0, []
    source_ids = [article.source_id for article in recent if article.source_id]
    source_by_id = {
        source.id: source
        for source in db.query(FeedSource).filter(
            FeedSource.id.in_(source_ids),
            FeedSource.workspace_id == workspace_id,
        ).all()
    } if source_ids else {}

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
            "source_id": art.source_id,
            "source_name": source_by_id.get(art.source_id).name if source_by_id.get(art.source_id) else None,
            "source_category": source_by_id.get(art.source_id).category if source_by_id.get(art.source_id) else None,
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
        "synthesis": _build_reference_synthesis(articles_data, risk_counts, top_entities, profile),
        "knowledge_collection": {
            "slug": profile.collection_slug,
            "name": profile.collection_name,
        },
    }
