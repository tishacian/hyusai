"""Freeze the last per-feature slug lists onto the workspaces they named.

``feature_enabled`` used to take a comma-separated list of slugs as a fallback,
and a few runtime gates read such a list directly. Each one made a customer a
property of the deployment. This migration writes what every list answered
into ``workspaces.settings["features"]``, where the runtime now looks, so the
lists and the fallback can go.

It covers three shapes of list:

- opt-in lists (``openai_realtime`` and the showcase connectors): a listed
  workspace gets ``true``; absence already means off.
- ``iam_enforced``: enforcement becomes the default for new workspaces, so
  every existing workspace gets the answer it had, ``true`` for a listed one
  and an explicit ``false`` for the others. None of them changes behaviour.
- ``voice_realtime_stt``: an empty list meant every workspace, and absence
  keeps meaning that. A non-empty list writes ``false`` on the workspaces it
  left out.

An explicit value already on a workspace is never overwritten, and the
migration records what it wrote so the downgrade removes exactly that.
"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "111_freeze_ws_slug_fallbacks"
down_revision = "110_secure_deposit_ws_flag"
branch_labels = None
depends_on = None

MARKER_KEY = "_migration_111_slug_fallbacks"

OPT_IN = "opt_in"
DEFAULT_ON = "default_on"
ALLOWLIST_OR_ALL = "allowlist_or_all"

# (feature, environment variable or None, shipped default, shape)
FREEZES: tuple[tuple[str, str | None, str, str], ...] = (
    ("iam_enforced", "IAM_ENFORCED_WORKSPACE_SLUGS", "andritz", DEFAULT_ON),
    ("openai_realtime", "OPENAI_REALTIME_ENABLED_WORKSPACE_SLUGS", "andritz", OPT_IN),
    ("voice_realtime_stt", "VOICE_REALTIME_STT_WORKSPACE_SLUGS", "", ALLOWLIST_OR_ALL),
    # These three were literals in code, not configuration.
    ("model_portal_beta", None, "agentium-showcase", OPT_IN),
    ("rpa_bridge", None, "agentium-showcase", OPT_IN),
    ("sap_hana_connector", None, "agentium-showcase", OPT_IN),
)


def _workspaces_table() -> sa.Table:
    return sa.table(
        "workspaces",
        sa.column("id", sa.String(length=36)),
        sa.column("slug", sa.String(length=100)),
        sa.column("settings", sa.JSON()),
    )


def _listed(env_var: str | None, default: str) -> set[str]:
    raw = None
    if env_var:
        # pydantic-settings matched these case-insensitively.
        raw = os.environ.get(env_var)
        if raw is None:
            raw = os.environ.get(env_var.lower())
    if raw is None:
        raw = default
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _frozen_value(shape: str, slug: str, listed: set[str]) -> bool | None:
    """The value to write so the workspace answers as before, or None."""

    if shape == OPT_IN:
        return True if slug in listed else None
    if shape == DEFAULT_ON:
        return slug in listed
    if shape == ALLOWLIST_OR_ALL:
        return False if listed and slug not in listed else None
    raise ValueError(f"unknown shape {shape}")


def _as_settings(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    if value is None:
        return {}
    raise RuntimeError("workspaces.settings must be a JSON object")


def upgrade() -> None:
    bind = op.get_bind()
    workspaces = _workspaces_table()
    lists = [
        (feature, _listed(env_var, default), shape) for feature, env_var, default, shape in FREEZES
    ]

    rows = bind.execute(sa.select(workspaces.c.id, workspaces.c.slug, workspaces.c.settings)).all()
    for row in rows:
        mapping = row._mapping
        settings = _as_settings(mapping["settings"])
        raw_features = settings.get("features")
        # The runtime reads a non-object ``features`` as no flag at all, so it
        # is frozen like an empty one; the marker keeps the original for the
        # downgrade. Skipping it would let the new IAM default govern a
        # workspace nobody decided to govern.
        malformed = raw_features is not None and not isinstance(raw_features, dict)
        features = {} if malformed else dict(raw_features or {})
        slug = str(mapping["slug"] or "").strip().lower()
        wrote: dict[str, bool] = {}
        for feature, listed, shape in lists:
            if feature in features:
                continue  # an explicit decision already exists
            value = _frozen_value(shape, slug, listed)
            if value is None:
                continue
            features[feature] = value
            wrote[feature] = value
        if not wrote:
            continue
        settings["features"] = features
        marker: dict[str, Any] = {"schema": 1, "wrote": wrote}
        if malformed:
            marker["replaced_features"] = raw_features
        settings[MARKER_KEY] = marker
        bind.execute(
            sa.update(workspaces).where(workspaces.c.id == mapping["id"]).values(settings=settings)
        )


def downgrade() -> None:
    bind = op.get_bind()
    workspaces = _workspaces_table()

    rows = bind.execute(sa.select(workspaces.c.id, workspaces.c.settings)).all()
    for row in rows:
        mapping = row._mapping
        settings = _as_settings(mapping["settings"])
        marker = settings.pop(MARKER_KEY, None)
        if not isinstance(marker, dict):
            continue
        wrote = marker.get("wrote")
        features = settings.get("features")
        if "replaced_features" in marker:
            settings["features"] = marker["replaced_features"]
        elif isinstance(wrote, dict) and isinstance(features, dict):
            for feature, value in wrote.items():
                if features.get(feature) == value:
                    features.pop(feature, None)
            if features:
                settings["features"] = features
            else:
                settings.pop("features", None)
        bind.execute(
            sa.update(workspaces).where(workspaces.c.id == mapping["id"]).values(settings=settings)
        )
