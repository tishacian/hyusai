"""Bounded Luma Maison reads on the workspace PostgreSQL connector.

No caller SQL, connection parameters, identifiers or credentials are accepted.
All five dossier reads share one read-only, repeatable-read transaction. A failed
lookup is an error, never an empty refund list or a synthetic replacement.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from app.services.connectors.generic.service import get_config

CLAIM_ID = re.compile(r"RC-[0-9]{4,8}")
MAX_ROWS = 100
MAX_RESULT_BYTES = 256_000
CLAIM_RESOURCES = [
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
]
QUERIES = {
    "context": """SELECT c.claim_id, LEFT(c.reason,4000) AS reason, c.state, c.opened_at,
 o.order_id, o.ordered_at, o.paid_amount, o.currency, o.payment_status,
 o.shipping_postcode, u.customer_id, LEFT(u.display_name,255) AS display_name
 FROM showcase_ecommerce.claims c
 JOIN showcase_ecommerce.orders o ON o.order_id=c.order_id
 JOIN showcase_ecommerce.customers u ON u.customer_id=o.customer_id
 WHERE c.claim_id=%(claim_id)s LIMIT 1""",
    "items": """SELECT i.item_id, LEFT(i.product_name,255) AS product_name, i.quantity, i.unit_price
 FROM showcase_ecommerce.order_items i JOIN showcase_ecommerce.claims c ON c.order_id=i.order_id
 WHERE c.claim_id=%(claim_id)s ORDER BY i.item_id LIMIT 101""",
    "shipments": """SELECT s.shipment_id, s.tracking_id, s.carrier, s.status, s.status_at
 FROM showcase_ecommerce.shipments s JOIN showcase_ecommerce.claims c ON c.order_id=s.order_id
 WHERE c.claim_id=%(claim_id)s ORDER BY s.status_at DESC, s.shipment_id LIMIT 101""",
    "refunds": """SELECT r.refund_id, r.amount, r.currency, r.status, r.executed_at
 FROM showcase_ecommerce.refunds r JOIN showcase_ecommerce.claims c ON c.order_id=r.order_id
 WHERE c.claim_id=%(claim_id)s ORDER BY r.executed_at DESC NULLS LAST, r.refund_id LIMIT 101""",
    "documents": """SELECT d.document_key, d.source_filename, d.document_type, d.version,
 d.effective_from, d.order_id, d.sha256, d.knowledge_source_id
 FROM showcase_ecommerce.document_refs d JOIN showcase_ecommerce.claims c
 ON (d.order_id=c.order_id OR d.order_id IS NULL)
 WHERE c.claim_id=%(claim_id)s AND d.is_current
 ORDER BY d.document_type, d.document_key LIMIT 101""",
    "queue": """SELECT c.claim_id, c.order_id, LEFT(c.reason,4000) AS reason, c.state, c.opened_at,
 o.paid_amount, o.currency, LEFT(u.display_name,255) AS display_name
 FROM showcase_ecommerce.claims c JOIN showcase_ecommerce.orders o ON o.order_id=c.order_id
 JOIN showcase_ecommerce.customers u ON u.customer_id=o.customer_id
 WHERE c.claim_id=ANY(%(claim_ids)s)
 ORDER BY c.opened_at, c.claim_id LIMIT 101""",
}


class ClaimReadError(ValueError):
    def __init__(self, code: str, status_code: int = 503):
        self.code, self.status_code = code, status_code
        super().__init__(code)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def validate_claim_id(value: Any) -> str:
    if not isinstance(value, str) or not CLAIM_ID.fullmatch(value):
        raise ClaimReadError("CLAIM_ID_INVALID", 422)
    return value


def _read(workspace, names: tuple[str, ...], params: dict[str, Any]) -> dict[str, Any]:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    connection = None
    try:
        config = get_config(workspace, "postgresql", include_secrets=True)
        values, secrets = config.get("values") or {}, config.get("secrets") or {}
        if not all(values.get(key) for key in ("host", "database", "username")) or not secrets.get(
            "password"
        ):
            raise ClaimReadError("POSTGRESQL_NOT_CONFIGURED", 409)
        connection = psycopg2.connect(
            host=values["host"],
            port=int(values.get("port") or 5432),
            dbname=values["database"],
            user=values["username"],
            password=secrets["password"],
            connect_timeout=5,
            application_name="agentium-claims-reader",
        )
        connection.set_session(isolation_level="REPEATABLE READ", readonly=True, autocommit=False)
        results: dict[str, Any] = {}
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SET LOCAL statement_timeout = '5s'")
            cursor.execute("SET LOCAL lock_timeout = '1s'")
            cursor.execute("SET LOCAL idle_in_transaction_session_timeout = '5s'")
            for name in names:
                cursor.execute(QUERIES[name], params)
                rows = [
                    {key: _value(value) for key, value in dict(row).items()}
                    for row in cursor.fetchall()
                ]
                if len(rows) > MAX_ROWS:
                    raise ClaimReadError("POSTGRESQL_RESULT_LIMIT", 409)
                results[name] = rows
                if len(canonical(results).encode()) > MAX_RESULT_BYTES:
                    raise ClaimReadError("POSTGRESQL_RESULT_LIMIT", 409)
        return {
            "data": results,
            "provenance": {
                "source": "postgresql",
                "connector_id": "postgresql",
                "read_mode": "live",
                "isolation": "repeatable_read",
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "snapshot_sha256": digest(results),
                "business_parameters": params,
                "queries": [
                    {"id": name, "sha256": hashlib.sha256(QUERIES[name].encode()).hexdigest()}
                    for name in names
                ],
                "schema": "showcase_ecommerce",
                "evidence_kind": "synthetic_demo",
            },
        }
    except ClaimReadError:
        raise
    except Exception as exc:
        code = {
            "42P01": "POSTGRESQL_SCHEMA_NOT_LOADED",
            "42501": "POSTGRESQL_PERMISSION_DENIED",
            "57014": "POSTGRESQL_READ_TIMEOUT",
        }.get(getattr(exc, "pgcode", None), "POSTGRESQL_READ_UNAVAILABLE")
        # Driver messages can contain connection credentials or SQL. Never echo.
        raise ClaimReadError(code) from None
    finally:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
            try:
                connection.close()
            except Exception:
                pass


def snapshot(workspace, claim_id: str) -> dict[str, Any]:
    result = _read(
        workspace,
        ("context", "items", "shipments", "refunds", "documents"),
        {"claim_id": validate_claim_id(claim_id)},
    )
    if not result["data"]["context"]:
        raise ClaimReadError("CLAIM_NOT_FOUND", 404)
    result["provenance"]["resources_read"] = [dict(resource) for resource in CLAIM_RESOURCES]
    return result


def queue(workspace, claim_ids: list[str]) -> dict[str, Any]:
    if not isinstance(claim_ids, list) or not 1 <= len(claim_ids) <= MAX_ROWS:
        raise ClaimReadError("CLAIM_COHORT_INVALID", 422)
    return _read(
        workspace, ("queue",), {"claim_ids": sorted({validate_claim_id(c) for c in claim_ids})}
    )
