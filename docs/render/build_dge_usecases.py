# -*- coding: utf-8 -*-
"""Document DGE (FR) — Datategy : acteur IA souverain francilien, cas d'usage et cohérence du socle."""
import os
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import dge_diagrams as dgd

HERE = os.path.dirname(os.path.abspath(__file__))
DIAG = os.path.join(HERE, "assets", "diagrams")
SCREENS = os.path.join(HERE, "assets", "screens")
LOGO = os.path.join(HERE, "assets", "logo_datategy.png")
OUT = os.path.join(HERE, "out", "Datategy-DGE-Cas-d-usage-IA-souveraine.docx")


def C(h):
    return RGBColor.from_string(h)

NAVY = C("0B2545"); BLUE = C("2D6CDF"); GREEN = C("0E8F62"); AMBER = C("B45309")
PURPLE = C("6D28D9"); INK = C("151A23"); MUT = C("596371")
WHITE = C("FFFFFF"); LINE = "D7DCE3"; PANEL = "F3F5F8"
TINT = {"BLUE": "E5EDFB", "GREEN": "E2F2EC", "AMBER": "F6ECE0", "NAVY": "E7ECF4", "PURPLE": "EFE8FB"}
BODY = "Arial"


def _runfmt(run, size, color, bold=False, italic=False, mono=False):
    run.font.name = "Consolas" if mono else BODY
    run.font.size = Pt(size); run.font.bold = bold; run.font.italic = italic
    run.font.color.rgb = color


def _shade(cell, hexfill):
    sh = OxmlElement("w:shd"); sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), hexfill)
    cell._tc.get_or_add_tcPr().append(sh)


def _cell_margins(cell, t=60, b=60, l=110, r=90):
    tcPr = cell._tc.get_or_add_tcPr(); m = OxmlElement("w:tcMar")
    for tag, v in (("top", t), ("bottom", b), ("start", l), ("end", r), ("left", l), ("right", r)):
        e = OxmlElement(f"w:{tag}"); e.set(qn("w:w"), str(v)); e.set(qn("w:type"), "dxa"); m.append(e)
    tcPr.append(m)


def _borders(table, color=LINE, sz=4):
    b = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}"); e.set(qn("w:val"), "single"); e.set(qn("w:sz"), str(sz))
        e.set(qn("w:space"), "0"); e.set(qn("w:color"), color); b.append(e)
    table._tbl.tblPr.append(b)


def _left_accent(cell, hexcolor, sz=30):
    tcPr = cell._tc.get_or_add_tcPr(); bd = OxmlElement("w:tcBorders")
    e = OxmlElement("w:left"); e.set(qn("w:val"), "single"); e.set(qn("w:sz"), str(sz))
    e.set(qn("w:space"), "0"); e.set(qn("w:color"), hexcolor); bd.append(e); tcPr.append(bd)


def _pbottom(p, color="C9D2DE", sz=6):
    pPr = p._p.get_or_add_pPr(); pb = OxmlElement("w:pBdr"); e = OxmlElement("w:bottom")
    e.set(qn("w:val"), "single"); e.set(qn("w:sz"), str(sz)); e.set(qn("w:space"), "4")
    e.set(qn("w:color"), color); pb.append(e); pPr.append(pb)


def _field(run, code, default=""):
    r = run._r
    for tag, attr, val in (("fldChar", "fldCharType", "begin"),):
        e = OxmlElement(f"w:{tag}"); e.set(qn(f"w:{attr}"), val); r.append(e)
    it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve"); it.text = code; r.append(it)
    sep = OxmlElement("w:fldChar"); sep.set(qn("w:fldCharType"), "separate"); r.append(sep)
    t = OxmlElement("w:t"); t.text = default; r.append(t)
    end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end"); r.append(end)


def h1(doc, text, color=NAVY):
    p = doc.add_heading(text, level=1)
    for r in p.runs:
        r.font.color.rgb = color; r.font.name = BODY
    _pbottom(p); return p


def h2(doc, text, color=BLUE):
    p = doc.add_heading(text, level=2)
    for r in p.runs:
        r.font.color.rgb = color; r.font.name = BODY
    return p


def para(doc, text, size=10.5, color=INK, bold=False, italic=False, before=3, after=4, spacing=1.14):
    p = doc.add_paragraph(); pf = p.paragraph_format
    pf.space_before = Pt(before); pf.space_after = Pt(after); pf.line_spacing = spacing
    r = p.add_run(text); _runfmt(r, size, color, bold=bold, italic=italic); return p


def runs_para(doc, parts, before=3, after=4, spacing=1.14, size=10.5):
    p = doc.add_paragraph(); pf = p.paragraph_format
    pf.space_before = Pt(before); pf.space_after = Pt(after); pf.line_spacing = spacing
    for text, bold, color in parts:
        _runfmt(p.add_run(text), size, color, bold=bold)
    return p


def bullet(doc, parts, size=10.5, before=1, after=1):
    p = doc.add_paragraph(style="List Bullet"); pf = p.paragraph_format
    pf.space_before = Pt(before); pf.space_after = Pt(after); pf.line_spacing = 1.12
    if isinstance(parts, str):
        parts = [(parts, False, INK)]
    for text, bold, color in parts:
        _runfmt(p.add_run(text), size, color, bold=bold)
    return p


def image(doc, name, width=16.5, caption=None, base=None):
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(5); p.paragraph_format.space_after = Pt(2)
    p.add_run().add_picture(os.path.join(base or DIAG, name), width=Cm(width))
    if caption:
        c = doc.add_paragraph(); c.alignment = WD_ALIGN_PARAGRAPH.CENTER
        c.paragraph_format.space_after = Pt(8)
        _runfmt(c.add_run(caption), 8.5, MUT, italic=True)


def callout(doc, title, body, accent, accent_hex, fill_hex, body_bold=False):
    t = doc.add_table(rows=1, cols=1); t.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = t.cell(0, 0); cell.width = Cm(17); _shade(cell, fill_hex)
    _left_accent(cell, accent_hex, sz=34); _cell_margins(cell, t=110, b=110, l=190, r=150)
    cell.text = ""; p = cell.paragraphs[0]; p.paragraph_format.space_after = Pt(2)
    _runfmt(p.add_run(title.upper()), 9, accent, bold=True, mono=True)
    p2 = cell.add_paragraph(); p2.paragraph_format.line_spacing = 1.16
    _runfmt(p2.add_run(body), 10.5, INK, bold=body_bold)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)
    return t


def fiche(doc, secteur, org, accent_hex, probleme, solution, resultat, mise=None):
    t = doc.add_table(rows=1, cols=1); t.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = t.cell(0, 0); cell.width = Cm(17); _shade(cell, "FFFFFF")
    _left_accent(cell, accent_hex, sz=32); _cell_margins(cell, t=80, b=80, l=170, r=140)
    cell.text = ""
    p = cell.paragraphs[0]; p.paragraph_format.space_after = Pt(2)
    _runfmt(p.add_run(secteur.upper() + "  "), 8.5, C(accent_hex), bold=True, mono=True)
    _runfmt(p.add_run(org), 11.5, INK, bold=True)
    lines = [("Besoin", probleme), ("Solution", solution), ("Résultat", resultat)]
    if mise:
        lines.append(("Mise en œuvre & HITL", mise))
    for lbl, txt in lines:
        bp = cell.add_paragraph(); bp.paragraph_format.space_before = Pt(2); bp.paragraph_format.line_spacing = 1.12
        _runfmt(bp.add_run(f"{lbl} — "), 9.5, C(accent_hex), bold=True)
        _runfmt(bp.add_run(txt), 9.5, MUT)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)
    return t


def cap_card(doc, family, brand, accent, accent_hex, fill_hex, mission, resp, message):
    t = doc.add_table(rows=1, cols=1); t.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = t.cell(0, 0); cell.width = Cm(17); _shade(cell, fill_hex)
    _left_accent(cell, accent_hex, sz=34); _cell_margins(cell, t=90, b=90, l=190, r=150)
    cell.text = ""
    p = cell.paragraphs[0]; p.paragraph_format.space_after = Pt(1)
    _runfmt(p.add_run(family.upper() + "   "), 9, accent, bold=True, mono=True)
    _runfmt(p.add_run(brand), 11.5, INK, bold=True)
    mp = cell.add_paragraph(); mp.paragraph_format.space_before = Pt(3); mp.paragraph_format.line_spacing = 1.14
    _runfmt(mp.add_run("Mission — "), 9.5, accent, bold=True)
    _runfmt(mp.add_run(mission), 9.5, INK)
    rp = cell.add_paragraph(); rp.paragraph_format.space_before = Pt(2); rp.paragraph_format.line_spacing = 1.14
    _runfmt(rp.add_run("Responsabilités — "), 9.5, accent, bold=True)
    _runfmt(rp.add_run(resp), 9.5, MUT)
    msgp = cell.add_paragraph(); msgp.paragraph_format.space_before = Pt(3); msgp.paragraph_format.line_spacing = 1.14
    _runfmt(msgp.add_run(message), 9.8, INK, italic=True)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)
    return t


def matrix(doc, rows):
    t = doc.add_table(rows=1, cols=4); t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.allow_autofit = False; _borders(t, LINE, 4)
    headers = ["Secteur · Organisation", "Cas d'usage", "Capacité IA", "Apport / résultat"]
    for j, htxt in enumerate(headers):
        _shade(t.cell(0, j), "0B2545"); _cell_margins(t.cell(0, j))
        cc = t.cell(0, j); cc.text = ""; pp = cc.paragraphs[0]
        _runfmt(pp.add_run(htxt), 9, WHITE, bold=True)
    for i, (org, uc, cap, res) in enumerate(rows):
        r = t.add_row(); fill = "FFFFFF" if i % 2 == 0 else PANEL
        for j, (val, col, bold) in enumerate([(org, INK, True), (uc, MUT, False), (cap, INK, False), (res, INK, True)]):
            c = r.cells[j]; _shade(c, fill); _cell_margins(c)
            c.text = ""; pp = c.paragraphs[0]; pp.paragraph_format.line_spacing = 1.08
            pp.paragraph_format.space_before = Pt(1); pp.paragraph_format.space_after = Pt(1)
            _runfmt(pp.add_run(val), 8.6, col, bold=bold)
    widths = (4.4, 5.8, 3.2, 3.6)
    for r in t.rows:
        for j, wv in enumerate(widths):
            r.cells[j].width = Cm(wv)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def shelf_table(doc, rows):
    t = doc.add_table(rows=1, cols=3); t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.allow_autofit = False; _borders(t, LINE, 4)
    for j, htxt, fillc in ((0, "Système (sur étagère)", "B45309"), (1, "Cas d'usage", "0B2545"),
                           (2, "Enjeux data & IA couverts", "0B2545")):
        _shade(t.cell(0, j), fillc); _cell_margins(t.cell(0, j))
        cc = t.cell(0, j); cc.text = ""; _runfmt(cc.paragraphs[0].add_run(htxt), 9, WHITE, bold=True)
    for i, (sysn, uc, stakes) in enumerate(rows):
        r = t.add_row(); fill = "FFFFFF" if i % 2 == 0 else PANEL
        for j, (val, col, bold) in enumerate([(sysn, INK, True), (uc, MUT, False), (stakes, MUT, False)]):
            c = r.cells[j]; _shade(c, fill); _cell_margins(c)
            c.text = ""; pp = c.paragraphs[0]; pp.paragraph_format.line_spacing = 1.08
            pp.paragraph_format.space_before = Pt(1); pp.paragraph_format.space_after = Pt(1)
            _runfmt(pp.add_run(val), 8.6, col, bold=bold)
    widths = (4.4, 5.8, 6.8)
    for r in t.rows:
        for j, wv in enumerate(widths):
            r.cells[j].width = Cm(wv)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def build():
    dgd.dge_socle(); dgd.dge_canonical(); dgd.dge_hierarchy(); dgd.dge_sovereign()
    dgd.dge_pluralite(); dgd.dge_papai(); dgd.dge_edge(); dgd.dge_method(); dgd.dge_translation(); dgd.dge_carakai()
    doc = Document()
    normal = doc.styles["Normal"]; normal.font.name = BODY; normal.font.size = Pt(10.5)
    normal.font.color.rgb = INK; normal.paragraph_format.space_after = Pt(4); normal.paragraph_format.line_spacing = 1.14
    for lvl, sz, col in (("Heading 1", 16, NAVY), ("Heading 2", 12.5, BLUE)):
        st = doc.styles[lvl]; st.font.name = BODY; st.font.size = Pt(sz); st.font.bold = True
        st.font.color.rgb = col; st.paragraph_format.space_before = Pt(12 if lvl == "Heading 1" else 8)
        st.paragraph_format.space_after = Pt(4); st.paragraph_format.keep_with_next = True

    sec = doc.sections[0]
    sec.page_width = Cm(21.0); sec.page_height = Cm(29.7)
    sec.top_margin = sec.bottom_margin = Cm(1.9); sec.left_margin = sec.right_margin = Cm(2.0)
    sec.header_distance = Cm(1.1); sec.footer_distance = Cm(1.1)
    # pas d'en-tête / pied de page sur la couverture
    sec.different_first_page_header_footer = True
    content_w = Cm(17.0)  # largeur utile (21 - 2*2)
    # en-tête : petit logo Datategy à gauche
    hdr = sec.header; hdr.is_linked_to_previous = False
    hp = hdr.paragraphs[0]; hp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    hp.paragraph_format.space_after = Pt(2)
    hp.add_run().add_picture(LOGO, height=Cm(0.62))
    _pbottom(hp, "D7DCE3", 4)
    # pied de page : « Confidentiel » à gauche, numéro de page à droite (table sans bordures)
    f = sec.footer; f.is_linked_to_previous = False
    ftab = f.add_table(rows=1, cols=2, width=content_w); ftab.allow_autofit = False
    lc = ftab.cell(0, 0); rc = ftab.cell(0, 1); lc.width = Cm(8.5); rc.width = Cm(8.5)
    lp = lc.paragraphs[0]; lp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _runfmt(lp.add_run("Confidentiel"), 8, MUT)
    rp = rc.paragraphs[0]; rp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _runfmt(rp.add_run("Page "), 8, MUT)
    pn = rp.add_run(); _runfmt(pn, 8, MUT); _field(pn, "PAGE", "1")
    # supprime le paragraphe vide laissé au-dessus de la table du pied de page
    _empty = f.paragraphs[0]; _empty._element.getparent().remove(_empty._element)
    # mise à jour automatique des champs (sommaire, pagination) à l'ouverture dans Word
    upd = OxmlElement("w:updateFields"); upd.set(qn("w:val"), "true")
    doc.settings.element.append(upd)

    # ============================================ COUVERTURE
    for _ in range(2):
        doc.add_paragraph()
    cov = doc.add_paragraph(); cov.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cov.add_run().add_picture(LOGO, width=Cm(4.8))
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before = Pt(24)
    _runfmt(p.add_run("INTELLIGENCE ARTIFICIELLE SOUVERAINE  ·  ÎLE-DE-FRANCE"), 11, BLUE, bold=True, mono=True)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before = Pt(10)
    _runfmt(p.add_run("Datategy — Cas d'usage IA et cohérence du socle produit"), 23, NAVY, bold=True)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _runfmt(p.add_run("Une plateforme souveraine unique, papAI — des données aux systèmes intelligents gouvernés"), 13, INK)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before = Pt(26)
    _runfmt(p.add_run("Document préparé pour la Direction Générale des Entreprises (DGE)"), 12, MUT, bold=True)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _runfmt(p.add_run("Juin 2026"), 11, MUT)
    doc.add_page_break()

    # ============================================ SOMMAIRE (champ à mettre à jour dans Word)
    ptoc = doc.add_paragraph(); ptoc.paragraph_format.space_after = Pt(6)
    _runfmt(ptoc.add_run("Sommaire"), 15, NAVY, bold=True); _pbottom(ptoc, "C9D2DE", 6)
    toc_p = doc.add_paragraph()
    toc_run = toc_p.add_run()
    _field(toc_run, 'TOC \\o "1-2" \\h \\z \\u',
           "Sommaire — clic droit › « Mettre à jour les champs » (ou F9) pour générer la table des matières.")
    doc.add_page_break()

    para(doc,
         "Ce document suit un fil de lecture en quatre temps : la structure et la vision de Datategy ; "
         "un portefeuille de cas d'usage qui saisit le métier par des capacités proches de besoins "
         "concrets ; l'environnement produit qui justifie la position d'éditeur et la livraison en "
         "confiance, gouvernance et souveraineté ; enfin, la pérennité des systèmes dans un écosystème "
         "en mouvement.",
         italic=True, color=MUT, before=0, after=8)

    # ============================================ 1. Structure & vision globale
    h1(doc, "1.  Datategy — structure et vision globale")
    runs_para(doc, [
        ("Datategy ", True, NAVY),
        ("est une entreprise française d'intelligence artificielle, dont le siège est situé à ", False, INK),
        ("Paris (58 rue de Monceau, 75008), en Île-de-France", True, INK),
        (". Fondée en 2016, elle aide les organisations publiques et privées à exploiter leurs données "
         "et à déployer des modèles d'IA pour améliorer la décision et l'efficacité opérationnelle — "
         "en mode SaaS comme ", False, INK),
        ("on-premise (souverain)", True, INK), (".", False, INK),
    ])
    h2(doc, "Vision : une IA souveraine, spécialisée et frugale")
    runs_para(doc, [
        ("Datategy défend une trajectoire claire pour l'IA industrialisée en France : ", True, NAVY),
        ("passer de plateformes horizontales standardisées — dominées par quelques multinationales — "
         "à une IA souveraine, spécialisée (verticale) et frugale, au service des secteurs critiques.", False, INK),
    ])
    bullet(doc, [("Du générique au vertical — ", True, INK), ("une IA dédiée aux secteurs critiques : défense, banque & finance, industrie, santé, collectivités & villes intelligentes.", False, MUT)])
    bullet(doc, [("Souveraineté par l'infrastructure — ", True, INK), ("clouds libres et infrastructures maîtrisées (pendant matériel de l'open source logiciel), pour garder le contrôle des données et des modèles.", False, MUT)])
    bullet(doc, [("IA générative spécialisée, frugale et auditable — ", True, INK), ("industrialisation plus rapide et à moindre coût, avec explicabilité et hallucinations réduites (traduction spécialisée, synthèse d'information, simulation).", False, MUT)])
    bullet(doc, [("Ancrage académique & écosystème — ", True, INK), ("fondée sur l'excellence académique française et l'écosystème d'innovation, au service de la compétitivité nationale et du respect des normes européennes.", False, MUT)])

    h2(doc, "Repères")
    bullet(doc, [("Création 2016 ", True, INK), ("· une vingtaine de collaborateurs (dont plusieurs docteurs) · une base de clients et d'utilisateurs construite depuis l'origine.", False, MUT)])
    bullet(doc, [("Premier produit sur étagère dès 2016-2017 — OctoCity ", True, INK), ("(anti-fraude et gestion de flotte d'agents de contrôle pour les transports publics), avant l'industrialisation de la plateforme papAI.", False, MUT)])
    bullet(doc, [("Ancrage francilien ", True, INK), ("· présence internationale (Paris, et bureaux à l'étranger) au service de clients français et export.", False, MUT)])
    bullet(doc, [("Disponible en SaaS ou ", True, INK), ("on-premise / air-gap ", True, INK), ("— l'IA accessible techniquement et financièrement à toute taille d'organisation.", False, MUT)])
    h2(doc, "Souveraineté & confiance — labels et reconnaissances")
    matrix_simple = doc.add_table(rows=0, cols=2); matrix_simple.alignment = WD_TABLE_ALIGNMENT.CENTER
    matrix_simple.allow_autofit = False; _borders(matrix_simple, LINE, 4)
    labels = [
        ("French Tech", "Reconnaissance de l'écosystème d'innovation français."),
        ("Jeune Entreprise Innovante (JEI)", "Prix décerné par le ministère de l'Enseignement supérieur et de la Recherche."),
        ("Référencement UGAP", "Référencée et certifiée pour le marché public français."),
        ("AI Act européen", "Contributeur à la rédaction des règles de mise en œuvre de l'AI Act."),
        ("EU Trusted AI start-up", "Sélectionnée par l'Union européenne comme start-up de confiance en IA."),
        ("Reconnaissances", "Label IEEE (publications scientifiques) · Top 10 des fournisseurs d'IA en Europe (CIO) · prix Big Data Paris."),
    ]
    for i, (a, b) in enumerate(labels):
        r = matrix_simple.add_row(); fill = "FFFFFF" if i % 2 == 0 else PANEL
        for j, (val, col, bold, w) in enumerate([(a, INK, True, 5.0), (b, MUT, False, 12.0)]):
            c = r.cells[j]; _shade(c, fill); _cell_margins(c); c.width = Cm(w)
            c.text = ""; pp = c.paragraphs[0]; pp.paragraph_format.line_spacing = 1.1
            pp.paragraph_format.space_before = Pt(1); pp.paragraph_format.space_after = Pt(1)
            _runfmt(pp.add_run(val), 9.5, col, bold=bold)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    doc.add_page_break()

    # ============================================ 2. Portefeuille de cas d'usage
    h1(doc, "2.  Portefeuille de cas d'usage — le métier saisi par des capacités concrètes")
    para(doc,
         "Datategy adresse une large pluralité de secteurs, avec un ancrage marqué dans le secteur "
         "public et les grands acteurs souverains français. Les cas ci-dessous sont représentatifs ; "
         "des déploiements internationaux complètent ces références.")
    runs_para(doc, [
        ("Le parti pris de lecture : ", True, NAVY),
        ("entrer par le besoin métier — maintenance, conformité, fraude, parcours patient, traduction "
         "technique, intelligence documentaire — et non par la technologie. Chaque référence répond à un "
         "enjeu opérationnel réel, avec des résultats concrets et mesurables.", False, INK),
    ])
    image(doc, "dge-pluralite.png", width=16.0,
          caption="Une pluralité de secteurs et de besoins métier — adressés par des capacités IA déployables.")
    h2(doc, "Panorama des cas d'usage")
    matrix(doc, [
        ("Ferroviaire — SNCF", "Détection de substances dangereuses (amiante) sur le terrain — vision + application pour les agents", "Vision par ordinateur · app terrain", "très haute fiabilité sur les classes critiques · forte baisse des analyses labo"),
        ("Autoroutes (France) — APRR", "Détection de fissures et de défauts de chaussée / d'ouvrages par vision", "Vision par ordinateur", "détection de corrosion & défauts par vision"),
        ("Mobilité (IDF) — RATP", "Lutte contre la fraude : ciblage et itinéraires de contrôle (OctoCity)", "ML d'optimisation + app web/mobile", "hausse marquée des contraventions sur les premiers mois"),
        ("Mobilité (IDF) — TICE (Évry-Courcouronnes)", "OctoCity : anti-fraude et gestion de flotte d'agents de contrôle (1er produit sur étagère, depuis 2017)", "ML prédictif · app mobile · back-office recouvrement", "hausse de la validation · itinéraires nettement plus efficaces"),
        ("Ens. sup. (IDF) — Univ. Évry / Paris-Saclay", "Mesure d'occupation des locaux en temps réel (sécurité, évacuation)", "Vision / capteurs", "haute précision en temps réel"),
        ("Santé publique — CH de Chalon-sur-Saône", "Optimisation du parcours patient (scoring, alertes cliniques)", "ML prédictif / scoring", "détection précoce des comorbidités · alertes utiles"),
        ("Infrastructure publique (Grand Paris) — Société des grands projets · consortium piloté par Explolab (CarakAI)", "Contrôle automatisé de la caractérisation/classification des déblais et de la conformité réglementaire (choix des exutoires)", "Agent IA · document intelligence · contrôle réglementaire", "conformité juridique & maîtrise des coûts"),
        ("Énergie — ENGIE", "Prévision de la consommation d'énergie et détection d'anomalies", "Prévision / ML", "estimations fiables · prévention de l'attrition"),
        ("Agroalimentaire — Le Gouessant (coopérative agricole)", "Prévision (séries temporelles) de la production d'élevage ; modèles surrogate pour calibrer des modèles d'expériences biologiques (fermentation)", "Forecasting · modèles surrogate · papAI SaaS", "papAI en SaaS · déployé via partenaire (ADBI)"),
        ("Justice & conformité — JusticeIA", "Analyse réglementaire et lutte anti-blanchiment", "NLP / NER", "détection d'anomalies réglementaires (LCB-FT)"),
        ("Secteur public — DGPR (Prévention des risques)", "Analyse documentaire réglementaire et projets data/IA de prévention des risques", "Document intelligence · ML", "analyse réglementaire de prévention des risques"),
        ("Collectivité (IDF) — Ville de Chatou", "Suivi énergétique multi-bâtiments, tableau de bord et alertes", "ETL · dashboards · RAG documentaire", "pilotage énergétique & alertes en continu"),
        ("Défense — DGA (Direction générale de l'armement)", "Reconstitution de la MCO (maintien en condition opérationnelle) à partir de carnets de bord manuscrits interprétés par IA — alimente le fleet management", "Reconnaissance d'écriture · document intelligence · fleet management", "carnets manuscrits structurés → données de MCO"),
        ("Énergie — Gestionnaire de réseau de transport d'électricité (référence anonymisée)", "Scoring technique d'actifs et aide à la maintenance du réseau", "Scoring ML · optimisation", "priorisation de la maintenance du réseau"),
        ("Mobilité (IDF) — Heex Technologies", "Données de véhicules autonomes : déclenchement intelligent à la périphérie (edge)", "ML edge · filtrage de données", "Pack IA Région Île-de-France"),
        ("Énergie fluviale — Producteur hydroélectrique (référence anonymisée)", "Optimisation d'infrastructure et maintenance prédictive", "ML prédictif · optimisation", "anticipation des pannes & optimisation"),
        ("Automobile (IDF) — Renault Group", "Traduction de documentation technique (Translation Suite, contrôle qualité normé)", "IA agentique + RAG souverain · QA SAE J2450", "qualité normée & auditable · fort ROI"),
        ("Automobile (IDF) — Renault Group", "Linéarisation de manuels multimodaux pour assistant vocal (Narration Suite)", "IA agentique multimodale · reward routing", "manuels → texte exploitable, décisions auditables"),
        ("IT / Finance (groupe Renault) — Mobilize Financial Services", "AIOps : prévention prédictive des incidents IT (timeouts critiques) à partir des logs et métriques", "AIOps · séries temporelles · BigData/Spark · explicabilité", "supervision IT proactive · anticipation des pics d'erreurs"),
        ("Ferroviaire — Grand équipementier (référence anonymisée)", "Gestion documentaire technique et assistant expert", "RAG / knowledge", "accès expert accéléré à la documentation"),
        ("Industrie — Andritz (opérations France)", "Capture de connaissances expertes et intelligence documentaire technique (maintenance, multilingue)", "Knowledge capture · RAG · agents", "expertise capitalisée & maintenance assistée"),
        ("Banque — Société Générale", "Intelligence documentaire et lutte contre la fraude documentaire (chèques, pièces justificatives)", "RAG · vision · OCR · détection de fraude", "détection de fraude documentaire"),
        ("Finance / justice commerciale — Infogreffe", "Scoring de risque et de performance financière des entreprises par apprentissage automatique (bilans, liasses fiscales, ratios) — explicable et auditable", "Machine Learning · scoring · explicabilité", "sur étagère · redéployable banque"),
        ("Juridique (souverain) — Metaketing", "Assistant juridique on-premise (habilitations, auditabilité)", "RAG propriétaire (HAH-RAG) + OCR/VLM", "hallucinations réduites · explicabilité"),
        ("Aéronautique — Airbus", "Analytique et IA sur données industrielles", "ML / data science", "exploitation analytique de données industrielles"),
        ("Edge AI / MLOps (France) — HyperOpenX", "Orchestration souveraine portable (OpenSVC), inférence edge multi-sites et apprentissage fédéré", "Edge AI · MLOps · apprentissage fédéré", "edge AI & apprentissage fédéré souverain (2024-2025)"),
    ])

    h2(doc, "Cas d'usage illustrés")
    runs_para(doc, [
        ("Les fiches qui suivent se lisent comme une progression, pas comme un catalogue : ", True, NAVY),
        ("de la vision sur le terrain à la gestion de flotte et au maintien en condition opérationnelle, "
         "puis à l'intelligence documentaire et réglementaire souveraine, aux Suites de connaissance et "
         "de langage, et enfin à la prévision au service de la décision publique. À chaque étape, le même "
         "socle papAI décliné à un métier différent.", False, INK),
    ])

    runs_para(doc, [
        ("Vision & inspection sur le terrain — détecter, diagnostiquer, prioriser. ", True, NAVY),
        ("Deux références de vision par ordinateur où l'IA fiabilise un diagnostic terrain et concentre "
         "l'effort humain là où il compte vraiment.", False, INK)], before=4, after=2)
    image(doc, "uc-sncf.png", base=SCREENS, width=16.5,
          caption="Ferroviaire — diagnostic par vision et pilotage de la maintenance des wagons.")
    fiche(doc, "Ferroviaire · SNCF", "Maintenance prédictive des wagons de marchandises", "2D6CDF",
          "Détection visuelle de la présence d'amiante sur les wagons ; processus d'analyse en laboratoire long et coûteux.",
          "Outil de diagnostic par vision pour identifier les équipements défectueux et piloter les interventions de maintenance.",
          "Très haut niveau de fiabilité sur les classes de sécurité critiques ; une part importante du stock de pièces évite une analyse en laboratoire.",
          mise="Application terrain pour les agents, formée à la détection ; les cas douteux ou critiques restent confirmés par l'expert / l'analyse en laboratoire en second recours.")
    image(doc, "uc-sncf-system.png", base=SCREENS, width=16.5,
          caption="Le système réel (projet IAmiante) — application terrain « Diagnostic Amiante » et chaîne de vision (extraction de caractéristiques → CNN → classifieur XGBoost → score), hébergée en souverain (OVH).")

    image(doc, "uc-aprr.png", base=SCREENS, width=16.0,
          caption="Inspection d'infrastructure routière (APRR) — captation terrain des glissières/barrières et classification de l'état (corrosion) par vision.")
    fiche(doc, "Autoroutes · APRR (France)", "Détection de la corrosion des barrières d'autoroute par vision", "B45309",
          "Repérer la corrosion des glissières et barrières sur le réseau autoroutier ; inspections manuelles longues, coûteuses et difficiles à prioriser.",
          "Classification d'images par vision (architecture ResNet/CNN) sur papAI, avec préparation de jeux de données, entraînement spécialisé et suivi de performance.",
          "Maintenance mieux ciblée et préventive ; détection fiable de la corrosion sur de grands volumes d'images.",
          mise="Ateliers réguliers avec les experts maintenance APRR (workshops, validation des classifications) ; surveillance du modèle et réentraînement automatique à mesure que de nouvelles données arrivent.")

    runs_para(doc, [
        ("OctoCity — le premier produit sur étagère de Datategy (2016-2017). ", True, NAVY),
        ("Avant même papAI, Datategy a industrialisé OctoCity : une suite complète de lutte contre la "
         "fraude et de gestion de flotte d'agents de contrôle pour les transports publics. C'est le socle "
         "historique de notre expertise « fleet management » — planification, optimisation d'itinéraires, "
         "application mobile terrain et back-office de recouvrement. Déployée dès 2017 sur le réseau "
         "francilien TICE (Évry-Courcouronnes) et auprès de la RATP.", False, INK),
    ])
    image(doc, "uc-octocity-suite.png", base=SCREENS, width=16.5,
          caption="OctoCity — une suite logicielle de bout en bout : déploiement des agents → contrôle → verbalisation → back-office & recouvrement → paiement en ligne.")
    fiche(doc, "Mobilité · TICE (Évry-Courcouronnes, IDF) · RATP", "OctoCity — lutte anti-fraude & gestion de flotte d'agents de contrôle", "0E8F62",
          "Réduire une fraude pouvant atteindre 25-30 % des voyageurs ; planifier et cibler les interventions des équipes de contrôle, et fiabiliser le recouvrement.",
          "Plateforme d'analyse de flux à algorithme prédictif : prévision en temps réel des lieux/moments de contrôle, optimisation des itinéraires, application mobile (itinéraire, feuille d'activité, contrôle des titres) et interface de gestion jusqu'au recouvrement.",
          "TICE : hausse du taux de validation, itinéraires de contrôle nettement plus efficaces, recettes en hausse ; RATP : forte hausse des contraventions sur les premiers mois.",
          mise="Déploiement chez TICE dès 2017 ; l'IA cible les zones/créneaux, le contrôleur décide sur le terrain via l'app mobile, l'encadrement pilote l'activité et le recouvrement depuis le back-office.")
    image(doc, "uc-octocity-planning.png", base=SCREENS, width=16.5,
          caption="OctoCity — gestion des plannings et des rondes : itinéraires de contrôle optimisés visualisés sur carte selon les critères définis.")
    image(doc, "uc-octocity-backoffice.png", base=SCREENS, width=16.5,
          caption="OctoCity — back-office & recouvrement : tableau de bord du recouvrement financier, statistiques de contrôle et tendances de la fraude.")

    callout(doc, "Fil rouge — une même expertise de « fleet management » terrain",
            "La gestion de flotte d'agents de contrôle d'OctoCity (planification, itinéraires optimisés, "
            "app mobile de restitution, back-office et recouvrement) est la même brique que Datategy "
            "décline aujourd'hui pour la Société des grands projets (suivi et optimisation d'itinéraires, "
            "ex. transport des déblais), et qu'elle sait alimenter à partir de documents manuscrits "
            "interprétés par IA (missions, trajets, véhicules, kilométrage) — y compris pour des enjeux "
            "de maintien en condition opérationnelle (MCO).",
            GREEN, "0E8F62", TINT["GREEN"], body_bold=True)

    runs_para(doc, [
        ("MCO & maintenance prédictive des équipements critiques — un second fil rouge. ", True, NAVY),
        ("La même chaîne (structurer la donnée terrain, prévoir, expliquer, décider) sert le maintien en "
         "condition opérationnelle des équipements. papAI aide à prédire les besoins de maintenance pour "
         "maximiser la disponibilité des équipements critiques, en réduisant les pannes imprévues et les "
         "coûts associés grâce à une maintenance proactive. Plateforme généraliste, Datategy est "
         "particulièrement forte dans l'industrie.", False, INK),
    ])
    image(doc, "uc-mco-report.png", base=SCREENS, width=16.5,
          caption="Rapport d'analyse d'équipement généré par l'IA : score de santé, progression et prédiction du stade de défaillance, et recommandations de maintenance hiérarchisées (exemple sur données industrielles, généralisable).")
    runs_para(doc, [("Quatre expertises au cœur du MCO :", True, NAVY)], before=3, after=1)
    bullet(doc, [("OCR & retrieval de données multimodales — ", True, INK), ("extraction et structuration de documents et signaux hétérogènes (dont manuscrits) en vue de l'entraînement de modèles.", False, MUT)])
    bullet(doc, [("Orchestration de pipelines BigData — ", True, INK), ("ingestion et traitement de gros volumes de données techniques et de capteurs, à l'échelle.", False, MUT)])
    bullet(doc, [("Prévision sur séries temporelles (TimeSeries forecasting) — ", True, INK), ("et industrialisation de ces prévisionnistes en edge, au plus près des équipements.", False, MUT)])
    bullet(doc, [("Analyse de cause racine (root cause analysis) — ", True, INK), ("sur des équipements à très nombreux paramètres et, souvent, peu d'historique de pannes.", False, MUT)])
    runs_para(doc, [("Ce que cela produit côté industrie : ", True, NAVY),
                    ("prévoir les incidents et les interventions, anticiper les commandes de pièces (demand "
                     "forecasting) et organiser les itinéraires de livraison ; et, en fabrication comme en vie "
                     "opérationnelle, déterminer la combinaison de paramètres qui donne le meilleur résultat — "
                     "le « golden batch ». Datategy maîtrise par ailleurs la traduction de documentation "
                     "technique structurée (DITA/XML), essentielle à la maintenance multilingue.", False, INK)], before=3, after=3)
    callout(doc, "Fil rouge — du fleet management au MCO des équipements de défense",
            "La donnée terrain (carnets, capteurs, documents) structurée par OCR et retrieval, la prévision "
            "sur séries temporelles industrialisée en edge et l'analyse de cause racine convergent vers une "
            "même promesse : maximiser la disponibilité des équipements critiques. Une ambition forte pour "
            "la défense — MCO de flottes de véhicules (dont véhicules blindés) et de systèmes critiques — "
            "où la souveraineté et le fonctionnement déconnecté sont déterminants.",
            BLUE, "2D6CDF", TINT["BLUE"], body_bold=True)

    runs_para(doc, [
        ("AIOps — le MCO appliqué aux systèmes d'information (Mobilize Financial Services, groupe Renault). ", True, NAVY),
        ("La même logique de maintien en condition opérationnelle s'applique à l'IT : passer d'une gestion "
         "réactive à une gestion proactive des incidents. Datategy a appliqué avec succès une approche "
         "AIOps (IA pour l'exploitation IT) pour analyser et prévenir une erreur de timeout critique qui "
         "bloquait des traitements et impactait la disponibilité des services.", False, INK),
    ])
    image(doc, "uc-aiops-pipeline.png", base=SCREENS, width=16.5,
          caption="AIOps (MFS) — pipeline papAI sur les logs et métriques (nettoyage, séries temporelles, ML, prévision) : l'orchestration BigData au service de la prévention des incidents.")
    fiche(doc, "IT / Finance · Mobilize Financial Services (groupe Renault)", "AIOps — prévention prédictive des incidents IT (timeouts critiques)", "6D28D9",
          "Une erreur de timeout critique bloquait des traitements (batchs nocturnes, finalisation de financements) et se propageait en cascade via un ESB, dans un environnement IT complexe et hétérogène.",
          "Approche AIOps sur les logs et métriques (pile Elastic) : exploration, ingénierie de variables, prévision sur séries temporelles et explicabilité — pour anticiper les créneaux à risque.",
          "Passage d'une supervision réactive à une supervision proactive : bonne anticipation des pics d'erreurs et ajustement de la surveillance IT.",
          mise="papAI déployé en souverain sur l'infrastructure du groupe, traitement de plusieurs millions de lignes de logs (Spark) ; les prévisions et explications sont restituées aux équipes IT, qui gardent la décision d'intervention.")
    image(doc, "uc-aiops-forecast.png", base=SCREENS, width=14.5,
          caption="AIOps (MFS) — prévision des pics d'erreurs comparée au réel : le modèle anticipe les créneaux critiques pour déclencher une surveillance ciblée.")

    runs_para(doc, [
        ("Société des grands projets (Grand Paris) — CarakAI, une référence souveraine emblématique. ", True, NAVY),
        ("Pour le plus grand projet d'infrastructure d'Europe, Datategy a conçu CarakAI au sein du "
         "consortium piloté par Explolab (mandataire du marché SGP) : une plateforme dédiée à la "
         "caractérisation des terres excavées, qui contrôle la conformité réglementaire des déblais et "
         "oriente leur acheminement vers les bons exutoires. Elle s'intègre à la traçabilité des déblais "
         "du Grand Paris (outil T-REX) et illustre la convergence de nos savoir-faire : intelligence "
         "documentaire, contrôle réglementaire et optimisation d'itinéraires (fleet management).", False, INK),
    ])
    image(doc, "uc-carakai-app.png", base=SCREENS, width=12.5,
          caption="CarakAI — la plateforme dédiée de caractérisation des terres excavées conçue pour la Société des grands projets (Grand Paris).")
    image(doc, "dge-carakai.png", width=16.8,
          caption="CarakAI — la chaîne : bordereaux PDF → OCR → rapprochement au référentiel réglementaire → validation de l'exutoire (HITL) → sortie structurée et tracée.")
    fiche(doc, "Secteur public · SGP — Société des grands projets (Grand Paris, Île-de-France)", "CarakAI — caractérisation des déblais, conformité réglementaire & routage", "6D28D9",
          "Vérifier la correspondance entre les déblais (composés chimiques mesurés) et les exutoires autorisés, face à une réglementation à analyser vite, sur des volumes considérables de bordereaux.",
          "Plateforme dédiée : OCR des bordereaux → rapprochement des mesures avec les règles de conformité par composé → score d'admissibilité de l'exutoire → sortie structurée, intégrée à la traçabilité des déblais (T-REX).",
          "Contrôle réglementaire fiabilisé et tracé ; brique réutilisable pour tout suivi documentaire et toute optimisation d'itinéraires (appros, fret, déchets, douanes, BTP, défense).",
          mise="Plateforme connectée à la base de référence réglementaire ; la décision d'admission de l'exutoire est validée par l'humain, chaque étape étant tracée pour l'audit.")

    runs_para(doc, [
        ("Les références Renault sont des démonstrateurs de la plateforme — des Suites complètes, pas des agents isolés. ", True, NAVY),
        ("Elles montrent comment une même grammaire (connaissance, agents, workflow, contrôle qualité, "
         "revue humaine, reporting) se verticalise en systèmes prêts à produire de la valeur.", False, INK),
    ])
    image(doc, "dge-translation.png", width=16.8,
          caption="Translation Suite — pipeline gouverné en 5 phases : Préparation → Traduction agentique (invariants protégés) → QA agentique normée SAE J2450 → Revue humaine (HITL) → Audit déterministe & verdict de livraison, avec boucles de replay et d'enrichissement continu.")
    fiche(doc, "Automobile · Renault Group (Île-de-France)", "Translation Suite — traduction technique industrialisée et gouvernée", "2D6CDF",
          "Réduire les délais et coûts de traduction de documentation technique sans aucun compromis sur la qualité, et démontrer cette qualité de manière reproductible.",
          "Suite qui maîtrise tout le cycle de vie — ingestion, traduction agentique (RAG contextualisé), contrôle qualité agentique évalué selon la norme SAE J2450, quality gates et revue humaine, export prêt à publier et apprentissage continu — entièrement souveraine.",
          "Qualité mesurable et normée, équivalente voire supérieure à l'humain ; cycles de publication réduits (de semaines à jours, à l'échelle de dizaines de langues) et fort retour sur investissement.",
          mise="Évaluation normée (SAE J2450) avec preuve de qualité à chaque livraison ; les rares segments non tranchés par les agents partent en revue humaine, puis les corrections enrichissent la base. Innovation documentée (CIR/CII).")

    image(doc, "uc-renault-transcription.png", base=SCREENS, width=16.5,
          caption="Narration Suite (Renault) — transcription multimodale pilotée par une fonction de récompense auditable (« Reward Routing »), avec garde-fous et revue humaine.")
    fiche(doc, "Automobile · Renault Group (Île-de-France)", "Narration Suite — transformation de contenu multimodal", "6D28D9",
          "Convertir des documents multimodaux (texte structuré + images : schémas, écrans, pictogrammes) en un texte autonome, exploitable sans visuel (lecture, recherche, assistant vocal).",
          "Suite qui arbitre intelligemment qualité, coût et latence (« Reward Routing ») pour choisir la bonne stratégie de transcription, avec des garde-fous sur les champs critiques (valeurs, unités) et une traçabilité de bout en bout.",
          "Narration cohérente, exhaustive et intelligible ; chaque décision est justifiée, rejouable et auditable, pour un coût maîtrisé.",
          mise="Arbitrage auditable des stratégies de transcription, garde-fous priorisés sur les éléments critiques et calibration continue avec revue humaine (HITL). Innovation documentée (CIR/CII).")
    callout(doc, "Le client n'achète pas des agents isolés",
            "Il déploie des systèmes complets, prêts à produire de la valeur — Translation Suite, Narration "
            "Suite — assemblés sur le même socle souverain et opérés sous la même gouvernance. Leur qualité "
            "repose sur des innovations R&D documentées (CIR/CII) et, pour la traduction, sur une évaluation "
            "conforme à une norme industrielle (SAE J2450).",
            PURPLE, "6D28D9", TINT["PURPLE"], body_bold=True)

    runs_para(doc, [
        ("Connaissance souveraine & conformité — répondre juste, sous habilitation, de façon auditable. ", True, NAVY),
        ("Quand le corpus est sensible et les autorisations strictes, la même grammaire documentaire "
         "s'exécute entièrement dans le périmètre du client.", False, INK)], before=4, after=2)
    image(doc, "uc-metaketing.png", base=SCREENS, width=16.5,
          caption="Juridique souverain — assistant on-premise, isolé, habilité et auditable.")
    fiche(doc, "Juridique souverain · Metaketing", "Assistant juridique on-premise, isolé et gouverné", "0E8F62",
          "Répondre aux questions juridiques en respectant strictement habilitations et autorisations, avec auditabilité des réponses.",
          "Ingestion multimodale (OCR/VLM), vectorisation par catégorie de métiers, génération via un RAG propriétaire — entièrement on-premise.",
          "Réduction des hallucinations grâce à l'innovation HAH-RAG ; explicabilité et traçabilité des réponses.",
          mise="Habilitations appliquées à la source, métadonnées capturées pour l'auditabilité ; les réponses sensibles passent par une relecture experte avant usage.")

    runs_para(doc, [
        ("Prévision & scoring au service de la décision publique. ", True, NAVY),
        ("Sur des données cliniques comme sur des compteurs d'énergie, les mêmes briques de prévision et "
         "de scoring éclairent la décision d'un médecin ou d'un agent municipal — sans jamais s'y "
         "substituer.", False, INK)], before=4, after=2)
    image(doc, "uc-chalon.png", base=SCREENS, width=16.5,
          caption="Santé publique — optimisation du parcours patient : un déploiement mené par étapes maîtrisées.")
    fiche(doc, "Santé publique · CH Chalon-sur-Saône", "Optimisation du parcours patient via une IA dédiée", "B45309",
          "Réduire le taux de comorbidité, le temps de séjour et la surcharge de notifications inutiles, sans dégrader le travail des soignants.",
          "Scoring et analyse du parcours patient sur données cliniques (comptes rendus, dossier patient informatisé), capables de traiter de grands volumes hétérogènes.",
          "Détection précoce des risques de comorbidité, alertes cliniques utiles et meilleures conditions de travail des soignants (charge cognitive, stress).",
          mise="Démarche menée par étapes en 2025 (cadrage, prototype, mise en service) ; prérequis posés (accès données cliniques, collaboration clinicien·data scientist, formation des équipes), alertes calibrées pour éviter la « fatigue d'alarme ».")
    image(doc, "uc-chatou-energy.png", base=SCREENS, width=14.5,
          caption="Collectivité — suivi et prévision de la consommation d'énergie (réel vs prédit, avec intervalles de confiance) : la base du tableau de bord énergétique multi-bâtiments.")
    fiche(doc, "Collectivité · Ville de Chatou (Île-de-France)", "Pilotage énergétique multi-bâtiments par l'IA", "2D6CDF",
          "Suivre la consommation d'énergie d'un parc de bâtiments, détecter les anomalies et anticiper les dérives pour réduire les coûts.",
          "Collecte et structuration des données de compteurs (ETL), prévision de consommation et détection d'anomalies, tableau de bord et alertes — assistant documentaire associé.",
          "Pilotage énergétique en continu, anomalies signalées et prévisions exploitables pour la décision.",
          mise="Données de compteurs connectés ingérées et fiabilisées ; alertes et prévisions restituées dans un tableau de bord, l'agent municipal gardant la décision d'action.")

    h2(doc, "Des systèmes verticalisés, prêts à déployer (sur étagère)")
    runs_para(doc, [
        ("Au-delà des références nommées, Datategy a conçu et verticalisé des systèmes réutilisables, "
         "éprouvés sur des déploiements variés — en France comme à l'international. ", True, NAVY),
        ("Ils sont présentés ici par cas d'usage et par enjeux data/IA, indépendamment de toute "
         "référence : ce sont les Capabilities et Systems « sur étagère » qui, assemblés à partir de "
         "Skills communs, alimentent les Suites de la plateforme.", False, INK),
    ])
    image(doc, "uc-smart-parking.png", base=SCREENS, width=15.0,
          caption="Exemple de système sur étagère (référence anonymisée) — analyse de flux vidéo pour le stationnement intelligent : détection en temps réel des véhicules et des places libres/occupées (CCTV/fisheye, inférence edge).")
    shelf_table(doc, [
        ("Maintenance prédictive & MCO des équipements", "Anticiper pannes, interventions et commandes de pièces (demand forecasting) ; analyse de cause racine (innovation R&D propriétaire) ; « golden batch » (combinaison de paramètres optimale).", "Flux de capteurs massifs (IoT), événements rares (classes déséquilibrées), peu d'historique de pannes, nombreux paramètres, exécution edge / on-premise, faible empreinte énergétique."),
        ("Supervision & diagnostic technique", "Ingestion de capteurs industriels normalisés, détection d'anomalies, performance opérationnelle (énergie, forage).", "Formats industriels complexes (p. ex. WITS/WITSML), flux temps réel, intégration on-premise."),
        ("AIOps — supervision prédictive des systèmes d'information", "Analyse des logs et métriques (pile Elastic), prévision et prévention des incidents et timeouts, explicabilité — le MCO appliqué à l'IT.", "Très gros volumes de logs (BigData/Spark), séries temporelles, environnements hétérogènes (mainframe, ESB), temps réel, déploiement souverain."),
        ("Analyse de flux vidéo & ville intelligente", "Stationnement, trafic et occupation en temps réel à partir de flux vidéo (CCTV/RTSP) ; détection d'objets, allocation de ressources.", "Flux vidéo RTSP/CCTV à haute cadence, détection d'objets accélérée (edge/GPU), latence d'inférence maîtrisée, passage à l'échelle, déploiement souverain."),
        ("Inspection visuelle automatisée", "Classification de défauts (fissures de chaussée/ouvrages, corrosion, anomalies) sur images.", "Images haute résolution, rareté des annotations, défauts spécifiques au domaine, inférence sur site."),
        ("Vision embarquée terrain & edge AI (sécurité / conformité)", "Captation et analyse d'images sur le terrain (ex. détection de substances dangereuses), avec application mobile pour les agents.", "Inférence embarquée (edge), connectivité intermittente, conformité réglementaire et sécurité, MLOps souverain et montée en charge."),
        ("Veille & intelligence souveraine (OSINT)", "Surveillance de sources ouvertes, extraction d'entités, scoring de risque.", "Multilingue (dont arabe), sources non structurées en temps réel, souveraineté des données."),
        ("Scoring & risque (finance / assurance)", "Scoring de crédit/sinistres, risque/performance d'entreprises, tarification, prévention de l'attrition — redéployable d'un jeu de données à un autre.", "Données sensibles (PII), classes déséquilibrées, conformité (Solvabilité II / Bâle), explicabilité (SHAP/LIME)."),
        ("Lutte anti-fraude & supervision des transactions", "Détection d'anomalies et classification de fraude.", "Gros volumes en flux, déséquilibre, temps réel, reporting réglementaire (LCB-FT)."),
        ("Gestion de flotte terrain & optimisation d'itinéraires (fleet management)", "Planification d'équipes, optimisation d'itinéraires, application mobile terrain (feuille d'activité, contrôle) et back-office jusqu'au recouvrement — éprouvé avec OctoCity (transports), décliné au suivi d'itinéraires (déblais) et à la MCO à partir de documents manuscrits.", "Optimisation sous contraintes temps réel, géolocalisation, app mobile terrain (connectivité intermittente), interprétation de documents manuscrits, traçabilité et recouvrement."),
        ("Document intelligence multimodal", "RAG sur documents, plans et images hétérogènes (PDF, modèles 3D/BIM, photos).", "Formats hétérogènes, fusion multimodale, grands corpus, souveraineté."),
        ("Suivi documentaire & conformité réglementaire (routage)", "Caractérisation de bordereaux et documents, contrôle automatique de conformité, organisation et optimisation d'itinéraires (ex. terres excavées).", "Applicable aux approvisionnements, au fret et aux déchets — partout où une vérification réglementaire rapide est requise (douanes, BTP, défense). Rapports hétérogènes, règles évolutives, détection d'anomalies, traçabilité."),
        ("Assistant réglementaire / juridique souverain", "Questions-réponses sur corpus réglementaire, respect des habilitations, auditabilité.", "Textes structurés, multilingue, on-premise, réduction des hallucinations."),
        ("Traduction & rédaction technique multilingue", "Traduction de documentation, gestion de terminologie, cohérence inter-versions.", "Terminologie métier, langues peu dotées, cohérence à l'échelle."),
        ("Prévision de la demande / consommation", "Prévision (énergie, trafic, activité) et détection d'anomalies.", "Séries temporelles multi-sources, saisonnalité, alertes en temps réel."),
        ("Relation client & support augmentés", "Agent de support multilingue sur base de connaissances, suggestions et FAQ.", "Sources hétérogènes (CRM, wikis), RGPD, fraîcheur temps réel."),
    ])
    doc.add_page_break()

    # ============================================ 3. Environnement produit & cohérence
    h1(doc, "3.  Environnement produit, vision et cohérence du socle")
    runs_para(doc, [
        ("Ce chapitre explique ", True, NAVY),
        ("pourquoi ces cas d'usage peuvent être livrés avec confiance, gouvernance et souveraineté — "
         "et dans la durée. Datategy se positionne comme éditeur et producteur de systèmes IA viables "
         "dans le temps : une plateforme unifiée, une stratégie produit cohérente et une capitalisation "
         "progressive des capacités, plutôt qu'une succession de projets ad hoc.", False, INK),
    ])

    h2(doc, "Une plateforme souveraine unifiée — papAI")
    runs_para(doc, [
        ("Datategy ne juxtapose pas une multitude de projets IA indépendants : ", True, NAVY),
        ("l'entreprise industrialise une plateforme souveraine unique, papAI, capable de produire et "
         "d'opérer des systèmes intelligents réutilisables dans des secteurs très différents. Chaque cas "
         "d'usage présenté dans ce document est une déclinaison de ce même socle.", False, INK),
    ])
    para(doc,
         "papAI couvre la chaîne complète — collecte des données, orchestration des infrastructures, "
         "entraînement des modèles (MLOps, AutoML, fine-tuning), capitalisation des connaissances et "
         "déploiement de systèmes gouvernés. Elle se positionne comme une AI/Data Fabric : une "
         "plateforme scalable, hybride et ouverte, déployable en SaaS comme en on-premise / air-gap.")
    image(doc, "ui-connectors.png", base=SCREENS, width=16.5,
          caption="papAI — connecteurs natifs aux sources de données (bases SQL/NoSQL, fichiers, stockage objet, cloud) : la couche AI/Data Fabric.")

    h2(doc, "Une seule plateforme, des capacités activées progressivement")
    runs_para(doc, [
        ("Document Center et Agentium ne sont pas trois plateformes indépendantes. ", True, NAVY),
        ("Ce sont des capacités spécialisées de papAI. Concrètement, le client :", False, INK),
    ])
    bullet(doc, [("n'achète pas trois plateformes", True, INK), (" — une seule plateforme, papAI.", False, MUT)])
    bullet(doc, [("n'achète pas trois licences distinctes", True, INK), (" — une activation progressive des capacités.", False, MUT)])
    bullet(doc, [("n'installe pas trois environnements", True, INK), (" — un seul environnement à déployer et maintenir.", False, MUT)])
    bullet(doc, [("n'opère pas trois interfaces", True, INK), (" — une expérience utilisateur unifiée.", False, MUT)])
    bullet(doc, [("ne gère pas trois piles technologiques", True, INK), (" — un seul socle souverain à gouverner.", False, MUT)])
    image(doc, "dge-socle.png", width=16.5,
          caption="papAI — socle souverain commun ; Data, Knowledge et Decision Intelligence sont des capacités d'une même plateforme.")
    callout(doc, "La formulation à retenir",
            "papAI constitue le socle souverain commun de Datategy. Document Center et Agentium ne sont "
            "pas des plateformes distinctes mais des capacités spécialisées de papAI, partageant la même "
            "infrastructure, la même gouvernance, le même moteur d'orchestration, le même modèle de "
            "sécurité, la même couche d'observabilité et la même expérience utilisateur. Le client déploie "
            "une seule plateforme et active progressivement les capacités dont il a besoin.",
            NAVY, "0B2545", TINT["NAVY"], body_bold=True)

    h2(doc, "Trois capacités, un même socle")
    cap_card(doc, "papAI", "Data Intelligence", BLUE, "2D6CDF", TINT["BLUE"],
             "Transformer les données en actifs IA industrialisés.",
             "DataOps · AutoML · fine-tuning · Machine Learning · Deep Learning · MLOps · AI Services.",
             "Transformer les données en capacités IA exploitables.")
    cap_card(doc, "Document Center", "Knowledge Intelligence", GREEN, "0E8F62", TINT["GREEN"],
             "Transformer les documents et connaissances en mémoire exploitable.",
             "OCR · parsing · structuration · gouvernance documentaire · recherche · RAG souverain · capitalisation des connaissances.",
             "Transformer les documents en mémoire d'entreprise exploitable.")
    cap_card(doc, "Agentium", "Decision Intelligence", PURPLE, "6D28D9", TINT["PURPLE"],
             "Transformer données et connaissances en systèmes intelligents gouvernés.",
             "orchestration · exécution · évaluation · gouvernance · supervision · amélioration continue.",
             "Transformer la connaissance en décisions et en actions mesurables.")
    bullet(doc, [("Suites métier ", True, AMBER), ("— systèmes verticalisés prêts à l'emploi (Translation, Narration, Compliance, Maintenance…), assemblés à partir de ces trois capacités.", False, MUT)])
    image(doc, "dge-papai.png", width=16.5,
          caption="La capacité Data Intelligence de papAI — de la donnée au déploiement, souveraine (SaaS ou on-premise).")
    image(doc, "papai-models.png", base=SCREENS, width=16.5,
          caption="Data Intelligence (papAI) — catalogue de modèles d'entraînement (AutoML, gradient boosting, TabPFN, deep learning…) sans dépendance externe ; ici un scoring de risque d'entreprise (type Infogreffe).")
    image(doc, "papai-interpret.png", base=SCREENS, width=16.5,
          caption="Explicabilité & équité intégrées sur un scoring de risque d'entreprise — impact des variables (dépendance partielle) et onglet Fairness : la transparence requise par l'AI Act, par conception.")

    h2(doc, "Du modèle IA au système intelligent gouverné")
    para(doc,
         "Datategy ne déploie plus uniquement des modèles ou des agents isolés : elle industrialise des "
         "systèmes capables de produire des résultats mesurables, évalués et gouvernés. Agentium structure "
         "cette logique autour d'un même modèle canonique, identique d'un cas d'usage à l'autre.")
    image(doc, "dge-canonical.png", width=16.5,
          caption="Le modèle canonique : Objectif → Système → Run → Évaluation → Décision → Action.")
    runs_para(doc, [
        ("De l'objectif au résultat — ", True, NAVY),
        ("un objectif métier est servi par un système, dont chaque exécution (run) est mesurée et "
         "évaluée, pour produire une décision puis une action tracée. C'est ce qui transforme un modèle "
         "en système intelligent gouverné, et non en simple prototype.", False, INK),
    ])
    image(doc, "ui-flow-builder-full.png", base=SCREENS, width=16.5,
          caption="Agentium (Decision Intelligence) — éditeur de flux : un système composé d'agents, de skills et de contrôles, exécuté comme un graphe gouverné (Run engine DAG).")

    h2(doc, "Skill, Capability, System, Suite — la grammaire de la plateforme")
    para(doc,
         "Toutes les réalisations de Datategy se décrivent avec le même vocabulaire, ce qui garantit leur "
         "réutilisation d'un secteur à l'autre.")
    bullet(doc, [("Skill — ", True, GREEN), ("primitive cognitive réutilisable : OCR, retrieval, classification, traduction, prévision (forecasting), scoring.", False, MUT)])
    bullet(doc, [("Capability — ", True, BLUE), ("promesse métier réutilisable : Document Understanding, Predictive Maintenance, Translation Intelligence, Regulatory Compliance, Risk Detection.", False, MUT)])
    bullet(doc, [("System — ", True, PURPLE), ("assemblage de capacités métier : plusieurs agents, skills, bases de connaissances, workflows, modèles, règles métiers et contrôle humain.", False, MUT)])
    bullet(doc, [("Suite — ", True, AMBER), ("système verticalisé prêt à l'emploi : Translation Suite, Narration Suite, Compliance Suite, Knowledge Suite.", False, MUT)])
    image(doc, "dge-hierarchy.png", width=16.5,
          caption="Une hiérarchie unique : Skill → Capability → System → Suite — réutilisée d'un cas d'usage à l'autre.")

    h2(doc, "Ce qui distingue papAI")
    runs_para(doc, [
        ("Les cas d'usage à forte valeur — risque, opérations, conformité, souveraineté — exigent plus qu'un orchestrateur, plus que des notebooks, plus que des copilotes. ", True, NAVY),
        ("papAI embarque nativement des moteurs industriels d'IA et de données (orchestration, ML, Spark, RAG), sans dépendance externe.", False, INK),
    ])
    diff = [
        ("Orchestration", "Moteur de flux natif (sans orchestrateur externe type Airflow / Prefect)."),
        ("Moteurs d'exécution", "ML, RAG et Spark embarqués — sans dépendance à un service externe."),
        ("Visuel + code", "Interface unifiée no-code et pro-code (les deux, pas l'un ou l'autre)."),
        ("Déploiement souverain", "OVHcloud, Outscale, on-premise / air-gap (vs cloud majoritairement américain)."),
        ("Architecture ouverte", "Extensions Python, injection de modèles/métriques, connecteurs configurables."),
        ("MLOps intégré", "Versioning, détection de dérive, réentraînement — non fragmenté."),
        ("RAG natif", "OmniRAG intégré (vs simple appel d'API LLM externe)."),
        ("Briques métier", "Toutes les actions et étapes modularisées, prêtes pour les utilisateurs métier."),
    ]
    t = doc.add_table(rows=0, cols=2); t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.allow_autofit = False; _borders(t, LINE, 4)
    for i, (a, b) in enumerate(diff):
        r = t.add_row(); fill = "FFFFFF" if i % 2 == 0 else PANEL
        for j, (val, col, bold, w) in enumerate([(a, INK, True, 4.6), (b, MUT, False, 12.4)]):
            c = r.cells[j]; _shade(c, fill); _cell_margins(c); c.width = Cm(w)
            c.text = ""; pp = c.paragraphs[0]; pp.paragraph_format.line_spacing = 1.1
            pp.paragraph_format.space_before = Pt(1); pp.paragraph_format.space_after = Pt(1)
            _runfmt(pp.add_run(val), 9.2, col, bold=bold)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    runs_para(doc, [
        ("Stratégie produit : ", True, NAVY),
        ("plateforme modulaire, composable et scalable, gouvernée par la valeur et le ROI ; conforme "
         "par conception (MLOps, CI/CD, piste d'audit, RGPD) ; fondation pour l'orchestration "
         "agentique et les copilotes verticaux (fraude, conformité, traduction, prévision).", False, INK),
    ])

    h2(doc, "Notre spécificité : edge AI & apprentissage fédéré souverain")
    runs_para(doc, [
        ("Dans le cadre du projet d'innovation HyperOpenX (2024-2025), ", True, NAVY),
        ("Datategy a démontré l'exécution de l'IA en environnement souverain, distribué et à la "
         "périphérie (edge) — au plus près des données, sans les centraliser.", False, INK),
    ])
    bullet(doc, [("Orchestration souveraine portable — ", True, INK), ("le MLOps de papAI a été porté de Kubernetes vers un orchestrateur souverain et léger (OpenSVC), déployable en multi-sites et à la périphérie, sur infrastructure on-premise ou souveraine — sans dépendance à un cloud étranger.", False, MUT)])
    bullet(doc, [("Inférence de bout en bout à la périphérie — ", True, INK), ("ingestion de documents, embeddings, base vectorielle et interrogation de modèle, opérés hors d'un cloud centralisé.", False, MUT)])
    bullet(doc, [("Montée en charge automatique — ", True, INK), ("à saturation d'un nœud, un nœud supplémentaire est instancié et les requêtes redistribuées, sans intervention.", False, MUT)])
    bullet(doc, [("Apprentissage fédéré souverain — ", True, INK), ("entraînement multi-sites par échange de deltas de modèles chiffrés et signés : aucune donnée brute ne quitte les sites ; agrégation FedAvg/FedProx, métriques locales/globales et détection de dérive (ex. maintenance prédictive non-IID).", False, MUT)])
    image(doc, "dge-edge.png", width=16.0,
          caption="Apprentissage fédéré souverain — les modèles apprennent ensemble sans que les données ne quittent les sites.")
    runs_para(doc, [
        ("En somme : ", True, NAVY),
        ("faire fonctionner et améliorer l'IA au plus près des données, en multi-sites, sans "
         "centralisation — souveraineté et confidentialité par conception.", False, INK),
    ])
    runs_para(doc, [
        ("Cette trajectoire se prolonge avec l'initiative ARCTIC ", True, NAVY),
        ("(avec Qarnot, cofinancée par le FEDER) : RAG à grande échelle et fine-tuning de modèles de "
         "langue sur CPU, opérés sur une infrastructure HPC souveraine — une souveraineté de bout en "
         "bout, du calcul à l'inférence, sans dépendance à un cloud étranger ni à des accélérateurs "
         "propriétaires.", False, INK),
    ])

    h2(doc, "Innovation & crédibilité : OmniRAG et l'analyse de cause racine au service du MCO")
    runs_para(doc, [
        ("Datategy investit dans sa propre R&D — ", True, NAVY),
        ("notamment sur le RAG souverain (OmniRAG) et l'analyse de cause racine, deux briques clés du MCO, "
         "là où les approches génériques hallucinent et restent opaques pour le métier. Sans entrer dans le "
         "détail technique, l'essentiel tient en trois points : crédibilité, valeur métier et souveraineté.", False, INK),
    ])
    bullet(doc, [("Crédibilité scientifique — ", True, INK), ("OmniRAG repose sur des travaux de recherche signés par les équipes Datategy (HAH-RAG) ; nous avons par ailleurs industrialisé un modèle d'analyse de cause racine de pointe (Big GCVAE), issu des travaux de notre chercheur Kenneth Ezukwoke.", False, MUT)])
    bullet(doc, [("Valeur métier — ", True, INK), ("une analyse des causes de panne plus fiable, moins hallucinatoire et plus compréhensible par les équipes — donc de meilleures prévisions, même avec peu d'historique de pannes.", False, MUT)])
    bullet(doc, [("Frugalité & souveraineté — ", True, INK), ("des composants sobres (énergie, bande passante), conçus pour être portés en edge via papAI, au plus près des données — sans transit ni dépendance externe, pour un LLM privé et frugal.", False, MUT)])
    image(doc, "uc-ragger-paper.png", base=SCREENS, width=10.5,
          caption="Une recherche R&D signée par les équipes Datategy (OmniRAG — HAH-RAG) : la base scientifique de nos Suites souveraines.")
    image(doc, "uc-biggcvae-archi.png", base=SCREENS, width=12.5,
          caption="Le modèle d'analyse de cause racine que Datategy a industrialisé (Big GCVAE) — d'après les travaux de Kenneth Ezukwoke, aujourd'hui dans nos effectifs.")
    image(doc, "uc-fa-inference.png", base=SCREENS, width=16.0,
          caption="Au banc d'essai, notre approche (OmniRAG) réduit les hallucinations pour une consommation d'énergie et des émissions de CO2 plus faibles que les RAG classiques.")

    h2(doc, "Méthode de mise en œuvre, HITL & qualification")
    para(doc,
         "Chaque cas d'usage suit une trajectoire commune, outillée par le socle : un déploiement "
         "par étapes maîtrisées, une boucle opérationnelle qui garde l'expert métier dans la boucle "
         "(HITL), et une qualification chiffrée à chaque maillon. C'est cette méthode — autant que la "
         "technologie — qui permet de livrer avec confiance et de réutiliser un système d'un domaine à l'autre.")
    image(doc, "dge-method.png", width=16.5,
          caption="Boucle opérationnelle type : de la donnée à la décision, qualifiée et supervisée, avec retour d'expérience continu.")

    runs_para(doc, [("Process de mise en place — ", True, NAVY),
                    ("du cadrage à l'industrialisation, en jalons courts.", False, MUT)], before=4, after=2)
    bullet(doc, [("POC timeboxé (~1 mois) — ", True, BLUE),
                 ("preuve de valeur sur un périmètre réel et des données du client, critères de succès définis dès le cadrage.", False, INK)])
    bullet(doc, [("MVP — ", True, BLUE),
                 ("mise en production d'un premier flux utile, prise en main par les équipes métier, montée en charge progressive.", False, INK)])
    bullet(doc, [("Industrialisation — ", True, BLUE),
                 ("intégration au SI, connecteurs, supervision, formation des agents et transfert de compétences.", False, INK)])

    runs_para(doc, [("Humain dans la boucle (HITL) — ", True, NAVY),
                    ("l'IA propose, l'expert décide.", False, MUT)], before=5, after=2)
    bullet(doc, [("Revue & validation experte ", True, AMBER),
                 ("des cas sensibles ou à faible confiance, avec second regard sur les décisions critiques.", False, INK)])
    bullet(doc, [("Seuils de confiance ", True, AMBER),
                 ("calibrés : escalade automatique vers l'humain en deçà du seuil, alertes dosées pour éviter la fatigue d'alarme.", False, INK)])
    bullet(doc, [("Corrections réinjectées ", True, AMBER),
                 ("dans le système (bases de connaissances, exemples, modèles) — l'expertise humaine améliore le modèle en continu.", False, INK)])
    image(doc, "ui-steering.png", base=SCREENS, width=16.5,
          caption="Pilotage de l'autonomie — leviers (ressources, autonomie, tolérance au risque), garde-fous HITL et politiques adaptatives : l'humain garde la main sur l'IA.")

    runs_para(doc, [("Qualification & évaluation — ", True, NAVY),
                    ("mesurer avant de croire, surveiller après de déployer.", False, MUT)], before=5, after=2)
    bullet(doc, [("Jeux d'évaluation de référence (golden sets) ", True, PURPLE),
                 ("et scoring automatique de la qualité, de la pertinence et de la complétude des réponses.", False, INK)])
    bullet(doc, [("Évaluation normée selon des référentiels industriels ", True, PURPLE),
                 ("(ex. SAE J2450 pour la qualité de traduction) : qualité mesurable, comparable et auditable, avec preuve à chaque livraison.", False, INK)])
    bullet(doc, [("Détection d'hallucination & d'ancrage (grounding) ", True, PURPLE),
                 (": les réponses non étayées par les sources sont signalées ou refusées.", False, INK)])
    bullet(doc, [("Équité & explicabilité ", True, PURPLE),
                 ("(SHAP, PDP, mesures de parité) conformes à l'esprit de l'AI Act, et surveillance de la dérive en production.", False, INK)])
    bullet(doc, [("Piste d'audit ", True, PURPLE),
                 ("complète : traçabilité des sources, des décisions et des interventions humaines, exportable pour la gouvernance.", False, INK)])
    image(doc, "ui-evaluation-quality.png", base=SCREENS, width=16.5,
          caption="Moteur d'évaluation — qualité multi-dimensions (12 axes), score composite, dérive, réclamations non étayées et santé des composants RAG (retriever, generator, router, verifier).")
    image(doc, "uc-renault-pipeline.png", base=SCREENS, width=15.0,
          caption="Qualification concrète d'une chaîne de traduction (Renault) : scoring par segment (métriques automatiques et évaluation normée SAE J2450) ; les cas non tranchés partent en revue humaine.")

    h2(doc, "La cohérence : une marketplace de capacités métier réutilisables")
    runs_para(doc, [
        ("La marketplace n'est pas un catalogue de fonctionnalités : ", True, NAVY),
        ("c'est une capitalisation progressive de capacités métier réutilisables. Chaque projet enrichit "
         "les catalogues de Skills, Capabilities, Systems et Suites — la même fondation souveraine, "
         "déclinée et renforcée à chaque déploiement.", False, INK),
    ])
    bullet(doc, [("le catalogue de Skills ", True, GREEN), ("— les primitives cognitives réutilisables (OCR, retrieval, scoring…).", False, MUT)])
    bullet(doc, [("le catalogue de Capabilities ", True, BLUE), ("— les promesses métier réutilisables (Document Understanding, Maintenance, Compliance…).", False, MUT)])
    bullet(doc, [("le catalogue de Systems ", True, PURPLE), ("— les assemblages de capacités métier, gouvernés et orchestrés.", False, MUT)])
    bullet(doc, [("les Suites verticalisées ", True, AMBER), ("— les systèmes prêts à l'emploi, rapidement déployables sur le socle.", False, MUT)])
    runs_para(doc, [("Pour le client, cela se traduit concrètement par :", True, NAVY)], before=4, after=1)
    bullet(doc, [("Mise en place rapide — ", True, INK), ("des Suites/Systems prêts à l'emploi plutôt qu'un développement à partir d'une page blanche.", False, MUT)])
    bullet(doc, [("Orchestration fine et souveraine — ", True, INK), ("exécution sur l'infrastructure du client (on-premise / air-gap), sans dépendance à un cloud étranger.", False, MUT)])
    bullet(doc, [("Collaborative et gouvernée — ", True, INK), ("composition et exploitation par les équipes métier et data, sous contrôle d'accès, traçabilité et audit.", False, MUT)])
    bullet(doc, [("Réutilisation à l'échelle — ", True, INK), ("un connecteur, un Skill ou un System construit pour un cas sert les suivants — sans recommencer.", False, MUT)])

    h2(doc, "Un modèle éditeur-ESN pour passer à l'échelle")
    runs_para(doc, [
        ("Datategy est un éditeur de logiciel, pas une régie de prestation. ", True, NAVY),
        ("Le passage à l'échelle s'appuie sur un écosystème de partenaires — ESN et intégrateurs — qui "
         "déploient papAI chez leurs clients grands comptes. La valeur transmise au partenaire est claire : "
         "un socle souverain et des Suites prêtes à l'emploi, des méthodes éprouvées, et la possibilité "
         "d'intégrer papAI à ses propres offres pour accélérer le delivery sans repartir d'une page blanche.", False, INK),
    ])
    bullet(doc, [("Partenariat éditeur-ESN ", True, INK), ("— Datategy a noué un partenariat de ce type avec ADBI ; le modèle est ouvert à d'autres ESN et sociétés d'ingénierie pour adresser les grands comptes industriels.", False, MUT)])
    bullet(doc, [("Co-construction d'offres verticalisées ", True, INK), ("— les partenaires assemblent des Suites métier sur le socle (maintenance, conformité, support technique, traduction…), gouvernées et souveraines.", False, MUT)])
    bullet(doc, [("Souveraineté préservée à l'échelle ", True, INK), ("— le déploiement par des partenaires français renforce l'ancrage souverain sans diluer la gouvernance ni la maîtrise des données par le client final.", False, MUT)])

    h2(doc, "Hypervisor : piloter la valeur créée par l'IA")
    runs_para(doc, [
        ("Mission — passer du monitoring à la décision. ", True, NAVY),
        ("L'Hypervisor offre une vue exécutive sur le portefeuille de systèmes IA et transforme l'IA en "
         "un actif pilotable au niveau de l'organisation.", False, INK),
    ])
    bullet(doc, [("Portefeuille de systèmes ", True, INK), ("— l'ensemble des capacités et systèmes en exploitation, en un seul écran.", False, MUT)])
    bullet(doc, [("Coût, qualité & ROI ", True, INK), ("— valeur générée, coût, confiance et efficience mesurés par capacité et par système.", False, MUT)])
    bullet(doc, [("Gouvernance & recommandations ", True, INK), ("— signaux, alertes et recommandations d'action, alignés sur les objectifs stratégiques.", False, MUT)])
    image(doc, "ui-hypervisor.png", base=SCREENS, width=16.5,
          caption="Hypervisor — vue exécutive du portefeuille IA : valeur générée, ROI, coût, qualité et recommandations, par capacité.")

    h2(doc, "Souveraineté & gouvernance — de bout en bout")
    runs_para(doc, [
        ("La souveraineté ne se limite pas à l'hébergement. ", True, NAVY),
        ("Elle est une propriété du système complet : elle s'applique aux données, aux connaissances, aux "
         "modèles, à l'exécution, aux décisions, à l'audit et à la gouvernance — du calcul à l'inférence, "
         "dans le périmètre du client.", False, INK),
    ])
    image(doc, "dge-sovereign.png", width=16.5,
          caption="Souveraineté de bout en bout — une propriété du système complet, pas uniquement de l'infrastructure.")
    bullet(doc, [("Déploiement souverain — ", True, INK), ("SaaS, cloud privé ou on-premise / air-gap ; les données et les modèles restent dans le périmètre du client.", False, MUT)])
    bullet(doc, [("Gouvernance & traçabilité — ", True, INK), ("contrôle d'accès, journalisation et auditabilité des traitements et des décisions.", False, MUT)])
    bullet(doc, [("Conformité — ", True, INK), ("Datategy contribue à la mise en œuvre de l'AI Act européen et est référencée pour le marché public (UGAP).", False, MUT)])
    bullet(doc, [("Réutilisation sans compromission — ", True, INK), ("la mutualisation du socle accélère les projets sans diluer la maîtrise des utilisateurs et des clients sur leurs données.", False, MUT)])

    doc.add_page_break()

    # ============================================ 4. Conclusion
    h1(doc, "4.  Conclusion — pérennité et robustesse des systèmes IA")
    runs_para(doc, [
        ("Datategy n'est pas dans une démarche « shoot & forget ». ", True, NAVY),
        ("Chaque déploiement s'inscrit dans une trajectoire évolutive : les systèmes sont conçus pour "
         "durer, s'améliorer et s'adapter à un écosystème technologique et réglementaire en mouvement "
         "permanent.", False, INK),
    ])
    h2(doc, "Une trajectoire évolutive, pas un projet jetable")
    bullet(doc, [("Amélioration continue — ", True, INK), ("HITL, réentraînement, détection de dérive, corrections réinjectées dans les bases de connaissances et les modèles.", False, MUT)])
    bullet(doc, [("Capitalisation progressive — ", True, INK), ("chaque référence enrichit la marketplace de Skills, Capabilities, Systems et Suites, réutilisables sur les projets suivants.", False, MUT)])
    bullet(doc, [("Pilotage dans la durée — ", True, INK), ("Hypervisor pour mesurer coût, qualité et ROI ; gouvernance et audit pour suivre les décisions dans le temps.", False, MUT)])
    bullet(doc, [("Adaptation à l'écosystème — ", True, INK), ("conformité AI Act, edge AI, apprentissage fédéré, ARCTIC : le socle évolue avec les contraintes et les opportunités du marché.", False, MUT)])
    h2(doc, "Robustesse et pérennité par conception")
    runs_para(doc, [
        ("La pérennité des systèmes repose sur trois piliers : ", True, NAVY),
        ("un socle produit unique et intégré (papAI), une méthode de livraison maîtrisée (POC → MVP → "
         "industrialisation, avec qualification à chaque étape), et une souveraineté de bout en bout qui "
         "garantit la maîtrise des données, des modèles et des décisions dans la durée.", False, INK),
    ])
    runs_para(doc, [
        ("Datategy industrialise une plateforme souveraine unique, papAI, capable de transformer les "
         "données, les connaissances et les modèles en systèmes intelligents gouvernés. Les cas d'usage "
         "présentés ne sont pas des réalisations isolées mais les démonstrations d'un même socle "
         "technologique réutilisable — conçu pour produire de la valeur mesurable aujourd'hui et "
         "rester opérationnel demain.", False, INK),
    ])
    callout(doc, "En conclusion",
            "Une pluralité de cas d'usage, une seule plateforme souveraine : papAI. Les données alimentent "
            "les modèles, les modèles enrichissent les connaissances, les connaissances alimentent les "
            "systèmes intelligents, et les systèmes produisent des résultats métier mesurables — le tout au "
            "sein d'un même environnement gouverné, souverain, réutilisable et pérenne.",
            NAVY, "0B2545", TINT["NAVY"], body_bold=True)

    p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(10); _pbottom(p, "C9D2DE", 6)
    para(doc, "Contact", size=11, color=NAVY, bold=True, before=6, after=2)
    para(doc, "Datategy — 58 rue de Monceau, 75008 Paris (Île-de-France)  ·  contact@datategy.net  ·  datategy.net",
         size=9.5, color=MUT)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    doc.save(OUT)
    print("saved:", os.path.relpath(OUT, HERE))
    return OUT


if __name__ == "__main__":
    build()
