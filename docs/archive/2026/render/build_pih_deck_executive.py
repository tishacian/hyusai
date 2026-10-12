# -*- coding: utf-8 -*-
"""Deck PIH — version executive, langage courant (même layout que build_pih_deck.py)."""
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
LOGO_AR = 1024 / 692  # ratio largeur/hauteur du PNG

prs = Presentation()
prs.slide_width  = Inches(SW)
prs.slide_height = Inches(SH)
BLANK = prs.slide_layouts[6]
PAGE = [0]

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
    para(tf, "Datategy — Agentium R&D — Confidentiel — Juin 2026", size=8.5, color=MUT, first=True)
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

# ================================================================ S1 — Titre
s = slide()
rect(s, 0, 0, SW, SH, NAVY)
rect(s, 0, 0, SW, 0.06, BLUE)
tf = box(s, MX, 2.0, 11.5, 0.4)
para(tf, "R&D AGENTIUM  ·  PROPOSITION DE SCOPE  ·  CONFIDENTIEL", size=12, color=BLUE, bold=True, mono=True, first=True)
tf = box(s, MX, 2.45, 12.0, 1.8)
para(tf, "Scope fonctionnel exclusif PIH", size=44, color=WHITE, bold=True, first=True)
para(tf, "Quatre pistes pour faire de votre souveraineté un avantage que personne d'autre n'offre",
     size=20, color=RGBColor(0xBE, 0xD0, 0xE8), before=10)
rect(s, MX, 4.55, 3.2, 0.018, RGBColor(0x2E, 0x4A, 0x73))
tf = box(s, MX, 4.75, 12.0, 1.2)
para(tf, "La boîte noire  ·  La procuration  ·  La répétition générale  ·  La voie prioritaire",
     size=13, color=RGBColor(0x8F, 0xA8, 0xC7), mono=True, first=True)
tf = box(s, MX, 6.75, 12.0, 0.4)
para(tf, "Datategy — Juin 2026", size=12, color=RGBColor(0x8F, 0xA8, 0xC7), first=True)
rect(s, SW - 2.35, 0.5, 1.75, 1.4, WHITE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.1)
lw = 1.45
s.shapes.add_picture(LOGO, Inches(SW - 2.35 + (1.75 - lw) / 2), Inches(0.5 + (1.4 - lw / LOGO_AR) / 2),
                     width=Inches(lw), height=Inches(lw / LOGO_AR))

# ================================================================ S2 — Besoin & constat
s = slide()
chrome(s, "Contexte", "Un besoin légitime — auquel tout le marché sait répondre")
colw = (SW - 2 * MX - 0.4) / 2
x2 = MX + colw + 0.4

tf = box(s, MX, 1.62, colw, 0.32)
para(tf, "CE QUE PIH DEMANDE", size=11, color=NAVY, bold=True, mono=True, first=True)
tf = box(s, MX, 2.0, colw, 4.6)
bullets(tf, [
    ("Souveraineté", "modèles et données chez vous, aucune dépendance à un cloud étranger"),
    ("Robustesse", "reprendre, rejouer, ne jamais perdre le fil d'une exécution"),
    ("Sécurité", "des garde-fous, une identité propre à chaque agent, des droits stricts"),
    ("Observabilité", "savoir tout ce que les agents font, et pouvoir le montrer"),
    ("Performance", "une dépense de calcul maîtrisée et prévisible"),
], size=12.5, color=MUT, before=12)

tf = box(s, x2, 1.62, colw, 0.32)
para(tf, "CE QUE LE MARCHÉ SAIT DÉJÀ FAIRE", size=11, color=NAVY, bold=True, mono=True, first=True)
rows = [
    ("Robustesse", "standards du marché (Temporal, LangGraph)"),
    ("Sécurité", "garde-fous et identités (Microsoft, NVIDIA)"),
    ("Observabilité", "tableaux de bord spécialisés (LangSmith…)"),
    ("Passage à l'échelle", "acquis pour tout acteur sérieux"),
    ("Coûts de calcul", "optimisations généralisées"),
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
para(tf, "Conclusion", size=10.5, color=BLUE, bold=True, mono=True, first=True)
para(tf, "Répondre au cahier des charges ne suffit pas à gagner. Il faut proposer ce que les autres ne peuvent pas faire.",
     size=13.5, color=WHITE, bold=True, before=6, spacing=1.1)

# ================================================================ S3 — Thèse & assets
s = slide()
chrome(s, "Thèse", "Eux louent leurs modèles. Nous possédons toute la machine.")
tf = box(s, MX, 1.62, SW - 2 * MX, 0.75)
p = para(tf, "Les plateformes concurrentes font tourner des modèles qu'elles louent au cloud : elles ne contrôlent ni le moteur, ni la boîte de vitesses. ",
         size=13.5, color=MUT, first=True, spacing=1.15)
add_run(p, "Agentium contrôle toute la chaîne — les modèles, le registre des actions, la gouvernance. C'est là que se construisent les quatre pistes.",
        size=13.5, color=INK, bold=True)

assets = [
    ("Mémoire d'exécution", "chaque exécution est enregistrée avec tous ses paramètres, et peut être rejouée", "lineage de runs · re-jeu paramétré", BLUE),
    ("Journal des actions", "chaque appel d'outil par un agent est tracé, horodaté, avec son coût", "ledger d'invocations horodaté", PURPLE),
    ("Contrôle des droits", "qui peut faire quoi : un moteur de permissions fin, déjà en production", "RBAC + ABAC · Keycloak / OIDC", PURPLE),
    ("Banc d'essai statistique", "aucun changement ne part en production sans avoir prouvé qu'il fait mieux", "tests A/B sur jeu d'or (golden set)", GREEN),
    ("Budget de calcul maîtrisé", "la dépense de chaque réponse est calculée et plafonnée à l'avance", "budget adaptatif par fenêtre de contexte", AMBER),
    ("Modèles dans vos murs", "les modèles tournent sur l'infrastructure souveraine, pas chez un tiers", "serving vLLM / Ollama on-prem", NAVY),
]
cw = (SW - 2 * MX - 0.6) / 3
for i, (t, b, tech, c) in enumerate(assets):
    cx = MX + (i % 3) * (cw + 0.3)
    cy = 2.75 + (i // 3) * 1.85
    tfc = panel_card(s, cx, cy, cw, 1.65, c, t, title_size=12.5)
    para(tfc, b, size=10.5, color=MUT, first=True, spacing=1.1)
    para(tfc, tech, size=8.5, color=c, mono=True, before=6)
tf = box(s, MX, 6.6, SW - 2 * MX, 0.4)
para(tf, "Six fondations déjà en place — chaque piste en réutilise au moins deux : on ne part pas de zéro.",
     size=11, color=MUT, first=True)

# ================================================================ S4 — Vue d'ensemble
s = slide()
chrome(s, "Portefeuille", "Quatre pistes — quatre images simples")
pistes = [
    ("A", "La boîte noire", "Exécution certifiée",
     "Chaque décision d'agent peut être rejouée à l'identique des mois plus tard — avec un dossier de preuve à remettre à un auditeur.", BLUE, 4, 5),
    ("B", "La procuration", "Mandats d'agent",
     "Un agent ne peut jamais dépasser le mandat reçu : actes, plafonds, durée. Tout est signé, révocable d'un clic.", PURPLE, 3, 4),
    ("C", "La répétition générale", "Auto-amélioration gouvernée",
     "La plateforme propose ses propres réglages, les prouve d'abord sur des cas passés, et un humain valide.", GREEN, 2, 4),
    ("D", "La voie prioritaire", "Gestion de capacité",
     "L'usage critique passe toujours ; le reste ralentit dans un ordre connu. Chaque direction paie ce qu'elle consomme.", AMBER, 3, 3),
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
    para(tf, f"PISTE {k}", size=13, color=WHITE, bold=True, mono=True, first=True)
    tf = box(s, cx + 0.2, cy + 0.76, cw - 0.4, 0.45)
    para(tf, t, size=15, color=INK, bold=True, first=True, spacing=1.0)
    tf = box(s, cx + 0.2, cy + 1.18, cw - 0.4, 0.3)
    para(tf, st.upper(), size=8.5, color=c, bold=True, mono=True, first=True)
    tf = box(s, cx + 0.2, cy + 1.52, cw - 0.4, 1.9)
    para(tf, b, size=10.5, color=MUT, first=True, spacing=1.12)
    gauge(s, cx + 0.2, cy + 3.5, dif, c, label="DIFF.", label_w=0.78)
    gauge(s, cx + 0.2, cy + 3.85, dis, c, label="DISR.", label_w=0.78)
tf = box(s, MX, 6.45, SW - 2 * MX, 0.6)
p = para(tf, "DIFF. = difficulté (1–5)   ·   DISR. = disruption / exclusivité (1–5). ",
         size=10.5, color=MUT, mono=True, first=True)
add_run(p, "Tout le monde sait faire tourner des agents. Personne d'autre ne contrôle toute la machine — c'est là que se jouent ces quatre pistes.",
        size=10.5, color=INK, bold=True)

# ---------------------------------------------------------------- générateurs
def piste_concept(letter, name, color, dif, dis, idee, exclu, vite, dur, ancrage):
    s = slide()
    chrome(s, f"Piste {letter} — l'idée", name, accent=color)
    gauge(s, SW - MX - 2.85, 0.46, dif, color, label="DIFF.", label_w=0.75)
    gauge(s, SW - MX - 2.85, 0.78, dis, color, label="DISR.", label_w=0.75)
    colw = (SW - 2 * MX - 0.4) / 2
    x2 = MX + colw + 0.4
    tfc = panel_card(s, MX, 1.62, colw, 2.35, color, "L'idée, simplement")
    bullets(tfc, idee, size=11.5, color=MUT, before=6)
    tfc = panel_card(s, MX, 4.15, colw, 2.35, color, "Pourquoi personne d'autre ne peut le faire")
    bullets(tfc, exclu, size=11.5, color=MUT, before=6)
    tfc = panel_card(s, x2, 1.62, colw, 2.35, NAVY, "Pourquoi nous pouvons aller vite")
    bullets(tfc, vite, size=11.5, color=MUT, before=6)
    tfc = panel_card(s, x2, 4.15, colw, 2.35, AMBER, "Ce qui est difficile — et pourquoi ça nous protège")
    bullets(tfc, dur, size=11.5, color=MUT, before=6)
    tf = box(s, MX, 6.68, SW - 2 * MX, 0.32)
    p = para(tf, "ANCRAGE TECHNIQUE  ", size=9, color=color, bold=True, mono=True, first=True)
    add_run(p, ancrage, size=9, color=MUT, mono=True)
    return s

def piste_exemple(letter, name, color, situation, sans, avec, va, kpi):
    s = slide()
    chrome(s, f"Piste {letter} — l'exemple", name, accent=color)
    rect(s, MX, 1.62, SW - 2 * MX, 0.85, NAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
    tf = box(s, MX + 0.28, 1.74, SW - 2 * MX - 0.56, 0.65)
    p = para(tf, "SITUATION   ", size=10.5, color=BLUE, bold=True, mono=True, first=True)
    add_run(p, situation, size=13, color=WHITE, bold=True)
    colw = (SW - 2 * MX - 0.4) / 2
    x2 = MX + colw + 0.4
    tfc = panel_card(s, MX, 2.72, colw, 2.05, MUT, "Aujourd'hui, sans")
    bullets(tfc, sans, size=11, color=MUT, before=5)
    tfc = panel_card(s, x2, 2.72, colw, 2.05, color, f"Demain, avec la piste {letter}")
    bullets(tfc, avec, size=11, color=MUT, before=5)
    rect(s, MX, 4.97, SW - 2 * MX, 1.85, PANEL, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
    rect(s, MX, 5.09, 0.05, 1.61, color)
    tf = box(s, MX + 0.25, 5.12, SW - 2 * MX - 3.6, 1.6)
    para(tf, "CE QUE LE CLIENT Y GAGNE", size=10.5, color=color, bold=True, mono=True, first=True)
    bullets(tf, va, size=11, color=INK, first=False, before=5)
    tf = box(s, SW - MX - 3.25, 5.12, 3.0, 1.6)
    para(tf, "ORDRE DE GRANDEUR*", size=10.5, color=color, bold=True, mono=True, first=True)
    for k_ in kpi:
        para(tf, k_, size=11.5, color=INK, bold=True, before=5, mono=True)
    tf = box(s, SW - MX - 3.25, 6.72, 3.1, 0.3)
    para(tf, "* projection illustrative", size=8.5, color=MUT, first=True)
    return s

# ================================================================ S5/S6 — Piste A
piste_concept(
    "A", "La boîte noire — exécution certifiée", BLUE, 4, 5,
    idee=[
        "Chaque décision d'un agent est enregistrée intégralement, comme dans un avion",
        "Des mois plus tard, on peut la rejouer à l'identique et remettre un dossier de preuve : ce qui a été décidé, pourquoi, sur la base de quoi",
        "Si quelque chose a changé entre-temps, le système dit précisément quoi",
    ],
    exclu=[
        "Les concurrents louent leurs modèles au cloud : ces modèles changent sans prévenir — impossible de rejouer hier",
        "Rejouer à l'identique exige de contrôler le modèle de bout en bout : c'est notre cas, pas le leur",
        "Face à un auditeur, leur réponse sera des journaux techniques. La nôtre : une preuve rejouable",
    ],
    vite=[
        "L'enregistrement des exécutions et le re-jeu existent déjà dans la plateforme",
        "Chaque action d'agent est déjà journalisée et horodatée",
        "Les modèles tournent déjà dans nos murs — la condition indispensable est acquise",
    ],
    dur=[
        "Garantir le « à l'identique » strict sur les calculateurs est un vrai défi scientifique",
        "Notre approche : un mode certifié dédié au re-jeu, et un rapport d'écart quand le strict n'est pas atteignable",
        "Cette difficulté est notre protection : ce qui est dur à faire est dur à copier",
    ],
    ancrage="lineage de runs & snapshots · empreintes SHA-256 · échantillonnage seedé · serving souverain (vLLM) · couloir de re-jeu épinglé",
)
piste_exemple(
    "A", "L'audit, neuf mois après les faits", BLUE,
    situation="Un agent a recommandé une dérogation de maintenance il y a neuf mois. L'auditeur demande : pourquoi ?",
    sans=[
        "Des semaines à fouiller les journaux techniques, plusieurs équipes mobilisées",
        "Le modèle a changé depuis : la décision n'est plus reproductible",
        "Au final, une explication déclarative — pas une preuve",
    ],
    avec=[
        "La décision est rejouée à l'identique en quelques minutes",
        "Si quelque chose a changé, le rapport d'écart dit précisément quoi",
        "Un dossier signé, remis tel quel à l'auditeur",
    ],
    va=[
        "Répondre à un audit : de plusieurs semaines à quelques heures",
        "Une preuve au lieu d'une explication — ça change la relation avec le régulateur",
        "Ouvre les usages dans les secteurs régulés (finance, gouvernement) où l'autonomie était inenvisageable",
    ],
    kpi=["-90% tps d'enquête", "100% décisions", "rejouables & signées"],
)

# ================================================================ S7/S8 — Piste B
piste_concept(
    "B", "La procuration — mandats d'agent", PURPLE, 3, 4,
    idee=[
        "On ne lâche pas un agent dans la nature : on lui donne une procuration, comme à un employé",
        "Actes autorisés, plafonds, durée de validité — et règle d'or : un agent ne peut jamais faire plus que la personne qui l'a mandaté",
        "Chaque action est signée ; la procuration se révoque d'un clic",
    ],
    exclu=[
        "Les solutions existantes gèrent des identités, pas des procurations : pas de plafond, pas de délégation contrôlée",
        "Les offres cloud arrivent (Microsoft) — mais hors de vos murs, et sans preuve opposable",
        "Notre version : dans vos murs, signée, vérifiable — intégrée au contrôle des droits existant",
    ],
    vite=[
        "Le moteur de droits et de permissions est déjà en production",
        "Les périmètres d'autorisation par métier sont déjà décrits et appliqués",
        "Il reste à ajouter la couche procuration et la signature — pas à reconstruire",
    ],
    dur=[
        "Gérer les clés de signature dans vos murs : rotation, révocation, cycle de vie",
        "Garder les procurations simples à administrer pour ne pas créer une usine à gaz",
        "Risque global modéré : le socle existe, la couche s'y greffe",
    ],
    ancrage="RBAC + ABAC (Keycloak / OIDC) · mandats signés · registre chaîné par hachage (principe Certificate Transparency) · révocation",
)
piste_exemple(
    "B", "Un agent tente de dépasser son mandat", PURPLE,
    situation="Un agent d'achats tente de déclencher un paiement au-delà de son plafond, en dehors de sa période d'autorisation.",
    sans=[
        "Des contrôles dispersés, codés au cas par cas dans chaque agent",
        "Des journaux simples, une responsabilité diluée entre humain et machine",
        "Conclusion du directeur sécurité : pas d'autonomie sur les sujets sensibles",
    ],
    avec=[
        "Le paiement est bloqué à la source — par construction, pas par convention",
        "Une trace signée : qui a mandaté quoi, à quel agent, pour quel périmètre",
        "Révocation immédiate de la procuration, effet instantané sur tout ce qui tourne",
    ],
    va=[
        "L'autonomie devient autorisable sur les périmètres sensibles — le frein n°1 de l'adoption saute",
        "Chaque action a un responsable identifié — la condition de l'engagement juridique",
        "On déploie plus d'agents sans accroître le risque",
    ],
    kpi=["0 action hors mandat", "possible by-design", "autoriser un agent :", "jours → heures"],
)

# ================================================================ S9/S10 — Piste C
piste_concept(
    "C", "La répétition générale — auto-amélioration", GREEN, 2, 4,
    idee=[
        "La plateforme se surveille elle-même et détecte les baisses de qualité",
        "Elle propose un réglage correctif — mais le répète d'abord sur des centaines de cas passés, chiffres à l'appui",
        "Un humain valide d'un clic ; en cas de problème, retour arrière automatique",
    ],
    exclu=[
        "Les outils du marché observent et alertent — aucun ne boucle : proposer, prouver, faire valider, déployer",
        "La recherche sait optimiser, mais sans cadre de validation ni chemin vers la production",
        "Nous livrons l'amélioration continue comme une fonction de la plateforme, sous contrôle humain",
    ],
    vite=[
        "La notation automatique des exécutions et les recommandations proactives sont déjà livrées",
        "Le banc d'essai statistique — le réglage doit prouver qu'il fait mieux — est déjà livré",
        "Environ 70% du chemin est déjà construit : il reste à fermer la boucle",
    ],
    dur=[
        "Risque faible : il s'agit d'assembler des briques existantes, pas de recherche",
        "Point d'attention : s'assurer que les cas passés utilisés pour la répétition sont représentatifs",
    ],
    ancrage="scoring automatique des runs · gate statistique A/B (golden set) · simulation what-if sur historique · rollout progressif + rollback",
)
piste_exemple(
    "C", "La qualité baisse après un ajout de documents", GREEN,
    situation="Un nouveau fonds documentaire est ajouté. Le taux de bonnes réponses chute de 91% à 84%.",
    sans=[
        "Des réglages manuels, à tâtons, directement en production",
        "Le risque de casser ce qui marchait ailleurs sans s'en apercevoir",
        "Aucune trace de qui a changé quoi, ni pourquoi",
    ],
    avec=[
        "La plateforme propose d'elle-même un réglage correctif",
        "Répétition générale sur 500 cas passés : 84% → 93%, coût par réponse −18%",
        "Validation humaine en un clic, déploiement progressif, retour arrière automatique",
    ],
    va=[
        "La qualité et les coûts se pilotent avec des chiffres, en continu",
        "Aucun changement sauvage : chaque évolution a son dossier — l'essai, les chiffres, le validateur",
        "Démontrable dès le premier comité : les chiffres parlent d'eux-mêmes",
    ],
    kpi=["qualité 84 → 93%", "coût/réponse −18%", "0 changement", "non tracé"],
)

# ================================================================ S11/S12 — Piste D
piste_concept(
    "D", "La voie prioritaire — gestion de capacité", AMBER, 3, 3,
    idee=[
        "La puissance de calcul souveraine est limitée : on décide à l'avance qui est prioritaire",
        "L'usage critique passe toujours ; les traitements de fond ralentissent dans un ordre connu, jamais au hasard",
        "Chaque direction paie ce qu'elle consomme réellement",
    ],
    exclu=[
        "Les géants du cloud font cela en interne — ils ne l'offrent jamais à leurs clients",
        "Les boîtes à outils du marché ne gèrent pas la capacité : elles la consomment",
        "Sur une capacité finie — votre cas par définition — c'est ce qui transforme une promesse en contrat",
    ],
    vite=[
        "Le calcul et le plafonnement de la dépense de chaque réponse sont déjà en production",
        "Les leviers de réglage fin du pipeline existent déjà, prêts à être orchestrés",
        "La consommation est déjà mesurée action par action — la facturation interne en découle",
    ],
    dur=[
        "Arbitrer entre plusieurs équipes sur une machine partagée demande du soin",
        "Calibrer les niveaux de service demande des campagnes de mesure",
        "Moins spectaculaire en démonstration — mais très parlant pour un DSI et un CFO",
    ],
    ancrage="budget de génération adaptatif · admission control · classes de QoS · mesure de coût par invocation (chargeback)",
)
piste_exemple(
    "D", "Tout le monde veut la machine en même temps", AMBER,
    situation="Fin de mois : le briefing de la direction et un gros traitement documentaire se disputent la même capacité de calcul.",
    sans=[
        "Des lenteurs imprévisibles pour tout le monde — y compris la direction",
        "Seule issue : acheter plus de machines pour absorber les pics",
        "Impossible de savoir quelle direction consomme quoi",
    ],
    avec=[
        "Le briefing passe en voie prioritaire : temps de réponse garanti",
        "Le traitement de fond ralentit dans un ordre prévu, jamais au hasard",
        "Chaque direction est facturée sur sa consommation réelle",
    ],
    va=[
        "Les engagements de service sont tenus sans acheter de machines supplémentaires",
        "Des coûts prévisibles et lisibles, direction par direction",
        "L'arbitrage de capacité devient une décision de gestion, plus jamais un incident",
    ],
    kpi=["achats machines évités", "temps de réponse", "garanti par priorité", "facturation / dir."],
)

# ================================================================ S13 — Comparatif
s = slide()
chrome(s, "Synthèse", "Évaluation comparative des quatre pistes")
headers = ["Critère", "A — La boîte noire", "B — La procuration", "C — La répétition générale", "D — La voie prioritaire"]
data = [
    ("Besoins PIH servis", "Souveraineté · Robustesse · Audit", "Sécurité · Audit", "Performance · Robustesse · Observabilité", "Performance · Échelle"),
    ("Exclusivité réelle", "Très forte — impossible pour un acteur cloud", "Forte — les offres cloud restent hors de vos murs", "Forte — personne ne boucle sous contrôle humain", "Forte mais discrète"),
    ("Ce qui existe déjà chez nous", "Enregistrement et re-jeu des exécutions", "Moteur de droits en production", "≈ 70% du chemin déjà construit", "Budgets et mesure de consommation"),
    ("Protection (brevet / publication)", "Forte", "Moyenne-forte", "Moyenne", "Moyenne"),
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
style_cell(tbl.cell(len(data) + 1, 0), "Difficulté (1–5)", size=10, bold=True, fill=WHITE)
style_cell(tbl.cell(len(data) + 2, 0), "Disruption / exclusivité (1–5)", size=10, bold=True, fill=PANEL)
dif_dis = [(4, 5), (3, 4), (2, 4), (3, 3)]
for j, (dif, dis) in enumerate(dif_dis):
    style_cell(tbl.cell(len(data) + 1, j + 1), "● " * dif + "○ " * (5 - dif), size=10, color=accents[j], fill=WHITE, mono=True)
    style_cell(tbl.cell(len(data) + 2, j + 1), "● " * dis + "○ " * (5 - dis), size=10, color=accents[j], fill=PANEL, mono=True)
tf = box(s, MX, 6.55, SW - 2 * MX, 0.5)
p = para(tf, "Lecture : ", size=11, color=MUT, first=True, bold=True)
add_run(p, "la répétition générale est le gain visible en premier ; la boîte noire est l'avantage de fond — sa difficulté est ce qui empêche de la copier.",
        size=11, color=MUT)

# ================================================================ S14 — Réglementation
s = slide()
chrome(s, "Cadre réglementaire", "Qatar & Golfe : pas d'AI Act, une trajectoire favorable")
colw = (SW - 2 * MX - 0.4) / 2
x2 = MX + colw + 0.4
tfc = panel_card(s, MX, 1.62, colw, 2.6, NAVY, "Qatar — des règles par secteur, pas de loi globale")
bullets(tfc, [
    ("Banque centrale (09/2024)", "règles contraignantes pour la finance : supervision humaine, signalement au régulateur"),
    ("Agence cybersécurité (2024)", "lignes directrices pour un usage sûr de l'IA"),
    ("Marchés financiers (05/2025)", "projet de règles dédiées en préparation"),
    ("2026–2027", "harmonisation entre secteurs et alignement régional : une loi globale est la trajectoire"),
], size=10.5, before=5)
tfc = panel_card(s, x2, 1.62, colw, 2.6, NAVY, "Région — la souveraineté avant la conformité")
bullets(tfc, [
    ("Arabie Saoudite", "2026 « année de l'IA », loi attendue ; projet phare sur la souveraineté des données (« data embassies »)"),
    ("Émirats", "approche souple assumée, avec des règles sectorielles qui arrivent (banque centrale, 02/2026)"),
    ("Bahreïn", "seule proposition de loi IA dédiée de la région (2024)"),
    ("Europe", "l'AI Act s'applique aussi hors d'Europe dès que les résultats y sont utilisés — en vigueur depuis 08/2026"),
], size=10.5, before=5)
rect(s, MX, 4.42, SW - 2 * MX, 1.0, NAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.07)
tf = box(s, MX + 0.28, 4.56, SW - 2 * MX - 0.56, 0.75)
para(tf, "CE QUE ÇA VEUT DIRE POUR PIH", size=10, color=BLUE, bold=True, mono=True, first=True)
para(tf, "Dans la région, le moteur n'est pas la conformité : c'est la souveraineté prouvable. Construire la preuve maintenant, c'est être prêt avant que les règles n'arrivent.",
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
    ("Commission européenne — AI Act", "https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai"),
]
for i in range(0, len(sources), 2):
    p = tf.add_paragraph()
    p.space_before = Pt(3)
    for k, (label, url) in enumerate(sources[i:i + 2]):
        if k:
            add_run(p, "      ", size=9.5, color=MUT)
        add_run(p, "↗ " + label, size=9.5, color=BLUE, link=url)

# ================================================================ S15 — Recommandation
s = slide()
chrome(s, "Recommandation", "Un scope en deux temps")
rect(s, MX, 1.62, SW - 2 * MX, 0.95, NAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.07)
tf = box(s, MX + 0.28, 1.78, SW - 2 * MX - 0.56, 0.7)
p = para(tf, "LA SOUVERAINETÉ CESSE D'ÊTRE UNE CONTRAINTE — ELLE DEVIENT L'AVANTAGE.  ", size=14, color=WHITE, bold=True, mono=True, first=True)
add_run(p, "Personne d'autre ne contrôle toute la chaîne ; personne d'autre ne peut offrir la preuve.",
        size=13, color=RGBColor(0xBE, 0xD0, 0xE8))
colw = (SW - 2 * MX - 0.4) / 2
x2 = MX + colw + 0.4
tfc = panel_card(s, MX, 2.85, colw, 2.3, GREEN, "Temps 1 — La répétition générale : le gain visible")
bullets(tfc, [
    "70% du chemin est déjà construit : résultat rapide, risque faible",
    "La preuve de valeur arrive en chiffres dès le premier comité",
    "Démontre que la plateforme sait s'améliorer sous contrôle humain",
], size=11.5, before=6)
tfc = panel_card(s, x2, 2.85, colw, 2.3, BLUE, "Temps 2 — Boîte noire + procuration : l'avantage de fond")
bullets(tfc, [
    "La preuve rejouable, portée par des mandats signés",
    "Incopiable par un acteur cloud sans renoncer à son modèle",
    "La voie prioritaire suit, en extension naturelle du contrat de service",
], size=11.5, before=6)
rect(s, MX, 5.35, SW - 2 * MX, 1.35, PANEL, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
rect(s, MX, 5.47, 0.05, 1.11, AMBER)
tf = box(s, MX + 0.25, 5.5, SW - 2 * MX - 0.5, 1.1)
para(tf, "POINTS DE VIGILANCE", size=10, color=AMBER, bold=True, mono=True, first=True)
bullets(tf, [
    "Promettre le « re-jeu certifié avec rapport d'écart » : le strict à l'identique est le mode nominal, pas un slogan",
    "Finaliser le durcissement sécurité interne avant tout engagement client — prérequis identifié dans notre feuille de route",
], size=11, color=INK, first=False, before=4)

# ---------------------------------------------------------------- save
import os
out = os.path.join(os.path.dirname(__file__), "out", "PIH-scope-exclusif-RD-agentium-executive.pptx")
os.makedirs(os.path.dirname(out), exist_ok=True)
prs.save(out)
print(f"saved: {out}")
