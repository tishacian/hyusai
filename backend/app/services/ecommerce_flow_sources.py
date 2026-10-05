"""Add actual SQL/document dependencies to a Luma Flow without replacing tasks."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping

from app.services.connectors.generic.postgresql_claims import CLAIM_RESOURCES
from app.services.flow_diff import semantic_flow_diff

PG_NODE_ID = "asset.postgresql"


def reviewed_source_base(published: Mapping, draft: Mapping) -> dict:
    candidate = copy.deepcopy(dict(draft))
    # Historical Builder normalization adds these exact idle chat defaults to
    # Luma's non-chat DAG. Do not publish them as unrelated runtime changes.
    for key, default in {
        "collections": [],
        "rag_mode": "OmniRAG",
        "canonical_rag_mode": "chah",
        "context_reused": False,
    }.items():
        if key not in published and candidate.get(key) == default:
            candidate.pop(key, None)
    diff = semantic_flow_diff(
        published, candidate, base_identity="published", target_identity="draft"
    )
    if any(change["impact"] != "presentation" for change in diff["changes"]):
        raise ValueError("CLAIMS_SOURCE_UPGRADE_UNPUBLISHED_DRAFT")
    return candidate


def with_data_sources(flow: Mapping, collections: list[str]) -> dict:
    result = copy.deepcopy(dict(flow))
    by_id = {node["id"]: node for node in result["nodes"]}
    for consumer_id in ("loop.investigate", "task.simulate"):
        if consumer_id not in by_id:
            raise ValueError("CLAIMS_FLOW_CONSUMER_MISSING")
    positions = {
        "source.request": (440, 80),
        "loop.investigate": (440, 260),
        "decision.ready": (790, 260),
        "hitl.review": (1120, 180),
        "task.simulate": (1450, 180),
        "sink.receipt": (1780, 180),
        "sink.blocked": (1120, 410),
    }
    for node in result["nodes"]:
        if node["id"] in positions and not node.get("position"):
            x, y = positions[node["id"]]
            node["position"] = {"x": x, "y": y}
    source_x = (
        min(node["position"]["x"] for node in result["nodes"] if node["id"] in positions) - 360
    )
    source_y = min(node["position"]["y"] for node in result["nodes"] if node["id"] in positions)
    source = {
        "id": PG_NODE_ID,
        "type": "source.connector",
        "kind": "asset",
        "label": "PostgreSQL · Luma Maison",
        "config": {
            "connector_id": "postgresql",
            "read_mode": "live",
            "resources": copy.deepcopy(CLAIM_RESOURCES),
        },
        "outputs": [{"name": "source", "schema": "object"}],
        "data": {
            "description": "Commandes, clients, livraisons, remboursements et références documentaires."
        },
        "position": {"x": source_x, "y": source_y},
    }
    if PG_NODE_ID in by_id:
        if by_id[PG_NODE_ID].get("config") != source["config"]:
            raise ValueError("CLAIMS_FLOW_SOURCE_ALREADY_EDITED")
    else:
        result["nodes"].append(source)
    for consumer_id in ("loop.investigate", "task.simulate"):
        edge = {"from": PG_NODE_ID, "to": consumer_id, "kind": "data", "from_port": "source"}
        if not any(e["from"] == PG_NODE_ID and e["to"] == consumer_id for e in result["edges"]):
            result["edges"].append(edge)
    for index, slug in enumerate(sorted(set(collections))):
        node_id = "asset.collection." + hashlib.sha256(slug.encode()).hexdigest()[:12]
        if node_id not in by_id:
            result["nodes"].append(
                {
                    "id": node_id,
                    "type": "source.collection",
                    "kind": "asset",
                    "label": slug,
                    "config": {"collection_slug": slug, "workspace_scoped": True},
                    "outputs": [{"name": "collection", "schema": "object"}],
                    "position": {"x": source_x, "y": source_y + 160 + index * 110},
                }
            )
        if not any(e["from"] == node_id and e["to"] == "loop.investigate" for e in result["edges"]):
            result["edges"].append(
                {
                    "from": node_id,
                    "to": "loop.investigate",
                    "kind": "data",
                    "from_port": "collection",
                }
            )
    result.setdefault("runtime_contract", {})["requires_postgresql_source"] = True
    return result
