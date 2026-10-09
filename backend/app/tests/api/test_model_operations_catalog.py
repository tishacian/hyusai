"""Managed model operations are discoverable without weakening their authority.

The Skills were installed and callable by their managed Flow, yet their public
catalog detail returned 404 because no Capability claimed them. Test the same
catalog and binding contracts that the palette and Flow authoring use, including
explicit workspace curation and upgrading an already seeded database.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import skills
from app.models.capability import Capability
from app.models.skill import Skill
from app.models.user import User
from app.models.workspace import Workspace
from app.services.skills_registry.seed import reconcile_catalog
from app.services.system_catalog_bindings import (
    SystemCatalogBindingError,
    resolve_system_catalog_bindings,
)
from app.tests.iam_baseline import OPEN_IAM_FEATURES

CARRIER = "model_operations"
OPERATIONS = ("ml_monitor_model_v1", "ml_retrain_model_v1")


def _catalog(db, *, family="generic", catalog=None):
    workspace = Workspace(
        id="ws-model-catalog",
        slug="model-catalog",
        name="Model catalog",
        settings={
            "family": family,
            "catalog": catalog or {},
            "features": OPEN_IAM_FEATURES,
        },
    )
    user = User(id="model-catalog-user", username="model-catalog-user")
    db.add_all([workspace, user])
    reconcile_catalog(db, apply=True)

    app = FastAPI()
    app.include_router(skills.router, prefix="/skills")
    app.dependency_overrides[skills.get_current_workspace] = lambda: workspace
    app.dependency_overrides[skills.get_current_user] = lambda: user
    app.dependency_overrides[skills.get_db] = lambda: db
    return workspace, TestClient(app)


def _bind(db, workspace, rows):
    return resolve_system_catalog_bindings(
        db,
        workspace=workspace,
        system_id=None,
        capability_id=None,
        skill_ids=[row.id for row in rows],
        adaptive_policy_id=None,
    )


@pytest.mark.parametrize("family", ["generic", "andritz", "sentinel_ci", "nawa"])
def test_managed_operations_are_discoverable_inspectable_and_bindable(db_session, family):
    workspace, client = _catalog(db_session, family=family)
    response = client.get("/skills", params={"category": "Models"})
    assert response.status_code == 200
    palette = {row["slug"]: row for row in response.json()["skills"]}

    for slug in OPERATIONS:
        assert palette[slug]["visibility"] == {
            "visible": True,
            "reason": "capability",
            "capabilities": [CARRIER],
            "key": "",
        }
        detail = client.get(f"/skills/{slug}")
        assert detail.status_code == 200
        assert detail.json()["runtime_status"] == "bound"
        assert detail.json()["certification_level"] == "beta"
        assert "managed monitoring Flow" in detail.json()["description"]

    rows = db_session.query(Skill).filter(Skill.slug.in_(OPERATIONS)).all()
    assert set(_bind(db_session, workspace, rows).effective_skill_ids) == {row.id for row in rows}
    carrier = db_session.query(Capability).filter_by(slug=CARRIER).one()
    assert carrier.workspace_id is None and carrier.industry is None
    assert carrier.tier == "universal"
    assert carrier.value_per_outcome is None and carrier.pricing == {}


@pytest.mark.parametrize(
    ("curation", "reason"),
    [
        ({"show_universal": False}, "universal_hidden"),
        ({"hidden_capabilities": [CARRIER]}, "capability_not_enabled"),
        (
            {"hidden_skills": list(OPERATIONS), "enabled_skills": list(OPERATIONS)},
            "hidden_override",
        ),
    ],
)
def test_explicit_curation_still_filters_details_and_refuses_new_bindings(
    db_session, curation, reason
):
    workspace, client = _catalog(db_session, catalog=curation)
    response = client.get("/skills", params={"include_filtered": True})
    assert response.status_code == 200
    palette = {row["slug"]: row for row in response.json()["skills"]}
    for slug in OPERATIONS:
        assert palette[slug]["visibility"]["visible"] is False
        assert palette[slug]["visibility"]["reason"] == reason
        assert client.get(f"/skills/{slug}").status_code == 404

    rows = db_session.query(Skill).filter(Skill.slug.in_(OPERATIONS)).all()
    with pytest.raises(SystemCatalogBindingError) as caught:
        _bind(db_session, workspace, rows)
    assert caught.value.code == "skill_not_visible"


def test_carrier_can_be_enabled_explicitly_without_enabling_other_universal_skills(db_session):
    workspace, client = _catalog(
        db_session,
        catalog={"show_universal": False, "enabled_capabilities": [CARRIER]},
    )
    response = client.get("/skills")
    assert response.status_code == 200
    assert {row["slug"] for row in response.json()["skills"]} == set(OPERATIONS)
    rows = db_session.query(Skill).filter(Skill.slug.in_(OPERATIONS)).all()
    assert len(_bind(db_session, workspace, rows).skills) == 2


def test_reconciliation_claims_existing_skills_once_without_changing_workspace_policy(db_session):
    workspace, _ = _catalog(db_session, catalog={"hidden_skills": [OPERATIONS[0]]})
    carrier = db_session.query(Capability).filter_by(slug=CARRIER).one()
    db_session.delete(carrier)
    rows = db_session.query(Skill).filter(Skill.slug.in_(OPERATIONS)).all()
    original_ids = {row.id for row in rows}
    # Stand in for the live catalog immediately before this carrier shipped.
    stamp = datetime.utcnow() - timedelta(days=1)
    for row in rows:
        row.updated_at = stamp
        row.metrics = {"calls": 3}
    db_session.commit()

    check = reconcile_catalog(db_session, apply=False)
    assert check["in_sync"] is False
    assert check["capabilities"]["missing"] == [CARRIER]
    assert db_session.query(Capability).filter_by(slug=CARRIER).count() == 0
    applied = reconcile_catalog(db_session, apply=True)
    assert applied["capabilities"]["missing"] == [CARRIER]
    carrier = db_session.query(Capability).filter_by(slug=CARRIER).one()
    assert set(carrier.skill_ids) == original_ids
    carrier_stamp = carrier.updated_at

    again = reconcile_catalog(db_session, apply=True)
    assert again["in_sync"] is True
    assert again["skills"]["changed"] == again["capabilities"]["changed"] == {}
    assert again["skills"]["missing"] == again["capabilities"]["missing"] == []
    db_session.expire_all()
    assert carrier.updated_at == carrier_stamp
    for row in rows:
        assert row.updated_at == stamp and row.metrics == {"calls": 3}
    assert workspace.settings["catalog"] == {"hidden_skills": [OPERATIONS[0]]}
