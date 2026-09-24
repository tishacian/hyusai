"""Seed a PIH-style maintenance demo dataset on SAP HANA Cloud.

Creates three tables (equipment, open/closed maintenance orders, spare parts)
with realistic PIH hydro rows. Idempotent: DROP (ignore missing) → CREATE → INSERT.

Row data lives in ``app.seeds.hana_demo_rows`` (shared with the
in-memory HANA fallback).

Credentials (never commit secrets):
    export HANA_HOST=...hna1.prod-us10.hanacloud.ondemand.com
    export HANA_PORT=443
    export HANA_USER=DBADMIN
    export HANA_PASSWORD='...'   # required

Usage:
    cd backend
    python -m scripts.seed_hana_demo_dataset

    # or with CLI overrides
    python -m scripts.seed_hana_demo_dataset \\
      --host "$HANA_HOST" --port 443 --user DBADMIN --password "$HANA_PASSWORD"

Demo defaults (host/port/user only — password must come from env or --password):
    Host: 535f81d3-5d3d-4313-92c6-187da6dd50a6.hna1.prod-us10.hanacloud.ondemand.com
    Port: 443
    User: DBADMIN
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

# Allow ``python -m scripts.seed_hana_demo_dataset`` to import ``app.*``.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from hdbcli import dbapi
except ImportError as exc:  # pragma: no cover - operator env
    raise SystemExit(
        "hdbcli is required. Install with: pip install 'hdbcli>=2.20'"
    ) from exc

from app.seeds.hana_demo_rows import (
    EQUIPMENT_ROWS,
    ORDER_ROWS,
    PART_ROWS,
    TABLE_EQUIPMENT,
    TABLE_ORDERS,
    TABLE_PARTS,
)

DEFAULT_HOST = (
    "535f81d3-5d3d-4313-92c6-187da6dd50a6"
    ".hna1.prod-us10.hanacloud.ondemand.com"
)
DEFAULT_PORT = 443
DEFAULT_USER = "DBADMIN"

DDL_DROP = [
    f'DROP TABLE "{TABLE_PARTS}"',
    f'DROP TABLE "{TABLE_ORDERS}"',
    f'DROP TABLE "{TABLE_EQUIPMENT}"',
]

# HANA Cloud trial (QRC) rejects DROP TABLE IF EXISTS; ignore missing-table errors.
_HANA_TABLE_NOT_FOUND = 259

DDL_CREATE = [
    f"""
    CREATE TABLE "{TABLE_EQUIPMENT}" (
        "EQUIPMENT_ID" NVARCHAR(20) PRIMARY KEY,
        "NAME" NVARCHAR(120) NOT NULL,
        "PLANT" NVARCHAR(40) NOT NULL,
        "FUNCTIONAL_LOCATION" NVARCHAR(80) NOT NULL,
        "EQUIPMENT_TYPE" NVARCHAR(40) NOT NULL,
        "CRITICALITY" NVARCHAR(10) NOT NULL,
        "STATUS" NVARCHAR(20) NOT NULL,
        "COMMISSIONED_ON" DATE
    )
    """,
    f"""
    CREATE TABLE "{TABLE_ORDERS}" (
        "ORDER_ID" NVARCHAR(20) PRIMARY KEY,
        "EQUIPMENT_ID" NVARCHAR(20) NOT NULL,
        "ORDER_TYPE" NVARCHAR(10) NOT NULL,
        "PRIORITY" NVARCHAR(10) NOT NULL,
        "STATUS" NVARCHAR(20) NOT NULL,
        "SHORT_TEXT" NVARCHAR(200) NOT NULL,
        "DESCRIPTION" NVARCHAR(1000),
        "PLANNED_START" DATE,
        "PLANNED_END" DATE,
        "CREATED_ON" TIMESTAMP NOT NULL,
        "WORK_CENTER" NVARCHAR(40)
    )
    """,
    f"""
    CREATE TABLE "{TABLE_PARTS}" (
        "PART_ID" NVARCHAR(20) PRIMARY KEY,
        "EQUIPMENT_ID" NVARCHAR(20) NOT NULL,
        "MATERIAL_NUMBER" NVARCHAR(40) NOT NULL,
        "DESCRIPTION" NVARCHAR(200) NOT NULL,
        "QTY_ON_HAND" INTEGER NOT NULL,
        "QTY_MIN" INTEGER NOT NULL,
        "UNIT" NVARCHAR(10) NOT NULL,
        "WAREHOUSE" NVARCHAR(40) NOT NULL,
        "LEAD_TIME_DAYS" INTEGER
    )
    """,
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed PIH maintenance demo tables on SAP HANA Cloud."
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("HANA_HOST", DEFAULT_HOST),
        help="HANA Cloud SQL endpoint host (env HANA_HOST).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("HANA_PORT", DEFAULT_PORT)),
        help="HANA Cloud SQL port (env HANA_PORT, default 443).",
    )
    parser.add_argument(
        "--user",
        default=os.environ.get("HANA_USER", DEFAULT_USER),
        help="DB user (env HANA_USER, default DBADMIN).",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("HANA_PASSWORD"),
        help="DB password (env HANA_PASSWORD). Required.",
    )
    parser.add_argument(
        "--schema",
        default=os.environ.get("HANA_SCHEMA"),
        help="Optional schema to SET SCHEMA before DDL (env HANA_SCHEMA).",
    )
    return parser.parse_args()


def connect(args: argparse.Namespace):
    if not args.password:
        raise SystemExit(
            "HANA password missing. Set HANA_PASSWORD or pass --password."
        )
    return dbapi.connect(
        address=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        encrypt=True,
        sslValidateCertificate=True,
    )


def exec_many(cursor, statements: Sequence[str]) -> None:
    for sql in statements:
        cursor.execute(sql)


def drop_tables(cursor, statements: Sequence[str]) -> None:
    """Drop demo tables; ignore 'invalid table name' when absent."""
    for sql in statements:
        try:
            cursor.execute(sql)
        except dbapi.Error as exc:
            # (259, 'invalid table name: ...')
            code = exc.errorcode if hasattr(exc, "errorcode") else None
            if code != _HANA_TABLE_NOT_FOUND and "invalid table name" not in str(exc).lower():
                raise
            print(f"  skip (missing): {sql}")


def insert_rows(cursor, table: str, columns: Sequence[str], rows: Sequence[tuple]) -> int:
    placeholders = ", ".join("?" for _ in columns)
    col_list = ", ".join(f'"{c}"' for c in columns)
    sql = f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})'
    cursor.executemany(sql, list(rows))
    return len(rows)


def count_rows(cursor, table: str) -> int:
    cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def seed(args: argparse.Namespace) -> dict[str, int]:
    conn = connect(args)
    try:
        cursor = conn.cursor()
        if args.schema:
            cursor.execute(f'SET SCHEMA "{args.schema}"')

        cursor.execute("SELECT CURRENT_USER, CURRENT_SCHEMA FROM DUMMY")
        user, schema = cursor.fetchone()
        print(f"Connected as {user} (schema={schema}) → {args.host}:{args.port}")

        print("Dropping existing demo tables (if any)…")
        drop_tables(cursor, DDL_DROP)

        print("Creating demo tables…")
        exec_many(cursor, DDL_CREATE)

        print("Inserting sample rows…")
        n_eq = insert_rows(
            cursor,
            TABLE_EQUIPMENT,
            (
                "EQUIPMENT_ID",
                "NAME",
                "PLANT",
                "FUNCTIONAL_LOCATION",
                "EQUIPMENT_TYPE",
                "CRITICALITY",
                "STATUS",
                "COMMISSIONED_ON",
            ),
            EQUIPMENT_ROWS,
        )
        n_ord = insert_rows(
            cursor,
            TABLE_ORDERS,
            (
                "ORDER_ID",
                "EQUIPMENT_ID",
                "ORDER_TYPE",
                "PRIORITY",
                "STATUS",
                "SHORT_TEXT",
                "DESCRIPTION",
                "PLANNED_START",
                "PLANNED_END",
                "CREATED_ON",
                "WORK_CENTER",
            ),
            ORDER_ROWS,
        )
        n_parts = insert_rows(
            cursor,
            TABLE_PARTS,
            (
                "PART_ID",
                "EQUIPMENT_ID",
                "MATERIAL_NUMBER",
                "DESCRIPTION",
                "QTY_ON_HAND",
                "QTY_MIN",
                "UNIT",
                "WAREHOUSE",
                "LEAD_TIME_DAYS",
            ),
            PART_ROWS,
        )
        conn.commit()

        counts = {
            TABLE_EQUIPMENT: count_rows(cursor, TABLE_EQUIPMENT),
            TABLE_ORDERS: count_rows(cursor, TABLE_ORDERS),
            TABLE_PARTS: count_rows(cursor, TABLE_PARTS),
        }
        # Sanity: inserted counts must match live counts.
        assert counts[TABLE_EQUIPMENT] == n_eq
        assert counts[TABLE_ORDERS] == n_ord
        assert counts[TABLE_PARTS] == n_parts

        # Showcase query used later by the Flow Builder demo flow.
        cursor.execute(
            f"""
            SELECT "ORDER_ID", "EQUIPMENT_ID", "PRIORITY", "STATUS", "SHORT_TEXT"
            FROM "{TABLE_ORDERS}"
            WHERE "STATUS" IN ('OPEN', 'RELEASED')
            ORDER BY "PRIORITY" DESC, "ORDER_ID"
            """
        )
        open_orders = cursor.fetchall()
        print(f"Open/released maintenance orders: {len(open_orders)}")
        for row in open_orders:
            print(f"  {row[0]}  {row[1]}  {row[2]:<6}  {row[3]:<8}  {row[4]}")

        return counts
    finally:
        conn.close()


def main() -> int:
    args = parse_args()
    counts = seed(args)
    print("Seed complete:")
    for table, n in counts.items():
        print(f"  {table}: {n} row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
