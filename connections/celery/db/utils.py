import functools
import logging
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from configurations import BackendConfig

logger = logging.getLogger(__name__)


@lru_cache(maxsize=None)
def get_engine():
    db_url = BackendConfig.get().celery_result.url

    try:
        return create_engine(db_url)
    except Exception:
        logger.error(
            f"Error while creating the engine with url: {db_url} "
            f"coming from config: {BackendConfig.get().celery_result}"
        )
        raise


def session_manager_decorator(func):
    """
    Decorator that ensures a SQLAlchemy session is available to the wrapped function.

    If a session is explicitly provided via the `session` keyword argument, it will be used as-is.
    Otherwise, a new session will be created, passed to the function, and committed automatically
    after execution.

    This is useful for simplifying functions that interact with the database by removing the need
    to manually manage session lifecycle in each call.
    """

    @functools.wraps(func)
    def wrapper(arg, *args, session=None, **kwargs):
        if isinstance(session, Session):
            return func(arg, *args, session=session, **kwargs)
        engine = get_engine()
        with Session(engine, expire_on_commit=False) as session:
            res = func(arg, *args, session=session, **kwargs)
            session.commit()
            return res

    return wrapper
