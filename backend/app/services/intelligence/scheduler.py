"""Background scheduler for periodic RSS intelligence batch runs."""
import asyncio
import threading
from datetime import datetime

from app.core.logging import get_logger

logger = get_logger(__name__)

_scheduler_started = False
_stop_event = threading.Event()
_thread = None

DEFAULT_INTERVAL_SECONDS = 43200  # 12 hours


def _run_batch_sync():
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
    except Exception as e:
        logger.error(f"Scheduled batch exception: {e}")
    finally:
        loop.close()


def _scheduler_loop(interval_seconds: int):
    """Thread target: sleep then run batch, repeat until stop."""
    logger.info("Intelligence scheduler started", interval=interval_seconds)
    while not _stop_event.is_set():
        _stop_event.wait(interval_seconds)
        if _stop_event.is_set():
            break
        logger.info("Triggering scheduled intelligence batch")
        try:
            _run_batch_sync()
        except Exception as e:
            logger.error(f"Scheduler iteration failed: {e}")
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
