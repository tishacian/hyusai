from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_")

    skip: bool = True
    cookie_name: str = "omnirag_auth"
    cookie_key: str = ""
    cookie_expiry_days: int = 1
