import sys
import traceback

from fastapi.responses import JSONResponse

from configurations import FastAPIConfig


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

    Returns
    -------
    str
        The formatted traceback as a string.
    """
    if exc is None:
        exc = sys.exception()

    if FastAPIConfig.get().logging.limit_traceback_size is True:
        limit = limit_on_prod_env
        chain = False  # if we limit the traceback, we don't want to show the context
    else:
        limit = None
        chain = True

    return "\n".join(traceback.format_exception(exc, limit=limit, chain=chain))


def prepare_json_response(task_id: str, status_code=200):
    """Prepare a JSON response with the given task ID and status code.

    Parameters
    ----------
    task_id : str
        The task ID to include in the response.
    status_code : int, optional
        The HTTP status code for the response, by default 200.

    Returns
    -------
    JSONResponse
        A JSON response containing the task ID and the specified status code.
    """
    return JSONResponse(
        content={"task_id": task_id},
        status_code=status_code,
        media_type="application/json",
    )
