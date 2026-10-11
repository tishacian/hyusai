"""Stable, credential-free errors shared by the Hub API and workers."""

from __future__ import annotations


class HFError(ValueError):
    def __init__(
        self, code: str, message: str, status_code: int = 400, details: dict | None = None
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = dict(details or {})

    def public(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}
