# -*- coding: utf-8 -*-
"""Create RFI Response v5 from v4.

v5 adds the explicit UCC Factory Validation Pilot range and raises post-build
AgentOps overage to Low/Medium/High = 70/80/90 USD per live agent per month.
"""
import copy
import os

from docx import Document

HERE = os.path.dirname(os.path.abspath(__file__))
PIH = os.path.join(os.path.dirname(HERE), "pih")
SRC = os.path.join(PIH, "RFI-PIH-AI-Factory-Response-v4.docx")
OUT = os.path.join(PIH, "RFI-PIH-AI-Factory-Response-v5.docx")

doc = Document(SRC)


def commercial_table():
    for table in doc.tables:
        if table.cell(0, 0).text.strip() == "Component":
            return table
    raise SystemExit("COMMERCIAL TABLE NOT FOUND")


def set_cell(cell, value):
    p = cell.paragraphs[0]
    for run in list(p.runs):
        run._r.getparent().remove(run._r)
    p.add_run(value)
    for extra in cell.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)


tbl = commercial_table()
for row in tbl.rows:
    label = row.cells[0].text.strip()
    if label == "AgentOps overage — post-build":
        set_cell(row.cells[2], "Low $69 · Medium $79 · High $89. High-impact scope includes reinforced drift watch and quarterly adversarial/red-team regression.")
    elif label.startswith("Enterprise Platform & Managed Operations Baseline"):
        set_cell(row.cells[1], "$8,900/month for the first 50 live agents, post-build")
        set_cell(row.cells[2], "Starts after final programme acceptance, or 90 days after the last accepted delivery if no successor factory plan is active. Includes platform continuity, updates, security patches, compatibility, golden-set regression, N3 support, standard AgentOps and knowledge service.")

# Add the optional direct-user-support service immediately after AgentOps.
ops_index = next(i for i, row in enumerate(tbl.rows) if row.cells[0].text.strip() == "AgentOps overage — post-build")
support_tr = copy.deepcopy(tbl.rows[ops_index]._tr)
tbl.rows[ops_index]._tr.addnext(support_tr)
support_row = tbl.rows[ops_index + 1]
set_cell(support_row.cells[0], "Enhanced End-User Support — optional")
set_cell(support_row.cells[1], "Per live agent / month")
set_cell(
    support_row.cells[2],
    "$50 for direct L1 functional user assistance: usage questions, request triage and guidance "
    "during agreed business hours. Separate from technical AgentOps, incident response and product support.",
)

# Insert a styled pilot row immediately after T&M, retaining table formatting.
tm_index = next(i for i, row in enumerate(tbl.rows) if row.cells[0].text.strip() == "T&M day rates")
pilot_tr = copy.deepcopy(tbl.rows[tm_index]._tr)
tbl.rows[tm_index]._tr.addnext(pilot_tr)
pilot_row = tbl.rows[tm_index + 1]
set_cell(pilot_row.cells[0], "UCC Factory Validation Pilot")
set_cell(pilot_row.cells[1], "13 weeks; UCC MIGO scope")
set_cell(
    pilot_row.cells[2],
    "≈ $90k–110k for mobilisation, design, build, parallel run, go-live stabilisation and "
    "pattern-library seeding. Priority-agent volume remains subject to PIH clarification; excludes "
    "PIH infrastructure and direct cloud consumption.",
)

for section in doc.sections:
    for p in section.header.paragraphs:
        for run in p.runs:
            if "DRAFT v4 — internal work in progress" in run.text:
                run.text = run.text.replace("DRAFT v4", "DRAFT v5")
for p in doc.paragraphs:
    for run in p.runs:
        if "DRAFT v4 — internal" in run.text:
            run.text = run.text.replace("DRAFT v4", "DRAFT v5")

for p in doc.paragraphs:
    if "After the Factory build programme, the Enterprise Platform" in p.text:
        set_text = (
            "After the Factory build programme, the Enterprise Platform & Managed Operations Baseline covers "
            "the first 50 live agents. PIH may operate agents itself or appoint another operator; delivered "
            "flows, design cards, evaluation evidence and documented connector mappings are handover-ready. "
            "If PIH requests direct L1 functional end-user assistance, Datategy offers Enhanced End-User "
            "Support as an optional per-agent service; it is separate from technical AgentOps, incident "
            "response and product support. PIH retains a non-exclusive right to execute accepted delivered "
            "versions on PIH-controlled infrastructure. This does not transfer Agentium product IP, future "
            "releases or source code; updates, compatibility, regression and N3 support remain part of the "
            "post-build continuity regime."
        )
        for run in list(p.runs):
            run._r.getparent().remove(run._r)
        p.add_run(set_text)

doc.save(OUT)

out = Document(OUT)
table_text = "\n".join(cell.text for table in out.tables for row in table.rows for cell in row.cells)
for term in ["Low $69 · Medium $79 · High $89", "$8,900/month for the first 50 live agents", "Enhanced End-User Support", "≈ $90k–110k", "DRAFT v5"]:
    source = "\n".join(p.text for p in out.paragraphs) + "\n" + table_text
    print(("OK" if term in source else "FAIL"), term)
print("saved:", OUT)
