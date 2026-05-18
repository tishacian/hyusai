"""SENTINEL-CI demo mission-room fixtures and bootstrap helpers.

The mission room is intentionally implemented as an Agentium workspace pattern,
not as a tenant-special case. Runtime surfaces read the current workspace, while
this module provides a portable demo seed and deterministic advisory payloads.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.core.iam.roles import WORKSPACE_CONTRIBUTOR, WORKSPACE_OWNER, legacy_role_for_template
from app.models.capability import Capability
from app.models.intelligence import FeedSource, SafetyFilter, SemanticTarget
from app.models.knowledge_collection import KnowledgeCollection
from app.models.rag_preset import RagPreset
from app.models.run import Run
from app.models.skill import Skill
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.audit_logger import emit_audit_event
from app.services.workspace_calendar import (
    ensure_calendar_seed,
    list_events as list_calendar_events,
    serialize_event as serialize_calendar_event,
    summary_payload as calendar_summary_payload,
)
from app.services.action_plans import (
    ensure_action_plan_seed,
    list_action_items,
    serialize_action_item,
    summary_payload as action_plan_summary_payload,
)
from app.services.scenario_engine import generate_scenarios
from app.services.visual_intelligence import (
    dashboard_payload as visual_dashboard_payload,
    ensure_visual_intelligence_seed,
)
from app.services.workspace_maps import ensure_workspace_map_seed, mission_room_map_payload


SENTINEL_WORKSPACE_SLUG = "sentinel-ci"
SENTINEL_WORKSPACE_NAME = "SENTINEL-CI"
SENTINEL_ASSISTANT_NAME = "AYA"
MISSION_ROOM_ROOT = "/hypervisor/mission-room"
MISSION_ROOM_ROUTE = f"{MISSION_ROOM_ROOT}/cockpit"


NAVIGATION_ITEMS = [
    {"key": "cockpit", "label": "Priorites", "glyph": "ledger", "variant": "government_mission_room", "object": "Workbench"},
    {"key": "monitor", "label": "Situation live", "glyph": "crosshair", "variant": "scenario_fusion_monitor", "object": "Workbench"},
    {"key": "briefing", "label": "Briefing", "glyph": "ledger", "variant": "ministerial_daily_briefing", "object": "Workbench"},
    {"key": "agenda", "label": "Agenda", "glyph": "ledger", "variant": "government_mission_room", "object": "Workbench"},
    {"key": "presse", "label": "Presse", "glyph": "pulse", "variant": "intelligence", "object": "Run"},
    {"key": "decisions", "label": "Arbitrages", "glyph": "check", "variant": "executive_instruction_drafting", "object": "Review Queue"},
    {"key": "strategie", "label": "Carte", "glyph": "sliders", "variant": "territorial_action_map", "object": "Workbench"},
]


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
]

AGENDA = [
    {
        "time": "08:30",
        "title": "Conseil Defense restreint",
        "location": "Salle du Conseil - Plateau",
        "tone": "urgent",
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
        "summary": "Rumeurs recurrentes + projet social en retard : renforcement de coordination recommande.",
        "deadline": "avant conseil restreint",
        "sources": ["src-cabinet-brief-001", "src-press-rfi-017"],
        "tone": "critical",
    },
    {
        "id": "prio-mail-konaté",
        "kind": "mail",
        "title": "Email prioritaire - Gen. Konate",
        "summary": "Demande d'arbitrage sur reception de materiels et communication preventive.",
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
]

SENTINEL_NEWS_FEEDS = [
    ("7info CI", "https://www.7info.ci/feed/", "ci-local"),
    ("Agence Ivoirienne de Presse", "https://www.aip.ci/feed/", "ci-agency"),
    ("RTI Info", "https://rti.info/feed/", "ci-public"),
    ("Connection Ivoirienne", "https://connectionivoirienne.net/feed/", "ci-local"),
    ("Fraternite Matin", "https://beta.fratmat.info/rssFeed/0", "ci-national"),
    ("BBC Africa", "https://feeds.bbci.co.uk/news/world/africa/rss.xml", "africa"),
    ("Jeune Afrique", "https://www.jeuneafrique.com/feed/", "africa-fr"),
    ("AllAfrica West Africa", "https://allafrica.com/tools/headlines/rdf/westafrica/headlines.rdf", "cedeao"),
    ("Africanews", "https://www.africanews.com/feed/rss", "africa"),
    ("France 24 Afrique", "https://www.france24.com/fr/afrique/rss", "afrique"),
    ("RFI Afrique", "https://www.rfi.fr/fr/afrique/rss", "afrique"),
    ("BBC World News", "https://feeds.bbci.co.uk/news/world/rss.xml", "world"),
]

GEOGRAPHIC_PRIORITY_ORDER = [
    ("ci", "Cote d'Ivoire", "Priorite absolue pour le vice-president et le pilotage interieur."),
    ("cedeao", "CEDEAO / voisins immediats", "Effets transfrontaliers, perception regionale et coordination diplomatique."),
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
}

MESSAGES = [
    {
        "id": "msg-konate-001",
        "from": "Gen. Konate",
        "subject": "Situation securitaire nord",
        "time": "09:15",
        "priority": "urgent",
        "summary": "Demande d'arbitrage sur reception de materiels et communication preventive.",
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
    "text": "M. le Vice-Président, votre priorité absolue ce matin est la Zone Nord. Tout le reste peut attendre.",
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
        "source_refs": ["src-press-ci-local-001"],
    },
    {
        "id": "attention-zone-nord",
        "rank": 2,
        "title": "Zone Nord - tension frontiere Burkina Faso",
        "sentence": "Renforcement preventif ou coordination CEDEAO a arbitrer avant Conseil 15h00.",
        "action_label": "Arbitrer les options",
        "deadline": "15:00",
        "status": "decision_required",
        "tone": "critical",
        "source_refs": ["src-cabinet-brief-001", "src-press-cedeao-001"],
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
        "source_refs": ["src-agenda-jour-015", "src-project-sante-042"],
    },
]

TERRITORIAL_LIVE_STATUS = [
    {"zone": "Nord", "level": "CRITIQUE", "bars": 4, "summary": "Incident frontiere · 06h14", "tone": "critical"},
    {"zone": "Ouest", "level": "SURVEILLANCE", "bars": 3, "summary": "Mouvements inhabituels", "tone": "watch"},
    {"zone": "Centre", "level": "STABLE", "bars": 2, "summary": "Institutions nominales", "tone": "stable"},
    {"zone": "Sud", "level": "OPERATIONNEL", "bars": 1, "summary": "Abidjan nominal", "tone": "stable"},
    {"zone": "Est", "level": "SURVEILLANCE", "bars": 3, "summary": "Frontiere Ghana", "tone": "watch"},
]

VOICE_DEMO_SCRIPT = {
    "prompt": "AYA, quelle est la situation au nord en ce moment ?",
    "answer": (
        "Zone nord — niveau critique depuis ce matin 06h14. Le General Konate signale des mouvements "
        "a 40 kilometres de la frontiere Burkina. Deux options sont sur la table : renforcement preventif "
        "ou coordination CEDEAO. Le General attend votre arbitrage avant 15 heures."
    ),
    "target_latency_s": 6,
}

EXECUTIVE_DECISION_PACKAGES = [
    {
        "id": "package-zone-nord",
        "label": "Dossier de decision",
        "title": "Zone Nord - arbitrage avant Conseil",
        "decision": "Choisir renforcement preventif ou coordination CEDEAO avant 15h00.",
        "recommended_option": "Coordination CEDEAO + presence institutionnelle sobre",
        "why_now": "La sequence presse de 14h00 peut amplifier la tension si aucune posture n'est annoncee.",
        "deadline": "15:00",
        "owner": "Directeur de cabinet",
        "confidence": 0.78,
        "status": "decision_required",
        "tone": "critical",
        "sources": ["Carte Nord", "Presse CI", "Agenda Conseil", "Flux visuels Abidjan"],
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
]

RUMOR_TRACE = {
    "headline": "Rumeur prioritaire sous verification",
    "summary": "Un signal d'emoi public part d'un groupe WhatsApp local, rebondit sur X, puis apparait dans deux pages Facebook regionales.",
    "origin": "WhatsApp public · secteur Korhogo",
    "spread": [
        {"channel": "WhatsApp", "time": "06:22", "signal": "message vocal non confirme", "confidence": 0.44},
        {"channel": "X", "time": "07:08", "signal": "captures reprises par comptes locaux", "confidence": 0.58},
        {"channel": "Facebook", "time": "07:41", "signal": "commentaires publics en hausse", "confidence": 0.63},
        {"channel": "Presse locale", "time": "08:15", "signal": "mention indirecte sans source primaire", "confidence": 0.52},
    ],
    "recommended_action": "Verifier source primaire, preparer message de compassion et coordonner presence prefectorale.",
    "aya_sentence": "Je ne recommande pas d'amplifier publiquement la rumeur avant verification, mais de preparer les mots et le geste institutionnel maintenant.",
}

DEMO_VALUE_METRICS = [
    {"label": "Sources filtrees", "value": "80 -> 3", "caption": "articles, flux et signaux faibles transformes en attentions actionnables"},
    {"label": "Reponse voix", "value": "6 s", "caption": "latence cible pour une reponse AYA exploitable en reunion"},
    {"label": "Zones suivies", "value": "5", "caption": "lecture Cote d'Ivoire + CEDEAO + Golfe de Guinee"},
    {"label": "Dossiers prets", "value": "3", "caption": "presse, Zone Nord, Ambassadeur France"},
]

PRESENTATION_BEATS = [
    {"step": "01", "label": "Ouvrir", "sentence": "AYA presente une seule priorite, pas un tableau de donnees."},
    {"step": "02", "label": "Croiser", "sentence": "Carte, presse, webcams, agenda et rumeurs convergent vers trois decisions."},
    {"step": "03", "label": "Parler", "sentence": "Le Vice-PM interroge AYA a voix haute sur la Zone Nord."},
    {"step": "04", "label": "Arbitrer", "sentence": "AYA propose les options et la fenetre de decision avant 15h00."},
]

LIBRARY_ITEMS = [
    {
        "id": "lib-briefing-template",
        "title": "Modele briefing vice-presidence",
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
]

MAP_ZONES = [
    {
        "id": "zone-nord",
        "name": "Nord",
        "level": 85,
        "tone": "critical",
        "centroid": {"x": 410, "y": 98},
        "polygon": "374,62 455,74 489,130 444,168 366,152 342,105",
        "signals": ["Projet social en retard", "Rumeurs recurrentes", "Faible presence institutionnelle"],
        "recommendations": ["Rencontre autorites locales", "Communication ciblee", "Mission terrain non militaire"],
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


def _clone(value: Any) -> Any:
    return copy.deepcopy(value)


def source_index() -> list[dict[str, Any]]:
    return _clone(SOURCES)


def _workspace_meta(workspace: Workspace) -> dict[str, Any]:
    return {"id": workspace.id, "slug": workspace.slug, "name": workspace.name}


def _risk_rank(level: str | None) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(str(level or "low").lower(), 1)


def _confidence(value: Any) -> float:
    try:
        score = float(value or 0)
    except (TypeError, ValueError):
        score = 0.0
    if score > 1:
        score = score / 100
    return round(max(0.34, min(score or 0.62, 0.94)), 2)


def _short_text(value: str | None, limit: int = 190) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _infer_zone(text: str) -> str:
    normalized = (text or "").lower()
    if any(token in normalized for token in ("abidjan", "plateau", "yamoussoukro", "côte d'ivoire", "cote d'ivoire", "ivory coast")):
        return "Cote d'Ivoire"
    if any(token in normalized for token in ("mali", "sahel", "bamako", "niger", "burkina")):
        return "Sahel / Afrique de l'Ouest"
    if any(token in normalized for token in ("ghana", "liberia", "guinea", "guinée", "gambia", "sierra leone")):
        return "Afrique de l'Ouest"
    if any(token in normalized for token in ("congo", "rdc", "uganda", "kenya", "nairobi")):
        return "Afrique élargie"
    return "Veille ouverte"


def _action_for_risk(level: str | None) -> str:
    rank = _risk_rank(level)
    if rank >= 3:
        return "Demander une note cabinet courte, qualifier les sources primaires et préparer une communication préventive."
    if rank == 2:
        return "Maintenir la veille, vérifier la convergence des sources et préparer un point de langage si le signal se confirme."
    return "Conserver en suivi, sans action ministérielle immédiate."


def _feed_scope(category: str | None) -> str:
    return FEED_CATEGORY_SCOPE.get(str(category or "").lower(), "world")


def _feed_viewpoint(category: str | None) -> str:
    scope = _feed_scope(category)
    if scope == "ci":
        return "politique interieure ivoirienne"
    if scope == "cedeao":
        return "politique regionale CEDEAO"
    if scope == "africa":
        return "politique africaine"
    return "politique internationale"


def _feed_rows(db: Optional[DBSession], workspace: Workspace) -> list[dict[str, Any]]:
    if not db:
        return [
            {"name": name, "url": url, "category": category, "active": True}
            for name, url, category in SENTINEL_NEWS_FEEDS
        ]
    rows = db.query(FeedSource).filter(FeedSource.workspace_id == workspace.id).all()
    return [
        {
            "name": row.name,
            "url": row.url,
            "category": row.category,
            "active": bool(row.active),
            "article_count": row.article_count or 0,
        }
        for row in rows
    ]


def _geographic_priority_payload(feed_rows: list[dict[str, Any]], signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload = []
    for scope, label, description in GEOGRAPHIC_PRIORITY_ORDER:
        feeds = [row for row in feed_rows if row.get("active") and _feed_scope(row.get("category")) == scope]
        scope_signals = [
            signal for signal in signals
            if str(signal.get("geography_tier") or _feed_scope(signal.get("source_category"))).lower() == scope
            or (scope == "ci" and "cote d'ivoire" in str(signal.get("zone") or signal.get("source") or "").lower())
        ]
        payload.append(
            {
                "key": scope,
                "label": label,
                "priority": len(payload) + 1,
                "description": description,
                "feed_count": len(feeds),
                "signal_count": len(scope_signals),
                "sources": [row.get("name") for row in feeds[:6]],
                "focus": [signal.get("title") for signal in scope_signals[:3]],
            }
        )
    return payload


def _news_viewpoints_payload(feed_rows: list[dict[str, Any]], signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = [
        ("interior", "Politique interieure ivoirienne", {"ci"}),
        ("regional", "Politique regionale CEDEAO", {"cedeao", "africa"}),
        ("international", "Politique internationale", {"world", "africa"}),
    ]
    payload = []
    for key, label, scopes in groups:
        feeds = [row for row in feed_rows if row.get("active") and _feed_scope(row.get("category")) in scopes]
        group_signals = [
            signal for signal in signals
            if any(scope in str(signal.get("geography_tier") or "").lower() for scope in scopes)
            or (key == "interior" and "ivoirienne" in str(signal.get("viewpoint") or "").lower())
            or (key == "international" and "internationale" in str(signal.get("viewpoint") or "").lower())
        ]
        payload.append(
            {
                "key": key,
                "label": label,
                "feed_count": len(feeds),
                "signal_count": len(group_signals),
                "sources": [row.get("name") for row in feeds[:6]],
                "brief": (
                    "Lecture prioritaire des impacts interieur, emotions publiques, rumeurs et attentes de presence."
                    if key == "interior"
                    else "Lecture des effets de voisinage, partenaires, diplomatie et perception internationale."
                ),
            }
        )
    return payload


def _social_listening_payload(signals: list[dict[str, Any]]) -> dict[str, Any]:
    social_signals = [
        signal for signal in signals
        if str(signal.get("id") or "").startswith("social-") or "social" in str(signal.get("source") or "").lower()
    ]
    return {
        "status": "demo_public_sources",
        "policy": "Pas de scraping prive WhatsApp/Facebook ; uniquement signaux publics, signalements terrain et connecteurs autorises.",
        "channels": [
            {"key": "x", "label": "X public", "coverage": 38, "status": "connector_ready"},
            {"key": "facebook_public", "label": "Pages Facebook publiques", "coverage": 34, "status": "connector_ready"},
            {"key": "whatsapp_reports", "label": "Signalements WhatsApp terrain", "coverage": 22, "status": "human_reported"},
        ],
        "signals": social_signals,
        "rumor_origins": [
            {
                "label": signal.get("title"),
                "origin": signal.get("origin") or "Origine a qualifier",
                "zone": signal.get("zone") or signal.get("source"),
                "confidence": signal.get("confidence", 0.58),
                "recommended_action": signal.get("recommended_action"),
            }
            for signal in social_signals[:4]
        ],
    }


def _latest_intelligence_run(db: DBSession, workspace: Workspace) -> Optional[Run]:
    systems = db.query(System).filter(System.workspace_id == workspace.id).all()
    preferred = _system_for_navigation_item(
        _system_map(db, workspace),
        systems,
        {"variant": "intelligence"},
    )
    query = db.query(Run).filter(Run.workspace_id == workspace.id)
    if preferred:
        query = query.filter(Run.system_id == preferred.id)
    else:
        recent = query.order_by(Run.started_at.desc()).limit(25).all()
        return next((run for run in recent if (run.input_ref or {}).get("source") == "intelligence.analyze"), None)
    return query.order_by(Run.started_at.desc()).first()


def _executive_news_payload(workspace: Workspace, db: Optional[DBSession]) -> dict[str, Any]:
    """Bridge News Lab diagnostics into a ministerial, advisory payload."""
    feed_rows = _feed_rows(db, workspace)
    fallback = {
        "workspace": _workspace_meta(workspace),
        "signals": _clone(NEWS_SIGNALS),
        "executive_alerts": _clone(NEWS_SIGNALS),
        "summary": "Lecture double : politique interieure ivoirienne prioritaire, avec contrepoint CEDEAO/Afrique/monde pour anticiper perception et diplomatie.",
        "briefing_note": {
            "headline": "Veille ouverte qualifiee CI + international",
            "bullets": [
                "Cote d'Ivoire : rumeurs, emotion publique et projets sensibles demandent une lecture cabinet rapide.",
                "CEDEAO / Golfe de Guinee : surveiller les effets transfrontaliers et narratifs regionaux.",
                "International : garder le contrepoint partenaires Europe/USA/Asie pour anticiper pression et opportunites.",
            ],
            "talking_points": [
                "Coordination preventive avec les autorites locales.",
                "Continuité des services publics et suivi transparent des projets.",
                "AYA peut expliquer l'origine d'une rumeur, la zone touchee et l'action recommandee.",
            ],
            "decisions_expected": [
                "Valider les elements de langage presse.",
                "Mandater une note cabinet sur les zones nord.",
                "Qualifier le signal social prioritaire avant toute action publique.",
            ],
        },
        "source_health": {
            "active_feeds": len([row for row in feed_rows if row.get("active")]),
            "total_articles": 0,
            "analyzed": 0,
            "high_risk": len([s for s in NEWS_SIGNALS if s.get("risk_level") == "high"]),
            "last_run_id": None,
            "last_run_status": "fixture",
            "coverage_label": "CI -> CEDEAO -> Afrique -> Monde",
            "live_news_used": False,
            "geography_order": [item[0] for item in GEOGRAPHIC_PRIORITY_ORDER],
        },
        "media_sources": _clone(
            [
                {"label": "Presse ivoirienne", "coverage": 84, "count": 5},
                {"label": "CEDEAO / voisins", "coverage": 68, "count": 1},
                {"label": "Afrique + international", "coverage": 72, "count": 6},
                {"label": "Rumeurs / social", "coverage": 41, "count": 3},
            ]
        ),
        "geographic_priority": _geographic_priority_payload(feed_rows, _clone(NEWS_SIGNALS)),
        "viewpoints": _news_viewpoints_payload(feed_rows, _clone(NEWS_SIGNALS)),
        "social_listening": _social_listening_payload(_clone(NEWS_SIGNALS)),
        "sources": source_index(),
    }
    if not db:
        return fallback

    try:
        from app.services.intelligence.batch import get_dashboard_data

        dashboard = get_dashboard_data(db, workspace_id=workspace.id)
    except Exception:
        return fallback

    latest_run = _latest_intelligence_run(db, workspace)
    kpis = dashboard.get("kpis") or {}
    synthesis = dashboard.get("synthesis") or {}
    articles = dashboard.get("articles") or []
    ranked = sorted(
        articles,
        key=lambda article: (
            _risk_rank(article.get("risk_level")),
            float(article.get("relevance_score") or 0),
            article.get("published_at") or "",
        ),
        reverse=True,
    )
    if not ranked:
        fallback["source_health"].update(
            {
                "active_feeds": kpis.get("active_feeds", 0),
                "total_articles": kpis.get("total_articles", 0),
                "analyzed": kpis.get("analyzed", 0),
                "last_run_id": latest_run.id if latest_run else None,
                "last_run_status": latest_run.status if latest_run else "standby",
            }
        )
        return fallback

    dynamic_sources: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    for idx, article in enumerate(ranked[:5]):
        source_id = f"src-live-news-{idx + 1}"
        title = _short_text(article.get("title") or "Signal de veille", 110)
        summary = _short_text(article.get("summary") or title)
        risk_level = str(article.get("risk_level") or "medium").lower()
        source_category = article.get("source_category")
        zone = _infer_zone(f"{title} {summary} {' '.join(article.get('entities') or [])}")
        confidence = _confidence(article.get("relevance_score"))
        dynamic_sources.append(
            {
                "id": source_id,
                "label": _short_text(title, 76),
                "kind": "rss_press_local" if _feed_scope(source_category) == "ci" else "rss_press",
                "confidence": confidence,
                "age": "flux public",
            }
        )
        alerts.append(
            {
                "id": f"live-news-{article.get('id') or idx}",
                "article_id": article.get("id"),
                "title": title,
                "risk_level": risk_level,
                "sentiment": article.get("sentiment") or "neutral",
                "summary": summary,
                "source": zone,
                "source_name": article.get("source_name"),
                "source_category": source_category,
                "sources": [source_id],
                "zone": zone,
                "geography_tier": _feed_scope(source_category),
                "viewpoint": _feed_viewpoint(source_category),
                "origin": article.get("source_name") or "Flux RSS public",
                "impact_ci": (
                    "Impact direct a qualifier pour la Cote d'Ivoire."
                    if zone == "Cote d'Ivoire"
                    else "Signal regional a surveiller pour ses effets de perception, cooperation ou coordination publique."
                ),
                "why_it_matters": summary,
                "recommended_action": _action_for_risk(risk_level),
                "confidence": confidence,
                "source_count": 1,
                "url": article.get("url"),
                "run_id": latest_run.id if latest_run else None,
                "entities": article.get("entities") or [],
            }
        )

    total = int(kpis.get("total_articles") or 0)
    analyzed = int(kpis.get("analyzed") or 0)
    active = int(kpis.get("active_feeds") or 0)
    high_risk = int(kpis.get("high_risk") or 0)
    analyzed_pct = round((analyzed / total) * 100) if total else 0
    high_pct = round((high_risk / max(analyzed, 1)) * 100) if analyzed else 0
    entity_names = [item.get("name") for item in (dashboard.get("top_entities") or []) if item.get("name")]
    key_findings = [_short_text(item, 170) for item in (synthesis.get("key_findings") or []) if item][:3]
    bullets = key_findings or [
        "La veille publique est disponible et doit etre qualifiee avant diffusion cabinet.",
        "Les signaux regionaux sont a relier aux priorites Cote d'Ivoire.",
        "Les alertes haut risque restent advisory-only et sources-requises.",
    ]
    payload = {
        "workspace": _workspace_meta(workspace),
        "signals": alerts[:3],
        "executive_alerts": alerts[:3],
        "summary": synthesis.get("summary") or fallback["summary"],
        "briefing_note": {
            "headline": "Brief presse et signaux faibles",
            "bullets": bullets,
            "talking_points": [
                "Répondre uniquement sur faits sourcés et convergence de sources publiques.",
                "Qualifier l'impact Côte d'Ivoire avant toute prise de parole.",
                "Rappeler le caractère préventif et non militaire des actions proposées.",
            ],
            "decisions_expected": [
                "Qualifier les alertes prioritaires pour point cabinet.",
                "Valider ou ajourner les éléments de langage associés.",
                "Promouvoir les signaux confirmés vers la base Knowledge.",
            ],
        },
        "source_health": {
            "active_feeds": active,
            "total_articles": total,
            "analyzed": analyzed,
            "high_risk": high_risk,
            "last_run_id": latest_run.id if latest_run else None,
            "last_run_status": latest_run.status if latest_run else "standby",
            "last_updated": latest_run.completed_at.isoformat() + "Z" if latest_run and latest_run.completed_at else None,
            "coverage_label": f"{active} sources · priorite CI puis CEDEAO/Afrique/Monde",
            "live_news_used": True,
            "source_entities": entity_names[:8],
            "geography_order": [item[0] for item in GEOGRAPHIC_PRIORITY_ORDER],
        },
        "media_sources": [
            {"label": "Sources actives", "coverage": 100 if active else 0, "count": active},
            {"label": "Articles analyses", "coverage": analyzed_pct, "count": analyzed},
            {"label": "Signaux prioritaires", "coverage": high_pct, "count": high_risk},
            {"label": "Confiance sources", "coverage": round(sum(a["confidence"] for a in alerts) / max(len(alerts), 1) * 100), "count": len(alerts)},
        ],
        "geographic_priority": _geographic_priority_payload(feed_rows, [*alerts, *_clone(NEWS_SIGNALS)]),
        "viewpoints": _news_viewpoints_payload(feed_rows, [*alerts, *_clone(NEWS_SIGNALS)]),
        "social_listening": _social_listening_payload(_clone(NEWS_SIGNALS)),
        "analysis_link": {
            "system_id": latest_run.system_id if latest_run else None,
            "run_id": latest_run.id if latest_run else None,
            "label": "Atelier de veille",
        },
        "sources": [*source_index(), *dynamic_sources],
    }
    return payload


def _system_map(db: DBSession, workspace: Workspace) -> dict[str, System]:
    systems = db.query(System).filter(System.workspace_id == workspace.id).all()
    result: dict[str, System] = {}
    for system in systems:
        variant = (system.flow_definition or {}).get("variant")
        if variant and variant not in result:
            result[str(variant)] = system
    return result


def _system_for_navigation_item(
    systems_by_variant: dict[str, System],
    all_systems: list[System],
    item: dict[str, Any],
) -> Optional[System]:
    """Pick the concrete System behind a mission-room rail item.

    A workspace can legitimately contain more than one ``variant=intelligence``
    System: the generic News Lab seed plus a mission-room-specific open
    intelligence System. For SENTINEL-CI's Presse/Veille/Reputation entries we
    want the latter, otherwise users land on the right surface but with the
    wrong product object. The selector stays generic by preferring the
    ``template_id`` produced by the workspace-app seed and only falling back to
    the first variant match.
    """
    variant = str(item.get("variant") or "")
    if variant == "intelligence":
        preferred = next(
            (
                system
                for system in all_systems
                if (system.flow_definition or {}).get("template_id") == "sentinel-ci-intelligence"
            ),
            None,
        )
        if preferred:
            return preferred
        named = next(
            (
                system
                for system in all_systems
                if str((system.flow_definition or {}).get("variant")) == "intelligence"
                and "veille" in (system.name or "").lower()
            ),
            None,
        )
        if named:
            return named
    return systems_by_variant.get(variant)


def navigation_payload(db: DBSession, workspace: Workspace) -> dict[str, Any]:
    all_systems = db.query(System).filter(System.workspace_id == workspace.id).all()
    systems_by_variant = _system_map(db, workspace)
    api_by_view = {
        "cockpit": "/api/v1/mission-room/cockpit",
        "monitor": "/api/v1/mission-room/monitor",
        "briefing": "/api/v1/mission-room/briefing",
        "pilotage": "/api/v1/mission-room/projects",
        "agenda": "/api/v1/mission-room/timeline",
        "messages": "/api/v1/mission-room/timeline",
        "bibliotheque": "/api/v1/mission-room/library",
        "projets": "/api/v1/mission-room/projects",
        "presse": "/api/v1/mission-room/news",
        "reputation": "/api/v1/mission-room/news",
        "veille": "/api/v1/mission-room/news",
        "decisions": "/api/v1/mission-room/decisions",
        "strategie": "/api/v1/mission-room/map",
        "recherche": "/api/v1/mission-room/search",
        "assistant": "/api/v1/chat/stream",
    }
    items: list[dict[str, Any]] = []
    for item in NAVIGATION_ITEMS:
        system = _system_for_navigation_item(systems_by_variant, all_systems, item)
        items.append(
            {
                **item,
                "route": f"{MISSION_ROOM_ROOT}/{item['key']}",
                "api": api_by_view[item["key"]],
                "system_id": system.id if system else None,
                "system_name": system.name if system else None,
                "workbench": item["object"],
            }
        )
    return {
        "workspace": _workspace_meta(workspace),
        "app": {
            "label": "SENTINEL-CI",
            "assistant_label": SENTINEL_ASSISTANT_NAME,
            "shell": "immersive",
            "default_route": MISSION_ROOM_ROUTE,
            "default_view": "cockpit",
        },
        "items": items,
        "exit_routes": [
            {"label": "Agentium OS", "route": "/systems"},
            {"label": "Workspace Admin", "route": f"/workspace/{workspace.slug}"},
        ],
    }


def overview_payload(workspace: Workspace) -> dict[str, Any]:
    return {
        "workspace": _workspace_meta(workspace),
        "title": "Bonjour, M. le Vice-Président.",
        "date_label": "Mercredi 15 Avril 2026",
        "mode": "demo",
        "briefing_status": "ready",
        "decision_sentence": _clone(DECISION_SENTENCE),
        "attention_required": _clone(ATTENTION_REQUIRED),
        "sixty_second_cockpit": {
            "urgences": _clone(ATTENTION_REQUIRED),
            "agenda_focus": _clone(AGENDA[:1]),
            "menace": {"label": "Zone Nord", "score": 85, "tone": "critical", "deadline": "15:00"},
            "reputation": {"score": 63, "delta": 5, "sentence": "Un article necessite votre attention ; les autres signaux sont gerables."},
        },
        "territorial_live_status": _clone(TERRITORIAL_LIVE_STATUS),
        "voice_demo_script": _clone(VOICE_DEMO_SCRIPT),
        "executive_decision_packages": _clone(EXECUTIVE_DECISION_PACKAGES),
        "rumor_trace": _clone(RUMOR_TRACE),
        "demo_value_metrics": _clone(DEMO_VALUE_METRICS),
        "presentation_beats": _clone(PRESENTATION_BEATS),
        "priorities": _clone(PRIORITIES),
        "kpis": {
            "press_alerts": 16,
            "negative_articles": 16,
            "emails": 5,
            "urgent_emails": 2,
            "meetings": 5,
            "next_meeting_in": "1h46",
            "reputation_score": 50,
            "analyzed_articles": 80,
            "ops_operational_pct": 68,
            "ops_watch_pct": 22,
            "ops_critical_pct": 10,
        },
        "threat_trend": [42, 39, 41, 55, 49, 60, 38, 69],
        "communications_flow": [
            {"hour": "06h", "institutional": 12, "press": 8},
            {"hour": "08h", "institutional": 35, "press": 26},
            {"hour": "10h", "institutional": 46, "press": 34},
            {"hour": "12h", "institutional": 29, "press": 31},
            {"hour": "14h", "institutional": 38, "press": 28},
            {"hour": "16h", "institutional": 43, "press": 30},
            {"hour": "18h", "institutional": 22, "press": 18},
            {"hour": "20h", "institutional": 8, "press": 5},
        ],
        "agenda": _clone(AGENDA),
        "zones": [{"name": z["name"], "level": z["level"], "tone": z["tone"]} for z in MAP_ZONES],
        "reputation": {
            "score": 63,
            "delta": 5,
            "trend": [51, 45, 57, 43, 49, 60, 63],
        },
        "media_sources": [
            {"label": "Presse nationale", "coverage": 72, "count": 45},
            {"label": "Presse internationale", "coverage": 58, "count": 28},
            {"label": "Reseaux sociaux", "coverage": 41, "count": 156},
            {"label": "Agences de presse", "coverage": 65, "count": 18},
        ],
        "latest_alerts": _clone(NEWS_SIGNALS),
        "keywords": [
            {"label": "Vice-presidence CI", "count": 340, "delta": 12},
            {"label": "Coordination nationale", "count": 280, "delta": 8},
            {"label": "Sahel CI", "count": 195, "delta": 24},
            {"label": "Continuite gouvernementale", "count": 120, "delta": -5},
            {"label": "Cooperation France", "count": 95, "delta": 3},
        ],
        "assistant_prompts": [
            "Prepare-moi le brief pour le conseil restreint de 8h30.",
            "Pourquoi l'alerte Nord est-elle prioritaire ?",
            "Quelles zones demandent une action preventive non militaire ?",
        ],
        "sources": source_index(),
    }


def _agenda_items_from_calendar(workspace: Workspace, db: Optional[DBSession]) -> list[dict[str, Any]]:
    if not db:
        return _clone(AGENDA)
    events = list_calendar_events(db, workspace)
    if not events:
        return _clone(AGENDA)
    return [
        {
            **serialize_calendar_event(event),
            "sources": ["src-agenda-jour-015"],
        }
        for event in events[:8]
    ]


def cockpit_payload(workspace: Workspace, db: Optional[DBSession] = None) -> dict[str, Any]:
    overview = overview_payload(workspace)
    news = _executive_news_payload(workspace, db)
    visual = _visual_payload(workspace, db)
    mapped = map_payload(workspace, db=db)
    posture = _strategic_posture(mapped, news, visual)
    calendar_summary = calendar_summary_payload(db, workspace) if db else None
    alerts = news.get("executive_alerts") or news.get("signals") or _clone(NEWS_SIGNALS)
    source_health = news.get("source_health") or {}
    if alerts:
        live_priorities = [
            {
                "id": f"prio-{alert.get('id')}",
                "kind": "decision_required",
                "title": alert.get("title"),
                "summary": alert.get("impact_ci") or alert.get("summary"),
                "deadline": "avant point cabinet",
                "sources": alert.get("sources") or [],
                "tone": "critical" if _risk_rank(alert.get("risk_level")) >= 3 else "watch",
            }
            for alert in alerts[:2]
        ]
        overview["priorities"] = [overview["priorities"][0], *live_priorities][:3]
    overview["latest_alerts"] = alerts[:3]
    overview["media_sources"] = news.get("media_sources") or overview["media_sources"]
    overview["kpis"].update(
        {
            "press_alerts": source_health.get("high_risk", overview["kpis"]["press_alerts"]),
            "negative_articles": source_health.get("high_risk", overview["kpis"]["negative_articles"]),
            "analyzed_articles": source_health.get("analyzed", overview["kpis"]["analyzed_articles"]),
            "active_feeds": source_health.get("active_feeds", 0),
            "total_articles": source_health.get("total_articles", 0),
        }
    )
    overview["press_intelligence"] = source_health
    overview["visual_summary"] = visual.get("source_health") or {}
    overview["strategic_posture"] = posture
    overview["situation_monitor"] = {
        "route": f"{MISSION_ROOM_ROOT}/monitor",
        "posture": posture,
        "top_zones": (mapped.get("zones") or [])[:3],
        "visual": visual.get("latest_observation"),
        "source_freshness": {
            "news": source_health.get("coverage_label", "Veille qualifiee"),
            "visual": (visual.get("source_health") or {}).get("coverage_label", "Flux visuels habilites"),
        },
    }
    overview["what_changed"] = (news.get("briefing_note") or {}).get("bullets") or []
    overview["sources"] = news.get("sources") or overview["sources"]
    overview["agenda"] = _agenda_items_from_calendar(workspace, db)
    if calendar_summary:
        overview["calendar"] = calendar_summary
        overview["kpis"]["meetings"] = calendar_summary.get("count", overview["kpis"]["meetings"])
        overview["kpis"]["calendar_conflicts"] = len(calendar_summary.get("conflicts") or [])
        next_event = calendar_summary.get("next_event")
        if next_event:
            overview["kpis"]["next_meeting_in"] = f"{next_event.get('time')} · {next_event.get('title')}"
    return {
        **overview,
        "layout": {
            "variant": "executive_grid",
            "density": "desktop_laptop",
            "charts": ["threat_trend", "communications_flow", "ops_state", "reputation", "media_sources", "keyword_trends"],
        },
        "decision_focus": _clone(DECISIONS[:2]),
        "messages": _clone(MESSAGES),
        "library": _clone(LIBRARY_ITEMS),
    }


def briefing_payload(workspace: Workspace) -> dict[str, Any]:
    return {
        "workspace": _workspace_meta(workspace),
        "title": "Briefing quotidien vice-présidence",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "sections": [
            {
                "id": "situation",
                "title": "Situation du jour",
                "content": "La journee combine un conseil restreint, un point presse et un sujet nord prioritaire. Les signaux presse convergent avec un retard projet territorial.",
                "sources": ["src-cabinet-brief-001", "src-press-rfi-017"],
            },
            {
                "id": "risks",
                "title": "Risques principaux",
                "content": "Risque d'amplification mediatique au Nord si aucune action institutionnelle visible n'est annoncee avant la fin de journee.",
                "sources": ["src-project-sante-042", "src-press-rfi-017"],
            },
            {
                "id": "decisions",
                "title": "Decisions attendues",
                "content": "Arbitrer une mission terrain non militaire, valider les elements de langage presse et decider d'une relance cabinet sur le projet rouge.",
                "sources": ["src-agenda-jour-015", "src-project-sante-042"],
            },
            {
                "id": "talking_points",
                "title": "Elements de langage",
                "content": "Insister sur la coordination preventive, la continuite des services publics et le suivi transparent des projets territoriaux.",
                "sources": ["src-cabinet-brief-001"],
            },
        ],
        "actions": [
            {"id": "act-brief-dircab", "label": "Créer instruction Directeur de cabinet", "target": "proj-health-north"},
            {"id": "act-press-lines", "label": "Valider éléments de langage presse", "target": "proj-civic-radio"},
            {"id": "act-map-zones", "label": "Afficher carte des zones prioritaires", "target": "zone-nord"},
        ],
        "sources": source_index(),
    }


def _scenario_options_for(target_id: str) -> list[dict[str, Any]]:
    risk_level = "high" if any(token in target_id for token in ("health", "north", "nord", "red")) else "medium"
    target_kind = "zone" if any(token in target_id for token in ("zone", "nord", "north")) else ("project" if "proj" in target_id else "decision")
    return generate_scenarios(
        target_kind=target_kind,
        target_id=target_id,
        risk_level=risk_level,
        source_refs=["src-cabinet-brief-001", "src-press-rfi-017"],
        signal_strength=78 if risk_level == "high" else 52,
        agenda_pressure=60 if risk_level == "high" else 30,
    )


def _recommended_windows_for(target_id: str) -> list[dict[str, Any]]:
    if "nord" in target_id or "north" in target_id:
        return [
            {
                "label": "Avant point presse",
                "start": "10:00",
                "end": "10:45",
                "why": "Dernier creneau avant expression publique et avant amplification potentielle.",
            },
            {
                "label": "Apres revue operations",
                "start": "16:10",
                "end": "16:45",
                "why": "Fenetre utile pour arbitrage cabinet avant sequence parlementaire.",
            },
        ]
    return [
        {
            "label": "Creneau cabinet court",
            "start": "12:00",
            "end": "12:25",
            "why": "Fenetre de coordination avant prochaine sequence institutionnelle.",
        }
    ]


def projects_payload(workspace: Workspace, db: Optional[DBSession] = None) -> dict[str, Any]:
    projects = _clone(PROJECTS)
    action_rows = list_action_items(db, workspace, include_cancelled=False) if db else []
    actions_by_target = {item.target_id: serialize_action_item(item) for item in action_rows}
    for project in projects:
        project["scenario_options"] = _scenario_options_for(project["id"])
        if project["id"] in actions_by_target:
            project["active_action"] = actions_by_target[project["id"]]
    return {
        "workspace": _workspace_meta(workspace),
        "summary": {
            "total": len(projects),
            "red": sum(1 for p in projects if p["weather"] == "red"),
            "orange": sum(1 for p in projects if p["weather"] == "orange"),
            "green": sum(1 for p in projects if p["weather"] == "green"),
        },
        "projects": projects,
        "sources": source_index(),
    }


def map_payload(workspace: Workspace, db: Optional[DBSession] = None) -> dict[str, Any]:
    if db:
        mapped = mission_room_map_payload(db, workspace)
        return {
            "workspace": _workspace_meta(workspace),
            "question": "Quelles zones necessitent une action preventive non militaire ce mois-ci ?",
            **mapped,
            "sources": source_index(),
        }
    zones = _clone(MAP_ZONES)
    action_rows = list_action_items(db, workspace, include_cancelled=False, target_kind="zone") if db else []
    actions_by_target = {item.target_id: serialize_action_item(item) for item in action_rows}
    for zone in zones:
        zone["recommended_windows"] = _recommended_windows_for(zone["id"])
        if zone["id"] in actions_by_target:
            zone["active_action"] = actions_by_target[zone["id"]]
    return {
        "workspace": _workspace_meta(workspace),
        "question": "Quelles zones necessitent une action preventive non militaire ce mois-ci ?",
        "map": {
            "country": "Cote d'Ivoire",
            "view_box": "200 40 470 480",
            "projection": "illustrative_exec_demo",
            "accuracy": "strategic_demo_not_geospatial_reference",
        },
        "zones": zones,
        "recommended_windows": [
            {"zone": zone["name"], "target_id": zone["id"], **(zone["recommended_windows"][0] if zone.get("recommended_windows") else {})}
            for zone in zones
        ],
        "sources": source_index(),
    }


def monitor_payload(workspace: Workspace, db: Optional[DBSession] = None) -> dict[str, Any]:
    mapped = map_payload(workspace, db=db)
    news = news_payload(workspace, db=db)
    visual = _visual_payload(workspace, db)
    calendar_summary = calendar_summary_payload(db, workspace) if db else None
    action_rows = list_action_items(db, workspace, include_cancelled=False) if db else []
    action_items = [serialize_action_item(row) for row in action_rows[:6]]
    action_summary = action_plan_summary_payload(db, workspace) if db else {}
    posture = _strategic_posture(mapped, news, visual, calendar_summary=calendar_summary, action_summary=action_summary)
    zones = mapped.get("zones") or []
    top_zones = sorted(zones, key=lambda item: int(item.get("level") or 0), reverse=True)[:3]
    visual_observations = visual.get("observations") or []
    cross_source_signals = _cross_source_signals(
        mapped,
        news,
        visual,
        calendar_summary=calendar_summary,
        action_summary=action_summary,
        action_items=action_items,
    )
    scenario = _scenario_fusion_payload(
        workspace,
        mapped,
        posture,
        cross_source_signals,
        calendar_summary=calendar_summary,
        action_summary=action_summary,
    )
    forecasts = [
        {
            "id": "forecast-nord-briefing",
            "title": "Narratif nord sous surveillance",
            "summary": "La combinaison presse + projet territorial maintient une fenetre d'action preventive avant le prochain briefing.",
            "level": "elevated" if posture.get("label") in {"elevated", "critical"} else "monitoring",
            "horizon": "24-48h",
            "confidence": 0.68,
        },
        {
            "id": "forecast-visual-normal",
            "title": "Flux visuels exploitables",
            "summary": (visual.get("latest_observation") or {}).get("summary")
            or "Aucune observation visuelle critique n'est disponible pour modifier la posture.",
            "level": (visual.get("posture") or {}).get("label", "monitoring"),
            "horizon": "prochain cycle",
            "confidence": (visual.get("latest_observation") or {}).get("confidence", 0.62),
        },
    ]
    layers = [
        {"key": "territorial-risk", "label": "Zones territoriales", "enabled": True, "count": len(zones)},
        {"key": "open-intelligence", "label": "Signaux presse", "enabled": True, "count": len(news.get("executive_alerts") or news.get("signals") or [])},
        {"key": "regional-context", "label": "Contexte CEDEAO / Golfe de Guinee", "enabled": True, "count": len([item for item in (news.get("geographic_priority") or []) if item.get("key") in {"cedeao", "africa"}])},
        {"key": "social-rumors", "label": "Rumeurs et origines", "enabled": True, "count": len((news.get("social_listening") or {}).get("rumor_origins") or [])},
        {"key": "projects", "label": "Projets sensibles", "enabled": True, "count": len(PROJECTS)},
        {"key": "agenda", "label": "Contraintes agenda", "enabled": True, "count": len(_agenda_items_from_calendar(workspace, db))},
        {"key": "visual-streams", "label": "Flux visuels", "enabled": True, "count": len(visual_observations)},
    ]
    return {
        "workspace": _workspace_meta(workspace),
        "title": "Mission Control Room",
        "summary": posture["summary"],
        "decision_sentence": _clone(DECISION_SENTENCE),
        "attention_required": _clone(ATTENTION_REQUIRED),
        "sixty_second_cockpit": {
            "urgences": _clone(ATTENTION_REQUIRED),
            "agenda_focus": _agenda_items_from_calendar(workspace, db)[:1],
            "menace": {"label": "Zone Nord", "score": 85, "tone": "critical", "deadline": "15:00"},
            "reputation": {"score": 63, "delta": 5, "sentence": "Un article necessite votre attention ; les autres signaux sont gerables."},
        },
        "territorial_live_status": _clone(TERRITORIAL_LIVE_STATUS),
        "voice_demo_script": _clone(VOICE_DEMO_SCRIPT),
        "executive_decision_packages": _clone(EXECUTIVE_DECISION_PACKAGES),
        "rumor_trace": _clone(RUMOR_TRACE),
        "demo_value_metrics": _clone(DEMO_VALUE_METRICS),
        "presentation_beats": _clone(PRESENTATION_BEATS),
        "scenario": scenario,
        "posture": posture,
        "layers": layers,
        "panel_layout": _mission_control_panel_layout(layers, news, visual, calendar_summary, cross_source_signals),
        "cross_source_signals": cross_source_signals,
        "voice_context": _aya_voice_context(scenario, cross_source_signals),
        "map": mapped.get("map"),
        "map_system": mapped.get("map_system"),
        "zones": zones,
        "top_zones": top_zones,
        "visual": visual,
        "visual_observations": visual_observations,
        "agenda": _agenda_items_from_calendar(workspace, db)[:6],
        "calendar": calendar_summary,
        "action_items": action_items,
        "action_summary": action_summary,
        "forecasts": forecasts,
        "news_signals": (news.get("executive_alerts") or news.get("signals") or [])[:5],
        "source_freshness": {
            "news": (news.get("source_health") or {}).get("coverage_label") or "Veille qualifiee",
            "visual": (visual.get("source_health") or {}).get("coverage_label") or "Flux visuels habilites",
            "map": (mapped.get("score_summary") or {}).get("top_zone", {}).get("name") if mapped.get("score_summary") else None,
        },
        "sources": source_index(),
    }


def news_payload(workspace: Workspace, db: Optional[DBSession] = None) -> dict[str, Any]:
    return _executive_news_payload(workspace, db)


def _visual_payload(workspace: Workspace, db: Optional[DBSession]) -> dict[str, Any]:
    if not db:
        return {
            "connector": {
                "id": "visual_streams",
                "label": "Flux visuels institutionnels",
                "status": "configured",
                "mode": "snapshot_only",
            },
            "source_health": {
                "active_sources": 1,
                "total_sources": 1,
                "captures": 0,
                "observations": 0,
                "coverage_label": "Flux visuels habilites",
            },
            "posture": {
                "label": "monitoring",
                "score": 38,
                "trend": "stable",
                "summary": "Posture en surveillance : source visuelle preparee pour capture ponctuelle.",
            },
            "sources": [],
            "captures": [],
            "observations": [],
            "latest_observation": None,
        }
    ensure_visual_intelligence_seed(db, workspace)
    return visual_dashboard_payload(db, workspace)


def _strategic_posture(
    mapped: dict[str, Any],
    news: dict[str, Any],
    visual: dict[str, Any],
    *,
    calendar_summary: Optional[dict[str, Any]] = None,
    action_summary: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    top_zone = ((mapped.get("score_summary") or {}).get("top_zone") or {})
    zone_score = int(top_zone.get("level") or top_zone.get("score", {}).get("score") or 0)
    high_risk = int((news.get("source_health") or {}).get("high_risk") or 0)
    visual_score = int((visual.get("posture") or {}).get("score") or 0)
    agenda_score = int((calendar_summary or {}).get("conflict_score") or 0)
    if not agenda_score:
        agenda_score = min(100, len((calendar_summary or {}).get("conflicts") or []) * 22 + len((calendar_summary or {}).get("decision_deadlines") or []) * 9)
    action_score = min(100, int((action_summary or {}).get("critical") or 0) * 28 + int((action_summary or {}).get("active") or 0) * 8)
    score = max(zone_score, min(100, high_risk * 18), visual_score, agenda_score, action_score)
    if score >= 75:
        label = "critical"
    elif score >= 55:
        label = "elevated"
    elif score >= 35:
        label = "monitoring"
    else:
        label = "stable"
    return {
        "label": label,
        "score": score,
        "trend": "stable" if label in {"stable", "monitoring"} else "a surveiller",
        "summary": (
            "Posture globale elevee : rapprocher zones territoriales, presse et observations visuelles avant arbitrage."
            if label in {"critical", "elevated"}
            else "Posture globale en surveillance : les signaux restent exploitables sans alerte visuelle critique automatisee."
        ),
        "drivers": [
            {"kind": "territorial", "label": top_zone.get("name") or "Zones", "score": zone_score},
            {"kind": "press", "label": "Signaux presse prioritaires", "score": high_risk},
            {"kind": "visual", "label": "Flux visuels", "score": visual_score},
            {"kind": "agenda", "label": "Contraintes agenda", "score": agenda_score},
            {"kind": "actions", "label": "Actions ouvertes", "score": action_score},
        ],
    }


def _signal_level(score: int) -> str:
    if score >= 75:
        return "critical"
    if score >= 55:
        return "elevated"
    if score >= 35:
        return "monitoring"
    return "stable"


def _cross_source_signals(
    mapped: dict[str, Any],
    news: dict[str, Any],
    visual: dict[str, Any],
    *,
    calendar_summary: Optional[dict[str, Any]],
    action_summary: Optional[dict[str, Any]],
    action_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    top_zone = ((mapped.get("score_summary") or {}).get("top_zone") or {})
    zone_score = int(top_zone.get("level") or top_zone.get("score", {}).get("score") or 0)
    alerts = news.get("executive_alerts") or news.get("signals") or []
    high_risk = int((news.get("source_health") or {}).get("high_risk") or 0)
    press_score = min(100, high_risk * 24 + len(alerts[:3]) * 7)
    visual_score = int((visual.get("posture") or {}).get("score") or 0)
    latest_observation = visual.get("latest_observation") or {}
    social = news.get("social_listening") or {}
    rumor_origins = social.get("rumor_origins") or []
    rumor_score = min(100, len(rumor_origins) * 18 + round(max([float(item.get("confidence") or 0.0) for item in rumor_origins] or [0.0]) * 52))
    agenda_score = int((calendar_summary or {}).get("conflict_score") or 0)
    agenda_score = agenda_score or min(
        100,
        len((calendar_summary or {}).get("conflicts") or []) * 24
        + len((calendar_summary or {}).get("decision_deadlines") or []) * 10,
    )
    action_score = min(
        100,
        int((action_summary or {}).get("critical") or 0) * 30
        + int((action_summary or {}).get("active") or 0) * 9,
    )
    rows = [
        {
            "id": "territorial-risk",
            "type": "territorial",
            "label": "Carte territoriale",
            "summary": f"{top_zone.get('name') or 'Zone prioritaire'} concentre le niveau de vigilance territorial le plus eleve.",
            "severity": _signal_level(zone_score),
            "score": zone_score,
            "source_keys": ["territorial_action_map", "workspace_map_scores"],
            "related_zone": top_zone.get("id"),
            "action_prompt": "Filtrer la carte sur la zone prioritaire et preparer les options non militaires.",
        },
        {
            "id": "press-escalation",
            "type": "press",
            "label": "Presse et signaux faibles",
            "summary": f"{high_risk} signal(aux) prioritaire(s) detectes dans la veille ouverte.",
            "severity": _signal_level(press_score),
            "score": press_score,
            "source_keys": ["open_intelligence_watch", "rss_feeds"],
            "related_zone": (alerts[0] or {}).get("zone") if alerts else None,
            "action_prompt": "Demander a AYA une synthese sourcee des alertes presse.",
        },
        {
            "id": "visual-activity",
            "type": "visual",
            "label": "Flux webcams",
            "summary": latest_observation.get("summary") or "Flux Abidjan/Cote d'Ivoire disponibles pour controle visuel live.",
            "severity": _signal_level(visual_score),
            "score": visual_score,
            "source_keys": ["visual_situation_watch", "visual_streams"],
            "related_zone": latest_observation.get("zone_id"),
            "action_prompt": "Ouvrir le flux webcam le plus parlant avant arbitrage.",
        },
        {
            "id": "social-rumor-origin",
            "type": "social",
            "label": "Rumeurs et origines",
            "summary": (
                f"{len(rumor_origins)} origine(s) de rumeur ou d'emoi public a qualifier avant action."
                if rumor_origins
                else "Connecteurs sociaux publics prepares : aucune origine prioritaire ne depasse le seuil demo."
            ),
            "severity": _signal_level(rumor_score),
            "score": rumor_score,
            "source_keys": ["social_listening_public", "field_reports", "open_intelligence_watch"],
            "related_zone": (rumor_origins[0] or {}).get("zone") if rumor_origins else None,
            "action_prompt": "Demander a AYA l'origine de la rumeur prioritaire et l'action de presence recommandee.",
        },
        {
            "id": "agenda-pressure",
            "type": "agenda",
            "label": "Agenda institutionnel",
            "summary": (calendar_summary or {}).get("summary") or "Agenda consolide sans conflit critique declare.",
            "severity": _signal_level(agenda_score),
            "score": agenda_score,
            "source_keys": ["government_calendar_assist", "institutional_calendar"],
            "related_zone": None,
            "action_prompt": "Verifier les fenetres d'arbitrage disponibles aujourd'hui.",
        },
        {
            "id": "action-readiness",
            "type": "actions",
            "label": "Actions cabinet",
            "summary": f"{(action_summary or {}).get('active', len(action_items))} action(s) active(s), prochaine echeance a cadrer.",
            "severity": _signal_level(action_score),
            "score": action_score,
            "source_keys": ["action_planner", "scenario_recommendations"],
            "related_zone": (action_items[0] or {}).get("target_id") if action_items else None,
            "action_prompt": "Transformer le signal en action cabinet avec responsable et echeance.",
        },
    ]
    active_categories = [row for row in rows if int(row["score"]) >= 35]
    if len(active_categories) >= 3:
        composite_score = min(100, max(int(row["score"]) for row in active_categories) + len(active_categories) * 4)
        rows.insert(
            0,
            {
                "id": "scenario-composite",
                "type": "composite",
                "label": "Correlation crise nationale",
                "summary": "Plusieurs familles de signaux convergent : terrain visuel, presse, carte, agenda ou actions.",
                "severity": _signal_level(composite_score),
                "score": composite_score,
                "source_keys": [row["id"] for row in active_categories],
                "related_zone": top_zone.get("id"),
                "action_prompt": "Demander a AYA une posture croisee et les trois decisions possibles.",
            },
        )
    return sorted(rows, key=lambda item: int(item["score"]), reverse=True)


def _scenario_fusion_payload(
    workspace: Workspace,
    mapped: dict[str, Any],
    posture: dict[str, Any],
    cross_source_signals: list[dict[str, Any]],
    *,
    calendar_summary: Optional[dict[str, Any]],
    action_summary: Optional[dict[str, Any]],
) -> dict[str, Any]:
    top_zone = ((mapped.get("score_summary") or {}).get("top_zone") or {})
    level = posture.get("label") or _signal_level(int(posture.get("score") or 0))
    score = int(posture.get("score") or 0)
    top_signals = cross_source_signals[:3]
    return {
        "id": "scenario-crise-nationale",
        "title": "Crise nationale",
        "status": "active",
        "mode": "cross_source_monitoring",
        "workspace_slug": workspace.slug,
        "level": level,
        "score": score,
        "timezone": "Africa/Abidjan",
        "time_window": "0-48h",
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "summary": (
            "Scenario Crise nationale actif : AYA croise webcams, presse, carte, agenda et actions pour soutenir le suivi gouvernemental."
        ),
        "focus_zone": top_zone.get("name") or "Cote d'Ivoire",
        "map_focus": {
            "zone_id": top_zone.get("id"),
            "label": top_zone.get("name") or "Cote d'Ivoire",
            "score": int(top_zone.get("level") or top_zone.get("score", {}).get("score") or score),
        },
        "contributing_signals": [signal["id"] for signal in top_signals],
        "agenda_impacts": {
            "conflicts": len((calendar_summary or {}).get("conflicts") or []),
            "decision_deadlines": len((calendar_summary or {}).get("decision_deadlines") or []),
            "next_event": (calendar_summary or {}).get("next_event"),
        },
        "action_readiness": {
            "active": int((action_summary or {}).get("active") or 0),
            "critical": int((action_summary or {}).get("critical") or 0),
            "next_due": (action_summary or {}).get("next_due"),
        },
        "recommended_actions": [
            "Verifier le flux webcam prioritaire et noter l'observation utile au briefing.",
            "Demander a AYA une synthese sourcee presse + cartographie avant decision.",
            "Bloquer une fenetre agenda pour arbitrage et convertir le signal en action cabinet.",
        ],
    }


def _mission_control_panel_layout(
    layers: list[dict[str, Any]],
    news: dict[str, Any],
    visual: dict[str, Any],
    calendar_summary: Optional[dict[str, Any]],
    cross_source_signals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {"key": "map", "region": "stage", "order": 1, "label": "Carte centrale", "visible": True, "live": True, "count": next((layer["count"] for layer in layers if layer["key"] == "territorial-risk"), 0)},
        {"key": "layers", "region": "left", "order": 1, "label": "Couches", "visible": True, "live": True, "count": len(layers)},
        {"key": "live-news", "region": "bottom", "order": 1, "label": "Live News", "visible": True, "live": True, "count": len(news.get("executive_alerts") or news.get("signals") or [])},
        {"key": "live-webcams", "region": "bottom", "order": 2, "label": "Live Webcams", "visible": True, "live": True, "count": int((visual.get("source_health") or {}).get("active_sources") or 0)},
        {"key": "agenda-actions", "region": "bottom", "order": 3, "label": "Agenda / Actions", "visible": True, "live": False, "count": (calendar_summary or {}).get("count", 0)},
        {"key": "ai-insights", "region": "right", "order": 1, "label": "AI Insights", "visible": True, "live": True, "count": len(cross_source_signals)},
        {"key": "strategic-posture", "region": "right", "order": 2, "label": "Strategic Posture", "visible": True, "live": True, "count": 1},
        {"key": "aya", "region": "right", "order": 3, "label": SENTINEL_ASSISTANT_NAME, "visible": True, "live": True, "count": 5},
    ]


def _aya_voice_context(scenario: dict[str, Any], cross_source_signals: list[dict[str, Any]]) -> dict[str, Any]:
    prompts = [
        "AYA, donne-moi la synthese du scenario croise.",
        "AYA, ouvre la camera Pont General-de-Gaulle.",
        "AYA, filtre la carte sur Abidjan.",
        "AYA, quels impacts agenda aujourd'hui ?",
        "AYA, d'ou vient la rumeur prioritaire ?",
        "AYA, separe politique interieure ivoirienne et perception internationale.",
        "AYA, montre la lecture CEDEAO autour de la Cote d'Ivoire.",
        "AYA, prepare une instruction executive.",
    ]
    return {
        "assistant": SENTINEL_ASSISTANT_NAME,
        "mode": "voice_first",
        "capability": "voice2voice_interaction",
        "transport": "backend_ws",
        "language": "fr-CI",
        "scenario_id": scenario.get("id"),
        "session_hint": "sentinel-ci-mission-control",
        "prompts": prompts,
        "demo_script": _clone(VOICE_DEMO_SCRIPT),
        "presentation_beats": _clone(PRESENTATION_BEATS),
        "decision_packages": _clone(EXECUTIVE_DECISION_PACKAGES),
        "rumor_trace": _clone(RUMOR_TRACE),
        "commands": [
            {"utterance": prompts[0], "intent": "scenario_brief", "target": scenario.get("id")},
            {"utterance": prompts[1], "intent": "visual_focus", "target": "pont-general-de-gaulle"},
            {"utterance": prompts[2], "intent": "map_focus", "target": "abidjan"},
            {"utterance": prompts[3], "intent": "agenda_impacts", "target": "today"},
            {"utterance": prompts[4], "intent": "rumor_origin", "target": "social-rumor-origin"},
            {"utterance": prompts[5], "intent": "political_viewpoint_split", "target": "news_viewpoints"},
            {"utterance": prompts[6], "intent": "regional_map_focus", "target": "regional-context"},
            {"utterance": prompts[7], "intent": "instruction_draft", "target": (cross_source_signals[0] or {}).get("id") if cross_source_signals else None},
        ],
        "fallback": "text_chat_overlay",
    }


def timeline_payload(workspace: Workspace, db: Optional[DBSession] = None) -> dict[str, Any]:
    calendar_summary = calendar_summary_payload(db, workspace) if db else None
    action_items = [serialize_action_item(row) for row in list_action_items(db, workspace, include_cancelled=False)[:6]] if db else []
    return {
        "workspace": _workspace_meta(workspace),
        "agenda": _agenda_items_from_calendar(workspace, db),
        "action_items": action_items,
        "messages": _clone(MESSAGES),
        "summary": (calendar_summary or {}).get("summary")
        or "Agenda et messages institutionnels consolides depuis les canaux habilites.",
        "calendar": calendar_summary,
        "conflicts": (calendar_summary or {}).get("conflicts") or [],
        "recommended_moves": (calendar_summary or {}).get("recommended_moves") or [],
        "decision_deadlines": (calendar_summary or {}).get("decision_deadlines") or [],
        "sources": source_index(),
    }


def decisions_payload(workspace: Workspace, db: Optional[DBSession] = None) -> dict[str, Any]:
    action_items = [serialize_action_item(row) for row in list_action_items(db, workspace, include_cancelled=True)] if db else []
    return {
        "workspace": _workspace_meta(workspace),
        "decisions": _clone(DECISIONS),
        "action_items": action_items,
        "action_summary": action_plan_summary_payload(db, workspace) if db else {},
        "scenario_options": _scenario_options_for("decision-press-lines"),
        "policy": {
            "advisory_only": True,
            "human_validation_required": True,
            "external_delivery": "requires_human_validation",
        },
        "sources": source_index(),
    }


def library_payload(workspace: Workspace) -> dict[str, Any]:
    return {
        "workspace": _workspace_meta(workspace),
        "items": _clone(LIBRARY_ITEMS),
        "collections": [
            "sentinel-ci-ministerial-briefs",
            "sentinel-ci-open-intelligence",
            "sentinel-ci-projects",
            "sentinel-ci-territorial-map",
            "sentinel-ci-territorial-intelligence",
            "sentinel-ci-visual-intelligence",
        ],
        "sources": source_index(),
    }


def search_payload(workspace: Workspace, query: str) -> dict[str, Any]:
    normalized = (query or "").strip().lower()
    candidates: list[dict[str, Any]] = []
    for item in [*PRIORITIES, *NEWS_SIGNALS, *PROJECTS, *MAP_ZONES, *MESSAGES, *DECISIONS, *LIBRARY_ITEMS]:
        text = " ".join(str(value) for value in item.values()).lower()
        if not normalized or normalized in text:
            candidates.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title") or item.get("name") or item.get("subject"),
                    "kind": item.get("kind") or item.get("target_type") or item.get("weather") or "signal",
                    "summary": item.get("summary") or item.get("risk") or item.get("recommendation") or "",
                    "sources": item.get("sources") or [],
                }
            )
    return {
        "workspace": _workspace_meta(workspace),
        "query": query,
        "results": candidates[:20],
        "total": len(candidates),
        "sources": source_index(),
    }


def draft_instruction_payload(
    *,
    workspace: Workspace,
    actor: str,
    target_id: str,
    target_type: str,
    instruction_type: str = "dircab_instruction",
    db: Optional[DBSession] = None,
) -> dict[str, Any]:
    project = next((p for p in PROJECTS if p["id"] == target_id), None)
    zone = next((z for z in MAP_ZONES if z["id"] == target_id), None)
    title = project["name"] if project else zone["name"] if zone else target_id
    if project:
        body = (
            f"Merci de preparer sous 24h une note d'arbitrage sur le projet '{project['name']}'. "
            f"Le projet est a {project['progress']}% au lieu de {project['expected']}%, "
            f"avec un retard estime de {project['delay_days']} jours. Cause probable : {project['cause']} "
            f"Risque identifie : {project['risk']} Proposer trois options : relance cabinet, mission terrain "
            "non militaire, ou replanification avec jalons de controle."
        )
        sources = project["sources"]
    elif zone:
        body = (
            f"Merci de coordonner une action preventive non militaire sur la zone {zone['name']}. "
            f"Niveau d'alerte {zone['level']}%. Signaux : {', '.join(zone['signals'])}. "
            f"Actions proposees : {', '.join(zone['recommendations'])}."
        )
        sources = zone["sources"]
    else:
        body = "Merci de preparer une instruction cabinet sur le sujet signale, avec sources, risque et options d'action."
        sources = []

    payload = {
        "status": "draft",
        "requires_validation": True,
        "sent": False,
        "instruction_type": instruction_type,
        "target_type": target_type,
        "target_id": target_id,
        "title": f"Instruction cabinet - {title}",
        "recipient": "Directeur de cabinet",
        "body": body,
        "sources": sources,
        "control": {
            "human_authority_required": True,
            "external_delivery": "requires_human_validation",
            "audit": "recorded",
        },
    }
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="mission_room.instruction.drafted",
        actor=actor,
        details=payload,
    )
    return payload


def _slug_skill_ids(db: DBSession, slugs: Iterable[str]) -> list[str]:
    rows = db.query(Skill).filter(Skill.slug.in_(list(slugs))).all()
    by_slug = {row.slug: row.id for row in rows}
    return [by_slug[slug] for slug in slugs if slug in by_slug]


def _capability_by_slug(db: DBSession, slug: str) -> Optional[Capability]:
    return db.query(Capability).filter(Capability.slug == slug).first()


def _ensure_collection(db: DBSession, workspace: Workspace, slug: str, name: str, description: str) -> None:
    existing = (
        db.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == workspace.id, KnowledgeCollection.slug == slug)
        .first()
    )
    if existing:
        existing.name = name
        existing.description = description
        return
    db.add(
        KnowledgeCollection(
            workspace_id=workspace.id,
            slug=slug,
            name=name,
            description=description,
            status="created",
            document_names=[],
            vector_collection_name=f"{workspace.slug}__{slug}",
            artifact_prefix=f"workspaces/{workspace.id}/collections/{slug}",
            embedding_model="text-embedding-3-small",
            chunking_method="semantic",
            chunking_params={"demo": True, "source": "sentinel-ci"},
        )
    )


def _ensure_feed(db: DBSession, workspace: Workspace, name: str, url: str, category: str) -> None:
    existing = (
        db.query(FeedSource)
        .filter(FeedSource.workspace_id == workspace.id, FeedSource.url == url)
        .first()
    )
    if existing:
        existing.name = name
        existing.category = category
        existing.active = True
        return
    db.add(
        FeedSource(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name=name,
            url=url,
            category=category,
            refresh_interval=3600,
            active=True,
        )
    )


def _ensure_target(db: DBSession, workspace: Workspace) -> None:
    name = "SENTINEL-CI ministerial signals"
    description = (
        "Cote d'Ivoire ministerial watch with geographic priority CI -> CEDEAO -> Africa -> World: "
        "domestic politics, public emotion, social rumors, government continuity, territorial security, "
        "industrial/government project steering, regional diplomacy, cooperation narratives and crisis communication."
    )
    keywords = [
        "Cote d'Ivoire",
        "Ivory Coast",
        "Abidjan",
        "Yamoussoukro",
        "politique ivoirienne",
        "politique interieure",
        "Afrique de l'Ouest",
        "CEDEAO",
        "West Africa",
        "Sahel",
        "Golfe de Guinee",
        "presidence",
        "vice-presidence",
        "securite",
        "rumeur",
        "reseaux sociaux",
        "social listening",
        "emoi public",
        "projet public",
        "pilotage industriel",
        "cooperation",
    ]
    existing = (
        db.query(SemanticTarget)
        .filter(SemanticTarget.workspace_id == workspace.id, SemanticTarget.name == name)
        .first()
    )
    if existing:
        existing.description = description
        existing.keywords = keywords
        existing.relevance_threshold = 0.16
        existing.active = True
        return
    db.add(
        SemanticTarget(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name=name,
            description=description,
            keywords=keywords,
            relevance_threshold=0.16,
            active=True,
        )
    )


def _ensure_filter(db: DBSession, workspace: Workspace) -> None:
    name = "Ministerial demo safety"
    existing = (
        db.query(SafetyFilter)
        .filter(SafetyFilter.workspace_id == workspace.id, SafetyFilter.name == name)
        .first()
    )
    if existing:
        return
    db.add(
        SafetyFilter(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name=name,
            prompt_template=(
                "Flag unsafe operational instructions, personal data exposure, or unsourced escalatory claims. "
                "Allow neutral public-interest news summaries and advisory non-military recommendations."
            ),
            severity="flag",
            active=True,
        )
    )


def _ensure_rag_preset(db: DBSession, workspace: Workspace) -> None:
    name = "SENTINEL-CI C-HAH briefing preset"
    existing_by_name = (
        db.query(RagPreset)
        .filter(RagPreset.workspace_id == workspace.id, RagPreset.name == name)
        .first()
    )
    existing_default = (
        db.query(RagPreset)
        .filter(
            RagPreset.workspace_id == workspace.id,
            RagPreset.scope == "workspace",
            RagPreset.scope_id == workspace.id,
            RagPreset.is_default.is_(True),
        )
        .first()
    )
    config = {
        "mode": "chah",
        "ragPipelineMode": "chah",
        "rag_pipeline_mode": "chah",
        "ragCollectionName": "sentinel-ci-open-intelligence",
        "topK": 6,
        "ragTopK": 6,
        "promptType": "executive_briefing",
        "asyncRetrieval": True,
        "sourcePolicy": "sources_required",
        "experience": {"demoSafeProviderLabels": True, "advisoryOnly": True},
    }
    existing = existing_default or existing_by_name
    if existing:
        if existing_by_name and existing_by_name.id != existing.id:
            existing_by_name.is_default = False
        existing.name = name
        existing.config = config
        existing.scope = "workspace"
        existing.scope_id = workspace.id
        existing.workspace_id = workspace.id
        existing.is_default = True
        return
    db.add(
        RagPreset(
            workspace_id=workspace.id,
            name=name,
            scope="workspace",
            scope_id=workspace.id,
            config=config,
            is_default=True,
        )
    )


def _flow(slug: str, skill_slugs: list[str], label: str) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {"id": "source.workspace_signals", "type": "source", "label": "Workspace signals", "position": {"x": 40, "y": 120}},
    ]
    edges: list[dict[str, Any]] = []
    previous = "source.workspace_signals"
    for idx, skill_slug in enumerate(skill_slugs):
        node_id = f"skill.{skill_slug}"
        nodes.append(
            {
                "id": node_id,
                "type": "skill",
                "kind": "task",
                "label": skill_slug.replace("_v1", "").replace("_", " ").title(),
                "position": {"x": 320 + idx * 280, "y": 120},
                "config": {"skill_slug": skill_slug},
            }
        )
        edges.append({"from": previous, "to": node_id, "kind": "data"})
        previous = node_id
    nodes.append({"id": "sink.advisory_output", "type": "sink", "label": label, "position": {"x": 360 + len(skill_slugs) * 280, "y": 120}})
    edges.append({"from": previous, "to": "sink.advisory_output", "kind": "control"})
    return {
        "schema_version": 2,
        "variant": slug,
        "template_id": f"sentinel-ci-{slug}",
        "template_name": label,
        "nodes": nodes,
        "edges": edges,
        "policy": {"advisory_only": True, "human_validation_required": True, "sources_required": True},
        "retrieval": {"mode": "chah", "top_k": 6, "non_blocking": True},
        "voice_runtime": {"capability": "voice2voice_interaction", "transport": "backend_ws"},
    }


def _ensure_system(
    db: DBSession,
    workspace: Workspace,
    *,
    name: str,
    objective: str,
    capability_slug: str,
    skill_slugs: list[str],
    variant: str,
    execution_mode: str = "human_augmented",
    legacy_names: Optional[list[str]] = None,
) -> Optional[System]:
    capability = _capability_by_slug(db, capability_slug)
    if not capability:
        return None
    skill_ids = _slug_skill_ids(db, skill_slugs)
    existing = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.name.in_([name, *(legacy_names or [])]))
        .first()
    )
    flow = _flow(variant, skill_slugs, name)
    if existing:
        existing.name = name
        existing.objective = objective
        existing.capability_id = capability.id
        existing.skill_ids = skill_ids
        existing.flow_definition = flow
        existing.status = "active"
        existing.execution_mode = execution_mode
        existing.coordination_pattern = "multi_agent" if len(skill_slugs) > 2 else "single_agent"
        existing.retrieval_mode_default = "chah"
        existing.execution_profile = {
            "demo": True,
            "advisory_only": True,
            "default_route": MISSION_ROOM_ROUTE,
            "voice": "voice2voice_interaction",
        }
        return existing
    system = System(
        workspace_id=workspace.id,
        name=name,
        objective=objective,
        capability_id=capability.id,
        skill_ids=skill_ids,
        flow_definition=flow,
        execution_mode=execution_mode,
        execution_profile={
            "demo": True,
            "advisory_only": True,
            "default_route": MISSION_ROOM_ROUTE,
            "voice": "voice2voice_interaction",
        },
        coordination_pattern="multi_agent" if len(skill_slugs) > 2 else "single_agent",
        status="active",
        created_by="system:sentinel_ci_seed",
        retrieval_mode_default="chah",
    )
    db.add(system)
    return system


def ensure_sentinel_ci_workspace(db: DBSession) -> dict[str, int | str]:
    """Create/update the portable government mission-room demo workspace."""
    workspace = db.query(Workspace).filter(Workspace.slug == SENTINEL_WORKSPACE_SLUG).first()
    created = 0
    if not workspace:
        workspace = Workspace(
            id=str(uuid4()),
            name=SENTINEL_WORKSPACE_NAME,
            slug=SENTINEL_WORKSPACE_SLUG,
            mode="demo",
            settings={},
        )
        db.add(workspace)
        db.flush()
        created = 1
    workspace.name = SENTINEL_WORKSPACE_NAME
    workspace.mode = "demo"
    settings = dict(workspace.settings or {})
    settings.update(
        {
            "demo_profile": "government_mission_room",
            "default_route": MISSION_ROOM_ROUTE,
            "hide_provider_details": True,
            "workspace_app_shell": "immersive",
            "workspace_app_label": SENTINEL_WORKSPACE_NAME,
            "workspace_app_default_view": "cockpit",
            "calendar": {
                "mode": "internal_shared",
                "connector_id": "institutional_calendar",
                "connector_label": "Agenda institutionnel",
                "write_policy": "direct",
                "timezone": "Africa/Abidjan",
            },
            "demo_time_context": {
                "mode": "fixed",
                "current_date": "2026-04-15",
                "label": "Mercredi 15 Avril 2026",
                "timezone": "Africa/Abidjan",
            },
            "action_planner": {
                "write_policy": "direct",
                "default_owner": "Cabinet",
                "advisory_only": True,
            },
            "visual_intelligence": {
                "enabled": True,
                "capture_cadence_minutes": 60,
                "allowed_adapters": ["demo_static", "http_image", "browser_screenshot"],
                "storage_policy": "snapshot_only_no_continuous_recording",
                "analysis_policy": "no_identification_no_biometrics",
                "source_model": "live_webcam_embed_layer",
            },
            "connectors": {
                "institutional_calendar": {
                    "enabled": True,
                    "status": "connected",
                    "mode": "internal_shared",
                    "label": "Agenda institutionnel",
                },
                "visual_streams": {
                    "enabled": True,
                    "status": "connected",
                    "mode": "live_webcam_embed_layer",
                    "label": "Flux visuels institutionnels",
                },
            },
            "assistant_profile_default": "vigie_executive",
            "knowledge_scopes": [
                {
                    "key": "vigie",
                    "label": "Presse + Rumeurs + Projets + Carte",
                    "description": "Sources qualifiees CI, CEDEAO, internationales et signaux sociaux publics pour briefing gouvernemental.",
                    "collection_slugs": [
                        "sentinel-ci-open-intelligence",
                        "sentinel-ci-projects",
                        "sentinel-ci-ministerial-briefs",
                        "sentinel-ci-territorial-map",
                        "sentinel-ci-territorial-intelligence",
                        "sentinel-ci-visual-intelligence",
                    ],
                    "default_mode": "chah",
                    "top_k": 8,
                    "is_default": True,
                },
                {
                    "key": "open_intelligence",
                    "label": "Presse, rumeurs et signaux faibles",
                    "description": "Articles RSS, syntheses News Lab et origines de rumeurs publiques consolides.",
                    "collection_slugs": ["sentinel-ci-open-intelligence"],
                    "default_mode": "chah",
                    "top_k": 8,
                    "is_default": False,
                },
            ],
            "assistant_profiles": [
                {
                    "key": "vigie_executive",
                    "label": SENTINEL_ASSISTANT_NAME,
                    "subtitle": "Assistante stratégique · Sources qualifiees",
                    "default_knowledge_scope": "vigie",
                    "executive_mode": True,
                    "tone": "ministerial",
                    "allowed_actions": [
                        "cite_sources",
                        "draft_instruction",
                        "open_news_lab",
                        "read_calendar",
                        "create_calendar_event",
                        "update_calendar_event",
                        "cancel_calendar_event",
                        "create_action_plan",
                        "reschedule_action_plan",
                        "status_action_plan",
                        "cancel_action_plan",
                        "set_time_context",
                        "read_visual_observations",
                        "capture_visual_snapshot",
                        "control_strategic_map",
                        "read_social_signals",
                        "trace_rumor_origin",
                        "explain_geographic_priority",
                    ],
                    "allowed_calendar_actions": [
                        "read_calendar",
                        "create_calendar_event",
                        "update_calendar_event",
                        "cancel_calendar_event",
                    ],
                    "hidden_controls": [
                        "provider",
                        "model",
                        "system_picker",
                        "retrieval",
                        "reasoning",
                        "voice_runtime",
                    ],
                    "prompt_pack": [
                        {
                            "icon": "newspaper",
                            "label": "Synthèse du jour",
                            "prompt": "Quels signaux nécessitent une attention cabinet aujourd'hui ?",
                        },
                        {
                            "icon": "shield-check",
                            "label": "Sources et confiance",
                            "prompt": "Quelles sources soutiennent cette alerte ?",
                        },
                        {
                            "icon": "check-circle",
                            "label": "Décision requise",
                            "prompt": "Quels arbitrages sont attendus cette semaine ?",
                        },
                        {
                            "icon": "message-square",
                            "label": "Langage public",
                            "prompt": "Prépare des éléments de langage prudents et sourcés.",
                        },
                        {
                            "icon": "pulse",
                            "label": "Origine rumeur",
                            "prompt": "D'ou vient la rumeur prioritaire et quelle action recommandes-tu ?",
                        },
                        {
                            "icon": "layers",
                            "label": "Double lecture",
                            "prompt": "Separe politique interieure ivoirienne et perception internationale.",
                        },
                        {
                            "icon": "crosshair",
                            "label": "Carte region",
                            "prompt": "Montre la lecture CEDEAO autour de la Cote d'Ivoire.",
                        },
                    ],
                }
            ],
            "mission_room": {
                "enabled": True,
                "country": "Cote d'Ivoire",
                "country_code": "CI",
                "region_scope": ["Cote d'Ivoire", "West Africa", "Sahel", "Gulf of Guinea"],
                "news_source_policy": "African public RSS first; synthetic demo fixtures only when feeds are unavailable.",
                "label": SENTINEL_ASSISTANT_NAME,
                "root_route": MISSION_ROOM_ROOT,
                "default_view": "cockpit",
                "navigation": NAVIGATION_ITEMS,
            },
        }
    )
    workspace.settings = settings

    members_added = 0
    users = db.query(User).filter(User.is_active.is_(True)).all()
    for index, user in enumerate(users):
        existing = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == user.id)
            .first()
        )
        if existing:
            continue
        role_template = WORKSPACE_OWNER if user.role == "admin" or index == 0 else WORKSPACE_CONTRIBUTOR
        db.add(
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=user.id,
                role=legacy_role_for_template(role_template),
                role_template=role_template,
                custom_labels=["demo:true", "domain:government"],
            )
        )
        members_added += 1

    for slug, name, description in (
        ("sentinel-ci-ministerial-briefs", "SENTINEL-CI Ministerial Briefs", "Briefings, agenda syntheses and validated talking points."),
        ("sentinel-ci-open-intelligence", "SENTINEL-CI Open Intelligence", "Public news and weak-signal summaries for ministerial watch."),
        ("sentinel-ci-projects", "SENTINEL-CI Strategic Projects", "Strategic project records and decision-support risk explanations."),
        ("sentinel-ci-territorial-map", "SENTINEL-CI Territorial Map", "Territorial zones, signals and non-military action recommendations."),
        ("sentinel-ci-territorial-intelligence", "SENTINEL-CI Territorial Intelligence", "Fused territorial scores from news, projects, agenda, visual observations and recommended action windows."),
        ("sentinel-ci-visual-intelligence", "SENTINEL-CI Visual Intelligence", "Visual snapshots and observations from authorized workspace streams."),
    ):
        _ensure_collection(db, workspace, slug, name, description)

    for name, url, category in SENTINEL_NEWS_FEEDS:
        _ensure_feed(db, workspace, name, url, category)
    _ensure_target(db, workspace)
    _ensure_filter(db, workspace)
    _ensure_rag_preset(db, workspace)
    ensure_calendar_seed(db, workspace)
    ensure_action_plan_seed(db, workspace)

    system_specs = [
        {
            "name": "SENTINEL-CI Mission Room",
            "legacy_names": ["ARIA / SENTINEL-CI Mission Room"],
            "objective": "Consolider briefing, signaux faibles, projets, carte et actions ministerielles sous controle humain.",
            "capability_slug": "government_mission_room",
            "skill_slugs": [
                "ministerial_briefing_v1",
                "news_signal_synthesis_v1",
                "project_risk_explainer_v1",
                "territorial_signal_map_v1",
                "instruction_draft_v1",
                "scenario_generate_v1",
                "scenario_compare_v1",
                "scenario_recommend_v1",
                "map_layer_read_v1",
                "map_zone_score_v1",
                "map_signal_attach_v1",
                "map_recommendation_generate_v1",
                "visual_source_read_v1",
                "visual_snapshot_capture_v1",
                "visual_snapshot_analyze_v1",
                "visual_observation_sync_knowledge_v1",
                "calendar_read_v1",
                "calendar_create_event_v1",
                "calendar_update_event_v1",
                "calendar_cancel_event_v1",
                "calendar_daily_summary_v1",
                "action_plan_create_v1",
                "action_plan_reschedule_v1",
                "action_plan_status_v1",
                "action_plan_cancel_v1",
                "time_context_set_v1",
                "territorial_action_window_v1",
                "voice_tandem_oracle_v1",
                "audit_log_v1",
            ],
            "variant": "government_mission_room",
        },
        {
            "name": "Briefing Quotidien Vice-Presidence",
            "objective": "Produire un briefing sourcé : priorites, risques, decisions attendues, actions et elements de langage.",
            "capability_slug": "ministerial_daily_briefing",
            "skill_slugs": ["ministerial_briefing_v1", "calendar_daily_summary_v1", "action_plan_status_v1", "llm_rag_answer_v1", "audit_log_v1"],
            "variant": "ministerial_daily_briefing",
        },
        {
            "name": "Veille Presse & Signaux Faibles",
            "objective": "Agreger presse ivoirienne, CEDEAO, internationale et signaux publics de rumeurs pour detecter les sujets sensibles avant escalation.",
            "capability_slug": "open_intelligence_watch",
            "skill_slugs": ["intelligence_batch_v1", "news_signal_synthesis_v1", "audit_log_v1"],
            "variant": "intelligence",
            "execution_mode": "continuous_monitoring",
        },
        {
            "name": "Scenario Fusion Monitor",
            "objective": "Fusionner webcams, presse, carte, agenda et actions pour maintenir le scenario Crise nationale et la posture strategique.",
            "capability_slug": "scenario_fusion_monitor",
            "skill_slugs": [
                "news_signal_synthesis_v1",
                "territorial_signal_map_v1",
                "map_layer_read_v1",
                "map_zone_score_v1",
                "visual_source_read_v1",
                "visual_snapshot_analyze_v1",
                "calendar_daily_summary_v1",
                "action_plan_status_v1",
                "scenario_generate_v1",
                "scenario_compare_v1",
                "scenario_recommend_v1",
                "chain_mixed_hah_v1",
                "voice_tandem_oracle_v1",
                "audit_log_v1",
            ],
            "variant": "scenario_fusion_monitor",
            "execution_mode": "continuous_monitoring",
        },
        {
            "name": "Pilotage Projets Strategiques",
            "objective": "Expliquer les projets rouges, causes probables, risques et options d'arbitrage.",
            "capability_slug": "strategic_project_pilotage",
            "skill_slugs": ["project_risk_explainer_v1", "scenario_generate_v1", "scenario_compare_v1", "scenario_recommend_v1", "semantic_search_v1", "instruction_draft_v1", "action_plan_create_v1", "action_plan_status_v1", "audit_log_v1"],
            "variant": "strategic_project_pilotage",
        },
        {
            "name": "Carte Strategique Executive",
            "objective": "Afficher les zones d'action preventive non militaire avec signaux, sources et recommandations.",
            "capability_slug": "territorial_action_map",
            "skill_slugs": ["territorial_signal_map_v1", "territorial_action_window_v1", "map_layer_read_v1", "map_zone_score_v1", "map_signal_attach_v1", "map_recommendation_generate_v1", "chain_mixed_hah_v1", "audit_log_v1"],
            "variant": "territorial_action_map",
        },
        {
            "name": "Live Visual Monitor",
            "legacy_names": ["Situation Monitor Visuel"],
            "objective": "Lire des flux visuels habilites, produire des observations snapshot-only et les synchroniser dans la connaissance.",
            "capability_slug": "visual_situation_watch",
            "skill_slugs": ["visual_source_read_v1", "visual_snapshot_capture_v1", "visual_snapshot_analyze_v1", "visual_observation_sync_knowledge_v1", "territorial_signal_map_v1", "chain_mixed_hah_v1", "audit_log_v1"],
            "variant": "visual_situation_watch",
            "execution_mode": "continuous_monitoring",
        },
        {
            "name": "Government Calendar Assist",
            "objective": "Lire l'agenda institutionnel, qualifier les conflits et proposer les fenetres d'arbitrage.",
            "capability_slug": "government_calendar_assist",
            "skill_slugs": ["calendar_read_v1", "calendar_daily_summary_v1", "calendar_create_event_v1", "calendar_update_event_v1", "calendar_cancel_event_v1", "action_plan_status_v1", "audit_log_v1"],
            "variant": "government_calendar_assist",
        },
        {
            "name": "AYA Voice Command",
            "objective": "Piloter la Mission Control Room en voice-first : briefing, camera, carte regionale, rumeurs, agenda et instructions.",
            "capability_slug": "aya_voice_command",
            "skill_slugs": ["voice_tandem_oracle_v1", "voice_realtime_session_v1", "llm_rag_answer_v1", "audit_log_v1"],
            "variant": "aya_voice_command",
        },
        {
            "name": "Instructions Cabinet",
            "objective": "Rediger des brouillons d'instruction sources et soumis a validation humaine.",
            "capability_slug": "executive_instruction_drafting",
            "skill_slugs": ["instruction_draft_v1", "claim_audit_v1", "audit_log_v1"],
            "variant": "executive_instruction_drafting",
        },
    ]
    systems_created = 0
    for spec in system_specs:
        before = db.query(System).filter(System.workspace_id == workspace.id, System.name == spec["name"]).count()
        _ensure_system(db, workspace, **spec)
        if before == 0:
            systems_created += 1
    map_system = db.query(System).filter(System.workspace_id == workspace.id, System.name == "Carte Strategique Executive").first()
    ensure_workspace_map_seed(db, workspace, system_id=map_system.id if map_system else None)
    visual_system = db.query(System).filter(System.workspace_id == workspace.id, System.name == "Live Visual Monitor").first()
    ensure_visual_intelligence_seed(db, workspace, system_id=visual_system.id if visual_system else None)

    db.commit()
    return {
        "workspace_slug": workspace.slug,
        "workspace_created": created,
        "members_added": members_added,
        "systems_created": systems_created,
    }
