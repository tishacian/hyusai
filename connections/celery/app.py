from celery import Celery

from configurations import back_conf
from connections.celery.db.celery_extra_extend_db_backend import ExtraDatabaseBackend

config = back_conf()


class CeleryConfig:
    broker_url = str(config.celery_broker.url)

    task_track_started = True
    task_acks_late = config.celery.acks_late

    task_serializer = "pickle"
    accept_content = ["pickle", "json"]

    result_extended = True

    worker_concurrency = config.celery.worker_concurrency
    worker_prefetch_multiplier = config.celery.worker_prefetch_multiplier
    worker_max_tasks_per_child = config.celery.worker_max_tasks_per_child
    worker_max_memory_per_child = config.celery.worker_max_memory_per_child
    worker_cancel_long_running_tasks_on_connection_loss = True
    worker_pool = "prefork"
    worker_hijack_root_logger = False


app = Celery("tasks", task_cls="connections.celery.custom_task_class:CustomTask")
app._backend = ExtraDatabaseBackend(
    app=app, dburi=str(config.celery_result_backend.url)
)
app.config_from_object(CeleryConfig)
app.autodiscover_tasks(["connections.celery.tasks"])
