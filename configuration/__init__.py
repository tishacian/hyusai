from functools import lru_cache

from .backend import BackendConfig
from .database import DatabaseConfig
from .general import GeneralConfig
from .standalone_interface import StandaloneInterfaceConfig
from .vlm import VLM


@lru_cache(maxsize=None)
def get_general_config():
    return GeneralConfig()


@lru_cache(maxsize=None)
def get_backend_config():
    return BackendConfig()


@lru_cache(maxsize=None)
def get_database_config():
    return DatabaseConfig()


@lru_cache(maxsize=None)
def get_standalone_interface_config():
    return StandaloneInterfaceConfig()


@cache
def get_vlm_config():
    return VLM()
