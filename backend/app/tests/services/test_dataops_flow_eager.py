"""Published DataPrep ports reach real eager SQL workers and canvas checkpoints."""

import copy

import polars as pl
import pytest

from app.core.config import settings
from app.models.recipe import RecipeExecution
from app.models.run import SkillInvocation
from app.models.skill import Skill
from app.models.tabular import TabularDataset
from app.services.run_engine.dag import _node_data_badge, execute_run_dag
from app.services.skills_registry.seed import SEED_SKILLS
from app.services.systems.flow_ingress import create_published_ingress_run
from app.services.tabular_datasets import read_frame, register_frame
from app.tests.services import test_service_contracts
from scripts import seed_dataops_showcase as seed

setup = test_service_contracts.setup


def test_port_badges_preserve_zero_and_strip_non_public_fields():
    badge = _node_data_badge(
        {"_data_prep": {"inputs": {"in": {"dataset_id": "spoof", "rows": 9000}}}},
        {
            "output": {
                "dataset_id": "train-version",
                "rows": 3,
                "inputs": {"in": {"dataset_id": "source-version", "rows": 3}},
                "outputs": {
                    "train": {"dataset_id": "train-version", "rows": 3, "storage_key": "private"},
                    "test": {"dataset_id": "empty-version", "rows": 0, "schema": ["private"]},
                },
            }
        },
    )
    assert badge == {
        "dataset_id": "train-version",
        "rows_in": 3,
        "rows_out": 3,
        "inputs": {"in": {"dataset_id": "source-version", "rows": 3}},
        "outputs": {
            "train": {"dataset_id": "train-version", "rows": 3},
            "test": {"dataset_id": "empty-version", "rows": 0},
        },
    }


@pytest.mark.parametrize("mode", ["strict", "overlay"])
async def test_published_prepare_join_split_two_sql_workers(mode, setup, monkeypatch):
    s = setup
    for key, value in {
        "worker_eager_mode": True,
        "tabular_data_enabled": True,
        "dataops_enabled": True,
        "dataops_write_delta_enabled": False,
    }.items():
        monkeypatch.setattr(settings, key, value)
    s.workspace.settings = {
        **s.workspace.settings,
        "features": {
            **s.workspace.settings["features"],
            "flow_publication_v1": True,
            "flow_v3_dag_authoritative": True,
            "dataops_enabled": True,
        },
    }
    skills = {}
    for definition in SEED_SKILLS:
        if definition["slug"] in {"data_prep_v1", "sql_transform_v1"}:
            row = Skill(**copy.deepcopy(definition), is_seeded="Y")
            s.db.add(row)
            skills[row.slug] = row
    left = register_frame(
        s.db,
        workspace_id=s.workspace.id,
        name="Customers",
        frame=pl.DataFrame(
            {
                "id": [1, 2, 3, 4],
                "amount": [10, 20, 30, 40],
            }
        ),
    )
    right = register_frame(
        s.db,
        workspace_id=s.workspace.id,
        name="Segments",
        frame=pl.DataFrame(
            {
                "id": [1, 2, 3, 4],
                "segment": ["train", "test", "train", "test"],
            }
        ),
    )
    s.db.commit()

    def prep(identifier, operation, params, *, sources=None, outputs=None):
        return seed._node(
            identifier,
            "data_prep_v1",
            skills,
            params={
                "spec": {"version": 1, "operation": operation, "params": params},
                "sources": sources or [],
                "outputs": outputs or [{"port": "out", "name": identifier}],
                "placement": "local",
            },
        )

    graph = {
        "schema_version": 3,
        "io_mode": mode,
        "nodes": [
            {"id": "source", "kind": "source", "config": {"ingress_kind": "manual"}},
            prep(
                "prepare",
                "prepare",
                {
                    "steps": [
                        {
                            "id": "amount-twice",
                            "kind": "formula",
                            "enabled": True,
                            "params": {"output": "twice", "expression": "amount * 2"},
                        }
                    ]
                },
            ),
            prep(
                "join",
                "join",
                {
                    "how": "inner",
                    "on": [{"left": "id", "right": "id", "op": "eq"}],
                    "merge_keys": True,
                },
                sources=[{"port": "right", "dataset_id": right.id}],
            ),
            prep(
                "split",
                "split",
                {
                    "method": "condition",
                    "outputs": [{"port": "train", "filter": "segment = 'train'"}],
                    "else_port": "test",
                },
                outputs=[
                    {"port": "train", "name": "Training"},
                    {"port": "test", "name": "Testing"},
                ],
            ),
            *[
                seed._node(
                    "sql-" + port,
                    "sql_transform_v1",
                    skills,
                    params={
                        "sql": "SELECT id, twice, segment FROM input ORDER BY id",
                        "output_name": "SQL " + port,
                    },
                )
                for port in ("train", "test")
            ],
            {
                "id": "sink",
                "kind": "sink",
                "config": {
                    "inputs_map": {
                        "train": {"node_id": "sql-train", "path": ["dataset_id"]},
                        "test": {"node_id": "sql-test", "path": ["dataset_id"]},
                    }
                },
            },
        ],
        "edges": [
            {"from": "source", "to": "prepare"},
            {"from": "prepare", "to": "join", "to_port": "left"},
            {"from": "join", "to": "split", "to_port": "in"},
            *[
                {"from": "split", "from_port": port, "to": "sql-" + port}
                for port in ("train", "test")
            ],
            *[{"from": "sql-" + port, "to": "sink"} for port in ("train", "test")],
        ],
    }
    # Strict mode requires explicit payload bindings. Read the dataset_id from
    # the edge's selected envelope, so this exercises from_port routing rather
    # than bypassing it with a VariableRef into split.outputs.
    for node in graph["nodes"]:
        if node["id"].startswith("sql-"):
            node["config"]["passthrough_inputs"] = ["dataset_id"]
    system = seed._system(
        s.db, s.workspace, s.owner, "ports-" + mode, graph, list(skills), skills, [], True
    )
    s.db.commit()
    run = create_published_ingress_run(
        s.db,
        system_id=system.id,
        workspace=s.workspace,
        ingress_id="source",
        kind="manual",
        payload={"dataset_id": left.id},
        initiated_by_user_id=s.owner.id,
    )
    s.db.commit()
    assert run.execution_contract["runtime_mode"] == "dag_" + mode
    outcome = await execute_run_dag(run.id)
    s.db.expire_all()
    assert run.status == "completed", {
        "outcome": outcome,
        "error": run.error,
        "checkpoints": run.checkpoints,
    }
    calls = s.db.query(SkillInvocation).filter_by(run_id=run.id).all()
    assert len(calls) == 5 and all(call.status == "completed" for call in calls)
    executions = {row.node_id: row for row in s.db.query(RecipeExecution).filter_by(run_id=run.id)}
    assert set(executions) == {"prepare", "join", "split", "sql-train", "sql-test"}
    assert all(row.status == "succeeded" for row in executions.values())
    assert executions["join"].input_json["inputs"] == {
        "left": executions["prepare"].output_json["dataset_id"],
        "right": right.id,
    }
    assert executions["split"].input_json["inputs"] == {
        "in": executions["join"].output_json["dataset_id"]
    }
    split_outputs = executions["split"].output_json["outputs"]
    for port, identifiers, doubled in (("train", [1, 3], [20, 60]), ("test", [2, 4], [40, 80])):
        execution = executions["sql-" + port]
        result = s.db.get(TabularDataset, execution.output_json["dataset_id"])
        frame = read_frame(result).sort("id")
        assert frame.to_dicts() == [
            {"id": identifier, "twice": value, "segment": port}
            for identifier, value in zip(identifiers, doubled)
        ]
        assert result.parent_ids == [split_outputs[port]["dataset_id"]]
    checkpoints = {
        cp["node_id"]: cp
        for cp in run.checkpoints or []
        if cp.get("kind") == "node_end" and cp.get("node_id") in executions
    }
    split_badge = checkpoints["split"]["data"]
    assert split_badge["outputs"] == {
        port: {"dataset_id": ref["dataset_id"], "rows": 2} for port, ref in split_outputs.items()
    }
    assert split_badge["rows_out"] == 4
    assert checkpoints["join"]["data"]["inputs"] == {
        "left": {"dataset_id": executions["prepare"].output_json["dataset_id"], "rows": 4},
        "right": {"dataset_id": right.id, "rows": 4},
    }
