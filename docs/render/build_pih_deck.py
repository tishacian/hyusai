# -*- coding: utf-8 -*-
"""Deck PIH — Scope fonctionnel exclusif R&D Agentium (16:9, style ingénieur)."""
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

# ---------------------------------------------------------------- tokens
SW, SH = 13.333, 7.5
MX = 0.62                      # marge horizontale
INK    = RGBColor(0x15, 0x1A, 0x23)
MUT    = RGBColor(0x59, 0x63, 0x71)
LINE   = RGBColor(0xD7, 0xDC, 0xE3)
PANEL  = RGBColor(0xF3, 0xF5, 0xF8)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
NAVY   = RGBColor(0x0B, 0x25, 0x45)
BLUE   = RGBColor(0x2D, 0x6C, 0xDF)   # piste A
PURPLE = RGBColor(0x6D, 0x28, 0xD9)   # piste B
GREEN  = RGBColor(0x0E, 0x8F, 0x62)   # piste C
AMBER  = RGBColor(0xB4, 0x53, 0x09)   # piste D
F      = "Arial"
FM     = "Courier New"

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
    """En-tête + pied de page standard des slides de contenu."""
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

def gauge(s, x, y, n, color, label=None, label_w=1.55):
    """Indice 1-5 en pastilles."""
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
    if fill is not None:
        cell.fill.solid()
        cell.fill.fore_color.rgb = fill
    else:
        cell.fill.solid()
        cell.fill.fore_color.rgb = WHITE
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
para(tf, "Quatre pistes R&D différenciantes pour une plateforme d'agents souveraine",
     size=20, color=RGBColor(0xBE, 0xD0, 0xE8), before=10)
rect(s, MX, 4.55, 3.2, 0.018, RGBColor(0x2E, 0x4A, 0x73))
tf = box(s, MX, 4.75, 12.0, 1.2)
para(tf, "Exécution certifiée  ·  Mandats d'agent  ·  Auto-amélioration gouvernée  ·  QoS token souverain",
     size=13, color=RGBColor(0x8F, 0xA8, 0xC7), mono=True, first=True)
tf = box(s, MX, 6.75, 12.0, 0.4)
para(tf, "Datategy — Juin 2026", size=12, color=RGBColor(0x8F, 0xA8, 0xC7), first=True)

# ================================================================ S2 — Besoin & constat
s = slide()
chrome(s, "Contexte", "Le besoin PIH est légitime — et entièrement standard")
colw = (SW - 2 * MX - 0.4) / 2
x2 = MX + colw + 0.4

tf = box(s, MX, 1.62, colw, 0.32)
para(tf, "LE BESOIN EXPRIMÉ", size=11, color=NAVY, bold=True, mono=True, first=True)
tf = box(s, MX, 2.0, colw, 4.6)
bullets(tf, [
    ("Sovereignty", "modèles et données sous contrôle, pas de dépendance cloud étranger"),
    ("Robustness", "replay, resubmission, exécution stateful"),
    ("Security", "guardrails, identité d'agent distincte, RBAC strict pour agents autonomes"),
    ("Observability & Scalability", "auditabilité totale du tool-calling, scale entreprise"),
    ("Token Performance", "orchestration souveraine efficiente et déterministe"),
], size=12.5, color=MUT, before=12)

tf = box(s, x2, 1.62, colw, 0.32)
para(tf, "LA RÉPONSE STANDARD DU MARCHÉ", size=11, color=NAVY, bold=True, mono=True, first=True)
rows = [
    ("Robustesse", "Temporal, checkpoints LangGraph"),
    ("Sécurité", "NeMo Guardrails, Llama Guard, Entra Agent ID"),
    ("Observabilité", "LangSmith, Langfuse, OpenTelemetry GenAI"),
    ("Scalabilité", "n'importe quel orchestrateur K8s-native"),
    ("Token perf.", "caching, routing — généralisés"),
]
tbl = s.shapes.add_table(len(rows), 2, Inches(x2), Inches(2.0), Inches(colw), Inches(2.5)).table
tbl.columns[0].width = Inches(1.95)
tbl.columns[1].width = Inches(colw - 1.95)
for i, (a, b) in enumerate(rows):
    fill = PANEL if i % 2 else WHITE
    style_cell(tbl.cell(i, 0), a, bold=True, fill=fill, size=11)
    style_cell(tbl.cell(i, 1), b, color=MUT, fill=fill, size=11)

rect(s, x2, 4.85, colw, 1.5, NAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
tf = box(s, x2 + 0.28, 5.05, colw - 0.56, 1.15)
para(tf, "Conclusion", size=10.5, color=BLUE, bold=True, mono=True, first=True)
para(tf, "Répondre au besoin ne différencie pas. Le scope exclusif doit exploiter ce que les concurrents cloud ne peuvent pas faire.",
     size=13.5, color=WHITE, bold=True, before=6, spacing=1.1)

# ================================================================ S3 — Thèse & assets
s = slide()
chrome(s, "Thèse", "Agentium contrôle ce que le cloud ne contrôle pas")
tf = box(s, MX, 1.62, SW - 2 * MX, 0.75)
p = para(tf, "Les orchestrateurs concurrents pilotent des modèles qu'ils ne contrôlent pas : API non déterministes, poids opaques, gouvernance qui observe sans agir. ",
         size=13.5, color=MUT, first=True, spacing=1.15)
add_run(p, "Agentium contrôle le serving, le ledger et la gouvernance — le scope exclusif se construit là.",
        size=13.5, color=INK, bold=True)

assets = [
    ("Chaîne canonique", "System → Run → Evaluation → Decision → Action — livrée (Vague E)", BLUE),
    ("Replay lineage", "parent_run_id + replay_overrides + flow_snapshot par Run", BLUE),
    ("Ledger d'invocation", "SkillInvocation + audit events horodatés par tool-call", PURPLE),
    ("IAM RBAC + ABAC", "AuthorizationEngine à manifestes par capability (owner_match, second_eye…)", PURPLE),
    ("Gating statistique", "golden_flag_ab : variant ≥ baseline avant tout déploiement", GREEN),
    ("Budget déterministe + serving souverain", "budget génératif RAGGER, routing 25 providers, vLLM / Ollama on-prem", AMBER),
]
cw = (SW - 2 * MX - 0.6) / 3
for i, (t, b, c) in enumerate(assets):
    cx = MX + (i % 3) * (cw + 0.3)
    cy = 2.75 + (i // 3) * 1.85
    tfc = panel_card(s, cx, cy, cw, 1.65, c, t, title_size=12.5)
    para(tfc, b, size=10.5, color=MUT, first=True, spacing=1.1)
tf = box(s, MX, 6.6, SW - 2 * MX, 0.4)
para(tf, "Six assets en production ou architecturés — chaque piste R&D ci-après en réutilise au moins deux.",
     size=11, color=MUT, first=True)

# ================================================================ S4 — Vue d'ensemble
s = slide()
chrome(s, "Portefeuille", "Quatre pistes R&D — positionnement")
pistes = [
    ("A", "Exécution certifiée", "Replay déterministe bit-exact + dossier de preuve d'exécution signable.", BLUE, 4, 5),
    ("B", "Identité & mandats d'agent", "Délégation atténuée, tool-calls signés, non-répudiation, kill-switch.", PURPLE, 3, 4),
    ("C", "Auto-amélioration gouvernée", "Patchs de politique simulés offline, gates statistiques, approbation humaine.", GREEN, 2, 4),
    ("D", "QoS token souverain", "Contrats de tokens, classes de priorité, dégradation déterministe, chargeback.", AMBER, 3, 3),
]
cw = (SW - 2 * MX - 0.9) / 4
for i, (k, t, b, c, dif, dis) in enumerate(pistes):
    cx = MX + i * (cw + 0.3)
    cy = 1.75
    ch_ = 4.45
    rect(s, cx, cy, cw, ch_, WHITE, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.04)
    rect(s, cx, cy, cw, 0.62, c, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.04)
    rect(s, cx, cy + 0.3, cw, 0.32, c)
    tf = box(s, cx + 0.2, cy + 0.13, cw - 0.4, 0.4)
    para(tf, f"PISTE {k}", size=13, color=WHITE, bold=True, mono=True, first=True)
    tf = box(s, cx + 0.2, cy + 0.78, cw - 0.4, 0.9)
    para(tf, t, size=14, color=INK, bold=True, first=True, spacing=1.0)
    tf = box(s, cx + 0.2, cy + 1.7, cw - 0.4, 1.7)
    para(tf, b, size=10.5, color=MUT, first=True, spacing=1.12)
    gauge(s, cx + 0.2, cy + 3.5, dif, c, label="DIFF.", label_w=0.78)
    gauge(s, cx + 0.2, cy + 3.85, dis, c, label="DISR.", label_w=0.78)
tf = box(s, MX, 6.45, SW - 2 * MX, 0.6)
p = para(tf, "DIFF. = difficulté R&D (1–5)   ·   DISR. = disruption / exclusivité (1–5). ",
         size=10.5, color=MUT, mono=True, first=True)
add_run(p, "La difficulté de la piste A est aussi sa barrière à l'entrée : ce qui est dur à faire est dur à copier.",
        size=10.5, color=INK, bold=True)

# ---------------------------------------------------------------- générateur piste concept
def piste_concept(letter, name, color, dif, dis, quoi, exclu, appuis, risque):
    s = slide()
    chrome(s, f"Piste {letter} — concept", name, accent=color)
    gauge(s, SW - MX - 2.85, 0.46, dif, color, label="DIFF.", label_w=0.75)
    gauge(s, SW - MX - 2.85, 0.78, dis, color, label="DISR.", label_w=0.75)
    colw = (SW - 2 * MX - 0.4) / 2
    x2 = MX + colw + 0.4
    tfc = panel_card(s, MX, 1.62, colw, 2.5, color, "Le concept")
    bullets(tfc, quoi, size=11.5, color=MUT, before=6)
    tfc = panel_card(s, MX, 4.3, colw, 2.5, color, "Pourquoi introuvable ailleurs")
    bullets(tfc, exclu, size=11.5, color=MUT, before=6)
    tfc = panel_card(s, x2, 1.62, colw, 2.5, NAVY, "Appuis dans l'existant Agentium")
    bullets(tfc, appuis, size=11.5, color=MUT, before=6)
    tfc = panel_card(s, x2, 4.3, colw, 2.5, AMBER, "Risque R&D — assumé")
    bullets(tfc, risque, size=11.5, color=MUT, before=6)
    return s

# ---------------------------------------------------------------- générateur piste exemple
def piste_exemple(letter, name, color, situation, sans, avec, va, kpi):
    s = slide()
    chrome(s, f"Piste {letter} — gain par l'exemple", name, accent=color)
    rect(s, MX, 1.62, SW - 2 * MX, 0.85, NAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
    tf = box(s, MX + 0.28, 1.74, SW - 2 * MX - 0.56, 0.65)
    p = para(tf, "SITUATION   ", size=10.5, color=BLUE, bold=True, mono=True, first=True)
    add_run(p, situation, size=13, color=WHITE, bold=True)
    colw = (SW - 2 * MX - 0.4) / 2
    x2 = MX + colw + 0.4
    tfc = panel_card(s, MX, 2.72, colw, 2.05, MUT, "Sans — état de l'art actuel")
    bullets(tfc, sans, size=11, color=MUT, before=5)
    tfc = panel_card(s, x2, 2.72, colw, 2.05, color, f"Avec la piste {letter}")
    bullets(tfc, avec, size=11, color=MUT, before=5)
    rect(s, MX, 4.97, SW - 2 * MX, 1.85, PANEL, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
    rect(s, MX, 5.09, 0.05, 1.61, color)
    tf = box(s, MX + 0.25, 5.12, SW - 2 * MX - 3.6, 1.6)
    para(tf, "VALEUR POUR LE CLIENT", size=10.5, color=color, bold=True, mono=True, first=True)
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
    "A", "Exécution certifiée & dossier de preuve", BLUE, 4, 5,
    quoi=[
        ("Run re-exécutable à l'identique", "prompts, chunks (SHA-256), I/O d'outils, version des poids, tokenizer, sampling seedé — tout est content-addressed et chaîné"),
        ("Sortie bit-exacte ou rapport de divergence", "localise ce qui a changé : modèle, donnée, outil ou politique"),
        ("Livrable client", "dossier de preuve d'exécution exportable et signable, opposable en audit"),
    ],
    exclu=[
        ("Temporal", "rejoue le code du workflow, jamais la sortie du modèle (effet de bord enregistré)"),
        ("LangGraph", "time-travel sur checkpoints, mais assume le non-déterminisme du LLM"),
        ("Tout acteur cloud-API", "ne contrôle ni les poids ni le batching — le bit-exact lui est physiquement impossible. Seul un serving souverain le permet."),
    ],
    appuis=[
        ("Run.flow_snapshot + lineage", "parent_run_id, replay_overrides (migration 017)"),
        ("SkillInvocation ledger", "chaque tool-call déjà journalisé et horodaté"),
        ("Provider vLLM existant", "contrôle du sampling, des seeds et de la version moteur"),
        ("Hashes de chunks", "SHA-256 déjà présents dans les payloads d'ingestion"),
    ],
    risque=[
        ("Invariance au batch GPU", "le déterminisme vLLM à travers batching dynamique et versions de kernels est un problème dur"),
        ("Mitigation", "« couloir de replay » à batch fixe et engine épinglé + score de divergence toléré en mode dégradé"),
        ("Revers de la médaille", "sujet défendable — publication / brevet possibles"),
    ],
)
piste_exemple(
    "A", "Audit réglementaire 9 mois après les faits", BLUE,
    situation="Un agent a recommandé une dérogation de maintenance il y a 9 mois. L'auditeur exige la justification complète de la décision.",
    sans=[
        "Archéologie de logs : des semaines d'investigation multi-équipes",
        "Le modèle a été mis à jour depuis — la décision n'est plus reproductible",
        "Reconstruction déclarative, non probante face à un régulateur",
    ],
    avec=[
        "Replay certifié en minutes sur le couloir épinglé",
        "Même sortie reproduite, ou divergence localisée (modèle / donnée / politique)",
        "Dossier de preuve signé remis tel quel à l'auditeur",
    ],
    va=[
        "Délai de réponse à l'audit : de semaines à heures",
        "Preuve opposable au lieu de logs déclaratifs — change la nature de la conversation avec le régulateur",
        "Débloque les périmètres régulés (exigences type QCB : supervision humaine, reporting) où l'autonomie était inenvisageable",
    ],
    kpi=["-90% tps d'enquête", "100% runs critiques", "rejouables & signés"],
)

# ================================================================ S7/S8 — Piste B
piste_concept(
    "B", "Identité d'agent & chaîne de mandats", PURPLE, 3, 4,
    quoi=[
        ("Agent = principal IAM de plein droit", "identité propre, distincte de l'humain et du service"),
        ("Mandat", "délégation scoped, bornée dans le temps, dérivée des droits RBAC/ABAC du mandant, atténuée skill par skill"),
        ("Invariant vérifiable à chaque tool-call", "agent ≤ mandat ∩ droits du mandant"),
        ("Non-répudiation", "tool-calls signés, ledger chaîné (Merkle), kill-switch par mandat"),
    ],
    exclu=[
        ("Microsoft Entra Agent ID", "identité d'agent, mais cloud Microsoft, sans sémantique d'atténuation ni preuve on-prem"),
        ("Frameworks open source", "aucune profondeur IAM — l'autorisation y est applicative, pas systémique"),
        ("Le différenciateur", "mandat atténué + preuve cryptographique + on-prem, intégré au moteur d'autorisation existant"),
    ],
    appuis=[
        ("AuthorizationEngine RBAC + ABAC", "conditions owner_match, label_intersect, second_eye_ingestion déjà en prod"),
        ("Manifestes par capability", "périmètres de permissions déjà déclaratifs"),
        ("Audit events", "emit_audit_event avec actor, trace_id, agent_id — la colonne existe déjà"),
    ],
    risque=[
        ("Gestion de clés on-prem", "cycle de vie des identités cryptographiques d'agents (rotation, révocation)"),
        ("Sémantique d'atténuation", "formaliser l'intersection mandat ∩ droits sans exploser la complexité des manifestes"),
        ("Risque global", "modéré — le moteur existe, la couche mandat + signature s'y greffe"),
    ],
)
piste_exemple(
    "B", "Tentative d'action hors mandat par un agent autonome", PURPLE,
    situation="Un agent d'approvisionnement autonome tente un appel payment_release au-delà du seuil délégué, hors de la fenêtre temporelle de son mandat.",
    sans=[
        "Contrôles applicatifs ad hoc, dispersés dans le code de chaque agent",
        "Logs simples, falsifiables, responsabilité diluée entre humain et machine",
        "Conséquence : le RSSI refuse l'autonomie sur tout périmètre sensible",
    ],
    avec=[
        "Blocage au point d'autorisation central — by-design, pas par convention",
        "Trace signée non répudiable : qui a mandaté quoi, à quel agent, pour quel périmètre",
        "Kill-switch : révocation immédiate du mandat, effet sur tous les runs en cours",
    ],
    va=[
        "L'autonomie devient autorisable sur périmètres sensibles — c'est le verrou n°1 de l'adoption des agents en entreprise",
        "Responsabilité attribuable : chaque action a un mandant identifié, condition de l'engagement juridique",
        "Le périmètre d'agents s'étend sans étendre le risque",
    ],
    kpi=["0 action hors mandat", "possible by-design", "autorisation agent :", "jours → heures"],
)

# ================================================================ S9/S10 — Piste C
piste_concept(
    "C", "Auto-amélioration gouvernée", GREEN, 2, 4,
    quoi=[
        ("Boucle fermée", "détection de dérive (scoring) → patch de politique proposé → simulation offline sur runs historiques → gate statistique → décision humaine → rollout progressif + rollback"),
        ("Primitive de plateforme", "l'orchestrateur s'améliore mesurablement sans jamais sortir du cadre de gouvernance"),
    ],
    exclu=[
        ("LangSmith / Langfuse", "observent, ne bouclent pas — aucune action gouvernée en retour"),
        ("DSPy et l'optimisation offline", "optimisent sans gouvernance ni chemin vers la production"),
        ("Personne ne livre", "l'adaptation continue sous gates statistiques et approbation RBAC comme primitive"),
    ],
    appuis=[
        ("Scoring & seuils (E1.5 — livré)", "évaluation auto des runs, triggers de threshold"),
        ("Recommandations proactives (E5 — livré)", "agrégation de scores, suggestions idempotentes"),
        ("Simulation offline (E6 — architecturée)", "what-if policy sur historique"),
        ("golden_flag_ab (livré)", "gate : le variant doit atteindre ≥ baseline"),
        ("≈ 70% du chemin déjà construit", "Vague E — il reste l'intégration de la boucle"),
    ],
    risque=[
        ("Risque R&D faible", "assemblage de briques livrées plus que recherche"),
        ("Point dur résiduel", "représentativité de l'historique de runs pour la simulation (biais de distribution)"),
    ],
)
piste_exemple(
    "C", "Dérive de qualité après ajout d'un corpus", GREEN,
    situation="Un nouveau corpus documentaire est ingéré. Le pass-rate retrieval chute de 91% à 84% sur les requêtes golden.",
    sans=[
        "Tuning manuel à l'aveugle, directement en production",
        "Risque de régression silencieuse sur les autres cas d'usage",
        "Aucune trace de qui a changé quoi, ni pourquoi",
    ],
    avec=[
        "Le système propose un patch : rag_mmr_enabled + λ = 0.6",
        "Rejoue 500 runs historiques offline — gate : 84% → 93%, coût/run −18%",
        "Approbation en un clic (RBAC), rollout progressif, rollback automatique",
    ],
    va=[
        "Amélioration continue chiffrée à chaque cycle — la qualité et le coût se pilotent comme des SLO",
        "Zéro changement non gouverné : chaque évolution de politique a un dossier (simulation + gate + approbateur)",
        "Démontrable dès le premier comité : les chiffres parlent",
    ],
    kpi=["pass-rate 84→93%", "coût/run −18%", "0 changement", "non tracé"],
)

# ================================================================ S11/S12 — Piste D
piste_concept(
    "D", "QoS token souverain — ordonnanceur de capacité", AMBER, 3, 3,
    quoi=[
        ("Contrats de tokens par Run / tenant", "admission control, classes de priorité sur la capacité GPU souveraine partagée"),
        ("Dégradation déterministe", "quand le budget se resserre, l'ordre de sacrifice est connu : compression → budget rerank → MMR — jamais aléatoire"),
        ("Attribution de coût", "par SkillInvocation → chargeback précis par direction métier"),
    ],
    exclu=[
        ("Hyperscalers", "font du QoS token en interne, ne l'exposent jamais à leurs clients"),
        ("Frameworks d'orchestration", "ne gèrent pas la capacité du tout — ils consomment des API"),
        ("Sur capacité souveraine finie", "(le cas PIH par définition), c'est ce qui transforme « scalability » d'une promesse en un contrat"),
    ],
    appuis=[
        ("Budget génératif RAGGER (prod)", "résolution de fenêtre, paliers, clamps de sécurité — déjà déterministe par génération"),
        ("Knobs de pipeline existants", "compression, budget cross-encoder (0.5s), MMR — tous flag-controlés"),
        ("SkillInvocation ledger", "le grain d'attribution de coût existe déjà"),
    ],
    risque=[
        ("Ordonnancement multi-tenant", "préemption et famine sur GPU partagé — classique mais exigeant"),
        ("Calibration des paliers", "lier latence cible et budget token par classe de service demande du bench"),
    ],
)
piste_exemple(
    "D", "Pic de charge sur capacité GPU souveraine finie", AMBER,
    situation="Fin de mois : le briefing exécutif interactif et un batch documentaire massif se disputent la même capacité GPU souveraine.",
    sans=[
        "Latence imprévisible pour tout le monde — y compris l'exécutif",
        "Seule issue : surprovisionner le GPU (capex) pour absorber le pic",
        "Coûts d'inférence non attribuables aux directions consommatrices",
    ],
    avec=[
        "Classe « critique » garantie : le briefing tient sa latence cible",
        "Le batch dégrade selon l'échelle déterministe — résultat prédictible, jamais aléatoire",
        "Chargeback par direction sur la base du ledger d'invocations",
    ],
    va=[
        "SLA tenus sans GPU additionnels — le capex évité finance la plateforme",
        "Coûts prédictibles par classe de service — lisible pour un DSI comme pour un CFO",
        "L'arbitrage de capacité devient une décision de gestion, plus un incident",
    ],
    kpi=["capex GPU évité", "latence garantie", "par classe", "chargeback / dir."],
)

# ================================================================ S13 — Comparatif
s = slide()
chrome(s, "Synthèse", "Évaluation comparative des quatre pistes")
headers = ["Critère", "A — Exécution certifiée", "B — Mandats d'agent", "C — Auto-amélioration", "D — QoS token"]
data = [
    ("Piliers PIH servis", "Souveraineté · Robustesse · Audit", "Sécurité · Audit", "Token perf · Robustesse · Observabilité", "Token perf · Scalabilité"),
    ("Exclusivité réelle", "Très forte — physiquement impossible en cloud-API", "Forte — Entra arrive, mais cloud-only", "Forte — personne ne boucle avec gouvernance", "Forte mais discrète"),
    ("Appui sur l'existant", "Élevé (replay lineage, ledger, vLLM)", "Élevé (IAM engine, manifestes)", "Très élevé (≈70% livré, Vague E)", "Élevé (RAGGER, knobs pipeline)"),
    ("Défendabilité (brevet / publi)", "Forte", "Moyenne-forte", "Moyenne", "Moyenne"),
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
style_cell(tbl.cell(len(data) + 1, 0), "Difficulté R&D (1–5)", size=10, bold=True, fill=WHITE)
style_cell(tbl.cell(len(data) + 2, 0), "Disruption / exclusivité (1–5)", size=10, bold=True, fill=PANEL)
dif_dis = [(4, 5), (3, 4), (2, 4), (3, 3)]
for j, (dif, dis) in enumerate(dif_dis):
    style_cell(tbl.cell(len(data) + 1, j + 1), "● " * dif + "○ " * (5 - dif), size=10, color=accents[j], fill=WHITE, mono=True)
    style_cell(tbl.cell(len(data) + 2, j + 1), "● " * dis + "○ " * (5 - dis), size=10, color=accents[j], fill=PANEL, mono=True)
tf = box(s, MX, 6.55, SW - 2 * MX, 0.5)
p = para(tf, "Lecture : ", size=11, color=MUT, first=True, bold=True)
add_run(p, "C est le quick-win démontrable ; A est le différenciateur structurel — sa difficulté est la barrière à l'entrée des concurrents.",
        size=11, color=MUT)

# ================================================================ S14 — Réglementation
s = slide()
chrome(s, "Cadre réglementaire", "Qatar & Golfe : pas d'AI Act, une trajectoire exploitable")
colw = (SW - 2 * MX - 0.4) / 2
x2 = MX + colw + 0.4
tfc = panel_card(s, MX, 1.62, colw, 2.6, NAVY, "Qatar — sectoriel, pas horizontal")
bullets(tfc, [
    ("QCB AI Guidelines (09/2024)", "contraignant pour la finance : systèmes « haut risque », supervision humaine, reporting régulateur"),
    ("NCSA (2024)", "guidelines d'adoption sécurisée de l'IA"),
    ("QFMA (05/2025)", "projet de règles IA pour les marchés de capitaux"),
    ("Phase 3 (2026–2027)", "harmonisation inter-sectorielle + alignement Golfe — le cadre horizontal est la trajectoire"),
], size=10.5, before=5)
tfc = panel_card(s, x2, 1.62, colw, 2.6, NAVY, "Région — souveraineté avant conformité")
bullets(tfc, [
    ("Arabie Saoudite", "2026 « Year of AI », loi IA attendue ; draft Global AI Hub Law : data embassies, souveraineté numérique"),
    ("EAU", "soft law assumée (AI Charter 2024) + contraignant sectoriel (CBUAE, 02/2026)"),
    ("Bahreïn", "seule proposition de loi IA dédiée du GCC (04/2024)"),
    ("AI Act UE", "applicable extraterritorialement si sorties utilisées dans l'UE — pleinement en vigueur depuis 08/2026"),
], size=10.5, before=5)
rect(s, MX, 4.42, SW - 2 * MX, 1.0, NAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.07)
tf = box(s, MX + 0.28, 4.56, SW - 2 * MX - 0.56, 0.75)
para(tf, "IMPLICATION POUR LE PITCH PIH", size=10, color=BLUE, bold=True, mono=True, first=True)
para(tf, "Le driver régional est la souveraineté prouvable, pas la conformité au risque. Construire la traçabilité de niveau « preuve » maintenant = conforme avant que les règles n'atterrissent.",
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
chrome(s, "Recommandation", "Un scope en deux temps sous une bannière unique")
rect(s, MX, 1.62, SW - 2 * MX, 0.95, NAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.07)
tf = box(s, MX + 0.28, 1.78, SW - 2 * MX - 0.56, 0.7)
p = para(tf, "« SOVEREIGN PROOF-OF-EXECUTION »  ", size=15, color=WHITE, bold=True, mono=True, first=True)
add_run(p, "— la souveraineté de PIH cesse d'être une contrainte : elle devient la capacité que personne d'autre ne peut leur offrir.",
        size=13, color=RGBColor(0xBE, 0xD0, 0xE8))
colw = (SW - 2 * MX - 0.4) / 2
x2 = MX + colw + 0.4
tfc = panel_card(s, MX, 2.85, colw, 2.3, GREEN, "Temps 1 — Piste C : le quick-win")
bullets(tfc, [
    "Fermer la boucle d'auto-amélioration gouvernée (≈70% livré)",
    "Preuve de valeur chiffrée dès le premier comité : pass-rate, coût/run",
    "Démontre la maturité de la chaîne System → Run → Evaluation → Decision → Action",
], size=11.5, before=6)
tfc = panel_card(s, x2, 2.85, colw, 2.3, BLUE, "Temps 2 — Pistes A + B : le différenciateur")
bullets(tfc, [
    "Replay déterministe certifié portant la chaîne de mandats",
    "Non copiable par un concurrent cloud sans renoncer à son modèle",
    "La piste D suit en extension naturelle du contrat de service",
], size=11.5, before=6)
rect(s, MX, 5.35, SW - 2 * MX, 1.35, PANEL, line_color=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
rect(s, MX, 5.47, 0.05, 1.11, AMBER)
tf = box(s, MX + 0.25, 5.5, SW - 2 * MX - 0.5, 1.1)
para(tf, "POINTS DE VIGILANCE", size=10, color=AMBER, bold=True, mono=True, first=True)
bullets(tf, [
    "Ne pas survendre le bit-exact : annoncer « replay certifié + rapport de divergence », le bit-exact strict étant le mode nominal sur couloir épinglé",
    "Prérequis E0 (rotation des secrets Keycloak / PG) bloquant avant tout engagement client réel — roadmap interne",
], size=11, color=INK, first=False, before=4)

# ---------------------------------------------------------------- save
import os
out = os.path.join(os.path.dirname(__file__), "out", "PIH-scope-exclusif-RD-agentium.pptx")
os.makedirs(os.path.dirname(out), exist_ok=True)
prs.save(out)
print(f"saved: {out} — {len(prs.slides.slides if hasattr(prs.slides,'slides') else prs.slides._sldIdLst)} slides")
