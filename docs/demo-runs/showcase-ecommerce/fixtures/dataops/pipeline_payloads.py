"""Public API payloads for native Luma DataOps and MLOps pipelines."""

from pathlib import Path

ROOT = Path(__file__).parent
FEATURES = [
    "claim_reason",
    "paid_amount",
    "shipment_status",
    "already_refunded",
    "case_documents",
    "item_quantity",
]
TARGET = "resolution_over_72h"


def task(node_id, label, slug, params, *, inputs_map=None, x=320):
    return {
        "id": node_id,
        "type": "skill",
        "kind": "task",
        "label": label,
        "config": {
            "skill_slug": slug,
            "params": params,
            "inputs_map": inputs_map or {},
        },
        "position": {"x": x, "y": 0},
    }


def pipeline(nodes):
    steps = [
        {
            "id": "start",
            "type": "source",
            "kind": "source",
            "label": "Exécution manuelle",
            "config": {
                "ingress_kind": "manual",
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                },
            },
            "position": {"x": 0, "y": 0},
        },
        *nodes,
        {
            "id": "receipt",
            "type": "sink",
            "kind": "sink",
            "label": "Artefacts et lignage",
            "position": {"x": 1000, "y": 0},
        },
    ]
    return {
        "schema_version": 3,
        "nodes": steps,
        "edges": [
            {"from": left["id"], "to": right["id"], "kind": "data"}
            for left, right in zip(steps, steps[1:])
        ],
    }


def training(raw_dataset_id):
    return pipeline(
        [
            task(
                "prepare",
                "Nettoyer, dédupliquer et construire la cible 72 h",
                "sql_transform_v1",
                {
                    "sql": (ROOT / "prepare_history.sql").read_text(),
                    "output_name": "Luma — Historique SAV préparé",
                    "sources": [{"view": "history", "dataset_id": raw_dataset_id}],
                },
            ),
            task(
                "train",
                "Entraîner le risque de résolution > 72 h",
                "ml_train_sklearn_v1",
                {
                    "task": "classification",
                    "target": TARGET,
                    "features": FEATURES,
                    "algo": "linear",
                    "knobs": {"max_iter": 1000, "alpha": 1},
                    "test_size": 0.25,
                    "cross_validation": 3,
                    "model_name": "Luma — Risque de résolution > 72 h",
                },
                inputs_map={"dataset_id": "prepare.dataset_id"},
                x=660,
            ),
        ]
    )


def snapshot_scoring(dataset_ids, model_id, model_version):
    """Bootstrap using explicitly dated native PostgreSQL imports.

    Activation replaces this first node with fresh, bounded PostgreSQL feature
    reads. The initial snapshot still exercises the real native SQL/model path.
    """
    return pipeline(
        [
            task(
                "prepare",
                "Assembler les dossiers PostgreSQL et leurs variables",
                "sql_transform_v1",
                {
                    "sql": (ROOT / "prepare_queue.sql").read_text(),
                    "output_name": "Luma — Variables de priorisation SAV",
                    "sources": [
                        {"view": view, "dataset_id": ref}
                        for view, ref in dataset_ids.items()
                    ],
                },
            ),
            task(
                "score",
                "Scorer et classer la file SAV",
                "ml_batch_score_v1",
                {
                    "model_id": model_id,
                    "pinned_version": model_version,
                    "output_name": "Luma — File SAV priorisée",
                },
                inputs_map={"dataset_id": "prepare.dataset_id"},
                x=660,
            ),
        ]
    )


def system_payload(name, flow, skill_ids, role):
    return {
        "name": name,
        "objective": "Prioriser le SAV avec un modèle entraîné sur un historique synthétique ; aucune décision financière.",
        "skill_ids": skill_ids,
        "flow_definition": flow,
        "status": "draft",
        "execution_mode": "real_time_decision",
        "settings": {
            "evidence_kind": "synthetic_demo",
            "production_baseline_eligible": False,
            "demo_role": role,
        },
    }
