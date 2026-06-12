"""A/B comparison of the golden retrieval batch under two flag sets.

Runs each golden case against the live vector store twice — baseline flags vs
variant flags — and compares pass-rate and matched sources. This is the
activation gate for the RAGGER refinements (adaptive fusion, MMR, compression,
prompt classifier): a variant must reach pass-rate >= baseline before its flag
ships enabled.

    cd backend
    python -m scripts.golden_flag_ab --flags rag_mmr_enabled=true
    python -m scripts.golden_flag_ab --batch app/resources/retrieval_golden/andritz_spl_multilingual.json \
        --flags rag_adaptive_fusion_enabled=true,rag_compression_enabled=true

Requires a reachable vector store with the golden collections indexed.
"""
from __future__ import annotations

import argparse
import asyncio
from typing import Any

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.services.rag.context import retrieve_rag_context
from app.services.rag.retrieval_golden import (
    evaluate_retrieval_golden_case,
    load_retrieval_golden_cases,
)


def _workspace(slug: str) -> Workspace:
    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.slug == slug).first()
        if not workspace:
            raise SystemExit(f"Workspace not found: {slug}")
        return workspace
    finally:
        db.close()


def _parse_flags(raw: str | None) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        key, _, value = item.partition("=")
        text = value.strip().lower()
        if text in {"true", "false"}:
            overrides[key.strip()] = text == "true"
        else:
            try:
                overrides[key.strip()] = float(value) if "." in value else int(value)
            except ValueError:
                overrides[key.strip()] = value
    return overrides


async def _run_batch(cases, overrides: dict[str, Any], workspace: Workspace) -> dict[str, dict[str, Any]]:
    # The retrieval-context cache key does not include feature flags, so a
    # variant run would silently reuse the baseline's cached contexts and the
    # comparison would be vacuous. Disable it unless explicitly overridden.
    overrides = {"rag_context_cache_enabled": False, **overrides}
    saved = {key: getattr(settings, key) for key in overrides}
    for key, value in overrides.items():
        setattr(settings, key, value)
    results: dict[str, dict[str, Any]] = {}
    try:
        for case in cases:
            try:
                request = case.to_request()
                request.update(
                    {
                        "workspace_id": workspace.id,
                        "workspace_slug": workspace.slug,
                        "retrieval_profile": request.get("retrieval_profile") or "chat",
                    }
                )
                context = await retrieve_rag_context(request)
                results[case.id] = evaluate_retrieval_golden_case(case, context)
            except Exception as exc:  # noqa: BLE001 - report, keep evaluating
                results[case.id] = {"id": case.id, "passed": False, "error": str(exc)}
    finally:
        for key, value in saved.items():
            setattr(settings, key, value)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", default=None, help="Golden batch JSON (default: andritz_spl_dense)")
    parser.add_argument("--flags", required=True, help="Variant overrides, e.g. rag_mmr_enabled=true,rag_mmr_lambda=0.6")
    parser.add_argument("--baseline-flags", default="", help="Optional baseline overrides")
    parser.add_argument("--workspace", default="andritz", help="Workspace slug owning the golden collections")
    args = parser.parse_args()

    cases = load_retrieval_golden_cases(args.batch)
    workspace = _workspace(args.workspace)
    baseline_overrides = _parse_flags(args.baseline_flags)
    variant_overrides = _parse_flags(args.flags)

    async def _run() -> tuple[dict, dict]:
        baseline = await _run_batch(cases, baseline_overrides, workspace)
        variant = await _run_batch(cases, variant_overrides, workspace)
        return baseline, variant

    baseline, variant = asyncio.run(_run())

    regressions = 0
    improvements = 0
    for case in cases:
        b = baseline.get(case.id, {})
        v = variant.get(case.id, {})
        marker = "="
        if b.get("passed") and not v.get("passed"):
            marker = "REGRESSION"
            regressions += 1
        elif not b.get("passed") and v.get("passed"):
            marker = "improved"
            improvements += 1
        print(
            f"{case.id:48s} baseline={'PASS' if b.get('passed') else 'fail':4s} "
            f"variant={'PASS' if v.get('passed') else 'fail':4s} "
            f"distinct_docs={b.get('distinct_documents')}->{v.get('distinct_documents')} {marker}"
        )
        if marker == "REGRESSION":
            print(f"    missing_sources={v.get('missing_sources')} missing_terms={v.get('missing_evidence_terms')}")

    base_rate = sum(1 for r in baseline.values() if r.get("passed"))
    var_rate = sum(1 for r in variant.values() if r.get("passed"))
    print(
        f"\nbaseline {base_rate}/{len(cases)}  variant {var_rate}/{len(cases)}  "
        f"improvements={improvements} regressions={regressions}"
    )
    print("VERDICT:", "OK to enable" if var_rate >= base_rate and regressions == 0 else "DO NOT enable")


if __name__ == "__main__":
    main()
