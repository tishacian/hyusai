# SENTINEL-CI Démo VP · pptx redesign (25 mai 2026)

Avant / après du polish design appliqué au deck
`docs/sentinel-ci-demo-deck-2026-05-25.pptx` pour la démo VP du 25 mai 2026.

## Approche

- **Option B retenue** : python-pptx post-processing.
- Script : `scripts/redesign_deck.py` (idempotent — peut être ré-exécuté à
  chaque régénération pandoc).
- Le contenu (texte, tableaux, 13 screenshots embarqués) est **préservé** ;
  seuls le fond, les couleurs, les fonts, les positions des blocs *Légende*
  et l'ajout des footers / page numbers / barre d'accent sont touchés.

## Palette appliquée

| Token | Hex | Usage |
|---|---|---|
| `--mission-bg-deep` | `#0a1118` | Fond cockpit principal |
| `--mission-bg-deep-2` | `#060b12` | Fond title slide + section headers |
| `--mission-accent` | `#3ee68a` | Titres + barre d'accent + en-tête table + badge PASS |
| `--mission-warn` | `#f59e0b` | Badge WARN |
| `--mission-critical` | `#ef4444` | Badge FAIL / CRITICAL |
| `--mission-violet` | `#a78bfa` | Badge `[AYA only]` + filets sentinel |
| `--mission-text` | `#e2e8f0` | Corps de texte (slate-200) |
| `--mission-text-muted` | `#94a3b8` | Sous-titres, captions, légendes |
| `--mission-text-dim` | `#64748b` | Footers, page numbers |

## Captures

| # | Avant (Pandoc défaut) | Après (Sentinel-CI cockpit) |
|---|---|---|
| Slide 1 — Titre | `01-before-title.png` | `01-after-title.png` |
| Slide 6 — `1.1 État du jour` | `02-before-content-slide-05.png` | `02-after-content-slide-05.png` |
| Slide 18 — Récap S1 | `03-before-recap-table-slide-17.png` | `03-after-recap-table-slide-17.png` |
| Slide 5 — Section header *Bloc 1* | — | `04-after-section-header-bloc1.png` |
| Slide 7 — Table KPI macro | — | `05-after-kpi-table.png` |
| Slide 13 — S1.2 PV douanes (fix overlap *Légende*) | — | `06-after-legend-fix-slide-12.png` |
| Slide 43 — A.1 Smoke probe | — | `07-after-smoke-probe-table.png` |

## Livrables

- `docs/sentinel-ci-demo-deck-2026-05-25.pptx` — redesigné (4.75 MB, 49 slides).
- `docs/sentinel-ci-demo-deck-2026-05-25.html` — reveal.js theme `black` enrichi
  d'overrides Sentinel + colorisation badges via JS final.
- `scripts/redesign_deck.py` — script idempotent. Usage :
  `python3 scripts/redesign_deck.py <input.pptx> [output.pptx]`.

## Dépendances

- `python-pptx` 1.0.2 installé via pip (sur le pyenv local).
- pandoc 3.9.0.2 (présent).
- LibreOffice / Marp **non installés** — Option A et Option C écartées,
  Option B (python-pptx) seule praticable.
