"""Sentinel CI wording and starters for the shared Intelligence product (News Lab).

Intelligence is a neutral product: a generic workspace gets neutral wording, its
own knowledge collection and no starter content. Before that, every workspace
received what Sentinel CI needed: the open-intelligence collection read by the
AYA assistant, cabinet and hypervisor actions in the reference brief, the
geopolitical prompts, the world-news starters and the Sentinel User-Agent.

``app.services.intelligence.profile`` reads these names through
``family_hook(family, "intelligence", ...)``. They reproduce the pre-change
output byte for byte, pinned by
``app/tests/fixtures/sentinel_ci_intelligence_pin.json``.
"""

from __future__ import annotations

COLLECTION_SLUG = "sentinel-ci-open-intelligence"
COLLECTION_NAME = "SENTINEL-CI Open Intelligence"
COLLECTION_DESCRIPTION = (
    "Open intelligence RSS sources, raw scraped article content, and consolidated "
    "News Lab analysis for AYA interactions."
)

BRIEF_TITLE = "Synthese de veille RSS"
RECOMMENDED_ACTIONS = (
    "Verifier les sources primaires avant diffusion cabinet.",
    "Promouvoir les signaux confirmes vers la base Knowledge du workspace.",
    "Relier les signaux haut risque aux vues Presse, Veille et Decisions de l'hyperviseur.",
)
CONSOLIDATED_TITLE = "Synthese consolidee News Lab"


def brief_summary(article_count: int, high_count: int, titles: str) -> str:
    return f"{article_count} articles analyses. {high_count} signal(s) haut risque. Priorite: {titles}."


ANALYSIS_PROMPT = """Analyze this news article for intelligence purposes.

## Article
Title: {title}
Content (truncated): {content}

## Semantic Target
{target_description}

## Instructions
Extract:
1. Key entities (people, organizations, locations, events)
2. Sentiment (positive / negative / neutral / mixed)
3. Risk level (low / medium / high / critical)
4. Key findings (2-3 bullet points)
5. Geopolitical relevance (if applicable)

Return ONLY valid JSON:
{{
  "entities": ["entity1", "entity2"],
  "sentiment": "neutral",
  "risk_level": "low",
  "key_findings": ["finding1", "finding2"],
  "geopolitical_relevance": "brief note or null"
}}"""

SAFETY_CHECK_PROMPT = """You are a content safety filter for a geopolitical intelligence platform.

## Content to check
{content_summary}

## Safety filter rules
{filter_rules}

## Instructions
Evaluate if this content is safe to include in the intelligence dashboard.
Consider the configured geopolitical alignment and sensitivity rules.

Return ONLY valid JSON:
{{
  "safe": true/false,
  "flag": "clear|flagged|blocked",
  "reason": "brief explanation"
}}"""

RSS_USER_AGENT = "Agentium-SENTINEL-CI/1.0 (+https://agentium.papai.ai)"

# Written into a Sentinel CI workspace that opens News Lab with no feed, target
# or filter yet, so "Run analysis" works before the mission-room seed adds its own.
DEFAULT_FEEDS = (
    {"name": "BBC World News (default)", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "category": "world"},
    {"name": "NYT World (default)", "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "category": "world"},
)
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
