"""Exact-value tests for the line-item reconciliation skill suite.

The two committed fixtures are synthetic sample documents (a PO register
workbook and a one-page text invoice) whose numbers are the contract: the
extractors must reproduce them exactly, the reconcile must find precisely the
two known discrepancies, and the report must be byte-stable.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.secure_deposit import DepositAccessLink, DepositFile
from app.models.user import User
from app.models.workspace import Workspace
from app.services.skills_registry import wrappers
from app.services.skills_registry.file_resolution import FileResolutionError

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "po_invoice_recon"
XLSX_NAME = "PO_Register_Sample.xlsx"
PDF_NAME = "Invoice_INV-8834_Sample.pdf"

# Raw text of the fixture invoice as extracted by the two PDF backends the
# platform may run on. PyPDF2 (local venv) emits the two header columns as
# separate line blocks; pdfplumber (production image, captured verbatim from
# pdfplumber 0.11.10 on the live backend) merges the side-by-side columns
# onto shared physical lines. Header parsing must succeed on BOTH.
PYPDF2_TEXT = (
    "INVOICE\n"
    " Sample document — created for Agentium Flow Builder demo only\n"
    "From:\n"
    "Al Fanar Industrial Supplies W.L.L.\n"
    "Industrial Area, Street 42\n"
    "Doha, Qatar\n"
    "Tax ID: QA-TX-119284\n"
    "Invoice No: INV-8834\n"
    "Invoice Date: 14 July 2026\n"
    "PO Reference: PO-2026-0451\n"
    "Due Date: 13 August 2026\n"
    "Bill To:\n"
    "PowerMinds Inc. — PIH Qatar Operations\n"
    "Procurement Department\n"
    "Doha, Qatar\n"
    "#\n"
    "Description\n"
    "Qty\n"
    "Unit Price\n"
    "(QAR)\n"
    "Line Total\n"
    "(QAR)\n"
    "1\n"
    "Industrial Bearings SKF-6205\n"
    "50\n"
    "45.00\n"
    "2,250.00\n"
    "2\n"
    'Hydraulic Hose 3/4"\n'
    "18\n"
    "120.00\n"
    "2,160.00\n"
    "3\n"
    "Safety Valves DN50\n"
    "10\n"
    "365.00\n"
    "3,650.00\n"
    "4\n"
    "Lubricant Grease 5kg Tub\n"
    "30\n"
    "60.00\n"
    "1,800.00\n"
    "Subtotal (QAR)\n"
    "9,860.00\n"
    "VAT (0% — free zone)\n"
    "0.00\n"
    "Total Due (QAR)\n"
    "9,860.00\n"
    "Payment Terms: Net 30 days from invoice date. Bank transfer to Al Fanar"
    " Industrial Supplies, Qatar National\n"
    "Bank, IBAN QA00 QNBA 0000 0000 0000 0000 0000.\n"
    "This is a synthetic sample invoice generated for a product demonstration."
    " It does not represent a real transaction, vendor, or financial\n"
    "obligation.\n"
)
PDFPLUMBER_TEXT = (
    "INVOICE\n"
    "Sample document — created for Agentium Flow Builder demo only\n"
    "From: Invoice No: INV-8834\n"
    "Al Fanar Industrial Supplies W.L.L. Invoice Date: 14 July 2026\n"
    "Industrial Area, Street 42 PO Reference: PO-2026-0451\n"
    "Doha, Qatar Due Date: 13 August 2026\n"
    "Tax ID: QA-TX-119284\n"
    "Bill To:\n"
    "PowerMinds Inc. — PIH Qatar Operations\n"
    "Procurement Department\n"
    "Doha, Qatar\n"
    "Unit Price Line Total\n"
    "# Description Qty\n"
    "(QAR) (QAR)\n"
    "1 Industrial Bearings SKF-6205 50 45.00 2,250.00\n"
    '2 Hydraulic Hose 3/4" 18 120.00 2,160.00\n'
    "3 Safety Valves DN50 10 365.00 3,650.00\n"
    "4 Lubricant Grease 5kg Tub 30 60.00 1,800.00\n"
    "Subtotal (QAR) 9,860.00\n"
    "VAT (0% — free zone) 0.00\n"
    "Total Due (QAR) 9,860.00\n"
    "Payment Terms: Net 30 days from invoice date. Bank transfer to Al Fanar"
    " Industrial Supplies, Qatar National\n"
    "Bank, IBAN QA00 QNBA 0000 0000 0000 0000 0000.\n"
    "This is a synthetic sample invoice generated for a product demonstration."
    " It does not represent a real transaction, vendor, or financial\n"
    "obligation."
)


def _stage_deposit(db_session, tmp_path, monkeypatch):
    """Two staged Secure Deposit files (xlsx + pdf) promoted to one collection."""
    root = tmp_path / "secure-deposit"
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(root))
    workspace = Workspace(id="ws-recon", slug="recon", name="Recon")
    user = User(id="user-recon", username="recon", email="recon@example.test")
    link = DepositAccessLink(
        id="link-recon",
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        label="Supplier drop",
        access_id="recon-link",
        password_hash="hash",
        allowed_extensions=[],
    )
    db_session.add_all([workspace, user, link])
    rows = {}
    for file_id, filename in (("dep-po-xlsx", XLSX_NAME), ("dep-invoice-pdf", PDF_NAME)):
        content = (FIXTURES / filename).read_bytes()
        object_key = f"workspaces/{workspace.id}/secure-deposit/recon/{filename}"
        path = root / object_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        row = DepositFile(
            id=file_id,
            workspace_id=workspace.id,
            access_link_id=link.id,
            filename=filename,
            object_key=object_key,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            status="promoted",
            promoted_collection_slug="supplier-drop",
        )
        db_session.add(row)
        rows[file_id] = row
    db_session.commit()
    return workspace, rows


def _ctx(db_session, workspace) -> dict:
    return {"db": db_session, "workspace_id": workspace.id, "input": {}}


async def test_spreadsheet_extract_returns_all_rows_with_computed_totals(
    db_session, tmp_path, monkeypatch
):
    workspace, _rows = _stage_deposit(db_session, tmp_path, monkeypatch)

    result = await wrappers._spreadsheet_table_extract_v1(
        {"file_ids": ["dep-po-xlsx", "dep-invoice-pdf"], "sheet": "PO Register"},
        _ctx(db_session, workspace),
    )

    assert result["columns"] == [
        "PO Number", "Vendor", "Line Item", "Description",
        "Quantity", "Unit Price (QAR)", "Total Amount (QAR)",
    ]
    assert result["row_count"] == 8
    assert result["source_file"] == XLSX_NAME
    assert [row["PO Number"] for row in result["rows"]] == (
        ["PO-2026-0451"] * 4 + ["PO-2026-0452"] * 2 + ["PO-2026-0453"] * 2
    )
    # Formula cells must come back as numbers, never "=E5*F5" strings.
    assert [row["Total Amount (QAR)"] for row in result["rows"]] == [
        2250, 2400, 3500, 1800, 3280, 1425, 1950, 1680,
    ]
    first = result["rows"][0]
    assert first["Description"] == "Industrial Bearings SKF-6205"
    assert first["Quantity"] == 50
    assert first["Unit Price (QAR)"] == 45


async def test_spreadsheet_extract_filters_to_the_referenced_po(
    db_session, tmp_path, monkeypatch
):
    workspace, _rows = _stage_deposit(db_session, tmp_path, monkeypatch)

    result = await wrappers._spreadsheet_table_extract_v1(
        {"file_id": "dep-po-xlsx", "filters": {"PO Number": "PO-2026-0451"}},
        _ctx(db_session, workspace),
    )

    assert result["row_count"] == 4
    assert [
        (row["Description"], row["Quantity"], row["Unit Price (QAR)"])
        for row in result["rows"]
    ] == [
        ("Industrial Bearings SKF-6205", 50, 45),
        ('Hydraulic Hose 3/4"', 20, 120),
        ("Safety Valves DN50", 10, 350),
        ("Lubricant Grease 5kg Tub", 30, 60),
    ]


def test_spreadsheet_extract_computes_uncached_formula_cells():
    """A workbook written by openpyxl itself carries no cached formula values;
    the simple binary formulas must be evaluated, not leaked as strings."""
    from io import BytesIO

    from openpyxl import Workbook

    from app.services.reconciliation import extract_spreadsheet_table

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Description", "Quantity", "Unit Price", "Total"])
    sheet.append(["Widget", 4, 25, "=B2*C2"])
    sheet.append(["Gadget", 3, 10, "=B3*C3"])
    buffer = BytesIO()
    workbook.save(buffer)

    result = extract_spreadsheet_table(buffer.getvalue())

    assert [row["Total"] for row in result["rows"]] == [100, 30]


@pytest.mark.parametrize(
    "raw_text",
    [PYPDF2_TEXT, PDFPLUMBER_TEXT],
    ids=["pypdf2-token-per-line", "pdfplumber-merged-columns"],
)
def test_invoice_header_fields_parse_on_both_text_layouts(raw_text):
    """The five header fields must parse exactly whichever PDF text backend
    produced the text — including pdfplumber's column-merged layout where
    ``From:`` and the label block share physical lines."""
    from app.services.reconciliation import extract_invoice_fields

    result = extract_invoice_fields(raw_text)

    assert result["invoice_number"] == "INV-8834"
    assert result["invoice_date"] == "14 July 2026"
    assert result["po_reference"] == "PO-2026-0451"
    assert result["due_date"] == "13 August 2026"
    assert result["vendor"] == "Al Fanar Industrial Supplies W.L.L."
    # Line items and totals were already layout-proof; keep them pinned.
    assert len(result["line_items"]) == 4
    assert result["subtotal"] == 9860.0
    assert result["vat"] == 0.0
    assert result["total_due"] == 9860.0
    assert result["currency"] == "QAR"


async def test_invoice_extract_returns_every_field_exactly(
    db_session, tmp_path, monkeypatch
):
    workspace, _rows = _stage_deposit(db_session, tmp_path, monkeypatch)

    result = await wrappers._invoice_document_extract_v1(
        {"collection_slug": "supplier-drop", "filename_pattern": "*.pdf"},
        _ctx(db_session, workspace),
    )

    assert result["invoice_number"] == "INV-8834"
    assert result["invoice_date"] == "14 July 2026"
    assert result["po_reference"] == "PO-2026-0451"
    assert result["due_date"] == "13 August 2026"
    assert result["vendor"] == "Al Fanar Industrial Supplies W.L.L."
    assert result["line_items"] == [
        {"description": "Industrial Bearings SKF-6205", "qty": 50.0,
         "unit_price": 45.0, "line_total": 2250.0},
        {"description": 'Hydraulic Hose 3/4"', "qty": 18.0,
         "unit_price": 120.0, "line_total": 2160.0},
        {"description": "Safety Valves DN50", "qty": 10.0,
         "unit_price": 365.0, "line_total": 3650.0},
        {"description": "Lubricant Grease 5kg Tub", "qty": 30.0,
         "unit_price": 60.0, "line_total": 1800.0},
    ]
    assert result["subtotal"] == 9860.0
    assert result["vat"] == 0.0
    assert result["total_due"] == 9860.0
    assert result["currency"] == "QAR"
    assert result["source_file"] == PDF_NAME


async def test_extractors_read_file_reference_from_the_run_input(
    db_session, tmp_path, monkeypatch
):
    """The same graph serves every ingress: with no explicit inputs_map the
    extractor falls back to the run input (deposit.promoted payload shape)."""
    workspace, _rows = _stage_deposit(db_session, tmp_path, monkeypatch)
    ctx = _ctx(db_session, workspace)
    ctx["input"] = {"file_ids": ["dep-po-xlsx", "dep-invoice-pdf"]}

    spreadsheet = await wrappers._spreadsheet_table_extract_v1({}, ctx)
    invoice = await wrappers._invoice_document_extract_v1({}, ctx)

    assert spreadsheet["row_count"] == 8
    assert invoice["invoice_number"] == "INV-8834"


async def test_reconcile_finds_exactly_the_two_expected_discrepancies(
    db_session, tmp_path, monkeypatch
):
    workspace, _rows = _stage_deposit(db_session, tmp_path, monkeypatch)
    ctx = _ctx(db_session, workspace)
    invoice = await wrappers._invoice_document_extract_v1({"file_id": "dep-invoice-pdf"}, ctx)
    spreadsheet = await wrappers._spreadsheet_table_extract_v1(
        {"file_id": "dep-po-xlsx", "filters": {"PO Number": invoice["po_reference"]}},
        ctx,
    )

    result = await wrappers._line_items_reconcile_v1(
        {
            "po_lines": spreadsheet["rows"],
            "invoice_lines": invoice["line_items"],
            "po_reference": invoice["po_reference"],
            "tolerance_pct": 2.0,
        },
        ctx,
    )

    assert result["po_reference"] == "PO-2026-0451"
    assert result["tolerance_pct"] == 2.0
    assert [(line["description"], line["status"]) for line in result["lines"]] == [
        ("Industrial Bearings SKF-6205", "matched"),
        ('Hydraulic Hose 3/4"', "qty_mismatch"),
        ("Safety Valves DN50", "price_mismatch"),
        ("Lubricant Grease 5kg Tub", "matched"),
    ]
    hose = result["lines"][1]
    assert (hose["po_qty"], hose["invoice_qty"], hose["qty_variance_pct"]) == (20.0, 18.0, -10.0)
    assert hose["price_variance_pct"] == 0.0
    valves = result["lines"][2]
    assert (valves["po_unit_price"], valves["invoice_unit_price"]) == (350.0, 365.0)
    assert valves["price_variance_pct"] == 4.29
    assert valves["qty_variance_pct"] == 0.0
    assert result["matched_count"] == 2
    assert result["flagged_count"] == 2
    assert result["po_total"] == 9950.0
    assert result["invoice_total"] == 9860.0
    assert result["total_variance_pct"] == -0.9


async def test_reconcile_flags_nothing_on_identical_lines():
    lines = [
        {"description": "Industrial Bearings SKF-6205", "qty": 50, "unit_price": 45.0},
        {"description": 'Hydraulic Hose 3/4"', "qty": 18, "unit_price": 120.0},
    ]

    result = await wrappers._line_items_reconcile_v1(
        {"po_lines": lines, "invoice_lines": lines},
        {},
    )

    assert result["flagged_count"] == 0
    assert result["matched_count"] == 2
    assert {line["status"] for line in result["lines"]} == {"matched"}


async def test_report_is_deterministic_and_names_both_flagged_lines():
    reconciliation = {
        "po_reference": "PO-2026-0451",
        "tolerance_pct": 2.0,
        "matched_count": 2,
        "flagged_count": 2,
        "po_total": 9950.0,
        "invoice_total": 9860.0,
        "total_variance_pct": -0.9,
        "lines": [
            {"description": "Industrial Bearings SKF-6205", "po_qty": 50.0, "invoice_qty": 50.0,
             "qty_variance_pct": 0.0, "po_unit_price": 45.0, "invoice_unit_price": 45.0,
             "price_variance_pct": 0.0, "status": "matched"},
            {"description": 'Hydraulic Hose 3/4"', "po_qty": 20.0, "invoice_qty": 18.0,
             "qty_variance_pct": -10.0, "po_unit_price": 120.0, "invoice_unit_price": 120.0,
             "price_variance_pct": 0.0, "status": "qty_mismatch"},
            {"description": "Safety Valves DN50", "po_qty": 10.0, "invoice_qty": 10.0,
             "qty_variance_pct": 0.0, "po_unit_price": 350.0, "invoice_unit_price": 365.0,
             "price_variance_pct": 4.29, "status": "price_mismatch"},
            {"description": "Lubricant Grease 5kg Tub", "po_qty": 30.0, "invoice_qty": 30.0,
             "qty_variance_pct": 0.0, "po_unit_price": 60.0, "invoice_unit_price": 60.0,
             "price_variance_pct": 0.0, "status": "matched"},
        ],
    }
    payload = {
        "reconciliation": reconciliation,
        "verdict": "Needs Review",
        "invoice_meta": {
            "invoice_number": "INV-8834",
            "vendor": "Al Fanar Industrial Supplies W.L.L.",
            "invoice_date": "14 July 2026",
            "total_due": 9860.0,
        },
    }

    first = await wrappers._reconciliation_report_v1(payload, {})
    second = await wrappers._reconciliation_report_v1(payload, {})

    assert first == second, "report must be byte-stable across invocations"
    assert first["verdict"] == "Needs Review"
    assert first["flagged_count"] == 2
    text = first["report_text"]
    assert "Verdict: Needs Review" in text
    assert "INV-8834" in text and "PO-2026-0451" in text
    assert 'Hydraulic Hose 3/4"' in text and "Safety Valves DN50" in text
    assert "-10.00%" in text and "+4.29%" in text
    assert "Totals: PO 9,950.00 | Invoice 9,860.00" in text
    assert text.count("<-- FLAG") == 2
    assert text.count("- Review '") == 2


async def test_file_resolution_is_scoped_to_the_run_workspace(
    db_session, tmp_path, monkeypatch
):
    """Tenant isolation: a file_id from another workspace must never resolve."""
    _workspace, _rows = _stage_deposit(db_session, tmp_path, monkeypatch)
    intruder = Workspace(id="ws-intruder", slug="intruder", name="Intruder")
    db_session.add(intruder)
    db_session.commit()

    with pytest.raises(FileResolutionError, match="file_resolution_no_match"):
        await wrappers._spreadsheet_table_extract_v1(
            {"file_id": "dep-po-xlsx"},
            _ctx(db_session, intruder),
        )


async def test_missing_file_reference_fails_with_a_clear_error(
    db_session, tmp_path, monkeypatch
):
    workspace, _rows = _stage_deposit(db_session, tmp_path, monkeypatch)

    with pytest.raises(FileResolutionError, match="file_resolution_reference_missing"):
        await wrappers._invoice_document_extract_v1({}, _ctx(db_session, workspace))
    with pytest.raises(FileResolutionError, match="file_resolution_no_match"):
        await wrappers._invoice_document_extract_v1(
            {"collection_slug": "supplier-drop", "filename_pattern": "*.docx"},
            _ctx(db_session, workspace),
        )


def test_reconciliation_skills_are_seeded_and_bound():
    from app.services.skills_registry.seed import SEED_SKILLS, SKILL_CATEGORIES

    slugs = {
        "spreadsheet_table_extract_v1",
        "invoice_document_extract_v1",
        "line_items_reconcile_v1",
        "reconciliation_report_v1",
    }
    seeded = {entry["slug"] for entry in SEED_SKILLS}
    assert slugs <= seeded
    assert slugs <= set(SKILL_CATEGORIES)
    assert {slug: wrappers.runtime_status(slug) for slug in slugs} == {
        slug: "bound" for slug in slugs
    }
