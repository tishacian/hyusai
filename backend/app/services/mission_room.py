"""SENTINEL-CI demo mission-room fixtures and bootstrap helpers.

The mission room is intentionally implemented as an Agentium workspace pattern,
not as a tenant-special case. Runtime surfaces read the current workspace, while
this module provides a portable demo seed and deterministic advisory payloads.
"""
from __future__ import annotations

import copy
from datetime import datetime, time, timedelta
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.models.capability import Capability
from app.models.intelligence import FeedSource, SafetyFilter, SemanticTarget
from app.models.knowledge_collection import KnowledgeCollection
from app.models.knowledge_guide import KnowledgeGuide
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
from app.services.intelligence.satellite_imagery import resolve_satellite_scenes
from app.services.demo_time_context import demo_time_context_defaults, resolve_demo_date
from app.services.workspace_maps import (
    IVORY_COAST_BOUNDS,
    ensure_workspace_map_seed,
    mission_room_map_payload,
)


SENTINEL_WORKSPACE_SLUG = "sentinel-ci"
SENTINEL_WORKSPACE_NAME = "SENTINEL-CI"
SENTINEL_ASSISTANT_NAME = "AYA"
SENTINEL_EVIDENCE_GRAPH_COLLECTION = "sentinel-ci-evidence-graph"
SENTINEL_MARITIME_INTELLIGENCE_COLLECTION = "sentinel-ci-maritime-intelligence"
MISSION_ROOM_ROOT = "/hypervisor/mission-room"
MISSION_ROOM_ROUTE = f"{MISSION_ROOM_ROOT}/cockpit"
VP_SCENARIO_ID = "sentinel-ci-vp-morning-zone-nord-v1"
OCTOCITY_WORKSPACE_SLUG = "octocity-mission-room"
OCTOCITY_WORKSPACE_NAME = "Octocity Mission Room"
OCTOCITY_ASSISTANT_NAME = "OCTAVE"
OCTOCITY_MISSION_ROOM_PROFILE = "octocity_institutional_v1"
OCTOCITY_OWNER_EMAILS = ("thibaud.ishacian@datategy.net",)


_OCTOCITY_TEXT_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("sentinel_ci_aya_security_v1", "octave_security_v1"),
    ("sentinel_ci_aya_v1", "octave_mission_room_v1"),
    ("sentinel_ci", "octocity"),
    ("sentinel-ci", "octocity"),
    ("SENTINEL-CI", OCTOCITY_WORKSPACE_NAME),
    ("Sentinel-CI", OCTOCITY_WORKSPACE_NAME),
    ("AYA", OCTOCITY_ASSISTANT_NAME),
    ("aya.", "octave."),
    ("aya_", "octave_"),
    ("aya", "octave"),
    ("Aya", OCTOCITY_ASSISTANT_NAME),
    ("Monsieur le Vice Premier Ministre", "Madame la Directrice de Coordination"),
    ("Vice Premier Ministre", "Directrice de Coordination"),
    ("Vice-Premier Ministre", "Directrice de Coordination"),
    ("Vice Premier minister", "Coordination Director"),
    ("VPM", "Coordination"),
    ("Republique de Côte d’Ivoire", "Octocity Civic Grid"),
    ("République de Côte d’Ivoire", "Octocity Civic Grid"),
    ("Republique de Cote d'Ivoire", "Octocity Civic Grid"),
    ("République de Côte d'Ivoire", "Octocity Civic Grid"),
    ("Côte d’Ivoire", "Asteria"),
    ("Côte d'Ivoire", "Asteria"),
    ("Cote d'Ivoire", "Asteria"),
    ("Ivory Coast", "Asteria"),
    ("Ambassadeur France", "Emissaire Helion"),
    ("ambassadeur France", "emissaire Helion"),
    ("Ambassadeur de France", "Emissaire d'Helion"),
    ("ambassadeur de France", "emissaire d'Helion"),
    ("ivoirienne", "asterienne"),
    ("ivoirien", "asterien"),
    ("CI", "AS"),
    ("BCEAO", "Civic Reserve"),
    ("UEMOA", "Civic Union"),
    ("XOF", "OCU"),
    ("CFA", "OCU"),
    ("Franc CFA", "Octocity Unit"),
    ("franc CFA", "Octocity unit"),
    ("Abidjan", "Meridian"),
    ("Yamoussoukro", "Civitas"),
    ("Bouaké", "Borealis"),
    ("Bouake", "Borealis"),
    ("Korhogo", "Northgate"),
    ("Bouna", "Eastwatch"),
    ("Kong", "Ridgepoint"),
    ("San Pedro", "Harbor West"),
    ("Vridi", "Quai Meridian"),
    ("Nawa", "Liora"),
    ("Soubre", "Solenne"),
    ("Napié", "Auralis"),
    ("Napie", "Auralis"),
    ("CEDEAO", "Alliance Aurora"),
    ("cedeao", "alliance aurora"),
    ("FANCI", "Garde Civique d'Asteria"),
    ("Prefet", "Coordinateur territorial"),
    ("Préfet", "Coordinateur territorial"),
    ("Préfecture", "Coordination territoriale"),
    ("prefet", "coordinateur territorial"),
    ("préfet", "coordinateur territorial"),
    ("préfecture", "coordination territoriale"),
    ("cacao", "bio-composites"),
    ("Cacao", "Bio-composites"),
    ("cocoa", "bio-composites"),
    ("Cocoa", "Bio-composites"),
    ("anacarde", "fibre solaire"),
    ("Anacarde", "Fibre solaire"),
    ("Afrique de l'Ouest", "Arc Atlantique"),
    ("West Africa", "Atlantic Arc"),
    ("Sahel", "Northern Belt"),
    ("Golfe de Guinee", "Gulf of Meridian"),
    ("Gulf of Guinea", "Gulf of Meridian"),
    ("Africa/Abidjan", "UTC"),
)

_OCTOCITY_FORBIDDEN_TERMS = (
    "AYA",
    "SENTINEL-CI",
    "Côte d’Ivoire",
    "Côte d'Ivoire",
    "Cote d'Ivoire",
    "Abidjan",
    "Nawa",
    "CEDEAO",
    "FANCI",
    "cacao",
    "anacarde",
)


def mission_room_profile(workspace: Workspace | None) -> str:
    settings = workspace.settings if workspace is not None else None
    mission_room = (settings or {}).get("mission_room") if isinstance(settings, dict) else None
    profile = (mission_room or {}).get("profile") if isinstance(mission_room, dict) else None
    return str(profile or "")


def is_octocity_mission_room(workspace: Workspace | None) -> bool:
    return (
        mission_room_profile(workspace) == OCTOCITY_MISSION_ROOM_PROFILE
        or (workspace is not None and (workspace.slug or "") == OCTOCITY_WORKSPACE_SLUG)
    )


def present_text_for_workspace(workspace: Workspace | None, value: str) -> str:
    """Apply workspace-specific presentation anonymization to visible strings."""
    if not is_octocity_mission_room(workspace):
        return value
    text = value
    for old, new in _OCTOCITY_TEXT_REPLACEMENTS:
        text = text.replace(old, new)
    return text


def present_payload_for_workspace(workspace: Workspace | None, payload: Any) -> Any:
    """Recursively anonymize Mission Room payload values for the Octocity profile."""
    if not is_octocity_mission_room(workspace):
        return payload
    if isinstance(payload, str):
        return present_text_for_workspace(workspace, payload)
    if isinstance(payload, dict):
        return {key: present_payload_for_workspace(workspace, value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [present_payload_for_workspace(workspace, item) for item in payload]
    if isinstance(payload, tuple):
        return tuple(present_payload_for_workspace(workspace, item) for item in payload)
    return payload


def octocity_forbidden_terms_present(payload: Any) -> list[str]:
    text = str(payload)
    return [term for term in _OCTOCITY_FORBIDDEN_TERMS if term in text]


def _ensure_workspace_members(
    db: DBSession,
    workspace: Workspace,
    emails: Iterable[str],
    *,
    role: str,
    role_template: str,
    custom_label: str,
) -> int:
    added = 0
    for email in emails:
        normalized_email = email.strip().lower()
        if not normalized_email:
            continue
        user = db.query(User).filter(func.lower(User.email) == normalized_email).first()
        if not user:
            continue
        existing = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == user.id,
            )
            .first()
        )
        if existing:
            continue
        db.add(
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=user.id,
                role=role,
                role_template=role_template,
                custom_labels=[custom_label],
            )
        )
        added += 1
    return added


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
    {"key": "cockpit", "label": "Cockpit", "glyph": "ledger", "variant": "government_mission_room", "object": "Workbench"},
    {"key": "strategie", "label": "Carte", "glyph": "sliders", "variant": "territorial_action_map", "object": "Workbench"},
    {"key": "securite", "label": "Securite", "glyph": "shield", "variant": "intelligence", "object": "Workbench"},
    {"key": "reputation", "label": "Reputation", "glyph": "pulse", "variant": "intelligence", "object": "Run"},
    {"key": "agenda", "label": "Agenda", "glyph": "ledger", "variant": "government_mission_room", "object": "Workbench"},
    {"key": "presse", "label": "Presse", "glyph": "pulse", "variant": "intelligence", "object": "Run"},
    {"key": "decisions", "label": "Arbitrages", "glyph": "check", "variant": "executive_instruction_drafting", "object": "Review Queue"},
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
        "sources": ["src-maritime-paa-001", "src-maritime-marinelink-001", "src-marinetraffic-context-001"],
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
            {"type": "rss", "id": "src-maritime-marinelink-001", "label": "MarineLink maritime news"},
            {"type": "source", "id": "src-marinetraffic-context-001", "label": "MarineTraffic AIS/API-ready"},
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
    ("AllAfrica West Africa", "https://allafrica.com/tools/headlines/rdf/westafrica/headlines.rdf", "cedeao"),
    ("Africanews", "https://www.africanews.com/feed/rss", "africa"),
    ("France 24 Afrique", "https://www.france24.com/fr/afrique/rss", "afrique"),
    ("RFI Afrique", "https://www.rfi.fr/fr/afrique/rss", "afrique"),
    ("BBC World News", "https://feeds.bbci.co.uk/news/world/rss.xml", "world"),
    ("Port Autonome d'Abidjan", "https://www.portabidjan.ci/rss.xml", "ci-maritime"),
    ("MarineLink Maritime News", "https://www.marinelink.com/news/rss", "maritime-world"),
]

GEOGRAPHIC_PRIORITY_ORDER = [
    ("ci", "Cote d'Ivoire", "Priorite absolue pour le Vice Premier Ministre et le pilotage interieur."),
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
        "source_refs": ["src-maritime-paa-001", "src-maritime-marinelink-001", "src-marinetraffic-context-001"],
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
    {"zone": "Nord", "level": "CRITIQUE", "bars": 4, "summary": "Incident frontiere · 06h14", "tone": "critical"},
    {"zone": "Ouest", "level": "SURVEILLANCE", "bars": 3, "summary": "Mouvements inhabituels", "tone": "watch"},
    {"zone": "Centre", "level": "STABLE", "bars": 2, "summary": "Institutions nominales", "tone": "stable"},
    {"zone": "Sud", "level": "OPERATIONNEL", "bars": 1, "summary": "Abidjan nominal", "tone": "stable"},
    {"zone": "Est", "level": "SURVEILLANCE", "bars": 3, "summary": "Frontiere Ghana", "tone": "watch"},
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


def _security_live_osint_enabled(workspace: Workspace) -> bool:
    """Guard rail: demo Vice Premier Ministre always baseline; live OSINT requires explicit feature flag."""
    if str(workspace.mode or "").lower() == "demo":
        return False
    flags = (workspace.settings or {}).get("feature_flag") or {}
    return bool(flags.get("security_live_osint", False))


def _resolve_security_posture(workspace: Workspace) -> dict[str, Any]:
    from app.services.intelligence.cedeao_index import cedeao_index_payload
    from app.services.intelligence.rss_security import rss_security_payload

    posture = _clone(SECURITY_POSTURE)
    allow_live = _security_live_osint_enabled(workspace)
    rss = rss_security_payload(allow_live=allow_live)
    cedeao = cedeao_index_payload(allow_live=allow_live)

    if cedeao:
        components = cedeao.get("components") or {}
        interior = posture.get("interior") or {}
        exterior = posture.get("exterior") or {}
        if components.get("unrest") is not None:
            interior["score"] = int(round(float(components["unrest"])))
        if components.get("information") is not None:
            interior["trend"] = cedeao.get("trend") or interior.get("trend") or "stable"
        if cedeao.get("score") is not None:
            exterior["score"] = int(round(float(cedeao["score"])))
            exterior["trend"] = cedeao.get("trend") or exterior.get("trend") or "stable"
        posture["interior"] = interior
        posture["exterior"] = exterior

    if rss and rss.get("signals"):
        exterior = posture.get("exterior") or {}
        existing = list(exterior.get("signals") or [])
        live_signals = []
        for signal in rss["signals"][:3]:
            live_signals.append(
                {
                    "id": signal.get("id") or f"sig-rss-{len(live_signals)}",
                    "label": signal.get("label") or "Signal RSS securite",
                    "tone": signal.get("tone") or "watch",
                    "summary": signal.get("summary") or signal.get("label"),
                    "sources": signal.get("sources") or ["src-rss-security-live"],
                    "url": signal.get("url"),
                    "feed_name": signal.get("feed_name"),
                }
            )
        exterior["signals"] = live_signals + existing[: max(0, 3 - len(live_signals))]
        posture["exterior"] = exterior

    posture["osint_sources"] = {
        "rss": {
            "live": bool(rss and rss.get("live")),
            "source_badge": (rss or {}).get("source_badge") or "CACHE BASELINE",
            "source": (rss or {}).get("source") or "fixtures Python",
            "fetched_at": (rss or {}).get("fetched_at"),
        },
        "cedeao_index": {
            "live": bool(cedeao.get("live")),
            "source_badge": cedeao.get("source_badge") or "CACHE BASELINE",
            "source": cedeao.get("source") or "fixtures Python",
            "fetched_at": cedeao.get("fetched_at"),
            "score": cedeao.get("score"),
            "delta_7d": cedeao.get("delta_7d"),
        },
    }
    return posture


def _resolve_troops_sahel(workspace: Workspace) -> dict[str, Any]:
    from app.services.intelligence.adsb_sahel import adsb_sahel_payload

    allow_live = _security_live_osint_enabled(workspace)
    snapshot = adsb_sahel_payload(allow_live=allow_live)
    return _clone(snapshot)


def _security_osint_source_badges(workspace: Workspace) -> dict[str, Any]:
    posture = _resolve_security_posture(workspace)
    troops = _resolve_troops_sahel(workspace)
    osint_sources = posture.get("osint_sources") or {}
    return {
        "rss_security": osint_sources.get("rss") or {"source_badge": "CACHE BASELINE", "live": False},
        "adsb_sahel": {
            "live": bool(troops.get("live")),
            "source_badge": troops.get("source_badge") or "CACHE BASELINE",
            "source": troops.get("source") or "fixtures Python",
            "fetched_at": troops.get("fetched_at") or troops.get("captured_at"),
        },
        "cedeao_index": osint_sources.get("cedeao_index")
        or {"source_badge": "CACHE BASELINE", "live": False},
    }


def cedeao_index_payload_for_workspace(workspace: Workspace) -> dict[str, Any]:
    from app.services.intelligence.cedeao_index import cedeao_index_payload

    allow_live = _security_live_osint_enabled(workspace)
    payload = cedeao_index_payload(allow_live=allow_live)
    payload["policy"] = "advisory_only"
    payload["demo_mode"] = not allow_live
    return payload


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


def _news_geo_tier(signal: dict[str, Any]) -> str:
    tier = str(signal.get("geo_tier") or signal.get("geography_tier") or _feed_scope(signal.get("source_category")) or "world").lower()
    return tier if tier in {"ci", "cedeao", "africa", "world"} else "world"


def _is_maritime_signal(signal: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(value or "")
        for value in [
            signal.get("id"),
            signal.get("title"),
            signal.get("summary"),
            signal.get("source"),
            signal.get("source_category"),
            signal.get("domain"),
            " ".join(signal.get("tags") or []),
        ]
    ).lower()
    return any(
        token in haystack
        for token in (
            "maritime",
            "marine",
            "port",
            "douane",
            "douanes",
            "customs",
            "ais",
            "navire",
            "vessel",
            "congestion",
            "logistique",
            "golfe de guinee",
            "golfe de guinée",
        )
    )


def _news_velocity(signal: dict[str, Any], index: int = 0) -> str:
    explicit = signal.get("velocity")
    if explicit:
        return str(explicit)
    risk = str(signal.get("risk_level") or "").lower()
    source_count = int(signal.get("source_count") or len(signal.get("sources") or []) or 0)
    if str(signal.get("id") or "").startswith("social-") or source_count >= 3:
        return "rapide"
    if risk in {"critical", "high"}:
        return "elevee"
    if index <= 1 or risk == "medium":
        return "moderee"
    return "veille"


def _normalize_news_signal(signal: dict[str, Any], index: int = 0) -> dict[str, Any]:
    row = _clone(signal)
    tier = _news_geo_tier(row)
    source_count = int(row.get("source_count") or len(row.get("sources") or []) or 1)
    row["geo_tier"] = tier
    row["geography_tier"] = tier
    row["velocity"] = _news_velocity(row, index)
    row["source_count"] = source_count
    row["rumor_origin"] = row.get("rumor_origin") or row.get("origin")
    row["briefing_value"] = row.get("briefing_value") or (
        "Impact politique interieur a traiter en priorite, puis verifier la perception internationale."
        if tier == "ci"
        else "Contrepoint utile pour diplomatie, CEDEAO ou partenaires internationaux."
    )
    badges = []
    if source_count >= 2:
        badges.append("multi-source")
    if str(row.get("id") or "").startswith("social-") or "rumeur" in str(row.get("title") or "").lower():
        badges.append("rumeur")
    if row.get("url") or tier == "ci":
        badges.append("source primaire")
    if row["velocity"] in {"rapide", "elevee"}:
        badges.append(f"vitesse {row['velocity']}")
    row["badges"] = badges
    row["impact_international"] = row.get("impact_international") or (
        "Perception a surveiller chez partenaires et presse internationale."
        if tier in {"world", "africa", "cedeao"}
        else "Impact international faible sauf amplification regionale ou partenaire."
    )
    if _is_maritime_signal(row):
        row["domain"] = row.get("domain") or "port_flow"
        row["source_type"] = row.get("source_type") or "rss"
        row["tags"] = row.get("tags") or ["port", "douanes", "securite maritime", "flux logistiques"]
        if "maritime" not in row["badges"]:
            row["badges"].insert(0, "maritime")
        row["briefing_value"] = row.get("briefing_value") or "Signal maritime utile pour relier port, douanes, securite et agenda economique."
    row["recommended_action"] = row.get("recommended_action") or _action_for_risk(row.get("risk_level"))
    return row


def _maritime_geo_tier(signal: dict[str, Any]) -> str:
    zone = f"{signal.get('zone') or ''} {signal.get('source') or ''} {signal.get('summary') or ''}".lower()
    if "abidjan" in zone or "san-pedro" in zone or "san pedro" in zone or "cote d'ivoire" in zone or "côte d'ivoire" in zone:
        return "ci"
    if "golfe" in zone or "guinee" in zone or "guinée" in zone or "ghana" in zone or "liberia" in zone:
        return "gulf_of_guinea"
    if "africa" in zone or "afrique" in zone:
        return "africa"
    return "world"


def _maritime_intelligence_payload(feed_rows: list[dict[str, Any]], signals: list[dict[str, Any]]) -> dict[str, Any]:
    maritime_signals = [_normalize_news_signal(signal) for signal in signals if _is_maritime_signal(signal)]
    feeds = [
        row for row in feed_rows
        if row.get("active") and "maritime" in str(row.get("category") or "").lower()
    ]
    if not feeds:
        feeds = [
            {"name": name, "url": url, "category": category, "active": True}
            for name, url, category in SENTINEL_NEWS_FEEDS
            if "maritime" in category
        ]
    latest_signal = maritime_signals[0] if maritime_signals else {}
    latest_event = _clone(MARITIME_EVENTS[0])
    latest_observation = {
        "id": latest_event["id"],
        "title": latest_signal.get("title") or latest_event["title"],
        "summary": latest_signal.get("summary") or latest_event["summary"],
        "geo_tier": _maritime_geo_tier(latest_signal or latest_event),
        "domain": latest_signal.get("domain") or latest_event["domain"],
        "source_type": latest_signal.get("source_type") or latest_event["source_type"],
        "score": int(latest_signal.get("score") or latest_event["score"]),
        "severity": latest_signal.get("severity") or latest_event["severity"],
        "recommended_action": latest_signal.get("recommended_action") or latest_event["recommended_action"],
        "decision_deadline": latest_signal.get("decision_deadline") or latest_event["decision_deadline"],
        "briefing_value": latest_signal.get("briefing_value") or "Croiser flux portuaire, douanes, securite maritime et agenda economique.",
        "confidence": latest_signal.get("confidence") or 0.66,
        "evidence_refs": latest_signal.get("evidence_refs") or [
            {"type": "rss", "id": "src-maritime-paa-001", "label": "RSS Port Autonome d'Abidjan"},
            {"type": "rss", "id": "src-maritime-marinelink-001", "label": "MarineLink Maritime News"},
            {"type": "source", "id": "src-marinetraffic-context-001", "label": "MarineTraffic AIS/API-ready"},
        ],
    }
    map_focus = {
        "basemap": "administrative",
        "active_layers": ["territorial-risk", "open-intelligence", "visual-streams", "maritime-traffic"],
        "camera": {"longitude": latest_event["longitude"], "latitude": latest_event["latitude"], "zoom": 9.15, "duration_ms": 220},
        "focus_marker": {
            "longitude": latest_event["longitude"],
            "latitude": latest_event["latitude"],
            "label": "Port d'Abidjan · surveillance maritime",
            "zone_id": "zone-sud",
            "tone": "maritime",
        },
    }
    active_evidence = {
        "id": "active-maritime-customs-watch",
        "type": "maritime",
        "title": "Maritime / douanes · Port d'Abidjan",
        "location": "Port autonome d'Abidjan / Golfe de Guinee",
        "score": latest_observation["score"],
        "severity": latest_observation["severity"],
        "source_quality": "RSS Port d'Abidjan + MarineLink + MarineTraffic API-ready",
        "observation": latest_observation["summary"],
        "recommended_action": latest_observation["recommended_action"],
        "decision_deadline": latest_observation["decision_deadline"],
        "evidence_refs": latest_observation["evidence_refs"],
        "aya_context": {
            "prompt": "AYA, relie l'actualite douanes au trafic maritime autour du port d'Abidjan.",
            "answer_frame": "Situation portuaire, preuve maritime, impact douanes/securite, option recommandee, deadline, confiance.",
            "decision_deadline": latest_observation["decision_deadline"],
            "confidence": latest_observation["confidence"],
        },
        "map_focus": map_focus,
    }
    return {
        "status": "ready",
        "provider": "MarineTraffic API-ready + RSS maritime qualifie",
        "source_url": "https://www.marinetraffic.com/en/ais/home/centerx:-3.9/centery:5.8/zoom:8",
        "source_policy": "Pas de scraping MarineTraffic ; RSS publics et API officielle si cle disponible.",
        "focus_area": "Port d'Abidjan, San-Pedro, Golfe de Guinee",
        "source_quality": {
            "label": "RSS publics + source AIS contextuelle",
            "limitations": "MarineTraffic News n'expose pas de RSS public confirme ; l'AIS live requiert API ou integration licenciee.",
        },
        "ports": _clone(MARITIME_PORTS),
        "vessel_events": _clone(MARITIME_EVENTS),
        "customs_links": [
            {
                "id": "customs-abidjan-verification",
                "label": "Douanes / verification portuaire",
                "domain": "customs",
                "summary": "Verifier si inspection, congestion ou retard a une origine douane, securite ou logistique.",
                "recommended_action": "Demander confirmation Port + Douanes avant communication publique.",
            }
        ],
        "signals": maritime_signals[:4],
        "feeds": [
            {"name": row.get("name"), "url": row.get("url"), "category": row.get("category"), "source_type": "rss"}
            for row in feeds
        ],
        "latest_observation": latest_observation,
        "active_evidence": active_evidence,
        "briefing_value": "Relie actualite portuaire, douanes, securite maritime, flux economiques et restitution AYA.",
        "aya_context": active_evidence["aya_context"],
        "prompts": [
            "AYA, quel est le risque autour du port d'Abidjan ?",
            "AYA, relie cette actualite douanes au trafic maritime.",
            "AYA, prepare une note pour Monsieur le Vice Premier Ministre avant le point economie.",
        ],
    }


def _news_geo_sections(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections = []
    for key, label, description in GEOGRAPHIC_PRIORITY_ORDER:
        scoped = [signal for signal in signals if _news_geo_tier(signal) == key]
        sections.append(
            {
                "key": key,
                "label": label,
                "description": description,
                "count": len(scoped),
                "signals": scoped[:30],
            }
        )
    return sections


def _octocity_news_payload(workspace: Workspace) -> dict[str, Any]:
    signals = [
        {
            "id": "octocity-news-transport-corridor",
            "title": "Northern Arc transport corridor: service variance detected",
            "risk_level": "high",
            "sentiment": "mixed",
            "summary": "Three civic feeds converge on a delayed mobility window and rising citizen-service pressure across the Northern Arc.",
            "source": "Northern Arc",
            "source_name": "Civic Signal Grid",
            "source_category": "ci-local",
            "sources": ["src-octocity-news-014", "src-octocity-map-001"],
            "zone": "Northern Arc",
            "geography_tier": "ci",
            "viewpoint": "territorial operations",
            "origin": "Synthetic open-intelligence feed",
            "briefing_value": "Connects map posture, citizen-service pressure and the next executive operating review.",
            "why_it_matters": "A high-visibility corridor can become a trust signal if the response is coordinated before the next public update.",
            "recommended_action": "Route to human review, attach evidence links and prepare a measured coordination note.",
            "confidence": 0.82,
            "source_count": 3,
            "badges": ["multi-source", "field-aligned", "human review"],
            "tags": ["mobility", "public service", "territorial operations"],
        },
        {
            "id": "octocity-news-energy-port",
            "title": "Atlantic Corridor energy and harbor signals remain contained",
            "risk_level": "medium",
            "sentiment": "neutral",
            "summary": "Harbor throughput, energy maintenance and field reports remain inside the monitored band after the morning reconciliation run.",
            "source": "Atlantic Corridor",
            "source_name": "Infrastructure Watch",
            "source_category": "ci-maritime",
            "sources": ["src-map-atlantic-003", "src-field-note-022"],
            "zone": "Atlantic Corridor",
            "geography_tier": "ci",
            "viewpoint": "infrastructure continuity",
            "origin": "Synthetic infrastructure feed",
            "briefing_value": "Shows how operational signals stay governed without triggering unnecessary escalation.",
            "why_it_matters": "The executive can keep the item in monitoring while preserving auditability.",
            "recommended_action": "Keep the current control level and capture the field note as reusable institutional memory.",
            "confidence": 0.76,
            "source_count": 2,
            "badges": ["monitored", "evidence linked"],
            "tags": ["energy", "harbor", "continuity"],
        },
        {
            "id": "octocity-news-central-review",
            "title": "Central Hub decision queue requires one governed arbitration",
            "risk_level": "high",
            "sentiment": "mixed",
            "summary": "Budget timing, agency dependency and public-facing commitments now point to one review package for the executive team.",
            "source": "Central Hub",
            "source_name": "Decision Ops",
            "source_category": "ci-agency",
            "sources": ["src-decision-queue-007", "src-budget-brief-005"],
            "zone": "Central Hub",
            "geography_tier": "ci",
            "viewpoint": "executive arbitration",
            "origin": "Synthetic decision feed",
            "briefing_value": "Turns weak signals into a concrete decision package with traceable evidence.",
            "why_it_matters": "This is the proof point for System -> Run -> Evaluation -> Decision.",
            "recommended_action": "Ask OCTAVE for a 60-second briefing, then promote the decision package to review.",
            "confidence": 0.84,
            "source_count": 4,
            "badges": ["decision-ready", "audit trail"],
            "tags": ["budget", "human review", "decision"],
        },
        {
            "id": "octocity-news-cross-border",
            "title": "Regional coordination brief updated for Rhine Interface",
            "risk_level": "medium",
            "sentiment": "neutral",
            "summary": "The regional coordination layer adds context for cross-border service continuity without changing the operating posture.",
            "source": "Rhine Interface",
            "source_name": "Regional Desk",
            "source_category": "cedeao",
            "sources": ["src-regional-aurora-002"],
            "zone": "Rhine Interface",
            "geography_tier": "cedeao",
            "viewpoint": "regional coordination",
            "origin": "Synthetic regional feed",
            "briefing_value": "Provides the external context leaders need without mixing it with the local decision queue.",
            "why_it_matters": "Agentium separates signal tiers while keeping the run lineage intact.",
            "recommended_action": "Keep as context for the next operating review; no public action required.",
            "confidence": 0.7,
            "source_count": 2,
            "badges": ["context", "lineage"],
            "tags": ["regional coordination", "continuity"],
        },
    ]
    normalized = [_normalize_news_signal(signal, index) for index, signal in enumerate(signals)]
    geo_sections = [
        {
            "key": "ci",
            "label": "France operations",
            "description": "Domestic operational signals anchored to the synthetic territorial map.",
            "count": 3,
            "signals": [signal for signal in normalized if _news_geo_tier(signal) == "ci"],
        },
        {
            "key": "cedeao",
            "label": "European coordination",
            "description": "Cross-border context used for executive coordination, not automatic escalation.",
            "count": 1,
            "signals": [signal for signal in normalized if _news_geo_tier(signal) == "cedeao"],
        },
        {
            "key": "africa",
            "label": "Strategic context",
            "description": "Broader institutional context kept separate from operational decisions.",
            "count": 0,
            "signals": [],
        },
        {
            "key": "world",
            "label": "International",
            "description": "Partner and market context for executive awareness.",
            "count": 0,
            "signals": [],
        },
    ]
    return _attach_vp_story(
        {
            "workspace": _workspace_meta(workspace),
            "signals": normalized[:3],
            "executive_alerts": normalized[:3],
            "all_signals": normalized,
            "summary": (
                "OCTAVE reconciles open-intelligence, map posture and decision evidence into a governed "
                "executive signal flow for a synthetic France-based operating room."
            ),
            "briefing_note": {
                "headline": "Open intelligence signal flow",
                "bullets": [
                    "Three domestic signals are linked to map zones, evidence sources and human-review thresholds.",
                    "One regional context signal is preserved for coordination without changing the operating posture.",
                    "The next action is decision-ready: briefing, evidence pack, review owner and audit trail.",
                ],
                "talking_points": [
                    "Respond from verified evidence, not from isolated headlines.",
                    "Keep operational decisions traceable through System, Run, Evaluation and Decision.",
                    "Use OCTAVE to summarize posture, confidence, risk and the next governed action in English.",
                ],
                "decisions_expected": [
                    "Promote the Central Hub package to executive review.",
                    "Keep the Atlantic Corridor in monitored status.",
                    "Capture the field note into Knowledge Capture after review.",
                ],
            },
            "source_health": {
                "active_feeds": 7,
                "total_articles": 128,
                "analyzed": 128,
                "high_risk": 2,
                "last_run_id": "octocity-news-sim-20260701",
                "last_run_status": "simulated",
                "coverage_label": "7 sources · synthetic France operating room",
                "live_news_used": False,
                "geography_order": ["ci", "cedeao", "africa", "world"],
            },
            "media_sources": [
                {"label": "Domestic civic feeds", "coverage": 92, "count": 4},
                {"label": "Infrastructure watch", "coverage": 78, "count": 2},
                {"label": "Regional context", "coverage": 64, "count": 1},
                {"label": "Decision evidence", "coverage": 86, "count": 6},
            ],
            "geographic_priority": geo_sections,
            "geo_sections": geo_sections,
            "viewpoints": [
                {"label": "Operations", "summary": "Map-linked signals with evidence and review thresholds.", "count": 3},
                {"label": "Governance", "summary": "Decision-ready packages remain auditable before action.", "count": 2},
                {"label": "Coordination", "summary": "Regional context is preserved without forcing escalation.", "count": 1},
            ],
            "social_listening": {
                "status": "synthetic",
                "top_themes": ["service continuity", "mobility", "executive review"],
                "summary": "Citizen-facing signals are treated as advisory evidence until reviewed.",
            },
            "maritime_intelligence": {},
            "analysis_link": {
                "system_id": None,
                "run_id": "octocity-news-sim-20260701",
                "label": "Open intelligence simulator",
            },
            "sources": [
                {"id": "src-octocity-news-014", "label": "Civic Signal Grid", "kind": "synthetic_feed", "confidence": 0.82, "age": "simulated"},
                {"id": "src-octocity-map-001", "label": "Synthetic territorial map", "kind": "map_layer", "confidence": 0.8, "age": "current"},
                {"id": "src-decision-queue-007", "label": "Decision queue", "kind": "governance_trace", "confidence": 0.84, "age": "current"},
            ],
        }
    )


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
    if is_octocity_mission_room(workspace):
        return _octocity_news_payload(workspace)

    feed_rows = _feed_rows(db, workspace)
    fallback_signals = [_normalize_news_signal(signal, index) for index, signal in enumerate(_clone(NEWS_SIGNALS))]
    fallback_maritime = _maritime_intelligence_payload(feed_rows, fallback_signals)
    fallback = {
        "workspace": _workspace_meta(workspace),
        "signals": fallback_signals,
        "executive_alerts": fallback_signals,
        "all_signals": fallback_signals,
        "summary": "Lecture double : politique interieure ivoirienne prioritaire, avec contrepoint CEDEAO/Afrique/monde pour anticiper perception et diplomatie.",
        "briefing_note": {
            "headline": "Veille ouverte qualifiee CI + international",
            "bullets": [
                "Cote d'Ivoire : rumeurs, emotion publique et projets sensibles demandent une lecture cabinet rapide.",
                "CEDEAO / Golfe de Guinee : surveiller les effets transfrontaliers et narratifs regionaux.",
                "International : garder le contrepoint partenaires Europe/USA/Asie pour anticiper pression et opportunites.",
                "Maritime / douanes : surveiller Port d'Abidjan, San-Pedro et Golfe de Guinee quand un signal logistique touche l'agenda economique.",
            ],
            "talking_points": [
                "Coordination preventive avec les autorites locales.",
                "Continuité des services publics et suivi transparent des projets.",
                "AYA peut expliquer l'origine d'une rumeur, la zone touchee et l'action recommandee.",
                "Sur le maritime, ne communiquer qu'apres confirmation Port + Douanes.",
            ],
            "decisions_expected": [
                "Valider les elements de langage presse.",
                "Mandater une note cabinet sur les zones nord.",
                "Qualifier le signal social prioritaire avant toute action publique.",
                "Verifier le signal maritime/douanes avant le point economie.",
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
        "geographic_priority": _geographic_priority_payload(feed_rows, fallback_signals),
        "geo_sections": _news_geo_sections(fallback_signals),
        "viewpoints": _news_viewpoints_payload(feed_rows, fallback_signals),
        "social_listening": _social_listening_payload(fallback_signals),
        "maritime_intelligence": fallback_maritime,
        "sources": source_index(),
    }
    if not db:
        return _attach_vp_story(fallback)

    try:
        from app.services.intelligence.batch import get_dashboard_data

        dashboard = get_dashboard_data(db, workspace_id=workspace.id)
    except Exception:
        return _attach_vp_story(fallback)

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
        return _attach_vp_story(fallback)

    dynamic_sources: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    for idx, article in enumerate(ranked[:30]):
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
                "published_at": article.get("published_at"),
                "tags": (article.get("entities") or [])[:6],
                "run_id": latest_run.id if latest_run else None,
                "entities": article.get("entities") or [],
            }
        )
    alerts = [_normalize_news_signal(alert, index) for index, alert in enumerate(alerts)]

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
        "all_signals": alerts,
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
        "geo_sections": _news_geo_sections([*alerts, *fallback_signals]),
        "viewpoints": _news_viewpoints_payload(feed_rows, [*alerts, *_clone(NEWS_SIGNALS)]),
        "social_listening": _social_listening_payload(fallback_signals),
        "maritime_intelligence": _maritime_intelligence_payload(feed_rows, [*alerts, *fallback_signals]),
        "analysis_link": {
            "system_id": latest_run.system_id if latest_run else None,
            "run_id": latest_run.id if latest_run else None,
            "label": "Atelier de veille",
        },
        "sources": [*source_index(), *dynamic_sources],
    }
    return _attach_vp_story(payload)


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
    settings = workspace.settings if isinstance(workspace.settings, dict) else {}
    mission_room_settings = settings.get("mission_room") if isinstance(settings.get("mission_room"), dict) else {}
    brand = (
        mission_room_settings.get("brand")
        if isinstance(mission_room_settings.get("brand"), dict)
        else settings.get("workspace_app_brand")
        if isinstance(settings.get("workspace_app_brand"), dict)
        else {}
    )
    app_label = str(settings.get("workspace_app_label") or brand.get("label") or "SENTINEL-CI")
    assistant_label = str(
        mission_room_settings.get("assistant_label")
        or mission_room_settings.get("label")
        or SENTINEL_ASSISTANT_NAME
    )
    api_by_view = {
        "cockpit": "/api/v1/mission-room/cockpit",
        "monitor": "/api/v1/mission-room/monitor",
        "securite": "/api/v1/mission-room/cockpit",
        "briefing": "/api/v1/mission-room/briefing",
        "pilotage": "/api/v1/mission-room/projects",
        "agenda": "/api/v1/mission-room/timeline",
        "messages": "/api/v1/mission-room/timeline",
        "bibliotheque": "/api/v1/mission-room/library",
        "projets": "/api/v1/mission-room/projects",
        "presse": "/api/v1/mission-room/news",
        "reputation": "/api/v1/mission-room/news",
        "veille-sociale": "/api/v1/mission-room/cockpit",
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
            "label": app_label,
            "assistant_label": assistant_label,
            "shell": settings.get("workspace_app_shell") or "immersive",
            "default_route": settings.get("default_route") or MISSION_ROOM_ROUTE,
            "default_view": settings.get("workspace_app_default_view") or "cockpit",
            "brand": brand,
            "profile": mission_room_profile(workspace),
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
        "title": "Bonjour, Monsieur le Vice Premier Ministre.",
        "date_label": demo_time_context_defaults(workspace)["label"],
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
            "score": REPUTATION_DRILL["score"],
            "delta": REPUTATION_DRILL["delta"],
            "trend": [58, 60, 62, 64, 66, 69, REPUTATION_DRILL["score"]],
            "summary": REPUTATION_DRILL["summary"],
            "period_label": REPUTATION_DRILL["period_label"],
            "items": _clone(REPUTATION_DRILL["items"]),
            "aya_sentence": REPUTATION_DRILL["aya_sentence"],
        },
        "security_posture": _resolve_security_posture(workspace),
        "social_snapshot": _clone(SOCIAL_SNAPSHOT),
        "troops_sahel": _resolve_troops_sahel(workspace),
        "security_osint_badges": _security_osint_source_badges(workspace),
        "rumor_frontier_trace": _clone(RUMOR_FRONTIER_TRACE),
        "media_sources": [
            {"label": "Presse nationale", "coverage": 72, "count": 45},
            {"label": "Presse internationale", "coverage": 58, "count": 28},
            {"label": "Reseaux sociaux", "coverage": 41, "count": 156},
            {"label": "Agences de presse", "coverage": 65, "count": 18},
        ],
        "latest_alerts": _clone(NEWS_SIGNALS),
        "keywords": [
            {"label": "Vice Premier Ministre CI", "count": 340, "delta": 12},
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
    # Filter the calendar window on the workspace demo date so the cockpit
    # surfaces today through J+2 and not stale events from past demos.
    # ``list_calendar_events`` rolls SENTINEL-CI seed fixtures onto the
    # current Africa/Abidjan day before applying the window.
    today = resolve_demo_date(workspace)
    start = datetime.combine(today, time.min)
    end = datetime.combine(today + timedelta(days=2), time.max)
    events = list_calendar_events(db, workspace, start=start, end=end, status="scheduled")
    if not events:
        # Fall back to the full window if nothing matches the demo day
        # (eg. the workspace was seeded against another fixture set).
        events = list_calendar_events(db, workspace, status="scheduled")
    if not events:
        return _clone(AGENDA)
    return [
        {
            **serialize_calendar_event(event, workspace=workspace),
            "sources": ["src-agenda-jour-015"],
        }
        for event in events[:8]
    ]


# ``key`` remains the canonical frontend identifier. ``id`` mirrors it so
# smoke probes, analytics, and older consumers can address the same chips
# without branching on payload version.
def _vp_status_bar(overview: dict[str, Any], posture: dict[str, Any]) -> list[dict[str, Any]]:
    kpis = overview.get("kpis") or {}
    return [
        {
            "id": "zone-nord-tension",
            "key": "zone-nord-tension",
            "label": "Zone Nord",
            "value": "Tendue",
            "detail": "Centre Drones Napie en retard - cargo Aerostar bloque",
            "tone": "critical",
            "pulse": True,
            "tooltip": "Tension territoriale Nord — Centre Drones Napie en retard, cargo Aerostar Dynamics bloque (advisory)",
        },
        {
            "id": "posture",
            "key": "posture",
            "label": "Posture nationale",
            "value": str(posture.get("label") or "vigilance").upper(),
            "detail": f"{posture.get('score', 72)}/100",
            "tone": posture.get("label") or "elevated",
        },
        {"id": "deadline", "key": "deadline", "label": "Décision avant", "value": "15h00", "detail": "Revue Sahel · Conseil Défense", "tone": "critical"},
        {
            "id": "posture-securite",
            "key": "posture-securite",
            "label": "Posture sécurité",
            "value": "VIG/ELEV",
            "detail": "Intérieur vigilance · extérieur élevé Sahel",
            "tone": "elevated",
            "tooltip": "Posture dual-axis — frontière Nord vigilance (rumeur démentie 13h46), théâtre Sahel surveillance ADS-B advisory.",
        },
        {"id": "arbitrages", "key": "arbitrages", "label": "Arbitrages ouverts", "value": "3", "detail": "validation humaine", "tone": "watch"},
        {"id": "presse", "key": "presse", "label": "Alertes presse", "value": str(kpis.get("press_alerts", 16)), "detail": "qualifiées par AYA", "tone": "critical"},
        {"id": "agenda", "key": "agenda", "label": "Rendez-vous", "value": str(kpis.get("meetings", 4)), "detail": "aujourd'hui", "tone": "stable"},
        {"id": "flux", "key": "flux", "label": "Flux temps reel", "value": "8", "detail": "presse · carte · agenda · visuel", "tone": "stable"},
    ]


def _sovereign_indicators(overview: dict[str, Any], posture: dict[str, Any]) -> list[dict[str, Any]]:
    kpis = overview.get("kpis") or {}
    reputation = overview.get("reputation") or {}
    return [
        {
            "label": "Menace nationale",
            "value": posture.get("score", 72),
            "unit": "/100",
            "source": "5 sources",
            "confidence": "94%",
            "trend": "+12",
            "tone": "critical" if posture.get("score", 0) >= 80 else "watch",
        },
        {
            "label": "Reputation de l'Etat",
            "value": reputation.get("score", kpis.get("reputation_score", 63)),
            "unit": "/100",
            "source": "OSINT",
            "confidence": "78%",
            "trend": f"{reputation.get('delta', -4):+}",
            "tone": "watch",
        },
        {
            "label": "Stabilite institutionnelle",
            "value": 78,
            "unit": "/100",
            "source": "4 sources",
            "confidence": "91%",
            "trend": "stable",
            "tone": "stable",
        },
        {
            "label": "Securite maritime Golfe",
            "value": 71,
            "unit": "/100",
            "source": "AIS-ready",
            "confidence": "86%",
            "trend": "-7",
            "tone": "watch",
        },
    ]


def _fused_map_preview(mapped: dict[str, Any], news: dict[str, Any], visual: dict[str, Any]) -> dict[str, Any]:
    zones = mapped.get("zones") or _clone(MAP_ZONES)
    score_summary = mapped.get("score_summary") or {}
    top_zone = score_summary.get("top_zone") or (max(zones, key=lambda zone: zone.get("level", 0)) if zones else {})
    top_zone_id = top_zone.get("id") or "zone-nord"
    map_system = mapped.get("map_system") or {}
    default_state = map_system.get("default_map_state") or {}
    camera_presets = map_system.get("camera_presets") or {}
    renderer = map_system.get("renderer") or {}
    camera = (
        camera_presets.get(top_zone_id)
        or camera_presets.get("zone-nord")
        or default_state.get("camera")
        or {
            "longitude": -5.6294,
            "latitude": 9.4580,
            "zoom": 7.35,
            "pitch": 0,
            "bearing": 0,
        }
    )
    bounds = renderer.get("bounds") or [
        [IVORY_COAST_BOUNDS["west"], IVORY_COAST_BOUNDS["south"]],
        [IVORY_COAST_BOUNDS["east"], IVORY_COAST_BOUNDS["north"]],
    ]
    zone_scores = [
        {
            "id": zone.get("id"),
            "name": zone.get("name"),
            "score": zone.get("level"),
            "trend": "+12/24h" if zone.get("id") == "zone-nord" else "stable",
            "tone": zone.get("tone"),
        }
        for zone in zones[:5]
    ]
    return {
        "route": f"{MISSION_ROOM_ROOT}/strategie",
        "label": "Carte fusionnee",
        "question": "Quelles zones necessitent une action preventive non militaire ce mois-ci ?",
        "top_zone": top_zone,
        "zones": zones[:5],
        "layers": [
            {"key": "threat", "label": "Menace", "count": len(zones), "tone": "critical", "visible": True},
            {"key": "press", "label": "Presse", "count": len(news.get("executive_alerts") or news.get("signals") or []), "tone": "watch", "visible": True},
            {"key": "projects", "label": "Projets", "count": len(PROJECTS), "tone": "stable", "visible": True},
            {"key": "visual", "label": "Visuel", "count": (visual.get("source_health") or {}).get("captures", 0), "tone": "stable", "visible": True},
        ],
        "heatmap": [
            {"label": zone.get("name"), "score": zone.get("level"), "tone": zone.get("tone")}
            for zone in zones[:5]
        ],
        "source_label": "Carte, presse, projets, agenda et observations visuelles",
        "geo_preview": {
            "camera": {
                **camera,
                "center": [camera.get("longitude"), camera.get("latitude")],
                "bounds": bounds,
            },
            "active_layers": ["threat", "press"],
            "zone_scores": zone_scores,
            "top_zone_id": top_zone_id,
        },
    }


def _agenda_day(overview: dict[str, Any], calendar_summary: Optional[dict[str, Any]]) -> dict[str, Any]:
    events = overview.get("agenda") or []
    next_event = (calendar_summary or {}).get("next_event") if calendar_summary else None
    return {
        "label": "Agenda ministeriel",
        "next_event": next_event or (events[0] if events else None),
        "events": events[:4],
        "available_window": {
            "label": "Fenetre utile",
            "time": "10:00-10:45",
            "reason": "Dernier creneau avant expression publique et amplification potentielle.",
        },
        "separate_from_actions": True,
    }


def _directive_of_day_payload() -> dict[str, Any]:
    return {
        **_clone(DECISION_SENTENCE),
        "window": "avant Conseil des ministres · 15h00",
        "primary_cta": "Ouvrir le dossier Zone Nord",
        "voice_cta": "Ecouter le briefing AYA",
    }


def _decision_queue_payload() -> list[dict[str, Any]]:
    return [
        {
            **_clone(package),
            "email_draft_ready": package["id"] in {"package-rumeur-emoi", "package-zone-nord"},
            "validation_required": True,
        }
        for package in EXECUTIVE_DECISION_PACKAGES
    ]


_ARBITRATION_DOMAIN_LABELS = {
    "PRESSE": "Presse",
    "DEFENSE": "Defense / territoire",
    "DIPLOMATIE": "Diplomatie",
    "COMMUNICATION": "Communication publique",
    "RUMEUR": "Rumeur / OSINT",
}

_ARBITRATION_STATUS_LABELS = {
    "draft_ready": "REPONSE A VALIDER",
    "decision_required": "DECISION REQUISE",
    "brief_ready": "FICHE PRETE",
}

_ATTENTION_PACKAGE_LINKS = {
    "attention-zone-nord": "package-zone-nord",
    "attention-ambassadeur-france": "package-france-brief",
}

_ATTENTION_DOMAINS = {
    "attention-inter-budget": "PRESSE",
    "attention-zone-nord": "DEFENSE",
    "attention-ambassadeur-france": "DIPLOMATIE",
}

_PACKAGE_DOMAINS = {
    "package-zone-nord": "DEFENSE",
    "package-rumeur-emoi": "COMMUNICATION",
    "package-france-brief": "DIPLOMATIE",
}

_ATTENTION_DRILL_DOWN = {
    "attention-inter-budget": {
        "view": "presse",
        "route": f"{MISSION_ROOM_ROOT}/presse",
        "anchor": "attention-inter-budget",
    },
    "attention-zone-nord": {
        "view": "briefing",
        "route": f"{MISSION_ROOM_ROOT}/briefing",
        "anchor": "package-zone-nord",
    },
    "attention-ambassadeur-france": {
        "view": "decisions",
        "route": f"{MISSION_ROOM_ROOT}/decisions",
        "anchor": "package-france-brief",
    },
}

_PACKAGE_DRILL_DOWN = {
    "package-zone-nord": {
        "view": "briefing",
        "route": f"{MISSION_ROOM_ROOT}/briefing",
        "anchor": "package-zone-nord",
    },
    "package-rumeur-emoi": {
        "view": "presse",
        "route": f"{MISSION_ROOM_ROOT}/presse",
        "anchor": "package-rumeur-emoi",
    },
    "package-france-brief": {
        "view": "decisions",
        "route": f"{MISSION_ROOM_ROOT}/decisions",
        "anchor": "package-france-brief",
    },
}


def _arbitration_status_label(status: str) -> str:
    return _ARBITRATION_STATUS_LABELS.get(status, status.replace("_", " ").upper())


def _arbitration_card(
    *,
    card_id: str,
    rank: int,
    domain: str,
    title: str,
    summary: str,
    status: str,
    deadline: str,
    tone: str,
    cta_label: str,
    cta_route: str,
    drill_down: dict[str, Any],
    draft_ready: bool,
    aya_prepared: bool = True,
    secondary_drill_down: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    card = {
        "id": card_id,
        "rank": rank,
        "domain": domain,
        "domain_label": _ARBITRATION_DOMAIN_LABELS.get(domain, domain.title()),
        "title": title,
        "summary": summary,
        "status": status,
        "status_label": _arbitration_status_label(status),
        "deadline": deadline,
        "tone": tone,
        "cta_label": cta_label,
        "cta_route": cta_route,
        "drill_down": drill_down,
        "draft_ready": draft_ready,
        "aya_prepared": aya_prepared,
    }
    if secondary_drill_down:
        card["secondary_drill_down"] = secondary_drill_down
    return card


def _arbitration_cards_payload() -> list[dict[str, Any]]:
    packages_by_id = {package["id"]: package for package in EXECUTIVE_DECISION_PACKAGES}
    linked_packages = set(_ATTENTION_PACKAGE_LINKS.values())
    cards: list[dict[str, Any]] = []

    for attention in ATTENTION_REQUIRED:
        package = packages_by_id.get(_ATTENTION_PACKAGE_LINKS.get(attention["id"], ""))
        domain = _ATTENTION_DOMAINS.get(attention["id"], "DEFENSE")
        drill_down = _clone(_ATTENTION_DRILL_DOWN.get(attention["id"]) or {
            "view": "decisions",
            "route": attention.get("action_route") or f"{MISSION_ROOM_ROOT}/decisions",
            "anchor": attention["id"],
        })
        secondary_drill_down = None
        if attention["id"] == "attention-ambassadeur-france":
            secondary_drill_down = {
                "view": "agenda",
                "route": f"{MISSION_ROOM_ROOT}/agenda",
                "anchor": attention["id"],
            }
        summary = attention.get("sentence") or (package or {}).get("decision") or attention.get("title")
        if package and package.get("recommended_option"):
            summary = f"{summary} Option recommandee : {package['recommended_option']}."
        cards.append(
            _arbitration_card(
                card_id=attention["id"],
                rank=int(attention.get("rank") or len(cards) + 1),
                domain=domain,
                title=attention.get("title") or (package or {}).get("title") or attention["id"],
                summary=summary,
                status=attention.get("status") or (package or {}).get("status") or "decision_required",
                deadline=attention.get("deadline") or (package or {}).get("deadline") or "aujourd'hui",
                tone=attention.get("tone") or (package or {}).get("tone") or "watch",
                cta_label=attention.get("action_label") or (package or {}).get("cta") or "Ouvrir le dossier",
                cta_route=attention.get("action_route") or drill_down["route"],
                drill_down=drill_down,
                draft_ready=attention.get("status") == "draft_ready" or bool((package or {}).get("status") == "draft_ready"),
                secondary_drill_down=secondary_drill_down,
            )
        )

    next_rank = len(cards) + 1
    for package in EXECUTIVE_DECISION_PACKAGES:
        if package["id"] in linked_packages:
            continue
        cards.append(
            _arbitration_card(
                card_id=package["id"],
                rank=next_rank,
                domain=_PACKAGE_DOMAINS.get(package["id"], "COMMUNICATION"),
                title=package.get("title") or package["id"],
                summary=package.get("decision") or package.get("why_now") or package.get("title"),
                status=package.get("status") or "decision_required",
                deadline=package.get("deadline") or "aujourd'hui",
                tone=package.get("tone") or "watch",
                cta_label=package.get("cta") or "Ouvrir le dossier",
                cta_route=_PACKAGE_DRILL_DOWN.get(package["id"], {}).get("route") or f"{MISSION_ROOM_ROOT}/decisions",
                drill_down=_clone(_PACKAGE_DRILL_DOWN.get(package["id"]) or {
                    "view": "decisions",
                    "route": f"{MISSION_ROOM_ROOT}/decisions",
                    "anchor": package["id"],
                }),
                draft_ready=package.get("status") == "draft_ready",
            )
        )
        next_rank += 1

    return sorted(cards, key=lambda card: int(card.get("rank") or 99))


def _intelligence_feeds_payload(
    news: dict[str, Any],
    visual: dict[str, Any],
    mapped: dict[str, Any],
    source_freshness: dict[str, Any],
    satellite: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    map_system = mapped.get("map_system") or {}
    maritime = map_system.get("maritime_snapshot") or (news.get("maritime_intelligence") or {}).get("latest_observation") or {}
    maritime_ports = maritime.get("ports") or _clone(MARITIME_PORTS)
    maritime_events = maritime.get("events") or _clone(MARITIME_EVENTS)
    visual_health = visual.get("source_health") or {}
    freshness_items = {item.get("key"): item for item in source_freshness.get("items") or []}
    delayed_project = next((project for project in PROJECTS if int(project.get("delay_days") or 0) > 0), PROJECTS[0])
    news_alerts = news.get("executive_alerts") or news.get("signals") or _clone(NEWS_SIGNALS)
    maritime_signal = next((signal for signal in news_alerts if signal.get("id") == "news-maritime-001"), None)
    satellite_scenes = (satellite or {}).get("scenes") or []
    satellite_mode = str((satellite or {}).get("mode") or "cache_baseline").replace("_", " ")
    return [
        {
            "key": "satellite",
            "label": "Imagerie satellite",
            "subtitle": "Couverture Nord + contexte Sahel · indicative",
            "metric": f"{len(satellite_scenes) or 2} scenes · {satellite_mode}",
            "confidence": 68,
            "freshness_at": (satellite or {}).get("captured_at") or "06:40",
            "tone": "watch",
            "route": f"{MISSION_ROOM_ROOT}/securite/monitor#satellite-imagery-rail",
        },
        {
            "key": "maritime-ais",
            "label": "Trafic maritime AIS",
            "subtitle": "Abidjan / San Pedro · lecture indicative",
            "metric": f"{len(maritime_ports)} ports · {len(maritime_events)} evenements",
            "confidence": int((freshness_items.get("maritime-traffic") or {}).get("confidence") or 66),
            "freshness_at": (maritime.get("freshness") or {}).get("updated_at") or "snapshot recent",
            "tone": "watch",
        },
        {
            "key": "ads-b",
            "label": "Espace aerien ADS-B",
            "subtitle": "Corridor Abidjan · demo-safe",
            "metric": "14 vols suivis",
            "confidence": 61,
            "freshness_at": "11:05",
            "tone": "stable",
        },
        {
            "key": "osint",
            "label": "OSINT multilingue",
            "subtitle": "Presse CI / CEDEAO / international",
            "metric": f"{len(news_alerts)} alertes qualifiees",
            "confidence": int((freshness_items.get("open-intelligence") or {}).get("confidence") or 72),
            "freshness_at": (news.get("source_health") or {}).get("coverage_label") or "dernier run veille",
            "tone": "critical" if news_alerts else "stable",
        },
        {
            "key": "mobile-signal",
            "label": "Signal reseau mobile",
            "subtitle": "Densite macro Korhogo / Nord",
            "metric": "Indice 0.58 · indicative",
            "confidence": 54,
            "freshness_at": "10:50",
            "tone": "watch",
        },
        {
            "key": "economy",
            "label": "Economie reelle",
            "subtitle": "Port Abidjan / retard chantier BTP",
            "metric": (
                f"{delayed_project.get('delay_days', 0)} j retard · "
                f"{(maritime_signal or {}).get('title', 'flux portuaire sous veille')[:42]}"
            ),
            "confidence": 70,
            "freshness_at": "11:00",
            "tone": "watch",
        },
        {
            "key": "terrain-sensors",
            "label": "Capteurs terrain",
            "subtitle": "Flux visuels Nord · lecture macro",
            "metric": f"{visual_health.get('observations') or visual_health.get('active_sources') or 16} capteurs actifs",
            "confidence": int((freshness_items.get("visual-streams") or {}).get("confidence") or 62),
            "freshness_at": visual_health.get("freshness_status") or visual_health.get("coverage_label") or "snapshot recent",
            "tone": "stable",
        },
        {
            "key": "cyber",
            "label": "Veille cyber",
            "subtitle": "Signaux institutionnels · fixture stable",
            "metric": "0 alerte critique",
            "confidence": 88,
            "freshness_at": "continu",
            "tone": "stable",
        },
    ]


_PRESS_CI_TAG_TOKENS = frozenset(
    {
        "zone nord",
        "nord ivoirien",
        "nord ci",
        "nord-côte d'ivoire",
        "nord-cote d'ivoire",
        "napie",
        "napié",
        "aerostar",
        "abidjan",
        "cacao",
        "prefet-nawa",
        "préfet-nawa",
        "prefet nawa",
        "préfet nawa",
        "vridi",
        "douanes-ci",
        "douanes ci",
        "ci-local",
        "ci-national",
        "sentinel-ci",
        "ivoirien",
        "ivoirienne",
        "ivoirians",
        "ivorian",
    }
)
_PRESS_CI_PUBLISHER_TOKENS = (
    "abidjan.net",
    "abidjan net",
    "fraternite matin",
    "fraternité matin",
    "fratmat",
    "rfi afrique ci",
    "jeune afrique ci",
    "rti info",
    "aip",
    "agence ivoirienne de presse",
    "7info",
    "connection ivoirienne",
    "ci-local",
    "ci-national",
    "ci-public",
    "ci-agency",
    "ci-maritime",
    "port autonome d'abidjan",
    "marinetraffic",
)
_PRESS_CI_COUNTRY_TOKENS = (
    "côte d'ivoire",
    "cote d'ivoire",
    "ivory coast",
    "ivoire",
)


def _press_ci_boost(alert: dict[str, Any]) -> int:
    """Compute a CI-first boost so the press hero stays local.

    +10 — geography_tier == "ci" or country/region matches Côte d'Ivoire.
    +5  — tags or haystack mention a SENTINEL-CI keyword (nord, napié,
          aerostar, abidjan, cacao, vridi, douanes-ci, prefet-nawa).
    +3  — publisher / source identified as a CI outlet.
    """

    boost = 0
    geo = str(
        alert.get("geography_tier")
        or alert.get("geo_tier")
        or alert.get("geography")
        or alert.get("region_iso")
        or ""
    ).lower()
    country = str(alert.get("country") or alert.get("zone") or "").lower()
    tags = [str(item).lower() for item in (alert.get("tags") or [])]
    source = str(alert.get("source") or alert.get("publisher") or "").lower()
    title = str(alert.get("title") or "").lower()
    summary = str(alert.get("summary") or alert.get("impact_ci") or "").lower()
    haystack = f"{title} {summary} {' '.join(tags)} {country} {geo} {source}"
    if geo == "ci" or geo.startswith("ci-") or geo == "ci-local":
        boost += 10
    elif any(token in country for token in _PRESS_CI_COUNTRY_TOKENS) or any(
        token in haystack for token in _PRESS_CI_COUNTRY_TOKENS
    ):
        boost += 10
    if any(token in _PRESS_CI_TAG_TOKENS for token in tags) or any(
        token in haystack for token in _PRESS_CI_TAG_TOKENS
    ):
        boost += 5
    if any(token in source for token in _PRESS_CI_PUBLISHER_TOKENS):
        boost += 3
    return boost


def _press_base_score(alert: dict[str, Any]) -> int:
    """Tie-breaker score used after the CI boost (risk + freshness)."""

    risk = str(alert.get("risk_level") or "medium").lower()
    base = {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(risk, 2)
    if alert.get("velocity") in {"rapide", "elevee"}:
        base += 1
    return base


def _press_preview_fallback_hero() -> dict[str, Any]:
    """Return the seeded Abidjan.net Centre Drones Napié article.

    Used as the press hero whenever the live RSS feeds are dry or every
    article comes from outside Côte d'Ivoire so the demo never opens with
    Mali / Iran / Ebola in the press_preview top-3.
    """

    return {
        "id": "press-fallback-abidjan-net-drone-napie",
        "title": "Côte d'Ivoire — Lancement du Centre International de Formation aux Métiers des Drones de Napié",
        "source": "Abidjan.net",
        "risk_level": "high",
        "risk_label": "HIGH",
        "tone": "critical",
        "route": (
            f"{MISSION_ROOM_ROOT}/presse?highlight=press-fallback-abidjan-net-drone-napie"
        ),
        "summary": (
            "Hero CI · Centre International de Formation aux Métiers des Drones de Napié "
            "(Poro) — chantier en retard de 120 jours, composants Aerostar Dynamics bloqués "
            "à Vridi sur le cargo MV Atlantic Trader."
        ),
        "geography_tier": "ci",
        "publisher": "Abidjan.net",
    }


def _press_preview_is_concrete_ci(item: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(item.get(key) or "")
        for key in ("title", "source", "summary", "country", "publisher", "region_iso", "geo_iso")
    ).lower()
    tags = [str(tag).lower() for tag in (item.get("tags") or [])]
    if str(item.get("region_iso") or item.get("geo_iso") or "").upper() == "CI":
        return True
    return any(token in haystack for token in _PRESS_CI_COUNTRY_TOKENS) or any(
        token in haystack for token in _PRESS_CI_TAG_TOKENS
    ) or any(token in _PRESS_CI_TAG_TOKENS for token in tags)


def _press_preview_region_iso(alert: dict[str, Any]) -> str | None:
    explicit = str(alert.get("region_iso") or alert.get("geo_iso") or "").upper()
    if explicit:
        return explicit
    # geography_tier='ci' alone can come from weak classifiers; only expose
    # region_iso when concrete CI markers are present in the article payload.
    if _press_preview_is_concrete_ci(alert):
        return "CI"
    return None


def _press_preview_payload(news: dict[str, Any], alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = list(alerts or _clone(NEWS_SIGNALS))

    def _rank_key(alert: dict[str, Any]) -> tuple[int, int]:
        return (-_press_ci_boost(alert), -_press_base_score(alert))

    candidates.sort(key=_rank_key)
    preview: list[dict[str, Any]] = []
    for alert in candidates[:3]:
        risk = alert.get("risk_level") or "medium"
        geo_tier = alert.get("geography_tier") or alert.get("geo_tier")
        preview.append(
            {
                "id": alert.get("id") or f"press-{len(preview) + 1}",
                "title": alert.get("title"),
                "source": alert.get("source") or "Veille executive",
                "risk_level": risk,
                "risk_label": risk.upper(),
                "tone": "critical" if _risk_rank(risk) >= 3 else "watch",
                "route": f"{MISSION_ROOM_ROOT}/presse?highlight={alert.get('id')}",
                "summary": alert.get("summary") or alert.get("impact_ci") or alert.get("recommended_action"),
                "geography_tier": geo_tier,
                "geo_tier": alert.get("geo_tier") or alert.get("geography_tier"),
                "region_iso": _press_preview_region_iso(alert),
                "country": alert.get("country") or alert.get("zone"),
                "publisher": alert.get("publisher") or alert.get("source"),
                "tags": alert.get("tags") or [],
            }
        )
    # If the top of the list still doesn't carry a CI signal (eg. RSS dry,
    # demo offline) we inject the Abidjan.net Centre Drones Napié hero so
    # the cockpit press card never opens on Mali / Iran / Ebola.
    if not preview or _press_ci_boost(preview[0]) == 0 or not _press_preview_is_concrete_ci(preview[0]):
        hero = _press_preview_fallback_hero()
        preview = [hero, *preview][:3]
    if not preview:
        for attention in ATTENTION_REQUIRED[:2]:
            preview.append(
                {
                    "id": attention["id"],
                    "title": attention["title"],
                    "source": "Attention cabinet",
                    "risk_level": "high" if attention.get("tone") == "critical" else "medium",
                    "risk_label": "HIGH" if attention.get("tone") == "critical" else "MEDIUM",
                    "tone": attention.get("tone") or "watch",
                    "route": f"{MISSION_ROOM_ROOT}/presse?highlight={attention['id']}",
                    "summary": attention.get("sentence") or attention.get("title"),
                }
            )
    return preview[:3]


def _agenda_timeline_payload(
    agenda_day: dict[str, Any],
    calendar_summary: Optional[dict[str, Any]],
    *,
    now_time_str: Optional[str] = None,
) -> dict[str, Any]:
    events = _clone(agenda_day.get("events") or AGENDA[:4])
    next_event = (calendar_summary or {}).get("next_event") or agenda_day.get("next_event") or (events[2] if len(events) > 2 else None)
    now_label = (now_time_str or "11:16")[:5]
    now_hh, _, now_mm = now_label.partition(":")
    try:
        now_minutes_total = int(now_hh) * 60 + int(now_mm or 0)
    except ValueError:
        now_minutes_total = 11 * 60 + 16

    def _event_minutes(value: str | None) -> int:
        if not value or ":" not in value:
            return 0
        try:
            hh, mm = value.split(":", 1)
            return int(hh) * 60 + int(mm or 0)
        except ValueError:
            return 0

    timeline: list[dict[str, Any]] = []
    now_inserted = False
    for event in events[:4]:
        entry = {
            **event,
            "status": "past" if _event_minutes(event.get("time")) <= now_minutes_total else "upcoming",
            "separate_from_actions": True,
        }
        timeline.append(entry)
        # Insert the "MAINTENANT" marker right after the latest past event.
        if not now_inserted and _event_minutes(event.get("time")) <= now_minutes_total:
            # Defer insertion until we know there's a later event, or simply
            # always insert and let UI place it last; here we insert if the
            # next event in the iteration is in the future.
            pass
    # Second pass: insert marker between past and upcoming events.
    rebuilt: list[dict[str, Any]] = []
    for idx, entry in enumerate(timeline):
        rebuilt.append(entry)
        next_entry = timeline[idx + 1] if idx + 1 < len(timeline) else None
        if (
            not now_inserted
            and entry.get("status") == "past"
            and (next_entry is None or next_entry.get("status") == "upcoming")
        ):
            rebuilt.append(
                {
                    "kind": "now",
                    "label": "MAINTENANT",
                    "time": now_label,
                    "separate_from_actions": True,
                }
            )
            now_inserted = True
    timeline = rebuilt
    if not now_inserted and timeline:
        timeline.insert(
            0,
            {
                "kind": "now",
                "label": "MAINTENANT",
                "time": now_label,
                "separate_from_actions": True,
            },
        )

    def _countdown_for(target_time: str | None) -> str:
        delta = _event_minutes(target_time) - now_minutes_total
        if delta <= 0:
            return "imminent"
        hours, minutes = divmod(delta, 60)
        if hours and minutes:
            return f"dans {hours}h{minutes:02d}"
        if hours:
            return f"dans {hours}h"
        return f"dans {minutes} min"

    if next_event:
        for entry in timeline:
            if entry.get("title") == next_event.get("title") or entry.get("time") == next_event.get("time"):
                entry["is_next"] = True
                entry["countdown"] = _countdown_for(entry.get("time") or next_event.get("time"))
                break
    elif timeline:
        for entry in reversed(timeline):
            if entry.get("kind") != "now":
                entry["is_next"] = True
                entry["countdown"] = _countdown_for(entry.get("time"))
                break
    return {
        "label": agenda_day.get("label") or "Agenda ministeriel",
        "separate_from_actions": True,
        "now_marker": {"label": "MAINTENANT", "time": now_label},
        "events": timeline,
        "next_event": next_event,
    }


def _cockpit_layout_widgets() -> list[dict[str, Any]]:
    return [
        {"id": "posture_bar", "stratum": "monitoring", "span": "full"},
        {"id": "map_preview", "stratum": "monitoring", "span": "2"},
        {"id": "sovereign_gauges", "stratum": "monitoring", "span": "1"},
        {"id": "intelligence_grid", "stratum": "monitoring", "span": "full"},
        {"id": "aya_banner", "stratum": "alerting", "span": "full"},
        {"id": "arbitration_strip", "stratum": "alerting", "span": "full"},
        {"id": "press_preview", "stratum": "alerting", "span": "full"},
        {"id": "agenda_timeline", "stratum": "alerting", "span": "half"},
        {"id": "decision_teaser", "stratum": "decision", "span": "full"},
        {"id": "aya_cta", "stratum": "decision", "span": "full"},
    ]


def _demo_narrative_payload() -> dict[str, Any]:
    return {
        "scenario_id": VP_SCENARIO_ID,
        "steps": [
            {
                "phase": "explorer",
                "focus_widget": "aya_banner",
                "prompt": "AYA oriente le Vice Premier Ministre vers la Zone Nord et les indicateurs de posture avant le Conseil.",
            },
            {
                "phase": "comprendre",
                "focus_widget": "press_preview",
                "anchor": "attention-inter-budget",
                "prompt": "Un signal presse ressort de la nuit — ouvrir le projet de reponse avant 14h00.",
            },
            {
                "phase": "decider",
                "focus_widget": "arbitration_strip",
                "anchor": "package-zone-nord",
                "prompt": "Comparer les options Zone Nord et preparer l'arbitrage avant 15h00.",
            },
        ],
        "economic_hook": {
            "title": "Port Abidjan / retard chantier",
            "cross_sources": ["maritime", "projets"],
            "cta_route": f"{MISSION_ROOM_ROOT}/strategie?layers=maritime,projects",
        },
    }


def _geographic_signal_tiers(news: dict[str, Any]) -> list[dict[str, Any]]:
    sections = news.get("geo_sections") or []
    if sections:
        return [
            {
                "key": section.get("key"),
                "label": section.get("label"),
                "count": section.get("count", 0),
                "top_signal": (section.get("signals") or [{}])[0].get("title"),
                "signals": section.get("signals") or [],
            }
            for section in sections
        ]
    return [
        {"key": "ci", "label": "Cote d'Ivoire", "count": 0, "top_signal": None, "signals": []},
        {"key": "cedeao", "label": "CEDEAO", "count": 0, "top_signal": None, "signals": []},
        {"key": "africa", "label": "Afrique", "count": 0, "top_signal": None, "signals": []},
        {"key": "world", "label": "Monde", "count": 0, "top_signal": None, "signals": []},
    ]


def _vp_story_context(
    *,
    agenda_day: Optional[dict[str, Any]] = None,
    news: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Single Vice Premier Ministre scenario shared by cockpit, agenda, briefing and press views."""
    news_context = news or {"geo_sections": _news_geo_sections(_clone(NEWS_SIGNALS))}
    return {
        "scenario_id": VP_SCENARIO_ID,
        "assistant": SENTINEL_ASSISTANT_NAME,
        "narrative": "Explorer les signaux, comprendre les sources, decider quoi faire et quand.",
        "anchors": {
            "priority_zone": "Zone Nord",
            "press_signal": "Article L'Inter - critique personnelle sur budget defense",
            "agenda_signal": "Ambassadeur France - dejeuner dans 1h44",
            "rumor_signal": "Emoi public - rumeur a contenir",
            "maritime_signal": "Port d'Abidjan - douanes et flux economiques",
        },
        "directive_of_day": _directive_of_day_payload(),
        "attention_required": _clone(ATTENTION_REQUIRED),
        "agenda_day": agenda_day
        or {
            "label": "Agenda ministeriel",
            "next_event": _clone(AGENDA[0]),
            "events": _clone(AGENDA[:4]),
            "available_window": {
                "label": "Fenetre utile",
                "time": "10:00-10:45",
                "reason": "Dernier creneau avant expression publique et amplification potentielle.",
            },
            "separate_from_actions": True,
        },
        "decision_queue": _decision_queue_payload(),
        "geographic_signal_tiers": _geographic_signal_tiers(news_context),
        "voice_demo_script": _clone(VOICE_DEMO_SCRIPT),
        "rumor_trace": _clone(RUMOR_TRACE),
        "executive_decision_packages": _clone(EXECUTIVE_DECISION_PACKAGES),
        "continuity_rule": "Toute information affichée doit mener à comprendre, ouvrir un dossier, préparer une réponse ou arbitrer.",
    }


def _attach_vp_story(payload: dict[str, Any], *, agenda_day: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    payload["vp_story"] = _vp_story_context(agenda_day=agenda_day, news=payload)
    return payload


def _source_freshness_payload(news: dict[str, Any], visual: dict[str, Any], mapped: dict[str, Any]) -> dict[str, Any]:
    map_system = mapped.get("map_system") or {}
    map_health = map_system.get("source_health") or mapped.get("source_health") or {}
    news_health = news.get("source_health") or {}
    visual_health = visual.get("source_health") or {}
    return {
        "status": "ready",
        "items": [
            {
                "key": "open-intelligence",
                "label": "Presse / rumeurs",
                "state": news_health.get("status") or "qualified",
                "freshness": news_health.get("last_run_label") or news_health.get("coverage_label") or "dernier run veille",
                "count": news_health.get("analyzed") or news_health.get("total_articles") or len(news.get("signals") or []),
                "confidence": 72,
            },
            {
                "key": "territorial-risk",
                "label": "Carte / territoire",
                "state": map_health.get("status") or "ready",
                "freshness": map_health.get("freshness") or "scoring actif",
                "count": (mapped.get("score_summary") or {}).get("zones_scored") or len(mapped.get("zones") or []),
                "confidence": 78,
            },
            {
                "key": "visual-streams",
                "label": "Observations visuelles",
                "state": visual_health.get("status") or "monitoring",
                "freshness": visual_health.get("freshness_status") or visual_health.get("coverage_label") or "snapshot recent",
                "count": visual_health.get("observations") or int(visual_health.get("active_sources") or 0),
                "confidence": 62,
            },
            {
                "key": "maritime-traffic",
                "label": "Maritime / douanes",
                "state": "snapshot",
                "freshness": "snapshot demo-safe · provider AIS optionnel",
                "count": len(MARITIME_PORTS) + len(MARITIME_EVENTS),
                "confidence": 66,
            },
        ],
    }


def _monitoring_layers_payload(mapped: dict[str, Any]) -> list[dict[str, Any]]:
    map_system = mapped.get("map_system") or {}
    registry = map_system.get("layer_registry") or map_system.get("layer_catalog") or []
    return [
        {
            "key": layer.get("key"),
            "label": layer.get("group") or layer.get("label"),
            "name": layer.get("label"),
            "count": int(layer.get("count") or 0),
            "freshness": layer.get("freshness") or "a jour",
            "confidence": int(layer.get("confidence") or 0),
            "source_kind": layer.get("source_kind") or layer.get("kind"),
            "visible": layer.get("visible", True),
        }
        for layer in registry
    ]


def _decision_posture_payload(
    posture: dict[str, Any],
    news: dict[str, Any],
    visual: dict[str, Any],
    mapped: dict[str, Any],
    calendar_summary: Optional[dict[str, Any]],
) -> dict[str, Any]:
    top_zone = ((mapped.get("score_summary") or {}).get("top_zone") or (mapped.get("zones") or [{}])[0] or {})
    news_alerts = news.get("executive_alerts") or news.get("signals") or []
    next_event = (calendar_summary or {}).get("next_event") or {}
    maritime = news.get("maritime_intelligence") or {}
    latest_maritime = maritime.get("latest_observation") or {}
    return {
        "label": posture.get("label") or "monitoring",
        "score": int(posture.get("score") or 0),
        "sentence": "Explorer les signaux, comprendre les preuves, decider avant les fenetres cabinet.",
        "modes": [
            {"key": "explorer", "label": "Explorer", "goal": "Voir posture, couches, zones et sources fraîches."},
            {"key": "comprendre", "label": "Comprendre", "goal": "Relier sources, rumeurs, projets, agenda et carte."},
            {"key": "decider", "label": "Décider", "goal": "Comparer options, coût/impact/confiance et préparer l'action."},
        ],
        "axes": [
            {
                "key": "security",
                "label": "Sécurité / territoire",
                "status": _signal_level(int(top_zone.get("level") or 0)),
                "score": int(top_zone.get("level") or 0),
                "why": top_zone.get("summary") or top_zone.get("signals", ["Zone prioritaire"])[0],
                "action": (top_zone.get("recommendations") or ["Ouvrir dossier zone"])[0],
                "deadline": "15:00",
            },
            {
                "key": "reputation",
                "label": "Réputation / presse",
                "status": "elevated" if news_alerts else "stable",
                "score": int((news.get("source_health") or {}).get("high_risk") or len(news_alerts)),
                "why": (news_alerts[0] or {}).get("title") if news_alerts else "Aucun signal prioritaire",
                "action": (news_alerts[0] or {}).get("recommended_action") or "Surveiller la couverture presse",
                "deadline": "14:00",
            },
            {
                "key": "economy",
                "label": "Économie / douanes",
                "status": "monitoring",
                "score": int(latest_maritime.get("score") or 58),
                "why": latest_maritime.get("summary") or "Ports et douanes sous veille contextuelle",
                "action": latest_maritime.get("recommended_action") or "Qualifier le signal portuaire",
                "deadline": latest_maritime.get("decision_deadline") or "12:00",
            },
            {
                "key": "agenda",
                "label": "Agenda / fenêtres",
                "status": "monitoring" if next_event else "stable",
                "score": len((calendar_summary or {}).get("decision_deadlines") or []),
                "why": next_event.get("title") or "Agenda habilité disponible",
                "action": "Préparer la prochaine séquence utile",
                "deadline": next_event.get("time") or "aujourd'hui",
            },
            {
                "key": "visual",
                "label": "Visuel / terrain",
                "status": "monitoring",
                "score": int((visual.get("latest_observation") or {}).get("vigilance_score") or 38),
                "why": (visual.get("latest_observation") or {}).get("summary") or "Observation snapshot sans signal critique confirmé",
                "action": "Croiser avec presse et carte avant recommandation",
                "deadline": "prochain cycle",
            },
        ],
    }


def _add_graph_node(nodes: dict[str, dict[str, Any]], *, node_id: str, label: str, kind: str, **props: Any) -> None:
    if not node_id:
        return
    nodes[node_id] = {
        "id": node_id,
        "label": label,
        "kind": kind,
        **{key: value for key, value in props.items() if value not in (None, "", [], {})},
    }


def _add_graph_edge(edges: list[dict[str, Any]], *, source: str, target: str, relation: str, **props: Any) -> None:
    if not source or not target:
        return
    edges.append(
        {
            "id": f"{source}->{relation}->{target}",
            "source": source,
            "target": target,
            "relation": relation,
            **{key: value for key, value in props.items() if value not in (None, "", [], {})},
        }
    )


def evidence_graph_payload(workspace: Workspace, db: Optional[DBSession] = None) -> dict[str, Any]:
    """Return a compact OSINT evidence graph for AYA and the executive cockpit."""
    news = _executive_news_payload(workspace, db)
    visual = _visual_payload(workspace, db)
    mapped = map_payload(workspace, db=db)
    calendar_summary = calendar_summary_payload(db, workspace) if db else None
    decision_posture = _decision_posture_payload(_strategic_posture(mapped, news, visual), news, visual, mapped, calendar_summary)
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    _add_graph_node(nodes, node_id="workspace-sentinel-ci", label="SENTINEL-CI", kind="workspace", country="Cote d'Ivoire")
    for source in source_index():
        _add_graph_node(
            nodes,
            node_id=source.get("id"),
            label=source.get("label") or source.get("title") or source.get("id"),
            kind="source",
            source_kind=source.get("kind"),
            confidence=source.get("confidence"),
            age=source.get("age"),
        )
        _add_graph_edge(edges, source="workspace-sentinel-ci", target=source.get("id"), relation="qualifies_source")

    zones = mapped.get("zones") or []
    for zone in zones:
        zone_id = zone.get("id") or zone.get("key")
        _add_graph_node(
            nodes,
            node_id=zone_id,
            label=zone.get("name") or zone_id,
            kind="location",
            score=zone.get("level") or (zone.get("score") or {}).get("score"),
            severity=_signal_level(int(zone.get("level") or 0)),
        )
        _add_graph_edge(edges, source="workspace-sentinel-ci", target=zone_id, relation="monitors_zone")

    alerts = news.get("executive_alerts") or news.get("signals") or _clone(NEWS_SIGNALS)
    for alert in alerts[:10]:
        alert_id = alert.get("id")
        _add_graph_node(
            nodes,
            node_id=alert_id,
            label=alert.get("title") or alert_id,
            kind="rumor" if "rumeur" in str(alert.get("title", "")).lower() or str(alert.get("id", "")).startswith("social") else "event",
            risk=alert.get("risk_level"),
            geo_tier=alert.get("geo_tier") or alert.get("geography_tier"),
            confidence=alert.get("confidence"),
            recommended_action=alert.get("recommended_action"),
        )
        _add_graph_edge(edges, source="workspace-sentinel-ci", target=alert_id, relation="prioritizes_signal")
        for source_id in alert.get("sources") or []:
            _add_graph_edge(edges, source=source_id, target=alert_id, relation="supports")
        zone_label = str(alert.get("zone") or "").lower()
        target_zone = next((zone.get("id") for zone in zones if str(zone.get("name", "")).lower() in zone_label), None)
        if not target_zone and ("nord" in zone_label or "north" in zone_label):
            target_zone = "zone-nord"
        if not target_zone and ("abidjan" in zone_label or "golfe" in zone_label):
            target_zone = "zone-sud"
        if target_zone:
            _add_graph_edge(edges, source=alert_id, target=target_zone, relation="impacts_zone")

    for project in PROJECTS:
        project_id = project.get("id")
        _add_graph_node(
            nodes,
            node_id=project_id,
            label=project.get("name"),
            kind="project",
            weather=project.get("weather"),
            progress=project.get("progress"),
            risk=project.get("risk"),
        )
        for source_id in project.get("sources") or ["src-project-sante-042"]:
            _add_graph_edge(edges, source=source_id, target=project_id, relation="documents")
        if "north" in str(project_id) or "nord" in str(project.get("name", "")).lower():
            _add_graph_edge(edges, source=project_id, target="zone-nord", relation="affects_zone")

    for package in EXECUTIVE_DECISION_PACKAGES:
        package_id = package.get("id")
        _add_graph_node(
            nodes,
            node_id=package_id,
            label=package.get("title"),
            kind="action",
            deadline=package.get("deadline"),
            confidence=package.get("confidence"),
            status=package.get("status"),
            recommended_option=package.get("recommended_option"),
        )
        _add_graph_edge(edges, source="aya", target=package_id, relation="recommends")
        if "nord" in str(package_id):
            _add_graph_edge(edges, source=package_id, target="zone-nord", relation="decides_for")

    _add_graph_node(nodes, node_id="aya", label=SENTINEL_ASSISTANT_NAME, kind="assistant", role="adjoint souverain")
    for item in (calendar_summary or {}).get("events", [])[:6]:
        event_id = item.get("id") or f"agenda-{item.get('time')}-{item.get('title')}"
        _add_graph_node(nodes, node_id=event_id, label=item.get("title"), kind="agenda", time=item.get("time"), location=item.get("location"))
        _add_graph_edge(edges, source=event_id, target="workspace-sentinel-ci", relation="constrains_day")

    for port in MARITIME_PORTS:
        port_id = port.get("id")
        _add_graph_node(nodes, node_id=port_id, label=port.get("name"), kind="port", score=port.get("score"), location=port.get("location"))
        _add_graph_edge(edges, source="workspace-sentinel-ci", target=port_id, relation="monitors_port")
    for event in MARITIME_EVENTS:
        event_id = event.get("id")
        _add_graph_node(nodes, node_id=event_id, label=event.get("title"), kind="maritime", score=event.get("score"), domain=event.get("domain"))
        for source_id in event.get("source_refs") or []:
            _add_graph_edge(edges, source=source_id, target=event_id, relation="supports")
        _add_graph_edge(edges, source=event_id, target="port-abidjan", relation="impacts_port")

    rumor_id = "rumor-trace-prioritaire"
    _add_graph_node(nodes, node_id=rumor_id, label=RUMOR_TRACE["headline"], kind="rumor_trace", origin=RUMOR_TRACE["origin"])
    for index, item in enumerate(RUMOR_TRACE.get("spread") or []):
        channel_id = f"rumor-channel-{index}-{str(item.get('channel')).lower()}"
        _add_graph_node(nodes, node_id=channel_id, label=item.get("channel"), kind="channel", time=item.get("time"), confidence=item.get("confidence"))
        _add_graph_edge(edges, source=channel_id, target=rumor_id, relation="propagates")
    _add_graph_edge(edges, source=rumor_id, target="package-rumeur-emoi", relation="requires_action")

    # ------------------------------------------------------------------
    # Phase A — chaine causale "Pourquoi -> pourquoi" (S1)
    #
    # Relations explicites typees `caused_by` qui relient la tension
    # Zone Nord au projet public en retard, puis au cargo bloque,
    # puis au PV douanes non-conformite et a l'email derogation.
    # Chaque noeud porte ses `evidence_refs` pour permettre au skill
    # `causal_drill_v1` de citer des sources lors du drill AYA.
    # ------------------------------------------------------------------
    _add_graph_node(
        nodes,
        node_id="proj-drone-centre-napie",
        label="Centre International Formation Drones - Napié (Poro)",
        kind="project",
        status="delayed",
        aliases=["proj-public-north-supply"],
        evidence_refs=[
            "src-abidjan-net-drone-napie-2025-07-16",
            "src-cabinet-brief-001",
        ],
        narrative_short=(
            "Composants drones Aerostar Dynamics (USA) bloqués à Vridi : retard estimé "
            "à 120 jours sur le chantier du Centre Napié (100 M USD / Côte d'Ivoire Innovation 2030)."
        ),
        next_surface={
            "route": "/hypervisor/mission-room/strategie",
            "queryParams": {"focus": "zone-nord"},
            "highlight": "proj-drone-centre-napie",
            "panel": "projects",
        },
    )
    _add_graph_node(
        nodes,
        node_id="cargo-abidjan-supply-001",
        label="Cargo MV Atlantic Trader - composants drones Napié",
        kind="cargo",
        vessel_name="MV Atlantic Trader",
        imo="9876543",
        mmsi="627012345",
        status="awaiting_customs",
        origin="USA East Coast",
        destination="Napié via Abidjan",
        linked_project="proj-drone-centre-napie",
        evidence_refs=[
            "src-maritime-paa-001",
            "src-marinetraffic-context-001",
            "src-abidjan-net-drone-napie-2025-07-16",
        ],
        narrative_short="Cargaison bloquee a Vridi par effet collateral du PV douanes du 18 mai.",
        next_surface={
            "route": "/hypervisor/mission-room/strategie",
            "queryParams": {"mode": "live", "panel": "maritime", "vessel": "mv-atlantic-trader"},
            "highlight": "cargo-abidjan-supply-001",
            "panel": "maritime",
        },
    )
    _add_graph_node(
        nodes,
        node_id="customs-record-non-conformite-2026-05",
        label="PV douanes - non conformite declarative (18 mai)",
        kind="customs_record",
        record_kind="customs_pv",
        record_date="2026-05-18",
        document_id="proces-verbal-douanes-non-conformite-2026-05-18",
        cited_page=2,
        affected_cargo_ids=["cargo-abidjan-supply-001"],
        evidence_refs=["sentinel-ci-customs-records"],
        narrative_short="PV douanes constate une non conformite sur un autre cargo, gelant le couloir d'entree port.",
        next_surface={
            "route": "/hypervisor/mission-room/strategie",
            "queryParams": {"panel": "maritime", "document": "proces-verbal-douanes-2026-05-18"},
            "highlight": "customs-record-non-conformite-2026-05",
            "panel": "document_preview",
        },
    )
    _add_graph_node(
        nodes,
        node_id="action-email-derogation-douanes",
        label="Brouillon email derogation Chef Douanes",
        kind="action_proposal",
        action_id="aya.draft_customs_email",
        evidence_refs=["proj-drone-centre-napie", "cargo-abidjan-supply-001", "customs-record-non-conformite-2026-05"],
        narrative_short="Proposition de courrier de priorisation pour distinguer le cargo Nord du cargo non conforme.",
        next_surface={
            "route": "/hypervisor/mission-room/decisions",
            "queryParams": {"focus": "action-email-derogation-douanes"},
            "panel": "draft_email",
        },
    )
    # Edges typed causal chain.
    _add_graph_edge(edges, source="zone-nord", target="proj-drone-centre-napie", relation="caused_by", weight=0.92, explanation="Retard du Centre Drones Napié nourrit la tension territoriale dans la région du Poro / Nord.")
    _add_graph_edge(edges, source="proj-drone-centre-napie", target="cargo-abidjan-supply-001", relation="caused_by", weight=0.88, explanation="Composants drones Aerostar Dynamics du projet Napié bloqués sur le cargo MV Atlantic Trader.")
    _add_graph_edge(edges, source="cargo-abidjan-supply-001", target="customs-record-non-conformite-2026-05", relation="caused_by", weight=0.84, explanation="Le PV douanes du 18 mai sur un autre cargo gele le couloir d'entree port.")
    _add_graph_edge(edges, source="customs-record-non-conformite-2026-05", target="action-email-derogation-douanes", relation="mitigated_by", weight=0.78, explanation="Email derogation chef douanes pour distinguer le cargo Nord du cargo non conforme.")

    clusters = [
        {"key": "territory", "label": "Territoire", "node_kinds": ["location", "project", "action", "zone"]},
        {"key": "osint", "label": "Presse / rumeurs", "node_kinds": ["source", "event", "rumor", "rumor_trace", "channel"]},
        {"key": "economy", "label": "Maritime / douanes", "node_kinds": ["port", "maritime", "cargo", "customs_record"]},
        {"key": "decision", "label": "Décision", "node_kinds": ["assistant", "agenda", "action", "action_proposal"]},
    ]
    return {
        "workspace": _workspace_meta(workspace),
        "mode": "evidence_graph_v1",
        "assistant": SENTINEL_ASSISTANT_NAME,
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "top_relationships": [
                "rumeurs -> zones -> options cabinet",
                "presse locale -> réputation -> brouillon email",
                "port/douanes -> économie -> arbitrage avant midi",
                "agenda -> fenêtres -> décision avant Conseil",
            ],
            "decision_posture": decision_posture,
        },
        "clusters": clusters,
        "nodes": list(nodes.values()),
        "edges": edges,
        "source_freshness": _source_freshness_payload(news, visual, mapped),
        "knowledge": {
            "scope": "vigie",
            "collection_slug": SENTINEL_EVIDENCE_GRAPH_COLLECTION,
            "adjacent_collections": [
                "sentinel-ci-open-intelligence",
                "sentinel-ci-projects",
                "sentinel-ci-ministerial-briefs",
                "sentinel-ci-territorial-map",
                "sentinel-ci-territorial-intelligence",
                "sentinel-ci-visual-intelligence",
            ],
        },
        "suggested_questions": [
            "AYA, trace l'origine de la rumeur prioritaire.",
            "AYA, relie le risque portuaire au point douanes.",
            "AYA, quelles sources soutiennent l'arbitrage Zone Nord ?",
        ],
    }


def evidence_graph_trace(
    workspace: Workspace,
    *,
    from_node: str,
    relation: str = "caused_by",
    depth: int = 4,
    db: Optional[DBSession] = None,
) -> dict[str, Any]:
    """Return the causal trace from ``from_node`` following ``relation``.

    Used by AYA's `aya.explain_why` action (skill ``causal_drill_v1``) to
    chain "pourquoi -> pourquoi" answers across screens. The trace
    surfaces, for each step, the next surface AYA should navigate to and
    the short narrative + evidence refs to cite.
    """
    graph = evidence_graph_payload(workspace, db=db)
    nodes_by_id = {node.get("id"): node for node in graph.get("nodes") or []}
    edges = graph.get("edges") or []
    out_edges_by_source: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        if edge.get("relation") != relation:
            continue
        out_edges_by_source.setdefault(str(edge.get("source")), []).append(edge)

    depth_cap = max(1, min(int(depth or 4), 8))
    path: list[dict[str, Any]] = []
    visited: set[str] = set()
    current = from_node
    while current and current not in visited and len(path) < depth_cap:
        visited.add(current)
        node = nodes_by_id.get(current)
        if not node:
            break
        outgoing = out_edges_by_source.get(current, [])
        outgoing_sorted = sorted(outgoing, key=lambda e: float(e.get("weight") or 0.0), reverse=True)
        next_edge = outgoing_sorted[0] if outgoing_sorted else None
        path.append(
            {
                "node": node,
                "edge": next_edge,
                "next_node_id": (next_edge or {}).get("target"),
            }
        )
        current = (next_edge or {}).get("target")

    tail_node = nodes_by_id.get(current) if current else None
    if tail_node and tail_node.get("id") not in {step["node"].get("id") for step in path}:
        path.append({"node": tail_node, "edge": None, "next_node_id": None})

    return {
        "workspace": _workspace_meta(workspace),
        "from_node": from_node,
        "relation": relation,
        "depth": depth_cap,
        "path": path,
        "terminal_node": (path[-1]["node"] if path else None),
        "knowledge": {
            "scope": "vigie",
            "collection_slug": SENTINEL_EVIDENCE_GRAPH_COLLECTION,
        },
    }


def cockpit_payload(workspace: Workspace, db: Optional[DBSession] = None) -> dict[str, Any]:
    overview = overview_payload(workspace)
    news = _executive_news_payload(workspace, db)
    visual = _visual_payload(workspace, db)
    mapped = map_payload(workspace, db=db)
    posture = _strategic_posture(mapped, news, visual)
    calendar_summary = calendar_summary_payload(db, workspace) if db else None
    decision_posture = _decision_posture_payload(posture, news, visual, mapped, calendar_summary)
    source_freshness = _source_freshness_payload(news, visual, mapped)
    monitoring_layers = _monitoring_layers_payload(mapped)
    evidence_graph = evidence_graph_payload(workspace, db=db)
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
    agenda_day = _agenda_day(overview, calendar_summary)
    fused_map_preview = _fused_map_preview(mapped, news, visual)
    arbitration_cards = _arbitration_cards_payload()
    satellite = resolve_satellite_scenes(workspace)
    intelligence_feeds = _intelligence_feeds_payload(news, visual, mapped, source_freshness, satellite)
    press_preview = _press_preview_payload(news, alerts)
    try:
        from app.services.demo_time_context import resolve_demo_time

        now_time_str = resolve_demo_time(workspace).strftime("%H:%M")
    except Exception:  # noqa: BLE001
        now_time_str = None
    agenda_timeline = _agenda_timeline_payload(agenda_day, calendar_summary, now_time_str=now_time_str)
    demo_narrative = _demo_narrative_payload()
    aya_recommendation = {
        "assistant": SENTINEL_ASSISTANT_NAME,
        "voice_first": True,
        "prompt": VOICE_DEMO_SCRIPT["prompt"],
        "answer": VOICE_DEMO_SCRIPT["answer"],
        "target_latency_s": VOICE_DEMO_SCRIPT["target_latency_s"],
        "cta_primary": "Ecouter le briefing AYA",
        "cta_secondary": "Parler a AYA",
        "decision_package": _clone(EXECUTIVE_DECISION_PACKAGES[0]),
    }
    decision_queue = _decision_queue_payload()
    vp_story = _vp_story_context(agenda_day=agenda_day, news=news)
    security_osint_badges = _security_osint_source_badges(workspace)
    cedeao_index = cedeao_index_payload_for_workspace(workspace)
    return {
        **overview,
        "security_osint_badges": security_osint_badges,
        "cedeao_index": cedeao_index,
        "vp_status_bar": _vp_status_bar(overview, posture),
        "directive_of_day": vp_story["directive_of_day"],
        "fused_map_preview": fused_map_preview,
        "agenda_day": agenda_day,
        "agenda_timeline": agenda_timeline,
        "arbitration_cards": arbitration_cards,
        "intelligence_feeds": intelligence_feeds,
        "press_preview": press_preview,
        "demo_narrative": demo_narrative,
        "aya_recommendation": aya_recommendation,
        "decision_queue": decision_queue,
        "geographic_signal_tiers": vp_story["geographic_signal_tiers"],
        "vp_story": vp_story,
        "sovereign_indicators": _sovereign_indicators(overview, posture),
        "decision_posture": decision_posture,
        "source_freshness": source_freshness,
        "monitoring_layers": monitoring_layers,
        "evidence_graph_summary": {
            **evidence_graph["summary"],
            "route": f"{MISSION_ROOM_ROOT}/recherche",
            "collection_slug": SENTINEL_EVIDENCE_GRAPH_COLLECTION,
        },
        "scenario_modes": decision_posture["modes"],
        "layout": {
            "variant": "vp_decision_cockpit",
            "density": "desktop_laptop",
            "demo_strata": [
                {"label": "Monitoring quotidien", "share": "50%"},
                {"label": "Information & alerting IA", "share": "25%"},
                {"label": "Decision & action", "share": "20-25%"},
            ],
            "charts": ["fused_map_preview", "threat_trend", "agenda_day", "decision_queue"],
            "widgets": _cockpit_layout_widgets(),
        },
        "decision_focus": _clone(DECISIONS[:2]),
        "messages": _clone(MESSAGES),
        "library": _clone(LIBRARY_ITEMS),
        "security_documents": _clone(SECURITY_LIBRARY_ITEMS),
    }


def briefing_payload(workspace: Workspace, db: Optional[DBSession] = None) -> dict[str, Any]:
    mapped = map_payload(workspace, db=db)
    news = news_payload(workspace, db=db)
    visual = _visual_payload(workspace, db)
    maritime = news.get("maritime_intelligence") or _maritime_intelligence_payload(_feed_rows(db, workspace), news.get("executive_alerts") or news.get("signals") or [])
    calendar_summary = calendar_summary_payload(db, workspace) if db else None
    agenda_day = _agenda_day({"agenda": _agenda_items_from_calendar(workspace, db)}, calendar_summary)
    vp_story = _vp_story_context(agenda_day=agenda_day, news=news)
    visual_brief = _visual_intelligence_brief(
        visual,
        news,
        mapped,
        calendar_summary=calendar_summary,
        cross_source_signals=[],
    )
    sections = [
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
            "id": "visual_cross_check",
            "title": "Lecture visuelle croisee",
            "content": visual_brief["briefing_insert"],
            "sources": ["src-visual-intelligence-001", "src-press-rfi-017", "src-map-sentinel-ci-001"],
        },
        {
            "id": "maritime_customs",
            "title": "Maritime / douanes",
            "content": (
                f"{(maritime.get('latest_observation') or {}).get('summary')} "
                f"Action recommandee : {(maritime.get('latest_observation') or {}).get('recommended_action')} "
                "Ce signal doit rester une preuve de contexte tant que Port + Douanes n'ont pas confirme."
            ),
            "sources": ["src-maritime-paa-001", "src-maritime-marinelink-001", "src-marinetraffic-context-001"],
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
    ]
    return {
        "workspace": _workspace_meta(workspace),
        "title": "Briefing quotidien Vice Premier Ministre",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "sections": sections,
        "vp_story": vp_story,
        "directive_of_day": vp_story["directive_of_day"],
        "attention_required": vp_story["attention_required"],
        "agenda_day": agenda_day,
        "decision_queue": vp_story["decision_queue"],
        "visual_intelligence_brief": visual_brief,
        "maritime_intelligence": maritime,
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
            "vp_story": _vp_story_context(),
            "sources": source_index(),
        }
    zones = _clone(MAP_ZONES)
    action_rows = list_action_items(db, workspace, include_cancelled=False, target_kind="zone") if db else []
    actions_by_target = {item.target_id: serialize_action_item(item) for item in action_rows}
    for zone in zones:
        zone["scenario_options"] = _scenario_options_for(zone["id"])
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
        "vp_story": _vp_story_context(),
        "sources": source_index(),
    }


def monitor_payload(workspace: Workspace, db: Optional[DBSession] = None) -> dict[str, Any]:
    mapped = map_payload(workspace, db=db)
    news = news_payload(workspace, db=db)
    visual = _visual_payload(workspace, db)
    maritime = news.get("maritime_intelligence") or _maritime_intelligence_payload(_feed_rows(db, workspace), news.get("executive_alerts") or news.get("signals") or [])
    calendar_summary = calendar_summary_payload(db, workspace) if db else None
    agenda_items = _agenda_items_from_calendar(workspace, db)
    agenda_day = _agenda_day({"agenda": agenda_items}, calendar_summary)
    vp_story = _vp_story_context(agenda_day=agenda_day, news=news)
    action_rows = list_action_items(db, workspace, include_cancelled=False) if db else []
    action_items = [serialize_action_item(row) for row in action_rows[:6]]
    action_summary = action_plan_summary_payload(db, workspace) if db else {}
    posture = _strategic_posture(mapped, news, visual, calendar_summary=calendar_summary, action_summary=action_summary)
    zones = _enriched_monitor_zones(mapped)
    top_zones = sorted(zones, key=lambda item: int(item.get("level") or 0), reverse=True)[:3]
    visual_observations = visual.get("observations") or []
    cross_source_signals = _cross_source_signals(
        mapped,
        news,
        visual,
        maritime=maritime,
        calendar_summary=calendar_summary,
        action_summary=action_summary,
        action_items=action_items,
    )
    visual_intelligence_brief = _visual_intelligence_brief(
        visual,
        news,
        mapped,
        calendar_summary=calendar_summary,
        cross_source_signals=cross_source_signals,
    )
    scenario = _scenario_fusion_payload(
        workspace,
        mapped,
        posture,
        cross_source_signals,
        calendar_summary=calendar_summary,
        action_summary=action_summary,
    )
    layers = _monitor_layers(zones, news, visual, maritime)
    monitor_map_system = _monitor_map_system(mapped, layers, maritime)
    active_evidence = _active_evidence_payload(scenario, cross_source_signals, visual_intelligence_brief)
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
    return {
        "workspace": _workspace_meta(workspace),
        "title": "Mission Control Room",
        "summary": posture["summary"],
        "vp_story": vp_story,
        "worldmonitor_principles": _worldmonitor_principles_payload(),
        "decision_sentence": _clone(DECISION_SENTENCE),
        "directive_of_day": vp_story["directive_of_day"],
        "attention_required": vp_story["attention_required"],
        "sixty_second_cockpit": {
            "urgences": vp_story["attention_required"],
            "agenda_focus": agenda_items[:1],
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
        "active_evidence": active_evidence,
        "cross_source_signals": cross_source_signals,
        "visual_intelligence_brief": visual_intelligence_brief,
        "maritime": maritime,
        "voice_context": _aya_voice_context(scenario, cross_source_signals, visual_intelligence_brief, active_evidence),
        "map": mapped.get("map"),
        "map_system": monitor_map_system,
        "zones": zones,
        "top_zones": top_zones,
        "visual": visual,
        "visual_observations": visual_observations,
        "agenda": agenda_items[:6],
        "agenda_day": agenda_day,
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


def security_monitor_payload(workspace: Workspace, db: Optional[DBSession] = None) -> dict[str, Any]:
    """Full-screen Security Monitor — Sahel theater, ADS-B advisory and social/rumor cross-feed."""
    mapped = map_payload(workspace, db=db)
    troops = _clone(TROOPS_SAHEL)
    social = _clone(SOCIAL_SNAPSHOT)
    rumor = _clone(RUMOR_FRONTIER_TRACE)
    posture = _clone(SECURITY_POSTURE)
    satellite = resolve_satellite_scenes(workspace)
    tracks = troops.get("tracks") or []
    tweets = social.get("tweets") or []
    layers = [
        {"key": "military-air", "label": "Traces ADS-B advisory", "enabled": True, "count": len(tracks)},
        {"key": "border-tension", "label": "Tension frontière Nord", "enabled": True, "count": len(rumor.get("chain") or [])},
        {"key": "social-geo", "label": "Pulsation sociale", "enabled": True, "count": len(tweets)},
        {"key": "satellite-footprint", "label": "Empreintes satellite advisory", "enabled": True, "count": len(satellite.get("scenes") or [])},
    ]
    map_state = {
        "preset": "sahel",
        "zoom": "regional",
        "basemap": "satellite",
        "active_layers": ["military-air", "border-tension", "satellite-footprint", "regional-context"],
        "focus": {"label": troops.get("theater_label"), "longitude": -2.0, "latitude": 13.5},
    }
    return {
        "workspace": _workspace_meta(workspace),
        "title": "Security Monitor — Théâtre Sahel",
        "summary": posture.get("summary"),
        "route": f"{MISSION_ROOM_ROOT}/securite/monitor",
        "security_posture": posture,
        "map": mapped.get("map"),
        "map_system": mapped.get("map_system"),
        "map_state": map_state,
        "zones": mapped.get("zones") or [],
        "layers": layers,
        "satellite_imagery": satellite,
        "theater_sahel": troops,
        "social_signals": social,
        "rumor_thread": rumor,
        "adsb_alerts": [
            {
                "id": track.get("id"),
                "callsign": track.get("callsign"),
                "kind": track.get("kind"),
                "tone": track.get("tone") or "watch",
                "summary": (
                    f"{track.get('origin', '—')} → {track.get('destination', '—')} · "
                    f"alt {track.get('altitude_ft', '—')} ft"
                ),
            }
            for track in tracks[:8]
        ],
        "social_feed": [
            {
                "id": tweet.get("id"),
                "handle": tweet.get("handle"),
                "kind": tweet.get("kind"),
                "sentiment": tweet.get("sentiment"),
                "text": tweet.get("text"),
                "engagement": tweet.get("engagement"),
            }
            for tweet in tweets[:6]
        ],
        "source_freshness": {
            "adsb": f"Snapshot ADS-B advisory — {troops.get('captured_at', '14h30')}",
            "social": f"Snapshot demo-safe — {social.get('captured_at', '14h25')}",
            "rumor": "Dossier OSINT — démenti officiel 13h46",
            "baseline": True,
            "mode": "cache_baseline",
        },
        "disclaimer": troops.get("disclaimer"),
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


def _monitor_layers(zones: list[dict[str, Any]], news: dict[str, Any], visual: dict[str, Any], maritime: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    alerts = news.get("executive_alerts") or news.get("signals") or []
    maritime_count = len((maritime or {}).get("vessel_events") or [])
    return [
        {"key": "territorial-risk", "label": "Territoire", "enabled": True, "count": len(zones)},
        {"key": "open-intelligence", "label": "Presse / rumeurs", "enabled": True, "count": len(alerts)},
        {"key": "visual-streams", "label": "Flux terrain", "enabled": True, "count": int((visual.get("source_health") or {}).get("active_sources") or 0)},
        {"key": "maritime-traffic", "label": "Maritime / douanes", "enabled": False, "count": maritime_count},
    ]


def _monitor_map_system(mapped: dict[str, Any], layers: list[dict[str, Any]], maritime: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    map_system = _clone(mapped.get("map_system"))
    if not map_system:
        return None
    active_layer_keys = [layer["key"] for layer in layers if layer.get("enabled") is not False]
    catalog_by_key = {
        str(layer.get("key")): layer
        for layer in (map_system.get("layer_catalog") or [])
        if layer.get("key")
    }
    compact_catalog = []
    for layer in layers:
        existing = _clone(catalog_by_key.get(layer["key"], {}))
        existing.update(
            {
                "key": layer["key"],
                "label": layer["label"],
                "short_label": layer["label"],
                "visible": layer.get("enabled") is not False,
                "count": layer["count"],
                "tone": "orange" if layer["key"] == "maritime-traffic" else existing.get("tone", "cyan"),
                "kind": "maritime_evidence" if layer["key"] == "maritime-traffic" else existing.get("kind"),
                "confidence": 64 if layer["key"] == "maritime-traffic" else existing.get("confidence", 65),
            }
        )
        compact_catalog.append(existing)
    map_system["layer_catalog"] = compact_catalog
    default_state = _clone(map_system.get("default_map_state") or {})
    default_state["active_layers"] = active_layer_keys
    default_state["basemap"] = default_state.get("basemap") or "administrative"
    map_system["default_map_state"] = default_state
    maritime_sources = _maritime_map_sources(maritime or {})
    geojson_sources = _clone(map_system.get("geojson_sources") or {})
    geojson_sources.update(maritime_sources)
    map_system["geojson_sources"] = geojson_sources
    presets = _clone(map_system.get("camera_presets") or {})
    presets["maritime-abidjan"] = {"longitude": -4.0083, "latitude": 5.2512, "zoom": 9.15, "duration_ms": 220}
    map_system["camera_presets"] = presets
    return map_system


def _maritime_map_sources(maritime: dict[str, Any]) -> dict[str, Any]:
    ports = maritime.get("ports") or _clone(MARITIME_PORTS)
    events = maritime.get("vessel_events") or _clone(MARITIME_EVENTS)
    port_features = [
        {
            "type": "Feature",
            "id": port.get("id"),
            "geometry": {"type": "Point", "coordinates": [port.get("longitude"), port.get("latitude")]},
            "properties": {
                "id": port.get("id"),
                "name": port.get("name"),
                "kind": "port",
                "location": port.get("location"),
                "weight": port.get("score") or 40,
                "tone": port.get("tone") or "monitoring",
                "summary": port.get("role"),
            },
        }
        for port in ports
        if port.get("longitude") is not None and port.get("latitude") is not None
    ]
    event_features = [
        {
            "type": "Feature",
            "id": event.get("id"),
            "geometry": {"type": "Point", "coordinates": [event.get("longitude"), event.get("latitude")]},
            "properties": {
                "id": event.get("id"),
                "name": event.get("title"),
                "kind": "maritime_event",
                "location": event.get("location"),
                "weight": event.get("score") or 50,
                "tone": event.get("severity") or "monitoring",
                "domain": event.get("domain"),
                "summary": event.get("summary"),
                "recommended_action": event.get("recommended_action"),
                "decision_deadline": event.get("decision_deadline"),
                "source_refs": event.get("source_refs") or [],
            },
        }
        for event in events
        if event.get("longitude") is not None and event.get("latitude") is not None
    ]
    route_features = [
        {
            "type": "Feature",
            "id": "maritime-route-abidjan-san-pedro",
            "geometry": {"type": "LineString", "coordinates": [[-4.0083, 5.2512], [-6.6368, 4.7446]]},
            "properties": {"name": "Couloir Abidjan / San-Pedro", "tone": "maritime"},
        },
        {
            "type": "Feature",
            "id": "maritime-route-gulf-watch",
            "geometry": {"type": "LineString", "coordinates": [[-4.0083, 5.2512], [-3.9, 5.8]]},
            "properties": {"name": "Veille Golfe de Guinee", "tone": "maritime"},
        },
    ]
    return {
        "maritime_points": {"type": "FeatureCollection", "features": [*port_features, *event_features]},
        "maritime_routes": {"type": "FeatureCollection", "features": route_features},
    }


def _zone_map_focus(mapped: dict[str, Any], zone_id: Optional[str]) -> dict[str, Any]:
    map_system = mapped.get("map_system") or {}
    presets = map_system.get("camera_presets") or {}
    camera = _clone(presets.get(zone_id or "") or presets.get("country") or {})
    if camera:
        camera["duration_ms"] = min(220, int(camera.get("duration_ms") or 220))
    return {
        "selected_zone": zone_id,
        "basemap": "administrative",
        "active_layers": ["territorial-risk", "open-intelligence", "visual-streams"],
        "camera": camera,
    }


def _zone_popup_brief(zone: dict[str, Any], mapped: dict[str, Any]) -> dict[str, Any]:
    score = int(zone.get("level") or (zone.get("score") or {}).get("score") or 0)
    drivers = list(zone.get("drivers") or zone.get("signals") or [])[:3]
    recommendations = list(zone.get("recommendations") or [])
    deadline = "15:00" if zone.get("id") == "zone-nord" else "aujourd'hui"
    return {
        "title": f"{zone.get('name') or 'Zone'} · brief operationnel",
        "score": score,
        "severity": _signal_level(score),
        "drivers": drivers or ["Signal territorial a qualifier", "Lecture presse a rapprocher", "Validation humaine requise"],
        "sources": list(zone.get("sources") or [])[:4],
        "recommendation": recommendations[0] if recommendations else "Qualifier la zone puis preparer une option d'arbitrage.",
        "decision_deadline": deadline,
        "cta": "Preparer arbitrage",
        "aya_context": {
            "prompt": f"AYA, donne-moi le brief operationnel pour la zone {zone.get('name') or 'prioritaire'}.",
            "answer_frame": "Situation, preuve disponible, option recommandee, deadline et niveau de confiance.",
            "confidence": 0.72 if score >= 55 else 0.62,
        },
        "map_focus": _zone_map_focus(mapped, zone.get("id")),
    }


def _enriched_monitor_zones(mapped: dict[str, Any]) -> list[dict[str, Any]]:
    zones = _clone(mapped.get("zones") or [])
    for zone in zones:
        zone["popup_brief"] = _zone_popup_brief(zone, mapped)
    return zones


def _signal_deadline(row: dict[str, Any]) -> str:
    signal_id = str(row.get("id") or row.get("type") or "")
    if signal_id in {"scenario-composite", "territorial-risk"}:
        return "15:00"
    if signal_id in {"press-escalation", "social-rumor-origin"}:
        return "14:00"
    if signal_id == "visual-activity":
        return "avant prochain point cabinet"
    if signal_id == "maritime-customs-watch":
        return "12:00"
    if signal_id == "agenda-pressure":
        return "avant prochain rendez-vous"
    return "aujourd'hui"


def _signal_evidence_refs(row: dict[str, Any], mapped: dict[str, Any], news: dict[str, Any], visual: dict[str, Any]) -> list[dict[str, Any]]:
    signal_id = str(row.get("id") or "")
    top_zone = ((mapped.get("score_summary") or {}).get("top_zone") or {})
    alerts = news.get("executive_alerts") or news.get("signals") or []
    sources = visual.get("sources") or []
    primary_source = sources[0] if sources else {}
    maritime = news.get("maritime_intelligence") or {}
    if signal_id == "visual-activity":
        return [
            {"type": "webcam", "id": primary_source.get("id"), "label": primary_source.get("name") or "Flux visuel actif"},
            {"type": "observation", "id": (visual.get("latest_observation") or {}).get("id"), "label": "Lecture snapshot"},
        ]
    if signal_id == "maritime-customs-watch":
        latest = maritime.get("latest_observation") or {}
        return latest.get("evidence_refs") or [
            {"type": "rss", "id": "src-maritime-paa-001", "label": "RSS Port Autonome d'Abidjan"},
            {"type": "rss", "id": "src-maritime-marinelink-001", "label": "MarineLink Maritime News"},
            {"type": "source", "id": "src-marinetraffic-context-001", "label": "MarineTraffic AIS/API-ready"},
        ]
    if signal_id in {"press-escalation", "social-rumor-origin"}:
        return [
            {"type": "article", "id": alert.get("id"), "label": alert.get("title"), "geo_tier": alert.get("geo_tier") or alert.get("geography_tier")}
            for alert in alerts[:3]
        ]
    if signal_id == "agenda-pressure":
        return [{"type": "calendar", "id": "government-calendar", "label": "Agenda institutionnel"}]
    return [
        {"type": "zone", "id": top_zone.get("id") or row.get("related_zone"), "label": top_zone.get("name") or "Zone prioritaire"},
        {"type": "signal", "id": signal_id, "label": row.get("label")},
    ]


def _signal_aya_context(row: dict[str, Any], deadline: str) -> dict[str, Any]:
    label = row.get("label") or "signal prioritaire"
    return {
        "prompt": f"AYA, explique {label} avec preuve, option recommandee et deadline.",
        "answer_frame": "Situation, preuve, option recommandee, deadline, confiance.",
        "decision_deadline": deadline,
        "confidence": round(min(0.9, max(0.52, int(row.get("score") or 0) / 100)), 2),
    }


def _visual_map_focus(visual: dict[str, Any], mapped: dict[str, Any]) -> dict[str, Any]:
    sources = visual.get("sources") or []
    source = next((item for item in sources if item.get("enabled") and item.get("status") == "active"), None) or (sources[0] if sources else {})
    metadata = source.get("metadata") or {}
    location = metadata.get("map_location") or metadata.get("location") or {}
    longitude = location.get("longitude") or metadata.get("longitude")
    latitude = location.get("latitude") or metadata.get("latitude")
    if longitude is None or latitude is None:
        return _zone_map_focus(mapped, metadata.get("zone_id"))
    return {
        "selected_zone": location.get("zone_id") or metadata.get("zone_id"),
        "basemap": "administrative",
        "active_layers": ["territorial-risk", "open-intelligence", "visual-streams"],
        "camera": {
            "longitude": longitude,
            "latitude": latitude,
            "zoom": location.get("zoom") or metadata.get("map_zoom") or 10.9,
            "duration_ms": 220,
        },
        "focus_marker": {
            "longitude": longitude,
            "latitude": latitude,
            "label": location.get("label") or metadata.get("camera_label") or source.get("name") or "Flux visuel",
            "zone_id": location.get("zone_id") or metadata.get("zone_id"),
            "tone": "visual",
        },
    }


def _maritime_map_focus(news: dict[str, Any]) -> dict[str, Any]:
    maritime = news.get("maritime_intelligence") or {}
    return (maritime.get("active_evidence") or {}).get("map_focus") or {
        "selected_zone": "zone-sud",
        "basemap": "administrative",
        "active_layers": ["territorial-risk", "open-intelligence", "visual-streams", "maritime-traffic"],
        "camera": {"longitude": -4.0083, "latitude": 5.2512, "zoom": 9.15, "duration_ms": 220},
        "focus_marker": {
            "longitude": -4.0083,
            "latitude": 5.2512,
            "label": "Port d'Abidjan · surveillance maritime",
            "zone_id": "zone-sud",
            "tone": "maritime",
        },
    }


def _enrich_cross_source_signal(row: dict[str, Any], mapped: dict[str, Any], news: dict[str, Any], visual: dict[str, Any]) -> dict[str, Any]:
    enriched = _clone(row)
    deadline = _signal_deadline(enriched)
    enriched["decision_deadline"] = deadline
    enriched["evidence_refs"] = _signal_evidence_refs(enriched, mapped, news, visual)
    enriched["aya_context"] = _signal_aya_context(enriched, deadline)
    if enriched.get("id") == "visual-activity":
        enriched["map_focus"] = _visual_map_focus(visual, mapped)
    elif enriched.get("id") == "maritime-customs-watch":
        enriched["map_focus"] = _maritime_map_focus(news)
    else:
        enriched["map_focus"] = _zone_map_focus(mapped, enriched.get("related_zone"))
    return enriched


def _active_evidence_payload(
    scenario: dict[str, Any],
    cross_source_signals: list[dict[str, Any]],
    visual_intelligence_brief: dict[str, Any],
) -> dict[str, Any]:
    signal = cross_source_signals[0] if cross_source_signals else {}
    return {
        "id": f"active-{signal.get('id') or scenario.get('id') or 'evidence'}",
        "type": signal.get("type") or "scenario",
        "title": signal.get("label") or scenario.get("title") or "Preuve active",
        "location": scenario.get("focus_zone") or "Cote d'Ivoire",
        "score": int(signal.get("score") or scenario.get("score") or 0),
        "severity": signal.get("severity") or scenario.get("level") or "monitoring",
        "source_quality": (visual_intelligence_brief.get("source_quality") or {}).get("label") or "Sources qualifiees",
        "observation": signal.get("summary") or scenario.get("summary"),
        "recommended_action": signal.get("action_prompt") or (scenario.get("recommended_actions") or ["Qualifier la preuve puis arbitrer."])[0],
        "decision_deadline": signal.get("decision_deadline") or "aujourd'hui",
        "evidence_refs": signal.get("evidence_refs") or [],
        "aya_context": signal.get("aya_context") or {},
        "map_focus": signal.get("map_focus") or scenario.get("map_focus"),
    }


def _worldmonitor_principles_payload() -> dict[str, Any]:
    return {
        "map_dominant": True,
        "compact_layers": ["territorial-risk", "open-intelligence", "visual-streams", "maritime-traffic"],
        "evidence_popup": True,
        "live_docks": "reduced",
        "decision_contract": "que faire, quand, avec quelle preuve",
        "sentinel_difference": "moins de couches, plus d'arbitrage cabinet",
    }


def _cross_source_signals(
    mapped: dict[str, Any],
    news: dict[str, Any],
    visual: dict[str, Any],
    *,
    calendar_summary: Optional[dict[str, Any]],
    action_summary: Optional[dict[str, Any]],
    action_items: list[dict[str, Any]],
    maritime: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    top_zone = ((mapped.get("score_summary") or {}).get("top_zone") or {})
    zone_score = int(top_zone.get("level") or top_zone.get("score", {}).get("score") or 0)
    alerts = news.get("executive_alerts") or news.get("signals") or []
    high_risk = int((news.get("source_health") or {}).get("high_risk") or 0)
    press_score = min(100, high_risk * 24 + len(alerts[:3]) * 7)
    visual_score = int((visual.get("posture") or {}).get("score") or 0)
    latest_observation = visual.get("latest_observation") or {}
    maritime_payload = maritime or news.get("maritime_intelligence") or {}
    maritime_observation = maritime_payload.get("latest_observation") or {}
    maritime_score = int(maritime_observation.get("score") or 0)
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
            "id": "maritime-customs-watch",
            "type": "maritime",
            "label": "Maritime / douanes",
            "summary": maritime_observation.get("summary") or "Port d'Abidjan, San-Pedro et Golfe de Guinee disponibles comme preuve maritime corrélée.",
            "severity": _signal_level(maritime_score),
            "score": maritime_score,
            "source_keys": ["maritime_intelligence", "port_abidjan_rss", "marinetraffic_context"],
            "related_zone": "zone-sud",
            "action_prompt": maritime_observation.get("recommended_action") or "Verifier Port + Douanes puis preparer une note Vice Premier Ministre si le signal se confirme.",
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
    ranked = sorted(rows, key=lambda item: int(item["score"]), reverse=True)
    return [_enrich_cross_source_signal(row, mapped, news, visual) for row in ranked]


def _visual_intelligence_brief(
    visual: dict[str, Any],
    news: dict[str, Any],
    mapped: dict[str, Any],
    *,
    calendar_summary: Optional[dict[str, Any]],
    cross_source_signals: list[dict[str, Any]],
) -> dict[str, Any]:
    sources = visual.get("sources") or []
    active_sources = [source for source in sources if source.get("enabled") and source.get("status") == "active"]
    primary_source = active_sources[0] if active_sources else (sources[0] if sources else {})
    metadata = primary_source.get("metadata") or {}
    latest = visual.get("latest_observation") or {}
    top_zone = ((mapped.get("score_summary") or {}).get("top_zone") or {})
    alerts = news.get("executive_alerts") or news.get("signals") or []
    high_risk = int((news.get("source_health") or {}).get("high_risk") or 0)
    visual_signal = next((signal for signal in cross_source_signals if signal.get("id") == "visual-activity"), None)
    next_event = (calendar_summary or {}).get("next_event") or {}
    quality_label = metadata.get("resolution_label") or "Basse resolution publique"
    native_hint = metadata.get("native_resolution_hint") or "Snapshot public sous-HD ; le detail fin ne doit pas etre interprete comme preuve."
    constraints = metadata.get("analysis_constraints") or [
        "pas d'identification individuelle",
        "pas de comptage fin fiable",
        "validation humaine obligatoire",
    ]
    reading = latest.get("summary") or (
        "Aucune capture analysee recente n'est disponible ; la webcam sert de contexte visuel live et doit etre capturee avant conclusion."
    )
    latest_reading = {
        "available": bool(latest),
        "summary": reading,
        "vigilance_score": latest.get("vigilance_score") or (visual.get("posture") or {}).get("score"),
        "confidence": latest.get("confidence"),
        "provider": latest.get("provider") or "snapshot_context",
        "created_at": latest.get("created_at"),
    }
    briefing_insert = (
        f"Lecture visuelle : {reading} "
        f"Qualite source : {quality_label.lower()} ({native_hint}). "
        f"Croisement utile : {high_risk} signal(aux) presse, zone {top_zone.get('name') or 'non priorisee'}, "
        f"prochaine contrainte agenda {next_event.get('time') or 'non critique'}. "
        "AYA peut utiliser cette lecture pour contextualiser un brief, pas pour identifier des personnes ou etablir une preuve detaillee."
    )
    if not latest:
        briefing_insert = (
            "Aucune observation visuelle analysee recente n'est encore disponible. "
            f"Les webcams publiques restent exploitables comme contexte macro ({quality_label.lower()}), "
            "mais AYA doit demander une capture snapshot avant de s'appuyer dessus dans une recommandation."
        )
    return {
        "status": "ready" if active_sources else "configured",
        "question_answered": "La valeur ajoutee vient de la lecture snapshot + croisement presse/carte/agenda, pas d'une transcription audio webcam.",
        "transcription": {
            "available": False,
            "type": "visual_snapshot_analysis",
            "label": "Lecture visuelle, pas transcription audio",
            "reason": "Les sources publiques Abidjan.net/Nest exposees ici ne fournissent pas de piste audio ni de transcript fiable.",
        },
        "source_quality": {
            "label": quality_label,
            "native_resolution_hint": native_hint,
            "evidence_grade": metadata.get("evidence_grade") or "macro_context_only",
            "best_use": metadata.get("best_use") or "Contexte macro : trafic, meteo visible, densite generale.",
            "constraints": constraints,
        },
        "latest_reading": latest_reading,
        "cross_check": [
            {"label": "Presse", "value": f"{high_risk} prioritaire(s)", "detail": (alerts[0] or {}).get("title") if alerts else "Aucun signal presse prioritaire"},
            {"label": "Carte", "value": top_zone.get("name") or "Cote d'Ivoire", "detail": f"{int(top_zone.get('level') or 0)}% vigilance"},
            {"label": "Agenda", "value": next_event.get("time") or "pas de conflit", "detail": next_event.get("title") or (calendar_summary or {}).get("summary") or "Fenetre a confirmer"},
        ],
        "briefing_insert": briefing_insert,
        "aya_context": [
            "Preciser que les webcams publiques sont basse resolution et macro-contextuelles.",
            "Croiser la lecture visuelle avec presse locale, rumeurs, carte et agenda avant recommandation.",
            "Demander une capture snapshot si la question porte sur une situation terrain actuelle.",
        ],
        "recommended_next_step": (visual_signal or {}).get("action_prompt") or "Capturer un snapshot puis demander a AYA une synthese croisee.",
    }


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
        {"key": "executive-filters", "region": "left", "order": 1, "label": "Filtres executifs", "visible": True, "live": True, "count": len(layers)},
        {"key": "active-evidence", "region": "right", "order": 1, "label": "Preuve active", "visible": True, "live": True, "count": 1},
        {"key": "correlated-signals", "region": "right", "order": 2, "label": "Signaux correles", "visible": True, "live": True, "count": len(cross_source_signals)},
        {"key": "strategic-posture", "region": "right", "order": 3, "label": "Posture", "visible": True, "live": True, "count": 1},
        {"key": "aya", "region": "right", "order": 4, "label": SENTINEL_ASSISTANT_NAME, "visible": True, "live": True, "count": 5},
        {"key": "live-webcams", "region": "bottom", "order": 1, "label": "Preuve terrain webcam", "visible": True, "live": True, "count": int((visual.get("source_health") or {}).get("active_sources") or 0)},
    ]


def _aya_voice_context(
    scenario: dict[str, Any],
    cross_source_signals: list[dict[str, Any]],
    visual_intelligence_brief: Optional[dict[str, Any]] = None,
    active_evidence: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    prompts = [
        "AYA, donne-moi la synthese du scenario croise.",
        "AYA, ouvre la camera Pont General-de-Gaulle.",
        "AYA, filtre la carte sur Abidjan.",
        "AYA, quels impacts agenda aujourd'hui ?",
        "AYA, d'ou vient la rumeur prioritaire ?",
        "AYA, separe politique interieure ivoirienne et perception internationale.",
        "AYA, montre la lecture CEDEAO autour de la Cote d'Ivoire.",
        "AYA, prepare une instruction executive.",
        "AYA, quel est le risque autour du port d'Abidjan ?",
        "AYA, relie cette actualite douanes au trafic maritime.",
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
        "visual_intelligence_brief": visual_intelligence_brief or {},
        "active_evidence": active_evidence or {},
        "commands": [
            {"utterance": prompts[0], "intent": "scenario_brief", "target": scenario.get("id")},
            {"utterance": prompts[1], "intent": "visual_focus", "target": "pont-general-de-gaulle"},
            {"utterance": prompts[2], "intent": "map_focus", "target": "abidjan"},
            {"utterance": prompts[3], "intent": "agenda_impacts", "target": "today"},
            {"utterance": prompts[4], "intent": "rumor_origin", "target": "social-rumor-origin"},
            {"utterance": prompts[5], "intent": "political_viewpoint_split", "target": "news_viewpoints"},
            {"utterance": prompts[6], "intent": "regional_map_focus", "target": "regional-context"},
            {"utterance": prompts[7], "intent": "instruction_draft", "target": (cross_source_signals[0] or {}).get("id") if cross_source_signals else None},
            {"utterance": prompts[8], "intent": "maritime_port_risk", "target": "maritime-customs-watch"},
            {"utterance": prompts[9], "intent": "maritime_customs_link", "target": "maritime-customs-watch"},
        ],
        "answer_contract": {
            "required_parts": ["situation", "preuve", "option recommandee", "deadline", "confiance"],
            "default_deadline": (active_evidence or {}).get("decision_deadline") or "aujourd'hui",
        },
        "fallback": "text_chat_overlay",
    }


def timeline_payload(workspace: Workspace, db: Optional[DBSession] = None) -> dict[str, Any]:
    calendar_summary = calendar_summary_payload(db, workspace) if db else None
    action_items = [serialize_action_item(row) for row in list_action_items(db, workspace, include_cancelled=False)[:6]] if db else []
    agenda_items = _agenda_items_from_calendar(workspace, db)
    agenda_day = _agenda_day({"agenda": agenda_items}, calendar_summary)
    vp_story = _vp_story_context(agenda_day=agenda_day)
    return {
        "workspace": _workspace_meta(workspace),
        "agenda": agenda_items,
        "agenda_day": agenda_day,
        "vp_story": vp_story,
        "attention_required": vp_story["attention_required"],
        "decision_queue": vp_story["decision_queue"],
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
            SENTINEL_MARITIME_INTELLIGENCE_COLLECTION,
            SENTINEL_EVIDENCE_GRAPH_COLLECTION,
            "sentinel-ci-security-briefs",
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
    attention = next((item for item in ATTENTION_REQUIRED if item["id"] == target_id), None)
    package = next((item for item in EXECUTIVE_DECISION_PACKAGES if item["id"] == target_id), None)
    is_press_response = target_type in {"press_response", "communication_email"} or target_id in {
        "attention-inter-budget",
        "decision-press-lines",
        "package-rumeur-emoi",
    }
    title = project["name"] if project else zone["name"] if zone else (attention or package or {}).get("title", target_id)
    recipient = "Directeur de cabinet"
    subject = f"Instruction cabinet - {title}"
    if is_press_response:
        recipient = "Responsable communication"
        subject = "Projet de reponse - sequence presse budget defense"
        body = (
            "Bonjour,\n\n"
            "Merci de preparer, pour validation avant 14h00, une reponse sobre a l'article de L'Inter "
            "relatif au budget defense. Ligne recommandee : rappeler la continuite de l'action publique, "
            "la coordination interministerielle et le controle humain des arbitrages, sans amplifier la polemique.\n\n"
            "Elements a integrer :\n"
            "- aucune annonce operationnelle non validee ;\n"
            "- insister sur la protection des populations et le calendrier du Conseil de 15h00 ;\n"
            "- prevoir une formule de compassion si la rumeur sociale se confirme.\n\n"
            "AYA recommande une diffusion courte, apres verification source primaire et validation cabinet."
        )
        sources = (attention or package or {}).get("source_refs") or (attention or package or {}).get("sources") or ["src-press-ci-local-001"]
    elif project:
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
        "title": subject,
        "recipient": recipient,
        "subject": subject,
        "body": body,
        "sources": sources,
        "deadline": "14:00" if is_press_response else "15:00" if zone else "24h",
        "control": {
            "human_authority_required": True,
            "external_delivery": "requires_human_validation",
            "audit": "recorded",
            "channel": "email_draft" if is_press_response else "cabinet_instruction",
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
    source = "octocity" if is_octocity_mission_room(workspace) else "sentinel-ci"
    existing = (
        db.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == workspace.id, KnowledgeCollection.slug == slug)
        .first()
    )
    if existing:
        existing.name = name
        existing.description = description
        existing.chunking_params = {**(existing.chunking_params or {}), "demo": True, "source": source}
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
            chunking_params={"demo": True, "source": source},
        )
    )


def _ensure_sentinel_knowledge_guides(db: DBSession, workspace: Workspace) -> int:
    """Seed workspace-scoped Knowledge Guides without rewriting history."""
    changed = 0
    now = datetime.utcnow()
    for spec in SENTINEL_KNOWLEDGE_GUIDES:
        current = (
            db.query(KnowledgeGuide)
            .filter(
                KnowledgeGuide.workspace_id == workspace.id,
                KnowledgeGuide.guide_key == spec["guide_key"],
                KnowledgeGuide.is_current.is_(True),
            )
            .first()
        )
        if (
            current
            and current.target_type == spec["target_type"]
            and current.target_ref == spec["target_ref"]
            and current.title == spec["title"]
            and current.markdown == spec["markdown"]
            and current.status == "published"
        ):
            continue
        version = 1
        supersedes_id = None
        if current:
            current.is_current = False
            db.add(current)
            version = int(current.version or 1) + 1
            supersedes_id = current.id
        db.add(
            KnowledgeGuide(
                id=str(uuid4()),
                guide_key=spec["guide_key"],
                workspace_id=workspace.id,
                target_type=spec["target_type"],
                target_ref=spec["target_ref"],
                title=spec["title"],
                markdown=spec["markdown"],
                status="published",
                version=version,
                is_current=True,
                supersedes_id=supersedes_id,
                created_by_user_id=None,
                created_at=now,
                published_at=now,
            )
        )
        changed += 1
    return changed


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


def _cleanup_sentinel_demo_artifacts(db: DBSession, workspace: Workspace) -> int:
    """Hide ad hoc QA artifacts from executive Sentinel surfaces."""
    from app.models.action_plan import WorkspaceActionItem
    from app.models.calendar import WorkspaceCalendarEvent

    cleaned = 0
    for pattern in ("%agenda qa wiring%", "%qa wiring%", "%codex qa%"):
        rows = (
            db.query(WorkspaceCalendarEvent)
            .filter(
                WorkspaceCalendarEvent.workspace_id == workspace.id,
                WorkspaceCalendarEvent.status != "cancelled",
                WorkspaceCalendarEvent.title.ilike(pattern),
            )
            .all()
        )
        for row in rows:
            row.status = "cancelled"
            row.updated_at = datetime.utcnow()
            row.meta_data = {**(row.meta_data or {}), "hidden_by_demo_clean": True}
            cleaned += 1

    for pattern in (
        "action cabinet ajoutee%",
        "action cabinet ajoutée%",
        "aya, action cabinet%",
        "%resume les prochaines etapes%",
        "%résume les prochaines étapes%",
    ):
        rows = (
            db.query(WorkspaceActionItem)
            .filter(
                WorkspaceActionItem.workspace_id == workspace.id,
                WorkspaceActionItem.status != "cancelled",
                WorkspaceActionItem.title.ilike(pattern),
            )
            .all()
        )
        for row in rows:
            row.status = "cancelled"
            row.updated_at = datetime.utcnow()
            row.meta_data = {**(row.meta_data or {}), "hidden_by_demo_clean": True}
            cleaned += 1
    return cleaned


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
        "Port d'Abidjan",
        "San-Pedro",
        "douanes",
        "maritime",
        "AIS",
        "congestion portuaire",
        "presidence",
        "vice-premier-ministre",
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
        "ragVectorDBType": "qdrant",
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


def _flow(slug: str, skill_slugs: list[str], label: str, *, template_prefix: str = "sentinel-ci") -> dict[str, Any]:
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
        "template_id": f"{template_prefix}-{slug}",
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
    template_prefix: str = "sentinel-ci",
    created_by: str = "system:sentinel_ci_seed",
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
    flow = _flow(variant, skill_slugs, name, template_prefix=template_prefix)
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
        created_by=created_by,
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
            "demo_time_context": demo_time_context_defaults(),
            "action_planner": {
                "write_policy": "direct",
                "default_owner": "Cabinet",
                "advisory_only": True,
            },
            "actions": {
                "enabled_packs": [
                    "global_voice_v1",
                    "sentinel_ci_aya_v1",
                    "sentinel_ci_aya_security_v1",
                ],
                "confirmation_policy": "confirm_side_effects",
                "legacy_adapters": ["aya_action_plans"],
            },
            "voice_loop": {
                "default_mode": "session_loop",
                "enabled_default": False,
                "manual_start_required": True,
                "auto_send_final_transcript": True,
                "auto_endpoint": True,
                "auto_rearm_after_tts": True,
                "barge_in": True,
                "commands_enabled": True,
                "command_packs": [
                    "global_voice_v1",
                    "sentinel_ci_aya_v1",
                    "sentinel_ci_aya_security_v1",
                ],
                "trigger_word": "AYA",
                "stop_phrases": ["stop", "pause", "on peut s'arreter la", "annule", "arrete"],
                "silence_ms": 1050,
                "min_speech_ms": 320,
                "max_turn_ms": 45000,
                "cooldown_ms": 450,
            },
            "voice_output": {
                "latency_profile": "fast",
                "voice": "nova",
                "flush_first_chars": 18,
                "flush_next_chars": 56,
                "flush_timeout_ms": 450,
                "interrupt_on_user_speech": True,
            },
            "document_intelligence": {
                "enabled": True,
                "default_profile": "sentinel_ci_ministerial",
                "profiles": [
                    {
                        "key": "sentinel_ci_ministerial",
                        "label": "SENTINEL-CI ministerial documents",
                        "synonyms": {
                            "briefing": ["note cabinet", "fiche", "brief", "elements de langage"],
                            "decision": ["arbitrage", "instruction", "validation", "deadline"],
                            "territory": ["zone", "region", "district", "frontiere", "port"],
                        },
                        "max_candidate_facts": 1800,
                        "max_evidence_rows": 18,
                    }
                ],
                "ocr": {
                    "enabled": True,
                    "provider_priority": ["tesseract_local", "ppocr_service"],
                    "languages": ["fra", "eng"],
                    "min_confidence": 0.45,
                    "timeout_seconds": 20,
                    "required": False,
                    "openai_vision_enabled": False,
                },
                "citation_policy": "raw_source_first_page_section_paragraph",
            },
            "visual_intelligence": {
                "enabled": True,
                "capture_cadence_minutes": 60,
                "allowed_adapters": ["demo_static", "http_image", "browser_screenshot"],
                "storage_policy": "snapshot_only_no_continuous_recording",
                "analysis_policy": "no_identification_no_biometrics",
                "source_model": "live_webcam_embed_layer",
            },
            "feature_flag": {
                "security_live_osint": False,
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
                        SENTINEL_MARITIME_INTELLIGENCE_COLLECTION,
                        SENTINEL_EVIDENCE_GRAPH_COLLECTION,
                        "sentinel-ci-security-briefs",
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
                    "grounding": {
                        "default_mode": "balanced",
                        "allowed_modes": ["strict", "balanced"],
                        "fallback_disclaimer": "Je n'ai pas de source workspace sur ce point ; analyse générale à valider :",
                        "strict_guard": "default",
                    },
                    "actions": {
                        "enabled_packs": [
                            "global_voice_v1",
                            "sentinel_ci_aya_v1",
                            "sentinel_ci_aya_security_v1",
                        ],
                        "confirmation_policy": "confirm_side_effects",
                    },
                    "voice_loop": {
                        "default_mode": "session_loop",
                        "enabled_default": False,
                        "manual_start_required": True,
                        "auto_send_final_transcript": True,
                        "auto_endpoint": True,
                        "auto_rearm_after_tts": True,
                        "barge_in": True,
                        "commands_enabled": True,
                        "command_packs": [
                            "global_voice_v1",
                            "sentinel_ci_aya_v1",
                            "sentinel_ci_aya_security_v1",
                        ],
                    },
                    "voice_output": {
                        "latency_profile": "fast",
                        "voice": "nova",
                        "flush_first_chars": 18,
                        "flush_next_chars": 56,
                        "flush_timeout_ms": 450,
                        "interrupt_on_user_speech": True,
                    },
                    "response_style": {
                        "address_as": "Monsieur le Vice Premier Ministre",
                        "tone": "formel",
                        "format": "brief_gouvernemental_court",
                        "max_bullets": 4,
                    },
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
                        "focus_evidence_graph",
                        "rank_decision_options",
                        "draft_response_email",
                        "read_maritime_snapshot",
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

    # Workspace bootstrap must never grant IAM access implicitly. SENTINEL-CI is
    # seeded as a portable demo workspace, while memberships are managed through
    # the normal invite/admin flow so newly-created platform users cannot leak
    # into the workspace on a later seed run.
    members_added = 0

    for slug, name, description in (
        ("sentinel-ci-ministerial-briefs", "SENTINEL-CI Ministerial Briefs", "Briefings, agenda syntheses and validated talking points."),
        ("sentinel-ci-open-intelligence", "SENTINEL-CI Open Intelligence", "Public news and weak-signal summaries for ministerial watch."),
        ("sentinel-ci-projects", "SENTINEL-CI Strategic Projects", "Strategic project records and decision-support risk explanations."),
        ("sentinel-ci-territorial-map", "SENTINEL-CI Territorial Map", "Territorial zones, signals and non-military action recommendations."),
        ("sentinel-ci-territorial-intelligence", "SENTINEL-CI Territorial Intelligence", "Fused territorial scores from news, projects, agenda, visual observations and recommended action windows."),
        ("sentinel-ci-visual-intelligence", "SENTINEL-CI Visual Intelligence", "Visual snapshots and observations from authorized workspace streams."),
        (SENTINEL_MARITIME_INTELLIGENCE_COLLECTION, "SENTINEL-CI Maritime Intelligence", "Port, customs and Gulf of Guinea signals used by AYA for executive briefings."),
        (SENTINEL_EVIDENCE_GRAPH_COLLECTION, "SENTINEL-CI Evidence Graph", "Entities, rumors, sources, locations, projects and decisions connected for AYA."),
        ("sentinel-ci-security-briefs", "SENTINEL-CI Security Briefs", "Security posture briefs, Sahel OSINT notes, defense council syntheses and rumor dossiers used by AYA S3 actions."),
    ):
        _ensure_collection(db, workspace, slug, name, description)
    knowledge_guides_changed = _ensure_sentinel_knowledge_guides(db, workspace)

    for name, url, category in SENTINEL_NEWS_FEEDS:
        _ensure_feed(db, workspace, name, url, category)
    _ensure_target(db, workspace)
    _ensure_filter(db, workspace)
    _ensure_rag_preset(db, workspace)
    ensure_calendar_seed(db, workspace)
    ensure_action_plan_seed(db, workspace)
    cleaned_demo_artifacts = _cleanup_sentinel_demo_artifacts(db, workspace)

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
                "source_registry_refresh_v1",
                "osint_signal_prioritize_v1",
                "rumor_origin_trace_v1",
                "evidence_graph_build_v1",
                "situation_posture_score_v1",
                "maritime_snapshot_read_v1",
                "decision_option_rank_v1",
                "draft_response_email_v1",
                "voice_tandem_oracle_v1",
                "audit_log_v1",
            ],
            "variant": "government_mission_room",
        },
        {
            "name": "Briefing Quotidien Vice Premier Ministre",
            "objective": "Produire un briefing sourcé : priorites, risques, decisions attendues, actions et elements de langage.",
            "capability_slug": "ministerial_daily_briefing",
            "skill_slugs": ["ministerial_briefing_v1", "calendar_daily_summary_v1", "action_plan_status_v1", "llm_rag_answer_v1", "audit_log_v1"],
            "variant": "ministerial_daily_briefing",
        },
        {
            "name": "Veille Presse & Signaux Faibles",
            "objective": "Agreger presse ivoirienne, CEDEAO, internationale et signaux publics de rumeurs pour detecter les sujets sensibles avant escalation.",
            "capability_slug": "open_intelligence_watch",
            "skill_slugs": ["intelligence_batch_v1", "news_signal_synthesis_v1", "source_registry_refresh_v1", "osint_signal_prioritize_v1", "rumor_origin_trace_v1", "audit_log_v1"],
            "variant": "intelligence",
            "execution_mode": "continuous_monitoring",
        },
        {
            "name": "OSINT & Rumor Intelligence",
            "objective": "Qualifier les signaux OSINT, rumeurs publiques, origines, propagation et priorite geographique Cote d'Ivoire / CEDEAO / Afrique / Monde.",
            "capability_slug": "osint_rumor_intelligence",
            "skill_slugs": ["intelligence_batch_v1", "source_registry_refresh_v1", "osint_signal_prioritize_v1", "rumor_origin_trace_v1", "news_signal_synthesis_v1", "audit_log_v1"],
            "variant": "osint_rumor_intelligence",
            "execution_mode": "continuous_monitoring",
        },
        {
            "name": "Evidence Graph",
            "objective": "Relier sources, entites, lieux, projets, rumeurs, agenda et actions pour les reponses sourcées d'AYA.",
            "capability_slug": "evidence_graph",
            "skill_slugs": ["evidence_graph_build_v1", "semantic_search_v1", "chain_mixed_hah_v1", "audit_log_v1"],
            "variant": "evidence_graph",
        },
        {
            "name": "Maritime & Customs Watch",
            "objective": "Suivre Abidjan, San Pedro, douanes et routes Golfe de Guinee pour anticiper impacts economiques et projets.",
            "capability_slug": "maritime_customs_watch",
            "skill_slugs": ["maritime_snapshot_read_v1", "map_layer_read_v1", "osint_signal_prioritize_v1", "situation_posture_score_v1", "audit_log_v1"],
            "variant": "maritime_customs_watch",
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
                "situation_posture_score_v1",
                "decision_option_rank_v1",
                "chain_mixed_hah_v1",
                "voice_tandem_oracle_v1",
                "audit_log_v1",
            ],
            "variant": "scenario_fusion_monitor",
            "execution_mode": "continuous_monitoring",
        },
        {
            "name": "Strategic Forecasts",
            "objective": "Produire des previsions courtes et options comparees en cout, impact, confiance et fenetres de decision.",
            "capability_slug": "strategic_forecasts",
            "skill_slugs": ["situation_posture_score_v1", "scenario_generate_v1", "scenario_compare_v1", "scenario_recommend_v1", "decision_option_rank_v1", "audit_log_v1"],
            "variant": "strategic_forecasts",
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
            "skill_slugs": [
                "territorial_signal_map_v1",
                "territorial_action_window_v1",
                "map_layer_read_v1",
                "map_zone_score_v1",
                "map_signal_attach_v1",
                "map_recommendation_generate_v1",
                "map_command_apply_v1",
                "situation_posture_score_v1",
                "maritime_snapshot_read_v1",
                "chain_mixed_hah_v1",
                "audit_log_v1",
            ],
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
            "name": "Decision Desk",
            "objective": "Classer les options, preparer brouillons email/actions et maintenir la validation humaine.",
            "capability_slug": "decision_desk",
            "skill_slugs": ["decision_option_rank_v1", "draft_response_email_v1", "instruction_draft_v1", "action_plan_create_v1", "action_plan_status_v1", "audit_log_v1"],
            "variant": "decision_desk",
        },
        {
            "name": "Instructions Cabinet",
            "objective": "Rediger des brouillons d'instruction sources et soumis a validation humaine.",
            "capability_slug": "executive_instruction_drafting",
            "skill_slugs": ["instruction_draft_v1", "draft_response_email_v1", "decision_option_rank_v1", "claim_audit_v1", "audit_log_v1"],
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
        "demo_artifacts_cleaned": cleaned_demo_artifacts,
        "knowledge_guides_changed": knowledge_guides_changed,
    }


OCTOCITY_COLLECTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "octocity-ministerial-briefs",
        "Octocity Mission Briefs",
        "Synthetic institutional briefings, agenda notes and validated language for OCTAVE.",
    ),
    (
        "octocity-open-intelligence",
        "Octocity Open Intelligence",
        "Demo-safe public signals, press syntheses and weak-signal monitoring for Octocity.",
    ),
    (
        "octocity-projects",
        "Octocity Strategic Projects",
        "Synthetic civic project records and decision-support risk explanations.",
    ),
    (
        "octocity-territorial-map",
        "Octocity Territorial Map",
        "Fictive regions, corridor signals and non-military action recommendations.",
    ),
    (
        "octocity-knowledge-capture",
        "Octocity Knowledge Capture Corpus",
        "Source inventory used by Knowledge Capture for synthetic expert interviews.",
    ),
    (
        "octocity-evidence-graph",
        "Octocity Evidence Graph",
        "Entities, sources, locations, decisions and risks connected for OCTAVE.",
    ),
)


def _octocity_collection_sources() -> dict[str, list[tuple[str, int]]]:
    return {
        "octocity-ministerial-briefs": [
            ("octocity-civic-brief-2026-05-25.md", 18),
            ("octocity-agenda-synthesis-2026-05-25.md", 12),
            ("octave-public-language-guide.md", 9),
        ],
        "octocity-open-intelligence": [
            ("aurora-public-signal-digest-2026-05-25.md", 16),
            ("meridian-social-pulse-snapshot.md", 11),
            ("northern-belt-rumor-trace-demo.md", 14),
        ],
        "octocity-projects": [
            ("liora-resilience-campus-project-note.md", 13),
            ("meridian-harbor-logistics-corridor.md", 15),
            ("solenne-infrastructure-risk-register.md", 10),
        ],
        "octocity-territorial-map": [
            ("asteria-territorial-map-legend.md", 10),
            ("auralis-zone-risk-reading.md", 12),
        ],
        "octocity-knowledge-capture": [
            ("octocity-expert-interview-seed.md", 8),
            ("octocity-decision-vocabulary.md", 6),
        ],
        "octocity-evidence-graph": [
            ("octocity-evidence-graph-nodes.json", 22),
            ("octocity-source-registry.json", 18),
        ],
    }


def _ensure_octocity_collection_sources(db: DBSession, workspace: Workspace) -> int:
    from app.services.knowledge_collections import upsert_collection_source

    written = 0
    for slug, source_specs in _octocity_collection_sources().items():
        collection = (
            db.query(KnowledgeCollection)
            .filter(KnowledgeCollection.workspace_id == workspace.id, KnowledgeCollection.slug == slug)
            .first()
        )
        if not collection:
            continue
        names: list[str] = []
        chunks = 0
        for filename, chunk_count in source_specs:
            names.append(filename)
            chunks += chunk_count
            upsert_collection_source(
                db,
                collection=collection,
                filename=filename,
                status="ready",
                origin="seed",
                chunk_count=chunk_count,
                source_metadata={
                    "demo": True,
                    "workspace_profile": OCTOCITY_MISSION_ROOM_PROFILE,
                    "source_profile": "synthetic_institutional_demo",
                },
                replace_source_metadata=True,
            )
            written += 1
        collection.status = "ready"
        collection.document_names = names
        collection.document_count = len(names)
        collection.chunk_count = chunks
    return written


def _octocity_guide_specs(workspace: Workspace) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for guide in SENTINEL_KNOWLEDGE_GUIDES:
        spec = present_payload_for_workspace(workspace, _clone(guide))
        if spec.get("target_type") == "scope" and spec.get("target_ref") == "vigie":
            spec["target_ref"] = "octocity_vigie"
        if isinstance(spec.get("guide_key"), str):
            spec["guide_key"] = spec["guide_key"].replace("vigie", "octocity-vigie")
        specs.append(spec)
    specs.append(
        {
            "guide_key": "octocity-knowledge-capture-v1",
            "target_type": "collection",
            "target_ref": "octocity-knowledge-capture",
            "title": "Guide OCTAVE - Knowledge Capture",
            "markdown": """# Guide OCTAVE - Knowledge Capture

OCTAVE conduit les entretiens de capture de connaissance dans un univers fictif. Les questions doivent rester concretes, institutionnelles et sourcees par les documents Octocity.

Regles :
- Reformuler chaque reponse en fait reutilisable, avec source ou incertitude explicite.
- Distinguer decision, signal, hypothese, action proposee et preuve.
- Ne jamais reintroduire de pays, ville, institution ou filiere reelle issue du workspace d'origine.
- Produire des propositions advisory only, relues par un humain avant publication.
""",
        }
    )
    return specs


def _ensure_octocity_knowledge_guides(db: DBSession, workspace: Workspace) -> int:
    changed = 0
    now = datetime.utcnow()
    for spec in _octocity_guide_specs(workspace):
        current = (
            db.query(KnowledgeGuide)
            .filter(
                KnowledgeGuide.workspace_id == workspace.id,
                KnowledgeGuide.guide_key == spec["guide_key"],
                KnowledgeGuide.is_current.is_(True),
            )
            .first()
        )
        if (
            current
            and current.target_type == spec["target_type"]
            and current.target_ref == spec["target_ref"]
            and current.title == spec["title"]
            and current.markdown == spec["markdown"]
            and current.status == "published"
        ):
            continue
        version = 1
        supersedes_id = None
        if current:
            current.is_current = False
            db.add(current)
            version = int(current.version or 1) + 1
            supersedes_id = current.id
        db.add(
            KnowledgeGuide(
                id=str(uuid4()),
                guide_key=spec["guide_key"],
                workspace_id=workspace.id,
                target_type=spec["target_type"],
                target_ref=spec["target_ref"],
                title=spec["title"],
                markdown=spec["markdown"],
                status="published",
                version=version,
                is_current=True,
                supersedes_id=supersedes_id,
                created_by_user_id=None,
                created_at=now,
                published_at=now,
            )
        )
        changed += 1
    return changed


def _ensure_octocity_filter(db: DBSession, workspace: Workspace) -> None:
    name = "Octocity demo safety"
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
                "Allow fictional institutional briefings, demo-safe public-signal summaries and advisory recommendations."
            ),
            severity="flag",
            active=True,
        )
    )


def _ensure_octocity_rag_preset(db: DBSession, workspace: Workspace) -> None:
    name = "Octocity C-HAH briefing preset"
    config = {
        "mode": "chah",
        "ragPipelineMode": "chah",
        "rag_pipeline_mode": "chah",
        "ragVectorDBType": "qdrant",
        "ragCollectionName": "octocity-open-intelligence",
        "topK": 6,
        "ragTopK": 6,
        "promptType": "executive_briefing",
        "asyncRetrieval": True,
        "sourcePolicy": "sources_required",
        "experience": {"demoSafeProviderLabels": True, "advisoryOnly": True},
    }
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


def _octocity_settings() -> dict[str, Any]:
    action_packs = ["global_voice_v1", "octave_mission_room_v1", "octave_security_v1"]
    return {
        "family": "generic",
        "demo_profile": "octocity_mission_room",
        "default_route": MISSION_ROOM_ROUTE,
        "hide_provider_details": True,
        "workspace_app_shell": "immersive",
        "workspace_app_label": OCTOCITY_WORKSPACE_NAME,
        "workspace_app_default_view": "cockpit",
        "workspace_app_brand": {
            "label": OCTOCITY_WORKSPACE_NAME,
            "lines": ["AGENTIUM", "MISSION ROOM"],
            "emblem": "/assets/brand/agentium-mark.svg",
            "style": "agentium",
            "accent": "cyan",
        },
        "calendar": {
            "mode": "internal_shared",
            "connector_id": "institutional_calendar",
            "connector_label": "Agenda institutionnel",
            "write_policy": "direct",
            "timezone": "UTC",
        },
        "demo_time_context": demo_time_context_defaults(),
        "action_planner": {
            "write_policy": "direct",
            "default_owner": "Coordination",
            "advisory_only": True,
        },
        "actions": {
            "enabled_packs": action_packs,
            "confirmation_policy": "confirm_side_effects",
            "legacy_adapters": ["octave_action_plans"],
        },
        "voice_loop": {
            "default_mode": "session_loop",
            "enabled_default": False,
            "manual_start_required": True,
            "auto_send_final_transcript": True,
            "auto_endpoint": True,
            "auto_rearm_after_tts": True,
            "barge_in": True,
            "commands_enabled": True,
            "command_packs": action_packs,
            "trigger_word": OCTOCITY_ASSISTANT_NAME,
            "stop_phrases": ["stop", "pause", "on peut s'arreter la", "annule", "arrete"],
            "silence_ms": 1050,
            "min_speech_ms": 320,
            "max_turn_ms": 45000,
            "cooldown_ms": 450,
        },
        "voice_output": {
            "latency_profile": "fast",
            "voice": "nova",
            "flush_first_chars": 18,
            "flush_next_chars": 56,
            "flush_timeout_ms": 450,
            "interrupt_on_user_speech": True,
        },
        "document_intelligence": {
            "enabled": True,
            "default_profile": "octocity_institutional",
            "profiles": [
                {
                    "key": "octocity_institutional",
                    "label": "Octocity institutional documents",
                    "synonyms": {
                        "briefing": ["note coordination", "fiche", "brief", "elements de langage"],
                        "decision": ["arbitrage", "instruction", "validation", "deadline"],
                        "territory": ["zone", "region", "corridor", "port", "district"],
                    },
                    "max_candidate_facts": 1800,
                    "max_evidence_rows": 18,
                }
            ],
            "ocr": {
                "enabled": True,
                "provider_priority": ["tesseract_local", "ppocr_service"],
                "languages": ["fra", "eng"],
                "min_confidence": 0.45,
                "timeout_seconds": 20,
                "required": False,
                "openai_vision_enabled": False,
            },
            "citation_policy": "raw_source_first_page_section_paragraph",
        },
        "visual_intelligence": {
            "enabled": True,
            "capture_cadence_minutes": 60,
            "allowed_adapters": ["demo_static", "http_image", "browser_screenshot"],
            "storage_policy": "snapshot_only_no_continuous_recording",
            "analysis_policy": "no_identification_no_biometrics",
            "source_model": "live_webcam_embed_layer",
        },
        "feature_flag": {
            "security_live_osint": False,
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
        "assistant_profile_default": "octave_executive",
        "knowledge_scopes": [
            {
                "key": "octocity_vigie",
                "label": "Signals + Projects + Map",
                "description": "Synthetic institutional signals, civic projects and map data for the Octocity Mission Room.",
                "collection_slugs": [slug for slug, _, _ in OCTOCITY_COLLECTIONS],
                "default_mode": "chah",
                "top_k": 8,
                "is_default": True,
            },
            {
                "key": "octocity_capture",
                "label": "Knowledge Capture",
                "description": "Curated synthetic corpus for expert capture sessions.",
                "collection_slugs": ["octocity-knowledge-capture", "octocity-ministerial-briefs"],
                "default_mode": "chah",
                "top_k": 6,
                "is_default": False,
            },
        ],
        "assistant_profiles": [
            {
                "key": "octave_executive",
                "label": OCTOCITY_ASSISTANT_NAME,
                "subtitle": "Assistant strategique - donnees fictives",
                "default_knowledge_scope": "octocity_vigie",
                "executive_mode": True,
                "tone": "institutional",
                "grounding": {
                    "default_mode": "balanced",
                    "allowed_modes": ["strict", "balanced"],
                    "fallback_disclaimer": "Je n'ai pas de source workspace sur ce point ; analyse generale a valider :",
                    "strict_guard": "default",
                },
                "actions": {
                    "enabled_packs": action_packs,
                    "confirmation_policy": "confirm_side_effects",
                },
                "voice_loop": {
                    "default_mode": "session_loop",
                    "enabled_default": False,
                    "manual_start_required": True,
                    "auto_send_final_transcript": True,
                    "auto_endpoint": True,
                    "auto_rearm_after_tts": True,
                    "barge_in": True,
                    "commands_enabled": True,
                    "command_packs": action_packs,
                    "trigger_word": OCTOCITY_ASSISTANT_NAME,
                },
                "voice_output": {
                    "latency_profile": "fast",
                    "voice": "nova",
                    "flush_first_chars": 18,
                    "flush_next_chars": 56,
                    "flush_timeout_ms": 450,
                    "interrupt_on_user_speech": True,
                },
                "response_style": {
                    "address_as": "Madame la Directrice de Coordination",
                    "tone": "formel",
                    "format": "brief_institutionnel_court",
                    "max_bullets": 4,
                },
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
                        "label": "Synthese du jour",
                        "prompt": "Quels signaux necessitent une attention coordination aujourd'hui ?",
                    },
                    {
                        "icon": "shield-check",
                        "label": "Sources et confiance",
                        "prompt": "Quelles sources soutiennent cette alerte ?",
                    },
                    {
                        "icon": "check-circle",
                        "label": "Decision requise",
                        "prompt": "Quels arbitrages sont attendus cette semaine ?",
                    },
                    {
                        "icon": "message-square",
                        "label": "Langage public",
                        "prompt": "Prepare des elements de langage prudents et sources.",
                    },
                ],
            }
        ],
        "mission_room": {
            "enabled": True,
            "profile": OCTOCITY_MISSION_ROOM_PROFILE,
            "country": "Asteria",
            "country_code": "AS",
            "region_scope": ["Asteria", "Atlantic Arc", "Northern Belt", "Gulf of Meridian"],
            "news_source_policy": "Synthetic public fixtures first; external feeds disabled for this anonymized demo.",
            "label": OCTOCITY_ASSISTANT_NAME,
            "assistant_label": OCTOCITY_ASSISTANT_NAME,
            "brand": {
                "label": OCTOCITY_WORKSPACE_NAME,
                "lines": ["AGENTIUM", "MISSION ROOM"],
                "emblem": "/assets/brand/agentium-mark.svg",
                "style": "agentium",
            },
            "root_route": MISSION_ROOM_ROOT,
            "default_view": "cockpit",
            "navigation": NAVIGATION_ITEMS,
        },
    }


def ensure_octocity_mission_room_workspace(db: DBSession) -> dict[str, int | str]:
    """Create/update the anonymized Agentium Mission Room video workspace."""
    workspace = db.query(Workspace).filter(Workspace.slug == OCTOCITY_WORKSPACE_SLUG).first()
    created = 0
    if not workspace:
        workspace = Workspace(
            id=str(uuid4()),
            name=OCTOCITY_WORKSPACE_NAME,
            slug=OCTOCITY_WORKSPACE_SLUG,
            mode="demo",
            settings={},
        )
        db.add(workspace)
        db.flush()
        created = 1

    workspace.name = OCTOCITY_WORKSPACE_NAME
    workspace.mode = "demo"
    settings = dict(workspace.settings or {})
    settings.update(_octocity_settings())
    workspace.settings = settings
    members_added = _ensure_workspace_members(
        db,
        workspace,
        OCTOCITY_OWNER_EMAILS,
        role="owner",
        role_template="workspace_owner",
        custom_label="octocity:video-owner",
    )

    for slug, name, description in OCTOCITY_COLLECTIONS:
        _ensure_collection(db, workspace, slug, name, description)
    sources_seeded = _ensure_octocity_collection_sources(db, workspace)
    knowledge_guides_changed = _ensure_octocity_knowledge_guides(db, workspace)
    _ensure_octocity_filter(db, workspace)
    _ensure_octocity_rag_preset(db, workspace)
    ensure_calendar_seed(db, workspace)
    ensure_action_plan_seed(db, workspace)

    mission_before = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.name == "OCTAVE Mission Room")
        .count()
    )
    _ensure_system(
        db,
        workspace,
        name="OCTAVE Mission Room",
        objective="Consolider signaux, projets, carte, decisions et actions institutionnelles fictives sous controle humain.",
        capability_slug="government_mission_room",
        skill_slugs=[
            "ministerial_briefing_v1",
            "news_signal_synthesis_v1",
            "project_risk_explainer_v1",
            "territorial_signal_map_v1",
            "instruction_draft_v1",
            "calendar_daily_summary_v1",
            "action_plan_status_v1",
            "maritime_snapshot_read_v1",
            "voice_tandem_oracle_v1",
            "audit_log_v1",
        ],
        variant="octocity_mission_room",
        template_prefix="octocity",
        created_by="system:octocity_seed",
    )
    systems_created = 1 if mission_before == 0 else 0

    map_system = db.query(System).filter(System.workspace_id == workspace.id, System.name == "OCTAVE Mission Room").first()
    ensure_workspace_map_seed(db, workspace, system_id=map_system.id if map_system else None)

    from app.services.systems.bootstrap import (
        ensure_expert_capture_system_default,
        ensure_workspace_chat_system_default,
    )

    chat_before = db.query(System).filter(System.workspace_id == workspace.id, System.name == "Workspace Chat").count()
    chat_system = ensure_workspace_chat_system_default(db, workspace.id)
    if chat_system:
        chat_system.name = "Workspace Chat"
        chat_system.objective = "Provide OCTAVE workspace chat over the synthetic Octocity corpus and Mission Room actions."
        systems_created += 1 if chat_before == 0 else 0

    capture_before = db.query(System).filter(System.workspace_id == workspace.id, System.name == "Knowledge Capture").count()
    capture_system = ensure_expert_capture_system_default(db, workspace.id)
    if capture_system:
        capture_system.name = "Knowledge Capture"
        capture_system.objective = "Run guided expert interviews connected to the Octocity synthetic corpus."
        systems_created += 1 if capture_before == 0 else 0

    db.commit()
    return {
        "workspace_slug": workspace.slug,
        "workspace_created": created,
        "members_added": members_added,
        "systems_created": systems_created,
        "knowledge_guides_changed": knowledge_guides_changed,
        "collection_sources_seeded": sources_seeded,
    }
