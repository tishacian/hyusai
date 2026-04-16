"""Intelligence models for RSS feeds and analysis"""
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, JSON, Float, Boolean, Integer, ForeignKey
from app.db.base import Base


class FeedSource(Base):
    __tablename__ = "feed_sources"

    id = Column(String(36), primary_key=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    url = Column(String(2000), nullable=False)
    category = Column(String(100), default="general")
    refresh_interval = Column(Integer, default=3600)
    last_fetched = Column(DateTime, nullable=True)
    active = Column(Boolean, default=True)
    article_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class FeedArticle(Base):
    __tablename__ = "feed_articles"

    id = Column(String(36), primary_key=True)
    source_id = Column(String(36), nullable=False)
    title = Column(String(500), nullable=False)
    url = Column(String(2000), nullable=True)
    content = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    published_at = Column(DateTime, nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    embedded = Column(Boolean, default=False)
    analysis = Column(JSON, nullable=True, default=None)
    relevance_score = Column(Float, default=0.0)
    safety_flag = Column(String(20), default="clear")


class SemanticTarget(Base):
    __tablename__ = "semantic_targets"

    id = Column(String(36), primary_key=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    keywords = Column(JSON, default=list)
    relevance_threshold = Column(Float, default=0.3)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SafetyFilter(Base):
    __tablename__ = "safety_filters"

    id = Column(String(36), primary_key=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    prompt_template = Column(Text, nullable=False)
    severity = Column(String(20), default="warn")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
