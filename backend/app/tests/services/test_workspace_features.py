from types import SimpleNamespace

from app.services.workspace_features import (
    chat_document_upload_enabled,
    feature_enabled,
    workspace_family,
)


def _workspace(slug: str = "demo", name: str = "Demo", settings: dict | None = None):
    return SimpleNamespace(slug=slug, name=name, settings=settings or {})


def test_stamped_family_is_authoritative():
    workspace = _workspace(slug="some-generic-slug", settings={"family": "andritz"})
    assert workspace_family(workspace) == "andritz"


def test_invalid_stamp_fails_safe_without_slug_or_name_inference():
    workspace = _workspace(slug="andritz-pilot", settings={"family": "bogus"})
    assert workspace_family(workspace) == "generic"


def test_missing_stamp_fails_safe_without_slug_or_name_inference():
    assert workspace_family(_workspace(slug="andritz")) == "generic"
    assert workspace_family(_workspace(slug="acme", name="Andritz Pilot")) == "generic"
    assert workspace_family(_workspace(slug="sentinel-ci")) == "generic"


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


def test_chat_document_upload_enabled_by_default():
    # Default-on (opt-out): absent settings, empty settings, and empty features
    # all resolve to True.
    assert chat_document_upload_enabled(_workspace(settings=None))
    assert chat_document_upload_enabled(_workspace(settings={}))
    assert chat_document_upload_enabled(_workspace(settings={"features": {}}))
    assert chat_document_upload_enabled(_workspace(settings={"features": {"other": False}}))


def test_chat_document_upload_disabled_when_flag_false():
    disabled = _workspace(settings={"features": {"chat_document_upload": False}})
    assert not chat_document_upload_enabled(disabled)

    explicit_on = _workspace(settings={"features": {"chat_document_upload": True}})
    assert chat_document_upload_enabled(explicit_on)
