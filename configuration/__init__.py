from functools import cache

from .general import General
from .standalone_interface import StandaloneInterface


@cache
def get_general_config():
    return General()


@cache
def get_standalone_interface_config():
    return StandaloneInterface()
