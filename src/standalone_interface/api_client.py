import httpx

from configurations import FrontendConfig

DEFAULT_TIMEOUT = httpx.Timeout(10.0)
STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=10.0, pool=10.0)


def get_client(timeout: httpx.Timeout = DEFAULT_TIMEOUT) -> httpx.Client:
    """Return a configured httpx.Client pointed at the FastAPI backend."""
    return httpx.Client(
        base_url=FrontendConfig.get().api.url,
        timeout=timeout,
    )
