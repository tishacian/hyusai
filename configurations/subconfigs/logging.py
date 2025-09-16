from pathlib import Path

from common_config.logging import LoggingConfig


class CustomLoggingConfig(LoggingConfig):
    limit_traceback_size: bool = False

    # overwrite the default config file for logging
    config_file_path: Path = Path("configurations", "subconfigs", "logging_dev.yaml")
