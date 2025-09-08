import sys
import traceback

from configuration import get_general_config


def get_traceback(limit_on_prod_env: int = 0, exc: BaseException | None = None) -> str:
    """Return the traceback of the exception.

    Parameters
    ----------
    limit_on_prod_env : int, optional
        Limit the number of stack it's gonna display. If 0, only the error
        is going to show, by default 0.
    exc : BaseException, optional
        Exception to get the traceback from. If None, will get the exception
        from the context. By default None
    """
    if exc is None:
        exc = sys.exception()

    if get_general_config().limit_traceback_size is True:
        limit = limit_on_prod_env
        chain = False  # if we limit the traceback, we don't want to show the context
    else:
        limit = None
        chain = True

    return "\n".join(traceback.format_exception(exc, limit=limit, chain=chain))
