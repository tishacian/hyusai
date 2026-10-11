# -*- coding: utf-8 -*-
"""Build Annex B v3 — clarity- and procurement-QA aligned RFI pricing schedule.

v3 resolves the QA findings against v2:
  * first-of-type agents are a subset of the 400-agent envelope;
  * the volume discount is calculated from the stated incremental rule;
  * first-of-type premium, reuse status and connector treatment are explicit;
  * RFI reuse targets are a proposed measurement method pending PIH clarification;
  * all commercial and technical jargon is defined once;
  * Platform Subscription rights, trigger and AgentOps transferability are clear;
  * knowledge is source-type scoped; inference optimisation is a target, not a guarantee;
  * T&M use cases are separated from all-inclusive catalogue delivery;
  * capacity units are described as planning, never pricing, units.

The workbook deliberately does NOT disclose internal JH or margin assumptions.
"""
import os

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

HERE = os.path.dirname(os.path.abspath(__file__))
PIH = os.path.join(os.path.dirname(HERE), "pih")
SRC = os.path.join(PIH, "RFI-PIH-AI-Factory-Annex-B-Pricing-Schedule-v2.xlsx")
OUT = os.path.join(PIH, "RFI-PIH-AI-Factory-Annex-B-Pricing-Schedule-v3.xlsx")

NAVY = "0B2545"; PANEL = "F3F5F8"; AMBER = "FFF8E7"; GREEN = "E2F2EC"
H_FONT = Font(name="Arial", bold=True, color="FFFFFF", size=10)
B_FONT = Font(name="Arial", size=10)
BOLD = Font(name="Arial", bold=True, size=10)
TITLE = Font(name="Arial", bold=True, size=14, color=NAVY)
NOTE = Font(name="Arial", italic=True, size=9, color="596371")
FILL_H = PatternFill("solid", fgColor=NAVY)
FILL_P = PatternFill("solid", fgColor=PANEL)
FILL_A = PatternFill("solid", fgColor=AMBER)
FILL_G = PatternFill("solid", fgColor=GREEN)
THIN = Border(*[Side(style="thin", color="D7DCE3")] * 4)
MONEY = "#,##0"


def clear(ws):
    # The v2 workbook has merged explanatory rows. Deleting rows alone leaves
    # merge ranges behind, which would turn new formula cells into MergedCell
    # placeholders on their reused coordinates.
    for merged_range in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(merged_range))
    ws.delete_rows(1, ws.max_row)


def style_row(ws, row, ncols, header=False, fill=None):
    for col in range(1, ncols + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = H_FONT if header else B_FONT
        cell.border = THIN
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        if header:
            cell.fill = FILL_H
        elif fill:
            cell.fill = fill


def write_two_col(ws, title, subtitle, rows, widths=(24, 112)):
    clear(ws)
    ws["A1"] = title
    ws["A1"].font = TITLE
    ws["A2"] = subtitle
    ws["A2"].font = NOTE
    row = 4
    for idx, (label, text) in enumerate(rows):
        ws.cell(row=row, column=1, value=label).font = BOLD
        ws.cell(row=row, column=2, value=text)
        style_row(ws, row, 2, fill=FILL_P if idx % 2 else None)
        ws.cell(row=row, column=1).font = BOLD
        row += 1
    ws.column_dimensions["A"].width = widths[0]
    ws.column_dimensions["B"].width = widths[1]


wb = load_workbook(SRC)

# ---------------------------------------------------------------- Reading Guide
rg = wb["Reading Guide"]
write_two_col(
    rg,
    "Annex B — Pricing Schedule (v3, indicative, RFI stage)",
    "PIH AI Factory Programme — Datategy response. USD, exclusive of taxes. Figures are indicative "
    "at RFI stage; firm pricing follows PIH clarifications, approved design cards and the confirmed "
    "agent mix at proposal / shortlist stage.",
    [
        ("RFI pricing format",
         "The RFI requires an all-inclusive unit price per agent by Simple / Medium / Complex tier, "
         "T&M day rates, an AgentOps monthly fee per live agent and transparent inference treatment. "
         "This annex maps directly to that format."),
        ("Pricing principle",
         "No per-user licence and no Datategy per-execution consumption charge. SaaS inference is "
         "passed through at cloud tariff without markup; sovereign inference runs on PIH infrastructure."),
        ("Catalogue build unit",
         "The catalogue price applies to a reuse instance: a new agent configured from patterns, "
         "skills and connectors already delivered and validated. Its business rules, rights, "
         "parameters and acceptance criteria are adapted; its technical mechanism is not rebuilt from zero."),
        ("First-of-type",
         "The first agent creating or materially extending a pattern, skill or connector. It is a "
         "subset of the programme agent volume and carries a separately identified premium."),
        ("Runtime during programme",
         "Agentium runtime is included for programme agents while an active contracted factory plan "
         "is in force. Post-programme rights and the subscription trigger are defined in Platform Rights."),
        ("Knowledge capacity",
         "Knowledge is shared memory serving many agents, scoped by source type and volume — never "
         "priced per agent. Source inventory determines allowance and packs at proposal stage."),
        ("Delivery model",
         "Remote-first delivery through Datategy's AI & Data Center of Excellence. Targeted Doha "
         "presence is limited to jointly agreed mobilisation, security/UAT and critical go-live gates."),
        ("Contents",
         "Definitions · Build Unit Prices · T&M Rate Card · AgentOps & Recurring · Illustrative "
         "Envelope · Platform Rights · Capacity & Commercial Gates."),
        ("Validity", "90 days from submission. Rates assume a ≥3-month engagement commitment."),
    ],
)

# ------------------------------------------------------------------ Definitions
if "Definitions" in wb.sheetnames:
    del wb["Definitions"]
defs = wb.create_sheet("Definitions", 1)
write_two_col(
    defs,
    "Definitions — pricing and delivery terms",
    "Terms used once and consistently across Annex B. These definitions are commercial-operational; "
    "contract language is finalised at proposal / contract stage.",
    [
        ("Agent", "A production automation for a defined business objective, with governed tools, tests, "
                  "security controls and execution evidence."),
        ("Pattern", "A reusable operating model, for example request → verification → approval → action → audit."),
        ("Skill", "A typed reusable capability called by an agent, such as retrieval, SAP posting, "
                  "ticket creation, entitlement verification or notification."),
        ("Connector", "A standardised integration with a target system, including authentication, "
                      "error handling, logging and permission validation."),
        ("Reuse instance", "A new agent configured from delivered and validated patterns, skills and "
                           "connectors; rules and parameters change, not the technical mechanism."),
        ("First-of-type", "An agent creating or materially extending a reusable pattern, skill or connector. "
                           "It carries an explicit premium defined in the design card."),
        ("Design card", "The approved build record defining tier, systems, first-of-type/reuse status, "
                         "security class, success metrics, acceptance evidence, delivery slot and fixed price."),
        ("Golden set", "A reference test set of expected outcomes and prohibited actions used for pre-go-live "
                       "validation and later regression testing."),
        ("AgentOps", "Operational monitoring, exception handling, quality/drift review and reporting for live agents."),
        ("Factory capacity unit", "A weighted delivery-planning unit used to schedule work by complexity. "
                                  "It is not a price unit and does not replace the S/M/C catalogue tiers."),
    ],
)

# ----------------------------------------------------------- Build Unit Prices
bu = wb["Build Unit Prices"]
clear(bu)
bu["A1"] = "Agent build — catalogue unit prices by complexity tier"
bu["A1"].font = TITLE
bu["A2"] = (
    "Catalogue price applies to a reuse instance. It includes detailed design (design card), authoring, "
    "mapping to delivered connectors, integration, unit/integration/UAT testing including golden-set "
    "creation, security validation, deployment and one knowledge-transfer session. A new or materially "
    "extended connector, skill or pattern is first-of-type and is separately identified before build."
)
bu["A2"].font = NOTE
headers = ["Tier", "Eligibility / objective classification", "RFI elapsed build time*", "Catalogue price — reuse instance", "First-of-type premium"]
for col, header in enumerate(headers, 1):
    bu.cell(row=4, column=col, value=header)
style_row(bu, 4, 5, header=True)
tiers = [
    ("Simple",
     "One system; delivered pattern and skill; deterministic or single-step generative; read or reversible "
     "write; maximum one standard approval.",
     "Up to 4 weeks", "≈ $3,500 – 5,000", "+50%"),
    ("Medium",
     "Two to three systems; delivered pattern adapted for business rules or exception handling; standard "
     "approval flow; no new material connector or skill.",
     "Up to 8 weeks", "≈ $9,000 – 13,000", "+50–75%"),
    ("Complex",
     "New or materially extended pattern/skill/connector; three or more systems; privileged write; "
     "regulatory/high-impact controls; multi-agent coordination or reinforced parallel-run.",
     "Up to 12 weeks", "≈ $20,000 – 30,000", "+75–100%"),
]
row = 5
for idx, values in enumerate(tiers):
    for col, value in enumerate(values, 1):
        bu.cell(row=row, column=col, value=value)
    style_row(bu, row, 5, fill=FILL_P if idx % 2 else None)
    row += 1
notes = [
    ("* Build time", "Elapsed calendar time, assuming PIH timely access to environments, SMEs, data and "
                    "approval/UAT participants. It is not a representation of internal Datategy effort."),
    ("First-of-type formula",
     "Premium is applied to the catalogue price selected in the approved design card, before any volume "
     "reduction. It is non-degressive and applies only to the explicitly identified first-of-type scope."),
    ("Price lock",
     "PIH and Datategy approve tier, systems, first-of-type/reuse status, acceptance criteria and price "
     "in the design card before build. The price is then fixed for that agent."),
    ("Volume reduction",
     "−10% applies only to incremental accepted reuse instances numbered 101–250; −20% applies only "
     "to incremental accepted reuse instances numbered 251+. No retroactive rebate. First-of-type "
     "agents are excluded from the count and receive no volume reduction."),
    ("RFI reuse targets",
     "Datategy proposes a 30% pattern-reuse / 15% component-standardisation measurement method, "
     "subject to PIH clarification of baseline, measurement and contractual status."),
]
for idx, (label, text) in enumerate(notes):
    bu.cell(row=row, column=1, value=label).font = BOLD
    bu.cell(row=row, column=2, value=text)
    bu.merge_cells(start_row=row, start_column=2, end_row=row, end_column=5)
    style_row(bu, row, 5, fill=FILL_G if label == "Volume reduction" else (FILL_P if idx % 2 else None))
    bu.cell(row=row, column=1).font = BOLD
    row += 1
bu.column_dimensions["A"].width = 22
bu.column_dimensions["B"].width = 65
bu.column_dimensions["C"].width = 18
bu.column_dimensions["D"].width = 27
bu.column_dimensions["E"].width = 20

# --------------------------------------------------------------- T&M Rate Card
tm = wb["T&M Rate Card"]
clear(tm)
tm["A1"] = "Staff augmentation — day rates (USD, excl. taxes)"
tm["A1"].font = TITLE
tm["A2"] = (
    "Remote-first delivery: nearshore build capacity from Datategy's AI & Data Center of Excellence, "
    "with senior architecture and QA support from France. Targeted Doha presence is limited to jointly "
    "agreed mobilisation, security/UAT and critical go-live gates. T&M is used for pilot staff "
    "augmentation, discovery, change requests or scope not eligible for catalogue unit pricing; it is "
    "not added to an all-inclusive unit-priced agent. Travel & accommodation at cost."
)
tm["A2"].font = NOTE
for col, header in enumerate(["Role", "Location / model", "Day rate (USD)"], 1):
    tm.cell(row=4, column=col, value=header)
style_row(tm, 4, 3, header=True)
rates = [
    ("AI / Data Engineer", "Nearshore CoE", 149),
    ("Developer", "Nearshore CoE", 149),
    ("QA / Evaluation Engineer", "Nearshore CoE", 149),
    ("CoE Director / Delivery leadership", "Nearshore CoE (part-time on programme)", 349),
    ("Solution Architect / Expert", "France · hybrid, targeted on-site only when agreed", 880),
]
row = 5
for idx, values in enumerate(rates):
    for col, value in enumerate(values, 1):
        tm.cell(row=row, column=col, value=value)
    tm.cell(row=row, column=3).number_format = MONEY
    style_row(tm, row, 3, fill=FILL_P if idx % 2 else None)
    row += 1
tm.column_dimensions["A"].width = 38
tm.column_dimensions["B"].width = 52
tm.column_dimensions["C"].width = 16

# ------------------------------------------------------ AgentOps & Recurring
ao = wb["AgentOps & Recurring"]
clear(ao)
ao["A1"] = "AgentOps, runtime and recurring components (indicative)"
ao["A1"].font = TITLE
for col, header in enumerate(["Component", "Basis", "Indicative price", "Scope / clarification"], 1):
    ao.cell(row=3, column=col, value=header)
style_row(ao, 3, 4, header=True)
recurring = [
    ("AgentOps — Low-impact agents", "per accepted live agent / month", "$50",
     "L1 monitoring, exception management, prompt-regression checks and reporting. Operational service "
     "may transfer to PIH or a third party under the agreed operating model."),
    ("AgentOps — Medium-impact agents", "per accepted live agent / month", "$60",
     "Low-impact scope plus approval-flow supervision and monthly quality review."),
    ("AgentOps — High-impact agents", "per accepted live agent / month", "$70",
     "Medium-impact scope plus reinforced drift watch and quarterly adversarial/red-team regression."),
    ("Agentium runtime — active programme", "included", "$0",
     "Included for programme agents while an active contracted factory capacity plan is in force. "
     "No per-user fee and no Datategy per-execution consumption charge."),
    ("Platform Subscription — post-programme", "annual / capacity tier", "proposal stage",
     "Covers create/modify rights, updates, security patches, connector/model compatibility, golden-set "
     "regression and N3 support. Commercial tier and price are confirmed at proposal/shortlist."),
    ("Knowledge capacity — source inventory", "per source type / volume", "proposal stage",
     "Inventory distinguishes logical knowledge bases, native digital pages, scanned/OCR pages, languages, "
     "metadata/cleaning effort and storage. Shared memory is never priced per agent."),
    ("Knowledge ingestion / capacity packs", "per defined pack", "proposal stage",
     "Additional source onboarding, OCR, cleaning/metadata, language coverage, storage or knowledge-base "
     "capacity is priced after source inventory; no unbounded page commitment at RFI stage."),
    ("Inference — SaaS endpoints", "pass-through", "cloud tariff",
     "No markup; token usage and cost are metered per agent and exportable to Finance."),
    ("Inference — sovereign serving", "PIH infrastructure envelope", "on quote",
     "Open-weight models on PIH GPU capacity in Azure Qatar region, private cloud or on-premise."),
    ("Inference optimisation", "joint KPI", "target −30–50% / 12 months",
     "Target measured against a jointly agreed baseline; not a guaranteed reduction. Caching, "
     "right-sized routing and prompt optimisation reviewed quarterly."),
]
row = 4
for idx, values in enumerate(recurring):
    for col, value in enumerate(values, 1):
        ao.cell(row=row, column=col, value=value)
    style_row(ao, row, 4, fill=FILL_P if idx % 2 else None)
    row += 1
ao.column_dimensions["A"].width = 40
ao.column_dimensions["B"].width = 30
ao.column_dimensions["C"].width = 22
ao.column_dimensions["D"].width = 76

# -------------------------------------------------------- Illustrative Envelope
il = wb["Illustrative Envelope"]
clear(il)
il["A1"] = "Illustrative programme envelope — 400 agents (indicative, like-for-like comparison)"
il["A1"].font = TITLE
il["A2"] = (
    "The 400-agent mix below includes both reuse and first-of-type agents. Catalogue base price is "
    "shown for every agent; first-of-type premiums are applied to a stated subset of the same 400 agents. "
    "The volume reduction is calculated only on the remaining accepted reuse instances. Amber cells are editable assumptions."
)
il["A2"].font = NOTE
for col, header in enumerate(["Tier", "Total agents incl. first-of-type", "Catalogue base price", "Base subtotal"], 1):
    il.cell(row=4, column=col, value=header)
style_row(il, 4, 4, header=True)
mix = [("Simple", 180, 4200), ("Medium", 160, 10500), ("Complex", 60, 24000)]
row = 5
for idx, values in enumerate(mix):
    for col, value in enumerate(values, 1):
        il.cell(row=row, column=col, value=value)
    il.cell(row=row, column=3).number_format = MONEY
    il.cell(row=row, column=4, value=f"=B{row}*C{row}").number_format = MONEY
    style_row(il, row, 4, fill=FILL_P if idx % 2 else None)
    il.cell(row=row, column=2).fill = FILL_A
    il.cell(row=row, column=3).fill = FILL_A
    row += 1
il.cell(row=row, column=1, value="Base unit-price subtotal — all 400 agents").font = BOLD
il.cell(row=row, column=4, value="=SUM(D5:D7)").number_format = MONEY
style_row(il, row, 4, fill=FILL_P)
base_total = row
row += 2

for col, header in enumerate(["First-of-type subset (included above)", "# agents (editable)", "Premium rate (editable)", "Premium subtotal"], 1):
    il.cell(row=row, column=col, value=header)
style_row(il, row, 4, header=True)
row += 1
first_rows = [
    ("Simple first-of-type", 20, 0.50, "=B{r}*$C$5*C{r}"),
    ("Medium first-of-type", 15, 0.60, "=B{r}*$C$6*C{r}"),
    ("Complex first-of-type", 5, 0.80, "=B{r}*$C$7*C{r}"),
]
first_start = row
for idx, (label, count, premium, formula) in enumerate(first_rows):
    il.cell(row=row, column=1, value=label)
    il.cell(row=row, column=2, value=count)
    il.cell(row=row, column=3, value=premium).number_format = "0%"
    il.cell(row=row, column=4, value=formula.format(r=row)).number_format = MONEY
    style_row(il, row, 4, fill=FILL_P if idx % 2 else None)
    il.cell(row=row, column=2).fill = FILL_A
    il.cell(row=row, column=3).fill = FILL_A
    row += 1
il.cell(row=row, column=1, value="First-of-type premium subtotal").font = BOLD
il.cell(row=row, column=2, value=f"=SUM(B{first_start}:B{row - 1})")
il.cell(row=row, column=4, value=f"=SUM(D{first_start}:D{row - 1})").number_format = MONEY
style_row(il, row, 4, fill=FILL_P)
first_total = row
row += 2

for col, header in enumerate(["Volume reduction — accepted reuse instances only", "Formula / input", "Result", "Amount"], 1):
    il.cell(row=row, column=col, value=header)
style_row(il, row, 4, header=True)
row += 1
il.cell(row=row, column=1, value="Eligible reuse-instance count")
il.cell(row=row, column=2, value=f"=SUM(B5:B7)-B{first_total}")
il.cell(row=row, column=3, value="All 400 agents less first-of-type subset")
style_row(il, row, 4)
reuse_count = row
row += 1
il.cell(row=row, column=1, value="Units 101–250 — 10%")
il.cell(row=row, column=2, value=f"=MAX(0,MIN(B{reuse_count},250)-100)")
il.cell(row=row, column=3, value="=B{r}*10%".format(r=row))
style_row(il, row, 4)
band_10 = row
row += 1
il.cell(row=row, column=1, value="Units 251+ — 20%")
il.cell(row=row, column=2, value=f"=MAX(0,B{reuse_count}-250)")
il.cell(row=row, column=3, value="=B{r}*20%".format(r=row))
style_row(il, row, 4)
band_20 = row
row += 1
il.cell(row=row, column=1, value="Illustrative effective reuse reduction")
il.cell(row=row, column=2, value=f"=(C{band_10}+C{band_20})/B{reuse_count}")
il.cell(row=row, column=2).number_format = "0.0%"
il.cell(row=row, column=3, value="Pro-rata allocation across reuse base-price subtotal")
style_row(il, row, 4, fill=FILL_P)
effective_reduction = row
row += 1
il.cell(row=row, column=1, value="Reuse base-price subtotal")
il.cell(row=row, column=2, value=f"=D{base_total}-SUMPRODUCT(B{first_start}:B{first_total-1},$C$5:$C$7)")
il.cell(row=row, column=2).number_format = MONEY
il.cell(row=row, column=3, value="Base price of agents eligible for volume reduction")
style_row(il, row, 4)
reuse_base = row
row += 1
il.cell(row=row, column=1, value="Volume reduction amount")
il.cell(row=row, column=4, value=f"=-B{reuse_base}*B{effective_reduction}").number_format = MONEY
style_row(il, row, 4)
volume_discount = row
row += 1

il.cell(row=row, column=1, value="INDICATIVE BUILD ENVELOPE").font = Font(name="Arial", bold=True, size=11, color=NAVY)
il.cell(row=row, column=4, value=f"=D{base_total}+D{first_total}+D{volume_discount}").number_format = MONEY
il.cell(row=row, column=4).font = Font(name="Arial", bold=True, size=11, color=NAVY)
style_row(il, row, 4, fill=FILL_G)
row += 2
il.cell(row=row, column=1, value="AgentOps — illustrative steady state")
il.cell(row=row, column=2, value="400 agents × $58/month blended")
il.cell(row=row, column=4, value="=400*58*12").number_format = MONEY
style_row(il, row, 4)
row += 1
il.cell(row=row, column=1, value="Scope note").font = BOLD
il.cell(row=row, column=2, value=(
    "The first-of-type subset is included in the 400-agent total. The pro-rata reduction is an "
    "illustrative presentation of the contractual incremental 100/250 rule; actual reduction follows "
    "the order of accepted reuse instances. Knowledge packs, PIH infrastructure, travel and the "
    "post-programme Platform Subscription are excluded and scoped separately."
)).font = NOTE
il.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
style_row(il, row, 4, fill=FILL_P)
il.column_dimensions["A"].width = 54
il.column_dimensions["B"].width = 30
il.column_dimensions["C"].width = 30
il.column_dimensions["D"].width = 24

# --------------------------------------------------------------- Platform Rights
pr = wb["Platform Rights"]
write_two_col(
    pr,
    "Platform rights during and after the factory programme",
    "Commercial operating model for portability and product maintenance. Final legal terms are agreed "
    "in the proposal/contract; this sheet defines the intended commercial boundary.",
    [
        ("Run delivered versions",
         "PIH receives a perpetual, non-exclusive right to execute accepted delivered agent versions on "
         "PIH-controlled infrastructure. This does not include future product releases or a source-code transfer."),
        ("Export / portability",
         "Delivered flow configurations, design cards, evaluation evidence and documented connector "
         "mappings are exportable. PIH can retain the operating record of delivered agents."),
        ("Build / material modification",
         "Included while a contracted factory plan is active. After programme, continued create/modify "
         "rights require an active Platform Subscription."),
        ("Maintain",
         "Updates, security patches, connector/model compatibility, golden-set regression, product roadmap "
         "and N3 support require an active Platform Subscription after programme."),
        ("AgentOps",
         "Optional operational service. PIH may operate agents itself or appoint another operator; this "
         "does not transfer Agentium product IP or subscription-maintenance rights."),
        ("Subscription trigger",
         "The subscription starts on the earlier of: final acceptance of the contracted factory programme; "
         "or 90 days after the last accepted delivery if no successor contracted capacity plan is active. "
         "Capacity tier and price are confirmed at proposal/shortlist stage."),
    ],
    widths=(30, 110),
)

# ---------------------------------------------------- Capacity & Commercial Gates
cg = wb["Capacity & Commercial Gates"]
clear(cg)
cg["A1"] = "Factory capacity, acceptance & commercial gates"
cg["A1"].font = TITLE
cg["A2"] = (
    "Capacity is planned by weighted complexity, never by an undifferentiated number of agents. "
    "Factory capacity units are planning units only: they do not determine the S/M/C catalogue price."
)
cg["A2"].font = NOTE
for col, header in enumerate(["Topic", "RFI-stage position", "Proposal / contract gate"], 1):
    cg.cell(row=4, column=col, value=header)
style_row(cg, 4, 3, header=True)
gates = [
    ("Factory capacity unit",
     "Simple reuse = 1 unit; Medium reuse = 2.5 units; Complex reuse = 7.5 units. First-of-type "
     "surcharge is planned separately.",
     "Monthly capacity is confirmed against PIH agent mix, named Datategy delivery resources and "
     "environment/API access."),
    ("Internal scale-up",
     "Datategy scales autonomously through internal recruitment and allocation of its AI & Data Center "
     "of Excellence capacity.",
     "Any capacity extension requires notice, named Datategy resources, PIH access and an agreed ramp-up plan."),
    ("Design-card gate",
     "Tier, systems, reuse/first-of-type status, security class, success metrics, acceptance evidence "
     "and delivery slot are approved before build.",
     "Catalogue price and first-of-type premium are fixed at design-card approval."),
    ("Acceptance",
     "An agent is counted live only after agreed UAT, security gate and production acceptance evidence.",
     "Volume reductions apply only to accepted reuse instances."),
    ("Pilot cash flow",
     "The 13-week pilot/staff-augmentation phase is invoiced monthly.",
     "Mobilisation payment and invoicing cadence are agreed before resources are reserved."),
    ("Industrial cash flow",
     "Build proceeds in planned waves with factory-ledger reporting.",
     "Mobilisation/capacity reservation plus short monthly or wave milestones; no deferred single milestone at 200 agents."),
    ("Travel",
     "Remote-first delivery. Doha attendance only for jointly agreed mobilisation, security/UAT or critical go-live gates.",
     "Travel/accommodation at cost; named attendance, purpose and dates agreed before travel."),
]
row = 5
for idx, values in enumerate(gates):
    for col, value in enumerate(values, 1):
        cg.cell(row=row, column=col, value=value)
    style_row(cg, row, 3, fill=FILL_P if idx % 2 else None)
    row += 1
cg.column_dimensions["A"].width = 28
cg.column_dimensions["B"].width = 72
cg.column_dimensions["C"].width = 72

wb.save(OUT)
print("saved:", OUT)
