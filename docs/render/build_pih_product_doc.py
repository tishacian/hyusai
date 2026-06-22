# -*- coding: utf-8 -*-
"""Assemble the Agentium product overview (.docx) for PIH.

Executive-light, English, branded. Capabilities are presented as a finished
product (no maturity tags); PIH-clean (no internal codenames or other client
names). Diagrams are rendered by pih_diagrams.py and embedded.
"""
import os
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.section import WD_SECTION
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

import pih_diagrams as dg

HERE = os.path.dirname(os.path.abspath(__file__))
DIAG = os.path.join(HERE, "assets", "diagrams")
SCREENS = os.path.join(HERE, "assets", "screens")
LOGO = os.path.join(HERE, "assets", "logo_datategy.png")
OUT = os.path.join(HERE, "out", "Agentium-Product-Overview-PIH.docx")

# ---------------------------------------------------------------- palette
def C(h):
    return RGBColor.from_string(h)

NAVY   = C("0B2545")
BLUE   = C("2D6CDF")
PURPLE = C("6D28D9")
GREEN  = C("0E8F62")
AMBER  = C("B45309")
INK    = C("151A23")
MUT    = C("596371")
LINE   = "D7DCE3"
PANEL  = "F3F5F8"
WHITE  = C("FFFFFF")
TINT = {"NAVY": "E7ECF4", "BLUE": "E5EDFB", "PURPLE": "EFE8FB",
        "GREEN": "E2F2EC", "AMBER": "F6ECE0"}
BODY = "Arial"


# ---------------------------------------------------------------- low-level helpers
def _shade(cell, hexfill):
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto")
    sh.set(qn("w:fill"), hexfill)
    cell._tc.get_or_add_tcPr().append(sh)


def _cell_margins(cell, top=60, bottom=60, left=120, right=120):
    tcPr = cell._tc.get_or_add_tcPr()
    m = OxmlElement("w:tcMar")
    for tag, val in (("top", top), ("bottom", bottom), ("start", left),
                     ("end", right), ("left", left), ("right", right)):
        e = OxmlElement(f"w:{tag}")
        e.set(qn("w:w"), str(val))
        e.set(qn("w:type"), "dxa")
        m.append(e)
    tcPr.append(m)


def _set_borders(table, color=LINE, sz=4):
    tblPr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "single")
        e.set(qn("w:sz"), str(sz))
        e.set(qn("w:space"), "0")
        e.set(qn("w:color"), color)
        borders.append(e)
    tblPr.append(borders)


def _left_accent(cell, hexcolor, sz=24):
    tcPr = cell._tc.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    e = OxmlElement("w:left")
    e.set(qn("w:val"), "single")
    e.set(qn("w:sz"), str(sz))
    e.set(qn("w:space"), "0")
    e.set(qn("w:color"), hexcolor)
    borders.append(e)
    tcPr.append(borders)


def _runfmt(run, size, color, bold=False, italic=False, font=BODY, mono=False):
    run.font.name = "Consolas" if mono else font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color


def _cell_text(cell, text, size=10, color=INK, bold=False, align=WD_ALIGN_PARAGRAPH.LEFT,
               italic=False, mono=False):
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = align
    pf = p.paragraph_format
    pf.space_before = Pt(1)
    pf.space_after = Pt(1)
    pf.line_spacing = 1.0
    r = p.add_run(text)
    _runfmt(r, size, color, bold=bold, italic=italic, mono=mono)
    return p


def _para_bottom_border(p, color, sz=8):
    pPr = p._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    b = OxmlElement("w:bottom")
    b.set(qn("w:val"), "single")
    b.set(qn("w:sz"), str(sz))
    b.set(qn("w:space"), "4")
    b.set(qn("w:color"), color)
    pbdr.append(b)
    pPr.append(pbdr)


def _field(run, code, default=""):
    r = run._r
    f1 = OxmlElement("w:fldChar"); f1.set(qn("w:fldCharType"), "begin")
    it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve"); it.text = code
    f2 = OxmlElement("w:fldChar"); f2.set(qn("w:fldCharType"), "separate")
    t = OxmlElement("w:t"); t.text = default
    f3 = OxmlElement("w:fldChar"); f3.set(qn("w:fldCharType"), "end")
    for e in (f1, it, f2, t, f3):
        r.append(e)


# ---------------------------------------------------------------- content helpers
def heading(doc, text, level, color=None, rule=False):
    p = doc.add_heading(text, level=level)
    if color is not None:
        for r in p.runs:
            r.font.color.rgb = color
    if rule:
        _para_bottom_border(p, "C9D2DE", sz=6)
    return p


def para(doc, text, size=10.5, color=INK, bold=False, italic=False,
         before=4, after=4, align=WD_ALIGN_PARAGRAPH.LEFT, spacing=1.12):
    p = doc.add_paragraph()
    p.alignment = align
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = spacing
    r = p.add_run(text)
    _runfmt(r, size, color, bold=bold, italic=italic)
    return p


def lead(doc, runs, before=4, after=6, spacing=1.16, size=10.5):
    """A paragraph mixing styles: runs = list of (text, bold, color)."""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = spacing
    for text, bold, color in runs:
        r = p.add_run(text)
        _runfmt(r, size, color, bold=bold)
    return p


def bullet(doc, text_runs, size=10.5, before=1, after=1):
    p = doc.add_paragraph(style="List Bullet")
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = 1.1
    if isinstance(text_runs, str):
        text_runs = [(text_runs, False, INK)]
    for text, bold, color in text_runs:
        r = p.add_run(text)
        _runfmt(r, size, color, bold=bold)
    return p


def image(doc, name, width=16.5, caption=None, base=None):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)
    p.add_run().add_picture(os.path.join(base or DIAG, name), width=Cm(width))
    if caption:
        c = doc.add_paragraph()
        c.alignment = WD_ALIGN_PARAGRAPH.CENTER
        c.paragraph_format.space_after = Pt(8)
        r = c.add_run(caption)
        _runfmt(r, 8.5, MUT, italic=True)
    return p


def callout(doc, title, body, accent, accent_hex, fill_hex):
    t = doc.add_table(rows=1, cols=1)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = t.cell(0, 0)
    cell.width = Cm(17)
    _shade(cell, fill_hex)
    _left_accent(cell, accent_hex, sz=36)
    _cell_margins(cell, top=120, bottom=120, left=200, right=160)
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(title.upper())
    _runfmt(r, 9, accent, bold=True, mono=True)
    p2 = cell.add_paragraph()
    p2.paragraph_format.space_before = Pt(0)
    p2.paragraph_format.line_spacing = 1.14
    r2 = p2.add_run(body)
    _runfmt(r2, 11, INK, bold=True)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def feature_table(doc, accent, accent_hex, rows, c0="Capability", c1="What it does",
                  w0=5.4, w1=11.6):
    t = doc.add_table(rows=1, cols=2)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.allow_autofit = False
    _set_borders(t, color=LINE, sz=4)
    # header
    h0, h1 = t.cell(0, 0), t.cell(0, 1)
    for c in (h0, h1):
        _shade(c, accent_hex)
        _cell_margins(c)
    _cell_text(h0, c0, size=9.5, color=WHITE, bold=True)
    _cell_text(h1, c1, size=9.5, color=WHITE, bold=True)
    for i, (a, b) in enumerate(rows):
        r = t.add_row()
        ca, cb = r.cells[0], r.cells[1]
        fill = "FFFFFF" if i % 2 == 0 else PANEL
        for c in (ca, cb):
            _shade(c, fill)
            _cell_margins(c)
        _cell_text(ca, a, size=10, color=INK, bold=True)
        _cell_text(cb, b, size=10, color=MUT)
    for r in t.rows:
        r.cells[0].width = Cm(w0)
        r.cells[1].width = Cm(w1)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def group(doc, title, accent, accent_hex, intro, rows):
    heading(doc, title, 3, color=accent)
    para(doc, intro, size=10.5, color=MUT, italic=True, before=0, after=4)
    feature_table(doc, accent, accent_hex, rows)


# ---------------------------------------------------------------- document scaffold
def build():
    dg.render_all()
    doc = Document()

    # base styles
    normal = doc.styles["Normal"]
    normal.font.name = BODY
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = INK
    normal.paragraph_format.space_after = Pt(4)
    normal.paragraph_format.line_spacing = 1.12
    for lvl, sz, col in (("Heading 1", 17, NAVY), ("Heading 2", 13.5, BLUE),
                         ("Heading 3", 11.5, INK)):
        st = doc.styles[lvl]
        st.font.name = BODY
        st.font.size = Pt(sz)
        st.font.bold = True
        st.font.color.rgb = col
        st.paragraph_format.space_before = Pt(12 if lvl == "Heading 1" else 8)
        st.paragraph_format.space_after = Pt(4)
        st.paragraph_format.keep_with_next = True

    # page geometry (A4)
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    for attr in ("top_margin", "bottom_margin"):
        setattr(sec, attr, Cm(2.0))
    sec.left_margin = sec.right_margin = Cm(2.0)

    # ===================================================== COVER (section 0)
    for _ in range(2):
        doc.add_paragraph()
    cov = doc.add_paragraph()
    cov.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cov.add_run().add_picture(LOGO, width=Cm(4.6))

    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(26)
    r = p.add_run("TECHNICAL PRODUCT OVERVIEW   ·   CONFIDENTIAL")
    _runfmt(r, 11, BLUE, bold=True, mono=True)

    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(10)
    r = p.add_run("Agentium")
    _runfmt(r, 46, NAVY, bold=True)

    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Sovereign Agent Orchestration, Building & Evaluation")
    _runfmt(r, 17, INK)

    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(28)
    r = p.add_run("Prepared for PowerMind")
    _runfmt(r, 14, MUT, bold=True)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Sovereign AI for PIH, Qatar and the region")
    _runfmt(r, 11, MUT)

    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Datategy   ·   June 2026")
    _runfmt(r, 11, MUT)

    # ===================================================== body section
    body = doc.add_section(WD_SECTION.NEW_PAGE)
    body.page_width = Cm(21.0); body.page_height = Cm(29.7)
    body.top_margin = body.bottom_margin = Cm(2.0)
    body.left_margin = body.right_margin = Cm(2.0)
    body.different_first_page_header_footer = False

    # header (body only): title left, logo right
    body.header.is_linked_to_previous = False
    htbl = body.header.add_table(1, 2, Cm(17))
    htbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    hl, hr = htbl.cell(0, 0), htbl.cell(0, 1)
    hl.width = Cm(13); hr.width = Cm(4)
    _cell_text(hl, "Agentium — Technical Product Overview", size=8, color=MUT)
    pr = hr.paragraphs[0]; pr.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    pr.add_run().add_picture(LOGO, width=Cm(1.9))
    _para_bottom_border(hl.paragraphs[0], "DCE1E8", sz=4)
    _para_bottom_border(hr.paragraphs[0], "DCE1E8", sz=4)

    # footer (body only): confidential left, page number right
    body.footer.is_linked_to_previous = False
    ftbl = body.footer.add_table(1, 2, Cm(17))
    fl, fr = ftbl.cell(0, 0), ftbl.cell(0, 1)
    fl.width = Cm(13); fr.width = Cm(4)
    _cell_text(fl, "Confidential — Datategy · Agentium", size=8, color=MUT)
    pf = fr.paragraphs[0]; pf.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    rr = pf.add_run("Page "); _runfmt(rr, 8, MUT)
    pn = pf.add_run(); _runfmt(pn, 8, MUT); _field(pn, "PAGE", "1")

    # ---- Contents
    heading(doc, "Contents", 1, color=NAVY)
    tp = doc.add_paragraph()
    _field(tp.add_run(), 'TOC \\o "1-3" \\h \\z \\u',
           "Update this field in Word (right-click → Update Field) to build the table of contents.")

    # ===================================================== 1 Executive Summary
    doc.add_page_break()
    heading(doc, "1   Executive Summary", 1, color=NAVY, rule=True)
    lead(doc, [
        ("Agentium is an operating system for intelligent systems — a single platform to ", False, INK),
        ("orchestrate, build and evaluate", True, INK),
        (" autonomous agents on infrastructure the customer fully controls.", False, INK),
    ])
    para(doc,
         "It unifies three product pillars. An agent orchestrator runs stateful, replayable and "
         "governed executions. An agent builder composes business capabilities from typed skills "
         "through a visual flow editor. An agent evaluation layer scores every execution and closes "
         "the loop with human review and governed adaptation.")
    lead(doc, [
        ("The sovereign thesis. ", True, NAVY),
        ("Unlike platforms that orchestrate models they rent from a public cloud, Agentium controls "
         "the entire stack — the models (served on-premise), the action ledger (every tool-call "
         "recorded) and the governance plane (identity, policy, audit). That control is what turns "
         "each of PIH's requirements from a checkbox into a structural advantage: sovereignty is "
         "enforced rather than promised, and auditability becomes proof rather than logs.", False, INK),
    ])
    image(doc, "d1_value_loop.png", width=16.5,
          caption="The Agentium value loop — objectives become measured, continuously improved systems.")
    heading(doc, "One unified, sovereign platform", 3, color=INK)
    para(doc,
         "Agentium is a single, unified operating system — one platform, one deployment, one "
         "sovereign boundary. Internally it is organised in capability layers: a data & "
         "machine-learning layer that builds the AI assets (pipelines, models, verticalised models), "
         "a knowledge layer that builds the enterprise memory (ingested, structured, governed "
         "knowledge), and an agentic layer that turns those assets and that memory into governed "
         "autonomous systems — with domain suites on top.")
    image(doc, "d8_portfolio.png", width=13.4,
          caption="One unified, sovereign platform — capability layers, not separate products to procure.")
    para(doc,
         "These are layers of one platform, deployed and operated as a single system — there is "
         "nothing extra to procure or stitch together. (They build on Datategy's data-science and "
         "knowledge technologies, which can also be offered standalone, but here form one integrated "
         "whole.) Models built in the data & ML layer are consumed directly by agents; agents in "
         "turn call data and knowledge services as tools — all inside the same boundary.",
         color=MUT)

    heading(doc, "At a glance — against PIH's needs", 3, color=INK)
    bullet(doc, [("Sovereignty — ", True, NAVY), ("models and data run entirely inside the customer boundary.", False, MUT)])
    bullet(doc, [("Robustness — ", True, NAVY), ("stateful runs, checkpoints, replay and resubmission with full lineage.", False, MUT)])
    bullet(doc, [("Security — ", True, NAVY), ("RBAC + ABAC, distinct agent identity and policy-based model guardrails.", False, MUT)])
    bullet(doc, [("Observability & scalability — ", True, NAVY), ("a complete tool-calling ledger, exportable audit and async enterprise scale.", False, MUT)])
    bullet(doc, [("Token performance — ", True, NAVY), ("a deterministic generation budget and adaptive retrieval fusion.", False, MUT)])

    # ===================================================== 2 The Agentium Model
    doc.add_page_break()
    heading(doc, "2   The Agentium Model", 1, color=NAVY, rule=True)
    para(doc,
         "Everything in Agentium is expressed through one canonical chain and a small set of "
         "first-class entities. This shared vocabulary is what makes the platform auditable "
         "end-to-end: a strategic decision can always be traced back to the runs, evaluations "
         "and inputs that produced it.")
    lead(doc, [
        ("System  →  Run  →  Evaluation  →  Decision  →  Action", True, NAVY),
    ], spacing=1.0, size=12)
    para(doc,
         "A System turns an objective into work. Each execution is a Run. Every Run is scored by an "
         "Evaluation. Evaluations and trends produce Decisions — a recommendation, a review request, "
         "or a policy change — and approved Decisions drive Actions, including governed replay.",
         color=MUT)
    image(doc, "d2_chain.png", width=16.5,
          caption="The canonical chain and the entities a System is composed from.")

    heading(doc, "Entity glossary", 2, color=BLUE)
    entities = [
        ("System", "A self-contained unit that receives an objective, uses capabilities, executes work and produces measurable outcomes."),
        ("Capability", "A business-level function — the atomic business promise (e.g. document understanding, contract-risk detection)."),
        ("Skill", "A cognitive primitive with typed input/output, cost, latency and version (e.g. retrieval, reasoning, scoring)."),
        ("Context", "A first-class object bundling data, documents, memory, history, environment state and business constraints."),
        ("Run", "A real execution instance of a System — the decision unit recording input, decision, cost, value and confidence."),
        ("Skill-Invocation", "A metered, versioned, auditable record of a single skill execution within a Run — the tool-calling ledger."),
        ("Evaluation", "A post-run quality assessment: composite score, hallucination and drift rates, and component-level attribution."),
        ("Decision", "A governed action — recommendation, review request or applied policy change — with an explicit approval trail."),
        ("Control Policy", "Hard guardrails: cost ceilings, latency limits, model whitelists and mandatory human-review thresholds."),
        ("Adaptive Policy", "Soft directives the runtime uses to adjust behaviour mid-run — switch model, fall back, escalate, stop."),
        ("Workspace", "The tenant boundary: members, identity, settings and strict isolation between tenants."),
    ]
    feature_table(doc, NAVY, "0B2545", entities, c0="Entity", c1="Definition", w0=4.2, w1=12.8)

    # ===================================================== 3 Orchestration Architecture
    doc.add_page_break()
    heading(doc, "3   Orchestration Architecture", 1, color=NAVY, rule=True)

    heading(doc, "3.1   Execution lifecycle", 2, color=BLUE)
    para(doc,
         "Every Run moves through six phases. The platform plans which skills to invoke, executes "
         "them while streaming output, observes cost and quality, evaluates the result against "
         "success criteria, and adapts. Adaptation is governed: the runtime may only take actions an "
         "Adaptive Policy explicitly permits, within hard Control-Policy bounds.")
    image(doc, "d3_lifecycle.png", width=16.5,
          caption="The orchestrator execution lifecycle, with policy-governed adaptive feedback.")

    heading(doc, "3.2   Stateful, replayable execution", 2, color=BLUE)
    para(doc,
         "Runs are durable. Long-running work checkpoints its progress and resumes after "
         "interruption. Each Run carries an immutable snapshot of the flow it executed, so it can be "
         "replayed months later with selective overrides — a different model, pipeline or query — "
         "while preserving full parent-child lineage. Resubmission and replay are first-class, not "
         "after-thoughts.")
    modes = [
        ("Real-time decision", "Interactive request/response", "Instant Q&A, live risk scoring"),
        ("Batch processing", "Scheduler or API", "Document batches, nightly jobs"),
        ("Event-driven automation", "Webhook, file or threshold", "New-file arrival, drift alerts"),
        ("Continuous monitoring", "Persistent observation loop", "KPI surveillance, SLA watch"),
        ("Human-augmented", "API with review gate", "Compliance review, legal sign-off"),
    ]
    t = doc.add_table(rows=1, cols=3)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.allow_autofit = False
    _set_borders(t, LINE, 4)
    hdr = ["Execution mode", "Trigger", "Typical use"]
    for j, htxt in enumerate(hdr):
        _shade(t.cell(0, j), "0B2545"); _cell_margins(t.cell(0, j))
        _cell_text(t.cell(0, j), htxt, size=9.5, color=WHITE, bold=True)
    for i, row in enumerate(modes):
        r = t.add_row()
        for j, val in enumerate(row):
            _shade(r.cells[j], "FFFFFF" if i % 2 == 0 else PANEL)
            _cell_margins(r.cells[j])
            _cell_text(r.cells[j], val, size=10, color=INK if j == 0 else MUT, bold=(j == 0))
    widths = (5.0, 5.0, 7.0)
    for r in t.rows:
        for j, wv in enumerate(widths):
            r.cells[j].width = Cm(wv)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)

    heading(doc, "3.3   The answer pipeline", 2, color=BLUE)
    para(doc,
         "When a System answers from enterprise knowledge, it runs a six-stage pipeline. Content is "
         "indexed and stored once; at query time the platform resolves intent, retrieves from "
         "multiple sources in parallel, refines within a budget, and generates a grounded, cited "
         "answer. Every stage is traced and time-budgeted, with graceful degradation under load.")
    image(doc, "d4_pipeline.png", width=16.5,
          caption="The retrieval-and-generation pipeline — six traced, budgeted stages.")

    heading(doc, "3.4   Sovereign deployment", 2, color=BLUE)
    para(doc,
         "Agentium deploys entirely within the customer's boundary. Models are served on-premise; "
         "the vector store, relational ledger and object store hold all data locally; identity, "
         "asynchronous workers and audit run alongside. No component requires an external dependency "
         "to operate, which is what makes sovereignty enforceable rather than contractual.")
    image(doc, "d5_deployment.png", width=16.0,
          caption="Reference deployment — every plane runs inside the sovereign boundary.")

    # ===================================================== 4 Engineering Foundation
    doc.add_page_break()
    heading(doc, "4   Engineering Foundation", 1, color=NAVY, rule=True)
    lead(doc, [
        ("Agentium is neither a black box nor a from-scratch reinvention. ", True, NAVY),
        ("It is built on a deliberately chosen foundation of best-in-class open-source frameworks, "
         "orchestrated and hardened into a single sovereign platform — with proprietary engineering "
         "added precisely where open source stops short of production needs.", False, INK),
    ])
    para(doc,
         "This matters for PIH on two counts. The open-source base means no opaque dependency and no "
         "single-vendor model risk: the platform can be audited, self-hosted and operated entirely "
         "in-house. The proprietary layer is where the engineering value sits — the orchestration, "
         "determinism and governance that turn capable components into a dependable, sovereign whole.")
    image(doc, "d7_foundation.png", width=16.5,
          caption="A proven open-source foundation, bound and optimised by Agentium, inside the sovereign boundary.")

    heading(doc, "4.1   The open-source foundation", 2, color=BLUE)
    para(doc, "Proven, widely adopted components — chosen for maturity, licensing and operability.",
         color=MUT, italic=True, before=0)
    feature_table(doc, GREEN, "0E8F62", [
        ("API & streaming", "FastAPI with server-sent events for low-latency, streaming responses."),
        ("Relational ledger", "PostgreSQL — the system of record for runs, decisions and audit."),
        ("Data layer & migrations", "SQLAlchemy with Alembic — typed data access and versioned schema migrations."),
        ("Vector store", "Qdrant — payload-filtered semantic search with strict scope isolation."),
        ("Identity", "Keycloak — OpenID Connect, federated authentication and key rotation."),
        ("Asynchronous workers", "Celery with a message broker for scalable background execution."),
        ("Model serving", "Ollama and self-hosted inference endpoints (e.g. vLLM, TGI) for sovereign on-prem inference."),
        ("Real-time voice", "LiveKit — self-hosted WebRTC media server for low-latency voice inside the boundary."),
        ("Embeddings", "Sentence-Transformers on PyTorch for local embedding generation."),
        ("Retrieval & ranking", "BM25 keyword search, reciprocal rank fusion and cross-encoder reranking."),
    ], c0="Layer", c1="Open-source component & role", w0=4.6, w1=12.4)

    heading(doc, "4.2   Where Agentium engineers beyond open source", 2, color=BLUE)
    para(doc, "The binding and optimisation layer — built where off-the-shelf components fall short.",
         color=MUT, italic=True, before=0)
    lead(doc, [
        ("The orchestration kernel is built in-house. ", True, NAVY),
        ("The run engine and the System → Run → Evaluation → Decision → Action model are Agentium's "
         "own — not assembled on a third-party agent-orchestration framework such as LangGraph, "
         "CrewAI or AutoGen. Best-of-breed libraries are used as pluggable adapters where useful, "
         "never as the control plane. The result is execution semantics that stay stable, fully "
         "auditable and free of a fast-moving external dependency — a deliberate choice for "
         "sovereignty and longevity.", False, INK),
    ], before=2, after=4)
    feature_table(doc, PURPLE, "6D28D9", [
        ("Orchestration runtime", "The canonical System → Run → Evaluation → Decision → Action engine, with stateful runs, checkpoints and replay."),
        ("Deterministic token budget", "Output is sized from the input-to-context ratio on a fixed schedule, with safety margins and per-latency caps — predictable cost and latency."),
        ("Query-adaptive fusion", "Dense and sparse weights adapt to each query before rank fusion, improving precision on identifiers and natural language alike."),
        ("Budgeted refinement", "Cross-encoder reranking and diversity selection run within strict time budgets, with graceful degradation under load."),
        ("Evaluation loop", "Automatic scoring, tunable thresholds, statistical gating and component-level attribution — quality is measured, not assumed."),
        ("Governance over identity", "An RBAC + ABAC policy engine and distinct agent identity layered on the identity provider."),
        ("Tamper-evident audit", "A metered, per-invocation tool-calling ledger and an exportable audit trail."),
        ("Knowledge isolation", "Strict multi-knowledge-base isolation and scoped caching, preventing cross-tenant or cross-collection leakage."),
    ], c0="Optimisation", c1="What Agentium adds", w0=4.6, w1=12.4)
    callout(doc, "The cream of open source, bound and optimised",
            "Best-of-breed components do the heavy lifting; Agentium provides the orchestration, "
            "determinism and governance that make them production-grade — and runs the entire stack "
            "sovereign and on-premise, with no external dependency required.",
            NAVY, "0B2545", TINT["NAVY"])

    heading(doc, "4.3   Reference infrastructure for sovereign hosting", 2, color=BLUE)
    lead(doc, [
        ("The entire stack runs inside the customer's boundary. ", True, NAVY),
        ("Orchestration, data plane and the models themselves run on a customer-controlled Kubernetes "
         "cluster, with complete network and tenant isolation — air-gap-capable, with no outbound "
         "calls. The figures below are an order-of-magnitude reference baseline; final sizing depends "
         "on the model mix and concurrency, and a leaner minimal profile hosts the full stack, models "
         "included, scaling to high availability without re-architecture.", False, INK),
    ])

    heading(doc, "Reference baseline (full stack, models included)", 3, color=INK)
    feature_table(doc, NAVY, "0B2545", [
        ("Accelerators", "7–9 GPUs, ~320–384 GB VRAM total (mix per the options below). Example with L40S + H100: 3× L40S 48G + 1× H100 80G + 4× L4 24G (8 GPUs, 320 GB)."),
        ("Compute", "~272 CPU cores (Xeon Gold / EPYC)."),
        ("Memory", "~1.85 TB ECC RAM."),
        ("Storage", "~19 TB local NVMe (OS + model cache); ~11 TB persistent data; 16 TB raw object storage (~10 TB usable, expandable)."),
        ("Network", "25 GbE, redundant."),
        ("Footprint", "7 servers (4 GPU + 3 data) on Kubernetes — deployed and managed by Datategy."),
    ], c0="Resource", c1="Reference", w0=3.4, w1=13.6)

    heading(doc, "GPU options — matched to available stock", 3, color=INK)
    gpu = [
        ("1 — A100 / H100 mix (preferred)", "2× H100 80G + 1× A100 80G + 4× L4 24G (7 GPUs)", "Best latency; MIG-capable"),
        ("2 — Ada only (no A100 / H100)", "5× L40S 48G + 4× L4 24G (9 GPUs)", "Wide availability; ECC"),
        ("3 — Full HBM", "3× H100 80G (or 3× A100 80G) + MIG for small models (3 GPUs)", "Maximum density"),
        ("4 — L40S only", "6× L40S 48G", "Homogeneous fleet"),
        ("5 — RTX 5090", "12× RTX 5090 32G (3× 4-GPU servers)", "Lowest CAPEX; staggered workloads; datacenter licence to confirm"),
    ]
    t = doc.add_table(rows=1, cols=3)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.allow_autofit = False
    _set_borders(t, LINE, 4)
    for j, htxt in enumerate(["Option", "Configuration", "Profile"]):
        _shade(t.cell(0, j), "0B2545"); _cell_margins(t.cell(0, j))
        _cell_text(t.cell(0, j), htxt, size=9.5, color=WHITE, bold=True)
    for i, (opt, cfg, prof) in enumerate(gpu):
        r = t.add_row()
        fill = "FFFFFF" if i % 2 == 0 else PANEL
        for c in r.cells:
            _shade(c, fill); _cell_margins(c)
        _cell_text(r.cells[0], opt, size=9.5, color=INK, bold=True)
        _cell_text(r.cells[1], cfg, size=9.5, color=INK)
        _cell_text(r.cells[2], prof, size=9.5, color=MUT)
    for r in t.rows:
        r.cells[0].width = Cm(4.6); r.cells[1].width = Cm(7.2); r.cells[2].width = Cm(5.2)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    para(doc,
         "Substitutions (70B-class): 1× H100 / A100 80G ≈ 2× L40S ≈ 2× RTX 5090 (tensor-parallel); "
         "A100 is accepted in place of H100. A 120B-class model typically needs 3× RTX 5090 or "
         "1× H100 / A100.", size=9.5, color=MUT, italic=True)

    heading(doc, "Data nodes (all GPU options)", 3, color=INK)
    feature_table(doc, GREEN, "0E8F62", [
        ("Services", "PostgreSQL HA · Qdrant ×2 · MinIO object store · Kubernetes control plane."),
        ("Per tier", "~48 cores, ~320 GB RAM, ~11 TB persistent (object tier expandable)."),
        ("Topology", "Lean: 2 data nodes · High-availability: 4 data nodes."),
    ], c0="Aspect", c1="Reference", w0=3.4, w1=13.6)
    callout(doc, "Entire stack inside the boundary — models included",
            "Every tier — orchestration, data and inference — runs on the customer's own cluster, "
            "air-gap-capable and with no outbound calls. The full stack fits a lean two-data-node "
            "profile for pilots and scales to high availability without re-architecture.",
            NAVY, "0B2545", TINT["NAVY"])

    heading(doc, "4.4   Air-gapped metering & reconciliation", 2, color=BLUE)
    para(doc,
         "Because every run and every skill invocation is metered in the ledger, the platform "
         "produces usage reports — counts of runs, tool-calls and tokens per workspace and "
         "capability — entirely offline. In an air-gapped deployment these are exported as signed "
         "files for reconciliation: there is no phone-home and no external telemetry, yet the figures "
         "are tamper-evident and independently verifiable. This gives a clean, auditable basis for "
         "licence and consumption reconciliation in a fully isolated environment.")

    # ===================================================== 5 Feature Catalog
    doc.add_page_break()
    heading(doc, "5   Feature Catalog", 1, color=NAVY, rule=True)
    para(doc,
         "The platform's capabilities, grouped by domain. Each capability is available in the "
         "product today and maps to one or more of PIH's stated needs (see Section 10).",
         color=MUT)

    group(doc, "5.1   Agent Builder", BLUE, "2D6CDF",
          "Compose a production agent from business capabilities — without glue code.",
          [("Six-step builder", "Objective → Skills → Context → Policy → Budget → Launch, with immediate in-product testing."),
           ("Visual flow composition", "Drag-and-drop graph editor; nodes for tasks, decisions, forks and joins, loops, retries, human-in-the-loop and sub-flows."),
           ("Versioning & rollback", "Every change is versioned; roll back to any prior version without rewriting history."),
           ("Export & import", "Portable JSON envelopes move a System between workspaces, re-binding skills by identifier."),
           ("Reusable capabilities", "A catalog of business capabilities bundles the right skills, pricing and quality thresholds.")])
    image(doc, "ui-flow-builder.png", width=16.5, base=SCREENS,
          caption="The flow builder — composing a System as a run-engine DAG of typed skills.")

    group(doc, "5.2   Orchestration & Execution", PURPLE, "6D28D9",
          "Stateful, governed execution of every agent run.",
          [("Execution modes", "Real-time, batch, event-driven, continuous-monitoring and human-augmented modes, each with its own service profile."),
           ("Stateful runs & checkpoints", "Long-running work persists progress and resumes after interruption."),
           ("Replay & resubmission", "Re-run any execution with overrides on an immutable flow snapshot, with full parent-child lineage."),
           ("Adaptive policies", "Mid-run directives switch model, fall back, escalate to a human or stop — only within permitted bounds."),
           ("Skill registry", "Typed, versioned, metered skills with declared cost, latency and retry behaviour."),
           ("Tool-calling ledger", "Every skill invocation is recorded with input, output, status, cost and latency.")])
    image(doc, "ui-steering.png", width=16.5, base=SCREENS,
          caption="Steering — control and adaptive policies with live what-if projection.")

    group(doc, "5.3   Agent Evaluation", GREEN, "0E8F62",
          "Measure and improve agent quality continuously, under human control.",
          [("Automatic scoring", "Each run is scored after execution: composite quality, hallucination rate and drift."),
           ("Tunable thresholds", "Quality presets per workspace, capability or system define the floors that trigger review."),
           ("Review queue", "Runs that breach thresholds become review tasks with accept, reject and re-run actions."),
           ("Human feedback loop", "Reviewer decisions are recorded and feed corrective signals back into the system."),
           ("Component attribution", "Quality failures are attributed to the responsible pipeline component — retrieval, ranking or generation."),
           ("Canonical answers", "Approved replies answer matching questions deterministically, bypassing the model."),
           ("Proactive recommendations", "Aggregated quality trends surface recommended adjustments for human approval.")])
    image(doc, "ui-evaluation-quality.png", width=16.5, base=SCREENS,
          caption="The evaluation dashboard — composite score, component-level health, drift and a 12-dimension quality radar.")

    group(doc, "5.4   Security & Identity", AMBER, "B45309",
          "Enterprise identity, access control and guardrails for autonomous agents.",
          [("Federated authentication", "OpenID Connect via Keycloak, with RS512-signed tokens and cached key rotation."),
           ("Role-based access (RBAC)", "Five workspace roles, from owner to viewer, govern every action."),
           ("Attribute-based rules (ABAC)", "Fine-grained conditions — ownership, label intersection, four-eyes approval and feature gates."),
           ("Distinct agent identity", "Agents are first-class principals; their permissions are managed and audited separately from users."),
           ("Model guardrails", "Control policies enforce model whitelists, cost and latency ceilings and mandatory human review below a confidence threshold; generation refuses ungrounded answers."),
           ("Multi-tenant isolation", "Every record is workspace-scoped; one tenant can never read another's data, runs or audit trail.")])

    group(doc, "5.5   Observability & Audit", NAVY, "0B2545",
          "Full, exportable visibility into everything an agent does.",
          [("Run ledger", "A complete, queryable record of every execution and its outcome."),
           ("Skill-invocation trail", "Per-tool-call timing, cost and metrics — the audit trail of agent tool-calling."),
           ("Pipeline tracing", "Step-level traces across ingestion, retrieval, ranking and generation."),
           ("Tamper-evident audit log", "Workspace-scoped audit events — actor, action, correlation id, agent id — with export."),
           ("Decision trail", "Every recommendation and approval recorded as a state machine, from proposed to applied.")])

    group(doc, "5.6   Sovereign Model Orchestration & Token Performance", BLUE, "2D6CDF",
          "Efficient, deterministic orchestration of models you control.",
          [("On-prem model serving", "Models run inside the customer boundary (e.g. Ollama, or GPU serving via self-hosted inference endpoints such as vLLM or TGI)."),
           ("Multi-provider routing", "A router selects the configured model and falls back through a health-checked chain."),
           ("Deterministic generation budget", "Output token budget is computed from the input-to-context ratio on a fixed schedule, with safety margins and per-latency caps."),
           ("Adaptive retrieval fusion", "Dense and sparse weights adapt to the query — identifiers versus natural language — before rank fusion."),
           ("Cross-encoder reranking", "A budgeted cross-encoder reorders candidates for precision within a latency ceiling."),
           ("Context compression & diversity", "Compression and diversity selection keep the context window tight and non-redundant.")])

    group(doc, "5.7   Document Intelligence", GREEN, "0E8F62",
          "Turn enterprise documents into governed, retrievable knowledge — entirely on-premise.",
          [("Multi-format ingestion", "PDF, Office, text and image ingestion, with batch upload and incremental sync."),
           ("Sovereign OCR", "Provider-neutral OCR — a self-hosted engine with a local fallback; documents never leave the boundary."),
           ("Chunking & indexing", "Parsing, chunking and embedding into the vector store and a keyword index, with content hashing and de-duplication."),
           ("Metadata extraction", "Title, author, keywords and token counts extracted and attached as filterable payload."),
           ("Multimodality", "Provider-neutral analysis of images and visual feeds, indexed as observations alongside documents."),
           ("Chunk & index audit", "Every indexed chunk is browsable with its source, position and payload; per-collection inventory and diagnostics give full transparency over coverage."),
           ("Hybrid retrieval", "Dense and sparse retrieval with adaptive fusion, reranking and grounded, cited answers (see Section 3)."),
           ("Knowledge-base isolation", "Strict per-collection isolation; cross-scope leakage is prevented at query time.")])
    image(doc, "ui-news-lab-charts.png", width=16.5, base=SCREENS,
          caption="Intelligence over a monitored feed — sentiment mix and top-entity analytics synthesised from ingested sources.")

    group(doc, "5.8   Connectors & Knowledge Capture", PURPLE, "6D28D9",
          "Bring knowledge in securely, with provenance and human review.",
          [("SharePoint connector", "Standard OAuth and guest-link ingestion, with incremental sync and encryption at rest."),
           ("Secure external deposit", "Scoped, audited file intake for trusted external contributors."),
           ("Expert knowledge capture", "Guided expert interviews — planning, voice capture, synchronous evaluation and reviewable proposals.")])

    group(doc, "5.9   Cockpit & Roles", PURPLE, "6D28D9",
          "One cockpit, four operating roles, a single source of truth.",
          [("Hypervisor", "Portfolio view — aggregated cost, value and quality, a decision feed and what-if levers."),
           ("Steering", "Operator view — control and adaptive policies, contexts and what-if simulation."),
           ("Runs & observability", "Execution health, timelines, metrics and replay lineage."),
           ("Audit & governance", "Audit trail, access management and quality presets."),
           ("Chat with citations", "Grounded answers with clickable sources, a reasoning trail and inline evaluation."),
           ("Real-time voice", "Low-latency spoken interaction over self-hosted WebRTC, with pluggable on-premise speech models — no external voice service required.")])
    para(doc,
         "Four operating roles share this cockpit: an Executive monitors the portfolio, an Operator "
         "runs and tunes systems, a Governance officer enforces policy and audit, and a Builder "
         "composes and tests new agents.", color=MUT, italic=True)
    image(doc, "ui-hypervisor.png", width=16.5, base=SCREENS,
          caption="The Hypervisor — portfolio cost, value, ROI and signals, live per capability.")

    # ===================================================== 6 Data, ML & Model Verticalisation
    doc.add_page_break()
    heading(doc, "6   Data, ML & Model Verticalisation", 1, color=NAVY, rule=True)
    lead(doc, [
        ("Agents are only as good as the models and data behind them. ", True, NAVY),
        ("The platform's data and machine-learning layer trains, tunes, fine-tunes and operates the "
         "models the agentic layer orchestrates. Generic models become domain models — verticalised "
         "on the customer's own data, in the customer's own environment, and governed end to end.", False, INK),
    ])
    image(doc, "d10_ml_verticalization.png", width=16.5,
          caption="From the customer's data to a verticalised sovereign model, served on-prem and orchestrated by Agentium.")

    heading(doc, "6.1   Machine-learning capabilities", 2, color=BLUE)
    para(doc, "A full data-science and machine-learning workbench, on a Spark-based data engine.",
         color=MUT, italic=True, before=0)
    feature_table(doc, BLUE, "2D6CDF", [
        ("DataOps & preparation", "Spark-based ingestion, cleaning, feature engineering and time-series preparation across enterprise sources."),
        ("Model families", "Classification, regression, clustering, survival and time-series forecasting; NLP — named-entity recognition, relation extraction and text classification; computer vision — image classification; and pre-trained tabular transformers (e.g. TabPFN)."),
        ("AutoML & tuning", "Automated model search and hyper-parameter optimisation (e.g. Tree-structured Parzen Estimator)."),
        ("Fine-tuning & verticalisation", "Train and fine-tune models on the customer's domain data — tabular, time-series, text and vision — to specialise generic models to the business. For sovereign language-model specialisation, the approach centres on retrieval and knowledge (RAG/CAG), complemented by parameter-efficient fine-tuning (e.g. LoRA, and proprietary layer-augmentation methods) for deeper domain adaptation."),
        ("Explainability & fairness", "SHAP, LIME and counterfactual explanations, feature importance, error analysis and fairness analysis."),
        ("Interpretable reporting", "Auto-generated model reports with evaluation metrics and interpretability."),
    ], c0="Capability", c1="What it does")
    image(doc, "papai-features.png", width=16.5, base=SCREENS,
          caption="Feature engineering — per-feature imputation, transformation, statistics and data quality on the customer's data.")
    image(doc, "papai-models.png", width=16.5, base=SCREENS,
          caption="Model selection and configuration — from classic ML to pre-trained tabular transformers (TabPFN).")
    image(doc, "papai-debug.png", width=16.5, base=SCREENS,
          caption="Explainability — error analysis and silent failure detection.")

    heading(doc, "6.2   MLOps lifecycle", 2, color=BLUE)
    para(doc, "Industrialise every model from training to monitored production.",
         color=MUT, italic=True, before=0)
    feature_table(doc, GREEN, "0E8F62", [
        ("Model registry & artefacts", "Versioned models with signatures, environment pinning and metadata lineage."),
        ("Deployment & serving", "Containerised model build and an inference gateway with multi-model routing, batch scoring for high-throughput offline inference, and workflow orchestration for multi-step ML pipelines."),
        ("Monitoring & drift", "Data- and performance-drift detection, prediction logging and feedback capture."),
        ("Champion / challenger", "Multi-model routing supports comparison and progressive rollout."),
        ("Governed retraining", "Feedback and new data flow back to retraining under human control."),
    ], c0="Capability", c1="What it does")
    image(doc, "papai-interpret.png", width=16.5, base=SCREENS,
          caption="Explainability — per-feature impact and partial dependence on the model's predictions.")
    image(doc, "papai-deployment.png", width=13.0, base=SCREENS,
          caption="Model serving — a trained model exposed as a secured, token-authenticated REST endpoint.")

    heading(doc, "6.3   How verticalised models feed the agents", 2, color=BLUE)
    para(doc,
         "A model trained or fine-tuned in the data & ML layer is registered, served inside the "
         "boundary and consumed by a System as a skill — a prediction, a classification, a forecast "
         "or a domain-adapted language capability. Conversely, a System can invoke data and ML "
         "services as tools within a workflow. Runs, evaluations and new data flow back into "
         "training, closing a governed improvement loop in which models and agents sharpen together "
         "on the customer's data — all within one platform and one sovereign boundary.")

    # ===================================================== 7 Enterprise Integration & Connectivity
    doc.add_page_break()
    heading(doc, "7   Enterprise Integration & Connectivity", 1, color=NAVY, rule=True)
    lead(doc, [
        ("Agentium connects to the systems where enterprise data and processes already live. ", True, NAVY),
        ("A proven, Spark-based connector framework — extensible to any source — lets agents and "
         "pipelines read from, and write back to, databases, warehouses, object stores, collaboration "
         "platforms and ERP systems, all from within the sovereign boundary.", False, INK),
    ])

    heading(doc, "7.1   Connector framework", 2, color=BLUE)
    para(doc, "A generalized, extensible framework. The connectors below are available today; the "
              "list is illustrative, not a closed catalogue — any further source is added through the "
              "same framework and then reused as a typed skill.",
         color=MUT, italic=True, before=0)
    feature_table(doc, BLUE, "2D6CDF", [
        ("Relational & warehouse", "PostgreSQL, Oracle, SQL Server, MySQL, Snowflake, BigQuery (JDBC and native)."),
        ("NoSQL & search", "MongoDB, Cassandra, Elasticsearch / OpenSearch."),
        ("Object & file storage", "S3, Google Cloud Storage, Azure, MinIO; Excel, CSV and document formats."),
        ("Collaboration & intake", "SharePoint (OAuth and guest-link), secure SFTP deposit."),
        ("Extensible by design", "Any further source — databases, APIs, message buses, line-of-business and ERP systems — is added through the generalized framework, then reused platform-wide."),
    ], c0="Category", c1="Available today (illustrative, not exhaustive)")
    image(doc, "ui-connectors.png", width=16.5, base=SCREENS,
          caption="The connections catalogue — relational, NoSQL, search, file-transfer and cloud-storage sources, extensible on demand.")

    heading(doc, "7.2   SAP interoperability", 2, color=BLUE)
    para(doc,
         "SAP is a first-class integration target. The connector framework speaks to SAP through its "
         "standard, supported interfaces — so SAP data and processes can be brought into agents, "
         "retrieval and ML without bespoke middleware, and without data leaving the boundary.")
    image(doc, "d9_sap_integration.png", width=16.5,
          caption="SAP and enterprise interoperability through standard interfaces, inside the sovereign boundary.")
    feature_table(doc, AMBER, "B45309", [
        ("SAP HANA — SQL / JDBC", "Direct, high-throughput read (and write) against HANA and S/4HANA data."),
        ("CDS views", "Consume SAP's semantic data models, preserving business meaning."),
        ("OData / SAP Gateway", "Read and write business objects over standard OData services."),
        ("BAPI / RFC", "Invoke transactional business functions through the standard RFC bridge."),
        ("IDoc", "Exchange business documents in SAP's native interchange format."),
        ("SLT / CDC & events", "Near-real-time replication and change-data-capture for event-driven flows."),
    ], c0="Interface", c1="Capability", w0=4.4, w1=12.6)
    para(doc,
         "The right mix is chosen per use case — direct SQL/CDS for analytical access, OData/BAPI for "
         "transactional read-write, SLT/CDC for streaming. A connector can be deployed inside the "
         "air-gapped boundary so SAP credentials and data never traverse an external network.",
         color=MUT)

    heading(doc, "7.3   APIs, skills & MCP", 2, color=BLUE)
    para(doc,
         "Every Agentium capability is exposed through a documented REST API, and every tool an agent "
         "uses is a typed, versioned skill in a shared registry — built once and factorised across "
         "all Systems, never re-implemented per project. New connectors and tools are added as skills "
         "and immediately reusable. The platform is designed to interoperate over the Model Context "
         "Protocol (MCP) for connecting external tools and data sources to agents.")
    feature_table(doc, PURPLE, "6D28D9", [
        ("Systems & runs", "Create, version, execute and replay Systems; browse the run ledger."),
        ("Skills & capabilities", "Discover the typed skill registry and business-capability catalogue."),
        ("Chat & retrieval", "Streaming chat with citations; document search and retrieval."),
        ("Documents & knowledge", "Upload, collections, chunks, diagnostics and metadata."),
        ("Evaluation & governance", "Scores, review queue, presets, decisions and audit export."),
        ("Control plane & hypervisor", "Policies, what-if simulation and portfolio aggregates."),
        ("Connectors & voice", "SharePoint and deposit intake; real-time voice gateway."),
    ], c0="API surface", c1="Endpoints", w0=4.6, w1=12.4)
    para(doc,
         "New APIs and connectors developed for a customer are built on this surface and factorised "
         "into the shared registry, so each integration enriches the reusable platform rather than a "
         "one-off silo.", color=MUT)

    # ===================================================== 8 Reference — Andritz
    doc.add_page_break()
    heading(doc, "8   Reference — Andritz", 1, color=NAVY, rule=True)
    lead(doc, [
        ("An industrial knowledge and AI program for a global heavy-industry equipment manufacturer. ", True, NAVY),
        ("Datategy is delivering a multi-domain program — expert knowledge capture, technical document "
         "intelligence, AI-assisted reporting and diagnostics, and ERP-integrated service intelligence "
         "— on a sovereign, on-premise-capable platform, operating alongside the customer's ERP and "
         "maintenance systems.", False, INK),
    ])
    para(doc, "Specific project, site, equipment and system details are covered by NDA and available "
              "on request; the account below is generalised accordingly.", size=9.5, color=MUT, italic=True)

    heading(doc, "8.1   Capabilities", 2, color=BLUE)
    feature_table(doc, BLUE, "2D6CDF", [
        ("Expert knowledge capture", "Guided, voice-enabled interviews with field-service experts; tacit reasoning structured into reviewable knowledge proposals."),
        ("Technical document intelligence", "A large multi-source technical corpus indexed for grounded, cited semantic search, scoped per project."),
        ("Secure ingestion", "A secure-deposit pipeline with operator-controlled staging, validation and promotion before any content is indexed."),
        ("Multilingual retrieval", "Grounded, cited answers across multiple languages, with strict per-scope isolation."),
    ], c0="Capability", c1="Demonstrated on a live system")
    para(doc, "The broader program extends to AI-assisted intervention reporting, troubleshooting and "
              "diagnostics support, and ERP-integrated customer and service intelligence.", color=MUT)

    heading(doc, "8.2   ERP & maintenance (SAP) context", 2, color=BLUE)
    para(doc,
         "The program operates alongside the customer's ERP and maintenance systems, including SAP. "
         "Agents cross-reference maintenance work orders and intervention records, and spare-parts "
         "knowledge is linked to ERP master data, so an expert's escalation reasoning is grounded in "
         "the maintenance record rather than informal report. It is a concrete demonstration of "
         "Agentium operating in an ERP-adjacent, maintenance-critical setting — the pattern that the "
         "SAP integration in Section 7 formalises.")

    heading(doc, "8.3   Outcomes & learnings", 2, color=BLUE)
    bullet(doc, [("Retrieval quality — ", True, INK), ("a validated question set passes end-to-end on the live system, with correct project scoping.", False, MUT)])
    bullet(doc, [("Multilingual coverage — ", True, INK), ("questions asked in one language reliably resolve against documents in another.", False, MUT)])
    bullet(doc, [("Provenance discipline — ", True, INK), ("answers cite project, document and section; proof sources (maintenance records, sensor exports) are treated as authoritative over informal report.", False, MUT)])
    bullet(doc, [("Operating learning — ", True, INK), ("operator-controlled promotion and human review of captured knowledge proved essential to trust; the workflow makes that gate explicit.", False, MUT)])

    # ===================================================== 9 Delivery & Operations
    doc.add_page_break()
    heading(doc, "9   Delivery & Operations", 1, color=NAVY, rule=True)

    heading(doc, "9.1   Building agents — complexity tiers", 2, color=BLUE)
    para(doc,
         "Agent build effort scales with complexity, not with platform friction: the Builder, the "
         "skill registry and reusable connectors mean most of the work is configuration and "
         "evaluation rather than bespoke code. The tiers below are indicative, order-of-magnitude "
         "guidance to map resources; actual effort depends on data readiness and integration depth.")
    tiers = [
        ("Simple", "One capability, existing skills and a ready knowledge source; light evaluation.", "~1–3 person-days"),
        ("Medium", "Several skills, a custom flow, one or two integrations, tuned retrieval and evaluation thresholds.", "~1–2 person-weeks"),
        ("Complex", "Heavy integration (e.g. SAP), multi-step or multi-agent orchestration, custom skills and rigorous evaluation.", "~3–6 person-weeks"),
    ]
    t = doc.add_table(rows=1, cols=3)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.allow_autofit = False
    _set_borders(t, LINE, 4)
    for j, htxt in enumerate(["Tier", "What it involves", "Indicative effort"]):
        _shade(t.cell(0, j), "0B2545"); _cell_margins(t.cell(0, j))
        _cell_text(t.cell(0, j), htxt, size=9.5, color=WHITE, bold=True)
    for i, (tier, inv, eff) in enumerate(tiers):
        r = t.add_row()
        fill = "FFFFFF" if i % 2 == 0 else PANEL
        for c in r.cells:
            _shade(c, fill); _cell_margins(c)
        _cell_text(r.cells[0], tier, size=9.5, color=INK, bold=True)
        _cell_text(r.cells[1], inv, size=9.5, color=MUT)
        _cell_text(r.cells[2], eff, size=9.5, color=INK, bold=True)
    for r in t.rows:
        r.cells[0].width = Cm(2.6); r.cells[1].width = Cm(10.4); r.cells[2].width = Cm(4.0)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    para(doc,
         "Effort falls over time as the registry of skills and connectors grows: the second SAP-heavy "
         "agent is far faster than the first. Delivery runs as a joint team — a Datategy solution "
         "architect leads as the Agentium expert, with the customer's architects building alongside "
         "and progressively taking ownership.", color=MUT)

    heading(doc, "9.2   Operating the platform locally", 2, color=BLUE)
    para(doc, "Day-to-day administration needs a small local team; the platform's own surfaces keep "
              "that footprint lean.", color=MUT, italic=True, before=0)
    feature_table(doc, GREEN, "0E8F62", [
        ("Platform / SRE", "Operates the Kubernetes cluster and Agentium services; uses built-in health checks and a cluster dashboard."),
        ("Security / IAM admin", "Manages identity, roles and policies through the identity provider and the governance surfaces."),
        ("Knowledge / data steward", "Curates collections, ingestion and quality presets; reviews captured knowledge."),
        ("ML engineer (optional)", "Runs model training and MLOps when model verticalisation is in scope."),
    ], c0="Local role", c1="Responsibility & platform support")
    para(doc,
         "Observability, audit and evaluation are built in, so the operating team supervises and "
         "governs rather than firefights. Datategy operates and manages the Kubernetes layer under an "
         "agreed model, with the customer's team progressively self-sufficient.", color=MUT)

    # ===================================================== 5 Alignment to PIH
    doc.add_page_break()
    heading(doc, "10   Alignment to PIH Requirements", 1, color=NAVY, rule=True)
    para(doc,
         "PIH expressed five needs. Each maps directly onto capabilities that exist in the product "
         "today. The distinction Agentium offers is not that it ticks these boxes — several "
         "orchestrators do — but that owning the full stack lets it deliver them as guarantees.")
    image(doc, "d6_alignment.png", width=16.0,
          caption="Each PIH need mapped to the capability cluster that delivers it.")

    for title, color, txt in [
        ("Sovereignty", NAVY,
         "Models and data never leave the customer boundary. Inference is served on-premise and "
         "routed locally; storage is workspace-scoped. No external service is required to operate, "
         "so sovereignty is structural, not contractual."),
        ("Robustness", BLUE,
         "Runs are stateful and durable. Immutable flow snapshots, parent-child lineage and "
         "checkpointing make replay and resubmission first-class, so any execution can be reproduced "
         "or re-run with controlled overrides."),
        ("Security", PURPLE,
         "Autonomous agents are distinct identities governed by RBAC and attribute-based rules. "
         "Control policies act as model guardrails — whitelists, cost and latency ceilings, and "
         "mandatory human review below a confidence threshold — and tenants are strictly isolated."),
        ("Observability & Scalability", GREEN,
         "Every tool-call is recorded in a skill-invocation ledger, every pipeline step is traced, "
         "and the audit log is exportable. Asynchronous workers and tenant isolation provide "
         "enterprise-grade horizontal scale."),
        ("Token Performance", AMBER,
         "A deterministic generation budget sizes output from the input-to-context ratio; adaptive "
         "fusion, budgeted reranking and compression keep token use efficient and predictable across "
         "sovereign models."),
    ]:
        lead(doc, [(title + ".  ", True, color), (txt, False, INK)], before=3, after=3)

    heading(doc, "Requirements traceability", 2, color=BLUE)
    matrix = [
        ("Sovereignty", "On-prem model serving & local data plane",
         "Inference inside the boundary; workspace-scoped vector, relational and object stores."),
        ("Robustness", "Stateful runs · replay · resubmission",
         "Immutable flow snapshots, checkpoints, parent-child lineage, replay with overrides, idempotent skills."),
        ("Security", "RBAC + ABAC · agent identity · guardrails",
         "Keycloak OIDC, five RBAC roles, attribute conditions, distinct agent principals, control-policy guardrails, tenant isolation."),
        ("Observability\n& Scalability", "Tool-call ledger · audit · async scale",
         "Skill-invocation ledger, pipeline tracing, exportable audit log, decision trail; async workers for scale."),
        ("Token Performance", "Deterministic budget & adaptive fusion",
         "Ratio-based generation budget with caps, adaptive dense/sparse fusion, budgeted reranking and compression, multi-provider routing."),
    ]
    t = doc.add_table(rows=1, cols=3)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.allow_autofit = False
    _set_borders(t, LINE, 4)
    for j, htxt in enumerate(["PIH need", "Agentium capability", "How it is delivered"]):
        _shade(t.cell(0, j), "0B2545"); _cell_margins(t.cell(0, j))
        _cell_text(t.cell(0, j), htxt, size=9.5, color=WHITE, bold=True)
    for i, (need, cap, how) in enumerate(matrix):
        r = t.add_row()
        fill = "FFFFFF" if i % 2 == 0 else PANEL
        for j, val in enumerate((need, cap, how)):
            _shade(r.cells[j], fill); _cell_margins(r.cells[j])
            _cell_text(r.cells[j], val, size=9.5,
                       color=INK if j < 2 else MUT, bold=(j < 2))
    for r in t.rows:
        r.cells[0].width = Cm(3.3); r.cells[1].width = Cm(5.4); r.cells[2].width = Cm(8.3)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)

    # ===================================================== 7 Competitive Positioning
    doc.add_page_break()
    heading(doc, "11   Competitive Positioning", 1, color=NAVY, rule=True)
    para(doc,
         "The comparison below is based on publicly available information as of June 2026 and focuses "
         "on the dimensions PIH prioritised. It is offered in good faith; where a capability is not "
         "publicly documented, it is noted as such rather than assumed absent.",
         color=MUT, italic=True)
    lead(doc, [
        ("TENN.ai ", True, INK),
        ("is a regional agentic-AI platform with real strengths: native Arabic and dialect support, a "
         "no-code “FlowTeam” experience, and strong go-to-market in the Gulf through its delivery "
         "ecosystem. These are genuine assets for fast, business-user adoption.", False, INK),
    ])
    para(doc,
         "Those strengths are about packaging and reach. Strip the packaging away and, on its own "
         "public description, TENN.ai is an orchestration layer over third-party frontier models "
         "(OpenAI, Anthropic, Google, Mistral): the intelligence is rented, not owned. Two "
         "consequences follow directly. First, sovereignty is conditional — unless a deployment is "
         "fully self-hosted, which public sources do not evidence, prompts and documents leave the "
         "boundary for external APIs. Second, the advertised escape from model lock-in is traded for "
         "lock-in to a proprietary “FlowTeam” runtime, from which workflows and memory have no "
         "demonstrated export path. The headline efficiency claims (e.g. “100× / 1000×”) carry no "
         "independent benchmark.")
    para(doc,
         "Agentium is built the other way round. It owns its orchestration kernel, runs sovereign "
         "models inside the customer boundary with no external call required, evaluates and audits "
         "every run, and lets a system be exported and run elsewhere. It does not compete on Arabic "
         "packaging — it orchestrates the best sovereign model, including a Qatari sovereign Arabic "
         "model, under governance a no-code factory does not expose. The comparison below is offered "
         "in good faith on that basis.")

    battle = [
        ("Owns the intelligence?",
         "Proprietary orchestration kernel; runs sovereign models in-boundary as first-class.",
         "No proprietary model — intelligence is rented from external frontier APIs; a packaging layer on top."),
        ("Sovereign deployment",
         "Full stack on-premise or air-gapped; no external dependency required.",
         "On-prem claimed, but routing to external model APIs means data leaves the boundary unless fully self-hosted — not evidenced."),
        ("Freedom from lock-in",
         "Systems export and import as portable JSON; open foundation; no proprietary runtime trap.",
         "Escapes model lock-in into a proprietary runtime; workflow and memory export not demonstrated."),
        ("Replicability of the offer",
         "Deep engineering — deterministic budget, evaluation, audit, governance — hard to reproduce.",
         "Orchestration-over-APIs is readily rebuilt on open frameworks; the moat is packaging and regional delivery."),
        ("Robustness — replay & state",
         "Immutable flow snapshots, checkpoints, replay with overrides and full lineage.",
         "No published replay, checkpoint or state model."),
        ("Auditability of tool-calling",
         "Per-invocation ledger, exportable audit log and a proposed-to-applied decision trail.",
         "No published tool-call ledger or audit export."),
        ("Agent evaluation",
         "Automatic scoring, thresholds, review queue, component attribution and statistical gating.",
         "No evaluation framework — agent quality is asserted, not measured."),
        ("Security model",
         "Keycloak OIDC, five-role RBAC + ABAC, distinct agent identity and policy-based guardrails.",
         "On-prem posture cited; no published RBAC, agent-identity or guardrail model."),
        ("Token performance",
         "Deterministic generation budget and query-adaptive fusion — predictable cost and latency.",
         "“100× / 1000×” efficiency claims with no independent benchmark."),
        ("Arabic / MENA fit",
         "Orchestrates sovereign Arabic models under full governance and evaluation.",
         "Native Arabic and dialect focus — a genuine strength."),
        ("Maturity & model",
         "Production engineering with an automated test suite and a documented data model.",
         "Early-stage and services-led (project-by-project delivery); limited public production evidence."),
    ]
    t = doc.add_table(rows=1, cols=3)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.allow_autofit = False
    _set_borders(t, LINE, 4)
    for j, htxt, fillc in ((0, "Dimension", "0B2545"),
                           (1, "Agentium", "2D6CDF"),
                           (2, "TENN.ai  (public sources)", "596371")):
        _shade(t.cell(0, j), fillc); _cell_margins(t.cell(0, j))
        _cell_text(t.cell(0, j), htxt, size=9.5, color=WHITE, bold=True)
    for dim, us, them in battle:
        r = t.add_row()
        _shade(r.cells[0], PANEL); _shade(r.cells[1], "EAF1FD"); _shade(r.cells[2], "FFFFFF")
        for c in r.cells:
            _cell_margins(c)
        _cell_text(r.cells[0], dim, size=9.5, color=INK, bold=True)
        _cell_text(r.cells[1], us, size=9.5, color=INK)
        _cell_text(r.cells[2], them, size=9.5, color=MUT)
    for r in t.rows:
        r.cells[0].width = Cm(3.6); r.cells[1].width = Cm(6.7); r.cells[2].width = Cm(6.7)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    callout(doc, "Rented intelligence vs. owned capability",
            "TENN.ai orchestrates models it does not own, inside a runtime a customer cannot leave. "
            "Agentium owns its orchestration kernel, runs sovereign models inside the customer's "
            "boundary, and lets the customer export and exit. One is a layer on someone else's "
            "intelligence; the other is infrastructure the organisation controls.",
            NAVY, "0B2545", TINT["NAVY"])

    heading(doc, "Questions worth putting to any agent platform", 3, color=INK)
    for q in [
        "Can a workflow run fully on-premise, with zero external calls?",
        "Is every tool-call recorded, and is the audit trail exportable?",
        "Can any execution be replayed deterministically, with controlled overrides?",
        "Are agents evaluated automatically, with thresholds that gate quality?",
        "Can a system be exported and run outside the platform?",
    ]:
        bullet(doc, [(q, False, MUT)])
    lead(doc, [("Agentium answers yes to each.", True, NAVY)], before=4, after=2)

    # ===================================================== 12 Value Model
    doc.add_page_break()
    heading(doc, "12   Value Model", 1, color=NAVY, rule=True)
    lead(doc, [
        ("Agentium is adopted along five value dimensions. ", True, NAVY),
        ("They describe how value is structured — so capacity, knowledge, expertise and infrastructure "
         "can scale independently to match the customer's pace. Commercial terms for each are set out "
         "separately, in the accompanying proposal.", False, INK),
    ])
    image(doc, "d11_value_model.png", width=15.5,
          caption="Five value dimensions that scale independently.")
    feature_table(doc, NAVY, "0B2545", [
        ("Agentium Platform", "The right to run the Agentium operating system — the orchestration, builder, evaluation and governance core."),
        ("System Capacity", "The number of autonomous business capabilities (Systems) deployed and run."),
        ("Knowledge Capacity", "The exploitable enterprise memory — document volume and the knowledge bases agents draw on."),
        ("Center of Excellence", "Datategy expertise to design, build and industrialise Systems, delivered as a joint team."),
        ("Sovereign Infrastructure", "The sovereign execution layer — run as the customer's own capacity or as a managed sovereign service (optional)."),
    ], c0="Dimension", c1="What it represents", w0=4.4, w1=12.6)
    para(doc,
         "Because the dimensions are independent, a customer can grow System Capacity without growing "
         "Knowledge Capacity, draw on the Center of Excellence only while ramping, and choose whether "
         "sovereign infrastructure is owned or managed — adapting the platform to the mission rather "
         "than the reverse.", color=MUT)

    # ===================================================== 13 Why Agentium
    doc.add_page_break()
    heading(doc, "13   Why Agentium for PIH", 1, color=NAVY, rule=True)
    para(doc,
         "The capabilities PIH asked for are, individually, available across the market. What is not "
         "available elsewhere is delivering them on a stack the customer fully owns. Because "
         "Agentium serves its own models, records its own action ledger and enforces its own "
         "governance, it does not have to trust an external provider to keep these promises.")
    callout(doc, "The constraint becomes the advantage",
            "Sovereignty stops being a limitation and becomes the source of guarantees no cloud-bound "
            "competitor can match: enforced data residency, reproducible executions, and auditability "
            "that is proof rather than logs.",
            NAVY, "0B2545", TINT["NAVY"])
    para(doc,
         "Agentium meets PIH's five needs today and gives a single, governed platform on which to "
         "build, run and continuously improve autonomous agents — under the organisation's own "
         "control, end to end.")

    # ===================================================== Appendix
    doc.add_page_break()
    heading(doc, "Appendix A — Glossary", 1, color=NAVY, rule=True)
    gloss = [
        ("RBAC", "Role-Based Access Control — permissions granted by a user's role."),
        ("ABAC", "Attribute-Based Access Control — permissions conditioned on attributes (ownership, labels, flags)."),
        ("OIDC", "OpenID Connect — the federated authentication protocol used for single sign-on."),
        ("HITL", "Human-In-The-Loop — a step that pauses execution for human review or approval."),
        ("Rank fusion", "Combining results from several retrieval methods into one ranked list."),
        ("Cross-encoder", "A precision reranking model that scores a query against each candidate passage."),
        ("Grounding", "Requiring an answer to be supported by a retrieved source, or else declining to answer."),
        ("Composite score", "A weighted aggregate quality score produced by the evaluation layer for each run."),
        ("MLOps", "The discipline and tooling for deploying, versioning, monitoring and retraining machine-learning models in production."),
        ("Fine-tuning", "Adapting a pre-trained model to a specific domain or task using the customer's own data."),
        ("NER / RE", "Named-Entity Recognition / Relation Extraction — NLP tasks that identify entities and the relations between them."),
        ("RAG / CAG", "Retrieval- and Cache-Augmented Generation — grounding answers in retrieved or cached enterprise knowledge."),
        ("LoRA", "Low-Rank Adaptation — a parameter-efficient method to adapt a language model to a domain without full retraining."),
        ("Drift", "A measurable shift in input data or model performance over time, signalling that retraining may be needed."),
        ("SAP PM", "SAP Plant Maintenance — the SAP module for maintenance work orders, intervention records and equipment data."),
        ("BAPI / RFC", "SAP's standard interfaces for invoking business functions and remote calls programmatically."),
        ("OData", "A standard REST protocol used by SAP Gateway to read and write business objects."),
        ("CDS views", "SAP Core Data Services — semantic data models exposing SAP data with business meaning."),
        ("SLT / CDC", "SAP Landscape Transformation / change-data-capture — near-real-time replication of changing data."),
        ("MCP", "Model Context Protocol — an open standard for connecting external tools and data sources to AI agents."),
    ]
    feature_table(doc, MUT, "596371", gloss, c0="Term", c1="Meaning", w0=4.0, w1=13.0)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    doc.save(OUT)
    print("saved:", os.path.relpath(OUT, HERE))
    return OUT


if __name__ == "__main__":
    build()
