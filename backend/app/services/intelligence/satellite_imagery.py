"""Demo-safe satellite imagery fixtures for SENTINEL-CI Security Monitor.

The Vice Premier Ministre demo must stay reproducible and advisory-only. Live EO providers are
therefore intentionally gated out for demo workspaces; this module currently
serves a fixed baseline package plus authenticated local assets.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from app.models.workspace import Workspace

RESOURCE_DIR = Path(__file__).resolve().parents[2] / "resources" / "security"
BASELINE_PATH = RESOURCE_DIR / "satellite-scenes-baseline.json"
ASSET_DIR = RESOURCE_DIR / "satellite"
MIME_BY_SUFFIX = {
    ".webp": "image/webp",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


@lru_cache(maxsize=1)
def load_satellite_baseline() -> dict[str, Any]:
    with BASELINE_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _workspace_settings(workspace: Workspace) -> dict[str, Any]:
    settings = workspace.settings if isinstance(workspace.settings, dict) else {}
    return settings


def _workspace_mode(workspace: Workspace) -> str:
    settings = _workspace_settings(workspace)
    return str(settings.get("mode") or getattr(workspace, "mode", "") or "").lower()


def should_use_live_satellite(workspace: Workspace) -> bool:
    """Return True only for explicitly flagged non-demo workspaces.

    The live Copernicus/Sentinel Hub implementation is deliberately not wired
    here yet. This guard exists so future Option C work cannot accidentally
    affect the Vice Premier Ministre demo.
    """

    if _workspace_mode(workspace) == "demo":
        return False
    flags = _workspace_settings(workspace).get("feature_flag") or {}
    return bool(flags.get("security_live_satellite"))


def _scene_public_metadata(scene: dict[str, Any]) -> dict[str, Any]:
    scene_id = str(scene.get("id") or "")
    out = dict(scene)
    out.pop("asset_key", None)
    out.pop("thumbnail_key", None)
    out["asset_url"] = f"/api/v1/mission-room/satellite/proxy?scene_id={scene_id}"
    out["thumbnail_url"] = f"/api/v1/mission-room/satellite/proxy?scene_id={scene_id}&variant=thumbnail"
    return out


def resolve_satellite_scenes(workspace: Workspace) -> dict[str, Any]:
    baseline = load_satellite_baseline()
    # Option C hook: live is intentionally not implemented until PO confirms
    # the Copernicus risk gate. Demo mode always returns the fixed baseline.
    mode = "live" if should_use_live_satellite(workspace) else "cache_baseline"
    if mode == "live":
        mode = "cache_baseline"

    scenes = [_scene_public_metadata(scene) for scene in baseline.get("scenes") or []]
    return {
        "version": baseline.get("version") or "1.0",
        "mode": mode,
        "captured_at": baseline.get("captured_at"),
        "provider": baseline.get("provider"),
        "source_product": baseline.get("source_product"),
        "attribution": baseline.get("attribution"),
        "disclaimer": baseline.get("disclaimer"),
        "basemap_recommendation": "satellite",
        "scenes": scenes,
    }


def _scene_asset_key(scene: dict[str, Any], variant: Literal["asset", "thumbnail"]) -> str:
    key_name = "thumbnail_key" if variant == "thumbnail" else "asset_key"
    key = str(scene.get(key_name) or "")
    if not key:
        raise FileNotFoundError(f"missing {key_name}")
    # Keep assets constrained to RESOURCE_DIR/satellite.
    if "/" in key or "\\" in key or key.startswith("."):
        raise FileNotFoundError("invalid asset key")
    return key


def get_scene_asset_bytes(scene_id: str, *, variant: Literal["asset", "thumbnail"] = "asset") -> tuple[bytes, str]:
    baseline = load_satellite_baseline()
    scene = next((item for item in baseline.get("scenes") or [] if item.get("id") == scene_id), None)
    if not scene:
        raise FileNotFoundError(scene_id)
    asset_path = ASSET_DIR / _scene_asset_key(scene, variant)
    suffix = asset_path.suffix.lower()
    mime = MIME_BY_SUFFIX.get(suffix)
    if not mime or not asset_path.exists() or not asset_path.is_file():
        raise FileNotFoundError(str(asset_path))
    return asset_path.read_bytes(), mime
