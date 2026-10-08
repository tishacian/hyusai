"""Actual labeling Skill → durable human gate → immutable dataset delivery."""
from copy import deepcopy
from datetime import datetime
from uuid import uuid4

import pytest

from app.models.decision import Decision
from app.models.skill import Skill
from app.models.tabular import TabularDataset
from app.services import llm_label_review as review
from app.services.run_engine.dag import execute_run_dag, resume_run_dag
from app.services.skills_registry.seed import SEED_SKILLS
from app.services.tabular_datasets import read_frame, register_frame
from app.tests.services.test_llm_dataset_labeling import config, provider  # noqa: F401
from app.tests.services.test_llm_label_review import review_case, object_store_root  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["confirmed", "rejected", "automatic"])
async def test_real_labeling_flow_only_delivers_human_reviewed_labels(
    db_session, review_case, config, provider, monkeypatch, verdict
):
    case = review_case
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-label-review-key")
    case.workspace.settings = {"llm_portal": {"routing": {
        "default_provider": "openai", "default_model": "gpt-4o-mini", "fallback_chain": ["openai"]}}}
    raw = register_frame(db_session, workspace_id=case.workspace.id, name="Raw tickets",
                         frame=read_frame(case.source).drop("topic"))
    skill = Skill(id=str(uuid4()), is_seeded="Y", **deepcopy(next(row for row in SEED_SKILLS if row["slug"] == review.LABEL_PRODUCER)))
    db_session.add(skill)
    flow = {"schema_version": 3, "io_mode": "overlay", "nodes": [
        {"id": "source", "kind": "source"},
        {"id": "label", "kind": "task", "config": {"skill_slug": skill.slug, "params": {**config, "batch_size": 10}}},
        {"id": "review", "kind": "hitl", "config": {"prompt_kind": review.PROMPT_KIND, "expiry_action": "approve"}},
        {"id": "sink", "kind": "sink"},
    ], "edges": [{"from": "source", "to": "label"}, {"from": "label", "to": "review"}, {"from": "review", "to": "sink"}]}
    case.system.flow_definition = flow
    case.system.skill_ids = [skill.id]
    case.run.status = "pending"
    case.run.checkpoints = []
    case.run.input_ref = {"dataset_id": raw.id}
    db_session.commit()

    paused = await execute_run_dag(case.run.id)
    assert paused["status"] == "hitl_pending", paused
    db_session.expire_all()
    decision = db_session.get(Decision, paused["awaiting_decision"])
    binding = decision.rationale["label_review"]
    assert decision.expiry_action == "reject"  # A timer never reviews a dataset.
    assert len(provider.calls) == 5
    labeled = db_session.get(TabularDataset, binding["dataset_id"])
    assert labeled.produced_by == review.LABEL_PRODUCER
    assert read_frame(labeled)["label"][0] == "normal"
    checkpoint = next(cp for cp in reversed(case.run.checkpoints) if cp["kind"] == "hitl_pause")
    assert checkpoint["prompt_kind"] == review.PROMPT_KIND
    assert checkpoint["label_review"]["dataset_id"] == labeled.id

    if verdict == "confirmed":
        output = review.apply_review(db_session, decision, reviewer_id=case.owner.id,
            body=review.LabelReviewInput(dataset_id=labeled.id, sha256=binding["sha256"],
                acknowledged=True, corrections=[{"row_id": 0, "label": "urgent"}]))
        decision.status = "accepted"
        decision.human_confirmed_by = case.owner.id
        decision.human_confirmed_at = datetime.utcnow()
    elif verdict == "rejected":
        decision.status = "rejected"
    else:
        decision.status = "accepted"
        decision.approved_by = "system:ttl"
    db_session.commit()
    result = await resume_run_dag(case.run.id, decision_id=decision.id)
    assert len(provider.calls) == 5
    db_session.expire_all()
    if verdict == "confirmed":
        assert result["status"] == "completed", result
        assert case.run.output_ref["dataset_id"] == output.id
        assert case.run.output_ref["approved"] is True
        assert read_frame(output)["label"][0] == "urgent"
        provenance = review.training_provenance(db_session, output, "label")
        assert provenance["teacher_labels"][0] == "normal"
        assert provenance["rows_reviewed"] == 48
    else:
        assert result["status"] == "failed", result
        assert result["error"] == ("LABEL_REVIEW_REJECTED" if verdict == "rejected" else "LABEL_REVIEW_HUMAN_REQUIRED")
        assert db_session.query(TabularDataset).filter_by(produced_by=review.PRODUCER).count() == 0
