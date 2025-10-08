from common_config.base import BaseConfig
from pydantic import Field
from pydantic_settings import SettingsConfigDict

from configurations.subconfigs.standalone_interface import StandaloneInterfaceConfig
from configurations.subconfigs.streamlit import StreamlitConfig
from configurations.subconfigs.uvicorn_client import UvicornClientConfig


class StandaloneInterfaceAppConfig(BaseConfig):
    model_config = SettingsConfigDict(
        env_prefix="papai_llm_front_", env_nested_delimiter="__"
    )

    streamlit: StreamlitConfig = Field(default_factory=StreamlitConfig)
    uvicorn_client: UvicornClientConfig = Field(default_factory=UvicornClientConfig)
    standalone_interface: StandaloneInterfaceConfig = Field(
        default_factory=StandaloneInterfaceConfig
    )
