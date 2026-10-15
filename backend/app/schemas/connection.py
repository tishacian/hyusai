"""Public connection data never accepts plaintext credentials."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=120, pattern=r"^[^\x00-\x1f]+$")
    profile_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    values: dict[str, Any] = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)
    access: Literal["read", "read_write"] = "read"
    allowed_schemas: list[str] = Field(default_factory=list, max_length=1000)
    allowed_tables: list[str] = Field(default_factory=list, max_length=1000)


class ConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120, pattern=r"^[^\x00-\x1f]+$")
    values: dict[str, Any] | None = None
    secret_refs: dict[str, str] | None = None
    access: Literal["read", "read_write"] | None = None
    allowed_schemas: list[str] | None = Field(default=None, max_length=1000)
    allowed_tables: list[str] | None = Field(default=None, max_length=1000)
