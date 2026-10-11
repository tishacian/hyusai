"""Immutable SkillInvocation snapshot and producer contracts."""
from __future__ import annotations

import ast
import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import intelligence as intelligence_endpoint
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services.chat_run_ledger import enrich_chat_run_ledger
from app.services.knowledge_capture import _record_capture_run
from app.services.run_engine import engine as engine_module
from app.services.skill_invocation_snapshot import (
    capture_skill_execution_evidence,
    resolve_skill_invocation_cost,
)

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _skill(
    *,
    identifier: str,
    slug: str,
    workspace_id: str | None,
    provider: str | None = "internal",
) -> Skill:
    return Skill(
        id=identifier,
        workspace_id=workspace_id,
        slug=slug,
        version="7",
        name="Snapshot test Skill",
        input_schema={"type": "object", "secret_example": "input-secret"},
        output_schema={"type": "object", "private": "output-secret"},
        execution={"mode": "sync", "api_key": "execution-secret"},
        pricing={"unit": "per_call", "unit_price": 0.25, "currency": "EUR"},
        provider=provider,
        certification_level="production",
    )


def test_resolved_snapshot_is_allowlisted_and_secret_free(db_session):
    skill = _skill(
        identifier="11111111-1111-1111-1111-111111111111",
        slug="snapshot_test_v1",
        workspace_id="workspace-a",
        provider="https://user:provider-secret@example.test",
    )
    db_session.add(skill)
    db_session.flush()

    evidence = capture_skill_execution_evidence(
        db_session,
        workspace_id="workspace-a",
        skill_slug=skill.slug,
    )

    assert evidence.skill_id == skill.id
    assert evidence.skill_slug == skill.slug
    assert set(evidence.execution_snapshot) == {
        "schema_version",
        "resolution",
        "skill",
        "digests",
    }
    assert evidence.execution_snapshot["resolution"] == "resolved"
    assert evidence.execution_snapshot["skill"] == {
        "id": skill.id,
        "slug": skill.slug,
        "scope": "workspace",
        "version": "7",
        "certification_level": "production",
    }
    assert set(evidence.execution_snapshot["digests"]) == {
        "input_contract_sha256",
        "output_contract_sha256",
        "execution_sha256",
    }
    assert all(
        len(digest) == 64
        for digest in evidence.execution_snapshot["digests"].values()
    )
    serialized = json.dumps(evidence.execution_snapshot, sort_keys=True)
    assert "input-secret" not in serialized
    assert "output-secret" not in serialized
    assert "execution-secret" not in serialized
    assert "provider-secret" not in serialized
    assert "api_key" not in serialized


def test_snapshot_is_immutable_when_catalogue_skill_changes(db_session):
    skill = _skill(
        identifier="22222222-2222-2222-2222-222222222222",
        slug="immutable_snapshot_v1",
        workspace_id=None,
    )
    db_session.add(skill)
    db_session.flush()
    before = capture_skill_execution_evidence(
        db_session,
        workspace_id="workspace-a",
        skill_id=skill.id,
        skill_slug=skill.slug,
    ).execution_snapshot
    run = Run(id="immutable-run", workspace_id="workspace-a", status="running")
    invocation = SkillInvocation(
        id="immutable-invocation",
        run_id=run.id,
        skill_id=skill.id,
        skill_slug=skill.slug,
        execution_snapshot=before,
        cost_measured=False,
    )
    db_session.add_all([run, invocation])
    db_session.flush()

    skill.version = "8"
    skill.execution = {"mode": "async", "token": "new-secret"}
    db_session.flush()
    db_session.expire(invocation, ["execution_snapshot"])
    after = capture_skill_execution_evidence(
        db_session,
        workspace_id="workspace-a",
        skill_id=skill.id,
        skill_slug=skill.slug,
    ).execution_snapshot

    assert invocation.execution_snapshot["skill"]["version"] == "7"
    assert invocation.execution_snapshot["skill"]["scope"] == "global"
    assert invocation.execution_snapshot["skill"]["provider"] == "internal"
    assert invocation.execution_snapshot["skill"]["certification_level"] == "production"
    assert after["skill"]["version"] == "8"
    assert (
        invocation.execution_snapshot["digests"]["execution_sha256"]
        != after["digests"]["execution_sha256"]
    )


def test_stale_or_mismatched_identity_stays_honestly_unresolved(db_session):
    skill = _skill(
        identifier="33333333-3333-3333-3333-333333333333",
        slug="canonical_slug_v1",
        workspace_id="workspace-a",
    )
    db_session.add(skill)
    db_session.flush()

    evidence = capture_skill_execution_evidence(
        db_session,
        workspace_id="workspace-a",
        skill_id=skill.id,
        skill_slug="different_slug_v1",
    )

    assert evidence.skill_id is None
    assert evidence.skill_slug == "different_slug_v1"
    assert evidence.execution_snapshot == {
        "schema_version": 1,
        "resolution": "unresolved",
        "resolution_reason": "skill_identity_mismatch",
        "requested_skill": {
            "id": skill.id,
            "slug": "different_slug_v1",
        },
    }


def test_historical_zero_cost_remains_unknown(db_session):
    run = Run(id="historical-run", workspace_id="workspace-a", status="completed")
    invocation = SkillInvocation(
        id="historical-invocation",
        run_id=run.id,
        skill_slug="legacy_v1",
        status="completed",
        cost=0.0,
    )
    db_session.add_all([run, invocation])
    db_session.flush()

    assert invocation.execution_snapshot is None
    assert invocation.cost == 0.0
    assert invocation.cost_measured is None


def test_chat_producer_captures_resolved_and_unresolved_evidence(db_session):
    db_session.add(
        _skill(
            identifier="44444444-4444-4444-4444-444444444444",
            slug="llm_rag_answer_v1",
            workspace_id=None,
        )
    )
    run = Run(
        id="new-chat-run",
        workspace_id="workspace-a",
        status="completed",
        trigger="chat",
        started_at=datetime.utcnow(),
        duration_ms=20.0,
        input_ref={},
        output_ref={},
    )
    db_session.add(run)
    db_session.flush()

    enrich_chat_run_ledger(
        db_session,
        run,
        sources=[],
        reasoning_trace=None,
        extra_output={},
    )
    invocations = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )

    assert [item.skill_slug for item in invocations] == [
        "llm_rag_answer_v1",
        "audit_log_v1",
    ]
    assert invocations[0].skill_id == "44444444-4444-4444-4444-444444444444"
    assert invocations[0].execution_snapshot["resolution"] == "resolved"
    assert invocations[1].skill_id is None
    assert invocations[1].execution_snapshot["resolution"] == "unresolved"
    assert invocations[0].cost == 0.25
    assert invocations[0].cost_measured is True
    assert invocations[0].metrics["cost_evidence"]["state"] == "calculated"
    assert invocations[0].metrics["cost_evidence"]["currency"] == "EUR"
    assert invocations[1].cost == 0.0
    assert invocations[1].cost_measured is False
    assert invocations[1].metrics["cost_evidence"] == {
        "schema_version": 1,
        "state": "not_measured",
        "reason": "skill_unresolved",
    }


def test_catalog_cost_requires_complete_identifiable_tariff(db_session):
    priced = _skill(
        identifier="55555555-5555-5555-5555-555555555555",
        slug="priced_v1",
        workspace_id="workspace-a",
    )
    priced.pricing = {
        "unit": "per_call",
        "unit_price": 0.25,
        "currency": "EUR",
        "api_key": "pricing-secret",
    }
    free = _skill(
        identifier="66666666-6666-6666-6666-666666666666",
        slug="free_v1",
        workspace_id="workspace-a",
    )
    free.pricing = {"unit": "per_call", "unit_price": 0.0, "currency": "USD"}
    incomplete = _skill(
        identifier="77777777-7777-7777-7777-777777777777",
        slug="incomplete_v1",
        workspace_id="workspace-a",
    )
    incomplete.pricing = {"unit_price": 0.0}
    usage_priced = _skill(
        identifier="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        slug="usage_priced_v1",
        workspace_id="workspace-a",
    )
    usage_priced.pricing = {
        "unit": "per_1k_tokens",
        "unit_price": 0.01,
        "currency": "USD",
    }
    db_session.add_all([priced, free, incomplete, usage_priced])
    db_session.flush()

    calculated = resolve_skill_invocation_cost(
        db_session,
        workspace_id="workspace-a",
        skill_id=priced.id,
        skill_slug=priced.slug,
        quantity=2,
    )
    zero_tariff = resolve_skill_invocation_cost(
        db_session,
        workspace_id="workspace-a",
        skill_id=free.id,
        skill_slug=free.slug,
    )
    missing_tariff = resolve_skill_invocation_cost(
        db_session,
        workspace_id="workspace-a",
        skill_id=incomplete.id,
        skill_slug=incomplete.slug,
    )
    unresolved = resolve_skill_invocation_cost(
        db_session,
        workspace_id="workspace-a",
        skill_id=None,
        skill_slug="missing_v1",
    )
    usage_without_quantity = resolve_skill_invocation_cost(
        db_session,
        workspace_id="workspace-a",
        skill_id=usage_priced.id,
        skill_slug=usage_priced.slug,
    )
    usage_with_quantity = resolve_skill_invocation_cost(
        db_session,
        workspace_id="workspace-a",
        skill_id=usage_priced.id,
        skill_slug=usage_priced.slug,
        quantity=2.5,
    )

    assert calculated.cost == 0.5
    assert calculated.cost_measured is True
    assert calculated.evidence["source"] == f"skill_catalog:{priced.id}:pricing"
    assert calculated.evidence["currency"] == "EUR"
    assert len(calculated.evidence["pricing_sha256"]) == 64
    assert "pricing-secret" not in json.dumps(calculated.evidence, sort_keys=True)
    assert zero_tariff.cost == 0.0
    assert zero_tariff.cost_measured is True
    assert missing_tariff.cost == 0.0
    assert missing_tariff.cost_measured is False
    assert missing_tariff.evidence["reason"] == "pricing_identity_incomplete"
    assert unresolved.cost == 0.0
    assert unresolved.cost_measured is False
    assert unresolved.evidence["reason"] == "skill_unresolved"
    assert usage_without_quantity.cost_measured is False
    assert usage_without_quantity.evidence["reason"] == (
        "pricing_quantity_not_measured"
    )
    assert usage_with_quantity.cost == 0.025
    assert usage_with_quantity.cost_measured is True
    assert usage_with_quantity.evidence["quantity"] == 2.5


async def test_engine_producer_calculates_cost_from_captured_tariff(
    db_session,
    monkeypatch,
):
    skill = _skill(
        identifier="88888888-8888-8888-8888-888888888888",
        slug="engine_priced_v1",
        workspace_id="workspace-a",
    )
    skill.pricing = {"unit": "per_call", "unit_price": 0.125, "currency": "USD"}
    run = Run(id="engine-cost-run", workspace_id="workspace-a", status="running")
    db_session.add_all([skill, run])
    db_session.flush()

    async def _execute(_payload, _ctx):
        return {"status": "ok"}

    monkeypatch.setattr(engine_module, "resolve_skill", lambda _slug: _execute)
    invocation = await engine_module._execute_task_node(
        db_session,
        run,
        {},
        skill.slug,
        control=None,
        last_output={},
    )

    assert invocation is not None
    assert invocation.cost == 0.125
    assert invocation.cost_measured is True
    assert invocation.metrics["cost_evidence"]["method"] == "catalog_unit_price"
    assert invocation.metrics["cost_evidence"]["source"].endswith(":pricing")


def test_knowledge_capture_producer_does_not_promote_unresolved_zero(db_session):
    skill = _skill(
        identifier="99999999-9999-9999-9999-999999999999",
        slug="capture_priced_v1",
        workspace_id="workspace-a",
    )
    skill.pricing = {"unit": "per_turn", "unit_price": 0.015, "currency": "EUR"}
    db_session.add(skill)
    db_session.flush()

    run_id = _record_capture_run(
        db_session,
        workspace_id="workspace-a",
        capability_id=None,
        trigger="capture_test",
        input_ref={"question": "q"},
        output_ref={"answer": "a"},
        skill_slugs=[skill.slug, "capture_missing_v1"],
    )
    db_session.flush()
    invocations = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run_id)
        .order_by(SkillInvocation.skill_slug.asc())
        .all()
    )

    by_slug = {item.skill_slug: item for item in invocations}
    assert by_slug[skill.slug].cost == 0.015
    assert by_slug[skill.slug].cost_measured is True
    assert by_slug[skill.slug].metrics["cost_evidence"]["currency"] == "EUR"
    assert by_slug["capture_missing_v1"].cost == 0.0
    assert by_slug["capture_missing_v1"].cost_measured is False
    assert (
        by_slug["capture_missing_v1"].metrics["cost_evidence"]["reason"]
        == "skill_unresolved"
    )


async def test_intelligence_producer_uses_catalog_cost_evidence(
    db_session,
    monkeypatch,
):
    workspace = Workspace(
        id="workspace-intelligence-cost",
        slug="intelligence-cost",
        name="Intelligence cost",
        mode="demo",
    )
    user = User(id="intelligence-cost-user", username="intelligence-cost-user")
    system = System(
        id="intelligence-cost-system",
        workspace_id=workspace.id,
        name="Intelligence",
        objective="Test truthful costs",
        flow_definition={"variant": "intelligence"},
    )
    skill = _skill(
        identifier="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        slug="intelligence_batch_v1",
        workspace_id=None,
    )
    skill.pricing = {"unit": "per_batch", "unit_price": 0.5, "currency": "USD"}
    db_session.add_all([workspace, user, system, skill])
    db_session.commit()

    async def _run_batch(**_kwargs):
        yield {"type": "batch_completed", "processed": 2}

    async def _sync(*_args, **_kwargs):
        return {"status": "completed"}

    monkeypatch.setattr(intelligence_endpoint, "run_batch", _run_batch)
    monkeypatch.setattr(
        intelligence_endpoint,
        "get_dashboard_data",
        lambda *_args, **_kwargs: {
            "kpis": {"total_articles": 2},
            "synthesis": {"status": "ready"},
        },
    )
    monkeypatch.setattr(intelligence_endpoint, "sync_intelligence_to_knowledge", _sync)

    response = await intelligence_endpoint.trigger_batch(
        workspace=workspace,
        user=user,
        body=intelligence_endpoint.AnalyzeRequest(system_id=system.id),
        db=db_session,
    )
    chunks = [chunk async for chunk in response.body_iterator]

    assert any("run_completed" in str(chunk) for chunk in chunks)
    db_session.expire_all()
    invocation = (
        db_session.query(SkillInvocation)
        .join(Run, Run.id == SkillInvocation.run_id)
        .filter(Run.system_id == system.id)
        .one()
    )
    run = db_session.query(Run).filter(Run.id == invocation.run_id).one()
    assert invocation.cost == 0.5
    assert invocation.cost_measured is True
    assert invocation.metrics["cost_evidence"]["source"] == (
        f"skill_catalog:{skill.id}:pricing"
    )
    assert run.cost_internal == 0.5


@pytest.mark.asyncio
async def test_intelligence_batch_enforces_system_engine_run_before_stream_or_run_creation(
    db_session,
    attest_authorization_v2,
):
    workspace = Workspace(
        id="workspace-intelligence-engine-denied",
        slug="intelligence-engine-denied",
        name="Intelligence engine denied",
        mode="demo",
    )
    user = User(
        id="intelligence-engine-denied-user",
        username="intelligence-engine-denied-user",
    )
    membership = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="member",
        role_template="workspace_viewer",
    )
    system = System(
        id="intelligence-engine-denied-system",
        workspace_id=workspace.id,
        name="Denied Intelligence",
        objective="Must not start",
        flow_definition={"variant": "intelligence"},
    )
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {"system.engine.run": "enforce"},
            }
        },
    )
    db_session.add_all([workspace, user, membership, system, config])
    db_session.flush()
    attest_authorization_v2(config, ["system.engine.run"])
    db_session.commit()

    with pytest.raises(HTTPException) as denied:
        await intelligence_endpoint.trigger_batch(
            workspace=workspace,
            user=user,
            body=intelligence_endpoint.AnalyzeRequest(system_id=system.id),
            db=db_session,
        )

    assert denied.value.status_code == 403
    assert db_session.query(Run).filter(Run.workspace_id == workspace.id).count() == 0


def test_every_application_producer_writes_snapshot_and_cost_state():
    """Fail when a new real producer bypasses immutable execution evidence."""

    uncovered: list[str] = []
    roots = (BACKEND_ROOT / "app", BACKEND_ROOT / "scripts")
    for root in roots:
        for path in root.rglob("*.py"):
            if "tests" in path.parts or path.name == "run.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                constructor_name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else None
                )
                if constructor_name != "SkillInvocation":
                    continue
                keyword_names = {keyword.arg for keyword in node.keywords}
                missing = {"execution_snapshot", "cost_measured"} - keyword_names
                if missing:
                    uncovered.append(
                        f"{path.relative_to(BACKEND_ROOT)}:{node.lineno} missing {sorted(missing)}"
                    )

    assert not uncovered, "\n".join(uncovered)


def test_synthetic_seed_costs_are_never_marked_measured():
    seed_paths = (
        BACKEND_ROOT / "scripts" / "seed_showcase_workspace.py",
        BACKEND_ROOT / "app" / "cli" / "seed_agentium_video_demo.py",
    )
    violations: list[str] = []
    for path in seed_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            constructor_name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else None
            )
            if constructor_name != "SkillInvocation":
                continue
            keyword = next(
                (item for item in node.keywords if item.arg == "cost_measured"),
                None,
            )
            if not (
                keyword
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is False
            ):
                violations.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}")

    assert not violations, "synthetic seed cost marked measured: " + ", ".join(violations)
