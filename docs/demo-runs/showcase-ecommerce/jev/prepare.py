"""Prepare synthetic, isolated Jev previews. No network, credentials or writes to Luma."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT.parent / "fixtures"
SYSTEM_ID = "f3ea83de-df89-45ec-8a85-c00d676b2713"
WORKSPACE_ID = "e2ed9e40-5fa6-4e32-8948-3e1220134fd3"
WORKSPACE_SLUG = "agentium-showcase"
NODE_ID = "quality.triage_jev"
MODEL = "jev-1.13.0"
TRANSPORT = "model_plane.typesafe.pinned_monetary_v1"
RESOLUTIONS = [
    "Ouvrir une enquête transporteur",
    "Proposer un remboursement à la validation humaine",
    "Clôturer sans nouveau remboursement",
    "Demander le justificatif manquant",
]
FOLLOWUPS = [
    "Soumettre l'enquête transporteur au responsable SAV",
    "Soumettre le montant remboursable et ses preuves au responsable SAV",
    "Présenter le remboursement antérieur et faire valider la clôture",
    "Demander la pièce puis reprendre l'enquête après réception",
]


def sha(value):
    """Same semantic JSON serialization as canonical_flow_sha256."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def flow_identity(state):
    if state.get("status") == 200:
        state = state.get("data", state.get("body"))
    if not isinstance(state, dict) or state.get("system_id") != SYSTEM_ID:
        raise ValueError("LUMA_FLOW_STATE_REQUIRED")
    draft, published = state["draft"], state["published"]
    for item in (draft, published):
        if sha(item["flow_definition"]) != item["flow_sha256"]:
            raise ValueError("FLOW_SNAPSHOT_HASH_MISMATCH")
    return {
        "system_id": SYSTEM_ID,
        "draft_revision": draft["revision"],
        "draft_flow_sha256": draft["flow_sha256"],
        "draft_policy_sha256": draft.get("control_policy_snapshot_sha256"),
        "published_version_id": published["version_id"],
        "published_version_number": published["version_number"],
        "published_flow_sha256": published["flow_sha256"],
        "published_policy_sha256": published.get("control_policy_snapshot_sha256"),
    }


def question_config():
    return {
        "rubric_id": "luma-exploratory-second-opinion",
        "rubric_version": "1",
        "questions": [
            {
                "key": "chosen_resolution",
                "question": (
                    "Quel traitement le responsable SAV doit-il examiner selon les faits et la "
                    "politique fournis ? Un statut livré ne prouve pas la réception si les pièces "
                    "se contredisent. Une perte confirmée permet d'examiner un remboursement, "
                    "un remboursement antérieur interdit le doublon, et une pièce nécessaire "
                    "absente impose de la demander. Ne jamais exécuter une action."
                ),
                "type": "choice",
                "choices": RESOLUTIONS,
                "required": True,
                "requires_evidence": False,
            },
            {
                "key": "refund_supported",
                "question": (
                    "Les informations fournies suffisent-elles à proposer un nouveau "
                    "remboursement à l'examen humain, sans paiement automatique ? La perte "
                    "doit être confirmée, la politique applicable et le montant payé connus, "
                    "et aucun remboursement antérieur ne doit épuiser le montant remboursable. "
                    "Une contradiction de livraison ou une pièce nécessaire absente ne suffit pas."
                ),
                "type": "probability",
                "required": False,
                "requires_evidence": False,
            },
            {
                "key": "safe_followup",
                "question": (
                    "Quelle prochaine étape conserve la maîtrise du responsable SAV ? "
                    "Choisir la suite correspondant aux faits, sans inventer de pièce, "
                    "d'autorisation ni de paiement. Toute action reste soumise à l'humain."
                ),
                "type": "choice",
                "choices": FOLLOWUPS,
                "required": True,
                "requires_evidence": False,
            },
        ],
        "budget": {
            "max_calls": 1,
            "max_tokens": 131072,
            "max_cost_usd": 0.003,
            "max_output_tokens": 2048,
            "timeout_s": 60,
            "max_prompt_bytes": 32000,
        },
        "tariff": {
            "provider": "typesafe",
            "model": MODEL,
            "input_per_million": 0.042,
            "output_per_million": 0.0,
            "currency": "USD",
            "reference": "https://docs.typesafe.ai/models.md (checked 2026-10-22)",
        },
    }


def preview_flow():
    return {
        "schema_version": 3,
        "source": "flow",
        "extended": True,
        "nodes": [
            {
                "id": NODE_ID,
                "kind": "task",
                "type": "skill",
                "label": "Orienter la revue SAV · Jev",
                "config": {
                    "skill_slug": "evaluate_v2",
                    "typed_evaluation": question_config(),
                    "on_error": "fail",
                },
            }
        ],
        "edges": [],
    }


def source_file(path):
    return {
        "path": str(path.relative_to(ROOT.parent)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def text_evidence(identifier, text):
    return {
        "id": identifier,
        "text": text,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def cases():
    spec_path = FIXTURES / "fixture_spec.json"
    spec = json.loads(spec_path.read_text())
    result = []
    for number, scenario, index, documents in [
        (1042, "delivery_conflict", 0, ["claim-lm1042", "delivery-lm1042"]),
        (1043, "confirmed_loss", 1, ["claim-lm1043", "loss-lm1043"]),
        (1044, "already_refunded", 2, ["claim-lm1044", "refund-receipt-lm1044"]),
        (5007, "missing_delivery_document", 3, ["claim-lm5007"]),
    ]:
        # RC-5007 is the existing benchmark clone of RC-1042 with its delivery
        # receipt deliberately absent. Reproduce that documented fixture transform;
        # never present these inputs as a fresh PostgreSQL or Document Center read.
        original = 1042 if number == 5007 else number
        order_id = f"LM-{original}"
        tables = {
            table: [row for row in spec[table] if row.get("order_id") == order_id]
            for table in ("orders", "shipments", "refunds", "claims")
        }
        if number == 5007:
            tables = json.loads(
                json.dumps(tables).replace("1042", "5007").replace("C-014", "C-B5007")
            )
        facts = {
            "evidence_kind": "synthetic_demo",
            "read_mode": "offline_fixture",
            "claim_id": f"RC-{number}",
            "tables": tables,
            "available_case_documents": documents,
            "missing_case_documents": ["delivery-lm5007"] if number == 5007 else [],
            "human_action_authorized": False,
            "financial_execution": "not_executed",
        }
        evidence = [
            text_evidence(
                "fixture_facts", json.dumps(facts, ensure_ascii=False, sort_keys=True)
            )
        ]
        sources = [source_file(spec_path)]
        for reference in ["refund-policy-v2", *documents]:
            folder = FIXTURES / (
                "benchmark/source-texts"
                if reference == "claim-lm5007"
                else "source-texts"
            )
            path = folder / f"{reference}.md"
            evidence.append(text_evidence(reference, path.read_text()))
            sources.append(source_file(path))
        if number == 5007:
            sources.append(source_file(FIXTURES / "build_benchmark.py"))
            sources.append(source_file(FIXTURES / "benchmark/protocol.json"))
        result.append(
            {
                "case_id": f"RC-{number}",
                "scenario": scenario,
                "input_ref": {
                    "subject_ref": f"offline-fixture:RC-{number}:jev-second-opinion-v1",
                    "evidence": evidence,
                },
                "sources": sources,
                "expected_business_direction": {
                    "chosen_resolution": RESOLUTIONS[index],
                    "safe_followup": FOLLOWUPS[index],
                    "proposed_refund_amount_eur": "49.90" if number == 1043 else "0",
                    "basis": "existing_synthetic_fixture_policy; not a newly reviewed Jev rubric",
                },
                "human_annotation": None,
                "observed_result": None,
            }
        )
    return result


def build(state):
    identity = flow_identity(state)
    flow = preview_flow()
    digest = sha(flow)
    prepared = []
    for case in cases():
        prepared.append(
            {
                **case,
                "request": {
                    "method": "POST",
                    "path": f"/api/v1/systems/{SYSTEM_ID}/flow-workbench/node-runs",
                    "body": {
                        "acknowledge_real_side_effects": True,
                        "flow_definition": copy.deepcopy(flow),
                        "expected_flow_sha256": digest,
                        "node_id": NODE_ID,
                        "input_ref": copy.deepcopy(case["input_ref"]),
                    },
                },
            }
        )
    return {
        "format": "luma-jev-node-preview-v1",
        "applied": False,
        "purpose": "exploratory_second_opinion_on_synthetic_fixture_cases",
        "rubric_human_reviewed": False,
        "calibration_qualified": False,
        "workspace_id": WORKSPACE_ID,
        "workspace_slug": WORKSPACE_SLUG,
        "required_qualified_transport": TRANSPORT,
        "preserve": identity,
        "cases": prepared,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flow-state", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    plan = build(json.loads(args.flow_state.read_text()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    print("Prepared four synthetic previews; no HTTP call or Luma write.")


if __name__ == "__main__":
    main()
