"""In-memory demo dataset mirroring ``scripts/seed_hana_demo_dataset.py``.

When the live HANA Cloud connection is unreachable, ``run_query`` falls back
to executing the same SQL against an in-memory sqlite3 database seeded from
``demo_rows`` (shared with the HANA seed script).
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any, Mapping, Optional

from app.services.connectors.hana.demo_rows import (
    EQUIPMENT_ROWS,
    ORDER_ROWS,
    PART_ROWS,
    TABLE_EQUIPMENT,
    TABLE_ORDERS,
    TABLE_PARTS,
)

_DDL = (
    f"""
    CREATE TABLE "{TABLE_EQUIPMENT}" (
        "EQUIPMENT_ID" TEXT PRIMARY KEY,
        "NAME" TEXT NOT NULL,
        "PLANT" TEXT NOT NULL,
        "FUNCTIONAL_LOCATION" TEXT NOT NULL,
        "EQUIPMENT_TYPE" TEXT NOT NULL,
        "CRITICALITY" TEXT NOT NULL,
        "STATUS" TEXT NOT NULL,
        "COMMISSIONED_ON" TEXT
    )
    """,
    f"""
    CREATE TABLE "{TABLE_ORDERS}" (
        "ORDER_ID" TEXT PRIMARY KEY,
        "EQUIPMENT_ID" TEXT NOT NULL,
        "ORDER_TYPE" TEXT NOT NULL,
        "PRIORITY" TEXT NOT NULL,
        "STATUS" TEXT NOT NULL,
        "SHORT_TEXT" TEXT NOT NULL,
        "DESCRIPTION" TEXT,
        "PLANNED_START" TEXT,
        "PLANNED_END" TEXT,
        "CREATED_ON" TEXT NOT NULL,
        "WORK_CENTER" TEXT
    )
    """,
    f"""
    CREATE TABLE "{TABLE_PARTS}" (
        "PART_ID" TEXT PRIMARY KEY,
        "EQUIPMENT_ID" TEXT NOT NULL,
        "MATERIAL_NUMBER" TEXT NOT NULL,
        "DESCRIPTION" TEXT NOT NULL,
        "QTY_ON_HAND" INTEGER NOT NULL,
        "QTY_MIN" INTEGER NOT NULL,
        "UNIT" TEXT NOT NULL,
        "WAREHOUSE" TEXT NOT NULL,
        "LEAD_TIME_DAYS" INTEGER
    )
    """,
)

_SEED = (
    (TABLE_EQUIPMENT, 8, EQUIPMENT_ROWS),
    (TABLE_ORDERS, 11, ORDER_ROWS),
    (TABLE_PARTS, 9, PART_ROWS),
)


def _build_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    for ddl in _DDL:
        conn.execute(ddl)
    for table, n_cols, rows in _SEED:
        placeholders = ", ".join("?" for _ in range(n_cols))
        conn.executemany(
            f'INSERT INTO "{table}" VALUES ({placeholders})', list(rows)
        )
    conn.commit()
    return conn


def run_demo_query(
    sql: str,
    params: Optional[Any] = None,
    *,
    limit: int = 200,
) -> dict[str, Any]:
    """Execute a read-only SQL statement against the seeded demo dataset.

    Returns the same shape as the live path plus ``source: demo_dataset``.
    """
    started = time.perf_counter()
    conn = _build_connection()
    try:
        if params is None:
            cursor = conn.execute(sql)
        elif isinstance(params, Mapping):
            cursor = conn.execute(sql, dict(params))
        else:
            cursor = conn.execute(sql, list(params))
        description = cursor.description or []
        columns = [str(col[0]) for col in description]
        rows = [list(row) for row in cursor.fetchmany(limit)] if columns else []
    finally:
        conn.close()
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "source": "demo_dataset",
    }
