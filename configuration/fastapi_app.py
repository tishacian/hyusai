from common_config.uvicorn import UvicornConfig
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FastapiAppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="papai_llm_fastapi_", env_nested_delimiter="__"
    )

    uvicorn: UvicornConfig = Field(default_factory=UvicornConfig)
