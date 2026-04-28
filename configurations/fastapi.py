from pydantic import Field

from configurations.components.server import ServerConfig
from configurations.shared import BackendConfig


class FastAPIConfig(BackendConfig):
    server: ServerConfig = Field(default_factory=ServerConfig)
