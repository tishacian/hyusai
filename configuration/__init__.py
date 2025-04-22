from functools import cache

from .backend import Backend
from .general import General
from .standalone_interface import StandaloneInterface


@cache
def get_general_config():
    return General()


@cache
def get_backend_config():
    return Backend()


@cache
def get_standalone_interface_config():
    return StandaloneInterface()
