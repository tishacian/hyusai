from common_config.base import BaseConfig
from common_config.core import CoreConfig
from common_config.fsspec_storage import FsspecStorageConfig as StorageConfig
from common_config.sqlalchemy_database import SQLAlchemyDBConfig as DatabaseConfig
from pydantic import Field

from configurations.components.broker import BrokerConfig
from configurations.components.celery_result import CeleryResultConfig
from configurations.components.logging import CustomLoggingConfig
from configurations.components.qdrant import QdrantConfig


class BackendConfig(BaseConfig):
    logging: CustomLoggingConfig = Field(default_factory=CustomLoggingConfig)
    db: DatabaseConfig = Field(default_factory=DatabaseConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    celery_result: CeleryResultConfig = Field(default_factory=CeleryResultConfig)
    core: CoreConfig = Field(default_factory=CoreConfig)
