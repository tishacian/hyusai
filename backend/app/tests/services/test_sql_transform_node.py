"""The SQL transform as a Flow node: config ownership and the DAG contract."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.tabular import TabularDataset
from app.models.workspace import Workspace
from app.services.run_engine.dag import (
    DagNode,
    _apply_transform_node_config,
    _passthrough_without_recipe,
)
from app.services.skills_registry.wrappers import _sql_transform_v1

pl = pytest.importorskip("polars")
pytest.importorskip("duckdb")


def _node(skill_slug: str, params: dict | None = None) -> DagNode:
    return DagNode(
        id="node-sql",
        type="task",
        kind="task",
        label="SQL",
        config={"params": params or {}},
        skill_slug=skill_slug,
        data={},
    )


def test_the_statement_is_graph_owned_and_caller_input_cannot_rewrite_it():
    node = _node(
        "sql_transform_v1",
        {"sql": "SELECT 1 AS a", "output_name": "Cohort", "sources": []},
    )
    # A hostile ingress payload trying to swap the query and the destination.
    node_input = {
        "sql": "SELECT * FROM secrets",
        "output_name": "hijacked",
        "customer_id": "C1",
    }

    _apply_transform_node_config(node, node_input)

    assert node_input["_transform"]["sql"] == "SELECT 1 AS a"
    assert node_input["_transform"]["output_name"] == "Cohort"
    assert node_input["_transform"]["node_id"] == "node-sql"
    # The raw config keys are gone from the data the statement sees.
    assert "sql" not in node_input and "output_name" not in node_input
    assert node_input["customer_id"] == "C1"


def test_a_non_transform_node_has_the_reserved_key_stripped():
    """Otherwise an ingress payload could smuggle one toward a downstream node."""

    node_input = {"_transform": {"sql": "SELECT * FROM secrets"}, "x": 1}

    _apply_transform_node_config(_node("llm_answer_v1"), node_input)

    assert "_transform" not in node_input
    assert node_input == {"x": 1}


def test_failure_envelopes_never_carry_the_statement_into_run_outputs():
    passthrough = _passthrough_without_recipe(
        {
            "_transform": {"sql": "SELECT * FROM input"},
            "_recipe": {"code": "print(1)"},
            "dataset_id": "abc",
        }
    )

    assert passthrough == {"dataset_id": "abc"}


@pytest.fixture()
def workspace(db_session) -> Workspace:
    ws = Workspace(
        id=str(uuid4()),
        name="SQL node",
        slug=f"sql-node-{uuid4().hex[:8]}",
        settings={},
    )
    db_session.add(ws)
    db_session.commit()
    return ws


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    return tmp_path / "store"


@pytest.mark.asyncio
async def test_the_wrapper_refuses_a_payload_without_graph_configuration():
    with pytest.raises(ValueError, match="transform_config_missing"):
        await _sql_transform_v1({"dataset_id": "x"}, {"workspace_id": "w"})


@pytest.mark.asyncio
async def test_the_wrapper_requires_a_workspace_scope():
    with pytest.raises(ValueError, match="transform_workspace_required"):
        await _sql_transform_v1({"_transform": {"sql": "SELECT 1"}}, {})


@pytest.mark.asyncio
async def test_the_wrapper_settles_a_transform_and_returns_a_dataset_envelope(
    db_session, workspace, store
):
    from app.services.tabular_datasets import register_frame

    upstream = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Customers",
        frame=pl.DataFrame({"customer_id": ["C1", "C2"], "churn": [1, 0]}),
        source="upload",
    )
    db_session.commit()

    result = await _sql_transform_v1(
        {
            "_transform": {
                "sql": "SELECT churn, count(*) AS n FROM input GROUP BY 1 ORDER BY 1",
                "output_name": "Churn split",
                "sources": [{"view": "input", "dataset_id": upstream.id}],
                "node_id": "node-sql",
            },
        },
        {"workspace_id": workspace.id, "run_id": "run-7"},
    )

    assert result["rows"] == 2 and result["columns"] == 2
    assert result["slug"] == "churn-split"
    assert result["duration_ms"] >= 0
    # The envelope is a reference, not the data: downstream nodes resolve the id.
    assert "preview" not in result

    row = db_session.query(TabularDataset).filter_by(id=result["dataset_id"]).one()
    assert row.run_id == "run-7" and row.node_id == "node-sql"
    assert row.parent_ids == [upstream.id]


@pytest.mark.asyncio
async def test_an_invalid_statement_fails_the_node_with_a_readable_reason(
    db_session, workspace, store
):
    from app.services.tabular_datasets import register_frame

    upstream = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Customers",
        frame=pl.DataFrame({"customer_id": ["C1"]}),
        source="upload",
    )
    db_session.commit()

    with pytest.raises(ValueError, match="SQL_FORBIDDEN_KEYWORD"):
        await _sql_transform_v1(
            {
                "_transform": {
                    "sql": "DROP TABLE input",
                    "output_name": "boom",
                    "sources": [{"dataset_id": upstream.id}],
                }
            },
            {"workspace_id": workspace.id},
        )
