"""Compose native preparation and inference nodes without changing SAV decisions."""

from __future__ import annotations

import copy

from app.services.connectors.generic.postgresql_claims import CLAIM_RESOURCES
from app.services.ecommerce_triage import FEATURE_DATASET_SKILL, FEATURE_SKILL, FEATURES


def _task(node_id, label, slug, *, params=None, inputs_map=None, x=320, y=0):
    return {
        "id": node_id,
        "type": "skill",
        "kind": "task",
        "label": label,
        "config": {"skill_slug": slug, "params": params or {}, "inputs_map": inputs_map or {}},
        "position": {"x": x, "y": y},
    }


def with_triage(flow, model_id, version):
    result = copy.deepcopy(flow)
    nodes = {node["id"]: node for node in result["nodes"]}
    if "sla_features" in nodes or "sla_risk" in nodes:
        raise ValueError("CLAIM_TRIAGE_ALREADY_INSTALLED")
    loop = nodes["loop.investigate"]
    origin = loop.get("position") or {"x": 320, "y": 0}
    x, y = origin["x"], origin["y"]
    for node in result["nodes"]:
        if node.get("position", {}).get("x", -1) >= x:
            node["position"]["x"] += 680
    result["nodes"].extend(
        [
            _task("sla_features", "Construire les variables SAV", FEATURE_SKILL, x=x, y=y),
            _task(
                "sla_risk",
                "Prédire le risque de résolution > 72 h",
                "ml_predict_v1",
                params={"model_id": model_id, "pinned_version": version, "explain": False},
                inputs_map={"rows": "sla_features.rows"},
                x=x + 340,
                y=y,
            ),
        ]
    )
    result["edges"] = [
        edge
        for edge in result["edges"]
        if not (edge["from"] == "source.request" and edge["to"] == "loop.investigate")
    ]
    result["edges"].extend(
        [
            {"from": "source.request", "to": "sla_features", "kind": "data"},
            {
                "from": "asset.postgresql",
                "to": "sla_features",
                "kind": "data",
                "from_port": "source",
            },
            {"from": "sla_features", "to": "sla_risk", "kind": "data"},
            {"from": "sla_risk", "to": "loop.investigate", "kind": "data"},
        ]
    )
    loop["config"]["inputs_map"] = {
        **loop["config"].get("inputs_map", {}),
        "claim_id": "run.claim_id",
        "sla_prediction": "sla_risk.predictions",
        "sla_model": "sla_risk.served",
    }
    loop["config"]["goal"]["objective"] += (
        " Le score de dépassement de 72 h est un conseil de priorité SAV."
        " L'éligibilité et le montant de remboursement reposent exclusivement sur les faits,"
        " les preuves documentaires et la politique ; le score ne constitue pas une preuve."
    )
    result.setdefault("runtime_contract", {}).update(
        {
            "requires_postgresql_source": True,
            "postgresql_consumers": [
                {"node_id": "sla_features", "resources": copy.deepcopy(CLAIM_RESOURCES)}
            ],
        }
    )
    return result


def fresh_scoring(flow, model_id, version):
    """Replace dated bootstrap imports with one coherent live PostgreSQL read."""
    result = copy.deepcopy(flow)
    nodes = {node["id"]: node for node in result["nodes"]}
    if set(nodes) != {"start", "prepare", "score", "receipt"}:
        raise ValueError("CLAIM_TRIAGE_SCORING_FLOW_EDITED")
    score = nodes["score"]
    if score["config"].get("skill_slug") != "ml_batch_score_v1":
        raise ValueError("CLAIM_TRIAGE_SCORING_FLOW_EDITED")
    score["config"]["params"] = {
        "model_id": model_id,
        "pinned_version": version,
        "output_name": "Luma — File SAV priorisée",
    }
    nodes["prepare"]["config"] = {
        "skill_slug": "sql_transform_v1",
        "inputs_map": {"dataset_id": "features.dataset_id"},
        "params": {
            "sql": "SELECT claim_id, " + ", ".join(FEATURES) + " FROM input ORDER BY claim_id",
            "output_name": "Luma — Variables SAV contrôlées",
        },
    }
    result["nodes"].append(
        _task("features", "Lire les données SAV dans PostgreSQL", FEATURE_DATASET_SKILL)
    )
    result["nodes"].append(
        {
            "id": "asset.postgresql",
            "type": "source.connector",
            "kind": "asset",
            "label": "PostgreSQL · Luma Maison",
            "position": {"x": 0, "y": -180},
            "config": {
                "connector_id": "postgresql",
                "read_mode": "live",
                "resources": [
                    {"schema": "showcase_ecommerce", "table": table}
                    for table in (
                        "claims",
                        "orders",
                        "customers",
                        "order_items",
                        "shipments",
                        "refunds",
                        "document_refs",
                    )
                ],
            },
            "outputs": [{"name": "source", "schema": "object"}],
        }
    )
    for node_id, pos_x in (("features", 320), ("prepare", 660), ("score", 1000), ("receipt", 1340)):
        next(node for node in result["nodes"] if node["id"] == node_id)["position"] = {
            "x": pos_x,
            "y": 0,
        }
    result["edges"] = [edge for edge in result["edges"] if edge["from"] != "start"]
    result["edges"].extend(
        [
            {"from": "start", "to": "features", "kind": "data"},
            {"from": "asset.postgresql", "to": "features", "kind": "data", "from_port": "source"},
            {"from": "features", "to": "prepare", "kind": "data"},
        ]
    )
    result["runtime_contract"] = {
        "requires_postgresql_source": True,
        "postgresql_consumers": [
            {"node_id": "features", "resources": copy.deepcopy(CLAIM_RESOURCES)}
        ],
    }
    return result
