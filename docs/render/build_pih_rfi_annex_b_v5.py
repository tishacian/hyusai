# -*- coding: utf-8 -*-
"""Create Annex B v5 from the restored v4.

v5 keeps the v4 commercial structure and adds the UCC pilot range plus the
approved post-build risk-tier overage (70/80/90).
"""
import copy
import os

from openpyxl import load_workbook

HERE = os.path.dirname(os.path.abspath(__file__))
PIH = os.path.join(os.path.dirname(HERE), "pih")
SRC = os.path.join(PIH, "RFI-PIH-AI-Factory-Annex-B-Pricing-Schedule-v4.xlsx")
OUT = os.path.join(PIH, "RFI-PIH-AI-Factory-Annex-B-Pricing-Schedule-v5.xlsx")


def copy_row_style(ws, source_row, target_row):
    for col in range(1, ws.max_column + 1):
        source = ws.cell(source_row, col)
        target = ws.cell(target_row, col)
        if source.has_style:
            target._style = copy.copy(source._style)
        if source.number_format:
            target.number_format = source.number_format
        if source.alignment:
            target.alignment = copy.copy(source.alignment)


def set_cell(cell, value):
    cell.value = value


wb = load_workbook(SRC)

# ---------------------------------------------------------------- Pricing Summary
ps = wb["Pricing Summary"]
ps["A1"] = ps["A1"].value.replace("(v4,", "(v5,")
baseline_row = next(
    row for row in range(1, ps.max_row + 1)
    if str(ps.cell(row, 1).value or "").startswith("Enterprise Platform & Managed Operations Baseline")
)
ps.insert_rows(baseline_row)
copy_row_style(ps, baseline_row + 1, baseline_row)
set_cell(ps.cell(baseline_row, 1), "UCC Factory Validation Pilot")
set_cell(ps.cell(baseline_row, 2), "13 weeks · UCC MIGO scope")
set_cell(ps.cell(baseline_row, 3), "≈ $90k – 110k")
set_cell(
    ps.cell(baseline_row, 4),
    "Factory validation capacity: mobilisation, design, build, parallel run, go-live stabilisation "
    "and pattern-library seeding. Priority-agent volume remains subject to PIH clarification; excludes "
    "PIH infrastructure and direct cloud consumption.",
)
for row in range(1, ps.max_row + 1):
    label = str(ps.cell(row, 1).value or "")
    if label.startswith("Enterprise Platform & Managed Operations Baseline"):
        ps.cell(row, 2).value = "first 50 live agents / month"
        ps.cell(row, 3).value = "$8,900"
        ps.cell(row, 4).value = (
            "Single post-build monthly baseline covering platform continuity, standard AgentOps and "
            "knowledge service for delivered agents."
        )
    elif label == "AgentOps overage — Low impact":
        ps.cell(row, 3).value = "$69"
    elif label == "AgentOps overage — Medium impact":
        ps.cell(row, 3).value = "$79"
    elif label == "AgentOps overage — High impact":
        ps.cell(row, 3).value = "$89"

high_row = next(
    row for row in range(1, ps.max_row + 1)
    if str(ps.cell(row, 1).value or "") == "AgentOps overage — High impact"
)
ps.insert_rows(high_row + 1)
copy_row_style(ps, high_row, high_row + 1)
set_cell(ps.cell(high_row + 1, 1), "Enhanced End-User Support — optional")
set_cell(ps.cell(high_row + 1, 2), "per live agent / month")
set_cell(ps.cell(high_row + 1, 3), "$50")
set_cell(
    ps.cell(high_row + 1, 4),
    "Direct user assistance: usage questions, request triage and functional guidance during agreed "
    "business hours. Separate from technical AgentOps, incident response and product support.",
)

# -------------------------------------------------- Illustrative Programme Envelope
ie = wb["Illustrative Programme Envelope"]
ie["A1"] = ie["A1"].value.replace("(indicative)", "(v5, indicative)")
# v4 post-build block: D26 baseline; D27-D29 risk tiers; D30 subtotal; D31 total.
ie["D25"] = "Monthly amount"
ie["C26"] = "$8,900/month"; ie["D26"] = 8900
ie["C27"] = "$69/month"; ie["D27"] = "=B27*69"
ie["C28"] = "$79/month"; ie["D28"] = "=B28*79"
ie["C29"] = "$89/month"; ie["D29"] = "=B29*89"
ie["C30"] = "Illustrative weighted average: $79/month"
ie["A31"] = "ILLUSTRATIVE POST-BUILD RECURRING — MONTHLY"

# Optional support is deliberately not included in the base recurring total.
optional_row = ie.max_row + 2
copy_row_style(ie, 31, optional_row)
ie.cell(optional_row, 1, "OPTIONAL ENHANCED END-USER SUPPORT — NOT INCLUDED ABOVE")
ie.cell(optional_row, 2, 400)
ie.cell(optional_row, 3, "$50/agent/month")
ie.cell(optional_row, 4, f"=B{optional_row}*50")
ie.cell(optional_row, 2).fill = copy.copy(ie["B27"].fill)
ie.cell(optional_row, 4).number_format = "$#,##0"
annual_row = optional_row + 1
copy_row_style(ie, 31, annual_row)
ie.cell(annual_row, 1, "Optional enhanced end-user support — annual equivalent")
ie.cell(annual_row, 4, f"=D{optional_row}*12")
ie.cell(annual_row, 4).number_format = "$#,##0"

ct = wb["Commercial Terms & Capacity"]
terms_row = ct.max_row + 1
copy_row_style(ct, ct.max_row, terms_row)
ct.cell(terms_row, 1, "Enhanced end-user support — optional")
ct.cell(
    terms_row,
    2,
    "Datategy can provide direct L1 functional user assistance for usage questions, request triage and "
    "guidance during agreed business hours. This is distinct from technical AgentOps and incident response.",
)
ct.merge_cells(start_row=terms_row, start_column=2, end_row=terms_row, end_column=4)

wb.save(OUT)
print("saved:", OUT)
