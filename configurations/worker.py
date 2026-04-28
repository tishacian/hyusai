from common_config.celery import CeleryEnvConfig
from pydantic import Field

from configurations.components.resources import ResourcesConfig
from configurations.shared import BackendConfig


class WorkerConfig(BackendConfig):
    celery: CeleryEnvConfig = Field(default_factory=CeleryEnvConfig)
    resources: ResourcesConfig = Field(default_factory=ResourcesConfig)
