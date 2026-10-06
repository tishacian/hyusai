"""One native Luma graph, real DataOps/ML artifacts and two released Work actions."""

import copy
import json
import subprocess
import sys
from datetime import datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import polars as pl
import pytest

from app.core.config import settings
from app.models.claim_trial import ClaimTrial
from app.models.decision import Decision
from app.models.experience import ExperienceRelease
from app.models.run import SkillInvocation
from app.models.system import System
from app.models.tabular import MLModel, TabularDataset
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services import ecommerce_claims, tabular_predict
from app.services import ecommerce_composition as composition
from app.services import ecommerce_composition_upgrade as activation
from app.services import ecommerce_triage as triage
from app.services.chains.dag_validator import validate_flow
from app.services.ecommerce_install import install
from app.services.experience import bindings
from app.services.flow_data_sources import bound_data_sources
from app.services.run_engine import dag
from app.services.systems import flow_publication
from app.services.tabular_datasets import read_rows, register_frame
from app.services.tabular_ml import harness_path, upload_model_dir
from app.tests.services.test_ecommerce_triage import FIXTURES, facts, module


@pytest.fixture(scope="module")
def luma_artifact(tmp_path_factory):
    directory = tmp_path_factory.mktemp("luma-fit")
    originals = {
        row["claim_id"]: row
        for row in module("generate_history").history()
        if "INVALID" not in row["claim_id"]
    }
    rows = [
        {
            **triage.feature_row(row),
            triage.TARGET: int(
                datetime.fromisoformat(row["resolved_at"])
                - datetime.fromisoformat(row["opened_at"])
                > timedelta(hours=72)
            ),
        }
        for row in list(originals.values())[:240]
    ]
    # Train a real small artifact with the serving contract's six columns.
    pl.DataFrame(rows).write_parquet(directory / "data.parquet")
    manifest = {
        "data_path": str(directory / "data.parquet"),
        "model_dir": str(directory / "model"),
        "task": "classification",
        "target": triage.TARGET,
        "features": triage.FEATURES,
        "estimator": "sklearn.linear_model.LogisticRegression",
        "params": {"max_iter": 200},
        "scale": True,
        "test_size": 0.25,
        "cv": 0,
        "random_state": 42,
        "min_rows": 40,
        "max_classes": 24,
        "curve_points": 20,
        "importance_rows": 50,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    result = subprocess.run(  # noqa: S603 - production harness with test-owned paths
        [
            sys.executable,
            str(harness_path()),
            str(directory / "manifest.json"),
            str(directory / "result.json"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return directory / "model", json.loads((directory / "result.json").read_text())


@pytest.fixture()
def environment(db_session, tmp_path, monkeypatch, luma_artifact):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    tabular_predict.reset_cache()
    workspace = Workspace(id="composed-ws", slug="composed-ws", name="Showcase", settings={})
    actor = User(id="composed-owner", username="composed-owner", email="owner@example.invalid")
    db_session.add_all([workspace, actor])
    db_session.flush()
    db_session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=actor.id,
            role="owner",
            role_template="workspace_owner",
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        triage.pg,
        "snapshot",
        lambda *a: {"data": {"documents": []}, "provenance": {"snapshot_sha256": "test-snapshot"}},
    )
    monkeypatch.setattr(ecommerce_claims, "_sources", lambda *a: [])
    installed = install(
        db_session,
        workspace,
        actor,
        policy_sha256="a" * 64,
        source_collections=["luma-rules"],
        benchmark=json.loads((FIXTURES.parent / "benchmark/protocol.json").read_text()),
        activate=True,
    )
    main = db_session.get(System, installed["system_id"])
    legacy = []
    for key, role in [("training", "luma-sla-training-v1"), ("scoring", triage.SCORE_ROLE)]:
        system = System(
            id="composed-" + key,
            workspace_id=workspace.id,
            name=key,
            status="active",
            settings={"demo_role": role},
            skill_ids=[],
            flow_definition={
                "schema_version": 2,
                "nodes": [{"id": "start", "kind": "source"}, {"id": "end", "kind": "sink"}],
                "edges": [{"from": "start", "to": "end"}],
            },
        )
        db_session.add(system)
        db_session.flush()
        flow_publication.initialize_new_system_publication_if_enabled(
            db_session, system=system, workspace=workspace, actor=actor.email
        )
        legacy.append(system)
    training = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Fitted synthetic history",
        frame=pl.DataFrame([facts()]),
    )
    directory, summary = luma_artifact
    model = MLModel(
        id="composed-model",
        workspace_id=workspace.id,
        name="Luma SLA",
        slug="luma-sla",
        version=1,
        task="classification",
        target=triage.TARGET,
        algo="linear",
        features=triage.FEATURES,
        classes_json=summary["classes"],
        status="ready",
        dataset_id=training.id,
        system_id=legacy[0].id,
        signature_json=summary["signature"],
        input_example_json=summary["input_example"],
        metrics_json=summary["metrics"],
    )
    model.model_uri, model.artifact_bytes = upload_model_dir(
        directory, workspace_id=workspace.id, model_id=model.id
    )
    db_session.add(model)
    db_session.commit()
    state = flow_publication.flow_state(db_session, system=main, workspace=workspace)
    plan = {
        "system_id": main.id,
        "expected_flow_sha256": state["published"]["flow_sha256"],
        "expected_release_id": installed["release_id"],
        "model_id": model.id,
        "model_version": 1,
        "training_system_id": legacy[0].id,
        "scoring_system_id": legacy[1].id,
        "retire": [],
    }
    for system in legacy:
        state = flow_publication.flow_state(db_session, system=system, workspace=workspace)
        plan["retire"].append(
            {
                "system_id": system.id,
                "expected_flow_sha256": state["published"]["flow_sha256"],
                "expected_draft_sha256": state["draft"]["flow_sha256"],
            }
        )
    reader = Mock(
        side_effect=lambda ws, ids: {
            "data": {
                "features": [
                    facts(
                        claim_id=id,
                        already_refunded=int(id == "RC-1044"),
                        case_documents=0 if id == "RC-1042" else 2,
                    )
                    for id in ids
                ]
            },
            "provenance": {
                "captured_at": datetime.utcnow().isoformat(),
                "snapshot_sha256": "actual-test-input",
                "resources_read": triage.pg.CLAIM_RESOURCES[:-1],
            },
        }
    )
    monkeypatch.setattr(triage.pg, "features", reader)
    yield workspace, actor, main, legacy, model, plan, reader
    tabular_predict.reset_cache()


def activate(db, environment):
    ws, actor, *_, plan, _reader = environment
    reviewed = activation.upgrade(db, ws, actor, plan=plan)
    result = activation.upgrade(
        db,
        ws,
        actor,
        plan=plan,
        apply=True,
        expected_composition_sha256=reviewed["composition_sha256"],
    )
    db.commit()
    return result


def create_run(db, environment, ingress):
    ws, actor, main, *_ = environment
    release = (
        db.query(ExperienceRelease)
        .filter(ExperienceRelease.workspace_id == ws.id)
        .order_by(ExperienceRelease.release_number.desc())
        .first()
    )
    key = (
        "showcase.claims.investigate"
        if ingress == composition.CASE_INGRESS
        else activation.QUEUE_BINDING
    )
    snapshot = next(b for b in release.bindings_snapshot if b["binding_key"] == key)
    nonce = str(uuid4())
    run = bindings.invoke_binding_snapshot(
        db,
        workspace=ws,
        snapshot=snapshot,
        payload={"claim_id": "RC-1042"} if ingress == composition.CASE_INGRESS else {},
        confirmed=True,
        initiated_by_user_id=actor.id,
        actor=actor.email,
        provenance={
            "experience_id": release.experience_id,
            "release_id": release.id,
            "page_id": "dossier",
            "component_id": "investigation"
            if ingress == composition.CASE_INGRESS
            else "queue_refresh",
        },
        trigger_dedup_key="work:" + nonce,
        experience_idempotency_key=nonce,
    )
    assert (
        run.system_id == main.id and run.published_flow_version_id == main.published_flow_version_id
    )
    db.commit()
    return run


def test_activation_keeps_one_operational_system_and_freezes_both_work_actions(
    db_session, environment
):
    ws, actor, main, legacy, model, plan, _ = environment
    previous = main.published_flow_version_id
    reviewed = activation.upgrade(db_session, ws, actor, plan=plan)
    assert reviewed["applied"] is False and main.published_flow_version_id == previous
    assert all(system.status == "active" for system in legacy)
    assert not [
        issue.to_dict()
        for issue in validate_flow(reviewed["flow_definition"])
        if issue.level == "error"
    ]
    for id in ["decision.ready", "hitl.review", "task.simulate"]:
        assert next(
            n["config"] for n in reviewed["flow_definition"]["nodes"] if n["id"] == id
        ) == next(n["config"] for n in main.flow_definition["nodes"] if n["id"] == id)
    with pytest.raises(ValueError, match="TARGET_NOT_REVIEWED"):
        activation.upgrade(
            db_session, ws, actor, plan=plan, apply=True, expected_composition_sha256="wrong"
        )
    assert main.published_flow_version_id == previous
    result = activate(db_session, environment)
    db_session.expire_all()
    assert result["applied"] and main.published_flow_version_id != previous
    assert main.status == "active" and all(system.status == "retired" for system in legacy)
    assert all(system.settings["composition_parent_system_id"] == main.id for system in legacy)
    assert db_session.get(MLModel, model.id).status == "ready"
    release = db_session.get(ExperienceRelease, result["release_id"])
    assert len(release.bindings_snapshot) == 2
    for key, ingress in [
        ("showcase.claims.investigate", composition.CASE_INGRESS),
        (activation.QUEUE_BINDING, composition.QUEUE_INGRESS),
    ]:
        bound = bindings.get_binding(db_session, workspace_id=ws.id, binding_key=key)
        assert (
            bound.system_id == main.id
            and bound.published_flow_version_id == main.published_flow_version_id
        )
        assert bound.ingress_id == ingress
        assert (
            next(b for b in release.bindings_snapshot if b["binding_key"] == key)[
                "published_flow_version_id"
            ]
            == main.published_flow_version_id
        )
    assert triage.read_triage(db_session, ws)["status"] == "not_scored"
    assert release.pages["i18n"]["fr"]["claims_queue_refresh"] == "Recalculer la file"


@pytest.mark.asyncio
async def test_native_queue_and_case_share_real_preparation_and_model_without_reviving_dead_branches(
    db_session, environment, monkeypatch
):
    ws, _, main, _, model, _, reader = environment
    activate(db_session, environment)
    inquiries = []

    async def inquiry(db, run, node, state, *, control, upstream=None):
        inquiries.append(upstream)
        # Stub only the external document/LLM stage, after real preparation and scoring.
        assert bound_data_sources(run.flow_snapshot, node.id)
        assert upstream["data_quality"]["evidence_gap"] is True
        assert upstream["sla_model"] == {"model_id": model.id, "version": 1}
        assert upstream["sav_facts"]["paid_amount"] == 420.0
        assert 0 <= upstream["sla_prediction"][0]["score"] <= 1
        return {"output": {"claim_id": "RC-1042", "exit": "complete"}}

    monkeypatch.setattr(dag, "_run_agent_loop", inquiry)
    queue = create_run(db_session, environment, composition.QUEUE_INGRESS)
    summary = await dag.execute_run_dag(queue.id)
    assert summary["status"] == "completed", summary
    db_session.expire_all()
    assert inquiries == [] and db_session.query(Decision).count() == 0
    slugs = {
        i.skill_slug
        for i in db_session.query(SkillInvocation).filter(SkillInvocation.run_id == queue.id)
    }
    assert slugs == {composition.DATASET_SKILL, "sql_transform_v1", "ml_batch_score_v1"}
    invocations = db_session.query(SkillInvocation).filter(SkillInvocation.run_id == queue.id).all()
    assert all(i.status == "completed" for i in invocations), [
        (i.skill_slug, i.input_ref, i.output_ref) for i in invocations
    ]
    advice = triage.read_triage(db_session, ws)
    assert advice["status"] == "ready" and advice["run_id"] == queue.id
    assert advice["scoring"]["system_id"] == main.id and advice["prepared_dataset"]["rows"] == 23
    queue_prepared = db_session.get(TabularDataset, advice["prepared_dataset"]["id"])
    prepared_rows = read_rows(queue_prepared)
    assert prepared_rows[0]["evidence_gap"] is True
    assert (
        next(row for row in prepared_rows if row["claim_id"] == "RC-1044")["duplicate_refund_check"]
        is True
    )
    assert triage.TARGET not in prepared_rows[0]
    case = create_run(db_session, environment, composition.CASE_INGRESS)
    summary = await dag.execute_run_dag(case.id)
    assert summary["status"] == "hitl_pending", summary
    db_session.expire_all()
    assert len(inquiries) == 1 and db_session.query(Decision).count() == 1
    bridge = (
        db_session.query(SkillInvocation)
        .filter(
            SkillInvocation.run_id == case.id,
            SkillInvocation.skill_slug == composition.CONTEXT_SKILL,
        )
        .one()
    )
    assert bridge.status == "completed", bridge.output_ref
    assert (
        bridge.output_ref["prepared_dataset"]["rows"]
        == bridge.output_ref["scored_dataset"]["rows"]
        == 1
    )
    assert (
        not db_session.query(SkillInvocation)
        .filter(SkillInvocation.skill_slug == "ecommerce_resolution_simulate_v1")
        .first()
    )
    assert reader.call_args.args[1] == ["RC-1042"]
    # Even a later completed inquiry must never replace the whole-queue snapshot.
    case.status = "completed"
    db_session.commit()
    assert triage.read_triage(db_session, ws)["run_id"] == queue.id
    scored = db_session.get(TabularDataset, bridge.output_ref["scored_dataset"]["id"])
    context = {"db": db_session, "workspace_id": ws.id, "run_id": case.id}
    with pytest.raises(ValueError, match="SCORE_REQUIRED"):
        composition._case_context({"dataset_id": advice["scored_dataset"]["id"]}, context)
    scored.lineage_json = {"model": {"model_id": model.id, "version": 2}}
    db_session.commit()
    with pytest.raises(ValueError, match="MODEL_MISMATCH"):
        composition._case_context({"dataset_id": scored.id}, context)
    queued_score = db_session.get(TabularDataset, advice["scored_dataset"]["id"])
    queued_score.ingested_at = datetime.utcnow() - timedelta(hours=2)
    db_session.commit()
    expired = triage.read_triage(db_session, ws)
    assert expired["status"] == "stale" and expired["rows"] == []


def test_dataset_uses_frozen_ingress_scope_and_refuses_missing_bindings_and_manual_aid(
    db_session, environment
):
    ws, actor, _, _, _, _, reader = environment
    activate(db_session, environment)
    case = create_run(db_session, environment, composition.CASE_INGRESS)
    ctx = {"db": db_session, "workspace_id": ws.id, "run_id": case.id}
    with pytest.raises(ValueError, match="BINDING_REQUIRED"):
        composition._dataset(ctx)
    assert reader.call_count == 0
    with pytest.raises(ValueError, match="SYSTEM_REQUIRED"):
        composition._dataset({**ctx, "workspace_id": "another-workspace"})
    case.input_ref = {**case.input_ref, "claim_id": "RC-9999"}
    db_session.commit()
    with pytest.raises(ValueError, match="OUTSIDE_DEMO_SCOPE"):
        composition._dataset(ctx)
    case.input_ref = {**case.input_ref, "claim_id": "RC-1042"}
    db_session.add(
        ClaimTrial(
            workspace_id=ws.id,
            operator_id=actor.id,
            protocol_sha256="a" * 64,
            pair_id="P01",
            condition="manual",
            claim_id="RC-5001",
            state="active",
            evidence={},
            events=[],
        )
    )
    db_session.commit()
    for run in [case, create_run(db_session, environment, composition.QUEUE_INGRESS)]:
        with pytest.raises(ValueError, match="MANUAL_TRIAL_ACTIVE"):
            composition._dataset(
                {
                    **ctx,
                    "run_id": run.id,
                    "_flow_data_sources": bound_data_sources(
                        run.flow_snapshot, composition.FEATURE_NODE
                    ),
                }
            )
    assert reader.call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["postgresql", "model"])
async def test_data_or_model_failure_stops_before_the_agent(
    db_session, environment, monkeypatch, failure
):
    _, _, _, _, model, _, reader = environment
    activate(db_session, environment)
    run = create_run(db_session, environment, composition.CASE_INGRESS)
    if failure == "postgresql":
        reader.side_effect = ValueError("POSTGRESQL_UNAVAILABLE")
    else:
        model.status = "failed"
        db_session.commit()
    inquiry = Mock(side_effect=AssertionError("Unverified data cannot reach the inquiry"))
    monkeypatch.setattr(dag, "_run_agent_loop", inquiry)
    summary = await dag.execute_run_dag(run.id)
    assert summary["status"] == "failed", summary
    assert inquiry.call_count == 0
    assert db_session.query(Decision).count() == 0


@pytest.mark.parametrize("change", ["draft", "retirement", "binding"])
def test_consolidation_refuses_unreviewed_legacy_changes(db_session, environment, change):
    ws, actor, main, legacy, _, original_plan, _ = environment
    plan = copy.deepcopy(original_plan)
    if change == "draft":
        plan["retire"][0]["expected_draft_sha256"] = "wrong"
    elif change == "retirement":
        plan["retire"][0]["system_id"] = main.id
    else:
        bindings.create_binding(
            db_session,
            workspace=ws,
            actor=actor.email,
            binding_key="qa.legacy",
            system_id=legacy[0].id,
            published_flow_version_id=legacy[0].published_flow_version_id,
            ingress_id="start",
            confirmation_policy="confirm",
            on_unavailable="unavailable",
        )
    with pytest.raises(
        ValueError, match="LEGACY_FLOW_CHANGED|RETIREMENT_SCOPE_INVALID|LEGACY_SYSTEM_BOUND"
    ):
        activation.upgrade(db_session, ws, actor, plan=plan)
    assert all(system.status == "active" for system in legacy)
