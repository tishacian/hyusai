"""Background scheduler for periodic RSS intelligence batch runs and OSINT security jobs."""
from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime

from app.core.logging import get_logger

logger = get_logger(__name__)

_scheduler_started = False
_stop_event = threading.Event()
_thread = None

DEFAULT_INTERVAL_SECONDS = 43200  # 12 hours
_OSINT_POLL_SECONDS = 30

OSINT_JOBS: tuple[tuple[str, int], ...] = (
    ("rss_security", 900),
    ("adsb_sahel", 300),
    ("cedeao_index", 1800),
)


def _run_batch_sync() -> None:
    """Run the async batch in a new event loop (for the background thread)."""
    from app.services.intelligence.batch import run_batch

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        async def consume():
            count = 0
            async for event in run_batch():
                if event.get("type") == "batch_complete":
                    count = event.get("analyzed", 0)
                elif event.get("type") == "batch_error":
                    logger.warning("Scheduled batch error", error=event.get("message"))
                    return
            logger.info("Scheduled batch completed", analyzed=count, time=datetime.utcnow().isoformat())

        loop.run_until_complete(consume())
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Scheduled batch exception: {exc}")
    finally:
        loop.close()


def _run_osint_job(name: str) -> None:
    try:
        if name == "rss_security":
            from app.services.intelligence.rss_security import sync_rss_security

            payload = sync_rss_security(force=True)
        elif name == "adsb_sahel":
            from app.services.intelligence.adsb_sahel import sync_adsb_sahel

            payload = sync_adsb_sahel(force=True)
        elif name == "cedeao_index":
            from app.services.intelligence.cedeao_index import sync_cedeao_index

            payload = sync_cedeao_index(force=True)
        else:
            logger.warning("Scheduled OSINT job unknown", job=name)
            return
        logger.info(
            "Scheduled OSINT job completed",
            job=name,
            live=bool(payload.get("live")),
            fetched_at=payload.get("fetched_at"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Scheduled OSINT job failed", job=name, error=str(exc))


def _scheduler_loop(batch_interval_seconds: int):
    """Thread target: run RSS batch + OSINT security jobs until stop."""
    logger.info(
        "Intelligence scheduler started",
        batch_interval=batch_interval_seconds,
        osint_jobs=[job[0] for job in OSINT_JOBS],
    )
    next_batch_at = time.time()
    next_osint_at = {name: time.time() for name, _ in OSINT_JOBS}
    while not _stop_event.is_set():
        now = time.time()
        if now >= next_batch_at:
            logger.info("Triggering scheduled intelligence batch")
            try:
                _run_batch_sync()
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Scheduler batch iteration failed: {exc}")
            next_batch_at = now + batch_interval_seconds

        for name, interval in OSINT_JOBS:
            if now >= next_osint_at[name]:
                logger.info("Triggering scheduled OSINT job", job=name)
                _run_osint_job(name)
                next_osint_at[name] = now + interval

        _stop_event.wait(_OSINT_POLL_SECONDS)
    logger.info("Intelligence scheduler stopped")


def start_scheduler(interval_seconds: int = DEFAULT_INTERVAL_SECONDS):
    """Start the background scheduler thread (idempotent)."""
    global _scheduler_started, _thread
    if _scheduler_started:
        return
    _stop_event.clear()
    _thread = threading.Thread(
        target=_scheduler_loop,
        args=(interval_seconds,),
        daemon=True,
        name="intel-scheduler",
    )
    _thread.start()
    _scheduler_started = True
    logger.info("Intelligence scheduler thread launched", interval=interval_seconds)


def stop_scheduler():
    """Stop the background scheduler."""
    global _scheduler_started
    _stop_event.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=5)
    _scheduler_started = False


def is_running() -> bool:
    return _scheduler_started and _thread is not None and _thread.is_alive()
