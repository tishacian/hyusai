"""Safe, provider-neutral classification for LLM failures."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Literal

import httpx

ProviderErrorCode = Literal[
    "provider_unreachable",
    "credentials_invalid",
    "model_missing",
    "rate_limited",
    "timeout",
    "generation_failed",
]


@dataclass(frozen=True)
class ProviderFailure:
    """The only provider-failure shape exposed to API consumers."""

    code: ProviderErrorCode
    message: str
    retryable: bool

    def as_dict(self) -> dict[str, str | bool]:
        return asdict(self)


_FAILURES: dict[ProviderErrorCode, ProviderFailure] = {
    "provider_unreachable": ProviderFailure(
        code="provider_unreachable",
        message=(
            "The configured model provider is unreachable. "
            "Check that it is running and try again."
        ),
        retryable=True,
    ),
    "credentials_invalid": ProviderFailure(
        code="credentials_invalid",
        message=(
            "The configured model provider credentials are missing or were rejected. "
            "Update the provider configuration and try again."
        ),
        retryable=False,
    ),
    "model_missing": ProviderFailure(
        code="model_missing",
        message=(
            "The selected model is not available from the configured provider. "
            "Install or select an available model and try again."
        ),
        retryable=False,
    ),
    "rate_limited": ProviderFailure(
        code="rate_limited",
        message="The model provider is rate limiting requests. Wait briefly and try again.",
        retryable=True,
    ),
    "timeout": ProviderFailure(
        code="timeout",
        message="The model provider did not respond in time. Try again.",
        retryable=True,
    ),
    "generation_failed": ProviderFailure(
        code="generation_failed",
        message=(
            "The model provider could not generate a response. "
            "Try again; if the problem continues, check the provider configuration."
        ),
        retryable=True,
    ),
}


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain and len(chain) < 8:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _status_code(exc: BaseException) -> int | None:
    value = getattr(exc, "status_code", None)
    if value is None:
        value = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def classify_provider_error(exc: BaseException) -> ProviderFailure:
    """Classify provider and HTTP failures without returning exception text.

    SDK packages are intentionally not imported here. Their stable exception
    class names and HTTP status attributes are enough, keeping this contract
    usable when optional provider SDKs are not installed.
    """

    chain = _exception_chain(exc)
    class_names = {item.__class__.__name__.lower() for item in chain}

    if any(
        isinstance(item, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException))
        for item in chain
    ) or class_names.intersection({"apitimeouterror", "timeout", "timeouterror"}):
        return _FAILURES["timeout"]

    statuses = [status for item in chain if (status := _status_code(item)) is not None]
    if any(status in {401, 403} for status in statuses) or class_names.intersection(
        {"authenticationerror", "permissiondeniederror", "unauthorizederror"}
    ):
        return _FAILURES["credentials_invalid"]
    if 429 in statuses or "ratelimiterror" in class_names:
        return _FAILURES["rate_limited"]
    if 404 in statuses or class_names.intersection({"notfounderror", "modelnotfounderror"}):
        return _FAILURES["model_missing"]
    if any(status in {408, 504} for status in statuses):
        return _FAILURES["timeout"]

    if any(
        isinstance(item, (ConnectionError, httpx.NetworkError)) for item in chain
    ) or class_names.intersection(
        {
            "apiconnectionerror",
            "connecterror",
            "connectionrefusederror",
            "networkerror",
            "requesterror",
        }
    ):
        return _FAILURES["provider_unreachable"]

    # Provider constructors and older clients often use ValueError/RuntimeError
    # for absent credentials. Inspect only to classify; the text is never copied
    # into the returned contract.
    if any(
        any(marker in str(item).lower() for marker in ("api key", "credential", "unauthorized"))
        for item in chain
    ):
        return _FAILURES["credentials_invalid"]

    failure = _FAILURES["generation_failed"]
    if statuses and all(status < 500 for status in statuses):
        return ProviderFailure(failure.code, failure.message, retryable=False)
    return failure


def provider_failure(code: ProviderErrorCode) -> ProviderFailure:
    """Return the canonical safe payload for a known provider error code."""
    return _FAILURES[code]


__all__ = [
    "ProviderErrorCode",
    "ProviderFailure",
    "classify_provider_error",
    "provider_failure",
]
