# -*- coding: utf-8 -*-
"""PIH Build Effort Detail v1 — micro man-day plan per use case, per wave.

Justifies the negotiated build total (Option 1 ≈ USD 50k / Option 2 ≈ USD 60k,
client-validated 2026-07-08) by detailing every action, per UC and per wave,
under explicit factorisation assumptions:
  - platformisation: Agentium product features = 0 build days (run engine,
    mandates, HITL, audit, eval harness, channels); flow authoring is hours;
  - functional overlap: shared one-time subflows (identity verification,
    simulate/parallel-run harness, credential delivery) paid once, reused by
    every UC of the family;
  - scalable pilot patterns: the pilot proves one exemplar of each of the four
    foundational patterns; every other UC is a reuse instance (1–2.5 d);
  - connector framework: PIH-specific connectors on the catalogue framework,
    10 d max each; SDP/Entra base laid in the initial engagement;
  - AI-assisted delivery across authoring, tests and documentation.

Day budgets (asserted below) land exactly on the negotiated prices:
  Engagement initial: 50 CoE d + 3 SSA d            = USD 10,000
  Wave 2:            150 CoE d + 3 SSA d + 2 QA d   = USD 25,900
  Wave 3:             82 CoE d + 2 SSA d            = USD 13,918
  Option 1 total                                    = USD 49,818 (≈ 50k)
  Employee Services:  67 CoE d                      = USD  9,983 (≈ 10k)
  Option 2 total                                    = USD 59,801 (≈ 60k)

Output: docs/pih/Service Help Desk - Build Effort Detail - v1 Datategy.xlsx
"""
import os
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "pih", "Service Help Desk - Build Effort Detail - v1 Datategy.xlsx")

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

COE_RATE = 149
SSA_RATE = 850
QA_RATE = 500


def style_row(ws, row, ncols, header=False, fill=None):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = H_FONT if header else B_FONT
        cell.border = THIN
        if header:
            cell.fill = FILL_H
        elif fill:
            cell.fill = fill
        cell.alignment = Alignment(vertical="top", wrap_text=True)


# ============================================================ micro plan data
# line = (item, pattern, type, actions, days)
#   type: "one-time" (paid once, reused), "first" (first pattern instance),
#         "reuse" (pattern reuse), "campaign" (cross-UC activity)

EI_LINES = [
    ("Environments & security foundation", "—", "one-time",
     "Deploy Agentium in PIH Azure tenant (Qatar region); Entra ID SSO (OIDC); RBAC/ABAC roles; "
     "secrets vault binding; audit log export. Product installation + configuration — no development.", 6),
    ("ManageEngine SDP connector (core)", "—", "one-time",
     "Catalogue framework base: auth, ticket create / enrich / categorise / track / close, SLA read. "
     "Sandbox-first, smoke-tested. Reused by every one of the 39 use cases.", 5),
    ("Entra ID connector — read + simulate", "—", "one-time",
     "Service account (least-privilege scope: reset/unlock/read), user resolution, account status; "
     "write skills wired in SIMULATE mode only at this stage.", 3),
    ("Teams + Exchange channel binding", "—", "one-time",
     "Front-door bot registration, notification templates, email channel intake. Product channel "
     "adapters — configuration only.", 2),
    ("Knowledge ingestion + golden-set harness", "—", "one-time",
     "IT KB ingestion (multi-format, OCR), workspace isolation, hybrid index; golden-set tooling "
     "seeded for the 4 pilot families (incl. refusal cases).", 5),
    ("Simulate / parallel-run harness (privileged writes)", "—", "one-time",
     "Produce the action the agent WOULD take (payload + log, no execution) and diff it against the "
     "human action on identical requests. Paid once — reused by the whole identity family.", 2),
    ("Identity-verification subflow", "—", "one-time",
     "Requester resolution from SSO context + MFA step-up branch + exclusion rules (admin/VIP/shared "
     "accounts), agreed with PIH security. Reused by every identity & provisioning UC.", 3),
    ("KPI cockpit baseline", "—", "one-time",
     "Deflection / MTTR / SLA baseline feeds wired to the run ledger; client-confirmed baselines "
     "for the pilot exit gate.", 2),
    ("UC18 — User Q&A Knowledgebase", "P-DEFLECT", "first",
     "First deflection instance: flow authoring (hours on Flow Builder); KB curation with IT team; "
     "grounded-answer golden set + abstention thresholds; live on representative population.", 4),
    ("UC19 — Ticket Creation & Tracking (Daizy)", "P-TICKET", "reuse",
     "Conversational create/track/status on the SDP connector laid above; intent nodes + templates. "
     "Highest-volume UC (1,104/mo) — validated against legacy on identical inputs.", 2),
    ("UC14 — AD Password Expiry Reminders", "P-DETECT", "first",
     "First proactive detector: scheduled scan (1,800/mo), notification campaign, opt-out & "
     "escalation branches; batch execution mode.", 2.5),
    ("UC29 — T&A Device Proactive Detection", "P-DETECT", "reuse",
     "Detector pattern reuse: device-offline scan + alert + auto-ticket in SDP. Config of the "
     "detector template, no new build.", 1.5),
    ("UC1 — Password Reset", "P-IDW", "first",
     "First identity write: security spec with client (verification semantics, step-up, exclusions) "
     "1d; flow authoring 0.5d; golden set + refusal cases 1.5d; parallel-run vs service desk on "
     "identical requests 1d. SIMULATE only — no production write in the pilot.", 4),
    ("UC4 — Email Group Creation", "P-APPR", "first",
     "First approval-orchestrated flow E2E: approval spec 0.5d; authoring (request → multi-level "
     "approval → fulfilment) 1d; Rejected/Missed/Failed branches 0.5d; eval 1d; UAT with approvers "
     "1d. Goes LIVE in the pilot (low-risk write).", 4),
    ("Pilot UAT, exit-gate evidence & hypercare", "—", "campaign",
     "Measured deflection vs baseline, parallel-run report signed, UAT & security validation, "
     "30-day hypercare with tuning.", 4),
]

W2_LINES = [
    ("Egnyte connector", "—", "one-time",
     "Catalogue framework: auth, document access, knowledge retrieval, file-related requests.", 6),
    ("SolarWinds ARM connector", "—", "one-time",
     "Access-rights read, permissions review feeds, identity checks for the access UCs.", 6),
    ("Palo Alto / Fortinet connector", "—", "one-time",
     "Firewall-rule request workflows (request objects, staged apply under mandate, rollback).", 8),
    ("Oracle Symphony connector", "—", "one-time",
     "Offboarding actions + status read; scoped to UC27 needs.", 4),
    ("SuccessFactors connector", "—", "one-time",
     "HR events (joiner/leaver triggers) + employee data read. Also reused by the Employee "
     "Services module in Option 2.", 4),
    ("UC1 — Password Reset (go-live)", "P-IDW", "reuse",
     "Staged live: canary write on controlled account, kill switch + rollback tested, production "
     "under signed mandate. Authoring already paid in the pilot.", 1.5),
    ("UC2 — Unlock AD Account", "P-IDW", "reuse",
     "Same connector, same verification subflow, same harness — different skill call. Config + "
     "parallel-run evidence + staged live.", 1.5),
    ("UC24 — Offboarding On-Prem AD", "P-JML", "first",
     "First offboarding orchestration: multi-step disable/archive/notify sequence, HR trigger, "
     "heavier parallel-run (416/mo), staged live under mandate.", 4),
    ("UC25 — Offboarding Intra AD", "P-JML", "reuse",
     "Variant of UC24 on the second directory: flow clone + scope config + evidence pack.", 1.5),
    ("UC27 — Oracle Symphony Offboarding", "P-JML", "reuse",
     "Offboarding pattern on the Oracle connector; event-driven trigger; parallel-run.", 2.5),
    ("UC28 — Offboarding SF Data", "P-JML", "reuse",
     "Offboarding pattern on SF events (843/mo); data-sync validation branch.", 2.5),
    ("UC23 — Onboarding (QWIK BOT)", "P-JML", "first",
     "First multi-system joiner orchestration (AD + M365 + SF): sequence spec, provisioning steps, "
     "manager notifications, exception queue. Reuses verification subflow + credential delivery.", 5),
    ("UC31 — Consultant Email ID Creation", "P-PROV", "reuse",
     "Provisioning pattern instance with consultant-specific eligibility rules and expiry metadata.", 1.5),
    ("UC32 — Consultant AVD/VPN Access", "P-PROV", "first",
     "First network-access provisioning: firewall connector binding, approval gate, access-expiry "
     "logic. Template for UC34.", 2.5),
    ("UC34 — VPN/AVD Access for Users", "P-PROV", "reuse",
     "Clone of UC32 for employees; eligibility rules differ, flow identical.", 1.5),
    ("UC33 — Email Block (HR + IT)", "P-APPR", "reuse",
     "Approval pattern with dual HR+IT approval branch; block/unblock skills on Exchange.", 1.5),
    ("UC21 — Email Creation", "P-PROV", "first",
     "First mailbox provisioning with secure credential delivery (one-time channel via Teams); "
     "naming rules + licence assignment.", 3),
    ("UC22 — Email Reactivation", "P-PROV", "reuse",
     "Reactivation variant of UC21: state checks + same delivery machinery.", 1.5),
    ("Identity family — write hardening", "P-IDW/JML", "campaign",
     "Per-UC signed mandates (caps, scopes, validity), tested kill switch and rollback for every "
     "write flow, staged-live sequencing per company batch.", 4.5),
    ("UC5 — Email Group Members Addition", "P-APPR", "reuse",
     "UC4 pattern; membership skill; approver matrix config.", 1),
    ("UC6 — Email Group Members Deletion", "P-APPR", "reuse",
     "UC4 pattern; deletion branch + confirmation guard.", 1),
    ("UC7 — Shared Mailbox Creation", "P-APPR", "reuse",
     "UC4 pattern on mailbox objects; naming/ownership rules.", 1.5),
    ("UC8 — Shared Mailbox User Addition", "P-APPR", "reuse",
     "Membership variant on shared mailboxes.", 1),
    ("UC9 — Shared Mailbox User Deletion", "P-APPR", "reuse",
     "Deletion variant; audit note to owner.", 1),
    ("UC15 — User Signature Update", "P-APPR", "reuse",
     "Template-driven signature generation (294/mo), brand rules, self-service approval-light.", 1.5),
    ("UC36 — Announcement Communication", "P-COMM", "reuse",
     "Approval pattern + broadcast skill (Teams/email), audience targeting per entity.", 1.5),
    ("UC10 — Printer Installation", "P-DEVICE", "first",
     "First device UC: guided flow + endpoint tool invocation + fallback to technician ticket.", 2),
    ("UC11 — Printer Code Creation", "P-DEVICE", "reuse",
     "Code generation + assignment on print management system (70/mo).", 1.5),
    ("UC12 — Color Printer Access", "P-DEVICE", "reuse",
     "Access grant variant with cost-centre approval branch.", 1),
    ("UC13 — Print Code Queries", "P-DEFLECT", "reuse",
     "Deflection pattern: grounded answer over print documentation + code lookup.", 1),
    ("UC16 — Software Installation", "P-DEVICE", "first",
     "Catalogue-driven install requests: licence check, approval gate, endpoint execution, "
     "30-min class UC kept human-in-the-loop.", 3),
    ("UC17 — Windows Update Installation", "P-DEVICE", "reuse",
     "Scheduled/triggered update flow with maintenance-window guard; reuses UC16 machinery.", 2.5),
    ("UC20 — User Office Address Updates", "P-APPR", "reuse",
     "Directory attribute update with validation branch; low volume, straight reuse.", 1.5),
    ("UC35 — Hardware Info Collection (Daizy)", "P-TICKET", "reuse",
     "Guided collection conversation writing to SDP asset fields; volume currently 0 — kept as "
     "authored flow, activated on demand.", 1),
    ("UC26 — Closure of Non-Responsive Tickets", "P-TICKET", "reuse",
     "Reminder cadence + auto-close with reopen guard, per SLA policy (30/mo).", 2),
    ("UC3 — Outlook Self-Healing", "P-DETECT", "reuse",
     "Diagnostic playbook (profile repair sequence) + endpoint skill + user confirmation loop.", 2.5),
    ("UC37 — Proactive Validation — Data Sync", "P-DETECT", "reuse",
     "Detector template on cross-system consistency checks (AD/SF/Oracle), auto-ticket on drift.", 1.5),
    ("39/39 parallel-run vs legacy", "—", "campaign",
     "Every migrated UC validated against legacy behaviour on identical inputs before cut-over; "
     "per-UC evidence pack for the exit gate. AI-assisted test generation.", 18),
    ("Golden sets & refusal cases (privileged UCs)", "—", "campaign",
     "Per-UC golden sets extended; refusal cases for every write (actions the agent must never "
     "take); thresholds + review queues configured.", 12),
    ("Integration testing & UAT support", "—", "campaign",
     "Per-wave quality gates: integration test runs, UAT sessions with IT agents and approvers, "
     "defect fixing loops.", 12),
    ("Legacy coexistence & cut-over", "—", "campaign",
     "Channel-by-channel switch from Daizy / Leena / QWIK BOT, parallel operation, decommission "
     "checklist per UC family.", 8),
    ("Extension to additional companies (first batch)", "—", "campaign",
     "Workspace + ABAC segmentation for the first batch of entities beyond the pilot population.", 5),
    ("Wave 2 hypercare (30 days)", "—", "campaign",
     "Reinforced support, prompt tuning, KB fixes, KPI verification against the run ledger.", 4.5),
]

W3_LINES = [
    ("Multi-entity / multi-country rollout", "—", "campaign",
     "Workspace templating industrialised and applied per company batch across 145+ companies / "
     "25 countries; entity-level segmentation, localised notification templates.", 18),
    ("Extended RCA & trend analytics", "—", "first",
     "12–24 months of SDP history: recurring-incident clustering, pattern detection per category / "
     "site / company, grounded root-cause explanations with remediation recommendations "
     "(Datategy published failure-analysis research applied to IT operations).", 14),
    ("UC30 — Device Manufacturing Data Collector", "P-REPORT", "first",
     "Batch collection pipeline (the 44,500-min manual UC): scheduled runs, consolidation, "
     "export to dashboards.", 3),
    ("UC38 — Email Expiry Reminder (Consultants)", "P-DETECT", "reuse",
     "Detector template instance on consultant accounts with expiry metadata from UC31.", 1),
    ("UC39 — Leena Dashboard Data Extractor", "P-REPORT", "reuse",
     "Superseded by the native KPI cockpit + API exports; residual work = mapping legacy report "
     "fields and validating continuity for consumers.", 3),
    ("Arabic user-experience package (optional)", "—", "one-time",
     "Arabic-capable model routing benchmark on PIH golden sets, KB coverage checks, UX validation "
     "with Arabic-speaking users.", 8),
    ("Optimisation & production robustness", "—", "campaign",
     "Prompt-regression suite, drift monitoring, latency/cost tuning per control policy, review of "
     "low-confidence queues.", 10),
    ("Datategy Academy enablement", "—", "campaign",
     "Role-based tracks: end users, IT agents (exception handling), administrators (cockpit, "
     "policies, connectors), builders (Flow Builder autonomy); train-the-trainer pack + "
     "documentation and runbooks.", 15),
    ("Handover & final acceptance", "—", "campaign",
     "Operations handed to PIH team, KPI dashboards reconciled with the run ledger, final "
     "acceptance evidence and sign-off.", 10),
]

HR_LINES = [
    ("HR knowledge ingestion & taxonomy", "—", "one-time",
     "HR policies & services corpus (leave, documents, onboarding questions): ingestion, "
     "classification by domain / audience / confidentiality, ownership mapping.", 10),
    ("SuccessFactors connector extension", "—", "one-time",
     "Employee-context read extension on the connector already built in Wave 2 (marginal cost — "
     "the connector itself is paid by the IT scope).", 4),
    ("HR Q&A flow", "P-DEFLECT", "reuse",
     "IT deflection pattern instance on the HR corpus: grounded, cited answers with abstention; "
     "same channels, same machinery.", 6),
    ("Self-service document requests", "P-APPR", "reuse",
     "Approval pattern instance: attestation / document requests routed to HR with status "
     "tracking; HR systems remain systems of record.", 5),
    ("Leave & onboarding-questions flows", "P-DEFLECT", "reuse",
     "Two further deflection instances scoped to leave rules and newcomer questions.", 6),
    ("PII guardrails & HR refusal sets", "—", "campaign",
     "HR-specific control policies: personal-data boundaries, seniority/salary refusals, "
     "escalation to HR humans; refusal golden sets.", 8),
    ("Multilingual EN/AR validation", "—", "campaign",
     "HR answers benchmarked in English and Arabic on the golden sets; terminology review.", 6),
    ("HR golden sets & evaluation", "—", "campaign",
     "Grounded-answer and hallucination rates measured per flow; thresholds and review queues.", 8),
    ("UAT & hypercare (HR scope)", "—", "campaign",
     "UAT with HR stakeholders, 30-day hypercare after go-live with Waves 2–3.", 8),
    ("Delivery coordination (HR scope)", "—", "campaign",
     "Backlog, HR stakeholder alignment, wave reporting.", 6),
]

WAVES = [
    ("Engagement initial — Phase 0-lite + Pilot (months 1–3) · ≈ USD 10k", EI_LINES, 50,
     [("Senior Solution Architect (Paris oversight)", 3, SSA_RATE)]),
    ("Wave 2 — Migration 39/39 & privileged writes (months 3–6) · ≈ USD 26k", W2_LINES, 150,
     [("Senior Solution Architect (Paris oversight)", 3, SSA_RATE),
      ("QA / Governance Lead (Paris oversight)", 2, QA_RATE)]),
    ("Wave 3 — Scale & proactive (months 6–8) · ≈ USD 14k", W3_LINES, 82,
     [("Senior Solution Architect (Paris oversight)", 2, SSA_RATE)]),
    ("Employee Services module — Option 2 (with Waves 2–3) · ≈ USD 10k", HR_LINES, 67, []),
]

# ---- assertions: day sums must match the negotiated wave budgets exactly
for title, lines, budget, _ in WAVES:
    total = sum(l[4] for l in lines)
    assert abs(total - budget) < 1e-9, f"{title}: {total} d != budget {budget} d"

wb = openpyxl.Workbook()

# ============================================================ ASSUMPTIONS
asm = wb.active
asm.title = "Assumptions"
asm["A1"] = "Build Effort Detail — factorisation assumptions"
asm["A1"].font = TITLE
asm["A2"] = ("Micro man-day plan justifying the negotiated build (Option 1 ≈ USD 50k / Option 2 ≈ USD 60k). "
             "All build days delivered by the AI & Data Center of Excellence at USD 149/day, under a thin "
             "Paris architecture & QA oversight (10 days across the programme). Aligned with the Technical & "
             "Commercial offer and the Price Schedule.")
asm["A2"].font = NOTE
ASSUMPTIONS = [
    ("Platformisation (Agentium = product)",
     "Run engine, mandates & approval gates, HITL, audit ledger, evaluation harness, channels (Teams/portal/"
     "email), model router: 0 build days — product features configured, not developed. Authoring a flow on "
     "the Flow Builder is measured in hours; the man-days below are dominated by security semantics, "
     "evaluation and parallel-run evidence, not by development."),
    ("Functional overlap between use cases",
     "One-time shared subflows paid once and reused by every UC of the family: identity-verification "
     "subflow (SSO + MFA step-up), simulate/parallel-run harness for privileged writes, secure credential "
     "delivery, detector template, approval matrix. This is why a reuse instance costs 1–2.5 days."),
    ("Scalable pilot patterns",
     "The pilot proves one exemplar of each of the 4 foundational patterns (deflection, proactive detector, "
     "identity write, approval-orchestrated). First instances carry the pattern cost (2.5–5 d); the other "
     "33 UCs are reuse instances at 1–2.5 d dominated by configuration + evidence."),
    ("Connector framework",
     "PIH-specific connectors are built on the catalogue framework (auth, retries, logging, permission "
     "validation standardised): 4–8 days each, delivered as reusable catalogue components. SDP + Entra "
     "bases are laid in the initial engagement and reused by all 39 UCs."),
    ("AI-assisted delivery",
     "Test-case and golden-set generation, documentation, translation and flow scaffolding are "
     "AI-assisted, compressing campaign lines (parallel-run, UAT, documentation) by roughly half."),
    ("Evidence-first migration",
     "Every UC ships with parallel-run evidence vs legacy on identical inputs before cut-over. These "
     "campaign lines (18 d in Wave 2) are the guarantee behind the '39/39 migration validated' exit gate."),
]
r = 4
for j, h in enumerate(["Assumption", "What it means in the plan"], 1):
    asm.cell(row=r, column=j, value=h)
style_row(asm, r, 2, header=True)
r += 1
for i, (a, b) in enumerate(ASSUMPTIONS):
    asm.cell(row=r, column=1, value=a).font = BOLD
    asm.cell(row=r, column=2, value=b)
    style_row(asm, r, 2, fill=FILL_P if i % 2 else None)
    asm.cell(row=r, column=1).font = BOLD
    r += 1
asm.column_dimensions["A"].width = 38
asm.column_dimensions["B"].width = 110

# ============================================================ WAVE SHEETS
GRAND = []  # (sheet title, total cell ref)
for title, lines, budget, oversight in WAVES:
    ws = wb.create_sheet(title.split(" — ")[0][:28])
    ws["A1"] = title
    ws["A1"].font = TITLE
    ws["A2"] = ("Type: one-time = paid once, reused across the family · first = first instance of a pattern "
                "(carries the pattern cost) · reuse = pattern instance (configuration + evidence) · "
                "campaign = cross-UC activity. CoE rate USD 149/day.")
    ws["A2"].font = NOTE
    r = 4
    for j, h in enumerate(["Item / Use case", "Pattern", "Type", "Actions (explicit)", "Days", "Amount (USD)"], 1):
        ws.cell(row=r, column=j, value=h)
    style_row(ws, r, 6, header=True)
    r += 1
    first = r
    for i, (item, pat, typ, actions, days) in enumerate(lines):
        ws.cell(row=r, column=1, value=item).font = BOLD
        ws.cell(row=r, column=2, value=pat)
        ws.cell(row=r, column=3, value=typ)
        ws.cell(row=r, column=4, value=actions)
        ws.cell(row=r, column=5, value=days)
        ws.cell(row=r, column=6, value=f"=E{r}*{COE_RATE}").number_format = MONEY
        fill = FILL_P if i % 2 else None
        style_row(ws, r, 6, fill=fill)
        ws.cell(row=r, column=1).font = BOLD
        r += 1
    ws.cell(row=r, column=1, value="Subtotal CoE").font = BOLD
    ws.cell(row=r, column=5, value=f"=SUM(E{first}:E{r-1})").font = BOLD
    ws.cell(row=r, column=6, value=f"=SUM(F{first}:F{r-1})").font = BOLD
    ws.cell(row=r, column=6).number_format = MONEY
    style_row(ws, r, 6, fill=FILL_A)
    coe_sub = r
    r += 1
    ov_refs = []
    for role, days, rate in oversight:
        ws.cell(row=r, column=1, value=role)
        ws.cell(row=r, column=3, value="oversight")
        ws.cell(row=r, column=4, value="Architecture & security-model review, quality-gate sign-off.")
        ws.cell(row=r, column=5, value=days)
        ws.cell(row=r, column=6, value=f"=E{r}*{rate}").number_format = MONEY
        style_row(ws, r, 6)
        ov_refs.append(f"F{r}")
        r += 1
    ws.cell(row=r, column=1, value="WAVE TOTAL").font = Font(name="Arial", bold=True, size=11, color=NAVY)
    total_formula = f"=F{coe_sub}" + ("+" + "+".join(ov_refs) if ov_refs else "")
    ws.cell(row=r, column=6, value=total_formula).number_format = MONEY
    ws.cell(row=r, column=6).font = Font(name="Arial", bold=True, size=11, color=NAVY)
    style_row(ws, r, 6, fill=FILL_G)
    ws.cell(row=r, column=1).font = Font(name="Arial", bold=True, size=11, color=NAVY)
    GRAND.append((title, f"'{ws.title}'!F{r}"))
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 10
    ws.column_dimensions["C"].width = 10
    ws.column_dimensions["D"].width = 95
    ws.column_dimensions["E"].width = 8
    ws.column_dimensions["F"].width = 14

# ============================================================ RECONCILIATION
rec = wb.create_sheet("Reconciliation", 1)
rec["A1"] = "Reconciliation vs negotiated pricing (offer table)"
rec["A1"].font = TITLE
r = 3
for j, h in enumerate(["Component", "This plan (USD)", "Offer table (USD)", "Days (CoE + oversight)"], 1):
    rec.cell(row=r, column=j, value=h)
style_row(rec, r, 4, header=True)
r += 1
TARGETS = [("Engagement initial", "≈ 10k", "50 + 3"), ("Wave 2", "≈ 26k", "150 + 5"),
           ("Wave 3", "≈ 14k", "82 + 2"), ("Employee Services module", "≈ 10k", "67 + 0")]
refs = [g[1] for g in GRAND]
for i, ((label, target, days), ref) in enumerate(zip(TARGETS, refs)):
    rec.cell(row=r, column=1, value=label).font = BOLD
    rec.cell(row=r, column=2, value=f"={ref}").number_format = MONEY
    rec.cell(row=r, column=3, value=target)
    rec.cell(row=r, column=4, value=days)
    style_row(rec, r, 4, fill=FILL_P if i % 2 else None)
    rec.cell(row=r, column=1).font = BOLD
    r += 1
rec.cell(row=r, column=1, value="TOTAL BUILD — Option 1 (IT)").font = BOLD
rec.cell(row=r, column=2, value="=" + "+".join(refs[:3])).number_format = MONEY
rec.cell(row=r, column=3, value="≈ 50k")
style_row(rec, r, 4, fill=FILL_A)
rec.cell(row=r, column=1).font = BOLD
r += 1
rec.cell(row=r, column=1, value="TOTAL BUILD — Option 2 (IT + Employee Services)").font = BOLD
rec.cell(row=r, column=2, value="=" + "+".join(refs)).number_format = MONEY
rec.cell(row=r, column=3, value="≈ 60k")
style_row(rec, r, 4, fill=FILL_G)
rec.cell(row=r, column=1).font = BOLD
rec.column_dimensions["A"].width = 46
rec.column_dimensions["B"].width = 16
rec.column_dimensions["C"].width = 16
rec.column_dimensions["D"].width = 22

wb.save(OUT)

# ---- expected values + UC coverage check
import re as _re
covered = set()
for _, lines, _, _ in WAVES:
    for item, *_rest in lines:
        m = _re.match(r"UC(\d+)", item)
        if m:
            covered.add(int(m.group(1)))
missing = sorted(set(range(1, 40)) - covered)
print("UCs covered:", len(covered), "· missing:", missing or "none")
for (title, lines, budget, oversight) in WAVES:
    coe = sum(l[4] for l in lines) * COE_RATE
    ov = sum(d * rate for _, d, rate in oversight)
    print(f"{title[:58]:58s} CoE {sum(l[4] for l in lines):5.1f}d  ${coe + ov:>8,.0f}")
opt1 = sum(sum(l[4] for l in w[1]) * COE_RATE + sum(d * r_ for _, d, r_ in w[3]) for w in WAVES[:3])
opt2 = opt1 + sum(l[4] for l in WAVES[3][1]) * COE_RATE
print(f"OPTION 1 TOTAL ${opt1:,.0f} · OPTION 2 TOTAL ${opt2:,.0f}")
print("saved:", OUT)
