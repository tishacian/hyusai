"""The Sentinel CI reports a demo workspace is seeded with (ADR 0003).

The Prefet report the Mission Room pre-renders, and the text of the strategic
report it drafts. ``app.services.sentinel_ci_reports`` renders, stores and
signs them; it no longer carries their content.
"""

from __future__ import annotations

#: The densified Prefet report: ``docs/demo-data/sentinel-ci-kb/<name>.md`` is
#: its source and ``app/resources/sentinel_ci_reports/<name>.pdf`` its render.
PREFET_REPORT_NAME = "rapport-prefet-nawa-2026-05-10"
PREFET_REPORT_TITLE = "Rapport Prefet de Nawa - 10 mai 2026"

#: Sources the strategic report cites when the caller names none.
DEFAULT_CONTEXT_REFS = "- report-prefet-nawa-2026-05-10\n- sentinel-ci-anacarde-diversification-v1"


def strategic_report_markdown(*, today: str, workspace_slug: str, topic: str, refs: str, length: str) -> str:
    """The strategic report's text; its hash names the report, so it stays verbatim."""

    return f"""# Rapport strategique - {topic}

**Date**: {today}
**Workspace**: {workspace_slug}
**Theme**: {topic}
**Longueur cible**: {length}

## Contexte

Synthese consolidee sur la diversification du cacao en region Nawa, avec
focus anacarde transformee. Sources mobilisees :

{refs}

## Recommandation principale

L'option **diversification anacarde transformee** combine :

- Filiere immediatement substituable (climat et sols compatibles)
- Marche export structure (UE, Inde, Vietnam)
- Compatibilite reglement europeen anti-deforestation
- Chiffrage indicatif : 4,2 a 6,8 Mds FCFA (ordre de grandeur public)

## Classement des options

| Rang | Option | Cout indicatif (Mds FCFA) | Compatibilite EUDR | Impact emploi |
|------|--------|---------------------------|--------------------|---------------|
| 1 | Anacarde transformee | 4,2 - 6,8 | Tres haut | Eleve |
| 2 | Cooperative cacao renforcee | 1,6 | Moyen | Moyen |
| 3 | PPP sechoirs solaires | 6,8 | Eleve | Eleve |
| 4 | Hevea diversification | 5,4 | Moyen | Moyen |
| 5 | Palmier a huile (RSPO) | 7,2 | Faible | Eleve |
| 6 | Banane premium | 3,0 | Moyen | Faible |
| 7 | Statu quo | 0,0 | Faible | Faible |

## Indicateurs cockpit suggeres

- Volume anacarde transforme localement (% production)
- Part export anacarde vs export brut cacao
- Emplois directs transformation (Soubre)
- Conformite EUDR (taux audits passes)

## Citations

- Banque mondiale - Note climat-developpement Cote d'Ivoire (2024)
- Reglement europeen anti-deforestation 2023/1115 (EUDR)
- Reuters - filiere cajou Cote d'Ivoire, chute prix producteur (2025)
- Rapport Prefet Nawa - 10 mai 2026, pp. 42-58

## Validation requise

Document advisory-only. Validation Cabinet + ministere de l'Economie
necessaire avant exposition publique.
"""
