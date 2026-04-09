from common_config.base import BaseConfig
from common_config.celery import CeleryBrokerConfig as BrokerConfig
from common_config.celery import CeleryEnvConfig as CeleryConfig
from common_config.celery import CeleryResultBackendConfig as CeleryDBConfig
from common_config.core import CoreConfig
from common_config.fsspec_storage import FsspecStorageConfig as StorageConfig
from common_config.sqlalchemy_database import SQLAlchemyDBConfig as DatabaseConfig
from common_config.uvicorn import UvicornConfig as FastAPIServerConfig
from pydantic import Field
from pydantic_settings import SettingsConfigDict

from configurations.components.backend import BackendConfig
from configurations.components.fastapi_client import FastAPIClientConfig
from configurations.components.interface import InterfaceConfig
from configurations.components.logging import CustomLoggingConfig as LoggingConfig
from configurations.components.qdrant import QdrantConfig
from configurations.components.ressources import RessourcesConfig
from configurations.components.streamlit import StreamlitConfig
from configurations.components.vlm import VLMConfig


class Config(BaseConfig):
    model_config = SettingsConfigDict(env_prefix="papaillm_", env_nested_delimiter="__")

    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    # frontend
    interface: InterfaceConfig = Field(default_factory=InterfaceConfig)
    streamlit: StreamlitConfig = Field(default_factory=StreamlitConfig)
    fastapi_client: FastAPIClientConfig = Field(default_factory=FastAPIClientConfig)
    # fastapi
    fastapi_server: FastAPIServerConfig = Field(default_factory=FastAPIServerConfig)
    # celery
    celery: CeleryConfig = Field(default_factory=CeleryConfig)
    celery_db: CeleryDBConfig = Field(default_factory=CeleryDBConfig)
    backend: BackendConfig = Field(default_factory=BackendConfig)
    vlm: VLMConfig = Field(default_factory=VLMConfig)
    ressources: RessourcesConfig = Field(default_factory=RessourcesConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    # external services
    core: CoreConfig = Field(default_factory=CoreConfig)
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
