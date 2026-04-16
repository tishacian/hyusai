#!/usr/bin/env python3
"""
Génère les PNG du bilan MVP JusticIA (mockups statiques, thème sombre + logo).
Simule une session réaliste couvrant l'ensemble de la roadmap MVP.
Dépendance : Pillow

  python scripts/generate_justicia_deck_mockup_images.py
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
LOGO_PATH = REPO / "image" / "justicia.png"
OUT = REPO / "presentations" / "justicia-metaketing-aziz" / "screenshots"
W, H = 1600, 900
BG_BASE = (11, 13, 18)
TEXT = (230, 237, 243)
TEXT_MUTED = (139, 148, 158)
ACCENT = (88, 166, 255)
CARD = (22, 27, 34)
BORDER = (48, 54, 61)
SIDEBAR_BG = (18, 21, 28)
USER_BG = (30, 40, 55)
AI_BG = (22, 27, 34)
SRC_BG = (13, 45, 85)
SRC_BORDER = (56, 139, 253)
INPUT_BG = (13, 17, 23)
GREEN = (63, 185, 80)
ORANGE = (227, 149, 52)
RED_MUTED = (200, 80, 80)
GRAD_COLS = [
    (122, 119, 185), (159, 107, 172), (194, 94, 154), (219, 86, 134),
    (232, 82, 111), (240, 87, 87), (243, 99, 64), (237, 120, 48),
]
WRAP_MAIN = 82
WRAP_NARROW = 60


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _gradient_background() -> Image.Image:
    img = Image.new("RGB", (W, H), BG_BASE)
    px = img.load()
    br, bg, bb = BG_BASE
    for x in range(W):
        t = x / max(W - 1, 1)
        idx = t * (len(GRAD_COLS) - 1)
        i = int(idx)
        f = idx - i
        c1 = GRAD_COLS[min(i, len(GRAD_COLS) - 1)]
        c2 = GRAD_COLS[min(i + 1, len(GRAD_COLS) - 1)]
        r = int(c1[0] * (1 - f) + c2[0] * f)
        g = int(c1[1] * (1 - f) + c2[1] * f)
        b = int(c1[2] * (1 - f) + c2[2] * f)
        ar = int(r * 0.38 + br * 0.62)
        ag = int(g * 0.38 + bg * 0.62)
        ab = int(b * 0.38 + bb * 0.62)
        for y in range(H):
            px[x, y] = (ar, ag, ab)
    return img


def _logo(size: int = 72) -> Image.Image | None:
    if not LOGO_PATH.is_file():
        return None
    lg = Image.open(LOGO_PATH).convert("RGBA")
    lg.thumbnail((size, size), Image.Resampling.LANCZOS)
    return lg


def _paste_logo(img: Image.Image, x: int, y: int, size: int = 72) -> None:
    lg = _logo(size)
    if lg:
        img.paste(lg, (x, y), lg)


def _save(name: str, img: Image.Image) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    img.save(path, "PNG", optimize=True)
    print(path)


def _draw_bubble(d: ImageDraw.ImageDraw, x0: int, y: int, x1: int,
                 label: str, text: str, bg: tuple, fs: ImageFont.ImageFont,
                 fl: ImageFont.ImageFont, wrap: int = WRAP_NARROW) -> int:
    lines = textwrap.wrap(text, width=wrap)
    lh = fs.size + 6 if hasattr(fs, "size") else 22
    h = 16 + 20 + len(lines) * lh + 12
    d.rounded_rectangle((x0, y, x1, y + h), radius=10, fill=bg, outline=BORDER)
    d.text((x0 + 16, y + 10), label, fill=TEXT_MUTED, font=fl)
    ty = y + 32
    for line in lines:
        d.text((x0 + 16, ty), line, fill=TEXT, font=fs)
        ty += lh
    return y + h + 10


def _draw_sidebar(d: ImageDraw.ImageDraw, img: Image.Image) -> int:
    sw = 340
    d.rectangle((0, 0, sw, H), fill=SIDEBAR_BG)
    d.line((sw, 0, sw, H), fill=BORDER, width=1)
    y = 32
    d.text((24, y), "Paramètres", fill=TEXT, font=_font(20))
    y += 36

    fs = _font(13)
    fv = _font(14)

    for label, val in [
        ("Profil", "Juge  ▾"),
        ("Modèle", "Llama 3.1 — 8B Instruct  ▾"),
        ("Base documentaire", "faiss_JusticIA  ▾"),
        ("Pipeline", "C-HAH — retrieval hybride  ▾"),
        ("Température", "0.10"),
    ]:
        d.text((24, y), label, fill=TEXT_MUTED, font=fs)
        d.text((24, y + 16), val, fill=TEXT, font=fv)
        y += 40

    d.line((24, y, sw - 24, y), fill=BORDER, width=1)
    y += 10
    d.text((24, y), "Instruction de raisonnement", fill=TEXT_MUTED, font=fs)
    y += 18
    d.rounded_rectangle((24, y, sw - 24, y + 28), radius=6, fill=CARD, outline=ACCENT, width=1)
    d.text((34, y + 6), "Analytique (fr)  ▾", fill=ACCENT, font=fv)
    y += 38

    d.line((24, y, sw - 24, y), fill=BORDER, width=1)
    y += 10
    d.text((24, y), "Historique", fill=TEXT_MUTED, font=fs)
    y += 20
    for title in [
        "Délais de recours — permis",
        "Clause de non-concurrence",
        "Responsabilité contractuelle",
    ]:
        d.rounded_rectangle((24, y, sw - 24, y + 28), radius=6, fill=CARD, outline=BORDER)
        d.text((34, y + 6), title, fill=TEXT, font=_font(12))
        y += 34

    d.line((24, y + 4, sw - 24, y + 4), fill=BORDER, width=1)
    y += 14
    d.rounded_rectangle((24, y, sw - 24, y + 30), radius=6, fill=CARD, outline=BORDER)
    d.text((34, y + 7), "Exporter la conversation (JSON)", fill=ACCENT, font=_font(12))
    return sw + 28


def _draw_header(d: ImageDraw.ImageDraw, img: Image.Image, mx: int) -> int:
    _paste_logo(img, mx, 24, 48)
    d.text((mx + 60, 28), "JusticIA", fill=TEXT, font=_font(28))
    d.text((mx + 60, 62), "Assistant juridique — recherche augmentée sur corpus indexé", fill=TEXT_MUTED, font=_font(13))
    return 90


# ---------------------------------------------------------------------------
# SLIDE 1 — Couverture : proposition de valeur
# ---------------------------------------------------------------------------

def slide_1() -> None:
    img = _gradient_background()
    d = ImageDraw.Draw(img)
    _paste_logo(img, 72, 48, 88)
    d.text((180, 58), "JusticIA", fill=TEXT, font=_font(44))
    d.text((180, 118), "Assistant juridique — recherche augmentée sur corpus indexé", fill=TEXT_MUTED, font=_font(20))

    cols = [
        ("Ingestion multi-format + OCR",
         "PDF, DOCX, e-mail, HTML — OCR\nTesseract pour les pièces numérisées.\nExtraction de méta-données."),
        ("Retrieval hybride intelligent",
         "Index dense FAISS + lexical BM25,\nrerank par cross-encoder.\nRecherche guidée par méta-données."),
        ("Multi-modèles & multi-profils",
         "3 familles (Gemma, Llama, Mistral),\nprofils métier (juge, avocat, …),\ndétection automatique de la tâche."),
    ]
    cw = (W - 160) // 3
    for i, (title, sub) in enumerate(cols):
        x0 = 72 + i * (cw + 16)
        d.rounded_rectangle((x0, 240, x0 + cw - 16, 470), radius=14, fill=CARD, outline=BORDER, width=1)
        d.text((x0 + 24, 264), title, fill=ACCENT, font=_font(20))
        for j, line in enumerate(sub.split("\n")):
            d.text((x0 + 24, 302 + j * 24), line, fill=TEXT_MUTED, font=_font(15))

    y = 510
    d.text((72, y), "Fonctionnalités clés du MVP", fill=TEXT, font=_font(22))
    y += 36
    features = [
        ("5 templates de raisonnement", GREEN),
        ("Pipeline C-HAH optimisé", GREEN),
        ("Chaîne hyper-layered", GREEN),
        ("Sélection auto. de la tâche", GREEN),
        ("Micro-service indépendant", GREEN),
        ("Réponses sourcées", GREEN),
    ]
    fx = 72
    for label, col in features:
        tw = _font(14).getlength(label) if hasattr(_font(14), "getlength") else len(label) * 8
        d.rounded_rectangle((fx, y, fx + tw + 28, y + 26), radius=6, fill=(20, 50, 30), outline=GREEN, width=1)
        d.text((fx + 14, y + 5), label, fill=GREEN, font=_font(14))
        fx += tw + 40
        if fx > W - 200:
            fx = 72
            y += 34

    _save("01-couverture.png", img)


# ---------------------------------------------------------------------------
# SLIDE 2 — Interface assistant avec session réaliste multi-tours
# ---------------------------------------------------------------------------

def slide_2() -> None:
    img = _gradient_background()
    d = ImageDraw.Draw(img)
    mx = _draw_sidebar(d, img)
    y = _draw_header(d, img, mx)
    fs = _font(14)
    fl = _font(12)

    d.rounded_rectangle((mx, y, W - 32, y + 36), radius=8, fill=SRC_BG, outline=SRC_BORDER, width=1)
    d.text((mx + 12, y + 9), "Sources — Code de l'urbanisme L.600-1 ; CE, 3e ch., 15 mars 2024, n° 472.318", fill=ACCENT, font=fl)
    d.text((W - 235, y + 9), "Dernière réponse  0,9 s", fill=TEXT, font=fl)
    d.rounded_rectangle((W - 360, y + 4, W - 244, y + 28), radius=4, fill=(30, 55, 30))
    d.text((W - 352, y + 7), "Analytique", fill=GREEN, font=_font(11))
    y += 48

    y = _draw_bubble(d, mx, y, W - 32,
        "Vous  ·  Profil : Juge",
        "Quels sont les délais de recours contre un refus de permis de construire ?",
        USER_BG, fs, fl, WRAP_NARROW)

    y = _draw_bubble(d, mx, y, W - 32,
        "JusticIA  ·  Llama 3.1 — Analytique  ·  3 sources",
        "Le recours contentieux contre un refus de permis de construire doit être exercé "
        "dans un délai de deux mois à compter de la notification de la décision au demandeur "
        "(art. R.600-1 et R.421-1 du code de l'urbanisme). En l'absence de notification régulière, "
        "le délai ne court pas. Un recours gracieux préalable proroge le délai de deux mois "
        "supplémentaires (art. R.421-2 CJA).",
        AI_BG, fs, fl, WRAP_NARROW)

    y = _draw_bubble(d, mx, y, W - 32,
        "Vous  ·  Profil : Juge",
        "Et si le refus est implicite (silence de l'administration) ?",
        USER_BG, fs, fl, WRAP_NARROW)

    y = _draw_bubble(d, mx, y, W - 32,
        "JusticIA  ·  Llama 3.1 — Analytique  ·  2 sources",
        "En cas de décision implicite de rejet, le délai de deux mois court à compter de la "
        "date à laquelle la décision est réputée acquise. L'administration doit avoir accusé "
        "réception de la demande en mentionnant ce mécanisme (art. L.112-6 CRPA). "
        "Vérifiez dans les pièces du dossier si l'accusé de réception était conforme.",
        AI_BG, fs, fl, WRAP_NARROW)

    d.rounded_rectangle((mx, H - 52, W - 32, H - 16), radius=8, fill=INPUT_BG, outline=BORDER)
    d.text((mx + 16, H - 40), "Le recours est-il suspensif dans ce cas ?", fill=TEXT_MUTED, font=fl)

    _save("02-assistant.png", img)


# ---------------------------------------------------------------------------
# SLIDE 3 — Pipeline C-HAH + détection automatique + modèles
# ---------------------------------------------------------------------------

def slide_3() -> None:
    img = _gradient_background()
    d = ImageDraw.Draw(img)
    _paste_logo(img, 72, 32, 48)
    d.text((132, 40), "Pipeline C-HAH & chaîne de raisonnement", fill=TEXT, font=_font(30))
    d.text((132, 80), "Architecture implémentée — détection automatique de la tâche et raisonnement hyper-layered", fill=TEXT_MUTED, font=_font(14))

    steps = [
        ("1. Ingestion", "Multi-format + OCR\nMéta-données\nMicro-service"),
        ("2. Embeddings", "sentence-transformers\nCache LRU\nBatch GPU/CPU"),
        ("3. Indexation", "FAISS (dense)\nBM25 (lexical)\nPersistance disque"),
        ("4. Retrieval", "C-HAH pipeline\nSmart retrieval\n+ méta-données"),
        ("5. Génération", "Classif. bayésienne\nTemplate adapté\nCitations sourcées"),
    ]
    bw = (W - 140) // 5
    y0 = 120
    for i, (title, lines) in enumerate(steps):
        x0 = 72 + i * bw
        d.rounded_rectangle((x0, y0, x0 + bw - 12, y0 + 140), radius=10, fill=CARD, outline=BORDER)
        d.text((x0 + 14, y0 + 12), title, fill=ACCENT, font=_font(15))
        for j, line in enumerate(lines.split("\n")):
            d.text((x0 + 14, y0 + 40 + j * 20), line, fill=TEXT_MUTED, font=_font(13))
        if i < 4:
            ax = x0 + bw - 6
            d.text((ax - 6, y0 + 60), "→", fill=BORDER, font=_font(20))

    y0 = 290
    d.text((72, y0), "Sélection automatique du raisonnement", fill=TEXT, font=_font(18))
    y0 += 30
    d.rounded_rectangle((72, y0, W - 72, y0 + 56), radius=8, fill=CARD, outline=BORDER)
    d.text((92, y0 + 8), "Classification bayésienne de la requête", fill=TEXT, font=_font(15))
    d.text((92, y0 + 30), "→  Factuel  |  Analytique  |  Comparatif  |  Causal  |  Hypothétique", fill=ACCENT, font=_font(14))
    d.rounded_rectangle((W - 300, y0 + 10, W - 92, y0 + 44), radius=6, fill=(30, 55, 30), outline=GREEN, width=1)
    d.text((W - 288, y0 + 17), "Hyper-layered chain-of-thoughts", fill=GREEN, font=_font(13))
    y0 += 74

    d.text((72, y0), "Modèles disponibles", fill=TEXT, font=_font(18))
    y0 += 30
    models = [
        ("Gemma (Google)", "2B · 7B · 9B", GREEN),
        ("Llama (Meta)", "3.1 8B · 70B Instruct", GREEN),
        ("Mistral", "7B · Nemo 12B", GREEN),
    ]
    mw = (W - 160) // 3
    for i, (name, sizes, col) in enumerate(models):
        x0 = 72 + i * (mw + 8)
        d.rounded_rectangle((x0, y0, x0 + mw, y0 + 60), radius=8, fill=CARD, outline=BORDER)
        d.text((x0 + 16, y0 + 10), name, fill=col, font=_font(16))
        d.text((x0 + 16, y0 + 34), sizes, fill=TEXT_MUTED, font=_font(13))
    y0 += 80

    metrics = [
        ("Documents indexés", "10", TEXT),
        ("Latence retrieval", "< 200 ms", GREEN),
        ("Précision sources", "92 %", GREEN),
        ("Temps indexation", "4,2 s", ACCENT),
    ]
    mw2 = (W - 140) // 4
    for i, (lab, val, col) in enumerate(metrics):
        x0 = 72 + i * (mw2 + 8)
        d.rounded_rectangle((x0, y0, x0 + mw2 - 16, y0 + 72), radius=10, fill=CARD, outline=BORDER)
        d.text((x0 + 14, y0 + 10), lab, fill=TEXT_MUTED, font=_font(14))
        d.text((x0 + 14, y0 + 36), val, fill=col, font=_font(24))
    _save("03-pipeline.png", img)


# ---------------------------------------------------------------------------
# SLIDE 4 — Traçabilité des sources avec méta-données
# ---------------------------------------------------------------------------

def slide_4() -> None:
    img = _gradient_background()
    d = ImageDraw.Draw(img)
    _paste_logo(img, 72, 32, 44)
    d.text((128, 40), "Traçabilité des sources & méta-données", fill=TEXT, font=_font(30))
    d.text((128, 78), "Chaque réponse cite les passages du corpus — extraction automatique des méta-données", fill=TEXT_MUTED, font=_font(14))

    sources = [
        ("Source 1 — Code de l'urbanisme, art. R.600-1",
         "« Le délai de recours contentieux à l'encontre d'une décision de non-opposition "
         "à une déclaration préalable ou d'un permis de construire court à l'égard des tiers "
         "à compter du premier jour d'une période continue de deux mois d'affichage … »",
         "Pertinence : 0.94",
         "Type : Code  ·  Juridiction : —  ·  Date : en vigueur"),
        ("Source 2 — CE, 3e ch., 15 mars 2024, n° 472.318",
         "« Considérant que le délai de recours contentieux ne court qu'à compter de la date "
         "à laquelle la décision attaquée a été régulièrement notifiée au pétitionnaire, avec "
         "mention des voies et délais de recours … »",
         "Pertinence : 0.89",
         "Type : Jurisprudence  ·  Juridiction : CE  ·  Date : 15/03/2024"),
        ("Source 3 — CRPA, art. L.112-6",
         "« L'administration est tenue de délivrer un accusé de réception pour toute demande "
         "adressée par un usager, mentionnant les délais et voies de recours ainsi que la date "
         "à laquelle la demande sera réputée acceptée ou rejetée. »",
         "Pertinence : 0.86",
         "Type : Code  ·  Juridiction : —  ·  Date : en vigueur"),
    ]
    y = 118
    for title, body, score, meta in sources:
        lines = textwrap.wrap(body, width=100)
        h = 22 + len(lines) * 18 + 30
        d.rounded_rectangle((72, y, W - 72, y + h), radius=8, fill=CARD, outline=BORDER)
        d.text((92, y + 8), title, fill=ACCENT, font=_font(15))
        d.text((W - 250, y + 8), score, fill=GREEN, font=_font(13))
        ty = y + 30
        for line in lines:
            d.text((92, ty), line, fill=TEXT, font=_font(13))
            ty += 18
        d.text((92, ty + 2), meta, fill=ORANGE, font=_font(12))
        y += h + 8

    d.rounded_rectangle((72, y + 6, W - 72, y + 48), radius=8, fill=SRC_BG, outline=SRC_BORDER, width=1)
    d.text((92, y + 18),
           "3 passages retenus sur 10 documents — seuil de pertinence : 0.80 — méta-données extraites automatiquement",
           fill=ACCENT, font=_font(14))
    _save("04-sources.png", img)


# ---------------------------------------------------------------------------
# SLIDE 5 — Profils VDB, gouvernance, admin
# ---------------------------------------------------------------------------

def slide_5() -> None:
    img = _gradient_background()
    d = ImageDraw.Draw(img)
    d.text((72, 40), "Profils, bases vectorielles & gouvernance", fill=TEXT, font=_font(30))
    d.text((72, 78), "Multi-profils métier avec bases dédiées — administration et rôles", fill=TEXT_MUTED, font=_font(14))

    y = 120
    d.text((72, y), "Bibliothèque de bases vectorielles (VDB)", fill=TEXT, font=_font(18))
    y += 30
    profiles = [
        ("Juge", "Corpus décisionnel, jurisprudence\nadministrative et judiciaire", GREEN, "Chargée"),
        ("Avocat", "Dossiers clients, notes de plaidoirie,\njurisprudence de référence", GREEN, "Chargée"),
        ("Notaire", "Actes notariés, réglementation\nfoncière et successorale", ACCENT, "Prête"),
        ("Personnalisé", "Corpus défini par l'utilisateur\n(upload documents)", ACCENT, "Prête"),
    ]
    pw = (W - 160) // 4
    for i, (name, desc, col, status) in enumerate(profiles):
        x0 = 72 + i * (pw + 8)
        d.rounded_rectangle((x0, y, x0 + pw, y + 100), radius=10, fill=CARD, outline=BORDER)
        d.text((x0 + 14, y + 10), name, fill=col, font=_font(16))
        for j, line in enumerate(desc.split("\n")):
            d.text((x0 + 14, y + 34 + j * 18), line, fill=TEXT_MUTED, font=_font(12))
        d.rounded_rectangle((x0 + pw - 74, y + 10, x0 + pw - 10, y + 30), radius=4, fill=col)
        d.text((x0 + pw - 70, y + 13), status, fill=(0, 0, 0), font=_font(11))
    y += 120

    d.text((72, y), "Rôles et accès", fill=TEXT, font=_font(18))
    y += 28
    headers = ["Rôle", "Périmètre d'accès", "Config."]
    rows = [
        ("Juriste / métier", "Chat JusticIA + corpus du profil attribué", "Non"),
        ("Admin données", "Création VDB, indexation, ajout / retrait documents", "Oui"),
        ("Admin instructions", "Modification des templates de raisonnement LLM", "Oui"),
        ("DSI / sécurité", "Journaux d'accès, politique de rétention, clés API", "Oui"),
    ]
    xs = [82, 380, 1120]
    for i, h in enumerate(headers):
        d.text((xs[i], y), h, fill=ACCENT, font=_font(15))
    y += 24
    d.line((72, y, W - 72, y), fill=BORDER, width=1)
    y += 10
    for row in rows:
        for i, cell in enumerate(row):
            d.text((xs[i], y), cell, fill=TEXT, font=_font(14))
        y += 30

    y += 16
    d.rounded_rectangle((72, y, W - 72, y + 90), radius=10, fill=CARD, outline=BORDER)
    d.text((92, y + 10), "Isolation par workspace", fill=ACCENT, font=_font(16))
    d.text((92, y + 34),
           "Chaque workspace dispose de ses propres bases vectorielles, historiques de conversation",
           fill=TEXT, font=_font(14))
    d.text((92, y + 54),
           "et droits d'accès. Interface de création et chargement de VDB intégrée.",
           fill=TEXT, font=_font(14))

    d.rounded_rectangle((W - 440, y + 10, W - 92, y + 34), radius=4, fill=RED_MUTED)
    d.text((W - 432, y + 14), "En attente : données client pour constitution des VDB", fill=TEXT, font=_font(12))

    _save("05-gouvernance.png", img)


# ---------------------------------------------------------------------------
# SLIDE 6 — Investissement et cadre contractuel
# ---------------------------------------------------------------------------

def slide_6() -> None:
    img = _gradient_background()
    d = ImageDraw.Draw(img)
    _paste_logo(img, 72, 28, 44)
    d.text((128, 36), "Investissement et cadre contractuel", fill=TEXT, font=_font(28))
    y = 86
    fs = _font(16)
    fl = _font(14)

    d.rounded_rectangle((72, y, 760, y + 56), radius=10, fill=CARD, outline=BORDER)
    d.text((92, y + 8), "Licence papAI", fill=ACCENT, font=fs)
    d.text((92, y + 30), "3 utilisateurs — 21 000 € HT / an", fill=TEXT, font=fl)

    d.rounded_rectangle((790, y, W - 72, y + 56), radius=10, fill=CARD, outline=BORDER)
    d.text((810, y + 8), "Développements", fill=ACCENT, font=fs)
    d.text((810, y + 30), "59 000 € HT — forfait Phases 1 et 2", fill=TEXT, font=fl)
    y += 72

    phases = [
        ("Phase 1 — CPU", "RAGGER + RAFT intégrés à papAI", "Premières briques RAG déployées", GREEN, "Livré"),
        ("Phase 2 — GPU", "Activation GPU, LAFT intégré à papAI", "Inférence locale + recherche automatisée", ORANGE, "En cours"),
    ]
    pw = (W - 160) // 2
    for i, (title, l1, l2, col, status) in enumerate(phases):
        x0 = 72 + i * (pw + 16)
        d.rounded_rectangle((x0, y, x0 + pw, y + 90), radius=10, fill=CARD, outline=BORDER)
        d.text((x0 + 16, y + 10), title, fill=ACCENT, font=fs)
        d.text((x0 + 16, y + 34), l1, fill=TEXT, font=fl)
        d.text((x0 + 16, y + 56), l2, fill=TEXT_MUTED, font=fl)
        d.rounded_rectangle((x0 + pw - 82, y + 10, x0 + pw - 12, y + 32), radius=6, fill=col)
        d.text((x0 + pw - 76, y + 13), status, fill=(0, 0, 0), font=_font(12))
    y += 108

    d.text((72, y), "Infrastructure mobilisée", fill=TEXT, font=fs)
    y += 26
    infra = [
        "Serveur GPU dédié — inférence locale Llama 3 / Gemma / Mistral, travaux LAFT",
        "Serveur CPU / staging OVH — développement, tests, démo Streamlit",
        "Stockage — index FAISS, corpus de test, artefacts de benchmarking",
        "Réseau — SSL, CI/CD Bitbucket, configuration ports et accès",
    ]
    for line in infra:
        d.text((92, y), "•  " + line, fill=TEXT_MUTED, font=fl)
        y += 22
    y += 10
    d.text((72, y), "Charge humaine estimée : ~55 jours-homme", fill=TEXT, font=fs)
    d.text((72, y + 22), "Moteur RAG, ingestion OCR, interface, embeddings, benchmarking, infra", fill=TEXT_MUTED, font=fl)

    _save("06-partenariat.png", img)


def main() -> None:
    slide_1()
    slide_2()
    slide_3()
    slide_4()
    slide_5()
    slide_6()
    print("Done:", OUT)


if __name__ == "__main__":
    main()
