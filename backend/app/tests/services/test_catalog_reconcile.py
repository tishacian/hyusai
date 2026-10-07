"""The canonical catalog, reconciled explicitly when startup reconciliation is off.

A transactional deployment boots with ``STARTUP_RECONCILIATION=disabled``, so a
release that adds a Skill (ml_forecast_v1 was the first) has to bring the
catalog in line itself. These pin what that reconciliation reports and what it
is allowed to write.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.cli import reconcile_catalog as cli
from app.models.capability import Capability
from app.models.skill import Skill
from app.services.skills_registry import SEED_CAPABILITIES, SEED_SKILLS, reconcile_catalog, seed_skills_and_capabilities


def test_an_empty_catalog_is_reported_behind_and_left_untouched_by_a_check(db_session):
    report = reconcile_catalog(db_session, apply=False)

    assert report["in_sync"] is False and report["applied"] is False
    assert set(report["skills"]["missing"]) == {entry["slug"] for entry in SEED_SKILLS}
    assert set(report["capabilities"]["missing"]) == {entry["slug"] for entry in SEED_CAPABILITIES}
    assert db_session.query(Skill).count() == 0 and db_session.query(Capability).count() == 0


def test_an_apply_brings_it_in_sync_and_a_second_pass_writes_nothing(db_session):
    reconcile_catalog(db_session, apply=True)
    assert reconcile_catalog(db_session, apply=False)["in_sync"] is True

    forecast = db_session.query(Skill).filter_by(slug="ml_forecast_v1").one()
    capability = db_session.query(Capability).filter_by(slug="time_series_models").one()
    assert capability.skill_ids == [forecast.id]

    # The boot seed now counts real changes: an identical catalog is not rewritten.
    stamp = datetime.utcnow() - timedelta(days=3)
    db_session.query(Skill).update({Skill.updated_at: stamp})
    db_session.commit()
    assert seed_skills_and_capabilities(db_session) == {
        "skills_added": 0,
        "skills_updated": 0,
        "capabilities_added": 0,
        "capabilities_updated": 0,
    }
    db_session.expire_all()
    assert db_session.query(Skill).filter(Skill.updated_at > stamp).count() == 0


def test_a_seeded_field_edited_in_production_is_named_and_restored_only_on_apply(db_session):
    reconcile_catalog(db_session, apply=True)
    skill = db_session.query(Skill).filter_by(slug="ml_forecast_v1").one()
    skill.pricing = {"unit": "per_forecast_dataset", "unit_price": 9.0, "currency": "USD"}
    # A field the seed does not own: the platform's, never reported or reverted.
    skill.metrics = {"calls": 12}
    db_session.commit()

    report = reconcile_catalog(db_session, apply=False)
    assert report["in_sync"] is False
    assert report["skills"]["changed"] == {"ml_forecast_v1": ["pricing"]}
    db_session.expire_all()
    assert db_session.query(Skill).filter_by(slug="ml_forecast_v1").one().pricing["unit_price"] == 9.0

    applied = reconcile_catalog(db_session, apply=True)
    assert applied["skills"]["changed"] == {"ml_forecast_v1": ["pricing"]}
    db_session.expire_all()
    restored = db_session.query(Skill).filter_by(slug="ml_forecast_v1").one()
    assert restored.pricing["unit_price"] == 0.0 and restored.metrics == {"calls": 12}


def test_a_seeded_row_the_code_no_longer_declares_is_reported_and_kept(db_session):
    reconcile_catalog(db_session, apply=True)
    db_session.add(Skill(slug="retired_skill_v1", name="Retired", is_seeded="Y"))
    db_session.commit()

    report = reconcile_catalog(db_session, apply=True)
    assert report["skills"]["orphaned"] == ["retired_skill_v1"]
    # A Flow may still reference it: reconciling never deletes.
    assert db_session.query(Skill).filter_by(slug="retired_skill_v1").count() == 1
    assert reconcile_catalog(db_session, apply=False)["in_sync"] is True


def test_the_command_exits_3_when_behind_and_says_what_to_run(monkeypatch, capsys):
    behind = {
        "in_sync": False,
        "applied": False,
        "skills": {"missing": ["ml_forecast_v1"], "changed": {}, "orphaned": []},
        "capabilities": {"missing": ["time_series_models"], "changed": {}, "orphaned": []},
    }
    monkeypatch.setattr("app.services.skills_registry.reconcile_catalog", lambda db, apply: behind)
    assert cli.main([]) == cli.BEHIND
    captured = capsys.readouterr()
    assert '"ml_forecast_v1"' in captured.out
    assert "BEHIND" in captured.err and "catalog-apply" in captured.err

    applied = {**behind, "in_sync": True, "applied": True}
    monkeypatch.setattr("app.services.skills_registry.reconcile_catalog", lambda db, apply: applied)
    assert cli.main(["--apply"]) == 0
    assert "catalog applied: 1 skill(s) missing" in capsys.readouterr().err
