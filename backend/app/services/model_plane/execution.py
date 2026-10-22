"""Resolve a model once, before policy checks, then build its exact connection.

Only ``public()`` belongs in APIs or the invocation ledger. Connection material
is private, never represented, and frozen for this invocation so a concurrent
workspace edit cannot change the provider between policy and dispatch.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlparse

from app.core.config import settings
from app.services.model_plane import workspace_config

TEXT_PROVIDERS = ("openai", "azure_openai", "ollama", "huggingface")
_MODEL_PREFIXES = (*TEXT_PROVIDERS, "azure", "anthropic", "typesafe")


class ModelExecutionError(ValueError):
    """Actionable configuration refusal containing no credential or prompt."""


class _DispatchRefused(Exception):
    """A local refusal must neither trigger fallback nor count as provider work."""

    def __init__(self, cause: Exception):
        self.cause = cause


@dataclass(frozen=True)
class ModelImage:
    """Server-resolved bytes only; URLs and credentials never enter this contract."""

    evidence_id: str
    data: bytes = field(repr=False)
    mime_type: str
    sha256: str

    def content_parts(self):
        if (
            self.mime_type not in {"image/png", "image/jpeg", "image/webp"}
            or not isinstance(self.data, bytes)
            or not 0 < len(self.data) <= 8_000_000
            or hashlib.sha256(self.data).hexdigest() != self.sha256
        ):
            raise ModelExecutionError("Invalid or unverified model image.")
        return [
            {"type": "text", "text": f"Evidence image: {self.evidence_id}; sha256: {self.sha256}"},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{self.mime_type};base64," + base64.b64encode(self.data).decode(),
                    "detail": "high",
                },
            },
        ]


@dataclass(frozen=True)
class ModelExecution:
    provider: str
    model: str
    credential_source: str
    model_source: str
    legacy_provider: str | None = None
    _api_key: str | None = field(default=None, repr=False)
    _endpoint: str | None = field(default=None, repr=False)
    _api_version: str | None = field(default=None, repr=False)
    _fallbacks: tuple[ModelExecution, ...] = field(default=(), repr=False)
    requested_provider: str | None = None
    _workspace_id: str | None = field(default=None, repr=False)
    artifact_provenance: dict | None = None

    def public(self, *, returned_model: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
            "credential_source": self.credential_source,
            "model_source": self.model_source,
            "fallback": False,
        }
        if self.legacy_provider:
            result["legacy_provider"] = self.legacy_provider
        if returned_model:
            result["returned_model"] = returned_model
        if self.requested_provider:
            result["requested_provider"] = self.requested_provider
        if self.requested_provider == "workspace" or self.model_source.startswith("route:"):
            result["fallback_plan"] = [candidate.public() for candidate in self._fallbacks]
        if self.artifact_provenance:
            result.update(self.artifact_provenance)
        return result

    def policy_model(self, allowed_models: list[str]) -> str:
        qualified = f"{self.provider}:{self.model}"
        # Existing policies also use bare model names; preserve that deliberate
        # allowance while evaluating provider-qualified policies exactly.
        return self.model if self.model in allowed_models else qualified


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _credential(workspace: Any, provider: str, env_name: str) -> tuple[str | None, str]:
    if workspace is not None:
        public = workspace_config.get_cloud_credentials_public(workspace)
        stored = next((entry for entry in public if entry["key"] == provider), {})
        if stored.get("api_key_set"):
            key = workspace_config.get_decrypted_api_key(workspace, provider)
            if not key:
                raise ModelExecutionError(
                    f"{provider}: workspace credential cannot be read; reconnect this provider."
                )
            return key, "workspace"
    key = os.getenv(env_name)
    return key, "env" if key else "not_configured"


def resolve_model_execution(
    workspace: Any = None,
    *,
    provider: str | None = None,
    model: str | None = None,
    model_source: str = "input",
    legacy_defaults: bool = False,
    capability: str = "text_generation",
) -> ModelExecution:
    if capability not in {"text_generation", "typed_decisions"}:
        raise ModelExecutionError("Unknown model capability.")
    routing = (
        workspace_config.get_routing(workspace)
        if workspace is not None
        else {
            "default_provider": settings.default_provider,
            "default_model": settings.default_model,
            "source": "global",
            "fallback_chain": [settings.default_provider, "ollama"],
        }
    )
    requested = _text(provider)
    route = (routing.get("named_routes") or {}).get(requested) if requested else None
    if isinstance(route, Mapping):
        resolved = resolve_model_execution(
            workspace,
            provider=_text(route.get("provider")) or None,
            model=_text(route.get("model")) or None,
            capability=capability,
        )
        if resolved.provider == "typesafe" and route.get("fallback_chain"):
            raise ModelExecutionError("typesafe: typed decisions do not support fallbacks.")
        fallbacks = tuple(
            resolve_model_execution(workspace, provider=_text(item))
            for item in (route.get("fallback_chain") or [])
            if _text(item)
        )
        return replace(
            resolved,
            model_source=f"route:{requested}",
            _fallbacks=fallbacks,
            requested_provider=requested,
        )
    inherited = not requested or requested == "workspace"
    selected = _text(routing["default_provider"]) if inherited else requested
    legacy = "azure" if selected == "azure" else None
    selected = "openai" if legacy else selected
    if selected == "typesafe" and (capability != "typed_decisions" or inherited):
        raise ModelExecutionError(
            "typesafe: select this provider explicitly for typed decisions, not text generation."
        )
    if selected.startswith("serving_"):
        return _resolve_serving_execution(
            workspace,
            selected,
            model,
            model_source,
            "workspace" if inherited else requested,
            routing if inherited else {},
        )
    if selected not in (*TEXT_PROVIDERS, "anthropic", "typesafe"):
        raise ModelExecutionError(
            f"{selected or 'unknown'}: text generation is not supported by this runtime."
        )
    chosen = _text(model)
    meta = workspace_config.get_provider_meta(workspace, selected) if workspace is not None else {}
    if not chosen:
        if legacy:
            chosen, model_source = "gpt-4o-mini", "legacy_default"
        elif legacy_defaults and selected == "ollama":
            chosen, model_source = (
                "deepseek-r1:14b",
                (
                    "legacy_default"
                    if model_source == "legacy_default"
                    else "published_legacy_default"
                ),
            )
        elif selected == _text(routing["default_provider"]):
            chosen, model_source = _text(routing["default_model"]), str(routing["source"])
        elif selected == "azure_openai":
            chosen = _text(meta.get("deployment")) or _text(os.getenv("AZURE_OPENAI_DEPLOYMENT"))
            model_source = "workspace" if meta.get("deployment") else "env"
        elif selected == "ollama":
            chosen, model_source = settings.ollama_default_model, "global"
        elif selected == "openai" and settings.default_provider == "openai":
            chosen, model_source = settings.default_model, "global"
    if not chosen:
        raise ModelExecutionError(
            f"{selected}: choose a text model or configure its default first."
        )
    if not legacy:
        prefix, separator, tail = chosen.partition(":")
        if separator and prefix in _MODEL_PREFIXES:
            if prefix != selected:
                raise ModelExecutionError("The selected model belongs to a different provider.")
            chosen = tail.strip()
        if not chosen:
            raise ModelExecutionError("Choose a non-empty model identifier.")
        from app.services.model_plane.providers import model_compatibility

        if selected != "typesafe" and model_compatibility(selected, chosen) == "other":
            raise ModelExecutionError(f"{selected}: this model is not a text-generation model.")
    if legacy:
        key = os.getenv("OPENAI_API_KEY")
        credential_source = "env" if key else "not_configured"
    elif selected == "ollama":
        key, credential_source = None, "none"
    elif selected == "huggingface":
        from app.services.huggingface.connection import DEFAULT_ENDPOINT, resolve_for_workspace

        if workspace is None:
            raise ModelExecutionError(
                "huggingface: choose a workspace to apply its license policy."
            )
        connection = resolve_for_workspace(workspace)
        if connection.endpoint != DEFAULT_ENDPOINT:
            raise ModelExecutionError(
                "huggingface: HF Inference requires a huggingface.co connection."
            )
        key = connection.token
        credential_source = connection.source if key else "not_configured"
    else:
        env = {
            "openai": "OPENAI_API_KEY",
            "azure_openai": "AZURE_OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "typesafe": "TYPESAFE_API_KEY",
        }[selected]
        key, credential_source = _credential(workspace, selected, env)
    endpoint = None
    api_version = None
    if selected == "azure_openai":
        endpoint = _text(meta.get("endpoint")) or _text(os.getenv("AZURE_OPENAI_ENDPOINT"))
        api_version = _text(meta.get("api_version")) or os.getenv(
            "AZURE_OPENAI_API_VERSION", "2024-02-01"
        )
        if endpoint:
            parsed = urlparse(endpoint)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ModelExecutionError(
                    "azure_openai: configure an HTTPS endpoint without credentials or query parameters."
                )
        if not endpoint:
            credential_source = "not_configured"
    elif selected == "ollama":
        endpoint = "http://localhost:11434" if legacy_defaults else settings.ollama_base_url
    elif selected == "huggingface":
        from app.services.huggingface.connection import INFERENCE_ENDPOINT

        endpoint = INFERENCE_ENDPOINT
    fallbacks = []
    if inherited:
        for candidate in dict.fromkeys(routing.get("fallback_chain") or []):
            if candidate in {selected, "workspace", "azure"}:
                continue
            # Refuse an invalid plan instead of presenting a fallback that can
            # only fail after the primary has consumed the request budget.
            fallbacks.append(resolve_model_execution(workspace, provider=candidate))
    return ModelExecution(
        selected,
        chosen,
        credential_source,
        model_source,
        legacy,
        key,
        endpoint,
        api_version,
        tuple(fallbacks),
        "workspace" if inherited else requested,
        getattr(workspace, "id", None),
    )


def build_model_client(execution: ModelExecution, *, no_retries: bool = False):
    if execution.provider == "typesafe":
        raise ModelExecutionError("typesafe: use the typed-decision transport.")
    if execution.artifact_provenance:
        from app.services.huggingface.inference import ArtifactInferenceClient

        return ArtifactInferenceClient(
            execution._workspace_id,
            execution.provider,
            execution.artifact_provenance,
            **({"max_retries": 0} if no_retries else {}),
        )
    if execution.provider == "ollama":
        from app.services.model_clients.ollama_client import OllamaClient

        return OllamaClient(base_url=execution._endpoint)
    if not execution._api_key or execution.credential_source == "not_configured":
        raise ModelExecutionError(
            f"{execution.provider}: connection is not configured. Open Models & Providers."
        )
    retry_options = {"max_retries": 0} if no_retries else {}
    if execution.provider == "huggingface":
        from app.services.huggingface.inference import HFInferenceClient

        return HFInferenceClient(execution._workspace_id, **retry_options)
    if execution.provider == "azure_openai":
        from app.services.model_clients.azure_openai_client import AzureOpenAIClient

        return AzureOpenAIClient(
            api_key=execution._api_key,
            endpoint=execution._endpoint,
            api_version=execution._api_version,
            **retry_options,
        )
    if execution.provider == "anthropic":
        from app.services.model_clients.anthropic_client import AnthropicClient

        return AnthropicClient(api_key=execution._api_key, **retry_options)
    from app.services.model_clients.openai_client import OpenAIClient

    return OpenAIClient(api_key=execution._api_key, **retry_options)


def skill_model_request(
    slug: str,
    executor: Mapping[str, Any] | None,
    payload: Mapping[str, Any],
    system_model: str | None,
    *,
    published: bool = False,
) -> dict[str, Any] | None:
    params = executor.get("params", {}) if isinstance(executor, Mapping) else {}
    params = params if isinstance(params, Mapping) else {}
    kind = executor.get("kind") if isinstance(executor, Mapping) else None
    if kind == "registry_call":
        slug = str(params.get("skill_slug") or "")
        frozen = params.get("frozen_input")
        payload = {**payload, **(frozen if isinstance(frozen, Mapping) else {})}
    if slug == "evaluate_v2":
        # DAG injection replaces this private block from the published graph;
        # ordinary inputs and upstream output cannot select a Judge connection.
        block = payload.get("_typed_evaluation")
        config = block.get("typed_evaluation") if isinstance(block, Mapping) else None
        tariff = config.get("tariff") if isinstance(config, Mapping) else None
        if isinstance(tariff, Mapping):
            provider, model = _text(tariff.get("provider")), _text(tariff.get("model"))
            if not provider or not model:
                raise ModelExecutionError("The published Judge requires a provider and model.")
            return {
                "provider": provider,
                "model": model,
                "model_source": "published_judge",
                "capability": "typed_decisions",
            }
    providers = {
        "azure_llm_v1": "azure",
        "ollama_llm_v1": "ollama",
        "openai_llm_v1": "openai",
        "azure_openai_llm_v1": "azure_openai",
        "workspace_llm_v1": "workspace",
        "llm_label_dataset_v1": "workspace",
        "evaluate_v2": "workspace",
        "decide_next_v1": "workspace",
    }
    provider = _text(params.get("provider")) if kind == "prompt_template" else providers.get(slug)
    if not provider:
        return None
    chosen, source = _text(payload.get("model")), "input"
    if not chosen and kind == "prompt_template":
        chosen, source = _text(params.get("model")), "executor"
    legacy_defaults = provider == "azure" or (
        provider == "ollama"
        and (kind != "prompt_template" or (published and not params.get("model")))
    )
    if provider == "ollama" and kind != "prompt_template" and not chosen:
        source = "legacy_default"
    if (
        kind == "registry_call"
        and isinstance(params.get("frozen_input"), Mapping)
        and _text(params["frozen_input"].get("model"))
    ):
        source = "executor"
    if not chosen and not legacy_defaults:
        chosen, source = _text(system_model), "system"
    if slug == "decide_next_v1" and chosen:
        # AgentLoop authors select a provider-qualified model in the published
        # Flow. Resolve it before the capability check, through the same plane
        # as other LLM nodes; never infer it from an ML result object.
        prefix, separator, tail = chosen.partition(":")
        if separator and (prefix in _MODEL_PREFIXES or prefix.startswith("serving_")):
            provider, chosen = prefix, tail.strip()
        elif chosen.lower().startswith(("gpt", "o1", "o3", "o4", "chatgpt", "text-", "davinci")):
            provider = "openai"
    return {
        "provider": provider,
        "model": chosen or None,
        "model_source": source,
        "legacy_defaults": legacy_defaults,
    }


def resolve_skill_model_execution(
    workspace: Any,
    *,
    executor: Mapping[str, Any] | None,
    input_ref: Mapping[str, Any],
    system_default_model: str | None = None,
    slug: str = "",
    published: bool = False,
) -> ModelExecution | None:
    request = skill_model_request(
        slug, executor, input_ref, system_default_model, published=published
    )
    return resolve_model_execution(workspace, **request) if request else None


async def complete_model(
    execution: ModelExecution,
    prompt: str,
    ctx: dict[str, Any],
    *,
    generation_options: Mapping[str, Any] | None = None,
    stream: bool = True,
    images: tuple[ModelImage, ...] = (),
) -> dict[str, Any]:
    from app.services.evaluation.judge import (
        new_provider_usage_accumulator,
        provider_usage_evidence,
    )

    usage = ctx.setdefault("_provider_usage_v1", new_provider_usage_accumulator())
    if execution.provider == "typesafe" and execution._fallbacks:
        raise ModelExecutionError("typesafe: typed decisions do not support fallbacks.")
    attempts: list[dict[str, Any]] = []
    candidates = (execution, *execution._fallbacks)
    for index, candidate in enumerate(candidates):
        attempt = {**candidate.public(), "dispatch_started": False}
        attempts.append(attempt)
        evidence = {
            **candidate.public(),
            "requested_provider": execution.requested_provider,
            "fallback": index > 0,
            "attempts": attempts,
        }
        ctx["_model_resolution_evidence"] = evidence
        check = ctx.get("_model_policy_check")
        if callable(check):
            try:
                check(candidate)
            except Exception:
                attempt["status"] = "blocked"
                # A denied fallback was never called. Preserve the last actual
                # attempt as effective while recording this refusal alongside it.
                raise
        try:
            output = await _complete_once(
                candidate, prompt, ctx, usage, generation_options, stream, images
            )
        except _DispatchRefused as exc:
            attempt["status"] = "blocked"
            raise exc.cause from None
        except asyncio.CancelledError:
            attempt["status"] = "cancelled"
            raise
        except Exception as exc:
            attempt.update(status="failed", error_code=type(exc).__name__)
            if index == len(candidates) - 1 or ctx.get("_model_stream_started"):
                if isinstance(exc, ModelExecutionError):
                    raise
                if candidate.provider == "typesafe":
                    from app.services.model_plane.typesafe import TypeSafeError

                    if isinstance(exc, TypeSafeError):
                        # The native adapter emits only fixed safe codes.
                        raise
                # SDK errors can include request details. The canonical ledger
                # gets a safe cause; provider logs retain transport diagnostics.
                raise ModelExecutionError(
                    f"{candidate.provider}: generation failed ({type(exc).__name__})."
                ) from exc
            continue
        attempt["status"] = "completed"
        evidence.update(
            returned_model=output["model"],
            returned_model_reported=output["returned_model_reported"],
        )
        output["model_execution"] = evidence
        output.update(provider_usage_evidence(usage))
        return output
    raise ModelExecutionError("No configured model could answer this request.")


def _provider_generation_options(execution, generation_options):
    options = copy.deepcopy(dict(generation_options or {}))
    if execution.provider == "typesafe":
        if set(options) - {"typed_questions", "max_tokens", "timeout_s"} or not isinstance(
            options.get("typed_questions"), dict
        ):
            raise ModelExecutionError("typesafe: explicit typed questions are required.")
        if type(options.get("max_tokens")) is not int or not 1 <= options["max_tokens"] <= 8192:
            raise ModelExecutionError("typesafe: a local output-token provision is required.")
        timeout = options.get("timeout_s", 60)
        if type(timeout) not in {int, float} or not 0 < timeout <= 120:
            raise ModelExecutionError("typesafe: timeout must be between zero and 120 seconds.")
        return options
    if "typed_questions" in options:
        raise ModelExecutionError("Typed questions require a typed-decision provider.")
    if "json_schema" in options:
        from app.services.flow_contracts import validate_schema_definition

        schema = validate_schema_definition(options.pop("json_schema"), field="json_schema")
        if "response_format" in options or "format" in options:
            raise ModelExecutionError(
                "json_schema cannot be combined with a provider-specific format."
            )
        if (
            execution.provider in {"openai", "azure_openai", "huggingface"}
            or execution.artifact_provenance
        ):
            options["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "structured_response", "strict": True, "schema": schema},
            }
        elif execution.provider == "ollama":
            options["format"] = schema
        else:
            raise ModelExecutionError(
                f"{execution.provider}: structured JSON schema generation is not supported."
            )
    if execution.provider == "ollama" and options:
        ollama_options = dict(options.pop("options", {}) or {})
        if options.get("max_tokens") is not None:
            ollama_options["num_predict"] = options.pop("max_tokens")
        if options.get("temperature") is not None:
            ollama_options["temperature"] = options.pop("temperature")
        if ollama_options:
            options["options"] = ollama_options
    return options


async def _complete_once(
    execution, prompt, ctx, usage_accumulator, generation_options, stream, images=()
):
    from app.services.model_usage_transport import context_from_execution

    with context_from_execution(ctx, execution):
        return await _complete_once_scoped(
            execution, prompt, ctx, usage_accumulator, generation_options, stream, images
        )


async def _complete_once_scoped(
    execution, prompt, ctx, usage_accumulator, generation_options, stream, images=()
):
    from app.services.evaluation.judge import normalize_provider_usage, record_provider_usage
    from app.services.model_usage_transport import ProviderCall, output_limit, tracking_active

    native_payload = None
    try:
        options = _provider_generation_options(execution, generation_options)
        if execution.provider == "typesafe":
            from app.services.model_plane import typesafe

            if stream or images:
                raise ModelExecutionError("typesafe: streaming and images are not supported.")
            if (
                not isinstance(execution._api_key, str)
                or not execution._api_key
                or any(not 33 <= ord(char) <= 126 for char in execution._api_key)
                or execution.credential_source == "not_configured"
            ):
                raise ModelExecutionError(
                    "typesafe: connection is not configured. Open Models & Providers."
                )
            native_payload = typesafe.validate_request(
                model=execution.model, state=prompt, questions=options["typed_questions"]
            )
        if "image_parts" in options:
            raise ModelExecutionError("Images require server-resolved ModelImage bytes.")
        if images:
            if (
                execution.provider not in {"openai", "azure_openai"}
                or stream
                or len(images) > 16
                or sum(len(image.data) for image in images) > 32_000_000
            ):
                raise ModelExecutionError("Unsupported vision transport or image limit.")
            options["image_parts"] = [part for image in images for part in image.content_parts()]
    except Exception as exc:
        raise _DispatchRefused(exc) from exc
    client = (
        None
        if execution.provider == "typesafe"
        else (
            build_model_client(execution, no_retries=True)
            if ctx.get("_model_no_retries") is True or tracking_active()
            else build_model_client(execution)
        )
    )
    sink = ctx.get("token_sink") if stream else None
    returned_model = execution.model
    returned_model_reported = False
    result = None
    evidence = ctx["_model_resolution_evidence"]
    if execution.provider == "huggingface" or execution.artifact_provenance:
        try:
            evidence["huggingface"] = await client.prepare(execution.model)
            evidence["attempts"][-1]["huggingface"] = dict(evidence["huggingface"])
        except Exception as exc:
            raise _DispatchRefused(exc) from exc
    before_dispatch = ctx.get("_model_before_dispatch")
    atomic_admission = ctx.get("_model_admission_hook")
    neutral_options = copy.deepcopy(dict(generation_options or {}))
    # A legacy reservation callback is deliberately not qualified for shared
    # hard budgets: it must first migrate to the same admission transaction.
    call = ProviderCall(
        execution.provider,
        execution.model,
        native_payload if native_payload is not None else {"prompt": prompt, "options": options},
        # Jev's local Judge provision is not an API-enforced output cap. Its
        # native transport independently qualifies monetary admission using
        # the exact wire payload and the provider's fixed input context limit.
        output_token_bound=None if native_payload is not None else output_limit(options),
        qualified=not callable(before_dispatch) or callable(atomic_admission),
        operation="typed_decisions" if execution.provider == "typesafe" else "completion",
        admission_hook=(
            lambda session, record: atomic_admission(
                session, record, execution, prompt, neutral_options
            )
        )
        if callable(atomic_admission)
        else None,
        after_admission=ctx.get("_model_admission_committed")
        if callable(atomic_admission)
        else None,
        before_dispatch=(lambda: before_dispatch(execution, prompt, neutral_options))
        if callable(before_dispatch) and not callable(atomic_admission)
        else None,
    )
    try:
        call.__enter__()
    except Exception as exc:
        raise _DispatchRefused(exc) from exc
    evidence["dispatch_started"] = True
    evidence["attempts"][-1]["dispatch_started"] = True
    ctx["_model_execution_evidence"] = evidence
    try:
        if execution.provider == "typesafe":
            from app.services.model_plane import typesafe

            try:
                result = await typesafe.evaluate(
                    api_key=execution._api_key,
                    model=native_payload["model"],
                    state=native_payload["state"],
                    questions=native_payload["questions"],
                    timeout_s=options.get("timeout_s", 60),
                )
            except typesafe.TypeSafeError as exc:
                # A rejected response can still contain measured provider
                # usage. Settle it without accepting its decision payload.
                result = {"usage": exc.usage, "model": exc.returned_model}
                call.observe(result)
                raise
            call.observe(result)
            ctx["_model_response_usage"] = result.get("usage", {})
            completion = ""
            returned_model = result["model"]
            returned_model_reported = result.get("returned_model_reported") is True
        elif callable(sink):
            parts = []
            async for chunk in client.stream(model=execution.model, prompt=prompt, **options):
                delta = chunk.get("delta") or chunk.get("content") or chunk.get("response") or ""
                if delta:
                    ctx["_model_stream_started"] = True
                    parts.append(delta)
                    sink(delta)
                call.observe(chunk)
                counters = normalize_provider_usage(chunk)
                if counters is not None:
                    result = {"usage": counters}
                returned_model = _text(chunk.get("model")) or returned_model
                returned_model_reported = returned_model_reported or bool(_text(chunk.get("model")))
            completion = "".join(parts)
        else:
            result = await client.generate(model=execution.model, prompt=prompt, **options)
            call.observe(result)
            ctx["_model_response_usage"] = result.get("usage", {})
            completion = (
                result.get("content") or result.get("response") or result.get("completion") or ""
            )
            returned_model = _text(result.get("model")) or returned_model
            returned_model_reported = bool(_text(result.get("model")))
    finally:
        import sys

        call.__exit__(*sys.exc_info())
        # Configuration failures before dispatch are not provider calls. A
        # failed transport after dispatch is a call with unavailable counters.
        record_provider_usage(
            usage_accumulator, result, provider=execution.provider, model=execution.model
        )
    return {
        "completion": completion,
        "model": returned_model,
        "returned_model_reported": returned_model_reported,
        **(
            {"typed_answers": result["answers"]}
            if execution.provider == "typesafe" and isinstance(result, dict)
            else {}
        ),
        **(
            {"output_truncated": True}
            if isinstance(result, dict) and result.get("output_truncated") is True
            else {}
        ),
        **({"streamed": True} if callable(sink) else {}),
    }


def routable_runtime_providers(workspace) -> set[str]:
    from app.services.model_plane.providers import RUNTIME_PROVIDERS
    from app.services.model_plane.registration import list_routable_providers

    workspace_id = getattr(workspace, "id", None)
    return set(RUNTIME_PROVIDERS) | {
        entry["key"]
        for entry in list_routable_providers()
        if entry.get("artifact_id")
        and entry.get("workspace_id") == workspace_id
        and entry.get("status") == "active"
    }


def _resolve_serving_execution(workspace, provider, model, source, requested, routing):
    from app.services.model_plane.registration import get_routable_provider, route_base_url
    from app.services.model_plane.serving_nodes import get_node

    metadata = get_routable_provider(provider)
    workspace_id = getattr(workspace, "id", None)
    if (
        not workspace_id
        or not metadata
        or not metadata.get("artifact_id")
        or metadata.get("workspace_id") != workspace_id
        or metadata.get("status") != "active"
    ):
        raise ModelExecutionError("This artifact provider is not available to the workspace.")
    node = get_node(metadata["node"], workspace=workspace)
    if (
        not node
        or not node.token
        or route_base_url(node.base_url, metadata) != metadata.get("openai_base_url")
    ):
        raise ModelExecutionError(
            "The artifact serving endpoint is not configured for this workspace."
        )
    chosen = _text(model) or metadata["model"]
    if chosen.startswith(provider + ":"):
        chosen = chosen[len(provider) + 1 :]
    if chosen != metadata.get("model"):
        raise ModelExecutionError("Choose the model served by this artifact deployment.")
    provenance = {
        key: metadata.get(key)
        for key in (
            "artifact_id",
            "revision",
            "repo_id",
            "variant",
            "runtime_version",
            "deployment_id",
        )
    }
    fallbacks = tuple(
        resolve_model_execution(workspace, provider=item)
        for item in dict.fromkeys(routing.get("fallback_chain") or [])
        if item not in {provider, "workspace"}
    )
    return ModelExecution(
        provider=provider,
        model=chosen,
        credential_source="workspace",
        model_source=source,
        _api_key="local",
        _endpoint=metadata["openai_base_url"],
        _workspace_id=workspace_id,
        requested_provider=requested,
        _fallbacks=fallbacks,
        artifact_provenance=provenance,
    )
