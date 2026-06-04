"""Test suite bootstrap — forces a SQLite test DB before any `app.*`
import resolves the real Postgres DSN.

Pytest imports this module before collecting test files, so setting
``DATABASE_URL`` here guarantees ``app.core.config.settings.database_url``
is read from the SQLite override. Any test that needs a live schema
imports ``session_factory`` / ``reset_db`` from this module.
"""
from __future__ import annotations

import os
import pathlib
import tempfile

# ---------------------------------------------------------------------------
# Test DSN — must be set before the first `from app.*` import happens.
# ---------------------------------------------------------------------------
_TEST_DB = pathlib.Path(tempfile.gettempdir()) / "pytest_omnirag.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
# Neutralise side-effects that would otherwise trigger real external calls
# at import time (Qdrant ping, Redis connect, Azure OpenAI cost meter).
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _provision_schema() -> None:
    """Create every ORM table once per session against the SQLite test DB.

    We import `app.models` as a package so SQLAlchemy discovers every
    mapped class (Workspace, Capability, System, Run, Skill, Context…)
    before `Base.metadata.create_all` runs. Without that, ForeignKey
    constraints referencing late-imported tables would silently get
    dropped by SQLite and trigger OperationalError on insert.
    """
    from app.db.base import Base, engine
    import app.models  # noqa: F401  (import for side-effect registration)

    Base.metadata.create_all(engine)
    yield
    # Session teardown: drop the DB file so the next run starts clean.
    try:
        _TEST_DB.unlink(missing_ok=True)
    except OSError:
        pass


@pytest.fixture()
def db_session():
    """Per-test SQLAlchemy session with a guaranteed clean slate.

    We TRUNCATE (DELETE FROM) the runtime tables we touch instead of
    dropping/recreating the whole schema — orders of magnitude faster
    on SQLite and keeps us from racing with ``_provision_schema``.
    """
    from app.db.base import SessionLocal

    # Order matters for FK constraints.
    _TRUNCATE_ORDER = [
        "expert_capture_events",
        "knowledge_update_proposals",
        "expert_capture_sessions",
        "deposit_files",
        "deposit_access_links",
        "feed_articles",
        "feed_sources",
        "semantic_targets",
        "safety_filters",
        "meeting_decisions",
        "workspace_macro_indicators",
        "workspace_visual_observations",
        "workspace_visual_captures",
        "workspace_visual_sources",
        "worker_jobs",
        "knowledge_collection_sources",
        "knowledge_document_facts",
        "knowledge_table_facts",
        "knowledge_guides",
        "knowledge_collections",
        "workspace_map_scores",
        "workspace_map_signals",
        "workspace_map_zones",
        "workspace_map_layers",
        "workspace_maps",
        "workspace_jobs",
        "messages",
        "sessions",
        "workspace_action_items",
        "workspace_calendar_events",
        "skill_invocations",
        "canonical_answers",
        "evaluation_feedback",
        "decisions",
        "evaluation_scores",
        "evaluation_presets",
        "rag_presets",
        "runs",
        "system_versions",
        "systems",
        "capabilities",
        "skills",
        "audit_logs",
        "workspace_iam_configs",
        "workspace_members",
        "workspaces",
        "users",
    ]
    db = SessionLocal()
    try:
        for table_name in _TRUNCATE_ORDER:
            try:
                db.execute(__import__("sqlalchemy").text(f"DELETE FROM {table_name}"))
            except Exception:
                # Table may not exist yet in minimal setups; ignore.
                db.rollback()
        db.commit()
        yield db
    finally:
        db.close()
