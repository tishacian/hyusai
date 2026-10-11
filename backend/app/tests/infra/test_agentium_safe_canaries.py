"""Contracts for the direct-VM fallback provenance and canary runner."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[4]
COLLECTOR = ROOT / "scripts/agentium_vm_fallback_attestation.py"
RUNNER = ROOT / "scripts/run-agentium-safe-canaries.sh"
LIVE_WORKSPACE_CONTRACT = ROOT / "frontend-ng/e2e/tests/09-live-workspace-contract.spec.ts"
PROTECTED_COLLECTOR = ROOT / "scripts/agentium_deployment_attestation.py"
ANDRITZ_BUILDER = ROOT / "scripts/agentium_andritz_proof.py"
TENANT_BUILDER = ROOT / "scripts/agentium_tenant_proof.py"
SHA = "a" * 40
IMAGE_ID = "sha256:" + "b" * 64
REVISION = "076_decision_scenario_lineage"
DEPLOYMENT_ID = "20260722T170000Z-aaaaaaaaaaaa"
ARTIFACT_KEY = "membrane/andritz/provenance.json"
ARTIFACT_CONTENT_SHA256 = "e" * 64
ARTIFACT_SIZE = 321
RUN_ID = "11111111-1111-4111-8111-111111111111"
WORKSPACE_ID = "22222222-2222-4222-8222-222222222222"
SYSTEM_ID = "44444444-4444-4444-8444-444444444444"
CAPABILITY_ID = "55555555-5555-4555-8555-555555555555"
KNOWLEDGE_COLLECTION_ID = "66666666-6666-4666-8666-666666666666"
CHAT_LINEAGE_CHECK_NAMES = (
    "workspace_exists",
    "workspace_is_andritz",
    "workspace_family_is_andritz",
    "run_exists",
    "run_completed",
    "trigger_is_strict_agentic_chat",
    "input_marker_present",
    "system_exists",
    "system_is_active_andritz_system",
    "system_type_is_agentic_chat",
    "system_flow_variant_is_agentic_chat",
    "run_flow_variant_matches_system",
    "migration_marker_targets_system",
    "run_capability_matches_system",
    "capability_exists",
    "capability_is_visible_to_andritz",
    "chat_execution_routes_agentic",
    "chat_execution_targets_system",
    "chat_execution_variant_is_agentic_chat",
    "system_retrieval_contract_is_andritz",
    "run_retrieval_contract_is_andritz",
    "knowledge_collection_exists",
    "knowledge_collection_is_ready",
    "knowledge_collection_has_chunks",
)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _storage_canary_comparison() -> dict[str, object]:
    empty = _canonical_sha256([])
    object_fields = ["path_sha256", "size", "content_sha256"]
    minio_fields = [
        "object_id_sha256",
        "version_id_sha256",
        "size",
        "etag_sha256",
        "last_modified",
        "is_latest",
        "delete_marker",
    ]
    stable_fields = [
        "source",
        "normalized_source",
        "expected_source",
        "source_matches_expected",
        "target",
        "fstype",
        "device_id",
    ]
    check_names = [
        "secure_deposit.aggregate",
        "object_store_bindings",
        "qdrant.inventory",
        "container_mounts",
        "object_store.algorithm",
        "object_store.entry_fields",
        "object_store.preexisting_entries_preserved",
        "minio.bucket_id_sha256",
        "minio.versioning_status",
        "minio.algorithm",
        "minio.entry_fields",
        "minio.preexisting_entries_preserved",
        "minio.preexisting_object_keys_not_reversioned",
        "minio.no_delete_marker_additions",
        "minio.delete_markers_unchanged",
        *[
            f"mounts.{mount}.{field}"
            for mount in ("data", "secure_deposit")
            for field in stable_fields
        ],
    ]
    entry = {
        "path_sha256": hashlib.sha256(ARTIFACT_KEY.encode()).hexdigest(),
        "size": ARTIFACT_SIZE,
        "content_sha256": ARTIFACT_CONTENT_SHA256,
    }
    return {
        "schema_version": 1,
        "profile": "agentium-storage-object-additions-v1",
        "assurance": "cryptographic_entry_inclusion",
        "result": "passed",
        "failed_checks": [],
        "checks": [{"name": name, "passed": True} for name in check_names],
        "additions": {
            "object_store": {
                "count": 1,
                "bytes": ARTIFACT_SIZE,
                "entry_fields": object_fields,
                "entries": [entry],
                "digest": _canonical_sha256([entry]),
            },
            "minio": {
                "count": 0,
                "bytes": 0,
                "entry_fields": minio_fields,
                "entries": [],
                "digest": empty,
            },
        },
        "deletions": {
            "object_store": {
                "count": 0,
                "bytes": 0,
                "entry_fields": object_fields,
                "entries": [],
                "digest": empty,
            },
            "minio": {
                "count": 0,
                "bytes": 0,
                "entry_fields": minio_fields,
                "entries": [],
                "digest": empty,
            },
        },
        "modifications": {
            "object_store": {
                "count": 0,
                "entry_fields": [
                    "path_sha256",
                    "before_entry_sha256",
                    "after_entry_sha256",
                ],
                "entries": [],
                "digest": empty,
            },
            "minio": {
                "count": 0,
                "entry_fields": [
                    "object_id_sha256",
                    "version_id_sha256",
                    "before_entry_sha256",
                    "after_entry_sha256",
                ],
                "entries": [],
                "digest": empty,
            },
        },
    }


def _load_collector() -> ModuleType:
    name = "agentium_vm_fallback_attestation_test"
    spec = importlib.util.spec_from_file_location(name, COLLECTOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_script(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def collector() -> ModuleType:
    return _load_collector()


def _deployment(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir(mode=0o700)
    deployment = tmp_path / DEPLOYMENT_ID
    proofs = deployment / "proofs"
    proofs.mkdir(parents=True, mode=0o700)
    (deployment / "phase").write_text("validation_pending\n", encoding="utf-8")
    helper = deployment / "agentium-maintenance-gate.sh"
    helper.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    helper.chmod(0o700)
    marker = tmp_path / "deploy-maintenance"
    marker.write_text("closed\n", encoding="utf-8")
    return repo, deployment, marker


class FakeRunner:
    def __init__(
        self,
        *,
        dirty: str = "",
        sftp_running: bool = False,
        service_revision: str = SHA,
        backend_revision: str = SHA,
        celery_beat: str = "0",
        legacy_state: str = "inactive",
        legacy_sftp_state: str = "inactive",
        legacy_sftp_unit_file_state: str = "disabled",
        listener_ports: tuple[int, ...] = (),
        udp_listener_ports: tuple[int, ...] = (),
        p4_state: str = "created",
        livekit_state: str = "absent",
        livekit_udp_start: str = "50000",
        livekit_udp_end: str = "50100",
    ) -> None:
        self.dirty = dirty
        self.sftp_running = sftp_running
        self.service_revision = service_revision
        self.backend_revision = backend_revision
        self.celery_beat = celery_beat
        self.legacy_state = legacy_state
        self.legacy_sftp_state = legacy_sftp_state
        self.legacy_sftp_unit_file_state = legacy_sftp_unit_file_state
        self.listener_ports = listener_ports
        self.udp_listener_ports = udp_listener_ports
        self.p4_state = p4_state
        self.livekit_state = livekit_state
        self.livekit_udp_start = livekit_udp_start
        self.livekit_udp_end = livekit_udp_end
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: list[str], **_: Any) -> str:
        command = tuple(str(value) for value in argv)
        self.calls.append(command)
        if command[:3] == ("git", "rev-parse", "HEAD"):
            return SHA
        if command[:3] == ("git", "branch", "--show-current"):
            return "demo/agentic"
        if command[:3] == ("git", "rev-parse", "refs/remotes/origin/demo/agentic"):
            return SHA
        if command[:3] == ("git", "status", "--porcelain=v1"):
            return self.dirty
        if command[:3] == ("docker", "image", "inspect"):
            return self.service_revision
        if command[:4] == ("docker", "exec", "agentium-backend", "alembic"):
            return f"{REVISION} (head)"
        if command[:2] == ("curl", "--silent"):
            service = "backend" if command[-1].endswith("/api/v1/build-info") else "frontend"
            revision = self.backend_revision if service == "backend" else SHA
            return json.dumps(
                {
                    "service": service,
                    "revision": revision,
                    "revision_verified": True,
                }
            )
        if command[-1:] == ("status",) and command[0].endswith("agentium-maintenance-gate.sh"):
            return "closed"
        if command[:2] == ("docker", "ps"):
            service = (
                command[command.index("--filter") + 1].removeprefix("name=^/").removesuffix("$")
            )
            if service == "agentium-p4-maintenance":
                return f"{service}|{self.p4_state}"
            if service in {"agentium-livekit", "agentium-livekit-agent"}:
                return "" if self.livekit_state == "absent" else f"{service}|{self.livekit_state}"
            return ""
        if command == (
            "docker",
            "inspect",
            "--format",
            "{{json .Config.Env}}",
            "agentium-worker-cpu",
        ):
            return json.dumps([f"CELERY_BEAT={self.celery_beat}", "PRIVATE_VALUE=not-persisted"])
        if command == (
            "docker",
            "inspect",
            "--format",
            "{{json .Config.Env}}",
            "agentium-livekit",
        ):
            return json.dumps(
                [
                    f"LIVEKIT_RTC_UDP_RANGE_START={self.livekit_udp_start}",
                    f"LIVEKIT_RTC_UDP_RANGE_END={self.livekit_udp_end}",
                    "PRIVATE_VALUE=not-persisted",
                ]
            )
        if command[:3] == ("docker", "inspect", "--format"):
            if command[-1] == "agentium-sftp":
                return f"{'true' if self.sftp_running else 'false'}|created"
            return f"true|{IMAGE_ID}"
        if command[:2] == ("systemctl", "show"):
            service = command[2]
            property_name = command[command.index("--property") + 1]
            if service == "agentium-backend" and property_name == "ActiveState":
                return self.legacy_state
            if service == "agentium-sftp" and property_name == "ActiveState":
                return self.legacy_sftp_state
            if service == "agentium-sftp" and property_name == "UnitFileState":
                return self.legacy_sftp_unit_file_state
        if command[:3] == ("ss", "-H", "-ltn"):
            ports = (8001, *self.listener_ports)
            return "\n".join(f"LISTEN 0 4096 127.0.0.1:{port} 0.0.0.0:*" for port in ports)
        if command[:3] == ("ss", "-H", "-lun"):
            return "\n".join(
                f"UNCONN 0 0 0.0.0.0:{port} 0.0.0.0:*" for port in self.udp_listener_ports
            )
        raise AssertionError(f"unexpected command: {command}")


def _collect(
    collector: ModuleType,
    tmp_path: Path,
    runner: FakeRunner,
) -> tuple[dict[str, Any], Path]:
    repo, deployment, marker = _deployment(tmp_path)
    payload = collector.collect_fallback_attestation(
        sha=SHA,
        branch="demo/agentic",
        alembic_revision=REVISION,
        repo_dir=repo,
        deployment_dir=deployment,
        runner=runner,
        gate_marker_path=marker,
    )
    return payload, deployment


def test_fallback_collector_proves_sha_images_build_info_db_gate_and_stopped_sftp(
    collector: ModuleType,
    tmp_path: Path,
) -> None:
    payload, _ = _collect(collector, tmp_path, FakeRunner())

    assert payload["outcome"] == "passed"
    assert payload["commit_sha"] == SHA
    assert payload["kind"] == "vm_fallback_provenance"
    assert payload["trust_boundary"] == "direct_operator_vm_fallback"
    assert payload["promotion_ceiling"] == "runner_verified"
    assert payload["database_heads"] == [REVISION]
    assert payload["maintenance"] == {
        "state": "closed",
        "marker_present": True,
        "sftp_running": False,
        "sftp_state": "created",
        "legacy_sftp_systemd": "inactive",
        "legacy_sftp_unit_file_state": "disabled",
        "sftp_required_before_public_reopen": True,
    }
    assert len(payload["services"]) == 3
    assert all(row["image_id"] == IMAGE_ID for row in payload["services"])
    assert payload["writer_exclusion"] == {
        "celery_beat": "0",
        "legacy_backend_systemd": "inactive",
        "legacy_backend_listener_count": 0,
        "p4_maintenance_state": "created",
        "livekit_state": "absent",
        "livekit_agent_state": "absent",
        "livekit_listener_count": 0,
        "livekit_udp_range_start": 50000,
        "livekit_udp_range_end": 50100,
        "livekit_udp_listener_count": 0,
    }
    assert "not-persisted" not in json.dumps(payload)
    assert all(check["passed"] is True for check in payload["checks"].values())


@pytest.mark.parametrize(
    ("runner", "failed_check"),
    [
        (FakeRunner(dirty="?? local-secret.txt"), "vm.checkout_clean"),
        (FakeRunner(sftp_running=True), "sftp.stopped"),
        (FakeRunner(service_revision="c" * 40), "oci.agentium-backend.revision"),
        (FakeRunner(backend_revision="d" * 40), "backend.build_info.revision"),
        (FakeRunner(celery_beat="1"), "worker.celery_beat"),
        (FakeRunner(legacy_state="active"), "legacy_backend.systemd_inactive"),
        (FakeRunner(legacy_sftp_state="active"), "legacy_sftp.systemd_inactive"),
        (
            FakeRunner(legacy_sftp_unit_file_state="enabled"),
            "legacy_sftp.systemd_disabled",
        ),
        (FakeRunner(listener_ports=(8000,)), "legacy_backend.no_listener_8000"),
        (FakeRunner(p4_state="running"), "p4_maintenance.stopped"),
        (FakeRunner(livekit_state="running"), "livekit.container_stopped"),
        (FakeRunner(listener_ports=(7881,)), "livekit.no_listener_7881"),
        (
            FakeRunner(livekit_state="created", livekit_udp_start="invalid"),
            "livekit.udp_range_valid",
        ),
        (
            FakeRunner(udp_listener_ports=(50042,)),
            "livekit.no_udp_listener_in_configured_range",
        ),
    ],
)
def test_fallback_collector_fails_closed_on_identity_or_writer_drift(
    collector: ModuleType,
    tmp_path: Path,
    runner: FakeRunner,
    failed_check: str,
) -> None:
    payload, _ = _collect(collector, tmp_path, runner)

    assert payload["outcome"] == "failed"
    assert payload["checks"][failed_check]["passed"] is False
    assert "local-secret.txt" not in json.dumps(payload)


def test_fallback_output_is_fixed_atomic_private_and_validator_compatible(
    collector: ModuleType,
    tmp_path: Path,
) -> None:
    payload, deployment = _collect(collector, tmp_path, FakeRunner())
    output = deployment / "proofs" / "provenance.json"

    collector.write_attestation(output, payload, deployment)

    assert output.stat().st_mode & 0o777 == 0o600
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["outcome"] == "passed"
    assert written["commit_sha"] == SHA
    assert all(row["passed"] is True for row in written["checks"].values())
    with pytest.raises(collector.FallbackAttestationError, match="fixed deployment path"):
        collector.write_attestation(deployment / "other.json", payload, deployment)


def test_fallback_collector_does_not_weaken_protected_gitlab_attestation() -> None:
    fallback = COLLECTOR.read_text(encoding="utf-8")
    protected = PROTECTED_COLLECTOR.read_text(encoding="utf-8")

    assert "protected_ci_identity" not in fallback
    assert "CI_COMMIT_REF_PROTECTED" not in fallback
    assert "direct_operator_vm_fallback" in fallback
    assert "CI_COMMIT_REF_PROTECTED" in protected
    assert "protected GitLab ref" in protected


def test_safe_canary_runner_has_separate_tenant_proofs_and_no_secret_cli() -> None:
    script = RUNNER.read_text(encoding="utf-8")

    assert RUNNER.stat().st_mode & 0o111
    subprocess.run(["bash", "-n", str(RUNNER)], check=True)
    assert "--password" not in script
    assert "--token" not in script
    assert 'export PATH="$CANARY_CLEAN_PATH"' in script
    assert "export PYTHONDONTWRITEBYTECODE=1" in script
    assert "unset PYTHONBREAKPOINT PYTHONHOME PYTHONINSPECT PYTHONOPTIMIZE" in script
    assert "assert_python_runtime" in script
    assert "sys.flags.optimize" in script
    assert "workspace-contract.xml" not in script
    for tenant in ("andritz", "sentinel", "octocity"):
        assert f"run_workspace_suite {tenant} " in script
    assert 'local junit="$PROOFS_DIR/$tenant.xml"' in script
    assert "E2E_LIVE_FORCE_REFRESH" in script
    assert "a forced access-token expiry" in script
    assert 'E2E_BASE_URL="https://agentium.papai.ai"' in script
    assert "MAP agentium.papai.ai 127.0.0.2" in script
    assert "--resolve agentium.papai.ai:443:127.0.0.1" in script
    assert "--resolve agentium.papai.ai:443:127.0.0.2" in script
    assert "E2E_HOST_RESOLVER_RULES" in script
    assert "--reporter=junit" in script
    assert '"$(node --version)" =~ ^v22\\.' in script
    assert 'LOCK_PATH="$STATE_ROOT/.agentium-deploy.lock"' in script
    assert "AGENTIUM_SAFE_DEPLOY_LOCK" not in script
    assert '[[ ! -L "$LOCK_PATH"' in script
    assert "flock -n 9" in script


def _workspace_target_payload() -> dict[str, Any]:
    identities = {
        "showcase": ("11111111-1111-4111-8111-111111111111", "alpha"),
        "andritz": ("22222222-2222-4222-8222-222222222222", "bravo"),
        "sentinel": ("33333333-3333-4333-8333-333333333333", "charlie"),
        "octocity": ("44444444-4444-4444-8444-444444444444", "delta"),
    }
    selectors = {
        "showcase": {"showcase_seed": True},
        "andritz": {"family": "andritz"},
        "sentinel": {
            "family": "sentinel_ci",
            "mission_room_enabled": True,
            "mission_room_profile": "sentinel_government_v1",
            "assistant_profile": "vigie_executive",
        },
        "octocity": {
            "family": "generic",
            "mission_room_enabled": True,
            "mission_room_profile": "octocity_institutional_v1",
            "assistant_profile": "octave_executive",
        },
    }
    return {
        "schema_version": 2,
        "profile": "agentium-workspace-target-gate-v2",
        "candidate_sha": SHA,
        "deployment_id": DEPLOYMENT_ID,
        "selection": "explicit_operator_workspace_ids",
        "operator_workspace_ids": sorted(identity[0] for identity in identities.values()),
        "targets": {
            role: {
                "workspace_id": identity[0],
                "workspace_slug": identity[1],
                "selector": selectors[role],
            }
            for role, identity in identities.items()
        },
    }


def _workspace_target_validator_source() -> str:
    script = RUNNER.read_text(encoding="utf-8")
    body = script.split("load_workspace_targets() {", 1)[1].split(
        "\n}\n\nload_workspace_targets", 1
    )[0]
    return body.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]


def _validate_workspace_target_payload(tmp_path: Path, payload: dict[str, Any]):
    target = tmp_path / "workspace-targets.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-", str(target), SHA, DEPLOYMENT_ID],
        input=_workspace_target_validator_source(),
        text=True,
        capture_output=True,
        check=False,
    )


def test_safe_canary_workspace_targets_are_private_bound_and_dynamic(tmp_path: Path) -> None:
    script = RUNNER.read_text(encoding="utf-8")
    contract = LIVE_WORKSPACE_CONTRACT.read_text(encoding="utf-8")
    database_audit = (ROOT / "backend/scripts/audit_post_canary_database.py").read_text(
        encoding="utf-8"
    )
    validator = (ROOT / "scripts/agentium_safe_validation.py").read_text(
        encoding="utf-8"
    )

    assert 'WORKSPACE_TARGETS="$DEPLOY_DIR/workspace-targets.json"' in script
    assert "workspace_targets_sha256" in script
    assert "stat -c '%a:%u:%h'" in script
    assert "agentium-workspace-target-gate-v2" in script
    for role in ("SHOWCASE", "ANDRITZ", "SENTINEL", "OCTOCITY"):
        assert f'E2E_{role}_WORKSPACE_ID="${role}_WORKSPACE_ID"' in script
        assert f'E2E_{role}_WORKSPACE_SLUG="${role}_WORKSPACE_SLUG"' in script
    assert "E2E_WORKSPACE_SLUG" not in script
    assert "WORKSPACE_SLUG=andritz" not in script
    assert "workspace.id === targetWorkspace.id" in contract
    assert "workspace.slug === targetWorkspace.slug" in contract
    assert "workspace target UUIDs must be unique" in contract
    assert "workspace target slugs must be unique" in contract
    for fixed_slug in ("agentium-showcase", "sentinel-ci", "octocity-mission-room"):
        assert fixed_slug not in database_audit
        assert fixed_slug not in validator
    assert "_workspace_target_hashes" in validator
    assert "expected_canary_identities" in validator

    result = _validate_workspace_target_payload(tmp_path, _workspace_target_payload())
    assert result.returncode == 0, result.stderr
    fields = result.stdout.strip().split("\t")
    assert len(fields) == 8
    assert fields[0:2] == [
        "11111111-1111-4111-8111-111111111111",
        "alpha",
    ]


@pytest.mark.parametrize(
    "mutation",
    ("legacy_schema", "wrong_sha", "duplicate_slug", "missing_id", "wrong_selector"),
)
def test_safe_canary_workspace_target_loader_fails_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    payload = _workspace_target_payload()
    if mutation == "legacy_schema":
        payload["schema_version"] = 1
    elif mutation == "wrong_sha":
        payload["candidate_sha"] = "b" * 40
    elif mutation == "duplicate_slug":
        payload["targets"]["octocity"]["workspace_slug"] = "alpha"
    elif mutation == "missing_id":
        del payload["targets"]["sentinel"]["workspace_id"]
    else:
        payload["targets"]["andritz"]["selector"] = {"family": "generic"}

    result = _validate_workspace_target_payload(tmp_path, payload)
    assert result.returncode != 0


def test_live_workspace_canaries_are_testcase_sha_bound_and_content_free() -> None:
    runner = RUNNER.read_text(encoding="utf-8")
    contract = LIVE_WORKSPACE_CONTRACT.read_text(encoding="utf-8")

    assert 'E2E_EXPECTED_SHA="$EXPECTED_SHA" E2E_SAFE_CONTENT_FREE=1' in runner
    assert "assert_workspace_junit_identity" in runner
    assert 'node.attrib.get("name") == "commit_sha"' in runner
    assert "workspace JUnit testcase is not exactly SHA-bound" in runner
    assert "Le canari content-free a conservé un média métier" in runner
    assert "workspace JUnit contains retained console output" in runner
    assert 'rm -f -- "$junit" "$log"' in runner
    assert 'rm -rf -- "$output_dir"' in runner
    assert "$PROOFS_DIR/$tenant.log" not in runner
    assert "testInfo.annotations.push({ type: 'commit_sha', description: revision })" in contract
    assert "readBuildInfo('/api/v1/build-info')" in contract
    assert "readBuildInfo('/build-info.json')" in contract
    assert "if (safeContentFree) return" in contract
    assert "body: JSON.stringify({ dry_run: true })" in contract
    assert "client360DryRunProjection" in contract
    assert "crossTenantSystemIsolationProjection" in contract
    assert "crossTenantReadStatus: 404" in contract
    # Post-Release B baseline: the Andritz workspace ships three apps through
    # four entitled surfaces (FSE reports rides the capture router).  The
    # content-free read-only projection and the lot 9 installations endpoint
    # are part of the contract — both are read-only and identity-free.
    assert "Andritz business preview exposes three apps through four entitled surfaces" in runner
    assert "the four Andritz surfaces survive deep links, history and reload" in runner
    assert "the three Andritz surfaces" not in runner
    assert "andritzReadOnlySurfaceProjection" in contract
    assert "/governance/workspace-apps/installations" in contract


def test_system360_canary_binds_runtime_and_retains_only_content_free_json() -> None:
    runner = RUNNER.read_text(encoding="utf-8")
    contract = (ROOT / "frontend-ng/e2e/tests/11-system360-canary.spec.ts").read_text(
        encoding="utf-8"
    )
    if "playwright_runtime: playwrightRuntime()" not in contract:
        pytest.skip("Release B System 360 runtime attestation is outside Release A")
    body = runner.split("run_system360_suite() {", 1)[1].split("\n}", 1)[0]

    assert "attest_playwright_runtime" in runner
    assert 'E2E_PLAYWRIGHT_RUNTIME_ATTESTATION="$PLAYWRIGHT_RUNTIME"' in body
    assert "E2E_SAFE_CONTENT_FREE=1" in body
    assert 'rm -f -- "$junit" "$log"' in body
    assert 'rm -rf -- "$output_dir"' in body
    assert "Le canari System 360 a conservé un média" in body
    assert "playwright_runtime: playwrightRuntime()" in contract
    assert "process.env['E2E_SAFE_CONTENT_FREE'] !== '1'" in contract
    assert "chromium_executable_sha256" in contract


def test_safe_canary_runner_keeps_writers_closed_and_hands_off_bound_proofs() -> None:
    script = RUNNER.read_text(encoding="utf-8")

    assert '"$(<"$PHASE_FILE")" == "validation_pending"' in script
    assert '"$MAINTENANCE_HELPER" status' in script
    assert "agentium-sftp agentium-p4-maintenance" in script
    assert '"$state" == "created" || "$state" == "exited"' in script
    assert "gate exit" not in script
    assert "docker start" not in script
    assert "docker compose up" not in script
    assert "agentium_vm_fallback_attestation.py" in script
    # The state-changing orchestrator is the sole owner of the final database
    # recapture, validation build and verification. This read-only runner only
    # emits the tenant/storage inputs while every ingress remains closed.
    assert '"$VALIDATION_HELPER" build' not in script
    assert '"$VALIDATION_HELPER" verify' not in script
    assert "validation finale, gate et SFTP restent fermés" in script
    assert "storage-quiesced.json" in script
    assert "storage-after.json" in script
    assert "storage-comparison.json" in script
    assert "storage-post-canary.json" in script
    assert "storage-canary-comparison.json" in script
    refresh_storage = script.split("refresh_storage_proof() {", 1)[1].split("\n}", 1)[0]
    assert 'sudo -n python3 "$STORAGE_HELPER" snapshot' in refresh_storage
    assert 'sudo -n chown "$owner" "$STORAGE_POST_CANARY"' in refresh_storage
    assert "compare --allow-object-additions" in refresh_storage
    assert '--before "$STORAGE_AFTER" --after "$STORAGE_POST_CANARY"' in refresh_storage
    assert '--output "$STORAGE_CANARY_COMPARISON"' in refresh_storage
    assert '--object-store "$object_store"' in refresh_storage
    for container in (
        "agentium-backend",
        "agentium-worker-cpu",
        "agentium-rabbitmq",
        "agentium-p4-maintenance",
    ):
        assert f"--container {container}" in refresh_storage
    assert "E2E_USERNAME" not in refresh_storage and "E2E_PASSWORD" not in refresh_storage
    assert "CELERY_BEAT=0" in script
    assert "systemctl show agentium-backend" in script
    assert ":8000" in script
    assert "agentium-livekit-agent" in script and "agentium-livekit" in script
    assert ":7881" in script
    assert "systemctl show agentium-sftp" in script
    assert "systemctl is-enabled agentium-sftp" in script
    assert "LIVEKIT_RTC_UDP_RANGE_START" in script
    assert "LIVEKIT_RTC_UDP_RANGE_END" in script
    assert "container_env_value agentium-livekit LIVEKIT_RTC_UDP_RANGE_START" in script
    assert "ss -H -lun" in script
    assert 'SFTP_BOUNDARY_HELPER="$DEPLOY_DIR/audit_sftp_deploy_boundary.py"' in script
    assert "SFTP_HELPER_BLOB" in script
    closed = script.split("run_sftp_closed_boundary() {", 1)[1].split("\n}", 1)[0]
    assert "closed-boundary" in closed
    assert '--expected-secure-source "$EXPECTED_SECURE_SOURCE"' in closed
    assert "docker start" not in closed and "docker compose" not in closed
    execution_tail = script.rsplit("assert_candidate_checkout", 1)[1]
    assert execution_tail.index("sftp-closed-before-canaries") < execution_tail.index(
        "run_workspace_suite andritz"
    )
    assert execution_tail.index("collect_provenance_for_safe_resume") < execution_tail.index(
        "sftp-closed-after-canaries"
    )


def test_safe_canary_runner_audits_all_workspaces_and_delivers_one_idempotent_chat() -> None:
    script = RUNNER.read_text(encoding="utf-8")

    assert "scripts.audit_persisted_system_bindings" in script
    binding_call = script.split("run_binding_audit() {", 1)[1].split("\n}", 1)[0]
    assert "--workspace" not in binding_call
    assert 'p.get("workspace_count", 0) >= 3' in binding_call
    assert "PROBE_MODES=auto" in script
    assert "PROBE_RUN_CHAT=1" in script
    assert "PROBE_RUN_STREAM=0" in script
    assert '"exactly_one_controlled_chat"' in script
    assert "controlled-chat-state.json" in script
    assert "redélivrance automatique refusée" in script
    assert "actual_chat_requests" in script
    assert 'log="$(mktemp "$PROOFS_DIR/.spl-probe.XXXXXX.log")"' in script
    assert 'rm -f -- "$raw" "$log"' in script
    assert 'spl-probe.log"' not in script
    assert "scripts.audit_safe_chat_run" in script
    assert '--workspace-id "$ANDRITZ_WORKSPACE_ID"' in script
    assert '"$PROOFS_DIR/chat-ledger.json"' in script
    execution_tail = script.rsplit("assert_candidate_checkout", 1)[1]
    assert (
        execution_tail.index("run_chat_ledger_audit")
        < execution_tail.index("refresh_storage_proof")
        < execution_tail.index("build_tenant_proofs")
        < execution_tail.index("collect_provenance_for_safe_resume")
    )
    for tenant in ("andritz", "sentinel", "octocity"):
        assert f'"$PROOFS_DIR/{tenant}.json"' in script


def _proof_file(path: Path, value: object | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
    path.chmod(0o600)
    return path


def _bundle_fixture(tmp_path: Path) -> Path:
    deployment = tmp_path / DEPLOYMENT_ID
    proofs = deployment / "proofs"
    proofs.mkdir(parents=True, mode=0o700)
    marker_sha256 = hashlib.sha256(
        f"agentium_safe_chat::{DEPLOYMENT_ID}::{SHA[:12]}".encode()
    ).hexdigest()
    _proof_file(deployment / "storage-canary-comparison.json", _storage_canary_comparison())
    andritz_titles = (
        "Andritz business preview exposes the three-app shell",
        "the three Andritz surfaces survive deep links, history and reload",
        "a forced access-token expiry retries inside the selected workspace",
        "business preview redirects advanced routes while admin mode keeps the full cockpit",
        "deployed Andritz profile, entitlements and active Systems match the Lot 4 contract",
        "resolved navigation is persisted with canonical routes and no user identity",
    )
    andritz_cases = "".join(
        f'<testcase name="{title}"><properties>'
        f'<property name="commit_sha" value="{SHA}" />'
        "</properties></testcase>"
        for title in andritz_titles
    )
    _proof_file(
        proofs / "andritz.xml",
        '<testsuite tests="6" failures="0" errors="0" skipped="0">' f"{andritz_cases}</testsuite>",
    )
    for tenant, title in {
        "sentinel": "Sentinel workspace keeps its immersive Mission Room shell",
        "octocity": "Octocity workspace keeps its immersive Mission Room shell",
    }.items():
        _proof_file(
            proofs / f"{tenant}.xml",
            '<testsuite tests="1" failures="0" errors="0" skipped="0">'
            f'<testcase name="{title}"><properties>'
            f'<property name="commit_sha" value="{SHA}" />'
            "</properties></testcase></testsuite>",
        )
    _proof_file(
        proofs / "runtime-bindings.json",
        {
            "result": "passed",
            "requested_workspace_slugs": [],
            "missing_workspace_slugs": [],
            "workspace_count": 4,
        },
    )
    _proof_file(
        proofs / "spl-probe.json",
        {
            "kind": "andritz_spl_controlled_probe",
            "outcome": "passed",
            "commit_sha": SHA,
            "deployment_id": DEPLOYMENT_ID,
            "actual_chat_requests": 1,
            "run_id": RUN_ID,
            "input_marker_sha256": marker_sha256,
            "checks": {"chat": {"passed": True}},
        },
    )
    _proof_file(
        proofs / "controlled-chat-state.json",
        {
            "kind": "controlled_chat_delivery",
            "status": "completed",
            "commit_sha": SHA,
            "deployment_id": DEPLOYMENT_ID,
            "attempt_ceiling": 1,
            "actual_chat_requests": 1,
            "run_id": RUN_ID,
            "input_marker_sha256": marker_sha256,
        },
    )
    _proof_file(
        proofs / "chat-ledger.json",
        {
            "schema_version": 2,
            "kind": "safe_controlled_chat_ledger",
            "outcome": "passed",
            "commit_sha": SHA,
            "deployment_id": DEPLOYMENT_ID,
            "run_id": RUN_ID,
            "workspace_id": WORKSPACE_ID,
            "system_id": SYSTEM_ID,
            "capability_id": CAPABILITY_ID,
            "knowledge_collection_id": KNOWLEDGE_COLLECTION_ID,
            "input_marker_sha256": marker_sha256,
            "input_query_sha256": "b" * 64,
            "run_trigger_sha256": "c" * 64,
            "system_type_sha256": "1" * 64,
            "flow_variant_sha256": "2" * 64,
            "retrieval_contract_sha256": "3" * 64,
            "knowledge_collection_slug_sha256": "4" * 64,
            "knowledge_collection_chunk_count": 87,
            "run_status_counts": {"completed": 1},
            "invocation_count": 3,
            "invocation_ids": [
                "33333333-3333-4333-8333-333333333331",
                "33333333-3333-4333-8333-333333333332",
                "33333333-3333-4333-8333-333333333333",
            ],
            "invocation_status_counts": {"completed": 3},
            "skill_sequence_sha256": "d" * 64,
            "flow_skill_contract_sha256": "a" * 64,
            "read_generation_allowlist_sha256": "b" * 64,
            "unexpected_skill_count": 0,
            "artifact_count": 1,
            "provenance_artifact": {
                "backend": "local",
                "key_sha256": hashlib.sha256(ARTIFACT_KEY.encode()).hexdigest(),
                "content_sha256": ARTIFACT_CONTENT_SHA256,
                "size": ARTIFACT_SIZE,
            },
            "checks": {
                "ledger": {"passed": True},
                **{name: {"passed": True} for name in CHAT_LINEAGE_CHECK_NAMES},
            },
        },
    )
    return deployment


def test_composite_tenant_proofs_are_distinct_sha_bound_and_content_free(
    tmp_path: Path,
) -> None:
    andritz_module = _load_script(ANDRITZ_BUILDER, "agentium_andritz_proof_test")
    tenant_module = _load_script(TENANT_BUILDER, "agentium_tenant_proof_test")
    deployment = _bundle_fixture(tmp_path)

    andritz = andritz_module.build_andritz_proof(
        candidate_sha=SHA,
        deployment_dir=deployment,
    )
    sentinel = tenant_module.build_tenant_proof(
        tenant_key="sentinel",
        candidate_sha=SHA,
        deployment_dir=deployment,
    )
    octocity = tenant_module.build_tenant_proof(
        tenant_key="octocity",
        candidate_sha=SHA,
        deployment_dir=deployment,
    )

    assert andritz["actual_chat_requests"] == 1
    assert andritz["schema_version"] == 2
    assert andritz["invocation_count"] == 3
    assert andritz["workspace_test_count"] == 6
    assert andritz["system_id"] == SYSTEM_ID
    assert andritz["capability_id"] == CAPABILITY_ID
    assert andritz["knowledge_collection_id"] == KNOWLEDGE_COLLECTION_ID
    assert andritz["knowledge_collection_chunk_count"] == 87
    assert set(andritz["evidence"]) == set(andritz_module.INPUTS)
    assert sentinel["tenant_key"] == "sentinel"
    assert octocity["tenant_key"] == "octocity"
    digests = {
        hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        for value in (andritz, sentinel, octocity)
    }
    assert len(digests) == 3
    serialized = json.dumps(andritz).lower()
    for forbidden in ("query", "answer", "citation"):
        assert f'"{forbidden}":' not in serialized


def test_andritz_composite_rejects_chat_or_ledger_omission(tmp_path: Path) -> None:
    module = _load_script(ANDRITZ_BUILDER, "agentium_andritz_proof_failure_test")
    deployment = _bundle_fixture(tmp_path)
    ledger_path = deployment / "proofs" / "chat-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["invocation_count"] = 0
    _proof_file(ledger_path, ledger)

    with pytest.raises(module.AndritzProofError, match="SkillInvocation"):
        module.build_andritz_proof(candidate_sha=SHA, deployment_dir=deployment)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("legacy_schema", "lineage contract"),
        ("missing_check", "lineage contract"),
        ("missing_system", "System id"),
        ("empty_collection", "lineage contract"),
    ],
)
def test_andritz_composite_requires_strict_postgresql_chat_lineage(
    tmp_path: Path,
    mutation: str,
    match: str,
) -> None:
    module = _load_script(ANDRITZ_BUILDER, f"andritz_lineage_{mutation}_test")
    deployment = _bundle_fixture(tmp_path)
    ledger_path = deployment / "proofs" / "chat-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if mutation == "legacy_schema":
        ledger["schema_version"] = 1
    elif mutation == "missing_check":
        del ledger["checks"]["chat_execution_targets_system"]
    elif mutation == "missing_system":
        ledger["system_id"] = None
    else:
        ledger["knowledge_collection_chunk_count"] = 0
    _proof_file(ledger_path, ledger)

    with pytest.raises(module.AndritzProofError, match=match):
        module.build_andritz_proof(candidate_sha=SHA, deployment_dir=deployment)


def test_tenant_composites_reject_a_filtered_binding_audit(tmp_path: Path) -> None:
    andritz_module = _load_script(ANDRITZ_BUILDER, "andritz_filtered_audit_test")
    tenant_module = _load_script(TENANT_BUILDER, "tenant_filtered_audit_test")
    deployment = _bundle_fixture(tmp_path)
    bindings_path = deployment / "proofs" / "runtime-bindings.json"
    bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    bindings["requested_workspace_slugs"] = ["andritz"]
    _proof_file(bindings_path, bindings)

    with pytest.raises(andritz_module.AndritzProofError, match="binding audit"):
        andritz_module.build_andritz_proof(
            candidate_sha=SHA,
            deployment_dir=deployment,
        )
    with pytest.raises(tenant_module.TenantProofError, match="binding audit"):
        tenant_module.build_tenant_proof(
            tenant_key="sentinel",
            candidate_sha=SHA,
            deployment_dir=deployment,
        )


def test_tenant_composite_rejects_an_unrelated_green_junit(tmp_path: Path) -> None:
    module = _load_script(TENANT_BUILDER, "tenant_unrelated_junit_test")
    deployment = _bundle_fixture(tmp_path)
    _proof_file(
        deployment / "proofs" / "sentinel.xml",
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase name="unrelated green test" /></testsuite>',
    )

    with pytest.raises(module.TenantProofError, match="expected tenant canary"):
        module.build_tenant_proof(
            tenant_key="sentinel",
            candidate_sha=SHA,
            deployment_dir=deployment,
        )


@pytest.mark.parametrize("mutation", ["missing", "wrong", "suite_only", "duplicate"])
def test_tenant_composite_requires_testcase_local_candidate_sha(
    tmp_path: Path,
    mutation: str,
) -> None:
    module = _load_script(TENANT_BUILDER, f"tenant_sha_{mutation}_test")
    deployment = _bundle_fixture(tmp_path)
    junit_path = deployment / "proofs" / "sentinel.xml"
    root = ElementTree.fromstring(junit_path.read_bytes())
    testcase = root.find("testcase")
    assert testcase is not None
    properties = testcase.find("properties")
    assert properties is not None
    binding = properties.find("property")
    assert binding is not None
    if mutation == "missing":
        properties.remove(binding)
    elif mutation == "wrong":
        binding.set("value", "c" * 40)
    elif mutation == "suite_only":
        properties.remove(binding)
        suite_properties = ElementTree.Element("properties")
        ElementTree.SubElement(
            suite_properties,
            "property",
            {"name": "commit_sha", "value": SHA},
        )
        root.insert(0, suite_properties)
    else:
        ElementTree.SubElement(
            properties,
            "property",
            {"name": "commit_sha", "value": SHA},
        )
    _proof_file(junit_path, ElementTree.tostring(root, encoding="unicode"))

    with pytest.raises(module.TenantProofError, match="SHA|candidate"):
        module.build_tenant_proof(
            tenant_key="sentinel",
            candidate_sha=SHA,
            deployment_dir=deployment,
        )


@pytest.mark.parametrize("tenant_key", ["andritz", "sentinel"])
def test_composite_builders_reject_retained_workspace_console_output(
    tmp_path: Path,
    tenant_key: str,
) -> None:
    deployment = _bundle_fixture(tmp_path)
    junit_path = deployment / "proofs" / f"{tenant_key}.xml"
    root = ElementTree.fromstring(junit_path.read_bytes())
    system_out = ElementTree.SubElement(root, "system-out")
    system_out.text = "rendered business content must not persist"
    _proof_file(junit_path, ElementTree.tostring(root, encoding="unicode"))

    if tenant_key == "andritz":
        module = _load_script(ANDRITZ_BUILDER, "andritz_console_output_test")
        with pytest.raises(module.AndritzProofError, match="console output"):
            module.build_andritz_proof(
                candidate_sha=SHA,
                deployment_dir=deployment,
            )
    else:
        module = _load_script(TENANT_BUILDER, "tenant_console_output_test")
        with pytest.raises(module.TenantProofError, match="console output"):
            module.build_tenant_proof(
                tenant_key=tenant_key,
                candidate_sha=SHA,
                deployment_dir=deployment,
            )


@pytest.mark.parametrize("mutation", ["unrelated", "missing", "duplicate"])
def test_andritz_composite_requires_exact_six_canaries(
    tmp_path: Path,
    mutation: str,
) -> None:
    module = _load_script(ANDRITZ_BUILDER, f"andritz_exact_junit_{mutation}_test")
    deployment = _bundle_fixture(tmp_path)
    junit_path = deployment / "proofs" / "andritz.xml"
    root = ElementTree.fromstring(junit_path.read_bytes())
    cases = list(root.findall("testcase"))
    if mutation == "unrelated":
        cases[0].set("name", "unrelated green test")
    elif mutation == "missing":
        root.remove(cases[-1])
        root.set("tests", "5")
    else:
        cases[-1].set("name", cases[0].attrib["name"])
    _proof_file(junit_path, ElementTree.tostring(root, encoding="unicode"))

    with pytest.raises(module.AndritzProofError, match="exactly the six expected"):
        module.build_andritz_proof(candidate_sha=SHA, deployment_dir=deployment)


@pytest.mark.parametrize("mutation", ["missing", "wrong", "suite_only", "duplicate"])
def test_andritz_composite_requires_testcase_local_candidate_sha(
    tmp_path: Path,
    mutation: str,
) -> None:
    module = _load_script(ANDRITZ_BUILDER, f"andritz_sha_{mutation}_test")
    deployment = _bundle_fixture(tmp_path)
    junit_path = deployment / "proofs" / "andritz.xml"
    root = ElementTree.fromstring(junit_path.read_bytes())
    testcases = root.findall("testcase")
    assert testcases
    first_properties = testcases[0].find("properties")
    assert first_properties is not None
    first_binding = first_properties.find("property")
    assert first_binding is not None
    if mutation == "missing":
        first_properties.remove(first_binding)
    elif mutation == "wrong":
        first_binding.set("value", "c" * 40)
    elif mutation == "suite_only":
        for testcase in testcases:
            properties = testcase.find("properties")
            assert properties is not None
            for binding in list(properties):
                properties.remove(binding)
        suite_properties = ElementTree.Element("properties")
        ElementTree.SubElement(
            suite_properties,
            "property",
            {"name": "commit_sha", "value": SHA},
        )
        root.insert(0, suite_properties)
    else:
        ElementTree.SubElement(
            first_properties,
            "property",
            {"name": "commit_sha", "value": SHA},
        )
    _proof_file(junit_path, ElementTree.tostring(root, encoding="unicode"))

    with pytest.raises(module.AndritzProofError, match="SHA|candidate"):
        module.build_andritz_proof(candidate_sha=SHA, deployment_dir=deployment)


def test_andritz_composite_refuses_persisted_chat_content(tmp_path: Path) -> None:
    module = _load_script(ANDRITZ_BUILDER, "andritz_content_free_test")
    deployment = _bundle_fixture(tmp_path)
    spl_path = deployment / "proofs" / "spl-probe.json"
    spl = json.loads(spl_path.read_text(encoding="utf-8"))
    spl["answer"] = "must never reach a deployment proof"
    _proof_file(spl_path, spl)

    with pytest.raises(module.AndritzProofError, match="persisted content"):
        module.build_andritz_proof(candidate_sha=SHA, deployment_dir=deployment)


def test_storage_addition_binding_supports_targeted_s3_content_verification() -> None:
    module = _load_script(ANDRITZ_BUILDER, "andritz_s3_binding_test")
    comparison = _storage_canary_comparison()
    empty = _canonical_sha256([])
    fields = [
        "object_id_sha256",
        "version_id_sha256",
        "size",
        "etag_sha256",
        "last_modified",
        "is_latest",
        "delete_marker",
    ]
    key_sha256 = hashlib.sha256(ARTIFACT_KEY.encode()).hexdigest()
    entry = [key_sha256, "1" * 64, ARTIFACT_SIZE, "2" * 64, "now", True, False]
    comparison["additions"] = {
        "object_store": {
            "count": 0,
            "bytes": 0,
            "entry_fields": ["path_sha256", "size", "content_sha256"],
            "entries": [],
            "digest": empty,
        },
        "minio": {
            "count": 1,
            "bytes": ARTIFACT_SIZE,
            "entry_fields": fields,
            "entries": [entry],
            "digest": _canonical_sha256([entry]),
        },
    }
    artifact = {
        "backend": "s3",
        "key_sha256": key_sha256,
        "content_sha256": ARTIFACT_CONTENT_SHA256,
        "size": ARTIFACT_SIZE,
    }

    assert module._storage_addition_matches_artifact(comparison, artifact) is True
    artifact["size"] = ARTIFACT_SIZE + 1
    assert module._storage_addition_matches_artifact(comparison, artifact) is False
