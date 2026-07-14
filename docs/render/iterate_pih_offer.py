# -*- coding: utf-8 -*-
"""Iterate on the PIH Service Help Desk offer draft (copy → v2, original untouched).

Fixes applied:
  P1 — Architecture reframed product-first (Agentium platform, not custom dev)
  P2 — Executive summary replaced with the selling version (differentiators, ROI, figures)
  P3 — Missing RFP sections added: Proactive Ops & RCA (§4.5), Evaluation & Quality,
       KPIs/ROI cockpit (§4.3), Deployment options (§6.1), Coexistence/migration,
       Enablement & CoE (§4.7), Planning, Commercial offer, Support & SLA (§6.5),
       Experience & References (§6.6)
  + secondary: figures 12,200 / 5,800/mo / 70K/yr, Leena/Daizy as migration not
    integration, wave naming, typo fixes, diagrams embedded.

Input : docs/pih/Service Help Desk - Technical and Commercial offer.docx
Output: docs/pih/Service Help Desk - Technical and Commercial offer - v2 Datategy.docx
"""
import os
from docx import Document
from docx.shared import Cm
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph

HERE = os.path.dirname(os.path.abspath(__file__))
DIAG = os.path.join(HERE, "assets", "diagrams")
PIH = os.path.join(os.path.dirname(HERE), "pih")
SRC = os.path.join(PIH, "Service Help Desk - Technical and Commercial offer.docx")
OUT = os.path.join(PIH, "Service Help Desk - Technical and Commercial offer - v2 Datategy.docx")

# ------------------------------------------------------------------ diagram
def build_architecture_diagram():
    """PIH-specific end-to-end architecture diagram (RFP §6.1), Datategy style."""
    import pih_diagrams as dg
    from matplotlib.patches import FancyBboxPatch
    NAVY, BLUE, GREEN, AMBER, PURPLE = dg.NAVY, dg.BLUE, dg.GREEN, dg.AMBER, dg.PURPLE
    MUT, LIGHT = dg.MUT, dg.LIGHT
    fig, ax = dg._fig(13, 8.2)
    # channels
    for label, cx in [("Microsoft Teams", 25), ("Web portal (ITSD)", 65), ("Email", 105)]:
        dg._box(ax, cx, 76, 34, 6.5, [(label, True, 9.5, BLUE)], fill=LIGHT[BLUE], edge=BLUE,
                accent=BLUE, round_r=1.8)
        dg._arrow(ax, cx, 72.4, cx, 68.4, color=MUT, lw=1.3)
    # Agentium platform panel
    panel = FancyBboxPatch((4, 40), 122, 28, boxstyle="round,pad=0,rounding_size=2.5",
                           linewidth=1.6, edgecolor=NAVY, facecolor="#F4F7FB", zorder=0)
    ax.add_patch(panel)
    ax.text(65, 64.2, "Agentium — sovereign agent platform (product)", ha="center",
            fontsize=10.5, color=NAVY, fontweight="bold")
    row1 = [("Flow Builder", "39 use-case flows", PURPLE), ("Run Engine", "stateful · replayable", BLUE),
            ("Evaluation Engine", "golden sets · review", GREEN)]
    row2 = [("Policies & Mandates", "HITL · caps · scopes", AMBER), ("Audit Ledger", "tamper-evident", NAVY),
            ("Model Router", "per-sensitivity routing", PURPLE)]
    for row, y in ((row1, 57), (row2, 47)):
        for i, (t, s, c) in enumerate(row):
            dg._box(ax, 25 + i * 40, y, 36, 8, [(t, True, 9.2, c), (s, False, 7.4, MUT)],
                    fill=LIGHT[c], edge=c, accent=c, round_r=1.8)
    # platform -> connectors / llm serving
    dg._arrow(ax, 45, 39.4, 45, 33.6, color=MUT, lw=1.4)
    dg._arrow(ax, 105, 39.4, 105, 33.6, color=MUT, lw=1.4)
    dg._box(ax, 45, 28, 78, 9,
            [("Connector framework", True, 9.5, GREEN),
             ("+ PIH-specific: ManageEngine SDP · Egnyte · SolarWinds ARM · Palo Alto/Fortinet",
              False, 7.6, MUT)],
            fill=LIGHT[GREEN], edge=GREEN, accent=GREEN, round_r=2.0)
    dg._box(ax, 105, 28, 40, 9,
            [("LLM serving", True, 9.5, AMBER),
             ("PIH Azure tenant (Qatar) ·\nprivate GPU · Azure OpenAI", False, 7.2, MUT)],
            fill=LIGHT[AMBER], edge=AMBER, accent=AMBER, round_r=2.0)
    # connectors -> target systems
    targets = [("ManageEngine SDP", "system of record", 15), ("AD / Entra ID", "identity", 40),
               ("M365 / Exchange", "collaboration", 65), ("SuccessFactors · Oracle", "HR / ERP", 90),
               ("Egnyte · ARM · Firewalls", "content · access · network", 115)]
    for t, s, cx in targets:
        dg._arrow(ax, min(max(cx, 12), 84) if cx <= 84 else 84, 23.2, cx, 18.4, color=MUT, lw=1.1, rad=0.0)
        dg._box(ax, cx, 13, 24, 8.5, [(t, True, 7.8, NAVY), (s, False, 6.8, MUT)],
                fill="#FFFFFF", edge=NAVY, accent=NAVY, round_r=1.6)
    ax.text(65, 4.2, "Every action is policy-checked, mandated, logged and replayable · "
                     "ManageEngine ServiceDesk Plus remains the ITSM system of record",
            ha="center", fontsize=8.4, color=MUT, style="italic")
    return dg._save(fig, "pih_helpdesk_architecture.png")


ARCH_PNG = build_architecture_diagram()

doc = Document(SRC)

# body style used by the gdoc export
BODY_STYLE = None
for p in doc.paragraphs:
    if p.style is not None and p.style.name == "normal":
        BODY_STYLE = p.style
        break


# ------------------------------------------------------------------ helpers
def find(prefix, style=None):
    for p in doc.paragraphs:
        if p.text.strip().startswith(prefix) and (style is None or (p.style and p.style.name == style)):
            return p
    raise SystemExit(f"ANCHOR NOT FOUND: {prefix!r}")


def delete(p):
    p._p.getparent().remove(p._p)


def set_text(p, text, bold_lead=None):
    """Replace a paragraph's runs, keeping its style. bold_lead = optional bold prefix."""
    for r in list(p.runs):
        r._r.getparent().remove(r._r)
    if bold_lead:
        r = p.add_run(bold_lead)
        r.bold = True
    p.add_run(text)
    return p


def insert_after(anchor, text="", style=None, bold_lead=None):
    new_p = OxmlElement("w:p")
    anchor._p.addnext(new_p)
    para = Paragraph(new_p, anchor._parent)
    if style is not None:
        para.style = style
    elif BODY_STYLE is not None:
        para.style = BODY_STYLE
    if bold_lead:
        r = para.add_run(bold_lead)
        r.bold = True
    if text:
        para.add_run(text)
    return para


def insert_block(anchor, items):
    """items: list of (kind, text) with kind in {'h2','h3','p','b:<lead>'}. Returns last para."""
    cur = anchor
    for kind, text in items:
        if kind == "h2":
            cur = insert_after(cur, text, style=doc.styles["Heading 2"])
        elif kind == "h3":
            cur = insert_after(cur, text, style=doc.styles["Heading 3"])
        elif kind.startswith("b:"):
            cur = insert_after(cur, text, bold_lead=kind[2:])
        else:
            cur = insert_after(cur, text)
    return cur


def insert_picture_after(anchor, path, width_cm=15.5):
    para = insert_after(anchor, "")
    para.add_run().add_picture(path, width=Cm(width_cm))
    return para


from docx.shared import Pt, RGBColor  # noqa: E402

_NAVY_HEX = "0B2545"; _PANEL_HEX = "F3F5F8"
_WHITE = RGBColor(0xFF, 0xFF, 0xFF)


def _shade_cell(cell, hexfill):
    from docx.oxml.ns import qn
    sh = OxmlElement("w:shd"); sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), hexfill)
    cell._tc.get_or_add_tcPr().append(sh)


def _tbl_borders(tbl, color="D7DCE3", sz=4):
    from docx.oxml.ns import qn
    b = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}"); e.set(qn("w:val"), "single"); e.set(qn("w:sz"), str(sz))
        e.set(qn("w:space"), "0"); e.set(qn("w:color"), color); b.append(e)
    tbl._tbl.tblPr.append(b)


def insert_table_after(anchor, headers, rows, widths=None, bold_col0=True, font_size=9):
    """Build a styled table and move it right after `anchor`. Returns a spacer paragraph after it."""
    tbl = doc.add_table(rows=len(rows) + 1, cols=len(headers))
    tbl.allow_autofit = False
    _tbl_borders(tbl)
    for j, h in enumerate(headers):
        c = tbl.cell(0, j); c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold = True; r.font.size = Pt(font_size); r.font.color.rgb = _WHITE
        _shade_cell(c, _NAVY_HEX)
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            c = tbl.cell(i + 1, j); c.text = ""
            r = c.paragraphs[0].add_run(val)
            r.font.size = Pt(font_size)
            if j == 0 and bold_col0:
                r.bold = True
            if i % 2:
                _shade_cell(c, _PANEL_HEX)
    if widths:
        for r_ in tbl.rows:
            for j, w in enumerate(widths):
                r_.cells[j].width = Cm(w)
    anchor._p.addnext(tbl._tbl)
    spacer = OxmlElement("w:p")
    tbl._tbl.addnext(spacer)
    return Paragraph(spacer, anchor._parent)


def paras_between(start, end_prefixes):
    """Paragraphs strictly after `start` until a paragraph starting with any end prefix."""
    out, seen = [], False
    for p in doc.paragraphs:
        if p._p is start._p:
            seen = True
            continue
        if seen:
            t = p.text.strip()
            if any(t.startswith(e) for e in end_prefixes):
                break
            out.append(p)
    return out


# ============================================================ P2 — EXEC SUMMARY
h_exec = find("Executive Summary", "Heading 1")
for p in paras_between(h_exec, ["Scope Of Work Response"]):
    delete(p)

insert_block(h_exec, [
    ("h2", "Our understanding of your need"),
    ("p", "PIH operates one of the region's most demanding IT service environments: approximately "
          "12,200 active users across 145+ companies, 289+ locations and 25 countries, generating "
          "around 5,800 support tickets per month (~70,000 a year) — in addition to the task volume "
          "already absorbed by the 39 automation use cases in production. Automation is proven at "
          "PIH; what limits it today is the platform: a workflow-automation model that is rule-based "
          "rather than agentic, without a credible roadmap toward agentic AI and LLM technologies, "
          "and with SLA performance below expectations."),
    ("p", "You are not asking for another chatbot. You are asking for “the new Leena”: a "
          "next-generation, AI-driven service layer that consolidates all 39 existing use cases onto "
          "one scalable platform, deflects and automates the residual ticket load, integrates deeply "
          "with your landscape (Microsoft Teams, ServiceDesk Plus, on-prem AD and Entra ID, Egnyte, "
          "SolarWinds ARM, Palo Alto/Fortinet), delivers real-time KPIs and ROI, adds proactive "
          "operations and root-cause analysis, and leaves your IT team in control — trained, "
          "autonomous, and free of vendor lock-in. ManageEngine ServiceDesk Plus remains the ITSM "
          "system of record throughout."),
    ("h2", "Our proposed solution"),
    ("p", "Datategy proposes Agentium, our agent orchestration, building and evaluation platform, "
          "deployed as the intelligent layer of your service desk — a software product configured "
          "for PIH, not a bespoke development. Where the current platform executes fixed workflows, "
          "Agentium runs governed agents: they understand intent in natural language, retrieve "
          "grounded answers from your knowledge with source citations, decide within explicit "
          "business rules, and act on your systems through governed connectors — every action "
          "mandated, logged, and replayable. Your requirements map onto four systems built from one "
          "shared library of skills and connectors:"),
    ("p", "•  Conversational Service Desk & Knowledge Deflection — the multi-channel front door "
          "(Teams, portal, email): grounded, cited answers that deflect tickets before they are "
          "created; intelligent triage and routing for the rest."),
    ("p", "•  Proactive Operations & Root-Cause Analysis — trend analysis over your ticket history, "
          "recurring-incident clustering, and RCA powered by Datategy's own published research — "
          "moving the desk from reactive to preventive."),
    ("p", "•  Identity & Access Lifecycle — onboarding/offboarding and access management across "
          "AD/Entra, Microsoft 365, SuccessFactors, Oracle and SolarWinds ARM, where every "
          "privileged action runs under a signed, revocable mandate."),
    ("p", "•  Approval-Orchestrated Requests — groups, mailboxes, announcements, firewall-rule "
          "requests (Palo Alto/Fortinet): request → multi-level approval → fulfilment, with "
          "rejection, reminder and escalation branches built in."),
    ("p", "Migration of the 39 use cases is an authoring exercise, not 39 rebuilds: your existing "
          "automations decompose into ~10 reusable patterns on our Flow Builder, and their Main / "
          "Rejected / Missed / Failed branches map one-to-one to governed flow branches. We migrate, "
          "validate in parallel run, and enhance — with a phased plan, UAT, and hypercare."),
    ("h2", "What makes Datategy different"),
    ("b:Agentic-native, with a real roadmap — ",
     "Agentium is built for agents (stateful, replayable runs; a tool-calling ledger; evaluation of "
     "every output), not workflows retrofitted with AI. Our product roadmap is published, dated, and "
     "demonstrable."),
    ("b:Deployment freedom and sovereignty — ",
     "the platform runs in your Azure tenant (Qatar region), in private cloud, or fully on-premise — "
     "and can migrate between these models without rework. Models are routed per data-sensitivity "
     "tier: open-weight families (including Arabic-capable options) served privately, and/or Azure "
     "OpenAI. No per-employee licence that bills your 12,200 users whether they use the platform or "
     "not."),
    ("b:Governance you can prove — ",
     "distinct agent identity, RBAC+ABAC, signed mandates with caps and scopes, tamper-evident audit, "
     "and full replay of any past decision. Ask any vendor: can your agent prove that no firewall "
     "rule was ever posted outside its mandate? Ours can."),
    ("b:Quality is measured, not promised — ",
     "every agent ships with an evaluation harness (golden test sets including refusal cases, "
     "grounded-answer and hallucination rates, drift monitoring) and KPI dashboards reconciled "
     "against the run ledger. Our methodology is aligned with ISO/IEC 42001; Datategy sits on the "
     "French national committee (AFNOR CN IA, mirror of ISO/IEC JTC 1/SC 42) that contributes to "
     "drafting these standards."),
    ("b:Proven at enterprise scale — ",
     "grounded retrieval over multi-million-chunk technical corpora for a global industrial "
     "engineering group; predictive IT operations (AIOps) for a European automotive "
     "financial-services group; industrialised multi-agent document pipelines with normed quality "
     "(SAE J2450) for a major European automotive manufacturer."),
    ("b:You own it at the end — ",
     "structured enablement (admin, builder and end-user tracks), knowledge transfer, and a platform "
     "your team extends without us. We are a software editor, not a body shop: our success is your "
     "autonomy."),
    ("h2", "Delivery and value"),
    ("p", "We propose a phased engagement: a foundation phase, then a pilot wave (conversational "
          "deflection in production, proactive detectors, identity flows in parallel-run, one "
          "approval-orchestrated flow end-to-end) with client-confirmed baselines; then wave-based "
          "migration and enhancement of all 39 use cases, and scale-out across entities — each wave "
          "closing with quality gates and ≥30 days of hypercare. At your volumes, a 30–40% "
          "deflection/automation rate on the residual ~70,000 tickets represents 5,000–7,000 "
          "analyst-hours per year returned to higher-value work — measured live in the platform's "
          "value cockpit, so each wave justifies the next. The run model is a flat editor licence "
          "with operations internalised in your team, designed to remain below your current "
          "conversational platform's annual cost."),
    ("p", "Datategy is a French AI software editor, EU Trusted AI-labelled, UGAP-referenced, and a "
          "contributor to European AI standards. We would be proud to make PIH's service desk the "
          "region's reference for sovereign, governed, agentic IT operations — and a foundation "
          "consistent with PIH's wider AI ambitions."),
])

# ============================================================ scope fixes
p_scale = find("The AI module will be implemented to support the organization")
set_text(p_scale,
         "The AI module will be implemented to support the organization's enterprise environment of "
         "approximately 12,200 active users across 145+ companies, 289+ locations, and 25 countries, "
         "handling approximately 5,800 support tickets per month (~70,000 per year) in addition to the "
         "volumes already automated. It will be designed to improve service quality, reduce manual "
         "workload, increase ticket deflection, accelerate request fulfilment, enhance SLA performance, "
         "and provide a more modern user experience without disrupting the existing ITSM operating model.")

p_integ = find("The AI module will also integrate with enterprise systems")
set_text(p_integ,
         "The AI module will also integrate with the enterprise systems required to execute the 39 "
         "automation use cases. These may include Active Directory and Azure AD / Entra ID, Microsoft "
         "365 and Exchange, Microsoft Teams, SAP SuccessFactors, SAP, Oracle Symphony, Egnyte, "
         "SolarWinds ARM, Palo Alto / Fortinet firewalls, printer management systems, endpoint "
         "management tools, IT databases, dashboards and knowledge repositories. The current "
         "conversational stack (Daizy / Leena AI / QWIK BOT) is handled as a migration and coexistence "
         "scope — parallel run during the transition, then decommissioning — rather than as a permanent "
         "integration. Each integration will be designed with appropriate authentication, "
         "authorization, data protection, logging, monitoring, and error-handling mechanisms.")

# ============================================================ P1 — TECHNICAL REFRAME
# --- architecture diagram (RFP §6.1 requires an end-to-end diagram)
h_arch = find("Main Architecture Layers", "Heading 2")
pic_para = insert_picture_after(h_arch, ARCH_PNG, 16.0)
cap = insert_after(pic_para, "End-to-end solution architecture — channels, Agentium platform, connector "
                             "framework, target systems and LLM serving options.")
for r in cap.runs:
    r.italic = True

# --- 1. Agentium
h_ag = find("1. Agentium", "Heading 3")
for p in paras_between(h_ag, ["2. Python Backend"]):
    delete(p)
last = insert_block(h_ag, [
    ("p", "Agentium is Datategy's agent orchestration, building and evaluation platform — a software "
          "product, not a bespoke development. The AI Help Desk module proposed in this offer is an "
          "instance of Agentium deployed and configured for PIH. The platform natively provides:"),
    ("p", "•  a visual Flow Builder to author, version and roll back agent workflows — the 39 use "
          "cases are authored as flows on a shared library of skills and connectors, not coded one by one;"),
    ("p", "•  a stateful run engine: every execution is recorded, resumable and replayable, with "
          "checkpoints and full lineage;"),
    ("p", "•  a skills & connector registry of typed, reusable components;"),
    ("p", "•  an evaluation engine: automatic scoring, golden test sets, thresholds and human review queues;"),
    ("p", "•  control policies and mandates: allowed actions, caps, scopes and approval gates "
          "(human-in-the-loop), enforced by construction;"),
    ("p", "•  a tamper-evident audit ledger of every tool call and decision;"),
    ("p", "•  an administration cockpit and value dashboards;"),
    ("p", "•  a model router for sovereign and/or cloud LLM serving."),
    ("p", "Because these capabilities are product features, project effort concentrates on "
          "configuration and use-case authoring rather than platform development — which is what makes "
          "the 39-use-case migration fast, consistent and maintainable. Agentium follows a published "
          "product roadmap with regular releases, directly addressing the requirement for a credible "
          "agentic-AI and LLM trajectory."),
    ("b:Product vs configuration vs custom — ",
     "Product: the Agentium platform (all components below). Configuration: the 39 use-case flows, "
     "knowledge ingestion, policies and dashboards. Custom development: only the PIH-specific "
     "connectors (ManageEngine ServiceDesk Plus, Egnyte, SolarWinds ARM, Palo Alto/Fortinet), built as "
     "reusable catalogue components."),
    ("b:Engineering foundation — ",
     "Agentium is neither a black box nor a from-scratch reinvention. It binds proven open-source "
     "engines — FastAPI, PostgreSQL, Qdrant, Keycloak, Celery, and on-premise model servers (Ollama / "
     "vLLM / TGI) — under an orchestration kernel engineered in-house. We deliberately did not adopt "
     "generic agent frameworks (LangGraph, CrewAI, AutoGen): the kernel is built for determinism, "
     "stateful replay, governance and auditability — properties an enterprise service desk requires "
     "and generic frameworks do not guarantee. On top of this foundation, Datategy adds its own "
     "engineering: deterministic token budgeting, query-adaptive retrieval fusion, the evaluation "
     "loop, tamper-evident audit, and per-workspace knowledge isolation."),
])

# --- 2. Python backend → Agentium run engine (full rewrite, drop draft bullets)
h_be = find("2. Python Backend", "Heading 3")
set_text(h_be, "2. Run Engine & Orchestration (Agentium Product Runtime)")
for p in paras_between(h_be, ["3. Custom Connector Layer"]):
    delete(p)
insert_block(h_be, [
    ("p", "The orchestration layer is the Agentium product runtime — not a bespoke backend developed "
          "for PIH. It is the controlled bridge between agents, connectors, LLM services, the "
          "administration cockpit, ManageEngine and enterprise systems, exposed through governed APIs "
          "(FastAPI, with SSE streaming for conversational surfaces)."),
    ("p", "Every execution is a Run following the platform's canonical chain — System → Run → "
          "Evaluation → Decision → Action — through a six-phase lifecycle: Initialize → Plan → "
          "Execute → Observe → Evaluate → Adapt. Concretely:"),
    ("p", "•  Stateful and replayable — immutable flow snapshots and checkpoints; any run can be "
          "resumed, replayed identically, or resubmitted with overrides; parent-child lineage is "
          "preserved for audit."),
    ("p", "•  Execution modes — real-time (conversational), scheduled (batch), event-driven (HR or "
          "monitoring triggers), continuous monitoring, and human-augmented: the same governed "
          "runtime serves all 39 use cases."),
    ("p", "•  Skill invocations — every tool call is typed, permission-checked, bounded in retries, "
          "timestamped and costed in the invocation ledger."),
    ("p", "•  Approvals and exceptions — approval gates, reminder and escalation logic, and the "
          "Main / Rejected / Missed / Failed paths are first-class flow constructs, not custom code."),
    ("p", "•  Asynchronous scale — long-running work executes on asynchronous workers (Celery), "
          "sized for PIH's concurrency across 145+ companies."),
    ("p", "These are product features of the runtime; the project configures them. No bespoke "
          "backend is developed for PIH — which is precisely what keeps delivery fast and the "
          "platform upgradable release after release."),
])

# --- 3. Connector layer
h_cn = find("3. Custom Connector Layer", "Heading 3")
set_text(h_cn, "3. Connector Layer (Platform Framework + PIH-Specific Connectors)")
p_cn1 = find("The connector layer provides secure, reusable integrations")
set_text(p_cn1,
         "Connectors are built on Agentium's connector framework, which standardises authentication, "
         "error handling, retries, logging, permission validation and response normalisation. Existing "
         "catalogue connectors are reused where available; the PIH-specific connectors (ManageEngine "
         "ServiceDesk Plus, Egnyte, SolarWinds ARM, Palo Alto / Fortinet) are developed on the "
         "framework and delivered as reusable catalogue components.")

# --- 4. React portal → cockpit
h_fe = find("4. React Frontend Portal", "Heading 3")
set_text(h_fe, "4. Administration Cockpit (Agentium)")
p_fe1 = find("The light React frontend portal will be used mainly")
set_text(p_fe1,
         "The administration surface is provided by Agentium's cockpit — a product interface used by "
         "IT administrators, service owners, and authorized support teams. No custom portal "
         "development is required.")
p_fe2 = find("The portal is not intended to replace ManageEngine")
set_text(p_fe2, "The cockpit does not replace ManageEngine; it is used to manage the AI automation layer.")

# --- 5. PostgreSQL → platform data layer
h_db = find("5. PostgreSQL Database", "Heading 3")
set_text(h_db, "5. Platform Data Layer (PostgreSQL & Vector Store)")
p_db1 = find("PostgreSQL will act as the persistence layer")
set_text(p_db1,
         "PostgreSQL acts as the relational persistence layer of the platform; a vector store powers "
         "grounded knowledge retrieval with source citations. All data is workspace-scoped, enabling "
         "strict segregation across PIH's 145+ companies and entities.")

# --- 6. LLM layer → sovereign model router
h_llm = find("6. LLM Layer", "Heading 3")
set_text(h_llm, "6. Model Layer — Sovereign Model Router")
p_llm1 = find("The LLM layer provides natural language and reasoning")
set_text(p_llm1,
         "LLM serving goes through Agentium's model router: models are selected per task and per "
         "data-sensitivity tier, and can run as open-weight models served privately (in PIH's Azure "
         "tenant, private cloud or on-premise) and/or as Azure OpenAI endpoints. For "
         "English-and-Arabic coverage — required across PIH's 25 countries — candidate open families "
         "include Fanar (Qatar's sovereign Arabic model), Jais, ALLaM, and strong multilingual models "
         "such as Qwen; exact model versions are pinned at foundation stage and benchmarked on PIH's "
         "golden sets. Agents are model-agnostic and can be migrated to alternative models without "
         "rework; a deterministic token budget keeps inference cost predictable.")
p_guard = find("A guardrail layer sit between")
set_text(p_guard,
         "A guardrail layer sits between the backend and the LLMs — a native platform capability — to enforce:")

# --- Table 1 (architecture layers) cell updates
t1 = doc.tables[0]
t1.cell(1, 1).text = "Microsoft Teams, email, web portal"
t1.cell(2, 1).text = "Agentium platform — Flow Builder, agents, evaluation"
t1.cell(3, 1).text = "Agentium run engine (product runtime — FastAPI, stateful runs, Celery workers)"
t1.cell(3, 2).text = "Product runtime serving all integrations, orchestration and business logic — no bespoke backend"
t1.cell(4, 1).text = "Agentium connector framework + PIH-specific connectors"
t1.cell(4, 2).text = ("Controlled integration with ManageEngine, Azure AD, Teams, email, Egnyte, "
                      "SolarWinds ARM, and firewalls")
t1.cell(7, 1).text = "Sovereign model router (open-weight and/or Azure OpenAI)"
t1.cell(8, 1).text = "RBAC + ABAC, mandates & control policies, guardrails, tamper-evident audit"

# --- Table 2 (connectors): add ManageEngine SDP row
t2 = doc.tables[1]
row = t2.add_row()
row.cells[0].text = "ManageEngine SDP connector"
row.cells[1].text = ("Ticket creation, enrichment, categorization, assignment, status tracking, SLA "
                     "visibility, closure recommendations")

# ============================================================ example: fix backend wording
p_ex = find("The Python backend analyzes the request.")
set_text(p_ex, "The run engine opens a stateful, checkpointed run and analyzes the request.")

# ============================================================ P3 — NEW TECHNICAL SECTIONS
anchor = find("The ITSM record remains traceable in ManageEngine.")
anchor = insert_block(anchor, [
    ("h2", "Grounded Answer Pipeline (Knowledge Deflection)"),
    ("p", "Deflection quality rests on Agentium's production answer pipeline — the same engine "
          "Datategy operates at industrial scale on multi-million-chunk technical corpora — in six "
          "stages:"),
    ("p", "•  Indexing — multi-format ingestion (PDF including scans with OCR, Office, HTML, images), "
          "chunking and metadata extraction; knowledge bases isolated per workspace and entity."),
    ("p", "•  Storage — hybrid vector store combining dense embeddings and sparse lexical signals, "
          "with PostgreSQL as system of record and object storage for artefacts."),
    ("p", "•  Query resolution — intent classification, conversation-history augmentation, corpus "
          "planning (scope inference), and decomposition when a question spans several items."),
    ("p", "•  Multi-source retrieval — dense semantic and sparse lexical (BM25-class) retrieval "
          "executed together."),
    ("p", "•  Ranking & refinement — reciprocal-rank fusion with query-adaptive weights, "
          "cross-encoder re-ranking under a strict latency budget, diversity selection and contextual "
          "compression."),
    ("p", "•  Generation & grounding — a deterministic token budget; every claim cited [n] to its "
          "source; when retrieved evidence does not support an answer, the assistant abstains or "
          "escalates to a human instead of inventing one."),
    ("p", "Each stage emits a decision trace: any answer can be explained and audited end to end — "
          "the property that makes deflection trustworthy enough to keep tickets from being opened."),
    ("h2", "Security & Identity Model"),
    ("p", "•  Identity is federated with PIH's Entra ID (OIDC / SSO); the platform enforces "
          "role-based access control across its operating roles (executive, operator, governance "
          "officer, builder, administrator) plus attribute-based conditions (entity, scope, time)."),
    ("p", "•  Every agent runs under its own identity — distinct from any user — with per-agent "
          "credentials and a signed mandate: allowed actions, caps, scopes, validity period, and "
          "one-click revocation."),
    ("p", "•  Control policies enforce guardrails at run time: allowed models per data-sensitivity "
          "tier, maximum cost per decision, latency ceilings, and mandatory human review below a "
          "confidence threshold."),
    ("p", "•  Auditability is layered: run ledger, skill-invocation trail, decision trail, and a "
          "tamper-evident audit log — all exportable to PIH's SIEM and reporting tools."),
    ("h2", "Proactive Operations & Root-Cause Analysis"),
    ("p", "Beyond reactive ticket handling, the module ships a proactive layer (RFP §4.5):"),
    ("p", "•  Trend analysis over 12–24 months of ServiceDesk Plus history: recurring-incident "
          "clustering and pattern detection across categories, sites and companies;"),
    ("p", "•  Root-cause analysis: Datategy's failure-analysis research (published in a peer-reviewed "
          "journal) applied to IT operations — grounded, cited explanations of why incidents recur, "
          "with remediation recommendations;"),
    ("p", "•  Proactive detectors that prevent tickets before they are raised (e.g. password-expiry "
          "campaigns, device-offline detection, data-synchronisation validation) — several of the 39 "
          "use cases already belong to this class and will be delivered in the first wave;"),
    ("p", "•  Continuous improvement: RCA findings feed the knowledge base and the automation backlog."),
    ("h2", "Evaluation & Quality Framework"),
    ("p", "Every agent ships with an evaluation harness — quality is measured, not assumed:"),
    ("p", "•  golden test sets per use case, including refusal cases (actions the agent must never take);"),
    ("p", "•  grounded-answer and hallucination rates for conversational answers — every claim cited "
          "to a source;"),
    ("p", "•  parallel-run validation before any privileged automation goes live: agent output "
          "compared with human output on identical requests;"),
    ("p", "•  thresholds and review queues: low-confidence outputs route to humans, and corrections "
          "are reinjected into the system;"),
    ("p", "•  drift monitoring and prompt-regression testing in production."),
    ("p", "Our delivery methodology is aligned with ISO/IEC 42001 (AI management systems) and ISO/IEC "
          "12792 (AI transparency). Datategy is a member of the AFNOR AI standardisation committee "
          "(CN IA), the French national mirror of ISO/IEC JTC 1/SC 42 that contributes to drafting "
          "these standards."),
    ("h2", "KPIs, Analytics & ROI Cockpit"),
    ("p", "The module provides executive and operational dashboards, reconciled with the execution "
          "ledger (RFP §4.3): MTTR by category, priority and team; ticket-deflection rate; automation "
          "effectiveness per use case; first-contact resolution; user-satisfaction scores; SLA "
          "compliance; and cost-saving / ROI views. All metrics are exportable via API for "
          "consolidation into corporate reporting."),
    ("h2", "Deployment Options & Data Residency"),
    ("p", "The platform deploys indifferently in three models, and can migrate between them without "
          "rework (RFP §6.1):"),
    ("p", "•  Option A — PIH Azure tenant (recommended for pilot and run): deployed in your own "
          "subscription (Azure Qatar region available); data remains in your tenant and jurisdiction; "
          "models served as open-weight on GPU instances and/or through Azure OpenAI. The fastest "
          "path — no hardware procurement — and consistent with a lean, predictable run budget;"),
    ("p", "•  Option B — private cloud / on-premise: for reinforced-security scopes, up to fully "
          "air-gapped operation with locally served models;"),
    ("p", "•  Option C — hybrid: platform in the tenant, sensitive inference on private GPU capacity, "
          "routed automatically by data classification."),
    ("p", "This freedom is structural: agents are model- and infrastructure-agnostic, so PIH's "
          "data-residency trajectory is never locked to a vendor's hosting choice."),
])
try:
    anchor = insert_picture_after(anchor, os.path.join(DIAG, "d5_deployment.png"), 15.5)
except Exception as e:
    print("note: deployment diagram not embedded:", e)
anchor = insert_block(anchor, [
    ("h2", "Coexistence & Migration from the Current Conversational Platform"),
    ("p", "The 39 use cases currently run on the incumbent conversational stack (Daizy / Leena AI / "
          "QWIK BOT). Migration follows assess → author → parallel-run → cut-over, wave by wave: each "
          "flow is re-authored on the Flow Builder, validated against legacy behaviour on identical "
          "inputs, then switched channel by channel. The legacy platform is kept in coexistence during "
          "the transition and decommissioned once its use cases have passed acceptance — no service "
          "interruption, and users keep a single front door (Teams / portal) throughout."),
])

# ============================================================ delivery-phase naming
h_ph = find("Phase 1 - 8 : Core", "Heading 2")
set_text(h_ph, "Phases 1–3 : Use-Case Delivery Waves (Factory Model)")

# Phase 0 paragraph still lists custom components — align with product framing
p_ph0 = find("The project will start with a foundation phase")
set_text(p_ph0,
         "The project will start with a foundation phase focused on architecture validation, security "
         "design, environment setup, integration readiness, and platform baseline configuration. "
         "During this phase, the Agentium platform will be deployed and configured — run engine, "
         "administration cockpit, data layer (PostgreSQL and vector store), model router and LLM "
         "connectivity, API management, authentication (Entra ID / SSO), audit logging — together "
         "with the initial ManageEngine integration. This foundation creates a reusable delivery "
         "framework for the 39 use cases and prevents each automation from being built as an "
         "isolated development.")

# ============================================================ Enablement & CoE (before Planning)
h_plan = find("Planning", "Heading 1")
# insert enablement section just before Planning: anchor on the paragraph preceding it —
# simplest: insert after the last delivery-approach paragraph
p_last_delivery = find("This delivery approach provides a scalable and controlled")
insert_block(p_last_delivery, [
    ("h2", "Delivery Engine & Team Enablement"),
    ("p", "Delivery is carried by Datategy's AI & Data Center of Excellence — our dedicated delivery "
          "engine combining senior architecture and QA with a nearshore build capacity, whose flagship "
          "domain is precisely intelligent IT service-desk automation (agentic + automation "
          "convergence), with Arabic-language AI expertise and regional reach. This capacity is "
          "included in the package and active from day one — it is what makes the commercial model "
          "below possible."),
    ("p", "Adoption and autonomy on the PIH side are treated as first-class deliverables (RFP §4.7), "
          "through the Datategy Academy programme: role-based enablement tracks for end users "
          "(self-service and conversational usage), IT agents (exception handling and review queues), "
          "administrators (cockpit, policies, connectors), and builders — enabling PIH to author new "
          "automations autonomously on the Flow Builder. Optionally, from the second wave, PIH "
          "builders can co-author use cases with our team (pair-authoring) to accelerate autonomy. "
          "Documentation, operating procedures and a train-the-trainer pack are included: after "
          "handover, new use cases are authored by PIH at marginal cost, with Datategy in editor "
          "support."),
])

# ============================================================ Planning content (roadmap table)
set_text(h_plan, "Implementation Roadmap & Planning")
p_intro = insert_after(h_plan,
    "The programme is delivered in a foundation phase and three waves over approximately nine months "
    "from mobilisation. Each wave has explicit entry and exit criteria, a full testing cycle, and a "
    "≥30-day hypercare period after go-live. Timings below are indicative and confirmed with PIH's "
    "sponsor and Product Owner during Phase 0.")
anchor_pl = insert_table_after(p_intro,
    ["Phase / wave", "Indicative timing", "Scope highlights", "Exit gate / go-live criteria"],
    [
        ("Phase 0 — Foundation", "Weeks 1–6",
         "Environments & security model; ManageEngine + Entra ID + Teams connectivity; knowledge "
         "ingestion; evaluation baseline & golden sets; KPI cockpit",
         "Architecture validated; connectors smoke-tested on sandbox; golden sets seeded; "
         "Finance/SLA baselines agreed"),
        ("Wave 1 — Pilot", "Months 2–4",
         "Conversational deflection live on a representative population; proactive detectors "
         "(password-expiry, device monitoring); identity flows in parallel-run / simulate; one "
         "approval-orchestrated flow end-to-end (e.g. email group creation)",
         "Measured deflection vs baseline; SLA improvement demonstrated; parallel-run report signed; "
         "UAT & security validation passed; 30-day hypercare"),
        ("Wave 2 — Core rollout", "Months 4–7",
         "Remaining use cases incl. privileged writes staged to live (offboarding, mailbox, access) "
         "under mandates & approval workflows; Egnyte, SolarWinds ARM and firewall request flows; "
         "extension to additional companies",
         "Per-use-case quality gates: UAT sign-off, parallel run for every privileged write, tested "
         "rollback; 39/39 migration validated; 30-day hypercare"),
        ("Wave 3 — Scale & proactive", "Months 7–9",
         "Multi-entity / multi-country rollout; extended RCA & trend analytics; optional Arabic UX; "
         "optimisation and handover to PIH's operations team (Datategy Academy)",
         "KPI dashboards reconciled with the run ledger; operations handed over; final acceptance "
         "signed"),
    ],
    widths=(3.0, 2.3, 6.0, 5.2))
anchor_pl = insert_block(anchor_pl, [
    ("b:Testing & migration methodology — ",
     "each of the 39 use cases follows the factory lifecycle described in the Delivery Approach "
     "(detailed design → development → unit, integration and user-acceptance testing → security "
     "validation → operational readiness review), and every migrated automation is validated in "
     "parallel run against the legacy behaviour on identical inputs before cut-over. No use case is "
     "promoted to production without meeting its predefined quality gates."),
    ("b:Illustrative calendar — ",
     "a September 2026 mobilisation places the Wave 1 pilot live in November 2026 and full completion "
     "by Q2 2027; calendar dates are confirmed at contract signature."),
    ("b:Key delivery risks & mitigations — ", ""),
])
anchor_pl = insert_table_after(anchor_pl,
    ["Risk", "Mitigation"],
    [
        ("Connector / third-party readiness (API access, service accounts)",
         "Prerequisites checklist cleared in Phase 0; connector stubs and mocks allow flow authoring "
         "before live credentials; sandbox-first integration."),
        ("Data & knowledge-base quality",
         "Phase 0 knowledge audit; cleaning and ownership per the prerequisites section; golden sets "
         "reveal gaps before go-live."),
        ("Privileged write actions (offboarding, access, firewall)",
         "Simulate / parallel-run first, then a single safe write, then staged live under mandates; "
         "tested kill switch and rollback for every write flow."),
        ("Adoption & change resistance",
         "Datategy Academy role-based training, BU communication, hypercare with reinforced support "
         "after each wave; adoption measured in the KPI cockpit."),
    ],
    widths=(6.0, 10.5))

# ============================================================ Commercial offer content
h_com = find("Commercial offer", "Heading 1")
last = insert_block(h_com, [
    ("p", "The commercial model follows three principles: (1) no per-employee licensing — costs do "
          "not scale with your 12,200 users but with the value delivered; (2) a phased build, each "
          "wave sized to pay for itself in measured savings before the next is engaged; (3) a flat, "
          "predictable run. Two commercial options are proposed; amounts in this section are orders "
          "of magnitude, finalised at contract in the separate Price Schedule."),
    ("h2", "Option 1 — IT Service Desk scope (RFP perimeter)"),
    ("b:Build — ", "fixed price per wave (Phase 0 foundation, Wave 1 pilot, Wave 2 core rollout, "
     "Wave 3 scale), covering design, flow authoring, integration, testing, deployment, training and "
     "hypercare — approximately USD 100–110k in total."),
    ("b:Run — ", "annual platform licence and editor support (product updates, security patches, "
     "level-3 support) — approximately USD 20k per year, roughly half the current conversational "
     "platform's IT licence alone. Day-to-day operations are internalised in PIH's IT operations "
     "team, trained through the Datategy Academy programme; infrastructure (Azure tenant or "
     "on-premise) remains under PIH's control and billing."),
    ("h2", "Option 2 — IT + Employee Services bundle (recommended)"),
    ("p", "Option 2 adds an Employee Services module: employee Q&A and self-service over HR policies "
          "and services (leave, documents, onboarding questions), delivered through the same channels, "
          "the same knowledge machinery and the same SuccessFactors connector already required for the "
          "IT identity-lifecycle flows. HR systems remain the systems of record — the module is a "
          "deflection and self-service layer, not HR process execution — so the marginal build cost is "
          "limited (approximately USD 15–20k on top of Option 1, i.e. ~USD 120–125k in total)."),
    ("p", "The run fee is unchanged (~USD 20k per year) and covers both scopes: editor support is "
          "platform-level, and operations are internalised in PIH's team for IT and employee services "
          "alike. This makes Option 2 the rational choice: one front door for employees across IT and "
          "HR questions, the full replacement of the current conversational stack, and a total cost of "
          "ownership designed to remain below the organisation's current combined "
          "conversational-platform spend across IT and employee services — while converting rented "
          "workflows into an owned, agentic platform."),
    ("h2", "What makes these prices possible"),
    ("p", "Three structural levers — not a discount. (1) The build is delivered end-to-end by "
          "Datategy's AI & Data Center of Excellence, our dedicated nearshore delivery engine, active "
          "from day one at a fraction of on-shore day rates, under senior Paris-based architecture and "
          "QA. (2) The factory effect: the 39 use cases decompose into ~10 reusable patterns, so cost "
          "falls wave on wave as second instances of each pattern are authored, not rebuilt. (3) "
          "AI-assisted delivery across the build track. The savings are structural because the "
          "platform and the delivery engine are products of the same house."),
    ("b:Options (both variants) — ", "managed AgentOps (per-agent monthly fee) if PIH prefers "
     "outsourced operations; additional use cases, connectors and entities at the rate card; Arabic "
     "user-experience package; extended support coverage."),
    ("p", "The run fee is bound to the perimeter of the selected option (systems, domains and "
          "companies listed in this offer); material extensions — new entities, new domains — are "
          "handled through the same wave model. A detailed Price Schedule is provided as a separate "
          "annex."),
])
last = insert_after(last, "Pricing summary (order of magnitude, USD excl. taxes):")
for r in last.runs:
    r.bold = True
last = insert_table_after(last,
    ["Component", "Option 1 — IT scope", "Option 2 — IT + Employee Services (recommended)", "Indicative timing"],
    [
        ("Phase 0 — Foundation", "≈ USD 25k", "≈ USD 25k", "Weeks 1–6"),
        ("Wave 1 — Pilot", "≈ USD 43k", "≈ USD 43k", "Months 2–4"),
        ("Wave 2 — Core rollout", "≈ USD 28k", "≈ USD 28k", "Months 4–7"),
        ("Wave 3 — Scale & proactive", "≈ USD 12k", "≈ USD 12k", "Months 7–9"),
        ("Employee Services module (HR deflection & self-service)", "—", "≈ USD 15k", "Delivered with Waves 2–3"),
        ("Total build (one-time, phased)", "≈ USD 108k", "≈ USD 123k", "≈ 9 months"),
        ("Annual run — licence & editor support", "USD 20k / year", "USD 20k / year (covers both scopes)", "From Wave 1 go-live"),
        ("Indicative 3-year TCO (build + 3× run)", "≈ USD 168k", "≈ USD 183k", "—"),
    ],
    widths=(5.4, 3.2, 4.6, 3.3))
insert_after(last,
    "Each wave is a fixed price engaged on the results of the previous one; the detailed day-based "
    "build-up per role and wave is provided in the Price Schedule annex.")

# ============================================================ Support & References (append at end)
doc.add_heading("Support & Maintenance", level=1)
p = doc.add_paragraph(style=BODY_STYLE)
p.add_run("Editor support is included in the run fee: quarterly platform releases, security patches, "
          "and level-3 support with business-hours coverage aligned on Qatar time. Indicative incident "
          "response targets: P1 — 4 business hours; P2 — next business day; P3/P4 — planned with the "
          "release cycle. Hypercare (≥30 days) follows each wave go-live with reinforced coverage. "
          "Platform updates are non-breaking for authored flows: every release is regression-tested "
          "against PIH's golden sets before rollout. 24/7 coverage and managed AgentOps are available "
          "as priced options.")

doc.add_heading("Experience & References", level=1)
p = doc.add_paragraph(style=BODY_STYLE)
p.add_run("Datategy is a French AI software editor founded in 2016 — EU Trusted AI-labelled, "
          "UGAP-referenced for the French public market, and a member of the AFNOR AI standardisation "
          "committee (CN IA / ISO/IEC JTC 1 SC 42). Three references representative of this engagement "
          "(details and reference interviews available under NDA at shortlist stage):")
for txt in [
    "Enterprise knowledge & retrieval at industrial scale — a grounded, cited assistant over a "
    "multi-million-chunk technical corpus for a global industrial engineering group: hybrid "
    "retrieval, evaluation harness, expert knowledge capture.",
    "Predictive IT operations (AIOps) — proactive prevention of critical IT incidents for a European "
    "automotive financial-services group: large-scale log and metric ingestion, time-series "
    "forecasting, explainable alerts adopted by the IT teams.",
    "Governed multi-agent document pipelines — industrialised translation and QA chains with normed "
    "quality measurement (SAE J2450) and human-in-the-loop review for a major European automotive "
    "manufacturer: agent-per-error-class design, golden-set gating, measured ROI.",
]:
    p = doc.add_paragraph(style=BODY_STYLE)
    p.add_run("•  " + txt)

# ============================================================ global figure sweep
for p in doc.paragraphs:
    if "12,000+" in p.text:
        set_text(p, p.text.replace("12,000+", "12,200"))

# ============================================================ save copy
doc.save(OUT)

# ---------------------------------------------------------------- fix stale static TOC
# This document uses a Google-Docs-style STATIC table of contents (literal hyperlink text,
# not a live TOC field), so renamed headings must be patched by hand here.
import zipfile
import shutil

TOC_FIXES = {
    "2. Python Backend": "2. Run Engine &amp; Orchestration",
    "3. Custom Connector Layer": "3. Connector Layer (Platform + PIH-Specific)",
    "4. React Frontend Portal": "4. Administration Cockpit (Agentium)",
    "5. PostgreSQL Database": "5. Platform Data Layer (PostgreSQL &amp; Vector Store)",
    "6. LLM Layer": "6. Model Layer — Sovereign Model Router",
    "Phase 1 - 8 : Core": "Phases 1–3 : Use-Case Delivery Waves",
    "6. Planning": "6. Implementation Roadmap &amp; Planning",
}

tmp = OUT + ".tmp"
with zipfile.ZipFile(OUT, "r") as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename == "word/document.xml":
            xml = data.decode("utf-8")
            for old, new in TOC_FIXES.items():
                xml = xml.replace(f">{old}<", f">{new}<")
            data = xml.encode("utf-8")
        zout.writestr(item, data)
shutil.move(tmp, OUT)

print("saved:", OUT)
print("NOTE: static TOC entries patched for renamed sections. New H1/H2 sections added by this "
      "script (Grounded Answer Pipeline, Security & Identity, Proactive Ops & RCA, Evaluation & "
      "Quality, KPIs, Deployment Options, Coexistence & Migration, Team Enablement, Support & "
      "Maintenance, Experience & References) have NO static TOC entry — regenerate a live Table of "
      "Contents (Google Docs: Insert > Table of contents) after import to pick them up.")
