# -*- coding: utf-8 -*-
"""Branded PDF for the Agentium Showcase onboarding / hands-on note (PIH).

Content mirrors docs/pih/Agentium-Showcase-Onboarding-PIH.md, laid out with
the same visual charter as the shortlist deck (white, navy/blue, mono kickers).
Output: out/Agentium-Showcase-Onboarding-PIH.pdf
"""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle,
    KeepTogether,
)

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(HERE, "assets", "logo_datategy.png")
OUT = os.path.join(HERE, "out", "Agentium-Showcase-Onboarding-PIH.pdf")

INK = HexColor("#151A23")
MUT = HexColor("#596371")
LINE = HexColor("#D7DCE3")
PANEL = HexColor("#F3F5F8")
NAVY = HexColor("#0B2545")
BLUE = HexColor("#2D6CDF")
GREEN = HexColor("#0E8F62")
AMBER = HexColor("#B45309")
TINT = HexColor("#EAF1FD")

F, FB, FM = "Helvetica", "Helvetica-Bold", "Courier-Bold"

PW, PH = A4
MARGIN = 18 * mm


def style(name, **kw):
    base = dict(fontName=F, fontSize=9.5, leading=13.5, textColor=INK,
                alignment=TA_LEFT, spaceBefore=0, spaceAfter=0)
    base.update(kw)
    return ParagraphStyle(name, **base)


S_KICKER = style("kicker", fontName=FM, fontSize=8, textColor=BLUE, leading=11)
S_TITLE = style("title", fontName=FB, fontSize=20, leading=24, textColor=INK)
S_SUB = style("sub", fontSize=10.5, leading=15, textColor=MUT)
S_H2 = style("h2", fontName=FB, fontSize=13, leading=16, textColor=NAVY,
             spaceBefore=13, spaceAfter=4)
S_H3 = style("h3", fontName=FB, fontSize=10.5, leading=14, textColor=BLUE,
             spaceBefore=8, spaceAfter=2)
S_BODY = style("body", spaceAfter=4)
S_BODY_M = style("bodym", textColor=MUT, spaceAfter=4)
S_BUL = style("bul", textColor=MUT, leftIndent=10, bulletIndent=2, spaceAfter=2.5)
S_CELL = style("cell", fontSize=8.5, leading=11.5, textColor=MUT)
S_CELL_H = style("cellh", fontName=FB, fontSize=8.5, leading=11.5, textColor=INK)
S_CELL_HEAD = style("cellhead", fontName=FB, fontSize=8.5, leading=11, textColor=NAVY)
S_NOTE = style("note", fontSize=9, leading=12.5, textColor=NAVY)


def header_footer(canvas, doc):
    canvas.saveState()
    # top rule + logo
    canvas.setFillColor(NAVY)
    canvas.rect(0, PH - 6, PW, 6, stroke=0, fill=1)
    if os.path.exists(LOGO):
        canvas.drawImage(LOGO, PW - MARGIN - 28 * mm, PH - 14.5 * mm,
                         width=28 * mm, height=7 * mm, preserveAspectRatio=True,
                         anchor="ne", mask="auto")
    canvas.setFont(FM, 7)
    canvas.setFillColor(MUT)
    canvas.drawString(MARGIN, PH - 12 * mm, "AGENTIUM SHOWCASE · PIH EVALUATION · CONFIDENTIAL")
    # footer
    canvas.setFillColor(MUT)
    canvas.setFont(F, 7.5)
    canvas.drawString(MARGIN, 10 * mm, "Datategy — Agentium Showcase onboarding · July 2026 · Confidential")
    canvas.drawRightString(PW - MARGIN, 10 * mm, f"{doc.page:02d}")
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, 13.5 * mm, PW - MARGIN, 13.5 * mm)
    canvas.restoreState()


doc = BaseDocTemplate(OUT, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                      topMargin=20 * mm, bottomMargin=17 * mm,
                      title="Agentium Showcase — Onboarding & Hands-On Guide (PIH)",
                      author="Datategy")
frame = Frame(MARGIN, 17 * mm, PW - 2 * MARGIN, PH - 37 * mm, id="main")
doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=header_footer)])

CW = PW - 2 * MARGIN
story = []


def bullet(text, style_=S_BUL):
    story.append(Paragraph(f"<bullet>▪</bullet> {text}", style_))


def band(text, bg=TINT, color=NAVY):
    t = Table([[Paragraph(text, style("band", fontSize=9, leading=12.5, textColor=color))]],
              colWidths=[CW])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(Spacer(1, 4))
    story.append(t)
    story.append(Spacer(1, 4))


def table(headers, rows, widths, header_bg=PANEL):
    data = [[Paragraph(h, S_CELL_HEAD) for h in headers]]
    for r in rows:
        data.append([Paragraph(c, S_CELL_H if j == 0 else S_CELL) for j, c in enumerate(r)])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)


# ---------------------------------------------------------------- title block
story.append(Paragraph("DATATEGY × PIH · EVALUATION ACCESS", S_KICKER))
story.append(Spacer(1, 4))
story.append(Paragraph("Agentium Showcase — Onboarding &amp; Hands-On Guide", S_TITLE))
story.append(Spacer(1, 4))
story.append(Paragraph(
    "Welcome to your Agentium workspace. This note tells you how to get in, what you will find "
    "once your access is active, and where the topics you care most about live in the platform: "
    "<b>Flow Builder, Systems, replay, skills, observability, orchestration/automation (RPA) "
    "and data-source connectivity (SAP, Databricks, UiPath)</b>. A dedicated guided hands-on "
    "session with our team will follow — see section 5.", S_SUB))
story.append(Spacer(1, 6))

# ---------------------------------------------------------------- 1 note
story.append(Paragraph("1 · Before you start — a note on releases", S_H2))
story.append(Paragraph(
    "Agentium is a <b>live platform, in production at client sites</b> (Renault Group, Andritz, "
    "Société du Grand Paris, Mobilize Financial Services, among others). The Showcase workspace "
    "you are accessing runs on our SaaS environment, which follows a <b>continuous-improvement "
    "release cycle</b>: we are currently rolling out a new version, so some screens may be "
    "refined between your sessions. Two things will not change under you:", S_BODY))
bullet("<b>The mental model</b> (section 3) — objects, their relationships and the governance chain are stable.")
bullet("<b>Your data and flows</b> in the Showcase workspace persist across releases.")
band("If a button has moved, the concept is still there — and telling us what you expected to find "
     "is exactly the feedback we want.")

# ---------------------------------------------------------------- 2 getting in
story.append(Paragraph("2 · Getting in", S_H2))
bullet("You will receive a <b>personal invitation email</b> (sender: Agentium / Datategy). "
       "Follow the link to set your password — the login page is the branded Agentium portal.")
bullet("After login, check that the workspace selector (top bar) shows <b>Showcase</b> — "
       "your shared evaluation environment.")
bullet("Everything in Showcase runs on <b>synthetic or anonymised data</b>. Click, edit, run and "
       "break things freely: nothing touches any production system.")

# ---------------------------------------------------------------- 3 mental model
story.append(Paragraph("3 · The mental model — five objects, one chain", S_H2))
story.append(Paragraph(
    "Everything in Agentium hangs off one canonical chain: "
    "<b>System → Flow → Run → Evaluation → Decision → Ledger</b>", S_BODY))
story.append(Spacer(1, 3))
table(
    ["Object", "What it is", "Where you see it"],
    [
        ["System", "A governed business capability (e.g. “Contract Risk”, “Hydro Plant Insights”). "
                   "Owns its flows, runs, metrics and evidence.", "Portfolio / System 360"],
        ["Flow", "The executable definition — a visual DAG of typed skills assembled in the Flow Builder.", "Flow Builder"],
        ["Skill", "A typed, reusable unit of work (query SAP, call an LLM, dispatch an RPA job…). "
                  "Skills are what connectors contribute to the catalog.", "Node palette / skills catalog"],
        ["Run", "One execution of a flow: stateful, resumable, fully traced (every step, tool call, cost) — and replayable.", "Runs / Run detail"],
        ["Decision / Gate", "A human-in-the-loop checkpoint inside a run — with expiry rules, so a run never waits forever.", "Run detail / inbox"],
    ],
    [28 * mm, CW - 28 * mm - 42 * mm, 42 * mm],
)
story.append(Spacer(1, 4))
story.append(Paragraph(
    "<b>System 360</b> shows each System through four perspectives — <b>Build</b> (flows &amp; skills), "
    "<b>Operate</b> (runs &amp; incidents), <b>Steer</b> (cost, value, ROI — the Hypervisor), "
    "<b>Govern</b> (decisions, audit evidence). Same object, four lenses: whatever evolves in the UI, "
    "this is the map.", S_BODY_M))

# ---------------------------------------------------------------- 4 what you'll find
story.append(Paragraph("4 · What you will find once your access is active", S_H2))
story.append(Paragraph(
    "The Showcase workspace comes pre-populated, so there is something meaningful behind every "
    "door from the first login:", S_BODY_M))

found = [
    ("A portfolio of showcase Systems",
     "The Hypervisor home lists governed business capabilities, each carrying its own flows, runs, "
     "cost/value metrics and audit evidence — explore any of them through the four System 360 "
     "perspectives (Build / Operate / Steer / Govern)."),
    ("Ready-made flows in the Flow Builder",
     "Demo flows — including an <b>SAP hydro insights</b> flow wired to a seeded HANA dataset — "
     "open as visual DAGs of typed skills. Node parameters (SQL statements, analysis questions) "
     "are inspectable and editable in place."),
    ("Run history with full traces",
     "Past executions with their step-by-step traces: inputs, outputs, timing and cost per step, "
     "plus <b>Rerun</b> to replay any DAG and compare executions side by side."),
    ("A skills &amp; connectors catalog",
     "Typed skills contributed by connectors — e.g. <font face='Courier'>sap_hana_query_v1</font> "
     "(SAP HANA Cloud) and <font face='Courier'>rpa_dispatch_v1</font> (RPA Bridge) — alongside "
     "the <b>Models &amp; Providers</b> portal with wired LLM providers and per-workspace routing."),
    ("Orchestration primitives",
     "Trigger nodes (schedules, signed webhooks, file-arrival events), human decision gates with "
     "expiry rules, and a run inbox for long-lived processes. The RPA Bridge dispatches jobs "
     "through a generic REST contract (a mock orchestrator answers in the Showcase)."),
]
for title, desc in found:
    story.append(KeepTogether([
        Paragraph(title, S_H3),
        Paragraph(desc, S_BODY_M),
    ]))

band("Feel free to browse and run what is there. For the structured hands-on part — building and "
     "modifying flows yourselves, replay scenarios, connector configuration — we will schedule a "
     "<b>dedicated guided session</b> with our team (section 5): it is the fastest way to get real "
     "value from the platform.")

# ---------------------------------------------------------------- 5 guided session
story.append(Paragraph("5 · Guided hands-on session — the next step", S_H2))
story.append(Paragraph(
    "Rather than leaving you alone with a set of exercises, we propose a <b>live guided "
    "hands-on session (60–90 min)</b> with our team, scheduled at your convenience shortly after "
    "your access is confirmed. Agenda, driven by your priorities:", S_BODY))
bullet("Build and edit a flow end-to-end in the <b>Flow Builder</b>, and execute it live.")
bullet("<b>Replay</b> a run and walk its full trace — inputs, outputs, timing, cost per step.")
bullet("Configure a <b>connector</b> (SAP HANA Cloud) and see its skills land in the catalog.")
bullet("<b>Orchestration &amp; RPA</b> — triggers, decision gates, and job dispatch through the RPA Bridge.")
bullet("Open Q&amp;A on architecture, governance and your evaluation criteria.")
story.append(Paragraph(
    "Your Datategy contact (see invitation email) will propose slots. In the meantime, individual "
    "exploration of the Showcase is welcome — nothing you do there can break anything.", S_BODY_M))

# ---------------------------------------------------------------- 6 focus map
story.append(Paragraph("6 · Your focus areas — where each one lives", S_H2))
table(
    ["Your topic", "Where to look", "Status in Showcase today"],
    [
        ["Flow Builder", "Build perspective → Flow Builder", "Live — editable Node Inspector, Execute, run results in place"],
        ["System / System 360", "Portfolio → any System", "Live — four perspectives (Build / Operate / Steer / Govern)"],
        ["Replay", "Run detail → Rerun", "Live — DAG-level replay; certified replay with evidence file is the R&amp;D axis presented in the deck"],
        ["Skills", "Node palette / catalog", "Live — typed skills, connector-contributed"],
        ["Observability", "Operate + Steer (Hypervisor)", "Live — step traces, cost per step, portfolio cost/value/ROI"],
        ["Orchestration", "Triggers, gates, run inbox, memory", "Live — schedules, webhooks, durable gates with expiry"],
        ["Automation (RPA / UiPath)", "RPA Bridge + rpa_dispatch_v1", "Live via generic REST bridge (mock orchestrator in Showcase); the contract maps 1:1 to UiPath Orchestrator — dedicated UiPath profiles mobilise with 60 days' notice, per our RFI response"],
        ["SAP connectivity", "Connectors → SAP HANA Cloud", "Live — encrypted config, test/query, demo dataset seeded"],
        ["Databricks connectivity", "Connectors rail", "Same connector pattern (SQL endpoint); walkthrough on request — agents consume governed data products through Unity Catalog, as described in our RFI response"],
    ],
    [34 * mm, 48 * mm, CW - 34 * mm - 48 * mm],
)

# ---------------------------------------------------------------- 7 ground rules
story.append(Paragraph("7 · Ground rules &amp; support", S_H2))
bullet("<b>Data</b> — synthetic/anonymised only. Please do not upload PIH production data to the Showcase tenant.")
bullet("<b>Licence</b> — time-boxed evaluation access; no commercial commitment implied.")
bullet("<b>Audit</b> — every action in the workspace is ledgered; inspect your own trail — that is the governance working.")
bullet("<b>Support</b> — one named Datategy contact (see invitation email) · guided session on request · "
       "feedback goes straight into the pilot design.")
band("The same platform you are touching deploys unchanged to an Azure Qatar tenancy, on-premise or "
     "air-gapped — <b>what you evaluate is what you get</b>.", bg=HexColor("#0B2545"), color=HexColor("#BED0E8"))

doc.build(story)
print("saved:", OUT)
