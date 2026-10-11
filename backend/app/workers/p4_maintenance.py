"""Bounded operational loop for P4 outbox repair and HITL expiry.

This process deliberately does not use Celery Beat.  It owns no mutable
in-memory schedule: PostgreSQL rows and coordination leases remain
authoritative, so a restart simply performs another bounded reconciliation.
"""
from __future__ import annotations

import signal
import threading
import time
from collections.abc import Callable
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger, setup_logging

logger = get_logger(__name__)

CycleResult = dict[str, Any]
Reconciler = Callable[..., CycleResult]
Watchdog = Callable[..., CycleResult]


def run_maintenance_cycle(
    *,
    reconcile: Reconciler | None = None,
    expire_hitl: Watchdog | None = None,
) -> CycleResult:
    """Run at most one configured batch for each repair mechanism."""

    if not settings.enable_p4_maintenance:
        return {"status": "disabled"}

    result: CycleResult = {"status": "ok"}
    # Deadlines are authoritative over continuations. Expire/reconcile HITL
    # first so a late approval cannot win merely because an outbox scan ran a
    # few milliseconds before the watchdog in the same maintenance tick.
    try:
        if expire_hitl is None:
            from app.services.run_engine.hitl_watchdog import expire_overdue_hitl_waits

            expire_hitl = expire_overdue_hitl_waits
        result["watchdog"] = expire_hitl(
            batch_size=settings.p4_maintenance_batch_size,
        )
    except Exception as exc:  # noqa: BLE001 - one subsystem must not starve the other
        logger.error("P4 HITL watchdog failed", error_type=type(exc).__name__)
        result["status"] = "degraded"
        result["watchdog"] = {"error": type(exc).__name__}

    try:
        if reconcile is None:
            from app.services.run_engine.dispatch_outbox import reconcile_dispatch_outbox

            reconcile = reconcile_dispatch_outbox
        result["outbox"] = reconcile(
            batch_size=settings.p4_maintenance_batch_size,
            lease_seconds=settings.p4_maintenance_lease_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - next interval retries persisted state
        logger.error("P4 outbox reconciliation failed", error_type=type(exc).__name__)
        result["status"] = "degraded"
        result["outbox"] = {"error": type(exc).__name__}
    return result


def run_maintenance_loop(
    *,
    stop_event: threading.Event | None = None,
    cycle: Callable[[], CycleResult] = run_maintenance_cycle,
) -> None:
    """Run maintenance until SIGTERM/SIGINT requests a clean shutdown."""

    stopper = stop_event or threading.Event()
    if not settings.enable_p4_maintenance:
        logger.info("P4 maintenance disabled", reason="enable_p4_maintenance=false")
        stopper.wait()
        return

    interval = float(settings.p4_maintenance_interval_seconds)
    logger.info(
        "P4 maintenance started",
        interval_seconds=interval,
        batch_size=settings.p4_maintenance_batch_size,
        lease_seconds=settings.p4_maintenance_lease_seconds,
    )
    while not stopper.is_set():
        started = time.monotonic()
        try:
            outcome = cycle()
            logger.debug("P4 maintenance cycle completed", outcome=outcome)
        except Exception as exc:  # noqa: BLE001 - keep the operational loop alive
            logger.error("P4 maintenance cycle crashed", error_type=type(exc).__name__)
        remaining = max(0.0, interval - (time.monotonic() - started))
        stopper.wait(remaining)
    logger.info("P4 maintenance stopped")


def main() -> None:
    setup_logging(settings.log_level)
    stop_event = threading.Event()

    def request_stop(signum: int, _frame: object) -> None:
        logger.info("P4 maintenance shutdown requested", signal=signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    run_maintenance_loop(stop_event=stop_event)


if __name__ == "__main__":
    main()
