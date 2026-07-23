from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
SAFE_DEPLOY = ROOT / "scripts" / "deploy-agentium-safe.sh"
VM_DEPLOY = ROOT / "scripts" / "deploy-vm.sh"
COMPOSE = ROOT / "docker" / "compose.agentium.yml"
QDRANT_OVERRIDE = ROOT / "docker" / "compose.agentium.qdrant-barrier.yml"
OPENED_OVERRIDE = ROOT / "docker" / "compose.agentium.opened.yml"
QDRANT_ENV_EXAMPLE = ROOT / "docker" / "env" / "qdrant.agentium.env.example"
QDRANT_HELPER = ROOT / "backend" / "scripts" / "audit_qdrant_write_barrier.py"

EFFECTIVE_KEY_EXPRESSION = (
    "${AGENTIUM_QDRANT_EFFECTIVE_API_KEY:?safe deployment Qdrant key missing}"
)
QDRANT_CLIENT_SERVICES = {
    "agentium-migrate",
    "agentium-backend",
    "agentium-worker-cpu",
    "agentium-p4-maintenance",
}


def _shell_function(script: str, name: str) -> str:
    marker = f"\n{name}() {{\n"
    assert marker in script
    suffix = script.split(marker, 1)[1]
    body: list[str] = []
    heredoc: str | None = None
    for line in suffix.splitlines(keepends=True):
        if heredoc is not None:
            body.append(line)
            if line.strip() == heredoc:
                heredoc = None
            continue
        if line.rstrip("\n") == "}":
            return "".join(body).rstrip("\n")
        body.append(line)
        match = re.search(
            r"<<-?\s*(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_]*))",
            line,
        )
        if match:
            heredoc = next(group for group in match.groups() if group is not None)
    raise AssertionError(f"shell function {name!r} has no closing brace")


def test_real_compose_overlays_cover_closed_and_opened_store_boundaries() -> None:
    main = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    closed = yaml.safe_load(QDRANT_OVERRIDE.read_text(encoding="utf-8"))
    opened = yaml.safe_load(OPENED_OVERRIDE.read_text(encoding="utf-8"))
    services = main["services"]
    closed_services = closed["services"]
    opened_services = opened["services"]

    assert set(closed_services) == QDRANT_CLIENT_SERVICES | {"agentium-sftp"}
    assert set(opened_services) == QDRANT_CLIENT_SERVICES
    assert set(closed_services) <= set(services)
    assert "agentium-qdrant" not in closed_services
    closed_data_mounts = [
        "${AGENTIUM_OBJECT_STORE_PATH:-/home/ubuntu/agentium-data/object_store}:/data/object_store:ro",
        "${AGENTIUM_SECURE_DEPOSIT_PATH:-/home/ubuntu/omnirag/backend/data/secure_deposit}:/data/secure_deposit:ro",
        "${AGENTIUM_FAISS_PATH:-/home/ubuntu/omnirag/backend/faiss_db}:/data/faiss_db:ro",
    ]
    for service in QDRANT_CLIENT_SERVICES:
        assert closed_services[service]["environment"]["QDRANT_API_KEY"] == EFFECTIVE_KEY_EXPRESSION
        assert opened_services[service]["environment"]["QDRANT_API_KEY"] == EFFECTIVE_KEY_EXPRESSION
        assert closed_services[service]["volumes"] == closed_data_mounts
        assert "agentium-net" in services[service]["networks"]
    for service in QDRANT_CLIENT_SERVICES - {"agentium-migrate"}:
        assert closed_services[service]["restart"] == "no"
        assert opened_services[service]["restart"] == "no"
        assert opened_services[service]["volumes"] == [
            "${AGENTIUM_FAISS_PATH:-/home/ubuntu/omnirag/backend/faiss_db}:/data/faiss_db"
        ]

    closed_sftp = closed_services["agentium-sftp"]
    assert closed_sftp["restart"] == "no"
    assert closed_sftp["volumes"] == [
        "${AGENTIUM_SECURE_DEPOSIT_PATH:-/home/ubuntu/omnirag/backend/data/secure_deposit}:/data/secure_deposit:ro"
    ]
    assert "agentium-sftp" not in opened_services

    qdrant = services["agentium-qdrant"]
    assert qdrant["container_name"] == "qdrant"
    assert qdrant["image"] == "qdrant/qdrant:v1.12.5-unprivileged"
    assert qdrant["ports"] == [
        "127.0.0.1:${AGENTIUM_QDRANT_HTTP_PORT:-6333}:6333",
        "127.0.0.1:${AGENTIUM_QDRANT_GRPC_PORT:-6334}:6334",
    ]


def test_qdrant_server_example_requires_two_uncommitted_distinct_secrets() -> None:
    example = QDRANT_ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "# QDRANT__SERVICE__API_KEY=<admin-secret-at-least-32-characters>" in example
    assert (
        "# QDRANT__SERVICE__READ_ONLY_API_KEY=" "<distinct-read-only-secret-at-least-32-characters>"
    ) in example
    active_assignments = [
        line
        for line in example.splitlines()
        if line.startswith("QDRANT__SERVICE__") and "=" in line
    ]
    assert active_assignments == []


def test_vm_deployer_has_one_compose_gateway_and_fails_closed_without_barrier() -> None:
    script = VM_DEPLOY.read_text(encoding="utf-8")
    gateway = _shell_function(script, "dc")
    guard = script.split("declare -a SELECTED_SERVICES=()", 1)[1].split(
        "read -r -a SELECTED_SERVICES", 1
    )[0]

    assert 'SAFE_QDRANT_OVERRIDE_FILE="${AGENTIUM_SAFE_QDRANT_OVERRIDE_FILE:-}"' in script
    assert 'SAFE_QDRANT_KEY="${AGENTIUM_QDRANT_EFFECTIVE_API_KEY:-}"' in script
    assert '[[ "$SAFE_QDRANT_OVERRIDE_FILE" == "$SAFE_DEPLOYMENT_DIR"/*' in guard
    assert '[[ "${#SAFE_QDRANT_KEY}" -ge 32 ]]' in guard
    assert '-f "$SAFE_QDRANT_OVERRIDE_FILE"' in gateway
    assert 'AGENTIUM_QDRANT_EFFECTIVE_API_KEY="$SAFE_QDRANT_KEY"' in gateway

    assert 'os.execvpe("docker", arguments, environment)' in gateway
    assert '"docker", "compose", "--env-file"' in gateway
    assert "/usr/bin/env" not in gateway
    assert re.search(r"\bdc build ", script)
    assert re.search(r"\bdc up -d ", script)
    assert re.search(r"\bdc .*create --no-build --force-recreate", script, re.DOTALL)


def test_candidate_paths_are_frozen_and_receive_read_only_key_before_opened() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    staged = _shell_function(script, "stage_candidate_helpers")
    run_candidate = _shell_function(script, "run_candidate_database_tool")
    build = _shell_function(script, "build_candidate_in_worktree")
    activate = _shell_function(script, "activate_candidate")
    rollback_restore = _shell_function(script, "complete_rollback_after_restore")

    assert "backend/scripts/audit_qdrant_write_barrier.py" in staged
    assert "docker/compose.agentium.qdrant-barrier.yml" in staged
    assert "docker/compose.agentium.opened.yml" in staged
    assert 'git rev-parse "${EXPECTED_SHA}:${source}"' in staged
    assert '--network "$MIGRATION_NETWORK"' in run_candidate
    assert "compose" not in run_candidate
    assert "QDRANT" not in run_candidate
    assert "AGENTIUM_QDRANT_EFFECTIVE_API_KEY" not in run_candidate
    for body in (build, activate, rollback_restore):
        assert 'AGENTIUM_SAFE_QDRANT_OVERRIDE_FILE="$FROZEN_QDRANT_OVERRIDE"' in body
        assert 'AGENTIUM_QDRANT_EFFECTIVE_API_KEY="$(qdrant_server_key read-only)"' in body
        assert body.index("AGENTIUM_SAFE_QDRANT_OVERRIDE_FILE") < body.index(
            'bash "$FROZEN_DEPLOYER"'
        )

    phase_key = _shell_function(script, "qdrant_effective_client_key")
    assert "opening_forward | opened | completed | rollback_opening | rolled_back" in phase_key
    assert "qdrant_server_key admin" in phase_key
    assert "qdrant_server_key read-only" in phase_key
    phase_override = _shell_function(script, "compose_transaction_override")
    assert "opening_forward | opened | completed | rollback_opening | rolled_back" in phase_override
    assert "FROZEN_OPENED_OVERRIDE" in phase_override
    assert "FROZEN_QDRANT_OVERRIDE" in phase_override


def test_qdrant_is_read_only_for_activation_resume_and_post_canary() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    activate = _shell_function(script, "activate_candidate")
    refresh = _shell_function(script, "refresh_and_build_validation")
    requiesce = _shell_function(script, "requiesce_validation_runtime")
    resume_boundary = _shell_function(script, "reestablish_persisted_phase_boundary")

    assert activate.index(
        'AGENTIUM_QDRANT_EFFECTIVE_API_KEY="$(qdrant_server_key read-only)"'
    ) < activate.index("attest_candidate_qdrant_barrier")
    assert activate.index("attest_candidate_qdrant_barrier") < activate.index("set_phase activated")
    assert refresh.index("attest_candidate_qdrant_barrier") < refresh.index(
        "validation artifact rebuild"
    )
    assert "compose up -d --no-build --force-recreate agentium-worker-cpu" in requiesce
    assert "compose up -d --no-build agentium-backend agentium-frontend agentium-worker-cpu" in (
        resume_boundary
    )
    assert '[[ "$(phase)" == "$persisted_phase" ]]' in resume_boundary


def test_admin_clients_are_recreated_only_after_durable_opened_and_before_gates() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    finalize = _shell_function(script, "finalize_deployment")
    reconcile = _shell_function(script, "reconcile_opening_forward")
    auxiliary = _shell_function(script, "restore_auxiliary_runtime_state")
    deposit_release = _shell_function(script, "remount_secure_deposit_after_sftp_proof")

    assert "compose up -d --no-build --force-recreate" in auxiliary
    assert deposit_release.index("assert_sftp_opening_intent_contract") < deposit_release.index(
        "set_secure_deposit_mode rw"
    )
    assert "leave_sftp_ingress_gate" not in deposit_release
    for body in (finalize, reconcile):
        attestations = [
            match.start() for match in re.finditer("attest_candidate_qdrant_admin_ready", body)
        ]
        assert len(attestations) == 2
        if body is finalize:
            assert body.index("set_phase opening_forward") < body.index(
                "restore_candidate_backend_writer"
            )
        assert body.index("restore_candidate_backend_writer") < attestations[0]
        assert body.index("restore_candidate_worker_with_scheduler") < attestations[0]
        assert attestations[0] < body.index("remount_secure_deposit_after_sftp_proof")
        assert attestations[0] < body.index("restore_auxiliary_runtime_state")
        assert body.index("restore_auxiliary_runtime_state") < attestations[1]
        for gate in (
            "release_sftp_ingress_with_attestation",
            "leave_systemd_backend_ingress_gate",
            "leave_livekit_ingress_gate",
            "open_sftp_ingress_after_attestation",
            "gate exit",
        ):
            assert attestations[1] < body.index(gate)


def test_qdrant_proofs_are_content_free_sha_bound_and_use_absent_targets() -> None:
    helper = QDRANT_HELPER.read_text(encoding="utf-8")
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    bootstrap = _shell_function(script, "attest_live_qdrant_bootstrap")
    admin = _shell_function(script, "attest_candidate_qdrant_admin_ready")

    assert "attest_live_qdrant_bootstrap" in _shell_function(script, "preflight_checks")
    assert "QDRANT_PREFLIGHT_BARRIER" in bootstrap
    assert "--expected-client-access" in script
    assert "--expected-access" in script
    assert "agentium-p4-maintenance" in admin
    assert "secrets_serialized" in helper
    assert '"proof_ceiling": "runner_verified"' in helper
    assert "agentium_guard_absent_" in helper
    assert 'method="DELETE"' not in helper
    assert '"DELETE", f"/collections/{guard}"' in helper
    assert "QDRANT__SERVICE__API_KEY" in helper
    assert "QDRANT__SERVICE__READ_ONLY_API_KEY" in helper
    assert "--api-key" not in helper
