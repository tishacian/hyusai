"""Immutable reviewed datasets and canonical human approval provenance."""
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import polars as pl
import pytest
from pydantic import ValidationError

from app.models.tabular import TabularDataset
from app.models.workspace_job import WorkspaceJob
from app.services import llm_label_review as review
from app.services.tabular_datasets import read_frame, register_frame, serialize_dataset
from app.tests.api.test_runs_hitl_auth import _seed_pending_run
from app.tests.services.test_tabular_datasets import object_store_root  # noqa: F401


@pytest.fixture()
def review_case(db_session, object_store_root):
    workspace, owner, other, membership, system, run, decision = _seed_pending_run(db_session)
    job = WorkspaceJob(id=str(uuid4()), workspace_id=workspace.id, kind="llm_label_dataset", status="completed",
        input_ref={"model": {"provider": "openai", "model": "teacher"}, "spec": {
            "text_columns": ["ticket"], "labels": ["billing", "technical"], "label_column": "topic"}},
        result={"rows_total": 48, "estimated_cost_usd": 0.024, "unknown_attempts": 0})
    db_session.add(job)
    source = register_frame(db_session, workspace_id=workspace.id, name="LLM tickets", source="generated",
        produced_by=review.LABEL_PRODUCER, run_id=run.id,
        frame=pl.DataFrame({"ticket": [f"{'invoice' if i % 2 else 'network'} ticket {i}" for i in range(48)],
                            "private_note": ["retained, not review context"] * 48,
                            "topic": ["billing" if i % 2 else "technical" for i in range(48)]}),
        lineage={"labeling": {"job_id": job.id, "label_column": "topic", "review_status": "unreviewed"}})
    job.result = {**job.result, "output_id": source.id}
    db_session.flush()
    binding = review.make_binding(db_session, workspace_id=workspace.id, dataset_id=source.id)
    decision.rationale = {"node_id": "review", "prompt_kind": review.PROMPT_KIND, "label_review": binding}
    run.checkpoints = [{"kind": "hitl_pause", "node_id": "review", "decision_id": decision.id,
                        "prompt_kind": review.PROMPT_KIND, "label_review": binding}]
    db_session.commit()
    return SimpleNamespace(workspace=workspace, owner=owner, other=other, membership=membership,
                           system=system, run=run, decision=decision, source=source, job=job, binding=binding)


def review_body(case, corrections=None):
    return review.LabelReviewInput(dataset_id=case.source.id, sha256=case.binding["sha256"],
                                  acknowledged=True, corrections=corrections or [])


def confirm(db, case, output):
    case.decision.status = "accepted"
    case.decision.human_confirmed_by = case.owner.id
    case.decision.human_confirmed_at = datetime.utcnow()
    db.commit()
    return output


def test_review_page_keeps_stable_ids_and_only_the_original_text_context(db_session, review_case):
    case = review_case
    page = review.review_page(db_session, case.decision, offset=20, limit=3)
    assert page["total"] == 48 and page["sha256"] == case.binding["sha256"]
    assert [row["row_id"] for row in page["rows"]] == [20, 21, 22]
    assert page["rows"][0] == {"row_id": 20, "values": {"ticket": "network ticket 20"}, "label": "technical"}


def test_review_creates_a_new_immutable_dataset_with_verified_parallel_teacher_labels(db_session, review_case):
    case = review_case
    original = read_frame(case.source)
    output = review.apply_review(db_session, case.decision, reviewer_id=case.owner.id,
                                body=review_body(case, [{"row_id": 0, "label": "billing"}]))
    with pytest.raises(review.TabularError, match="confirmed human"):
        review.reviewed_output(db_session, case.decision)
    confirm(db_session, case, output)
    assert output.id != case.source.id and output.parent_ids == [case.source.id]
    assert output.produced_by == review.PRODUCER and output.source == "generated"
    assert read_frame(case.source).equals(original)
    assert read_frame(output).columns == original.columns
    assert read_frame(output)["topic"][0] == "billing"
    lineage = serialize_dataset(output, include_preview=True)["lineage"]
    assert lineage["labeling"]["review_status"] == "reviewed"
    assert lineage["label_review"]["rows_reviewed"] == 48
    assert lineage["label_review"]["corrected_rows"] == 1
    provenance = review.training_provenance(db_session, output, "topic")
    assert provenance["teacher_labels"] == original["topic"].to_list()
    assert provenance["llm_estimated_cost_usd"] == .024
    assert provenance["reviewed_dataset_id"] == output.id
    assert provenance["decision_id"] == case.decision.id


@pytest.mark.parametrize("corrections", [
    [{"row_id": 0, "label": "unknown"}], [{"row_id": 48, "label": "billing"}],
    [{"row_id": 0, "label": "billing"}, {"row_id": 0, "label": "technical"}],
])
def test_invalid_corrections_publish_nothing(db_session, review_case, corrections):
    with pytest.raises(review.TabularError) as error:
        review.apply_review(db_session, review_case.decision, reviewer_id=review_case.owner.id,
                            body=review_body(review_case, corrections))
    assert error.value.code == "LABEL_REVIEW_CORRECTION_INVALID"
    assert db_session.query(TabularDataset).filter_by(produced_by=review.PRODUCER).count() == 0
    assert review_case.decision.status == "proposed"


@pytest.mark.parametrize("patch", [
    {"acknowledged": False}, {"corrections": [{"row_id": True, "label": "billing"}]},
    {"corrections": [{"row_id": -1, "label": "billing"}]}, {"sha256": "wrong"},
])
def test_review_payload_is_strict(review_case, patch):
    with pytest.raises(ValidationError):
        review.LabelReviewInput.model_validate({**review_body(review_case).model_dump(), **patch})


def test_unreviewed_teacher_target_is_refused_for_training(db_session, review_case):
    with pytest.raises(review.TabularError) as error:
        review.training_provenance(db_session, review_case.source, "topic")
    assert error.value.code == "ML_LABEL_REVIEW_REQUIRED"


def test_changed_source_and_wrong_workspace_are_refused(db_session, review_case):
    case = review_case
    with pytest.raises(review.TabularError):
        review.make_binding(db_session, workspace_id=str(uuid4()), dataset_id=case.source.id)
    register_frame(db_session, workspace_id=case.workspace.id, name=case.source.name, into=case.source,
                   frame=read_frame(case.source).with_columns(pl.lit("changed").alias("ticket")))
    db_session.commit()
    with pytest.raises(review.TabularError) as error:
        review.review_page(db_session, case.decision)
    assert error.value.code == "LABEL_REVIEW_SOURCE_CHANGED"


def test_review_cannot_be_forged_by_automatic_approval_or_changed_output(db_session, review_case):
    case = review_case
    output = review.apply_review(db_session, case.decision, reviewer_id=case.owner.id, body=review_body(case))
    case.decision.status = "accepted"
    case.decision.approved_by = "system:ttl"
    db_session.commit()
    with pytest.raises(review.TabularError) as error:
        review.training_provenance(db_session, output, "topic")
    assert error.value.code == "LABEL_REVIEW_HUMAN_REQUIRED"
    confirm(db_session, case, output)
    register_frame(db_session, workspace_id=case.workspace.id, name=output.name, into=output,
                   frame=read_frame(output).with_columns(pl.lit("billing").alias("topic")))
    db_session.commit()
    with pytest.raises(review.TabularError) as error:
        review.training_provenance(db_session, output, "topic")
    assert error.value.code == "LABEL_REVIEW_SOURCE_CHANGED"


def test_approval_and_dataset_creation_can_be_rolled_back_together(db_session, review_case):
    case = review_case
    output_id = review.apply_review(db_session, case.decision, reviewer_id=case.owner.id,
                                   body=review_body(case)).id
    db_session.rollback()
    assert db_session.get(TabularDataset, output_id) is None
    db_session.refresh(case.decision)
    assert "label_review_result" not in case.decision.rationale
    assert case.decision.status == "proposed"
