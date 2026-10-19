"""The generic workshop keeps Luma's exact data and native Work lineage contract."""

import copy
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import duckdb
import pyarrow as pa
import pytest

from app.core.config import settings
from app.models.run import SkillInvocation
from app.models.skill import Skill
from app.models.tabular import TabularDataset
from app.schemas.data_prep import bind_spec
from app.services.chains.dag_validator import validate_flow
from app.services.dataops.compiler import compile_prep
from app.services.dataops.flow import data_prep_issues
from app.services.dataops.types import describe
from app.services.ecommerce import composition, composition_upgrade, triage
from app.services.run_engine.dag import execute_run_dag
from app.services.skills_registry.seed import SEED_SKILLS
from app.services.tabular_datasets import read_rows, slugify
from app.tests.services.test_ecommerce_composition import (
    activate,
    create_run,
    environment,  # noqa: F401 - shared real native-flow fixture
    luma_artifact,  # noqa: F401 - shared production training harness
)

FIXTURES = Path(__file__).resolve().parents[4] / "docs/demo-runs/showcase-ecommerce/fixtures"
_spec = importlib.util.spec_from_file_location(
    "luma_visual_preparation_config", FIXTURES / "showcase_visual_prep/configuration.py"
)
config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(config)


def original_flow():
    return json.loads((FIXTURES / "showcase_learning/live_learning_plan.json").read_text())[
        "configuration"
    ]["flow_definition"]


def compiled_result(table):
    parameters = config.preparation_parameters()
    spec = bind_spec(parameters["spec"], parameters["outputs"])
    compiled = compile_prep(
        spec, {"in": describe(table.schema)}, arrow_schemas={"in": table.schema}
    )
    with duckdb.connect(config={"threads": 1}) as conn:
        conn.register("in", table)
        conn.register("input", table)
        result = conn.execute(compiled.sql, compiled.preview_parameters).to_arrow_table()
        expected = conn.execute(composition.PREPARE_SQL).to_arrow_table()
    return result, expected, compiled


def test_visual_configuration_changes_only_the_reviewed_preparation_and_its_ports():
    original = original_flow()
    graph = config.build_flow(original)
    assert original == original_flow()
    assert len(graph["nodes"]) == len(original["nodes"])
    assert len(graph["edges"]) == len(original["edges"])
    assert graph["runtime_contract"] == original["runtime_contract"]
    before = {node["id"]: node for node in original["nodes"]}
    after = {node["id"]: node for node in graph["nodes"]}
    assert all(
        after[key] == node
        for key, node in before.items()
        if key not in {"sav.prepare", "sav.score"}
    )
    assert after["sav.prepare"]["position"] == before["sav.prepare"]["position"]
    assert after["sav.prepare"]["config"]["skill_slug"] == "data_prep_v1"
    assert "inputs_map" not in after["sav.prepare"]["config"]
    assert after["sav.prepare"]["config"]["params"]["sources"] == []
    expected_score = copy.deepcopy(before["sav.score"])
    expected_score["config"].pop("inputs_map")
    expected_score["config"]["passthrough_inputs"] = ["dataset_id"]
    assert after["sav.score"] == expected_score
    assert not data_prep_issues(graph)
    assert validate_flow(graph) == []
    assert config.build_flow(graph) == graph


def test_preserves_unpublished_user_preparation_and_rejects_changed_reviewed_sql():
    draft = original_flow()
    custom = {"id": "nodePrepare", "kind": "task", "label": "User draft", "config": {}}
    draft["nodes"].append(copy.deepcopy(custom))
    patched = config.build_flow(draft)
    assert next(node for node in patched["nodes"] if node["id"] == "nodePrepare") == custom
    next(node for node in draft["nodes"] if node["id"] == "sav.prepare")["config"]["params"][
        "sql"
    ] += " LIMIT 2"
    with pytest.raises(ValueError, match="LUMA_PREPARATION_SOURCE_CHANGED"):
        config.build_flow(draft)


@pytest.mark.parametrize(
    "change, error",
    [
        ("source", "LUMA_PREPARATION_SOURCE_EDGE_CHANGED"),
        ("extra_source", "LUMA_PREPARATION_SOURCE_EDGE_CHANGED"),
        ("score_skill", "LUMA_PREPARATION_SCORE_BINDING_CHANGED"),
        ("score_source", "LUMA_PREPARATION_SCORE_EDGE_CHANGED"),
        ("input_port", "LUMA_PREPARATION_GRAPH_INVALID"),
        ("output_port", "LUMA_PREPARATION_GRAPH_INVALID"),
    ],
)
def test_idempotent_preparation_refuses_edited_sources_score_and_ports(change, error):
    graph = config.build_flow(original_flow())
    incoming = next(edge for edge in graph["edges"] if edge.get("to") == "sav.prepare")
    outgoing = next(edge for edge in graph["edges"] if edge.get("to") == "sav.score")
    if change == "source":
        incoming["from"] = "source.queue"
    elif change == "extra_source":
        graph["edges"].append({"from": "source.request", "to": "sav.prepare", "kind": "data"})
    elif change == "score_skill":
        score = next(node for node in graph["nodes"] if node["id"] == "sav.score")
        score["config"]["skill_slug"] = "ml_forecast_v1"
    elif change == "score_source":
        outgoing["from"] = "sav.features"
    elif change == "input_port":
        incoming["to_port"] = "other"
    elif change == "output_port":
        outgoing["from_port"] = "dataset_id"
    before = copy.deepcopy(graph)
    with pytest.raises(ValueError, match=error):
        config.build_flow(graph)
    assert graph == before


@pytest.mark.parametrize("empty", [False, True])
def test_four_visible_steps_preserve_23_rows_exact_types_and_null_semantics(empty):
    # Deliberately unordered synthetic demo cases, with all three reasons, exact
    # numeric boundaries, refund flags and unknown evidence. No target enters ML.
    rows = [
        {
            "claim_id": f"RC-{5001 + index:04d}",
            "claim_reason": ["delivery_disputed", "parcel_lost", "refund_requested"][index % 3],
            "paid_amount": [0.0, 49.9, 420.0, 1234567.89][index % 4],
            "shipment_status": ["delivered", "lost", "in_transit"][index % 3],
            "already_refunded": None if index == 9 else index % 2,
            "case_documents": None if index == 8 else index % 4,
            "item_quantity": index % 3 + 1,
            "unused_context": "must not leak into the scoring dataset",
            "resolution_over_72h": index % 2,
        }
        for index in reversed(range(23))
    ]
    table = pa.Table.from_pylist(rows)
    if empty:
        table = table.slice(0, 0)
    result, expected, compiled = compiled_result(table)
    assert config.LEGACY_SQL == composition.PREPARE_SQL
    assert result.schema == expected.schema
    assert result.to_pylist() == expected.to_pylist()
    assert result.num_rows == (0 if empty else 23)
    assert result.column_names == [
        "claim_id",
        *triage.FEATURES,
        "evidence_gap",
        "duplicate_refund_check",
    ]
    assert len(compiled.step_schemas) == 4
    if not empty:
        assert result["evidence_gap"].null_count == 1
        assert result["duplicate_refund_check"].null_count == 1
        assert all(result[name].equals(expected[name]) for name in triage.FEATURES)


@pytest.mark.asyncio
async def test_work_queue_runs_real_visual_preparation_and_model_for_23_cases(
    db_session,
    environment,  # noqa: F811 - request the shared pytest fixture
    monkeypatch,
):
    ws, actor, main, _, model, plan, _reader = environment
    monkeypatch.setattr(settings, "dataops_enabled", True)
    definition = next(item for item in SEED_SKILLS if item["slug"] == "data_prep_v1")
    if db_session.query(Skill).filter_by(slug="data_prep_v1").first() is None:
        db_session.add(Skill(**copy.deepcopy(definition), is_seeded="Y"))
        db_session.commit()
    reviewed = composition_upgrade.upgrade(db_session, ws, actor, plan=plan)
    legacy = TabularDataset(
        id=str(uuid4()), workspace_id=ws.id, name=config.LEGACY_OUTPUT_NAME,
        slug=slugify(config.LEGACY_OUTPUT_NAME), version=1, status="ready",
        source="transform", produced_by="sql_transform_v1", system_id=main.id,
        node_id="sav.prepare", row_count=23,
    )
    db_session.add(legacy)
    db_session.commit()
    plan["configuration"] = {"flow_definition": config.build_flow(reviewed["flow_definition"])}
    activate(db_session, environment)
    run = create_run(db_session, environment, composition.QUEUE_INGRESS)
    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed", summary
    db_session.expire_all()
    invocations = db_session.query(SkillInvocation).filter_by(run_id=run.id).all()
    assert {invocation.skill_slug for invocation in invocations} == {
        composition.DATASET_SKILL,
        "data_prep_v1",
        "ml_batch_score_v1",
    }
    assert all(invocation.status == "completed" for invocation in invocations)
    advice = triage.read_triage(db_session, ws)
    assert advice["status"] == "ready", advice
    assert advice["scoring"]["system_id"] == main.id
    assert advice["prepared_dataset"]["rows"] == 23
    prepared = db_session.get(TabularDataset, advice["prepared_dataset"]["id"])
    scored = db_session.get(TabularDataset, advice["scored_dataset"]["id"])
    assert prepared.node_id == "sav.prepare" and prepared.produced_by == "data_prep_v1"
    assert prepared.slug == slugify(config.OUTPUT_NAME) != legacy.slug
    assert db_session.get(TabularDataset, legacy.id).produced_by == "sql_transform_v1"
    assert db_session.get(TabularDataset, legacy.id).version == 1
    assert prepared.source == "transform" and prepared.run_id == run.id
    assert scored.parent_ids == [prepared.id]
    assert scored.lineage_json["model"]["model_id"] == model.id
    assert scored.lineage_json["model"]["version"] == model.version
    source = db_session.get(TabularDataset, prepared.parent_ids[0])
    actual = read_rows(prepared)
    _, expected, _ = compiled_result(pa.Table.from_pylist(read_rows(source)))
    assert actual == expected.to_pylist()
    assert next(row for row in actual if row["claim_id"] == "RC-1042")["evidence_gap"] is True
    assert (
        next(row for row in actual if row["claim_id"] == "RC-1044")["duplicate_refund_check"]
        is True
    )
