from functools import cache

from .backend import BackendConfig
from .database import DatabaseConfig
from .general import GeneralConfig
from .standalone_interface import StandaloneInterfaceConfig


@cache
def get_general_config():
    return GeneralConfig()


@cache
def get_backend_config():
    return BackendConfig()


@cache
def get_database_config():
    return DatabaseConfig()


@cache
def get_standalone_interface_config():
    return StandaloneInterfaceConfig()
