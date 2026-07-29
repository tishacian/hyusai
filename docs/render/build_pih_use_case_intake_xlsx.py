# -*- coding: utf-8 -*-
"""Excel version of the PIH use-case intake & evaluation grid.

Mirrors docs/pih/Use-Case-Intake-Template-PIH.md. One sheet for the intake
grid (with Status dropdown + free-text columns for PIH answers and our
follow-up), one sheet for the Datategy evaluation returned to PIH.
Output: docs/pih/Use-Case-Intake-Template-PIH.xlsx
"""
import os
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "pih", "Use-Case-Intake-Template-PIH.xlsx")

NAVY = "0B2545"
BLUE = "2D6CDF"
TINT = "EAF1FD"
PANEL = "F3F5F8"
MUT = "596371"
LINE = "D7DCE3"

thin = Side(style="thin", color=LINE)
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)
WRAP = Alignment(vertical="top", wrap_text=True)

F_TITLE = Font(name="Calibri", size=15, bold=True, color=NAVY)
F_SUB = Font(name="Calibri", size=10, color=MUT)
F_SECTION = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
F_HEAD = Font(name="Calibri", size=10, bold=True, color=NAVY)
F_CELL = Font(name="Calibri", size=10)
F_ID = Font(name="Calibri", size=10, bold=True, color=BLUE)

FILL_SECTION = PatternFill("solid", fgColor=NAVY)
FILL_HEAD = PatternFill("solid", fgColor=TINT)
FILL_INPUT = PatternFill("solid", fgColor="FFFDF2")  # subtle: PIH fills these


def sheet_title(ws, title, subtitle, ncols):
    ws.cell(row=1, column=1, value=title).font = F_TITLE
    ws.cell(row=2, column=1, value=subtitle).font = F_SUB
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
    ws.cell(row=2, column=1).alignment = Alignment(vertical="top", wrap_text=True)
    ws.row_dimensions[2].height = 42


wb = Workbook()

# ============================================================== Sheet 1: intake
ws = wb.active
ws.title = "Intake grid"
HEADERS = ["#", "Item", "Why we need it", "Typical source",
           "Status", "PIH answer / reference", "Datategy follow-up question"]
WIDTHS = [6, 44, 40, 16, 13, 46, 46]
for i, w in enumerate(WIDTHS, start=1):
    ws.column_dimensions[get_column_letter(i)].width = w

sheet_title(
    ws,
    "Use Case Intake & Evaluation — Datategy × PIH",
    "How it works: PIH sends a use case in any format; we map it onto this grid, set the Status of "
    "each item (Provided / To clarify / Missing) and return the file with our questions within 2 "
    "working days. Items whose source is the requester usually need a short direct exchange with "
    "the business owner rather than a written loop. Yellow columns are filled by PIH.",
    len(HEADERS),
)

SECTIONS = [
    ("1 · Business framing", [
        ("1.1", "Business problem in one paragraph — what happens today, who suffers, at what frequency/volume",
         "Anchors scope and success criteria", "Requester"),
        ("1.2", "Requesting entity & business owner (name, role)",
         "Design-card sign-off, acceptance authority", "PowerMind / BA"),
        ("1.3", "Users of the agent (roles, count, languages EN/AR)",
         "UX, permissions, language stack", "Requester"),
        ("1.4", "Expected outcome & how success is measured today (KPI, SLA, cost/time per case)",
         "Golden-set design, value tracking in the Hypervisor", "Requester"),
        ("1.5", "Volume: cases per day/week, peak patterns, seasonality",
         "Sizing, run scheduling", "Requester / ops data"),
    ]),
    ("2 · Process & decision logic", [
        ("2.1", "Current process step by step (even informal) — inputs, decisions, outputs, exceptions",
         "Flow design; what stays human", "Requester walkthrough"),
        ("2.2", "Decision points: which are rule-based vs judgement-based",
         "Where gates / human approval sit", "Requester"),
        ("2.3", "10–20 worked examples of real cases with the expected correct outcome",
         "Seed of the golden set (stored at PIH, PIH IP)", "Requester / archives"),
        ("2.4", "Error tolerance: what happens if the agent is wrong; is a human review acceptable and where",
         "Gate placement, risk tier", "Requester + PowerMind"),
    ]),
    ("3 · Data & systems", [
        ("3.1", "Systems touched (SAP module/transaction, Databricks tables, file shares, email, other apps)",
         "Connector selection & access requests", "IT + requester"),
        ("3.2", "For each system: read or write? If write — which transactions, with what approval today",
         "Privileged-write policy, parallel-run validation", "IT"),
        ("3.3", "Data samples (anonymised acceptable at intake stage)",
         "Feasibility check, prompt/skill design", "BA"),
        ("3.4", "Documents involved: formats, volumes, languages, quality (scans? handwriting?)",
         "Document Center / OCR / indexing scope", "Requester"),
        ("3.5", "Data sensitivity & residency constraints (personal data, commercial, classified)",
         "Deployment tier, masking rules", "IT / compliance"),
    ]),
    ("4 · Access & environment (prerequisites)", [
        ("4.1", "Service accounts / API access to the systems in 3.1, sandbox first",
         "Build & test without touching production", "IT"),
        ("4.2", "Test environment or representative extract for the data in 3.3",
         "Golden-set runs before any production contact", "IT / BA"),
        ("4.3", "Named IT contact per system",
         "Unblocks access issues fast — historically the critical path", "IT"),
        ("4.4", "Where the agent must run: PIH on-prem / sovereign tenancy / Datategy SaaS (POC)",
         "Infrastructure & network prerequisites", "IT / PowerMind"),
    ]),
]

row = 4
dv = DataValidation(type="list", formula1='"Provided,To clarify,Missing,N/A"',
                    allow_blank=True, showDropDown=False)
ws.add_data_validation(dv)

for section, items in SECTIONS:
    c = ws.cell(row=row, column=1, value=section)
    c.font = F_SECTION
    c.fill = FILL_SECTION
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(HEADERS))
    for col in range(1, len(HEADERS) + 1):
        ws.cell(row=row, column=col).fill = FILL_SECTION
    row += 1
    for col, h in enumerate(HEADERS, start=1):
        c = ws.cell(row=row, column=col, value=h)
        c.font = F_HEAD
        c.fill = FILL_HEAD
        c.border = BORDER
        c.alignment = WRAP
    row += 1
    for item in items:
        vals = list(item) + ["", "", ""]
        for col, v in enumerate(vals, start=1):
            c = ws.cell(row=row, column=col, value=v or None)
            c.font = F_ID if col == 1 else F_CELL
            c.border = BORDER
            c.alignment = WRAP
            if col in (5, 6):
                c.fill = FILL_INPUT
        dv.add(ws.cell(row=row, column=5))
        ws.row_dimensions[row].height = 30
        row += 1
    row += 1  # blank spacer

ws.freeze_panes = "A4"

# ========================================================= Sheet 2: evaluation
ws2 = wb.create_sheet("Datategy evaluation")
HEADERS2 = ["#", "Item", "Content expected", "Datategy assessment"]
WIDTHS2 = [6, 26, 52, 64]
for i, w in enumerate(WIDTHS2, start=1):
    ws2.column_dimensions[get_column_letter(i)].width = w

sheet_title(
    ws2,
    "Datategy evaluation — returned to PIH",
    "Filled by Datategy once the intake grid is sufficiently complete. This is the structured "
    "answer that goes back to the BA / requester.",
    len(HEADERS2),
)

EVAL = [
    ("5.1", "Feasibility", "Feasible now / feasible with conditions / needs de-scoping — with reasons"),
    ("5.2", "Tier", "Simple / Medium / Complex, per the Annex B typology, with the drivers "
                    "(systems touched, write access, reasoning depth)"),
    ("5.3", "Reuse", "Which existing patterns / skills / connectors apply; what would be first-of-type"),
    ("5.4", "Effort & lead time", "Indicative build window once access (section 4) is confirmed — "
                                  "planning heuristic, not contractual"),
    ("5.5", "Open questions", "Questions back to the BA / requester, each tagged written-answer vs direct-exchange"),
    ("5.6", "Risks & assumptions", "Anything that could invalidate the estimate"),
]

r = 4
for col, h in enumerate(HEADERS2, start=1):
    c = ws2.cell(row=r, column=col, value=h)
    c.font = F_HEAD
    c.fill = FILL_HEAD
    c.border = BORDER
    c.alignment = WRAP
r += 1
for item in EVAL:
    for col, v in enumerate(list(item) + [""], start=1):
        c = ws2.cell(row=r, column=col, value=v or None)
        c.font = F_ID if col == 1 else F_CELL
        c.border = BORDER
        c.alignment = WRAP
        if col == 4:
            c.fill = FILL_INPUT
    ws2.row_dimensions[r].height = 44
    r += 1

r += 1
chain = ws2.cell(row=r, column=1, value=(
    "Next step once the use case is qualified: full capture with the Datategy delivery-methodology "
    "templates (ISO/IEC 42001 & 12792 aligned) — Business Requirements (DTG-METH-BR: why/what, "
    "personas, As-Is → To-Be, KPIs) → Target Operating Model (DTG-METH-TOM: human + agent value "
    "streams, HITL, RACI) → build → QA Acceptance Record (DTG-METH-QA: golden-set gates, "
    "procès-verbal de recette for go-live). This intake grid is the lightweight screening step "
    "before that chain."))
chain.font = F_SUB
chain.alignment = WRAP
ws2.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(HEADERS2))
ws2.row_dimensions[r].height = 56
r += 2
note = ws2.cell(row=r, column=1, value=(
    "Internal process note: for each use case, log date received, date returned, number of "
    "clarification round-trips, and which questions required a direct requester exchange — raw "
    "material for refining the CoE / PowerMind / PIH operating process."))
note.font = F_SUB
note.alignment = WRAP
ws2.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(HEADERS2))
ws2.row_dimensions[r].height = 40

# ========================================================= tracker sheet
ws3 = wb.create_sheet("Use case log")
HEADERS3 = ["Use case", "Received", "Returned", "Turnaround (days)",
            "Clarification round-trips", "Direct requester exchanges needed", "Status", "Notes"]
WIDTHS3 = [34, 12, 12, 16, 20, 26, 16, 40]
for i, w in enumerate(WIDTHS3, start=1):
    ws3.column_dimensions[get_column_letter(i)].width = w
sheet_title(
    ws3,
    "Use case log (internal)",
    "One line per use case received — feeds the process-refinement objective agreed with the sponsor.",
    len(HEADERS3),
)
for col, h in enumerate(HEADERS3, start=1):
    c = ws3.cell(row=4, column=col, value=h)
    c.font = F_HEAD
    c.fill = FILL_HEAD
    c.border = BORDER
    c.alignment = WRAP
for rr in range(5, 15):
    for col in range(1, len(HEADERS3) + 1):
        c = ws3.cell(row=rr, column=col)
        c.border = BORDER
        c.alignment = WRAP

wb.save(OUT)
print("saved:", os.path.abspath(OUT))
