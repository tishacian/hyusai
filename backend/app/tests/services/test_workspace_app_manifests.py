"""Static trust and isolation contracts for built-in Workspace App manifests."""

import hashlib
import json
from copy import deepcopy

import pytest

from app.services.workspace_app_manifests import (
    BUILTIN_WORKSPACE_APP_MANIFEST_LOCK,
    BUILTIN_WORKSPACE_APP_MANIFESTS,
    DEFAULT_MANIFEST_LOCK_PATH,
    WorkspaceAppManifestError,
    WorkspaceAppManifestNotFound,
    _compile_manifest,
    get_builtin_workspace_app_manifest,
    list_builtin_workspace_app_manifests,
    validate_manifest_configuration,
    verify_builtin_workspace_app_manifest_lock,
)


def test_registry_is_content_addressed_and_returns_defensive_payloads():
    manifest = BUILTIN_WORKSPACE_APP_MANIFESTS[("mission-room.extension", "1.1.0")]
    assert hashlib.sha256(manifest.canonical_json.encode()).hexdigest() == manifest.digest
    resolved = get_builtin_workspace_app_manifest(
        manifest.app_id,
        manifest.version,
        expected_digest=manifest.digest,
    )
    assert resolved is manifest

    payload = resolved.as_dict()
    payload["branding"]["namespace"] = "tampered"
    assert resolved.as_dict()["branding"]["namespace"] == "mission-room"


def test_published_manifest_versions_are_exactly_frozen_by_lockfile(tmp_path):
    assert BUILTIN_WORKSPACE_APP_MANIFEST_LOCK == {
        key: manifest.digest for key, manifest in BUILTIN_WORKSPACE_APP_MANIFESTS.items()
    }

    payload = json.loads(DEFAULT_MANIFEST_LOCK_PATH.read_text(encoding="utf-8"))
    payload["manifests"][0]["sha256"] = "0" * 64
    tampered = tmp_path / "workspace-app-manifests.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WorkspaceAppManifestError, match="SemVer bump"):
        verify_builtin_workspace_app_manifest_lock(tampered)

    payload = json.loads(DEFAULT_MANIFEST_LOCK_PATH.read_text(encoding="utf-8"))
    payload["manifests"].pop()
    missing = tmp_path / "workspace-app-manifests-missing.json"
    missing.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WorkspaceAppManifestError, match="SemVer bump"):
        verify_builtin_workspace_app_manifest_lock(missing)


def test_unknown_version_and_digest_fail_closed():
    manifest = BUILTIN_WORKSPACE_APP_MANIFESTS[("andritz.chat", "1.0.0")]
    with pytest.raises(WorkspaceAppManifestNotFound, match="unknown built-in"):
        get_builtin_workspace_app_manifest(
            "andritz.chat",
            "9.9.9",
            expected_digest=manifest.digest,
        )
    with pytest.raises(WorkspaceAppManifestError, match="digest mismatch"):
        get_builtin_workspace_app_manifest(
            manifest.app_id,
            manifest.version,
            expected_digest="0" * 64,
        )
    with pytest.raises(WorkspaceAppManifestError, match="SHA-256"):
        get_builtin_workspace_app_manifest(
            manifest.app_id,
            manifest.version,
            expected_digest="latest",
        )


def test_andritz_has_exactly_three_apps_and_fse_is_a_knowledge_capture_surface():
    expected = {
        "andritz.chat": ["chat"],
        "andritz.client360-pdr": ["client360-pdr"],
        "andritz.knowledge-capture": ["knowledge-capture", "fse-reports"],
    }
    andritz = {
        manifest.app_id: manifest.as_dict()["entitlement_keys"]
        for manifest in list_builtin_workspace_app_manifests()
        if manifest.app_id.startswith("andritz.")
    }
    assert andritz == expected
    assert len(andritz) == 3
    for app_id in expected:
        payload = BUILTIN_WORKSPACE_APP_MANIFESTS[(app_id, "1.0.0")].as_dict()
        assert payload["compatibility"]["workspace_families"] == ["andritz"]
        assert payload["experience"]["shell"] == "business"
    chat = BUILTIN_WORKSPACE_APP_MANIFESTS[("andritz.chat", "1.0.0")].as_dict()
    assert chat["api_prefixes"] == ["/api/v1/chat", "/api/v1/sessions"]
    knowledge_capture = BUILTIN_WORKSPACE_APP_MANIFESTS[
        ("andritz.knowledge-capture", "1.0.0")
    ].as_dict()
    assert knowledge_capture["routes"] == [
        "/knowledge/capture",
        "/knowledge/interventions",
    ]
    assert [surface["api_prefix"] for surface in knowledge_capture["surfaces"]] == [
        "/api/v1/knowledge-capture",
        "/api/v1/knowledge-capture",
    ]
    assert "api_prefixes" not in knowledge_capture


def test_every_manifest_declares_platform_migration_and_explicit_safe_backfill():
    for manifest in list_builtin_workspace_app_manifests():
        payload = manifest.as_dict()
        assert payload["migrations"] == [
            {
                "executor": "platform_schema_contract_v1",
                "id": "workspace_app_platform.schema.069",
                "kind": "platform_schema",
                "phase": "precondition",
                "required": True,
                "reversibility": "persistent_additive_schema",
            },
            {
                "executor": "platform_schema_contract_v1",
                "id": "workspace_app_platform.lifecycle_steps.073",
                "kind": "platform_schema",
                "phase": "precondition",
                "required": True,
                "reversibility": "persistent_additive_schema",
            },
        ]
        assert payload["backfills"] == [
            {
                "executor": "explicit_legacy_backfill_v1",
                "id": f"{manifest.app_id}.legacy_installation.v1",
                "kind": "explicit_application_backfill",
                "mutates_member_entitlements": False,
                "phase": "legacy_adoption",
                "required": True,
                "reversibility": "installation_transaction",
                "runner": (
                    "backend/scripts/backfill_workspace_app_installations.py"
                ),
                "selection": "explicit_workspace_ids",
            }
        ]


def test_sentinel_and_octocity_branding_and_action_packs_are_isolated():
    sentinel = BUILTIN_WORKSPACE_APP_MANIFESTS[("sentinel.mission-room", "1.0.0")]
    octocity = BUILTIN_WORKSPACE_APP_MANIFESTS[("octocity.mission-room", "1.0.0")]
    sentinel_text = sentinel.canonical_json.lower()
    octocity_text = octocity.canonical_json.lower()

    assert "sentinel" in sentinel_text
    assert "octocity" not in sentinel_text
    assert "octocity" in octocity_text
    assert "sentinel" not in octocity_text
    assert sentinel.as_dict()["branding"]["namespace"] == "sentinel"
    assert octocity.as_dict()["branding"]["namespace"] == "octocity"
    assert sentinel.as_dict()["action_packs"] == [
        "global_voice_v1",
        "sentinel_ci_aya_v1",
        "sentinel_ci_aya_security_v1",
    ]
    assert octocity.as_dict()["action_packs"] == [
        "global_voice_v1",
        "octave_mission_room_v1",
        "octave_security_v1",
    ]
    assert sentinel.as_dict()["conflict_group"] == "mission-room.primary"
    assert octocity.as_dict()["conflict_group"] == "mission-room.primary"
    assert sentinel.as_dict()["exclusive_routes"] is True
    assert octocity.as_dict()["exclusive_routes"] is True
    assert sentinel.as_dict()["compatibility"]["workspace_families"] == [
        "sentinel_ci"
    ]
    assert sentinel.as_dict()["compatibility"]["workspace_profiles"] == [
        "sentinel_government_v1"
    ]
    assert octocity.as_dict()["compatibility"]["workspace_families"] == ["generic"]
    assert octocity.as_dict()["compatibility"]["workspace_profiles"] == [
        "octocity_institutional_v1"
    ]


def test_configuration_contract_applies_defaults_and_rejects_cross_profile():
    sentinel = BUILTIN_WORKSPACE_APP_MANIFESTS[("sentinel.mission-room", "1.0.0")]
    assert validate_manifest_configuration(sentinel, None) == {
        "profile": "government_mission_room",
        "assistant_profile": "vigie_executive",
    }
    with pytest.raises(WorkspaceAppManifestError, match="allowed values"):
        validate_manifest_configuration(
            sentinel,
            {"assistant_profile": "octave_executive"},
        )
    with pytest.raises(WorkspaceAppManifestError, match="unknown"):
        validate_manifest_configuration(sentinel, {"octocity_branding": True})


@pytest.mark.parametrize(
    "configuration",
    [
        {"profile": "sentinel_government_v1", "assistant_profile": "default"},
        {"profile": "generic", "assistant_profile": "vigie_executive"},
        {"profile": "octocity_mission_room", "assistant_profile": "default"},
        {"profile": "generic", "assistant_profile": "octave_executive"},
    ],
)
def test_generic_mission_room_cannot_claim_reserved_identities(configuration):
    manifest = BUILTIN_WORKSPACE_APP_MANIFESTS[("mission-room.extension", "1.0.0")]

    with pytest.raises(WorkspaceAppManifestError, match="reserved workspace-app identity"):
        validate_manifest_configuration(manifest, configuration)


def test_mission_room_default_route_is_nested_under_its_declared_route():
    for app_id, version in (
        ("mission-room.extension", "1.0.0"),
        ("mission-room.extension", "1.1.0"),
        ("mission-room.extension", "1.2.0"),
        ("sentinel.mission-room", "1.0.0"),
        ("octocity.mission-room", "1.0.0"),
    ):
        payload = BUILTIN_WORKSPACE_APP_MANIFESTS[(app_id, version)].as_dict()
        assert payload["routes"] == ["/hypervisor/mission-room"]
        assert payload["experience"]["default_route"] == (
            "/hypervisor/mission-room/cockpit"
        )


def test_generic_provider_is_declared_only_by_a_new_immutable_manifest_version():
    previous = BUILTIN_WORKSPACE_APP_MANIFESTS[
        ("mission-room.extension", "1.1.0")
    ].as_dict()["experience"]["mission_room"]
    provider = BUILTIN_WORKSPACE_APP_MANIFESTS[
        ("mission-room.extension", "1.2.0")
    ].as_dict()["experience"]["mission_room"]

    assert "provider_kind" not in previous
    assert "provider_endpoints" not in previous
    assert provider["provider_kind"] == "workspace_objects_v1"
    assert provider["provider_endpoints"] == [
        "GET /overview",
        "GET /navigation",
        "GET /cockpit",
        "GET /briefing",
        "GET /timeline",
        "GET /projects",
        "GET /decisions",
        "GET /library",
        "GET /search",
        "GET /map",
        "GET /monitor",
        "GET /news",
        "POST /actions/draft",
    ]

    tampered_endpoint = deepcopy(
        BUILTIN_WORKSPACE_APP_MANIFESTS[
            ("mission-room.extension", "1.2.0")
        ].as_dict()
    )
    tampered_endpoint["experience"]["mission_room"]["provider_endpoints"].append(
        "GET /security-monitor"
    )
    with pytest.raises(WorkspaceAppManifestError, match="provider contract"):
        _compile_manifest(tampered_endpoint)

    tampered_source = deepcopy(
        BUILTIN_WORKSPACE_APP_MANIFESTS[
            ("mission-room.extension", "1.2.0")
        ].as_dict()
    )
    tampered_source["experience"]["mission_room"]["profile_source"] = (
        "configuration.assistant_profile"
    )
    with pytest.raises(WorkspaceAppManifestError, match="configuration sources"):
        _compile_manifest(tampered_source)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda payload: payload.__setitem__("action_packs", ["invented_pack_v1"]),
            "Unknown action pack",
        ),
        (
            lambda payload: payload["experience"].__setitem__(
                "default_route", "/outside"
            ),
            "outside declared routes",
        ),
        (
            lambda payload: payload["compatibility"].__setitem__(
                "workspace_families", ["showcase"]
            ),
            "workspace family compatibility",
        ),
        (
            lambda payload: payload.__setitem__("exclusive_routes", False),
            "exclusive route ownership",
        ),
        (
            lambda payload: payload.__setitem__(
                "entitlement_keys", ["Future Surface"]
            ),
            "non-canonical key",
        ),
        (
            lambda payload: payload.__setitem__(
                "api_prefixes", ["/api/v1/unrelated"]
            ),
            "outside the application boundary",
        ),
    ],
)
def test_manifest_compiler_rejects_noncanonical_platform_contracts(mutation, message):
    payload = deepcopy(
        BUILTIN_WORKSPACE_APP_MANIFESTS[("mission-room.extension", "1.1.0")].as_dict()
    )
    mutation(payload)

    with pytest.raises(WorkspaceAppManifestError, match=message):
        _compile_manifest(payload)


def test_new_entitlement_requires_the_registry_schema_contract():
    payload = deepcopy(
        BUILTIN_WORKSPACE_APP_MANIFESTS[("andritz.chat", "1.0.0")].as_dict()
    )
    payload["entitlement_keys"] = ["future-surface"]

    with pytest.raises(WorkspaceAppManifestError, match="require schema 070"):
        _compile_manifest(payload)

    payload["migrations"].append(
        {
            "executor": "platform_schema_contract_v1",
            "id": "workspace_app_platform.entitlement_registry.070",
            "kind": "platform_schema",
            "phase": "precondition",
            "required": True,
            "reversibility": "persistent_additive_schema",
        }
    )
    assert _compile_manifest(payload).as_dict()["entitlement_keys"] == [
        "future-surface"
    ]


@pytest.mark.parametrize(
    ("contract", "executor"),
    [
        ("migrations", "shell_command_v1"),
        ("backfills", "python_import_v1"),
    ],
)
def test_manifest_lifecycle_executors_are_closed(contract, executor):
    payload = deepcopy(
        BUILTIN_WORKSPACE_APP_MANIFESTS[("andritz.chat", "1.0.0")].as_dict()
    )
    payload[contract][0]["executor"] = executor

    with pytest.raises(WorkspaceAppManifestError, match="closed platform schema|explicit safe"):
        _compile_manifest(payload)


@pytest.mark.parametrize(
    "field",
    [
        "api_token",
        "API-TOKEN",
        "ApiToken",
        "password",
        "client.secret",
        "credential",
        "private_key",
        "Private-Key",
    ],
)
def test_manifest_configuration_rejects_credential_shaped_fields(field):
    payload = deepcopy(
        BUILTIN_WORKSPACE_APP_MANIFESTS[("andritz.chat", "1.0.0")].as_dict()
    )
    payload["configuration_contract"]["properties"][field] = {"type": "string"}
    payload["configuration_contract"]["defaults"][field] = "must-not-be-stored"

    with pytest.raises(WorkspaceAppManifestError, match="credential-shaped"):
        _compile_manifest(payload)


@pytest.mark.parametrize(
    "field",
    ["token_budget", "api_contract", "private_sector", "credentialing_status"],
)
def test_manifest_configuration_keeps_innocent_business_fields(field):
    payload = deepcopy(
        BUILTIN_WORKSPACE_APP_MANIFESTS[("andritz.chat", "1.0.0")].as_dict()
    )
    payload["configuration_contract"]["properties"][field] = {"type": "string"}
    payload["configuration_contract"]["defaults"][field] = "business-value"

    assert _compile_manifest(payload).as_dict()["configuration_contract"][
        "properties"
    ][field] == {"type": "string"}
