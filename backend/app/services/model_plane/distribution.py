"""Workspace-scoped routing distribution from the SkillInvocation ledger."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from app.models.run import Run, SkillInvocation

_WINDOWS = {
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

_KNOWN_PROVIDERS = frozenset(
    {
        "ollama",
        "openai",
        "azure",
        "azure_openai",
        "anthropic",
        "openrouter",
        "gemini",
        "vllm",
        "llamacpp",
        "lmstudio",
        "lmdeploy",
        "sglang",
    }
)


def parse_window(window: str) -> timedelta:
    key = (window or "7d").strip().lower()
    if key not in _WINDOWS:
        raise ValueError("window must be '7d' or '30d'")
    return _WINDOWS[key]


def split_effective_model(raw: Optional[str]) -> tuple[str, str]:
    """Infer (provider, model) from ``trace.effective_model``."""
    text = (raw or "").strip()
    if not text:
        return ("unknown", "unknown")
    for sep in (":", "/"):
        if sep in text:
            head, tail = text.split(sep, 1)
            if head.lower() in _KNOWN_PROVIDERS and tail.strip():
                provider = "azure_openai" if head.lower() == "azure" else head.lower()
                return provider, tail.strip()
    low = text.lower()
    if low.startswith(("gpt", "o1", "o3", "o4", "chatgpt", "text-", "davinci")):
        return "openai", text
    if low.startswith("claude"):
        return "anthropic", text
    if low.startswith("gemini"):
        return "gemini", text
    return "unknown", text


def get_distribution(
    db: DBSession,
    *,
    workspace_id: str,
    window: str = "7d",
) -> Dict[str, Any]:
    """Aggregate invocations by provider/model over the requested window."""
    delta = parse_window(window)
    since = datetime.utcnow() - delta

    rows = (
        db.query(SkillInvocation)
        .join(Run, Run.id == SkillInvocation.run_id)
        .filter(Run.workspace_id == workspace_id)
        .filter(SkillInvocation.started_at >= since)
        .all()
    )

    buckets: Dict[tuple[str, str], Dict[str, Any]] = {}
    totals = {"invocations": 0, "cost": 0.0, "latency_ms_sum": 0.0, "latency_samples": 0}

    for inv in rows:
        trace = inv.trace if isinstance(inv.trace, dict) else {}
        provider, model = split_effective_model(trace.get("effective_model"))
        key = (provider, model)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "provider": provider,
                "model": model,
                "invocations": 0,
                "cost": 0.0,
                "latency_ms_sum": 0.0,
                "latency_samples": 0,
            }
            buckets[key] = bucket
        bucket["invocations"] += 1
        cost = float(inv.cost or 0.0)
        bucket["cost"] += cost
        totals["invocations"] += 1
        totals["cost"] += cost
        if inv.latency_ms is not None:
            latency = float(inv.latency_ms)
            bucket["latency_ms_sum"] += latency
            bucket["latency_samples"] += 1
            totals["latency_ms_sum"] += latency
            totals["latency_samples"] += 1

    items: List[Dict[str, Any]] = []
    for bucket in buckets.values():
        samples = bucket["latency_samples"]
        items.append(
            {
                "provider": bucket["provider"],
                "model": bucket["model"],
                "invocations": bucket["invocations"],
                "cost": round(bucket["cost"], 6),
                "avg_latency_ms": round(bucket["latency_ms_sum"] / samples, 1) if samples else None,
                "share": round(bucket["invocations"] / totals["invocations"], 4)
                if totals["invocations"]
                else 0.0,
            }
        )
    items.sort(key=lambda row: (-row["invocations"], row["provider"], row["model"]))

    by_provider: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"provider": "", "invocations": 0, "cost": 0.0}
    )
    for item in items:
        agg = by_provider[item["provider"]]
        agg["provider"] = item["provider"]
        agg["invocations"] += item["invocations"]
        agg["cost"] = round(agg["cost"] + item["cost"], 6)

    provider_items = sorted(
        by_provider.values(),
        key=lambda row: (-row["invocations"], row["provider"]),
    )
    for agg in provider_items:
        agg["share"] = (
            round(agg["invocations"] / totals["invocations"], 4) if totals["invocations"] else 0.0
        )

    total_samples = totals["latency_samples"]
    return {
        "window": window if window in _WINDOWS else "7d",
        "since": since.isoformat() + "Z",
        "totals": {
            "invocations": totals["invocations"],
            "cost": round(totals["cost"], 6),
            "avg_latency_ms": round(totals["latency_ms_sum"] / total_samples, 1)
            if total_samples
            else None,
        },
        "by_model": items,
        "by_provider": provider_items,
    }
