"""Single model-routing resolver shared by every LLM call site.

The platform has one question to answer before it talks to a model: *which
provider and which model?*  Historically four places answered it on their own
(the classic ``/chat`` orchestrator, ``ModelRouter``, the workspace LLM portal
and a handful of feature-specific constants).  This module is the one answer.

Resolution order (first hit wins)::

    1. explicit model on the request / DAG node   -> source "explicit"
    2. System.default_model (operator pin)        -> source "system"
    3. workspace tier table  routing.tiers[tier]  -> source "tier"
    4. workspace routing.default_model            -> source "workspace"
    5. Settings.default_model                     -> source "global"

Every answer is then bounded by the membrane ``allowed_models`` list: a model
outside the list is downgraded to the first allowed tier (or the first allowed
model) and the downgrade is reported in ``ModelChoice.reason``.  The membrane
capability gate in the run engine stays as the backstop.

The resolver is pure: it never opens a DB session or a network connection.
Callers pass either a ``Workspace`` row or a serialisable ``snapshot`` (the run
engine seeds ``ctx["model_routing"]`` once per run so skills never re-read the
workspace).  With no workspace routing and no tiers configured the answer is
byte-identical to the pre-resolver behaviour (``settings.default_provider`` +
``settings.default_model``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.workspace import Workspace

MODEL_TIERS: tuple[str, ...] = ("fast", "balanced", "strong")

# Retrieval lanes (agentic planner ``mode`` / classic ``latency_profile``) are a
# different axis from model tiers; this is the default bridge between the two.
LANE_TO_TIER: dict[str, str] = {
    "fast": "fast",
    "balanced": "balanced",
    "deep": "strong",
    "multihop": "strong",
}

# Answer profiles that deserve the strong tier on the classic path (comparison,
# cross-document aggregation, multi-hop).  Everything else stays balanced.
STRONG_TIER_PROFILES: frozenset[str] = frozenset(
    {"comparison", "transversal_inventory", "multi_hop", "table_extract"}
)

KNOWN_PROVIDERS: frozenset[str] = frozenset(
    {
        "ollama",
        "openai",
        "azure",
        "azure_openai",
        "azure_foundry",
        "anthropic",
        "vllm",
        "openrouter",
        "gemini",
        "llamacpp",
        "lmstudio",
        "lmdeploy",
        "sglang",
    }
)

_OPENAI_PREFIXES = ("gpt", "o1", "o3", "o4", "chatgpt", "text-", "davinci")


def is_known_provider(provider: str) -> bool:
    head = str(provider or "").strip().lower()
    return bool(head) and (head in KNOWN_PROVIDERS or head.startswith("serving_"))


def parse_model_spec(spec: Optional[str], *, default_provider: Optional[str] = None) -> dict[str, str]:
    """Map ``provider:model`` / ``provider/model`` / bare model to router prefs.

    Same contract as the historical ``wrappers._resolve_model_preferences``:
    an explicit known prefix wins (``azure`` is served by the OpenAI client),
    the gpt/o-series infer OpenAI, anything else takes ``default_provider``.
    """
    from app.core.config import settings

    provider_default = str(default_provider or settings.default_provider or "ollama")
    raw = str(spec or "").strip()
    if not raw:
        return {"provider": provider_default, "model": str(settings.default_model or "")}
    for sep in (":", "/"):
        if sep in raw:
            head, tail = raw.split(sep, 1)
            head_l = head.strip().lower()
            if is_known_provider(head_l) and tail.strip():
                provider = "openai" if head_l == "azure" else head_l
                return {"provider": provider, "model": tail.strip()}
    if raw.lower().startswith(_OPENAI_PREFIXES):
        return {"provider": "openai", "model": raw}
    return {"provider": provider_default, "model": raw}


def normalise_tiers(raw: Any) -> dict[str, str]:
    """Validate a ``{tier: "provider:model"}`` mapping; raises ``ValueError``."""
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("tiers must be an object keyed by fast/balanced/strong")
    tiers: dict[str, str] = {}
    for key, value in raw.items():
        tier = str(key or "").strip().lower()
        if tier not in MODEL_TIERS:
            raise ValueError(f"unknown model tier {key!r}; expected one of {', '.join(MODEL_TIERS)}")
        spec = str(value or "").strip()
        if not spec:
            continue
        for sep in (":", "/"):
            if sep in spec:
                head, tail = spec.split(sep, 1)
                if not is_known_provider(head):
                    raise ValueError(f"tier {tier!r}: unknown provider {head!r}")
                if not tail.strip():
                    raise ValueError(f"tier {tier!r}: model name is required after {head!r}")
                break
        tiers[tier] = spec
    return tiers


def coerce_tier(value: Any, default: Optional[str] = None) -> Optional[str]:
    tier = str(value or "").strip().lower()
    if tier in MODEL_TIERS:
        return tier
    if tier in LANE_TO_TIER:
        return LANE_TO_TIER[tier]
    return default


def tier_for_lane(lane: Any, *, has_sub_queries: bool = False) -> str:
    if has_sub_queries:
        return LANE_TO_TIER["multihop"]
    return LANE_TO_TIER.get(str(lane or "").strip().lower(), "balanced")


def tier_for_answer_profile(profile: Any) -> str:
    return "strong" if str(profile or "").strip().lower() in STRONG_TIER_PROFILES else "balanced"


@dataclass(frozen=True)
class ModelChoice:
    provider: str
    model: str
    source: str
    tier: Optional[str] = None
    fallback_chain: tuple[str, ...] = ()
    reason: str = ""
    requested: Optional[str] = None

    @property
    def spec(self) -> str:
        return f"{self.provider}:{self.model}"

    def preferences(self) -> dict[str, str]:
        return {"provider": self.provider, "model": self.model}

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "spec": self.spec,
            "source": self.source,
            "tier": self.tier,
            "fallback_chain": list(self.fallback_chain),
            "reason": self.reason,
            "requested": self.requested,
        }


@dataclass(frozen=True)
class RoutingSnapshot:
    """Serialisable view of a workspace's routing config plus governance."""

    default_provider: str
    default_model: str
    fallback_chain: tuple[str, ...]
    tiers: dict[str, str] = field(default_factory=dict)
    allowed_models: tuple[str, ...] = ()
    source: str = "global"

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_provider": self.default_provider,
            "default_model": self.default_model,
            "fallback_chain": list(self.fallback_chain),
            "tiers": dict(self.tiers),
            "allowed_models": list(self.allowed_models),
            "source": self.source,
        }

    @classmethod
    def from_mapping(cls, raw: Any) -> "RoutingSnapshot":
        from app.core.config import settings

        data = raw if isinstance(raw, Mapping) else {}
        provider = str(data.get("default_provider") or settings.default_provider or "openai")
        model = str(data.get("default_model") or settings.default_model or "")
        chain_raw = data.get("fallback_chain")
        chain = tuple(str(x) for x in chain_raw if str(x).strip()) if isinstance(chain_raw, list) else ()
        try:
            tiers = normalise_tiers(data.get("tiers"))
        except ValueError:
            tiers = {}
        allowed_raw = data.get("allowed_models")
        allowed = (
            tuple(str(x).strip() for x in allowed_raw if str(x).strip())
            if isinstance(allowed_raw, (list, tuple))
            else ()
        )
        return cls(
            default_provider=provider,
            default_model=model,
            fallback_chain=chain,
            tiers=tiers,
            allowed_models=allowed,
            source=str(data.get("source") or "global"),
        )


def global_tiers() -> dict[str, str]:
    """Deployment-level tier table from ``Settings`` (empty values are unset)."""
    from app.core.config import settings

    out: dict[str, str] = {}
    for tier in MODEL_TIERS:
        value = str(getattr(settings, f"model_tier_{tier}", "") or "").strip()
        if value:
            out[tier] = value
    return out


def routing_snapshot(
    workspace: Optional["Workspace"],
    *,
    allowed_models: Optional[Iterable[str]] = None,
) -> RoutingSnapshot:
    """Read the workspace LLM portal routing once (no DB round-trip)."""
    from app.services.model_plane import workspace_config

    if workspace is not None:
        routing = workspace_config.get_routing(workspace)
    else:
        from app.core.config import settings

        routing = {
            "default_provider": settings.default_provider or "openai",
            "default_model": settings.default_model or "",
            "fallback_chain": [settings.default_provider or "openai", "ollama"]
            if (settings.default_provider or "openai") != "ollama"
            else ["ollama"],
            "tiers": global_tiers(),
            "source": "global",
        }
    allowed = tuple(str(x).strip() for x in (allowed_models or ()) if str(x).strip())
    return RoutingSnapshot(
        default_provider=str(routing.get("default_provider") or "openai"),
        default_model=str(routing.get("default_model") or ""),
        fallback_chain=tuple(str(x) for x in routing.get("fallback_chain") or ()),
        tiers=dict(routing.get("tiers") or {}),
        allowed_models=allowed,
        source=str(routing.get("source") or "global"),
    )


def model_allowed(prefs: Mapping[str, str], allowed_models: Iterable[str]) -> bool:
    """Empty allow-list = unrestricted; otherwise match model or provider:model."""
    allowed = [str(x).strip() for x in allowed_models if str(x).strip()]
    if not allowed:
        return True
    model = str(prefs.get("model") or "").strip()
    spec = f"{prefs.get('provider')}:{model}"
    for entry in allowed:
        if entry == model or entry == spec:
            return True
        parsed = parse_model_spec(entry, default_provider=prefs.get("provider"))
        if parsed["model"] == model and parsed["provider"] == prefs.get("provider"):
            return True
    return False


def _candidates(
    *,
    snapshot: RoutingSnapshot,
    explicit_model: Optional[str],
    system_default_model: Optional[str],
    tier_hint: Optional[str],
) -> list[tuple[str, dict[str, str], Optional[str]]]:
    """Ordered ``(source, prefs, tier)`` candidates before governance."""
    out: list[tuple[str, dict[str, str], Optional[str]]] = []
    provider_default = snapshot.default_provider
    if explicit_model and str(explicit_model).strip():
        out.append(("explicit", parse_model_spec(explicit_model, default_provider=provider_default), tier_hint))
    if system_default_model and str(system_default_model).strip():
        out.append(("system", parse_model_spec(system_default_model, default_provider=provider_default), tier_hint))
    tier = coerce_tier(tier_hint)
    if tier and snapshot.tiers.get(tier):
        out.append(("tier", parse_model_spec(snapshot.tiers[tier], default_provider=provider_default), tier))
    if snapshot.source == "workspace" and snapshot.default_model:
        out.append(("workspace", parse_model_spec(snapshot.default_model, default_provider=provider_default), tier))
    out.append(("global", parse_model_spec(snapshot.default_model or None, default_provider=provider_default), tier))
    return out


def resolve_model(
    *,
    workspace: Optional["Workspace"] = None,
    snapshot: Any = None,
    system_default_model: Optional[str] = None,
    tier_hint: Optional[str] = None,
    explicit_model: Optional[str] = None,
    allowed_models: Optional[Iterable[str]] = None,
) -> ModelChoice:
    """Pick the provider/model for one call.  Pure; never raises."""
    if isinstance(snapshot, RoutingSnapshot):
        snap = snapshot
    elif snapshot is not None:
        snap = RoutingSnapshot.from_mapping(snapshot)
    else:
        snap = routing_snapshot(workspace)
    allowed = tuple(
        str(x).strip()
        for x in (allowed_models if allowed_models is not None else snap.allowed_models)
        if str(x).strip()
    )
    # An explicit model equal to the System pin is the pin, not a request.
    if (
        explicit_model
        and system_default_model
        and str(explicit_model).strip() == str(system_default_model).strip()
    ):
        explicit_model = None

    candidates = _candidates(
        snapshot=snap,
        explicit_model=explicit_model,
        system_default_model=system_default_model,
        tier_hint=tier_hint,
    )
    source, prefs, tier = candidates[0]
    requested = f"{prefs['provider']}:{prefs['model']}"
    chain = _fallback_chain(snap, prefs["provider"])
    if model_allowed(prefs, allowed):
        return ModelChoice(
            provider=prefs["provider"],
            model=prefs["model"],
            source=source,
            tier=tier,
            fallback_chain=chain,
            requested=requested,
        )

    # Governance downgrade: first allowed candidate in order, then the tier
    # table in a sensible order, then the allow-list itself.
    for cand_source, cand_prefs, cand_tier in candidates[1:]:
        if model_allowed(cand_prefs, allowed):
            return ModelChoice(
                provider=cand_prefs["provider"],
                model=cand_prefs["model"],
                source=cand_source,
                tier=cand_tier,
                fallback_chain=_fallback_chain(snap, cand_prefs["provider"]),
                reason=f"model_not_allowed_downgraded:{requested}",
                requested=requested,
            )
    order = [t for t in (coerce_tier(tier_hint), "balanced", "strong", "fast") if t]
    for cand_tier in dict.fromkeys(order):
        spec = snap.tiers.get(cand_tier)
        if not spec:
            continue
        cand_prefs = parse_model_spec(spec, default_provider=snap.default_provider)
        if model_allowed(cand_prefs, allowed):
            return ModelChoice(
                provider=cand_prefs["provider"],
                model=cand_prefs["model"],
                source="tier",
                tier=cand_tier,
                fallback_chain=_fallback_chain(snap, cand_prefs["provider"]),
                reason=f"model_not_allowed_downgraded:{requested}",
                requested=requested,
            )
    first = parse_model_spec(allowed[0], default_provider=snap.default_provider)
    return ModelChoice(
        provider=first["provider"],
        model=first["model"],
        source="allowed_models",
        tier=coerce_tier(tier_hint),
        fallback_chain=_fallback_chain(snap, first["provider"]),
        reason=f"model_not_allowed_downgraded:{requested}",
        requested=requested,
    )


def _fallback_chain(snapshot: RoutingSnapshot, provider: str) -> tuple[str, ...]:
    chain = [p for p in snapshot.fallback_chain if p]
    if not chain:
        chain = [provider]
        if "ollama" not in chain:
            chain.append("ollama")
    elif provider not in chain:
        chain = [provider, *chain]
    return tuple(dict.fromkeys(chain))
