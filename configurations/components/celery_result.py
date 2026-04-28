from pydantic_settings import BaseSettings, SettingsConfigDict


class CeleryResultConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CELERY_RESULT_")

    host: str = "localhost"
    port: int = 5432
    db: str = "papai_llm_database"
    user: str = "username"
    password: str = "password"

    @property
    def url(self) -> str:
        return f"postgresql+psycopg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"
