# -*- coding: utf-8 -*-
"""UC-01 — Financial Reporting Automation Agent (PIH Finance, AGT-FIN-FRA-001).

Takes the blank intake template and fills Status / PIH answer / follow-up
columns from the BRD received 27 July 2026, plus the Datategy evaluation tab.
Output: docs/pih/UC-01-Financial-Reporting-Automation-Intake.xlsx
"""
import os
from openpyxl import load_workbook

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "pih", "Use-Case-Intake-Template-PIH.xlsx")
OUT = os.path.join(HERE, "..", "pih", "UC-01-Financial-Reporting-Automation-Intake.xlsx")

# item id -> (status, PIH answer / reference, Datategy follow-up question)
DATA = {
    "1.1": ("Provided",
            "BRD §2.1 — fragmented manual monthly reporting: SAP TB extraction, per-entity GL "
            "mapping, Excel P&L/BS/Forecast, rework into Flash, XCOM and ~200-slide PPT, multiple "
            "review cycles (Finance → GCFO → CEO → XCOM). ~40 business units, day-5/7/15 cycle.",
            ""),
    "1.2": ("Provided",
            "Requesting entity: Estithmar Holding — Finance (per transmittal email, 23 Jul). "
            "Sponsor: Mr. Samer Ratrout (Group CFO). Business owner: Ahmad Abbad (Financial "
            "Controller). Process owner: Riamme Songcuan Tandoc (Chief Accountant). Lead BA: "
            "Ralph Pagarigan.",
            ""),
    "1.3": ("To clarify",
            "BRD §3 — Finance Analysts / Managers, up to 25 staff, AI literacy medium-high, "
            "trust posture: validation required before submission.",
            "Working language of reports and of the validation UI — English only, or "
            "English + Arabic anywhere in the chain?"),
    "1.4": ("To clarify",
            "BRD §11 — KPIs defined (cycle time vs day-5/7/15, manual hours, error/restatement "
            "rate, on-time delivery, automation coverage, hours saved, rework).",
            "Baseline values needed to measure improvement: current hours per cycle (per BU and "
            "consolidated), current error/restatement rate, current on-time delivery rate. Even "
            "rough estimates from the last 3 cycles are enough at this stage."),
    "1.5": ("Provided",
            "Monthly cycle, ~40 business units, deadlines day-5 (Flash) / day-7 / day-15. Peak "
            "load concentrated on month close.",
            "Confirm the day-5/7/15 mapping to each deliverable (which report is due which day)."),

    "2.1": ("Provided",
            "BRD §4.1 As-Is (8 steps with actor/system/time/pain) + §4.2 To-Be + process-map "
            "workbook (Flash & XCOM current/future).",
            "The process-map file is mostly diagrams — a 30-min walkthrough with the process "
            "owner is requested to capture the exception paths (late BU submissions, mapping "
            "gaps, restatements)."),
    "2.2": ("To clarify",
            "BRD §5 — decision inventory D1–D6 (validate TB, apply GL mapping, detect "
            "inconsistencies, trigger workflows, generate reports, request validation).",
            "For D6 (request validation): what are the threshold rules (materiality, variance "
            "vs prior month/budget)? For D3: which inconsistency checks run today and who "
            "arbitrates a flagged issue? For D2: who owns and maintains the GL mapping "
            "library, and how often does it change?"),
    "2.3": ("Missing",
            "",
            "Golden set: please provide the last 2–3 complete monthly cycles — SAP TB extracts "
            "per entity + the corresponding validated final outputs (P&L, BS, Flash, XCOM, PPT "
            "deck). This becomes the acceptance reference (PIH IP, stored at PIH). Anonymised "
            "figures acceptable if structure is preserved."),
    "2.4": ("To clarify",
            "BRD §8/§10 — no data modification without validation, no fabricated values, full "
            "auditability, final approval with finance leadership; human validation layer before "
            "submission; manual Excel fallback as DR.",
            "Tolerance split: is a formatting deviation in the PPT treated the same as a numeric "
            "error? What happens to the cycle if the agent flags an inconsistency on day 4 — "
            "who resolves it and within what SLA?"),

    "3.1": ("To clarify",
            "BRD §6 — SAP (Trial Balance, ERP, Finance IT), Excel & PPT templates on SharePoint, "
            "reporting rules documents, historical reports archive.",
            "SAP landscape: ECC or S/4HANA? Single instance for all ~40 BUs or several? How is "
            "the TB extracted today (transaction code, BW/BO report, flat-file export)? "
            "SharePoint Online (M365) or on-premises?"),
    "3.2": ("To clarify",
            "Implied: SAP read-only; agent writes generated reports to SharePoint; validation "
            "before any submission (R2, N1, N3).",
            "Confirm SAP is strictly read-only for the agent. For SharePoint: which libraries "
            "does the agent write to, and does the existing approval workflow (Finance → GCFO → "
            "CEO → XCOM) live in SharePoint/Teams or by email?"),
    "3.3": ("Missing",
            "",
            "Samples requested: one TB extract (any entity, anonymised OK), the GL mapping file "
            "for 2–3 entities including one known to be inconsistent, and one current-month "
            "Excel model (P&L/BS with formulas)."),
    "3.4": ("To clarify",
            "BRD §6 — approved Excel/PPT templates and reporting rules exist on SharePoint.",
            "Please share the approved templates (Excel P&L/BS/Forecast, Flash, XCOM, PPT master) "
            "and the reporting-rules documents. Are templates identical across BUs or per-entity "
            "variants?"),
    "3.5": ("Provided",
            "BRD §12 — Confidential; data residency: PIH internal systems / SharePoint; no "
            "external data exposure; financial governance standards; full traceability.",
            "Consistent with sovereign deployment. See 4.4 for the runtime consequence."),

    "4.1": ("Missing",
            "Stage 1 (SaaS showcase): no live SAP/SharePoint access needed — anonymised "
            "file-based extracts suffice (see 3.3, 2.3).",
            "For stage 2 (on-prem): read-only SAP service account (TB scope) on a sandbox or QA "
            "client first; SharePoint/Microsoft Graph service account limited to the reporting "
            "libraries; M365 tenant app registration process and owner. Can start in parallel "
            "with stage 1."),
    "4.2": ("Missing",
            "",
            "A test environment or representative extract: SAP QA client or recurring TB "
            "flat-file drop + a sandbox SharePoint site mirroring the reporting libraries "
            "(stage 2)."),
    "4.3": ("Missing",
            "",
            "Named IT contact for (a) SAP / Finance IT and (b) SharePoint / M365 — this is "
            "historically the critical path; we would like both named before the August visit."),
    "4.4": ("Provided",
            "Two-stage approach agreed (PowerMind email, 27 Jul): stage 1 — showcase on NAWA "
            "SaaS (minimal prerequisites); stage 2 — redeploy the same use case unchanged to an "
            "on-prem demo box (reduced single-node configuration, no full HA) to demonstrate "
            "the air-gapped capability. Consistent with BRD §12 confidentiality constraints.",
            "For stage 2 planning: demo box specs and availability date, and whether outbound "
            "connectivity is allowed or the box is strictly air-gapped (determines self-hosted "
            "LLM serving on the box)."),
}

EVAL = {
    "5.1": "Feasible — strong structural fit (scheduled pipeline + deterministic generation + "
           "human validation layer, exactly Agentium's System/Flow/gate model). Two conditions: "
           "(1) the GL mapping library per entity is the make-or-break input — the BRD itself "
           "flags SAP data inconsistency across BUs as the current blocker; (2) golden set "
           "(item 2.3) must be available before build starts.",
    "5.2": "Complex tier (Annex B typology): multi-system integration (SAP + SharePoint + "
           "Office), consolidation across ~40 entities, generated deliverables submitted to "
           "executive level, write access to SharePoint. The conversational surface is minimal; "
           "the complexity is in data mapping, consolidation and document generation at scale.",
    "5.3": "Reuse: SAP connector pattern (read/query), scheduled triggers (monthly calendar), "
           "human decision gates with expiry, audit ledger, SharePoint connectivity (existing "
           "connector base). First-of-type: financial consolidation logic, Excel-model "
           "generation, and industrial PPT deck generation (~200 slides) — the latter becomes a "
           "reusable pattern for every other reporting use case at PIH, which is the factory "
           "argument.",
    "5.4": "Indicative phasing (planning heuristic, not contractual — set at design-card stage): "
           "Phase A: TB ingestion + GL mapping + P&L/BS for a subset of 3–5 BUs, human "
           "validation gate. Phase B: consolidation + Flash/XCOM. Phase C: PPT deck automation. "
           "Each phase gated on its golden-set run. Deployment sequence per the agreed two-stage "
           "approach: build and showcase on SaaS first (unlocked by the reference cycles, item "
           "2.3 — no live access needed), then redeploy unchanged to the on-prem demo box when "
           "ready (stage-2 access items 4.1–4.3 can be provisioned in parallel).",
    "5.5": "Open questions: see column G of the intake grid. Tagged for direct requester "
           "exchange (walkthrough): 2.1 exception paths, 2.2 threshold/mapping governance, 2.4 "
           "tolerance split. Written answers sufficient: 1.3, 1.4, 3.1, 3.2, 3.4, 4.4. Note: BRD "
           "section numbering jumps 6→8→10 — please confirm sections 7 and 9 were intentionally "
           "removed or share them if they exist.",
    "5.6": "Risks: (1) GL mapping inconsistency across the 40 BUs — mitigated by starting with a "
           "clean subset and building the mapping library incrementally; (2) acceptance "
           "subjectivity on the 200-slide deck — mitigated by template lock + golden-set visual "
           "diff on a sample of slides; (3) SAP access lead time before the Aug 2–8 visit; "
           "(4) baseline KPIs missing (1.4) — without them the ROI story cannot be evidenced.",
}

wb = load_workbook(SRC)
ws = wb["Intake grid"]
filled = 0
for row in ws.iter_rows(min_row=4):
    key = row[0].value
    if key in DATA:
        st, ans, q = DATA[key]
        row[4].value = st
        row[5].value = ans or None
        row[6].value = q or None
        n = max(1, len(ans) // 55, len(q) // 55)
        ws.row_dimensions[row[0].row].height = max(30, 13 * (n + 1))
        filled += 1
assert filled == len(DATA), (filled, len(DATA))

ws2 = wb["Datategy evaluation"]
filled2 = 0
for row in ws2.iter_rows(min_row=5):
    key = row[0].value
    if key in EVAL:
        row[3].value = EVAL[key]
        ws2.row_dimensions[row[0].row].height = max(44, 13 * (len(EVAL[key]) // 60 + 1))
        filled2 += 1
assert filled2 == len(EVAL), (filled2, len(EVAL))

ws3 = wb["Use case log"]
ws3.cell(row=5, column=1, value="UC-01 — Financial Reporting Automation Agent (AGT-FIN-FRA-001, "
                                "Estithmar Holding Finance)")
ws3.cell(row=5, column=2, value="2026-07-23")
ws3.cell(row=5, column=3, value="2026-07-27")
ws3.cell(row=5, column=4, value=2)
ws3.cell(row=5, column=7, value="Returned — awaiting answers")
ws3.cell(row=5, column=8, value="BRD + process map from BA (Ralph Pagarigan), pilot verbally "
                                "confirmed. BRD already ISO 42001/BABOK-structured — maps ~1:1 to "
                                "our BR template. Two-stage SaaS → on-prem deployment agreed with "
                                "PowerMind (Z. Mandouli). Walkthrough with process owner requested.")

wb.save(OUT)
print("saved:", os.path.abspath(OUT))
