"""Catalog connectors without a page of their own (config, write-only secrets, test)."""

from app.services.connectors.generic.service import (
    CONNECTORS,
    SETTINGS_KEY,
    clear_config,
    get_config,
    list_configs,
    set_config,
    test_connection,
)

__all__ = [
    "CONNECTORS",
    "SETTINGS_KEY",
    "clear_config",
    "get_config",
    "list_configs",
    "set_config",
    "test_connection",
]
