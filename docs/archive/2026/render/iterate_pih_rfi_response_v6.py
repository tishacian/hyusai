#!/usr/bin/env python3
"""RFI Response v6 — from v5: AgentOps overage tiers raised to $120/$140/$160
to align with Annex B v6. DRAFT marking updated."""
import os
from docx import Document

HERE = os.path.dirname(os.path.abspath(__file__))
PIH = os.path.join(HERE, "..", "pih")
SRC = os.path.join(PIH, "RFI-PIH-AI-Factory-Response-v5.docx")
OUT = os.path.join(PIH, "RFI-PIH-AI-Factory-Response-v6.docx")

doc = Document(SRC)

def set_cell(cell, text):
    # Keep the first run's formatting; drop extra paragraphs/runs.
    first_par = cell.paragraphs[0]
    if first_par.runs:
        first_par.runs[0].text = text
        for run in first_par.runs[1:]:
            run.text = ""
    else:
        first_par.add_run(text)
    for par in cell.paragraphs[1:]:
        for run in par.runs:
            run.text = ""

changed = 0
for tbl in doc.tables:
    for row in tbl.rows:
        if row.cells[0].text.strip() == "AgentOps overage — post-build":
            set_cell(
                row.cells[2],
                "Low $120 · Medium $140 · High $160. High-impact scope includes reinforced "
                "drift watch and quarterly adversarial/red-team regression.",
            )
            changed += 1

assert changed >= 1, "AgentOps overage row not found"

for par in doc.paragraphs:
    if "DRAFT v5" in par.text:
        for run in par.runs:
            if "DRAFT v5" in run.text:
                run.text = run.text.replace("DRAFT v5", "DRAFT v6")

doc.save(OUT)
print("saved:", OUT)

# ------------------------------------------------ verification
import re, zipfile
xml = zipfile.ZipFile(OUT).read("word/document.xml").decode("utf-8")
txt = re.sub(r"<[^>]+>", " ", xml)
txt = re.sub(r"\s+", " ", txt)
for needle in ["Low $120 · Medium $140 · High $160", "$8,900/month for the first 50 live agents", "DRAFT v6"]:
    assert needle in txt, f"missing: {needle}"
for stale in ["Low $69", "Medium $79", "High $89", "DRAFT v5"]:
    assert stale not in txt, f"stale: {stale}"
print("all checks passed")
