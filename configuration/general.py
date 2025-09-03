from pydantic_settings import BaseSettings, SettingsConfigDict


class GeneralConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="general", env_nested_delimiter="__")

    is_standalone: bool = True
    """
    If True, the service will be accessible through a customizable RAG webapp.
    """
