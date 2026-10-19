"""Configure the generic DataOps workshop in the existing Luma business Flow.

This is authored demo configuration, not an alternative execution engine. The
published SQL preparation is replaced only when its exact reviewed contract is
still present. No other node, user draft, model pin or business decision changes.
"""

from __future__ import annotations

import copy

FEATURES = [
    "claim_reason",
    "paid_amount",
    "shipment_status",
    "already_refunded",
    "case_documents",
    "item_quantity",
]
NODE_ID = "sav.prepare"
LEGACY_OUTPUT_NAME = "Luma — Données SAV préparées"
OUTPUT_NAME = "Luma — Préparation visuelle SAV"
LEGACY_SQL = (
    "SELECT claim_id, "
    + ", ".join(FEATURES)
    + ", case_documents = 0 AS evidence_gap, already_refunded = 1 AS duplicate_refund_check"
    + " FROM input ORDER BY claim_id"
)


def preparation_parameters():
    """Canonical editor-owned shape; the incoming edge supplies today's dataset."""
    return {
        "spec": {
            "version": 1,
            "operation": "prepare",
            "params": {
                "steps": [
                    {
                        "id": "sav_columns",
                        "kind": "select_columns",
                        "comment": "Conserver l’identifiant du dossier et les six variables du modèle SLA.",
                        "params": {"columns": ["claim_id", *FEATURES]},
                    },
                    {
                        "id": "sav_missing_evidence",
                        "kind": "formula",
                        "comment": "Signaler l’absence de pièce ; une valeur inconnue reste inconnue.",
                        "params": {
                            "output": "evidence_gap",
                            "expression": "case_documents = 0",
                        },
                    },
                    {
                        "id": "sav_refund_check",
                        "kind": "formula",
                        "comment": "Signaler un remboursement déjà enregistré, sans autoriser une action.",
                        "params": {
                            "output": "duplicate_refund_check",
                            "expression": "already_refunded = 1",
                        },
                    },
                    {
                        "id": "sav_order",
                        "kind": "sort",
                        "comment": "Présenter les dossiers dans un ordre stable avant le scoring.",
                        "params": {
                            "keys": [{"column": "claim_id", "direction": "asc"}]
                        },
                    },
                ]
            },
        },
        "outputs": [{"port": "out", "name": OUTPUT_NAME}],
        "sources": [],
        "placement": "local",
    }


def build_flow(flow):
    """Return a non-mutating, minimal patch of the existing preparation node."""
    from app.services.dataops.flow import data_prep_issues
    from app.services.flow_skill_binding import resolve_flow_skill_binding

    result = copy.deepcopy(flow)
    candidates = [node for node in result["nodes"] if node.get("id") == NODE_ID]
    if len(candidates) != 1:
        raise ValueError("LUMA_PREPARATION_NODE_REQUIRED")
    node = candidates[0]
    config = node.get("config") or {}
    params = preparation_parameters()
    score_nodes = [item for item in result["nodes"] if item.get("id") == "sav.score"]
    if len(score_nodes) != 1:
        raise ValueError("LUMA_PREPARATION_SCORE_REQUIRED")
    score = score_nodes[0]
    score_config = score.get("config") or {}
    binding = resolve_flow_skill_binding(node)
    if resolve_flow_skill_binding(score).skill_slug != "ml_batch_score_v1":
        raise ValueError("LUMA_PREPARATION_SCORE_BINDING_CHANGED")
    incoming = [
        edge
        for edge in result["edges"]
        if edge.get("to") == NODE_ID and edge.get("kind", "data") == "data"
    ]
    if len(incoming) != 1 or incoming[0].get("from") != "sav.features":
        raise ValueError("LUMA_PREPARATION_SOURCE_EDGE_CHANGED")
    score_inputs = [
        edge
        for edge in result["edges"]
        if edge.get("to") == "sav.score" and edge.get("kind", "data") == "data"
    ]
    if len(score_inputs) != 1 or score_inputs[0].get("from") != NODE_ID:
        raise ValueError("LUMA_PREPARATION_SCORE_EDGE_CHANGED")
    if binding.skill_slug == "data_prep_v1":
        if (
            config.get("params") != params
            or score_config.get("inputs_map")
            or score_config.get("passthrough_inputs") != ["dataset_id"]
        ):
            raise ValueError("LUMA_PREPARATION_ALREADY_EDITED")
        if (
            incoming[0].get("to_port") != "in"
            or score_inputs[0].get("from_port") != "out"
            or any(node_id == NODE_ID for node_id, _reason in data_prep_issues(result))
        ):
            raise ValueError("LUMA_PREPARATION_GRAPH_INVALID")
        return result
    if (
        binding.skill_slug != "sql_transform_v1"
        or config.get("params") != {"sql": LEGACY_SQL, "output_name": LEGACY_OUTPUT_NAME}
        or config.get("inputs_map")
        != {
            "dataset_id": {
                "node_id": "sav.features",
                "path": ["dataset_id"],
                "required": True,
            }
        }
    ):
        raise ValueError("LUMA_PREPARATION_SOURCE_CHANGED")
    if (
        score_config.get("inputs_map")
        != {
            "dataset_id": {"node_id": NODE_ID, "path": ["dataset_id"], "required": True}
        }
        or score_config.get("passthrough_inputs")
    ):
        raise ValueError("LUMA_PREPARATION_SCORE_BINDING_CHANGED")
    # A native preparation takes its authorized dataset from data edges, never
    # from an inputs_map or a frozen dataset pin. Keep layout and node identity.
    node["config"] = {
        key: value
        for key, value in config.items()
        if key
        not in {"skill_id", "skill", "skill_slug", "inputs_map", "params", "data_prep"}
    }
    node["config"].update({"skill_slug": "data_prep_v1", "params": params})
    node.pop("inputs_map", None)
    if isinstance(node.get("data"), dict):
        for key in ("bound_skill_slug", "skill_slug"):
            if key in node["data"]:
                node["data"][key] = "data_prep_v1"
    node["inputs"] = [{"name": "in", "schema": "object"}]
    node["outputs"] = [{"name": "out", "schema": "object"}]
    incoming[0]["to_port"] = "in"
    for edge in result["edges"]:
        if edge.get("from") == NODE_ID:
            edge["from_port"] = "out"
    # DataOps' visual ports describe dataset branches, not fields of the outer
    # result. Consume the selected out envelope through the native edge merge,
    # explicitly retaining dataset_id in strict mode, as other DataOps consumers
    # do. Do not disguise dataset_id as a second dataset output port.
    score["config"].pop("inputs_map")
    score["config"]["passthrough_inputs"] = ["dataset_id"]
    if any(node_id == NODE_ID for node_id, _reason in data_prep_issues(result)):
        raise ValueError("LUMA_PREPARATION_GRAPH_INVALID")
    return result
