# -*- coding: utf-8 -*-
"""PIH Service Help Desk — Price Schedule v3: two variants + TCO comparison.

Variants:
  Option 1 — IT scope (RFP perimeter)
  Option 2 — IT + Employee Services (HR deflection & self-service) — RECOMMENDED
Build prices assume co-authoring with the PIH CoE from Wave 2 (pair-building) +
pattern reuse + AI-assisted delivery — that is what compresses the build.
Figures are an ORDER OF MAGNITUDE (finalised at contract), formula-driven.

Sheets: Summary · Rate Card · Build Detail · Run & Options · TCO Comparison
Output: docs/pih/Service Help Desk - Price Schedule - v3 Datategy.xlsx
"""
import os
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "pih", "Service Help Desk - Price Schedule - v3 Datategy.xlsx")

NAVY = "0B2545"; PANEL = "F3F5F8"; AMBER_BG = "FFF8E7"; GREEN_BG = "E2F2EC"; WHITE = "FFFFFF"
H_FONT = Font(name="Arial", bold=True, color=WHITE, size=10)
B_FONT = Font(name="Arial", size=10)
BOLD = Font(name="Arial", bold=True, size=10)
TITLE = Font(name="Arial", bold=True, size=14, color=NAVY)
NOTE = Font(name="Arial", italic=True, size=9, color="596371")
FILL_H = PatternFill("solid", fgColor=NAVY)
FILL_P = PatternFill("solid", fgColor=PANEL)
FILL_A = PatternFill("solid", fgColor=AMBER_BG)
FILL_G = PatternFill("solid", fgColor=GREEN_BG)
THIN = Border(*[Side(style="thin", color="D7DCE3")] * 4)
MONEY = "#,##0"


def style_row(ws, row, cols, header=False, fill=None):
    for c in cols:
        cell = ws.cell(row=row, column=c)
        cell.font = H_FONT if header else B_FONT
        cell.border = THIN
        if header:
            cell.fill = FILL_H
        elif fill:
            cell.fill = fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)


wb = openpyxl.Workbook()

# ================================================================ RATE CARD
rc = wb.active
rc.title = "Rate Card"
rc["A1"] = "Rate Card — indicative day rates (USD, excl. taxes)"
rc["A1"].font = TITLE
rc["A2"] = ("To be confirmed before contract. On-site presence in Qatar: travel & accommodation at cost; "
            "on-site premium to be agreed. Nearshore roles are staffed by Datategy's AI & Data Center of Excellence.")
rc["A2"].font = NOTE
for j, h in enumerate(["Role", "Location / model", "Day rate (USD)"], 1):
    rc.cell(row=4, column=j, value=h)
style_row(rc, 4, range(1, 4), header=True)

RATES = [
    ("Senior Solution Architect", "France · remote/hybrid", 850),
    ("AI / Agent Tech Lead", "France · remote/hybrid", 700),
    ("Delivery Manager", "France · remote/hybrid", 600),
    ("QA / Governance Lead", "France · remote/hybrid", 500),
    ("Nearshore AI Engineer", "Nearshore delivery center", 149),
    ("Nearshore Integration Engineer (connectors)", "Nearshore delivery center", 149),
    ("Nearshore QA / Evaluation Engineer", "Nearshore delivery center", 149),
]
RATE_ROW = {}
for i, (role, loc, rate) in enumerate(RATES):
    r = 5 + i
    rc.cell(row=r, column=1, value=role)
    rc.cell(row=r, column=2, value=loc)
    rc.cell(row=r, column=3, value=rate).number_format = MONEY
    style_row(rc, r, range(1, 4), fill=FILL_P if i % 2 else None)
    RATE_ROW[role] = r
rc.column_dimensions["A"].width = 44
rc.column_dimensions["B"].width = 28
rc.column_dimensions["C"].width = 16

# ================================================================ BUILD DETAIL
bd = wb.create_sheet("Build Detail")
bd["A1"] = "Build — day-based build-up (USD excl. taxes) · order of magnitude, finalised at contract"
bd["A1"].font = TITLE
bd["A2"] = ("Compression levers embedded: delivery by Datategy's AI & Data Center of Excellence (nearshore, "
            "active from day 1), pattern reuse across the 39 use cases (factory effect), and AI-assisted delivery.")
bd["A2"].font = NOTE

PHASES = [
    ("Phase 0 — Foundation (weeks 1–6)",
     "Environments, security model, SDP + Entra ID + Teams connectivity, knowledge ingestion, evaluation baseline, KPI cockpit",
     [("Senior Solution Architect", 10), ("AI / Agent Tech Lead", 10),
      ("Nearshore AI Engineer", 30), ("Nearshore Integration Engineer (connectors)", 10),
      ("Delivery Manager", 6)]),
    ("Wave 1 — Pilot (months 2–4)",
     "Deflection live, proactive detectors, identity flows in parallel-run, one approval flow E2E, golden sets, exit gate",
     [("Senior Solution Architect", 6), ("AI / Agent Tech Lead", 12),
      ("Nearshore AI Engineer", 80), ("Nearshore Integration Engineer (connectors)", 25),
      ("Nearshore QA / Evaluation Engineer", 25), ("QA / Governance Lead", 5),
      ("Delivery Manager", 12)]),
    ("Wave 2 — Core rollout (months 4–7) · pattern-reuse effect",
     "Remaining 39 use cases incl. privileged writes staged live, Egnyte / ARM / firewall flows — second instances of proven patterns",
     [("Senior Solution Architect", 4), ("AI / Agent Tech Lead", 8),
      ("Nearshore AI Engineer", 50), ("Nearshore Integration Engineer (connectors)", 18),
      ("Nearshore QA / Evaluation Engineer", 15), ("QA / Governance Lead", 4),
      ("Delivery Manager", 8)]),
    ("Wave 3 — Scale & proactive (months 7–9) · pattern-reuse effect",
     "Multi-entity rollout, extended RCA & trends, optional Arabic UX, CoE handover",
     [("Senior Solution Architect", 2), ("AI / Agent Tech Lead", 4),
      ("Nearshore AI Engineer", 25), ("Nearshore QA / Evaluation Engineer", 8),
      ("Delivery Manager", 4)]),
    ("Employee Services module (HR deflection & self-service) — Option 2 only",
     "Employee Q&A / self-service over HR policies & services: same channels, knowledge machinery and SuccessFactors "
     "connector reused; HR systems remain the systems of record",
     [("Senior Solution Architect", 2), ("AI / Agent Tech Lead", 4),
      ("Nearshore AI Engineer", 45), ("Nearshore QA / Evaluation Engineer", 12),
      ("Delivery Manager", 4)]),
]

row = 4
SUBTOTALS = []
for title, scope, lines in PHASES:
    bd.cell(row=row, column=1, value=title).font = BOLD
    for c in range(1, 6):
        bd.cell(row=row, column=c).fill = FILL_P
        bd.cell(row=row, column=c).border = THIN
    bd.cell(row=row, column=2, value=scope).font = NOTE
    bd.merge_cells(start_row=row, start_column=2, end_row=row, end_column=5)
    row += 1
    for j, h in enumerate(["Role", "", "Days", "Rate (USD)", "Amount (USD)"], 1):
        if h:
            bd.cell(row=row, column=j, value=h)
    style_row(bd, row, range(1, 6), header=True)
    row += 1
    first = row
    for role, days in lines:
        bd.cell(row=row, column=1, value=role)
        bd.cell(row=row, column=3, value=days)
        bd.cell(row=row, column=4, value=f"='Rate Card'!C{RATE_ROW[role]}").number_format = MONEY
        bd.cell(row=row, column=5, value=f"=C{row}*D{row}").number_format = MONEY
        style_row(bd, row, range(1, 6))
        row += 1
    bd.cell(row=row, column=1, value="Subtotal").font = BOLD
    bd.cell(row=row, column=3, value=f"=SUM(C{first}:C{row - 1})").font = BOLD
    bd.cell(row=row, column=5, value=f"=SUM(E{first}:E{row - 1})").font = BOLD
    bd.cell(row=row, column=5).number_format = MONEY
    for c in range(1, 6):
        bd.cell(row=row, column=c).fill = FILL_A
        bd.cell(row=row, column=c).border = THIN
    SUBTOTALS.append(f"E{row}")
    row += 2

it_refs = SUBTOTALS[:4]
hr_ref = SUBTOTALS[4]
bd.cell(row=row, column=1, value="TOTAL BUILD — OPTION 1 (IT scope)").font = Font(name="Arial", bold=True, size=11, color=NAVY)
bd.cell(row=row, column=5, value="=" + "+".join(it_refs)).number_format = MONEY
bd.cell(row=row, column=5).font = Font(name="Arial", bold=True, size=11, color=NAVY)
for c in range(1, 6):
    bd.cell(row=row, column=c).fill = FILL_P
    bd.cell(row=row, column=c).border = THIN
OPT1_CELL = f"'Build Detail'!E{row}"
row += 1
bd.cell(row=row, column=1, value="TOTAL BUILD — OPTION 2 (IT + Employee Services) · RECOMMENDED").font = Font(name="Arial", bold=True, size=11, color=NAVY)
bd.cell(row=row, column=5, value="=" + "+".join(it_refs + [hr_ref])).number_format = MONEY
bd.cell(row=row, column=5).font = Font(name="Arial", bold=True, size=11, color=NAVY)
for c in range(1, 6):
    bd.cell(row=row, column=c).fill = FILL_G
    bd.cell(row=row, column=c).border = THIN
OPT2_CELL = f"'Build Detail'!E{row}"
bd.column_dimensions["A"].width = 46
bd.column_dimensions["B"].width = 10
bd.column_dimensions["C"].width = 10
bd.column_dimensions["D"].width = 14
bd.column_dimensions["E"].width = 16

# ================================================================ RUN & OPTIONS
ro = wb.create_sheet("Run & Options")
ro["A1"] = "Run & Options (USD, excl. taxes)"
ro["A1"].font = TITLE
row = 3
ro.cell(row=row, column=1, value="Annual Run — Platform licence & editor support").font = BOLD
row += 1
ro.cell(row=row, column=1, value="Annual fee (identical for both options)")
ro.cell(row=row, column=2, value=20000).number_format = MONEY
style_row(ro, row, range(1, 3), fill=FILL_A)
RUN_CELL = f"'Run & Options'!B{row}"
row += 1
for inc in [
    "Includes: platform licence (perimeter of the selected option), quarterly product releases, security "
    "patches, level-3 editor support (business hours, Qatar-time friendly), golden-set regression on every release.",
    "Option 2: the same run fee covers the Employee Services module — editor support is platform-level, and "
    "day-to-day operations are internalised in PIH's team (Datategy Academy enablement) for both scopes.",
    "Excludes: infrastructure (PIH Azure tenant or on-premise, under PIH billing), day-to-day AgentOps, new "
    "use cases / connectors / entities (wave model or rate card).",
    "Perimeter bound to the systems, domains and companies listed in the offer; material extensions "
    "re-priced through the same wave model.",
]:
    ro.cell(row=row, column=1, value=inc).font = NOTE
    ro.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    row += 1

row += 1
ro.cell(row=row, column=1, value="Options (indicative)").font = BOLD
row += 1
for j, h in enumerate(["Option", "Unit", "Indicative price (USD)", "Notes"], 1):
    ro.cell(row=row, column=j, value=h)
style_row(ro, row, range(1, 5), header=True)
row += 1
OPTIONS = [
    ("Managed AgentOps (outsourced operations)", "per agent / month", "50",
     "Monitoring, exception management, prompt regression, reporting. Alternative to CoE-operated model."),
    ("Additional use case — Simple", "fixed", "2,500 – 5,000", "Single system, existing pattern (~8–15 nearshore days)."),
    ("Additional use case — Medium", "fixed", "6,000 – 12,000", "Multi-step / two systems, pattern adaptation."),
    ("Additional use case — Complex", "fixed", "15,000 – 30,000", "Multi-system, privileged writes, new pattern."),
    ("New connector (catalogue component)", "fixed", "4,000 – 10,000", "10–20 days on the connector framework, reusable."),
    ("Arabic user-experience package", "fixed", "15,000 – 25,000", "Arabic-capable model serving, KB coverage, UX validation."),
    ("Extended support (24/7)", "annual uplift", "on quote", "P1 coverage outside business hours."),
    ("Additional entity / company onboarding", "per batch", "wave model", "Scoped and priced as a mini-wave."),
]
for i, (opt, unit, price, note) in enumerate(OPTIONS):
    ro.cell(row=row, column=1, value=opt)
    ro.cell(row=row, column=2, value=unit)
    ro.cell(row=row, column=3, value=price)
    ro.cell(row=row, column=4, value=note).font = NOTE
    style_row(ro, row, range(1, 5), fill=FILL_P if i % 2 else None)
    ro.cell(row=row, column=4).font = NOTE
    row += 1
ro.column_dimensions["A"].width = 42
ro.column_dimensions["B"].width = 16
ro.column_dimensions["C"].width = 20
ro.column_dimensions["D"].width = 60

# ================================================================ TCO COMPARISON
tc = wb.create_sheet("TCO Comparison")
tc["A1"] = "TCO comparison — anonymised (USD, excl. taxes)"
tc["A1"].font = TITLE
tc["A2"] = ("INTERNAL CALIBRATION — baseline values below are informal estimates of the incumbent's licences. "
            "Verify or hide before any client-facing export; never quote the incumbent's figures in writing.")
tc["A2"].font = Font(name="Arial", italic=True, bold=True, size=9, color="B45309")

tc["A4"] = "Baseline inputs (editable)"; tc["A4"].font = BOLD
tc["A5"] = "Current conversational platform — IT licence / year"
tc["B5"] = 38000; tc["B5"].number_format = MONEY; tc["B5"].fill = FILL_A; tc["B5"].border = THIN
tc["A6"] = "Current conversational platform — HR budget / year (assumption)"
tc["B6"] = 35000; tc["B6"].number_format = MONEY; tc["B6"].fill = FILL_A; tc["B6"].border = THIN
tc["C6"] = "← to confirm via sales channel"; tc["C6"].font = NOTE

row = 8
for j, h in enumerate(["Scenario", "Year 1", "3 years", "5 years"], 1):
    tc.cell(row=row, column=j, value=h)
style_row(tc, row, range(1, 5), header=True)
row += 1
SCEN = [
    ("Current platform — IT only (rented)", "=$B$5*{n}", None),
    ("Current platform — IT + HR (rented)", "=($B$5+$B$6)*{n}", None),
    ("Option 1 — IT scope (build + run)", f"={OPT1_CELL}+{RUN_CELL}*{{n}}", None),
    ("Option 2 — IT + Employee Services (build + run) · RECOMMENDED", f"={OPT2_CELL}+{RUN_CELL}*{{n}}", FILL_G),
]
opt2_row = None
combined_row = None
for i, (label, fmla, fill) in enumerate(SCEN):
    tc.cell(row=row, column=1, value=label).font = BOLD if fill else B_FONT
    for k, n in enumerate([1, 3, 5], 2):
        c = tc.cell(row=row, column=k, value=fmla.format(n=n))
        c.number_format = MONEY
    style_row(tc, row, range(1, 5), fill=fill if fill else (FILL_P if i % 2 else None))
    if label.startswith("Current platform — IT + HR"):
        combined_row = row
    if label.startswith("Option 2"):
        opt2_row = row
    row += 1
tc.cell(row=row, column=1, value="Savings — Option 2 vs current IT + HR").font = BOLD
for k in (2, 3, 4):
    col = chr(64 + k)
    c = tc.cell(row=row, column=k, value=f"={col}{combined_row}-{col}{opt2_row}")
    c.number_format = MONEY
    c.font = BOLD
style_row(tc, row, range(1, 5), fill=FILL_A)
row += 2
tc.cell(row=row, column=1,
        value="Reading: Option 2 replaces both rented scopes with an owned, agentic platform; the build is "
              "one-time and self-funding (5,000–7,000 analyst-hours/year returned at 30–40% deflection), while "
              "the run stays roughly half the current IT-only licence — covering both scopes.").font = NOTE
tc.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
tc.column_dimensions["A"].width = 56
for col in ("B", "C", "D"):
    tc.column_dimensions[col].width = 14

# ================================================================ SUMMARY (first tab)
sm = wb.create_sheet("Summary", 0)
sm["A1"] = "PIH Service Help Desk — Price Schedule (v3, two options, indicative)"
sm["A1"].font = TITLE
sm["A2"] = ("Currency USD, exclusive of taxes. Order-of-magnitude figures, finalised at contract once the "
            "Wave 1 perimeter is confirmed. Delivered by Datategy's AI & Data Center of Excellence. Aligned "
            "with the Technical & Commercial offer. Validity: 90 days.")
sm["A2"].font = NOTE

row = 4
for j, h in enumerate(["Component", "Option 1 — IT scope", "Option 2 — IT + Employee Services (RECOMMENDED)", "Notes"], 1):
    sm.cell(row=row, column=j, value=h)
style_row(sm, row, range(1, 5), header=True)
row += 1
LINES = [
    ("Build — one-time, phased (fixed price per wave)", f"={OPT1_CELL}", f"={OPT2_CELL}",
     "Each wave self-justifying; pattern reuse compresses cost wave on wave"),
    ("Annual Run — licence & editor support", f"={RUN_CELL}", f"={RUN_CELL}",
     "Identical fee; Option 2 covers both scopes (ops internalised in PIH team)"),
    ("3-year TCO (build + 3× run)", f"={OPT1_CELL}+3*{RUN_CELL}", f"={OPT2_CELL}+3*{RUN_CELL}",
     "See TCO Comparison sheet vs current platform spend"),
]
for i, (comp, v1, v2, note) in enumerate(LINES):
    sm.cell(row=row, column=1, value=comp).font = BOLD
    a = sm.cell(row=row, column=2, value=v1); a.number_format = MONEY
    b = sm.cell(row=row, column=3, value=v2); b.number_format = MONEY; b.font = BOLD
    sm.cell(row=row, column=4, value=note).font = NOTE
    style_row(sm, row, range(1, 5), fill=FILL_P if i % 2 else None)
    sm.cell(row=row, column=3).fill = FILL_G
    row += 1
sm.cell(row=row, column=1, value="Options (both variants)").font = B_FONT
sm.cell(row=row, column=4, value="Managed AgentOps, additional use cases, Arabic UX, 24/7 — see 'Run & Options'").font = NOTE
style_row(sm, row, range(1, 5))
sm.column_dimensions["A"].width = 42
sm.column_dimensions["B"].width = 20
sm.column_dimensions["C"].width = 34
sm.column_dimensions["D"].width = 52

wb.save(OUT)

# ---- expected values
rates = {role: rate for role, _, rate in RATES}
subs = []
for title, _, lines in PHASES:
    sub = sum(d * rates[r] for r, d in lines)
    days = sum(d for _, d in lines)
    subs.append(sub)
    print(f"{title[:58]:58s} {days:4d}d  ${sub:>8,.0f}")
opt1 = sum(subs[:4]); opt2 = opt1 + subs[4]
print(f"{'TOTAL OPTION 1 (IT)':58s}       ${opt1:>8,.0f}")
print(f"{'TOTAL OPTION 2 (IT + Employee Services)':58s}       ${opt2:>8,.0f}")
print(f"3-yr TCO: opt1 ${opt1+60000:,.0f} · opt2 ${opt2+60000:,.0f} · baseline IT+HR (38k+35k)×3 = $219,000")
print("saved:", OUT)
