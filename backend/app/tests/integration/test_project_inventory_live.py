"""Live, opt-in integration test for the cross-project inventory facet.

This exercises the REAL ``transversal_inventory`` facet
(``app.services.rag.project_inventory.build_project_inventory``) against a live
Qdrant holding the ``andritz__andritz-notices-techniques-spl-pilot`` multilingual
content index, and pins the ground truth for the canonical URACA enumeration.

It is gated exactly like ``test_qdrant_vector_db.py`` so it NEVER breaks normal
CI: it is marked ``integration``, probes a TCP socket, and skips when Qdrant is
unreachable or when the andritz SPL pilot collection is not loaded in the target
Qdrant. It only enforces the hardcoded ground truth where the data exists.

How to run (in-container, where Qdrant + the andritz dataset are reachable)::

    ssh omnirag-demo \\
      "docker exec -i -w /app agentium-backend \\
         python -m pytest app/tests/integration/test_project_inventory_live.py -q -m integration"

The in-container backend already exports ``QDRANT_HOST=agentium-qdrant`` /
``QDRANT_PORT=6333``. Set ``QDRANT_INTEGRATION=0`` to force-skip. Outside the
container (no Qdrant on localhost) the socket probe fails and the test skips.

Ground truth re-confirmed live 2026-06-24 via this exact facet entry point.
"""

from __future__ import annotations

import os
import socket

import pytest

pytestmark = pytest.mark.integration

# Canonical transversal_inventory question and its verified live ground truth.
_URACA_QUERY = "Quels projets utilisent une pompe URACA ?"
_EXPECTED_TOTAL_PROJECTS = 133
_EXPECTED_TERMS = ["uraca"]
_MUST_INCLUDE = {"AVA100", "NAN330", "NBD100"}
# Turkish false positives that the discriminating "uraca" full-text match must
# NOT surface for this query.
_MUST_EXCLUDE = {"KUT100", "MOG400"}

# The andritz SPL pilot workspace/collection that holds the live content index.
# The VectorDBFactory resolves the logical slug to the active physical Qdrant
# collection (e.g. ``andritz__andritz-notices-techniques-spl-pilot__hybrid_...``).
_WORKSPACE_SLUG = "andritz"
_SPL_COLLECTION = "andritz-notices-techniques-spl-pilot"


def _qdrant_host() -> str:
    return os.getenv("QDRANT_HOST", "localhost")


def _qdrant_port() -> int:
    return int(os.getenv("QDRANT_PORT", "6333"))


def _qdrant_reachable() -> bool:
    if os.getenv("QDRANT_INTEGRATION") == "0":
        return False
    try:
        with socket.create_connection((_qdrant_host(), _qdrant_port()), timeout=0.75):
            return True
    except OSError:
        return False


@pytest.fixture
def require_qdrant():
    if not _qdrant_reachable():
        pytest.skip(
            f"Qdrant not reachable at {_qdrant_host()}:{_qdrant_port()} "
            "(run in-container or set QDRANT_HOST / QDRANT_PORT)"
        )


def _andritz_profile() -> dict[str, object]:
    return {
        "vector_db": "qdrant",
        "workspace_slug": _WORKSPACE_SLUG,
        "collections": [_SPL_COLLECTION],
    }


def _require_spl_collection_loaded() -> None:
    """Skip (do not fail) when this Qdrant lacks the andritz SPL pilot data."""
    from app.services.vector_db.factory import VectorDBFactory

    try:
        db = VectorDBFactory.get_db(
            _SPL_COLLECTION, db_type="qdrant", workspace_slug=_WORKSPACE_SLUG
        )
        loaded = db.client is not None and db.client.collection_exists(db.collection_name)
    except Exception as exc:  # noqa: BLE001 - environment without the dataset -> skip.
        pytest.skip(f"andritz SPL pilot collection not resolvable here: {exc}")
    if not loaded:
        pytest.skip(
            "andritz SPL pilot collection not loaded in this Qdrant "
            "(expected the live multilingual content index)"
        )


def test_uraca_project_inventory_matches_live_ground_truth(require_qdrant):
    """The real facet enumerates exactly 133 URACA projects with the right members."""
    pytest.importorskip("qdrant_client")
    _require_spl_collection_loaded()

    from app.services.rag.project_inventory import build_project_inventory

    inventory = build_project_inventory(_andritz_profile(), _URACA_QUERY)

    assert inventory is not None, (
        "facet returned None against a loaded collection — regression in "
        "build_project_inventory or the project_code keyword index"
    )

    assert inventory["terms"] == _EXPECTED_TERMS
    assert inventory["total_projects"] == _EXPECTED_TOTAL_PROJECTS

    project_codes = {entry["project_code"] for entry in inventory["projects"]}
    assert len(project_codes) == _EXPECTED_TOTAL_PROJECTS
    assert _MUST_INCLUDE <= project_codes, sorted(_MUST_INCLUDE - project_codes)
    assert _MUST_EXCLUDE.isdisjoint(project_codes), sorted(_MUST_EXCLUDE & project_codes)
