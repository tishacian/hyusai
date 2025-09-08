from pydantic_settings import BaseSettings, SettingsConfigDict


class GeneralConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="general", env_nested_delimiter="__")

    is_standalone: bool = True
    """
    If True, the service will be accessible through a customizable RAG webapp.
    """

    limit_traceback_size: bool = False
    """
    If True, full traceback will not be shown and only the final error will be
    shown. This is useful to not expose users to the full traceback.
    """
