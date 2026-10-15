"""Declarative connection forms. Importing profiles never imports a database driver.

Profiles describe the adapter contract, not certification or driver availability.
Only the runner can establish whether its pinned image contains a driver.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.connectors.certification import Capabilities

PROFILE_DIRECTORY = Path(__file__).resolve().parents[2] / "resources" / "connectors" / "profiles"


class ProfileError(ValueError):
    code = "CONNECTOR_PROFILE_INVALID"


class Parameter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    type: Literal["string", "integer", "boolean", "enum", "host", "secret", "secret_file", "json"]
    required: bool = False
    default: Any = None
    choices: tuple[str, ...] = ()
    min: int | None = None
    max: int | None = None
    pattern: str | None = None
    advanced: bool = False
    when: dict[str, tuple[Any, ...]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coherent(self):
        if self.type in {"secret", "secret_file"} and self.default is not None:
            raise ValueError("secret defaults are forbidden")
        if self.type == "enum" and not self.choices:
            raise ValueError("enum needs choices")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("invalid bounds")
        if self.pattern:
            re.compile(self.pattern)
        return self


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    preview_rows: int = Field(default=100, ge=1, le=1000)
    statement_timeout_ms: int = Field(default=30000, ge=1, le=3600000)
    fetch_rows: int = Field(default=10000, ge=1, le=100000)


class ConnectorProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    version: int = Field(ge=1)
    label_key: str
    family: Literal[
        "dbapi",
        "sqlalchemy",
        "adbc",
        "object_store",
        "document",
        "search",
        "wide_column",
        "uc_rest",
        "delta_sharing",
        "iceberg_rest",
        "mcp",
        "openapi",
    ]
    dialect: str
    packages: tuple[str, ...]
    parameters: tuple[Parameter, ...]
    capabilities: Capabilities
    limits: Limits = Field(default_factory=Limits)

    @model_validator(mode="after")
    def unique_parameters(self):
        keys = [p.key for p in self.parameters]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate parameter")
        for p in self.parameters:
            if set(p.when) - set(keys):
                raise ValueError("unknown conditional parameter")
        return self

    @property
    def digest(self) -> str:
        raw = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    def validate_values(
        self, values: dict[str, Any], secret_refs: dict[str, str]
    ) -> dict[str, Any]:
        parameters = {p.key: p for p in self.parameters}
        if set(values) - parameters.keys() or set(secret_refs) - parameters.keys():
            raise ProfileError("unknown parameter")
        result = {}
        for p in self.parameters:
            secret = p.type in {"secret", "secret_file"}
            if secret and p.key in values:
                raise ProfileError("credentials must use registry references")
            if not secret and p.key in secret_refs:
                raise ProfileError("unexpected secret reference")
            value = secret_refs.get(p.key) if secret else values.get(p.key, p.default)
            enabled = all(
                values.get(k, parameters[k].default) in choices for k, choices in p.when.items()
            )
            if value is None or value == "":
                if p.required and enabled:
                    raise ProfileError(f"missing parameter: {p.key}")
                continue
            if secret:
                if not isinstance(value, str):
                    raise ProfileError("invalid secret reference")
                continue
            valid = True
            if p.type == "integer":
                valid = type(value) is int
                if valid:
                    valid = (p.min is None or value >= p.min) and (p.max is None or value <= p.max)
            elif p.type == "boolean":
                valid = type(value) is bool
            elif p.type == "json":
                valid = isinstance(value, (dict, list))
            else:
                valid = isinstance(value, str) and len(value) <= 2048 and "\x00" not in value
                if valid and p.type == "enum":
                    valid = value in p.choices
                if valid and p.type == "host":
                    valid = (
                        bool(value)
                        and not any(c in value for c in "/@?#\\")
                        and not any(c.isspace() for c in value)
                    )
                if valid and p.pattern:
                    valid = re.fullmatch(p.pattern, value) is not None
            if not valid:
                raise ProfileError(f"invalid parameter: {p.key}")
            result[p.key] = copy.deepcopy(value)
        return result


@lru_cache(maxsize=1)
def _profiles() -> dict[str, ConnectorProfile]:
    profiles = {}
    for path in sorted(PROFILE_DIRECTORY.glob("*.yaml")):
        profile = ConnectorProfile.model_validate(yaml.safe_load(path.read_text()))
        if path.stem != profile.key or profile.key in profiles:
            raise ProfileError("profile key does not match its unique file")
        profiles[profile.key] = profile
    return profiles


def get_profile(key: str) -> ConnectorProfile:
    try:
        return _profiles()[key]
    except KeyError as exc:
        raise ProfileError("unknown profile") from exc


def list_profiles() -> list[ConnectorProfile]:
    return list(_profiles().values())
