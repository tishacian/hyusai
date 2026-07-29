"""Tenant/catalog authority for System authoring and runtime entry points."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.v1.endpoints import systems
from app.models.capability import Capability
from app.models.policy import AdaptivePolicy
from app.models.run import Run, SkillInvocation
from app.models.run_schedule import RunSchedule
from app.models.skill import Skill
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.run_engine import scheduler, triggers
from app.services.run_engine.dag import execute_run_dag
from app.services.run_engine.engine import execute_run
from app.services.system_catalog_bindings import (
    SystemCatalogBindingError,
    resolve_persisted_system_catalog_bindings,
    resolve_system_catalog_bindings,
)


def _workspace(db, key: str, settings: dict | None = None) -> Workspace:
    row = Workspace(
        id=str(uuid4()),
        name=key,
        slug=f"catalog-{key.lower()}-{uuid4().hex[:8]}",
        settings=settings or {},
    )
    db.add(row)
    db.flush()
    return row


def _skill(db, slug: str, *, workspace_id: str | None = None) -> Skill:
    row = Skill(
        id=str(uuid4()),
        workspace_id=workspace_id,
        slug=f"{slug}-{uuid4().hex[:8]}",
        name=slug,
        version="1",
        input_schema={},
        output_schema={},
        execution={"mode": "sync"},
        pricing={"unit_price": 0.0},
    )
    db.add(row)
    db.flush()
    return row


def _capability(
    db,
    slug: str,
    skill: Skill,
    *,
    tier: str,
    industry: str | None = None,
    workspace_id: str | None = None,
) -> Capability:
    row = Capability(
        id=str(uuid4()),
        workspace_id=workspace_id,
        slug=f"{slug}-{uuid4().hex[:8]}",
        name=slug,
        tier=tier,
        industry=industry,
        skill_ids=[skill.id],
    )
    db.add(row)
    db.flush()
    return row


def _resolve(db, workspace: Workspace, capability: Capability | None, skills=None, policy=None):
    return resolve_system_catalog_bindings(
        db,
        workspace=workspace,
        system_id="prospective-system",
        capability_id=capability.id if capability else None,
        skill_ids=skills,
        adaptive_policy_id=policy.id if policy else None,
    )


def _assert_code(code: str, fn) -> None:
    with pytest.raises(SystemCatalogBindingError) as caught:
        fn()
    assert caught.value.code == code


def test_family_catalog_visibility_is_authoritative_for_system_bindings(db_session):
    sentinel = _workspace(db_session, "Sentinel", {"family": "sentinel_ci"})
    andritz = _workspace(
        db_session,
        "Andritz",
        {
            "family": "andritz",
            "catalog": {
                "hidden_capabilities": [],
                "hidden_skills": [],
            },
        },
    )
    octocity = _workspace(
        db_session,
        "Octocity",
        {"family": "generic", "catalog": {}},
    )

    government_skill = _skill(db_session, "sentinel-government")
    government = _capability(
        db_session,
        "sentinel-government",
        government_skill,
        tier="industry",
        industry="government",
    )
    manufacturing_skill = _skill(db_session, "andritz-manufacturing")
    manufacturing = _capability(
        db_session,
        "andritz-manufacturing",
        manufacturing_skill,
        tier="industry",
        industry="manufacturing",
    )
    octocity_skill = _skill(db_session, "octocity-client")
    octocity_capability = _capability(
        db_session,
        "octocity-client",
        octocity_skill,
        tier="client",
    )
    hidden_skill = _skill(db_session, "hidden-global")
    hidden_capability = _capability(
        db_session,
        "hidden-global",
        hidden_skill,
        tier="universal",
    )
    hidden_fallback_skill = _skill(db_session, "hidden-fallback")
    visible_with_hidden_fallback = _capability(
        db_session,
        "visible-hidden-fallback",
        hidden_fallback_skill,
        tier="universal",
    )
    foreign_skill = _skill(db_session, "sentinel-local", workspace_id=sentinel.id)
    foreign_capability = _capability(
        db_session,
        "sentinel-local",
        foreign_skill,
        tier="client",
        workspace_id=sentinel.id,
    )

    octocity.settings = {
        **octocity.settings,
        "catalog": {"enabled_capabilities": [octocity_capability.slug]},
    }
    andritz.settings = {
        **andritz.settings,
        "catalog": {
            "hidden_capabilities": [hidden_capability.slug],
            "hidden_skills": [hidden_skill.slug, hidden_fallback_skill.slug],
        },
    }
    db_session.commit()

    assert _resolve(db_session, sentinel, government).skills == (government_skill,)
    assert _resolve(db_session, andritz, manufacturing).skills == (manufacturing_skill,)
    assert _resolve(db_session, octocity, octocity_capability).skills == (octocity_skill,)

    for workspace, capability in (
        (sentinel, manufacturing),
        (sentinel, octocity_capability),
        (andritz, government),
        (andritz, octocity_capability),
        (octocity, government),
        (octocity, manufacturing),
        (andritz, foreign_capability),
    ):
        _assert_code(
            "capability_not_visible",
            lambda workspace=workspace, capability=capability: _resolve(
                db_session, workspace, capability
            ),
        )

    _assert_code(
        "capability_not_visible",
        lambda: _resolve(db_session, andritz, hidden_capability),
    )
    _assert_code(
        "skill_not_visible",
        lambda: _resolve(db_session, andritz, None, [hidden_skill.id]),
    )
    _assert_code(
        "skill_not_visible",
        lambda: _resolve(db_session, andritz, visible_with_hidden_fallback),
    )
    _assert_code(
        "skill_not_visible",
        lambda: _resolve(db_session, andritz, None, [foreign_skill.id]),
    )


def test_persisted_andritz_business_systems_do_not_inherit_discovery_filters(
    db_session,
):
    """Client360 and News Lab remain runnable without catalog opt-in.

    Their global client/finance rows are intentionally absent from Andritz's
    discovery surface.  The persisted System binding is runtime authority;
    changing that discovery decision must not silently disable production.
    """

    workspace = _workspace(
        db_session,
        "Andritz",
        {
            "family": "andritz",
            "catalog": {
                "enabled_capabilities": [],
                "enabled_skills": [],
            },
        },
    )
    client360_skill = _skill(db_session, "client360-pdr-runtime")
    client360_capability = _capability(
        db_session,
        "client360_pdr_opportunity_engine",
        client360_skill,
        tier="client",
        industry="industrial_nonwovens",
    )
    news_skill = _skill(db_session, "intelligence_batch_v1")
    news_capability = _capability(
        db_session,
        "market_signal_brief",
        news_skill,
        tier="industry",
        industry="finance",
    )
    client360 = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Client360 PDR",
        capability_id=client360_capability.id,
        skill_ids=[],
        status="active",
    )
    news_lab = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="News Lab",
        capability_id=news_capability.id,
        skill_ids=[news_skill.id],
        status="active",
    )
    db_session.add_all([client360, news_lab])
    db_session.commit()

    # They stay absent from discovery/create/import authority.
    _assert_code(
        "capability_not_visible",
        lambda: _resolve(db_session, workspace, client360_capability),
    )
    _assert_code(
        "capability_not_visible",
        lambda: _resolve(db_session, workspace, news_capability),
    )

    # Their already persisted bindings remain authoritative at runtime.
    client360_bindings = resolve_persisted_system_catalog_bindings(
        db_session,
        workspace=workspace,
        system=client360,
    )
    news_bindings = resolve_persisted_system_catalog_bindings(
        db_session,
        workspace=workspace,
        system=news_lab,
    )
    assert client360_bindings.capability is client360_capability
    assert client360_bindings.skills == (client360_skill,)
    assert news_bindings.capability is news_capability
    assert news_bindings.skills == (news_skill,)

    # An explicit runtime disable still wins over the persisted binding.
    workspace.settings = {
        **workspace.settings,
        "catalog": {
            "hidden_capabilities": [client360_capability.slug],
        },
    }
    db_session.commit()
    _assert_code(
        "capability_not_visible",
        lambda: resolve_persisted_system_catalog_bindings(
            db_session,
            workspace=workspace,
            system=client360,
        ),
    )


@pytest.mark.asyncio
async def test_run_api_uses_persisted_authority_for_client360_gate_off(
    db_session,
):
    workspace = _workspace(db_session, "Andritz", {"family": "andritz"})
    user = User(
        id=str(uuid4()),
        username="client360-runtime-admin",
        email="client360-runtime-admin@example.test",
        role="admin",
    )
    skill = _skill(db_session, "client360-pdr-api")
    capability = _capability(
        db_session,
        "client360_pdr_opportunity_engine_api",
        skill,
        tier="client",
        industry="industrial_nonwovens",
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Client360 PDR",
        capability_id=capability.id,
        skill_ids=[],
        status="active",
    )
    db_session.add_all([user, system])
    db_session.commit()

    result = await systems.trigger_run(
        system.id,
        systems.RunCreate(input_ref={"query": "PDR opportunities"}),
        BackgroundTasks(),
        workspace,
        user,
        db_session,
    )

    run = db_session.query(Run).filter(Run.id == result["id"]).one()
    assert run.system_id == system.id
    assert run.capability_id == capability.id


@pytest.mark.asyncio
async def test_dag_uses_persisted_authority_for_news_lab_gate_off(db_session):
    workspace = _workspace(db_session, "Andritz", {"family": "andritz"})
    skill = _skill(db_session, "intelligence_batch_v1-dag")
    capability = _capability(
        db_session,
        "market_signal_brief_dag",
        skill,
        tier="industry",
        industry="finance",
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="News Lab",
        capability_id=capability.id,
        skill_ids=[skill.id],
        status="active",
        flow_definition={
            "schema_version": 3,
            "nodes": [
                {"id": "source", "kind": "source"},
                {"id": "sink", "kind": "sink"},
            ],
            "edges": [{"from": "source", "to": "sink"}],
        },
    )
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        capability_id=capability.id,
        status="pending",
    )
    db_session.add_all([system, run])
    db_session.commit()

    result = await execute_run_dag(run.id)

    assert result["status"] == "completed"
    assert "system_catalog_binding_invalid" not in str(result.get("error"))


def test_scheduler_uses_persisted_authority_for_news_lab_gate_off(
    db_session,
    monkeypatch,
):
    workspace = _workspace(db_session, "Andritz", {"family": "andritz"})
    skill = _skill(db_session, "intelligence_batch_v1-scheduler")
    capability = _capability(
        db_session,
        "market_signal_brief_scheduler",
        skill,
        tier="industry",
        industry="finance",
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="News Lab",
        capability_id=capability.id,
        skill_ids=[skill.id],
        status="active",
    )
    schedule = RunSchedule(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        name="News Lab hourly",
        cron_expr="0 * * * *",
        timezone="UTC",
        enabled=True,
    )
    db_session.add_all([system, schedule])
    db_session.commit()
    monkeypatch.setattr(scheduler, "_dispatch_run", lambda _run_id: None)

    run_id = scheduler._fire_schedule(db_session, schedule, now=datetime.utcnow())

    assert run_id is not None
    run = db_session.query(Run).filter(Run.id == run_id).one()
    assert run.system_id == system.id
    assert run.capability_id == capability.id


def test_adaptive_policy_owner_and_scope_match_prospective_system(db_session):
    workspace = _workspace(db_session, "Owner", {"family": "andritz"})
    other = _workspace(db_session, "Other", {"family": "sentinel_ci"})
    skill = _skill(db_session, "manufacturing-policy")
    capability = _capability(
        db_session,
        "manufacturing-policy",
        skill,
        tier="industry",
        industry="manufacturing",
    )
    valid = AdaptivePolicy(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Capability policy",
        scope="capability",
        target_id=capability.id,
        enabled=True,
    )
    wrong_target = AdaptivePolicy(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Wrong capability",
        scope="capability",
        target_id=str(uuid4()),
        enabled=True,
    )
    foreign = AdaptivePolicy(
        id=str(uuid4()),
        workspace_id=other.id,
        name="Foreign policy",
        scope="portfolio",
        target_id=other.id,
        enabled=True,
    )
    db_session.add_all([valid, wrong_target, foreign])
    db_session.commit()

    assert _resolve(db_session, workspace, capability, policy=valid).adaptive_policy is valid
    _assert_code(
        "adaptive_policy_scope_mismatch",
        lambda: _resolve(db_session, workspace, capability, policy=wrong_target),
    )
    _assert_code(
        "adaptive_policy_workspace_mismatch",
        lambda: _resolve(db_session, workspace, capability, policy=foreign),
    )


@pytest.mark.asyncio
async def test_create_and_update_reject_invisible_catalog_references(
    db_session,
    monkeypatch,
):
    workspace = _workspace(db_session, "Andritz", {"family": "andritz"})
    other = _workspace(db_session, "Sentinel", {"family": "sentinel_ci"})
    user = User(
        id=str(uuid4()),
        username="catalog-admin",
        email="catalog-admin@example.test",
        role="admin",
    )
    local_skill = _skill(db_session, "local-andritz", workspace_id=workspace.id)
    local_capability = _capability(
        db_session,
        "local-andritz",
        local_skill,
        tier="client",
        workspace_id=workspace.id,
    )
    foreign_skill = _skill(db_session, "foreign-sentinel", workspace_id=other.id)
    foreign_capability = _capability(
        db_session,
        "foreign-sentinel",
        foreign_skill,
        tier="client",
        workspace_id=other.id,
    )
    db_session.add(user)
    db_session.commit()
    monkeypatch.setattr(systems, "enforce_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        systems,
        "legacy_object_action_allowed",
        lambda *args, **kwargs: True,
    )

    with pytest.raises(HTTPException) as create_error:
        await systems.create_system(
            systems.SystemCreate(
                name="Cross-family System",
                capability_id=foreign_capability.id,
            ),
            workspace,
            user,
            db_session,
        )
    assert create_error.value.detail["code"] == "capability_not_visible"

    created = await systems.create_system(
        systems.SystemCreate(
            name="Local System",
            capability_id=local_capability.id,
            skill_ids=[local_skill.id],
        ),
        workspace,
        user,
        db_session,
    )
    with pytest.raises(HTTPException) as update_error:
        await systems.update_system(
            created["id"],
            systems.SystemUpdate(skill_ids=[foreign_skill.id]),
            systems.SystemUpdateOptions(),
            workspace,
            user,
            db_session,
        )
    assert update_error.value.detail["code"] == "skill_not_visible"
    persisted = db_session.query(System).filter(System.id == created["id"]).one()
    assert persisted.skill_ids == [local_skill.id]

    corrupt = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Persisted cross-family System",
        capability_id=foreign_capability.id,
        skill_ids=[foreign_skill.id],
    )
    db_session.add(corrupt)
    db_session.commit()
    with pytest.raises(HTTPException) as trigger_error:
        await systems.trigger_run(
            corrupt.id,
            systems.RunCreate(input_ref={"query": "must not run"}),
            BackgroundTasks(),
            workspace,
            user,
            db_session,
        )
    assert trigger_error.value.detail["code"] == "capability_not_visible"
    assert db_session.query(Run).count() == 0


@pytest.mark.asyncio
async def test_sequential_and_dag_fail_before_skill_invocation_on_hidden_binding(
    db_session,
):
    hidden = _skill(db_session, "runtime-hidden")
    workspace = _workspace(
        db_session,
        "Andritz",
        {
            "family": "andritz",
            "catalog": {"hidden_skills": [hidden.slug]},
        },
    )
    sequential_system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Invalid sequential",
        skill_ids=[hidden.id],
        flow_definition={},
    )
    dag_system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Invalid DAG",
        skill_ids=[hidden.id],
        flow_definition={
            "schema_version": 3,
            "nodes": [
                {"id": "source", "kind": "source"},
                {"id": "work", "kind": "task", "config": {"skill_slug": hidden.slug}},
                {"id": "sink", "kind": "sink"},
            ],
            "edges": [
                {"from": "source", "to": "work"},
                {"from": "work", "to": "sink"},
            ],
        },
    )
    sequential_run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=sequential_system.id,
        status="pending",
    )
    dag_run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=dag_system.id,
        status="pending",
    )
    db_session.add_all([sequential_system, dag_system, sequential_run, dag_run])
    db_session.commit()

    sequential_result = await execute_run(sequential_run.id)
    dag_result = await execute_run_dag(dag_run.id)

    assert sequential_result["status"] == "failed"
    assert sequential_result["error"] == "system_catalog_binding_invalid:skill_not_visible"
    assert dag_result["status"] == "failed"
    assert dag_result["error"] == "system_catalog_binding_invalid:skill_not_visible"
    assert db_session.query(SkillInvocation).count() == 0


@pytest.mark.asyncio
async def test_runtime_rejects_run_system_workspace_and_capability_drift(db_session):
    owner = _workspace(db_session, "Owner")
    other = _workspace(db_session, "Other")
    first_skill = _skill(db_session, "first")
    second_skill = _skill(db_session, "second")
    first_capability = _capability(
        db_session, "first", first_skill, tier="universal"
    )
    second_capability = _capability(
        db_session, "second", second_skill, tier="universal"
    )
    system = System(
        id=str(uuid4()),
        workspace_id=owner.id,
        name="Scoped System",
        capability_id=first_capability.id,
        skill_ids=[first_skill.id],
    )
    foreign_run = Run(
        id=str(uuid4()),
        workspace_id=other.id,
        system_id=system.id,
        capability_id=first_capability.id,
        status="pending",
    )
    drifted_run = Run(
        id=str(uuid4()),
        workspace_id=owner.id,
        system_id=system.id,
        capability_id=second_capability.id,
        status="pending",
    )
    db_session.add_all([system, foreign_run, drifted_run])
    db_session.commit()

    foreign = await execute_run(foreign_run.id)
    drifted = await execute_run(drifted_run.id)
    assert foreign["error"] == "system_not_found"
    assert drifted["error"] == "system_catalog_binding_invalid:run_system_capability_mismatch"
    assert db_session.query(SkillInvocation).count() == 0


def test_event_trigger_rejects_invalid_catalog_before_journaling(
    db_session,
    monkeypatch,
):
    hidden = _skill(db_session, "trigger-hidden")
    workspace = _workspace(
        db_session,
        "Octocity",
        {
            "family": "generic",
            "features": {"enable_event_triggers": True},
            "catalog": {"hidden_skills": [hidden.slug]},
        },
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Invalid trigger System",
        skill_ids=[hidden.id],
        status="active",
        flow_definition={
            "schema_version": 3,
            "nodes": [
                {"id": "source", "kind": "source", "type": "source.deposit_promoted"},
                {"id": "work", "kind": "task", "config": {"skill_slug": hidden.slug}},
            ],
            "edges": [{"from": "source", "to": "work"}],
        },
    )
    db_session.add(system)
    db_session.commit()
    monkeypatch.setattr(triggers.settings, "enable_event_triggers", False)

    result = triggers.emit_event(
        triggers.EVENT_DEPOSIT_PROMOTED,
        workspace.id,
        {"file_id": "f-1"},
        db=db_session,
    )

    assert result == [
        {
            "system_id": system.id,
            "status": "rejected",
            "reason": "catalog_binding_invalid:skill_not_visible",
        }
    ]
    assert db_session.query(Run).count() == 0


def test_event_trigger_uses_persisted_authority_for_news_lab_gate_off(
    db_session,
):
    workspace = _workspace(
        db_session,
        "Andritz",
        {
            "family": "andritz",
            "features": {"enable_event_triggers": True},
        },
    )
    skill = _skill(db_session, "intelligence_batch_v1-trigger")
    capability = _capability(
        db_session,
        "market_signal_brief_trigger",
        skill,
        tier="industry",
        industry="finance",
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="News Lab",
        capability_id=capability.id,
        skill_ids=[skill.id],
        status="active",
        flow_definition={
            "schema_version": 3,
            "nodes": [
                {
                    "id": "source",
                    "kind": "source",
                    "type": "source.deposit_promoted",
                },
                {"id": "sink", "kind": "sink"},
            ],
            "edges": [{"from": "source", "to": "sink"}],
        },
    )
    db_session.add(system)
    db_session.commit()

    result = triggers.emit_event(
        triggers.EVENT_DEPOSIT_PROMOTED,
        workspace.id,
        {"file_id": "news-source"},
        db=db_session,
    )

    assert len(result) == 1
    assert result[0]["system_id"] == system.id
    assert result[0]["status"] == "simulated"
    run = db_session.query(Run).one()
    assert run.capability_id == capability.id


def test_event_trigger_stamps_authoritative_system_capability(db_session):
    workspace = _workspace(
        db_session,
        "Sentinel",
        {
            "family": "sentinel_ci",
            "features": {"enable_event_triggers": True},
        },
    )
    skill = _skill(db_session, "government-trigger")
    capability = _capability(
        db_session,
        "government-trigger",
        skill,
        tier="industry",
        industry="government",
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Valid trigger System",
        capability_id=capability.id,
        status="active",
        flow_definition={
            "schema_version": 3,
            "nodes": [
                {"id": "source", "kind": "source", "type": "source.deposit_promoted"},
                {"id": "work", "kind": "task", "config": {"skill_slug": skill.slug}},
            ],
            "edges": [{"from": "source", "to": "work"}],
        },
    )
    db_session.add(system)
    db_session.commit()

    result = triggers.emit_event(
        triggers.EVENT_DEPOSIT_PROMOTED,
        workspace.id,
        {"file_id": "f-2"},
        db=db_session,
    )

    assert result[0]["status"] == "simulated"
    run = db_session.query(Run).one()
    assert run.workspace_id == system.workspace_id
    assert run.system_id == system.id
    assert run.capability_id == system.capability_id
