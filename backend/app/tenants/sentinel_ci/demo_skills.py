"""Sentinel CI demonstration skills: scripted government mission-room content.

``summarize_long_document_v1``, ``generate_recommendations_v1`` and
``draft_email_v1`` are listed in the shared skill catalogue, but what they
return is the Sentinel CI scenario: the Nawa prefect report, cocoa
diversification options, customs and security letters for the Vice Prime
Minister's cabinet. The shared wrappers call these only for a workspace of the
``sentinel_ci`` family and refuse elsewhere, so no other tenant receives this
content as if it were its own.
"""

from __future__ import annotations

from typing import Any, Optional


def load_prefet_report_text() -> str:
    from pathlib import Path

    candidates = [
        Path(__file__).resolve().parents[3]
        / "docs"
        / "demo-data"
        / "sentinel-ci-kb"
        / "rapport-prefet-nawa-2026-05-10.md",
        Path(__file__).resolve().parents[2]
        / ".."
        / "docs"
        / "demo-data"
        / "sentinel-ci-kb"
        / "rapport-prefet-nawa-2026-05-10.md",
    ]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""


async def summarize_long_document(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    document_id = str(payload.get("document_id") or "report-prefet-nawa-2026-05-10")
    focus_topics = list(
        payload.get("focus_topics") or ["cacao", "diversification", "infrastructures"]
    )
    report_text = load_prefet_report_text()
    citations = [
        {
            "source_id": "src-prefet-nawa-report-001",
            "document_id": document_id,
            "title": "Rapport Prefet Nawa — 10 mai 2026",
            "sent_at": "2026-05-10",
            "pages": 70,
        }
    ]
    key_topics = [
        topic for topic in focus_topics if topic.lower() in report_text.lower()
    ] or focus_topics
    summary_lines = [
        "Monsieur le Vice Premier Ministre, synthese des derniers echanges avec le Prefet de Nawa (rapport du 10 mai, ~70 pages) :",
        "- Contexte : region Nawa / Soubre, filiere cacao dominante, pression sur prix FCFA et infrastructures.",
        "- Points saillants : besoin de sechoirs, routes secondaires, electrifiation et diversification cultures.",
        "- Risques : volatilite prix export, dependance monoculture, fenetre climatique.",
        "- Recommandations prefet : transformation locale a court terme, montee en charge cooperative, financement mixte.",
    ]
    if "cacao" in report_text.lower():
        summary_lines.append(
            "- Emergence cacao : sections filiere et chiffrage publics confirment un gap transformation ~4,2-6,8 Mds FCFA."
        )
    return {
        "status": "ready",
        "summary_markdown": "\n".join(summary_lines),
        "key_topics": key_topics,
        "citations": citations,
        "document_id": document_id,
    }


async def generate_recommendations(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    topic = str(payload.get("topic") or "cacao_diversification")
    chiffrage = bool(payload.get("chiffrage", True))
    options = [
        {
            "label": "Petite industrie transformation + diversification cultures",
            "summary": "Unité locale de transformation cacao + ananas/culture de couverture ; impact emploi Soubre.",
            "cost_estimate": "4,2 Mds FCFA" if chiffrage else None,
            "infra_required": ["Sechoirs", "Mini-usine", "Routes secondaires"],
            "confidence": 0.78,
        },
        {
            "label": "Cooperative regionale renforcee",
            "summary": "Montee en charge cooperative existante, formation qualite export et tracabilite.",
            "cost_estimate": "1,6 Mds FCFA" if chiffrage else None,
            "infra_required": ["Centres de collecte", "Formation"],
            "confidence": 0.71,
        },
        {
            "label": "PPP infrastructure sechoirs",
            "summary": "Partenariat public-prive sur sechoirs solaires ; partage risque prix.",
            "cost_estimate": "6,8 Mds FCFA" if chiffrage else None,
            "infra_required": ["Sechoirs solaires", "Electrification"],
            "confidence": 0.66,
        },
    ]
    return {
        "status": "ready",
        "topic": topic,
        "options": options,
        "sources": [
            {
                "source_id": "src-prefet-nawa-report-001",
                "document_id": "report-prefet-nawa-2026-05-10",
            }
        ],
        "human_validation_required": True,
    }


async def draft_email(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    template_kind = str(payload.get("template_kind") or "customs_priority")
    target_id = str(payload.get("target_id") or "")
    context_refs = list(payload.get("context_refs") or [])
    if template_kind == "customs_priority":
        return {
            "status": "draft",
            "template_kind": template_kind,
            "subject": (
                "Priorisation dedouanement — composants drones Aerostar Dynamics, "
                "Centre Formation Drones Napié (cargo-abidjan-supply-001)"
            ),
            "recipient": "Direction generale des Douanes — Cellule Port Abidjan",
            "body_markdown": (
                "Monsieur le Directeur,\n\n"
                "Je vous prie de bien vouloir accorder une priorisation de traitement a la cargaison "
                "**MV ATLANTIC TRADER** (ref. cargo-abidjan-supply-001, IMO 9876543) : composants drones "
                "Aerostar Dynamics importes depuis la cote Est des Etats-Unis (hangars de formation, "
                "terrains d'apprentissage, laboratoires de cartographie) destines au "
                "**Centre International de Formation aux Métiers des Drones de Napié** "
                "(ref. proj-drone-centre-napie, region Poro / Nord ; investissement 100 M USD / 60 Mds FCFA ; "
                "alignement Côte d'Ivoire Innovation 2030).\n\n"
                "Le retard actuel (de l'ordre de 120 jours sur la sequence ouverture du centre) impacte le "
                "calendrier de demarrage des formations FAA et la perception institutionnelle du projet sur zone.\n\n"
                "Merci de me confirmer la fenetre de dedouanement envisagee.\n\n"
                "Bien cordialement,\nCabinet Vice Premier Ministre"
            ),
            "sources": [
                {"source_id": "src-maritime-paa-001"},
                {"source_id": "src-cabinet-brief-001", "project_id": "proj-drone-centre-napie"},
                {
                    "source_id": "src-abidjan-net-drone-napie-2025-07-16",
                    "title": "Abidjan.net — Lancement Centre Formation Drones Napié (16/07/2025)",
                    "kind": "rss_news_ci",
                },
            ],
            "requires_validation": True,
        }
    if template_kind == "customs_derogation":
        return {
            "status": "draft",
            "template_kind": template_kind,
            "subject": (
                "Demande de derogation operationnelle — cargaison composants drones "
                "Centre Formation Napié (MV Atlantic Trader)"
            ),
            "recipient": "Direction generale des Douanes — Chef de la cellule portuaire Abidjan",
            "body_markdown": (
                "Monsieur le Chef de la cellule douaniere,\n\n"
                "Faisant suite au proces-verbal de non-conformite declarative du 18 mai 2026 "
                "(ref. DGD-CI/CPA/PV-2026-05-018, page 2), je vous saisis pour solliciter une "
                "**derogation operationnelle ciblee** au benefice du cargo MV ATLANTIC TRADER "
                "(IMO 9876543, MMSI 627012345, ref. cargo-abidjan-supply-001).\n\n"
                "**Le cargo MV Atlantic Trader est distinct du lot non conforme** (LOT-INTRA-IMP-2026-05-018). "
                "Sa cargaison — composants drones AerostarDynamics (hangars de formation, terrains "
                "d'apprentissage, laboratoires de cartographie), importes depuis la cote Est des Etats-Unis — "
                "est exclusivement destinee au **Centre International de Formation aux Métiers des Drones "
                "de Napié** (ref. proj-drone-centre-napie, region Poro / Nord ; partenariat Agence de "
                "Developpement Regional du Poro, Aerostar Dynamics et CEPICI ; alignement Côte d'Ivoire "
                "Innovation 2030 ; investissement 100 M USD / 60 Mds FCFA ; cf. Abidjan.net, "
                "16 juillet 2025).\n\n"
                "Le gel temporaire du couloir d'entree Vridi, motive par la non-conformite d'un **autre** lot, "
                "affecte par effet collateral la cargaison drones Napié sans qu'aucune anomalie declarative "
                "n'ait ete relevee a son encontre.\n\n"
                "Au vu :\n"
                "- de la distinction documentaire claire entre les deux lots ;\n"
                "- du calendrier de livraison engageant l'ouverture du Centre Formation Drones de Napié "
                "(retard cumule de l'ordre de 120 jours en Q2 2026) ;\n"
                "- et de l'absence totale de non-conformite sur le lot drones Napié,\n\n"
                "je sollicite votre accord pour une derogation operationnelle permettant le dedouanement "
                "anticipe du cargo MV Atlantic Trader sous reserve des controles physiques habituels.\n\n"
                "Demande advisory soumise a validation Cabinet et a confirmation du ministere de l'Economie "
                "avant transmission officielle.\n\n"
                "Bien cordialement,\nCabinet Vice Premier Ministre"
            ),
            "sources": [
                {
                    "source_id": "customs-record-non-conformite-2026-05",
                    "title": "PV douanes - non conformite declarative (18 mai)",
                    "kind": "customs_pv",
                    "page": 2,
                },
                {"source_id": "src-maritime-paa-001"},
                {"source_id": "src-cabinet-brief-001", "project_id": "proj-drone-centre-napie"},
                {
                    "source_id": "src-abidjan-net-drone-napie-2025-07-16",
                    "title": "Abidjan.net — Lancement Centre Formation Drones Napié (16/07/2025)",
                    "kind": "rss_news_ci",
                },
            ],
            "context_refs": context_refs,
            "requires_validation": True,
            "advisory_only": True,
            "target_id": target_id or "cargo-abidjan-supply-001",
        }
    if template_kind == "strategic_report_long":
        return {
            "status": "draft",
            "template_kind": template_kind,
            "subject": "Rapport strategique - Diversification cacao region Nawa (anacarde transformee)",
            "recipient": "Cabinet Vice Premier Ministre + Ministere Economie + Ministere Agriculture",
            "body_markdown": (
                "# Rapport strategique - Diversification cacao region Nawa\n\n"
                "## Synthese executive\n"
                "L'option **anacarde transformee** ressort prioritaire (note Banque mondiale 2024, "
                "Reuters 2025, EUDR). Chiffrage indicatif : 4,2 - 6,8 Mds FCFA.\n\n"
                "## Classement des 7 cultures evaluees\n"
                "1. Anacarde transformee (prioritaire)\n"
                "2. Cooperative cacao tracable (court terme)\n"
                "3. Hevea (complement)\n"
                "4. Banane premium (niche)\n"
                "5. PPP sechoirs solaires (infrastructure)\n"
                "6. Palmier a huile RSPO (risque EUDR)\n"
                "7. Statu quo (non recommande)\n\n"
                "## Citations\n"
                "- Banque mondiale - Note climat-developpement 2024\n"
                "- Reglement europeen anti-deforestation (EUDR)\n"
                "- Reuters 2025 - filiere cajou Cote d'Ivoire\n"
                "- Rapport Prefet Nawa - 10 mai 2026 (pp. 42-58)\n\n"
                "Document **advisory-only** soumis a validation Conseil des Ministres."
            ),
            "sources": [
                {"source_id": "report-prefet-nawa-2026-05-10"},
                {"source_id": "sentinel-ci-anacarde-diversification-v1"},
                {"source_id": "src-banque-mondiale-2024"},
                {"source_id": "src-eudr-2023"},
                {"source_id": "src-reuters-cajou-2025"},
            ],
            "context_refs": context_refs,
            "requires_validation": True,
            "advisory_only": True,
            "target_id": target_id,
        }
    return {
        "status": "draft",
        "template_kind": template_kind,
        "subject": "Rapport de diversification cacao — region Nawa (arbitrage cabinet)",
        "recipient": "Ministere de l'Economie — Direction filieres",
        "body_markdown": (
            "# Rapport de diversification cacao — Nawa\n\n"
            "## Contexte\nSuite au rapport Prefet Nawa (10 mai) et aux echanges a Soubre.\n\n"
            "## Option recommandee\nPetite industrie de transformation + diversification cultures.\n\n"
            "## Chiffrage indicatif\n4,2 a 6,8 milliards FCFA (ordres de grandeur publics).\n\n"
            "## Prochaines etapes\nArbitrage cabinet, puis RDV ministere de l'Economie."
        ),
        "sources": [
            {
                "source_id": "src-prefet-nawa-report-001",
                "document_id": "report-prefet-nawa-2026-05-10",
            }
        ],
        "requires_validation": True,
        "target_id": target_id,
    }
