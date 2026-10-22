"""Retained controls remain plural, authorized and distinct from business truth."""

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import evaluation, hypervisor
from app.models.decision import Decision
from app.models.evaluation import EvaluationScore
from app.models.evaluation_feedback import EvaluationFeedback
from app.models.run import SkillInvocation
from app.models.user import User
from app.models.workspace import Workspace
from app.services.evaluation import read_model, typed_judge
from app.tests.services.test_auto_eval import _seed_minimal_run


@pytest.fixture
def scope(db_session):
    run = _seed_minimal_run(db_session)
    user = User(id=str(uuid4()), username=str(uuid4()), role="admin", is_active=True)
    text = "Retained delivery evidence."
    evidence = {
        "id": "delivery",
        "kind": "text",
        "text": text,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }
    run.input_ref = {"evidence": [evidence]}
    db_session.add(user)
    db_session.commit()
    return run, db_session.get(Workspace, run.workspace_id), user, evidence


def typed_row(db, scope, *, status="failed", quality="unassessed", producer=True):
    run, workspace, _, evidence = scope
    identifier = str(uuid4())
    result = {
        "schema_version": 2,
        "evaluation_id": identifier,
        "status": status,
        "quality_status": quality,
        "reason": "JUDGE_RESPONSE_INVALID" if status == "failed" else None,
        "rubric_id": "claims",
        "rubric_version": "1",
        "rubric_sha256": "a" * 64,
        "evidence": [{key: value for key, value in evidence.items() if key != "text"}],
        "coverage": {
            "questions_total": 1,
            "questions_answered": 0 if status == "failed" else 1,
            "evidence_total": 1,
            "evidence_examined": 0 if status == "failed" else 1,
        },
        "questions": [{"key": "valid", "question": "Supported?", "type": "boolean"}],
        "answers": {
            "valid": {
                "value": False,
                "explanation": evidence["text"],
                "evidence": [{"evidence_id": "delivery", "quote": evidence["text"]}],
            }
        },
    }
    invocation = SkillInvocation(
        id=str(uuid4()),
        run_id=run.id,
        skill_slug="evaluate_v2",
        status="completed",
        output_ref=result,
        trace={"node_id": "quality"},
    )
    db.add(invocation)
    db.flush()
    row = EvaluationScore(
        id=identifier,
        workspace_id=workspace.id,
        run_id=run.id,
        composite_score=0,
        hallucination_rate=0,
        drift_rate=0,
        metadata_={
            "source": "evaluate_v2",
            "status": status,
            "typed_evaluation": result,
            **({"producer_invocation_id": invocation.id} if producer else {}),
        },
    )
    db.add(row)
    db.commit()
    return row, invocation


@pytest.mark.asyncio
async def test_plural_summary_does_not_replace_auto_eval_snapshot(db_session, scope):
    run, workspace, user, _ = scope
    run.evaluation_scores = {"status": "queued", "job_id": "legacy-job"}
    first, invocation = typed_row(db_session, scope)
    second, _ = typed_row(db_session, scope, status="completed", quality="failed")
    # A cached invocation refers to the same observation, never a second test.
    db_session.add(
        SkillInvocation(
            run_id=run.id,
            skill_slug="evaluate_v2",
            status="completed",
            output_ref=deepcopy(invocation.output_ref),
        )
    )
    db_session.commit()
    summary = await evaluation.evaluation_run_summary(
        run.id, workspace=workspace, user=user, db=db_session
    )
    assert {r["evaluation_id"] for r in summary["records"]} == {first.id, second.id}
    totals = summary["totals"]
    assert totals["evaluations"] == 2 and totals["distinct_runs"] == 1
    assert totals["technical_failures"] == 1 and totals["failed"] == 1
    assert totals["assessed"] == 1 and totals["unassessed"] == 1
    assert totals["pass_rate"] == 0 and totals["pass_rate_denominator"] == 1
    first_record = next(r for r in summary["records"] if r["id"] == first.id)
    assert len(first_record["invocation_ids"]) == 2
    assert first_record["producer_invocation_id"] == invocation.id
    assert first_record["node_id"] == "quality"
    db_session.refresh(run)
    assert run.evaluation_scores == {"status": "queued", "job_id": "legacy-job"}


@pytest.mark.asyncio
async def test_nine_failed_controls_do_not_mean_nine_bad_answers(db_session, scope):
    _, workspace, user, _ = scope
    for _ in range(9):
        typed_row(db_session, scope)
    summary = await evaluation.evaluation_summary(
        system_id=None, since="90d", limit=100, workspace=workspace, user=user, db=db_session
    )
    assert summary["totals"]["technical_failures"] == 9
    assert summary["totals"]["failed"] == 0
    assert summary["totals"]["assessed"] == 0
    assert summary["totals"]["unassessed"] == 9
    assert summary["totals"]["pass_rate"] is None
    assert summary["scope"]["traffic"] == "business"
    assert all("typed_evaluation" not in row for row in summary["records"])


@pytest.mark.asyncio
async def test_historical_failed_run_readable_and_false_drift_ignored(db_session, scope):
    run, workspace, user, _ = scope
    row, invocation = typed_row(db_session, scope, producer=False)
    run.status = "failed"
    db_session.commit()
    record = await evaluation.evaluation_record(
        row.id, workspace=workspace, user=user, db=db_session
    )
    assert record["producer_invocation_id"] == invocation.id
    assert record["evidence_availability"] == "available"
    assert record["typed_evaluation"]["evaluation_id"] == row.id
    assert all(value is None for value in record["metrics"].values())
    trend = await evaluation.eval_trend(
        since="7d", group_by="day", workspace=workspace, user=user, db=db_session
    )
    assert trend["series"][0]["avg_drift"] is None
    assert trend["series"][0]["observed_drift_count"] == 0
    legacy = await evaluation.evaluation_by_run(
        run.id, workspace=workspace, user=user, db=db_session
    )
    assert legacy["reason"] == "no_persisted_evaluation"  # backwards compatible


@pytest.mark.asyncio
async def test_source_changed_redacts_values_quotes_and_explanations(db_session, scope):
    run, workspace, user, evidence = scope
    row, _ = typed_row(db_session, scope, status="completed", quality="passed")
    run.input_ref = {"evidence": [{**evidence, "text": "different bytes"}]}
    db_session.commit()
    record = await evaluation.evaluation_record(
        row.id, workspace=workspace, user=user, db=db_session
    )
    assert record["evidence_availability"] == "unavailable"
    assert record["typed_evaluation"] is None and record["evidence_sources"] == []
    assert record["quality_status"] == "unassessed"
    assert record["reason"] == "evidence_unavailable"
    assert evidence["text"] not in json.dumps(record)


@pytest.mark.asyncio
async def test_exact_invocation_permission_checked_for_historical_record(
    db_session, scope, monkeypatch
):
    _, workspace, user, _ = scope
    row, _ = typed_row(db_session, scope, producer=False)
    monkeypatch.setattr(
        read_model, "readable_skill_invocations_for_runs", lambda *args, **kwargs: []
    )
    with pytest.raises(HTTPException) as caught:
        await evaluation.evaluation_record(row.id, workspace=workspace, user=user, db=db_session)
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_private_run_is_not_disclosed(db_session, scope):
    run, workspace, _, _ = scope
    row, _ = typed_row(db_session, scope)
    run.trigger = "chat_agentic"
    run.initiated_by_user_id = str(uuid4())
    user = User(id=str(uuid4()), username=str(uuid4()), role="user")
    db_session.add(user)
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        await evaluation.evaluation_record(row.id, workspace=workspace, user=user, db=db_session)
    assert caught.value.status_code == 404


def test_typed_writer_nulls_legacy_metrics_and_binds_exact_producer(db_session, scope):
    run, workspace, _, _ = scope
    invocation = SkillInvocation(
        id=str(uuid4()), run_id=run.id, skill_slug="evaluate_v2", status="running"
    )
    db_session.add(invocation)
    db_session.flush()
    result = {"evaluation_id": str(uuid4()), "status": "failed"}
    typed_judge._persist_evaluation(
        db_session,
        result,
        workspace,
        run,
        ctx={"_skill_invocation_id": invocation.id, "_skill_node_id": "control"},
        job=SimpleNamespace(id="job"),
    )
    db_session.commit()
    row = db_session.get(EvaluationScore, result["evaluation_id"])
    assert row.composite_score is None and row.hallucination_rate is None and row.drift_rate is None
    assert row.metadata_["producer_invocation_id"] == invocation.id
    assert row.metadata_["producer_job_id"] == "job"


def test_operations_monitor_does_not_turn_missing_judge_scores_into_breaches(db_session, scope):
    from app.api.v1.endpoints.observability import _evaluation_summary

    row, _ = typed_row(db_session, scope)
    summary = _evaluation_summary([row])
    assert summary["total"] == 1 and summary["breaches"] == 0
    assert summary["avg_composite"] is None
    assert summary["latest"]["drift_rate"] is None


@pytest.mark.parametrize("binding", ["first", None, "foreign"])
def test_feedback_never_chooses_the_newest_judge(db_session, scope, binding):
    run, workspace, _, _ = scope
    first, _ = typed_row(db_session, scope)
    second, _ = typed_row(db_session, scope)
    first.created_at = datetime.utcnow() - timedelta(minutes=1)
    selected = first.id if binding == "first" else str(uuid4()) if binding else None
    decision = Decision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope="run",
        target_id=run.id,
        kind="review_required",
        title="Review",
        rationale={"evaluation_id": selected},
    )
    db_session.add(decision)
    db_session.commit()
    hypervisor._maybe_record_eval_feedback(
        db_session, decision=decision, body=None, default_label="true_breach", actor="reviewer"
    )
    feedback = db_session.query(EvaluationFeedback).one()
    assert feedback.evaluation_score_id == (first.id if binding == "first" else None)
    assert feedback.evaluation_score_id != second.id


@pytest.mark.asyncio
async def test_asset_provenance_and_revoked_source_are_checked(
    db_session, scope, monkeypatch, tmp_path
):
    from app.core.config import settings
    from app.services import governed_assets as assets

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    run, workspace, user, evidence = scope
    row, producer = typed_row(db_session, scope, status="completed", quality="passed")
    source = SkillInvocation(
        id=str(uuid4()), run_id=run.id, skill_slug="delivery_v1", status="completed"
    )
    db_session.add(source)
    db_session.flush()
    asset = assets.register_asset(
        db_session,
        workspace.id,
        "reference",
        "retained-control",
        {
            "type": "run_evidence_snapshot",
            "evidence": [evidence],
            "native_refs": [],
            "provenance": [
                {
                    "evidence_id": evidence["id"],
                    "invocation_id": source.id,
                    "node_id": "delivery",
                    "paths": ["/proof"],
                }
            ],
        },
        run_id=run.id,
    )
    metadata = deepcopy(row.metadata_)
    metadata["typed_evaluation"]["evidence"][0]["asset_ref"] = assets.asset_ref(asset)
    row.metadata_ = metadata
    db_session.commit()
    record = await evaluation.evaluation_record(
        row.id, workspace=workspace, user=user, db=db_session
    )
    assert record["evidence_availability"] == "available"
    assert record["evidence_sources"][0]["invocation_id"] == source.id
    assert record["evidence_sources"][0]["asset_ref"]["version"] == asset.version
    monkeypatch.setattr(
        read_model, "readable_skill_invocations_for_runs", lambda *args, **kwargs: [producer]
    )
    restricted = await evaluation.evaluation_record(
        row.id, workspace=workspace, user=user, db=db_session
    )
    assert restricted["typed_evaluation"] is None
    assert restricted["evidence_availability"] == "unavailable"
    assert evidence["text"] not in json.dumps(restricted)


@pytest.mark.asyncio
async def test_changed_asset_bytes_are_not_replaced_with_current_data(
    db_session, scope, monkeypatch, tmp_path
):
    from app.core.config import settings
    from app.services import governed_assets as assets

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    run, workspace, user, evidence = scope
    row, _ = typed_row(db_session, scope)
    asset = assets.register_asset(
        db_session, workspace.id, "reference", "control", {"evidence": [evidence]}, run_id=run.id
    )
    metadata = deepcopy(row.metadata_)
    metadata["typed_evaluation"]["evidence"][0]["asset_ref"] = assets.asset_ref(asset)
    row.metadata_ = metadata
    db_session.commit()
    # Simulate a corrupted object, without bypassing the immutable ORM record.
    assets.get_object_store().write_bytes(asset.manifest_key, b"changed bytes")
    record = await evaluation.evaluation_record(
        row.id, workspace=workspace, user=user, db=db_session
    )
    assert record["typed_evaluation"] is None
    assert record["evidence_availability"] == "unavailable"


@pytest.mark.asyncio
async def test_qa_traffic_is_explicit_and_does_not_fill_business_quality(db_session, scope):
    from app.models.evaluation_campaign import EvaluationCampaign, EvaluationSuite

    run, workspace, user, _ = scope
    row, _ = typed_row(db_session, scope)
    suite = EvaluationSuite(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=run.system_id,
        name="QA",
        cases=[],
        created_by_user_id=user.id,
    )
    db_session.add(suite)
    db_session.flush()
    campaign = EvaluationCampaign(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=run.system_id,
        suite_id=suite.id,
        baseline_run_id=run.id,
        request_key="qa",
        request_sha256="a" * 64,
        snapshot={},
        created_by_user_id=user.id,
    )
    db_session.add(campaign)
    db_session.flush()
    run.evaluation_campaign_id = campaign.id
    db_session.commit()

    async def summary(traffic):
        return await evaluation.evaluation_summary(
            traffic=traffic, since="7d", limit=100, workspace=workspace, user=user, db=db_session
        )

    assert (await summary("business"))["totals"]["evaluations"] == 0
    assert (await summary("evaluation"))["totals"]["evaluations"] == 1
    assert (await summary("all"))["totals"]["distinct_runs"] == 1
    assert (
        await evaluation.evaluation_record(row.id, workspace=workspace, user=user, db=db_session)
    )["run_id"] == run.id
    history = await evaluation.evaluation_history(
        agent_id=None, since="7d", limit=20, workspace=workspace, user=user, db=db_session
    )
    assert history["evaluations"] == []
    # Legacy comparisons had a preview surface before campaign IDs existed.
    run.evaluation_campaign_id = None
    run.execution_surface = "golden_preview"
    db_session.commit()
    assert (await summary("business"))["totals"]["evaluations"] == 0
    assert (await summary("evaluation"))["totals"]["evaluations"] == 1


@pytest.mark.asyncio
async def test_pending_control_is_visible_without_inventing_an_evaluation(db_session, scope):
    run, workspace, user, _ = scope
    db_session.add(
        SkillInvocation(
            run_id=run.id, skill_slug="evaluate_v2", status="running", trace={"node_id": "judge"}
        )
    )
    db_session.commit()
    summary = await evaluation.evaluation_run_summary(
        run.id, workspace=workspace, user=user, db=db_session
    )
    assert summary["records"] == []
    assert summary["totals"]["evaluations"] == 0
    assert summary["totals"]["pass_rate"] is None
    assert summary["unrecorded_controls"][0]["reason"] == "evaluation_pending"
    assert summary["unrecorded_controls"][0]["evaluation_id"] is None
