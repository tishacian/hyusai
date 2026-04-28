from common_config.base import BaseConfig
from pydantic import Field

from configurations.components.api_client import APIClientConfig
from configurations.components.auth import AuthConfig
from configurations.components.logging import CustomLoggingConfig
from configurations.components.streamlit import StreamlitConfig
from configurations.components.ui import UIConfig


class FrontendConfig(BaseConfig):
    logging: CustomLoggingConfig = Field(default_factory=CustomLoggingConfig)
    server: StreamlitConfig = Field(default_factory=StreamlitConfig)
    api: APIClientConfig = Field(default_factory=APIClientConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
