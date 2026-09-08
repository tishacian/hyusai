"""Showcase activity backfill: determinism, rhythm, flags, basis linkage, replay."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import hypervisor
from app.api.v1.endpoints.capabilities import serialize_value_basis
from app.models.capability import Capability
from app.models.decision import Decision
from app.models.evaluation import EvaluationScore
from app.models.evaluation_feedback import EvaluationFeedback
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from scripts import seed_showcase_workspace as showcase_seed
from scripts import showcase_activity as activity

NOW = datetime(2026, 9, 8, 14, 30)  # a Tuesday, mid office hours
BASIS_SYSTEMS = set(showcase_seed.SHOWCASE_VALUE_BASES_BY_SYSTEM)
NO_BASIS_SYSTEMS = {"Contract Risk Copilot", "Compliance Review Loop", "Translation Suite"}


def _seed_workspace(db_session, *, slug: str = "showcase-activity", tender_slug: str = "showcase_tender_response"):
    workspace = Workspace(id=f"ws-{slug}", slug=slug, name=slug, settings={"showcase_seed": True})
    user = User(id=f"user-{slug}", username=slug, email=f"{slug}@example.test")
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="admin",
        role_template="workspace_admin",
    )
    db_session.add_all([workspace, user, member])
    capability_slugs = {
        "Knowledge Capture": showcase_seed.CAPTURE_CAPABILITY_SLUG,
        "Tender Response Analyst": tender_slug,
        "Contract Risk Copilot": "video_contract_risk",
        "SAP HANA Maintenance Copilot": "showcase_hana_maintenance",
        "Compliance Review Loop": "showcase_compliance_loop",
        "Translation Suite": "showcase_translation_suite",
    }
    systems: dict[str, System] = {}
    for profile in activity.PROFILES:
        cap_slug = capability_slugs[profile.system_name]
        if slug != "showcase-activity":
            cap_slug = f"{slug}-{cap_slug}"  # Capability.slug is globally unique
        capability = Capability(
            id=f"cap-{slug}-{cap_slug}",
            workspace_id=workspace.id,
            slug=cap_slug,
            name=cap_slug,
            tier="client",
            output_unit=profile.question_type,
            pricing={"unit": "per_outcome", "unit_price": 1.0, "currency": "EUR"},
            value_per_outcome=10.0,
        )
        system = System(
            id=f"sys-{slug}-{cap_slug}",
            workspace_id=workspace.id,
            capability_id=capability.id,
            name=profile.system_name,
            status="active",
        )
        db_session.add_all([capability, system])
        systems[profile.system_name] = system
    db_session.commit()
    return {"workspace": workspace, "user": user, "systems": systems}


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(hypervisor.router, prefix="/hypervisor")
    app.dependency_overrides[hypervisor.get_current_workspace] = lambda: workspace
    app.dependency_overrides[hypervisor.get_current_user] = lambda: user
    app.dependency_overrides[hypervisor.get_db] = lambda: db_session
    return TestClient(app)


# --- plan (pure, no database) -------------------------------------------------


def test_plan_is_deterministic_for_a_fixed_seed():
    first = activity.plan_activity(now=NOW)
    second = activity.plan_activity(now=NOW)
    assert first == second
    assert first != activity.plan_activity(now=NOW, seed=activity.DEFAULT_SEED + 1)


def test_plan_covers_the_window_with_weekday_rhythm_and_target_volume():
    plan = activity.plan_activity(now=NOW)
    window_start = NOW.date() - timedelta(days=activity.DEFAULT_WINDOW_DAYS - 1)
    portfolio: dict = {}
    for per_day in plan.counts.values():
        for day, count in per_day.items():
            assert window_start <= day <= NOW.date()
            portfolio[day] = portfolio.get(day, 0) + count
    assert len(portfolio) == activity.DEFAULT_WINDOW_DAYS
    weekdays = [total for day, total in portfolio.items() if day.weekday() < 5]
    weekends = [total for day, total in portfolio.items() if day.weekday() >= 5]
    weekday_rate = sum(weekdays) / len(weekdays)
    weekend_rate = sum(weekends) / len(weekends)
    assert 35 <= weekday_rate <= 60
    assert 0.1 <= weekend_rate / weekday_rate <= 0.35
    assert 3_000 <= plan.total() <= 4_500
    # Every profile ranks as designed: high, medium, low volume.
    ordered = sorted(plan.counts, key=plan.total, reverse=True)
    assert ordered[:2] == ["Knowledge Capture", "Tender Response Analyst"]
    assert ordered[-1] == "Translation Suite"


def test_plan_has_one_visible_peak_weekday_inside_the_last_30_days():
    plan = activity.plan_activity(now=NOW)
    assert plan.peak_day.weekday() < 5
    assert NOW.date() - timedelta(days=30) < plan.peak_day < NOW.date()
    portfolio = {}
    for per_day in plan.counts.values():
        for day, count in per_day.items():
            portfolio[day] = portfolio.get(day, 0) + count
    recent = {day: total for day, total in portfolio.items() if day > NOW.date() - timedelta(days=30)}
    assert max(recent, key=recent.get) == plan.peak_day


def test_plan_keeps_the_stale_system_quiet_only_in_its_stale_tail():
    plan = activity.plan_activity(now=NOW)
    stale = plan.counts[activity.DEFAULT_STALE_SYSTEM]
    cutoff = NOW.date() - timedelta(days=activity.DEFAULT_STALE_DAYS - 1)
    assert all(count == 0 for day, count in stale.items() if day >= cutoff)
    assert sum(count for day, count in stale.items() if day < cutoff) > 0
    for name, per_day in plan.counts.items():
        if name != activity.DEFAULT_STALE_SYSTEM:
            assert sum(count for day, count in per_day.items() if day >= cutoff) > 0


def test_plan_honours_window_volume_and_stale_parameters():
    plan = activity.plan_activity(
        now=NOW, window_days=14, volume_scale=0.5, stale_system="Translation Suite", stale_days=7
    )
    assert plan.window_start == NOW.date() - timedelta(days=13)
    assert all(len(per_day) == 14 for per_day in plan.counts.values())
    assert plan.total() < activity.plan_activity(now=NOW, window_days=14).total()
    assert sum(list(plan.counts["Translation Suite"].values())[-7:]) == 0
    assert sum(plan.counts[activity.DEFAULT_STALE_SYSTEM].values()) > 0


# --- persistence --------------------------------------------------------------


def test_backfill_flags_costs_and_outcomes_on_every_run(db_session):
    seeded = _seed_workspace(db_session)
    summary = activity.backfill_showcase_activity(
        db_session, seeded["workspace"], seeded["systems"], now=NOW, window_days=21, log=lambda _: None
    )
    db_session.commit()
    plan = activity.plan_activity(now=NOW, window_days=21)
    assert summary["created_runs"] == plan.total() > 0
    assert summary["skipped_systems"] == []

    runs = db_session.query(Run).filter(Run.workspace_id == seeded["workspace"].id).all()
    scores = {
        score.run_id: score
        for score in db_session.query(EvaluationScore)
        .filter(EvaluationScore.workspace_id == seeded["workspace"].id)
        .all()
    }
    assert len(runs) == len(scores) == plan.total()
    for run in runs:
        assert run.input_ref["showcase_seed"] is True
        assert run.input_ref["evidence_kind"] == "synthetic_demo"
        assert run.input_ref[activity.ACTIVITY_MARKER] is True
        assert run.status == "completed"
        assert run.cost_internal is not None and run.cost_internal > 0
        assert run.decision in activity.DECISIONS
        assert run.started_at <= run.completed_at <= NOW
        assert activity.OFFICE_START <= run.started_at.time() <= activity.OFFICE_END
        assert scores[run.id].metadata_["showcase_seed"] is True
        assert scores[run.id].metadata_[activity.ACTIVITY_MARKER] is True

    outcomes = [run for run in runs if run.decision in hypervisor.OUTCOME_DECISIONS]
    assert len(outcomes) > 0.6 * len(runs)
    bucket = hypervisor._bucket_metrics(runs, output_unit="answer", hours_per_unit=0.5, value_per_unit=12.0)
    assert bucket["outcomes"]["value"] == len(outcomes)
    assert bucket["hours"] == {"state": "available", "value": 0.5 * len(outcomes)}
    assert bucket["cost"]["state"] == "available"
    assert bucket["cost"]["value"] == sum(run.cost_internal for run in runs)


def test_series_lists_every_system_with_daily_buckets_three_converting_one_stale(db_session, monkeypatch):
    seeded = _seed_workspace(db_session)
    applied = showcase_seed.apply_showcase_value_bases(db_session, seeded["workspace"])
    assert set(applied) == BASIS_SYSTEMS and None not in applied.values()
    activity.backfill_showcase_activity(
        db_session, seeded["workspace"], seeded["systems"], now=NOW, window_days=45, log=lambda _: None
    )
    db_session.commit()

    class _FrozenDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return NOW

    monkeypatch.setattr(hypervisor, "datetime", _FrozenDatetime)
    payload = _client(db_session, seeded["workspace"], seeded["user"]).get(
        "/hypervisor/series", params={"window": "30d"}
    ).json()
    by_name = {item["name"]: item for item in payload["systems"]}
    assert set(by_name) == {profile.system_name for profile in activity.PROFILES}
    for name, item in by_name.items():
        assert len(item["buckets"]) >= 10, name
        states = {bucket["hours"]["state"] for bucket in item["buckets"]}
        assert states == ({"available"} if name in BASIS_SYSTEMS else {"not_configured"}), name
        assert all(bucket["cost"]["state"] == "available" for bucket in item["buckets"])
    stale = by_name[activity.DEFAULT_STALE_SYSTEM]["days_since_last_run"]
    assert stale["state"] == "available" and stale["value"] >= activity.DEFAULT_STALE_DAYS - 1
    assert all(
        by_name[name]["days_since_last_run"]["value"] <= 3
        for name in by_name
        if name != activity.DEFAULT_STALE_SYSTEM
    )


def test_value_bases_attach_to_the_capability_each_system_references(db_session):
    # Reproduces the VM: the video seed re-pointed Tender Response Analyst to
    # `video_tender_response`; a basis written on `showcase_tender_response`
    # by slug converts nothing because the series joins System.capability_id.
    seeded = _seed_workspace(db_session, tender_slug="video_tender_response")
    orphan = Capability(
        id="cap-orphan-tender",
        workspace_id=seeded["workspace"].id,
        slug="showcase_tender_response",
        name="orphan",
        tier="client",
        value_basis=dict(showcase_seed.TENDER_VALUE_BASIS),
    )
    db_session.add(orphan)
    db_session.commit()

    applied = showcase_seed.apply_showcase_value_bases(db_session, seeded["workspace"])
    assert applied["Tender Response Analyst"] == "video_tender_response"

    for name in BASIS_SYSTEMS:
        system = db_session.query(System).filter(System.name == name).one()
        capability = db_session.get(Capability, system.capability_id)  # the series join
        basis = serialize_value_basis(
            capability.value_basis, default_unit=capability.output_unit, default_currency="EUR"
        )
        assert hypervisor._hours_per_unit(basis) is not None, name
        assert hypervisor._value_per_unit(basis) is not None, name
        assert basis["currency"] == "EUR" and basis["status"] == "declared"
        assert capability.value_per_outcome == basis["value_per_unit"]
    for name in NO_BASIS_SYSTEMS:
        system = db_session.query(System).filter(System.name == name).one()
        assert db_session.get(Capability, system.capability_id).value_basis is None


def test_double_replay_keeps_run_counts_equal_and_only_touches_its_own_rows(db_session):
    seeded = _seed_workspace(db_session)
    other = _seed_workspace(db_session, slug="other-workspace")
    workspace = seeded["workspace"]
    story_run = Run(
        id="story-run",
        workspace_id=workspace.id,
        system_id=seeded["systems"]["Contract Risk Copilot"].id,
        status="completed",
        trigger="chat",
        decision="answer",
        input_ref={"showcase_seed": True, "evidence_kind": "synthetic_demo"},
        started_at=NOW - timedelta(days=1),
        completed_at=NOW - timedelta(days=1),
    )
    db_session.add(story_run)
    db_session.commit()

    first = activity.backfill_showcase_activity(
        db_session, workspace, seeded["systems"], now=NOW, window_days=14, log=lambda _: None
    )
    other_summary = activity.backfill_showcase_activity(
        db_session, other["workspace"], other["systems"], now=NOW, window_days=14, log=lambda _: None
    )
    db_session.commit()
    first_ids = {
        run_id
        for (run_id,) in db_session.query(Run.id).filter(Run.workspace_id == workspace.id).all()
    }
    synthetic_id = next(run_id for run_id in first_ids if run_id != "story-run")
    db_session.add_all(
        [
            EvaluationFeedback(workspace_id=workspace.id, run_id=synthetic_id, label="wrong"),
            Decision(workspace_id=workspace.id, scope="run", target_id=synthetic_id, title="triage"),
            Decision(workspace_id=workspace.id, scope="system", target_id="sys-x", title="keep me"),
        ]
    )
    db_session.commit()

    second = activity.backfill_showcase_activity(
        db_session, workspace, seeded["systems"], now=NOW, window_days=14, log=lambda _: None
    )
    db_session.commit()

    assert first["wiped_runs"] == 0
    assert second["wiped_runs"] == first["created_runs"]
    assert second["created_runs"] == first["created_runs"]
    second_ids = {
        run_id
        for (run_id,) in db_session.query(Run.id).filter(Run.workspace_id == workspace.id).all()
    }
    assert len(second_ids) == len(first_ids)
    assert second_ids & first_ids == {"story-run"}
    assert db_session.query(EvaluationScore).filter(
        EvaluationScore.workspace_id == workspace.id
    ).count() == first["created_runs"]
    assert db_session.query(EvaluationFeedback).filter(
        EvaluationFeedback.workspace_id == workspace.id
    ).count() == 0
    decisions = db_session.query(Decision).filter(Decision.workspace_id == workspace.id).all()
    assert [decision.title for decision in decisions] == ["keep me"]
    assert (
        db_session.query(Run).filter(Run.workspace_id == other["workspace"].id).count()
        == other_summary["created_runs"]
        > 0
    )
