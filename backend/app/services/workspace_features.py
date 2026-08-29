"""Workspace family resolution and per-workspace feature toggles.

Families and feature flags historically lived in global config CSVs plus
substring matches on the workspace slug/name ("andritz" in slug). Migration
058 stamps the legacy result once; runtime settings are now the source of
truth:

- ``settings["family"]`` — canonical stamped family (``WorkspaceFamily``)
- ``settings["features"][<feature>]`` — boolean toggle per feature

An absent or malformed family is deliberately fail-safe ``generic``. Runtime
code must never infer a business specialization from a mutable slug or name.

Posture
-------
A workspace should differ because its use cases differ, not because a flag was
toggled. A proven capability therefore graduates to a **code default** that a
workspace can still override, rather than being back-filled into every
``settings["features"]`` row: the default is then one reviewable line instead of
N rows of drifting JSON, and ``false`` stays a real, explicit opt-out.

Default-on capabilities (absence means enabled):

- ``chat_document_upload`` — drop-and-ask upload in transverse chat.
- ``flow_publication_v1`` — server draft separated from the immutable published
  pointer. Graduated because the alternative is the destructive posture: with
  it off, an editor write lands straight on the live executable graph.
- ``experience_studio_v1`` — authoring surface split from the ``experience_v1``
  Work runtime. Absence preserves the pre-split rollout; an explicit ``false``
  keeps published applications usable while hiding authoring.

Everything else stays an explicit opt-in flag. The ones that look ready but are
not, with the reason they remain flags:

- ``flow_workbench_v1`` — dispatch still rides ``BackgroundTasks`` with no
  request idempotency, so previews of real-effect Skills are not resumable.
- ``flow_v3_dag_authoritative`` — flips the walker for already-published
  ``schema_version>=3`` / ``io_mode=strict`` graphs; an execution-semantics
  change needs the orchestrated rollout, not a default.
- ``cockpit_router_axes_v3`` / ``_v4`` — staged, not superseded. ``_v3`` is read
  in exactly one place, the axes zoom gate, as ``v3 or v4``; every other reader
  (navigation resolver, System perspective, Lot 7 rollout) tests ``_v4`` alone.
  Both true is therefore redundant but harmless, and dropping ``_v3`` would
  change behaviour for a stage-one workspace that has ``_v4`` off.
- ``system_360_projection_v1`` — vertical slice, additionally gated per System
  by ``settings.experience.system_360_canary``.
- ``workspace_experience_v2`` / ``app_entitlements_v1`` — navigation ownership
  and entitlement grants, named in the product-compliance contract.
- ``rpa_bridge`` / ``sap_hana_connector`` / ``mcp_connector`` / ``model_portal_beta``
  — each needs per-workspace credentials or an external endpoint, so enabling
  one without configuration would only advertise a connector that cannot
  connect.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.schemas.canonical import WorkspaceFamily

KNOWN_FAMILIES = frozenset(family.value for family in WorkspaceFamily)

#: Capabilities that graduated to a code default. Listed for auditability: the
#: resolver takes the key from the caller, not from this set.
DEFAULT_ON_FEATURES: frozenset[str] = frozenset(
    {
        "chat_document_upload",
        "experience_studio_v1",
        "flow_publication_v1",
    }
)


def _workspace_settings(workspace: Any) -> Mapping[str, Any]:
    raw = getattr(workspace, "settings", None)
    return raw if isinstance(raw, Mapping) else {}


def workspace_family(workspace: Any) -> str:
    """Resolve only a canonical stamped family, otherwise fail safe."""
    stamped = str(_workspace_settings(workspace).get("family") or "").strip().lower()
    if stamped in KNOWN_FAMILIES:
        return stamped
    return WorkspaceFamily.generic.value


def feature_enabled(workspace: Any, feature: str, *, csv_fallback: str = "") -> bool:
    """Per-workspace feature toggle with the legacy global CSV as fallback.

    ``workspace.settings["features"][feature]`` wins when present; otherwise
    the slug is matched (exact, case-insensitive) against the comma-separated
    global config value the flag historically used.
    """
    features = _workspace_settings(workspace).get("features")
    if isinstance(features, Mapping) and feature in features:
        return bool(features[feature])
    slug = str(getattr(workspace, "slug", "") or "").strip().lower()
    allowed = {item.strip().lower() for item in str(csv_fallback or "").split(",") if item.strip()}
    return slug in allowed


def graduated_feature_enabled(workspace: Any, feature: str) -> bool:
    """Resolve a graduated capability: on unless the workspace opts out.

    Absence means enabled, so a stored ``false`` stays a deliberate opt-out
    rather than being indistinguishable from a workspace nobody has migrated.
    """
    features = _workspace_settings(workspace).get("features")
    if isinstance(features, Mapping) and feature in features:
        return bool(features[feature])
    return True


def chat_document_upload_enabled(workspace: Any) -> bool:
    """Drop-and-ask upload in transverse chat. Enabled unless explicitly off."""
    return graduated_feature_enabled(workspace, "chat_document_upload")
