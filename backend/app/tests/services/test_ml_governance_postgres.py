"""Real PostgreSQL proves multi-process admission and exposure serialization."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ml_governance import MLAdmissionCounter
from app.models.tabular import MLModel
from app.services.ml_governance import admit
from app.services.tabular_datasets import TabularError
from app.services.tabular_predict import mint_api_key
from app.tests.services.test_activity_observability_postgres import pg as pg


def model(db, slug):
    row = MLModel(
        id=str(uuid4()),
        workspace_id="pg-activity-ws",
        name=slug,
        slug=slug,
        task="regression",
        target="y",
        algo="ridge",
        status="ready",
    )
    db.add(row)
    db.commit()
    return row.id


def test_postgres_parallel_model_and_key_budget_is_exact(pg, monkeypatch):
    monkeypatch.setattr(settings, "ml_predict_rate_per_minute", 5)
    with Session(pg) as db:
        identifier = model(db, "concurrent")

    def reserve(_):
        with Session(pg) as db:
            try:
                admit(
                    db,
                    db.get(MLModel, identifier),
                    rows=3,
                    key_id="same-key",
                    now=datetime(2026, 10, 15, 12, 0),
                )
                return True
            except TabularError as exc:
                assert exc.code == "ML_RATE_LIMITED"
                return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(reserve, range(20)))
    assert sum(outcomes) == 5
    with Session(pg) as db:
        counters = db.query(MLAdmissionCounter).all()
        assert len(counters) == 2
        assert {(row.requests, row.rows) for row in counters} == {(5, 15)}


def test_postgres_exposure_quota_has_one_winner(pg, monkeypatch):
    monkeypatch.setattr(settings, "ml_max_exposed_models", 1)
    with Session(pg) as db:
        identifiers = [model(db, "first"), model(db, "second")]

    def expose(identifier):
        with Session(pg) as db:
            try:
                mint_api_key(db, model=db.get(MLModel, identifier))
                return True
            except TabularError as exc:
                assert exc.code == "ML_EXPOSURE_QUOTA_EXCEEDED"
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(expose, identifiers)) == [False, True]
