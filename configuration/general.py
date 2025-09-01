from pydantic_settings import BaseSettings, SettingsConfigDict


class GeneralConfig(BaseSettings):
    model_config = SettingsConfigDict(protected_namespaces=("general_",))

    is_standalone: bool = True
    """
    If True, the service will be accessible through a customizable RAG webapp.
    """
