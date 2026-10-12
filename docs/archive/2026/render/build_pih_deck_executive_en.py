# -*- coding: utf-8 -*-
"""PIH deck — executive version, plain language, ENGLISH (client-facing).

English counterpart of build_pih_deck_executive.py — same layout. Presents the four
proposed axes (A/B/C/D). Does NOT overwrite the French deck.
Output: out/PIH-scope-exclusif-RD-agentium-executive-EN.pptx
"""
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

# ---------------------------------------------------------------- tokens
SW, SH = 13.333, 7.5
MX = 0.62
INK    = RGBColor(0x15, 0x1A, 0x23)
MUT    = RGBColor(0x59, 0x63, 0x71)
LINE   = RGBColor(0xD7, 0xDC, 0xE3)
PANEL  = RGBColor(0xF3, 0xF5, 0xF8)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
NAVY   = RGBColor(0x0B, 0x25, 0x45)
BLUE   = RGBColor(0x2D, 0x6C, 0xDF)   # A
PURPLE = RGBColor(0x6D, 0x28, 0xD9)   # B
GREEN  = RGBColor(0x0E, 0x8F, 0x62)   # C
AMBER  = RGBColor(0xB4, 0x53, 0x09)   # D
F      = "Arial"
FM     = "Courier New"
import os
LOGO   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo_datategy.png")
LOGO_AR = 1024 / 692

prs = Presentation()
prs.slide_width  = Inches(SW)
prs.slide_height = Inches(SH)
BLANK = prs.slide_layouts[6]
PAGE = [0]

FOOTER = "Datategy — Agentium R&D — Confidential — June 2026"


# ---------------------------------------------------------------- helpers
def slide():
    return prs.slides.add_slide(BLANK)

def box(s, x, y, w, h):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    return tf

def para(tf, text, size=12, color=INK, bold=False, mono=False, first=False,
         before=4, after=0, align=PP_ALIGN.LEFT, spacing=1.0):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.space_before = Pt(0 if first else before)
    p.space_after = Pt(after)
    try:
        p.line_spacing = spacing
    except Exception:
        pass
    r = p.add_run()
    r.text = text
    r.font.name = FM if mono else F
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color
    return p

def add_run(p, text, size=12, color=INK, bold=False, mono=False, link=None):
    r = p.add_run()
    r.text = text
    r.font.name = FM if mono else F
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color
    if link:
        r.hyperlink.address = link
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

def chrome(s, kicker, title, accent=NAVY):
    PAGE[0] += 1
    rect(s, MX, 0.52, 0.30, 0.045, accent)
    tf = box(s, MX + 0.42, 0.40, SW - 2 * MX - 0.42, 0.3)
    para(tf, kicker.upper(), size=10.5, color=accent, bold=True, mono=True, first=True)
    tf = box(s, MX, 0.72, SW - 2 * MX, 0.62)
    para(tf, title, size=25, color=INK, bold=True, first=True)
    rect(s, MX, 1.38, SW - 2 * MX, 0.012, LINE)
    tf = box(s, MX, SH - 0.42, 8.0, 0.3)
    para(tf, FOOTER, size=8.5, color=MUT, first=True)
    tf = box(s, SW - MX - 1.0, SH - 0.42, 1.0, 0.3)
    para(tf, f"{PAGE[0]:02d}", size=9, color=MUT, mono=True, first=True, align=PP_ALIGN.RIGHT)
    lw = 0.72
    s.shapes.add_picture(LOGO, Inches(SW - MX - lw), Inches(0.34), width=Inches(lw), height=Inches(lw / LOGO_AR))

def gauge(s, x, y, n, color, label=None, label_w=1.55):
    if label:
        tf = box(s, x, y - 0.025, label_w, 0.24)
        para(tf, label, size=9.5, color=MUT, bold=True, mono=True, first=True)
        x += label_w
    d, gap = 0.15, 0.065
    for i in range(5):
        c = color if i < n else PANEL
        o = color if i < n else LINE
        rect(s, x + i * (d + gap), y, d, d, c, line_color=o, shape=MSO_SHAPE.OVAL)

def bullets(tf, items, size=12, color=INK, first=True, before=6, spacing=1.05):
    for i, it in enumerate(items):
        if isinstance(it, tuple):
            head, body = it
            p = para(tf, "▪ ", size=size, color=color, first=(first and i == 0), before=before, spacing=spacing)
            add_run(p, head + " — ", size=size, color=INK, bold=True)
            add_run(p, body, size=size, color=color)
        else:
            para(tf, "▪ " + it, size=size, color=color, first=(first and i == 0), before=before, spacing=spacing)

def panel_card(s, x, y, w, h, accent, title, title_size=13):
    rect(s, x, y, w, h, WHITE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.045)
    rect(s, x, y + 0.12, 0.05, h - 0.24, accent)
    tf = box(s, x + 0.22, y + 0.14, w - 0.4, 0.35)
    para(tf, title, size=title_size, color=accent, bold=True, first=True)
    return box(s, x + 0.22, y + 0.52, w - 0.4, h - 0.68)

def style_cell(cell, text, size=10.5, color=INK, bold=False, fill=None, mono=False,
               align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE):
    cell.fill.solid()
    cell.fill.fore_color.rgb = fill if fill is not None else WHITE
    cell.vertical_anchor = anchor
    cell.margin_left = Inches(0.08)
    cell.margin_right = Inches(0.06)
    cell.margin_top = Inches(0.03)
    cell.margin_bottom = Inches(0.03)
    tf = cell.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = align
    r = p.add_run()
    r.text = text
    r.font.name = FM if mono else F
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color

# ================================================================ S1 — Title
s = slide()
rect(s, 0, 0, SW, SH, NAVY)
rect(s, 0, 0, SW, 0.06, BLUE)
tf = box(s, MX, 2.0, 11.5, 0.4)
para(tf, "AGENTIUM R&D  ·  SCOPE PROPOSAL  ·  CONFIDENTIAL", size=12, color=BLUE, bold=True, mono=True, first=True)
tf = box(s, MX, 2.45, 12.0, 1.8)
para(tf, "Exclusive functional scope for PIH", size=44, color=WHITE, bold=True, first=True)
para(tf, "Four axes that turn your sovereignty into an advantage no one else can offer",
     size=20, color=RGBColor(0xBE, 0xD0, 0xE8), before=10)
rect(s, MX, 4.55, 3.2, 0.018, RGBColor(0x2E, 0x4A, 0x73))
tf = box(s, MX, 4.75, 12.0, 1.2)
para(tf, "The black box  ·  The power of attorney  ·  The dress rehearsal  ·  The priority lane",
     size=13, color=RGBColor(0x8F, 0xA8, 0xC7), mono=True, first=True)
tf = box(s, MX, 6.75, 12.0, 0.4)
para(tf, "Datategy — June 2026", size=12, color=RGBColor(0x8F, 0xA8, 0xC7), first=True)
rect(s, SW - 2.35, 0.5, 1.75, 1.4, WHITE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.1)
lw = 1.45
s.shapes.add_picture(LOGO, Inches(SW - 2.35 + (1.75 - lw) / 2), Inches(0.5 + (1.4 - lw / LOGO_AR) / 2),
                     width=Inches(lw), height=Inches(lw / LOGO_AR))

# ================================================================ S2 — Need & observation
s = slide()
chrome(s, "Context", "A legitimate need — one the whole market can already meet")
colw = (SW - 2 * MX - 0.4) / 2
x2 = MX + colw + 0.4

tf = box(s, MX, 1.62, colw, 0.32)
para(tf, "WHAT PIH ASKS FOR", size=11, color=NAVY, bold=True, mono=True, first=True)
tf = box(s, MX, 2.0, colw, 4.6)
bullets(tf, [
    ("Sovereignty", "models and data on your premises, no dependency on a foreign cloud"),
    ("Robustness", "resume, replay, never lose track of an execution"),
    ("Security", "guardrails, a distinct identity for each agent, strict permissions"),
    ("Observability", "know everything the agents do — and be able to show it"),
    ("Performance", "controlled, predictable compute spend"),
], size=12.5, color=MUT, before=12)

tf = box(s, x2, 1.62, colw, 0.32)
para(tf, "WHAT THE MARKET ALREADY DOES", size=11, color=NAVY, bold=True, mono=True, first=True)
rows = [
    ("Robustness", "market standards (Temporal, LangGraph)"),
    ("Security", "guardrails and identities (Microsoft, NVIDIA)"),
    ("Observability", "specialised dashboards (LangSmith…)"),
    ("Scaling", "a given for any serious player"),
    ("Compute costs", "widespread optimisations"),
]
tbl = s.shapes.add_table(len(rows), 2, Inches(x2), Inches(2.0), Inches(colw), Inches(2.5)).table
tbl.columns[0].width = Inches(2.1)
tbl.columns[1].width = Inches(colw - 2.1)
for i, (a, b) in enumerate(rows):
    fill = PANEL if i % 2 else WHITE
    style_cell(tbl.cell(i, 0), a, bold=True, fill=fill, size=11)
    style_cell(tbl.cell(i, 1), b, color=MUT, fill=fill, size=11)

rect(s, x2, 4.85, colw, 1.5, NAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
tf = box(s, x2 + 0.28, 5.05, colw - 0.56, 1.15)
para(tf, "Bottom line", size=10.5, color=BLUE, bold=True, mono=True, first=True)
para(tf, "Meeting the requirements is not enough to win. You must offer what others cannot do.",
     size=13.5, color=WHITE, bold=True, before=6, spacing=1.1)

# ================================================================ S3 — Thesis & assets
s = slide()
chrome(s, "Thesis", "They rent their models. We own the whole machine.")
tf = box(s, MX, 1.62, SW - 2 * MX, 0.75)
p = para(tf, "Competing platforms run models they rent from the cloud: they control neither the engine nor the gearbox. ",
         size=13.5, color=MUT, first=True, spacing=1.15)
add_run(p, "Agentium controls the whole chain — the models, the action ledger, the governance. That is where the four axes are built.",
        size=13.5, color=INK, bold=True)

assets = [
    ("Execution memory", "every run is recorded with all its parameters, and can be replayed", "run lineage · parameterised replay", BLUE),
    ("Action ledger", "every tool call by an agent is traced, timestamped, with its cost", "timestamped invocation ledger", PURPLE),
    ("Access control", "who can do what: a fine-grained permission engine, already in production", "RBAC + ABAC · Keycloak / OIDC", PURPLE),
    ("Statistical test bench", "no change goes to production without proving it does better", "A/B tests on a golden set", GREEN),
    ("Controlled compute budget", "the spend of each answer is computed and capped in advance", "adaptive budget per context window", AMBER),
    ("Models within your walls", "models run on the sovereign infrastructure, not at a third party", "on-prem vLLM / Ollama serving", NAVY),
]
cw = (SW - 2 * MX - 0.6) / 3
for i, (t, b, tech, c) in enumerate(assets):
    cx = MX + (i % 3) * (cw + 0.3)
    cy = 2.75 + (i // 3) * 1.85
    tfc = panel_card(s, cx, cy, cw, 1.65, c, t, title_size=12.5)
    para(tfc, b, size=10.5, color=MUT, first=True, spacing=1.1)
    para(tfc, tech, size=8.5, color=c, mono=True, before=6)
tf = box(s, MX, 6.6, SW - 2 * MX, 0.4)
para(tf, "Six foundations already in place — each axis reuses at least two: we are not starting from scratch.",
     size=11, color=MUT, first=True)

# ================================================================ S4 — Overview
s = slide()
chrome(s, "Portfolio", "Four axes — four simple images")
pistes = [
    ("A", "The black box", "Certified execution",
     "Every agent decision can be replayed identically months later — with an evidence file to hand to an auditor.", BLUE, 4, 5),
    ("B", "The power of attorney", "Agent mandates",
     "An agent can never exceed the mandate it was given: actions, caps, duration. Everything is signed, revocable in one click.", PURPLE, 3, 4),
    ("C", "The dress rehearsal", "Governed self-improvement",
     "The platform proposes its own adjustments, proves them first on past cases, and a human validates.", GREEN, 2, 4),
    ("D", "The priority lane", "Capacity management",
     "Critical usage always gets through; the rest slows down in a known order. Each department pays for what it consumes.", AMBER, 3, 3),
]
cw = (SW - 2 * MX - 0.9) / 4
for i, (k, t, st, b, c, dif, dis) in enumerate(pistes):
    cx = MX + i * (cw + 0.3)
    cy = 1.75
    ch_ = 4.45
    rect(s, cx, cy, cw, ch_, WHITE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.04)
    rect(s, cx, cy, cw, 0.62, c, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.04)
    rect(s, cx, cy + 0.3, cw, 0.32, c)
    tf = box(s, cx + 0.2, cy + 0.13, cw - 0.4, 0.4)
    para(tf, f"AXIS {k}", size=13, color=WHITE, bold=True, mono=True, first=True)
    tf = box(s, cx + 0.2, cy + 0.76, cw - 0.4, 0.45)
    para(tf, t, size=15, color=INK, bold=True, first=True, spacing=1.0)
    tf = box(s, cx + 0.2, cy + 1.18, cw - 0.4, 0.3)
    para(tf, st.upper(), size=8.5, color=c, bold=True, mono=True, first=True)
    tf = box(s, cx + 0.2, cy + 1.52, cw - 0.4, 1.9)
    para(tf, b, size=10.5, color=MUT, first=True, spacing=1.12)
    gauge(s, cx + 0.2, cy + 3.5, dif, c, label="DIFF.", label_w=0.78)
    gauge(s, cx + 0.2, cy + 3.85, dis, c, label="DISR.", label_w=0.78)
tf = box(s, MX, 6.45, SW - 2 * MX, 0.6)
p = para(tf, "DIFF. = difficulty (1–5)   ·   DISR. = disruption / exclusivity (1–5). ",
         size=10.5, color=MUT, mono=True, first=True)
add_run(p, "Everyone can run agents. No one else controls the whole machine — that is where these four axes play out.",
        size=10.5, color=INK, bold=True)

# ---------------------------------------------------------------- generators
def piste_concept(letter, name, color, dif, dis, idee, exclu, vite, dur, ancrage):
    s = slide()
    chrome(s, f"Axis {letter} — the idea", name, accent=color)
    gauge(s, SW - MX - 2.85, 0.46, dif, color, label="DIFF.", label_w=0.75)
    gauge(s, SW - MX - 2.85, 0.78, dis, color, label="DISR.", label_w=0.75)
    colw = (SW - 2 * MX - 0.4) / 2
    x2 = MX + colw + 0.4
    tfc = panel_card(s, MX, 1.62, colw, 2.35, color, "The idea, simply")
    bullets(tfc, idee, size=11.5, color=MUT, before=6)
    tfc = panel_card(s, MX, 4.15, colw, 2.35, color, "Why no one else can do it")
    bullets(tfc, exclu, size=11.5, color=MUT, before=6)
    tfc = panel_card(s, x2, 1.62, colw, 2.35, NAVY, "Why we can move fast")
    bullets(tfc, vite, size=11.5, color=MUT, before=6)
    tfc = panel_card(s, x2, 4.15, colw, 2.35, AMBER, "What is hard — and why it protects us")
    bullets(tfc, dur, size=11.5, color=MUT, before=6)
    tf = box(s, MX, 6.68, SW - 2 * MX, 0.32)
    p = para(tf, "TECHNICAL ANCHOR  ", size=9, color=color, bold=True, mono=True, first=True)
    add_run(p, ancrage, size=9, color=MUT, mono=True)
    return s

def piste_exemple(letter, name, color, situation, sans, avec, va, kpi):
    s = slide()
    chrome(s, f"Axis {letter} — the example", name, accent=color)
    rect(s, MX, 1.62, SW - 2 * MX, 0.85, NAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
    tf = box(s, MX + 0.28, 1.74, SW - 2 * MX - 0.56, 0.65)
    p = para(tf, "SITUATION   ", size=10.5, color=BLUE, bold=True, mono=True, first=True)
    add_run(p, situation, size=13, color=WHITE, bold=True)
    colw = (SW - 2 * MX - 0.4) / 2
    x2 = MX + colw + 0.4
    tfc = panel_card(s, MX, 2.72, colw, 2.05, MUT, "Today, without")
    bullets(tfc, sans, size=11, color=MUT, before=5)
    tfc = panel_card(s, x2, 2.72, colw, 2.05, color, f"Tomorrow, with axis {letter}")
    bullets(tfc, avec, size=11, color=MUT, before=5)
    rect(s, MX, 4.97, SW - 2 * MX, 1.85, PANEL, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
    rect(s, MX, 5.09, 0.05, 1.61, color)
    tf = box(s, MX + 0.25, 5.12, SW - 2 * MX - 3.6, 1.6)
    para(tf, "WHAT THE CLIENT GAINS", size=10.5, color=color, bold=True, mono=True, first=True)
    bullets(tf, va, size=11, color=INK, first=False, before=5)
    tf = box(s, SW - MX - 3.25, 5.12, 3.0, 1.6)
    para(tf, "ORDER OF MAGNITUDE*", size=10.5, color=color, bold=True, mono=True, first=True)
    for k_ in kpi:
        para(tf, k_, size=11.5, color=INK, bold=True, before=5, mono=True)
    tf = box(s, SW - MX - 3.25, 6.72, 3.1, 0.3)
    para(tf, "* illustrative projection", size=8.5, color=MUT, first=True)
    return s

# ================================================================ S5/S6 — Axis A
piste_concept(
    "A", "The black box — certified execution", BLUE, 4, 5,
    idee=[
        "Every decision an agent makes is recorded in full, like in an aircraft",
        "Months later, it can be replayed identically and an evidence file handed over: what was decided, why, and on what basis",
        "If something changed in the meantime, the system says precisely what",
    ],
    exclu=[
        "Competitors rent their models from the cloud: those models change without notice — replaying yesterday is impossible",
        "Identical replay requires controlling the model end to end: that is our case, not theirs",
        "Facing an auditor, their answer is technical logs. Ours: replayable proof",
    ],
    vite=[
        "Run recording and replay already exist in the platform",
        "Every agent action is already logged and timestamped",
        "Models already run within our walls — the essential precondition is met",
    ],
    dur=[
        "Guaranteeing strict, identical replay on accelerators is a genuine scientific challenge",
        "Our approach: a dedicated certified replay mode, plus a discrepancy report when strict identity is not attainable",
        "This difficulty is our protection: what is hard to do is hard to copy",
    ],
    ancrage="run lineage & snapshots · SHA-256 fingerprints · seeded sampling · sovereign serving (vLLM) · pinned replay corridor",
)
piste_exemple(
    "A", "The audit, nine months after the fact", BLUE,
    situation="An agent recommended a maintenance waiver nine months ago. The auditor asks: why?",
    sans=[
        "Weeks digging through technical logs, several teams mobilised",
        "The model has changed since: the decision is no longer reproducible",
        "In the end, a declarative explanation — not proof",
    ],
    avec=[
        "The decision is replayed identically in minutes",
        "If anything changed, the discrepancy report says precisely what",
        "A signed file, handed to the auditor as is",
    ],
    va=[
        "Answering an audit: from several weeks to a few hours",
        "Proof instead of an explanation — it changes the relationship with the regulator",
        "Opens uses in regulated sectors (finance, government) where autonomy was unthinkable",
    ],
    kpi=["-90% investigation time", "100% of decisions", "replayable & signed"],
)

# ================================================================ S7/S8 — Axis B
piste_concept(
    "B", "The power of attorney — agent mandates", PURPLE, 3, 4,
    idee=[
        "You don't release an agent into the wild: you give it a power of attorney, like an employee",
        "Authorised actions, caps, validity period — and a golden rule: an agent can never do more than the person who mandated it",
        "Every action is signed; the mandate is revoked in one click",
    ],
    exclu=[
        "Existing solutions manage identities, not mandates: no caps, no controlled delegation",
        "Cloud offerings are emerging (Microsoft) — but outside your walls, and without enforceable proof",
        "Our version: within your walls, signed, verifiable — integrated with the existing access control",
    ],
    vite=[
        "The rights and permissions engine is already in production",
        "Per-role authorisation scopes are already described and enforced",
        "What remains is to add the mandate layer and signing — not to rebuild",
    ],
    dur=[
        "Managing signing keys within your walls: rotation, revocation, lifecycle",
        "Keeping mandates simple to administer, so as not to build an over-engineered mess",
        "Moderate overall risk: the foundation exists, the layer grafts onto it",
    ],
    ancrage="RBAC + ABAC (Keycloak / OIDC) · signed mandates · hash-chained ledger (Certificate Transparency principle) · revocation",
)
piste_exemple(
    "B", "An agent tries to exceed its mandate", PURPLE,
    situation="A procurement agent tries to trigger a payment beyond its cap, outside its authorisation window.",
    sans=[
        "Scattered controls, hand-coded case by case in each agent",
        "Plain logs, responsibility diluted between human and machine",
        "The security director's conclusion: no autonomy on sensitive matters",
    ],
    avec=[
        "The payment is blocked at the source — by construction, not by convention",
        "A signed trace: who mandated what, to which agent, for what scope",
        "Immediate revocation of the mandate, instant effect on everything running",
    ],
    va=[
        "Autonomy becomes authorisable on sensitive scopes — the #1 adoption blocker falls",
        "Every action has an identified owner — the condition for legal accountability",
        "You deploy more agents without increasing risk",
    ],
    kpi=["0 out-of-mandate action", "possible by design", "authorise an agent:", "days → hours"],
)

# ================================================================ S9/S10 — Axis C
piste_concept(
    "C", "The dress rehearsal — self-improvement", GREEN, 2, 4,
    idee=[
        "The platform monitors itself and detects quality drops",
        "It proposes a corrective adjustment — but first rehearses it on hundreds of past cases, with the numbers to back it",
        "A human validates in one click; if there's a problem, automatic rollback",
    ],
    exclu=[
        "Market tools observe and alert — none closes the loop: propose, prove, get validated, deploy",
        "Research can optimise, but without a validation framework or a path to production",
        "We deliver continuous improvement as a platform function, under human control",
    ],
    vite=[
        "Automatic run scoring and proactive recommendations are already delivered",
        "The statistical test bench — the adjustment must prove it does better — is already delivered",
        "About 70% of the way is already built: what remains is closing the loop",
    ],
    dur=[
        "Low risk: this assembles existing building blocks, not research",
        "Watch point: ensure the past cases used for the rehearsal are representative",
    ],
    ancrage="automatic run scoring · A/B statistical gate (golden set) · what-if simulation on history · progressive rollout + rollback",
)
piste_exemple(
    "C", "Quality drops after adding documents", GREEN,
    situation="A new document corpus is added. The correct-answer rate falls from 91% to 84%.",
    sans=[
        "Manual, trial-and-error tuning, straight in production",
        "The risk of breaking what worked elsewhere without noticing",
        "No trace of who changed what, or why",
    ],
    avec=[
        "The platform proposes a corrective adjustment on its own",
        "Dress rehearsal on 500 past cases: 84% → 93%, cost per answer −18%",
        "One-click human validation, progressive rollout, automatic rollback",
    ],
    va=[
        "Quality and costs are steered with numbers, continuously",
        "No wild changes: every evolution has its file — the trial, the numbers, the validator",
        "Demonstrable from the first steering committee: the numbers speak for themselves",
    ],
    kpi=["quality 84 → 93%", "cost/answer −18%", "0 untracked", "change"],
)

# ================================================================ S11/S12 — Axis D
piste_concept(
    "D", "The priority lane — capacity management", AMBER, 3, 3,
    idee=[
        "Sovereign compute is finite: you decide in advance who has priority",
        "Critical usage always gets through; background workloads slow down in a known order, never at random",
        "Each department pays for what it actually consumes",
    ],
    exclu=[
        "Cloud giants do this internally — they never offer it to their customers",
        "Market toolkits don't manage capacity: they consume it",
        "On finite capacity — your case by definition — this is what turns a promise into a contract",
    ],
    vite=[
        "Computing and capping each answer's spend are already in production",
        "The pipeline's fine-tuning levers already exist, ready to be orchestrated",
        "Consumption is already measured action by action — internal billing follows",
    ],
    dur=[
        "Arbitrating between several teams on a shared machine takes care",
        "Calibrating service levels requires measurement campaigns",
        "Less spectacular in a demo — but very compelling for a CIO and a CFO",
    ],
    ancrage="adaptive generation budget · admission control · QoS classes · per-invocation cost metering (chargeback)",
)
piste_exemple(
    "D", "Everyone wants the machine at once", AMBER,
    situation="Month-end: the executive briefing and a large document workload compete for the same compute capacity.",
    sans=[
        "Unpredictable slowdowns for everyone — including the executives",
        "The only way out: buy more machines to absorb the peaks",
        "No way to know which department consumes what",
    ],
    avec=[
        "The briefing enters the priority lane: guaranteed response time",
        "The background workload slows down in a planned order, never at random",
        "Each department is billed on its actual consumption",
    ],
    va=[
        "Service commitments are met without buying extra machines",
        "Predictable, legible costs, department by department",
        "Capacity arbitration becomes a management decision, never again an incident",
    ],
    kpi=["machine purchases avoided", "response time", "guaranteed by priority", "billing / dept."],
)

# ================================================================ S13 — Comparative
s = slide()
chrome(s, "Synthesis", "Comparative evaluation of the four axes")
headers = ["Criterion", "A — The black box", "B — The power of attorney", "C — The dress rehearsal", "D — The priority lane"]
data = [
    ("PIH needs served", "Sovereignty · Robustness · Audit", "Security · Audit", "Performance · Robustness · Observability", "Performance · Scale"),
    ("Real exclusivity", "Very strong — impossible for a cloud player", "Strong — cloud offerings stay outside your walls", "Strong — no one closes the loop under human control", "Strong but discreet"),
    ("What we already have", "Run recording and replay", "Rights engine in production", "≈ 70% of the way already built", "Budgets and consumption metering"),
    ("Protection (patent / publication)", "Strong", "Medium-strong", "Medium", "Medium"),
]
tw = SW - 2 * MX
tbl = s.shapes.add_table(len(data) + 3, 5, Inches(MX), Inches(1.65), Inches(tw), Inches(4.6)).table
tbl.columns[0].width = Inches(2.5)
for i in range(1, 5):
    tbl.columns[i].width = Inches((tw - 2.5) / 4)
accents = [BLUE, PURPLE, GREEN, AMBER]
for j, h in enumerate(headers):
    style_cell(tbl.cell(0, j), h, size=10.5, color=WHITE, bold=True,
               fill=NAVY if j == 0 else accents[j - 1], align=PP_ALIGN.LEFT)
for i, row in enumerate(data):
    fill = PANEL if i % 2 else WHITE
    style_cell(tbl.cell(i + 1, 0), row[0], size=10, bold=True, fill=fill)
    for j in range(1, 5):
        style_cell(tbl.cell(i + 1, j), row[j], size=9.5, color=MUT, fill=fill)
style_cell(tbl.cell(len(data) + 1, 0), "Difficulty (1–5)", size=10, bold=True, fill=WHITE)
style_cell(tbl.cell(len(data) + 2, 0), "Disruption / exclusivity (1–5)", size=10, bold=True, fill=PANEL)
dif_dis = [(4, 5), (3, 4), (2, 4), (3, 3)]
for j, (dif, dis) in enumerate(dif_dis):
    style_cell(tbl.cell(len(data) + 1, j + 1), "● " * dif + "○ " * (5 - dif), size=10, color=accents[j], fill=WHITE, mono=True)
    style_cell(tbl.cell(len(data) + 2, j + 1), "● " * dis + "○ " * (5 - dis), size=10, color=accents[j], fill=PANEL, mono=True)
tf = box(s, MX, 6.55, SW - 2 * MX, 0.5)
p = para(tf, "Reading: ", size=11, color=MUT, first=True, bold=True)
add_run(p, "the dress rehearsal is the gain seen first; the black box is the deep advantage — its difficulty is precisely what prevents copying.",
        size=11, color=MUT)

# ================================================================ S14 — Regulation
s = slide()
chrome(s, "Regulatory landscape", "Qatar & the Gulf: no AI Act, a favourable trajectory")
colw = (SW - 2 * MX - 0.4) / 2
x2 = MX + colw + 0.4
tfc = panel_card(s, MX, 1.62, colw, 2.6, NAVY, "Qatar — sector rules, no global law")
bullets(tfc, [
    ("Central Bank (09/2024)", "binding rules for finance: human oversight, reporting to the regulator"),
    ("Cybersecurity Agency (2024)", "guidelines for the safe use of AI"),
    ("Financial markets (05/2025)", "draft dedicated rules in preparation"),
    ("2026–2027", "cross-sector harmonisation and regional alignment: a global law is the trajectory"),
], size=10.5, before=5)
tfc = panel_card(s, x2, 1.62, colw, 2.6, NAVY, "Region — sovereignty before compliance")
bullets(tfc, [
    ("Saudi Arabia", "2026 'year of AI', law expected; flagship project on data sovereignty ('data embassies')"),
    ("UAE", "a deliberately light-touch approach, with sector rules arriving (central bank, 02/2026)"),
    ("Bahrain", "the region's only dedicated AI bill (2024)"),
    ("Europe", "the AI Act also applies outside Europe once outputs are used there — in force since 08/2026"),
], size=10.5, before=5)
rect(s, MX, 4.42, SW - 2 * MX, 1.0, NAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.07)
tf = box(s, MX + 0.28, 4.56, SW - 2 * MX - 0.56, 0.75)
para(tf, "WHAT THIS MEANS FOR PIH", size=10, color=BLUE, bold=True, mono=True, first=True)
para(tf, "In the region, the driver is not compliance: it is provable sovereignty. Building the proof now means being ready before the rules arrive.",
     size=12.5, color=WHITE, bold=True, before=4, spacing=1.1)
tf = box(s, MX, 5.65, SW - 2 * MX, 1.3)
para(tf, "SOURCES", size=10, color=NAVY, bold=True, mono=True, first=True)
sources = [
    ("Nemko — AI Regulation in Qatar", "https://digital.nemko.com/regulations/ai-regulation-in-qatar"),
    ("Pinsent Masons — Gulf approach to AI regulation", "https://www.pinsentmasons.com/out-law/analysis/gulf-governments-approach-to-ai-regulation"),
    ("TransPerfect — Saudi Global AI Hub Law", "https://www.transperfectlegal.com/blog/saudi-arabias-global-ai-hub-law-new-model-digital-sovereignty-gcc"),
    ("Pinsent Masons — Saudi data sovereignty", "https://www.pinsentmasons.com/out-law/news/saudi-arabia-data-sovereignty-ai-hub-law"),
    ("Bird & Bird — AI Horizon Tracker (KSA)", "https://www.twobirds.com/en/capabilities/artificial-intelligence/ai-legal-services/ai-regulatory-horizon-tracker/saudi-arabia"),
    ("Modulos — Middle East AI Compliance Guide", "https://www.modulos.ai/middle-east-ai-regulations/"),
    ("European Commission — AI Act", "https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai"),
]
for i in range(0, len(sources), 2):
    p = tf.add_paragraph()
    p.space_before = Pt(3)
    for k, (label, url) in enumerate(sources[i:i + 2]):
        if k:
            add_run(p, "      ", size=9.5, color=MUT)
        add_run(p, "↗ " + label, size=9.5, color=BLUE, link=url)

# ================================================================ S15 — Recommendation
s = slide()
chrome(s, "Recommendation", "A two-step scope")
rect(s, MX, 1.62, SW - 2 * MX, 0.95, NAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.07)
tf = box(s, MX + 0.28, 1.78, SW - 2 * MX - 0.56, 0.7)
p = para(tf, "SOVEREIGNTY STOPS BEING A CONSTRAINT — IT BECOMES THE ADVANTAGE.  ", size=14, color=WHITE, bold=True, mono=True, first=True)
add_run(p, "No one else controls the whole chain; no one else can offer the proof.",
        size=13, color=RGBColor(0xBE, 0xD0, 0xE8))
colw = (SW - 2 * MX - 0.4) / 2
x2 = MX + colw + 0.4
tfc = panel_card(s, MX, 2.85, colw, 2.3, GREEN, "Step 1 — The dress rehearsal: the visible gain")
bullets(tfc, [
    "70% of the way is already built: fast result, low risk",
    "Proof of value arrives in numbers at the first steering committee",
    "Shows the platform can improve itself under human control",
], size=11.5, before=6)
tfc = panel_card(s, x2, 2.85, colw, 2.3, BLUE, "Step 2 — Black box + power of attorney: the deep advantage")
bullets(tfc, [
    "Replayable proof, carried by signed mandates",
    "Uncopyable by a cloud player without giving up its model",
    "The priority lane follows, as a natural extension of the service contract",
], size=11.5, before=6)
rect(s, MX, 5.35, SW - 2 * MX, 1.35, PANEL, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
rect(s, MX, 5.47, 0.05, 1.11, AMBER)
tf = box(s, MX + 0.25, 5.5, SW - 2 * MX - 0.5, 1.1)
para(tf, "WATCH POINTS", size=10, color=AMBER, bold=True, mono=True, first=True)
bullets(tf, [
    "Promise 'certified replay with discrepancy report': strict identical replay is the nominal mode, not a slogan",
    "Finalise internal security hardening before any client commitment — a prerequisite identified in our roadmap",
], size=11, color=INK, first=False, before=4)

# ---------------------------------------------------------------- save
out = os.path.join(os.path.dirname(__file__), "out", "PIH-scope-exclusif-RD-agentium-executive-EN.pptx")
os.makedirs(os.path.dirname(out), exist_ok=True)
prs.save(out)
print(f"saved: {out}  ·  {len(prs.slides._sldIdLst)} slides")
