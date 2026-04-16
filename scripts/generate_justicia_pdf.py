#!/usr/bin/env python3
"""
Génère le PDF du bilan de livraison MVP JusticIA — une page par slide.
Dépendances : fpdf2, Pillow

  python scripts/generate_justicia_pdf.py
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from fpdf import FPDF
from PIL import Image as PILImage

REPO = Path(__file__).resolve().parent.parent
SHOTS = REPO / "presentations" / "justicia-metaketing-aziz" / "screenshots"
LOGO = REPO / "image" / "justicia.png"
OUT = REPO / "presentations" / "justicia-metaketing-aziz" / "JusticIA_Bilan_MVP.pdf"

PW, PH = 297, 167.0625  # 16:9 landscape in mm
MARGIN = 12
BG = (11, 13, 18)
CARD_BG = (22, 27, 34)
TEXT_COL = (230, 237, 243)
MUTED = (139, 148, 158)
ACCENT = (88, 166, 255)
GREEN = (63, 185, 80)
ORANGE = (227, 149, 52)
RED = (200, 80, 80)
BORDER_COL = (48, 54, 61)


class JusticIAPDF(FPDF):

    def __init__(self) -> None:
        super().__init__(orientation="L", unit="mm", format=(PH, PW))
        self.set_auto_page_break(auto=False)
        self._load_fonts()

    def _load_fonts(self) -> None:
        for path in (
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        ):
            p = Path(path)
            if p.is_file():
                name = "Arial" if "Bold" not in p.name else "ArialB"
                style = "" if "Bold" not in p.name else "B"
                self.add_font(name, style, str(p))
        self._has_arial = Path("/System/Library/Fonts/Supplemental/Arial.ttf").is_file()

    def _set_font(self, size: float, bold: bool = False) -> None:
        if self._has_arial:
            self.set_font("ArialB" if bold else "Arial", "B" if bold else "", size)
        else:
            self.set_font("Helvetica", "B" if bold else "", size)

    def _bg(self) -> None:
        self.set_fill_color(*BG)
        self.rect(0, 0, PW, PH, "F")

    def _card(self, x: float, y: float, w: float, h: float) -> None:
        self.set_fill_color(*CARD_BG)
        self.set_draw_color(*BORDER_COL)
        self.rect(x, y, w, h, "DF")

    def _text(self, x: float, y: float, txt: str, size: float = 8,
              color: tuple = TEXT_COL, bold: bool = False) -> None:
        self._set_font(size, bold)
        self.set_text_color(*color)
        self.set_xy(x, y)
        self.cell(0, size * 0.5, txt)

    def _mtext(self, x: float, y: float, w: float, txt: str, size: float = 7,
               color: tuple = TEXT_COL, bold: bool = False, line_h: float | None = None) -> float:
        self._set_font(size, bold)
        self.set_text_color(*color)
        self.set_xy(x, y)
        lh = line_h or size * 0.55
        self.multi_cell(w, lh, txt, align="L")
        return self.get_y()

    def _logo(self, x: float, y: float, h: float = 10) -> None:
        if LOGO.is_file():
            self.image(str(LOGO), x, y, h=h)

    # ------------------------------------------------------------------

    def page_title_slide(self) -> None:
        self.add_page()
        self._bg()
        self._logo(MARGIN, MARGIN, 16)
        self._text(MARGIN + 20, MARGIN + 2, "JusticIA", 22, bold=True)
        self._text(MARGIN + 20, MARGIN + 14, "Bilan de livraison MVP", 12, MUTED)

        self._text(MARGIN, 40, "Périmètre contractuel", 11, ACCENT, bold=True)

        rows = [
            ("Client", "Metaketing FZE"),
            ("Objet", "Intégration de papAI pour JusticIA — assistant juridique à recherche augmentée (RAG)"),
            ("Licence papAI", "3 utilisateurs — 21 000 € HT / an"),
            ("Développements", "59 000 € HT (forfait)"),
            ("Phase 1", "Intégration CPU de RAGGER + RAFT dans papAI, premières briques RAG"),
            ("Phase 2", "Activation GPU, intégration LAFT, automatisation de la recherche juridique"),
            ("Prérequis infra", "Kubernetes, SSL, serveur Unix (vCores, RAM, stockage), Git, Docker"),
        ]
        y = 50
        for label, val in rows:
            self._card(MARGIN, y, PW - 2 * MARGIN, 7)
            self._text(MARGIN + 3, y + 1.5, label, 6, ACCENT, bold=True)
            self._text(80, y + 1.5, val, 6)
            y += 8.5

        y += 4
        self._text(MARGIN, y, "Ressources engagées", 11, ACCENT, bold=True)
        y += 10

        lots = [
            ("Moteur RAG & C-HAH", "~22 j/h"),
            ("Classification & templates", "~5 j/h"),
            ("Ingestion & OCR", "~8 j/h"),
            ("Interface", "~7 j/h"),
            ("Modèles & embeddings", "~6 j/h"),
            ("Benchmarking", "~3 j/h"),
            ("Infra & déploiement", "~4 j/h"),
        ]
        col_w = (PW - 2 * MARGIN) / len(lots)
        for i, (lot, jh) in enumerate(lots):
            x = MARGIN + i * col_w
            self._card(x + 0.5, y, col_w - 1, 14)
            self._text(x + 2, y + 2, lot, 5.5, ACCENT, bold=True)
            self._text(x + 2, y + 7.5, jh, 6, GREEN)

        self._text(PW - MARGIN - 40, y + 16, "Total : ~55 j/h", 8, TEXT_COL, bold=True)

    # ------------------------------------------------------------------

    def page_screenshot(self, img_name: str, title: str,
                        bullets: list[str] | None = None,
                        table: list[tuple[str, ...]] | None = None,
                        note: str | None = None) -> None:
        self.add_page()
        self._bg()

        self._logo(MARGIN, MARGIN - 2, 8)
        self._text(MARGIN + 11, MARGIN - 1, title, 12, TEXT_COL, bold=True)

        img_path = SHOTS / img_name
        if img_path.is_file():
            with PILImage.open(img_path) as im:
                iw, ih = im.size
            img_w = PW - 2 * MARGIN
            img_h = img_w * ih / iw
            max_h = PH - 36 if not bullets and not table else 90
            if img_h > max_h:
                img_h = max_h
                img_w = img_h * iw / ih
            ix = (PW - img_w) / 2
            self.image(str(img_path), ix, 22, img_w, img_h)
            content_y = 22 + img_h + 4
        else:
            content_y = 30

        if bullets:
            for b in bullets:
                parts = b.split(" — ", 1)
                if len(parts) == 2:
                    self._text(MARGIN + 2, content_y, "•", 6, ACCENT)
                    self._set_font(6, bold=True)
                    self.set_text_color(*ACCENT)
                    self.set_xy(MARGIN + 6, content_y)
                    self.cell(0, 3.5, parts[0])
                    bw = self.get_string_width(parts[0]) + 1
                    self._set_font(6)
                    self.set_text_color(*TEXT_COL)
                    self.set_xy(MARGIN + 6 + bw, content_y)
                    self.cell(0, 3.5, " — " + parts[1])
                else:
                    self._text(MARGIN + 2, content_y, "•  " + b, 6)
                content_y += 5

        if table:
            y = content_y + 1
            col_w = (PW - 2 * MARGIN) / len(table[0])
            for ri, row in enumerate(table):
                is_header = ri == 0
                for ci, cell in enumerate(row):
                    x = MARGIN + ci * col_w
                    color = ACCENT if is_header else TEXT_COL
                    self._text(x + 2, y, cell, 5.5 if is_header else 5, color, bold=is_header)
                y += 5

        if note:
            self._card(MARGIN, PH - 16, PW - 2 * MARGIN, 10)
            self._text(MARGIN + 4, PH - 14, note, 6, ORANGE)

    # ------------------------------------------------------------------

    def page_coverage(self) -> None:
        self.add_page()
        self._bg()
        self._logo(MARGIN, MARGIN - 2, 8)
        self._text(MARGIN + 11, MARGIN - 1, "Couverture de la roadmap MVP", 12, TEXT_COL, bold=True)

        items = [
            ("OK", "Extraction de méta-données", "Type, juridiction, date — extraction automatique"),
            ("OK", "Micro-service indépendant", "Architecture découplée, déployable séparément"),
            ("OK", "Smart retrieval par méta-données", "Filtres avancés (date, juridiction, type)"),
            ("OK", "Réponses sourcées", "Citations, score de pertinence, traçabilité"),
            ("OK", "Bibliothèque VDB multi-profils", "Juge, avocat, notaire — bases dédiées"),
            ("OK", "Interface création / chargement VDB", "Création et sélection dynamique"),
            ("BLOQUÉ", "Constitution VDB sur données client", "Données non transmises par le client"),
            ("OK", "Bibliothèque d'instructions LLM", "Templates modifiables par l'admin"),
            ("OK", "5 templates de raisonnement", "Factuel, Analytique, Comparatif, Causal, Hypothétique"),
            ("OK", "Templates bilingues FR / EN", "Basculement par configuration"),
            ("OK", "Interface admin instructions", "Modification du rôle et consignes modèle"),
            ("OK", "Sélection du modèle LLM", "Choix parmi les modèles disponibles"),
            ("OK", "3 familles de modèles", "Gemma (Google), Llama (Meta), Mistral"),
            ("OK", "Détection automatique de la tâche", "Classification bayésienne du raisonnement"),
            ("OK", "Pipeline C-HAH optimisé", "Custom pipeline — résultats accélérés"),
            ("OK", "Pipeline RAG complet", "Chaîne hyper-layered chain-of-thoughts"),
            ("OK", "Recherche sémantique", "Contexte, recherche dense + lexicale"),
            ("OK", "Ingestion multi-modale", "PDF, DOCX, HTML, e-mail, PPTX, CSV"),
            ("OK", "OCR", "Tesseract pour pièces numérisées"),
            ("OK", "Raisonnement multi-modal", "Texte + image"),
            ("N/A", "ElasticSearch", "Écarté — remplacé par FAISS + BM25"),
            ("N/A", "Base relationnelle méta-données", "Écarté — intégrées dans l'index vectoriel"),
        ]

        y = 22
        col_status = MARGIN + 2
        col_feat = MARGIN + 12
        col_detail = MARGIN + 110
        row_h = 6

        self._text(col_status, y, "Statut", 5.5, ACCENT, bold=True)
        self._text(col_feat, y, "Fonctionnalité", 5.5, ACCENT, bold=True)
        self._text(col_detail, y, "Détail", 5.5, ACCENT, bold=True)
        y += 5
        self.set_draw_color(*BORDER_COL)
        self.line(MARGIN, y, PW - MARGIN, y)
        y += 2

        for status, feat, detail in items:
            if status == "OK":
                color = GREEN
            elif status == "BLOQUÉ":
                color = RED
            else:
                color = MUTED
            self._text(col_status, y, status, 5, color, bold=True)
            self._text(col_feat, y, feat, 5, TEXT_COL if status != "N/A" else MUTED)
            self._text(col_detail, y, detail, 4.5, MUTED)
            y += row_h
            if y > PH - 10:
                self.add_page()
                self._bg()
                y = MARGIN


def main() -> None:
    pdf = JusticIAPDF()

    # Page 1 : titre + périmètre + ressources
    pdf.page_title_slide()

    # Page 2 : proposition de valeur
    pdf.page_screenshot(
        "01-couverture.png",
        "Proposition de valeur",
        bullets=[
            "Ingestion multi-format + OCR — PDF, DOCX, e-mail, HTML, OCR Tesseract, extraction automatique de méta-données",
            "Retrieval hybride intelligent — FAISS + BM25, rerank cross-encoder, recherche guidée par méta-données",
            "Multi-modèles & multi-profils — 3 familles (Gemma, Llama, Mistral), profils métier, détection automatique de la tâche",
        ],
    )

    # Page 3 : interface assistant
    pdf.page_screenshot(
        "02-assistant.png",
        "Interface assistant",
        bullets=[
            "Zone de dialogue — Réponse sourcée, template de raisonnement affiché, nombre de sources",
            "Panneau paramètres — Profil métier, modèle, pipeline C-HAH, instruction de raisonnement (5 templates FR/EN)",
            "Gestion de sessions — Historique persisté, export CSV / XLSX / JSON",
            "Latence affichée — Temps de réponse pour le suivi qualité",
        ],
    )

    # Page 4 : pipeline
    pdf.page_screenshot(
        "03-pipeline.png",
        "Pipeline C-HAH & raisonnement",
        bullets=[
            "Architecture Custom C-HAH — chaîne de raisonnement hyper-layered, classification bayésienne automatique",
            "5 templates — Factuel, Analytique, Comparatif, Causal, Hypothétique (FR / EN)",
            "3 familles de modèles — Gemma (2B–9B), Llama (8B–70B), Mistral (7B–12B)",
        ],
    )

    # Page 5 : sources
    pdf.page_screenshot(
        "04-sources.png",
        "Traçabilité des sources & méta-données",
        bullets=[
            "Extraits affichés — Passages fondant la réponse avec score de pertinence",
            "Méta-données — Type, juridiction, date extraits automatiquement pour le smart retrieval",
            "Auditabilité — Chaque réponse vérifiable contre le fond documentaire",
        ],
    )

    # Page 6 : gouvernance
    pdf.page_screenshot(
        "05-gouvernance.png",
        "Profils, bases vectorielles & gouvernance",
        bullets=[
            "VDB multi-profils — Juge, avocat, notaire, personnalisé — avec interface de création et chargement",
            "Rôles — Juriste (utilisation directe), Admin données, Admin instructions, DSI",
            "Isolation par workspace — Bases, historiques et droits scindés par périmètre",
        ],
        note="Point bloquant : la constitution des VDB par profil nécessite les données documentaires du client, non encore transmises.",
    )

    # Page 7 : investissement
    pdf.page_screenshot(
        "06-partenariat.png",
        "Investissement et cadre contractuel",
        bullets=[
            "Licence papAI — 3 utilisateurs, 21 000 € HT / an",
            "Développements — 59 000 € HT forfait (Phase 1 CPU + Phase 2 GPU)",
            "Infrastructure — GPU dédié (inférence locale), serveurs staging OVH, CI/CD",
            "Charge humaine — ~55 jours-homme",
        ],
    )

    # Page 8 : couverture roadmap
    pdf.page_coverage()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUT))
    print(f"PDF généré : {OUT}")


if __name__ == "__main__":
    main()
