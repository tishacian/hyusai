"""Fixture-only proof storage exercises live badge invalidation, never certification."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.models.connector_governance import ConnectorEvidence
from app.services.connectors import connections
from app.services.connectors import runtime_identity as runtime
from app.services.connectors.certification import ComponentIdentity
from app.tests.connectors.kit.test_certification_contract import NOW, bundle
from app.tests.services.test_connection_registry import setup as connection_setup

setup = connection_setup


@pytest.fixture()
def observed(db_session, setup, monkeypatch):
    from app.schemas.connection import ConnectionCreate

    monkeypatch.setattr(runtime.settings, "connector_runner_image_sha256", "b" * 64)
    monkeypatch.setattr(runtime.settings, "connector_environment_id", "fixture-host")
    monkeypatch.setattr(
        runtime, "kit_identity", lambda: {"version": "fixture-v1", "sha256": "c" * 64}
    )
    monkeypatch.setattr(runtime.metadata, "version", lambda package: "1.2.3")
    row = connections.create_connection(
        db_session,
        workspace_id=setup[0].id,
        actor=setup[2][0].id,
        data=ConnectionCreate(
            name="Runtime proof fixture",
            profile_key="postgresql",
            values={"host": "db.example", "database": "db", "username": "reader"},
            secret_refs={"password": setup[3]["ref"]},
        ),
    )
    output = {"connected": True, "source": "real", "server_version": "16.3"}
    observation = runtime.observe("postgresql", output)
    assert observation
    row.last_test = {
        "run_id": "test-run",
        "connection_revision": row.revision,
        "observed_at": (NOW - timedelta(hours=1)).isoformat(),
        "source": "real",
        "connected": True,
        "identity": observation,
    }
    db_session.commit()
    return row, ComponentIdentity.model_validate(observation)


def install(db, identity, *, kind="suite", age=None):
    proof = bundle(identity, kind=kind, at=age, environment_id="fixture-host")
    row = ConnectorEvidence(
        digest=proof.sha256,
        profile_key=identity.profile_key,
        identity_digest=identity.sha256,
        payload=proof.model_dump(mode="json"),
        reports=[],
        accepted_by=db.query(__import__("app.models.user", fromlist=["User"]).User).first().id,
        producer="fixture-only",
    )
    db.add(row)
    db.commit()
    return row


def test_badge_requires_observation_suite_and_live_canary(db_session, observed):
    row, identity = observed
    assert runtime.connection_decision(db_session, row, now=NOW).level == "unverified"
    install(db_session, identity)
    assert runtime.connection_decision(db_session, row, now=NOW).level == "verified"
    canary = install(db_session, identity, kind="canary")
    assert runtime.connection_decision(db_session, row, now=NOW).level == "certified"
    canary.revoked_at = NOW.replace(tzinfo=None)
    db_session.commit()
    assert runtime.connection_decision(db_session, row, now=NOW).level == "verified"


@pytest.mark.parametrize(
    "change",
    [
        "image",
        "image_missing",
        "environment_missing",
        "kit",
        "revision",
        "expired",
        "demo",
        "driver",
    ],
)
def test_changed_components_or_incomplete_identity_cannot_keep_positive_badge(
    db_session, observed, monkeypatch, change
):
    row, identity = observed
    install(db_session, identity)
    install(db_session, identity, kind="canary")
    if change == "image":
        monkeypatch.setattr(runtime.settings, "connector_runner_image_sha256", "f" * 64)
    if change == "image_missing":
        monkeypatch.setattr(runtime.settings, "connector_runner_image_sha256", "")
    if change == "environment_missing":
        monkeypatch.setattr(runtime.settings, "connector_environment_id", "")
    if change == "kit":
        monkeypatch.setattr(
            runtime, "kit_identity", lambda: {"version": "fixture-v2", "sha256": "f" * 64}
        )
    if change == "revision":
        row.revision += 1
    if change == "expired":
        row.last_test = {**row.last_test, "observed_at": (NOW - timedelta(days=31)).isoformat()}
    if change == "demo":
        row.last_test = {**row.last_test, "source": "demo"}
    if change == "driver":
        row.last_test = {
            **row.last_test,
            "identity": {
                **row.last_test["identity"],
                "drivers": [{"package": "psycopg2", "version": "9.0.0"}],
            },
        }
    assert runtime.connection_decision(db_session, row, now=NOW).level == "needs_requalification"


def test_failed_test_clears_previous_runtime_observation(db_session, observed):
    row, identity = observed
    install(db_session, identity)
    runtime.record_test(
        db_session,
        SimpleNamespace(
            id="failed",
            workspace_id=row.workspace_id,
            connection_id=row.id,
            connection_revision=row.revision,
        ),
        {},
    )
    assert row.last_test["identity"] is None and not row.last_test["connected"]
    assert runtime.connection_decision(db_session, row, now=NOW).level == "needs_requalification"


@pytest.mark.parametrize("kind", ["api", "protocol", "", None, "server", "absent"])
def test_api_or_protocol_version_is_never_a_server_identity(monkeypatch, kind):
    monkeypatch.setattr(runtime.settings, "connector_runner_image_sha256", "b" * 64)
    monkeypatch.setattr(runtime.metadata, "version", lambda package: "1.2.3")
    monkeypatch.setattr(
        runtime, "kit_identity", lambda: {"version": "fixture-v1", "sha256": "c" * 64}
    )
    output = {"connected": True, "source": "real", "server_version": "16.3"}
    if kind != "absent":
        output["version_kind"] = kind
    identity = runtime.observe("postgresql", output)
    assert (identity is not None) == (kind in {"server", "absent"})


def test_missing_driver_or_demo_is_never_observed(monkeypatch):
    monkeypatch.setattr(runtime.settings, "connector_runner_image_sha256", "b" * 64)

    def missing(package):
        raise runtime.metadata.PackageNotFoundError(package)

    monkeypatch.setattr(runtime.metadata, "version", missing)
    assert (
        runtime.observe(
            "postgresql", {"source": "demo", "connected": False, "server_version": "16.3"}
        )
        is None
    )
    assert (
        runtime.observe(
            "postgresql", {"source": "real", "connected": True, "server_version": "16.3"}
        )
        is None
    )
