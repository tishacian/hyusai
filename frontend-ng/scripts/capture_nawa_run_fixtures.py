#!/usr/bin/env python
"""Capture real run traces for the Nawa ITSD projection guard.

Drives the Password Reset flow on the local DAG bench — stubbed skills, throwaway
SQLite — once per selector entry, and writes the resulting ``checkpoints`` and
``output_ref`` verbatim to a fixture the front-end guard replays. The point is
that ``check-nawa-projection.mjs`` never asserts against traces we imagined: the
walker's own emission order, its missing ``status`` on decision nodes and its
skipped siblings are all in the captured data.

The stubs are not re-implemented here. They come from the backend's own runtime
test, so a change in the flow's contract reaches this fixture instead of being
silently papered over:

    backend/app/tests/services/test_nawa_password_reset_flow.py

Run it from the repository root with an interpreter that has the backend
requirements installed::

    python frontend-ng/scripts/capture_nawa_run_fixtures.py

Nothing under ``backend/`` is written to, and the SQLite file is a temporary one.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FIXTURE = ROOT / "frontend-ng" / "src" / "app" / "features" / "nawa" / "nawa-run-fixtures.ts"

# Must be set before the first `app.*` import binds the engine, and mirrors what
# the backend test bootstrap does for its own throwaway database.
_DB = pathlib.Path(tempfile.gettempdir()) / f"nawa_fixtures-{os.getpid()}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

sys.path.insert(0, str(BACKEND))

from app.db.base import Base, SessionLocal, engine  # noqa: E402
import app.models  # noqa: E402,F401  (registers every mapped class)
from app.services.run_engine import engine as engine_module  # noqa: E402
from app.services.run_engine.dag import execute_run_dag, resume_run_dag  # noqa: E402


def _load_backend_test_module():
    """Import the backend runtime test by path — `app/tests` is not a package."""
    path = BACKEND / "app" / "tests" / "services" / "test_nawa_password_reset_flow.py"
    spec = importlib.util.spec_from_file_location("nawa_flow_runtime_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The walker attaches its accumulated run payload to every checkpoint. The
# projection never reads it and it is half the weight of the capture, so it is
# the one key dropped here. Everything the projection can consume — `status`,
# `node_kind`, `label`, `error`, `chosen_branch`, `latency_ms`, `skipped_reason`,
# and the emission order itself — is kept verbatim.
_UNREAD_CHECKPOINT_KEY = "state"


def _snapshot(db, run_id: str) -> dict:
    from app.models.run import Run

    db.expire_all()
    run = db.query(Run).filter(Run.id == run_id).one()
    return {
        "status": run.status,
        "checkpoints": [
            {k: v for k, v in cp.items() if k != _UNREAD_CHECKPOINT_KEY}
            for cp in (run.checkpoints or [])
        ],
        "output_ref": run.output_ref or {},
    }


async def _capture(bench) -> dict:
    Base.metadata.create_all(engine)
    db = SessionLocal()

    # The bench's own prompt-driven fakes, installed the way its registry helper
    # does — the walker resolves skills through this one reference.
    engine_module.resolve_skill = lambda slug: {
        "azure_llm_v1": bench._fake_azure_llm,
        "audit_log_v1": bench._fake_audit_log,
        "response_eval_v1": bench._fake_response_eval,
        "rpa_dispatch_v1": bench._fake_rpa_dispatch,
    }[slug]

    system = bench._mk_system(db, bench.LLM_FLOW)
    captured: dict = {}

    for key, scenario, extra in (
        ("nominal", "nominal", {}),
        ("ambiguous", "ambiguous", {}),
        ("ad_unreachable", "ad_unreachable", {}),
        ("ad_unreachable_fallback", "ad_unreachable", {"bridge_fallback": True}),
        ("quality_guard", "quality_guard", {}),
    ):
        run = bench._mk_run(db, system, scenario, **extra)
        summary = await execute_run_dag(run.id)
        captured[key] = _snapshot(db, run.id)
        print(f"  {key:24} -> {summary['status']}")

    # The gate lane is two snapshots: what the page shows while the run waits,
    # and what it shows once the Decision is accepted.
    run = bench._mk_run(db, system, "weak_identity")
    paused = await execute_run_dag(run.id)
    captured["weak_identity_pending"] = _snapshot(db, run.id)
    print(f"  {'weak_identity (paused)':24} -> {paused['status']}")

    decision = bench._pending_decision(db, paused)
    decision.status = "accepted"
    db.commit()
    resumed = await resume_run_dag(run.id, decision_id=decision.id)
    captured["weak_identity"] = _snapshot(db, run.id)
    print(f"  {'weak_identity (approved)':24} -> {resumed['status']}")

    db.close()
    return captured


def main() -> int:
    bench = _load_backend_test_module()
    print("capturing real run traces on the local DAG bench")
    captured = asyncio.run(_capture(bench))
    body = json.dumps(captured, indent=2, sort_keys=True, ensure_ascii=False)
    FIXTURE.write_text(
        "/**\n"
        " * Real run traces, captured on the local DAG bench — DO NOT EDIT BY HAND.\n"
        " *\n"
        " * Regenerate with:\n"
        " *   python frontend-ng/scripts/capture_nawa_run_fixtures.py\n"
        " *\n"
        " * Consumed by `nawa-run-projection.spec.ts`, which asserts the state of the\n"
        " * six business steps against what the outcome banner claims. These are the\n"
        " * walker's own checkpoints, in its own emission order, so the guard cannot\n"
        " * drift towards a trace we imagined.\n"
        " */\n"
        f"export const NAWA_RUN_FIXTURES = {body} as const;\n",
        encoding="utf-8",
    )
    print(f"\nwrote {FIXTURE.relative_to(ROOT)} ({FIXTURE.stat().st_size} bytes)")
    _DB.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
