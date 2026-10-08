"""Real dataset/checkpoint writes with a mocked provider transport, never a billable call."""
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import polars as pl
import pytest

from app.db.base import SessionLocal
from app.models.tabular import TabularDataset
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services import llm_dataset_labeling as labeling
from app.services.model_plane import execution
from app.services.model_plane.execution import ModelExecution
from app.services.tabular_datasets import read_frame, register_frame, serialize_dataset
from app.tests.services.test_tabular_datasets import object_store_root, workspace  # noqa: F401


@pytest.fixture()
def source(db_session, workspace, object_store_root):
    row = register_frame(db_session, workspace_id=workspace.id, name="Tickets",
        frame=pl.DataFrame({"id": [10, 11, 12, 13, 14], "ticket": [f"request {i}" for i in range(5)],
                            "private_note": ["never send this column"] * 5}))
    db_session.commit()
    return row


@pytest.fixture()
def config():
    return {"text_columns": ["ticket"], "labels": ["urgent", "normal"],
            "instruction": "Assign urgency to support tickets.", "batch_size": 2,
            "input_cost_per_million": 1.0, "output_cost_per_million": 2.0}


@pytest.fixture()
def ctx(workspace):
    return {"workspace_id": workspace.id,
            "_model_execution": ModelExecution("openai", "gpt-4o-mini", "workspace", "workspace")}


@pytest.fixture()
def provider(monkeypatch):
    class Provider:
        calls = []
        effect = None

        async def generate(self, *, model, prompt, **options):
            self.calls.append({"model": model, "prompt": prompt, "options": options})
            records = json.loads(prompt.split("\nRecords: ", 1)[1])
            if self.effect:
                result = self.effect(records, len(self.calls))
                if asyncio.iscoroutine(result):
                    result = await result
                if result is not None:
                    return result
            return {"model": "gpt-4o-mini-2024-07-18", "content": json.dumps({"labels": [
                {"row_id": row["row_id"], "label": "urgent" if row["row_id"] % 2 else "normal"}
                for row in reversed(records)]}), "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}

    client = Provider()
    monkeypatch.setattr(execution, "build_model_client", lambda *args, **kwargs: client)
    return client


async def invoke(source, config, ctx, **changes):
    return await labeling.label_dataset({"config": {**config, **changes},
        "dataset_ref": {"dataset_id": source.id} if source is not None else None}, ctx)


def saved_job(db_session):
    db_session.expire_all()
    return db_session.query(WorkspaceJob).filter_by(kind=labeling.KIND).one()


@pytest.mark.asyncio
async def test_labels_publish_once_with_order_lineage_and_cumulative_usage(db_session, source, config, ctx, provider):
    policies = []
    ctx["_model_policy_check"] = lambda model: policies.append(model.model)
    original = ctx["_model_execution"]
    result = await invoke(source, config, ctx)
    output = db_session.get(TabularDataset, result["dataset_id"])
    frame = read_frame(output)
    assert frame["id"].to_list() == [10, 11, 12, 13, 14]
    assert frame["label"].to_list() == ["normal", "urgent", "normal", "urgent", "normal"]
    assert output.source == "generated" and output.parent_ids == [source.id]
    assert output.status == "ready" and output.produced_by == labeling.SKILL
    assert len(provider.calls) == len(policies) == 3
    assert all("private_note" not in call["prompt"] for call in provider.calls)
    assert all(call["options"]["response_format"]["type"] == "json_schema" for call in provider.calls)
    assert ctx["_model_execution"] is original and "_model_generation_options" not in ctx
    assert len(ctx["_provider_usage_v1"]["calls"]) == 3
    evidence = serialize_dataset(output, include_preview=True)["lineage"]["labeling"]
    assert evidence["charged_tokens"] == 360
    assert evidence["estimated_cost_usd"] == pytest.approx(.00042)
    assert evidence["cost_basis"] == "declared_tariff" and evidence["review_status"] == "unreviewed"
    assert evidence["returned_models"] == ["gpt-4o-mini-2024-07-18"]
    assert "instruction" not in evidence and "provider_cost_usd" not in evidence
    assert len(evidence["source_sha256"]) == 64
    repeated = await invoke(None, config, ctx, resume_job_id=result["job_id"])
    assert repeated["dataset_id"] == output.id and len(provider.calls) == 3
    assert repeated["usage"]["total_tokens"] == 0 and repeated["usage"]["provider_calls"] == 0
    assert db_session.query(TabularDataset).filter_by(produced_by=labeling.SKILL).count() == 1


@pytest.mark.asyncio
async def test_failed_batch_resumes_after_checkpoint_without_relabeling_paid_rows(db_session, source, config, ctx, provider):
    def interrupt(records, call):
        if call == 2:
            raise TimeoutError("private provider diagnostic")
    provider.effect = interrupt
    with pytest.raises(labeling.LabelingError, match="Labeling stopped") as error:
        await invoke(source, config, ctx)
    job = saved_job(db_session)
    assert error.value.job_id == job.id and job.status == "failed"
    assert job.result["cursor"] == 2 and job.result["unknown_attempts"] == 1
    charged = job.result["charged_tokens"]
    assert charged > 120  # Lost response retains its reservation.
    assert "private" not in (job.error or "")
    provider.effect = None
    result = await invoke(None, config, ctx, resume_job_id=job.id)
    starts = [json.loads(call["prompt"].split("\nRecords: ")[1])[0]["row_id"] for call in provider.calls]
    assert starts == [0, 2, 2, 4]
    assert result["labeling"]["unknown_attempts"] == 1
    assert result["labeling"]["charged_tokens"] == charged + 240


@pytest.mark.asyncio
async def test_budget_is_reserved_before_dispatch_and_can_only_be_raised_explicitly(db_session, source, config, ctx, provider):
    with pytest.raises(labeling.LabelingError) as error:
        await invoke(source, config, ctx, max_cost_usd=.000001)
    assert error.value.code == "LABELING_BUDGET_EXHAUSTED" and not provider.calls
    job = saved_job(db_session)
    assert job.result["provider_calls"] == 0 and job.result["charged_tokens"] == 0
    assert "_provider_usage_v1" in ctx and not ctx["_provider_usage_v1"]["calls"]
    result = await invoke(None, config, ctx, resume_job_id=job.id, max_cost_usd=1.0)
    assert result["labeling"]["rows_labeled"] == 5
    db_session.refresh(job)
    assert job.input_ref["spec"]["max_cost_usd"] == 1.0
    with pytest.raises(labeling.LabelingError) as lowered:
        await invoke(None, config, ctx, resume_job_id=job.id, max_cost_usd=.5)
    assert lowered.value.code == "LABELING_BUDGET_INVALID"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    '{"labels":[{"row_id":0,"label":"urgent"},{"row_id":0,"label":"normal"}]}',
    '{"labels":[{"row_id":0,"label":"unknown"},{"row_id":1,"label":"normal"}]}',
    '```json\n{"labels": []}\n```',
    '{"labels":[],"extra":NaN}',
    '{"labels":[{"row_id":true,"label":"urgent"}]}',
])
async def test_invalid_output_keeps_real_usage_and_publishes_no_partial_table(db_session, source, config, ctx, provider, response):
    provider.effect = lambda *_: {"content": response, "usage": {"prompt_tokens": 40, "completion_tokens": 10}}
    with pytest.raises(labeling.LabelingError) as error:
        await invoke(source, config, ctx)
    assert error.value.code == "LABELING_OUTPUT_INVALID"
    job = saved_job(db_session)
    assert job.result["cursor"] == 0 and job.result["charged_tokens"] == 50
    assert job.result["unknown_attempts"] == 0
    output = db_session.get(TabularDataset, job.result["output_id"])
    assert output.status == "failed" and output.storage_key is None


@pytest.mark.asyncio
async def test_ollama_top_level_usage_is_settled_from_canonical_evidence(db_session, source, config, ctx, provider):
    ctx["_model_execution"] = ModelExecution("ollama", "llama3", "none", "workspace")
    def reply(records, _):
        return {"response": json.dumps({"labels": [{"row_id": row["row_id"], "label": "normal"} for row in records]}),
                "prompt_eval_count": 70, "eval_count": 12}
    provider.effect = reply
    result = await invoke(source, config, ctx)
    assert result["labeling"]["charged_tokens"] == 3 * 82
    assert result["labeling"]["unknown_attempts"] == 0
    assert all(call["options"]["format"]["type"] == "object" for call in provider.calls)


@pytest.mark.asyncio
async def test_concurrent_invocation_is_refused_before_any_second_job_or_call(db_session, source, config, ctx, provider):
    entered, release = asyncio.Event(), asyncio.Event()
    async def wait(*_):
        entered.set()
        await release.wait()
    provider.effect = wait
    first = asyncio.create_task(invoke(source, config, ctx))
    await entered.wait()
    try:
        with pytest.raises(labeling.LabelingError) as error:
            await invoke(source, config, dict(ctx))
        assert error.value.code == "LABELING_BUSY"
        assert len(provider.calls) == 1
    finally:
        release.set()
    await first
    assert db_session.query(WorkspaceJob).filter_by(kind=labeling.KIND).count() == 1


@pytest.mark.asyncio
async def test_deleted_output_is_not_resurrected_after_an_inflight_call(db_session, source, config, ctx, provider):
    def remove(*_):
        with SessionLocal() as other:
            job = other.query(WorkspaceJob).filter_by(kind=labeling.KIND).one()
            other.get(TabularDataset, job.result["output_id"]).status = "deleted"
            other.commit()
    provider.effect = remove
    with pytest.raises(labeling.LabelingError) as error:
        await invoke(source, config, ctx)
    assert error.value.code == "LABELING_DATASET_UNAVAILABLE" and len(provider.calls) == 1
    job = saved_job(db_session)
    assert db_session.get(TabularDataset, job.result["output_id"]).status == "deleted"
    assert job.result["charged_tokens"] == 120


@pytest.mark.asyncio
async def test_cancellation_keeps_checkpoint_and_charged_unknown_call(db_session, source, config, ctx, provider):
    entered = asyncio.Event()
    async def wait(records, count):
        if count == 2:
            entered.set()
            await asyncio.Event().wait()
    provider.effect = wait
    task = asyncio.create_task(invoke(source, config, ctx))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    job = saved_job(db_session)
    assert job.result["cursor"] == 2 and job.result["unknown_attempts"] == 1
    assert job.status == "failed" and job.error == "LABELING_CANCELLED"
    assert "_model_before_dispatch" not in ctx


@pytest.mark.asyncio
async def test_workspace_is_authoritative_and_resume_is_scoped(db_session, source, config, ctx, provider):
    result = await invoke(source, config, ctx)
    other = Workspace(id=str(uuid4()), slug="other-label-ws", name="Other", settings={})
    db_session.add(other)
    db_session.commit()
    with pytest.raises(labeling.LabelingError) as error:
        await invoke(None, config, {**ctx, "workspace_id": other.id}, resume_job_id=result["job_id"])
    assert error.value.code == "LABELING_JOB_NOT_FOUND"
    with pytest.raises(labeling.TabularError) as source_error:
        await invoke(source, config, {**ctx, "workspace_id": other.id})
    assert source_error.value.code == "DATASET_NOT_FOUND"
    assert len(provider.calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,code", [
    ({"labels": ["same", "same"]}, "LABELING_SPEC_INVALID"),
    ({"max_cost_usd": float("inf")}, "LABELING_SPEC_INVALID"),
    ({"max_tokens": True}, "LABELING_SPEC_INVALID"),
    ({"max_rows": 4}, "LABELING_DATASET_TOO_LARGE"),
    ({"text_columns": ["id"]}, "LABELING_COLUMNS_INVALID"),
    ({"label_column": "ticket"}, "LABELING_COLUMNS_INVALID"),
    ({"unexpected": 1}, "LABELING_SPEC_INVALID"),
])
async def test_invalid_spec_fails_before_creating_a_job_or_spending(db_session, source, config, ctx, provider, changes, code):
    with pytest.raises(labeling.LabelingError) as error:
        await invoke(source, config, ctx, **changes)
    assert error.value.code == code and not provider.calls
    assert db_session.query(WorkspaceJob).filter_by(kind=labeling.KIND).count() == 0


@pytest.mark.asyncio
async def test_changed_instruction_or_source_cannot_reuse_paid_labels(db_session, source, config, ctx, provider):
    result = await invoke(source, config, ctx)
    with pytest.raises(labeling.LabelingError) as error:
        await invoke(source, config, ctx, resume_job_id=result["job_id"], instruction="Different classification")
    assert error.value.code == "LABELING_RESUME_MISMATCH"
    assert len(provider.calls) == 3


@pytest.mark.asyncio
async def test_policy_rechecked_before_every_paid_batch(db_session, source, config, ctx, provider):
    seen = []
    def check(model):
        seen.append(model)
        if len(seen) == 2:
            raise ValueError("policy_revoked")
    ctx["_model_policy_check"] = check
    with pytest.raises(labeling.LabelingError):
        await invoke(source, config, ctx)
    assert len(provider.calls) == 1
    job = saved_job(db_session)
    assert job.result["charged_tokens"] == 120 and job.result["cursor"] == 2
    assert job.result["provider_calls"] == 1


@pytest.mark.asyncio
async def test_failed_publication_resumes_from_all_fragments_without_another_call(db_session, source, config, ctx, provider, monkeypatch):
    from app.services import tabular_datasets
    real = tabular_datasets.register_frame
    def fail(*args, **kwargs):
        raise OSError("simulated publication failure")
    monkeypatch.setattr(tabular_datasets, "register_frame", fail)
    with pytest.raises(labeling.LabelingError) as error:
        await invoke(source, config, ctx)
    job = saved_job(db_session)
    assert job.result["cursor"] == 5 and len(provider.calls) == 3
    monkeypatch.setattr(tabular_datasets, "register_frame", real)
    result = await invoke(None, config, ctx, resume_job_id=error.value.job_id)
    assert len(provider.calls) == 3
    assert result["labeling"]["rows_labeled"] == 5
    assert result["usage"]["provider_calls"] == result["usage"]["total_tokens"] == 0


@pytest.mark.asyncio
async def test_corrupt_fragment_stops_resume_before_new_spending(db_session, source, config, ctx, provider):
    from app.services.object_store import get_object_store
    def fail(records, call):
        if call == 2:
            raise RuntimeError("temporary failure")
    provider.effect = fail
    with pytest.raises(labeling.LabelingError):
        await invoke(source, config, ctx)
    job = saved_job(db_session)
    get_object_store().write_bytes(job.result["fragments"][0]["key"], b'{}')
    provider.effect = None
    with pytest.raises(labeling.LabelingError) as error:
        await invoke(None, config, ctx, resume_job_id=job.id)
    assert error.value.code == "LABELING_CHECKPOINT_INVALID" and len(provider.calls) == 2


@pytest.mark.asyncio
async def test_crash_after_reservation_keeps_charge_when_next_producer_resumes(db_session, source, config, ctx, provider):
    with pytest.raises(labeling.LabelingError):
        await invoke(source, config, ctx, max_tokens=1)
    job = saved_job(db_session)
    # State left on disk by a killed process after dispatch, before settlement.
    job.status = "running"
    job.result = {**job.result, "pending": {"start": 0, "rows": 2, "tokens": 500, "cost": .002},
                  "charged_tokens": 500, "estimated_cost_usd": .002, "provider_calls": 1}
    db_session.commit()
    result = await invoke(None, config, ctx, resume_job_id=job.id, max_tokens=100_000)
    assert result["labeling"]["charged_tokens"] == 500 + 360
    assert result["labeling"]["estimated_cost_usd"] == pytest.approx(.00242)
    assert result["labeling"]["provider_calls"] == 4 and result["labeling"]["unknown_attempts"] == 1


@pytest.mark.asyncio
async def test_source_changed_under_same_id_is_refused_at_resume(db_session, source, config, ctx, provider):
    from app.services.object_store import get_object_store
    from io import BytesIO
    result = await invoke(source, config, ctx)
    frame = read_frame(source).with_columns(pl.lit("changed content").alias("ticket"))
    content = BytesIO()
    frame.write_parquet(content)
    get_object_store().write_bytes(source.storage_key, content.getvalue())
    with pytest.raises(labeling.LabelingError) as error:
        await invoke(source, config, ctx, resume_job_id=result["job_id"])
    assert error.value.code == "LABELING_RESUME_MISMATCH" and len(provider.calls) == 3


@pytest.mark.asyncio
async def test_missing_usage_keeps_conservative_reservations(db_session, source, config, ctx, provider):
    provider.effect = lambda rows, _: {"content": json.dumps({"labels": [
        {"row_id": row["row_id"], "label": "normal"} for row in rows]})}
    result = await invoke(source, config, ctx)
    assert result["labeling"]["unknown_attempts"] == 3
    assert result["labeling"]["charged_tokens"] > 3 * config.get("max_output_tokens", 2048)
    assert all(not call["reported"] for call in ctx["_provider_usage_v1"]["calls"])


@pytest.mark.asyncio
async def test_membership_revocation_stops_before_the_next_batch(db_session, source, config, ctx, provider):
    from app.models.user import User
    from app.models.workspace import WorkspaceMember
    user = User(id=str(uuid4()), username="labeler", email="labeler@example.test", role="user", is_active=True)
    db_session.add(user)
    db_session.flush()
    membership = WorkspaceMember(user_id=user.id, workspace_id=ctx["workspace_id"], role="member")
    db_session.add(membership)
    db_session.commit()
    ctx["user_id"] = user.id
    def revoke(*_):
        with SessionLocal() as other:
            other.query(WorkspaceMember).filter_by(user_id=user.id, workspace_id=ctx["workspace_id"]).delete()
            other.commit()
    provider.effect = revoke
    with pytest.raises(labeling.LabelingError) as error:
        await invoke(source, config, ctx)
    assert error.value.code == "LABELING_ACCESS_REVOKED" and len(provider.calls) == 1


@pytest.mark.asyncio
async def test_job_cancellation_is_not_overwritten_after_an_inflight_call(db_session, source, config, ctx, provider):
    def cancel(*_):
        with SessionLocal() as other:
            other.query(WorkspaceJob).filter_by(kind=labeling.KIND).one().status = "cancelled"
            other.commit()
    provider.effect = cancel
    with pytest.raises(labeling.LabelingError) as error:
        await invoke(source, config, ctx)
    assert error.value.code == "LABELING_CANCELLED"
    job = saved_job(db_session)
    assert job.status == "cancelled" and len(provider.calls) == 1
    assert f"job_id={job.id}" in str(error.value)


@pytest.mark.asyncio
async def test_workspace_fallback_is_never_used_for_labeling(db_session, source, config, ctx, provider):
    from dataclasses import replace
    ctx["_model_execution"] = replace(ctx["_model_execution"], _fallbacks=(ModelExecution("ollama", "other", "none", "workspace"),))
    def fail(*_):
        raise RuntimeError("provider failed")
    provider.effect = fail
    with pytest.raises(labeling.LabelingError):
        await invoke(source, config, ctx)
    assert len(provider.calls) == 1 and provider.calls[0]["model"] == "gpt-4o-mini"
    assert len(ctx["_model_execution"]._fallbacks) == 1
