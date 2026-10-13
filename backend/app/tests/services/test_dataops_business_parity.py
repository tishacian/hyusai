"""Existing business SQL remains the independent oracle for authored no-code specs."""

import csv
import hashlib
import json
from pathlib import Path

import duckdb
import pyarrow as pa

from app.schemas.data_prep import bind_spec
from app.services.dataops.compiler import compile_prep
from app.services.dataops.types import describe
from scripts.gen_nawa_telecom_data import churn_raw_frame, clean_churn_sql

ROOT = Path(__file__).resolve().parents[4]


def step(kind, **params):
    return {"id": f"business-{kind}", "kind": kind, "params": params}


def assert_business_parity(table, steps, reference_sql, *, expected_rows):
    # Several operations repeat; authored step identities remain stable and unique.
    steps = [{**item, "id": f"business-{index}-{item['kind']}"} for index, item in enumerate(steps)]
    spec = bind_spec(
        {"version": 1, "operation": "prepare", "params": {"steps": steps}},
        [{"port": "out", "name": "Business parity"}],
    )
    compiled = compile_prep(
        spec, {"in": describe(table.schema)}, arrow_schemas={"in": table.schema}
    )
    with duckdb.connect(config={"threads": 1, "memory_limit": "128MB"}) as conn:
        conn.execute("SET TimeZone='UTC'")
        conn.register("input", table)
        conn.register("in", table)
        expected = conn.execute(reference_sql).to_arrow_table()
        actual = conn.execute(compiled.sql, compiled.preview_parameters).to_arrow_table()
    assert len(actual) == len(expected) == expected_rows
    assert actual.schema.equals(expected.schema)
    assert [
        {key: f[key] for key in ("name", "dtype", "nullable")} for f in compiled.output_schema
    ] == [{key: f[key] for key in ("name", "dtype", "nullable")} for f in describe(expected.schema)]

    # Both specifications include the same final sort. Hash canonical row values,
    # not Parquet bytes, whose encodings and row-group boundaries may differ.
    def digest(result):
        return hashlib.sha256(
            json.dumps(
                result.to_pylist(), ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()

    assert digest(actual) == digest(expected)


def test_prepare_history_matches_existing_sql_with_timezone_aware_casts():
    fixtures = ROOT / "docs/demo-runs/showcase-ecommerce/fixtures/dataops"
    with (fixtures / "luma_sav_history_synthetic.csv").open(newline="") as source:
        # Raw export strings, including malformed/empty date values, exercise the
        # conversion steps instead of relying on CSV inference to prepare them.
        table = pa.Table.from_pylist(list(csv.DictReader(source)))
    assert len(table) == 1236  # 1,200 cases, 24 duplicate records and 12 invalid outcomes.
    steps = [
        step(
            "text_transform",
            columns=["claim_id", "claim_reason", "shipment_status"],
            operation="trim",
        ),
        step("text_transform", columns=["claim_reason", "shipment_status"], operation="lower"),
        step("cast", columns=["paid_amount"], to="double"),
        step("cast", columns=["already_refunded", "case_documents", "item_quantity"], to="integer"),
        step("cast", columns=["opened_at", "resolved_at"], to="timestamp_tz"),
        step(
            "filter_expression",
            expression=(
                "resolved_at > opened_at "
                "AND claim_reason IN ('delivery_disputed','parcel_lost','refund_requested') "
                "AND shipment_status IN ('delivered','lost','in_transit') "
                "AND paid_amount >= 0 AND already_refunded IN (0,1) "
                "AND case_documents >= 0 AND item_quantity > 0"
            ),
        ),
        step(
            "deduplicate",
            columns=["claim_id"],
            keep="first",
            order_by=[{"column": "resolved_at", "direction": "desc"}],
        ),
        step("date_add", column="opened_at", amount=72, unit="hour", output="after_72h"),
        step(
            "formula",
            output="resolution_over_72h",
            expression="cast(resolved_at > after_72h AS INTEGER)",
        ),
        step(
            "select_columns",
            columns=[
                "claim_id",
                "claim_reason",
                "paid_amount",
                "shipment_status",
                "already_refunded",
                "case_documents",
                "item_quantity",
                "resolution_over_72h",
            ],
        ),
        step("sort", keys=[{"column": "claim_id", "direction": "asc"}]),
    ]
    assert_business_parity(
        table, steps, (fixtures / "prepare_history.sql").read_text(), expected_rows=1200
    )


def test_nawa_a2_matches_existing_cleanup_sql_and_seeded_export():
    table = churn_raw_frame(seed=20260825).to_arrow()
    assert len(table) == 8412
    steps = [
        # Deduplicate BEFORE filtering: otherwise an older active snapshot could
        # bring back a subscriber whose most recent line is suspended.
        step(
            "deduplicate",
            columns=["msisdn"],
            keep="first",
            order_by=[{"column": "snapshot_date", "direction": "desc"}],
        ),
        step("text_transform", columns=["region", "plan"], operation="trim"),
        step("text_transform", columns=["region", "plan"], operation="lower"),
        step(
            "filter_expression",
            expression="line_status = 'active' AND arpu_mad IS NOT NULL AND arpu_mad >= 0",
        ),
        step(
            "select_columns",
            columns=[
                "msisdn",
                "region",
                "plan",
                "contract",
                "tenure_months",
                "arpu_mad",
                "data_gb",
                "voice_minutes",
                "sms_count",
                "intl_minutes",
                "roaming_days",
                "support_tickets",
                "dropped_calls",
                "avg_download_mbps",
                "late_payments",
                "device_age_months",
                "handset_tier",
                "fiber_bundle",
                "family_lines",
                "promo_discount_pct",
                "nps",
                "churn",
            ],
        ),
        step("sort", keys=[{"column": "msisdn", "direction": "asc"}]),
    ]
    assert_business_parity(table, steps, clean_churn_sql("input"), expected_rows=6903)
