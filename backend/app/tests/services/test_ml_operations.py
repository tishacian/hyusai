"""Serving accounting never invents cost or broadens workspace permissions."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import ml_operations as api
from app.core.config import settings
from app.models.ml_operations import MLInferenceUsage, MLUsageRollup
from app.models.tabular import MLModel, MLModelApiKey
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services import ml_operations as service


@pytest.fixture()
def case(db_session, monkeypatch):
    for flag in ("ml_operations_enabled", "ml_alerts_enabled"):
        monkeypatch.setitem(settings.__dict__, flag, True)
    workspace = Workspace(id=str(uuid4()), name="ML Operations", slug="mlops-" + uuid4().hex[:8])
    other_workspace = Workspace(id=str(uuid4()), name="Other", slug="other-" + uuid4().hex[:8])
    admin = User(id=str(uuid4()), username="ops-" + uuid4().hex, role="user", is_active=True)
    reader = User(id=str(uuid4()), username="reader-" + uuid4().hex, role="user", is_active=True)
    db_session.add_all([workspace, other_workspace, admin, reader])
    db_session.flush()
    db_session.add_all(
        [
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=admin.id,
                role="admin",
                role_template="workspace_admin",
            ),
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=reader.id,
                role="member",
                role_template="workspace_reader",
            ),
        ]
    )

    def model(w, name):
        return MLModel(
            id=str(uuid4()),
            workspace_id=w.id,
            name=name,
            slug=name.lower(),
            task="classification",
            algo="linear",
            target="label",
            status="ready",
            created_by=admin.id,
        )

    m, other = model(workspace, "Endpoint"), model(other_workspace, "Private")
    db_session.add_all([m, other])
    db_session.flush()
    for row in (m, other):
        db_session.add(
            MLModelApiKey(
                id=str(uuid4()),
                workspace_id=row.workspace_id,
                model_id=row.id,
                name="key metadata",
                key_prefix="key",
                key_sha256=uuid4().hex + uuid4().hex,
            )
        )
    db_session.commit()
    return SimpleNamespace(
        workspace=workspace,
        other_workspace=other_workspace,
        admin=admin,
        reader=reader,
        model=m,
        other=other,
    )


def client(db, case, user=None):
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_db] = lambda: db
    app.dependency_overrides[api.get_current_user] = lambda: user or case.admin
    app.dependency_overrides[api.get_current_workspace] = lambda: case.workspace
    return TestClient(app)


def add_usage(db, model, duration=12, **kwargs):
    identity = service.record_inference(
        db,
        requested=model,
        served=model,
        caller="api_key",
        row_count=kwargs.pop("row_count", 10),
        duration_ms=duration,
        **kwargs,
    )
    row = db.get(MLInferenceUsage, identity)
    row.created_at = datetime(2026, 10, 15, 12, 1)
    return row


def test_no_payloads_and_redacted_error(db_session, case):
    row = add_usage(db_session, case.model, error_code="postgres://user:password@host")
    assert row.error_code == "ML_INFERENCE_FAILED"
    assert not {"payload_json", "output_json", "exception", "api_key"} & set(
        row.__table__.columns.keys()
    )


def test_disabled_usage_is_noop(db_session, case, monkeypatch):
    monkeypatch.setitem(settings.__dict__, "ml_operations_enabled", False)
    assert (
        service.record_inference(
            db_session,
            requested=case.model,
            served=case.model,
            caller="api_key",
            row_count=1,
            duration_ms=1,
        )
        is None
    )
    assert db_session.query(MLInferenceUsage).count() == 0


def test_idempotent_event_and_rollup(db_session, case):
    first = add_usage(db_session, case.model, event_id="same")
    second = add_usage(db_session, case.model, event_id="same")
    assert first.id == second.id
    assert service.rollup_usage(db_session) == 1
    assert service.rollup_usage(db_session) == 0
    assert db_session.query(MLUsageRollup).one().requests == 1


def test_cross_scope_rejected(db_session, case):
    with pytest.raises(ValueError, match="SCOPE"):
        service.record_inference(
            db_session,
            requested=case.model,
            served=case.other,
            caller="session",
            row_count=1,
            duration_ms=1,
        )


def test_merge_quantiles_not_average_percentiles(db_session, case):
    for _ in range(100):
        add_usage(db_session, case.model, duration=1)
    high = add_usage(db_session, case.model, duration=1000)
    high.created_at += timedelta(minutes=5)
    assert service.rollup_usage(db_session, limit=30) == 30
    db_session.commit()
    assert service.rollup_usage(db_session, limit=1000) == 71
    result = service.summarize(db_session.query(MLUsageRollup).all())
    assert result["requests"] == 101
    assert result["p50_ms"] == result["p95_ms"] == 1
    assert result["quantile_method"] == "histogram_upper_bound"


def test_errors_cost_unknown_and_measured_zero(db_session, case):
    add_usage(db_session, case.model, measured_cost_usd=0, row_count=2)
    add_usage(db_session, case.model, error_code="ML_INPUT_INVALID", row_count=0, tariff_cost_usd=3)
    service.rollup_usage(db_session)
    result = service.summarize(db_session.query(MLUsageRollup).all())
    assert result["errors"] == 1 and result["error_rate"] == 0.5
    assert result["unknown_cost_requests"] == 1
    assert result["measured_cost_per_1000_rows_usd"] == 0 and result["tariff_cost_usd"] == 3
    assert service.summarize([])["measured_cost_usd"] is None


def test_nonfinite_and_overflow(db_session, case):
    row = add_usage(
        db_session,
        case.model,
        duration=float("nan"),
        measured_cost_usd=float("inf"),
        cpu_seconds=-2,
    )
    assert row.duration_ms is None and row.measured_cost_usd is None and row.cpu_seconds is None
    add_usage(db_session, case.model, duration=1e10)
    service.rollup_usage(db_session)
    result = service.summarize(db_session.query(MLUsageRollup).all())
    assert result["latency_overflow"] == 1 and result["p95_ms"] is None


def test_windows_exclude_open_bucket(db_session, case):
    add_usage(db_session, case.model)
    service.rollup_usage(db_session)
    assert (
        service.model_metrics(db_session, case.model, now=datetime(2026, 10, 15, 12, 4))["24h"][
            "requests"
        ]
        == 0
    )
    result = service.model_metrics(db_session, case.model, now=datetime(2026, 10, 15, 12, 6))["24h"]
    assert result["requests"] == 1 and result["until"] == "2026-10-15T12:05:00"


def test_list_scopes_and_key_metadata_only(db_session, case):
    r = client(db_session, case).get("/ml-operations/endpoints")
    assert r.status_code == 200, r.text
    assert [m["id"] for m in r.json()["items"]] == [case.model.id]
    assert "key_sha256" not in r.text and "key_prefix" not in r.text
    assert (
        client(db_session, case, case.reader).get("/ml-operations/endpoints").json()["items"] == []
    )


def test_platform_scope_admin_only(db_session, case):
    assert (
        client(db_session, case).get("/ml-operations/endpoints?scope=platform").status_code == 403
    )
    case.admin.role = "admin"
    db_session.commit()
    r = client(db_session, case).get("/ml-operations/endpoints?scope=platform")
    assert r.status_code == 200 and r.json()["total"] == 2


def test_system_read_boundaries(db_session, case, monkeypatch):
    from app.models.system import System

    system = System(id=str(uuid4()), workspace_id=case.workspace.id, name="Private")
    db_session.add(system)
    db_session.flush()
    case.model.system_id = system.id
    db_session.commit()
    monkeypatch.setattr(api, "readable_systems", lambda *args, **kwargs: [])
    assert client(db_session, case).get("/ml-operations/endpoints?scope=system").status_code == 422
    assert (
        client(db_session, case, case.reader)
        .get("/ml-operations/endpoints?scope=system&system_id=" + system.id)
        .json()["items"]
        == []
    )


def test_revoked_membership_denied(db_session, case):
    db_session.query(WorkspaceMember).filter_by(user_id=case.reader.id).delete()
    db_session.commit()
    for path in ("features", "endpoints", "alerts"):
        assert (
            client(db_session, case, case.reader).get("/ml-operations/" + path).status_code == 403
        )


def test_disabled_routes(db_session, case, monkeypatch):
    monkeypatch.setitem(settings.__dict__, "ml_operations_enabled", False)
    c = client(db_session, case)
    for path in ("endpoints", "alerts", "channels", "deliveries"):
        assert c.get("/ml-operations/" + path).status_code == 404
    assert c.get("/ml-operations/features").json()["enabled"] is False


def test_model_scoped_audit_is_metadata_only(db_session, case):
    from app.models.audit import AuditLog

    db_session.add(
        AuditLog(
            id=str(uuid4()),
            workspace_id=case.workspace.id,
            event_type="ml.publish",
            details={"model_id": case.model.id, "secret": "not-returned"},
        )
    )
    db_session.commit()
    r = client(db_session, case).get("/ml-operations/endpoints")
    assert r.json()["items"][0]["last_audit"]["event"] == "ml.publish"
    assert "not-returned" not in r.text


def test_catalogue_tariff_is_separate_from_measured_cost_and_cpu(db_session, case):
    from app.models.skill import Skill

    skill = Skill(
        id=str(uuid4()),
        workspace_id=case.workspace.id,
        name="Prediction",
        slug="priced-prediction",
        pricing={
            "unit": "per_1000_predictions",
            "unit_price": 2.5,
            "currency": "USD",
            "password": "not-copied",
        },
    )
    db_session.add(skill)
    case.model.published_skill_id = skill.id
    case.model.published_skill_slug = skill.slug
    db_session.flush()
    usage = add_usage(db_session, case.model, row_count=250)
    assert usage.tariff_cost_usd == 0.625
    assert usage.tariff_evidence["state"] == "calculated"
    assert usage.tariff_evidence["quantity"] == 0.25
    assert "not-copied" not in str(usage.tariff_evidence)
    assert usage.measured_cost_usd is None
    assert usage.cpu_seconds is None
    # Another unpriced call must not dilute the tariff denominator.
    skill.pricing = {}
    db_session.flush()
    add_usage(db_session, case.model, row_count=750)
    service.rollup_usage(db_session)
    metrics = service.summarize(db_session.query(MLUsageRollup).all())
    assert metrics["tariff_cost_per_1000_rows_usd"] == 2.5
    assert metrics["tariff_requests"] == 1
    assert metrics["tariff_rows"] == 250
    assert metrics["measured_cost_per_1000_rows_usd"] is None
    assert metrics["unknown_cost_requests"] == 2
    assert metrics["cpu_seconds"] is None


@pytest.mark.parametrize(
    "pricing",
    [
        {},
        {"unit": "per_prediction", "unit_price": 5, "currency": "EUR"},
        {"unit": "per_1k_tokens", "unit_price": 1, "currency": "USD"},
    ],
)
def test_absent_or_incompatible_tariff_stays_unknown(db_session, case, pricing):
    from app.models.skill import Skill

    skill = Skill(
        id=str(uuid4()),
        workspace_id=case.workspace.id,
        name="Prediction",
        slug="unknown-prediction",
        pricing=pricing,
    )
    db_session.add(skill)
    case.model.published_skill_id = skill.id
    case.model.published_skill_slug = skill.slug
    db_session.flush()
    usage = add_usage(db_session, case.model)
    assert usage.tariff_cost_usd is None
    assert usage.measured_cost_usd is None


def test_cpu_zero_is_only_known_when_explicitly_measured(db_session, case):
    add_usage(db_session, case.model, cpu_seconds=0)
    service.rollup_usage(db_session)
    metrics = service.summarize(db_session.query(MLUsageRollup).all())
    assert metrics["cpu_seconds"] == 0
    assert metrics["cpu_requests"] == 1


@pytest.mark.parametrize(
    "confirmed, expected", [(None, None), (False, None), ("true", None), (True, 0)]
)
def test_generated_ml_zero_requires_explicit_confirmation(db_session, case, confirmed, expected):
    from app.models.skill import Skill

    pricing = {"unit": "per_prediction", "unit_price": 0.0, "currency": "USD"}
    if confirmed is not None:
        pricing["confirmed"] = confirmed
    skill = Skill(
        id=str(uuid4()),
        workspace_id=case.workspace.id,
        name="Predict",
        slug="legacy-free",
        pricing=pricing,
    )
    db_session.add(skill)
    case.model.published_skill_id = skill.id
    case.model.published_skill_slug = skill.slug
    db_session.flush()
    usage = add_usage(db_session, case.model)
    assert usage.tariff_cost_usd == expected
    assert usage.measured_cost_usd is None
    if confirmed is True:
        assert usage.tariff_evidence["pricing_confirmed"] is True
    else:
        assert usage.tariff_evidence["reason"] == "pricing_zero_not_confirmed"


def test_journal_and_usage_commit_together_without_inputs(db_session, case):
    from app.models.tabular import MLPrediction
    from app.services.tabular_predict import journal_call

    prediction_id = journal_call(
        db_session, requested=case.model, served=case.model, caller="session",
        rows=[{"sensitive": "private-value"}], answers=[{"prediction": 1}],
        duration_ms=12, store=False,
    )
    db_session.rollback()
    prediction = db_session.get(MLPrediction, prediction_id)
    usage = db_session.query(MLInferenceUsage).one()
    assert prediction.payload_json == []
    assert usage.id == service.digest(case.workspace.id, prediction_id)
    assert usage.row_count == 1 and usage.error_code is None
    assert usage.tariff_cost_usd is None and usage.measured_cost_usd is None


def test_real_prediction_refusal_survives_caller_rollback(db_session, case, monkeypatch):
    from app.models.ml_operations import MLAlert
    from app.services import tabular_predict
    from app.services.tabular_datasets import TabularError

    monkeypatch.setattr(settings, "ml_predict_rate_per_minute", 1)
    monkeypatch.setattr(tabular_predict, "serving_version", lambda *a, **kw: case.model)
    monkeypatch.setattr(tabular_predict, "_interval_band", lambda *a: None)
    monkeypatch.setattr(tabular_predict, "coerce_rows", lambda model, rows: rows)
    payload_calls = []
    def payload(*args, **kwargs):
        payload_calls.append(1)
        return {"predictions": [{"prediction": 1}], "classes": [], "positive_label": None,
                "duration_ms": 1, "load_ms": 0, "cached": True}
    monkeypatch.setattr(tabular_predict, "_prediction_payload", payload)
    tabular_predict.predict_rows(db_session, case.model, [{"x": 1}], store=False)
    with pytest.raises(TabularError, match="ML_RATE_LIMITED"):
        tabular_predict.predict_rows(db_session, case.model, [{"x": "must-not-persist"}])
    db_session.rollback()
    assert len(payload_calls) == 1
    usage = db_session.query(MLInferenceUsage).filter_by(error_code="ML_RATE_LIMITED").one()
    assert usage.row_count == 0 and usage.duration_ms >= 0
    assert db_session.query(MLAlert).one().event_type == "quota_reached"
    assert service.rollup_usage(db_session) == 2
    metrics = db_session.query(MLUsageRollup).one()
    assert (metrics.requests, metrics.rows, metrics.errors) == (2, 1, 1)


def test_failed_prediction_logs_code_only_and_preserves_exception(db_session, case, monkeypatch):
    from app.services import tabular_predict

    monkeypatch.setattr(tabular_predict, "serving_version", lambda *a, **kw: case.model)
    monkeypatch.setattr(tabular_predict, "_interval_band", lambda *a: None)
    monkeypatch.setattr(tabular_predict, "coerce_rows", lambda model, rows: rows)
    failure = RuntimeError("secret-storage-password")
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(tabular_predict, "_prediction_payload", fail)
    with pytest.raises(RuntimeError) as caught:
        tabular_predict.predict_rows(db_session, case.model, [{"x": 1}])
    assert caught.value is failure
    db_session.rollback()
    row = db_session.query(MLInferenceUsage).one()
    assert row.error_code == "ML_INFERENCE_FAILED" and row.row_count == 0
    assert "secret-storage-password" not in str(row.__dict__)


def test_exposure_quota_alert_survives_refused_key_creation(db_session, case, monkeypatch):
    from app.models.ml_operations import MLAlert
    from app.services.tabular_predict import mint_api_key
    from app.services.tabular_datasets import TabularError

    monkeypatch.setattr(settings, "ml_max_exposed_models", 1)
    candidate = MLModel(workspace_id=case.workspace.id, name="Second", slug="second",
                        task="classification", algo="linear", target="label", status="ready")
    db_session.add(candidate)
    db_session.commit()
    with pytest.raises(TabularError, match="ML_EXPOSURE_QUOTA_EXCEEDED"):
        mint_api_key(db_session, model=candidate, created_by=case.admin.id)
    db_session.rollback()
    assert db_session.query(MLModelApiKey).filter_by(model_id=candidate.id).count() == 0
    assert db_session.query(MLAlert).one().state == "ML_EXPOSURE_QUOTA_EXCEEDED"


def test_forecast_counter_failure_does_not_double_count(db_session, case, monkeypatch):
    from app.models.tabular import MLPrediction
    from app.services import tabular_predict
    from app.services.ml import forecast_serving, runtime
    from app.services.huggingface import adapters

    case.model.task = "forecasting"
    case.model.family = "forecast_stats"
    db_session.commit()
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    monkeypatch.setattr(tabular_predict, "serving_version", lambda *a, **kw: case.model)
    monkeypatch.setattr(adapters, "require_model_foundation", lambda *a: None)
    monkeypatch.setattr(runtime, "serving_availability", lambda *a: (True, None))
    monkeypatch.setattr(forecast_serving, "answer_for", lambda *a, **kw: {"forecast": []})
    def fail(*args, **kwargs):
        raise RuntimeError("counter unavailable")
    monkeypatch.setattr(tabular_predict, "record_usage", fail)
    with pytest.raises(RuntimeError, match="counter unavailable"):
        forecast_serving.request_forecast(db_session, case.model, horizon=1)
    db_session.rollback()
    assert db_session.query(MLPrediction).count() == 0
    assert db_session.query(MLInferenceUsage).count() == 1
    assert db_session.query(MLInferenceUsage).one().error_code == "ML_INFERENCE_FAILED"
