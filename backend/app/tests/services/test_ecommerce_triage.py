"""SLA advice must have real lineage and cannot replace financial evidence."""

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.core.config import settings
from app.models.run import Run
from app.models.system import System
from app.models.tabular import MLModel, TabularDataset
from app.models.workspace import Workspace
from app.services import ecommerce_triage as triage
from app.services.chains.dag_validator import validate_flow
from app.services.ecommerce_triage_flows import fresh_scoring, with_triage
from app.services.flow_data_sources import bound_data_sources
from app.services.tabular_datasets import read_rows, register_frame
from app.services.tabular_transforms import run_sql_transform

FIXTURES = (
    Path(__file__).resolve().parents[4] / "docs/demo-runs/showcase-ecommerce/fixtures/dataops"
)
BASE_FLOW = (
    Path(__file__).resolve().parents[2] / "resources/flows/showcase_ecommerce_claims_v1.json"
)


def module(name):
    spec = importlib.util.spec_from_file_location(name, FIXTURES / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_native_preparation_removes_quality_issues_without_target_leakage(
    db_session, tmp_path, monkeypatch
):
    import polars as pl

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    ws = Workspace(id="triage-history", slug="triage-history", name="Triage")
    db_session.add(ws)
    db_session.commit()
    rows = module("generate_history").history()
    raw = register_frame(
        db_session,
        workspace_id=ws.id,
        name="Synthetic history",
        frame=pl.DataFrame(rows),
        source="upload",
    )
    sources = [{"view": "history", "dataset_id": raw.id}]
    result = run_sql_transform(
        db_session,
        workspace_id=ws.id,
        sql=(FIXTURES / "prepare_history.sql").read_text(),
        declared=sources,
        output_name="Prepared",
    )
    prepared = db_session.get(TabularDataset, result["dataset_id"])
    records = read_rows(prepared)
    assert len(rows) == 1236 and len(records) == 1200
    assert len({r["claim_id"] for r in records}) == 1200
    assert set(records[0]) == {"claim_id", *triage.FEATURES, triage.TARGET}
    assert "resolved_at" not in triage.FEATURES and "claim_id" not in triage.FEATURES
    assert {r[triage.TARGET] for r in records} == {0, 1}
    assert prepared.parent_ids == [raw.id]
    originals = {row["claim_id"]: row for row in rows if "INVALID" not in row["claim_id"]}
    for record in records:
        original = originals[record["claim_id"]]
        hours = (
            datetime.fromisoformat(original["resolved_at"])
            - datetime.fromisoformat(original["opened_at"])
        ).total_seconds() / 3600
        assert record[triage.TARGET] == int(hours > 72)
        assert (
            triage.feature_row(record)["claim_reason"] == original["claim_reason"].strip().lower()
        )


def facts(**patch):
    return {
        "claim_id": "RC-1042",
        "claim_reason": " delivery_disputed ",
        "paid_amount": "420.00",
        "shipment_status": "delivered",
        "already_refunded": 0,
        "case_documents": 2,
        "item_quantity": 1,
        **patch,
    }


@pytest.mark.parametrize(
    "patch",
    [
        {"paid_amount": "NaN"},
        {"paid_amount": "Infinity"},
        {"paid_amount": -1},
        {"shipment_status": None},
        {"item_quantity": 0},
        {"case_documents": 1.5},
        {"already_refunded": 2},
    ],
)
def test_missing_or_invalid_facts_do_not_become_confident_predictions(patch):
    with pytest.raises(ValueError, match="FEATURES_INVALID"):
        triage.feature_row(facts(**patch))


@pytest.mark.asyncio
async def test_claim_run_owns_the_features_and_the_postgresql_dependency(db_session, monkeypatch):
    config = {
        "allowed_claim_ids": ["RC-1042"],
        "policy_sha256": "a" * 64,
        "allowed_collection_slugs": ["rules"],
    }
    ws = Workspace(
        id="triage-run-ws",
        slug="triage-run-ws",
        name="Triage",
        settings={"features": {"ecommerce_claims_v1": True}, "ecommerce_claims": config},
    )
    flow = with_triage(json.loads(BASE_FLOW.read_text()), "pinned-model", 1)
    system = System(
        id="triage-claim-sys", workspace_id=ws.id, name="Claims", blueprint_key=triage.BLUEPRINT
    )
    run = Run(
        id="triage-claim-run",
        workspace_id=ws.id,
        system_id=system.id,
        flow_snapshot=flow,
        input_ref={"claim_id": "RC-1042"},
    )
    db_session.add_all([ws, system, run])
    db_session.commit()
    reader = Mock(
        return_value={"data": {"features": [facts()]}, "provenance": {"captured_at": "now"}}
    )
    monkeypatch.setattr(triage.pg, "features", reader)
    ctx = {
        "db": db_session,
        "workspace_id": ws.id,
        "run_id": run.id,
        "_flow_data_sources": bound_data_sources(flow, "sla_features"),
    }
    result = await triage.invoke({"claim_id": "RC-9999", "rows": [{"paid_amount": 0}]}, ctx)
    assert reader.call_args.args[1] == ["RC-1042"]
    assert result["rows"] == [triage.feature_row(facts())]
    assert set(result["rows"][0]) == set(triage.FEATURES)
    with pytest.raises(ValueError, match="BINDING_REQUIRED"):
        triage._extract({**ctx, "_flow_data_sources": []})
    with pytest.raises(ValueError, match="RUN_REQUIRED"):
        triage._extract({**ctx, "workspace_id": "another-workspace"})
    assert reader.call_count == 1


def test_model_advice_does_not_change_financial_guards_or_document_sources():
    original = json.loads(BASE_FLOW.read_text())
    changed = with_triage(original, "approved-model", 3)
    assert not [issue.to_dict() for issue in validate_flow(changed) if issue.level == "error"]
    by_id = {node["id"]: node for node in changed["nodes"]}
    for node in original["nodes"]:
        if node["id"] in {"hitl.review", "task.simulate", "decision.ready"}:
            assert by_id[node["id"]]["config"] == node["config"]
    assert by_id["sla_risk"]["config"]["params"] == {
        "model_id": "approved-model",
        "pinned_version": 3,
        "explain": False,
    }
    assert by_id["loop.investigate"]["config"]["skill_allowlist"] == next(
        node["config"]["skill_allowlist"]
        for node in original["nodes"]
        if node["id"] == "loop.investigate"
    )
    score = module("pipeline_payloads").snapshot_scoring({}, "approved-model", 3)
    fresh = fresh_scoring(score, "approved-model", 3)
    assert not [issue.to_dict() for issue in validate_flow(fresh) if issue.level == "error"]
    assert bound_data_sources(fresh, "features")[0]["read_mode"] == "live"


@pytest.mark.parametrize("change", ["edge", "resource", "consumer"])
def test_generic_postgresql_requirements_protect_the_scoring_flow_before_execution(change):
    score = module("pipeline_payloads").snapshot_scoring({}, "model", 1)
    fresh = fresh_scoring(score, "model", 1)
    if change == "edge":
        fresh["edges"] = [edge for edge in fresh["edges"] if edge["from"] != "asset.postgresql"]
    elif change == "resource":
        next(node for node in fresh["nodes"] if node["id"] == "asset.postgresql")["config"][
            "resources"
        ].pop()
    else:
        fresh["runtime_contract"]["postgresql_consumers"][0]["node_id"] = "missing-reader"
    issues = validate_flow(fresh)
    assert any(issue.level == "error" and issue.code == "data_source_invalid" for issue in issues)
    assert not any(issue.node_id in {"loop.investigate", "task.simulate"} for issue in issues)


def test_activation_is_reviewed_then_publishes_both_flows_and_a_frozen_work_release(
    db_session, monkeypatch
):
    from app.models.experience import ExperienceRelease
    from app.models.skill import Skill
    from app.models.user import User
    from app.models.workspace import WorkspaceMember
    from app.services import ecommerce_claims, ecommerce_triage_upgrade
    from app.services.ecommerce_install import install
    from app.services.experience import bindings
    from app.services.skills_registry.seed import SEED_SKILLS
    from app.services.systems import flow_publication

    ws = Workspace(id="triage-install-ws", name="Triage", slug="triage-install-ws", settings={})
    user = User(id="triage-owner", username="triage-owner", email="triage@example.invalid")
    db_session.add_all([ws, user])
    db_session.flush()
    db_session.add(
        WorkspaceMember(
            workspace_id=ws.id, user_id=user.id, role="owner", role_template="workspace_owner"
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        triage.pg,
        "snapshot",
        lambda *a: {"data": {"documents": []}, "provenance": {"snapshot_sha256": "snapshot"}},
    )
    monkeypatch.setattr(ecommerce_claims, "_sources", lambda *a: [])
    benchmark = json.loads((FIXTURES.parent / "benchmark/protocol.json").read_text())
    installed = install(
        db_session,
        ws,
        user,
        policy_sha256="a" * 64,
        source_collections=["luma-maison-regles"],
        benchmark=benchmark,
        activate=True,
    )
    original = db_session.get(System, installed["system_id"])
    for definition in SEED_SKILLS:
        if definition["slug"] in {"sql_transform_v1", "ml_batch_score_v1"}:
            db_session.add(Skill(**definition, is_seeded="Y", workspace_id=None))
    db_session.flush()
    ids = [
        s.id
        for s in db_session.query(Skill)
        .filter(Skill.slug.in_(["sql_transform_v1", "ml_batch_score_v1"]))
        .all()
    ]
    scorer = System(
        id="triage-install-scorer",
        workspace_id=ws.id,
        name="Scorer",
        skill_ids=ids,
        settings={"demo_role": triage.SCORE_ROLE},
        status="active",
        flow_definition=module("pipeline_payloads").snapshot_scoring({}, "triage-install-model", 1),
    )
    trainer = System(id="triage-install-trainer", workspace_id=ws.id, name="Trainer")
    training = TabularDataset(
        id="triage-install-data",
        workspace_id=ws.id,
        name="Synthetic training",
        slug="triage-install-data",
        status="ready",
        row_count=1200,
    )
    db_session.add_all([scorer, trainer, training])
    db_session.flush()
    model = MLModel(
        id="triage-install-model",
        workspace_id=ws.id,
        name="Model",
        slug="triage-install-model",
        version=1,
        task="classification",
        target=triage.TARGET,
        algo="linear",
        features=triage.FEATURES,
        classes_json=["0", "1"],
        status="ready",
        dataset_id=training.id,
        system_id=trainer.id,
    )
    db_session.add(model)
    flow_publication.initialize_new_system_publication_if_enabled(
        db_session, system=scorer, workspace=ws, actor=user.email
    )
    db_session.commit()
    main_sha = flow_publication.flow_state(db_session, system=original, workspace=ws)["published"][
        "flow_sha256"
    ]
    score_sha = flow_publication.flow_state(db_session, system=scorer, workspace=ws)["published"][
        "flow_sha256"
    ]
    plan = {
        "system_id": original.id,
        "expected_flow_sha256": main_sha,
        "expected_release_id": installed["release_id"],
        "model_id": model.id,
        "model_version": 1,
        "training_system_id": trainer.id,
        "scoring_system_id": scorer.id,
        "expected_scoring_flow_sha256": score_sha,
    }
    previous_ids = (original.published_flow_version_id, scorer.published_flow_version_id)
    reviewed = ecommerce_triage_upgrade.upgrade(db_session, ws, user, plan=plan)
    assert reviewed["applied"] is False
    assert (original.published_flow_version_id, scorer.published_flow_version_id) == previous_ids
    assert "triage" not in ws.settings["ecommerce_claims"]
    with pytest.raises(ValueError, match="TARGET_NOT_REVIEWED"):
        ecommerce_triage_upgrade.upgrade(
            db_session, ws, user, plan=plan, apply=True, expected_target_sha256="wrong"
        )
    assert (original.published_flow_version_id, scorer.published_flow_version_id) == previous_ids
    result = ecommerce_triage_upgrade.upgrade(
        db_session,
        ws,
        user,
        plan=plan,
        apply=True,
        expected_target_sha256=reviewed["flow_sha256"],
        expected_scoring_target_sha256=reviewed["scoring_flow_sha256"],
    )
    db_session.commit()
    assert result["applied"] is True and result["release_id"] != installed["release_id"]
    assert (
        original.published_flow_version_id != previous_ids[0]
        and scorer.published_flow_version_id != previous_ids[1]
    )
    assert ws.settings["ecommerce_claims"]["triage"]["model_id"] == model.id
    binding = bindings.get_binding(
        db_session, workspace_id=ws.id, binding_key="showcase.claims.investigate"
    )
    assert binding.published_flow_version_id == original.published_flow_version_id
    release = db_session.get(ExperienceRelease, result["release_id"])
    released_binding = next(
        item
        for item in release.bindings_snapshot
        if item["binding_key"] == "showcase.claims.investigate"
    )
    assert released_binding["published_flow_version_id"] == original.published_flow_version_id


@pytest.fixture()
def scored(db_session, tmp_path, monkeypatch):
    import polars as pl

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    ws = Workspace(
        id="triage-score-ws",
        slug="triage-score-ws",
        name="Triage",
        settings={
            "features": {"ecommerce_claims_v1": True},
            "ecommerce_claims": {
                "allowed_claim_ids": ["RC-1042", "RC-1043"],
                "policy_sha256": "a" * 64,
                "allowed_collection_slugs": ["rules"],
                "triage": {
                    "model_id": "triage-model",
                    "model_version": 1,
                    "scoring_system_id": "triage-score-sys",
                    "scoring_version_id": "published",
                    "scoring_flow_sha256": "b" * 64,
                },
            },
        },
    )
    system = System(
        id="triage-score-sys",
        workspace_id=ws.id,
        name="Scoring",
        settings={"demo_role": triage.SCORE_ROLE},
    )
    run = Run(
        id="triage-score-run",
        workspace_id=ws.id,
        system_id=system.id,
        status="completed",
        flow_sha256="b" * 64,
    )
    db_session.add_all([ws, system, run])
    db_session.commit()
    training = register_frame(
        db_session, workspace_id=ws.id, name="Synthetic training", frame=pl.DataFrame([facts()])
    )
    model = MLModel(
        id="triage-model",
        workspace_id=ws.id,
        name="Model",
        slug="triage-model",
        version=1,
        task="classification",
        algo="linear",
        target=triage.TARGET,
        features=triage.FEATURES,
        classes_json=["0", "1"],
        status="ready",
        dataset_id=training.id,
    )
    db_session.add(model)
    db_session.commit()
    dataset = register_frame(
        db_session,
        workspace_id=ws.id,
        name="Scored queue",
        source="score",
        frame=pl.DataFrame({"claim_id": ["RC-1042", "RC-1043"], "score_1": [0.82, 0.16]}),
        run_id=run.id,
        node_id="score",
        lineage={"model": {"model_id": model.id, "version": 1}},
    )
    from app.services.systems import flow_publication

    monkeypatch.setattr(
        flow_publication,
        "flow_state",
        lambda *a, **k: {"published": {"version_id": "published", "flow_sha256": "b" * 64}},
    )
    from app.services import tabular_predict

    monkeypatch.setattr(
        tabular_predict,
        "predict_rows",
        Mock(side_effect=AssertionError("A page read cannot infer")),
    )
    return ws, model, dataset, run


def test_persisted_positive_class_scores_are_read_with_versioned_lineage(db_session, scored):
    ws, model, dataset, run = scored
    result = triage.read_triage(db_session, ws)
    assert result["status"] == "ready" and result["run_id"] == run.id
    assert result["scored_dataset"]["id"] == dataset.id
    assert result["rows"][0] == {"claim_id": "RC-1042", "risk": 0.82, "priority": "high"}
    model.workspace_id = "another-workspace"
    db_session.flush()
    assert triage.read_triage(db_session, ws) == {"status": "unavailable", "rows": []}


@pytest.mark.asyncio
async def test_batch_skill_emits_a_real_dataset_and_satisfies_its_published_output_schema(
    db_session, scored, monkeypatch
):
    from jsonschema import validate

    from app.services.ecommerce_skill_catalog import CLAIM_SKILLS
    from app.services.skills_registry.wrappers import resolve

    ws, _, _, run = scored
    flow = fresh_scoring(module("pipeline_payloads").snapshot_scoring({}, "model", 1), "model", 1)
    run.flow_snapshot = flow
    db_session.commit()
    provenance = {
        "captured_at": datetime.utcnow().isoformat(),
        "snapshot_sha256": "measured",
        "resources_read": triage.pg.CLAIM_RESOURCES,
    }
    monkeypatch.setattr(
        triage.pg,
        "features",
        lambda *a: {
            "data": {"features": [facts(), facts(claim_id="RC-1043", claim_reason="parcel_lost")]},
            "provenance": provenance,
        },
    )
    ctx = {
        "db": db_session,
        "workspace_id": ws.id,
        "run_id": run.id,
        "_flow_data_sources": bound_data_sources(flow, "features"),
    }
    result = await resolve(triage.FEATURE_DATASET_SKILL)({"claim_id": "RC-9999"}, ctx)
    definition = next(
        skill for skill in CLAIM_SKILLS if skill["slug"] == triage.FEATURE_DATASET_SKILL
    )
    validate(result, definition["output_schema"])
    dataset = db_session.get(TabularDataset, result["dataset_id"])
    assert result["rows"] == 2 and dataset.system_id == run.system_id
    assert dataset.source == "postgresql" and dataset.produced_by == triage.FEATURE_DATASET_SKILL
    assert dataset.lineage_json["provenance"]["snapshot_sha256"] == "measured"
    with pytest.raises(ValueError, match="SKILL_SHAPE_MISMATCH"):
        await resolve(triage.FEATURE_SKILL)({}, ctx)


def test_expired_failed_or_wrong_version_predictions_cannot_sort_the_queue(db_session, scored):
    ws, model, dataset, run = scored
    dataset.ingested_at = datetime.utcnow() - timedelta(hours=2)
    db_session.flush()
    stale = triage.read_triage(db_session, ws)
    assert (
        stale["status"] == "stale"
        and stale["rows"] == []
        and stale["scored_dataset"]["id"] == dataset.id
    )
    run.status = "failed"
    db_session.flush()
    assert triage.read_triage(db_session, ws)["status"] == "not_scored"
    run.status = "completed"
    run.flow_sha256 = "c" * 64
    db_session.flush()
    assert triage.read_triage(db_session, ws)["status"] == "not_scored"
    run.flow_sha256 = "b" * 64
    dataset.lineage_json = {"model": {"model_id": model.id, "version": 2}}
    db_session.flush()
    assert triage.read_triage(db_session, ws)["status"] == "unavailable"
