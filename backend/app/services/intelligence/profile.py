"""What Intelligence (News Lab) says and starts with, per workspace family.

Intelligence is a neutral watch product available to every workspace: it
reads the workspace's own feeds, scores them against the workspace's own
targets and writes into the workspace's own knowledge collection. Nothing here
names a customer. A family that needs its own wording, prompts or starter
content provides it as ``app.tenants.<family>.intelligence`` and is reached
through ``family_hook`` (docs/adr/0003-generalisation-frontieres.md, D6).

Generic workspaces get no starter feed, target or filter: News Lab opens empty
and guides the user to add them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from app.tenants import family_hook

COLLECTION_SLUG = "workspace-intelligence"
COLLECTION_NAME = "Workspace intelligence"
COLLECTION_DESCRIPTION = (
    "RSS sources, raw article content and consolidated News Lab analysis "
    "for this workspace's watch."
)

BRIEF_TITLE = "Watch brief"
RECOMMENDED_ACTIONS = (
    "Check the primary sources before sharing a signal.",
    "Promote confirmed signals to the workspace Knowledge.",
    "Review high-risk signals with the people who own the decision.",
)
CONSOLIDATED_TITLE = "News Lab consolidated brief"


def brief_summary(article_count: int, high_count: int, titles: str) -> str:
    return (
        f"{article_count} article(s) analysed. {high_count} high-risk signal(s). "
        f"Priority: {titles}."
    )


ANALYSIS_PROMPT = """Analyze this article for a watch tuned to the workspace's own targets.

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
5. Relevance to the semantic target (if applicable)

Return ONLY valid JSON:
{{
  "entities": ["entity1", "entity2"],
  "sentiment": "neutral",
  "risk_level": "low",
  "key_findings": ["finding1", "finding2"],
  "target_relevance": "brief note or null"
}}"""

SAFETY_CHECK_PROMPT = """You are a content safety filter for a watch tuned to the workspace's own targets.

## Content to check
{content_summary}

## Safety filter rules
{filter_rules}

## Instructions
Evaluate if this content is safe to include in the watch dashboard.
Apply the configured safety and sensitivity rules.

Return ONLY valid JSON:
{{
  "safe": true/false,
  "flag": "clear|flagged|blocked",
  "reason": "brief explanation"
}}"""

RSS_USER_AGENT = "Agentium-Intelligence/1.0 (+https://agentium.papai.ai)"


@dataclass(frozen=True)
class IntelligenceProfile:
    family: str
    collection_slug: str
    collection_name: str
    collection_description: str
    brief_title: str
    brief_summary: Callable[[int, int, str], str]
    recommended_actions: tuple[str, ...]
    consolidated_title: str
    analysis_prompt: str
    safety_prompt: str
    rss_user_agent: str
    default_feeds: tuple[dict[str, Any], ...]
    default_target: Optional[dict[str, Any]]
    default_filter: Optional[dict[str, Any]]

    @property
    def has_starters(self) -> bool:
        return bool(self.default_feeds or self.default_target or self.default_filter)


def intelligence_profile(family: Optional[str]) -> IntelligenceProfile:
    """The profile for a stamped family; unknown and ``generic`` get the neutral one."""

    def hook(name: str, default: Any) -> Any:
        return family_hook(family, "intelligence", name, default)

    return IntelligenceProfile(
        family=str(family or "generic"),
        collection_slug=hook("COLLECTION_SLUG", COLLECTION_SLUG),
        collection_name=hook("COLLECTION_NAME", COLLECTION_NAME),
        collection_description=hook("COLLECTION_DESCRIPTION", COLLECTION_DESCRIPTION),
        brief_title=hook("BRIEF_TITLE", BRIEF_TITLE),
        brief_summary=hook("brief_summary", brief_summary),
        recommended_actions=tuple(hook("RECOMMENDED_ACTIONS", RECOMMENDED_ACTIONS)),
        consolidated_title=hook("CONSOLIDATED_TITLE", CONSOLIDATED_TITLE),
        analysis_prompt=hook("ANALYSIS_PROMPT", ANALYSIS_PROMPT),
        safety_prompt=hook("SAFETY_CHECK_PROMPT", SAFETY_CHECK_PROMPT),
        rss_user_agent=hook("RSS_USER_AGENT", RSS_USER_AGENT),
        default_feeds=tuple(hook("DEFAULT_FEEDS", ())),
        default_target=hook("DEFAULT_TARGET", None),
        default_filter=hook("DEFAULT_FILTER", None),
    )


def workspace_intelligence_profile(workspace: Any) -> IntelligenceProfile:
    """The profile of a workspace row; ``None`` gets the neutral one."""

    from app.services.workspace_features import workspace_family

    if workspace is None:
        return intelligence_profile(None)
    return intelligence_profile(workspace_family(workspace))


def profile_for_workspace_id(db: Any, workspace_id: Optional[str]) -> IntelligenceProfile:
    from app.models.workspace import Workspace

    if not workspace_id:
        return intelligence_profile(None)
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    return workspace_intelligence_profile(workspace)
