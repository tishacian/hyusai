from pathlib import Path

from common_config.logging import LoggingConfig
from pydantic import AliasChoices, Field


class CustomLoggingConfig(LoggingConfig):
    level: str = Field(
        default="INFO", validation_alias=AliasChoices("LOG_LEVEL", "LOGGING_LEVEL")
    )
    limit_traceback_size: bool = False
    config_file_path: Path = Path("configurations", "components", "logging_dev.yaml")

    def setup(self) -> None:
        self.config.setdefault("loggers", {}).setdefault("root", {})["level"] = (
            self.level.upper()
        )
        super().setup()
