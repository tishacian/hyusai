"""Mission Room identities, profiles and Octocity presentation."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.iam.app_entitlements import (
    BUSINESS_APP_KEYS,
    app_entitlements_enabled,
    replace_member_app_entitlements,
)
from app.services.workspace_app_runtime import (
    resolve_mission_room_provider_runtime,
    workspace_app_platform_enabled,
)


logger = logging.getLogger(__name__)


SENTINEL_WORKSPACE_SLUG = "sentinel-ci"
SENTINEL_WORKSPACE_NAME = "SENTINEL-CI"
SENTINEL_ASSISTANT_NAME = "AYA"
SENTINEL_MISSION_ROOM_PROFILE = "sentinel_government_v1"
SENTINEL_EVIDENCE_GRAPH_COLLECTION = "sentinel-ci-evidence-graph"
SENTINEL_MARITIME_INTELLIGENCE_COLLECTION = "sentinel-ci-maritime-intelligence"
MISSION_ROOM_ROOT = "/hypervisor/mission-room"
MISSION_ROOM_ROUTE = f"{MISSION_ROOM_ROOT}/cockpit"
VP_SCENARIO_ID = "sentinel-ci-vp-morning-zone-nord-v1"
OCTOCITY_WORKSPACE_SLUG = "octocity-mission-room"
OCTOCITY_WORKSPACE_NAME = "Octocity Mission Room"
OCTOCITY_ASSISTANT_NAME = "OCTAVE"
OCTOCITY_MISSION_ROOM_PROFILE = "octocity_institutional_v1"


def _octocity_owner_emails() -> tuple[str, ...]:
    return tuple(
        email.strip()
        for email in os.environ.get("OCTOCITY_OWNER_EMAILS", "").split(",")
        if email.strip()
    )


_OCTOCITY_TEXT_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    # Public action ids are presentation contracts. Keep this exact alias
    # ahead of the generic AYA/OCTAVE and sector-name substitutions so a
    # persisted confirmation can still resolve to an effective manifest.
    ("aya.recommend_cacao", "octave.recommend_diversification"),
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


def authoritative_mission_room_projection(
    workspace: Workspace | None,
    *,
    db: DBSession | None = None,
) -> dict[str, Any] | None:
    """Return the installed provider contract when platform authority is on.

    This boundary deliberately has no settings fallback. Provider-less generic
    versions and invalid installations raise through the runtime resolver. A
    provider-capable generic version is dispatched by the API to the separate
    workspace-object service, so this fixture module never becomes its
    accidental provider.
    """

    if workspace is None or not workspace_app_platform_enabled(workspace):
        return None
    runtime = resolve_mission_room_provider_runtime(workspace, db=db)
    projection = runtime.mission_room
    if not isinstance(projection, Mapping):
        # The strict runtime resolver normally makes this unreachable; keep the
        # service boundary fail-closed if its contract ever regresses.
        raise RuntimeError("authoritative Mission Room projection is missing")
    return dict(projection)


def mission_room_profile(
    workspace: Workspace | None,
    *,
    db: DBSession | None = None,
) -> str:
    authoritative = authoritative_mission_room_projection(workspace, db=db)
    if authoritative is not None:
        return str(authoritative["profile"])
    settings = workspace.settings if workspace is not None else None
    mission_room = (settings or {}).get("mission_room") if isinstance(settings, dict) else None
    profile = (mission_room or {}).get("profile") if isinstance(mission_room, dict) else None
    return str(profile or "")


def is_octocity_mission_room(
    workspace: Workspace | None,
    *,
    db: DBSession | None = None,
) -> bool:
    return mission_room_profile(workspace, db=db) == OCTOCITY_MISSION_ROOM_PROFILE


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

    return _present_octocity_payload(payload)


def _present_octocity_payload(payload: Any) -> Any:
    """Apply the already-resolved Octocity presentation without DB re-reads."""

    if isinstance(payload, str):
        text = payload
        for old, new in _OCTOCITY_TEXT_REPLACEMENTS:
            text = text.replace(old, new)
        return text
    if isinstance(payload, dict):
        return {
            key: _present_octocity_payload(value) for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_present_octocity_payload(item) for item in payload]
    if isinstance(payload, tuple):
        return tuple(_present_octocity_payload(item) for item in payload)
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
    grant_source: str,
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
        membership = existing
        if membership is None:
            membership = WorkspaceMember(
                workspace_id=workspace.id,
                user_id=user.id,
                role=role,
                role_template=role_template,
                custom_labels=[custom_label],
            )
            db.add(membership)
            db.flush()
            added += 1
        if app_entitlements_enabled(workspace):
            replace_member_app_entitlements(
                db,
                membership,
                BUSINESS_APP_KEYS,
                granted_by_user_id=None,
                grant_source=grant_source,
            )
    return added
