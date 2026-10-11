#!/usr/bin/env python3
"""Annex B v7 — from v6, propagating the PIH clarification register:
- A1: official mix 40/40/20 -> envelope 160 Simple / 160 Medium / 80 Complex,
  first-of-type Complex subset 5 -> 8.
- D14: single sovereign-inference line replaced by three neutral infrastructure
  models (cloud-hosted sovereign, partner-provided, PIH-provisioned on-premise).
- B6: delivery model = core squad on-site in Qatar during Phase 1, hybrid for
  supporting roles (replaces Remote-first wording, incl. the Doha T&M line).
- F20: perpetual, royalty-free licence to use delivered/accepted versions,
  excluding future releases/upgrades and source code."""
import os
from copy import copy
from openpyxl import load_workbook

HERE = os.path.dirname(os.path.abspath(__file__))
PIH = os.path.join(HERE, "..", "pih")
SRC = os.path.join(PIH, "RFI-PIH-AI-Factory-Annex-B-Pricing-Schedule-v6.xlsx")
OUT = os.path.join(PIH, "RFI-PIH-AI-Factory-Annex-B-Pricing-Schedule-v7.xlsx")

wb = load_workbook(SRC)


def copy_row_style(ws, dst_row, src_row, max_col=8):
    for col in range(1, max_col + 1):
        src, dst = ws.cell(src_row, col), ws.cell(dst_row, col)
        dst.font = copy(src.font)
        dst.fill = copy(src.fill)
        dst.border = copy(src.border)
        dst.alignment = copy(src.alignment)
        dst.number_format = src.number_format
    if src_row in ws.row_dimensions:
        ws.row_dimensions[dst_row].height = ws.row_dimensions[src_row].height


def find_row(ws, label, col=1):
    for row in range(1, ws.max_row + 1):
        if str(ws.cell(row, col).value or "").strip() == label:
            return row
    raise LookupError(label)


# ---------------------------------------------------------------- Pricing Summary
ps = wb["Pricing Summary"]
ps["A1"] = "Annex B — Pricing Schedule (v7, indicative, RFI stage)"

# B6 — Doha T&M line aligned with the mandated on-site core squad.
doha = find_row(ps, "Targeted Doha attendance")
ps.cell(doha, 1).value = "Doha on-site presence"
ps.cell(doha, 4).value = (
    "Core delivery squad (Factory Lead, SAP module SMEs, QA lead) on-site in Qatar during the "
    "Phase 1 pilot; hybrid arrangements for supporting roles. Travel/accommodation at cost."
)

# D14 — replace the single sovereign line by three neutral infrastructure models.
sov = find_row(ps, "Private / sovereign inference")
ps.insert_rows(sov + 1, amount=2)
for r in (sov + 1, sov + 2):
    copy_row_style(ps, r, sov)
rows = [
    (
        "Sovereign inference — cloud-hosted (Azure Qatar)",
        "PIH tenancy, GPU consumption",
        "$0 Datategy fee",
        "Open-weight or approved models served on PIH-controlled Azure Qatar capacity; GPU "
        "consumption billed directly between PIH and its cloud provider; Datategy provides "
        "model sizing and routing guidance.",
    ),
    (
        "Sovereign inference — partner-provided",
        "optional managed service",
        "Price on request",
        "Datategy-operated dedicated GPU capacity, subject to PIH data-residency approval; "
        "scoped and priced before commitment.",
    ),
    (
        "Sovereign inference — PIH-provisioned (on-premise)",
        "PIH capex",
        "$0 Datategy infrastructure fee",
        "PIH-procured GPU capacity; Datategy deploys and operates the model-serving stack — "
        "setup scoped as Complex/first-of-type or T&M; ongoing model operations available as "
        "an annual subscription.",
    ),
]
for offset, (a, b, c, d) in enumerate(rows):
    ps.cell(sov + offset, 1).value = a
    ps.cell(sov + offset, 2).value = b
    ps.cell(sov + offset, 3).value = c
    ps.cell(sov + offset, 4).value = d

# ---------------------------------------------------------------- Illustrative Envelope
ie = wb["Illustrative Programme Envelope"]
ie["A1"] = "Illustrative programme envelope — 400 agents (v7, indicative)"
# A1 clarification: official mix 40/40/20.
ie["B5"] = 160  # Simple (was 180)
ie["B6"] = 160  # Medium (unchanged)
ie["B7"] = 80   # Complex (was 60)
ie["B13"] = 8   # Complex first-of-type subset (was 5), proportional to the larger Complex share
ie["A2"] = (
    "The 400-agent mix follows the PIH-clarified tier split (40% Simple / 40% Medium / 20% "
    "Complex) and includes reuse and first-of-type agents. First-of-type premiums apply to a "
    "stated subset of the same 400 agents. Amber cells are editable assumptions."
)

# ---------------------------------------------------------------- Commercial Terms
ct = wb["Commercial Terms & Capacity"]

run_row = find_row(ct, "Run delivered agent versions")
ct.cell(run_row, 2).value = (
    "PIH receives a perpetual, royalty-free, non-exclusive licence to use and execute accepted "
    "delivered agent versions on PIH-controlled infrastructure, without dependence on a "
    "continued commercial relationship with Datategy. This covers delivered and accepted "
    "versions; it does not include future product releases or upgrades, and does not include a "
    "source-code transfer."
)

inf_row = find_row(ct, "SaaS / sovereign inference")
ct.cell(inf_row, 2).value = (
    "Where PIH approves Azure/SaaS endpoints, Datategy charges $0 and PIH pays cloud "
    "consumption directly. For private/sovereign inference, three infrastructure models are "
    "described in the Pricing Summary — cloud-hosted sovereign (Azure Qatar, PIH tenancy), "
    "partner-provided (optional managed service), or PIH-provisioned on-premise capacity. "
    "None carries a Datategy recurring infrastructure fee unless the partner-provided option "
    "is selected."
)

cash_row = find_row(ct, "Cash flow")
ct.cell(cash_row, 2).value = (
    "Mobilisation payment and monthly pilot invoicing are agreed before resources are "
    "reserved. Industrial delivery is paid through short monthly or wave milestones; no "
    "deferred single milestone at 200 agents. Aggregate at-risk exposure (wave-gate at-risk "
    "plus adoption holdback, per the response document §3.4/§12) is capped at 15% of any "
    "wave's fees."
)

dm_row = find_row(ct, "Delivery model")
ct.cell(dm_row, 2).value = (
    "Core delivery squad (Factory Lead, SAP module SMEs, QA lead) on-site in Qatar during the "
    "Phase 1 pilot, per PIH clarification B6. Hybrid arrangements for supporting roles: "
    "architecture, agent build and evaluation are delivered by the Datategy AI & Data Center "
    "of Excellence remotely under PIH security and data-residency controls. "
    "Travel/accommodation at cost."
)

wb.save(OUT)
print("saved:", OUT)

# ---------------------------------------------------------------- verification
wb2 = load_workbook(OUT)
ps2 = wb2["Pricing Summary"]
ie2 = wb2["Illustrative Programme Envelope"]
ct2 = wb2["Commercial Terms & Capacity"]

assert ie2["B5"].value == 160 and ie2["B6"].value == 160 and ie2["B7"].value == 80
assert ie2["B5"].value + ie2["B6"].value + ie2["B7"].value == 400
assert ie2["B13"].value == 8
base = 160 * 4200 + 160 * 10500 + 80 * 24000
print(f"envelope base (mix 40/40/20): ${base:,}")
assert base == 4_272_000

labels = [str(ps2.cell(r, 1).value or "") for r in range(1, ps2.max_row + 1)]
for needed in [
    "Sovereign inference — cloud-hosted (Azure Qatar)",
    "Sovereign inference — partner-provided",
    "Sovereign inference — PIH-provisioned (on-premise)",
    "Doha on-site presence",
]:
    assert needed in labels, f"missing: {needed}"
assert "Private / sovereign inference" not in labels
assert "Targeted Doha attendance" not in labels

all_text = " ".join(
    str(c.value)
    for sheet in wb2.worksheets
    for row in sheet.iter_rows()
    for c in row
    if c.value is not None
)
assert "Remote-first" not in all_text, "stale Remote-first wording"
assert "perpetual, royalty-free" in all_text
assert "capped at 15%" in all_text
assert "$120" in all_text and "$160" in all_text  # v6 recurring preserved
print("all checks passed")
