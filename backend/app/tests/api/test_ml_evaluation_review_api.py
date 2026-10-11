"""The review route shares model-card auth and cannot write training state."""

from uuid import uuid4

from app.models.tabular import MLModel
from app.models.workspace import Workspace
from app.tests.api.test_ml_models_api import (  # noqa: F401
    _stub_harness,
    _train,
    client,
    dataset,
    user,
    workspace,
)


def test_review_route_is_scoped_and_only_reads(client, dataset, db_session, monkeypatch):
    _stub_harness(monkeypatch)
    model = _train(client, dataset).json()["model"]
    before = db_session.query(MLModel).count()
    answer = client.get(f"/ml-models/{model['id']}/evaluation-review")
    assert answer.status_code == 200
    assert answer.json()["mode"] == "proposal_only" and answer.json()["proposals"] == []
    assert db_session.query(MLModel).count() == before
    foreign_workspace = Workspace(
        id=str(uuid4()), name="Foreign", slug=f"foreign-{uuid4().hex[:8]}"
    )
    db_session.add(foreign_workspace)
    foreign = MLModel(
        id=str(uuid4()),
        workspace_id=foreign_workspace.id,
        name="Foreign",
        slug="foreign",
        task="classification",
        algo="linear",
        target="churn",
        status="ready",
    )
    db_session.add(foreign)
    db_session.commit()
    denied = client.get(f"/ml-models/{foreign.id}/evaluation-review")
    assert denied.status_code == 404
    assert denied.json()["detail"]["code"] == "ML_MODEL_NOT_FOUND"
