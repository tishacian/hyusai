"""Offline eval of the Bayesian prompt-type classifier against golden labels.

Zero LLM, zero Qdrant. Reuses the hard-intent golden cases (and any other
batch carrying ``expected_prompt_type``) as ground truth and scores the FAST
(patterns-only) classifier — the path on the fast profile and the one a few
ms cheaper than the full classifier. With ``--full`` it also runs the
patterns+coherence classifier for cases marked ``requires_coherence`` (needs a
reachable embedder, so not strictly offline).

    cd backend
    python -m scripts.golden_classifier_eval
    python -m scripts.golden_classifier_eval --batch app/resources/retrieval_golden/andritz_spl_hard_intents.json
    python -m scripts.golden_classifier_eval --min-accuracy 0.8

Exits non-zero when strict accuracy (ambiguous cases excluded) drops below the
threshold, so it can gate CI.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from pathlib import Path

from app.services.rag.retrieval_golden import (
    evaluate_prompt_type_case,
    evaluate_prompt_type_case_full,
    load_retrieval_golden_cases,
)

_DEFAULT_BATCHES = [
    "app/resources/retrieval_golden/andritz_spl_hard_intents.json",
]
_TYPES = ["factual", "analytical", "comparative", "causal", "hypothetical"]


def _confusion(results: list[dict]) -> None:
    # rows = expected, cols = predicted
    matrix: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        expected = r.get("expected_prompt_type") or "(none)"
        matrix[expected][r["predicted"]] += 1
    cols = _TYPES
    header = "expected \\ pred   " + " ".join(f"{c[:5]:>6s}" for c in cols)
    print(header)
    for expected in _TYPES + ["(none)"]:
        if expected not in matrix:
            continue
        row = matrix[expected]
        cells = " ".join(f"{row.get(c, 0):>6d}" for c in cols)
        print(f"{expected:16s} {cells}")


def _report(label: str, results: list[dict], *, min_accuracy: float) -> bool:
    strict = [r for r in results if not r["ambiguous"] and r["correct"] is not None]
    ambiguous = [r for r in results if r["ambiguous"]]
    correct = sum(1 for r in strict if r["correct"])
    total = len(strict)
    accuracy = correct / total if total else 1.0

    print(f"\n===== {label}: {correct}/{total} strict = {accuracy:.1%} "
          f"(min {min_accuracy:.0%}) =====")
    print("\nConfusion (strict cases):")
    _confusion(strict)

    print("\nPer-type accuracy:")
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in strict:
        by_type[r["expected_prompt_type"]].append(r)
    for ptype in _TYPES:
        rows = by_type.get(ptype) or []
        if not rows:
            continue
        ok = sum(1 for r in rows if r["correct"])
        print(f"  {ptype:12s} {ok}/{len(rows)}")

    fails = [r for r in strict if not r["correct"]]
    if fails:
        print("\nFailures (query -> predicted vs expected):")
        for r in fails:
            print(f"  [{r['language']}] {r['id']}")
            print(f"      {r['query']}")
            print(f"      predicted={r['predicted']} (fallback={r['fallback_applied']}) "
                  f"expected={r['expected_prompt_type']} accept={r['acceptable_prompt_types']}")

    if ambiguous:
        print("\nAmbiguous (excluded from strict):")
        for r in ambiguous:
            mark = "ok" if r["correct"] else "off"
            print(f"  [{mark}] {r['id']} predicted={r['predicted']} "
                  f"accept={r['acceptable_prompt_types']}")

    return accuracy >= min_accuracy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", action="append", default=None,
                        help="Golden batch JSON (repeatable). Default: hard_intents.")
    parser.add_argument("--min-accuracy", type=float, default=0.8,
                        help="Strict fast-classifier accuracy gate (default 0.8).")
    parser.add_argument("--min-accuracy-full", type=float, default=0.7,
                        help="Strict full-classifier accuracy gate (default 0.7).")
    parser.add_argument("--full", action="store_true",
                        help="Also run the full (patterns+coherence) classifier (needs embedder).")
    args = parser.parse_args()

    batches = args.batch or _DEFAULT_BATCHES
    cases = []
    for batch in batches:
        cases.extend(load_retrieval_golden_cases(Path(batch)))

    fast_results = [r for r in (evaluate_prompt_type_case(c) for c in cases) if r]
    if not fast_results:
        raise SystemExit("No cases carry expected_prompt_type / prompt_type_ambiguous")
    fast_ok = _report("FAST (patterns only)", fast_results, min_accuracy=args.min_accuracy)

    full_ok = True
    if args.full:
        async def _run_full():
            out = []
            for c in cases:
                r = await evaluate_prompt_type_case_full(c, latency_profile="balanced")
                if r:
                    out.append(r)
            return out

        full_results = asyncio.run(_run_full())
        full_ok = _report("FULL (patterns+coherence)", full_results,
                           min_accuracy=args.min_accuracy_full)

    if not (fast_ok and full_ok):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
