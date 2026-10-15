"""Transport-neutral execution policy. HTTP waiting never chooses an executor."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExecutionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    engine: Literal["legacy", "langgraph", "temporal"] = "legacy"
    runtime_revision: str = Field(min_length=1, max_length=80)
    lane: Literal["interactive", "batch"] = "interactive"
    response_wait_s: float = Field(default=2, ge=0, le=10)
    attempt_timeout_s: float = Field(default=40, gt=0, le=86400)
    deadline_at: datetime | None = None
    max_attempts: int = Field(default=1, ge=1, le=10)
    effect: Literal["pure", "idempotent", "reconcile"] = "reconcile"
    native_profile: dict | None = None
    native_profile_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_retries(self):
        if self.effect == "reconcile" and self.max_attempts != 1:
            raise ValueError("uncertain effects require reconciliation, not automatic retries")
        if self.deadline_at is not None and self.deadline_at.tzinfo is None:
            raise ValueError("deadline_at must include a UTC offset")
        if self.engine == "temporal" and (
            not self.native_profile or not self.native_profile_digest
        ):
            raise ValueError("Temporal requires a frozen native profile")
        if self.engine != "temporal" and (
            self.native_profile is not None or self.native_profile_digest is not None
        ):
            raise ValueError("native profile belongs to Temporal only")
        return self

    def remaining_seconds(self, now: datetime | None = None) -> float:
        if self.deadline_at is None:
            return self.attempt_timeout_s
        current = now or datetime.now(UTC)
        return max(0, min(self.attempt_timeout_s, (self.deadline_at - current).total_seconds()))


async def wait_for_result(read_state, *, wait_s: float = 2, poll_s: float = 0.05):
    """Read a *previously submitted* job; no worker is spawned or cancelled here."""
    deadline = asyncio.get_running_loop().time() + max(0, min(wait_s, 10))
    while True:
        result = await read_state()
        if result.get("status") in {
            "completed",
            "succeeded",
            "ready",
            "failed",
            "cancelled",
            "timed_out",
            "lost",
        }:
            return 200, result
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return 202, result
        await asyncio.sleep(min(remaining, poll_s))
