from __future__ import annotations

import json
from uuid import uuid4

from app.models.capability import Capability
from app.models.context import Context
from app.models.expert_capture import ExpertCaptureEvent, ExpertCaptureSession
from app.models.run import Run
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace
from scripts.audit_persisted_system_bindings import audit_persisted_system_bindings


def _workspace(db, slug: str, settings: dict | None = None) -> Workspace:
    row = Workspace(
        id=str(uuid4()),
        name=slug,
        slug=slug,
        settings=settings or {},
    )
    db.add(row)
    db.flush()
    return row


def _global_binding(db, suffix: str, *, tier: str, industry: str) -> Capability:
    skill = Skill(
        id=str(uuid4()),
        slug=f"{suffix}-skill",
        name=f"{suffix} skill",
        workspace_id=None,
    )
    capability = Capability(
        id=str(uuid4()),
        slug=f"{suffix}-capability",
        name=f"{suffix} capability",
        workspace_id=None,
        tier=tier,
        industry=industry,
        skill_ids=[skill.id],
    )
    db.add_all([skill, capability])
    db.flush()
    return capability


def test_runtime_audit_accepts_persisted_client_and_foreign_industry_bindings(
    db_session,
) -> None:
    workspace = _workspace(db_session, "andritz", {"family": "andritz"})
    client = _global_binding(
        db_session,
        "client360",
        tier="client",
        industry="industrial_nonwovens",
    )
    news = _global_binding(
        db_session,
        "news-lab",
        tier="industry",
        industry="finance",
    )
    db_session.add_all(
        [
            System(
                id=str(uuid4()),
                workspace_id=workspace.id,
                name="Client360",
                capability_id=client.id,
                status="active",
            ),
            System(
                id=str(uuid4()),
                workspace_id=workspace.id,
                name="News Lab",
                capability_id=news.id,
                status="active",
            ),
        ]
    )
    db_session.commit()

    report = audit_persisted_system_bindings(
        db_session,
        workspace_slugs=[workspace.slug],
    )

    assert report["result"] == "passed"
    assert report["system_count"] == 2
    assert report["failed_system_count"] == 0
    assert {row["effective_skill_count"] for row in report["systems"]} == {1}
    assert report["expert_capture_system_workspace_mismatch_count"] == 0


def test_runtime_audit_fails_closed_on_explicit_disable_and_cross_tenant_skill(
    db_session,
) -> None:
    workspace = _workspace(db_session, "andritz", {"family": "andritz"})
    other = _workspace(db_session, "other")
    capability = _global_binding(
        db_session,
        "client360-hidden",
        tier="client",
        industry="industrial_nonwovens",
    )
    other_skill = Skill(
        id=str(uuid4()),
        slug="other-private-skill",
        name="Other private skill",
        workspace_id=other.id,
    )
    disabled = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Disabled binding",
        capability_id=capability.id,
        status="active",
    )
    cross_tenant = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Cross tenant binding",
        skill_ids=[other_skill.id],
        status="active",
    )
    db_session.add_all([other_skill, disabled, cross_tenant])
    db_session.flush()
    workspace.settings = {
        "family": "andritz",
        "catalog": {"hidden_capabilities": [capability.slug]},
    }
    db_session.commit()

    report = audit_persisted_system_bindings(
        db_session,
        workspace_slugs=[workspace.slug],
    )

    assert report["result"] == "failed"
    assert report["failed_system_count"] == 2
    assert {row["code"] for row in report["systems"]} == {
        "capability_not_visible",
        "skill_not_visible",
    }


def test_runtime_audit_reports_missing_requested_workspace(db_session) -> None:
    report = audit_persisted_system_bindings(
        db_session,
        workspace_slugs=["missing-workspace"],
    )

    assert report["result"] == "failed"
    assert report["missing_workspace_slugs"] == ["missing-workspace"]
    assert report["systems"] == []


def test_runtime_audit_fails_closed_on_cross_workspace_expert_capture_system(
    db_session,
) -> None:
    source = _workspace(db_session, "capture-source")
    target = _workspace(db_session, "andritz", {"family": "andritz"})
    system = System(
        id=str(uuid4()),
        workspace_id=target.id,
        name="Andritz target",
        status="active",
    )
    context = Context(
        id=str(uuid4()),
        workspace_id=source.id,
        name="Source context must remain private",
    )
    run = Run(
        id=str(uuid4()),
        workspace_id=source.id,
        system_id=None,
        status="completed",
    )
    session = ExpertCaptureSession(
        id=str(uuid4()),
        workspace_id=source.id,
        system_id=system.id,
        capability_id=str(uuid4()),
        context_id=context.id,
        run_id=run.id,
        title="Cross-workspace fixture",
        objective="Verify fail-closed lineage",
    )
    event = ExpertCaptureEvent(
        id=str(uuid4()),
        workspace_id=source.id,
        session_id=session.id,
        event_type="answer",
        text_raw="Sensitive content must never enter the audit report",
    )
    db_session.add_all([system, context, run, session, event])
    db_session.commit()

    report = audit_persisted_system_bindings(db_session)

    assert report["result"] == "failed"
    assert report["schema_version"] == 2
    assert report["expert_capture_system_workspace_mismatch_count"] == 1
    assert report["expert_capture_system_workspace_mismatch_details_truncated"] is False
    assert report["expert_capture_system_workspace_mismatch_detail_limit"] == 100
    assert report["expert_capture_system_workspace_mismatches"] == [
        {
            "session_id": session.id,
            "session_workspace_id": source.id,
            "system_id": system.id,
            "system_workspace_id": target.id,
            "status": "planned",
            "run_workspace_relation": "same_workspace",
            "run_system_relation": "run_not_system_bound",
            "capability_workspace_relation": "missing",
            "context_workspace_relation": "same_workspace",
            "event_count": 1,
            "proposal_count": 0,
        }
    ]
    rendered = json.dumps(report, sort_keys=True)
    assert "Sensitive content" not in rendered
    assert "Cross-workspace fixture" not in rendered
    assert "Verify fail-closed lineage" not in rendered


def test_runtime_audit_bounds_cross_workspace_capture_details(db_session) -> None:
    source = _workspace(db_session, "capture-source")
    target = _workspace(db_session, "capture-target")
    system = System(
        id=str(uuid4()),
        workspace_id=target.id,
        name="Target",
        status="active",
    )
    db_session.add(system)
    db_session.flush()
    for index in range(101):
        db_session.add(
            ExpertCaptureSession(
                id=f"{index:032d}"[-32:],
                workspace_id=source.id,
                system_id=system.id,
                title="Bounded fixture",
                objective="Bound mismatch evidence",
            )
        )
    db_session.commit()

    report = audit_persisted_system_bindings(db_session)

    assert report["expert_capture_system_workspace_mismatch_count"] == 101
    assert len(report["expert_capture_system_workspace_mismatches"]) == 100
    assert report["expert_capture_system_workspace_mismatch_details_truncated"] is True
