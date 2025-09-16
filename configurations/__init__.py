from functools import lru_cache

from .celery_app import CeleryAppConfig
from .fastapi_app import FastapiAppConfig
from .standalone_interface_app import StandaloneInterfaceAppConfig


@lru_cache(maxsize=None)
def back_conf():
    return CeleryAppConfig()


@lru_cache(maxsize=None)
def rout_conf():
    return FastapiAppConfig()


@lru_cache(maxsize=None)
def front_conf():
    return StandaloneInterfaceAppConfig()
