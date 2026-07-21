"""One-shot validation of the PIH demo 'live node add' arc (run on the VM).

Simulates exactly what the Flow Builder UI produces when the presenter:
  1. drags a 'SAP HANA Query' palette node (empty inputs_map, params from
     the Node Inspector),
  2. wires src -> new node -> synthesize,
  3. rebinds synthesize context to the new node and edits the question.

Runs it on a temporary System in agentium-showcase, verifies the chain and
the rerun (replay) path, then cleans everything up.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from uuid import uuid4

sys.path.insert(0, "/app/backend")

import app.models  # noqa: F401 — register models
from app.db.base import SessionLocal
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace

STOCKOUT_SQL = """SELECT PART_ID, EQUIPMENT_ID, DESCRIPTION, QTY_ON_HAND, QTY_MIN, LEAD_TIME_DAYS
FROM DEMO_SPARE_PARTS
WHERE QTY_ON_HAND < QTY_MIN
ORDER BY QTY_ON_HAND ASC, LEAD_TIME_DAYS DESC""".strip()

STOCKOUT_QUESTION = (
    "Which spare parts are below minimum stock, and what should procurement "
    "reorder first given the lead times?"
)


def summarize(db, run_id: str) -> dict:
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
        "answer": str((fresh.output_ref or {}).get("answer") or "")[:400] if fresh else "",
        "invocations": [
            {
                "node_id": (inv.trace or {}).get("node_id"),
                "skill": inv.skill_slug,
                "status": inv.status,
                "row_count": (inv.output_ref or {}).get("row_count"),
                "source": (inv.output_ref or {}).get("source"),
                "error": inv.error,
            }
            for inv in invocations
        ],
    }


def main() -> int:
    db = SessionLocal()
    temp_system_id = None
    run_ids: list[str] = []
    try:
        ws = db.query(Workspace).filter(Workspace.slug == "agentium-showcase").first()
        assert ws, "showcase workspace missing"
        demo = (
            db.query(System)
            .filter(
                System.workspace_id == ws.id,
                System.name == "SAP HANA Maintenance Copilot",
            )
            .first()
        )
        assert demo, "demo system missing"
        skill = db.query(Skill).filter(Skill.slug == "sap_hana_query_v1").first()
        assert skill, "sap_hana_query_v1 not seeded"

        flow = json.loads(json.dumps(demo.flow_definition))

        # Exact palette shape (skillToPaletteItem): empty inputs_map, params
        # holding the inspector-edited SQL. No explicit inputs_map entries —
        # this is what the engine patch must cover.
        flow["nodes"].append(
            {
                "id": "task.stockout",
                "kind": "task",
                "label": "Spare parts below minimum (HANA)",
                "config": {
                    "skill_slug": "sap_hana_query_v1",
                    "skill_id": skill.id,
                    "inputs_map": {},
                    "outputs_map": {},
                    "params": {"sql": STOCKOUT_SQL},
                    "runtime_ref": "skill:sap_hana_query_v1",
                },
            }
        )
        flow["edges"].append({"from": "src", "to": "task.stockout"})
        flow["edges"].append({"from": "task.stockout", "to": "task.synthesize"})
        for node in flow["nodes"]:
            if node["id"] == "task.synthesize":
                node["config"]["inputs_map"]["context"] = {
                    "node_id": "task.stockout",
                    "path": ["context"],
                }
                node["config"]["params"]["query"] = STOCKOUT_QUESTION

        temp = System(
            id=str(uuid4()),
            workspace_id=ws.id,
            name="HANA Node-Add Validation (temp)",
            objective="engine validation for live node-add demo",
            capability_id=demo.capability_id,
            skill_ids=list(demo.skill_ids or []),
            flow_definition=flow,
            settings={"validation_temp": True},
            execution_mode=demo.execution_mode,
            coordination_pattern="graph",
            status="active",
            created_by="validation",
            default_model=demo.default_model,
            default_prompt_type=demo.default_prompt_type,
            retrieval_mode_default=demo.retrieval_mode_default,
        )
        db.add(temp)
        db.commit()
        temp_system_id = temp.id

        from app.services.run_engine.dag import execute_run_dag

        run = Run(
            id=str(uuid4()),
            workspace_id=ws.id,
            system_id=temp.id,
            input_ref={"query": ""},
            status="pending",
            trigger="validation",
            started_at=datetime.utcnow(),
        )
        db.add(run)
        db.commit()
        run_ids.append(run.id)
        asyncio.run(execute_run_dag(run.id))
        db.expire_all()
        first = summarize(db, run.id)
        print("RUN1", json.dumps(first, indent=2))

        # Replay path: same copy semantics as POST /runs/{id}/rerun.
        parent = db.query(Run).filter(Run.id == run.id).first()
        rerun = Run(
            id=str(uuid4()),
            workspace_id=ws.id,
            system_id=temp.id,
            input_ref=parent.input_ref or {},
            status="pending",
            trigger="rerun",
            parent_run_id=parent.id,
            flow_snapshot=parent.flow_snapshot,
            started_at=datetime.utcnow(),
        )
        db.add(rerun)
        db.commit()
        run_ids.append(rerun.id)
        asyncio.run(execute_run_dag(rerun.id))
        db.expire_all()
        second = summarize(db, rerun.id)
        print("RERUN", json.dumps(second, indent=2))

        stockout_ok = any(
            i["node_id"] == "task.stockout"
            and i["status"] == "completed"
            and (i["row_count"] or 0) >= 1
            for i in first["invocations"]
        )
        answer_ok = first["status"] == "completed" and len(first["answer"]) > 0
        rerun_ok = second["status"] == "completed" and any(
            i["node_id"] == "task.stockout" and i["status"] == "completed"
            for i in second["invocations"]
        )
        print(f"VERDICT stockout_ok={stockout_ok} answer_ok={answer_ok} rerun_ok={rerun_ok}")
        return 0 if (stockout_ok and answer_ok and rerun_ok) else 1
    finally:
        # Cleanup: temp runs + invocations + system.
        for rid in run_ids:
            db.query(SkillInvocation).filter(SkillInvocation.run_id == rid).delete()
            db.query(Run).filter(Run.id == rid).delete()
        if temp_system_id:
            db.query(System).filter(System.id == temp_system_id).delete()
        db.commit()
        db.close()
        print("CLEANUP done")


if __name__ == "__main__":
    sys.exit(main())
