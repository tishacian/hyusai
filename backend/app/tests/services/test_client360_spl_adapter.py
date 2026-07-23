"""Unit tests for Client360 SPL adapter (no large binary fixtures)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
from app.models.workspace import Workspace
from app.services.client360_contract import CLIENT360_INSTALLED_BASE_COLLECTION_SLUG
from app.services.client360_pdr import classify_data_source
from app.models.client360 import Client360DataSource
from app.services.client360_contract import CLIENT360_PILOT_DATASET_MARKER
from app.services.client360_pdr import client360_scope
from app.services.client360_spl_adapter import (
    aggregate_purchase_history_records,
    aggregate_sales_orders_records,
    aggregate_spc_records,
    build_project_registry_index,
    detect_spl_role,
    expand_project_registry_records,
    map_row_for_role,
    months_to_weeks,
    passes_phase1_scope,
    rehydrate_pilot_mvp_into_collection,
    resolve_customer_for_project,
    sales_orders_row_accepted,
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
    assert (
        classify_data_source(
            "Installed_base_SPL/Histo_Achat_Pieces_Machines_Montbonnot.xlsx"
        )
        == "other"
    )
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
    # Must not match ``machine`` via "Machines" in the basename.
    assert (
        detect_spl_role(
            "Installed_base_SPL/Histo_Achat_Pieces_Machines_Montbonnot.xlsx"
        )
        == "purchase_history"
    )
    # project_registry before machine; sales_orders distinct from sales_by_country.
    assert (
        detect_spl_role("Installed_base_SPL/Liste Projets _ Clients.xlsx")
        == "project_registry"
    )
    assert (
        detect_spl_role(
            "Installed_base_SPL/Liste Sales Orders D800 MNT SPL 2011_2026 VA05.xlsx"
        )
        == "sales_orders"
    )


def test_classify_project_registry_and_sales_orders() -> None:
    assert (
        classify_data_source("Installed_base_SPL/Liste Projets _ Clients.xlsx")
        == "contact_hub"
    )
    assert (
        classify_data_source(
            "Liste Sales Orders D800 MNT SPL 2011_2026 VA05.xlsx"
        )
        == "sap_sales_history"
    )


def test_map_project_registry_multi_codes() -> None:
    mapped = map_row_for_role(
        "project_registry",
        {
            "CONTRACT NAME": "SEP100\nXEP100",
            "FINAL CUSTOMER": "Eruslu Tekstil",
            "SAP REFERENCE": "4500123",
            "Site Country": "Turkey",
        },
    )
    assert mapped is not None
    assert mapped["customer_name"] == "Eruslu Tekstil"
    assert mapped["sap_reference"] == "4500123"
    assert mapped["country"] == "Turkey"
    assert mapped["project_codes"] == ["SEP100", "XEP100"]
    expanded = expand_project_registry_records([mapped])
    assert len(expanded) == 2
    assert {row["project_code"] for row in expanded} == {"SEP100", "XEP100"}
    assert all(row["customer_name"] == "Eruslu Tekstil" for row in expanded)


def test_resolve_customer_for_project_from_registry() -> None:
    records = expand_project_registry_records(
        [
            {
                "project_codes": ["SEP100", "XEP100"],
                "customer_name": "Eruslu Tekstil",
                "sap_reference": "4500123",
                "country": "Turkey",
            }
        ]
    )
    index = build_project_registry_index(records)
    by_project = resolve_customer_for_project("SEP100", index=index)
    assert by_project is not None
    assert by_project["customer_name"] == "Eruslu Tekstil"
    assert by_project["country"] == "Turkey"
    by_sap = resolve_customer_for_project(sap_ref="4500123", index=index)
    assert by_sap is not None
    assert by_sap["customer_name"] == "Eruslu Tekstil"
    assert resolve_customer_for_project("UNKNOWN", index=index) is None


def test_sales_orders_filters_and_aggregation() -> None:
    keep = map_row_for_role(
        "sales_orders",
        {
            "Sold-To Party Name": "Mogul Nonwovens",
            "Material": "MAT-1",
            "Description": "Injector strip",
            "Order Quantity": 2,
            "Net Price": 50.0,
            "Offering": "SSPA",
            "Document Date": "2021-06-15",
            "Currency": "EUR",
        },
    )
    assert keep is not None
    assert keep["sales_known_value"] == pytest.approx(100.0)
    assert sales_orders_row_accepted(keep) is True

    andritz = map_row_for_role(
        "sales_orders",
        {
            "Sold-To Party Name": "ANDRITZ SAS",
            "Material": "MAT-1",
            "Order Quantity": 1,
            "Net Price": 10.0,
            "Offering": "SSPA",
            "Document Date": "2022-01-01",
        },
    )
    assert sales_orders_row_accepted(andritz) is False

    dummy = map_row_for_role(
        "sales_orders",
        {
            "Sold-To Party Name": "Dummy Customer FR",
            "Material": "MAT-1",
            "Order Quantity": 1,
            "Net Price": 10.0,
            "Offering": "SSPA",
            "Document Date": "2022-01-01",
        },
    )
    assert sales_orders_row_accepted(dummy) is False

    old = map_row_for_role(
        "sales_orders",
        {
            "Sold-To Party Name": "Mogul Nonwovens",
            "Material": "MAT-1",
            "Order Quantity": 1,
            "Net Price": 10.0,
            "Offering": "SSPA",
            "Document Date": "2015-01-01",
        },
    )
    assert sales_orders_row_accepted(old) is False

    non_sspa = map_row_for_role(
        "sales_orders",
        {
            "Sold-To Party Name": "Mogul Nonwovens",
            "Material": "MAT-1",
            "Order Quantity": 1,
            "Net Price": 10.0,
            "Offering": "MACHINE",
            "Document Date": "2022-01-01",
        },
    )
    assert sales_orders_row_accepted(non_sspa) is False

    rows = [
        keep,
        map_row_for_role(
            "sales_orders",
            {
                "Sold-To Party Name": "Mogul Nonwovens",
                "Material": "MAT-1",
                "Description": "Injector strip",
                "Order Quantity": 3,
                "Net Price": 40.0,
                "Offering": "SSPA",
                "Document Date": "2023-01-01",
                "Currency": "EUR",
            },
        ),
    ]
    aggregated, meta = aggregate_sales_orders_records(rows)
    assert meta["aggregation"] == "by_customer_material"
    assert meta["material_count"] == 1
    assert len(aggregated) == 1
    assert aggregated[0]["sales_known_qty"] == pytest.approx(5.0)
    assert aggregated[0]["sales_known_value"] == pytest.approx(220.0)
    assert aggregated[0]["role"] == "sales_orders"


def test_aggregate_spc_joins_registry_country() -> None:
    registry = build_project_registry_index(
        [
            {
                "project_code": "SEP100",
                "customer_name": "Septona SA",
                "customer_key": "septona sa",
                "country": "Greece",
                "sap_reference": "111",
            }
        ]
    )
    aggregated, meta = aggregate_spc_records(
        [
            {
                "customer_name": "Septona SA",
                "customer_key": "septona sa",
                "part_reference": "PDR-1",
                "part_description": "Strip",
                "installed_quantity": 2,
                "country": None,
            },
            {
                "customer_name": "Septona SA",
                "customer_key": "septona sa",
                "part_reference": "PDR-1",
                "part_description": "Strip",
                "installed_quantity": 3,
                "country": None,
            },
            {
                "customer_name": "Septona SA",
                "customer_key": "septona sa",
                "part_reference": "PDR-2",
                "part_description": "Belt",
                "installed_quantity": 0,
                "country": None,
            },
        ],
        registry_index=registry,
    )
    assert meta["aggregation"] == "by_customer_material"
    assert len(aggregated) == 1
    assert aggregated[0]["part_reference"] == "PDR-1"
    assert aggregated[0]["installed_quantity"] == pytest.approx(5.0)
    assert aggregated[0]["country"] == "Greece"
    assert meta["registry_country_joins"] == 1


def test_client360_scope_mode_pilot_and_all() -> None:
    from app.services.client360_pdr import _scope_skip_reason

    pilot_ws = Workspace(
        id=str(uuid4()),
        name="Andritz",
        slug="andritz",
        settings={},
    )
    pilot_scope = client360_scope(pilot_ws)
    assert pilot_scope["scope_mode"] == "pilot"
    assert (
        _scope_skip_reason(
            {
                "country": "France",
                "customer_name": "Acme",
                "part_family": "wear strip",
                "mapping_status": "validated",
            },
            pilot_scope,
        )
        == "country_out_of_pilot_scope"
    )

    all_ws = Workspace(
        id=str(uuid4()),
        name="Andritz",
        slug="andritz",
        settings={"client360_pdr_scope": {"scope_mode": "all"}},
    )
    all_scope = client360_scope(all_ws)
    assert all_scope["scope_mode"] == "all"
    assert (
        _scope_skip_reason(
            {
                "country": "France",
                "customer_name": "Acme",
                "part_family": "wear strip",
                "mapping_status": "validated",
            },
            all_scope,
        )
        is None
    )
    # Wear-parts mapping gate remains in scope_mode=all.
    assert (
        _scope_skip_reason(
            {
                "country": "France",
                "customer_name": "Acme",
                "part_family": "structural frame",
            },
            all_scope,
        )
        == "not_confirmed_wear_part"
    )


def test_map_purchase_history_has_no_sales_or_customer_fields() -> None:
    mapped = map_row_for_role(
        "purchase_history",
        {
            "Material": "MAT-PH-1",
            "Material Description": "Injector strip",
            "(EUR) Net order value": 120.0,
            "Currency": "EUR",
            "Planned Deliv# Time": 6,
            "Project definition": "P-100",
            "Name": "Montbonnot workshop",
            "Andritz WBS Element": "WBS-1",
            "Vendor Name": "Vendor SA",
            "Country": "FR",
        },
    )
    assert mapped is not None
    assert mapped["part_reference"] == "MAT-PH-1"
    assert mapped["unit_cost"] == 120.0
    assert mapped["delivery_time_weeks"] == 6
    assert mapped["vendor_country"] == "FR"
    assert "country" not in mapped
    assert "sales_known_qty" not in mapped
    assert "sales_known_value" not in mapped
    assert "customer_name" not in mapped
    assert "customer_key" not in mapped
    assert "installed_quantity" not in mapped


def test_aggregate_purchase_history_by_material() -> None:
    rows = [
        {
            "part_reference": "MAT-1",
            "part_description": "Part A",
            "unit_cost": 100.0,
            "delivery_time_weeks": 4,
            "currency": "EUR",
            "project_name": "P1",
            "wbs_element": "W1",
            "vendor_name": "V1",
            "vendor_country": "FR",
        },
        {
            "part_reference": "MAT-1",
            "part_description": "Part A",
            "unit_cost": 200.0,
            "delivery_time_weeks": 8,
            "currency": "EUR",
            "project_name": "P2",
            "wbs_element": "W2",
            "vendor_name": "V2",
            "vendor_country": "DE",
        },
        {
            "part_reference": "MAT-1",
            "part_description": "Part A alt",
            "unit_cost": 150.0,
            "delivery_time_weeks": 6,
            "currency": "EUR",
            "project_name": "P3",
            "wbs_element": "W3",
            "vendor_name": "V3",
            "vendor_country": "FR",
        },
    ]
    aggregated, meta = aggregate_purchase_history_records(rows)
    assert meta["aggregation"] == "by_material"
    assert meta["material_count"] == 1
    assert meta["po_lines_seen"] == 3
    assert len(aggregated) == 1
    record = aggregated[0]
    assert record["part_reference"] == "MAT-1"
    assert record["unit_cost"] == pytest.approx(150.0)
    assert record["delivery_time_weeks"] == pytest.approx(6.0)
    assert record["po_count"] == 3
    assert record["role"] == "purchase_history"
    assert "sales_known_qty" not in record
    assert "sales_known_value" not in record


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
    assert result.get("mvp_sources_linked") == 0


def _purchase_history_xlsx(tmp_path: Path) -> Path:
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "View_ASAP_PO_Delivered_By_Proje"
    sheet.append(
        [
            "Material",
            "Material Description",
            "(EUR) Net order value",
            "Currency",
            "Planned Deliv# Time",
            "Project definition",
            "Name",
            "Andritz WBS Element",
            "Vendor Name",
            "Country",
        ]
    )
    sheet.append(
        ["MAT-PH-1", "Injector strip", 100.0, "EUR", 4, "P1", "Proj A", "W1", "Vendor", "FR"]
    )
    sheet.append(
        ["MAT-PH-1", "Injector strip", 200.0, "EUR", 8, "P2", "Proj B", "W2", "Vendor", "FR"]
    )
    sheet.append(
        ["MAT-PH-1", "Injector strip", 150.0, "EUR", 6, "P3", "Proj C", "W3", "Vendor", "DE"]
    )
    path = tmp_path / "Histo_Achat_Pieces_Machines_Montbonnot.xlsx"
    workbook.save(path)
    return path


def test_sync_phase1_skips_purchase_history(db_session, tmp_path, monkeypatch) -> None:
    workspace = _seed_workspace(db_session)
    filename = "Histo_Achat_Pieces_Machines_Montbonnot.xlsx"
    collection = KnowledgeCollection(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
        name="Andritz Client360 Installed Base",
        status="ready",
        document_names=[filename],
        vector_collection_name="andritz_client360_installed_base",
        artifact_prefix=f"knowledge/{CLIENT360_INSTALLED_BASE_COLLECTION_SLUG}/",
        document_count=1,
        chunk_count=0,
    )
    source = KnowledgeCollectionSource(
        id=str(uuid4()),
        workspace_id=workspace.id,
        collection_id=collection.id,
        filename=filename,
        normalized_name=filename,
        source_kind="spreadsheet",
        extension=".xlsx",
        origin="test",
        status="ready",
    )
    db_session.add_all([collection, source])
    db_session.commit()

    xlsx_path = _purchase_history_xlsx(tmp_path)

    def fake_materialize(db, workspace_arg, collection_arg, name):
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
        rehydrate_mvp=False,
    )
    skipped = [item for item in result["sources"] if item.get("action") == "skipped"]
    assert any(
        item.get("reason") == "purchase_history_deferred_phase2" for item in skipped
    )
    assert result["skipped"].get("purchase_history_deferred") == 1
    assert result["include_purchase_history"] is False


def test_sync_include_purchase_history_upserts_other(
    db_session, tmp_path, monkeypatch
) -> None:
    workspace = _seed_workspace(db_session)
    filename = "Histo_Achat_Pieces_Machines_Montbonnot.xlsx"
    collection = KnowledgeCollection(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
        name="Andritz Client360 Installed Base",
        status="ready",
        document_names=[filename],
        vector_collection_name="andritz_client360_installed_base",
        artifact_prefix=f"knowledge/{CLIENT360_INSTALLED_BASE_COLLECTION_SLUG}/",
        document_count=1,
        chunk_count=0,
    )
    source = KnowledgeCollectionSource(
        id=str(uuid4()),
        workspace_id=workspace.id,
        collection_id=collection.id,
        filename=filename,
        normalized_name=filename,
        source_kind="spreadsheet",
        extension=".xlsx",
        origin="test",
        status="ready",
    )
    db_session.add_all([collection, source])
    db_session.commit()

    xlsx_path = _purchase_history_xlsx(tmp_path)

    def fake_materialize(db, workspace_arg, collection_arg, name):
        return Path(xlsx_path), source.id, None

    monkeypatch.setattr(
        "app.services.client360_spl_adapter._materialize_collection_file",
        fake_materialize,
    )

    result = sync_sources_from_collection(
        db_session,
        workspace,
        collection_slug=CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
        dry_run=False,
        scope="phase1",
        rehydrate_mvp=False,
        include_purchase_history=True,
    )
    assert result["include_purchase_history"] is True
    assert result["sources_upserted"] >= 1
    upserted = next(
        item
        for item in result["sources"]
        if item.get("action") in {"created", "updated"}
    )
    assert upserted["source_type"] == "other"
    assert upserted["metadata"]["role"] == "purchase_history"
    assert upserted["metadata"]["aggregation"] == "by_material"
    assert upserted["row_count"] == 1.0
    records = upserted["metadata"]["records"]
    assert len(records) == 1
    assert records[0]["part_reference"] == "MAT-PH-1"
    assert records[0]["unit_cost"] == pytest.approx(150.0)
    assert records[0]["delivery_time_weeks"] == pytest.approx(6.0)
    assert "sales_known_qty" not in records[0]
    assert "sales_known_value" not in records[0]

    row = (
        db_session.query(Client360DataSource)
        .filter(Client360DataSource.workspace_id == workspace.id)
        .one()
    )
    assert row.source_type == "other"
    assert row.meta_data["role"] == "purchase_history"


def _spc_xlsx(tmp_path: Path) -> Path:
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Sold name", "Number", "Title", "Quantity", "Country Key"])
    sheet.append(["Septona SA", "PDR-1", "Injector Strip", 4, "GR"])
    sheet.append(["Septona SA", "PDR-1", "Injector Strip", 2, "GR"])
    path = tmp_path / "Installed base - SPC.xlsx"
    workbook.save(path)
    return path


def test_sync_phase1_skips_spc_without_flag(db_session, tmp_path, monkeypatch) -> None:
    workspace = _seed_workspace(db_session)
    filename = "Installed base - SPC.xlsx"
    collection = KnowledgeCollection(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
        name="Andritz Client360 Installed Base",
        status="ready",
        document_names=[filename],
        vector_collection_name="andritz_client360_installed_base",
        artifact_prefix=f"knowledge/{CLIENT360_INSTALLED_BASE_COLLECTION_SLUG}/",
        document_count=1,
        chunk_count=0,
    )
    source = KnowledgeCollectionSource(
        id=str(uuid4()),
        workspace_id=workspace.id,
        collection_id=collection.id,
        filename=filename,
        normalized_name=filename,
        source_kind="spreadsheet",
        extension=".xlsx",
        origin="test",
        status="ready",
    )
    db_session.add_all([collection, source])
    db_session.commit()

    xlsx_path = _spc_xlsx(tmp_path)

    def fake_materialize(db, workspace_arg, collection_arg, name):
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
        rehydrate_mvp=False,
    )
    skipped = [item for item in result["sources"] if item.get("action") == "skipped"]
    assert any(
        item.get("reason") == "spc_deferred_until_include_spc_or_scope_all"
        for item in skipped
    )
    assert result["include_spc"] is False


def test_sync_include_spc_aggregates(db_session, tmp_path, monkeypatch) -> None:
    workspace = _seed_workspace(db_session)
    filename = "Installed base - SPC.xlsx"
    collection = KnowledgeCollection(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
        name="Andritz Client360 Installed Base",
        status="ready",
        document_names=[filename],
        vector_collection_name="andritz_client360_installed_base",
        artifact_prefix=f"knowledge/{CLIENT360_INSTALLED_BASE_COLLECTION_SLUG}/",
        document_count=1,
        chunk_count=0,
    )
    source = KnowledgeCollectionSource(
        id=str(uuid4()),
        workspace_id=workspace.id,
        collection_id=collection.id,
        filename=filename,
        normalized_name=filename,
        source_kind="spreadsheet",
        extension=".xlsx",
        origin="test",
        status="ready",
    )
    db_session.add_all([collection, source])
    db_session.commit()

    xlsx_path = _spc_xlsx(tmp_path)

    def fake_materialize(db, workspace_arg, collection_arg, name):
        return Path(xlsx_path), source.id, None

    monkeypatch.setattr(
        "app.services.client360_spl_adapter._materialize_collection_file",
        fake_materialize,
    )

    result = sync_sources_from_collection(
        db_session,
        workspace,
        collection_slug=CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
        dry_run=False,
        scope="phase1",
        rehydrate_mvp=False,
        include_spc=True,
    )
    assert result["include_spc"] is True
    assert result["sources_upserted"] >= 1
    upserted = next(
        item
        for item in result["sources"]
        if item.get("action") in {"created", "updated"}
    )
    assert upserted["source_type"] == "installed_base"
    assert upserted["metadata"]["role"] == "spc"
    assert upserted["metadata"]["aggregation"] == "by_customer_material"
    assert upserted["row_count"] == 1.0
    assert upserted["metadata"]["records"][0]["installed_quantity"] == pytest.approx(6.0)


def test_sync_project_registry_always(db_session, tmp_path, monkeypatch) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    workspace = _seed_workspace(db_session)
    filename = "Liste Projets _ Clients.xlsx"
    collection = KnowledgeCollection(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
        name="Andritz Client360 Installed Base",
        status="ready",
        document_names=[filename],
        vector_collection_name="andritz_client360_installed_base",
        artifact_prefix=f"knowledge/{CLIENT360_INSTALLED_BASE_COLLECTION_SLUG}/",
        document_count=1,
        chunk_count=0,
    )
    source = KnowledgeCollectionSource(
        id=str(uuid4()),
        workspace_id=workspace.id,
        collection_id=collection.id,
        filename=filename,
        normalized_name=filename,
        source_kind="spreadsheet",
        extension=".xlsx",
        origin="test",
        status="ready",
    )
    db_session.add_all([collection, source])
    db_session.commit()

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["CONTRACT NAME", "FINAL CUSTOMER", "SAP REFERENCE", "Site Country"])
    sheet.append(["SEP100\nXEP100", "Eruslu Tekstil", "4500123", "Turkey"])
    sheet.append(["FR-99", "Acme France", "999", "France"])
    xlsx_path = tmp_path / filename
    workbook.save(xlsx_path)

    def fake_materialize(db, workspace_arg, collection_arg, name):
        return Path(xlsx_path), source.id, None

    monkeypatch.setattr(
        "app.services.client360_spl_adapter._materialize_collection_file",
        fake_materialize,
    )

    result = sync_sources_from_collection(
        db_session,
        workspace,
        collection_slug=CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
        dry_run=False,
        scope="phase1",
        rehydrate_mvp=False,
    )
    upserted = next(
        item
        for item in result["sources"]
        if item.get("action") in {"created", "updated"}
    )
    assert upserted["source_type"] == "contact_hub"
    assert upserted["metadata"]["role"] == "project_registry"
    # France row kept (registry is not country-filtered); multi-code expanded.
    assert upserted["row_count"] == 3.0


def test_sync_rehydrates_mvp_without_promoted_files(db_session) -> None:
    workspace = _seed_workspace(db_session)
    collection = KnowledgeCollection(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
        name="Andritz Client360 Installed Base",
        status="created",
        document_names=[],
        vector_collection_name="andritz_client360_installed_base",
        artifact_prefix=f"knowledge/{CLIENT360_INSTALLED_BASE_COLLECTION_SLUG}/",
        document_count=0,
        chunk_count=0,
    )
    orphan = Client360DataSource(
        id=str(uuid4()),
        workspace_id=workspace.id,
        source_type="installed_base",
        label="MVP Pilot - Septona Greece installed base",
        filename="SEPTONA - Client 360.xlsx",
        status="ready",
        row_count=1,
        meta_data={
            "pilot_dataset": CLIENT360_PILOT_DATASET_MARKER,
            "records": [{"customer_name": "Septona S.A.", "country": "Greece", "installed_quantity": 1}],
        },
    )
    db_session.add_all([collection, orphan])
    db_session.commit()

    result = sync_sources_from_collection(
        db_session,
        workspace,
        collection_slug=CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
        dry_run=False,
        scope="phase1",
        rehydrate_mvp=True,
    )
    assert result["mvp_sources_linked"] == 1
    assert result["files_seen"] == 0
    db_session.refresh(orphan)
    assert orphan.collection_slug == CLIENT360_INSTALLED_BASE_COLLECTION_SLUG
    assert orphan.meta_data.get("rehydrated_from_mvp") is True

    preview = rehydrate_pilot_mvp_into_collection(
        db_session, workspace, dry_run=True
    )
    assert preview["count"] == 0  # already linked + adapter_version stamped
