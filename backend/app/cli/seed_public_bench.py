"""Ingest the frozen HotpotQA distractor subset into the public-bench workspace.

Usage:
    python -m app.cli.seed_public_bench [--run] [--limit N]

``--run`` executes the bench once after seeding (the nightly Celery beat task
runs it otherwise).
"""
from __future__ import annotations

import argparse
import asyncio
import json

from app.db.base import SessionLocal
from app.services.rag.public_bench import run_public_bench, seed_public_bench, serialize_bench_run


async def _main(run: bool, limit: int | None) -> None:
    with SessionLocal() as db:
        result = await seed_public_bench(db)
        print(json.dumps({k: result.get(k) for k in ("status", "collection_slug", "documents_written", "document_count", "chunk_count")}))
        if run:
            print(json.dumps(serialize_bench_run(await run_public_bench(db, limit=limit))))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Run the bench once after seeding")
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N cases")
    args = parser.parse_args(argv)
    asyncio.run(_main(args.run, args.limit))


if __name__ == "__main__":
    main()
