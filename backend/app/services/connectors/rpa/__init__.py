"""RPA Bridge connector (config, test, generic REST job dispatch)."""

from app.services.connectors.rpa.service import (
    dispatch_and_poll,
    get_config,
    get_job,
    is_workspace_enabled,
    set_config,
    start_job,
    test_connection,
)

__all__ = [
    "dispatch_and_poll",
    "get_config",
    "get_job",
    "is_workspace_enabled",
    "set_config",
    "start_job",
    "test_connection",
]
