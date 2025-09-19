from typing import overload

from connections.celery.status import CeleryStatuses, CeleryStatusesFinal
from connections.payload_models.core.celery_task_progress import (
    CoreStatuses,
    CoreStatusesFinal,
)

CELERY_STATUSES_TO_CORE_STATUSES: dict[CeleryStatuses, CoreStatuses] = {
    "PENDING": "waiting",
    "STARTED": "running",
    "SUCCESS": "available",
    "FAILURE": "error",
    "REVOKED": "cancelled",
}


@overload
def translate_status_for_core(status: CeleryStatusesFinal) -> CoreStatusesFinal: ...
@overload
def translate_status_for_core(status: CeleryStatuses) -> CoreStatuses: ...


def translate_status_for_core(status):
    return CELERY_STATUSES_TO_CORE_STATUSES[status]


def full_logs_for_task(progress_message: str | None, logs: str | None) -> str:
    """
    Get the full logs of a task.

    Parameters
    ----------
    task_extra : CeleryTaskExtra
        The extra information of the task.

    Returns
    -------
    str
        The full logs of the task.
    """
    if not progress_message:
        progress_message = ""

    return f"{progress_message}\n\n{logs}" if logs else progress_message
