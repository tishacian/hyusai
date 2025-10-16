import logging
from contextvars import ContextVar
from time import perf_counter

from asgi_correlation_id.extensions.celery import (
    load_celery_current_and_parent_ids,
    load_correlation_ids,
)
from celery.signals import (
    after_task_publish,
    task_failure,
    task_postrun,
    task_prerun,
    task_received,
    worker_ready,
    worker_shutdown,
)
from celery.worker.request import Request

from configurations import Config
from connections.celery.db.celery_task_links import CeleryTaskLinks, LinkType

logger = logging.getLogger("papai")

task_start_chrono: ContextVar[float] = ContextVar("task_start_chrono")


## Worker Signals


@worker_ready.connect
def create_readiness_file_on_worker_ready(**_):
    Config.get().celery.readiness_file_path.touch()


@worker_shutdown.connect
def remove_readiness_file_on_worker_shutdown(**_):
    Config.get().celery.readiness_file_path.unlink(missing_ok=True)


## Task Signals

# asgi-correlation signals
load_correlation_ids()
load_celery_current_and_parent_ids()


@after_task_publish.connect
def log_task_published(**_):
    logger.debug("Celery task published.")


@task_prerun.connect
def start_chrono(**_) -> None:
    task_start_chrono.set(perf_counter())


@task_postrun.connect
def log_task_postrun(**_) -> None:
    """from asgi-correlation-id library"""
    task_start = task_start_chrono.get()
    task_duration = perf_counter() - task_start
    logger.info(f"Processing time: {task_duration:.6f} seconds")


@task_received.connect
def log_task_received(request: Request, **_):
    logger.debug(f"Celery task {request.task_id} received for {request.task_name}")


@task_failure.connect
def log_task_failure(task_id: str, exception: Exception, **_):
    logger.exception(f"Celery task {task_id} failed with exception: {exception}")


@task_received.connect
def register_task_link(request: Request, **_):
    """Automatically register task links in the database when a child task is received
    by the broker.
    """
    # get the parent_id set by celery for canvas tasks
    parent_id = getattr(request, "parent_id", None)
    task_id = getattr(request, "task_id", None)
    if not parent_id:
        # skip root tasks
        return
    if getattr(request, "chord", False):
        link_type = LinkType.chord
    elif getattr(request, "group", False):
        link_type = LinkType.group
    elif getattr(request, "chain", False):
        link_type = LinkType.chain
    elif getattr(request, "errbacks", False):
        link_type = LinkType.link_error
    else:
        link_type = LinkType.link
    CeleryTaskLinks.add_link(
        parent_task_id=parent_id, child_task_id=task_id, link_type=link_type
    )
