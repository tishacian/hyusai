"""Transport-owned usage capture and budget admission.

Only trusted runtime scopes create attribution. Payloads are hashed, never
stored here. An admitted attempt owns its ledger row all the way through
streaming, cancellation and failure; nested wrappers do not create another
charge. Missing usage after a possible send is deliberately left unsettled.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from threading import Lock
from typing import Any
from uuid import uuid4


@dataclass
class _Scope:
    context: Any
    key: str
    call_ids: list[str] = field(default_factory=list)
    counter: dict = field(default_factory=lambda: {"value": 0, "lock": Lock()})


_SCOPE: ContextVar[_Scope | None] = ContextVar("model_usage_scope", default=None)
_REQUEST: ContextVar[dict | None] = ContextVar("model_usage_request", default=None)
_OWNER: ContextVar[bool] = ContextVar("model_usage_transport_owner", default=False)
QUALIFIED_TEXT_PROVIDERS = frozenset({"openai", "azure_openai", "anthropic"})
# Capability digest for rollout attestation. Per-call qualification still
# rejects vision, hosted tools, missing output caps and unsupported transports.
QUALIFIED_TRANSPORTS = frozenset(
    {
        "direct_sdk.text.openai",
        "model_plane.text.openai",
        "model_plane.text.azure_openai",
        "model_plane.text.anthropic",
        "model_router.text.openai",
        "model_router.text.azure_openai",
        "model_router.text.anthropic",
        "legacy_llm.text.openai",
        "legacy_llm.text.azure_openai",
        "legacy_llm.text.anthropic",
        "assistant.openai.tools",
        "rag.openai.embeddings",
        "giskard.ipc.openai",
        "typed_judge.atomic_admission",
        "model_plane.typesafe.pinned_monetary_v1",
    }
)


def _mapping(value: Any) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump()
    return {
        name: getattr(value, name)
        for name in (
            "usage",
            "token_usage",
            "model",
            "id",
            "prompt_tokens",
            "completion_tokens",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cached_tokens",
            "reasoning_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "prompt_tokens_details",
            "completion_tokens_details",
            "input_tokens_details",
            "output_tokens_details",
        )
        if getattr(value, name, None) is not None
    }


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def response_usage(
    response: Any, *, provider: str | None = None, embedding: bool = False
) -> dict | None:
    """Normalize *reported* counters, retaining cache/reasoning breakdowns.

    Anthropic's native input excludes its cache categories, unlike OpenAI.
    Cache/reasoning details are subsets of normalized input/output, never
    extra tokens to add to the normalized total.
    """
    data = _mapping(response)
    usage = _mapping(data.get("usage") or data.get("token_usage"))
    if not usage:
        usage = data
    if usage.get("measurement_coverage") in {"partial", "unavailable", "not_measured"}:
        return None
    first = lambda *keys: next(
        (_count(usage[k]) for k in keys if _count(usage.get(k)) is not None), None
    )
    inputs = first("prompt_tokens", "input_tokens", "prompt_eval_count")
    outputs = first("completion_tokens", "output_tokens", "eval_count")
    total = first("total_tokens", "tokens_total", "token_count")
    cached = first("cached_tokens", "cache_read_input_tokens")
    cache_write = first("cache_creation_input_tokens", "cache_write_tokens")
    reasoning = first("reasoning_tokens")
    input_details = _mapping(
        usage.get("prompt_tokens_details") or usage.get("input_tokens_details")
    )
    output_details = _mapping(
        usage.get("completion_tokens_details") or usage.get("output_tokens_details")
    )
    if cached is None:
        cached = _count(input_details.get("cached_tokens"))
    if reasoning is None:
        reasoning = _count(output_details.get("reasoning_tokens"))
    # Only the *native* Anthropic shape needs the cache categories added.
    if provider == "anthropic" and "prompt_tokens" not in usage and inputs is not None:
        inputs += (cached or 0) + (cache_write or 0)
    if embedding and inputs is not None and total == inputs and outputs is None:
        # The embedding protocol emits no completion tokens.
        outputs = 0
    if total is None and inputs is not None and outputs is not None:
        total = inputs + outputs
    if inputs is None and outputs is None and total is None:
        return None
    if (
        total is not None
        and inputs is not None
        and outputs is not None
        and total != inputs + outputs
    ):
        return None
    if cached is not None and inputs is not None and cached > inputs:
        return None
    if reasoning is not None and outputs is not None and reasoning > outputs:
        return None
    return {
        key: value
        for key, value in {
            "prompt_tokens": inputs,
            "completion_tokens": outputs,
            "total_tokens": total,
            "cached_tokens": cached,
            "cache_write_tokens": cache_write,
            "reasoning_tokens": reasoning,
        }.items()
        if value is not None
    }


def _active_scope():
    return _SCOPE.get() or (_REQUEST.get() or {}).get("scope")


@contextmanager
def request_usage_scope():
    """Mutable holder survives Starlette's sync-dependency thread boundary."""
    holder = {"scope": None}
    token = _REQUEST.set(holder)
    try:
        yield holder
    finally:
        _REQUEST.reset(token)


def bind_request_usage_context(context, *, key=None):
    holder = _REQUEST.get()
    if holder is not None:
        holder["scope"] = _Scope(context, key or str(uuid4()))


def set_usage_context(context, *, key=None):
    return _SCOPE.set(_Scope(context, key or str(uuid4())))


def reset_usage_context(token):
    _SCOPE.reset(token)


def current_scope() -> Any | None:
    scope = _active_scope()
    return scope.context if scope else None


def tracking_active() -> bool:
    return _active_scope() is not None


@contextmanager
def usage_scope(context: Any, *, key: str | None = None, call_ids: list[str] | None = None):
    """Bind a server-created UsageContext to asynchronous execution."""
    if context is None:
        yield
        return
    identity = key or next(
        (
            str(getattr(context, name))
            for name in ("invocation_id", "job_id", "worker_job_id", "run_id")
            if getattr(context, name, None)
        ),
        str(uuid4()),
    )
    scope = _Scope(context, identity, call_ids=call_ids if call_ids is not None else [])
    token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        _SCOPE.reset(token)


@contextmanager
def context_from_execution(ctx: dict, execution: Any = None):
    """Canonical Model Plane also serves jobs outside the Run dispatcher."""
    previous = _SCOPE.get()
    explicit = ctx.get("_model_usage_context")
    if previous is not None:
        # A Judge shares its invocation scope but contributes its own identity.
        fields = {
            name: ctx[key]
            for name, key in (
                ("evaluation_id", "_model_usage_evaluation_id"),
                ("job_id", "_model_usage_job_id"),
                ("purpose", "_model_usage_purpose"),
            )
            if ctx.get(key)
        }
        token = (
            _SCOPE.set(
                _Scope(
                    replace(previous.context, **fields),
                    previous.key,
                    call_ids=previous.call_ids,
                    counter=previous.counter,
                )
            )
            if fields
            else None
        )
        try:
            yield
        finally:
            if token is not None:
                _SCOPE.reset(token)
        return
    if explicit is None:
        workspace_id = ctx.get("workspace_id") or getattr(execution, "_workspace_id", None)
        if workspace_id:
            from app.services.model_usage import UsageContext

            explicit = UsageContext(
                workspace_id=str(workspace_id),
                system_id=ctx.get("system_id"),
                run_id=ctx.get("run_id"),
                invocation_id=ctx.get("_skill_invocation_id"),
                job_id=ctx.get("_model_usage_job_id") or ctx.get("job_id"),
                evaluation_id=ctx.get("_model_usage_evaluation_id"),
                purpose=ctx.get("_model_usage_purpose") or "generation",
            )
    if explicit is None:
        yield
        return
    scope = ctx.get("_model_usage_scope")
    if not isinstance(scope, _Scope) or scope.context != explicit:
        identity = next(
            (
                str(getattr(explicit, name))
                for name in ("invocation_id", "job_id", "worker_job_id", "run_id")
                if getattr(explicit, name, None)
            ),
            str(uuid4()),
        )
        if getattr(explicit, "evaluation_id", None):
            identity += ":" + explicit.evaluation_id
        scope = _Scope(explicit, identity, call_ids=ctx.setdefault("_model_usage_call_ids", []))
        ctx["_model_usage_scope"] = scope
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        _SCOPE.reset(token)


def _has_nontext(value: Any) -> bool:
    if isinstance(value, Mapping):
        kind = value.get("type")
        if isinstance(kind, str) and kind in {
            "image_url",
            "image",
            "input_image",
            "input_audio",
            "audio",
            "video",
        }:
            return True
        if isinstance(kind, str) and kind.startswith(("web_search", "computer", "file_search")):
            return True
        return any(_has_nontext(item) for item in value.values())
    return isinstance(value, (list, tuple)) and any(_has_nontext(item) for item in value)


def native_typesafe_input_bound(model: str, payload: dict) -> int | None:
    """Bound native billable input, never invent a bound for free output tokens.

    https://docs.typesafe.ai/models documents 64k total request context for
    these pinned models, with state ingested once for all questions. Overlong
    requests are rejected (api/errors). Reserve 65,536 to cover either meaning
    of "64k". This qualification excludes aliases, images, custom headers and
    the opt-in long-context protocol. The fixed transport sends only this body.
    Output tokens are free at the documented tariff but have no known bound;
    the ledger must still reject token ceilings and nonzero output tariffs.
    """
    from app.services.model_plane.typesafe import (
        PINNED_MONETARY_MODELS,
        TypeSafeError,
        validate_request,
    )

    if (
        model not in PINNED_MONETARY_MODELS
        or not isinstance(payload, dict)
        or set(payload) != {"model", "state", "questions"}
        or payload.get("model") != model
        or _has_nontext(payload)
    ):
        return None
    try:
        validate_request(model=model, state=payload["state"], questions=payload["questions"])
    except TypeSafeError:
        return None
    return 65_536


class ProviderCall:
    """One owner around exactly one SDK/network attempt; usable from Giskard IPC."""

    def __init__(
        self,
        provider: str,
        model: str,
        payload: dict,
        *,
        operation="completion",
        output_token_bound=None,
        qualified=True,
        admission_hook=None,
        before_dispatch=None,
        after_admission=None,
        purpose=None,
        request_key=None,
    ):
        self.provider, self.model, self.payload = provider, model, payload
        self.operation, self.output_bound = operation, output_token_bound
        self.qualified, self.admission_hook = qualified, admission_hook
        self.before_dispatch = before_dispatch
        self.after_admission = after_admission
        self.purpose, self.request_key = purpose, request_key
        self.id = None
        self.result = None
        self.returned_model = None
        self.provider_request_id = None
        self._token = None

    def __enter__(self):
        scope = _active_scope()
        if scope is None or _OWNER.get():
            if callable(self.before_dispatch):
                self.before_dispatch()
            return self
        from app.services.model_usage import UsageError, mark_dispatched, prepare_call

        raw = json.dumps(
            self.payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode()
        textual = not _has_nontext(self.payload)
        # UTF-8 bytes are a conservative token bound for the qualified byte-
        # tokenizer routes. Include wire/framing overhead, never chars/4.
        native = self.provider == "typesafe" and self.operation == "typed_decisions"
        if native:
            input_bound = native_typesafe_input_bound(self.model, self.payload)
            # max_tokens is a local Judge provision, not a TypeSafe wire cap.
            output_bound = None
            qualified = self.qualified and input_bound is not None
        else:
            input_bound = (
                len(raw) + 4096 if textual and self.provider in QUALIFIED_TEXT_PROVIDERS else None
            )
            output_bound = 0 if self.operation == "embedding" else self.output_bound
            qualified = (
                self.qualified
                and input_bound is not None
                and type(output_bound) is int
                and output_bound >= 0
            )
        with scope.counter["lock"]:
            scope.counter["value"] += 1
            ordinal = scope.counter["value"]
        request_key = self.request_key or f"transport:{scope.key}:{ordinal}"
        context = replace(scope.context, purpose=self.purpose) if self.purpose else scope.context
        record = prepare_call(
            context,
            request_key=request_key,
            provider=self.provider,
            model=self.model,
            operation=self.operation,
            input_token_bound=input_bound,
            output_token_bound=output_bound,
            request_sha256=hashlib.sha256(raw).hexdigest(),
            admission_qualified=qualified,
            **({"admission_hook": self.admission_hook} if self.admission_hook else {}),
        )
        self.id = record["id"]
        scope.call_ids.append(self.id)
        if callable(self.after_admission):
            self.after_admission(record)
        try:
            if callable(self.before_dispatch):
                self.before_dispatch()
        except BaseException:
            from app.services.model_usage import cancel_before_dispatch

            cancel_before_dispatch(self.id)
            raise
        if not mark_dispatched(self.id):
            raise UsageError("USAGE_CALL_REQUIRES_RECONCILIATION")
        self._token = _OWNER.set(True)
        return self

    def observe(self, response: Any):
        counters = response_usage(
            response, provider=self.provider, embedding=self.operation == "embedding"
        )
        if counters is not None:
            # Streaming usage is cumulative, not a sequence of increments.
            self.result = counters
        data = _mapping(response)
        model = data.get("model")
        if isinstance(model, str) and model:
            self.returned_model = model
        request_id = data.get("id")
        if isinstance(request_id, str) and request_id:
            self.provider_request_id = request_id

    def __exit__(self, exc_type, exc, tb):
        if self._token is not None:
            _OWNER.reset(self._token)
        if self.id:
            from app.services.model_usage import settle_call

            settle_call(
                self.id,
                usage=self.result,
                returned_model=self.returned_model,
                provider_request_id=self.provider_request_id,
                status="failed" if exc is not None else "completed",
                diagnostic=type(exc).__name__ if exc is not None else None,
            )
        return False


def output_limit(options: Mapping) -> int | None:
    for key in ("max_completion_tokens", "max_output_tokens", "max_tokens"):
        value = options.get(key)
        if type(value) is int and value > 0:
            n = options.get("n", 1)
            return value * n if type(n) is int and 1 <= n <= 128 else None
    nested = options.get("options")
    value = nested.get("num_predict") if isinstance(nested, Mapping) else None
    return value if type(value) is int and value > 0 else None


def metered_model_method(provider: str, *, default_output: int | None = None):
    """Cover direct ModelRouter calls as well as Model Plane callers.

    The outer Model Plane owns its reservation hook; these nested wrappers
    only own attempts for clients used directly by legacy skills/auto-Judge.
    """
    import functools
    import inspect

    def decorate(function):
        signature = inspect.signature(function)

        def call_for(self, args, kwargs):
            values = dict(signature.bind(self, *args, **kwargs).arguments)
            values.pop("self", None)
            options = values.pop("kwargs", {})
            values.update(options)
            model = values.pop("model")
            resolved = getattr(self, "usage_provider", provider)
            if (
                resolved == "openai"
                and getattr(self, "base_url", "https://api.openai.com/v1")
                != "https://api.openai.com/v1"
            ):
                resolved = "openai_compatible"
            return ProviderCall(
                resolved,
                model,
                values,
                output_token_bound=output_limit(options) or default_output,
                qualified=resolved in QUALIFIED_TEXT_PROVIDERS,
            )

        if inspect.isasyncgenfunction(function):

            @functools.wraps(function)
            async def stream(self, *args, **kwargs):
                with call_for(self, args, kwargs) as call:
                    async for result in function(self, *args, **kwargs):
                        call.observe(result)
                        yield result

            return stream

        @functools.wraps(function)
        async def complete(self, *args, **kwargs):
            with call_for(self, args, kwargs) as call:
                result = await function(self, *args, **kwargs)
                call.observe(result)
                return result

        return complete

    return decorate
