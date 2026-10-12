# -*- coding: utf-8 -*-
"""PIH AI Factory RFI — Response skeleton (DRAFT v1, EN).

From-scratch draft structured on the RFI's §9 response sections (15 sections, target
25–35 pages). High-weight sections pre-drafted; markers flag (a) items pending PIH's
answers to our 7-July clarification letter, (b) items to complete internally.
Commercial model per the corrected doctrine (platform capacity back-office, agents
front-office, CoE day rates); OEM/white-label deliberately NOT included (negotiation).
Competitive posture vs platform-vendor and big-SI rivals is embedded without naming them.

Output: docs/pih/RFI-PIH-AI-Factory-Response-DRAFT.docx
"""
import os
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(HERE, "assets", "logo_datategy.png")
OUT = os.path.join(os.path.dirname(HERE), "pih", "RFI-PIH-AI-Factory-Response-DRAFT.docx")


def C(h):
    return RGBColor.from_string(h)


NAVY = C("0B2545"); BLUE = C("2D6CDF"); GREEN = C("0E8F62"); AMBER = C("B45309")
INK = C("151A23"); MUT = C("596371"); WHITE = C("FFFFFF")
LINE = "D7DCE3"; PANEL = "F3F5F8"; PEND = "FFF3E0"
BODY = "Arial"


def _runfmt(run, size, color, bold=False, italic=False, mono=False):
    run.font.name = "Consolas" if mono else BODY
    run.font.size = Pt(size); run.font.bold = bold; run.font.italic = italic
    run.font.color.rgb = color


def _shade(cell, hexfill):
    sh = OxmlElement("w:shd"); sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), hexfill)
    cell._tc.get_or_add_tcPr().append(sh)


def _borders(table, color=LINE, sz=4):
    b = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}"); e.set(qn("w:val"), "single"); e.set(qn("w:sz"), str(sz))
        e.set(qn("w:space"), "0"); e.set(qn("w:color"), color); b.append(e)
    table._tbl.tblPr.append(b)


def _pagefield(run):
    r = run._r
    e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), "begin"); r.append(e)
    it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve"); it.text = "PAGE"; r.append(it)
    sep = OxmlElement("w:fldChar"); sep.set(qn("w:fldCharType"), "separate"); r.append(sep)
    t = OxmlElement("w:t"); t.text = "1"; r.append(t)
    end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end"); r.append(end)


doc = Document()
normal = doc.styles["Normal"]; normal.font.name = BODY; normal.font.size = Pt(10)
normal.font.color.rgb = INK; normal.paragraph_format.space_after = Pt(4)
normal.paragraph_format.line_spacing = 1.15
for lvl, sz, col in (("Heading 1", 14, NAVY), ("Heading 2", 11.5, BLUE)):
    st = doc.styles[lvl]; st.font.name = BODY; st.font.size = Pt(sz); st.font.bold = True
    st.font.color.rgb = col
    st.paragraph_format.space_before = Pt(12 if lvl == "Heading 1" else 8)
    st.paragraph_format.space_after = Pt(4); st.paragraph_format.keep_with_next = True

sec = doc.sections[0]
sec.page_width = Cm(21.0); sec.page_height = Cm(29.7)
sec.top_margin = Cm(2.2); sec.bottom_margin = Cm(1.9)
sec.left_margin = sec.right_margin = Cm(2.0)
sec.header_distance = Cm(1.0); sec.footer_distance = Cm(1.0)
sec.different_first_page_header_footer = True
hdr = sec.header; hdr.is_linked_to_previous = False
hp = hdr.paragraphs[0]
hp.add_run().add_picture(LOGO, height=Cm(0.55))
hp.add_run("    ")
_runfmt(hp.add_run("PIH AI Factory RFI — Datategy Response (DRAFT — internal work in progress)"), 8, MUT, italic=True)
f = sec.footer; f.is_linked_to_previous = False
ft = f.add_table(rows=1, cols=2, width=Cm(17)); ft.allow_autofit = False
ft.cell(0, 0).width = Cm(12.5); ft.cell(0, 1).width = Cm(4.5)
_runfmt(ft.cell(0, 0).paragraphs[0].add_run("Datategy — Confidential — response to PIH RFI (AI Factory Programme)"), 8, MUT)
rp = ft.cell(0, 1).paragraphs[0]; rp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
_runfmt(rp.add_run("Page "), 8, MUT); _pagefield(rp.add_run())
_e = f.paragraphs[0]; _e._element.getparent().remove(_e._element)


def h1(text):
    p = doc.add_heading(text, level=1)
    for r in p.runs:
        r.font.color.rgb = NAVY; r.font.name = BODY
    return p


def h2(text):
    p = doc.add_heading(text, level=2)
    for r in p.runs:
        r.font.color.rgb = BLUE; r.font.name = BODY
    return p


def para(text, size=10, color=INK, bold=False, italic=False, before=3, after=4):
    p = doc.add_paragraph(); pf = p.paragraph_format
    pf.space_before = Pt(before); pf.space_after = Pt(after); pf.line_spacing = 1.15
    _runfmt(p.add_run(text), size, color, bold=bold, italic=italic)
    return p


def lead(head, body, size=10):
    p = doc.add_paragraph(); pf = p.paragraph_format
    pf.space_before = Pt(3); pf.space_after = Pt(4); pf.line_spacing = 1.15
    _runfmt(p.add_run(head), size, NAVY, bold=True)
    _runfmt(p.add_run(body), size, INK)
    return p


def bullet(text, size=10, bold_head=None):
    p = doc.add_paragraph(); pf = p.paragraph_format
    pf.space_before = Pt(1); pf.space_after = Pt(1); pf.left_indent = Cm(0.5)
    pf.first_line_indent = Cm(-0.35); pf.line_spacing = 1.12
    _runfmt(p.add_run("• "), size, INK)
    if bold_head:
        _runfmt(p.add_run(bold_head + " — "), size, INK, bold=True)
    _runfmt(p.add_run(text), size, INK)
    return p


def qtag(text):
    """Which RFI question(s) this section answers."""
    p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(0); p.paragraph_format.space_after = Pt(4)
    _runfmt(p.add_run("Answers: " + text), 8.5, BLUE, bold=True, mono=True)
    return p


def pending(text):
    """Amber marker: waiting for PIH's answer to our clarification letter."""
    t = doc.add_table(rows=1, cols=1); t.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = t.cell(0, 0); cell.width = Cm(17); _shade(cell, PEND); _borders(t, "E0B96A", 4)
    cell.text = ""
    p = cell.paragraphs[0]
    _runfmt(p.add_run("⚠ PENDING PIH CLARIFICATION — "), 9, AMBER, bold=True)
    _runfmt(p.add_run(text), 9, INK, italic=True)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)


def todo(text):
    p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(2); p.paragraph_format.space_after = Pt(2)
    _runfmt(p.add_run("‹ TO COMPLETE — " + text + " ›"), 9, C("B00020"), bold=True, italic=True)
    return p


def table(headers, rows, widths=None, hdr_fill="0B2545", size=9):
    t = doc.add_table(rows=1, cols=len(headers)); t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.allow_autofit = False; _borders(t)
    for j, htxt in enumerate(headers):
        c = t.cell(0, j); _shade(c, hdr_fill); c.text = ""
        _runfmt(c.paragraphs[0].add_run(htxt), size, WHITE, bold=True)
    for i, row in enumerate(rows):
        r = t.add_row()
        for j, val in enumerate(row):
            c = r.cells[j]; _shade(c, "FFFFFF" if i % 2 == 0 else PANEL); c.text = ""
            pp = c.paragraphs[0]; pp.paragraph_format.line_spacing = 1.08
            _runfmt(pp.add_run(val), size, INK, bold=(j == 0))
    if widths:
        for r in t.rows:
            for j, w in enumerate(widths):
                r.cells[j].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


# ================================================================ COVER
for _ in range(2):
    doc.add_paragraph()
cov = doc.add_paragraph(); cov.alignment = WD_ALIGN_PARAGRAPH.CENTER
cov.add_run().add_picture(LOGO, width=Cm(4.4))
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before = Pt(22)
_runfmt(p.add_run("RESPONSE TO REQUEST FOR INFORMATION  ·  CONFIDENTIAL"), 10.5, BLUE, bold=True, mono=True)
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before = Pt(8)
_runfmt(p.add_run("PIH AI Factory Programme"), 26, NAVY, bold=True)
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
_runfmt(p.add_run("A product-grade agent factory — sovereign, evaluated, governed — "
                  "delivered inside PIH's factory model"), 12, INK)
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before = Pt(20)
_runfmt(p.add_run("Submitted to: Power International Holding — Group Data & AI Office"), 11, MUT, bold=True)
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
_runfmt(p.add_run("Datategy  ·  ‹ 14 July 2026 ›  ·  DRAFT v1 — internal"), 10, MUT)
doc.add_page_break()

# ================================================================ READER'S NOTE + COMPLIANCE MATRIX
h1("Reader's note & compliance matrix")
para("This response follows the structure requested in Section 9 of the RFI. Each section states the "
     "RFI questions it answers. Amber boxes flag elements that depend on PIH's answers to our written "
     "clarification questions submitted on 7 July 2026 (no response received at the time of writing); "
     "these will be consolidated as soon as the clarification responses are issued.", italic=True, color=MUT)
table(["Response section (per RFI §9)", "RFI questions"],
      [["1. Organisation overview", "General"],
       ["2. Technical capability evidence", "Q3.1 · Q3.2 · Q6.1"],
       ["3. Engagement & commercial model", "Q2.1 · Q5.1 · Q5A.1 · Q5A.2"],
       ["4. Pilot approach (UCC)", "Q2B.1 · Q2B.2 · Q2C.1"],
       ["5. Factory economics & reuse", "Q2A.1 · Q2A.2 · Q2A.3"],
       ["6. SAP financial module capability", "Q2.3"],
       ["7. Platform architecture & Hikmah integration", "Q2.2 · Q3B.1 – Q3B.6"],
       ["8. AI evaluation framework", "Q4A.1 · Q4A.2"],
       ["9. Governance, risk & AI security", "Q4.1 · Q4B.1 · Q4B.2 · Q4C.1 · Q4E.1"],
       ["10. Go-live readiness", "Q4D.1"],
       ["11. Model strategy & sovereignty", "Q3A.1 · Q3A.2 · Q3A.3"],
       ["12. Adoption & value realisation", "Q5B.1 – Q5B.4"],
       ["13. AgentOps — operate & monitor", "Q8.1 – Q8.4"],
       ["14. Named individuals", "General"],
       ["15. References (≥1 SAP financial · ≥1 Gulf region)", "General"],
       ["16. Questions & clarifications", "Q7.1 · General"]],
      widths=(9.0, 8.0))

# ================================================================ 1. ORGANISATION
h1("1.  Organisation overview")
qtag("General")
para("Datategy is a French AI software editor founded in 2016. We design, build and operate sovereign "
     "AI platforms: papAI (data & machine-learning intelligence), Document Center (knowledge "
     "intelligence) and Agentium (decision & agentic intelligence), delivered as one composite, "
     "Kubernetes-native platform and verticalised into turnkey Suites (translation, narration, "
     "compliance, maintenance).")
bullet("EU Trusted AI-labelled; UGAP-referenced for the French public market; member of the AFNOR AI "
       "standardisation committee (CN IA — the French national mirror of ISO/IEC JTC 1/SC 42) that "
       "contributes to drafting ISO/IEC 42001 and 12792.", bold_head="Trust & standards")
bullet("delivery is carried by Datategy's AI & Data Center of Excellence — a dedicated hub-and-spoke "
       "delivery engine (Paris · London · Algiers · UAE · KSA) whose flagship domain is intelligent "
       "service-desk and process automation (agentic + RPA/BPA convergence), directed by our Chief "
       "Scientific Officer. It combines senior architecture with a nearshore build capacity at highly "
       "competitive day rates, and a continuous-recruitment partnership with a national AI school.",
       bold_head="Delivery engine")
bullet("peer-reviewed research on retrieval (HAH-RAG / OmniRAG) and failure root-cause analysis, "
       "published and operated in production — the scientific base of our evaluation-first factory.",
       bold_head="Owned R&D")
para("Positioning for this programme: we are neither a platform vendor selling consumption, nor a "
     "systems integrator assembling third-party frameworks per project. We bring a product-grade "
     "agent factory — orchestration, evaluation, governance and audit as platform features — and a "
     "delivery squad that executes inside PIH's factory model, on PIH's strategic platforms, with "
     "full portability of what we build.", bold=True)

# ================================================================ 2. TECHNICAL CAPABILITY
h1("2.  Technical capability evidence")
qtag("Q3.1 · Q3.2 · Q6.1")
para("Per RFI Section 6, for each capability area: a capability statement, the evidence we would "
     "present at shortlist stage, and gaps stated honestly.")
table(["Capability area", "Statement & evidence", "Gaps / mitigation"],
      [["Agentic orchestration, MCP, durable execution",
        "Core product capability: graph-based flows, stateful & replayable runs (checkpoints, "
        "resubmission with overrides, parent-child lineage), MCP-compliant connector framework, "
        "typed skill registry. Evidence: product demo, run-replay live, architecture dossier.",
        "None — flagship."],
       ["AI evaluation & drift detection",
        "Evaluation engine as a platform feature: golden sets (incl. refusal cases), grounded-answer "
        "& hallucination rates, thresholds & review queues, drift monitoring, prompt-regression. "
        "Production evidence on multi-million-chunk corpora.",
        "None — flagship."],
       ["AI-specific security controls",
        "Distinct agent identity, signed mandates (caps, scopes, revocation), control policies "
        "(allowed models, max cost/decision, HITL thresholds), tamper-evident audit. Production "
        "deployments incl. regulated clients.",
        "Red-teaming for High-Impact agents: methodology in-house; independent third party "
        "recommended (see §9)."],
       ["Portability & handover",
        "Agents authored as flows on typed skills; pattern library, prompts, connectors and test "
        "harnesses handed over per RFI; no dependency on closed libraries; runtime integrates via "
        "PIH's Abstraction Layer / MCP.",
        "None — contractual commitment."],
       ["SAP — S/4HANA, BTP, FI/MM/SD/HCM/FI-AA",
        "Agentic + integration engineering proven on SAP-adjacent estates (SuccessFactors, ERP "
        "triggers). Named SAP module process experts fielded through delivery partnership.",
        "Named SAP module experts to be presented at shortlist. ‹structure depends on consortium "
        "clarification›"],
       ["RPA platform at enterprise scale",
        "CoE pole 'Intelligent Automation' combines Agentium agent-building with UiPath RPA and BPA "
        "(hyperautomation). Platform-agnostic approach.",
        "Enterprise-scale RPA references to be evidenced with partner at shortlist."],
       ["Databricks — medallion, Unity Catalog, Azure AI",
        "papAI is Spark-native (Kubernetes fabric); agents consume governed Gold data products via "
        "Unity Catalog — we build on the lakehouse investment, never beside or beneath it. Azure "
        "OpenAI / AI Foundry integration through the LLM gateway.",
        "Reference deployment on Databricks to be documented. ‹TO COMPLETE›"],
       ["Enterprise AI assistant — assistive & agentic",
        "Production conversational agents with grounded citations at industrial scale; service-desk "
        "automation is the CoE's flagship domain.",
        "None."],
       ["Parallel run & SoD compliance",
        "Parallel-run validation is our standard gate for privileged automations (agent vs human on "
        "identical inputs); SoD respected via minimum-privilege batch users and external "
        "authorisation review.",
        "SAP SoD review executed with partner's SAP security practice."],
       ["Cross-sector capability",
        "Construction & infrastructure (major public infrastructure programme, Grand Paris); "
        "healthcare (public hospital patient-flow AI); food & beverage / agro (co-operative "
        "forecasting on papAI SaaS); industry & energy (predictive maintenance, vision inspection); "
        "finance (risk scoring; predictive IT operations for an automotive financial-services group).",
        "Hospitality: transferable patterns (POS/Oracle experience); direct reference to be "
        "confirmed."]],
      widths=(4.0, 8.6, 4.4))
lead("Portability in practice (Q3.2) — ",
     "our platforms run in client runtimes as standard practice: a global industrial engineering "
     "group operates our retrieval and knowledge platform entirely on its own infrastructure, with "
     "flows, knowledge collections and configurations exported as versioned artefacts; a public-"
     "sector client received the complete containerised stack (models included) for air-gapped "
     "operation. Agents are authored as declarative flows over typed skills — the handover package "
     "(patterns, prompts, connectors, test harnesses, runbooks) is a deliverable, not a concession. "
     "‹reference details to confirm for shortlist›")
pending("Q5 (consortium/prime structure) and Q8 (Abstraction Layer maturity) condition the final shape "
        "of the SAP/RPA capability presentation — held as ‹options A/B› until PIH's clarification "
        "responses are issued.")

# ================================================================ 3. ENGAGEMENT & COMMERCIAL
h1("3.  Proposed engagement & commercial model")
qtag("Q2.1 · Q5.1 · Q5A")
h2("3.1  Engagement model — staff augmentation first, outcome-based as the factory proves")
para("We propose the hybrid model PIH anticipates, in two stages:")
bullet("specialist squads operate under the PIH Factory Lead inside the assembly line. Squad shape "
       "(per build squad): 1 agentic tech lead, 2–4 CoE AI/automation engineers, 1 QA/evaluation "
       "engineer (shared), SAP module expert on demand, under a France-based solution architect and "
       "our CoE director. Squads scale by adding cells, not by inflating one team.",
       bold_head="Stage 1 — Staff augmentation (mobilisation → pilot)")
bullet("once (i) the pattern library is seeded, (ii) ≥ 20 agents have passed go-live gates, and "
       "(iii) Finance baselines are stable, we transition to fixed unit prices per agent tier with "
       "outcome commitments (quality metrics of §8, adoption metrics of §12).",
       bold_head="Stage 2 — Outcome-based delivery")
bullet("named hypercare lead per wave, daily stand-ups with BU Champions, defect SLA (P1 same business "
       "day), rolling coverage as multiple agents overlap; transition-to-AgentOps checklist closes "
       "each hypercare.", bold_head="Hypercare bridge")
h2("3.2  Commercial architecture — you buy capacity and outcomes, not licence meters")
para("Our commercial design has one purpose: PIH's cost per agent falls as the factory scales, and "
     "no meter grows with your success. No per-user licence; no consumption tax on agent executions; "
     "the agentic runtime is included for programme agents.", bold=True)
table(["Component", "Basis", "Indicative pricing"],
      [["Agent build — unit price (factory execution, 2nd+ instance of a pattern)",
        "Per agent, by complexity tier (front-office unit PIH requested)",
        "Simple ≈ $3.5–5k · Medium ≈ $8–13k · Complex ≈ $18–30k. First-of-type: +50–100%, scoped "
        "separately. Volume degressivity: −10% beyond 100 live agents, −20% beyond 250."],
       ["Agentium runtime for programme agents",
        "Included in unit prices during the programme (capacity envelope, unlimited users)",
        "No separate platform fee while the factory runs — the runtime is how we deliver "
        "evaluation, replay, governance and audit as features, not per-agent rebuilds."],
       ["Knowledge capacity (Document Center)",
        "Per knowledge base / document volume — shared memory serving all agents",
        "Included allowance per phase; additional KB packs & volume overage at catalogue rates. "
        "Never priced per agent."],
       ["AgentOps managed service (§13)",
        "Per agent per month (operations effort scales with the estate)",
        "≈ $50–70 / agent / month, tiered by risk class. Model per PIH's decision at shortlist."],
       ["T&M day rates (staff augmentation)",
        "Per role — CoE delivery engine",
        "AI/Data engineer $149 · Developer $149 · QA/Eval engineer $149 · CoE Director $349 · "
        "Solution Architect (France) $880. Hybrid delivery; on-site Doha presence for pilot & leads; "
        "travel at cost."],
       ["Sovereign infrastructure",
        "PIH-owned (reference spec) or managed option",
        "On quote — see §11 for the sovereign serving options."]],
      widths=(4.6, 4.6, 7.8))
h2("3.3  Inference cost transparency (Q5A.1 · Q5A.2)")
para("Because models can be served on PIH infrastructure (open-weight) and/or through Azure OpenAI, "
     "inference is an infrastructure envelope plus per-agent telemetry, not an opaque markup: every "
     "run's token usage and cost are metered per agent in the value cockpit, exportable to Finance.")
bullet("model right-sizing per agent (small models for classification/routing, larger only where "
       "accuracy demands), prompt efficiency (deterministic token budgets with hard caps), response "
       "caching at the gateway, and batch inference for scheduled agents. Observed ranges on "
       "comparable estates: from fractions of a cent for routed transactional decisions to a few "
       "cents for grounded generative answers (benchmark ≈ $0.001 per governed execution at scale). "
       "Inputs needed from PIH to firm estimates: transaction volumes per agent, acceptable latency "
       "thresholds per surface, model preferences/constraints per data class, and concurrency "
       "profiles.", bold_head="Estimating & optimising (Q5A.1)")
bullet("SaaS endpoint costs passed through at cloud tariff (no markup) with full per-agent "
       "telemetry; sovereign serving billed as infrastructure envelope. Typical maturity trajectory: "
       "−30–50% cost per execution within 12 months through caching, routing to right-sized models "
       "and prompt optimisation — we propose sharing this trajectory as a jointly-tracked KPI, with "
       "optimisation reviews each quarter.", bold_head="Commercial structure & trajectory (Q5A.2)")
h2("3.4  Payment milestones (Q5.1)")
para("The milestone philosophy (gates, not elapsed time) is acceptable. Two comments:")
bullet("we request a mobilisation payment at signature covering factory onboarding and squad "
       "ramp-up, and milestone granularity at wave level rather than a single 200-agent step — "
       "standard for a programme of this cash profile.", bold_head="Cash profile")
bullet("we propose objective completion criteria per milestone: agents live = passed the six go-live "
       "acceptance criteria (§10), with the AI Control Tower registration as the timestamp of record.",
       bold_head="Auditable triggers")
pending("Q21 (mobilisation/interim payment) and Q18 (definition & baseline of the 30% / 15% reuse "
        "targets) — commercial figures above are indicative until clarified; unit prices assume the "
        "reuse-baseline definition proposed in §4.")

# ================================================================ 4. PILOT (official §9 order)
h1("4.  Pilot approach — UCC (factory validation)")
qtag("Q2B.1 · Q2B.2 · Q2C.1")
para("We treat the pilot as the factory's first production run, not a demo: every pilot agent goes "
     "through the full assembly line (triage → design card → build → evaluate → gates → deploy → "
     "hypercare), seeding the pattern library and validating the governance framework end to end.")
bullet("mobilisation plan: week 1–2 factory onboarding (access, environments, Abstraction Layer "
       "interfaces, data-quality audit kickoff); squad fielded: solution architect (on-site), agentic "
       "tech lead, 3–4 CoE engineers, QA/eval engineer, SAP module expert; weeks 3–13: build & "
       "parallel run; go-live per PIH gates.", bold_head="Mobilisation & team (Q2B.1)")
bullet("every pilot learning is written back as a pattern-library asset (pattern update, connector "
       "hardening, golden-set case, runbook entry) — reviewed weekly with the PIH Factory Lead; the "
       "pilot exit report includes the seeded catalogue inventory.", bold_head="Learnings loop")
bullet("with an 81.1% automation target on ~950,240 annual transactions, the parallel run must be "
       "statistically representative: we propose a 2-week run on full production volume in shadow "
       "mode, stratified by transaction type, with Finance-signed baseline established from the "
       "preceding 12 months and discrepancy thresholds agreed before the run. Risks: master-data "
       "quality (audit before build, not at UAT), SAP integration depth (early RFC/BAPI testing on "
       "non-prod), change resistance (BU Champions engaged from week 1).",
       bold_head="Parallel run & baseline (Q2B.2)")
bullet("Phase 1 (validation): one concentrated squad — architect, tech lead, 3–4 engineers, QA/eval — "
       "optimised for pattern creation and gate calibration. Phase 2 (volume): scale by adding build "
       "cells (2–4 engineers + shared QA) around a stable architecture core; pattern authoring "
       "shifts to instantiation, so the senior-to-engineer ratio drops. Phase 3 (cognitive agents): "
       "re-concentrate — research-grade profiles (evaluation, RCA, multi-step reasoning) join the "
       "core while build cells maintain volume. The CoE's hub-and-spoke model is designed exactly "
       "for this elasticity.", bold_head="Team evolution across phases (Q2C.1)")
pending("Q16 (non-production SAP environment availability) and Q3 (number/complexity of priority pilot "
        "agents) determine the pilot build plan granularity — held as assumptions pending "
        "clarification.")

# ================================================================ 5. FACTORY ECONOMICS
h1("5.  Factory economics — reuse & productivity")
qtag("Q2A.1 · Q2A.2 · Q2A.3")
lead("Reuse is our grammar, not a slogan. ",
     "Every agent is authored from typed, versioned components: Skills (atomic capabilities), "
     "Capabilities (business promises), Systems (assembled agents), Patterns (structural templates). "
     "A new idea matching an existing skill enters the instantiation queue, not a build. Connectors, "
     "prompts and test harnesses are catalogue components — built once, reused programme-wide.")
bullet("we accept the 30% (pattern reuse) / 15% (component standardisation) cost-reduction targets, "
       "measured against the first-of-type build cost of each pattern, reported monthly from the "
       "factory ledger (reuse rate per agent = % of its flow nodes drawn from the catalogue). "
       "Conditions: stable pattern taxonomy, PIH-side prerequisites met (data access, environments).",
       bold_head="Commitment (Q2A.1)")
bullet("Phase 1 is dominated by first-of-type patterns (unit cost ≈ 1.5–2× factory price); Phase 2 "
       "crosses to majority-instantiation (unit cost → catalogue price, −10% volume break); Phase 3 "
       "cognitive agents reuse the evaluated component base (complex tier, but with mature harnesses). "
       "Primary drivers: pattern coverage, connector catalogue completeness, golden-set maturity, "
       "AI-assisted authoring.", bold_head="Cost trajectory (Q2A.2)")
bullet("our build track is AI-assisted end-to-end (code agents for flow scaffolding, test generation, "
       "connector stubs), with governance: human review on every merge, generated code subject to the "
       "same golden-set regression and security validation as hand-written code. Measured effect on "
       "our deliveries: 25–40% cycle-time reduction on authoring and test coverage. ‹internal metric "
       "to finalise›", bold_head="AI coding agents (Q2A.3)")

# ================================================================ 6. SAP FINANCIAL MODULE CAPABILITY
h1("6.  SAP financial module capability")
qtag("Q2.3")
para("Approach for SAP FI / MM / SD / HCM / FI-AA agents: agents act through governed, typed skills "
     "wrapping BAPI/RFC, OData and BTP services — never screen-level automation for posting flows; "
     "every SAP-posting agent runs as a dedicated minimum-privilege batch user (no shared users, no "
     "dialog logon), with three-tier error classification (hard stop / soft exception / business "
     "warning) implemented as flow branches, and full parallel-run before go-live.")
bullet("integration patterns applied on SAP-centred estates: event-driven triggers from "
       "SuccessFactors (joiner/mover/leaver states), OData reads for master and transactional data, "
       "BAPI/RFC wrapped as typed skills with bounded retries and idempotency, IDoc/CDC where "
       "streaming is required. Financial-posting context: parallel run against human postings on "
       "identical transactions, weekly GL reconciliation during hypercare, external SoD review "
       "before the go-live gate.", bold_head="Integration & compliance experience")
todo("named SAP module experts (FI, MM, SD, HCM, FI-AA) with process credentials — to be nominated "
     "with delivery partner; CVs at shortlist stage")
pending("Q5 (consortium structure) conditions how SAP module experts are contracted and presented.")

# ================================================================ 7. HIKMAH
h1("7.  Platform architecture & Hikmah integration")
qtag("Q2.2 · Q3B.1 – Q3B.6")
bullet("agents consuming external market feeds, regulatory data, supplier systems or third-party "
       "APIs follow the same discipline as internal sources: the source is registered as a governed "
       "connector (auth, rate limits, schema contract, provenance metadata), its data passes an "
       "agent-level quality gate before any action, retrieved external content is treated as data — "
       "never as instructions (prompt-injection isolation), and every external call is ledgered with "
       "cost and provenance. Licensing and redistribution constraints are enforced as control "
       "policies.", bold_head="Exogenous data sources (Q2.2)")
bullet("we build on the Databricks medallion on Azure (ADLS, Delta Lake, Unity Catalog, MLflow) with "
       "SAP Datasphere as a primary source: Analytical and Autonomous agents consume governed Gold "
       "data products through Unity Catalog, inheriting dataset-level access; agents never bypass "
       "the medallion to raw or source data. Our agents strengthen the lakehouse investment: they "
       "are consumers and publishers of governed data products, not a parallel stack.",
       bold_head="Medallion, Datasphere & governance (Q3B.1/4/5)")
bullet("agents expose and consume capabilities through MCP-compliant APIs registered in the connector "
       "registry; no point-to-point integration. Where a required connector does not yet exist, we "
       "build it as a registered, reusable catalogue component and hand it over.",
       bold_head="Connector registry (Q3B.3)")
bullet("consumption surface selected per agent type at design-card stage: Teams/portal for assistive, "
       "dashboards/Power BI for analytical, real-time endpoints for decisioning, headless A2A for "
       "consumable agents — one output contract per agent, rendered per surface, no bespoke "
       "front-ends.", bold_head="Consumption surfaces (Q3B.2)")
bullet("input data-quality (completeness, accuracy, consistency, uniqueness, timeliness, validity, "
       "version control) is evaluated as a gate in the agent flow: below threshold, the agent routes "
       "to exception instead of acting; writes back to Silver/Gold obey the platform's quality rules.",
       bold_head="Data-quality framework (Q3B.4)")
bullet("per-agent identity via Entra ID service principals, credentials in Key Vault, row/column-level "
       "security inherited from Unity Catalog; least-privilege enforced by the mandate (allowed "
       "actions, scopes, caps).", bold_head="Least privilege (Q3B.5)")
h2("Sector capability — concrete examples across PIH's domains (Q3B.6)")
table(["PIH domain", "Delivered example", "Outcome & stack"],
      [["Construction & Projects",
        "Automated characterisation and regulatory routing of excavated-material transport documents "
        "for Europe's largest infrastructure programme (Grand Paris), within a consortium",
        "Reliable, audited regulatory control integrated with the programme's traceability system; "
        "OCR + rules + agentic validation, human sign-off; on-prem."],
       ["Operations & FM / Technology",
        "Predictive IT operations (AIOps) for a European automotive financial-services group — "
        "prevention of critical incidents from logs & metrics",
        "Proactive supervision adopted by IT teams; Spark pipelines, time-series forecasting, "
        "explainable alerts; sovereign deployment."],
       ["Food & Beverage",
        "Production forecasting and surrogate models for biological-process calibration for an "
        "agricultural co-operative",
        "Forecast-driven planning on papAI SaaS; time-series + surrogate modelling; delivered "
        "through partner."],
       ["Hospitality & Retail (transferable)",
        "Real-time video analytics for a Gulf-region smart-parking / guidance operator",
        "Live vehicle & occupancy detection at scale; edge inference (Kafka + detection models); "
        "regional reference — details under NDA."]],
      widths=(3.4, 6.8, 6.8))
pending("Q8 (Abstraction Layer / AI Control Tower implementation status & API specs at mobilisation) "
        "and Q9 (role expected versus existing Hikmah conversational/agent components) materially "
        "affect integration effort and the Phase-1 critical path. Our plan carries two scenarios "
        "(integrate-to-existing vs partner-provided reference implementation under PIH governance) "
        "until clarified.")

# ================================================================ 8. EVALUATION
h1("8.  AI evaluation framework")
qtag("Q4A.1 · Q4A.2")
para("Evaluation is a platform feature, not a project deliverable — every agent ships with its "
     "harness. Methodology per agent type:")
table(["Agent type", "Evaluation methodology"],
      [["Transactional", "Deterministic path coverage; regression suite executed on every change; "
        "parallel-run vs human output on identical transactions; three-tier error classification "
        "validated per branch."],
       ["Assistive / Analytical", "Ground-truth datasets (golden sets) with held-out splits; "
        "precision/recall per intent; grounded-answer and citation completeness for RAG outputs."],
       ["Autonomous", "Multi-criteria rubrics; hallucination-rate measurement; reasoning-consistency "
        "checks; refusal cases (actions the agent must never take); human expert review queues."]],
      widths=(3.4, 13.6))
bullet("we commit to PIH's indicative targets per agent type — task accuracy ≥98% transactional / "
       "≥95% others, precision & recall ≥0.90, hallucination ≤2%, groundedness ≥95% — measured on "
       "jointly-signed golden sets, reported continuously against the go-live baseline.",
       bold_head="Metric commitments")
bullet("golden sets are created at design-card stage from real historical cases (including refusal "
       "and escalation cases), owned jointly, versioned, refreshed quarterly; contamination is "
       "prevented structurally: the live path never reads evaluation data, and our regression "
       "tooling asserts it (anti-overfit test).", bold_head="Ground truth & contamination (Q4A.1)")
bullet("pre-go-live: evaluation thresholds are one of the six gates. Post-go-live: continuous "
       "scoring against baseline, drift detection on inputs and outputs, prompt-regression suite on "
       "every prompt change, quarterly ground-truth refresh — all visible in the cockpit and the AI "
       "Control Tower.", bold_head="Gates & continuous evaluation (Q4A.2)")

# ================================================================ 9. GOVERNANCE & SECURITY
h1("9.  Governance, risk & AI security")
qtag("Q4.1 · Q4B.1 · Q4B.2 · Q4C.1 · Q4E.1")
para("We operate inside PIH's retained governance (Factory Lead authority, AI Control Tower, gates) "
     "and bring enforcement mechanics that make it provable:")
bullet("already implemented in production on comparable enterprise AI deliveries: parallel-run "
       "validation before privileged automation, evaluation-threshold gates, kill-switch & tested "
       "rollback, tamper-evident audit with export, per-agent identity and minimum-privilege service "
       "accounts, three-tier error classification as flow branches. Not yet exercised at PIH's SAP "
       "scale: SoD authorisation review on SAP posting agents — met through the partner's SAP "
       "security practice plus external review, as the RFI requires.",
       bold_head="Delivery controls — implemented vs to-meet (Q4.1)")
bullet("PIH's risk tiers map to control policies: Low = autonomous with audit; Medium = "
       "approve-then-act on downstream triggers; High = mandatory HITL, parallel-run, kill-switch "
       "rehearsal, red-teaming before go-live. Proportionality is demonstrable: each agent's model "
       "card records its tier, the active control policies, and the evidence (gates passed) — "
       "reviewable by PIH's governance function at any time.", bold_head="Risk tiering (Q4B.1)")
bullet("data-sensitivity classification is applied per knowledge collection and per skill "
       "input/output at design-card stage (public / internal / confidential / regulated), and "
       "enforced by routing (§11) and knowledge-base isolation. Multi-jurisdictional residency: our "
       "platforms run today under GDPR, French sovereignty requirements (on-prem/air-gap deliveries) "
       "and EU AI Act preparation; we monitor evolving Gulf AI regulation through our standards "
       "activity (AFNOR CN IA / ISO/IEC JTC 1 SC 42) and regional counsel.",
       bold_head="Data classification & multi-jurisdiction (Q4B.2)")
bullet("prompt-injection: input sanitisation, instruction/data separation, guarded tool scopes, and "
       "grounding refusal (the agent cannot execute instructions found in retrieved content); tool & "
       "API misuse: signed mandates (allowed actions, caps, scopes) enforced by construction plus "
       "anomaly detection on invocation patterns; data exfiltration: output validation, citation "
       "gating, egress monitoring; secrets: per-agent credentials in vault, rotation without "
       "interruption; red-teaming: structured adversarial campaigns for High-Impact agents before "
       "go-live — executed by our security practice with an independent third party recommended for "
       "arbitration.", bold_head="Five security areas (Q4C.1)")
bullet("additional threat we surface: cross-agent contamination in multi-agent estates (an agent "
       "consuming another's unvalidated output). Mitigation: consumable agents publish through "
       "evaluated, versioned contracts only — A2A calls carry the producer's evaluation status.",
       bold_head="Beyond the framing")
bullet("risk register: each RFI risk answered in-line — data quality (audit before build, gate at "
       "design), SAP integration (early RFC testing, tested kill switch), adoption (BU Champions + "
       "Academy + hypercare), financial discrepancy (mandatory parallel run + weekly GL reconciliation "
       "during hypercare).", bold_head="Programme risks (Q4E.1)")
todo("Q4E.1 also asks for a lived example ('where you encountered the same risk, what happened and "
     "what you did') — add one anonymised anecdote per major risk (data quality on an industrial "
     "corpus; integration depth on an ERP-triggered flow)")

# ================================================================ 10. GO-LIVE READINESS
h1("10.  Go-live readiness")
qtag("Q4D.1")
para("The six acceptance criteria are validated simultaneously through a single go-live readiness "
     "review per agent, chaired by PIH's Factory Lead: (1) parallel-run report signed by Finance; "
     "(2) evaluation thresholds met on the golden set; (3) security validation incl. SoD review; "
     "(4) kill-switch and rollback rehearsed; (5) Control Tower registration & model card complete; "
     "(6) BU Champion UAT sign-off. Our go/no-go authority: the engagement delivery director "
     "(named in §14), with a written recommendation per criterion; PIH holds the final gate.")

# ================================================================ 11. MODEL STRATEGY
h1("11.  Model strategy & sovereignty")
qtag("Q3A.1 · Q3A.2 · Q3A.3")
bullet("all model access flows through the LLM gateway / model router: per-task routing with "
       "fallback chains (primary → secondary → degraded-mode), a model catalogue versioned like any "
       "dependency, and caching + deterministic token budgets for cost control.",
       bold_head="Routing & fallback (Q3A.1)")
bullet("routing is decided per agent and per data-sensitivity tier at design-card stage: regulated or "
       "confidential data classes route to private inference (open-weight models served on PIH "
       "infrastructure — Azure Qatar region GPU, private cloud or on-premise; Arabic-capable "
       "families available); public/internal classes may use Azure OpenAI endpoints. The decision is "
       "recorded in the agent's model card and enforced by control policy — not by convention.",
       bold_head="Sovereign vs SaaS inference (Q3A.2)")
bullet("model selection is a scored trade-off (sensitivity, accuracy on the agent's golden set, "
       "latency, cost per decision) re-run at every major model release; agents are model-agnostic "
       "by construction (no prompt or logic tied to a provider), so migration is a routing change "
       "plus a golden-set regression — no rework.", bold_head="Justification & migration (Q3A.3)")
pending("Q13/Q14 (sensitivity tiers requiring sovereign inference; sovereign GPU capacity — PIH-provided "
        "or partner-provided) — the serving architecture is presented with both options pending "
        "clarification.")

# ================================================================ 12. ADOPTION & VALUE
h1("12.  Adoption & value realisation")
qtag("Q5B.1 – Q5B.4")
bullet("per agent: active-usage rate (weekly active users / eligible population), override rate, "
       "exception-escalation rate, output-acceptance rate, and CSAT where user-facing — all measured "
       "natively in the platform and reconciled with the run ledger, exportable to PIH's value "
       "registry.", bold_head="Adoption metrics (Q5B.1)")
bullet("delivery scope includes: BU Champion structured workshop before each go-live, daily "
       "hypercare support and peer-training material (train-the-trainer), Datategy Academy tracks "
       "for administrators and builders — supporting PIH's three-tier model, not replacing it. "
       "Hypercare runs ≥30 days per agent batch; concurrent hypercares are managed by a dedicated "
       "hypercare lead with a consolidated defect board across live batches; transition to "
       "steady-state is triggered by a checklist (defect rate below threshold, adoption baseline "
       "established, runbook accepted by operations).", bold_head="Change & hypercare scope (Q5B.2)")
bullet("we accept linking a portion of outcome payments to adoption: proposal — up to 10–15% of the "
       "per-agent outcome fee held back against adoption thresholds set per agent type after a "
       "4-week post-go-live baseline (indicative commitment: ≥70% active usage on assistive agents "
       "at T+90 days), released monthly on measured metrics; clawback accepted within the holdback "
       "envelope (no uncapped clawback). ‹percentages to validate internally›",
       bold_head="Adoption-linked structure (Q5B.3)")
bullet("monthly value reviews with each BU Champion: Finance-baseline tracking surfaced in the "
       "cockpit (savings vs baseline per agent), early quality warnings (drift, exception spikes, "
       "override-rate anomalies flagged to the Champion before users complain), refresh sessions and "
       "usage nudges beyond hypercare, and a quarterly value report consolidated for the value "
       "registry and 90-day value confirmations.", bold_head="Value realisation support (Q5B.4)")
pending("Q19 (at-risk fee portion & value attribution between partner and PIH change structure).")

# ================================================================ 13. AGENTOPS
h1("13.  AgentOps — operate & monitor")
qtag("Q8.1 – Q8.4")
para("Our AgentOps capability is the platform's own telemetry plus an operating team — the five "
     "signals PIH requires are native:")
bullet("distributed tracing per invocation (run → skill → tool call), agent quality scores updated "
       "continuously against the go-live baseline, automated prompt-regression on every change, cost "
       "telemetry per agent (tokens, infra, per-decision cost), drift detection on inputs/outputs.",
       bold_head="Telemetry (Q8.1)")
bullet("drift is detected on both inputs (distribution shifts on incoming data) and outputs "
       "(quality-score decay vs go-live baseline); prompt changes are gated: no prompt reaches "
       "production without passing the golden-set regression suite, and model upgrades follow a "
       "quarterly assessment cadence (candidate model scored on every affected agent's golden set "
       "before migration).", bold_head="Drift & prompt-regression governance (Q8.2)")
bullet("incident response targets: P1 15 min acknowledgement / restore-or-rollback 4h; P2 same "
       "business day; P3 planned. Kill-switch execution within the 5-minute requirement is rehearsed "
       "at go-live and quarterly.", bold_head="Incident SLAs (Q8.3)")
todo("Q8.3 also asks for a lived incident narrative (issue → response → permanent fix) — add one "
     "anonymised production incident from our AgentOps history")
bullet("AgentOps findings feed the factory: every recurring exception becomes a pattern-library "
       "update, a golden-set case or a policy adjustment — the improvement loop is evaluated "
       "(dress-rehearsal on historical cases) before rollout, with automatic rollback.",
       bold_head="Continuous improvement (Q8.4)")
para("We can deliver AgentOps as build-partner or hand it to a separate operator at PIH's choice — "
     "the telemetry and runbooks are handover-ready either way (per-agent monthly fee indicated in §3).")

# ================================================================ 14. NAMED INDIVIDUALS
h1("14.  Named individuals")
qtag("General")
table(["Role on programme", "Individual", "Profile highlights"],
      [["CoE Director / scientific leadership", "Mounir Ouadi — Chief Scientific Officer & Head of "
        "AI & Data CoE", "Computer vision, Edge AI, deep-learning optimisation, embedded systems; "
        "built AI/software teams from zero; agentic conversational AI experience; industrial "
        "deployments (energy, infrastructure)."],
       ["Evaluation & retrieval research", "‹ Kenneth Ezukwoke — Research Scientist ›",
        "Peer-reviewed research: HAH-RAG retrieval (OmniRAG), failure root-cause analysis (Big "
        "GCVAE); evaluation methodology."],
       ["Solution Architect (France)", "‹ TO COMPLETE ›", "Agentium architecture, sovereign "
        "deployments, enterprise integration."],
       ["Delivery director / engagement lead", "‹ TO COMPLETE ›", "Go/no-go authority (§10)."],
       ["SAP module experts (FI/MM/SD/HCM/FI-AA)", "‹ TO COMPLETE — with delivery partner ›",
        "Process credentials per module; presented at shortlist."]],
      widths=(4.6, 5.2, 7.2))
para("CVs available at shortlist stage per the RFI's guidance.", italic=True, color=MUT)

# ================================================================ 15. REFERENCES
h1("15.  References")
qtag("General — RFI requires ≥1 SAP financial agent delivery and ≥1 Gulf-region reference")
para("References representative of this programme (details and reference interviews under NDA at "
     "shortlist stage):")
bullet("real-time video analytics and guidance for a smart-parking operator in the Gulf — live "
       "vehicle and occupancy detection at production scale, edge inference, streaming pipeline. "
       "‹additional Gulf telecommunications reference subject to clearance›",
       bold_head="1 · Gulf region — smart-city AI in production")
bullet("proactive prevention of critical IT incidents for a European automotive financial-services "
       "group — large-scale log/metric ingestion, time-series forecasting, explainable alerts "
       "adopted by IT teams; SAP-adjacent estate (SuccessFactors-triggered identity flows, "
       "ERP-connected operations).", bold_head="2 · Predictive IT operations (AIOps)")
bullet("industrialised translation & QA chains with normed quality measurement (SAE J2450) and "
       "human-in-the-loop review for a major European automotive manufacturer — agent-per-error-class "
       "design, golden-set gating, measured ROI.", bold_head="3 · Governed multi-agent document pipelines")
bullet("grounded, cited assistant over a multi-million-chunk technical corpus for a global industrial "
       "engineering group — hybrid retrieval, evaluation harness, expert knowledge capture.",
       bold_head="4 · Enterprise knowledge & retrieval at industrial scale")
para("Acknowledged gap per the RFI's reference criteria: our direct references do not include an "
     "SAP financial posting agent delivery; this is precisely the capability our delivery "
     "partnership brings, and a partner reference meeting this criterion will be presented at "
     "shortlist stage. ‹confirm with partner›", italic=True, color=MUT)

# ================================================================ 16. QUESTIONS & CLARIFICATIONS
h1("16.  Questions & clarifications")
qtag("Q7.1 · General")
bullet("from our factory-style programmes, the criteria most predictive of delivery success are: "
       "(1) maturity of the evaluation harness before scale-up (golden sets signed, gates "
       "calibrated) — the single best predictor of agent quality at volume; (2) data-access and "
       "environment readiness at mobilisation (the most common source of slippage); (3) "
       "pattern-library governance discipline (who may publish a pattern, and how reuse is "
       "measured). We suggest PIH's framework add an explicit criterion for 'evidence of "
       "production evaluation practice' — evaluation is where agent factories succeed or fail, and "
       "it is currently assessed only inside the AI-governance weighting.",
       bold_head="Most predictive criteria (Q7.1)")
bullet("we submitted 21 written clarification questions on 7 July 2026 (scope split & sizing, "
       "delivery structure, Abstraction Layer / AI Control Tower maturity, sovereign inference "
       "expectations, SAP environment access, reuse-target definitions, commercial mechanics). At "
       "the time of submission no responses had been received; the amber boxes throughout this "
       "document flag the answers that depend on them. We would welcome the responses ahead of the "
       "shortlist stage and will consolidate this response accordingly.",
       bold_head="Open clarifications")

# ================================================================ ANNEXES
h1("Annexes (separate attachments, ≤ 20 pages)")
bullet("A — Agentium Product Overview (technical dossier)")
bullet("B — Pricing schedule (unit prices, T&M rate card, AgentOps)")
bullet("C — Reference case studies (‹ under NDA ›)")
bullet("D — CVs of named individuals (‹ at shortlist ›)")

doc.save(OUT)
print("saved:", OUT)
