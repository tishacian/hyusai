#!/usr/bin/env python3
"""RFI Response v8 — from v7. Two changes:
(1) UiPath / Intelligent Automation CoE profile added to the staffing
    proposition, with a 60-day mobilisation notice as prerequisite for the
    UiPath and Databricks stack profiles.
(2) Q2C.1 team evolution reframed as a human-capacity scale-up matrix
    (resources -> delivery capacity, anchored on ~5 person-days per
    reuse-instance agent), so scaling reads in people and throughput —
    not in stack.
"""
import copy
import os
from docx import Document

HERE = os.path.dirname(os.path.abspath(__file__))
PIH = os.path.join(HERE, "..", "pih")
SRC = os.path.join(PIH, "RFI-PIH-AI-Factory-Response-v7.docx")
OUT = os.path.join(PIH, "RFI-PIH-AI-Factory-Response-v8.docx")

doc = Document(SRC)


def replace_paragraph(par, segments):
    template = par.runs[0].font if par.runs else None
    for run in list(par.runs):
        run._element.getparent().remove(run._element)
    for text, bold in segments:
        run = par.add_run(text)
        run.bold = bold
        if template is not None:
            run.font.size = template.size
            run.font.name = template.name


def set_cell(cell, text, bold=False):
    first = cell.paragraphs[0]
    for par in cell.paragraphs:
        for run in list(par.runs):
            run._element.getparent().remove(run._element)
    run = first.add_run(text)
    run.bold = bold
    run.font.size = None  # inherit table style


def find_paragraph(startswith):
    for par in doc.paragraphs:
        if par.text.strip().startswith(startswith):
            return par
    raise LookupError(startswith)


# ---------------------------------------------------------------- DRAFT marking
for par in doc.paragraphs:
    if "DRAFT v7" in par.text:
        for run in par.runs:
            if "DRAFT v7" in run.text:
                run.text = run.text.replace("DRAFT v7", "DRAFT v8")

# running header still carries the v5 marking from the original build
for sec in doc.sections:
    for par in sec.header.paragraphs:
        for run in par.runs:
            if "DRAFT v5" in run.text:
                run.text = run.text.replace("DRAFT v5", "DRAFT v8")

# ================================================================ (1) UiPath profile + 60-day notice
# §14 named-individuals table: insert Intelligent Automation lead row before SAP experts
team_tbl = None
for tbl in doc.tables:
    if any("CoE Director / scientific leadership" in c.text for r in tbl.rows for c in r.cells):
        team_tbl = tbl
        break
assert team_tbl is not None, "team table not found"

sap_row = None
for row in team_tbl.rows:
    if row.cells[0].text.strip().startswith("SAP module experts"):
        sap_row = row
        break
assert sap_row is not None

new_tr = copy.deepcopy(sap_row._element)
sap_row._element.addprevious(new_tr)
from docx.table import _Row  # noqa: E402

new_row = _Row(new_tr, team_tbl)
set_cell(new_row.cells[0], "Intelligent Automation lead — UiPath RPA/BPA (CoE pole)")
set_cell(new_row.cells[1], "‹ TO COMPLETE — CoE Intelligent Automation pole ›")
set_cell(
    new_row.cells[2],
    "UiPath RPA/BPA delivery and hyperautomation (agentic + RPA convergence); joins where "
    "in-scope processes require RPA execution alongside Agentium agents. Prerequisite: UiPath "
    "and Databricks stack profiles are mobilised with 60 days' notice.",
)

# §2 capability table: RPA & Databricks rows carry the 60-day mobilisation notice
rpa_done = dbx_done = False
for tbl in doc.tables:
    for row in tbl.rows:
        for cell in row.cells:
            t = cell.text.strip()
            if t == "Enterprise-scale RPA references to be evidenced with partner at shortlist.":
                set_cell(
                    cell,
                    "Enterprise-scale RPA references evidenced at shortlist; dedicated UiPath "
                    "profiles mobilised from the CoE with 60 days' notice.",
                )
                rpa_done = True
            elif t == "Reference deployment on Databricks: evidence at shortlist stage.":
                set_cell(
                    cell,
                    "Reference deployment on Databricks: evidence at shortlist stage; "
                    "Databricks-specialised profiles mobilised from the CoE with 60 days' "
                    "notice.",
                )
                dbx_done = True
assert rpa_done and dbx_done, (rpa_done, dbx_done)

# §3 Stage 1 squad shape: UiPath/RPA engineers as on-demand cell members
par = find_paragraph("• Stage 1 — Staff augmentation")
replace_paragraph(par, [
    ("• Stage 1 — Staff augmentation (mobilisation → pilot) — ", True),
    (
        "specialist squads operate under the PIH Factory Lead inside the assembly line. Squad "
        "shape (per build squad): 1 agentic tech lead, 2–4 CoE AI/automation engineers, 1 "
        "QA/evaluation engineer (shared), SAP module expert on demand, under a France-based "
        "solution architect and our CoE director. UiPath/RPA engineers from the CoE "
        "Intelligent Automation pole join build cells where hyperautomation scope requires "
        "RPA execution alongside agents — as do Databricks-specialised profiles — with 60 "
        "days' mobilisation notice. Squads scale by adding cells, not by inflating one team.",
        False,
    ),
])

# ================================================================ (2) Q2C.1 — human-capacity scale-up matrix
par = find_paragraph("Team evolution across phases (Q2C.1)")
replace_paragraph(par, [
    ("Team evolution & scale-up across phases (Q2C.1) — ", True),
    (
        "our scale-up is measured in people and delivery throughput, on a stable architecture "
        "core — it does not depend on any particular platform stack. The unit of scaling is "
        "the trained CoE engineer: once a pattern is validated, a single engineer "
        "configures, tests and documents a standard reuse-instance agent in the order of a "
        "week of effort. This is an illustrative planning heuristic, not a contractual "
        "unit — actual effort per agent is set at design-card stage and varies by tier "
        "(Simple/Medium/Complex) and first-of-type content, consistent with the tiered "
        "pricing in §3. Capacity grows linearly by adding build cells of 5, each cell "
        "productive within one wave of joining (pattern library + evaluation harness + "
        "factory runbooks make onboarding a process, not an apprenticeship):",
        False,
    ),
])

# capacity matrix table inserted right after the Q2C.1 paragraph.
# Borders/shading are copied from the §3 commercial table so the matrix
# renders like every other table in the document (add_table with
# 'Normal Table' style produces an invisible, badly paginated grid).
from docx.oxml.ns import qn  # noqa: E402

ref_tbl = None
for tbl in doc.tables:
    if tbl.rows[0].cells[0].text.strip() == "Component":
        ref_tbl = tbl
        break
assert ref_tbl is not None, "reference table not found"

matrix = doc.add_table(rows=5, cols=4)
ref_tblPr = ref_tbl._element.find(qn("w:tblPr"))
old_tblPr = matrix._element.find(qn("w:tblPr"))
matrix._element.replace(old_tblPr, copy.deepcopy(ref_tblPr))

# fixed layout with explicit column widths
sec = doc.sections[0]
content_tw = (sec.page_width - sec.left_margin - sec.right_margin) // 635  # EMU -> twips
widths = [0.17, 0.13, 0.33, 0.37]
tblPr = matrix._element.find(qn("w:tblPr"))
tblW = tblPr.find(qn("w:tblW"))
tblW.set(qn("w:w"), str(int(content_tw)))
tblW.set(qn("w:type"), "dxa")
layout = tblPr.makeelement(qn("w:tblLayout"), {qn("w:type"): "fixed"})
tblPr.append(layout)
grid = matrix._element.find(qn("w:tblGrid"))
for col, frac in zip(grid.findall(qn("w:gridCol")), widths):
    col.set(qn("w:w"), str(int(content_tw * frac)))

ref_header_tcPr = ref_tbl.rows[0].cells[0]._element.find(qn("w:tcPr"))
ref_body_tcPr = ref_tb_body = ref_tbl.rows[1].cells[0]._element.find(qn("w:tcPr"))
for ri, row in enumerate(matrix.rows):
    # keep rows unsplittable and repeat the header row across pages
    trPr = row._element.get_or_add_trPr()
    trPr.append(trPr.makeelement(qn("w:cantSplit"), {}))
    if ri == 0:
        trPr.append(trPr.makeelement(qn("w:tblHeader"), {}))
    for ci, cell in enumerate(row.cells):
        src = ref_header_tcPr if ri == 0 else ref_body_tcPr
        if src is not None:
            new_tcPr = copy.deepcopy(src)
            for w_el in new_tcPr.findall(qn("w:tcW")):
                w_el.set(qn("w:w"), str(int(content_tw * widths[ci])))
                w_el.set(qn("w:type"), "dxa")
            old = cell._element.find(qn("w:tcPr"))
            if old is not None:
                cell._element.replace(old, new_tcPr)
            else:
                cell._element.insert(0, new_tcPr)
headers = ["Phase", "Build resources (FTE)", "Profile mix", "Delivery capacity"]
rows_data = [
    (
        "Phase 1 — validation (pilot)",
        "5 → 10",
        "1 architect, 1 tech lead, 3–4 engineers, QA/eval; SAP SMEs on-site",
        "Pilot scope (<10 SAP agents) + pattern library seeded; gates calibrated",
    ),
    (
        "Phase 2 — volume ramp",
        "10 → 30",
        "Build cells of 5 around the architecture core; senior-to-engineer ratio drops as "
        "authoring shifts to instantiation",
        "Indicative: ≈ 70–200 reuse-instance agents/quarter (with part of capacity on "
        "first-of-type, QA and integration); per-agent effort set at design-card stage by "
        "tier",
    ),
    (
        "Phase 2 — full throughput",
        "30 → 50",
        "6–10 parallel cells; UiPath/RPA and Databricks profiles on 60 days' notice where "
        "scope requires",
        "Indicative: ≈ 200–360 agents/quarter on the same basis — up to 2× headroom over "
        "the wave plan implied by a 400-agent programme",
    ),
    (
        "Phase 3 — cognitive agents",
        "30–40 sustained",
        "Research-grade evaluation, RCA and multi-step-reasoning profiles join the core; "
        "cells maintain volume",
        "Volume held while Complex/cognitive share of the mix rises",
    ),
]
ref_header_font = ref_tbl.rows[0].cells[0].paragraphs[0].runs[0].font
ref_body_font = ref_tbl.rows[1].cells[0].paragraphs[0].runs[0].font


def fill_cell(cell, text, header=False):
    set_cell(cell, text, bold=header)
    src = ref_header_font if header else ref_body_font
    run = cell.paragraphs[0].runs[0]
    run.font.size = src.size
    run.font.name = src.name
    if src.color and src.color.rgb:
        run.font.color.rgb = src.color.rgb


for j, h in enumerate(headers):
    fill_cell(matrix.rows[0].cells[j], h, header=True)
for i, row_data in enumerate(rows_data, start=1):
    for j, v in enumerate(row_data):
        fill_cell(matrix.rows[i].cells[j], v)

par._element.addnext(matrix._element)

# closing note after the matrix
note = copy.deepcopy(par._element)
matrix._element.addnext(note)
from docx.text.paragraph import Paragraph  # noqa: E402

note_par = Paragraph(note, par._parent)
replace_paragraph(note_par, [
    (
        "Capacity figures are indicative planning ranges built on internal Datategy CoE "
        "resources (continuous-recruitment pipeline across Paris · Algiers · UAE · KSA); "
        "they do not replace per-agent effort estimation at design-card stage. The headroom "
        "between effective throughput and the committed wave plan is deliberate — it absorbs "
        "first-of-type complexity, rework and PIH-side readiness variance without schedule "
        "risk.",
        False,
    ),
])

doc.save(OUT)
print("saved:", OUT)

# ---------------------------------------------------------------- verification
import re
import zipfile

import html

zf = zipfile.ZipFile(OUT)
xml = "".join(
    zf.read(name).decode("utf-8")
    for name in zf.namelist()
    if name == "word/document.xml" or re.match(r"word/(header|footer)\d*\.xml", name)
)
txt = html.unescape(re.sub(r"<[^>]+>", " ", xml))
txt = re.sub(r"\s+", " ", txt)
for needle in [
    "DRAFT v8",
    "Intelligent Automation lead — UiPath RPA/BPA",
    "mobilised with 60 days' notice",
    "60 days' mobilisation notice",
    "illustrative planning heuristic, not a contractual unit",
    "per-agent effort set at design-card stage by tier",
    "Team evolution & scale-up across phases (Q2C.1)",
    "Build resources (FTE)",
    "5 → 10",
    "30 → 50",
    "up to 2× headroom",
    "DRAFT v8 — internal work in progress",
    "does not depend on any particular platform stack",
]:
    assert needle in txt, f"missing: {needle}"
for stale in [
    "DRAFT v7",
    "DRAFT v5",
    "~5 person-days",
    "5 person-days per agent",
    "Enterprise-scale RPA references to be evidenced with partner at shortlist.",
    "Team evolution across phases (Q2C.1) — Phase 1 (validation): one concentrated",
]:
    assert stale not in txt, f"stale: {stale}"
print("all checks passed")
