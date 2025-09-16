from common_config.logging import LoggingConfig


class CustomLoggingConfig(LoggingConfig):
    limit_traceback_size: bool = False
