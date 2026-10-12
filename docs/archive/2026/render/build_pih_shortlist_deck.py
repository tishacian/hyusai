# -*- coding: utf-8 -*-
"""Datategy × PIH — shortlist presentation deck (2h meeting, EN, 16:9).

Agenda: 1) Company Presentation & References  2) Full Products Overview
3) Platform Walkthrough (live demo ~20-30 min)  4) SaaS Demo Access (PIH account).

Content strictly aligned with the submitted dossier:
- RFI-PIH-AI-Factory-Response-v8.docx (delivery model, scale-up, pricing principles)
- Annex B v7 (commercial figures) · Annex C (case studies, anonymised)
- Agentium-Product-Overview-PIH.docx (product capabilities)
- PIH-scope-exclusif-RD-agentium-executive-EN.pptx (disruptive R&D axes)
Company facts from "Datategy PIH Qatar.pdf", visual charter cleaned up.
NOTE: no UAE references (geopolitical sensitivity); KSA kept.

Output: out/Datategy-PIH-Shortlist-Presentation.pptx
"""
import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(HERE, "assets", "logo_datategy.png")
SCREENS = os.path.join(HERE, "assets", "screens")
SHOTS = os.path.join(HERE, "assets", "screenshots")
LOGOS = os.path.join(HERE, "assets", "logos")
OUT = os.path.join(HERE, "out", "Datategy-PIH-Shortlist-Presentation.pptx")

SW, SH = 13.333, 7.5
MX = 0.62
INK = RGBColor(0x15, 0x1A, 0x23)
MUT = RGBColor(0x59, 0x63, 0x71)
LINE = RGBColor(0xD7, 0xDC, 0xE3)
PANEL = RGBColor(0xF3, 0xF5, 0xF8)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
NAVY = RGBColor(0x0B, 0x25, 0x45)
BLUE = RGBColor(0x2D, 0x6C, 0xDF)
PURPLE = RGBColor(0x6D, 0x28, 0xD9)
GREEN = RGBColor(0x0E, 0x8F, 0x62)
AMBER = RGBColor(0xB4, 0x53, 0x09)
TINTBLUE = RGBColor(0xEA, 0xF1, 0xFD)
LIGHTBLUE = RGBColor(0xBE, 0xD0, 0xE8)
F = "Arial"
FM = "Courier New"
FOOTER = "Datategy × PIH — Shortlist presentation — Confidential · July 2026"

prs = Presentation()
prs.slide_width = Inches(SW)
prs.slide_height = Inches(SH)
BLANK = prs.slide_layouts[6]
PAGE = [0]


def slide():
    PAGE[0] += 1
    return prs.slides.add_slide(BLANK)


def box(s, x, y, w, h, anchor=None):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    if anchor is not None:
        tf.vertical_anchor = anchor
    return tf


def para(tf, text, size=12, color=INK, bold=False, mono=False, first=False,
         before=4, after=0, align=PP_ALIGN.LEFT, spacing=1.0):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.space_before = Pt(0 if first else before)
    p.space_after = Pt(after)
    p.line_spacing = spacing
    r = p.add_run()
    r.text = text
    r.font.name = FM if mono else F
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color
    return p


def add_run(p, text, size=12, color=INK, bold=False, mono=False):
    r = p.add_run()
    r.text = text
    r.font.name = FM if mono else F
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color
    return r


def rect(s, x, y, w, h, fill, line_color=None, shape=MSO_SHAPE.RECTANGLE, radius=None):
    sp = s.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        sp.fill.background()
    else:
        sp.fill.solid()
        sp.fill.fore_color.rgb = fill
    if line_color is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line_color
        sp.line.width = Pt(0.75)
    if radius is not None and shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        try:
            sp.adjustments[0] = radius
        except Exception:
            pass
    sp.shadow.inherit = False
    return sp


def logo(s, dark_bg=False):
    if os.path.exists(LOGO):
        s.shapes.add_picture(LOGO, Inches(SW - MX - 1.45), Inches(0.42), height=Inches(0.34))


def chrome(s, kicker, title, accent=NAVY):
    rect(s, MX, 0.52, 0.30, 0.045, accent)
    tf = box(s, MX + 0.42, 0.40, SW - 2 * MX - 2.0, 0.3)
    para(tf, kicker.upper(), size=10.5, color=accent, bold=True, mono=True, first=True)
    tf = box(s, MX, 0.72, SW - 2 * MX - 1.6, 0.62)
    para(tf, title, size=24, color=INK, bold=True, first=True)
    rect(s, MX, 1.38, SW - 2 * MX, 0.012, LINE)
    tf = box(s, MX, SH - 0.42, 9.5, 0.3)
    para(tf, FOOTER, size=8.5, color=MUT, first=True)
    tf = box(s, SW - MX - 1.0, SH - 0.42, 1.0, 0.3)
    para(tf, f"{PAGE[0]:02d}", size=9, color=MUT, mono=True, first=True, align=PP_ALIGN.RIGHT)
    logo(s)


def panel_card(s, x, y, w, h, accent, title, subtitle=None, title_size=13):
    rect(s, x, y, w, h, WHITE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.045)
    rect(s, x, y + 0.12, 0.05, h - 0.24, accent)
    tf = box(s, x + 0.22, y + 0.13, w - 0.4, 0.55 if subtitle else 0.35)
    para(tf, title, size=title_size, color=accent, bold=True, first=True)
    if subtitle:
        para(tf, subtitle, size=9.5, color=MUT, mono=True, before=1)
    return box(s, x + 0.22, y + (0.66 if subtitle else 0.52), w - 0.4, h - (0.82 if subtitle else 0.68))


def bullets(tf, items, size=10.5, before=5, spacing=1.02, color_head=INK, color_body=MUT):
    for i, it in enumerate(items):
        if isinstance(it, tuple):
            head, body = it
            p = para(tf, "▪ ", size=size, color=color_head, first=(i == 0), before=before, spacing=spacing)
            add_run(p, head + " — ", size=size, color=color_head, bold=True)
            add_run(p, body, size=size, color=color_body)
        else:
            para(tf, "▪ " + it, size=size, color=color_body, first=(i == 0), before=before, spacing=spacing)


def client_logo(s, name, x=None, y=0.0, h=0.30, right=None):
    """Place a client logo by height (aspect preserved). Anchor by left x or right edge."""
    path = os.path.join(LOGOS, f"{name}.png")
    if not os.path.exists(path):
        return None
    pic = s.shapes.add_picture(path, Inches(x if x is not None else 0), Inches(y), height=Inches(h))
    if right is not None:
        pic.left = Inches(right) - pic.width
    pic.shadow.inherit = False
    return pic


def screenshot(s, path, x, w, y=None, bottom=None):
    pic = s.shapes.add_picture(path, Inches(x), Inches(y or 0), width=Inches(w))
    if bottom is not None:
        pic.top = Inches(bottom) - pic.height
    pic.line.color.rgb = LINE
    pic.line.width = Pt(1.0)
    pic.shadow.inherit = False
    return pic


def divider(part_no, part_title, duration, items):
    s = slide()
    rect(s, 0, 0, SW, SH, NAVY)
    rect(s, MX, 2.10, 0.55, 0.06, BLUE)
    tf = box(s, MX, 2.35, 3.0, 0.5)
    para(tf, f"PART {part_no} · {duration}", size=13, color=LIGHTBLUE, bold=True, mono=True, first=True)
    tf = box(s, MX, 2.85, SW - 2 * MX, 1.2)
    para(tf, part_title, size=36, color=WHITE, bold=True, first=True)
    tf = box(s, MX, 4.25, SW - 2 * MX - 2.0, 2.2)
    for i, it in enumerate(items):
        para(tf, "—  " + it, size=14, color=LIGHTBLUE, first=(i == 0), before=8)
    tf = box(s, MX, SH - 0.5, 9.5, 0.3)
    para(tf, FOOTER, size=8.5, color=RGBColor(0x7C, 0x8D, 0xA6), first=True)
    if os.path.exists(LOGO):
        s.shapes.add_picture(LOGO, Inches(SW - MX - 1.45), Inches(0.5), height=Inches(0.36))
    return s


def kpi_row(s, y, kpis, w_total=None, x0=MX, h=1.05):
    w_total = w_total or (SW - 2 * MX)
    gap = 0.18
    n = len(kpis)
    w = (w_total - (n - 1) * gap) / n
    for i, (value, label) in enumerate(kpis):
        x = x0 + i * (w + gap)
        rect(s, x, y, w, h, PANEL, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
        tf = box(s, x + 0.12, y + 0.14, w - 0.24, 0.45)
        para(tf, value, size=21, color=NAVY, bold=True, first=True, align=PP_ALIGN.CENTER)
        tf = box(s, x + 0.12, y + 0.60, w - 0.24, 0.4)
        para(tf, label, size=9.5, color=MUT, first=True, align=PP_ALIGN.CENTER)


# ================================================================ 01 · COVER
s = slide()
rect(s, 0, 0, SW, SH, NAVY)
rect(s, 0, 0, SW, 0.10, BLUE)
tf = box(s, MX, 1.75, SW - 2 * MX, 0.4)
para(tf, "DATATEGY × PIH  ·  AI FACTORY PROGRAMME  ·  SHORTLIST PRESENTATION", size=12.5,
     color=LIGHTBLUE, bold=True, mono=True, first=True)
tf = box(s, MX, 2.25, SW - 2 * MX, 1.8)
para(tf, "The AI Factory, delivered as a product", size=40, color=WHITE, bold=True, first=True)
para(tf, "Sovereign platform · governed agents · factory economics — aligned with our RFI response (v8)",
     size=16, color=LIGHTBLUE, before=12)
tf = box(s, MX, 4.55, SW - 2 * MX, 1.4)
for i, line in enumerate([
    "1 · Company presentation & references",
    "2 · Full products overview — architecture, stack, capabilities",
    "3 · Platform walkthrough — live demo",
    "4 · SaaS demo access — PIH account",
]):
    para(tf, line, size=13.5, color=WHITE, first=(i == 0), before=6)
tf = box(s, MX, SH - 0.55, SW - 2 * MX, 0.3)
para(tf, "July 2026 · Doha — Confidential", size=10, color=RGBColor(0x7C, 0x8D, 0xA6), first=True)
if os.path.exists(LOGO):
    s.shapes.add_picture(LOGO, Inches(SW - MX - 1.7), Inches(0.55), height=Inches(0.42))

# ================================================================ 02 · AGENDA
s = slide()
chrome(s, "Agenda", "Two hours, four parts")
rows = [
    ("1", "Company presentation & references", "Who we are, how we deliver, proof in production", "~25 min", BLUE),
    ("2", "Full products overview", "Architecture, stack, capabilities — papAI · Document Center · Agentium", "~35 min", PURPLE),
    ("3", "Platform walkthrough", "Live demo — build, run, evaluate, govern", "~25 min", GREEN),
    ("4", "SaaS demo access — PIH account", "Your environment, scope, security, next steps", "~15 min", AMBER),
]
y = 1.75
for no, t, d, dur, accent in rows:
    rect(s, MX, y, SW - 2 * MX, 1.06, WHITE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
    rect(s, MX, y + 0.10, 0.05, 0.86, accent)
    tf = box(s, MX + 0.28, y + 0.14, 0.7, 0.8, anchor=MSO_ANCHOR.MIDDLE)
    para(tf, no, size=26, color=accent, bold=True, first=True)
    tf = box(s, MX + 1.05, y + 0.16, 8.6, 0.8)
    para(tf, t, size=15, color=INK, bold=True, first=True)
    para(tf, d, size=11, color=MUT, before=3)
    tf = box(s, SW - MX - 1.6, y + 0.14, 1.35, 0.8, anchor=MSO_ANCHOR.MIDDLE)
    para(tf, dur, size=12, color=MUT, bold=True, mono=True, first=True, align=PP_ALIGN.RIGHT)
    y += 1.22
tf = box(s, MX, y + 0.06, SW - 2 * MX, 0.4)
para(tf, "Q&A woven throughout — plus a dedicated buffer at the end of each part.", size=10.5, color=MUT, first=True)

# ================================================================ PART 1 DIVIDER
divider(1, "Company & references", "~25 MIN", [
    "Datategy at a glance — sovereign AI since 2016",
    "Delivery engine — AI & Data Center of Excellence",
    "Four reference case studies in production",
    "Why we fit the AI Factory",
])

# ================================================================ 03 · COMPANY AT A GLANCE
s = slide()
chrome(s, "Part 1 · Company", "Datategy at a glance", accent=BLUE)
tf = box(s, MX, 1.52, SW - 2 * MX, 0.55)
p = para(tf, "Datategy helps organisations turn their data into decisions ", size=12, color=INK, bold=True, first=True)
add_run(p, "by deploying sovereign AI platforms and governed agents — available in SaaS, private cloud or fully "
           "on-premise, making AI technically and financially accessible without giving up control.", size=12, color=MUT)
kpi_row(s, 2.20, [
    ("2016", "Founded — Paris HQ"),
    ("110+", "Employees · 15% PhD"),
    ("50+", "Enterprise clients"),
    ("1,000+", "Platform users"),
    ("3", "Offices — Paris · Brussels · Algiers"),
])
CW = (SW - 2 * MX - 0.24) / 2
tf = panel_card(s, MX, 3.55, CW, 2.20, BLUE, "Labels & certifications")
bullets(tf, [
    ("EU Trusted AI start-up", "selected by the European Union"),
    ("UGAP-referenced", "certified for French public procurement"),
    ("Top 10 AI providers in Europe", "CIO magazine ranking; top AI companies (Wavestone)"),
    ("IEEE-certified research", "peer-reviewed scientific publications (OmniRAG, root-cause analysis)"),
    ("French Tech · Young Innovative Company", "awarded by the French Ministry of Finance"),
], size=10.2, before=4)
tf = panel_card(s, MX + CW + 0.24, 3.55, CW, 2.20, NAVY, "What makes us different")
bullets(tf, [
    ("Product company, not a body shop", "we sell delivered, governed AI systems — not per-user licences or day rates"),
    ("Sovereign by design", "models, data and governance run in the client's perimeter — SaaS to air-gap"),
    ("Evaluation-first", "no agent ships without golden-set evidence; quality is measured, not promised"),
    ("Own R&D", "we control the whole chain — models, ledger, governance — not a wrapper on rented APIs"),
], size=10.2, before=4)
rect(s, MX, 5.95, SW - 2 * MX, 0.62, TINTBLUE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
tf = box(s, MX + 0.28, 6.06, SW - 2 * MX - 0.56, 0.44, anchor=MSO_ANCHOR.MIDDLE)
p = para(tf, "SECTORS IN PRODUCTION.  ", size=10, color=NAVY, bold=True, mono=True, first=True)
add_run(p, "Mobility & transport · energy & utilities · finance & insurance · industrial manufacturing · public sector.",
        size=11, color=INK)

# ================================================================ 04 · DELIVERY ENGINE / CoE
s = slide()
chrome(s, "Part 1 · Delivery engine", "AI & Data Center of Excellence — built to scale", accent=BLUE)
tf = box(s, MX, 1.52, SW - 2 * MX, 0.55)
p = para(tf, "A hub-and-spoke delivery engine — Paris · London · Algiers · KSA — ", size=12, color=INK, bold=True, first=True)
add_run(p, "directed by our Chief Scientific Officer. Senior architecture combined with a scalable build capacity, "
           "English- and Arabic-speaking, with a continuous-recruitment pipeline.", size=12, color=MUT)
CW = (SW - 2 * MX - 0.24) / 2
tf = panel_card(s, MX, 2.20, CW, 2.30, BLUE, "The engine")
bullets(tf, [
    ("Flagship domain", "intelligent process automation — agentic + RPA/BPA convergence (Agentium with UiPath where scope requires)"),
    ("Talent pipeline", "partnership and a dedicated office inside the National School of AI (Algiers) — early identification, structured onboarding"),
    ("Senior profiles", "from top international schools and firms; SAP module SMEs, QA/evaluation engineers, research-grade AI profiles"),
    ("Specialised stacks", "UiPath and Databricks profiles mobilised with 60 days' notice"),
], size=10.2, before=4)
tf = panel_card(s, MX + CW + 0.24, 2.20, CW, 2.30, NAVY, "Scale-up in people, not promises",
                subtitle="AS SUBMITTED IN OUR RFI RESPONSE (§4)")
bullets(tf, [
    ("Phase 1 — validation", "5 → 10 FTE; core squad on-site in Qatar (Factory Lead, SAP SMEs, QA lead)"),
    ("Phase 2 — volume", "10 → 30 → 50 FTE in build cells of 5 around a stable architecture core"),
    ("Phase 3 — cognitive", "research-grade evaluation, RCA and multi-step-reasoning profiles join the core"),
    ("Capacity headroom", "indicative throughput up to 2× the wave plan implied by a 400-agent programme"),
], size=10.2, before=4)
rect(s, MX, 4.65, SW - 2 * MX, 1.90, PANEL, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
tf = box(s, MX + 0.28, 4.80, SW - 2 * MX - 0.56, 1.65)
para(tf, "WHY THIS MATTERS FOR THE AI FACTORY", size=10, color=NAVY, bold=True, mono=True, first=True)
bullets(tf, [
    ("Unit of scaling = the trained engineer", "once a pattern is validated, a single engineer configures, tests and documents a standard reuse-instance agent in the order of a week of effort (planning heuristic — per-agent effort is set at design-card stage by tier)"),
    ("Onboarding is a process, not an apprenticeship", "pattern library + evaluation harness + factory runbooks make each new cell productive within one wave"),
    ("Partnership posture", "white-labelling available on sovereign products; long-term commitment; possible exclusivity arrangements for Qatar"),
], size=10.2, before=4)

# ================================================================ 05 · REFERENCES GRID
s = slide()
chrome(s, "Part 1 · References", "Four reference case studies — in production", accent=BLUE)
tf = box(s, MX, 1.50, SW - 2 * MX, 0.4)
p = para(tf, "The case studies submitted in Annex C of our RFI response — named. ", size=11.5, color=INK, bold=True, first=True)
add_run(p, "Full metrics and reference interviews available under NDA.", size=11.5, color=MUT)
CW = (SW - 2 * MX - 0.24) / 2
CH = 2.24
cards = [
    (BLUE, "1 · Gulf region — smart-city AI in production", "SMART-PARKING OPERATOR · GULF", [
        "Real-time video analytics and parking guidance — live vehicle and occupancy detection at production scale",
        "Streaming ingestion (Kafka), real-time inference, sustained peak throughput",
        "Relevance: production AI operated in the Gulf; pattern-to-shelf reuse economics",
    ]),
    (PURPLE, "2 · Predictive IT operations (AIOps)", "MOBILIZE FINANCIAL SERVICES · RENAULT GROUP", [
        "Proactive prevention of critical IT incidents across a heterogeneous estate (mainframe, ESB, web services)",
        "Millions of log/metric lines (Spark), forecasting, explainable alerts adopted by IT operators",
        "Relevance: Operations & Technology agents — the AgentOps mindset in production",
    ]),
    (GREEN, "3 · Governed multi-agent translation & QA (SAE J2450)", "RENAULT GROUP", [
        "Multi-agent pipeline for technical documentation (XML/DITA) — one QA agent per error class, golden-set gated",
        "Quality equal or superior to human baselines, normed; 400% financial ROI, 1800% turnaround ROI measured",
        "Relevance: the clearest demonstration of factory economics and normed quality governance",
    ]),
    (AMBER, "4 · Enterprise knowledge, retrieval & SAP-integrated agents", "ANDRITZ", [
        "Grounded, cited answers over a multi-million-chunk multilingual technical corpus — client-operated runtime",
        "In production on the same account: S/4HANA-integrated agents collecting installed-base and parts data to drive aftermarket campaigns",
        "Relevance: the knowledge layer of the factory + live SAP S/4HANA integration evidence",
    ]),
]
card_logos = [None, ["mobilize"], ["renault"], ["andritz"]]
for i, (accent, t, sub, items) in enumerate(cards):
    x = MX + (i % 2) * (CW + 0.24)
    y = 1.98 + (i // 2) * (CH + 0.18)
    tf = panel_card(s, x, y, CW, CH, accent, t, subtitle=sub, title_size=11.5)
    bullets(tf, items, size=9.3, before=3)
    if card_logos[i]:
        lx = x + CW - 0.18
        for name in card_logos[i]:
            pic = client_logo(s, name, y=y + 0.14, h=0.30, right=lx)
            if pic is not None:
                lx -= pic.width.inches + 0.14
rect(s, MX, 6.48, SW - 2 * MX, 0.60, TINTBLUE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
tf = box(s, MX + 0.28, 6.56, 2.6, 0.44, anchor=MSO_ANCHOR.MIDDLE)
para(tf, "ALSO IN PRODUCTION", size=9.5, color=NAVY, bold=True, mono=True, first=True)
lx = MX + 3.0
for name, lh in [("ratp", 0.38), ("sncf", 0.40), ("sgp", 0.38), ("aprr", 0.24)]:
    pic = client_logo(s, name, x=lx, y=6.48 + (0.60 - lh) / 2, h=lh)
    if pic is not None:
        lx += pic.width.inches + 0.55
tf = box(s, lx + 0.05, 6.56, SW - MX - lx - 0.3, 0.44, anchor=MSO_ANCHOR.MIDDLE)
para(tf, "+ energy, public-sector and anti-fraud deployments", size=9, color=MUT, first=True)

# ================================================================ 06 · WHY WE FIT
s = slide()
chrome(s, "Part 1 · Fit", "Why Datategy fits the AI Factory", accent=BLUE)
tf = box(s, MX, 1.52, SW - 2 * MX, 0.4)
p = para(tf, "You buy delivered agents — not per-user licences, not execution meters, not day rates. ",
         size=12, color=INK, bold=True, first=True)
add_run(p, "The only model that answers the RFI's factory format line by line.", size=12, color=MUT)
CW = (SW - 2 * MX - 2 * 0.22) / 3
cards = [
    (BLUE, "Factory economics, by construction", [
        "You buy delivered, accepted agents by tier (Simple / Medium / Complex) — all-inclusive, no per-user licences, no execution meters",
        "Reuse built into the model: first-of-type assets identified before build, then every reuse instance benefits — 30/15 reuse targets proven by construction, not promised",
        "Runtime included during the programme; full commercial detail is in our submitted Annex B",
    ]),
    (GREEN, "De-risked delivery", [
        "Core squad on-site in Qatar for the Phase 1 pilot — Factory Lead, SAP module SMEs, QA lead",
        "13-week UCC validation pilot; parallel run on production volume before any privileged automation",
        "Agentium operational at mobilisation — a transitional reference implementation under PIH governance, branding and IP terms while PIH components reach production",
    ]),
    (PURPLE, "Aligned with your estate", [
        "We extend Hikmah — never compete with it: capability discovery at engagement start, MCP-compliant interfaces, no lock-in",
        "Built on the Databricks medallion (Unity Catalog); agents consume and publish governed data products",
        "Perpetual, royalty-free licence to run accepted delivered agent versions — no dependency on a continued relationship",
    ]),
]
for i, (accent, t, items) in enumerate(cards):
    tf = panel_card(s, MX + i * (CW + 0.22), 2.05, CW, 3.55, accent, t, title_size=12.5)
    bullets(tf, items, size=9.8, before=6)
rect(s, MX, 5.80, SW - 2 * MX, 0.80, NAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.07)
tf = box(s, MX + 0.28, 5.92, SW - 2 * MX - 0.56, 0.58, anchor=MSO_ANCHOR.MIDDLE)
p = para(tf, "Predictable by design: ", size=12, color=WHITE, bold=True, first=True)
add_run(p, "a priced catalogue per delivered agent and a capped post-build operating baseline — no consumption "
           "meters, no per-user licences. Full figures in our submitted Annex B.", size=12, color=LIGHTBLUE)

# ================================================================ PART 2 DIVIDER
divider(2, "Full products overview", "~35 MIN", [
    "One sovereign platform, three capabilities",
    "Architecture & deployment models — SaaS to air-gap",
    "Technology stack & integration (SAP, Databricks, Hikmah)",
    "Governance: identity, mandates, audit, evaluation",
    "Beyond the market — four exclusive R&D axes",
])

# ================================================================ 07 · PLATFORM OVERVIEW (3 products)
s = slide()
chrome(s, "Part 2 · Products", "One sovereign AI platform, three capabilities", accent=PURPLE)
tf = box(s, MX, 1.52, SW - 2 * MX, 0.4)
p = para(tf, "papAI is the common sovereign foundation. ", size=11.5, color=INK, bold=True, first=True)
add_run(p, "Document Center and Agentium are not separate products: one platform, one deployment, one governance "
           "and security model — capabilities activated as needs grow.", size=11.5, color=MUT)
CW = (SW - 2 * MX - 2 * 0.24) / 3
CY, CH = 2.02, 4.36
cards = [
    (BLUE, "papAI", "DATA INTELLIGENCE", os.path.join(SCREENS, "papai-features.png"), [
        ("What it does", "turns data into industrialised AI assets: DataOps, AutoML, ML/deep learning, fine-tuning, MLOps"),
        ("Built in", "native orchestration, embedded ML/Spark/RAG engines, no-code + pro-code, drift detection and retraining"),
        ("Typical uses", "predictive maintenance, AIOps, forecasting, risk scoring, fraud detection, computer vision"),
    ]),
    (PURPLE, "Document Center", "KNOWLEDGE INTELLIGENCE", os.path.join(SCREENS, "guide-recherche-anon.png"), [
        ("What it does", "turns documents and expert knowledge into governed, searchable enterprise memory"),
        ("Built in", "OmniRAG sovereign retrieval (peer-reviewed research), cited answers, grounding checks, per-collection access rights"),
        ("Typical uses", "technical documentation assistants, regulatory analysis, expert knowledge capture, document compliance"),
    ]),
    (GREEN, "Agentium", "DECISION INTELLIGENCE", os.path.join(SCREENS, "ui-flow-builder.png"), [
        ("What it does", "turns data and knowledge into governed intelligent systems: agents that decide and act under control"),
        ("Built in", "visual Flow Builder over typed skills, run engine with replay, golden-set evaluation, agent identity and mandates, audit ledger, model router"),
        ("Typical uses", "enterprise assistants, transactional process agents, approval workflows, multi-agent pipelines"),
    ]),
]
for i, (accent, title, sub, img, items) in enumerate(cards):
    x = MX + i * (CW + 0.24)
    tf = panel_card(s, x, CY, CW, CH, accent, title, subtitle=sub)
    bullets(tf, items, size=9.0, before=3)
    screenshot(s, img, x + 0.22, CW - 0.44, bottom=CY + CH - 0.14)
rect(s, MX, 6.50, SW - 2 * MX, 0.52, TINTBLUE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
tf = box(s, MX + 0.28, 6.56, SW - 2 * MX - 0.56, 0.42)
p = para(tf, "ONE GRAMMAR, REUSED EVERYWHERE.  ", size=10, color=NAVY, bold=True, mono=True, first=True)
add_run(p, "Skill → Capability → System → Suite: reusable primitives assemble into business systems and vertical Suites. ",
        size=10.5, color=INK)
add_run(p, "Each delivery enriches the catalogue — the next one starts from assets, not from a blank page.",
        size=10.5, color=INK, bold=True)

# ================================================================ 08 · ARCHITECTURE
s = slide()
chrome(s, "Part 2 · Architecture", "Sovereign architecture — SaaS to air-gap", accent=PURPLE)
tf = box(s, MX, 1.52, SW - 2 * MX, 0.4)
p = para(tf, "Every intelligent system follows one canonical chain: ", size=11.5, color=INK, bold=True, first=True)
add_run(p, "Objective → System → Run → Evaluation → Decision → Action. What runs is measured; what is measured is governed.",
        size=11.5, color=MUT)
# layered architecture diagram (simple bands)
layers = [
    (NAVY, "EXPERIENCE", "Business UIs · assistants · approvals · Hypervisor (cost / value / ROI) · APIs & MCP interfaces"),
    (PURPLE, "ORCHESTRATION", "Flow Builder · run engine (stateful, resumable, replayable) · model router · agent identity & mandates"),
    (BLUE, "KNOWLEDGE & DATA", "OmniRAG retrieval · vector store (Qdrant) · Databricks medallion / Unity Catalog · SAP & enterprise connectors"),
    (GREEN, "GOVERNANCE", "RBAC + ABAC (Keycloak/OIDC) · audit ledger · golden-set evaluation gates · budget caps per run"),
    (AMBER, "INFRASTRUCTURE", "Kubernetes · sovereign model serving (vLLM/Ollama) · PostgreSQL HA · MinIO object storage · GPU pool"),
]
y = 2.10
for accent, name, desc in layers:
    rect(s, MX, y, SW - 2 * MX, 0.62, WHITE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
    rect(s, MX, y + 0.08, 0.05, 0.46, accent)
    tf = box(s, MX + 0.24, y + 0.09, 2.2, 0.44, anchor=MSO_ANCHOR.MIDDLE)
    para(tf, name, size=10.5, color=accent, bold=True, mono=True, first=True)
    tf = box(s, MX + 2.55, y + 0.09, SW - 2 * MX - 2.85, 0.44, anchor=MSO_ANCHOR.MIDDLE)
    para(tf, desc, size=10.5, color=MUT, first=True)
    y += 0.74
rect(s, MX, y + 0.04, SW - 2 * MX, 1.10, PANEL, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
tf = box(s, MX + 0.28, y + 0.16, SW - 2 * MX - 0.56, 0.9)
para(tf, "DEPLOYMENT & INFERENCE — PER YOUR CLARIFICATION D13/D14", size=9.5, color=NAVY, bold=True, mono=True, first=True)
p = para(tf, "Same platform in SaaS, private cloud, on-premise or air-gap. Three sovereign inference models: ", size=10.2, color=MUT, before=4)
add_run(p, "cloud-hosted sovereign (Azure Qatar, PIH tenancy, no Datategy fee) · partner-provided (optional managed service) · "
           "PIH-provisioned on-premise (Datategy deploys and operates the serving stack). ", size=10.2, color=INK, bold=True)
add_run(p, "Routing per agent follows its data classification at design-card stage.", size=10.2, color=MUT)

# ================================================================ 08b · UNIFIED ARCHITECTURE DIAGRAM
def chip(s, x, y, w, text, accent=MUT, h=0.30, fill=WHITE):
    rect(s, x, y, w, h, fill, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.5)
    tf = box(s, x + 0.05, y + 0.02, w - 0.10, h - 0.04, anchor=MSO_ANCHOR.MIDDLE)
    para(tf, text, size=8, color=accent, bold=True, first=True, align=PP_ALIGN.CENTER)


def chip_row(s, x, y, specs, gap=0.10):
    cx = x
    for text, w in specs:
        chip(s, cx, y, w, text)
        cx += w + gap


def plane(s, x, y, w, h, accent, title, sub):
    rect(s, x, y, w, h, WHITE, line_color=accent, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.035)
    rect(s, x, y, w, 0.44, accent, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.035)
    rect(s, x, y + 0.22, w, 0.22, accent)  # square off the header bottom
    tf = box(s, x + 0.16, y + 0.04, w - 0.32, 0.38, anchor=MSO_ANCHOR.MIDDLE)
    p = para(tf, title + "  ", size=12, color=WHITE, bold=True, first=True)
    add_run(p, sub, size=8.5, color=RGBColor(0xDD, 0xE6, 0xF5), mono=True)


def arrow_label(s, x, y, w, text, accent=MUT, up=False):
    shp = MSO_SHAPE.UP_ARROW if up else MSO_SHAPE.RIGHT_ARROW
    ah = 0.30 if not up else 0.34
    aw = w if not up else 0.30
    a = rect(s, x, y, aw, ah, TINTBLUE, line_color=LIGHTBLUE, shape=shp)
    tf = box(s, x - 0.55 + (0 if up else 0), y + (0.36 if up else 0.34), w + 1.1, 0.24)
    para(tf, text, size=7.5, color=accent, mono=True, bold=True, first=True, align=PP_ALIGN.CENTER)


s = slide()
chrome(s, "Part 2 · Architecture", "One backbone — papAI, Agentium and Document Center together", accent=PURPLE)
tf = box(s, MX, 1.48, SW - 2 * MX, 0.36)
p = para(tf, "Not three products glued together: ", size=11, color=INK, bold=True, first=True)
add_run(p, "one deployment, one security model, one audit plane — papAI produces the models, Document Center "
           "produces the knowledge, Agentium turns both into governed action.", size=11, color=MUT)

PLW = 5.42
PLH = 1.92
plane(s, MX, 1.95, PLW, PLH, BLUE, "papAI", "DATA & ML PLANE")
chip_row(s, MX + 0.16, 2.52, [("DataOps / pipelines", 1.62), ("AutoML · fine-tuning", 1.62), ("MLOps registry", 1.30)])
chip_row(s, MX + 0.16, 2.90, [("Spark / lakehouse jobs", 1.78), ("Drift detection · retraining", 2.10)])
tf = box(s, MX + 0.16, 3.32, PLW - 0.32, 0.45)
para(tf, "Ships versioned, evaluated models — served through the shared model router.",
     size=8.5, color=MUT, first=True)

AX = SW - MX - PLW
plane(s, AX, 1.95, PLW, PLH, GREEN, "Agentium", "AGENTIC PLANE")
chip_row(s, AX + 0.16, 2.52, [("Flow Builder (typed skills)", 2.02), ("Run engine · replay", 1.62), ("Model router", 1.10)])
chip_row(s, AX + 0.16, 2.90, [("Identity & mandates", 1.60), ("Evaluation gates", 1.38), ("Audit ledger", 1.10)])
tf = box(s, AX + 0.16, 3.32, PLW - 0.32, 0.45)
para(tf, "Consumes models and knowledge; every action traced, budgeted and replayable.",
     size=8.5, color=MUT, first=True)

# horizontal arrow papAI -> Agentium
mid_x = MX + PLW + 0.12
arrow_label(s, mid_x, 2.55, AX - mid_x - 0.12, "models · router", accent=BLUE)

# knowledge plane
KY = 4.18
plane(s, MX, KY, SW - 2 * MX, 1.16, PURPLE, "Document Center", "KNOWLEDGE PLANE · OMNIRAG")
chip_row(s, MX + 0.16, KY + 0.56, [
    ("Multi-format ingestion + OCR", 2.05), ("Chunking & enrichment", 1.70), ("Qdrant vector store (HA ×2)", 2.00),
    ("Hybrid retrieval + re-ranking", 2.05), ("Per-claim citations", 1.45), ("Collection-level ACLs", 1.55),
])
# up arrows knowledge -> planes
a = rect(s, MX + PLW / 2 - 0.15, 3.92, 0.30, 0.24, TINTBLUE, line_color=LIGHTBLUE, shape=MSO_SHAPE.UP_ARROW)
a = rect(s, AX + PLW / 2 - 0.15, 3.92, 0.30, 0.24, TINTBLUE, line_color=LIGHTBLUE, shape=MSO_SHAPE.UP_ARROW)
tf = box(s, MX + PLW + 0.10, 3.94, AX - MX - PLW - 0.20, 0.24, anchor=MSO_ANCHOR.MIDDLE)
para(tf, "grounded knowledge, cited", size=7.5, color=PURPLE, mono=True, bold=True, first=True, align=PP_ALIGN.CENTER)

# foundation
FY = 5.56
plane(s, MX, FY, SW - 2 * MX, 1.10, NAVY, "Sovereign foundation", "ONE DEPLOYMENT · SAAS → AIR-GAP")
chip_row(s, MX + 0.16, FY + 0.54, [
    ("Kubernetes", 1.10), ("vLLM / Ollama model serving", 2.25), ("PostgreSQL HA", 1.30),
    ("Qdrant", 0.80), ("MinIO object store", 1.55), ("Keycloak · OIDC (RBAC+ABAC)", 2.30), ("GPU pool", 0.90),
])
tf = box(s, MX, 6.78, SW - 2 * MX, 0.3)
p = para(tf, "Same stack at every deployment tier — ", size=9.5, color=INK, bold=True, first=True)
add_run(p, "what PIH evaluates on SaaS is bit-for-bit what runs in the Azure Qatar tenancy or on-premise.",
        size=9.5, color=MUT)

# ================================================================ 08c · DOCUMENT CENTER RAG AT SCALE
s = slide()
chrome(s, "Part 2 · Knowledge engine", "Document Center — indexing & RAG at industrial scale", accent=PURPLE)
tf = box(s, MX, 1.48, SW - 2 * MX, 0.36)
p = para(tf, "The knowledge layer every agent stands on. ", size=11, color=INK, bold=True, first=True)
add_run(p, "Proven in production on a multi-million-chunk multilingual corpus (Andritz) — grounded, cited, "
           "measured continuously.", size=11, color=MUT)

stages = [
    (BLUE, "1 · INGEST", [
        "Multi-format: PDF, Office, XML/DITA, scans",
        "Industrial OCR + layout analysis",
        "Provenance & version gates (superseded revisions quarantined)",
    ]),
    (PURPLE, "2 · INDEX", [
        "Semantic chunking + metadata enrichment",
        "Embeddings on sovereign serving (vLLM)",
        "Qdrant vector store (HA ×2) + lexical index — incremental, no full re-index",
    ]),
    (GREEN, "3 · RETRIEVE", [
        "Hybrid dense + lexical, fusion & re-ranking",
        "OmniRAG — our peer-reviewed retrieval research",
        "Collection-level ACLs enforced at query time",
    ]),
    (AMBER, "4 · ANSWER", [
        "Grounded generation, per-claim citations",
        "Grounding & hallucination checks before display",
        "Deep-search mode for exhaustive queries",
    ]),
    (NAVY, "5 · IMPROVE", [
        "Expert corrections re-injected (capture workflow)",
        "Golden-set regression on every corpus update",
        "Ingestion quality gate blocks polluting batches",
    ]),
]
CW5 = (SW - 2 * MX - 4 * 0.42) / 5
y0 = 2.02
for i, (accent, t, items) in enumerate(stages):
    x = MX + i * (CW5 + 0.42)
    rect(s, x, y0, CW5, 2.55, WHITE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
    rect(s, x, y0, CW5, 0.36, accent, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
    rect(s, x, y0 + 0.18, CW5, 0.18, accent)
    tf = box(s, x + 0.10, y0 + 0.02, CW5 - 0.20, 0.32, anchor=MSO_ANCHOR.MIDDLE)
    para(tf, t, size=10, color=WHITE, bold=True, mono=True, first=True, align=PP_ALIGN.CENTER)
    tf = box(s, x + 0.14, y0 + 0.48, CW5 - 0.28, 2.0)
    for j, it in enumerate(items):
        para(tf, "▪ " + it, size=8.6, color=MUT, first=(j == 0), before=4, spacing=1.0)
    if i < 4:
        rect(s, x + CW5 + 0.06, y0 + 1.10, 0.30, 0.26, TINTBLUE, line_color=LIGHTBLUE, shape=MSO_SHAPE.RIGHT_ARROW)

# feedback loop arrow
rect(s, MX + 1.2, 4.72, SW - 2 * MX - 2.4, 0.20, PANEL, line_color=LINE, shape=MSO_SHAPE.LEFT_ARROW)
tf = box(s, MX + 1.2, 4.96, SW - 2 * MX - 2.4, 0.22)
para(tf, "corrections, golden-set cases and usage signals feed the corpus and the retrieval — the system improves with use",
     size=8, color=MUT, mono=True, first=True, align=PP_ALIGN.CENTER)

kpi_row(s, 5.40, [
    ("Multi-million", "chunks in one production corpus"),
    ("Hybrid + re-rank", "dense · lexical · fusion (OmniRAG)"),
    ("Per-claim", "source citations on every answer"),
    ("HA ×2", "Qdrant vector store, replicated"),
    ("Golden-set", "quality tracked release over release"),
], h=1.00)
tf = box(s, MX, 6.60, SW - 2 * MX, 0.4)
p = para(tf, "Why it matters for the Factory: ", size=10, color=INK, bold=True, first=True)
add_run(p, "one governed memory serves many agents — Assistive agents cite it, Analytical agents query it, "
           "Autonomous agents act on it under mandate. Build the corpus once, reuse it across every wave.",
        size=10, color=MUT)

# ================================================================ 09 · GOVERNANCE
s = slide()
chrome(s, "Part 2 · Governance", "Governed, sovereign, measurable — by design", accent=PURPLE)
CW2 = (SW - 2 * MX - 3 * 0.22) / 4
pillars = [
    (BLUE, "Evaluated by default", [
        "Golden sets and quality scoring per system; industry-normed where it exists (e.g. SAE J2450)",
        "Drift detection in production; no prompt or model change without passing regression",
    ]),
    (PURPLE, "Governed & auditable", [
        "Agents hold their own identity with scoped, time-boxed mandates",
        "Full audit ledger: every run, tool call, cost and human decision traced and replayable",
    ]),
    (GREEN, "Human in the loop", [
        "The AI proposes, the expert decides: confidence thresholds, escalation, calibrated alerts",
        "Corrections feed back into knowledge bases, golden sets and models",
    ]),
    (AMBER, "Sovereign by design", [
        "Data and models stay in the client's perimeter — SaaS to air-gap",
        "Open-weight model serving, edge AI and federated learning proven in production",
    ]),
]
for i, (accent, title, items) in enumerate(pillars):
    tf = panel_card(s, MX + i * (CW2 + 0.22), 1.70, CW2, 2.42, accent, title, title_size=12)
    bullets(tf, items, size=9.5, before=5)
y3 = 4.32
PH = 1.82
rect(s, MX, y3, SW - 2 * MX, PH, PANEL, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
shot_w = 2.48
shot_x = SW - MX - 0.22 - shot_w
screenshot(s, os.path.join(SHOTS, "09_evaluation.png"), shot_x, shot_w, y=y3 + 0.08)
tf = box(s, shot_x, y3 + 0.08 + shot_w * 0.625 + 0.03, shot_w, 0.2)
para(tf, "Hypervisor — live cost, value & ROI", size=7.5, color=MUT, mono=True, first=True, align=PP_ALIGN.RIGHT)
tf = box(s, MX + 0.28, y3 + 0.16, shot_x - MX - 0.56, PH - 0.3)
p = para(tf, "STEERED WITH NUMBERS.  ", size=10, color=NAVY, bold=True, mono=True, first=True)
add_run(p, "The Hypervisor reads the platform as a balance sheet: cost, business value and ROI per capability, "
           "live. Every delivered agent reports its runs, cost per execution and confidence — the numbers PIH's "
           "steering committee sees are the numbers the platform produces, not a slide.", size=10.2, color=MUT)
p = para(tf, "Six foundations already in production: ", size=10.2, color=INK, bold=True, before=6)
add_run(p, "execution memory (run lineage & replay) · action ledger · access control (RBAC+ABAC) · statistical "
           "test bench (A/B on golden sets) · controlled compute budget · models within your walls.", size=10.2, color=MUT)
rect(s, MX, y3 + PH + 0.14, SW - 2 * MX, 0.54, NAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
tf = box(s, MX + 0.28, y3 + PH + 0.245, SW - 2 * MX - 0.56, 0.38)
p = para(tf, "The client does not buy isolated agents or licences per user — ", size=11.5, color=WHITE, bold=True, first=True)
add_run(p, "it deploys complete, governed systems ready to produce measurable value, on infrastructure it controls.",
        size=11.5, color=LIGHTBLUE)

# ================================================================ 10 · FACTORY MODEL
s = slide()
chrome(s, "Part 2 · Factory model", "From agents to a factory — reuse as an economic engine", accent=PURPLE)
tf = box(s, MX, 1.52, SW - 2 * MX, 0.4)
p = para(tf, "The factory is not a metaphor — it is the pricing model. ", size=12, color=INK, bold=True, first=True)
add_run(p, "Every asset built once is reused at catalogue price; the platform enforces the discipline that makes it possible.",
        size=12, color=MUT)
steps = [
    (BLUE, "1 · Design card", "Tier, systems, first-of-type or reuse status, security class, success metrics, acceptance evidence and price — approved before build."),
    (PURPLE, "2 · Build from patterns", "Validated patterns, typed skills and hardened connectors from the library; AI-assisted build (disclosed toolchain, PIH Git, human review on every merge)."),
    (GREEN, "3 · Gate & go live", "Golden-set evaluation gates, parallel run on production volume for privileged flows, six go-live acceptance criteria."),
    (AMBER, "4 · Feed the library", "Every delivery writes back: pattern updates, connector hardening, golden-set cases, runbooks — the next agent starts from assets."),
]
CW = (SW - 2 * MX - 3 * 0.22) / 4
for i, (accent, t, d) in enumerate(steps):
    tf = panel_card(s, MX + i * (CW + 0.22), 2.05, CW, 2.30, accent, t, title_size=11.5)
    para(tf, d, size=9.8, color=MUT, first=True, spacing=1.05)
rect(s, MX, 4.55, SW - 2 * MX, 1.95, PANEL, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
tf = box(s, MX + 0.28, 4.70, SW - 2 * MX - 0.56, 1.7)
para(tf, "WHAT THIS PRODUCES — COMMITMENTS FROM OUR RFI RESPONSE", size=9.5, color=NAVY, bold=True, mono=True, first=True)
bullets(tf, [
    ("A priced catalogue, not estimates", "every delivered agent has a tier and a catalogue reference; first-of-type assets are identified and approved before build — no open-ended engineering"),
    ("Reuse targets by construction", "30% component reuse / 15% cost reduction trajectory measured on accepted reuse instances — visible in the catalogue, not asserted in a slide"),
    ("Unit economics improve with volume", "the more the factory delivers, the more each next agent starts from existing assets; runtime included, no execution meters during the programme"),
], size=10.2, before=5)

# ================================================================ 11 · INTEGRATION
s = slide()
chrome(s, "Part 2 · Integration", "Your estate, extended — SAP, Databricks, Hikmah", accent=PURPLE)
CW = (SW - 2 * MX - 2 * 0.22) / 3
cards = [
    (BLUE, "SAP S/4HANA", [
        "Live in production at Andritz: S/4HANA-integrated agents collecting installed-base and parts data to drive aftermarket campaigns",
        "OData reads, BAPI/RFC wrapped as typed skills with bounded retries and idempotency; IDoc/CDC where streaming is required",
        "Financial postings: parallel run against human postings, weekly GL reconciliation during hypercare, external SoD review before go-live",
    ]),
    (AMBER, "Databricks lakehouse", [
        "We build on your medallion (ADLS, Delta Lake, Unity Catalog, MLflow) with SAP Datasphere as a primary source",
        "Agents consume governed Gold data products through Unity Catalog and inherit dataset-level access — never bypassing the medallion",
        "Agents are consumers and publishers: they strengthen the lakehouse investment",
    ]),
    (GREEN, "Hikmah & Abstraction Layer", [
        "We extend Hikmah, never compete with it — capability discovery against existing components at engagement start (per C9/C10)",
        "Agentium proposed as the transitional reference implementation under PIH governance, branding and IP (per C8) — operational at mobilisation, MCP-compliant, handover without rework",
        "Protects the October go-live from dependency on components still in build",
    ]),
]
for i, (accent, t, items) in enumerate(cards):
    tf = panel_card(s, MX + i * (CW + 0.22), 1.72, CW, 3.80, accent, t, title_size=13)
    bullets(tf, items, size=9.7, before=6)
rect(s, MX, 5.72, SW - 2 * MX, 0.80, TINTBLUE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.07)
tf = box(s, MX + 0.28, 5.84, SW - 2 * MX - 0.56, 0.58, anchor=MSO_ANCHOR.MIDDLE)
p = para(tf, "PORTABILITY GUARANTEED.  ", size=10, color=NAVY, bold=True, mono=True, first=True)
add_run(p, "Delivered flows, design cards, evaluation evidence and connector mappings are exportable; PIH holds a "
           "perpetual licence to run accepted agent versions — with or without Datategy.", size=11, color=INK)

# ================================================================ 12 · DISRUPTIVE R&D
s = slide()
chrome(s, "Part 2 · Beyond the market", "They rent their models. We own the whole machine.", accent=PURPLE)
tf = box(s, MX, 1.52, SW - 2 * MX, 0.55)
p = para(tf, "Competing platforms run models they rent from the cloud — they control neither the engine nor the gearbox. ",
         size=11.5, color=INK, bold=True, first=True)
add_run(p, "Agentium controls the whole chain: models, action ledger, governance. Four exclusive R&D axes are built on that "
           "control — each reuses at least two foundations already in production.", size=11.5, color=MUT)
CW = (SW - 2 * MX - 0.24) / 2
CH = 1.86
axes = [
    (NAVY, "AXIS A — The black box", "CERTIFIED EXECUTION",
     "Every agent decision can be replayed identically months later — with a signed evidence file to hand to an auditor. "
     "Impossible for cloud-rented models that change without notice."),
    (BLUE, "AXIS B — The power of attorney", "AGENT MANDATES",
     "An agent can never exceed the mandate it was given: authorised actions, caps, validity period. Everything signed, "
     "revocable in one click — autonomy becomes authorisable on sensitive scopes."),
    (GREEN, "AXIS C — The dress rehearsal", "GOVERNED SELF-IMPROVEMENT",
     "The platform proposes its own adjustments, proves them first on hundreds of past cases (A/B on golden sets), and a "
     "human validates — with progressive rollout and automatic rollback."),
    (AMBER, "AXIS D — The priority lane", "CAPACITY MANAGEMENT",
     "On finite sovereign compute, critical usage always gets through; the rest slows in a known order. Each department "
     "pays for what it consumes — chargeback built in."),
]
for i, (accent, t, sub, d) in enumerate(axes):
    x = MX + (i % 2) * (CW + 0.24)
    y = 2.22 + (i // 2) * (CH + 0.20)
    tf = panel_card(s, x, y, CW, CH, accent, t, subtitle=sub, title_size=12.5)
    para(tf, d, size=10, color=MUT, first=True, spacing=1.05)
rect(s, MX, 6.40, SW - 2 * MX, 0.62, NAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
tf = box(s, MX + 0.28, 6.51, SW - 2 * MX - 0.56, 0.44, anchor=MSO_ANCHOR.MIDDLE)
p = para(tf, "Sovereignty stops being a constraint — it becomes the advantage. ", size=11.5, color=WHITE, bold=True, first=True)
add_run(p, "What is hard to do is hard to copy: none of this is available to a platform that rents its models.",
        size=11.5, color=LIGHTBLUE)

# ================================================================ PART 3 DIVIDER
divider(3, "Platform walkthrough — live demo", "~25 MIN", [
    "Build — assemble an agent in the Flow Builder from typed skills",
    "Run — execute, pause, resume; inspect the full run trace",
    "Evaluate — golden-set gates; a change must prove it does better",
    "Govern — identity, mandates, audit ledger, Hypervisor ROI view",
    "Ask — grounded, cited answers over a technical corpus (Document Center)",
])

# ================================================================ 13 · DEMO STORYLINE
s = slide()
chrome(s, "Part 3 · Live demo", "What you will see — five moments, one platform", accent=GREEN)
steps = [
    ("1 · BUILD", BLUE, "Flow Builder", "Assemble a governed agent from typed skills and connectors — the same grammar your teams would use. Pattern reuse visible in the node library."),
    ("2 · RUN", PURPLE, "Run engine", "Execute the agent live: stateful runs, pause/resume, full trace of every step, tool call and cost. Nothing is a black box."),
    ("3 · EVALUATE", GREEN, "Evaluation harness", "Golden-set scoring on real cases; a prompt or model change must pass regression before production — quality is a gate, not a hope."),
    ("4 · GOVERN", AMBER, "Identity · ledger · Hypervisor", "Agent identity and scoped permissions; the audit ledger of every action; the Hypervisor reading cost, value and ROI per capability, live."),
    ("5 · ASK", NAVY, "Document Center", "Grounded, source-cited answers over an industrial technical corpus — with deep search and expert correction feeding back into the knowledge base."),
]
y = 1.72
for tag, accent, t, d in steps:
    rect(s, MX, y, SW - 2 * MX, 0.90, WHITE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
    rect(s, MX, y + 0.08, 0.05, 0.74, accent)
    tf = box(s, MX + 0.24, y + 0.10, 1.55, 0.7, anchor=MSO_ANCHOR.MIDDLE)
    para(tf, tag, size=10.5, color=accent, bold=True, mono=True, first=True)
    tf = box(s, MX + 1.95, y + 0.10, 2.3, 0.7, anchor=MSO_ANCHOR.MIDDLE)
    para(tf, t, size=12, color=INK, bold=True, first=True)
    tf = box(s, MX + 4.35, y + 0.10, SW - MX - 0.3 - (MX + 4.35), 0.7, anchor=MSO_ANCHOR.MIDDLE)
    para(tf, d, size=10.2, color=MUT, first=True, spacing=1.0)
    y += 1.02
tf = box(s, MX, y + 0.04, SW - 2 * MX, 0.4)
p = para(tf, "Demo environment: ", size=10.5, color=INK, bold=True, first=True)
add_run(p, "Agentium showcase workspace on our SaaS — the same build PIH will receive access to in Part 4. "
           "All data is synthetic or anonymised.", size=10.5, color=MUT)

# ================================================================ 14 · LIVE DEMO PLACEHOLDER
s = slide()
rect(s, 0, 0, SW, SH, NAVY)
tf = box(s, MX, 2.9, SW - 2 * MX, 1.2, anchor=MSO_ANCHOR.MIDDLE)
para(tf, "LIVE DEMO", size=54, color=WHITE, bold=True, first=True, align=PP_ALIGN.CENTER)
para(tf, "~20–30 minutes · questions welcome as we go", size=15, color=LIGHTBLUE, before=10, align=PP_ALIGN.CENTER)
if os.path.exists(LOGO):
    s.shapes.add_picture(LOGO, Inches(SW - MX - 1.45), Inches(0.5), height=Inches(0.36))

# ================================================================ PART 4 DIVIDER
divider(4, "SaaS demo access — PIH account", "~15 MIN", [
    "Your dedicated PIH workspace — what is provisioned",
    "Scope, security and data rules",
    "A guided evaluation path for your teams",
    "Next steps & engagement path",
])

# ================================================================ 15 · SAAS ACCESS
s = slide()
chrome(s, "Part 4 · SaaS access", "A PIH account on the platform — evaluate it yourselves", accent=AMBER)
CW = (SW - 2 * MX - 0.24) / 2
tf = panel_card(s, MX, 1.72, CW, 2.55, AMBER, "What is provisioned", subtitle="AVAILABLE THIS WEEK")
bullets(tf, [
    ("Dedicated PIH workspace", "on our EU SaaS — isolated tenant, named PIH users with individual accounts (SSO-ready)"),
    ("Showcase capabilities", "the systems from today's demo: agent flows, run traces, evaluation dashboards, Hypervisor, Document Center corpus"),
    ("Sandbox build rights", "your team can assemble and run its own flows from the pattern library — not just watch"),
    ("Support channel", "named Datategy contact; guided session on request; feedback loop into the pilot design"),
], size=10.2, before=5)
tf = panel_card(s, MX + CW + 0.24, 1.72, CW, 2.55, NAVY, "Scope & security rules")
bullets(tf, [
    ("Synthetic and anonymised data only", "no PIH production data in the demo tenancy — by design"),
    ("Evaluation licence", "time-boxed access for the evaluation period; no commercial commitment implied"),
    ("Full audit visibility", "every action in the workspace is ledgered — you see governance working on yourselves"),
    ("Path to sovereign", "the same platform deploys to Azure Qatar tenancy, on-premise or air-gap — what you evaluate is what you get"),
], size=10.2, before=5)
rect(s, MX, 4.47, SW - 2 * MX, 1.55, PANEL, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
tf = box(s, MX + 0.28, 4.62, SW - 2 * MX - 0.56, 1.3)
para(tf, "SUGGESTED EVALUATION PATH — TWO WEEKS, YOUR PACE", size=9.5, color=NAVY, bold=True, mono=True, first=True)
bullets(tf, [
    ("Week 1", "guided walkthrough replay with your team · free exploration of showcase systems · Document Center Q&A on the sample corpus"),
    ("Week 2", "assemble one flow from patterns with our support · review run traces, evaluation gates and Hypervisor together · consolidate questions for the RFP stage"),
], size=10.2, before=5)

# ================================================================ 16 · ENGAGEMENT PATH
s = slide()
chrome(s, "Part 4 · Next steps", "Engagement path — de-risked by construction", accent=AMBER)
steps = [
    (BLUE, "Now — shortlist stage", "SaaS evaluation access · named individuals and CVs · references under NDA · SAP financial-posting evidence"),
    (GREEN, "UCC validation pilot — 13 weeks", "Mobilisation, design, build, parallel run, go-live stabilisation and pattern-library seeding — core squad on-site in Qatar."),
    (PURPLE, "Wave-based industrial delivery", "Delivered agents at catalogue reference · short monthly/wave milestones · outcome commitments tied to objective wave gates"),
    (AMBER, "Post-build continuity", "Enterprise Platform & Managed Operations Baseline + AgentOps · perpetual licence to run accepted agent versions — with or without Datategy"),
]
y = 1.75
for accent, t, d in steps:
    rect(s, MX, y, SW - 2 * MX, 1.02, WHITE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
    rect(s, MX, y + 0.09, 0.05, 0.84, accent)
    tf = box(s, MX + 0.26, y + 0.12, 3.3, 0.8, anchor=MSO_ANCHOR.MIDDLE)
    para(tf, t, size=12.5, color=accent, bold=True, first=True)
    tf = box(s, MX + 3.75, y + 0.12, SW - MX - 0.3 - (MX + 3.75), 0.8, anchor=MSO_ANCHOR.MIDDLE)
    para(tf, d, size=10.5, color=MUT, first=True, spacing=1.02)
    y += 1.16
rect(s, MX, y + 0.05, SW - 2 * MX, 0.62, NAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
tf = box(s, MX + 0.28, y + 0.16, SW - 2 * MX - 0.56, 0.44, anchor=MSO_ANCHOR.MIDDLE)
p = para(tf, "Everything you saw today is in the submitted dossier — ", size=11.5, color=WHITE, bold=True, first=True)
add_run(p, "RFI response, Annex B pricing schedule, Annex C references. No surprises between the presentation and the contract.",
        size=11.5, color=LIGHTBLUE)

# ================================================================ 17 · CLOSING
s = slide()
rect(s, 0, 0, SW, SH, NAVY)
rect(s, 0, SH - 0.10, SW, 0.10, BLUE)
tf = box(s, MX, 2.0, SW - 2 * MX, 0.4)
para(tf, "THANK YOU", size=13, color=LIGHTBLUE, bold=True, mono=True, first=True)
tf = box(s, MX, 2.5, SW - 2 * MX, 1.6)
para(tf, "Sovereign AI, delivered as a product.", size=34, color=WHITE, bold=True, first=True)
para(tf, "Questions & discussion", size=16, color=LIGHTBLUE, before=12)
tf = box(s, MX, 4.7, SW - 2 * MX, 1.4)
for i, line in enumerate([
    "Datategy — 50 Avenue du Général de Gaulle, 92800 Puteaux, France",
    "www.datategy.net",
]):
    para(tf, line, size=12, color=LIGHTBLUE, first=(i == 0), before=6)
if os.path.exists(LOGO):
    s.shapes.add_picture(LOGO, Inches(SW - MX - 1.7), Inches(0.55), height=Inches(0.42))

prs.save(OUT)
print("saved:", OUT, "| slides:", len(prs.slides.__iter__.__self__._sldIdLst))
