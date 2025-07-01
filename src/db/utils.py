import functools
import logging
import os
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session

from configuration import get_database_config

logger = logging.getLogger(__name__)

Base = declarative_base()


@lru_cache(maxsize=None)
def get_engine():
    db_url = get_database_config().url

    application_name = get_database_config().application_name
    if application_name is not None:
        if get_database_config().application_name_append_pid:
            application_name += f"_PID_{os.getpid()}"
        db_url += f"?application_name={application_name}"

    pool_size = get_database_config().pool_size
    max_overflow = get_database_config().max_overflow

    try:
        return create_engine(db_url, pool_size=pool_size, max_overflow=max_overflow)
    except Exception:
        logger.error(
            f"Error while creating the engine with url: {db_url} "
            f"coming from config: {get_database_config()}"
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
