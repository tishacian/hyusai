"""L20b — « Utilisé par » for a dataset (systems and models)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.system import System
from app.models.tabular import MLModel, TabularDataset
from app.models.workspace import Workspace
from app.services.tabular_datasets import dataset_used_by


@pytest.fixture()
def workspace(db_session) -> Workspace:
    ws = Workspace(
        id=str(uuid4()),
        name="Used-by",
        slug=f"used-by-{uuid4().hex[:8]}",
        settings={},
    )
    db_session.add(ws)
    db_session.commit()
    return ws


def test_dataset_used_by_lists_models_and_systems(db_session, workspace):
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Qualité commandes",
        objective="",
    )
    dataset = TabularDataset(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Commandes nettoyées",
        slug="commandes-nettoyees",
        version=2,
        source="transform",
        status="ready",
        system_id=system.id,
    )
    db_session.add_all([system, dataset])
    db_session.flush()
    db_session.add(
        MLModel(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name="Prévision retards",
            slug="prevision-retards",
            version=3,
            task="classification",
            algo="gradient_boosting",
            target="en_retard",
            features=["delai"],
            status="ready",
            is_champion=True,
            dataset_id=dataset.id,
            system_id=system.id,
        )
    )
    db_session.commit()

    payload = dataset_used_by(db_session, dataset=dataset)

    assert [row["slug"] for row in payload["models"]] == ["prevision-retards"]
    assert payload["models"][0]["is_champion"] is True
    assert payload["models"][0]["version"] == 3
    assert payload["systems"] == [{"id": system.id, "name": "Qualité commandes"}]


def test_dataset_used_by_is_empty_when_nothing_consumes_it(db_session, workspace):
    dataset = TabularDataset(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Orphan",
        slug="orphan",
        version=1,
        source="upload",
        status="ready",
    )
    db_session.add(dataset)
    db_session.commit()

    assert dataset_used_by(db_session, dataset=dataset) == {
        "models": [],
        "systems": [],
    }
