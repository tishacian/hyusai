"""Test suite bootstrap — defaults to an isolated SQLite DB before `app.*`.

An explicitly supplied external DB is accepted only with a destructive-reset
acknowledgement and a test-shaped database name.  This check runs before any
application import can bind the engine or clear runtime tables.
"""
from __future__ import annotations

import os
import pathlib
import tempfile
from urllib.parse import unquote, urlsplit

# ---------------------------------------------------------------------------
# Test DSN — must be set before the first `from app.*` import happens.
# ---------------------------------------------------------------------------
_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "main")
_TEST_DB = pathlib.Path(tempfile.gettempdir()) / f"pytest_omnirag-{_WORKER}-{os.getpid()}.db"
_CONFIGURED_DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _assert_external_test_database_is_disposable(database_url: str) -> None:
    """Fail before imports/fixtures can mutate an externally supplied DB.

    ``db_session`` deliberately clears every runtime table between tests.  An
    explicit acknowledgement and a test-shaped database name are therefore
    both mandatory whenever a caller overrides the per-process SQLite file.
    The check runs before importing ``app.db.base`` so a bad DSN cannot reach
    ``create_all`` or the first destructive ``DELETE``.
    """

    if not database_url:
        return
    if database_url.startswith("sqlite"):
        parsed_sqlite = urlsplit(database_url)
        sqlite_path = unquote(parsed_sqlite.path or "")
        if sqlite_path in {"/:memory:", ":memory:"}:
            return
        database_name = pathlib.Path(sqlite_path).name
        disposable_name = (
            database_name.startswith("pytest_")
            or database_name.startswith("pytest-")
            or database_name.startswith("test_")
            or database_name.endswith("_test.db")
        )
        acknowledged = os.getenv("PYTEST_ALLOW_DESTRUCTIVE_DATABASE_RESET") == "1"
        if not acknowledged or not disposable_name:
            raise RuntimeError(
                "Refusing destructive pytest SQLite reset: an explicit "
                "DATABASE_URL requires PYTEST_ALLOW_DESTRUCTIVE_DATABASE_RESET=1 "
                "and a test-shaped database filename"
            )
        return
    parsed = urlsplit(database_url.replace("postgresql+psycopg2://", "postgresql://", 1))
    database_name = parsed.path.lstrip("/").split("?", 1)[0]
    disposable_name = (
        database_name.startswith("agentium_p4")
        or database_name.startswith("test_")
        or database_name.endswith("_test")
    )
    acknowledged = os.getenv("PYTEST_ALLOW_DESTRUCTIVE_DATABASE_RESET") == "1"
    if not acknowledged or not disposable_name:
        raise RuntimeError(
            "Refusing destructive pytest database reset: external DATABASE_URL "
            "requires PYTEST_ALLOW_DESTRUCTIVE_DATABASE_RESET=1 and a database "
            "named agentium_p4*, test_* or *_test"
        )


def _assert_p4_broker_is_isolated() -> None:
    """Refuse the destructive RabbitMQ gate on a shared broker/queue."""

    if os.getenv("RUN_RABBITMQ_INTEGRATION") != "1":
        return
    broker_url = os.getenv("CELERY_BROKER_URL", "")
    queue = os.getenv("CELERY_TASK_DEFAULT_QUEUE", "")
    parsed = urlsplit(broker_url)
    vhost = unquote(parsed.path.lstrip("/"))
    isolated = (
        parsed.scheme in {"amqp", "amqps"}
        and "agentium_p4" in str(parsed.username or "")
        and "agentium_p4" in vhost
        and "agentium_p4" in queue
    )
    if not isolated:
        raise RuntimeError(
            "Refusing P4 RabbitMQ integration gate: CELERY_BROKER_URL must use "
            "an agentium_p4 user and vhost, and CELERY_TASK_DEFAULT_QUEUE must "
            "name an isolated agentium_p4 queue"
        )


_assert_external_test_database_is_disposable(_CONFIGURED_DATABASE_URL)
_assert_p4_broker_is_isolated()
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
        "client360_impact_events",
        "client360_mail_drafts",
        "client360_campaigns",
        "client360_mapping_rules",
        "client360_opportunities",
        "client360_data_sources",
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
        "run_inbox",
        "system_memory",
        "webhook_hooks",
        "run_schedules",
        "decisions",
        "evaluation_scores",
        "evaluation_presets",
        "rag_presets",
        "run_dispatch_outbox",
        "runs",
        "system_versions",
        "systems",
        "capabilities",
        "skills",
        "audit_logs",
        "workspace_iam_configs",
        "workspace_member_app_entitlements",
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
