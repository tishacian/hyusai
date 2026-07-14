# -*- coding: utf-8 -*-
"""Iterate on the PIH offer v3 → v4 (v3 untouched): staged commercial structure.

Validated 2026-07-08:
  - Engagement initial ≈ USD 25k (Phase 0-lite + pilot on the 4 foundational
    patterns), the only amount engaged at signature.
  - Waves 2–3 pre-priced (≈ USD 80k), engaged wave by wave on measured results.
  - Full path: Option 1 ≈ 105k, Option 2 ≈ 120k (HR module ≈ 15k). Run 20k/yr.
  - Delivery 100% CoE with thin Paris architecture & QA oversight (~15 days).
  - Aligned with Price Schedule v4.

Input : docs/pih/Service Help Desk - Technical and Commercial offer - v3 Datategy.docx
Output: docs/pih/Service Help Desk - Technical and Commercial offer - v4 Datategy.docx
"""
import os
from docx import Document
from docx.shared import Pt

HERE = os.path.dirname(os.path.abspath(__file__))
PIH = os.path.join(os.path.dirname(HERE), "pih")
SRC = os.path.join(PIH, "Service Help Desk - Technical and Commercial offer - v3 Datategy.docx")
OUT = os.path.join(PIH, "Service Help Desk - Technical and Commercial offer - v4 Datategy.docx")

doc = Document(SRC)


def find(prefix, style=None):
    for p in doc.paragraphs:
        if p.text.strip().startswith(prefix) and (style is None or (p.style and p.style.name == style)):
            return p
    raise SystemExit(f"ANCHOR NOT FOUND: {prefix!r}")


def set_text(p, text, bold_lead=None):
    for r in list(p.runs):
        r._r.getparent().remove(r._r)
    if bold_lead:
        r = p.add_run(bold_lead)
        r.bold = True
    p.add_run(text)
    return p


# ============================================================ exec summary — staged commitment
p_dv = find("We propose a phased engagement")
set_text(p_dv,
    "We propose a phased engagement: a foundation phase and a pilot wave with client-confirmed "
    "baselines, then wave-based migration and enhancement of all 39 use cases and scale-out across "
    "entities — each wave closing with quality gates and ≥30 days of hypercare. The commercial "
    "commitment is staged the same way: an initial engagement of approximately USD 25k puts the "
    "pilot in production, and each subsequent wave is engaged only on the measured results of the "
    "previous one. At your volumes, a 30–40% deflection/automation rate on the residual ~70,000 "
    "tickets represents 5,000–7,000 analyst-hours per year returned to higher-value work — measured "
    "live in the platform's value cockpit, so each wave justifies the next. The run model is a flat "
    "editor licence with operations internalised in your team, designed to remain below your "
    "current conversational platform's annual cost.")

# ============================================================ commercial section prose
p_pri = find("The commercial model follows three principles")
set_text(p_pri,
    "The commercial model follows three principles: (1) no per-employee licensing — costs do not "
    "scale with your 12,200 users but with the value delivered; (2) a staged commitment — the only "
    "amount engaged at signature is the initial engagement (~USD 25k), which puts the pilot in "
    "production; the following waves are pre-priced and engaged wave by wave on the pilot's "
    "measured results; (3) a flat, predictable run. Two commercial options are proposed; amounts in "
    "this section are orders of magnitude, finalised at contract in the separate Price Schedule.")

p_build = find("Build —")
set_text(p_build,
    "an initial engagement of approximately USD 25k covers Phase 0-lite (environments, security "
    "model, ManageEngine + Entra ID + Teams connectivity, knowledge ingestion, golden sets) and a "
    "pilot wave proving one exemplar of each of the four foundational patterns that cover the 39 "
    "use cases: conversational deflection live on a representative population, proactive "
    "operations & RCA over ServiceDesk Plus history, identity & access lifecycle in "
    "parallel-run/simulate, and one approval-orchestrated flow end-to-end. Waves 2–3 — migration "
    "and enhancement of all 39 use cases, privileged writes under mandates, the remaining "
    "connectors (Egnyte, SolarWinds ARM, firewalls) and multi-entity scale-out — are pre-priced "
    "(approximately USD 80k) and engaged wave by wave on measured results, bringing the full build "
    "to approximately USD 105k.",
    bold_lead="Build (staged commitment) — ")

p_opt2 = find("Option 2 adds an Employee Services module")
set_text(p_opt2,
    "Option 2 adds an Employee Services module: employee Q&A and self-service over HR policies and "
    "services (leave, documents, onboarding questions), delivered through the same channels, the "
    "same knowledge machinery and the same SuccessFactors connector already required for the IT "
    "identity-lifecycle flows. HR systems remain the systems of record — the module is a deflection "
    "and self-service layer, not HR process execution — so the marginal build cost is limited "
    "(approximately USD 15k on top of Option 1, delivered with Waves 2–3, i.e. a full build of "
    "approximately USD 120k). The initial engagement is identical (~USD 25k).")

p_lev = find("Three structural levers")
set_text(p_lev,
    "Three structural levers — not a discount. (1) The build is delivered end-to-end by Datategy's "
    "AI & Data Center of Excellence, our dedicated delivery engine whose flagship domain is "
    "intelligent IT service-desk automation, active from day one at a fraction of on-shore day "
    "rates — under a focused senior Paris-based architecture and QA oversight (roughly fifteen "
    "days across the programme, concentrated on the security model and the quality gates). "
    "(2) The factory effect: the 39 use cases decompose into ~10 reusable patterns, so cost falls "
    "wave on wave as second instances of each pattern are authored, not rebuilt. (3) AI-assisted "
    "delivery across the build track. The savings are structural because the platform and the "
    "delivery engine are products of the same house.")

# ============================================================ pricing table
tbl = None
for t in doc.tables:
    if t.cell(0, 0).text.strip() == "Component":
        tbl = t
        break
if tbl is None:
    raise SystemExit("PRICING TABLE NOT FOUND")


def set_cell(cell, text, bold=False):
    cell.text = ""
    r = cell.paragraphs[0].add_run(text)
    r.font.size = Pt(9)
    r.bold = bold


ROWS = [
    ("Engagement initial — Phase 0-lite + Pilot (4 foundational patterns)",
     "≈ USD 25k", "≈ USD 25k", "Months 1–4 · only amount engaged at signature"),
    ("Wave 2 — Migration 39/39, privileged writes, remaining connectors",
     "≈ USD 53k", "≈ USD 53k", "Months 4–7 · engaged on pilot results"),
    ("Wave 3 — Scale & proactive",
     "≈ USD 28k", "≈ USD 28k", "Months 7–9 · engaged on Wave 2 results"),
    ("Employee Services module (HR deflection & self-service)",
     "—", "≈ USD 15k", "Delivered with Waves 2–3"),
    ("Total build — full path (one-time, staged)",
     "≈ USD 105k", "≈ USD 120k", "≈ 9 months"),
    ("Annual run — licence & editor support",
     "USD 20k / year", "USD 20k / year (covers both scopes)", "From pilot go-live"),
    ("Indicative 3-year TCO (build + 3× run)",
     "≈ USD 165k", "≈ USD 180k", "—"),
]
n_data = len(tbl.rows) - 1
if n_data > len(ROWS):
    for tr in [r._tr for r in tbl.rows[len(ROWS) + 1:]]:
        tbl._tbl.remove(tr)
for i, row_vals in enumerate(ROWS):
    for j, val in enumerate(row_vals):
        set_cell(tbl.rows[i + 1].cells[j], val, bold=(j == 0))

p_after = find("Each wave is a fixed price engaged on the results of the previous one")
set_text(p_after,
    "Each wave is a fixed price engaged on the results of the previous one — should PIH stop after "
    "the pilot, the only amount due is the initial engagement. The detailed day-based build-up per "
    "role and wave is provided in the Price Schedule annex.")

doc.save(OUT)

# sanity
d2 = Document(OUT)
hits = sum(1 for p in d2.paragraphs if "USD 25k" in p.text)
print(f"'USD 25k' occurrences: {hits}")
print("saved:", OUT)
