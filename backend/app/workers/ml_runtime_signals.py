"""Heartbeat of a model-family worker: "this runtime is listening on these queues".

Started when the worker is ready and stopped when it shuts down, from a daemon
thread so a slow database never delays a task. Only a worker whose
``ml_runtime`` names a family image beats: the general worker has always
trained the tabular family and is never made to prove it is there.
"""

from __future__ import annotations

import os
import threading

from celery.signals import worker_ready, worker_shutdown

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_stop = threading.Event()


def consumed_queues() -> list[str]:
    """The queues this worker was started on (``run_celery.sh`` passes ``-Q``)."""

    return [queue.strip() for queue in os.environ.get("CELERY_QUEUES", "").split(",") if queue.strip()]


def beat_once() -> None:
    from app.db.base import SessionLocal
    from app.services.ml.runtime import beat

    with SessionLocal() as db:
        beat(db, queues=consumed_queues())
        db.commit()


def _loop() -> None:
    while not _stop.is_set():
        try:
            beat_once()
        except Exception as exc:  # noqa: BLE001 - a missed beat only ages the row
            logger.warning("ml runtime heartbeat failed", error=str(exc))
        _stop.wait(float(settings.ml_runtime_heartbeat_s))


@worker_ready.connect
def start_heartbeat(**_: object) -> None:
    if settings.ml_runtime == "worker":
        return
    _stop.clear()
    threading.Thread(target=_loop, name="ml-runtime-heartbeat", daemon=True).start()
    logger.info("ml runtime heartbeat started", runtime=settings.ml_runtime, queues=consumed_queues())


@worker_shutdown.connect
def stop_heartbeat(**_: object) -> None:
    _stop.set()
