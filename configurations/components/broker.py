from pydantic_settings import BaseSettings, SettingsConfigDict


class BrokerConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BROKER_")

    host: str = "localhost"
    port: int = 5672
    user: str = "guest"
    password: str = "guest"
    vhost: str = "/"
    transport: str = "amqp"

    @property
    def url(self) -> str:
        return f"{self.transport}://{self.user}:{self.password}@{self.host}:{self.port}/{self.vhost}"
