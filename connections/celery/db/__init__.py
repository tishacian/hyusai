from connections.celery.db.base import ResultModelBase
from connections.celery.db.celery_task_links import CeleryTaskLinks
from connections.celery.db.utils import get_engine


def init_celery_db():
    ResultModelBase.metadata.create_all(get_engine())
