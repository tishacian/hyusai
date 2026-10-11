import logging
from dataclasses import asdict

from celery import Task
from logging_utils.change_logger_level import change_logger_level
from logging_utils.requests import request

from configurations import Config
from connections.celery.status import CeleryStatuses
from connections.celery.utils import full_logs_for_task, translate_status_for_core
from connections.payload_models.core.celery_task_progress import (
    CeleryTaskProgressToCore,
)

STATUS_UPDATE_ENDPOINT = "/api/private/v1/jobs/py-status"
logger = logging.getLogger(__name__)


class CustomTask(Task):
    """A custom Task class that ensures the core is being updated when the task is."""

    last_known_state: CeleryStatuses = "PENDING"
    last_known_progress_message: str | None = None
    last_known_logs: str | None = None

    def update_core(self) -> None:
        assert self.request.id is not None

        payload = CeleryTaskProgressToCore(
            id=self.request.id,
            status=translate_status_for_core(self.last_known_state),
            logs=full_logs_for_task(
                self.last_known_progress_message, self.last_known_logs
            ),
        )
        # temporarily deactivate logs from request logger to avoid flooding the logs
        with change_logger_level("request", logging.ERROR):
            # we don't want to fail the task if core is not reachable
            try:
                url = f"{Config.get().core.base_http_url}{STATUS_UPDATE_ENDPOINT}"
                request("put", url, asdict(payload))
            except Exception:
                logger.error("Failed to send progress to core.")

    def update_state(self, task_id=None, state=None, meta=None, **kwargs):
        update_core = False
        if state:
            self.last_known_state = state
            update_core = True
        if "progress_message" in kwargs:
            self.last_known_progress_message = kwargs["progress_message"]
            update_core = True
        if "logs" in kwargs:
            self.last_known_logs = kwargs["logs"]
            update_core = True

        if update_core:
            self.update_core()

        return super().update_state(task_id, state, meta, **kwargs)

    def update_progress(self, progress_message: str):
        self.update_state(progress_message=progress_message)

    def update_logs(self, logs: str):
        self.update_state(logs=logs)
