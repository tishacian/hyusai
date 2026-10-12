"""SENTINEL-CI demo scenario content: guides, navigation, sources, signals and snapshots."""

from __future__ import annotations

from typing import Any


from app.models.workspace import Workspace
from app.services.mission_room.profile import (
    MISSION_ROOM_ROOT,
    SENTINEL_ASSISTANT_NAME,
    is_octocity_mission_room,
)


SENTINEL_KNOWLEDGE_GUIDES = (
    {
        "guide_key": "sentinel-ci-aya-mission-room-v1",
        "target_type": "scope",
        "target_ref": "vigie",
        "title": "Guide AYA - Mission Room SENTINEL-CI",
        "markdown": """# Guide AYA - Mission Room SENTINEL-CI

AYA agit comme adjoint souverain du Vice Premier Ministre. Elle s'adresse a l'utilisateur par "Monsieur le Vice Premier Ministre" et repond en priorisant : quoi faire, quand agir, pourquoi cette action est justifiee, et quelles sources brutes ou consolidees soutiennent la recommandation.

Principes d'interpretation :
- Distinguer les trois strates : Monitoring, Information & alerting, Decision & action.
- Ton attendu : formel, direct, phrases courtes, style briefing gouvernemental.
- Commencer les reponses de synthese par "Monsieur le Vice Premier Ministre," quand la formulation reste naturelle.
- Ne jamais traiter un guide comme une preuve brute : citer les articles, evenements agenda, zones, observations visuelles, projets ou actions sources.
- Les actions avec effet de bord restent advisory-only tant qu'elles ne sont pas confirmees.
- Les rumeurs doivent etre qualifiees par origine, propagation, zone, confiance et action recommandee.
- La cartographie sert a cadrer une zone ou un port ; elle ne remplace pas les sources textuelles ou operationnelles.

Lexique :
- "Situation Nord" : zone de vigilance prioritaire avant Conseil de 15h.
- "Langage public" : elements de reponse prudents et sourcés, sans envoi automatique.
- "Risque portuaire" : lecture Abidjan / San Pedro / douanes / corridor Golfe de Guinee.
- "Attention cabinet" : sujet avec deadline, responsable, action proposee et validation humaine.
""",
    },
    {
        "guide_key": "sentinel-ci-open-intelligence-v1",
        "target_type": "collection",
        "target_ref": "sentinel-ci-open-intelligence",
        "title": "Guide de lecture - Presse, rumeurs et OSINT",
        "markdown": """# Guide de lecture - Presse, rumeurs et OSINT

Cette collection regroupe articles RSS, syntheses News Lab et signaux publics demo-safe. AYA doit privilegier les signaux Cote d'Ivoire, puis CEDEAO, Afrique et Monde.

Regles :
- Identifier la source, la zone, le niveau de confiance et l'impact institutionnel.
- Ne pas presenter un volume brut comme decision : transformer en attention requise ou en sujet gerable.
- Les signaux sociaux prives ne sont pas connectes en v1 ; les rumeurs visibles sont publiques ou scenario de demonstration.
- Tout projet de reponse reste un brouillon soumis a validation.
""",
    },
    {
        "guide_key": "sentinel-ci-territorial-map-v1",
        "target_type": "collection",
        "target_ref": "sentinel-ci-territorial-intelligence",
        "title": "Guide territorial - Carte, zones et actions",
        "markdown": """# Guide territorial - Carte, zones et actions

La carte SENTINEL-CI sert a explorer, comprendre et decider. Les zones Nord, Ouest, Centre, Sud et Est sont des regroupements administratifs de lecture executive.

Regles :
- Associer chaque recommandation a des sources : presse, projet, agenda, visuel, maritime ou briefing.
- Rouge uniquement pour critique ; orange pour vigilance elevee ; vert pour nominal.
- Les commandes carte d'AYA peuvent focaliser, activer des couches et ouvrir les sources, mais ne declenchent pas une decision.
- Toujours proposer une fenetre d'action si une urgence est liee a l'agenda.
""",
    },
    {
        "guide_key": "sentinel-ci-doc-intelligence-v1",
        "target_type": "collection",
        "target_ref": "sentinel-ci-ministerial-briefs",
        "title": "Guide Document Intelligence - Briefs ministeriels",
        "markdown": """# Guide Document Intelligence - Briefs ministeriels

Les notes, briefings et fiches de preparation doivent etre citees avec fichier, section, page ou paragraphe quand disponible. Les extractions OCR ou visuelles doivent signaler leur confiance.

Regles :
- Citer la source brute avant le guide.
- Pour une procedure ou une fiche, repondre par etapes courtes.
- Pour un parametre ou une date, indiquer la section ou le paragraphe d'origine.
- Si OCR est absent ou faible, le signaler clairement plutot que combler.
""",
    },
    {
        "guide_key": "sentinel-ci-cacao-diversification-v1",
        "target_type": "scope",
        "target_ref": "vigie",
        "title": "Guide de lecture - Filiere cacao et diversification Nawa",
        "markdown": """# Guide de lecture - Filiere cacao et diversification Nawa

Ce guide explique comment lire la filiere cacao en region Nawa (Soubre). Il ne remplace pas les briefs ministeriels ni le rapport prefet du 10 mai.

Regles :
- Commencer par le rapport prefet Nawa (sent_at 2026-05-10) pour les faits terrain.
- Distinguer production brute, transformation locale, prix FCFA et besoins d'infrastructure.
- Les chiffrages d'investissement restent des ordres de grandeur publics ; toujours citer la section source.
- Relier les preconisations aux arbitrages cabinet (package-cacao-diversification) avant tout engagement.
""",
    },
)


NAVIGATION_ITEMS = [
    {
        "key": "cockpit",
        "label": "Cockpit",
        "glyph": "ledger",
        "variant": "government_mission_room",
        "object": "Workbench",
    },
    {
        "key": "strategie",
        "label": "Carte",
        "glyph": "sliders",
        "variant": "territorial_action_map",
        "object": "Workbench",
    },
    {
        "key": "securite",
        "label": "Securite",
        "glyph": "shield",
        "variant": "intelligence",
        "object": "Workbench",
    },
    {
        "key": "reputation",
        "label": "Reputation",
        "glyph": "pulse",
        "variant": "intelligence",
        "object": "Run",
    },
    {
        "key": "agenda",
        "label": "Agenda",
        "glyph": "ledger",
        "variant": "government_mission_room",
        "object": "Workbench",
    },
    {
        "key": "presse",
        "label": "Presse",
        "glyph": "pulse",
        "variant": "intelligence",
        "object": "Run",
    },
    {
        "key": "decisions",
        "label": "Arbitrages",
        "glyph": "check",
        "variant": "executive_instruction_drafting",
        "object": "Review Queue",
    },
]


OCTOCITY_NAVIGATION_ITEMS = [
    {
        "key": "cockpit",
        "label": "Cockpit",
        "glyph": "ledger",
        "variant": "octocity_mission_room",
        "object": "Workbench",
    },
    {
        "key": "strategie",
        "label": "Carte",
        "glyph": "sliders",
        "variant": "octocity_territorial_map",
        "object": "Workbench",
    },
    {
        "key": "securite",
        "label": "Securite",
        "glyph": "shield",
        "variant": "octocity_intelligence",
        "object": "Workbench",
    },
    {
        "key": "reputation",
        "label": "Reputation",
        "glyph": "pulse",
        "variant": "octocity_intelligence",
        "object": "Run",
    },
    {
        "key": "agenda",
        "label": "Agenda",
        "glyph": "ledger",
        "variant": "octocity_mission_room",
        "object": "Workbench",
    },
    {
        "key": "presse",
        "label": "Presse",
        "glyph": "pulse",
        "variant": "octocity_intelligence",
        "object": "Run",
    },
    {
        "key": "decisions",
        "label": "Arbitrages",
        "glyph": "check",
        "variant": "octocity_decision_desk",
        "object": "Review Queue",
    },
]

_NAVIGATION_REQUIRED_FIELDS = ("key", "label", "glyph", "variant", "object")


def _default_navigation_items(workspace: Workspace) -> list[dict[str, Any]]:
    defaults = (
        OCTOCITY_NAVIGATION_ITEMS if is_octocity_mission_room(workspace) else NAVIGATION_ITEMS
    )
    return [dict(item) for item in defaults]


def _validated_navigation_items(
    workspace: Workspace,
    configured_navigation: Any,
) -> list[dict[str, Any]]:
    """Return a complete, stable workspace navigation or its safe default.

    Mission Room navigation is a seven-item shell contract.  A partially
    written JSON setting must not silently truncate the shell, and malformed
    rows must never turn a navigation request into a 500.  Valid custom labels
    and variants remain supported when the full key set is present.
    """
    defaults = _default_navigation_items(workspace)
    expected_keys = [item["key"] for item in defaults]
    if not isinstance(configured_navigation, list) or len(configured_navigation) != len(defaults):
        return defaults

    configured_by_key: dict[str, dict[str, Any]] = {}
    for raw_item in configured_navigation:
        if not isinstance(raw_item, dict):
            return defaults
        item = dict(raw_item)
        if any(
            not isinstance(item.get(field), str) or not str(item[field]).strip()
            for field in _NAVIGATION_REQUIRED_FIELDS
        ):
            return defaults
        key = str(item["key"])
        if key not in expected_keys or key in configured_by_key:
            return defaults
        configured_by_key[key] = item

    if set(configured_by_key) != set(expected_keys):
        return defaults
    return [configured_by_key[key] for key in expected_keys]


SOURCES = [
    {
        "id": "src-cabinet-brief-001",
        "label": "Note cabinet - situation nord",
        "kind": "internal_note",
        "confidence": 0.86,
        "age": "06:40",
    },
    {
        "id": "src-press-rfi-017",
        "label": "Flux presse Afrique - tensions locales",
        "kind": "rss_press",
        "confidence": 0.72,
        "age": "08:12",
    },
    {
        "id": "src-press-ci-local-001",
        "label": "Presse ivoirienne - politique interieure",
        "kind": "rss_press_local",
        "confidence": 0.77,
        "age": "flux continu",
    },
    {
        "id": "src-press-cedeao-001",
        "label": "Veille CEDEAO / Golfe de Guinee",
        "kind": "rss_press_regional",
        "confidence": 0.73,
        "age": "flux continu",
    },
    {
        "id": "src-social-watch-001",
        "label": "Social listening public - rumeurs et origines",
        "kind": "social_signal_demo",
        "confidence": 0.61,
        "age": "12 min",
    },
    {
        "id": "src-project-sante-042",
        "label": "Dossier projet - centres de sante frontaliers",
        "kind": "project_record",
        "confidence": 0.81,
        "age": "hier",
    },
    {
        "id": "src-agenda-jour-015",
        "label": "Agenda ministeriel autorise",
        "kind": "calendar",
        "confidence": 0.94,
        "age": "aujourd'hui",
    },
    {
        "id": "src-visual-intelligence-001",
        "label": "Flux visuels institutionnels",
        "kind": "visual_stream",
        "confidence": 0.68,
        "age": "capture recente",
    },
    {
        "id": "src-maritime-paa-001",
        "label": "Port Autonome d'Abidjan - actualites",
        "kind": "rss_maritime_local",
        "confidence": 0.79,
        "age": "flux RSS",
    },
    {
        "id": "src-maritime-marinelink-001",
        "label": "MarineLink - maritime news",
        "kind": "rss_maritime_world",
        "confidence": 0.71,
        "age": "flux RSS",
    },
    {
        "id": "src-marinetraffic-context-001",
        "label": "MarineTraffic - contexte AIS/API-ready",
        "kind": "maritime_ais_context",
        "confidence": 0.64,
        "age": "source externe",
    },
    {
        "id": "src-prefet-nawa-report-001",
        "label": "Rapport Prefet Nawa - 10 mai 2026",
        "kind": "ministerial_brief",
        "confidence": 0.91,
        "age": "13 jours",
    },
    {
        "id": "src-abidjan-net-drone-napie-2025-07-16",
        "label": "Abidjan.net — Lancement Centre Formation Drones Napié",
        "kind": "rss_news_ci",
        "url": (
            "https://news.abidjan.net/articles/743173/"
            "cote-divoire-lancement-des-travaux-de-construction-du-centre-international-"
            "de-formation-aux-metiers-des-drones-a-napie"
        ),
        "publisher": "Abidjan.net",
        "published_at": "2025-07-16",
        "confidence": 0.83,
        "age": "publié 2025-07-16",
    },
    {
        "id": "src-note-posture-sahel-2026-05-25",
        "label": "Note posture sécurité Sahel — 25 mai 2026",
        "kind": "security_brief",
        "confidence": 0.78,
        "age": "ce matin",
    },
    {
        "id": "src-conseil-defense-2026-05-25-am",
        "label": "Synthèse Conseil Défense restreint — 08h30",
        "kind": "security_brief",
        "confidence": 0.82,
        "age": "ce matin",
    },
    {
        "id": "src-rumor-frontier-nord-2026-05-25",
        "label": "Dossier rumeur frontière Nord — chronologie OSINT et démentis",
        "kind": "rumor_dossier",
        "confidence": 0.74,
        "age": "ce midi",
    },
    {
        "id": "src-social-snapshot-2026-05-25",
        "label": "Snapshot social Abidjan — pulsation 14h25",
        "kind": "social_snapshot",
        "confidence": 0.66,
        "age": "il y a 30 min",
    },
    {
        "id": "src-troops-sahel-2026-05-25",
        "label": "Snapshot ADS-B advisory Sahel — 14h30",
        "kind": "ads_b_advisory",
        "confidence": 0.62,
        "age": "il y a 30 min",
    },
    {
        "id": "src-press-jeune-afrique-001",
        "label": "Jeune Afrique — gestion Nord saluée",
        "kind": "rss_press_world",
        "confidence": 0.78,
        "age": "22 mai 2026",
    },
    {
        "id": "src-press-fratmat-nawa-001",
        "label": "Fraternité Matin — réponse rapide au Préfet Nawa",
        "kind": "rss_press_local",
        "confidence": 0.79,
        "age": "23 mai 2026",
    },
]

AGENDA = [
    {
        "time": "08:30",
        "title": "Conseil Defense restreint",
        "location": "Salle du Conseil - Plateau",
        "tone": "urgent",
    },
    {
        "id": "evt-prefet-nawa",
        "time": "11:00",
        "title": "Rencontre Prefet de la region de Nawa",
        "location": "Soubre (capitale regionale)",
        "tone": "watch",
        "context_ref": "report-prefet-nawa-2026-05-10",
    },
    {
        "time": "11:00",
        "title": "Point presse hebdomadaire",
        "location": "Salle presse ministere",
        "tone": "watch",
    },
    {
        "time": "13:00",
        "title": "Dejeuner Ambassadeur de France",
        "location": "Residence officielle",
        "tone": "neutral",
    },
    {
        "time": "15:00",
        "title": "Revue operations Sahel",
        "location": "Centre de commandement",
        "tone": "watch",
    },
    {
        "time": "17:40",
        "title": "Audience parlementaire",
        "location": "Assemblee Nationale",
        "tone": "neutral",
    },
]

PRIORITIES = [
    {
        "id": "prio-meeting-france",
        "kind": "next_meeting",
        "title": "Dejeuner Ambassadeur de France",
        "summary": "Trois points sensibles : cooperation FR-CI, image presse, suivi projets frontaliers.",
        "deadline": "dans 1h46",
        "sources": ["src-agenda-jour-015", "src-cabinet-brief-001"],
        "tone": "info",
    },
    {
        "id": "prio-security-north",
        "kind": "urgent",
        "title": "Situation securitaire nord",
        "summary": (
            "Cause racine : retard Centre Drones Napie (120 jours) + cargo MV Atlantic Trader "
            "bloque a Vridi. Signal frontalier secondaire (Gen. Konate) a tenir distinct."
        ),
        "deadline": "avant conseil restreint",
        "sources": ["src-cabinet-brief-001", "src-press-rfi-017"],
        "tone": "critical",
    },
    {
        "id": "prio-mail-konaté",
        "kind": "mail",
        "title": "Email prioritaire - Gen. Konate (signal frontalier secondaire)",
        "summary": (
            "Demande d'arbitrage sur reception de materiels et communication preventive. "
            "Signal regional independant de la cause racine economique (chantier Napie)."
        ),
        "deadline": "09:15",
        "sources": ["src-cabinet-brief-001"],
        "tone": "watch",
    },
]

NEWS_SIGNALS = [
    {
        "id": "news-001",
        "title": "Rumeur persistante sur retards de programmes sociaux au nord",
        "risk_level": "high",
        "sentiment": "negative",
        "summary": "Plusieurs reprises presse et canaux locaux convergent vers un risque de perception d'abandon.",
        "source": "Presse ivoirienne + flux RSS Afrique",
        "sources": ["src-press-ci-local-001", "src-press-rfi-017"],
        "zone": "Cote d'Ivoire",
        "geography_tier": "ci",
        "viewpoint": "politique interieure ivoirienne",
        "origin": "Boucles locales + presse nationale",
        "recommended_action": "Demander a AYA une note de clarification et proposer une visite terrain non militaire.",
    },
    {
        "id": "news-002",
        "title": "Cooperation FR-CI : reprise positive apres annonce infrastructure",
        "risk_level": "medium",
        "sentiment": "positive",
        "summary": "Le narratif institutionnel s'ameliore, mais reste fragile si les livrables terrain glissent.",
        "source": "Presse internationale",
        "sources": ["src-press-rfi-017", "src-project-sante-042"],
        "zone": "International / Cote d'Ivoire",
        "geography_tier": "world",
        "viewpoint": "politique internationale",
        "origin": "Presse internationale Afrique / Europe",
    },
    {
        "id": "news-003",
        "title": "Tensions nord CI : besoin d'un message preventif non militaire",
        "risk_level": "high",
        "sentiment": "mixed",
        "summary": "Signal faible recurrent ; action proposee : communication locale + rencontre autorites.",
        "source": "Veille ouverte",
        "sources": ["src-cabinet-brief-001", "src-press-cedeao-001"],
        "zone": "Nord CI / CEDEAO",
        "geography_tier": "cedeao",
        "viewpoint": "politique regionale",
        "origin": "Signaux territoriaux + contexte transfrontalier",
    },
    {
        "id": "social-001",
        "title": "Emoi public apres un deces tragique relayé sur canaux sociaux",
        "risk_level": "high",
        "sentiment": "negative",
        "summary": "Une rumeur fortement partagee evoque un deces tragique et cristallise une attente de presence institutionnelle.",
        "source": "Social listening public demo",
        "sources": ["src-social-watch-001", "src-press-ci-local-001"],
        "zone": "Abidjan / Cote d'Ivoire",
        "geography_tier": "ci",
        "viewpoint": "politique interieure ivoirienne",
        "origin": "X public + pages Facebook publiques + relais WhatsApp signales par cellule terrain",
        "impact_ci": "Signal emotionnel interieur : recommander une action mediatique et physique forte, sous validation humaine.",
        "why_it_matters": "Le risque n'est pas seulement informationnel : il touche l'empathie publique, la presence terrain et la credibilite institutionnelle.",
        "recommended_action": "Qualifier la source primaire, preparer un message de compassion, puis proposer une presence terrain coordonnee.",
        "confidence": 0.61,
        "source_count": 3,
    },
    {
        "id": "news-maritime-001",
        "title": "Port d'Abidjan : signal maritime a rapprocher des points douanes",
        "risk_level": "medium",
        "sentiment": "mixed",
        "summary": "Actualite portuaire et veille maritime convergent vers un point d'attention logistique : inspection, congestion ou retard doivent etre qualifies avant prise de parole economique.",
        "source": "Port Autonome d'Abidjan + veille maritime internationale",
        "sources": [
            "src-maritime-paa-001",
            "src-maritime-marinelink-001",
            "src-marinetraffic-context-001",
        ],
        "zone": "Abidjan / Golfe de Guinee",
        "geography_tier": "ci",
        "geo_tier": "ci",
        "viewpoint": "douanes, securite portuaire et flux economiques",
        "origin": "RSS Port Autonome d'Abidjan + MarineLink + contexte MarineTraffic",
        "domain": "port_flow",
        "source_type": "rss",
        "tags": ["port", "douanes", "congestion", "retard", "securite maritime", "Golfe de Guinee"],
        "impact_ci": "Impact interieur : anticiper congestion, retards douaniers ou perception de rupture logistique autour du port.",
        "impact_international": "Impact international : surveiller perception investisseurs, chaines logistiques et partenaires commerciaux.",
        "why_it_matters": "Le port d'Abidjan est un signal economique et securitaire ; un incident ou retard visible peut devenir sujet presse, douanes et cabinet.",
        "recommended_action": "Demander une confirmation douanes/port avant 12h00, puis preparer une note Vice Premier Ministre si le signal se confirme.",
        "briefing_value": "Ajoute une preuve maritime au brief : port, douanes, flux economiques et communication gouvernementale.",
        "confidence": 0.66,
        "source_count": 3,
        "evidence_refs": [
            {"type": "rss", "id": "src-maritime-paa-001", "label": "RSS Port Autonome d'Abidjan"},
            {
                "type": "rss",
                "id": "src-maritime-marinelink-001",
                "label": "MarineLink maritime news",
            },
            {
                "type": "source",
                "id": "src-marinetraffic-context-001",
                "label": "MarineTraffic AIS/API-ready",
            },
        ],
        "aya_context": {
            "prompt": "AYA, relie ce signal portuaire aux douanes, au trafic maritime et au risque de congestion.",
            "answer_frame": "Situation portuaire, preuve maritime, impact douanes/securite, option recommandee, deadline, confiance.",
            "confidence": 0.66,
        },
    },
]

SENTINEL_NEWS_FEEDS = [
    ("7info CI", "https://www.7info.ci/feed/", "ci-local"),
    ("Agence Ivoirienne de Presse", "https://www.aip.ci/feed/", "ci-agency"),
    ("RTI Info", "https://rti.info/feed/", "ci-public"),
    ("Connection Ivoirienne", "https://connectionivoirienne.net/feed/", "ci-local"),
    ("Fraternite Matin", "https://beta.fratmat.info/rssFeed/0", "ci-national"),
    ("BBC Africa", "https://feeds.bbci.co.uk/news/world/africa/rss.xml", "africa"),
    ("Jeune Afrique", "https://www.jeuneafrique.com/feed/", "africa-fr"),
    (
        "AllAfrica West Africa",
        "https://allafrica.com/tools/headlines/rdf/westafrica/headlines.rdf",
        "cedeao",
    ),
    ("Africanews", "https://www.africanews.com/feed/rss", "africa"),
    ("France 24 Afrique", "https://www.france24.com/fr/afrique/rss", "afrique"),
    ("RFI Afrique", "https://www.rfi.fr/fr/afrique/rss", "afrique"),
    ("BBC World News", "https://feeds.bbci.co.uk/news/world/rss.xml", "world"),
    ("Port Autonome d'Abidjan", "https://www.portabidjan.ci/rss.xml", "ci-maritime"),
    ("MarineLink Maritime News", "https://www.marinelink.com/news/rss", "maritime-world"),
]

GEOGRAPHIC_PRIORITY_ORDER = [
    (
        "ci",
        "Cote d'Ivoire",
        "Priorite absolue pour le Vice Premier Ministre et le pilotage interieur.",
    ),
    (
        "cedeao",
        "CEDEAO / voisins immediats",
        "Effets transfrontaliers, perception regionale et coordination diplomatique.",
    ),
    ("africa", "Afrique", "Contexte continental utile aux arbitrages et aux messages publics."),
    ("world", "Monde", "Europe, Asie, USA et partenaires internationaux a garder en contrepoint."),
]

FEED_CATEGORY_SCOPE = {
    "ci-local": "ci",
    "ci-agency": "ci",
    "ci-public": "ci",
    "ci-national": "ci",
    "cedeao": "cedeao",
    "west-africa": "cedeao",
    "africa": "africa",
    "africa-fr": "africa",
    "afrique": "africa",
    "world": "world",
    "ci-maritime": "ci",
    "maritime-world": "world",
}

MARITIME_PORTS = [
    {
        "id": "port-abidjan",
        "name": "Port autonome d'Abidjan",
        "location": "Abidjan / Vridi",
        "longitude": -4.0083,
        "latitude": 5.2512,
        "score": 68,
        "tone": "elevated",
        "role": "hub economique et douanier prioritaire",
    },
    {
        "id": "port-san-pedro",
        "name": "Port autonome de San-Pedro",
        "location": "San-Pedro",
        "longitude": -6.6368,
        "latitude": 4.7446,
        "score": 44,
        "tone": "monitoring",
        "role": "flux export et surveillance logistique",
    },
]

MARITIME_EVENTS = [
    {
        "id": "cargo-abidjan-supply-001",
        "title": "Cargo composants drones Napié — attente dedouanement Abidjan",
        "location": "Port autonome d'Abidjan / zone Vridi",
        "longitude": -4.02,
        "latitude": 5.24,
        "score": 74,
        "severity": "elevated",
        "domain": "customs",
        "status": "awaiting_customs",
        "vessel_name": "MV Atlantic Trader",
        "cargo": (
            "Composants drones AerostarDynamics — hangars formation, "
            "terrains apprentissage, labos cartographie (Centre Napié)"
        ),
        "origin": "USA East Coast",
        "destination": "Napié via Port autonome d'Abidjan",
        "project_ref": "proj-drone-centre-napie",
        "project_ref_aliases": ["proj-public-north-supply"],
        "summary": (
            "Cargaison de composants drones Aerostar Dynamics destinée au Centre "
            "International de Formation aux Métiers des Drones de Napié bloquée à "
            "Vridi par effet collatéral du PV douanes du 18 mai."
        ),
        "recommended_action": "Preparer courrier de priorisation douanes et port avant arbitrage cabinet.",
        "decision_deadline": "12:00",
        "source_type": "ais+fixture",
        "source_refs": [
            "src-maritime-paa-001",
            "src-marinetraffic-context-001",
            "src-cabinet-brief-001",
            "src-abidjan-net-drone-napie-2025-07-16",
        ],
    },
    {
        "id": "maritime-abidjan-customs-watch",
        "title": "Point d'attention Port d'Abidjan / douanes",
        "location": "Port autonome d'Abidjan",
        "longitude": -4.0083,
        "latitude": 5.2512,
        "score": 68,
        "severity": "elevated",
        "domain": "customs",
        "summary": "Activite portuaire a rapprocher d'une actualite douanes/logistique avant toute communication economique.",
        "recommended_action": "Verifier aupres du Port et des Douanes avant 12h00 ; preparer une note Vice Premier Ministre si congestion ou inspection sensible se confirme.",
        "decision_deadline": "12:00",
        "source_type": "rss+api_ready",
        "source_refs": [
            "src-maritime-paa-001",
            "src-maritime-marinelink-001",
            "src-marinetraffic-context-001",
        ],
    },
    {
        "id": "maritime-gulf-security-watch",
        "title": "Golfe de Guinee : veille securite maritime",
        "location": "Golfe de Guinee",
        "longitude": -3.9,
        "latitude": 5.8,
        "score": 52,
        "severity": "monitoring",
        "domain": "maritime_security",
        "summary": "Contexte regional a garder en contrepoint des flux commerciaux et des alertes internationales.",
        "recommended_action": "Maintenir en veille et rapprocher de la cellule economique si un incident touche les corridors Abidjan/San-Pedro.",
        "decision_deadline": "aujourd'hui",
        "source_type": "rss+source_link",
        "source_refs": ["src-maritime-marinelink-001", "src-marinetraffic-context-001"],
    },
]

MESSAGES = [
    {
        "id": "msg-konate-001",
        "from": "Gen. Konate",
        "subject": "Situation securitaire nord (signal frontalier secondaire)",
        "time": "09:15",
        "priority": "urgent",
        "summary": (
            "Demande d'arbitrage sur reception de materiels et communication preventive. "
            "Signal frontalier independant de la cause racine economique (retard chantier Napie + cargo MV Atlantic Trader)."
        ),
        "sources": ["src-cabinet-brief-001"],
    },
    {
        "id": "msg-cabinet-014",
        "from": "Directeur de cabinet",
        "subject": "Elements de langage point presse",
        "time": "10:05",
        "priority": "watch",
        "summary": "Validation attendue avant 11h pour clarifier la position institutionnelle.",
        "sources": ["src-agenda-jour-015", "src-press-rfi-017"],
    },
    {
        "id": "msg-territory-027",
        "from": "Cellule coordination terrain",
        "subject": "Suivi projets frontaliers",
        "time": "10:42",
        "priority": "normal",
        "summary": "Remontee terrain coherente avec les risques projet et la veille presse.",
        "sources": ["src-project-sante-042"],
    },
]

DECISIONS = [
    {
        "id": "decision-north-mission",
        "title": "Mission terrain preventive Nord",
        "status": "validation_required",
        "risk": "high",
        "recommendation": "Valider une mission non militaire coordonnee avec autorites locales et communication ciblee.",
        "target_id": "zone-nord",
        "target_type": "zone",
        "sources": ["src-cabinet-brief-001", "src-project-sante-042", "src-press-rfi-017"],
    },
    {
        "id": "decision-project-red",
        "title": "Relance cabinet projet centres de sante",
        "status": "draft_ready",
        "risk": "high",
        "recommendation": "Demander note d'arbitrage sous 24h avec options budget, terrain et replanification.",
        "target_id": "proj-health-north",
        "target_type": "project",
        "sources": ["src-project-sante-042", "src-cabinet-brief-001"],
    },
    {
        "id": "decision-press-lines",
        "title": "Elements de langage presse",
        "status": "review",
        "risk": "medium",
        "recommendation": "Valider un message de coordination preventive et de continuite des services publics.",
        "target_id": "proj-civic-radio",
        "target_type": "project",
        "sources": ["src-press-rfi-017", "src-agenda-jour-015"],
    },
]

DECISION_SENTENCE = {
    "label": "Sentence du jour",
    "text": "Monsieur le Vice Premier Ministre, votre priorité absolue ce matin est la Zone Nord. Tout le reste peut attendre.",
    "generated_by": SENTINEL_ASSISTANT_NAME,
    "refresh_policy": "mise a jour horaire ou nouvelle alerte critique",
    "deadline": "avant Conseil 15h00",
    "source_refs": ["src-cabinet-brief-001", "src-press-ci-local-001", "src-agenda-jour-015"],
}

ATTENTION_REQUIRED = [
    {
        "id": "attention-inter-budget",
        "rank": 1,
        "title": "Article L'Inter - critique personnelle sur budget defense",
        "sentence": "Reponse recommandee avant 14h00.",
        "action_label": "Voir le projet de reponse",
        "deadline": "14:00",
        "status": "draft_ready",
        "tone": "critical",
        "next_step": "Preparer un email au responsable communication",
        "action_route": f"{MISSION_ROOM_ROOT}/presse",
        "draft_target_type": "press_response",
        "draft_recipient": "Responsable communication",
        "source_refs": ["src-press-ci-local-001"],
    },
    {
        "id": "attention-zone-nord",
        "rank": 2,
        "title": "Zone Nord - retard chantier Napie + cargo bloque (cause racine)",
        "sentence": (
            "Tension territoriale Nord — cause racine : retard du Centre Drones Napie "
            "(120 jours) et cargo MV Atlantic Trader bloque a Vridi. Options secondaires : "
            "renforcement preventif ou coordination CEDEAO sur effets regionaux. "
            "A arbitrer avant Conseil 15h00."
        ),
        "action_label": "Arbitrer les options",
        "deadline": "15:00",
        "status": "decision_required",
        "tone": "critical",
        "next_step": "Choisir l'option a porter au Conseil",
        "action_route": f"{MISSION_ROOM_ROOT}/strategie",
        "draft_target_type": "zone",
        "draft_recipient": "Directeur de cabinet",
        "source_refs": [
            "src-cabinet-brief-001",
            "src-press-cedeao-001",
            "src-abidjan-net-drone-napie-2025-07-16",
            "src-maritime-paa-001",
        ],
    },
    {
        "id": "attention-ambassadeur-france",
        "rank": 3,
        "title": "Ambassadeur France - dejeuner dans 1h44",
        "sentence": "Fiche de preparation deja prete pour cadrer cooperation, presse et projets frontaliers.",
        "action_label": "Ouvrir la fiche",
        "deadline": "13:00",
        "status": "brief_ready",
        "tone": "watch",
        "next_step": "Ouvrir la fiche et les elements de langage",
        "action_route": f"{MISSION_ROOM_ROOT}/decisions",
        "draft_target_type": "briefing_note",
        "draft_recipient": "Conseiller diplomatique",
        "source_refs": ["src-agenda-jour-015", "src-project-sante-042"],
    },
]

TERRITORIAL_LIVE_STATUS = [
    {
        "zone": "Nord",
        "level": "CRITIQUE",
        "bars": 4,
        "summary": "Incident frontiere · 06h14",
        "tone": "critical",
    },
    {
        "zone": "Ouest",
        "level": "SURVEILLANCE",
        "bars": 3,
        "summary": "Mouvements inhabituels",
        "tone": "watch",
    },
    {
        "zone": "Centre",
        "level": "STABLE",
        "bars": 2,
        "summary": "Institutions nominales",
        "tone": "stable",
    },
    {
        "zone": "Sud",
        "level": "OPERATIONNEL",
        "bars": 1,
        "summary": "Abidjan nominal",
        "tone": "stable",
    },
    {
        "zone": "Est",
        "level": "SURVEILLANCE",
        "bars": 3,
        "summary": "Frontiere Ghana",
        "tone": "watch",
    },
]

VOICE_DEMO_SCRIPT = {
    "prompt": "AYA, pourquoi la situation Nord est-elle tendue ?",
    "answer": (
        "Monsieur le Vice Premier Ministre, la tension Nord remonte au retard du chantier "
        "Centre International Formation Drones — Napié (Poro) : 120 jours de "
        "décalage, composants Aerostar Dynamics bloqués au port d'Abidjan "
        "sur cargo MV Atlantic Trader (effet collatéral PV douanes 18 mai). "
        "Recommandation : dérogation Chef Douanes — brouillon prêt."
    ),
    "target_latency_s": 6,
}

EXECUTIVE_DECISION_PACKAGES = [
    {
        "id": "package-zone-nord",
        "label": "Dossier de decision",
        "title": "Zone Nord - arbitrage avant Conseil",
        "decision": (
            "Cause racine identifiee : retard Centre Drones Napie + cargo MV Atlantic Trader "
            "bloque (effet collateral PV douanes 18 mai). Arbitrer la priorisation "
            "dedouanement (cause racine) et la coordination CEDEAO (signal frontalier "
            "secondaire) avant 15h00."
        ),
        "recommended_option": (
            "Priorisation dedouanement cargo Napie + coordination CEDEAO en appui sur le "
            "contexte regional secondaire."
        ),
        "why_now": "La sequence presse de 14h00 peut amplifier la tension si aucune posture n'est annoncee.",
        "deadline": "15:00",
        "owner": "Directeur de cabinet",
        "confidence": 0.78,
        "status": "decision_required",
        "tone": "critical",
        "sources": [
            "Carte Nord",
            "Presse CI",
            "Agenda Conseil",
            "Flux visuels Abidjan",
            "PV douanes 18 mai",
            "Abidjan.net Centre Drones Napie",
        ],
        "cta": "Faire lire par AYA",
    },
    {
        "id": "package-rumeur-emoi",
        "label": "Reponse publique",
        "title": "Emoi public - rumeur a contenir",
        "decision": "Valider un message de compassion et une verification terrain avant 12h30.",
        "recommended_option": "Message court + contact prefectoral + point source confirme",
        "why_now": "Le signal part de WhatsApp local, rebondit sur X puis commence a toucher la presse nationale.",
        "deadline": "12:30",
        "owner": "Communication Presidence",
        "confidence": 0.71,
        "status": "draft_ready",
        "tone": "elevated",
        "sources": ["WhatsApp public", "X", "Facebook local", "Presse nationale"],
        "cta": "Ouvrir les elements de langage",
    },
    {
        "id": "package-france-brief",
        "label": "Preparation agenda",
        "title": "Ambassadeur France - dejeuner",
        "decision": "Cadrer la position sur cooperation frontaliere et perception presse avant l'entretien.",
        "recommended_option": "Brief 3 points + ligne rouge + opportunite projets",
        "why_now": "La rencontre intervient apres une critique budgetaire et avant la sequence presse.",
        "deadline": "13:00",
        "owner": "Conseiller diplomatique",
        "confidence": 0.83,
        "status": "brief_ready",
        "tone": "watch",
        "sources": ["Agenda", "Presse internationale", "Brief ministeriel"],
        "cta": "Ouvrir la fiche de preparation",
    },
    {
        "id": "package-cacao-diversification",
        "label": "Diversification agricole",
        "title": "Diversification cacao — RDV Ministere Economie",
        "decision": "Arbitrer petite industrie transformation vs cooperative renforcee vs PPP sechoirs.",
        "recommended_option": "Petite industrie transformation + diversification cultures",
        "why_now": "Le rapport prefet Nawa (10 mai) chiffre les besoins ; fenetre avant saison export.",
        "deadline": "semaine",
        "owner": "Direction filieres agricoles",
        "confidence": 0.76,
        "status": "pending_arbitration",
        "tone": "watch",
        "sources": ["Rapport Prefet Nawa", "Guide cacao", "News Lab ICCO"],
        "cta": "Caler le RDV ministre Economie",
        "project_ref": "proj-cacao-transformation-nawa",
    },
    {
        "id": "package-securite-dual",
        "label": "Posture sécuritaire",
        "title": "Posture sécuritaire dual-axis — intérieur et extérieur",
        "decision": (
            "Confirmer la posture sécuritaire combinée : vigilance frontière Nord après rumeur "
            "OSINT démentie à 13h46, et lecture ADS-B advisory sur le théâtre Sahel "
            "(Bamako/Ouaga/Niamey) avant le Conseil Défense de 15h00."
        ),
        "recommended_option": (
            "Maintenir la posture VIGILANCE en intérieur + ÉLEVÉE en extérieur Sahel, "
            "communiquer le démenti officiel de la rumeur frontière Nord, et préparer "
            "un point Conseil 15h00 sur la coordination CEDEAO."
        ),
        "why_now": "Le Conseil Défense restreint 15h00 attend une posture consolidée.",
        "deadline": "15:00",
        "owner": "Conseiller sécurité",
        "confidence": 0.81,
        "status": "decision_required",
        "tone": "elevated",
        "sources": [
            "Note posture sécurité Sahel",
            "Synthèse Conseil Défense 08h30",
            "Dossier rumeur frontière Nord",
            "Pulsation sociale Abidjan",
        ],
        "cta": "Ouvrir la posture sécuritaire",
    },
]

# ---------------------------------------------------------------------------
# S3 — Posture sécuritaire dual-axis
#
# Scenario 3 fixtures: interior Nord/Abidjan + exterior Sahel theater snapshot
# used by the ``aya_security_v1`` action pack and the cockpit ``security_posture``
# block. Everything below is demo-safe seed data (no live feed): Twitter handles
# are pseudonymised, ADS-B callsigns are advisory-only, the reputation drill
# reuses the L'Inter critique already seeded in S1, and the rumeur frontière
# chain matches the dossier_rumeur_frontiere_nord_2026-05-25.md KB document.
# ---------------------------------------------------------------------------

SECURITY_POSTURE = {
    "summary": "Posture dual-axis : vigilance intérieure · Sahel élevé.",
    "next_council": {
        "label": "Conseil Défense restreint — revue Sahel",
        "time": "15:00",
        "date": "2026-05-25",
        "event_seed_id": "evt-revue-sahel",
        "location": "Centre de commandement",
    },
    "interior": {
        "axis": "interieur",
        "label": "Intérieur (Nord + Abidjan)",
        "level": "vigilance",
        "tone": "elevated",
        "score": 64,
        "trend": "stable",
        "headline": "Frontière Nord — rumeur OSINT démentie à 13h46, posture nominale rétablie.",
        "signals": [
            {
                "id": "sig-interior-nord-rumor",
                "label": "Rumeur frontière Nord (Bouna/Kong)",
                "tone": "watch",
                "summary": "Tweet d'un compte citoyen, repris sur Telegram et un blog régional, démenti officiel publié à 13h46.",
                "sources": ["src-rumor-frontier-nord-2026-05-25"],
            },
            {
                "id": "sig-interior-abidjan-mood",
                "label": "Climat social Abidjan (Plateau · Cocody)",
                "tone": "stable",
                "summary": "Pulsation sociale mesurée : 4 signaux positifs, 10 neutres, 4 critiques ou rumeur, sans emballement après les démentis.",
                "sources": ["src-social-snapshot-2026-05-25"],
            },
            {
                "id": "sig-interior-nord-trafic",
                "label": "Trafic axe Korhogo — Ferké",
                "tone": "stable",
                "summary": "Postes mixtes nominaux, pas de signalement d'incident terrain dans les dernières 6 heures.",
                "sources": ["src-cabinet-brief-001"],
            },
        ],
        "actions_recommended": [
            "Confirmer le démenti officiel sur les canaux institutionnels",
            "Préparer 3 éléments de langage courts pour le Conseil 15h",
        ],
    },
    "exterior": {
        "axis": "exterieur",
        "label": "Extérieur (théâtre Sahel)",
        "level": "elevee",
        "tone": "watch",
        "score": 74,
        "trend": "up",
        "headline": "Théâtre Sahel : activité ADS-B advisory soutenue sur l'axe Bamako/Ouaga/Niamey.",
        "signals": [
            {
                "id": "sig-exterior-sahel-ads-b",
                "label": "Activité ADS-B advisory (Bamako/Ouaga/Niamey)",
                "tone": "watch",
                "summary": "10 traces ADS-B advisory (snapshot 14h30) — callsigns logistiques régionaux et publics.",
                "sources": ["src-troops-sahel-2026-05-25"],
            },
            {
                "id": "sig-exterior-sahel-cedeao",
                "label": "Coordination CEDEAO",
                "tone": "watch",
                "summary": "2 bases CEDEAO en alerte standard (Abidjan logistique + corridor Mali).",
                "sources": ["src-conseil-defense-2026-05-25-am"],
            },
            {
                "id": "sig-exterior-osint-sahel",
                "label": "OSINT public Sahel (ACLED-like)",
                "tone": "watch",
                "summary": "3 zones de surveillance active : Liptako-Gourma, frontière Mali/Burkina, région de Tillabéri.",
                "sources": ["src-note-posture-sahel-2026-05-25"],
            },
        ],
        "actions_recommended": [
            "Présenter la lecture OSINT publique en ouverture du Conseil 15h",
            "Confirmer la posture advisory-only sur les flux ADS-B régionaux",
        ],
    },
}

# ----------------------------------------------------------------------------
# Snapshot Twitter figé (demo-safe). Les comptes officiels sont des comptes
# institutionnels publics; les comptes citoyens sont pseudonymisés @citoyen_***
# et les comptes rumeur frontière sont en @rumeur_*** pour éviter toute
# confusion avec de vrais individus. Géocoordonnées centrées Abidjan
# (Plateau / Cocody) + 3 points Bouna/Korhogo pour la rumeur frontière.
# ----------------------------------------------------------------------------

SOCIAL_SNAPSHOT = {
    "captured_at": "2026-05-25T14:25:00",
    "window_label": "Pulsation sociale — séquence 08h30-14h25",
    "city_focus": "Abidjan",
    "totals": {
        "tweets": 18,
        "officiel": 5,
        "citoyen": 8,
        "rumeur": 5,
        "engagement_total": 5992,
        "sentiment_positive": 4,
        "sentiment_neutral": 10,
        "sentiment_negative": 4,
    },
    "tweets": [
        # --- 5 officiels (handles publics institutionnels) -----------------
        {
            "id": "tweet-off-001",
            "kind": "officiel",
            "handle": "@PresidenceCI",
            "author": "Présidence de la République de Côte d'Ivoire",
            "verified": True,
            "text": "Le Conseil Défense restreint se tiendra à 15h00 pour revue de la coordination CEDEAO et de la posture régionale.",
            "language": "fr",
            "sentiment": "neutral",
            "engagement": 1240,
            "retweets": 312,
            "likes": 928,
            "geo": {"label": "Abidjan / Plateau", "longitude": -4.0244, "latitude": 5.3253},
            "posted_at": "2026-05-25T13:48:00",
            "tags": ["officiel", "conseil-defense"],
        },
        {
            "id": "tweet-off-002",
            "kind": "officiel",
            "handle": "@FANCIofficiel",
            "author": "Forces Armées Nationales de Côte d'Ivoire",
            "verified": True,
            "text": "Démenti officiel : aucune incursion confirmée à la frontière Nord. Les postes mixtes sont nominaux. Source : État-Major.",
            "language": "fr",
            "sentiment": "neutral",
            "engagement": 1850,
            "retweets": 612,
            "likes": 1238,
            "geo": {"label": "Abidjan / Plateau", "longitude": -4.0192, "latitude": 5.3175},
            "posted_at": "2026-05-25T13:46:00",
            "tags": ["officiel", "démenti", "frontiere-nord"],
        },
        {
            "id": "tweet-off-003",
            "kind": "officiel",
            "handle": "@RFI_Sahel",
            "author": "RFI Sahel — Afrique",
            "verified": True,
            "text": "Côte d'Ivoire : la Présidence dément la rumeur d'incursion frontalière au Nord et annonce un point de coordination CEDEAO.",
            "language": "fr",
            "sentiment": "neutral",
            "engagement": 720,
            "retweets": 185,
            "likes": 535,
            "geo": {"label": "Paris (relais)", "longitude": 2.3522, "latitude": 48.8566},
            "posted_at": "2026-05-25T13:55:00",
            "tags": ["presse", "international"],
        },
        {
            "id": "tweet-off-004",
            "kind": "officiel",
            "handle": "@JeuneAfrique",
            "author": "Jeune Afrique",
            "verified": True,
            "text": "Lecture favorable : la réponse rapide du Cabinet du Vice Premier Ministre sur le dossier Nawa marque un précédent en matière de continuité gouvernementale.",
            "language": "fr",
            "sentiment": "positive",
            "engagement": 540,
            "retweets": 142,
            "likes": 398,
            "geo": {"label": "Paris (relais)", "longitude": 2.3522, "latitude": 48.8566},
            "posted_at": "2026-05-25T12:40:00",
            "tags": ["presse", "réputation"],
        },
        {
            "id": "tweet-off-005",
            "kind": "officiel",
            "handle": "@PrefectureNord",
            "author": "Préfecture de la région Nord (officiel)",
            "verified": True,
            "text": "Mise au point : la rumeur circulant sur les axes Bouna-Kong est sans fondement. Postes mixtes nominaux. Communiqué à suivre.",
            "language": "fr",
            "sentiment": "neutral",
            "engagement": 410,
            "retweets": 98,
            "likes": 312,
            "geo": {"label": "Korhogo", "longitude": -5.6294, "latitude": 9.4580},
            "posted_at": "2026-05-25T13:52:00",
            "tags": ["officiel", "frontiere-nord", "démenti"],
        },
        # --- 8 citoyens pseudonymises (geo Abidjan) ------------------------
        {
            "id": "tweet-cit-001",
            "kind": "citoyen",
            "handle": "@citoyen_plateau_01",
            "author": "Citoyen pseudonymisé",
            "verified": False,
            "text": "Beaucoup de circulation au Plateau ce matin, mais tout reste calme. RAS côté sécurité.",
            "language": "fr",
            "sentiment": "neutral",
            "engagement": 24,
            "retweets": 3,
            "likes": 18,
            "geo": {"label": "Abidjan / Plateau", "longitude": -4.0244, "latitude": 5.3253},
            "posted_at": "2026-05-25T08:30:00",
            "tags": ["citoyen", "plateau"],
        },
        {
            "id": "tweet-cit-002",
            "kind": "citoyen",
            "handle": "@citoyen_cocody_22",
            "author": "Citoyen pseudonymisé",
            "verified": False,
            "text": "Bon mouvement institutionnel cette semaine, on sent une vraie présence du Cabinet sur les sujets régionaux.",
            "language": "fr",
            "sentiment": "positive",
            "engagement": 52,
            "retweets": 11,
            "likes": 38,
            "geo": {"label": "Abidjan / Cocody", "longitude": -3.9783, "latitude": 5.3537},
            "posted_at": "2026-05-25T10:12:00",
            "tags": ["citoyen", "cocody"],
        },
        {
            "id": "tweet-cit-003",
            "kind": "citoyen",
            "handle": "@citoyen_vridi_18",
            "author": "Citoyen pseudonymisé",
            "verified": False,
            "text": "Le port de Vridi reprend une activité normale, ça fait plaisir. Hâte que le cargo bloqué soit dédouané.",
            "language": "fr",
            "sentiment": "positive",
            "engagement": 38,
            "retweets": 8,
            "likes": 27,
            "geo": {"label": "Abidjan / Vridi", "longitude": -4.0083, "latitude": 5.2512},
            "posted_at": "2026-05-25T09:45:00",
            "tags": ["citoyen", "vridi", "port"],
        },
        {
            "id": "tweet-cit-004",
            "kind": "citoyen",
            "handle": "@citoyen_marcory_07",
            "author": "Citoyen pseudonymisé",
            "verified": False,
            "text": "Circulation impossible vers le Plateau ce matin. Encore une heure perdue dans les bouchons.",
            "language": "fr",
            "sentiment": "negative",
            "engagement": 41,
            "retweets": 6,
            "likes": 22,
            "geo": {"label": "Abidjan / Marcory", "longitude": -3.9889, "latitude": 5.2911},
            "posted_at": "2026-05-25T08:55:00",
            "tags": ["citoyen", "marcory", "trafic"],
        },
        {
            "id": "tweet-cit-005",
            "kind": "citoyen",
            "handle": "@citoyen_yopougon_44",
            "author": "Citoyen pseudonymisé",
            "verified": False,
            "text": "RAS côté Yopougon ce matin, ambiance habituelle. Marché de Niangon ouvert normalement.",
            "language": "fr",
            "sentiment": "neutral",
            "engagement": 12,
            "retweets": 2,
            "likes": 9,
            "geo": {"label": "Abidjan / Yopougon", "longitude": -4.0833, "latitude": 5.3458},
            "posted_at": "2026-05-25T07:25:00",
            "tags": ["citoyen", "yopougon"],
        },
        {
            "id": "tweet-cit-006",
            "kind": "citoyen",
            "handle": "@citoyen_treichville_09",
            "author": "Citoyen pseudonymisé",
            "verified": False,
            "text": "Bonne nouvelle pour la filière cacao d'après ce que j'ai lu. Espérons que les planteurs et coopératives en profitent.",
            "language": "fr",
            "sentiment": "positive",
            "engagement": 28,
            "retweets": 5,
            "likes": 21,
            "geo": {"label": "Abidjan / Treichville", "longitude": -4.0142, "latitude": 5.2925},
            "posted_at": "2026-05-25T11:08:00",
            "tags": ["citoyen", "cacao"],
        },
        {
            "id": "tweet-cit-007",
            "kind": "citoyen",
            "handle": "@citoyen_abobo_31",
            "author": "Citoyen pseudonymisé",
            "verified": False,
            "text": "Tensions sur l'axe Anyama-Abobo : on dirait que ça se calme depuis le contrôle. Patience.",
            "language": "fr",
            "sentiment": "neutral",
            "engagement": 35,
            "retweets": 6,
            "likes": 19,
            "geo": {"label": "Abidjan / Abobo", "longitude": -4.0250, "latitude": 5.4275},
            "posted_at": "2026-05-25T09:18:00",
            "tags": ["citoyen", "abobo"],
        },
        {
            "id": "tweet-cit-008",
            "kind": "citoyen",
            "handle": "@citoyen_plateau_56",
            "author": "Citoyen pseudonymisé",
            "verified": False,
            "text": "Le débat sur le budget défense mérite d'être clarifié, mais les résultats du Cabinet sur le Nord comptent aussi.",
            "language": "fr",
            "sentiment": "neutral",
            "engagement": 47,
            "retweets": 9,
            "likes": 26,
            "geo": {"label": "Abidjan / Plateau", "longitude": -4.0244, "latitude": 5.3253},
            "posted_at": "2026-05-25T11:30:00",
            "tags": ["citoyen", "réputation", "budget-defense"],
        },
        # --- 5 rumeur frontière Nord (pseudonymisés @rumeur_***) -----------
        {
            "id": "tweet-rum-001",
            "kind": "rumeur",
            "handle": "@rumeur_nord_001",
            "author": "Compte pseudonyme — non vérifié",
            "verified": False,
            "text": "Mouvements suspects vers la frontière Nord ce matin... à vérifier. Source indirecte, non confirmée.",
            "language": "fr",
            "sentiment": "negative",
            "engagement": 215,
            "retweets": 92,
            "likes": 78,
            "geo": {"label": "Bouna (rumeur)", "longitude": -2.9956, "latitude": 9.2667},
            "posted_at": "2026-05-25T11:42:00",
            "tags": ["rumeur", "frontiere-nord"],
        },
        {
            "id": "tweet-rum-002",
            "kind": "rumeur",
            "handle": "@rumeur_telegram_relai",
            "author": "Canal Telegram relai (pseudonyme)",
            "verified": False,
            "text": "Une source indirecte évoque des bruits dans la zone Kong. Rien d'officiel pour l'instant. #FrontiereNord",
            "language": "fr",
            "sentiment": "negative",
            "engagement": 312,
            "retweets": 124,
            "likes": 116,
            "geo": {"label": "Kong (rumeur)", "longitude": -4.6122, "latitude": 9.1539},
            "posted_at": "2026-05-25T12:08:00",
            "tags": ["rumeur", "telegram", "frontiere-nord"],
        },
        {
            "id": "tweet-rum-003",
            "kind": "rumeur",
            "handle": "@rumeur_blog_relai",
            "author": "Blog régional (pseudonyme)",
            "verified": False,
            "text": "Article publié : 'Tensions Nord — ce que cachent les autorités'. À lire avec prudence : pas de source primaire.",
            "language": "fr",
            "sentiment": "negative",
            "engagement": 188,
            "retweets": 71,
            "likes": 64,
            "geo": {"label": "Korhogo (rumeur)", "longitude": -5.6294, "latitude": 9.4580},
            "posted_at": "2026-05-25T12:48:00",
            "tags": ["rumeur", "blog", "frontiere-nord"],
        },
        {
            "id": "tweet-rum-004",
            "kind": "rumeur",
            "handle": "@rumeur_nord_022",
            "author": "Compte pseudonyme — non vérifié",
            "verified": False,
            "text": "Mouvements inhabituels non vérifiés vers Bouna selon des contacts locaux. Une clarification officielle est attendue.",
            "language": "fr",
            "sentiment": "neutral",
            "engagement": 156,
            "retweets": 58,
            "likes": 49,
            "geo": {"label": "Bouna (rumeur)", "longitude": -2.9956, "latitude": 9.2667},
            "posted_at": "2026-05-25T13:15:00",
            "tags": ["rumeur", "frontiere-nord"],
        },
        {
            "id": "tweet-rum-005",
            "kind": "rumeur",
            "handle": "@rumeur_nord_007",
            "author": "Compte pseudonyme — non vérifié",
            "verified": False,
            "text": "Je rappelle juste que la rumeur Nord a été démentie par la FANCI il y a quelques minutes. RT pour info.",
            "language": "fr",
            "sentiment": "neutral",
            "engagement": 84,
            "retweets": 29,
            "likes": 38,
            "geo": {"label": "Korhogo", "longitude": -5.6294, "latitude": 9.4580},
            "posted_at": "2026-05-25T13:58:00",
            "tags": ["rumeur", "démenti", "frontiere-nord"],
        },
    ],
}

# ----------------------------------------------------------------------------
# Snapshot ADS-B advisory du théâtre Sahel. Callsigns + types militaires
# plausibles (C-130, CN-235, AT-6, vols logistiques regionaux). Le disclaimer
# « ADS-B advisory only » est porté par la légende côté front et par la
# couche `military-air` dans workspace_maps.py. Aucune donnée opérationnelle
# classifiée — snapshot figé scénario.
# ----------------------------------------------------------------------------

TROOPS_SAHEL = {
    "captured_at": "2026-05-25T14:30:00",
    "disclaimer": "ADS-B advisory only — snapshot scénario, aucune donnée opérationnelle classifiée.",
    "theater_label": "Théâtre Sahel — axe Bamako/Ouagadougou/Niamey",
    "tracks": [
        {
            "id": "track-001",
            "callsign": "FRA9201",
            "kind": "C-130 (transport)",
            "operator": "Vol logistique régional",
            "altitude_ft": 22000,
            "heading": 65,
            "speed_kt": 280,
            "longitude": -7.9892,
            "latitude": 12.5391,
            "origin": "Bamako (advisory)",
            "destination": "Ouagadougou (advisory)",
            "tone": "watch",
        },
        {
            "id": "track-002",
            "callsign": "BFA1107",
            "kind": "CN-235 (transport leger)",
            "operator": "Vol logistique régional",
            "altitude_ft": 18000,
            "heading": 88,
            "speed_kt": 245,
            "longitude": -2.4308,
            "latitude": 12.7619,
            "origin": "Ouagadougou (advisory)",
            "destination": "Niamey (advisory)",
            "tone": "watch",
        },
        {
            "id": "track-003",
            "callsign": "NIG3304",
            "kind": "AT-6 Wolverine (appui)",
            "operator": "Vol advisory",
            "altitude_ft": 12000,
            "heading": 215,
            "speed_kt": 175,
            "longitude": 2.1086,
            "latitude": 13.5125,
            "origin": "Niamey (advisory)",
            "destination": "Tillaberi (advisory)",
            "tone": "watch",
        },
        {
            "id": "track-004",
            "callsign": "ECW0414",
            "kind": "Vol logistique CEDEAO",
            "operator": "Mission régionale",
            "altitude_ft": 24000,
            "heading": 145,
            "speed_kt": 310,
            "longitude": -3.9889,
            "latitude": 11.8167,
            "origin": "Bobo-Dioulasso (advisory)",
            "destination": "Tamale (advisory)",
            "tone": "stable",
        },
        {
            "id": "track-005",
            "callsign": "FRA9220",
            "kind": "C-130 (transport)",
            "operator": "Vol logistique régional",
            "altitude_ft": 21000,
            "heading": 282,
            "speed_kt": 275,
            "longitude": -3.5644,
            "latitude": 14.5089,
            "origin": "Gao (advisory)",
            "destination": "Bamako (advisory)",
            "tone": "watch",
        },
        {
            "id": "track-006",
            "callsign": "MAL5512",
            "kind": "Helicoptere advisory",
            "operator": "Vol terrain",
            "altitude_ft": 4500,
            "heading": 12,
            "speed_kt": 105,
            "longitude": -2.9650,
            "latitude": 13.0428,
            "origin": "Mopti (advisory)",
            "destination": "Dori (advisory)",
            "tone": "watch",
        },
        {
            "id": "track-007",
            "callsign": "BFA1108",
            "kind": "CN-235 (transport leger)",
            "operator": "Vol logistique régional",
            "altitude_ft": 17500,
            "heading": 268,
            "speed_kt": 235,
            "longitude": -0.9656,
            "latitude": 12.4789,
            "origin": "Ouagadougou (advisory)",
            "destination": "Bobo-Dioulasso (advisory)",
            "tone": "stable",
        },
        {
            "id": "track-008",
            "callsign": "NIG3315",
            "kind": "AT-6 Wolverine (appui)",
            "operator": "Vol advisory",
            "altitude_ft": 9500,
            "heading": 192,
            "speed_kt": 170,
            "longitude": 1.5483,
            "latitude": 13.9892,
            "origin": "Tillaberi (advisory)",
            "destination": "Niamey (advisory)",
            "tone": "watch",
        },
        {
            "id": "track-009",
            "callsign": "ECW0418",
            "kind": "Vol logistique CEDEAO",
            "operator": "Mission régionale",
            "altitude_ft": 23000,
            "heading": 320,
            "speed_kt": 295,
            "longitude": -4.5650,
            "latitude": 10.5567,
            "origin": "Korhogo (advisory)",
            "destination": "Bamako (advisory)",
            "tone": "stable",
        },
        {
            "id": "track-010",
            "callsign": "MAL5520",
            "kind": "Helicoptere advisory",
            "operator": "Vol terrain",
            "altitude_ft": 3800,
            "heading": 75,
            "speed_kt": 95,
            "longitude": -5.2767,
            "latitude": 13.2456,
            "origin": "Sikasso (advisory)",
            "destination": "Segou (advisory)",
            "tone": "watch",
        },
    ],
    "watch_zones": [
        {
            "id": "zone-sahel-liptako",
            "name": "Liptako-Gourma",
            "tone": "watch",
            "centroid": [-0.2, 14.5],
            "summary": "Zone tripoint Mali/Burkina/Niger — OSINT public ACLED-like.",
        },
        {
            "id": "zone-sahel-mali-burkina",
            "name": "Frontiere Mali/Burkina",
            "tone": "watch",
            "centroid": [-3.8, 14.0],
            "summary": "Axe Tominian-Yoro — surveillance régionale.",
        },
        {
            "id": "zone-sahel-tillaberi",
            "name": "Region de Tillaberi (Niger)",
            "tone": "watch",
            "centroid": [1.45, 14.2],
            "summary": "Zone Liptako Niger — flux humanitaires sous tension.",
        },
    ],
    "cedeao_bases": [
        {
            "id": "base-cedeao-abidjan",
            "name": "Base logistique CEDEAO — Abidjan",
            "tone": "stable",
            "longitude": -4.0244,
            "latitude": 5.3253,
            "role": "Plateforme logistique régionale.",
        },
        {
            "id": "base-cedeao-corridor-mali",
            "name": "Hub coordination CEDEAO — corridor Mali",
            "tone": "watch",
            "longitude": -5.6294,
            "latitude": 9.4580,
            "role": "Hub coordination corridor Korhogo-Bamako (advisory).",
        },
    ],
}

# ----------------------------------------------------------------------------
# Reputation drill Vice Premier Ministre : 2 items positifs + 1 critique sourcée (article L'Inter
# déjà seedé S1, attention-inter-budget). Garantit que l'item critique reste
# une critique réelle déjà publique, pas une invention.
# ----------------------------------------------------------------------------

REPUTATION_DRILL = {
    "score": 72,
    "delta": 4,
    "period_label": "Cette semaine — 19-25 mai 2026",
    "sentiment_overall": "Plutôt positif (72/100)",
    "summary": (
        "La tonalité hebdomadaire reste favorable : 2 signaux positifs marqués "
        "(presse internationale + réactivité Nawa) viennent compenser une critique "
        "ciblée de L'Inter sur le budget défense."
    ),
    "items": [
        {
            "id": "rep-pos-jeune-afrique",
            "kind": "positif",
            "tone": "positive",
            "title": "Lecture favorable de Jeune Afrique sur la séquence Nord",
            "summary": "L'article 'Côte d'Ivoire — la nouvelle main du Cabinet' souligne la coordination du Vice Premier Ministre sur la séquence Nord.",
            "source_label": "Jeune Afrique — 22 mai 2026",
            "source_id": "src-press-jeune-afrique-001",
            "url": "https://www.jeuneafrique.com/example/cabinet-cote-divoire-mai-2026",
            "sentiment": "positive",
            "engagement": 8400,
        },
        {
            "id": "rep-pos-prefet-nawa",
            "kind": "positif",
            "tone": "positive",
            "title": "Réponse rapide au Préfet de Nawa",
            "summary": "La presse régionale (Fraternité Matin, AIP) souligne la rapidité de la réponse Vice Premier Ministre au rapport préfet sur la diversification cacao.",
            "source_label": "Fraternité Matin — 23 mai 2026",
            "source_id": "src-press-fratmat-nawa-001",
            "url": "https://www.fratmat.info/example/reponse-vp-nawa-mai-2026",
            "sentiment": "positive",
            "engagement": 4200,
        },
        {
            "id": "rep-neg-inter-budget",
            "kind": "critique",
            "tone": "negative",
            "title": "Critique sur le budget défense (L'Inter)",
            "summary": "L'Inter publie une tribune critique sur la ventilation du budget défense. Réponse cabinet recommandée cette semaine.",
            "source_label": "L'Inter — 25 mai 2026",
            "source_id": "src-press-ci-local-001",
            "url": "https://www.linter.ci/example/budget-defense-mai-2026",
            "sentiment": "negative",
            "engagement": 6800,
            "linked_attention_id": "attention-inter-budget",
        },
    ],
    "aya_sentence": "Monsieur le Vice Premier Ministre, la semaine reste favorable. Je vous propose de capitaliser sur les deux signaux positifs en préparant un encart concis pour le Conseil 15h.",
}

# ----------------------------------------------------------------------------
# Trace evidence-graph de la rumeur frontière Nord — chaîne source primaire
# vers démenti officiel : tweet citoyen pseudonyme -> relai Telegram ->
# blog régional -> démenti FANCI/Préfecture. Sert au handler aya.trace_rumor_origin
# et au dossier KB associé.
# ----------------------------------------------------------------------------

RUMOR_FRONTIER_TRACE = {
    "headline": "Rumeur frontière Nord — chaîne OSINT et démenti officiel",
    "summary": (
        "Le signal initial est un tweet d'un compte citoyen pseudonyme posté à 11h42 "
        "depuis la zone Bouna. Il est repris sur un canal Telegram régional à 12h08, "
        "puis sur un blog local à 12h48. La FANCI et la Préfecture Nord démentent "
        "officiellement la rumeur à partir de 13h46."
    ),
    "origin": "Tweet citoyen pseudonyme — secteur Bouna",
    "chain": [
        {
            "step": 1,
            "channel": "X / Twitter",
            "time": "11:42",
            "actor": "@rumeur_nord_001",
            "kind": "tweet_origine",
            "signal": "Tweet citoyen pseudonyme — 'mouvements suspects vers la frontière Nord'",
            "confidence": 0.32,
            "source_id": "tweet-rum-001",
        },
        {
            "step": 2,
            "channel": "Telegram",
            "time": "12:08",
            "actor": "@rumeur_telegram_relai",
            "kind": "relai_telegram",
            "signal": "Canal Telegram régional reprend la rumeur avec hashtag #FrontiereNord",
            "confidence": 0.45,
            "source_id": "tweet-rum-002",
        },
        {
            "step": 3,
            "channel": "Blog régional",
            "time": "12:48",
            "actor": "@rumeur_blog_relai",
            "kind": "article_relai",
            "signal": "Article 'Tensions Nord — ce que cachent les autorités' publié sans source primaire",
            "confidence": 0.51,
            "source_id": "tweet-rum-003",
        },
        {
            "step": 4,
            "channel": "Réseaux sociaux",
            "time": "13:15",
            "actor": "@rumeur_nord_022",
            "kind": "amplification",
            "signal": "Compte pseudonyme amplifie le récit, demande une réponse gouvernementale",
            "confidence": 0.48,
            "source_id": "tweet-rum-004",
        },
        {
            "step": 5,
            "channel": "Communiqué officiel",
            "time": "13:46",
            "actor": "@FANCIofficiel",
            "kind": "demente_officielle",
            "signal": "Démenti officiel FANCI : aucune incursion confirmée, postes mixtes nominaux.",
            "confidence": 0.95,
            "source_id": "tweet-off-002",
        },
        {
            "step": 6,
            "channel": "Préfecture Nord",
            "time": "13:52",
            "actor": "@PrefectureNord",
            "kind": "demente_officielle",
            "signal": "Mise au point Préfecture Nord : rumeur sans fondement, postes mixtes nominaux.",
            "confidence": 0.96,
            "source_id": "tweet-off-005",
        },
    ],
    "recommended_action": (
        "Préparer un communiqué souverain bref : rappeler le démenti officiel, citer les sources "
        "FANCI et Préfecture, ouvrir la coordination CEDEAO comme suite logique."
    ),
    "aya_sentence": (
        "Monsieur le Vice Premier Ministre, la rumeur est démentie depuis 13h46. Je vous propose un "
        "communiqué court qui s'appuie sur le démenti FANCI et la mise au point de la Préfecture."
    ),
}

RUMOR_TRACE = {
    "headline": "Rumeur prioritaire sous verification",
    "summary": "Un signal d'emoi public part d'un groupe WhatsApp local, rebondit sur X, puis apparait dans deux pages Facebook regionales.",
    "origin": "WhatsApp public · secteur Korhogo",
    "spread": [
        {
            "channel": "WhatsApp",
            "time": "06:22",
            "signal": "message vocal non confirme",
            "confidence": 0.44,
        },
        {
            "channel": "X",
            "time": "07:08",
            "signal": "captures reprises par comptes locaux",
            "confidence": 0.58,
        },
        {
            "channel": "Facebook",
            "time": "07:41",
            "signal": "commentaires publics en hausse",
            "confidence": 0.63,
        },
        {
            "channel": "Presse locale",
            "time": "08:15",
            "signal": "mention indirecte sans source primaire",
            "confidence": 0.52,
        },
    ],
    "recommended_action": "Verifier source primaire, preparer message de compassion et coordonner presence prefectorale.",
    "aya_sentence": "Je ne recommande pas d'amplifier publiquement la rumeur avant verification, mais de preparer les mots et le geste institutionnel maintenant.",
}

DEMO_VALUE_METRICS = [
    {
        "label": "Sources filtrees",
        "value": "80 -> 3",
        "caption": "articles, flux et signaux faibles transformes en attentions actionnables",
    },
    {
        "label": "Reponse voix",
        "value": "6 s",
        "caption": "latence cible pour une reponse AYA exploitable en reunion",
    },
    {
        "label": "Zones suivies",
        "value": "5",
        "caption": "lecture Cote d'Ivoire + CEDEAO + Golfe de Guinee",
    },
    {"label": "Dossiers prets", "value": "3", "caption": "presse, Zone Nord, Ambassadeur France"},
]

PRESENTATION_BEATS = [
    {
        "step": "01",
        "label": "Ouvrir",
        "sentence": "AYA presente une seule priorite, pas un tableau de donnees.",
    },
    {
        "step": "02",
        "label": "Croiser",
        "sentence": "Carte, presse, webcams, agenda et rumeurs convergent vers trois decisions.",
    },
    {
        "step": "03",
        "label": "Parler",
        "sentence": "Le Vice-PM interroge AYA a voix haute sur la Zone Nord.",
    },
    {
        "step": "04",
        "label": "Arbitrer",
        "sentence": "AYA propose les options et la fenetre de decision avant 15h00.",
    },
]

SECURITY_LIBRARY_ITEMS = [
    {
        "id": "lib-security-posture-sahel",
        "title": "Note posture sécurité Sahel — 25 mai 2026",
        "kind": "security_brief",
        "collection": "sentinel-ci-security-briefs",
        "summary": "Posture dual-axis intérieur/extérieur, théâtre Sahel et signaux OSINT publics avant Conseil Défense 15h.",
        "sources": ["src-note-posture-sahel-2026-05-25"],
    },
    {
        "id": "lib-conseil-defense-am",
        "title": "Synthèse Conseil Défense restreint — 08h30",
        "kind": "security_brief",
        "collection": "sentinel-ci-security-briefs",
        "summary": "Revue matinale Sahel, bases CEDEAO en alerte standard et éléments de langage pour le Vice Premier Ministre.",
        "sources": ["src-conseil-defense-2026-05-25-am"],
    },
    {
        "id": "lib-rumor-frontier-dossier",
        "title": "Dossier rumeur frontière Nord — chronologie OSINT",
        "kind": "rumor_dossier",
        "collection": "sentinel-ci-security-briefs",
        "summary": "Chaîne tweet → Telegram → blog → démentis FANCI et Préfecture Nord, advisory only.",
        "sources": ["src-rumor-frontier-nord-2026-05-25"],
    },
    {
        "id": "lib-troops-sahel-snapshot",
        "title": "Snapshot ADS-B advisory Sahel — 14h30",
        "kind": "ads_b_advisory",
        "collection": "sentinel-ci-security-briefs",
        "summary": "Traces ADS-B advisory Bamako/Ouaga/Niamey, zones de surveillance et bases CEDEAO.",
        "sources": ["src-troops-sahel-2026-05-25"],
    },
]

LIBRARY_ITEMS = [
    {
        "id": "lib-briefing-template",
        "title": "Modele briefing Vice Premier Ministre",
        "kind": "template",
        "collection": "sentinel-ci-ministerial-briefs",
        "summary": "Structure priorites, risques, decisions attendues, actions et sources.",
        "sources": ["src-cabinet-brief-001"],
    },
    {
        "id": "lib-project-record",
        "title": "Dossier centres de sante frontaliers",
        "kind": "project_record",
        "collection": "sentinel-ci-projects",
        "summary": "Dossier de pilotage prioritaire reliant causes, risques et arbitrages possibles.",
        "sources": ["src-project-sante-042"],
    },
    {
        "id": "lib-map-signals",
        "title": "Signaux carte territoriale",
        "kind": "map_context",
        "collection": "sentinel-ci-territorial-map",
        "summary": "Zones, niveaux d'alerte et recommandations preventives non militaires.",
        "sources": ["src-cabinet-brief-001", "src-press-rfi-017"],
    },
    {
        "id": "lib-territorial-intelligence",
        "title": "Intelligence territoriale consolidee",
        "kind": "map_context",
        "collection": "sentinel-ci-territorial-intelligence",
        "summary": "Scores de zones, signaux presse, projets, agenda, flux visuels et fenetres d'action.",
        "sources": ["src-cabinet-brief-001", "src-project-sante-042", "src-press-rfi-017"],
    },
]

PROJECTS = [
    {
        "id": "proj-health-north",
        "name": "Centres de sante frontaliers - Nord",
        "weather": "red",
        "progress": 63,
        "expected": 78,
        "delay_days": 24,
        "owner": "Direction programmes territoriaux",
        "cause": "Livraison et validation administrative retardees.",
        "risk": "Decalage de reception avant periode critique et amplification de rumeurs locales.",
        "options": [
            "Relance cabinet",
            "Arbitrage budgetaire",
            "Mission terrain",
            "Reunion fournisseur",
            "Replanification",
        ],
        "sources": ["src-project-sante-042", "src-cabinet-brief-001"],
    },
    {
        "id": "proj-drone-centre-napie",
        "aliases": ["proj-public-north-supply"],
        "name": "Centre International de Formation aux Métiers des Drones — Napié",
        "region": "Poro / Nord",
        "location": "Napié",
        "status": "critical",
        "weather": "red",
        "progress": 41,
        "expected": 78,
        "delay_days": 120,
        "owner": "Agence de Développement Régional du Poro",
        "zone_id": "zone-nord",
        "cause": (
            "Cargaison de composants drones importés (Aerostar Dynamics, USA) "
            "bloquée au port d'Abidjan — équipements hangars de vol, terrains "
            "d'apprentissage, laboratoires cartographie."
        ),
        "risk": (
            "Décalage de l'ouverture du centre (cible : démarrage formations début 2026) "
            "et perception d'enlisement d'un investissement souverain de 100 M USD."
        ),
        "investment_label": "100 M USD / 60 Mds FCFA",
        "partners": [
            "Agence Développement Régional Poro",
            "Aerostar Dynamics (USA)",
            "CEPICI",
        ],
        "strategic_alignment": "Côte d'Ivoire Innovation 2030",
        "cargo_ref": "cargo-abidjan-supply-001",
        "source_refs": ["src-abidjan-net-drone-napie-2025-07-16"],
        "options": [
            "Priorisation dedouanement",
            "Relance douanes + port",
            "Replanification livraison",
        ],
        "sources": [
            "src-abidjan-net-drone-napie-2025-07-16",
            "src-cabinet-brief-001",
            "src-maritime-paa-001",
            "src-marinetraffic-context-001",
        ],
    },
    {
        "id": "proj-civic-radio",
        "name": "Communication civique regionale",
        "weather": "orange",
        "progress": 71,
        "expected": 76,
        "delay_days": 8,
        "owner": "Service communication",
        "cause": "Elements de langage non valides pour deux regions sensibles.",
        "risk": "Fenetre presse courte avant conseil restreint.",
        "options": ["Validation elements de langage", "Brief prefets", "Point presse cible"],
        "sources": ["src-press-rfi-017", "src-agenda-jour-015"],
    },
    {
        "id": "proj-border-logistics",
        "name": "Logistique preventive zones frontalieres",
        "weather": "green",
        "progress": 82,
        "expected": 80,
        "delay_days": 0,
        "owner": "Cellule coordination terrain",
        "cause": "Flux stabilises, coordination interministerielle active.",
        "risk": "Surveillance a maintenir sur deux corridors.",
        "options": ["Maintien surveillance", "Brief hebdomadaire", "Suivi carte"],
        "sources": ["src-cabinet-brief-001"],
    },
    {
        "id": "proj-cacao-transformation-nawa",
        "name": "Transformation locale cacao — region Nawa",
        "weather": "orange",
        "progress": 22,
        "expected": 45,
        "delay_days": 120,
        "owner": "Direction filieres agricoles",
        "zone_id": "zone-ouest",
        "cause": "Besoin chiffre de sechoirs, routes secondaires et electrifiation issu du rapport prefet Nawa (10 mai).",
        "risk": "Dependance export brute et volatilite prix sans diversification.",
        "investment_estimate_fcfa": "4,2 a 6,8 milliards FCFA (ordre de grandeur public)",
        "options": [
            "Petite industrie transformation + diversification cultures",
            "Cooperative regionale renforcee",
            "PPP infrastructure sechoirs",
        ],
        "sources": ["src-prefet-nawa-report-001"],
    },
]

MAP_ZONES = [
    {
        "id": "zone-nord",
        "name": "Nord",
        "level": 85,
        "tone": "critical",
        "centroid": {"x": 410, "y": 98},
        "polygon": "374,62 455,74 489,130 444,168 366,152 342,105",
        "signals": [
            "Projet social en retard",
            "Rumeurs recurrentes",
            "Faible presence institutionnelle",
        ],
        "recommendations": [
            "Rencontre autorites locales",
            "Communication ciblee",
            "Mission terrain non militaire",
        ],
        "sources": ["src-cabinet-brief-001", "src-project-sante-042", "src-press-rfi-017"],
    },
    {
        "id": "zone-ouest",
        "name": "Ouest",
        "level": 45,
        "tone": "watch",
        "centroid": {"x": 300, "y": 220},
        "polygon": "263,158 347,171 369,260 315,319 244,282 229,205",
        "signals": ["Flux transfrontaliers", "Besoin de couverture institutionnelle"],
        "recommendations": ["Brief prefectoral", "Suivi logistique", "Coordination regionale"],
        "sources": ["src-cabinet-brief-001"],
    },
    {
        "id": "zone-centre",
        "name": "Centre",
        "level": 25,
        "tone": "stable",
        "centroid": {"x": 430, "y": 272},
        "polygon": "371,176 470,169 511,248 476,334 382,327 342,258",
        "signals": ["Situation stable", "Projet prioritaire dans les temps"],
        "recommendations": ["Maintien veille", "Capitaliser sur communication positive"],
        "sources": ["src-project-sante-042"],
    },
    {
        "id": "zone-sud",
        "name": "Sud",
        "level": 15,
        "tone": "stable",
        "centroid": {"x": 420, "y": 410},
        "polygon": "340,335 492,344 536,438 463,499 334,473 296,390",
        "signals": ["Couverture institutionnelle forte"],
        "recommendations": ["Aucune action urgente", "Veille presse standard"],
        "sources": ["src-agenda-jour-015"],
    },
    {
        "id": "zone-est",
        "name": "Est",
        "level": 55,
        "tone": "watch",
        "centroid": {"x": 558, "y": 257},
        "polygon": "493,143 596,166 629,263 581,356 497,327 520,238",
        "signals": ["Tension mediatique", "Besoin de communication preventive"],
        "recommendations": ["Communication ciblee", "Reunion coordination", "Suivi projet local"],
        "sources": ["src-press-rfi-017"],
    },
]
