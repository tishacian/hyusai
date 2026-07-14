# -*- coding: utf-8 -*-
"""PIH AI Factory RFI — Annexes B (pricing schedule, xlsx) and C (reference case studies, docx).

Coherent with the main response draft (§3 commercial architecture): unit prices per tier,
runtime included, degressivity, T&M CoE rates, AgentOps per-agent, inference pass-through.
All figures indicative (RFI stage). OEM/white-label absent.

Outputs:
  docs/pih/RFI-PIH-AI-Factory-Annex-B-Pricing-Schedule.xlsx
  docs/pih/RFI-PIH-AI-Factory-Annex-C-Reference-Case-Studies.docx
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PIH = os.path.join(os.path.dirname(HERE), "pih")
LOGO = os.path.join(HERE, "assets", "logo_datategy.png")
OUT_B = os.path.join(PIH, "RFI-PIH-AI-Factory-Annex-B-Pricing-Schedule.xlsx")
OUT_C = os.path.join(PIH, "RFI-PIH-AI-Factory-Annex-C-Reference-Case-Studies.docx")

# ================================================================ ANNEX B — XLSX
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

NAVY_X = "0B2545"; PANEL_X = "F3F5F8"; AMBER_X = "FFF8E7"; GREEN_X = "E2F2EC"
H_FONT = Font(name="Arial", bold=True, color="FFFFFF", size=10)
B_FONT = Font(name="Arial", size=10)
BOLD = Font(name="Arial", bold=True, size=10)
TITLE = Font(name="Arial", bold=True, size=14, color=NAVY_X)
NOTE = Font(name="Arial", italic=True, size=9, color="596371")
FILL_H = PatternFill("solid", fgColor=NAVY_X)
FILL_P = PatternFill("solid", fgColor=PANEL_X)
FILL_A = PatternFill("solid", fgColor=AMBER_X)
FILL_G = PatternFill("solid", fgColor=GREEN_X)
THIN = Border(*[Side(style="thin", color="D7DCE3")] * 4)
MONEY = "#,##0"


def srow(ws, row, ncols, header=False, fill=None):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = H_FONT if header else B_FONT
        cell.border = THIN
        if header:
            cell.fill = FILL_H
        elif fill:
            cell.fill = fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)


wb = openpyxl.Workbook()

# ---- Sheet 1: Reading guide
rg = wb.active; rg.title = "Reading Guide"
rg["A1"] = "Annex B — Pricing Schedule (indicative, RFI stage)"; rg["A1"].font = TITLE
rows = [
    ("Scope", "PIH AI Factory Programme — response of Datategy. All figures USD, exclusive of taxes, "
              "indicative at RFI stage; firm pricing at proposal stage once clarifications and agent "
              "mix are known."),
    ("Principle 1", "No per-user licence. No consumption tax on agent executions. The Agentium runtime "
                    "is included for programme agents — no separate platform fee while the factory runs."),
    ("Principle 2", "The build unit is the agent (front office), delivered from a factory of reusable "
                    "patterns, skills and connectors; unit cost falls as the factory matures."),
    ("Principle 3", "Knowledge capacity (Document Center) is shared memory serving all agents — priced "
                    "per knowledge base / document volume, never per agent."),
    ("Principle 4", "Full transparency: every run's token usage and cost metered per agent, exportable "
                    "to Finance; SaaS inference passed through at cloud tariff, no markup."),
    ("Contents", "Sheet 2 — Build unit prices · Sheet 3 — T&M rate card · Sheet 4 — AgentOps & "
                 "recurring · Sheet 5 — Illustrative programme envelope"),
    ("Validity", "90 days from submission. Rates assume a ≥3-month engagement commitment."),
]
r = 3
for k, v in rows:
    rg.cell(row=r, column=1, value=k).font = BOLD
    rg.cell(row=r, column=2, value=v).font = B_FONT
    srow(rg, r, 2, fill=FILL_P if r % 2 else None)
    r += 1
rg.column_dimensions["A"].width = 16; rg.column_dimensions["B"].width = 100

# ---- Sheet 2: Build unit prices
bu = wb.create_sheet("Build Unit Prices")
bu["A1"] = "Agent build — unit prices by complexity tier (factory execution)"; bu["A1"].font = TITLE
bu["A2"] = ("Unit price covers: detailed design (design card), flow authoring, connector mapping, "
            "integration, unit/integration/UAT testing incl. golden-set creation, security validation, "
            "deployment, one knowledge-transfer session. Per RFI tier definitions (factory build time).")
bu["A2"].font = NOTE
hdrs = ["Tier", "RFI definition", "Factory build time", "Unit price (2nd+ instance)", "First-of-type"]
for j, h in enumerate(hdrs, 1):
    bu.cell(row=4, column=j, value=h)
srow(bu, 4, 5, header=True)
tiers = [
    ("Simple", "Single agent type, single system, deterministic or single-step generative; pattern "
               "exists or close-match", "Up to 4 weeks", "≈ $3,500 – 5,000", "+50%"),
    ("Medium", "Multi-step, may span two systems or agent types; some reasoning / exception handling; "
               "pattern requires adaptation", "Up to 8 weeks", "≈ $8,000 – 13,000", "+50–75%"),
    ("Complex", "Multi-system, multi-agent, regulatory compliance, or full Autonomous tier; pattern "
                "new or significantly extended", "Up to 12 weeks", "≈ $18,000 – 30,000", "+75–100%"),
]
r = 5
for row in tiers:
    for j, v in enumerate(row, 1):
        bu.cell(row=r, column=j, value=v)
    srow(bu, r, 5, fill=FILL_P if r % 2 else None)
    r += 1
r += 1
bu.cell(row=r, column=1, value="Volume degressivity").font = BOLD
bu.cell(row=r, column=2, value="−10% on all unit prices beyond 100 live agents · −20% beyond 250 live "
                               "agents — the factory effect passed back to PIH.").font = B_FONT
srow(bu, r, 2, fill=FILL_G)
r += 1
bu.cell(row=r, column=1, value="Reuse commitment").font = BOLD
bu.cell(row=r, column=2, value="30% (pattern reuse) / 15% (component standardisation) cost-reduction "
                               "targets accepted, measured against first-of-type cost per pattern, "
                               "reported monthly from the factory ledger.").font = B_FONT
srow(bu, r, 2)
bu.column_dimensions["A"].width = 14
bu.column_dimensions["B"].width = 52
bu.column_dimensions["C"].width = 16
bu.column_dimensions["D"].width = 22
bu.column_dimensions["E"].width = 14

# ---- Sheet 3: T&M rate card
tm = wb.create_sheet("T&M Rate Card")
tm["A1"] = "Staff augmentation — day rates (USD, excl. taxes)"; tm["A1"].font = TITLE
tm["A2"] = ("Delivery model: hybrid — nearshore build capacity from Datategy's AI & Data Center of "
            "Excellence, senior architecture and QA from France, on-site presence in Doha for the "
            "pilot and lead roles. Travel & accommodation at cost. Valid for a ≥3-month commitment.")
tm["A2"].font = NOTE
for j, h in enumerate(["Role", "Location / model", "Day rate (USD)"], 1):
    tm.cell(row=4, column=j, value=h)
srow(tm, 4, 3, header=True)
rates = [
    ("AI / Data Engineer", "Nearshore CoE", 149),
    ("Developer", "Nearshore CoE", 149),
    ("QA / Evaluation Engineer", "Nearshore CoE", 149),
    ("CoE Director / Delivery leadership", "Nearshore CoE (part-time on programme)", 349),
    ("Solution Architect / Expert", "France · hybrid, on-site as required", 880),
]
r = 5
for role, loc, rate in rates:
    tm.cell(row=r, column=1, value=role)
    tm.cell(row=r, column=2, value=loc)
    tm.cell(row=r, column=3, value=rate).number_format = MONEY
    srow(tm, r, 3, fill=FILL_P if r % 2 else None)
    r += 1
tm.column_dimensions["A"].width = 36; tm.column_dimensions["B"].width = 38; tm.column_dimensions["C"].width = 16

# ---- Sheet 4: AgentOps & recurring
ao = wb.create_sheet("AgentOps & Recurring")
ao["A1"] = "AgentOps managed service & recurring components (indicative)"; ao["A1"].font = TITLE
for j, h in enumerate(["Component", "Basis", "Indicative price", "Notes"], 1):
    ao.cell(row=3, column=j, value=h)
srow(ao, 3, 4, header=True)
recs = [
    ("AgentOps — Low-impact agents", "per agent / month", "$50",
     "L1 monitoring, exception management, prompt regression, reporting"),
    ("AgentOps — Medium-impact agents", "per agent / month", "$60",
     "As above + approval-flow supervision, monthly quality review"),
    ("AgentOps — High-impact agents", "per agent / month", "$70",
     "As above + reinforced drift watch, quarterly red-team regression"),
    ("Agentium runtime (programme agents)", "included", "$0",
     "No separate platform fee while the factory runs — included in build unit prices"),
    ("Knowledge capacity (Document Center)", "per knowledge base / volume", "allowance + packs",
     "Shared memory serving all agents; KB packs & volume overage at catalogue rates; never per agent"),
    ("Inference — SaaS endpoints", "pass-through", "at cloud tariff",
     "No markup; per-agent token telemetry exportable to Finance"),
    ("Inference — sovereign serving", "infrastructure envelope", "on quote",
     "Open-weight models on PIH GPU (Azure Qatar region, private cloud or on-prem)"),
    ("Inference optimisation trajectory", "jointly-tracked KPI", "−30–50% / 12 months",
     "Caching, right-sized routing, prompt optimisation; quarterly reviews"),
]
r = 4
for row in recs:
    for j, v in enumerate(row, 1):
        ao.cell(row=r, column=j, value=v)
    srow(ao, r, 4, fill=FILL_P if r % 2 else None)
    r += 1
ao.column_dimensions["A"].width = 34; ao.column_dimensions["B"].width = 22
ao.column_dimensions["C"].width = 18; ao.column_dimensions["D"].width = 62

# ---- Sheet 5: Illustrative envelope (formula-driven)
il = wb.create_sheet("Illustrative Envelope")
il["A1"] = "Illustrative programme envelope — ~400 agents (indicative, for like-for-like comparison)"
il["A1"].font = TITLE
il["A2"] = ("Purely illustrative: assumes the agent mix below, factory-execution prices (first-of-type "
            "premiums excluded), before volume degressivity. Editable cells in amber.")
il["A2"].font = NOTE
for j, h in enumerate(["Tier", "# agents (editable)", "Unit price used (editable)", "Subtotal"], 1):
    il.cell(row=4, column=j, value=h)
srow(il, 4, 4, header=True)
mix = [("Simple", 180, 4200), ("Medium", 160, 10500), ("Complex", 60, 24000)]
r = 5
for tier, n, price in mix:
    il.cell(row=r, column=1, value=tier)
    c_n = il.cell(row=r, column=2, value=n); c_n.fill = FILL_A
    c_p = il.cell(row=r, column=3, value=price); c_p.number_format = MONEY; c_p.fill = FILL_A
    il.cell(row=r, column=4, value=f"=B{r}*C{r}").number_format = MONEY
    srow(il, r, 4)
    il.cell(row=r, column=2).fill = FILL_A; il.cell(row=r, column=3).fill = FILL_A
    r += 1
il.cell(row=r, column=1, value="Build subtotal (before degressivity)").font = BOLD
il.cell(row=r, column=4, value=f"=SUM(D5:D{r-1})").number_format = MONEY
srow(il, r, 4, fill=FILL_P); SUB = r; r += 1
il.cell(row=r, column=1, value="Volume degressivity (blended, editable)").font = BOLD
c_d = il.cell(row=r, column=2, value=0.12); c_d.number_format = "0%"; c_d.fill = FILL_A
il.cell(row=r, column=4, value=f"=-D{SUB}*B{r}").number_format = MONEY
srow(il, r, 4); il.cell(row=r, column=2).fill = FILL_A; DEG = r; r += 1
il.cell(row=r, column=1, value="INDICATIVE BUILD ENVELOPE").font = Font(name="Arial", bold=True, size=11, color=NAVY_X)
il.cell(row=r, column=4, value=f"=D{SUB}+D{DEG}").number_format = MONEY
il.cell(row=r, column=4).font = Font(name="Arial", bold=True, size=11, color=NAVY_X)
srow(il, r, 4, fill=FILL_G); r += 2
il.cell(row=r, column=1, value="AgentOps at steady state (400 agents, blended $58/mo)").font = BOLD
il.cell(row=r, column=4, value="=400*58*12").number_format = MONEY
srow(il, r, 4); r += 1
il.cell(row=r, column=1, value="Note").font = BOLD
il.cell(row=r, column=2, value="First-of-type premiums, knowledge-capacity packs and sovereign-serving "
                               "infrastructure are additional and depend on the clarified scope; see "
                               "sheets 2 and 4.").font = NOTE
il.column_dimensions["A"].width = 44
for col in ("B", "C", "D"):
    il.column_dimensions[col].width = 20

wb.save(OUT_B)
print("saved:", OUT_B)

# ================================================================ ANNEX C — DOCX
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


def C(h):
    return RGBColor.from_string(h)


NAVY = C("0B2545"); BLUE = C("2D6CDF"); GREEN = C("0E8F62"); AMBER = C("B45309")
PURPLE = C("6D28D9"); INK = C("151A23"); MUT = C("596371"); WHITE = C("FFFFFF")
BODY = "Arial"

doc = Document()
normal = doc.styles["Normal"]; normal.font.name = BODY; normal.font.size = Pt(10)
normal.font.color.rgb = INK; normal.paragraph_format.space_after = Pt(4)
normal.paragraph_format.line_spacing = 1.15


def _runfmt(run, size, color, bold=False, italic=False, mono=False):
    run.font.name = "Consolas" if mono else BODY
    run.font.size = Pt(size); run.font.bold = bold; run.font.italic = italic
    run.font.color.rgb = color


def _pagefield(run):
    r = run._r
    e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), "begin"); r.append(e)
    it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve"); it.text = "PAGE"; r.append(it)
    sep = OxmlElement("w:fldChar"); sep.set(qn("w:fldCharType"), "separate"); r.append(sep)
    t = OxmlElement("w:t"); t.text = "1"; r.append(t)
    end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end"); r.append(end)


sec = doc.sections[0]
sec.page_width = Cm(21.0); sec.page_height = Cm(29.7)
sec.top_margin = Cm(2.2); sec.bottom_margin = Cm(1.9); sec.left_margin = sec.right_margin = Cm(2.0)
sec.different_first_page_header_footer = True
hdr = sec.header; hdr.is_linked_to_previous = False
hp = hdr.paragraphs[0]
hp.add_run().add_picture(LOGO, height=Cm(0.55))
hp.add_run("    ")
_runfmt(hp.add_run("PIH AI Factory RFI — Annex C: Reference Case Studies"), 8, MUT, italic=True)
f = sec.footer; f.is_linked_to_previous = False
ft = f.add_table(rows=1, cols=2, width=Cm(17)); ft.allow_autofit = False
ft.cell(0, 0).width = Cm(12.5); ft.cell(0, 1).width = Cm(4.5)
_runfmt(ft.cell(0, 0).paragraphs[0].add_run("Datategy — Confidential — details & reference interviews under NDA"), 8, MUT)
rp = ft.cell(0, 1).paragraphs[0]; rp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
_runfmt(rp.add_run("Page "), 8, MUT); _pagefield(rp.add_run())
_e = f.paragraphs[0]; _e._element.getparent().remove(_e._element)

# cover-lite
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before = Pt(30)
p.add_run().add_picture(LOGO, width=Cm(4.0))
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before = Pt(18)
_runfmt(p.add_run("ANNEX C  ·  REFERENCE CASE STUDIES  ·  CONFIDENTIAL"), 10.5, BLUE, bold=True, mono=True)
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before = Pt(6)
_runfmt(p.add_run("PIH AI Factory Programme — Datategy RFI Response"), 18, NAVY, bold=True)
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
_runfmt(p.add_run("References are anonymised at RFI stage; client names, full metrics and reference "
                  "interviews are available under NDA at shortlist stage."), 10, MUT, italic=True)
doc.add_page_break()


def case(num, accent, domain, title, context, challenge, delivered, outcomes, relevance):
    h = doc.add_heading(f"Case study {num} — {title}", level=1)
    for r in h.runs:
        r.font.color.rgb = NAVY; r.font.name = BODY; r.font.size = Pt(13)
    p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(6)
    _runfmt(p.add_run(domain.upper()), 9, accent, bold=True, mono=True)
    for label, text in [("Context", context), ("Challenge", challenge),
                        ("What Datategy delivered", delivered)]:
        p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(4); p.paragraph_format.space_after = Pt(2)
        _runfmt(p.add_run(label + " — "), 10, NAVY, bold=True)
        _runfmt(p.add_run(text), 10, INK)
    p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(4); p.paragraph_format.space_after = Pt(2)
    _runfmt(p.add_run("Measured outcomes"), 10, NAVY, bold=True)
    for o in outcomes:
        b = doc.add_paragraph(); b.paragraph_format.left_indent = Cm(0.5)
        b.paragraph_format.space_before = Pt(1); b.paragraph_format.space_after = Pt(1)
        _runfmt(b.add_run("• " + o), 10, INK)
    p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(4)
    _runfmt(p.add_run("Relevance to the PIH AI Factory — "), 10, accent, bold=True)
    _runfmt(p.add_run(relevance), 10, INK)
    doc.add_page_break()


case(1, GREEN, "Gulf region · Smart city & mobility",
     "Real-time video analytics for a Gulf smart-parking operator",
     "A parking-guidance operator in the Gulf region running large camera estates across "
     "high-traffic facilities.",
     "Detect vehicles and occupancy in real time across heterogeneous camera feeds (including "
     "fisheye), at production scale and latency, with resilient streaming.",
     "An end-to-end video-analytics pipeline: streaming ingestion (Kafka), object-detection models "
     "served for real-time inference, occupancy logic and guidance outputs; performance tuning for "
     "sustained peak throughput; operational monitoring and auto-retraining as new data arrived.",
     ["Live vehicle and free/occupied-space detection in production across the estate",
      "Sustained real-time throughput at peak load after inference and pipeline optimisation",
      "Foundation reused as a shelf capability for video-analytics use cases"],
     "Demonstrates production AI operated in the Gulf, real-time constraints, and the "
     "pattern-to-shelf reuse economics at the heart of the factory model.")

case(2, BLUE, "Automotive financial services · IT operations (AIOps)",
     "Proactive prevention of critical IT incidents (AIOps)",
     "The financial-services arm of a major European automotive group; a complex, heterogeneous IT "
     "estate (mainframe stacks, ESB, web services) where a recurring timeout error blocked nightly "
     "batches and customer-facing financing operations.",
     "Move IT supervision from reactive to proactive: anticipate critical incidents from logs and "
     "metrics before they impact the business.",
     "An AIOps pipeline on our platform, deployed on the group's sovereign infrastructure: ingestion "
     "of millions of log/metric lines (Elastic stack sources, Spark processing), feature engineering "
     "on error and infrastructure signals, time-series forecasting of error peaks, and explainable "
     "alerts (feature contributions) delivered to the IT teams.",
     ["Error peaks anticipated with strong alignment to ground truth over the evaluation period",
      "Supervision shifted from reactive to proactive on the critical error class",
      "Explainability adopted by IT operators (clear feature-level rationale per alert)"],
     "Directly relevant to Operations & Technology agents: large-scale telemetry, prediction, "
     "explainability, and adoption by operations teams — the AgentOps mindset in production.")

case(3, PURPLE, "Automotive manufacturing · Multi-agent document pipelines",
     "Governed multi-agent translation & QA chains (SAE J2450)",
     "A major European automotive manufacturer producing large volumes of structured technical "
     "documentation (XML/DITA) in many languages.",
     "Industrialise translation without compromising quality — and prove the quality level "
     "reproducibly, at scale, against an automotive industry standard.",
     "A governed multi-agent pipeline: contextual retrieval over the manufacturer's own memory, "
     "translation agents with invariant protection, a QA stage with one agent per error class "
     "evaluated against the SAE J2450 standard, human-in-the-loop review of unresolved segments, "
     "corrections reinjected into the knowledge base, and deterministic delivery audits.",
     ["Quality equivalent or superior to human baselines on evaluated batches, normed (SAE J2450)",
      "Strong measured ROI on cost and turnaround versus the legacy process",
      "Per-segment evidence files (scores, decisions, review trail) at every delivery"],
     "The clearest demonstration of factory economics: agent-per-error-class patterns, golden-set "
     "gating, human oversight, and normed quality — the exact governance PIH requires for "
     "Assistive and Autonomous agents.")

case(4, AMBER, "Industrial engineering · Enterprise knowledge",
     "Grounded enterprise retrieval over a multi-million-chunk corpus",
     "A global industrial engineering group with massive multilingual technical documentation "
     "(manuals, procedures, engineering records) spread across formats and repositories.",
     "Give experts grounded, cited answers over an industrial-scale corpus — with the quality "
     "measured continuously, and the platform operated on the client's own infrastructure.",
     "Our knowledge platform deployed in the client runtime: multi-format ingestion with OCR, "
     "hybrid retrieval (dense + lexical) with fusion and re-ranking, grounded generation with "
     "per-claim citations, expert knowledge-capture loop feeding the corpus, and a golden-set "
     "evaluation harness run continuously against retrieval quality.",
     ["Production retrieval over a multi-million-chunk corpus with per-claim source citations",
      "Retrieval quality tracked on golden sets with measured improvements release over release",
      "Expert knowledge captured, reviewed and re-injected — the corpus improves with use"],
     "Proves the knowledge layer of the factory: shared, governed memory serving many agents, "
     "evaluation-first quality management, and full portability (client-operated runtime).")

p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(10)
_runfmt(p.add_run("Note on SAP financial agent delivery — "), 10, NAVY, bold=True)
_runfmt(p.add_run("per the RFI's reference criteria, a partner reference covering SAP financial "
                  "posting agent delivery will be presented at shortlist stage, together with the "
                  "named SAP module experts. ‹ TO COMPLETE — with delivery partner ›"), 10, INK, italic=True)

doc.save(OUT_C)
print("saved:", OUT_C)
