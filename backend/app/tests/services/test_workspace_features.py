from types import SimpleNamespace

from app.services.workspace_features import (
    family_heuristic,
    feature_enabled,
    workspace_family,
)


def _workspace(slug: str = "demo", name: str = "Demo", settings: dict | None = None):
    return SimpleNamespace(slug=slug, name=name, settings=settings or {})


def test_stamped_family_wins_over_heuristic():
    workspace = _workspace(slug="some-generic-slug", settings={"family": "andritz"})
    assert workspace_family(workspace) == "andritz"


def test_invalid_stamp_falls_back_to_heuristic():
    workspace = _workspace(slug="andritz-pilot", settings={"family": "bogus"})
    assert workspace_family(workspace) == "andritz"


def test_heuristic_matches_legacy_substring_behaviour():
    assert family_heuristic(_workspace(slug="andritz")) == "andritz"
    assert family_heuristic(_workspace(slug="acme", name="Andritz Pilot")) == "andritz"
    assert family_heuristic(_workspace(slug="sentinel-ci")) == "sentinel_ci"
    assert family_heuristic(_workspace(slug="acme")) == "generic"


def test_stamped_generic_blocks_substring_match():
    # The whole point of stamping: a workspace named "andritz-test" can opt
    # out of the Andritz specialization.
    workspace = _workspace(slug="andritz-test", settings={"family": "generic"})
    assert workspace_family(workspace) == "generic"


def test_feature_enabled_settings_override_wins():
    workspace = _workspace(slug="other", settings={"features": {"secure_deposit": True}})
    assert feature_enabled(workspace, "secure_deposit", csv_fallback="andritz")

    disabled = _workspace(slug="andritz", settings={"features": {"secure_deposit": False}})
    assert not feature_enabled(disabled, "secure_deposit", csv_fallback="andritz")


def test_feature_enabled_csv_fallback_is_exact_match():
    assert feature_enabled(_workspace(slug="andritz"), "x", csv_fallback="andritz, other")
    assert feature_enabled(_workspace(slug="Andritz"), "x", csv_fallback="andritz")
    assert not feature_enabled(_workspace(slug="andritz-test"), "x", csv_fallback="andritz")
    assert not feature_enabled(_workspace(slug="andritz"), "x", csv_fallback="")
