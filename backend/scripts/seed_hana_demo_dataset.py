"""Seed a PIH-style maintenance demo dataset on SAP HANA Cloud.

Creates three tables (equipment, open/closed maintenance orders, spare parts)
with a few realistic rows. Idempotent: DROP (ignore missing) → CREATE → INSERT.

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
from typing import Any, Sequence

try:
    from hdbcli import dbapi
except ImportError as exc:  # pragma: no cover - operator env
    raise SystemExit(
        "hdbcli is required. Install with: pip install 'hdbcli>=2.20'"
    ) from exc


DEFAULT_HOST = (
    "535f81d3-5d3d-4313-92c6-187da6dd50a6"
    ".hna1.prod-us10.hanacloud.ondemand.com"
)
DEFAULT_PORT = 443
DEFAULT_USER = "DBADMIN"

# Schema prefix keeps demo objects easy to find / drop on a shared trial DB.
TABLE_EQUIPMENT = "DEMO_EQUIPMENT"
TABLE_ORDERS = "DEMO_MAINTENANCE_ORDERS"
TABLE_PARTS = "DEMO_SPARE_PARTS"

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

EQUIPMENT_ROWS: Sequence[tuple[Any, ...]] = (
    (
        "EQ-PIH-G2-01",
        "Kaplan turbine G2 — Rivage Lac",
        "PIH-HYDRO-NORD",
        "PIH-HYDRO/G2/TURBINE",
        "Turbine",
        "A",
        "OPERATING",
        "2014-06-12",
    ),
    (
        "EQ-PIH-G2-02",
        "Guide bearing assembly G2",
        "PIH-HYDRO-NORD",
        "PIH-HYDRO/G2/BEARING",
        "Bearing",
        "A",
        "OPERATING",
        "2018-03-21",
    ),
    (
        "EQ-PIH-AUX-11",
        "Cooling water pump P-11",
        "PIH-HYDRO-NORD",
        "PIH-HYDRO/AUX/CW-P11",
        "Pump",
        "B",
        "OPERATING",
        "2016-11-02",
    ),
    (
        "EQ-PIH-TRF-03",
        "Step-up transformer T3",
        "PIH-HYDRO-SUD",
        "PIH-HYDRO/T3/TRANSFORMER",
        "Transformer",
        "A",
        "OPERATING",
        "2012-09-30",
    ),
)

ORDER_ROWS: Sequence[tuple[Any, ...]] = (
    (
        "4500124101",
        "EQ-PIH-G2-01",
        "PM02",
        "HIGH",
        "OPEN",
        "Vibration post-revision Kaplan G2",
        "Vibration trend above threshold after Kaplan overhaul. "
        "Cross-check Metris 48h export before spare-parts escalation.",
        "2026-07-18",
        "2026-07-25",
        "2026-07-18 08:15:00",
        "MECH-HYDRO-01",
    ),
    (
        "4500124102",
        "EQ-PIH-G2-02",
        "PM01",
        "MEDIUM",
        "OPEN",
        "Guide bearing oil analysis overdue",
        "Preventive oil sampling and viscosity check per runbook v4.",
        "2026-07-20",
        "2026-07-28",
        "2026-07-19 10:40:00",
        "MECH-HYDRO-01",
    ),
    (
        "4500124103",
        "EQ-PIH-AUX-11",
        "PM02",
        "HIGH",
        "OPEN",
        "Cooling pump P-11 seal leak",
        "Visible seal leak at packing gland. Isolate and replace mechanical seal.",
        "2026-07-21",
        "2026-07-23",
        "2026-07-21 06:05:00",
        "MECH-AUX-02",
    ),
    (
        "4500123988",
        "EQ-PIH-TRF-03",
        "PM01",
        "LOW",
        "CLOSED",
        "Annual dissolved-gas analysis T3",
        "DGA within limits. No corrective action required.",
        "2026-06-01",
        "2026-06-03",
        "2026-05-28 14:00:00",
        "ELEC-HV-01",
    ),
    (
        "4500124055",
        "EQ-PIH-G2-01",
        "PM06",
        "MEDIUM",
        "RELEASED",
        "Kaplan G2 major overhaul follow-up",
        "Post-overhaul punch-list: shaft seal torque verification and alignment check.",
        "2026-07-22",
        "2026-07-30",
        "2026-07-15 09:30:00",
        "MECH-HYDRO-01",
    ),
)

PART_ROWS: Sequence[tuple[Any, ...]] = (
    (
        "SP-PIH-001",
        "EQ-PIH-G2-01",
        "MAT-SEAL-KAP-G2",
        "Shaft seal kit — Kaplan G2",
        2,
        1,
        "EA",
        "WH-HYDRO-NORD",
        21,
    ),
    (
        "SP-PIH-002",
        "EQ-PIH-G2-02",
        "MAT-BRG-GUIDE-G2",
        "Guide bearing pad set — G2",
        1,
        1,
        "SET",
        "WH-HYDRO-NORD",
        45,
    ),
    (
        "SP-PIH-003",
        "EQ-PIH-AUX-11",
        "MAT-SEAL-MECH-P11",
        "Mechanical seal — cooling pump P-11",
        0,
        2,
        "EA",
        "WH-HYDRO-NORD",
        14,
    ),
    (
        "SP-PIH-004",
        "EQ-PIH-TRF-03",
        "MAT-BUSH-HV-T3",
        "HV bushing — transformer T3",
        1,
        1,
        "EA",
        "WH-HYDRO-SUD",
        60,
    ),
    (
        "SP-PIH-005",
        "EQ-PIH-G2-01",
        "MAT-OIL-ISOVG68",
        "Turbine bearing oil ISO VG 68 (200 L drum)",
        6,
        2,
        "DRM",
        "WH-HYDRO-NORD",
        7,
    ),
)


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
