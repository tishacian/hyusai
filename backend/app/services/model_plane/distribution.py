"""Workspace-scoped routing distribution from the SkillInvocation ledger."""

from __future__ import annotations

from collections import defaultdict
import math
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
        "azure_foundry",
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
                provider = head.lower()
                return provider, tail.strip()
    low = text.lower()
    if low.startswith(("gpt", "o1", "o3", "o4", "chatgpt", "text-", "davinci")):
        return "openai", text
    if low.startswith("claude"):
        return "anthropic", text
    if low.startswith("gemini"):
        return "gemini", text
    return "unknown", text


def _model_identity(inv: SkillInvocation) -> tuple[str, str, str] | None:
    trace = inv.trace if isinstance(inv.trace, dict) else {}
    output = inv.output_ref if isinstance(inv.output_ref, dict) else {}
    evidence = trace.get("model_execution")
    if isinstance(evidence, dict) and evidence.get("provider") and evidence.get("model"):
        return str(evidence["provider"]), str(evidence.get("returned_model") or evidence["model"]), "runtime_evidence"
    raw = trace.get("effective_model") or output.get("model")
    if not isinstance(raw, str) or not raw.strip():
        return None
    provider, model = split_effective_model(raw)
    return provider, model, "legacy_inferred"


def _summary(rows: list[SkillInvocation]) -> Dict[str, Any]:
    amounts: dict[str, float] = defaultdict(float)
    sources: set[str] = set()
    cost_samples = 0
    latencies = []
    evidence = []
    run_ids = []
    for inv in rows:
        metrics = inv.metrics if isinstance(inv.metrics, dict) else {}
        cost_evidence = metrics.get("cost_evidence") or {}
        currency = cost_evidence.get("currency") if isinstance(cost_evidence, dict) else None
        amount = inv.cost
        if (inv.cost_measured is True and isinstance(amount, (float, int)) and not isinstance(amount, bool)
                and math.isfinite(amount) and amount >= 0 and isinstance(currency, str) and currency):
            method = cost_evidence.get("method")
            state = cost_evidence.get("state")
            source = "skill_catalog" if method == "catalog_unit_price" else (
                "provider" if state == "measured" or method == "provider_measurement" else None
            )
            if source:
                amounts[currency.upper()] += amount
                sources.add(source)
                cost_samples += 1
        if isinstance(inv.latency_ms, (float, int)) and math.isfinite(inv.latency_ms) and inv.latency_ms >= 0:
            latencies.append(inv.latency_ms)
        if len(evidence) < 20:
            evidence.append({"run_id": inv.run_id, "invocation_id": inv.id})
        if inv.run_id not in run_ids and len(run_ids) < 20:
            run_ids.append(inv.run_id)
    unknown = len(rows) - cost_samples
    currency = next(iter(amounts)) if len(amounts) == 1 else None
    source = next(iter(sources)) if len(sources) == 1 else "mixed" if sources else None
    state = (
        "not_measured" if not amounts else "mixed_currencies" if len(amounts) > 1 else
        "partial" if unknown else "calculated" if source == "skill_catalog" else
        "measured" if source == "provider" else "mixed"
    )
    return {
        "invocations": len(rows),
        "cost": amounts[currency] if currency else None,
        "currency": currency, "cost_state": state, "cost_source": source,
        "cost_samples": cost_samples, "unknown_costs": unknown,
        "costs_by_currency": dict(amounts),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "run_ids": run_ids, "invocation_ids": [item["invocation_id"] for item in evidence],
        "evidence": evidence, "evidence_truncated": len(rows) > len(evidence),
    }


def get_distribution(
    db: DBSession,
    *,
    workspace_id: str,
    window: str = "7d",
    workspace: Any = None,
    user: Any = None,
) -> Dict[str, Any]:
    """Project model execution evidence and attributable costs from one ledger.

    Unknown/default costs stay absent. Different currencies are never summed.
    API callers supply the principal for the canonical Run and invocation read
    guards; internal aggregation callers retain the existing scoped interface.
    """
    since = datetime.utcnow() - parse_window(window)
    rows = (
        db.query(SkillInvocation)
        .join(Run, Run.id == SkillInvocation.run_id)
        .filter(Run.workspace_id == workspace_id)
        .filter(SkillInvocation.started_at >= since)
        .order_by(SkillInvocation.started_at.desc(), SkillInvocation.id)
        .all()
    )
    if (workspace is None) != (user is None):
        raise ValueError("Both workspace and user are required for authorized distribution")
    if workspace is not None:
        from app.services.run_access import readable_runs, readable_skill_invocations_for_runs
        runs = db.query(Run).filter(Run.workspace_id == workspace_id, Run.id.in_({row.run_id for row in rows})).all()
        visible = readable_runs(db, runs=runs, user=user, workspace=workspace)
        rows = readable_skill_invocations_for_runs(db, invocations=rows, runs=visible, user=user, workspace=workspace)
    by_model: dict[tuple[str, str], list[SkillInvocation]] = defaultdict(list)
    by_provider: dict[str, list[SkillInvocation]] = defaultdict(list)
    model_sources: dict[tuple[str, str], set[str]] = defaultdict(set)
    routed = []
    for inv in rows:
        identity = _model_identity(inv)
        if identity is None:
            continue
        provider, model, source = identity
        by_model[(provider, model)].append(inv)
        by_provider[provider].append(inv)
        model_sources[(provider, model)].add(source)
        routed.append(inv)
    total = len(routed)
    models = [
        {"provider": provider, "model": model, **_summary(group),
         "model_sources": sorted(model_sources[(provider, model)]),
         "share": round(len(group) / total, 4)}
        for (provider, model), group in by_model.items()
    ]
    providers = [
        {"provider": provider, **_summary(group), "share": round(len(group) / total, 4)}
        for provider, group in by_provider.items()
    ]
    return {
        "source": "skill_invocations", "window": window.strip().lower(),
        "since": since.isoformat() + "Z", "totals": _summary(routed),
        "excluded_without_model_evidence": len(rows) - total,
        "by_model": sorted(models, key=lambda row: (-row["invocations"], row["provider"], row["model"])),
        "by_provider": sorted(providers, key=lambda row: (-row["invocations"], row["provider"])),
    }
