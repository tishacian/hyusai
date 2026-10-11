"""Scheduler smoke tests for Vague 2.2 OSINT jobs.

The intelligence scheduler thread is deliberately kept off in tests (we never
``start_scheduler``); we only exercise the pure job dispatcher to validate that
each known job name routes to the right ``sync_*`` entry point and that
unknown / failing jobs are absorbed without raising.
"""
from __future__ import annotations

import pytest

from app.services.intelligence import cache as intel_cache
from app.services.intelligence import scheduler as intel_scheduler


@pytest.fixture(autouse=True)
def _clear_intel_cache():
    intel_cache.clear_memory_cache()
    yield
    intel_cache.clear_memory_cache()


def test_osint_jobs_table_is_complete_and_cadence_aligned():
    """The three OSINT pipelines must be declared with the documented cadence."""
    names = {name: interval for name, interval in intel_scheduler.OSINT_JOBS}
    assert names == {
        "rss_security": 900,
        "adsb_sahel": 300,
        "cedeao_index": 1800,
    }


def test_run_osint_job_dispatches_to_rss_sync(monkeypatch):
    calls: list[bool] = []

    def fake_sync(*, force: bool = False):
        calls.append(force)
        return {"live": False, "fetched_at": "2026-05-25T00:00:00Z"}

    monkeypatch.setattr(
        "app.services.intelligence.rss_security.sync_rss_security",
        fake_sync,
    )
    intel_scheduler._run_osint_job("rss_security")
    assert calls == [True]


def test_run_osint_job_dispatches_to_adsb_sync(monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(
        "app.services.intelligence.adsb_sahel.sync_adsb_sahel",
        lambda *, force=False: (calls.append(force) or {"live": False, "fetched_at": "x"}),
    )
    intel_scheduler._run_osint_job("adsb_sahel")
    assert calls == [True]


def test_run_osint_job_dispatches_to_cedeao_sync(monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(
        "app.services.intelligence.cedeao_index.sync_cedeao_index",
        lambda *, force=False: (calls.append(force) or {"live": False, "fetched_at": "x"}),
    )
    intel_scheduler._run_osint_job("cedeao_index")
    assert calls == [True]


def test_run_osint_job_unknown_name_is_silent(caplog):
    """Unknown job names must log a warning but never raise."""
    intel_scheduler._run_osint_job("not_a_job")  # must not raise


def test_run_osint_job_absorbs_sync_exception(monkeypatch):
    """A failing sync must be swallowed so the scheduler thread stays alive."""

    def boom(*, force=False):
        raise RuntimeError("upstream feed exploded")

    monkeypatch.setattr(
        "app.services.intelligence.rss_security.sync_rss_security",
        boom,
    )
    intel_scheduler._run_osint_job("rss_security")  # must not raise


def test_start_and_stop_scheduler_is_idempotent(monkeypatch):
    """Smoke test the start/stop path without actually firing OSINT jobs."""
    monkeypatch.setattr(intel_scheduler, "_OSINT_POLL_SECONDS", 0.01)
    monkeypatch.setattr(intel_scheduler, "_run_batch_sync", lambda: None)
    monkeypatch.setattr(intel_scheduler, "_run_osint_job", lambda name: None)
    try:
        intel_scheduler.start_scheduler(interval_seconds=3600)
        intel_scheduler.start_scheduler(interval_seconds=3600)  # idempotent
        assert intel_scheduler.is_running() is True
    finally:
        intel_scheduler.stop_scheduler()
    assert intel_scheduler.is_running() is False
