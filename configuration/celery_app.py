from common_config.celery import CeleryBrokerConfig, CeleryEnvConfig
from common_config.logging import LoggingConfig
from common_config.sqlalchemy_database import SQLAlchemyDBConfig
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from configuration.subconfigs.backend import BackendConfig
from configuration.subconfigs.vlm import VLMConfig


class CeleryAppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="papai_llm_celery_", env_nested_delimiter="__"
    )

    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    celery_broker: CeleryBrokerConfig = Field(default_factory=CeleryBrokerConfig)
    celery: CeleryEnvConfig = Field(default_factory=CeleryEnvConfig)
    backend: BackendConfig = Field(default_factory=BackendConfig)
    vlm: VLMConfig = Field(default_factory=VLMConfig)
    db: SQLAlchemyDBConfig = Field(default_factory=SQLAlchemyDBConfig)
