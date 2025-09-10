from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from configuration.subconfigs.standalone_interface import StandaloneInterfaceConfig


class StandaloneInterfaceAppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="papai_llm_front_", env_nested_delimiter="__"
    )

    standalone_interface: StandaloneInterfaceConfig = Field(
        default_factory=StandaloneInterfaceConfig
    )
