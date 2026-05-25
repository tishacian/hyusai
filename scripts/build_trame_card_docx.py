#!/usr/bin/env python3
"""Build the SENTINEL-CI presenter trame card as a minimal Word document.

The output is a sober, presenter-friendly carte de trame: one heading per
scenario, one block per step (S1.1 → S2.7), with the verbatim phrase to say
in bold, AYA's expected reply in one line, what shows up on screen, and a
manual Plan B click path. No emoji, no dev jargon (no commit hashes, no
technical intent names).

Usage:
    python3 scripts/build_trame_card_docx.py [output.docx]

Default output: docs/sentinel-ci-demo-trame-presenter-card-2026-05-25.docx
"""

from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Cm, Pt, RGBColor


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "sentinel-ci-demo-trame-presenter-card-2026-05-25.docx"

FONT_FAMILY = "Calibri"
BODY_PT = 10.5
SMALL_PT = 9.5
TITLE_PT = 18
H2_PT = 13
H3_PT = 11.5

ACCENT = RGBColor(0x0F, 0x6F, 0x3F)  # sober green
DIM = RGBColor(0x55, 0x60, 0x6E)
TEXT = RGBColor(0x12, 0x18, 0x22)


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

PROD_URL = "https://agentium.papai.ai/hypervisor/mission-room/cockpit?workspace=sentinel-ci"
PROFIL = "Profil vigie_executive · Bouton « Parler à AYA » (barre AYA en bas du cockpit)"

PREAMBLE = [
    "Lire chaque phrase mot pour mot, sans filler poli en début de tour.",
    "Si AYA ne réagit pas en 2 secondes, copier la phrase telle quelle dans le Quick Panel (Cmd / Ctrl + K).",
    "Si toujours rien, suivre le Plan B clic indiqué pour l'étape — même effet à l'écran.",
]

SCENARIO_1 = (
    "Scénario 1 — Drill Nord & cargo Atlantic Trader",
    [
        {
            "id": "S1.1",
            "title": "Brief lundi matin",
            "say": "AYA, c'est lundi matin. Qu'est-ce qui demande mon attention ?",
            "reply": "« Monsieur le Vice-Président, la zone Nord est tendue : projet drone Napié, retard cargo, dédouanement à Vridi. »",
            "screen": "Navigation Stratégie, focus Zone Nord, projet drones Napié mis en évidence.",
            "plan_b": "Sidebar gauche → chip « Zone Nord · Tendue » (la carte se cale sur la zone-nord).",
        },
        {
            "id": "S1.3",
            "title": "Drill Nord",
            "say": "AYA, pourquoi la situation Nord est-elle tendue ?",
            "reply": "« La cause amont, c'est Napié : retard projet drone, chaîne logistique bloquée à Vridi. »",
            "screen": "Drill causal Zone Nord, brief opérationnel Napié, vignette webcam APM Apapa si la chaîne s'étend au cargo.",
            "plan_b": "Sidebar gauche → chip « Zone Nord · Tendue » (même cible que S1.1, focus zone-nord).",
        },
        {
            "id": "S1.4",
            "title": "PV douanes",
            "say": "AYA, ouvre le PV douanes.",
            "reply": "« Page 2 du PV du 18 mai : la non-conformité vise un autre cargo. MV Atlantic Trader est bloqué par effet collatéral. »",
            "screen": "Drawer aperçu document : PV douanes PDF, page 2, citation OCR surlignée.",
            "plan_b": "Quick Panel → onglet Documents → « PV douanes Atlantic Trader ».",
        },
        {
            "id": "S1.5",
            "title": "Cargo Atlantic Trader",
            "say": "AYA, montre le cargo Atlantic Trader.",
            "reply": "« MV Atlantic Trader (IMO 9876543), en attente de dédouanement à Vridi. Voir le PV douanes lié ? »",
            "screen": "Zoom carte Abidjan, pin AIS du cargo allumé, vignette webcam APM Apapa.",
            "plan_b": "Carte Stratégie → clic sur le pin vert « MV Atlantic Trader » → drawer fiche cargo.",
        },
        {
            "id": "S1.6",
            "title": "Situation au port",
            "say": "AYA, montre la situation au port.",
            "reply": "« Trafic maritime à destination d'Abidjan, zoom sur le cargo Nord. »",
            "screen": "Mission Control en mode live, panneau maritime ouvert, webcam APM Apapa Gate.",
            "plan_b": "Menu Monitor → bloc « Flux terrain » → vignette « APM Apapa Gate #1 ».",
        },
        {
            "id": "S1.7",
            "title": "Courrier de dédouanement",
            "say": "AYA, rédige le courrier de dédouanement pour Atlantic Trader.",
            "reply": "« Brouillon prêt. Validation advisory requise. »",
            "screen": "Drawer brouillon courrier prérempli — destinataire DGD Abidjan, refs projet et PV.",
            "plan_b": "Drawer Brouillons → « Nouveau courrier » → template « Atlantic Trader ».",
        },
    ],
)

TRANSITION = (
    "Transition — Vers la Rencontre Préfet Nawa",
    [
        {
            "id": "T.1",
            "title": "Prochain rendez-vous",
            "say": "AYA, quel est mon prochain rendez-vous ?",
            "reply": "« Prochain rendez-vous : Rencontre Préfet Nawa, 11:00, Soubré. »",
            "screen": "Sidebar Agenda ouverte, prochain rendez-vous mis en évidence.",
            "plan_b": "Sidebar → onglet Agenda → premier RDV listé (Rencontre Préfet Nawa).",
        },
    ],
)

SCENARIO_2 = (
    "Scénario 2 — Préfet Nawa & arbitrage cacao",
    [
        {
            "id": "S2.1",
            "title": "Résumé rapport Préfet",
            "say": "AYA, donne-moi le résumé du rapport préfet.",
            "reply": "« Synthèse rapport Préfet Nawa : cacao, diversification, infrastructures — citations RAG. »",
            "screen": "Synthèse markdown inline dans le chat AYA, citations cliquables.",
            "plan_b": "Quick Panel → Documents → « Rapport Préfet Nawa » → onglet Synthèse.",
        },
        {
            "id": "S2.2",
            "title": "Préconisations cacao",
            "say": "AYA, donne-moi des préconisations sur le cacao.",
            "reply": "« Trois options chiffrées : transformation locale, coopérative, partenariat public-privé. »",
            "screen": "Vue Décisions, package « Diversification cacao », options A / B / C avec confiance.",
            "plan_b": "Voix uniquement — en cas d'échec, reformuler « préconisations cacao » dans le Quick Panel.",
        },
        {
            "id": "S2.3",
            "title": "Rapport complet",
            "say": "AYA, génère le rapport complet.",
            "reply": "« Rapport de diversification cacao généré, prêt pour validation advisory. »",
            "screen": "Drawer aperçu rapport stratégique (~12 pages), bouton de téléchargement signé.",
            "plan_b": "Drawer Brouillons → « Rapport stratégique ».",
        },
        {
            "id": "S2.4",
            "title": "Patch ordre du jour",
            "say": "AYA, ajoute le point cacao à l'ordre du jour.",
            "reply": "« Je propose d'ajouter le point cacao à l'ordre du jour de la Rencontre Préfet Nawa. Validation requise. »",
            "screen": "Drawer patch d'ordre du jour, bannière orange « Modification ODJ proposée · AYA ».",
            "plan_b": "Sidebar Agenda → meeting Préfet Nawa → ajouter un point d'ordre du jour « Cacao ».",
        },
        {
            "id": "S2.5",
            "title": "Validation du patch",
            "say": "Oui, valide.",
            "reply": "« Ordre du jour mis à jour, point cacao ajouté avec traçabilité advisory. »",
            "screen": "Bannière retirée, badge « Ajouté par AYA » sur le point cacao, agenda à jour.",
            "plan_b": "Cliquer le bouton de coche « ✓ » dans la proposition AYA.",
        },
        {
            "id": "S2.6",
            "title": "Démarrer la réunion",
            "say": "AYA, démarre la réunion.",
            "reply": "« Je démarre la réunion Rencontre Préfet Nawa. Mode live — chaque arbitrage sera loggé. »",
            "screen": "Mission Room live, ordre du jour vertical, chrono lancé.",
            "plan_b": "Sidebar → Mission Room live → bouton « Démarrer la réunion ».",
        },
        {
            "id": "S2.7",
            "title": "Décision Option B",
            "say": "AYA, décide option B.",
            "reply": "« Décision loggée : option B — diversification anacarde, alignement Banque mondiale, EUDR. »",
            "screen": "Registre arbitrages à jour, nouvelle décision liée à la réunion.",
            "plan_b": "Sidebar Arbitrages → « Nouvelle décision » → choisir option B.",
        },
    ],
)

SECTIONS = [SCENARIO_1, TRANSITION, SCENARIO_2]

FOOTER_NOTES = [
    "Hard reload (Cmd / Ctrl + Shift + R) avant la démo pour purger tout état résiduel.",
    "predemo_reset.sh lancé à H-30 — états awaiting / current_meeting nettoyés.",
    "Pas de wake-word côté client : utiliser le bouton « Parler à AYA » ou le Quick Panel.",
    "En cas de doute pendant la scène : présenter directement en mode Quick Panel texte (même résolveur, même effet).",
]


# ---------------------------------------------------------------------------
# python-docx helpers
# ---------------------------------------------------------------------------


def _set_run(run, *, size_pt=BODY_PT, bold=False, italic=False, color=TEXT):
    run.font.name = FONT_FAMILY
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
        rFonts.set(qn(f"w:{attr}"), FONT_FAMILY)
    run.font.size = Pt(size_pt)
    run.bold = bold
    run.italic = italic
    if color is not None:
        run.font.color.rgb = color


def _tighten(paragraph, *, before=0, after=2, line=1.15):
    pf = paragraph.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line


def _add_paragraph(document, text="", *, size_pt=BODY_PT, bold=False, italic=False,
                   color=TEXT, before=0, after=2, line=1.15):
    p = document.add_paragraph()
    _tighten(p, before=before, after=after, line=line)
    if text:
        run = p.add_run(text)
        _set_run(run, size_pt=size_pt, bold=bold, italic=italic, color=color)
    return p


def _add_label_value(document, label, value, *, value_bold=False, value_italic=False,
                     value_color=TEXT):
    p = document.add_paragraph()
    _tighten(p, before=0, after=1, line=1.15)
    lab = p.add_run(f"{label} ")
    _set_run(lab, size_pt=BODY_PT, bold=True, color=DIM)
    val = p.add_run(value)
    _set_run(val, size_pt=BODY_PT, bold=value_bold, italic=value_italic, color=value_color)
    return p


def _add_horizontal_rule(document):
    p = document.add_paragraph()
    _tighten(p, before=2, after=4)
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "4")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "BFC6D1")
    pBdr.append(bottom)
    pPr.append(pBdr)


def _set_margins(section, *, top=1.6, bottom=1.6, left=1.8, right=1.8):
    section.top_margin = Cm(top)
    section.bottom_margin = Cm(bottom)
    section.left_margin = Cm(left)
    section.right_margin = Cm(right)


def _style_heading(document, style_name, size_pt, color=ACCENT, bold=True):
    style = document.styles[style_name]
    style.font.name = FONT_FAMILY
    style.font.size = Pt(size_pt)
    style.font.bold = bold
    if color is not None:
        style.font.color.rgb = color


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build_document(output_path: Path) -> Path:
    document = Document()

    base_style = document.styles["Normal"]
    base_style.font.name = FONT_FAMILY
    base_style.font.size = Pt(BODY_PT)
    base_style.font.color.rgb = TEXT

    _style_heading(document, "Title", TITLE_PT, color=ACCENT, bold=True)
    _style_heading(document, "Heading 1", TITLE_PT, color=ACCENT, bold=True)
    _style_heading(document, "Heading 2", H2_PT, color=ACCENT, bold=True)
    _style_heading(document, "Heading 3", H3_PT, color=TEXT, bold=True)

    for section in document.sections:
        _set_margins(section)

    title = document.add_heading("SENTINEL-CI — Carte de trame VP · 25 mai 2026", level=1)
    _tighten(title, before=0, after=4)

    sub = document.add_paragraph()
    _tighten(sub, before=0, after=2)
    r1 = sub.add_run("URL prod : ")
    _set_run(r1, size_pt=SMALL_PT, bold=True, color=DIM)
    r2 = sub.add_run(PROD_URL)
    _set_run(r2, size_pt=SMALL_PT, color=TEXT)

    sub2 = document.add_paragraph()
    _tighten(sub2, before=0, after=6)
    r3 = sub2.add_run(PROFIL)
    _set_run(r3, size_pt=SMALL_PT, italic=True, color=DIM)

    pre_h = document.add_paragraph()
    _tighten(pre_h, before=0, after=2)
    rh = pre_h.add_run("Mode d'emploi (3 lignes)")
    _set_run(rh, size_pt=BODY_PT, bold=True, color=ACCENT)

    for line in PREAMBLE:
        bullet = document.add_paragraph(style="List Bullet")
        _tighten(bullet, before=0, after=1)
        run = bullet.add_run(line)
        _set_run(run, size_pt=BODY_PT, color=TEXT)

    _add_horizontal_rule(document)

    for idx, (section_title, steps) in enumerate(SECTIONS):
        h2 = document.add_heading(section_title, level=2)
        _tighten(h2, before=6 if idx > 0 else 0, after=3)

        for step in steps:
            h3 = document.add_heading(f"{step['id']} — {step['title']}", level=3)
            _tighten(h3, before=4, after=2)

            say_p = document.add_paragraph()
            _tighten(say_p, before=0, after=1)
            lab = say_p.add_run("À dire : ")
            _set_run(lab, size_pt=BODY_PT, bold=True, color=DIM)
            quote = say_p.add_run(f"« {step['say']} »")
            _set_run(quote, size_pt=BODY_PT, bold=True, color=TEXT)

            _add_label_value(document, "AYA répond :", step["reply"], value_italic=True)
            _add_label_value(document, "À l'écran :", step["screen"])
            _add_label_value(document, "Plan B clic :", step["plan_b"], value_color=DIM)

    _add_horizontal_rule(document)

    foot_h = document.add_paragraph()
    _tighten(foot_h, before=4, after=2)
    rf = foot_h.add_run("Garde-fous présentateur")
    _set_run(rf, size_pt=BODY_PT, bold=True, color=ACCENT)

    for line in FOOTER_NOTES:
        bullet = document.add_paragraph(style="List Bullet")
        _tighten(bullet, before=0, after=1)
        run = bullet.add_run(line)
        _set_run(run, size_pt=SMALL_PT, color=TEXT)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output_path))
    return output_path


def main(argv: list[str]) -> int:
    out = Path(argv[1]).resolve() if len(argv) > 1 else DEFAULT_OUTPUT
    written = build_document(out)
    print(f"Wrote {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
