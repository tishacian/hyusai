# -*- coding: utf-8 -*-
"""PIH defense meeting deck (2h session, EN, 16:9).

Agenda: 1) Company Presentation & References · 2) Full Products Overview —
Architecture, Stack, Capabilities · 3) Platform Walkthrough (live demo
~20–30 min) · 4) SaaS Demo Access — PIH Account.

Charte inspired by "Datategy PIH Qatar.pdf" (deep navy + vivid blue) but
cleaned up: white content slides, navy dividers, Arial, card system.
Content strictly aligned with RFI-PIH-AI-Factory-Response-v8.docx,
Annex B v7, Annex C case studies and the Agentium Product Overview.
Output: out/Datategy-PIH-Defense-Meeting.pptx
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
OUT = os.path.join(HERE, "out", "Datategy-PIH-Defense-Meeting.pptx")

SW, SH = 13.333, 7.5
MX = 0.62
INK = RGBColor(0x15, 0x1A, 0x23)
MUT = RGBColor(0x59, 0x63, 0x71)
LINE = RGBColor(0xD7, 0xDC, 0xE3)
PANEL = RGBColor(0xF3, 0xF5, 0xF8)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
NAVY = RGBColor(0x0B, 0x25, 0x45)
DEEPNAVY = RGBColor(0x07, 0x1A, 0x33)
BLUE = RGBColor(0x2D, 0x6C, 0xDF)
SKY = RGBColor(0x6E, 0xA8, 0xFF)
PURPLE = RGBColor(0x6D, 0x28, 0xD9)
GREEN = RGBColor(0x0E, 0x8F, 0x62)
AMBER = RGBColor(0xB4, 0x53, 0x09)
TINTBLUE = RGBColor(0xEA, 0xF1, 0xFD)
LIGHTBLUE = RGBColor(0xBE, 0xD0, 0xE8)
F = "Arial"
FM = "Courier New"
FOOTER = "Datategy × Power International Holding — Confidential · July 2026"

prs = Presentation()
prs.slide_width = Inches(SW)
prs.slide_height = Inches(SH)
BLANK = prs.slide_layouts[6]
PAGE = [0]


def slide():
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


def logo(s):
    if os.path.exists(LOGO):
        s.shapes.add_picture(LOGO, Inches(SW - MX - 1.45), Inches(0.42), height=Inches(0.34))


def chrome(s, kicker, title, accent=NAVY, title_size=24):
    PAGE[0] += 1
    rect(s, MX, 0.52, 0.30, 0.045, accent)
    tf = box(s, MX + 0.42, 0.40, SW - 2 * MX - 2.0, 0.3)
    para(tf, kicker.upper(), size=10.5, color=accent, bold=True, mono=True, first=True)
    tf = box(s, MX, 0.72, SW - 2 * MX - 1.6, 0.62)
    para(tf, title, size=title_size, color=INK, bold=True, first=True)
    rect(s, MX, 1.38, SW - 2 * MX, 0.012, LINE)
    tf = box(s, MX, SH - 0.42, 9.0, 0.3)
    para(tf, FOOTER, size=8.5, color=MUT, first=True)
    tf = box(s, SW - MX - 1.0, SH - 0.42, 1.0, 0.3)
    para(tf, f"{PAGE[0]:02d}", size=9, color=MUT, mono=True, first=True, align=PP_ALIGN.RIGHT)
    logo(s)


def divider(s, number, title, subtitle, duration):
    PAGE[0] += 1
    rect(s, 0, 0, SW, SH, DEEPNAVY)
    rect(s, 0, 0, SW, 0.06, BLUE)
    tf = box(s, MX, 2.35, 1.8, 1.2)
    para(tf, number, size=64, color=BLUE, bold=True, mono=True, first=True)
    rect(s, MX + 0.05, 3.65, 0.55, 0.05, BLUE)
    tf = box(s, MX, 3.95, SW - 2 * MX, 1.0)
    para(tf, title, size=34, color=WHITE, bold=True, first=True)
    tf = box(s, MX, 4.85, SW - 2 * MX - 2.0, 0.8)
    para(tf, subtitle, size=14, color=LIGHTBLUE, first=True, spacing=1.15)
    tf = box(s, MX, SH - 0.75, 6.0, 0.3)
    para(tf, duration, size=10.5, color=SKY, mono=True, bold=True, first=True)
    tf = box(s, SW - MX - 1.0, SH - 0.42, 1.0, 0.3)
    para(tf, f"{PAGE[0]:02d}", size=9, color=RGBColor(0x5E, 0x74, 0x94), mono=True, first=True, align=PP_ALIGN.RIGHT)
    if os.path.exists(LOGO):
        s.shapes.add_picture(LOGO, Inches(SW - MX - 1.45), Inches(0.42), height=Inches(0.34))


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


def screenshot(s, path, x, w, y=None, bottom=None, caption=None):
    pic = s.shapes.add_picture(path, Inches(x), Inches(y or 0), width=Inches(w))
    if bottom is not None:
        pic.top = Inches(bottom) - pic.height
    pic.line.color.rgb = LINE
    pic.line.width = Pt(1.0)
    pic.shadow.inherit = False
    if caption:
        h = pic.height / 914400
        top = (pic.top / 914400) + h + 0.04
        tf = box(s, x, top, w, 0.2)
        para(tf, caption, size=7.5, color=MUT, mono=True, first=True)
    return pic


def kpi_row(s, y, items, w_total=None, x0=MX, h=1.05):
    w_total = w_total or (SW - 2 * MX)
    gap = 0.2
    cw = (w_total - gap * (len(items) - 1)) / len(items)
    for i, (val, lab) in enumerate(items):
        x = x0 + i * (cw + gap)
        rect(s, x, y, cw, h, PANEL, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
        tf = box(s, x + 0.1, y + 0.14, cw - 0.2, 0.45)
        para(tf, val, size=19, color=NAVY, bold=True, first=True, align=PP_ALIGN.CENTER)
        tf = box(s, x + 0.1, y + 0.60, cw - 0.2, h - 0.66)
        para(tf, lab, size=9, color=MUT, first=True, align=PP_ALIGN.CENTER, spacing=0.95)


# ============================================================ COVER
s = slide()
PAGE[0] += 1
rect(s, 0, 0, SW, SH, DEEPNAVY)
rect(s, 0, 0, SW, 0.06, BLUE)
rect(s, 0, SH - 0.06, SW, 0.06, BLUE)
if os.path.exists(LOGO):
    s.shapes.add_picture(LOGO, Inches(MX), Inches(0.7), height=Inches(0.5))
tf = box(s, MX, 2.5, SW - 2 * MX, 0.4)
para(tf, "PIH AI FACTORY PROGRAMME — RESPONSE DEFENSE", size=13, color=SKY, bold=True, mono=True, first=True)
tf = box(s, MX, 2.95, SW - 2 * MX, 1.4)
para(tf, "Sovereign AI agents, delivered as a factory", size=40, color=WHITE, bold=True, first=True)
tf = box(s, MX, 4.15, SW - 2 * MX - 2.5, 0.8)
para(tf, "Company · References · Products & Architecture · Live Platform Walkthrough · SaaS Access",
     size=15, color=LIGHTBLUE, first=True, spacing=1.2)
rect(s, MX + 0.02, 5.25, 0.55, 0.05, BLUE)
tf = box(s, MX, 5.5, SW - 2 * MX, 0.8)
para(tf, "Datategy — Power International Holding", size=13, color=WHITE, bold=True, first=True)
para(tf, "Doha · July 2026 · 2-hour session incl. ~30 min live demo", size=11.5, color=LIGHTBLUE, before=4)

# ============================================================ AGENDA
s = slide()
chrome(s, "Agenda", "Two hours, four movements")
items = [
    ("01", "Company presentation & references", "Who we are, how we deliver, and four production references relevant to the AI Factory", "~25 min", BLUE),
    ("02", "Full products overview", "One sovereign platform — architecture, stack, capabilities; how it maps to the Factory requirements", "~35 min", PURPLE),
    ("03", "Platform walkthrough — live demo", "Build, run, evaluate, govern: an agent lifecycle end-to-end on Agentium", "~25 min", GREEN),
    ("04", "SaaS demo access — PIH account", "Your own environment: scope, access, support, and what to test first — then Q&A", "~15 min + Q&A", AMBER),
]
y = 1.75
for num, t, d, dur, accent in items:
    rect(s, MX, y, SW - 2 * MX, 1.16, WHITE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
    rect(s, MX, y + 0.10, 0.05, 0.96, accent)
    tf = box(s, MX + 0.3, y + 0.18, 0.9, 0.8)
    para(tf, num, size=26, color=accent, bold=True, mono=True, first=True)
    tf = box(s, MX + 1.3, y + 0.16, 8.6, 0.9)
    para(tf, t, size=15.5, color=INK, bold=True, first=True)
    para(tf, d, size=11, color=MUT, before=3)
    tf = box(s, SW - MX - 1.9, y + 0.4, 1.6, 0.4)
    para(tf, dur, size=10.5, color=accent, bold=True, mono=True, first=True, align=PP_ALIGN.RIGHT)
    y += 1.32

# ============================================================ DIVIDER 1
divider(slide(), "01", "Company presentation & references",
        "Real-World AI since 2016 — sovereign products, a delivery engine built for volume, and production references that match the Factory's demands.",
        "≈ 25 MINUTES")

# ============================================================ 1.1 AT A GLANCE
s = slide()
chrome(s, "Company", "Datategy at a glance — Real-World AI", accent=BLUE)
kpi_row(s, 1.66, [
    ("2016", "Founded — Paris HQ; Brussels · Algiers; presence UAE · KSA"),
    ("110+", "Employees — 15% PhD; AI research in production, not in papers"),
    ("50+", "Enterprise clients — 1,000+ active users"),
    ("3", "Sovereign products — papAI · Document Center · Agentium"),
])
CW = (SW - 2 * MX - 0.24) / 2
tf = panel_card(s, MX, 2.98, CW, 2.55, BLUE, "What we do")
bullets(tf, [
    ("Mission", "help organisations turn their data into governed, production AI — models and agents that business teams actually use"),
    ("Model", "sovereign software products + a delivery Center of Excellence + training & certification — three components, one accountability"),
    ("Deployment", "SaaS, private cloud, on-premise or air-gapped — the client's perimeter, the client's rules"),
    ("Focus sectors", "mobility, energy & utilities, finance & insurance, industry, public sector"),
], size=10.5)
tf = panel_card(s, MX + CW + 0.24, 2.98, CW, 2.55, NAVY, "Why it matters for PIH")
bullets(tf, [
    ("Product owner, not integrator", "we own the platform end-to-end — models, runtime, governance — which is what makes certified replay and $0-runtime economics possible"),
    ("Factory-native", "our references are pattern-based, evaluation-gated deliveries — the exact operating model the AI Factory requires"),
    ("Gulf-ready", "production AI operated in the Gulf region today; English- and Arabic-speaking delivery capacity"),
], size=10.5)
rect(s, MX, 5.72, SW - 2 * MX, 0.58, TINTBLUE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
tf = box(s, MX + 0.28, 5.82, SW - 2 * MX - 0.56, 0.4)
p = para(tf, "One accountable partner: ", size=11, color=NAVY, bold=True, first=True)
add_run(p, "product, delivery and training under the same roof — no consortium, no subcontracting. Datategy responds as an autonomous prime.", size=11, color=INK)

# ============================================================ 1.2 TRUST MARKS
s = slide()
chrome(s, "Company", "Labels, certifications & recognition", accent=BLUE)
marks = [
    ("EU Trusted AI", "Selected by the European Union as a trusted AI start-up"),
    ("UGAP referenced", "Certified for the French public procurement market"),
    ("French Tech", "Young Innovative Company award — French Ministry of Finance"),
    ("Top 10 AI Europe", "Ranked top-10 European AI provider by CIO magazine"),
    ("IEEE certified", "Certification label for peer-reviewed scientific publications"),
    ("Wavestone ranking", "Ranked among top AI companies (FR ecosystem radar)"),
]
CW = (SW - 2 * MX - 2 * 0.22) / 3
for i, (t, d) in enumerate(marks):
    x = MX + (i % 3) * (CW + 0.22)
    y = 1.75 + (i // 3) * 1.55
    rect(s, x, y, CW, 1.38, WHITE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
    rect(s, x, y + 0.10, 0.05, 1.18, BLUE)
    tf = box(s, x + 0.24, y + 0.16, CW - 0.44, 1.1)
    para(tf, t, size=13.5, color=NAVY, bold=True, first=True)
    para(tf, d, size=10, color=MUT, before=4, spacing=1.05)
rect(s, MX, 5.05, SW - 2 * MX, 1.3, PANEL, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
tf = box(s, MX + 0.28, 5.2, SW - 2 * MX - 0.56, 1.0)
p = para(tf, "RESEARCH IN PRODUCTION.  ", size=10.5, color=NAVY, bold=True, mono=True, first=True)
add_run(p, "Peer-reviewed R&D shipped into the platform: OmniRAG (sovereign retrieval), root-cause analysis, generative time-series models. "
           "Contributor to the EU AI Act consultation — governance is a design input, not an afterthought.", size=11, color=MUT)
p = para(tf, "AI approach — ", size=10.5, color=INK, bold=True, before=6)
add_run(p, "holistic & sovereign: ethical and responsible AI, agnostic and open solutions, no-code + pro-code, explainability by default, green by design.",
        size=10.5, color=MUT)

# ============================================================ 1.3 DELIVERY ENGINE
s = slide()
chrome(s, "Company", "The delivery engine — AI & Data Center of Excellence", accent=BLUE)
tf = box(s, MX, 1.52, SW - 2 * MX, 0.4)
p = para(tf, "A hub-and-spoke delivery engine — Paris · London · Algiers · UAE · KSA — ", size=11.5, color=INK, bold=True, first=True)
add_run(p, "directed by our Chief Scientific Officer, whose flagship domain is intelligent service-desk and process automation.", size=11.5, color=MUT)
CW = (SW - 2 * MX - 2 * 0.24) / 3
cards = [
    (BLUE, "Senior talent, at scale", [
        "Senior profiles from top international schools and firms (Huawei, Viber, Heetch…)",
        "Partnership and secondary office inside the National School of AI — early talent identification, structured onboarding",
        "Continuous-recruitment pipeline; English- and Arabic-speaking teams",
    ]),
    (NAVY, "Built for factory volume", [
        "Build cells of 5 around a stable architecture core — squads scale by adding cells, not inflating teams",
        "Scale-up in people: 5→10 (pilot) · 10→30 (ramp) · 30→50 FTE (full throughput)",
        "UiPath/RPA and Databricks-specialised profiles mobilised with 60 days' notice",
    ]),
    (GREEN, "Present where it counts", [
        "Phase 1 pilot: core squad on-site in Qatar — Factory Lead, SAP module SMEs (FI/MM/SD/HCM/FI-AA), QA lead",
        "Supporting roles hybrid/remote under PIH security and data-residency controls",
        "World-class quality at competitive near-shore pricing; long-term commitment to Qatar",
    ]),
]
for i, (accent, t, its) in enumerate(cards):
    tf = panel_card(s, MX + i * (CW + 0.24), 2.06, CW, 3.3, accent, t)
    bullets(tf, its, size=10.2, before=6)
rect(s, MX, 5.55, SW - 2 * MX, 0.72, TINTBLUE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
tf = box(s, MX + 0.28, 5.65, SW - 2 * MX - 0.56, 0.55)
p = para(tf, "TRAINING & CERTIFICATION.  ", size=10.5, color=NAVY, bold=True, mono=True, first=True)
add_run(p, "State-of-the-art curriculum on the platform and on agentic delivery — the vehicle for PIH capability transfer and the Factory's "
           "long-term autonomy (train-the-trainer, certification tracks, co-delivery).", size=11, color=INK)

# ============================================================ 1.4 REFERENCES OVERVIEW
def client_logo(s, name, x=None, y=0.0, h=0.30, right=None):
    path = os.path.join(LOGOS, f"{name}.png")
    if not os.path.exists(path):
        return None
    pic = s.shapes.add_picture(path, Inches(x if x is not None else 0), Inches(y), height=Inches(h))
    if right is not None:
        pic.left = Inches(right) - pic.width
    pic.shadow.inherit = False
    return pic


s = slide()
chrome(s, "References", "Four production references", accent=BLUE)
tf = box(s, MX, 1.5, SW - 2 * MX, 0.35)
p = para(tf, "Full metrics and reference interviews available under NDA. ", size=11, color=MUT, first=True)
add_run(p, "Each reference proves one pillar of the Factory.", size=11, color=INK, bold=True)
CW = (SW - 2 * MX - 0.24) / 2
refs = [
    (BLUE, "1 · Gulf smart-city AI in production", "SMART-PARKING OPERATOR · GULF REGION", None, [
        ("Scope", "real-time video analytics for a Gulf parking-guidance operator — Kafka streaming, live detection across large heterogeneous camera estates"),
        ("Outcome", "sustained real-time throughput at peak load; foundation reused as a shelf capability"),
        ("Proves", "production AI operated in the Gulf + pattern-to-shelf reuse economics"),
    ]),
    (PURPLE, "2 · Predictive IT operations (AIOps)", "MOBILIZE FINANCIAL SERVICES · RENAULT GROUP", "mobilize", [
        ("Scope", "proactive incident prevention on a heterogeneous estate (mainframe → ESB) — millions of log/metric lines, Spark, explainable alerts"),
        ("Outcome", "supervision moved from reactive to predictive; alerts adopted by IT operators"),
        ("Proves", "Operations & Technology agents — the AgentOps mindset in production"),
    ]),
    (GREEN, "3 · Governed multi-agent translation (SAE J2450)", "RENAULT GROUP", "renault", [
        ("Scope", "multi-agent XML/DITA pipeline — one QA agent per error class, golden-set gates, human review loop, normed quality"),
        ("Outcome", "quality ≥ human baselines (SAE J2450); strong measured ROI on cost and turnaround"),
        ("Proves", "factory economics — patterns, gates, per-segment evidence at every delivery"),
    ]),
    (AMBER, "4 · Enterprise knowledge & SAP-integrated agents", "ANDRITZ", "andritz", [
        ("Scope", "grounded, cited retrieval over a multi-million-chunk corpus; on the same account, in production: S/4HANA-integrated agents driving spare-parts aftermarket campaigns"),
        ("Outcome", "per-claim citations in production; corpus improves with expert feedback"),
        ("Proves", "the knowledge layer + live SAP S/4HANA integration in production"),
    ]),
]
for i, (accent, t, sub, logo_name, its) in enumerate(refs):
    x = MX + (i % 2) * (CW + 0.24)
    y = 2.0 + (i // 2) * 2.2
    tf = panel_card(s, x, y, CW, 2.05, accent, t, subtitle=sub, title_size=12)
    bullets(tf, its, size=9.3, before=3)
    if logo_name:
        client_logo(s, logo_name, y=y + 0.14, h=0.28, right=x + CW - 0.18)

# ============================================================ 1.5 SAP & GAP
s = slide()
chrome(s, "References", "SAP evidence — production proof and shortlist commitments", accent=BLUE)
CW = (SW - 2 * MX - 0.24) / 2
tf = panel_card(s, MX, 1.72, CW, 3.15, GREEN, "What is in production today")
bullets(tf, [
    ("S/4HANA integration live", "agents collect master and transactional data from SAP S/4HANA (installed base, parts consumption, order history) to generate targeted spare-parts aftermarket campaigns — in production for a global industrial engineering group"),
    ("SAP-adjacent estates", "event-driven triggers from SuccessFactors (joiner/mover/leaver), OData reads, BAPI/RFC wrapped as typed skills with bounded retries and idempotency"),
    ("Financial-posting discipline", "parallel run against human postings on identical transactions, weekly GL reconciliation during hypercare, external SoD review before go-live"),
], size=10.3, before=7)
tf = panel_card(s, MX + CW + 0.24, 1.72, CW, 3.15, AMBER, "The acknowledged gap — and the plan")
bullets(tf, [
    ("Stated in our response", "we do not yet have an SAP financial-posting agent delivery as a reference — we prefer to state it than to blur it"),
    ("At shortlist", "named Datategy SAP module experts (FI/MM/SD/HCM/FI-AA) and relevant financial-posting evidence presented"),
    ("By construction", "every posting flow in the Factory carries a mandatory parallel run — the reference discipline above is the risk treatment"),
], size=10.3, before=7)
rect(s, MX, 5.05, SW - 2 * MX, 1.25, PANEL, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
tf = box(s, MX + 0.28, 5.2, SW - 2 * MX - 0.56, 1.0)
p = para(tf, "WHY THIS DISCIPLINE MATTERS.  ", size=10.5, color=NAVY, bold=True, mono=True, first=True)
add_run(p, "Two lived lessons shape our SAP approach: a design-stage corpus audit that stopped a build before confidently-wrong answers shipped "
           "(data-quality sign-off is now a hard gate), and a cascading ESB timeout on a financing estate that taught us to sign interface contracts "
           "and map downstream dependencies before writing code.", size=10.5, color=MUT)

# ============================================================ DIVIDER 2
divider(slide(), "02", "Full products overview",
        "Architecture, stack, capabilities — one sovereign platform whose three products share one deployment, one governance and one security model.",
        "≈ 35 MINUTES")

# ============================================================ 2.1 ONE PLATFORM
s = slide()
chrome(s, "Products", "One sovereign AI platform, three capabilities", accent=PURPLE)
tf = box(s, MX, 1.5, SW - 2 * MX, 0.4)
p = para(tf, "papAI is the common sovereign foundation. ", size=11.5, color=INK, bold=True, first=True)
add_run(p, "Document Center and Agentium are not separate products: one platform, one deployment, one governance and security model.", size=11.5, color=MUT)
CW = (SW - 2 * MX - 2 * 0.24) / 3
cards = [
    (BLUE, "papAI", "DATA INTELLIGENCE", os.path.join(SCREENS, "papai-features.png"), [
        ("What", "turns data into industrialised AI assets — DataOps, AutoML, ML/deep learning, fine-tuning, MLOps"),
        ("Uses", "predictive maintenance, AIOps, forecasting, risk scoring, computer vision"),
    ]),
    (PURPLE, "Document Center", "KNOWLEDGE INTELLIGENCE", os.path.join(SCREENS, "guide-recherche-anon.png"), [
        ("What", "turns documents and expert knowledge into governed, searchable enterprise memory — OmniRAG retrieval, cited answers, grounding checks"),
        ("Uses", "technical documentation assistants, regulatory analysis, knowledge capture"),
    ]),
    (GREEN, "Agentium", "DECISION INTELLIGENCE", os.path.join(SCREENS, "ui-flow-builder.png"), [
        ("What", "turns data and knowledge into governed intelligent systems — agents that decide and act under control"),
        ("Uses", "enterprise assistants, transactional process agents, multi-agent pipelines"),
    ]),
]
for i, (accent, t, sub, img, its) in enumerate(cards):
    x = MX + i * (CW + 0.24)
    tf = panel_card(s, x, 2.0, CW, 4.05, accent, t, subtitle=sub)
    bullets(tf, its, size=9.6, before=4)
    screenshot(s, img, x + 0.22, CW - 0.44, bottom=2.0 + 4.05 - 0.14)
rect(s, MX, 6.22, SW - 2 * MX, 0.52, TINTBLUE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
tf = box(s, MX + 0.28, 6.29, SW - 2 * MX - 0.56, 0.4)
p = para(tf, "ONE GRAMMAR.  ", size=10, color=NAVY, bold=True, mono=True, first=True)
add_run(p, "Skill → Capability → System → Suite: reusable primitives assemble into business systems. Each delivery enriches the catalogue — "
           "the next one starts from assets, not from a blank page.", size=10.5, color=INK)

# ============================================================ 2.2 AGENTIUM MODEL
s = slide()
chrome(s, "Products · Agentium", "The Agentium model — governed by construction", accent=PURPLE)
tf = box(s, MX, 1.52, SW - 2 * MX, 0.4)
p = para(tf, "One canonical chain for every intelligent system: ", size=11.5, color=INK, bold=True, first=True)
add_run(p, "Objective → System → Run → Evaluation → Decision → Action. What runs is measured; what is measured is governed.", size=11.5, color=MUT)
CW = (SW - 2 * MX - 3 * 0.22) / 4
pillars = [
    (BLUE, "Evaluated by default", [
        "Golden sets and quality scoring per system, normed where standards exist (e.g. SAE J2450)",
        "No prompt or model change reaches production without passing regression",
    ]),
    (PURPLE, "Governed & auditable", [
        "Agents hold their own identity with scoped, time-boxed mandates",
        "Full audit ledger — every run, tool call, cost and human decision traced and replayable",
    ]),
    (GREEN, "Human in the loop", [
        "The AI proposes, the expert decides — confidence thresholds, escalation, calibrated alerts",
        "Corrections feed back into knowledge bases, golden sets and models",
    ]),
    (AMBER, "Sovereign by design", [
        "SaaS, private cloud, on-premise or air-gap — data and models in the client perimeter",
        "Open-weight model serving (vLLM), edge AI, federated learning in production",
    ]),
]
for i, (accent, t, its) in enumerate(pillars):
    tf = panel_card(s, MX + i * (CW + 0.22), 2.04, CW, 2.5, accent, t, title_size=12)
    bullets(tf, its, size=9.4, before=5)
rect(s, MX, 4.75, SW - 2 * MX, 1.55, PANEL, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
tf = box(s, MX + 0.28, 4.9, SW - 2 * MX - 0.56, 1.3)
p = para(tf, "THE FACTORY GRAMMAR, OPERATIONALLY.  ", size=10.5, color=NAVY, bold=True, mono=True, first=True)
add_run(p, "A pattern is a validated agent blueprint; a skill is a typed, testable capability; a connector binds skills to enterprise systems. "
           "First-of-type builds create assets; reuse instances are configured from them — this is what makes per-agent pricing and the 30/15 "
           "reuse targets measurable by construction, not by promise.", size=10.8, color=INK)
p = para(tf, "Design card — ", size=10.5, color=INK, bold=True, before=6)
add_run(p, "every agent starts from an approved card: tier, systems touched, first-of-type/reuse status, security class, success metrics, "
           "acceptance evidence, delivery slot and price — approved before build.", size=10.5, color=MUT)

# ============================================================ 2.3 ARCHITECTURE
s = slide()
chrome(s, "Products · Agentium", "Orchestration architecture — build, run, replay", accent=PURPLE)
LW = 6.6
tf = panel_card(s, MX, 1.66, LW, 4.6, PURPLE, "From flow to certified execution", title_size=13)
bullets(tf, [
    ("Flow Builder", "visual DAG over typed skills — triggers, LLM steps, oracles, actions, approval gates; validity checked at design time"),
    ("Run engine", "stateful execution with checkpointing — every run resumable, inspectable and replayable with all its parameters"),
    ("Answer pipeline", "retrieval routing, grounding and citation checks, deterministic guardrails before any privileged action"),
    ("Agent identity & mandates", "each agent runs under its own identity with scoped, time-boxed, revocable permissions — enforced at the platform level, not coded per agent"),
    ("Audit ledger", "every tool invocation timestamped with cost attribution; evidence exportable for auditors"),
    ("Model router", "right-sized model per step — small models for routing/classification, larger only where accuracy demands; caching and token budgets enforced"),
], size=10.4, before=7)
RX = MX + LW + 0.28
RW = SW - MX - RX
screenshot(s, os.path.join(SCREENS, "ui-flow-builder.png"), RX, RW, y=1.9,
           caption="Flow Builder — a governed multi-agent pipeline (validated DAG)")
rect(s, RX, 5.55, RW, 0.75, TINTBLUE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
tf = box(s, RX + 0.2, 5.65, RW - 0.4, 0.6)
p = para(tf, "SEEN LIVE IN THE DEMO.  ", size=9, color=NAVY, bold=True, mono=True, first=True)
add_run(p, "We will build a flow, run it, and replay a past execution identically — with its evidence trail.", size=9.8, color=INK)

# ============================================================ 2.4 STACK
s = slide()
chrome(s, "Products · Stack", "Sovereign deployment — the stack behind the platform", accent=PURPLE)
CW = (SW - 2 * MX - 2 * 0.24) / 3
cards = [
    (NAVY, "Runtime & serving", [
        "Kubernetes-orchestrated — we deploy and manage; 7-server reference topology (4 GPU + 3 data nodes)",
        "Open-weight model serving on vLLM within the client perimeter; no external dependency at inference time",
        "PostgreSQL HA · Qdrant ×2 · MinIO object storage · K8s control plane on data nodes",
    ]),
    (BLUE, "Data & lakehouse alignment", [
        "Native fit with the Databricks medallion on Azure (ADLS, Delta Lake, Unity Catalog, MLflow)",
        "Agents consume governed Gold data products through Unity Catalog, inheriting dataset-level access — never bypassing the medallion",
        "SAP Datasphere as a primary source for analytical and autonomous agents",
    ]),
    (GREEN, "Inference — three sovereign models", [
        "Cloud-hosted sovereign: PIH-controlled Azure Qatar GPU capacity — $0 Datategy fee, mobilisable in weeks",
        "Partner-provided: Datategy-operated dedicated capacity as an optional managed service",
        "PIH-provisioned on-premise: PIH GPUs, Datategy deploys and operates the serving stack",
    ]),
]
for i, (accent, t, its) in enumerate(cards):
    tf = panel_card(s, MX + i * (CW + 0.24), 1.7, CW, 3.5, accent, t, title_size=12.5)
    bullets(tf, its, size=10, before=7)
rect(s, MX, 5.4, SW - 2 * MX, 0.95, TINTBLUE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
tf = box(s, MX + 0.28, 5.52, SW - 2 * MX - 0.56, 0.75)
p = para(tf, "NO METERS, BY DESIGN.  ", size=10.5, color=NAVY, bold=True, mono=True, first=True)
add_run(p, "Agentium runtime is included in delivered-agent prices during the Factory programme — $0 runtime fee, no execution meters. "
           "Where PIH approves Azure/SaaS endpoints, consumption is billed directly between PIH and its cloud provider. "
           "Cost per execution is measured, capped and optimised (target −30–50% over 12 months, jointly baselined).", size=10.8, color=INK)

# ============================================================ 2.5 DATA & ML
s = slide()
chrome(s, "Products · papAI", "Data & ML — verticalised models feed the agents", accent=PURPLE)
LW = 7.3
tf = panel_card(s, MX, 1.66, LW, 4.6, BLUE, "The ML factory under the agent factory", title_size=13)
bullets(tf, [
    ("End-to-end workbench", "DataOps, feature engineering, AutoML across the algorithm spectrum, hyperparameter search, calibration — no-code and pro-code in one place"),
    ("MLOps lifecycle", "experiment tracking, model registry, drift detection, automated retraining — models stay honest in production"),
    ("Verticalised models as skills", "forecasting, scoring, anomaly detection and vision models are wrapped as typed skills — agents call governed models, not ad-hoc scripts"),
    ("Proven at scale", "AIOps on multi-million-line telemetry (Spark), computer-vision fleets in production, generative time-series research shipped into product"),
    ("Why it matters for the Factory", "Analytical and Autonomous agent tiers require exactly this — a governed path from PIH data to models the agents can trust"),
], size=10.6, before=8)
RX = MX + LW + 0.28
RW = SW - MX - RX
screenshot(s, os.path.join(SCREENS, "papai-features.png"), RX, RW, y=1.75,
           caption="papAI — experiment configuration, data quality")
screenshot(s, os.path.join(SCREENS, "papai-models.png"), RX, RW, y=4.35,
           caption="papAI — model selection & training")

# ============================================================ 2.6 INTEGRATION
s = slide()
chrome(s, "Products · Integration", "Enterprise integration — SAP, connectors, MCP", accent=PURPLE)
CW = (SW - 2 * MX - 0.24) / 2
tf = panel_card(s, MX, 1.66, CW, 2.3, NAVY, "Connector framework")
bullets(tf, [
    ("Typed connectors", "bounded retries, idempotency, circuit breakers — enterprise systems touched through contracts, not scripts"),
    ("SAP interoperability", "OData reads, BAPI/RFC wrapped as typed skills, IDoc/CDC where streaming is required, SuccessFactors event triggers"),
    ("MCP-compliant", "skills and agents exposed through open interfaces — portable, lock-in-free, ready for PIH's Abstraction Layer"),
], size=10, before=6)
tf = panel_card(s, MX + CW + 0.24, 1.66, CW, 2.3, GREEN, "Extending Hikmah — not competing with it")
bullets(tf, [
    ("Capability discovery first", "at engagement start, we map existing Hikmah components and integrate through the Abstraction Layer"),
    ("Reference implementation (C8)", "Agentium proposed as the transitional reference implementation — operational at mobilisation, under PIH governance, branding and IP terms"),
    ("Clean handover", "API specifications handed over so PIH components take over without rework as they reach production readiness"),
], size=10, before=6)
rect(s, MX, 4.2, SW - 2 * MX, 2.1, PANEL, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
tf = box(s, MX + 0.28, 4.35, SW - 2 * MX - 3.6, 1.8)
p = para(tf, "WHY THIS DE-RISKS OCTOBER.  ", size=10.5, color=NAVY, bold=True, mono=True, first=True)
add_run(p, "PIH's Abstraction Layer and AI Control Tower are still in build. With Agentium as the transitional reference implementation, "
           "the pilot does not depend on components that do not exist yet: the Factory is operational at mobilisation, exposed through "
           "MCP-compliant interfaces, and portability is preserved by design.", size=10.8, color=INK)
p = para(tf, "This is the one de-risking of the October go-live no other respondent can offer without an equivalent product.", size=10.8, color=INK, bold=True, before=6)
screenshot(s, os.path.join(SCREENS, "ui-connectors.png"), SW - MX - 3.1, 2.86, y=4.42,
           caption="Connector catalogue — typed, governed bindings")

# ============================================================ 2.7 R&D DISRUPTIVE
s = slide()
chrome(s, "Products · Beyond the market", "Four R&D axes no cloud player can copy", accent=PURPLE)
tf = box(s, MX, 1.5, SW - 2 * MX, 0.4)
p = para(tf, "Competing platforms rent their models — they control neither the engine nor the gearbox. ", size=11.5, color=MUT, first=True)
add_run(p, "Agentium owns the whole chain: models, ledger, governance. That is where these four axes are built.", size=11.5, color=INK, bold=True)
CW = (SW - 2 * MX - 3 * 0.22) / 4
axes = [
    (NAVY, "The black box", "CERTIFIED EXECUTION", "Every agent decision replayable identically months later — with a signed evidence file to hand to an auditor. Impossible when you rent models that change without notice."),
    (BLUE, "The power of attorney", "AGENT MANDATES", "An agent can never exceed the mandate it was given: actions, caps, duration. Signed, verifiable, revocable in one click — within your walls."),
    (GREEN, "The dress rehearsal", "GOVERNED SELF-IMPROVEMENT", "The platform proposes its own adjustments, proves them on hundreds of past cases first, and a human validates. ~70% already built."),
    (AMBER, "The priority lane", "CAPACITY MANAGEMENT", "On finite sovereign compute, critical usage always gets through; each department pays for what it consumes. Cloud giants do this internally — never for their customers."),
]
for i, (accent, t, sub, d) in enumerate(axes):
    x = MX + i * (CW + 0.22)
    tf = panel_card(s, x, 2.02, CW, 3.1, accent, t, subtitle=sub, title_size=12.5)
    para(tf, d, size=9.8, color=MUT, first=True, spacing=1.1)
rect(s, MX, 5.35, SW - 2 * MX, 0.95, DEEPNAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
tf = box(s, MX + 0.28, 5.5, SW - 2 * MX - 0.56, 0.7, anchor=MSO_ANCHOR.MIDDLE)
p = para(tf, "Sovereignty stops being a constraint — it becomes the advantage. ", size=12.5, color=WHITE, bold=True, first=True)
add_run(p, "Everyone can run agents. No one else controls the whole machine. These axes are proposed as exclusive R&D scope for PIH.", size=12.5, color=LIGHTBLUE)

# ============================================================ 2.8 FACTORY FIT
s = slide()
chrome(s, "Products · Factory fit", "Built for the AI Factory — how we deliver 400 agents", accent=PURPLE)
CW = (SW - 2 * MX - 0.24) / 2
tf = panel_card(s, MX, 1.66, CW, 2.6, GREEN, "The factory operating model")
bullets(tf, [
    ("Design card gate", "tier, systems, reuse status, security class, metrics, price — approved before build"),
    ("Pattern library", "first-of-type builds seed patterns, skills, connectors; reuse instances configured from validated assets"),
    ("Evaluation-gated go-live", "six acceptance criteria, golden-set regression, parallel run on privileged flows"),
    ("Hypercare → AgentOps", "named hypercare lead per wave, then steady-state operations with drift watch"),
], size=10, before=5)
tf = panel_card(s, MX + CW + 0.24, 1.66, CW, 2.6, BLUE, "Human scale-up — people, not stack")
bullets(tf, [
    ("Phase 1 — validation", "5→10 FTE; one concentrated squad, SAP SMEs on-site in Qatar; pattern creation and gate calibration"),
    ("Phase 2 — volume", "10→30→50 FTE in build cells of 5; indicatively ≈70–200 then 200–360 agents/quarter as authoring shifts to instantiation"),
    ("Phase 3 — cognitive", "research-grade evaluation, RCA and multi-step-reasoning profiles join while cells maintain volume"),
    ("Effort per agent", "set at design-card stage by tier — capacity ranges are planning heuristics, not contractual units"),
], size=10, before=5)
kpi_row(s, 4.48, [
    ("13 wks", "UCC validation pilot — mobilisation to go-live stabilisation"),
    ("40/40/20", "PIH tier mix (Simple/Medium/Complex) across the 400-agent envelope"),
    ("30/15", "Reuse design targets — measurable by construction via the pattern library"),
    ("Oct 2026", "Go-live protected by the transitional reference implementation"),
], h=1.15)
rect(s, MX, 5.85, SW - 2 * MX, 0.52, TINTBLUE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
tf = box(s, MX + 0.28, 5.92, SW - 2 * MX - 0.56, 0.4)
p = para(tf, "COMMERCIAL PRINCIPLE.  ", size=10, color=NAVY, bold=True, mono=True, first=True)
add_run(p, "PIH buys delivered agents at catalogue unit prices — all-inclusive, runtime included, no per-user licences, no execution meters. "
           "Full schedule in Annex B (v7) as submitted.", size=10.5, color=INK)

# ============================================================ DIVIDER 3
divider(slide(), "03", "Platform walkthrough — live demo",
        "An agent lifecycle end-to-end on Agentium: portfolio value, building from patterns, governed execution, evaluation gates, audit evidence.",
        "≈ 25 MINUTES · LIVE ON THE PLATFORM")

# ============================================================ 3.1 DEMO STORYLINE
s = slide()
chrome(s, "Live demo", "Walkthrough storyline — what you will see", accent=GREEN)
steps = [
    ("1 · Steer", "Hypervisor — the portfolio balance sheet", "Net value, cost, ROI and confidence per capability — how a CIO steers an agent estate", os.path.join(SHOTS, "09_evaluation.png")),
    ("2 · Build", "Flow Builder — an agent from patterns", "Assemble a governed pipeline from typed skills; validity checked at design time", os.path.join(SCREENS, "ui-flow-builder.png")),
    ("3 · Run", "Stateful execution & replay", "A live run, its full trace, and identical replay — the black box in action", os.path.join(SHOTS, "08_run_detail.png")),
    ("4 · Evaluate", "Golden sets & quality gates", "Regression before production; quality scored continuously against reference cases", os.path.join(SHOTS, "01_hypervisor.png")),
    ("5 · Govern", "Mandates, access & audit ledger", "Agent identity, scoped permissions, tamper-evident audit — evidence on demand", os.path.join(SHOTS, "03_governance_audit.png")),
    ("6 · Ask", "Document intelligence & Quick Ask", "Grounded, cited answers over workspace documents — retrieval routed automatically", os.path.join(SHOTS, "06_chat.png")),
]
CW = (SW - 2 * MX - 2 * 0.22) / 3
for i, (num, t, d, img) in enumerate(steps):
    x = MX + (i % 3) * (CW + 0.22)
    y = 1.62 + (i // 3) * 2.42
    rect(s, x, y, CW, 2.28, WHITE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
    tf = box(s, x + 0.2, y + 0.1, CW - 0.4, 0.55)
    p = para(tf, num + "  ", size=10.5, color=GREEN, bold=True, mono=True, first=True)
    add_run(p, t, size=11.5, color=INK, bold=True)
    tf = box(s, x + 0.2, y + 0.42, CW - 0.4, 0.55)
    para(tf, d, size=9, color=MUT, first=True, spacing=1.0)
    screenshot(s, img, x + 0.2, CW - 0.4, bottom=y + 2.28 - 0.12)

# ============================================================ 3.2 PROOF POINTS
s = slide()
chrome(s, "Live demo", "What to watch for — five proof points", accent=GREEN)
proofs = [
    ("Nothing is a slideware promise", "everything shown runs on the platform you will receive access to today — same build, same governance"),
    ("Replay is real", "we will replay a past run identically and show its evidence trail — the capability behind certified execution"),
    ("Governance is structural", "mandates and permissions are enforced by the platform, not coded per agent — watch an out-of-scope action get blocked"),
    ("Evaluation gates production", "a change that fails golden-set regression cannot ship — quality is a gate, not a dashboard"),
    ("Cost is visible per action", "every tool call carries its cost — the transparency that makes capped, meter-free economics credible"),
]
y = 1.72
for i, (t, d) in enumerate(proofs):
    rect(s, MX, y, SW - 2 * MX, 0.86, WHITE if i % 2 == 0 else PANEL, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.07)
    tf = box(s, MX + 0.3, y + 0.13, 0.6, 0.6)
    para(tf, f"{i+1:02d}", size=18, color=GREEN, bold=True, mono=True, first=True)
    tf = box(s, MX + 1.05, y + 0.12, SW - 2 * MX - 1.4, 0.65, anchor=MSO_ANCHOR.MIDDLE)
    p = para(tf, t + " — ", size=12, color=INK, bold=True, first=True)
    add_run(p, d, size=12, color=MUT)
    y += 0.97

# ============================================================ DIVIDER 4
divider(slide(), "04", "SaaS demo access — PIH account",
        "Your own environment on the platform, from today: scope, credentials, support, and what to test first.",
        "≈ 15 MINUTES + Q&A")

# ============================================================ 4.1 SAAS ACCESS
s = slide()
chrome(s, "SaaS access", "Your PIH demo account — hands-on from today", accent=AMBER)
CW = (SW - 2 * MX - 2 * 0.24) / 3
cards = [
    (AMBER, "What you receive", [
        "Dedicated PIH workspace on the Agentium SaaS demo environment",
        "Named accounts for your evaluation team (roles: admin, builder, business user)",
        "Pre-loaded showcase: sample capabilities, golden sets, run history and audit trails to explore",
        "Demo corpus for document intelligence — or load your own public documents",
    ]),
    (BLUE, "What to test first", [
        "Replay a run and export its evidence file (the black box)",
        "Trip a mandate: ask an agent to exceed its scope and watch the block",
        "Break a golden set: change a prompt and see regression stop the deploy",
        "Build a small flow from existing skills in the Flow Builder",
        "Track cost per run in the Hypervisor",
    ]),
    (GREEN, "How we support you", [
        "Onboarding session for your evaluators (60–90 min, this week)",
        "Named Datategy contact; response within one business day",
        "Weekly office hours during the evaluation window",
        "Demo environment — no PIH internal, confidential or PIH-IP data; sovereign deployment models are covered in the RFI response",
    ]),
]
for i, (accent, t, its) in enumerate(cards):
    tf = panel_card(s, MX + i * (CW + 0.24), 1.7, CW, 4.0, accent, t, title_size=13)
    bullets(tf, its, size=10, before=7)
rect(s, MX, 5.9, SW - 2 * MX, 0.52, TINTBLUE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
tf = box(s, MX + 0.28, 5.97, SW - 2 * MX - 0.56, 0.4)
p = para(tf, "SAME PLATFORM, SMALLER PERIMETER.  ", size=10, color=NAVY, bold=True, mono=True, first=True)
add_run(p, "The demo environment runs the same build as the sovereign deployment described in our response — what you evaluate is what gets deployed.",
        size=10.5, color=INK)

# ============================================================ 4.2 NEXT STEPS
s = slide()
chrome(s, "Next steps", "From this room to a running Factory", accent=AMBER)
steps = [
    ("Today", "Demo access live", "PIH workspace and named accounts activated; onboarding session scheduled"),
    ("This week", "Evaluation support", "Office hours open; your evaluators test replay, mandates, gates and builder hands-on"),
    ("Shortlist", "Full disclosure", "Named SAP module experts and CVs, reference interviews under NDA, financial-posting evidence, measurement methodologies"),
    ("Contract", "Mobilisation", "Core squad on-site in Qatar — Factory Lead, SAP SMEs, QA lead; factory onboarding weeks 1–2"),
    ("13 weeks", "UCC validation pilot", "Design, build, parallel run, go-live stabilisation — pattern library seeded, gates calibrated"),
    ("October", "Go-live, protected", "Transitional reference implementation removes dependency on components still in build"),
]
CW = (SW - 2 * MX - 2 * 0.22) / 3
for i, (when, t, d) in enumerate(steps):
    x = MX + (i % 3) * (CW + 0.22)
    y = 1.72 + (i // 3) * 2.12
    rect(s, x, y, CW, 1.98, WHITE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
    rect(s, x, y + 0.1, 0.05, 1.78, AMBER)
    tf = box(s, x + 0.24, y + 0.15, CW - 0.44, 1.7)
    para(tf, when.upper(), size=9.5, color=AMBER, bold=True, mono=True, first=True)
    para(tf, t, size=13, color=INK, bold=True, before=3)
    para(tf, d, size=9.8, color=MUT, before=4, spacing=1.05)
rect(s, MX, 6.0, SW - 2 * MX, 0.62, DEEPNAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
tf = box(s, MX + 0.28, 6.1, SW - 2 * MX - 0.56, 0.44, anchor=MSO_ANCHOR.MIDDLE)
p = para(tf, "One ask: ", size=12, color=WHITE, bold=True, first=True)
add_run(p, "put your hardest governance question to the live platform today — that is what it is for.", size=12, color=LIGHTBLUE)

# ============================================================ CLOSING
s = slide()
PAGE[0] += 1
rect(s, 0, 0, SW, SH, DEEPNAVY)
rect(s, 0, 0, SW, 0.06, BLUE)
rect(s, 0, SH - 0.06, SW, 0.06, BLUE)
if os.path.exists(LOGO):
    s.shapes.add_picture(LOGO, Inches(MX), Inches(0.7), height=Inches(0.5))
tf = box(s, MX, 2.7, SW - 2 * MX, 1.2)
para(tf, "Shukran — thank you", size=40, color=WHITE, bold=True, first=True)
tf = box(s, MX, 3.85, SW - 2 * MX - 2.0, 1.0)
p = para(tf, "You do not buy isolated agents or licences per user — ", size=15, color=LIGHTBLUE, first=True, spacing=1.2)
add_run(p, "you deploy complete, governed systems ready to produce measurable value, on infrastructure you control.", size=15, color=WHITE, bold=True)
rect(s, MX + 0.02, 5.15, 0.55, 0.05, BLUE)
tf = box(s, MX, 5.4, SW - 2 * MX, 1.0)
para(tf, "Datategy — 50 Avenue du Général de Gaulle, 92800 Puteaux, France", size=11.5, color=LIGHTBLUE, first=True)
para(tf, "www.datategy.net · Paris · Brussels · Algiers · UAE · KSA", size=11.5, color=LIGHTBLUE, before=3)

prs.save(OUT)
print("saved:", OUT, "| slides:", len(prs.slides.__iter__.__self__._sldIdLst))
