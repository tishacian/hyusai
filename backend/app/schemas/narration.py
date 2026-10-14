"""Closed gateway protocol for bounded, version-pinned document narration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.service_contract import AssetRef


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class NarrationBudget(Closed):
    max_pages: int = Field(default=500, ge=1, le=500)
    max_images: int = Field(default=500, ge=1, le=500)
    max_requests: int = Field(default=2000, ge=2, le=10000)
    max_output_bytes: int = Field(default=64 * 1024**2, ge=1, le=256 * 1024**2)
    max_unit_bytes: int = Field(default=256 * 1024, ge=1, le=1024**2)
    max_cost_usd: float = Field(default=10, gt=0, le=10000)
    max_tokens: int = Field(default=100000, ge=1, le=10000000)
    timeout_s: int = Field(default=900, ge=1, le=7200)
    poll_interval_s: float = Field(default=1, ge=0.05, le=30)


class NarrationSpec(Closed):
    source_ref: AssetRef | None = None
    engine_revision: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:@/-]+$")
    options: dict[str, Any] = Field(default_factory=dict)
    budgets: NarrationBudget = Field(default_factory=NarrationBudget)


class NarrationSourceUnit(Closed):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    kind: Literal["page", "image"]
    object_key: str = Field(min_length=1, max_length=1000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int | None = Field(default=None, ge=1, le=100000)


class NarrationUnitResult(Closed):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    status: Literal["completed", "failed"]
    content_base64: str | None = Field(default=None, max_length=1400000)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    mime_type: (
        Literal["text/plain", "text/markdown", "application/json", "image/png", "image/jpeg"] | None
    ) = None

    @model_validator(mode="after")
    def content(self):
        if self.status == "completed" and any(
            value is None for value in (self.content_base64, self.sha256, self.mime_type)
        ):
            raise ValueError("NARRATION_UNIT_CONTENT_REQUIRED")
        if self.status == "failed" and any(
            value is not None for value in (self.content_base64, self.sha256, self.mime_type)
        ):
            raise ValueError("NARRATION_FAILED_UNIT_HAS_CONTENT")
        return self


class NarrationGatewayResult(Closed):
    protocol_version: Literal[1] = 1
    job_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    engine_revision: str = Field(min_length=1, max_length=160)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    units: list[NarrationUnitResult] = Field(default_factory=list, max_length=100)
    next_cursor: str | None = Field(default=None, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    cost_usd: float | None = Field(default=None, ge=0)
    tokens: int | None = Field(default=None, ge=0)
