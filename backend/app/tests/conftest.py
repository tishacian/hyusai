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
    import app.models  # noqa: F401  (import for side-effect registration)
    from app.db.base import Base, engine

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
        "value_measurements",
        "value_action_executions",
        "value_simulations",
        "decisions",
        "value_scenarios",
        "value_loop_operations",
        "workspace_app_lifecycle_step_receipts",
        "workspace_app_operations",
        "workspace_app_installations",
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


@pytest.fixture()
def attest_authorization_v2(monkeypatch):
    """Attach a production-shaped authorization-v2 promotion in tests."""

    import copy
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from sqlalchemy.orm import object_session

    from app.core.config import settings
    from app.models.audit import AuditLog
    from app.services.iam.decision_plane import (
        PROMOTION_EVENT_TYPE,
        PROMOTION_RECEIPT_KEY,
        build_promotion_receipt_document,
        candidate_config_sha256,
    )
    from app.services.iam.shadow_review import build_source_manifest_row, sha256_ref

    revision = "a" * 40
    monkeypatch.setattr(settings, "agentium_image_revision", revision)
    monkeypatch.setattr(
        settings,
        "authorization_v2_trusted_oidc_issuer",
        "https://gitlab.example.test",
    )
    monkeypatch.setattr(settings, "authorization_v2_trusted_project_id", "42")
    monkeypatch.setattr(settings, "authorization_v2_trusted_ref", "demo/agentic")

    def _attest(config, actions, *, attested_revision: str = revision):
        payload = copy.deepcopy(config.capability_overrides or {})
        policy = payload.setdefault("authorization_v2", {})
        policy["policy_version"] = 2
        modes = policy.setdefault("modes", {})
        group = sorted(actions)
        session = object_session(config)
        if session is None:
            raise RuntimeError("authorization-v2 test attestation requires a persisted config")
        observed_at = datetime.now(UTC)
        started_at = observed_at - timedelta(microseconds=1)
        ended_at = observed_at + timedelta(microseconds=max(1, len(group)))
        validated_at = ended_at + timedelta(microseconds=1)
        counters = {
            action: {
                "evaluations": 5,
                "legacy_allowed": 4,
                "legacy_denied": 1,
                "candidate_allowed": 4,
                "candidate_denied": 1,
                "matches": 5,
                "mismatches": 0,
                "explained_mismatches": 0,
                "unexplained_mismatches": 0,
            }
            for action in group
        }
        attestation = {
            "schema_version": 1,
            "workspace_id": str(config.workspace_id),
            "actions": group,
            "revision": attested_revision,
            "evidence_sha256": "b" * 64,
            "validated_by": "pytest-security-gate",
            "validated_at": validated_at.isoformat(),
            "environment": "isolated-test",
            "contracts": {
                "legacy": {
                    "result": "passed",
                    "format": "junit",
                    "artifact_ref": "sha256:" + "d" * 64,
                    "test_count": 11,
                    "failure_count": 0,
                    "error_count": 0,
                    "skipped_count": 0,
                    "producer": {
                        "issuer": "https://gitlab.example.test",
                        "project_id": "42",
                        "pipeline_id": "314",
                        "job_id": "159",
                        "commit_sha": attested_revision,
                        "ref": "demo/agentic",
                        "ref_protected": True,
                    },
                },
                "candidate": {
                    "result": "passed",
                    "format": "junit",
                    "artifact_ref": "sha256:" + "e" * 64,
                    "test_count": 13,
                    "failure_count": 0,
                    "error_count": 0,
                    "skipped_count": 0,
                    "producer": {
                        "issuer": "https://gitlab.example.test",
                        "project_id": "42",
                        "pipeline_id": "314",
                        "job_id": "160",
                        "commit_sha": attested_revision,
                        "ref": "demo/agentic",
                        "ref_protected": True,
                    },
                },
            },
            "candidate_config_sha256": candidate_config_sha256(config),
            "candidate_config_version": int(config.version or 1),
            "shadow_observation": {
                "source": "pytest",
                "source_ref": "",
                "window_started_at": started_at.isoformat(),
                "window_ended_at": ended_at.isoformat(),
                "runtime_revision": attested_revision,
                "candidate_config_sha256": candidate_config_sha256(config),
                "candidate_config_version": int(config.version or 1),
                "actions": counters,
            },
            "trusted_runner": {
                "issuer": "https://gitlab.example.test",
                "project_id": "42",
                "pipeline_id": "314",
                "job_id": "159",
                "commit_sha": attested_revision,
                "ref": "demo/agentic",
                "ref_protected": True,
            },
            "promoted_by": "pytest-operator",
            "promoted_at": validated_at.isoformat(),
        }
        source_rows = []
        for index, action in enumerate(group):
            row_id = str(uuid4())
            timestamp = observed_at + timedelta(microseconds=index)
            source_row = build_source_manifest_row(
                row_id=row_id,
                timestamp=timestamp,
                action=action,
                evaluation_count=5,
                runtime_revision=attested_revision,
                candidate_config_sha256=attestation["candidate_config_sha256"],
                candidate_config_version=attestation["candidate_config_version"],
                counters={
                    "legacy_allowed": 4,
                    "legacy_denied": 1,
                    "candidate_allowed": 4,
                    "candidate_denied": 1,
                    "matches": 5,
                    "mismatches": 0,
                },
            )
            source_rows.append(source_row)
            session.add(
                AuditLog(
                    id=row_id,
                    workspace_id=str(config.workspace_id),
                    timestamp=timestamp.astimezone(UTC).replace(tzinfo=None),
                    event_type="iam.shadow.evaluation",
                    actor="pytest-shadow-runner",
                    details={
                        "origin": "server",
                        "resource": {"kind": action.split(".", maxsplit=1)[0]},
                        "action": action,
                        "evaluation_count": 5,
                        "legacy_allowed": 4,
                        "legacy_denied": 1,
                        "candidate_allowed": 4,
                        "candidate_denied": 1,
                        "matches": 5,
                        "mismatches": 0,
                        "policy_id": "pytest-policy-v2",
                        "policy_version": 2,
                        "configured_mode": "shadow",
                        "runtime_revision": attested_revision,
                        "candidate_config_sha256": attestation["candidate_config_sha256"],
                        "candidate_config_version": attestation["candidate_config_version"],
                    },
                )
            )
        source_manifest = {
            "schema_version": 1,
            "workspace_id": str(config.workspace_id),
            "actions": group,
            "window_started_at": started_at.isoformat(),
            "window_ended_at": ended_at.isoformat(),
            "event_type": "iam.shadow.evaluation",
            "runtime_revision": attested_revision,
            "candidate_config_sha256": attestation["candidate_config_sha256"],
            "candidate_config_version": attestation["candidate_config_version"],
            "rows": source_rows,
        }
        attestation["shadow_observation"]["source_ref"] = sha256_ref(source_manifest)
        receipt_document = build_promotion_receipt_document(
            workspace_id=str(config.workspace_id),
            promotion=attestation,
            source_manifest=source_manifest,
        )
        receipt_ref = sha256_ref(receipt_document)
        receipt_id = str(uuid4())
        session.add(
            AuditLog(
                id=receipt_id,
                workspace_id=str(config.workspace_id),
                timestamp=validated_at.astimezone(UTC).replace(tzinfo=None),
                event_type=PROMOTION_EVENT_TYPE,
                actor=attestation["promoted_by"],
                details={"artifact_ref": receipt_ref, "document": receipt_document},
            )
        )
        attestation[PROMOTION_RECEIPT_KEY] = {
            "audit_id": receipt_id,
            "artifact_ref": receipt_ref,
        }
        attestations = policy.setdefault("enforcement_attestations", {})
        for action in group:
            modes[action] = "enforce"
            attestations[action] = copy.deepcopy(attestation)
        config.capability_overrides = payload
        session.flush()
        return attestation

    return _attest
