"""The Sentinel CI institutional calendar a demo workspace is seeded with.

The calendar service seeds and shifts these events; it no longer carries them
(ADR 0003). The dates are anchored on ``SENTINEL_CALENDAR_ANCHOR_DATE`` and the
demo clock moves them to the current day.
"""

from __future__ import annotations

from datetime import date

SENTINEL_CALENDAR_ANCHOR_DATE = date(2026, 5, 25)


SENTINEL_CALENDAR_SEED = [
    {
        "id": "evt-conseil-defense",
        "title": "Conseil Defense restreint",
        "description": "Point de coordination securitaire et arbitrages cabinet.",
        "start_at": "2026-05-25T08:30:00",
        "end_at": "2026-05-25T09:30:00",
        "location": "Salle du Conseil - Plateau",
        "participants": ["Ministre", "Directeur de cabinet", "Conseiller securite"],
        "category": "cabinet",
        "priority": "critical",
    },
    {
        "id": "evt-prefet-nawa",
        "title": "Rencontre Prefet de la region de Nawa",
        "description": "Suite au rapport du 10 mai : filiere cacao, infrastructures et diversification regionale.",
        "start_at": "2026-05-25T11:00:00",
        "end_at": "2026-05-25T12:00:00",
        "location": "Soubre (capitale regionale)",
        "participants": ["Vice Premier Ministre", "Prefet de Nawa", "AYA"],
        "category": "territorial",
        "priority": "high",
        "context_ref": "report-prefet-nawa-2026-05-10",
    },
    {
        "id": "evt-point-presse",
        "title": "Point presse hebdomadaire",
        "description": "Preparation des elements de langage et suivi image publique.",
        "start_at": "2026-05-25T11:45:00",
        "end_at": "2026-05-25T12:30:00",
        "location": "Salle presse ministere",
        "participants": ["Ministre", "Communication", "Porte-parole"],
        "category": "press",
        "priority": "high",
    },
    {
        "id": "evt-dejeuner-france",
        "title": "Dejeuner Ambassadeur de France",
        "description": "Cooperation FR-CI, perception publique et projets frontaliers.",
        "start_at": "2026-05-25T13:00:00",
        "end_at": "2026-05-25T14:15:00",
        "location": "Residence officielle",
        "participants": ["Ministre", "Ambassadeur de France", "Conseiller cooperation"],
        "category": "diplomacy",
        "priority": "medium",
    },
    {
        "id": "evt-revue-sahel",
        "title": "Revue operations Sahel",
        "description": "Synthese signaux regionaux et implications non militaires.",
        "start_at": "2026-05-25T15:00:00",
        "end_at": "2026-05-25T16:00:00",
        "location": "Centre de commandement",
        "participants": ["Ministre", "Cellule veille", "Strategie"],
        "category": "strategy",
        "priority": "high",
    },
    {
        "id": "evt-audience-parlement",
        "title": "Audience parlementaire",
        "description": "Reponses institutionnelles et suivi des questions sensibles.",
        "start_at": "2026-05-25T17:40:00",
        "end_at": "2026-05-25T18:30:00",
        "location": "Assemblee Nationale",
        "participants": ["Ministre", "Cabinet parlementaire"],
        "category": "institutional",
        "priority": "medium",
    },
    {
        "id": "evt-comite-nord",
        "title": "Comite projets sociaux Nord",
        "description": "Arbitrage des retards terrain et communication preventive.",
        "start_at": "2026-05-26T09:00:00",
        "end_at": "2026-05-26T10:00:00",
        "location": "Salon cabinet",
        "participants": ["Ministre", "Dircab", "Pilotage projets"],
        "category": "projects",
        "priority": "critical",
    },
    {
        "id": "evt-brief-ao",
        "title": "Brief veille Afrique de l'Ouest",
        "description": "Lecture des signaux faibles presse et diplomatie regionale.",
        "start_at": "2026-05-26T14:00:00",
        "end_at": "2026-05-26T14:45:00",
        "location": "Bureau Ministre",
        "participants": ["Monsieur le Vice Premier Ministre", "AYA", "Cellule veille"],
        "category": "intelligence",
        "priority": "high",
    },
]
