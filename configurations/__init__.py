from .celery_app import CeleryAppConfig
from .fastapi_app import FastapiAppConfig
from .standalone_interface_app import StandaloneInterfaceAppConfig


def back_conf():
    return CeleryAppConfig.get()


def rout_conf():
    return FastapiAppConfig.get()


def front_conf():
    return StandaloneInterfaceAppConfig.get()
