"""HANA catalog preview lists demo tables when live SQL is unreachable."""

from __future__ import annotations

import pytest

from app.services.connectors.hana import service as hana_service
from app.services.connectors.hana.demo_rows import TABLE_EQUIPMENT, TABLE_ORDERS


def test_preview_falls_back_to_demo_tables(monkeypatch):
    monkeypatch.setattr(
        hana_service,
        "test_connection",
        lambda _cfg: (_ for _ in ()).throw(RuntimeError("down")),
    )
    result = hana_service.preview_catalog(
        {"host": "example.hanacloud", "user": "DBADMIN", "password": "x"}
    )
    names = {item["name"] for item in result["tables"]}
    assert result["ok"] is True
    assert result["source"] == "demo_dataset"
    assert TABLE_EQUIPMENT in names
    assert TABLE_ORDERS in names
    assert result["sample_table"] == TABLE_EQUIPMENT
    assert result["row_count"] > 0
    assert "EQUIPMENT_ID" in result["columns"]


def test_preview_can_sample_a_named_demo_table(monkeypatch):
    monkeypatch.setattr(
        hana_service,
        "test_connection",
        lambda _cfg: (_ for _ in ()).throw(RuntimeError("down")),
    )
    result = hana_service.preview_catalog(
        {"host": "example.hanacloud", "user": "DBADMIN", "password": "x"},
        table=TABLE_ORDERS,
    )
    assert result["sample_table"] == TABLE_ORDERS
    assert "ORDER_ID" in result["columns"]
    assert result["row_count"] > 0


def test_preview_rejects_unknown_or_unsafe_table(monkeypatch):
    monkeypatch.setattr(
        hana_service,
        "test_connection",
        lambda _cfg: (_ for _ in ()).throw(RuntimeError("down")),
    )
    with pytest.raises(ValueError, match="not in the preview catalog"):
        hana_service.preview_catalog(
            {"host": "example.hanacloud", "user": "DBADMIN", "password": "x"},
            table="not_a_table",
        )
    with pytest.raises(ValueError, match="not in the preview catalog"):
        hana_service.preview_catalog(
            {"host": "example.hanacloud", "user": "DBADMIN", "password": "x"},
            table='ORDERS"; DROP TABLE X;--',
        )


def test_preview_live_lists_tables_from_query(monkeypatch):
    monkeypatch.setattr(
        hana_service,
        "test_connection",
        lambda _cfg: {"ok": True, "current_user": "DBADMIN", "current_schema": "S4"},
    )

    def fake_query(_config, sql, params=None, *, max_rows=200, allow_writes=False):
        if "FROM TABLES" in sql:
            return {
                "columns": ["TABLE_NAME", "TABLE_TYPE"],
                "rows": [["EKKO", "COLUMN"], ["EKPO", "COLUMN"]],
                "row_count": 2,
                "source": "hana_live",
            }
        assert "S4" in sql and "EKKO" in sql
        return {
            "columns": ["EBELN", "BUKRS"],
            "rows": [["4500001", "1000"]],
            "row_count": 1,
            "source": "hana_live",
        }

    monkeypatch.setattr(hana_service, "run_query", fake_query)
    result = hana_service.preview_catalog(
        {"host": "example.hanacloud", "user": "DBADMIN", "password": "x"}
    )
    assert result["source"] == "hana_live"
    assert [item["name"] for item in result["tables"]] == ["EKKO", "EKPO"]
    assert result["sample_table"] == "EKKO"
    assert result["rows"] == [["4500001", "1000"]]
