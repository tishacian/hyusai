#!/usr/bin/env python3
"""Build the SENTINEL-CI demo PDFs (Prefet Nawa report).

Idempotent: skips regeneration when the markdown hash is unchanged.

Usage:
    poetry run python scripts/generate_sentinel_ci_reports.py [--force]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional


REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Force regeneration even when cached.")
    args = parser.parse_args(argv)

    from app.services.sentinel_ci_reports import build_prefet_report_pdf

    result = build_prefet_report_pdf(force=args.force)
    print(result)


if __name__ == "__main__":
    main()
