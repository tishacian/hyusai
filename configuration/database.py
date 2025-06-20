from typing import Annotated, Literal
from urllib.parse import quote_plus

from pydantic import Field, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="database_")

    host: str = "localhost"
    port: PositiveInt = 5432
    name: str = "omnirag_database"
    username: str = "username"
    password: SecretStr = SecretStr("password")
    dialect: Literal["postgresql", "mysql", "sqlite"] = "sqlite"
    application_name: None | str = None
    """
    Shown in the postgres `pg_stat_activity` table. It is useful to identify from
    postgres the source of the connections.
    """
    application_name_append_pid: bool = False
    """
    Appends the PID to the application name. This is useful to identify the
    process that maintains the connection.
    """

    database_url: str | None = None
    """
    Overrides the contruction of the database url. If this is set, the other
    fields are ignored.
    See https://docs.sqlalchemy.org/en/20/core/engines.html#database-urls.
    """

    pool_size: PositiveInt = 5
    """
    The size of the pool to be maintained.
    This is the largest number of connections that will be kept persistently in the pool.
    Note that the pool begins with no connections; once this number of connections is
    requested, that number of connections will remain.
    pool_size can be set to 0 to indicate no size limit.
    """
    max_overflow: Annotated[int, Field(gt=-1)] = 10
    """
    The maximum overflow size of the pool.
    When the number of checked-out connections reaches the size set in pool_size,
    additional connections will be returned up to this limit. When those additional
    connections are returned to the pool, they are disconnected and discarded. It
    follows then that the total number of simultaneous connections the pool will allow
    is pool_size + max_overflow, and the total number of “sleeping” connections the pool
    will allow is pool_size. 
    max_overflow can be set to -1 to indicate no overflow limit; no limit will be placed
    on the total number of concurrent connections.
    """

    @property
    def url(self) -> str:
        if self.database_url is not None:
            return self.database_url
        elif self.dialect == "sqlite":
            if self.name == ":memory:":
                return "sqlite:///:memory:"
            return f"sqlite:///{self.name}.db"
        else:
            protocol = f"{self.dialect}"
            username_escaped = quote_plus(self.username)
            password_escaped = quote_plus(self.password.get_secret_value())
            credentials = f"{username_escaped}:{password_escaped}"
            address = f"{self.host}:{self.port}/{self.name}"
            return f"{protocol}://{credentials}@{address}"
