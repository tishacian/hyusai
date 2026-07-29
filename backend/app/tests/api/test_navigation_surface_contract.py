"""The navigation catalogue and the audit allow-list must agree.

`navigation.resolved` events carry the surface the router landed on. The endpoint
validates that surface against `_NAVIGATION_SURFACES` and answers 422 when it does
not recognise it — and the frontend swallows that failure, because navigation
telemetry must never block a redirect. So a surface added to the catalogue without
a line here disappears from the audit trail silently.

That is exactly what had happened: `fse-reports`, `model-portal`, `sap-hana` and
`nawa-itsd` were declared in the catalogue, emitted on every page view of those
apps, and rejected. Nothing failed loudly. This test is the missing seam.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.api.v1.endpoints.audit import _NAVIGATION_SURFACES

REPO_ROOT = Path(__file__).resolve().parents[4]
CATALOGUE = REPO_ROOT / "frontend-ng" / "src" / "app" / "core" / "navigation.catalog.ts"

# The catalogue is a TypeScript array of object literals; each entry opens with
# its id at a fixed indentation. Parsing that is enough to compare two lists of
# slugs, and it keeps the test free of a node toolchain.
_ENTRY_ID = re.compile(r"^    id: '([a-z0-9-]+)',$", re.MULTILINE)

# Emitted when the router cannot attribute a route to any catalogue entry, so it
# is accepted by the endpoint without being declared on the frontend side.
_ROUTER_FALLBACK = "unknown"


def _catalogue_surfaces() -> set[str]:
    if not CATALOGUE.exists():  # pragma: no cover - only outside a full checkout
        pytest.skip(f"navigation catalogue not found at {CATALOGUE}")
    ids = set(_ENTRY_ID.findall(CATALOGUE.read_text(encoding="utf-8")))
    assert len(ids) > 20, "the catalogue parser stopped matching entries"
    return ids


def test_every_catalogued_surface_is_accepted_by_the_audit_endpoint():
    rejected = sorted(_catalogue_surfaces() - set(_NAVIGATION_SURFACES))
    assert not rejected, (
        "these surfaces are declared in navigation.catalog.ts but rejected by the "
        f"audit endpoint, so their page views never reach the trail: {rejected}"
    )


def test_the_allow_list_carries_nothing_beyond_the_catalogue_and_the_fallback():
    """Guard the other direction: a stale entry means a surface was renamed."""
    extra = sorted(set(_NAVIGATION_SURFACES) - _catalogue_surfaces() - {_ROUTER_FALLBACK})
    assert not extra, (
        "these surfaces are accepted by the audit endpoint but no longer exist in "
        f"navigation.catalog.ts: {extra}"
    )


def test_the_router_fallback_stays_accepted():
    """A route the catalogue cannot attribute must still be recordable."""
    assert _ROUTER_FALLBACK in _NAVIGATION_SURFACES
