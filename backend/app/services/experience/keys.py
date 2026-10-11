"""Stable SystemBinding keys for dual-run Experiences (Lot 8).

No imports. Seed, mission-room resolve, and tests share these literals.
"""

ANDRITZ_RECHERCHE_KEY = "andritz.recherche"
ANDRITZ_CLIENT360_KEY = "andritz.client360"
ANDRITZ_CAPTURE_KEY = "andritz.capture"
ANDRITZ_FSE_KEY = "andritz.fse"

SENTINEL_COCKPIT_KEY = "sentinel.cockpit"
SENTINEL_MAP_KEY = "sentinel.map"
SENTINEL_AGENDA_KEY = "sentinel.agenda"
SENTINEL_INTELLIGENCE_KEY = "sentinel.intelligence"
SENTINEL_DECISIONS_KEY = "sentinel.decisions"

OCTOCITY_COCKPIT_KEY = "octocity.cockpit"
OCTOCITY_MAP_KEY = "octocity.map"
OCTOCITY_AGENDA_KEY = "octocity.agenda"
OCTOCITY_INTELLIGENCE_KEY = "octocity.intelligence"
OCTOCITY_DECISIONS_KEY = "octocity.decisions"

MISSION_COCKPIT_KEY = "mission.cockpit"
MISSION_MAP_KEY = "mission.map"
MISSION_AGENDA_KEY = "mission.agenda"
MISSION_INTELLIGENCE_KEY = "mission.intelligence"
MISSION_DECISIONS_KEY = "mission.decisions"

ANDRITZ_SLUG = "andritz"
SENTINEL_SLUG = "sentinel-ci"
OCTOCITY_SLUG = "octocity-mission-room"

RECHERCHE_EXPERIENCE_SLUG = "recherche"
CLIENT360_EXPERIENCE_SLUG = "client360"
CAPTURE_EXPERIENCE_SLUG = "capture"
FSE_EXPERIENCE_SLUG = "fse"
MISSION_CONTROL_EXPERIENCE_SLUG = "mission-control"
SENTINEL_EXPERIENCE_SLUG = "sentinel-ci"
OCTOCITY_EXPERIENCE_SLUG = "octocity"

SENTINEL_PROFILES = frozenset({"sentinel_government_v1", "government_mission_room"})
OCTOCITY_PROFILES = frozenset({"octocity_institutional_v1"})

_NAV_KEYS = {
    "sentinel": {
        "cockpit": SENTINEL_COCKPIT_KEY,
        "strategie": SENTINEL_MAP_KEY,
        "agenda": SENTINEL_AGENDA_KEY,
        "presse": SENTINEL_INTELLIGENCE_KEY,
        "securite": SENTINEL_INTELLIGENCE_KEY,
        "reputation": SENTINEL_INTELLIGENCE_KEY,
        "decisions": SENTINEL_DECISIONS_KEY,
    },
    "octocity": {
        "cockpit": OCTOCITY_COCKPIT_KEY,
        "strategie": OCTOCITY_MAP_KEY,
        "agenda": OCTOCITY_AGENDA_KEY,
        "presse": OCTOCITY_INTELLIGENCE_KEY,
        "securite": OCTOCITY_INTELLIGENCE_KEY,
        "reputation": OCTOCITY_INTELLIGENCE_KEY,
        "decisions": OCTOCITY_DECISIONS_KEY,
    },
    "mission": {
        "cockpit": MISSION_COCKPIT_KEY,
        "strategie": MISSION_MAP_KEY,
        "agenda": MISSION_AGENDA_KEY,
        "presse": MISSION_INTELLIGENCE_KEY,
        "securite": MISSION_INTELLIGENCE_KEY,
        "reputation": MISSION_INTELLIGENCE_KEY,
        "decisions": MISSION_DECISIONS_KEY,
    },
}


def mission_family(profile: str) -> str:
    value = (profile or "").strip()
    if value in SENTINEL_PROFILES:
        return "sentinel"
    if value in OCTOCITY_PROFILES or value.startswith("octocity"):
        return "octocity"
    return "mission"


def mission_nav_binding_key(profile: str, nav_key: str) -> str | None:
    return _NAV_KEYS[mission_family(profile)].get(nav_key)
