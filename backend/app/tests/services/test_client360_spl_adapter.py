"""Unit tests for Client360 SPL adapter (no large binary fixtures)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
from app.models.workspace import Workspace
from app.services.client360_contract import CLIENT360_INSTALLED_BASE_COLLECTION_SLUG
from app.services.client360_pdr import classify_data_source
from app.services.client360_spl_adapter import (
    detect_spl_role,
    map_row_for_role,
    months_to_weeks,
    passes_phase1_scope,
    sync_sources_from_collection,
)


def _seed_workspace(db_session, *, slug: str = "andritz") -> Workspace:
    workspace = Workspace(
        id=str(uuid4()),
        name=slug.title(),
        slug=slug,
        settings={"family": "andritz"},
    )
    db_session.add(workspace)
    db_session.flush()
    return workspace


def test_classify_installed_base_spl_and_underscored_names() -> None:
    assert (
        classify_data_source("Installed_base_SPL/Installed base - Machine.xlsx")
        == "installed_base"
    )
    assert (
        classify_data_source("Installed_base_SPL/Installed base - SPC.xlsx") == "installed_base"
    )
    assert classify_data_source("Family - Opportunity.xlsx") == "periodicity"
    assert classify_data_source("Family_Opportunity.xlsx") == "periodicity"
    assert classify_data_source("Sales_By_Country.xlsx") == "sap_sales_history"
    assert classify_data_source("Materials_Consumptions.xlsx") == "other"
    assert classify_data_source("Base installée TURQUIE.xlsx") == "installed_base"


def test_months_to_weeks_conversion() -> None:
    assert months_to_weeks(1) == pytest.approx(4.345)
    assert months_to_weeks(12) == pytest.approx(52.14)
    assert months_to_weeks(None) is None
    assert months_to_weeks(0) is None


def test_map_family_opportunity_months_to_weeks() -> None:
    mapped = map_row_for_role(
        "family_opportunity",
        {
            "Familly": "Injector Strip",
            "Periodicity": 6,
            "IB Turkey": 40,
            "Price": 120.5,
            "Currency": "EUR",
        },
    )
    assert mapped is not None
    assert mapped["part_family"] == "Injector Strip"
    assert mapped["periodicity_weeks"] == pytest.approx(26.07)
    assert mapped["periodicity_months_raw"] == 6
    assert mapped["installed_quantity"] == 40
    assert mapped["sales_known_value"] == 120.5


def test_map_machine_and_spc_and_sales() -> None:
    machine = map_row_for_role(
        "machine",
        {
            "Equipment Sold to party name": "Septona SA",
            "Object Description": "JETLACE Line",
            "Machine": "JL-01",
            "Country Key": "GR",
            "Project Name": "Oinofyta",
            "Construction year": 2018,
        },
    )
    assert machine["customer_name"] == "Septona SA"
    assert machine["country"] == "GR"
    assert machine["machine_label"] == "JL-01"

    spc = map_row_for_role(
        "spc",
        {
            "Sold name": "Septona SA",
            "Number": "PDR-100",
            "Title": "Injector Strip",
            "Quantity": 8,
            "Country Key": "GR",
        },
    )
    assert spc["part_reference"] == "PDR-100"
    assert spc["installed_quantity"] == 8

    sales = map_row_for_role(
        "sales_by_country",
        {
            "Country Key": "TR",
            "Material": "MAT-1",
            "Net value": 500,
            "Quantity": 2,
        },
    )
    assert sales["country"] == "TR"
    assert sales["sales_known_value"] == 500


def test_phase1_scope_filter() -> None:
    assert passes_phase1_scope({"country": "Greece", "customer_name": "Other"})
    assert passes_phase1_scope({"country": "TR", "customer_name": "Acme"})
    assert passes_phase1_scope({"customer_name": "Septona SA", "country": "France"})
    assert passes_phase1_scope({"part_family": "Injector Strip", "periodicity_weeks": 26})
    assert not passes_phase1_scope({"country": "France", "customer_name": "Acme"})
    assert not passes_phase1_scope(
        {
            "country": "Greece",
            "customer_name": "Acme",
            "technology": "Needlepunch carding",
        }
    )


def test_detect_spl_role() -> None:
    assert detect_spl_role("Installed_base_SPL/Installed base - SPC.xlsx") == "spc"
    assert detect_spl_role("Family - Opportunity.xlsx") == "family_opportunity"
    assert detect_spl_role("Sales_By_Country.xlsx") == "sales_by_country"
    assert detect_spl_role("Client360_Pilot/SEPTONA - Client 360.xlsx") == "pilot"


def test_sync_from_collection_dry_run_with_xlsx_fixture(db_session, tmp_path, monkeypatch) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    workspace = _seed_workspace(db_session)
    collection = KnowledgeCollection(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
        name="Andritz Client360 Installed Base",
        status="ready",
        document_names=["Family - Opportunity.xlsx"],
        vector_collection_name="andritz_client360_installed_base",
        artifact_prefix=f"knowledge/{CLIENT360_INSTALLED_BASE_COLLECTION_SLUG}/",
        document_count=1,
        chunk_count=0,
    )
    source = KnowledgeCollectionSource(
        id=str(uuid4()),
        workspace_id=workspace.id,
        collection_id=collection.id,
        filename="Family - Opportunity.xlsx",
        normalized_name="Family - Opportunity.xlsx",
        source_kind="spreadsheet",
        extension=".xlsx",
        origin="test",
        status="ready",
    )
    db_session.add_all([collection, source])
    db_session.commit()

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Familly", "Periodicity", "IB Turkey", "Price", "Currency"])
    sheet.append(["Injector Strip", 3, 12, 99.0, "EUR"])
    sheet.append(["O'ring", 2, 5, 10.0, "EUR"])
    xlsx_path = tmp_path / "Family - Opportunity.xlsx"
    workbook.save(xlsx_path)

    def fake_materialize(db, workspace_arg, collection_arg, filename):
        return Path(xlsx_path), source.id, None

    monkeypatch.setattr(
        "app.services.client360_spl_adapter._materialize_collection_file",
        fake_materialize,
    )

    result = sync_sources_from_collection(
        db_session,
        workspace,
        collection_slug=CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
        dry_run=True,
        scope="phase1",
    )

    assert result["dry_run"] is True
    assert result["collection_slug"] == CLIENT360_INSTALLED_BASE_COLLECTION_SLUG
    assert result["sources_upserted"] >= 1
    previews = [item for item in result["sources"] if item.get("action") == "preview"]
    assert previews
    family = next(item for item in previews if item.get("source_type") == "periodicity")
    assert family["row_count"] == 2
    assert family["metadata"]["adapter_version"]
    records = family["metadata"]["records"]
    assert records[0]["periodicity_weeks"] == pytest.approx(13.035)
    assert records[0]["part_family"] == "Injector Strip"
