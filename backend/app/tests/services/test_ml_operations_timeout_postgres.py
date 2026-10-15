"""A model lock cannot turn a quota refusal into an unbounded telemetry wait."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ml_operations import MLAlert, MLInferenceUsage
from app.models.tabular import MLModel, MLModelApiKey
from app.services import ml_operations as usage
from app.services.tabular_datasets import TabularError
from app.services.tabular_predict import mint_api_key, predict_rows
from app.tests.services.test_ml_operations_postgres import pg as pg_fixture

pg = pg_fixture


@pytest.mark.parametrize("operation", ["inference", "exposure"])
def test_quota_refusal_returns_while_model_remains_locked(pg, monkeypatch, operation):
    monkeypatch.setattr(settings, "ml_predict_rows_per_minute", 1)
    monkeypatch.setattr(settings, "ml_max_exposed_models", 1)
    with Session(pg) as db:
        model = db.get(MLModel, "model")
        model.signature_json = {"inputs": [{"name": "x", "type": "float"}]}
        exposed = MLModel(
            id="already-exposed",
            workspace_id=model.workspace_id,
            name="Already exposed",
            slug="already-exposed",
            task="classification",
            algo="linear",
            target="label",
            status="ready",
        )
        db.add(exposed)
        db.flush()
        db.add(
            MLModelApiKey(
                workspace_id=model.workspace_id,
                model_id=exposed.id,
                name="Test fixture",
                key_prefix="fixture",
                key_sha256="0" * 64,
            )
        )
        db.commit()

    sqlstates = []

    def record_failure(context):
        sqlstates.append(getattr(context.original_exception, "pgcode", None))

    def refused_request():
        with Session(pg) as db:
            model = db.get(MLModel, "model")
            with pytest.raises(TabularError) as caught:
                if operation == "inference":
                    # Two rows exceed the real admission budget before loading
                    # a pipeline; no patched predictor or simulated quota error.
                    predict_rows(db, model, [{"x": 1}, {"x": 2}], version=1, store=False)
                else:
                    mint_api_key(db, model=model)
            # The telemetry timeout must preserve the original public refusal.
            return caught.value.code

    event.listen(pg, "handle_error", record_failure)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool, Session(pg) as blocker:
            # NO KEY UPDATE permits the usage FK check but blocks emit_alert's
            # FOR UPDATE, matching an overlapping model metadata mutation.
            blocker.query(MLModel).filter_by(id="model").with_for_update(key_share=True).one()
            pending = pool.submit(refused_request)
            assert pending.result(timeout=3) == (
                "ML_RATE_LIMITED" if operation == "inference" else "ML_EXPOSURE_QUOTA_EXCEEDED"
            )
            # The holder is deliberately still active when the request returns.
            assert blocker.in_transaction()
            assert sqlstates == ["55P03"]
    finally:
        event.remove(pg, "handle_error", record_failure)

    with Session(pg) as db:
        # The failed independent transaction leaves neither partial usage nor
        # an alert. Its failure cannot create a key for the refused candidate.
        assert db.query(MLAlert).count() == 0
        assert db.query(MLInferenceUsage).count() == 0
        assert db.query(MLModelApiKey).filter_by(model_id="model").count() == 0


def test_accounting_sql_timeouts_are_transaction_local(pg):
    with Session(pg) as caller:
        with usage._failure_accounting_session(caller) as audit:
            assert audit.execute(text("SHOW lock_timeout")).scalar_one() == "250ms"
            assert audit.execute(text("SHOW statement_timeout")).scalar_one() == "1s"
            audit.commit()
            # A new transaction on the same Session recovers the connection's
            # original fixture defaults rather than leaking telemetry limits.
            assert audit.execute(text("SHOW lock_timeout")).scalar_one() == "5s"
            assert audit.execute(text("SHOW statement_timeout")).scalar_one() == "10s"
