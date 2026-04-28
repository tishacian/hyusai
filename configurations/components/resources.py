from pydantic_settings import BaseSettings, SettingsConfigDict


class ResourcesConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RESOURCES_")

    tessdata: str = "./data/assets/tessdata"
    nltk: str = "./data/assets/nltk_data"
    custom: str = "./data/assets/custom"
