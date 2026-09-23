from types import SimpleNamespace

from app.services.systems.flow_publication import (
    FEATURE_KEY as FLOW_PUBLICATION_FEATURE,
)
from app.services.systems.flow_publication import (
    flow_publication_enabled,
)
from app.services.rag.project_references import project_reference_scheme
from app.services.workspace_features import (
    DEFAULT_ON_FEATURES,
    chat_document_upload_enabled,
    feature_enabled,
    graduated_feature_enabled,
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


def test_andritz_project_scheme_follows_stamped_family_only():
    assert project_reference_scheme(_workspace(settings={"family": "andritz"})) == "andritz"
    assert project_reference_scheme(_workspace(settings={"family": "industrial"})) == ""
    assert project_reference_scheme(_workspace(slug="andritz")) == ""


def test_feature_enabled_reads_the_workspace_setting():
    workspace = _workspace(slug="other", settings={"features": {"secure_deposit": True}})
    assert feature_enabled(workspace, "secure_deposit")

    disabled = _workspace(slug="andritz", settings={"features": {"secure_deposit": False}})
    assert not feature_enabled(disabled, "secure_deposit")


def test_feature_enabled_never_consults_the_slug():
    """There is no fallback list to pass any more: the signature refuses one."""

    import inspect

    assert list(inspect.signature(feature_enabled).parameters) == ["workspace", "feature"]
    assert not feature_enabled(_workspace(slug="andritz"), "x")
    assert not feature_enabled(_workspace(slug="agentium-showcase"), "rpa_bridge")


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


def test_flow_publication_is_on_without_any_stored_flag():
    # Production carries 17 workspaces whose ``features`` never named this key;
    # the destructive legacy write path must not be what they resolve to.
    assert flow_publication_enabled(_workspace(settings=None))
    assert flow_publication_enabled(_workspace(settings={}))
    assert flow_publication_enabled(_workspace(settings={"features": {}}))
    assert flow_publication_enabled(
        _workspace(settings={"features": {"cockpit_router_axes_v4": True}})
    )


def test_flow_publication_honours_an_explicit_workspace_opt_out():
    opted_out = _workspace(settings={"features": {FLOW_PUBLICATION_FEATURE: False}})
    assert not flow_publication_enabled(opted_out)

    opted_in = _workspace(settings={"features": {FLOW_PUBLICATION_FEATURE: True}})
    assert flow_publication_enabled(opted_in)


def test_graduated_features_are_declared_for_audit():
    assert DEFAULT_ON_FEATURES == {
        "adoption_experience_v1",
        "chat_document_upload",
        "cockpit_nav_v5",
        "cockpit_router_axes_v3",
        "cockpit_router_axes_v4",
        "experience_studio_v1",
        FLOW_PUBLICATION_FEATURE,
        "hypervisor_v2",
        "system_360_projection_v1",
        "iam_enforced",
        "voice_realtime_stt",
    }
    for feature in DEFAULT_ON_FEATURES:
        assert graduated_feature_enabled(_workspace(settings={}), feature)
        assert not graduated_feature_enabled(
            _workspace(settings={"features": {feature: False}}), feature
        )


def test_an_unlisted_feature_stays_opt_in():
    # Absence must keep meaning "off" for everything that did not graduate.
    for feature in ("flow_workbench_v1", "flow_v3_dag_authoritative", "rpa_bridge"):
        assert not feature_enabled(_workspace(settings={}), feature)
