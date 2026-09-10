"""Bounded presentation options; never CSS, scripts, access policy or navigation."""

import base64
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


def validate_brand_logo(value: str) -> str:
    if value.startswith("data:"):
        match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})", value)
        if not match or len(value) > 132000:
            raise ValueError("Logo must be PNG, JPEG or WebP, up to 96 KiB")
        raw = base64.b64decode(match[2], validate=True)
        signatures = {
            "png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
            "jpeg": raw.startswith(b"\xff\xd8\xff"),
            "webp": raw.startswith(b"RIFF") and raw[8:12] == b"WEBP",
        }
        if len(raw) > 96 * 1024 or not signatures[match[1]]:
            raise ValueError("Invalid logo image")
        return value
    if not value or len(value) > 2048 or re.search(r"[\s\\<>]", value):
        raise ValueError("Invalid logo URL")
    if value.startswith("/") and not value.startswith("//"):
        return value
    url = urlsplit(value)
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise ValueError("Logo must use HTTPS or a local asset path")
    return value


class BrandAppearance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    palette: Literal["agentium", "graphite", "sand"] | None = None
    accent: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    corners: Literal["square", "soft", "round"] | None = None
    logo: str | None = None
    logo_light: str | None = None

    @field_validator("logo", "logo_light")
    @classmethod
    def check_logo(cls, value: str | None) -> str | None:
        return validate_brand_logo(value) if value is not None else None


def validate_appearance(value: object) -> dict:
    return BrandAppearance.model_validate(value).model_dump(exclude_none=True)


class PlatformBrand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=120)
    emblem: str
    emblem_light: str | None = None
    home: str | None = None
    appearance: BrandAppearance | None = None

    @field_validator("label")
    @classmethod
    def check_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Brand name is required")
        return value.strip()

    @field_validator("emblem", "emblem_light")
    @classmethod
    def check_emblem(cls, value: str | None) -> str | None:
        return validate_brand_logo(value) if value is not None else None

    @field_validator("home")
    @classmethod
    def check_home(cls, value: str | None) -> str | None:
        if value is not None and (not value.startswith("/") or value.startswith("//") or "\\" in value or re.search(r"\s", value)):
            raise ValueError("Home must be an internal path")
        return value
