from __future__ import annotations

import threading

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.workers import p4_maintenance


def test_p4_maintenance_is_disabled_by_default(monkeypatch) -> None:
    for name in (
        "ENABLE_P4_MAINTENANCE",
        "P4_MAINTENANCE_INTERVAL_SECONDS",
        "P4_MAINTENANCE_BATCH_SIZE",
        "P4_MAINTENANCE_LEASE_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    configured = Settings(_env_file=None)

    assert configured.enable_p4_maintenance is False
    assert configured.p4_maintenance_interval_seconds == 5.0
    assert configured.p4_maintenance_batch_size == 50
    assert configured.p4_maintenance_lease_seconds == 60


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("p4_maintenance_interval_seconds", 0),
        ("p4_maintenance_batch_size", 0),
        ("p4_maintenance_lease_seconds", 4),
    ),
)
def test_p4_maintenance_rejects_unbounded_or_invalid_settings(
    name: str,
    value: int,
) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{name: value})


def test_disabled_cycle_does_not_import_or_call_repairs(monkeypatch) -> None:
    monkeypatch.setattr(p4_maintenance.settings, "enable_p4_maintenance", False)

    result = p4_maintenance.run_maintenance_cycle(
        reconcile=lambda **_kwargs: pytest.fail("outbox must remain disabled"),
        expire_hitl=lambda **_kwargs: pytest.fail("watchdog must remain disabled"),
    )

    assert result == {"status": "disabled"}


def test_cycle_is_bounded_and_passes_configured_limits(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(p4_maintenance.settings, "enable_p4_maintenance", True)
    monkeypatch.setattr(p4_maintenance.settings, "p4_maintenance_batch_size", 7)
    monkeypatch.setattr(p4_maintenance.settings, "p4_maintenance_lease_seconds", 19)

    def reconcile(**kwargs):
        calls.append(("outbox", kwargs))
        return {"published": 2}

    def expire_hitl(**kwargs):
        calls.append(("watchdog", kwargs))
        return {"expired": 1}

    result = p4_maintenance.run_maintenance_cycle(
        reconcile=reconcile,
        expire_hitl=expire_hitl,
    )

    assert result == {
        "status": "ok",
        "outbox": {"published": 2},
        "watchdog": {"expired": 1},
    }
    assert calls == [
        ("watchdog", {"batch_size": 7}),
        ("outbox", {"batch_size": 7, "lease_seconds": 19}),
    ]


def test_cycle_runs_watchdog_before_outbox_and_survives_outbox_failure(monkeypatch) -> None:
    monkeypatch.setattr(p4_maintenance.settings, "enable_p4_maintenance", True)
    watchdog_called = False

    def fail_outbox(**_kwargs):
        raise RuntimeError("broker unavailable")

    def expire_hitl(**_kwargs):
        nonlocal watchdog_called
        watchdog_called = True
        return {"expired": 0}

    result = p4_maintenance.run_maintenance_cycle(
        reconcile=fail_outbox,
        expire_hitl=expire_hitl,
    )

    assert watchdog_called is True
    assert result["status"] == "degraded"
    assert result["outbox"] == {"error": "RuntimeError"}


def test_disabled_loop_waits_until_stop_without_running_cycle(monkeypatch) -> None:
    monkeypatch.setattr(p4_maintenance.settings, "enable_p4_maintenance", False)
    stop_event = threading.Event()
    stop_event.set()

    p4_maintenance.run_maintenance_loop(
        stop_event=stop_event,
        cycle=lambda: pytest.fail("disabled runner must not execute a cycle"),
    )


def test_enabled_loop_stops_cleanly_after_current_cycle(monkeypatch) -> None:
    monkeypatch.setattr(p4_maintenance.settings, "enable_p4_maintenance", True)
    monkeypatch.setattr(p4_maintenance.settings, "p4_maintenance_interval_seconds", 1.0)
    stop_event = threading.Event()
    cycles = 0

    def cycle():
        nonlocal cycles
        cycles += 1
        stop_event.set()
        return {"status": "ok"}

    p4_maintenance.run_maintenance_loop(stop_event=stop_event, cycle=cycle)

    assert cycles == 1
