"""Seed the PIH SAP HANA demo flow on agentium-showcase and optionally run it.

Idempotent. Configures the workspace HANA connector (password from env only),
upserts a Capability + System with:

    source → sap_hana_query_v1 → llm_rag_answer_v1 → sink

Credentials (never commit secrets):
    export HANA_PASSWORD='...'                 # or HANA_CONNECTOR_PASSWORD
    export HANA_HOST=...                       # optional, demo default below
    export HANA_USER=DBADMIN                   # optional

Usage:
    cd backend
    # Configure connector + upsert System/flow (requires app DATABASE_URL)
    python -m scripts.seed_hana_demo_flow

    # Also execute the DAG and print skill chaining evidence
    python -m scripts.seed_hana_demo_flow --run

    # Skill-only smoke (live HANA, no Run engine / LLM required)
    python -m scripts.seed_hana_demo_flow --validate-skill
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: F401 — register models
from app.db.base import Base, SessionLocal, engine
from app.models.capability import Capability
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.workspace import Workspace
from app.services.connectors.hana import service as hana_service
from app.services.skills_registry import seed_skills_and_capabilities
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

DEFAULT_WORKSPACE_SLUG = "agentium-showcase"
DEFAULT_HOST = (
    "535f81d3-5d3d-4313-92c6-187da6dd50a6"
    ".hna1.prod-us10.hanacloud.ondemand.com"
)
DEFAULT_PORT = 443
DEFAULT_USER = "DBADMIN"

HANA_SYSTEM_NAME = "SAP HANA Maintenance Copilot"
HANA_CAPABILITY_SLUG = "showcase_hana_maintenance"
HANA_SKILL_SLUGS = ["sap_hana_query_v1", "llm_rag_answer_v1"]

# Demo query used by the Flow Builder / run engine (open + released orders).
DEMO_OPEN_ORDERS_SQL = """
SELECT ORDER_ID, EQUIPMENT_ID, PRIORITY, STATUS, SHORT_TEXT
FROM DEMO_MAINTENANCE_ORDERS
WHERE STATUS IN ('OPEN', 'RELEASED')
ORDER BY PRIORITY DESC, ORDER_ID
""".strip()

DEMO_QUERY = (
    "Quels ordres de maintenance SAP HANA sont ouverts ou released, "
    "et lesquels sont prioritaires ?"
)


def flow_hana_maintenance() -> Dict[str, Any]:
    """source → HANA query → grounded LLM synthesis → sink."""
    return {
        "schema_version": 2,
        "nodes": [
            {
                "id": "src",
                "kind": "source",
                "label": "Trigger",
                "data": {
                    "description": "Manual / API trigger. Pass run.query for the synthesis prompt.",
                },
            },
            {
                "id": "task.hana",
                "kind": "task",
                "label": "Open maintenance orders (HANA)",
                "config": {
                    "skill_slug": "sap_hana_query_v1",
                    "inputs_map": {
                        "sql": {"node_id": "system", "path": ["hana_demo", "sql"]},
                        "max_rows": {
                            "node_id": "system",
                            "path": ["hana_demo", "max_rows"],
                        },
                    },
                },
                "data": {
                    "description": (
                        "sap_hana_query_v1 against workspace connector. "
                        "SQL baked in system.settings.hana_demo (params are not "
                        "engine-authoritative)."
                    ),
                },
            },
            {
                "id": "task.synthesize",
                "kind": "task",
                "label": "Synthèse ordres ouverts",
                "config": {
                    "skill_slug": "llm_rag_answer_v1",
                    "inputs_map": {
                        "query": {"node_id": "run", "path": ["query"]},
                        "context": {"node_id": "task.hana", "path": ["context"]},
                    },
                },
                "data": {
                    "description": (
                        "llm_rag_answer_v1 grounded on HANA row passages "
                        "(task.hana.context)."
                    ),
                },
            },
            {
                "id": "sink",
                "kind": "sink",
                "label": "Result",
            },
        ],
        "edges": [
            {"from": "src", "to": "task.hana"},
            {"from": "task.hana", "to": "task.synthesize"},
            {"from": "task.synthesize", "to": "sink"},
        ],
    }


def _resolve_password(cli_password: Optional[str] = None) -> str:
    return (
        (cli_password or "").strip()
        or os.environ.get("HANA_PASSWORD", "").strip()
        or os.environ.get("HANA_CONNECTOR_PASSWORD", "").strip()
    )


def ensure_showcase_hana_flags(db: DBSession, workspace: Workspace) -> None:
    """Ensure feature + catalog gating for the HANA connector/skill."""
    settings = dict(workspace.settings or {})
    features = dict(settings.get("features") or {})
    catalog = dict(settings.get("catalog") or {})
    enabled = list(catalog.get("enabled_skills") or [])
    features["sap_hana_connector"] = True
    if "sap_hana_query_v1" not in enabled:
        enabled.append("sap_hana_query_v1")
    catalog["enabled_skills"] = enabled
    settings["features"] = features
    settings["catalog"] = catalog
    settings["showcase_seed"] = True
    workspace.settings = settings
    flag_modified(workspace, "settings")
    db.add(workspace)
    db.commit()
    db.refresh(workspace)


def configure_hana_connector(
    db: DBSession,
    workspace: Workspace,
    *,
    host: str,
    port: int,
    user: str,
    password: str,
) -> dict[str, Any]:
    """Persist connector host/user; password encrypted or plaintext envelope."""
    if not password:
        raise ValueError(
            "HANA password missing. Set HANA_PASSWORD or HANA_CONNECTOR_PASSWORD."
        )
    ensure_showcase_hana_flags(db, workspace)
    return hana_service.set_config(
        db,
        workspace,
        {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "encrypt": True,
        },
    )


def _skill_ids(db: DBSession, slugs: list[str]) -> list[str]:
    rows = db.query(Skill).filter(Skill.slug.in_(slugs)).all()
    by_slug = {r.slug: r.id for r in rows}
    missing = [s for s in slugs if s not in by_slug]
    if missing:
        raise RuntimeError(
            f"Skills not seeded: {missing}. Run seed_skills_and_capabilities first."
        )
    return [by_slug[s] for s in slugs]


def ensure_hana_capability(db: DBSession, workspace: Workspace) -> Capability:
    skill_ids = _skill_ids(db, HANA_SKILL_SLUGS)
    payload = {
        "workspace_id": workspace.id,
        "name": "SAP HANA Maintenance Orders",
        "description": (
            "Query open/released PIH maintenance orders from SAP HANA Cloud "
            "and synthesize a short operator brief."
        ),
        "tier": "client",
        "industry": "energy_hydro",
        "input_unit": "question",
        "output_unit": "maintenance_brief",
        "skill_ids": skill_ids,
        "pricing": {"unit": "per_brief", "unit_price": 0.35, "currency": "EUR"},
        "value_per_outcome": 18.0,
        "confidence_threshold": 0.8,
        "sla": {"target_latency_ms": 8000, "availability": "99.5%"},
        "roi_model": {"seed": "showcase_seed", "value_driver": "maintenance_triage"},
        "is_seeded": "Y",
    }
    cap = db.query(Capability).filter(Capability.slug == HANA_CAPABILITY_SLUG).first()
    if cap:
        for key, value in payload.items():
            setattr(cap, key, value)
    else:
        cap = Capability(id=str(uuid4()), slug=HANA_CAPABILITY_SLUG, **payload)
        db.add(cap)
    db.commit()
    db.refresh(cap)
    return cap


def ensure_hana_system(
    db: DBSession, workspace: Workspace, capability: Capability
) -> System:
    flow = flow_hana_maintenance()
    settings = {
        "showcase_seed": True,
        "surface": "system",
        "system_type": "hana_maintenance",
        "brand": "Agentium Showcase",
        "hana_demo": {
            "sql": DEMO_OPEN_ORDERS_SQL,
            "max_rows": 50,
            "dataset": "DEMO_MAINTENANCE_ORDERS",
        },
    }
    payload = {
        "objective": (
            "Lister les ordres de maintenance ouverts/released depuis SAP HANA "
            "Cloud et produire une synthèse priorisée pour l'opérateur PIH."
        ),
        "capability_id": capability.id,
        "skill_ids": list(capability.skill_ids or []),
        "flow_definition": flow,
        "settings": settings,
        "execution_mode": "real_time_decision",
        "execution_profile": {
            "showcase_seed": True,
            "persona": "maintenance_operator",
            "connector": "sap_hana",
        },
        "coordination_pattern": "graph",
        "status": "active",
        "created_by": "showcase-seed",
        "default_prompt_type": "factual",
        "default_model": "gpt-4o-mini",
        "retrieval_mode_default": "hybrid",
    }
    system = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.name == HANA_SYSTEM_NAME)
        .first()
    )
    if system:
        for key, value in payload.items():
            setattr(system, key, value)
        system.updated_at = datetime.utcnow()
    else:
        system = System(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name=HANA_SYSTEM_NAME,
            **payload,
        )
        db.add(system)
        db.flush()

    existing = (
        db.query(SystemVersion)
        .filter(
            SystemVersion.system_id == system.id,
            SystemVersion.version_number == 1,
        )
        .first()
    )
    if existing:
        existing.flow_definition = flow
        existing.message = "HANA demo flow baseline"
    else:
        db.add(
            SystemVersion(
                id=str(uuid4()),
                workspace_id=workspace.id,
                system_id=system.id,
                version_number=1,
                flow_definition=flow,
                message="HANA demo flow baseline",
                created_by="showcase-seed",
            )
        )
    db.commit()
    db.refresh(system)
    return system


def ensure_hana_demo(
    db: DBSession,
    workspace: Workspace,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    user: str = DEFAULT_USER,
    password: Optional[str] = None,
    configure_connector: bool = True,
) -> Dict[str, Any]:
    """Upsert capability + system; optionally persist connector credentials."""
    seed_skills_and_capabilities(db)
    pwd = _resolve_password(password)
    config_summary: dict[str, Any] = {}
    if configure_connector:
        if not pwd:
            raise ValueError(
                "HANA password missing. Set HANA_PASSWORD or HANA_CONNECTOR_PASSWORD "
                "(or pass --password). Use --skip-connector to only seed the flow."
            )
        config_summary = configure_hana_connector(
            db, workspace, host=host, port=port, user=user, password=pwd
        )
    else:
        ensure_showcase_hana_flags(db, workspace)
        config_summary = hana_service.get_config(workspace)

    capability = ensure_hana_capability(db, workspace)
    system = ensure_hana_system(db, workspace, capability)
    return {
        "workspace_id": workspace.id,
        "workspace_slug": workspace.slug,
        "capability_id": capability.id,
        "system_id": system.id,
        "system_name": system.name,
        "connector": {
            "configured": bool(config_summary.get("configured")),
            "host": config_summary.get("host"),
            "user": config_summary.get("user"),
            "password_set": bool(config_summary.get("password_set")),
        },
    }


async def validate_skill(workspace: Workspace, db: DBSession) -> dict[str, Any]:
    """Run sap_hana_query_v1 against the live connector (no LLM)."""
    from app.services.skills_registry.wrappers import _sap_hana_query_v1

    result = await _sap_hana_query_v1(
        {"sql": DEMO_OPEN_ORDERS_SQL, "max_rows": 50},
        {"db": db, "workspace_id": workspace.id, "workspace_slug": workspace.slug},
    )
    return result


async def run_demo_flow(
    db: DBSession, workspace: Workspace, system: System, *, query: str = DEMO_QUERY
) -> dict[str, Any]:
    """Execute the seeded System via execute_run_dag and return chaining evidence."""
    from app.services.run_engine.dag import execute_run_dag

    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        input_ref={"query": query},
        status="pending",
        trigger="hana_demo_seed",
    )
    db.add(run)
    db.commit()
    run_id = run.id

    await execute_run_dag(run_id)

    db.expire_all()
    fresh = db.query(Run).filter(Run.id == run_id).first()
    invocations = (
        db.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run_id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )
    return {
        "run_id": run_id,
        "status": fresh.status if fresh else None,
        "error": fresh.error if fresh else None,
        "output_ref": (fresh.output_ref if fresh else None) or {},
        "invocations": [
            {
                "skill_slug": inv.skill_slug,
                "status": inv.status,
                "latency_ms": inv.latency_ms,
                "error": inv.error,
                "row_count": (inv.output_ref or {}).get("row_count"),
                "context_len": len((inv.output_ref or {}).get("context") or []),
                "answer_preview": str((inv.output_ref or {}).get("answer") or "")[:240],
            }
            for inv in invocations
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-slug", default=DEFAULT_WORKSPACE_SLUG)
    parser.add_argument("--host", default=os.environ.get("HANA_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("HANA_PORT", DEFAULT_PORT))
    )
    parser.add_argument("--user", default=os.environ.get("HANA_USER", DEFAULT_USER))
    parser.add_argument(
        "--password",
        default=None,
        help="Override env HANA_PASSWORD / HANA_CONNECTOR_PASSWORD.",
    )
    parser.add_argument(
        "--skip-connector",
        action="store_true",
        help="Do not write connector credentials (flow/capability only).",
    )
    parser.add_argument(
        "--validate-skill",
        action="store_true",
        help="After seed, run sap_hana_query_v1 once against live HANA.",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="After seed, execute the DAG (needs LLM keys for full synthesis).",
    )
    parser.add_argument(
        "--query",
        default=DEMO_QUERY,
        help="run.query passed to llm_rag_answer_v1 when --run is set.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        workspace = (
            db.query(Workspace).filter(Workspace.slug == args.workspace_slug).first()
        )
        if not workspace:
            raise SystemExit(
                f"Workspace {args.workspace_slug!r} not found. "
                "Run scripts.seed_showcase_workspace first, or create the workspace."
            )

        seeded = ensure_hana_demo(
            db,
            workspace,
            host=args.host,
            port=args.port,
            user=args.user,
            password=args.password,
            configure_connector=not args.skip_connector,
        )
        print(
            f"HANA demo ready: workspace={seeded['workspace_slug']} "
            f"system={seeded['system_name']} id={seeded['system_id']}"
        )
        print(
            "Connector: "
            f"configured={seeded['connector']['configured']} "
            f"host={seeded['connector']['host']} "
            f"user={seeded['connector']['user']} "
            f"password_set={seeded['connector']['password_set']}"
        )

        if args.validate_skill or args.run:
            # Refresh workspace after connector write.
            db.refresh(workspace)

        if args.validate_skill:
            result = asyncio.run(validate_skill(workspace, db))
            print(
                f"Skill sap_hana_query_v1: row_count={result.get('row_count')} "
                f"context={len(result.get('context') or [])} "
                f"duration_ms={result.get('duration_ms')}"
            )
            for row in (result.get("rows") or [])[:10]:
                print(f"  {row}")
            if int(result.get("row_count") or 0) < 1:
                raise SystemExit("Validation failed: expected ≥1 open/released order")

        if args.run:
            system = db.query(System).filter(System.id == seeded["system_id"]).first()
            assert system is not None
            evidence = asyncio.run(
                run_demo_flow(db, workspace, system, query=args.query)
            )
            print(
                f"Run {evidence['run_id']}: status={evidence['status']} "
                f"error={evidence['error']!r}"
            )
            for inv in evidence["invocations"]:
                print(
                    f"  {inv['skill_slug']}: status={inv['status']} "
                    f"latency_ms={inv['latency_ms']} "
                    f"row_count={inv['row_count']} "
                    f"context_len={inv['context_len']}"
                )
                if inv["answer_preview"]:
                    print(f"    answer: {inv['answer_preview']}")
                if inv["error"]:
                    print(f"    error: {inv['error']}")
            slugs = [i["skill_slug"] for i in evidence["invocations"]]
            hana_ok = any(
                i["skill_slug"] == "sap_hana_query_v1"
                and i["status"] == "completed"
                and (i["row_count"] or 0) >= 1
                for i in evidence["invocations"]
            )
            llm_ran = "llm_rag_answer_v1" in slugs
            if not hana_ok:
                raise SystemExit(
                    "Validation failed: sap_hana_query_v1 did not return rows"
                )
            if not llm_ran:
                raise SystemExit(
                    "Validation failed: llm_rag_answer_v1 was not invoked"
                )
            print("Flow chain validated: sap_hana_query_v1 → llm_rag_answer_v1")

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
