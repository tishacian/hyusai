"""Closed, typed tools for an evidence-driven e-commerce claim inquiry."""

TOOLS = {
    "postgresql_claim_snapshot_v1": (
        "Read claim facts",
        "Read the order, shipments, past refunds and current document references in one PostgreSQL snapshot.",
        "data_query",
    ),
    "ecommerce_policy_evidence_v1": (
        "Find applicable rules",
        "Retrieve the current refund policy and SAV procedure with exact source and revision checks.",
        "retrieval",
    ),
    "ecommerce_delivery_evidence_v1": (
        "Investigate delivery",
        "Retrieve this order's claim, delivery receipt or loss confirmation; compare them to PostgreSQL facts.",
        "retrieval",
    ),
    "ecommerce_refund_evidence_v1": (
        "Verify previous refund",
        "Retrieve the actual previous-refund receipt; stop a repeated refund without alleging fraud.",
        "retrieval",
    ),
    "ecommerce_resolution_propose_v1": (
        "Prepare resolution",
        "Apply the deterministic evidence and amount guards; request missing information or propose a human decision.",
        "analysis",
    ),
    "ecommerce_resolution_simulate_v1": (
        "Record simulated resolution",
        "After canonical human approval, recheck live evidence and issue one explicitly simulated action receipt.",
        "action",
    ),
}

CLAIM_SKILLS = [
    {
        "slug": slug,
        "version": "1",
        "name": name,
        "description": description,
        "type": kind,
        "provider": "internal",
        "certification_level": "production",
        "execution": {"mode": "async", "timeout_ms": 120000, "retryable": True, "idempotent": True},
        "pricing": {}
        if kind == "retrieval"
        else {"unit": "per_call", "unit_price": 0.0, "currency": "EUR"},
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["claim_id"],
            "properties": {"claim_id": {"type": "string", "pattern": "^RC-[0-9]{4,8}$"}},
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "action": {"type": "string"},
                "citations": {"type": "array"},
                "provenance": {"type": "object"},
                "data": {"type": "object"},
                "results": {"type": "array"},
                "evidence_kind": {"type": "string"},
                "receipt_id": {"type": "string"},
                "snapshot_sha256": {"type": "string"},
                "amount": {"type": "string"},
            },
        },
    }
    for slug, (name, description, kind) in TOOLS.items()
]

CLAIM_SKILLS.append(
    {
        "slug": "ecommerce_sla_features_v1",
        "version": "1",
        "name": "Luma SAV intake features",
        "description": "Read bounded PostgreSQL intake facts for one claim's resolution-risk prediction. Emits model inputs only; no financial recommendation.",
        "type": "data_query",
        "provider": "internal",
        "certification_level": "beta",
        "execution": {"mode": "async", "timeout_ms": 120000, "retryable": True, "idempotent": True},
        "pricing": {"unit": "per_call", "unit_price": 0.0, "currency": "EUR"},
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "rows": {"type": "array"},
                "provenance": {"type": "object"},
            },
        },
    }
)

CLAIM_SKILLS.append(
    {
        "slug": "ecommerce_sla_dataset_v1",
        "version": "1",
        "name": "Luma SAV feature dataset",
        "description": "Read the authorized Luma cohort in one bounded PostgreSQL snapshot and materialize a versioned feature dataset for native SQL preparation and model scoring.",
        "type": "data_query",
        "provider": "internal",
        "certification_level": "beta",
        "execution": {"mode": "async", "timeout_ms": 120000, "retryable": True, "idempotent": True},
        "pricing": {"unit": "per_call", "unit_price": 0.0, "currency": "EUR"},
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string"},
                "name": {"type": "string"},
                "slug": {"type": "string"},
                "version": {"type": "integer"},
                "rows": {"type": "integer"},
                "columns": {"type": "integer"},
                "provenance": {"type": "object"},
            },
        },
    }
)
