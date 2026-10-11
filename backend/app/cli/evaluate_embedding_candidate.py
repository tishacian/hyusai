"""Compare an isolated embedding candidate against a baseline retrieval export.

Examples::

    python -m app.cli.evaluate_embedding_candidate \
        --baseline-export /tmp/baseline.json \
        --candidate-export /tmp/bge_m3.json \
        --candidate bge-m3 \
        --base-collection andritz-notices-techniques-spl-pilot \
        --output /tmp/bge_m3_report.json

    python -m app.cli.evaluate_embedding_candidate \
        --baseline-export /tmp/baseline.jsonl \
        --candidate-export /tmp/openai_large.jsonl \
        --candidate openai-text-embedding-3-large \
        --dimensions 1536
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.services.rag.offline_eval import (
    embedding_candidate_eval_report_from_exports,
    embedding_eval_candidate,
)


def _ks(value: str) -> tuple[int, ...]:
    items = tuple(int(item.strip()) for item in str(value or "").split(",") if item.strip())
    if not items or any(item <= 0 for item in items):
        raise argparse.ArgumentTypeError("--ks must contain positive integers, e.g. 1,3,5,10")
    return items


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a non-destructive offline report for bge-m3 or an OpenAI dense "
            "embedding candidate from exported retrieval rows."
        )
    )
    parser.add_argument("--baseline-export", required=True, help="Baseline JSON/JSONL retrieval export.")
    parser.add_argument("--candidate-export", required=True, help="Candidate JSON/JSONL retrieval export.")
    parser.add_argument(
        "--candidate",
        default="bge-m3",
        help="Candidate key: bge-m3 or openai-text-embedding-3-large. Default: bge-m3.",
    )
    parser.add_argument(
        "--dimensions",
        type=int,
        default=None,
        help="Optional dimensions hint for OpenAI text-embedding-3-large candidate exports.",
    )
    parser.add_argument(
        "--base-collection",
        default=None,
        help="Logical baseline collection; the report derives the isolated candidate collection name.",
    )
    parser.add_argument("--ks", type=_ks, default=(1, 3, 5, 10), help="Recall cutoffs. Default: 1,3,5,10.")
    parser.add_argument("--output", default=None, help="Optional path to write the JSON report.")
    return parser


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    candidate = embedding_eval_candidate(args.candidate, dimensions=args.dimensions)
    return embedding_candidate_eval_report_from_exports(
        candidate=candidate,
        baseline_export=args.baseline_export,
        candidate_export=args.candidate_export,
        base_collection=args.base_collection,
        ks=args.ks,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = build_report(args)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
