from connections.celery.db.base import ResultModelBase

# import as to avoid unused import warnings
from connections.celery.db.celery_task_links import CeleryTaskLinks as CeleryTaskLinks
from connections.celery.db.utils import get_engine


def init_celery_db():
    ResultModelBase.metadata.create_all(get_engine())
