"""Labeling through the real Skill engine, with only provider transport replaced."""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

from app.models.policy import ControlPolicy
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.tabular import TabularDataset
from app.models.workspace_job import WorkspaceJob
from app.services.llm_dataset_labeling import KIND, SKILL
from app.services.membrane.enforcement import MeasurementCoverage, collect_valve_usage
from app.services.run_engine.engine import _execute_task_node
from app.services.skills_registry.seed import SEED_SKILLS
from app.services.tabular_datasets import read_frame
from app.tests.services.test_llm_dataset_labeling import config, provider, source  # noqa: F401
from app.tests.services.test_tabular_datasets import object_store_root, workspace  # noqa: F401


@pytest.fixture()
def labeling_run(db_session, workspace, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-label-invocation-key")
    workspace.settings = {
        "llm_portal": {
            "routing": {
                "default_provider": "openai",
                "default_model": "gpt-4o-mini",
                "fallback_chain": ["openai"],
            }
        }
    }
    # Capture the actual catalog tariff, including its measurement semantics.
    entry = next(row for row in SEED_SKILLS if row["slug"] == SKILL)
    skill = Skill(id=str(uuid4()), is_seeded="Y", **deepcopy(entry))
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Label invocation integration",
        objective="Publish a labeled dataset under the workspace model policy",
        skill_ids=[skill.id],
    )
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="running",
        input_ref={},
        output_ref={},
        flow_snapshot={},
        execution_contract={},
    )
    db_session.add_all([skill, system, run])
    db_session.commit()
    return run


def _policy(db, run, allowed_model):
    policy = ControlPolicy(
        id=str(uuid4()),
        workspace_id=run.workspace_id,
        name="Label model policy",
        scope="system",
        target_id=run.system_id,
        allowed_skills=[SKILL],
        extra={
            "membrane_spec": {
                "version": 2,
                "enforcement_mode": "enforce",
                "capabilities": {
                    "allowed_skills": [SKILL],
                    "allowed_models": [allowed_model],
                },
            }
        },
    )
    db.add(policy)
    db.commit()
    return policy


async def _invoke(db, run, control, config, source):
    return await _execute_task_node(
        db,
        run,
        {
            "workspace_id": run.workspace_id,
            "system_id": run.system_id,
            "run_id": run.id,
        },
        SKILL,
        control=control,
        last_output={},
        node_id="label-tickets",
        resolved_input={
            "dataset": {"dataset_id": source.id},
            "_label": {**config, "node_id": "label-tickets"},
        },
    )


@pytest.mark.asyncio
async def test_label_invocation_accounts_each_batch_once_and_reuses_completed_dataset(
    db_session, labeling_run, source, config, provider
):
    control = _policy(db_session, labeling_run, "openai:gpt-4o-mini")
    first = await _invoke(db_session, labeling_run, control, config, source)

    assert first is not None
    assert first.status == "completed", first.error
    output = db_session.get(TabularDataset, first.output_ref["dataset_id"])
    job = db_session.get(WorkspaceJob, first.output_ref["job_id"])
    assert job.status == "completed"
    assert output.status == "ready" and output.source == "generated"
    assert output.run_id == labeling_run.id and output.parent_ids == [source.id]
    assert read_frame(output)["label"].to_list() == [
        "normal", "urgent", "normal", "urgent", "normal"
    ]
    assert len(provider.calls) == 3

    usage = first.metrics["token_evidence"]
    assert first.metrics["total_tokens"] == usage["total_tokens"] == 360
    assert usage["prompt_tokens"] == 300 and usage["completion_tokens"] == 60
    assert usage["provider_calls"] == len(usage["calls"]) == 3
    assert usage["measurement_source"] == "provider_reported"
    assert usage["measurement_coverage"] == "complete"
    assert all(
        call["provider"] == "openai" and call["model"] == "gpt-4o-mini"
        for call in usage["calls"]
    )
    assert first.trace["effective_model"] == "openai:gpt-4o-mini"
    assert first.trace["model_execution"]["returned_model"] == "gpt-4o-mini-2024-07-18"
    assert first.trace["model_execution"]["dispatch_started"] is True

    # A declared tariff is a budget estimate, never measured provider spend.
    assert first.output_ref["labeling"]["estimated_cost_usd"] == pytest.approx(0.00042)
    assert first.output_ref["labeling"]["cost_basis"] == "declared_tariff"
    second = await _invoke(db_session, labeling_run, control, config, source)
    assert second is not None and second.id != first.id
    assert second.status == "completed", second.error
    assert second.output_ref["dataset_id"] == output.id
    assert second.output_ref["job_id"] == job.id
    assert len(provider.calls) == 3
    assert second.metrics["total_tokens"] == second.output_ref["usage"]["total_tokens"] == 0
    assert second.metrics["token_evidence"]["provider_calls"] == 0
    assert second.metrics["token_evidence"]["measurement_source"] == "contractual_non_token_path"
    assert "model_execution" not in second.trace
    assert db_session.query(WorkspaceJob).filter_by(kind=KIND, run_id=labeling_run.id).count() == 1
    assert db_session.query(TabularDataset).filter_by(produced_by=SKILL).count() == 1

    # The run-level valve consumer must see 360, not cumulative re-additions.
    totals = collect_valve_usage([first, second])
    assert totals.tokens == 360 and totals.token_measurement_count == 2
    assert totals.token_coverage is MeasurementCoverage.COMPLETE
    for invocation in (first, second):
        assert invocation.cost_measured is False and invocation.provider_cost_usd is None
        assert invocation.metrics["cost_evidence"]["reason"] == "pricing_quantity_not_measured"
    assert totals.cost_coverage is MeasurementCoverage.UNAVAILABLE


@pytest.mark.asyncio
async def test_label_invocation_denies_workspace_model_before_job_or_provider(
    db_session, labeling_run, source, config, provider
):
    control = _policy(db_session, labeling_run, "openai:gpt-allowed")
    invocation = await _invoke(db_session, labeling_run, control, config, source)

    assert invocation is None
    assert "membrane_capability_block" in labeling_run.error
    assert "model_not_allowed" in labeling_run.error
    assert not provider.calls
    assert db_session.query(SkillInvocation).filter_by(run_id=labeling_run.id).count() == 0
    assert db_session.query(WorkspaceJob).filter_by(kind=KIND).count() == 0
    assert db_session.query(TabularDataset).filter_by(produced_by=SKILL).count() == 0
