"""Model operations stay navigable without claiming ownership or reallocating cost."""

from copy import deepcopy
from datetime import datetime, timedelta

from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.tabular import MLModel
from app.models.workspace import Workspace
from app.tests.api.test_systems_flow_safety import _client, _seed


def _model(db, workspace, *, model_id="model-v1", slug="risk", version=1):
    row = MLModel(
        id=model_id,
        workspace_id=workspace.id,
        slug=slug,
        name=slug,
        version=version,
        task="classification",
        target="label",
        algo="linear",
        status="ready",
    )
    db.add(row)
    db.flush()
    return row


def _flow(model, *, pin=None):
    return {
        "nodes": [
            {
                "id": "score",
                "kind": "task",
                "config": {
                    "skill_slug": "ml_batch_score_v1",
                    "params": {"model_id": model.id, "pinned_version": pin},
                },
            }
        ],
        "edges": [],
    }


def test_categories_preserve_default_portfolio_and_legacy_monitor_links(db_session):
    workspace, user, business = _seed(db_session)
    monitor = System(
        id="monitor",
        workspace_id=workspace.id,
        name="Monitoring",
        status="active",
        settings={"ml_monitoring_model_id": "model-v1"},
        flow_definition={},
    )
    db_session.add(monitor)
    db_session.commit()
    api = _client(db_session, workspace, user)
    rows = api.get("/systems").json()["systems"]
    assert {row["id"] for row in rows} == {business.id, monitor.id}
    operation = next(row for row in rows if row["id"] == monitor.id)
    assert operation["category"] == "model_operations"
    assert operation["model_operation"] == {"kind": "model_monitoring", "model_id": "model-v1"}
    for category, expected in [("business", business.id), ("model_operations", monitor.id)]:
        assert [
            row["id"]
            for row in api.get("/systems", params={"category": category}).json()["systems"]
        ] == [expected]
    assert api.get("/systems", params={"category": "unknown"}).status_code == 422


def test_model_relation_is_plural_published_and_tenant_scoped(db_session):
    workspace, user, first = _seed(db_session)
    model = _model(db_session, workspace)
    challenger = _model(db_session, workspace, model_id="model-v2", version=2)
    first.flow_definition = _flow(challenger, pin=2)
    second = System(
        id="second",
        workspace_id=workspace.id,
        name="Second consumer",
        status="active",
        flow_definition={
            "nodes": [
                {
                    "id": "forecast",
                    "config": {
                        "skill_slug": "ml_forecast_v1",
                        "params": {"model_slug": model.slug},
                    },
                }
            ]
        },
    )
    draft = System(
        id="draft",
        workspace_id=workspace.id,
        name="Not published",
        status="draft",
        flow_definition=_flow(model),
    )
    different = _model(db_session, workspace, model_id="different", slug="different")
    misleading = System(
        id="mismatch",
        workspace_id=workspace.id,
        name="Other model",
        status="active",
        flow_definition=_flow(different),
    )
    misleading.flow_definition["nodes"][0]["config"]["params"]["model_slug"] = model.slug
    # The immutable publication has no model. An edited mirror must not turn
    # this into a published consumer.
    unpublished = System(
        id="unpublished",
        workspace_id=workspace.id,
        name="Edited mirror",
        status="active",
        flow_definition=_flow(model),
        published_flow_version_id="published-empty",
    )
    version = SystemVersion(
        id="published-empty",
        system_id=unpublished.id,
        workspace_id=workspace.id,
        version_number=1,
        flow_definition={"nodes": []},
    )
    foreign = Workspace(id="foreign", slug="foreign", name="Other tenant")
    db_session.add(foreign)
    db_session.flush()
    foreign_model = _model(db_session, foreign, model_id="foreign-model")
    foreign_system = System(
        id="foreign-system",
        workspace_id=foreign.id,
        name="Private",
        status="active",
        flow_definition=_flow(model),
    )
    db_session.add_all([second, draft, misleading, unpublished, version, foreign_system])
    db_session.commit()
    api = _client(db_session, workspace, user)
    response = api.get("/systems", params={"uses_model_id": model.id})
    assert response.status_code == 200
    payload = response.json()
    assert payload["reference_scope"] == "published_model_lineage"
    assert not payload["has_more"]
    rows = {row["id"]: row for row in payload["systems"]}
    assert set(rows) == {first.id, second.id}
    assert rows[first.id]["model_references"][0]["pinned_version"] == 2
    assert rows[second.id]["model_references"][0]["binding"] == "champion"
    assert api.get("/systems", params={"uses_model_id": foreign_model.id}).status_code == 404


def test_relation_filter_precedes_limit_and_reports_more(db_session):
    workspace, user, first = _seed(db_session)
    model = _model(db_session, workspace)
    first.flow_definition = _flow(model)
    second = System(
        id="second",
        workspace_id=workspace.id,
        name="Second",
        status="active",
        flow_definition=_flow(model),
    )
    unrelated = System(
        id="newest",
        workspace_id=workspace.id,
        name="Unrelated",
        status="active",
        flow_definition={},
        updated_at=datetime.utcnow() + timedelta(days=1),
    )
    db_session.add_all([second, unrelated])
    db_session.commit()
    payload = (
        _client(db_session, workspace, user)
        .get("/systems", params={"uses_model_id": model.id, "limit": 1})
        .json()
    )
    assert payload["has_more"]
    assert len(payload["systems"]) == 1
    assert payload["systems"][0]["id"] in {first.id, second.id}


def test_legacy_invalid_markers_are_not_model_operations(db_session):
    workspace, user, system = _seed(db_session)
    api = _client(db_session, workspace, user)
    for marker in [None, "", "   ", 123, {"id": "model"}]:
        system.settings = {"ml_monitoring_model_id": marker}
        db_session.commit()
        assert api.get("/systems", params={"category": "model_operations"}).json()["systems"] == []
        business = api.get("/systems", params={"category": "business"}).json()["systems"]
        assert len(business) == 1 and business[0]["category"] == "business"


def test_missing_model_id_falls_back_to_local_slug_like_serving_wrapper(db_session):
    from app.services.skills_registry.wrappers import _resolve_model

    workspace, user, system = _seed(db_session)
    model = _model(db_session, workspace)
    params = {"model_id": "missing-or-foreign", "model_slug": model.slug}
    system.flow_definition = {
        "nodes": [{"id": "score", "config": {"skill_slug": "ml_batch_score_v1", "params": params}}]
    }
    db_session.commit()
    assert _resolve_model(db_session, params, workspace.id).id == model.id
    rows = (
        _client(db_session, workspace, user)
        .get("/systems", params={"uses_model_id": model.id})
        .json()["systems"]
    )
    assert [row["id"] for row in rows] == [system.id]


def test_operation_identity_cannot_be_spoofed_removed_or_rebound_by_generic_settings(db_session):
    workspace, user, system = _seed(db_session)
    api = _client(db_session, workspace, user)
    forged = api.patch(
        f"/systems/{system.id}", json={"settings": {"ml_monitoring_model_id": "other"}}
    )
    assert forged.status_code == 409
    assert forged.json()["detail"]["code"] == "MODEL_OPERATION_BINDING_MANAGED"
    system.settings = {
        "ml_monitoring_model_id": "original",
        "model_operation": {"kind": "model_monitoring", "model_id": "original"},
    }
    db_session.commit()
    existing = deepcopy(system.settings)
    preserved = api.patch(f"/systems/{system.id}", json={"settings": {"custom": True}})
    assert preserved.status_code == 200, preserved.text
    assert preserved.json()["settings"] == {**existing, "custom": True}
    refused = api.patch(
        f"/systems/{system.id}", json={"settings": {"model_operation": {"model_id": "foreign"}}}
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "MODEL_OPERATION_BINDING_MANAGED"
