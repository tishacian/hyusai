"""Work, Flow and their canonical runtime readers recheck Judge source grants."""

import json
from copy import deepcopy
from uuid import uuid4

import pytest

from app.api.v1.endpoints import flow_runner, runs
from app.models.run import SkillInvocation
from app.services import governed_assets as assets
from app.services import object_perspective
from app.services.evaluation import read_model
from app.tests.services.test_evaluation_read_model import scope as scope
from app.tests.services.test_evaluation_read_model import typed_row


def retained_control(db, context):
    run, workspace, user, evidence = context
    row, producer = typed_row(db, context, status="completed", quality="passed")
    source = SkillInvocation(
        id=str(uuid4()),
        run_id=run.id,
        skill_slug="source_v1",
        status="completed",
        output_ref={"proof": evidence["text"]},
    )
    db.add(source)
    db.flush()
    asset = assets.register_asset(
        db,
        workspace.id,
        "reference",
        "runtime-proof",
        {
            "type": "run_evidence_snapshot",
            "evidence": [evidence],
            "native_refs": [],
            "provenance": [
                {
                    "evidence_id": evidence["id"],
                    "invocation_id": source.id,
                    "node_id": "source",
                    "paths": ["/proof"],
                }
            ],
        },
        run_id=run.id,
    )
    metadata = deepcopy(row.metadata_)
    metadata["typed_evaluation"]["evidence"][0]["asset_ref"] = assets.asset_ref(asset)
    row.metadata_ = metadata
    producer.output_ref = deepcopy(metadata["typed_evaluation"])
    producer.input_ref = {"copied_input": evidence["text"]}
    producer.metrics = {"derived_explanation": evidence["text"]}
    producer.trace = {"node_id": "judge", "derived_explanation": evidence["text"]}
    run.output_ref = {
        "typed_evaluation": deepcopy(producer.output_ref),
        "downstream_summary": evidence["text"],
    }
    run.checkpoints = [
        {
            "kind": "skill_end",
            "t": "2026-10-22T00:00:00Z",
            "node_id": "judge",
            "state": {"copied": evidence["text"]},
        }
    ]
    run.status = "completed"
    db.commit()
    return row, producer, source


@pytest.mark.asyncio
async def test_work_flow_and_direct_invocation_mask_revoked_judge_and_derived_text(
    db_session, scope, monkeypatch
):
    run, workspace, user, evidence = scope
    row, producer, source = retained_control(db_session, scope)
    monkeypatch.setattr(runs, "projection_feature_enabled", lambda *args: True)
    readable = await runs.get_run(run.id, workspace=workspace, user=user, db=db_session)
    assert readable["output_ref"]["typed_evaluation"]["evaluation_id"] == row.id
    assert evidence["text"] in json.dumps(readable)
    # Invocation source access is independently revoked; the Run and Judge
    # remain readable, so hiding only the source node is insufficient.
    monkeypatch.setattr(
        read_model, "readable_skill_invocations_for_runs", lambda *args, **kwargs: [producer]
    )
    restricted = await runs.get_run(run.id, workspace=workspace, user=user, db=db_session)
    assert restricted["payload_unavailable_reason"] == "evidence_unavailable"
    assert restricted["output_ref"] == {} and restricted["input_ref"] == {}
    assert restricted["checkpoints"][0]["node_id"] == "judge"
    assert evidence["text"] not in json.dumps(restricted)
    direct = await runs.get_skill_invocation(
        run.id, producer.id, workspace=workspace, user=user, db=db_session
    )
    assert direct["output_ref"] == {} and direct["metrics"] == {}
    assert direct["trace"] == {"node_id": "judge"}
    assert direct["payload_unavailable_reason"] == "evidence_unavailable"
    assert evidence["text"] not in json.dumps(direct)
    runner = flow_runner._run_row(
        run, payload_visible=flow_runner._judge_payload_visible(db_session, run, workspace, user)
    )
    assert runner["output_ref"] == {} and evidence["text"] not in json.dumps(runner)
    # Reading never changes the retained evidence or the runtime ledger.
    assert producer.output_ref["evaluation_id"] == row.id
    assert run.output_ref["downstream_summary"] == evidence["text"]


@pytest.mark.asyncio
async def test_runtime_perspectives_and_checkpoint_replay_share_evidence_guard(
    db_session, scope, monkeypatch
):
    run, workspace, user, evidence = scope
    _, producer, _ = retained_control(db_session, scope)
    monkeypatch.setattr(
        read_model, "readable_skill_invocations_for_runs", lambda *args, **kwargs: [producer]
    )
    for lens in ("build", "operate", "steer", "govern"):
        projected = object_perspective.build_run_perspective(
            db_session, workspace=workspace, user=user, run=run, lens=lens
        )
        assert evidence["text"] not in json.dumps(projected)
        projected = object_perspective.build_skill_invocation_perspective(
            db_session, workspace=workspace, user=user, run=run, invocation=producer, lens=lens
        )
        assert evidence["text"] not in json.dumps(projected)
    checkpoint = runs._reader_checkpoint(db_session, run, run.checkpoints[0], workspace.id, user.id)
    assert checkpoint["payload_unavailable_reason"] == "evidence_unavailable"
    assert "state" not in checkpoint and evidence["text"] not in json.dumps(checkpoint)

    class Request:
        headers = {}

        async def is_disconnected(self):
            return False

    frames = [
        frame async for frame in runs._run_event_stream(run.id, Request(), workspace.id, user.id)
    ]
    assert any("event: skill_end" in frame and "evidence_unavailable" in frame for frame in frames)
    assert evidence["text"] not in "".join(frames)


def test_unpersisted_typed_runtime_result_cannot_bypass_the_guard(db_session, scope):
    run, workspace, user, _ = scope
    producer = SkillInvocation(
        run_id=run.id,
        skill_slug="evaluate_v2",
        status="completed",
        output_ref={
            "schema_version": 2,
            "evaluation_id": str(uuid4()),
            "answers": {"copied": "unretained"},
        },
    )
    db_session.add(producer)
    db_session.commit()
    assert not read_model.runtime_judgment_payload_visible(
        db_session, run, workspace=workspace, user=user
    )


def test_batch_runtime_uses_its_immutable_asset_instead_of_a_single_score_id(
    db_session, scope, monkeypatch
):
    run, workspace, user, _ = scope
    envelope = {
        "schema_version": 2,
        "evaluation_id": "a" * 64,
        "batch_mode": "per_unit",
        "status": "completed",
        "quality_status": "passed",
        "answers": {},
    }
    asset = assets.register_asset(
        db_session,
        workspace.id,
        "reference",
        "batch-result",
        {
            "output": {"typed_evaluation": envelope},
            "native_refs": [],
        },
        run_id=run.id,
    )
    producer = SkillInvocation(
        run_id=run.id,
        skill_slug="evaluate_v2",
        status="completed",
        output_ref={**envelope, "asset_ref": assets.asset_ref(asset)},
    )
    db_session.add(producer)
    db_session.commit()
    assert read_model.runtime_judgment_payload_visible(
        db_session, run, workspace=workspace, user=user
    )
    monkeypatch.setattr(
        read_model, "historical_evidence_authorizer", lambda *args: lambda *args: False
    )
    assert not read_model.runtime_judgment_payload_visible(
        db_session, run, workspace=workspace, user=user
    )
