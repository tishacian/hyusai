from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SAFE_DEPLOY = ROOT / "scripts" / "deploy-agentium-safe.sh"
MAINTENANCE_GATE = ROOT / "scripts" / "agentium-maintenance-gate.sh"
VM_DEPLOY = ROOT / "scripts" / "deploy-vm.sh"
STORAGE_HELPER = ROOT / "scripts" / "agentium_storage_attestation.py"
LEGACY_BACKEND_INSTALLER = ROOT / "deploy" / "install-backend-service.sh"
LEGACY_BACKEND_UNIT = ROOT / "deploy" / "agentium-backend.service"


def _storage_module():
    spec = importlib.util.spec_from_file_location(
        "agentium_storage_attestation_test", STORAGE_HELPER
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _embedded_python(function_body: str) -> str:
    start = function_body.index("<<'PY'") + len("<<'PY'")
    end = function_body.index("\nPY", start)
    return function_body[start:end]


def test_safe_deploy_scripts_are_syntactically_valid_and_executable() -> None:
    for script in (SAFE_DEPLOY, VM_DEPLOY, LEGACY_BACKEND_INSTALLER):
        assert script.stat().st_mode & 0o111
        subprocess.run(["bash", "-n", str(script)], check=True)
    assert STORAGE_HELPER.stat().st_mode & 0o111


def test_legacy_backend_adoption_is_narrow_reversible_and_loopback_only() -> None:
    installer = LEGACY_BACKEND_INSTALLER.read_text(encoding="utf-8")
    unit = LEGACY_BACKEND_UNIT.read_text(encoding="utf-8")

    assert "--host 127.0.0.1" in unit
    assert "--host 0.0.0.0" not in unit
    assert "loopback_no_env_sha=" in installer
    assert "public_no_env_sha=" in installer
    assert "--host 0.0.0.0" in installer
    assert 'target_sha" == "$source_sha"' in installer
    assert 'target_sha" == "$loopback_no_env_sha"' in installer
    assert 'target_sha" == "$public_no_env_sha"' in installer
    assert "adoption automatique refusée" in installer
    assert "agentium-backend-backups" in installer
    assert "restore_previous_unit" in installer
    assert "systemctl stop" in installer
    assert "http://127.0.0.1:8000/api/v1/health" in installer
    assert "pgrep" not in installer
    assert "kill -9" not in installer
    assert "systemctl enable" not in installer
    assert "systemctl disable" not in installer
    assert "EnvironmentFile=\\nEnvironmentFile=" in installer
    assert "AGENTIUM_DISABLE_DOTENV=1" in unit
    assert "^Environment=AGENTIUM_DISABLE_DOTENV=1$" in installer
    assert "^Environment=AGENTIUM_DISABLE_DOTENV=1$" in SAFE_DEPLOY.read_text(encoding="utf-8")
    assert "99-agentium-safe-runtime-env.conf" in installer
    assert 'MODE" == "restore-env"' in installer
    assert "systemd-env-dropin.previous" in installer
    assert "durable_write_state" in installer
    assert "os.fsync" in installer
    assert "restore_previous_dropin" in installer
    assert "effective EnvironmentFiles is not the unique frozen snapshot" in installer


def test_systemd_process_identity_is_bound_to_served_build_info() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    wait = _shell_function(script, "wait_systemd_backend_identity")

    assert "http://127.0.0.1:8000/api/v1/build-info" in wait
    assert 'payload.get("service") != "backend"' in wait
    assert 'payload.get("revision") != expected' in wait
    assert 'payload.get("revision_verified") is not True' in wait
    assert '"$expected_sha"' in wait
    assert 'readlink -f "/proc/$main_pid/cwd"' in wait
    installer = LEGACY_BACKEND_INSTALLER.read_text(encoding="utf-8")
    assert 'EXPECTED_REVISION="${AGENTIUM_BACKEND_EXPECTED_SHA:-}"' in installer
    assert "frozen EnvironmentFile is not bound to the expected revision" in installer
    assert "http://127.0.0.1:8000/api/v1/build-info" in installer


def test_previous_systemd_environment_is_restored_before_old_process_restarts() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    recovery = _shell_function(script, "recover_pre_migration_failure")
    complete = _shell_function(script, "complete_rollback_after_restore")
    reconcile = _shell_function(script, "reconcile_rollback_opening")

    assert recovery.index("restore_previous_systemd_env_dropin") < recovery.index(
        "restore_systemd_backend_state"
    )
    assert complete.index("restore_previous_systemd_env_dropin") < complete.index(
        "set_phase rollback_opening"
    )
    assert "assert_systemd_env_dropin_contract" not in reconcile
    assert 'restore_systemd_backend_state "$(metadata previous_sha)"' in reconcile


def test_safe_deploy_is_sha_bound_locked_and_persists_only_on_data_disk() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")

    assert "preflight | prepare | apply | resume | rollback" in script
    assert "^/srv/agentium-data/deployments" not in script
    assert (
        'STATE_ROOT="${AGENTIUM_SAFE_DEPLOY_STATE_DIR:-/srv/agentium-data/deployments}"' in script
    )
    assert '[[ "$DATA_ROOT" == /srv/agentium-data ]]' in script
    assert '[[ "$STATE_ROOT" == "$DATA_ROOT/deployments" ]]' in script
    assert 'state_device="$(findmnt -n -o SOURCE --target "$DATA_ROOT")"' in script
    assert '"$state_device" == "$EXPECTED_DATA_SOURCE"' in script
    assert 'LOCK_PATH="$STATE_ROOT/$LOCK_NAME"' in script
    assert "AGENTIUM_SAFE_DEPLOY_LOCK" not in script
    assert 'exec 9<"$STATE_ROOT"' in script
    assert 'stat -Lc \'%d:%i\' "/proc/$$/fd/9"' in script
    assert "flock -n 9" in script
    assert 'exec 9>"$LOCK_PATH"' not in script
    assert 'exec 8<>"$LOCK_PATH"' in script
    assert "flock -n 8" in script
    assert "--sha doit être un SHA Git complet" in script
    assert 'remote_sha="$(git rev-parse "origin/$BRANCH")"' in script
    assert '[[ "$remote_sha" == "$EXPECTED_SHA" ]]' in script
    assert "--force)" not in script
    assert "git pull" not in script
    assert "docker volume prune" not in script
    assert "docker system prune" not in script
    assert 'export PATH="$COMPOSE_CLEAN_PATH"' in script
    assert "export PYTHONDONTWRITEBYTECODE=1" in script
    assert "unset PYTHONBREAKPOINT PYTHONHOME PYTHONINSPECT PYTHONOPTIMIZE" in script
    assert "assert_python_runtime" in script
    assert "sys.flags.optimize" in script
    assert "grep -vE 'uvicorn\\.log|\\.pyc$'" not in script


def test_safe_deploy_journal_creation_is_nofollow_private_and_race_aware(
    tmp_path: Path,
) -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    private_dir = _shell_function(script, "ensure_private_child_dir")
    private_lock = _shell_function(script, "ensure_private_lock_file")

    assert "follow_symlinks=False" in private_dir
    assert 'getattr(os, "O_NOFOLLOW", 0)' in private_dir
    assert "os.mkdir(name, 0o700, dir_fd=parent_fd)" in private_dir
    assert "row.st_uid != os.geteuid()" in private_dir
    assert "stat.S_IMODE(row.st_mode) != 0o700" in private_dir
    assert "row.st_dev != opened.st_dev" in private_dir
    assert "os.O_CREAT | os.O_EXCL" in private_lock
    assert 'getattr(os, "O_NOFOLLOW", 0)' in private_lock
    assert "opened_lock.st_nlink != 1" in private_lock
    assert "opened_lock.st_dev != opened_parent.st_dev" in private_lock

    harness = f"""
set -Eeuo pipefail
ensure_private_child_dir() {{
{private_dir}
}}
ensure_private_child_dir "$1" deployments "$2"
"""
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    created = subprocess.run(
        ["bash", "-c", harness, "bash", str(root), "1"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert created.returncode == 0, created.stderr
    assert (root / "deployments").stat().st_mode & 0o777 == 0o700

    (root / "deployments").chmod(0o755)
    rejected_mode = subprocess.run(
        ["bash", "-c", harness, "bash", str(root), "0"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected_mode.returncode != 0
    assert "owner/mode/link identity differs" in rejected_mode.stderr

    unsafe_root = tmp_path / "unsafe"
    unsafe_root.mkdir(mode=0o700)
    (unsafe_root / "target").mkdir(mode=0o700)
    (unsafe_root / "deployments").symlink_to(unsafe_root / "target", target_is_directory=True)
    rejected_symlink = subprocess.run(
        ["bash", "-c", harness, "bash", str(unsafe_root), "0"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected_symlink.returncode != 0
    assert "not a real directory" in rejected_symlink.stderr

    lock_harness = f"""
set -Eeuo pipefail
ensure_private_lock_file() {{
{private_lock}
}}
ensure_private_lock_file "$1" .agentium-deploy.lock
"""
    lock_root = tmp_path / "lock-root"
    lock_root.mkdir(mode=0o700)
    created_lock = subprocess.run(
        ["bash", "-c", lock_harness, "bash", str(lock_root)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert created_lock.returncode == 0, created_lock.stderr
    lock_path = lock_root / ".agentium-deploy.lock"
    assert lock_path.stat().st_mode & 0o777 == 0o600
    assert lock_path.stat().st_nlink == 1

    lock_path.unlink()
    victim = lock_root / "victim"
    victim.write_text("unchanged", encoding="utf-8")
    lock_path.symlink_to(victim)
    rejected_lock_symlink = subprocess.run(
        ["bash", "-c", lock_harness, "bash", str(lock_root)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected_lock_symlink.returncode != 0
    assert victim.read_text(encoding="utf-8") == "unchanged"


def test_safe_deploy_locks_before_deployment_child_and_preserves_frozen_reexec() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    calls = script.split("ensure_private_lock_file()", 1)[1]

    state_create = calls.index('ensure_private_child_dir "$DATA_ROOT" deployments 1')
    state_lock = calls.index("flock -n 9")
    compatibility_lock = calls.index("flock -n 8")
    deployment_create = calls.index(
        'ensure_private_child_dir "$STATE_ROOT" "$DEPLOYMENT_ID" 1'
    )
    frozen_write = calls.index('git -C "$REPO_DIR" show')
    frozen_exec = calls.index('exec "$FROZEN_ORCHESTRATOR"')

    assert state_create < state_lock < compatibility_lock < deployment_create
    assert deployment_create < frozen_write < frozen_exec
    assert 'if [[ -e "/proc/$$/fd/9" ]]' in calls
    assert 'if [[ -e "/proc/$$/fd/8" ]]' in calls
    assert "assert_state_root_fd_identity" in calls
    assert "exec 9<&-" not in calls
    assert "exec 8<&-" not in calls


def test_transaction_state_is_private_schema_checked_and_durably_published() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    initialize = _shell_function(script, "initialize_metadata")
    atomic = _shell_function(script, "atomic_text")
    publish = _shell_function(script, "durable_publish_file")

    assert "data.resolve(strict=True) != data.absolute()" in script
    assert "private directory is not a real directory" in script
    assert "private directory owner/mode/link identity differs" in script
    assert "assert_private_state_file" in script
    assert "600:$(id -u):1" in script
    assert "assert_metadata_contract" in script
    assert "assert_runtime_state_contract" in script
    assert "deployment metadata is malformed or duplicated" in script
    assert "runtime state contains an unknown row" in script
    assert "runtime state inventory is incomplete" in script
    assert '[[ "$(metadata deployment_id)" == "$DEPLOYMENT_ID" ]]' in initialize
    assert 'durable_publish_file "$runtime_temporary" "$RUNTIME_STATE_FILE"' in initialize
    assert 'durable_publish_file "$metadata_temporary" "$METADATA_FILE"' in initialize
    assert 'ln "$runtime_temporary" "$RUNTIME_STATE_FILE"' not in initialize
    assert 'ln "$metadata_temporary" "$METADATA_FILE"' not in initialize
    assert "os.fsync(handle.fileno())" in atomic
    assert "os.replace(temporary, target)" in atomic
    assert "os.fsync(directory_fd)" in atomic
    assert 'assert_private_state_file "$target"' in atomic
    assert "os.fsync(handle.fileno())" in publish
    assert "os.replace(temporary, target)" in publish
    assert "os.fsync(directory_fd)" in publish
    assert 'assert_private_state_file "$target"' in publish
    assert "Transition de phase interdite" in script
    assert "rollback_closing" in script
    assert "recovering_pre_migration" in script


def test_release_a_operator_gate_is_frozen_sha_bound_and_required_before_metadata() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    ensure = _shell_function(script, "ensure_release_a_gate")
    freeze = _shell_function(script, "freeze_release_a_attestation")
    receipt = _shell_function(script, "assert_release_a_receipt_contract")
    completed = _shell_function(script, "assert_completed_release_a_transaction")
    initialize = _shell_function(script, "initialize_metadata")
    dispatch = script.rsplit('case "$MODE" in', 1)[1]
    preflight = dispatch.split("preflight)", 1)[1].split("\n\t;;", 1)[0]

    assert "--release-a-attestation" in script
    assert "--release-a-attestation-sha256" in script
    assert "RELEASE_A_ATTESTATION_MAX_AGE_HOURS=24" in script
    assert "AGENTIUM_RELEASE_A_ATTESTATION_MAX_AGE_HOURS" not in script
    assert "scripts/agentium_release_a_attestation.py" in script
    assert "authentication_result" not in script  # the orchestrator never embeds evidence
    assert "waiver" not in script
    assert "O_NOFOLLOW" in freeze
    assert "before.st_nlink != 1" in freeze
    assert "mode not in {0o400, 0o600}" in freeze
    assert "before.st_size > 1024 * 1024" in freeze
    assert "hashlib.sha256(content).hexdigest() != expected" in freeze
    assert 'durable_publish_file "$temporary" "$FROZEN_RELEASE_A_ATTESTATION"' in freeze
    assert 'git merge-base --is-ancestor "$current_sha" "$EXPECTED_SHA"' in ensure
    assert ensure.index("assert_completed_release_a_transaction") < ensure.index(
        'git merge-base --is-ancestor "$current_sha" "$EXPECTED_SHA"'
    )
    assert "/srv/agentium-data/release-a-deployments" in completed
    assert 'private_bytes(path/"phase").decode("ascii").strip()!="completed"' in completed
    assert "agentium-release-a-transaction-receipt" in completed
    assert "release-a-final-evidence-receipt.json" in completed
    assert "release-a-final-evidence-bindings.json" in completed
    assert "release-a-evidence-authority-keyring.json" in completed
    assert "external-final-evidence" in completed
    assert "agentium_release_a_evidence_bundle.py" in completed
    assert "agentium_release_a_attestation.py" in completed
    assert "agentium_release_a_preconditions.py" in completed
    assert "agentium_release_a_sftp_positive_canary.py" in completed
    assert "config/agentium/release-a-evidence-authorities.v1.json" in completed
    assert '"verify-final-frozen"' in completed
    assert 'final.get("authority_keyring_sha256")!=keyring_digest' in completed
    assert 'final.get("binding_manifest_sha256")!=hashlib.sha256(binding_body).hexdigest()' in completed
    assert '"external_provenance_set_sha256"' in completed
    assert "release-a-candidate-oci-receipt.json" in completed
    assert "release-a-runtime-oci-receipt.json" in completed
    assert 'completion.get("schema_version")!=3' in completed
    assert 'attestation_receipt.get("schema_version")!=4' in completed
    assert '"sftp_runtime_ready_receipt_sha256":"sftp-validation-runtime-ready.json"' in completed
    assert '"sftp_postgres_ledger_receipt_sha256":"sftp-postgres-ledger-receipt.json"' in completed
    assert "Release A forward-open terminal marker differs" in completed
    assert 'runtime_state_path=path/"runtime-state.tsv"' in completed
    assert "historical_sftp_restart" in completed
    assert 'sftp_restart.get("Name")' in completed
    assert "!=matched_sftp_restart" in completed
    assert "Release A forward terminal authorization differs" in completed
    assert 'forward_authorization_body!=expected_authorization_body' in completed
    assert 'authorization_sha256={hashlib.sha256(forward_authorization_body).hexdigest()}' in completed
    assert "Release A historical Keycloak runtime state cardinality differs" in completed
    assert "Release A historical Keycloak control-plane contract differs" in completed
    assert 'keycloak.get("Id")!=matched_keycloak_contract["container_id"]' in completed
    assert 'keycloak.get("Image")!=matched_keycloak_contract["image_id"]' in completed
    assert 'keycloak_health.get("Status")!="healthy"' in completed
    assert "!=matched_keycloak_restart" in completed
    assert 'row.get("HostIp")!="127.0.0.1"' in completed
    assert 'set(rows).issubset({"8080/tcp","8443/tcp","9000/tcp"})' in completed
    assert 'value not in (None,[])' in completed
    assert "contains another published endpoint" in completed
    assert "matching Release A SFTP runtime identity was invalidated" in completed
    assert completed.index('sftp_invalidation_path=path/"sftp-runtime-identity-invalidation.json"') < completed.index(
        'if private_bytes(path/"phase").decode("ascii").strip()!="completed"'
    )
    assert 'metadata.get("docker_engine_id")!=engine_id' in completed
    assert "verify-live" in completed
    assert 'container.get("Image")!=expected["image_id"]' in completed
    assert "live Release A backend build-info differs" in completed
    assert "expected exactly one completed Release A transaction" in completed
    assert '"$RELEASE_A_HELPER" verify' in ensure
    assert '--expected-release-a-sha "$current_sha"' in ensure
    assert '--expected-sftp-sha "$sftp_release_sha"' in ensure
    assert '--expected-hostname "$runtime_hostname"' in ensure
    assert '--max-age-hours "$RELEASE_A_ATTESTATION_MAX_AGE_HOURS"' in ensure
    assert 'durable_replace_file "$receipt_temporary" "$RELEASE_A_RECEIPT"' in ensure
    assert 'payload.get("release_a_sha") != expected_sha' in receipt
    assert 'payload.get("attestation_sha256") != expected_attestation' in receipt
    assert 'payload.get("hostname_sha256") != hostname_digest' in receipt
    assert 'freshness == "fresh" and datetime.now(timezone.utc) > times[1]' in receipt
    assert '"$MODE" != "rollback"' in script
    assert '"$current_phase" == "preflight_ok"' in script
    assert "release_a_attestation_sha256" in initialize
    assert "release_a_receipt_sha256" in initialize
    assert "printf 'format\\t5\\n'" in initialize
    assert "sftp_release_sha" in initialize
    assert "sftp_image_id" in initialize
    assert preflight.index("preflight_checks") < preflight.index("ensure_release_a_gate")
    assert preflight.index("ensure_release_a_gate") < preflight.index("initialize_metadata")
    startup = script.rsplit("ensure_runtime_env_bundle", 1)[1]
    assert "assert_recorded_release_a_gate" in startup


@pytest.mark.parametrize(
    (
        "tampered_helper_name",
        "sftp_receipt_name",
        "sftp_completion_key",
        "sftp_mutation_path",
        "sftp_mutation_value",
        "expected_sftp_error",
    ),
    (
        (
            "agentium_release_a_evidence_bundle.py",
            "sftp-validation-runtime-ready.json",
            "sftp_runtime_ready_receipt_sha256",
            ("restart_policy_disabled",),
            False,
            "runtime-ready safety state differs",
        ),
        (
            "agentium_release_a_attestation.py",
            "sftp-validation-runtime-ready.json",
            "sftp_runtime_ready_receipt_sha256",
            ("published_transport", "listener_count"),
            0,
            "runtime-ready transport differs",
        ),
        (
            "agentium_release_a_preconditions.py",
            "sftp-postgres-ledger-receipt.json",
            "sftp_postgres_ledger_receipt_sha256",
            ("deposit_file_delta_count",),
            1,
            "PostgreSQL ledger cleanup differs",
        ),
        (
            "agentium_release_a_sftp_positive_canary.py",
            "sftp-postgres-ledger-receipt.json",
            "sftp_postgres_ledger_receipt_sha256",
            ("audits", "auth_success", "count"),
            2,
            "PostgreSQL audit ledger differs",
        ),
    ),
    ids=(
        "evidence-bundle-and-sftp-runtime-policy",
        "attestation-and-sftp-runtime-transport",
        "preconditions-and-sftp-final-cleanup",
        "sftp-canary-and-sftp-final-audit",
    ),
)
def test_release_b_accepts_only_byte_bound_completed_release_a_journal(
    tmp_path: Path,
    tampered_helper_name: str,
    sftp_receipt_name: str,
    sftp_completion_key: str,
    sftp_mutation_path: tuple[str, ...],
    sftp_mutation_value: object,
    expected_sftp_error: str,
) -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    verifier = _embedded_python(
        _shell_function(script, "assert_completed_release_a_transaction")
    )
    engine_id = "engine-local-1234"
    hostname = "agentium.test"
    source_repo = tmp_path / "release-a-source"
    scripts_dir = source_repo / "scripts"
    config_dir = source_repo / "config" / "agentium"
    scripts_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    frozen_helper_source = scripts_dir / "agentium_release_a_evidence_bundle.py"
    frozen_helper_source.write_text(
        """#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("command")
for option in (
    "attestation", "preconditions-receipt", "evidence-receipt",
    "binding-manifest", "evidence-root", "journal-root", "authority-keyring",
    "expected-authority-keyring-sha256", "expected-live-sha",
    "expected-release-a-sha", "expected-sftp-sha", "expected-hostname",
    "deployment-id",
):
    parser.add_argument(f"--{option}", required=True)
args = parser.parse_args()
if args.command != "verify-final-frozen":
    raise SystemExit(2)
keyring = Path(args.authority_keyring).read_bytes()
if hashlib.sha256(keyring).hexdigest() != args.expected_authority_keyring_sha256:
    raise SystemExit(3)
manifest = json.loads(Path(args.binding_manifest).read_text(encoding="utf-8"))
proof = (Path(args.evidence_root) / "proof.bin").read_bytes()
if manifest["entries"][23]["artifact_sha256"] != hashlib.sha256(proof).hexdigest():
    raise SystemExit(4)
print("passed")
""",
        encoding="utf-8",
    )
    dependency_names = (
        "agentium_release_a_attestation.py",
        "agentium_release_a_preconditions.py",
        "agentium_release_a_sftp_positive_canary.py",
    )
    frozen_helper_source.chmod(0o700)
    for name in dependency_names:
        dependency = scripts_dir / name
        dependency.write_text("VALUE = 'trusted-release-a'\n", encoding="utf-8")
        dependency.chmod(0o700)
    keyring_payload = {
        "schema_version": 1,
        "kind": "agentium-release-a-evidence-authority-keyring",
        "authorities": [
            {"producer": producer, "issuer": f"test-{producer}"}
            for producer in (
                "backup_provider",
                "protected_runner",
                "release_a_host_collector",
            )
        ],
    }
    keyring_source = config_dir / "release-a-evidence-authorities.v1.json"
    keyring_source.write_text(
        json.dumps(keyring_payload, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(source_repo)], check=True)
    subprocess.run(
        ["git", "-C", str(source_repo), "config", "user.name", "Release A Test"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(source_repo),
            "config",
            "user.email",
            "release-a@example.invalid",
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(source_repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(source_repo), "commit", "-qm", "release-a fixture"],
        check=True,
    )
    release_sha = subprocess.run(
        ["git", "-C", str(source_repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    root = tmp_path / "release-a-deployments"
    deployment = root / "release-a-proof"
    deployment.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    deployment.chmod(0o700)
    for name in (frozen_helper_source.name, *dependency_names):
        target = deployment / name
        target.write_bytes((scripts_dir / name).read_bytes())
        target.chmod(0o700)
    keyring = deployment / "release-a-evidence-authority-keyring.json"
    keyring.write_bytes(keyring_source.read_bytes())
    keyring.chmod(0o600)
    keyring_sha256 = hashlib.sha256(keyring.read_bytes()).hexdigest()

    candidate_images = [
        {
            "service": service,
            "image_ref": image_ref,
            "image_id": f"sha256:{index + 3:x}{'0' * 63}",
            "revision": release_sha,
        }
        for index, (service, image_ref) in enumerate(
            (
                ("agentium-backend", "agentium-backend:release-a"),
                ("agentium-frontend", "agentium-frontend:release-a"),
                ("agentium-worker-cpu", "agentium-worker:release-a"),
            ),
            start=1,
        )
    ]
    candidate_receipt = {
        "schema_version": 1,
        "kind": "agentium-release-a-candidate-oci-receipt",
        "result": "passed",
        "deployment_id": deployment.name,
        "release_a_sha": release_sha,
        "docker_engine_id": engine_id,
        "images": candidate_images,
        "captured_at": "2026-07-22T19:58:00Z",
    }
    candidate_receipt_sha256 = hashlib.sha256(
        json.dumps(candidate_receipt).encode("utf-8")
    ).hexdigest()
    live_sha = "b" * 40
    sftp_sha = "c" * 40
    hostname_sha256 = hashlib.sha256(hostname.encode("utf-8")).hexdigest()
    attestation_payload = {"kind": "release-a-test-attestation"}
    attestation = deployment / "release-a-attestation.json"
    attestation.write_text(json.dumps(attestation_payload), encoding="utf-8")
    attestation.chmod(0o600)
    preconditions_evidence_payload = {"result": "passed"}
    preconditions_evidence_bytes = json.dumps(preconditions_evidence_payload).encode(
        "utf-8"
    )
    external_evidence = deployment / "external-final-evidence"
    external_evidence.mkdir(mode=0o700)
    proof = external_evidence / "proof.bin"
    proof.write_bytes(b"signed-frozen-evidence")
    proof.chmod(0o600)
    proof_sha256 = hashlib.sha256(proof.read_bytes()).hexdigest()
    binding_entries = [
        {
            "claim": f"canonical-{index:02d}",
            "source": "release_a_journal",
            "artifact_sha256": hashlib.sha256(
                f"canonical-{index}".encode()
            ).hexdigest(),
        }
        for index in range(23)
    ] + [
        {
            "claim": f"external-{index:02d}",
            "source": "authorized_external",
            "artifact_sha256": proof_sha256
            if index == 0
            else hashlib.sha256(f"external-{index}".encode()).hexdigest(),
        }
        for index in range(14)
    ]
    binding_manifest = {
        "schema_version": 1,
        "result": "passed",
        "environment": "production",
        "deployment_id": deployment.name,
        "live_sha": live_sha,
        "release_a_sha": release_sha,
        "hostname_sha256": hostname_sha256,
        "kind": "agentium-release-a-final-evidence-bindings",
        "sftp_release_sha": sftp_sha,
        "reference_count": 37,
        "canonical_reference_count": 23,
        "external_reference_count": 14,
        "authority_keyring_sha256": keyring_sha256,
        "entries": binding_entries,
        "verified_at": "2026-07-22T19:58:30Z",
    }
    binding_manifest_path = deployment / "release-a-final-evidence-bindings.json"
    binding_manifest_path.write_text(json.dumps(binding_manifest), encoding="utf-8")
    binding_manifest_path.chmod(0o600)
    binding_manifest_sha256 = hashlib.sha256(
        binding_manifest_path.read_bytes()
    ).hexdigest()
    final_evidence_receipt = {
        "schema_version": 1,
        "kind": "agentium-release-a-final-evidence-receipt",
        "result": "passed",
        "environment": "production",
        "deployment_id": deployment.name,
        "live_sha": live_sha,
        "release_a_sha": release_sha,
        "sftp_release_sha": sftp_sha,
        "hostname_sha256": hostname_sha256,
        "attestation_sha256": hashlib.sha256(attestation.read_bytes()).hexdigest(),
        "preconditions_receipt_sha256": hashlib.sha256(
            preconditions_evidence_bytes
        ).hexdigest(),
        "preconditions_sha256": "d" * 64,
        "evidence_file_count": 24,
        "evidence_digest_count": 24,
        "evidence_reference_count": 37,
        "evidence_set_sha256": "e" * 64,
        "binding_manifest_sha256": binding_manifest_sha256,
        "authority_keyring_sha256": keyring_sha256,
        "canonical_reference_count": 23,
        "external_reference_count": 14,
        "external_provenance_set_sha256": "f" * 64,
        "verified_at": "2026-07-22T19:58:30Z",
    }
    sftp_container_id = "9" * 64
    sftp_image_id = f"sha256:{'1' * 64}"
    sftp_started_at = "2026-07-22T19:57:00Z"
    sftp_ready_at = "2026-07-22T19:57:30Z"
    sftp_port = 2222
    runtime_identity = hashlib.sha256(
        b"agentium-release-a-sftp-runtime-identity-v1"
        + b"\0"
        + b"\0".join(
            value.encode("utf-8")
            for value in (
                live_sha,
                release_sha,
                sftp_sha,
                deployment.name,
                hostname_sha256,
                sftp_container_id,
                sftp_image_id,
                str(sftp_port),
                sftp_started_at,
            )
        )
    ).hexdigest()
    host_key_fingerprint = f"SHA256:{'A' * 43}"
    runtime_ready = {
        "schema_version": 1,
        "kind": "agentium-release-a-sftp-runtime-ready",
        "result": "passed",
        "live_sha": live_sha,
        "deployment_id": deployment.name,
        "release_a_sha": release_sha,
        "sftp_sha": sftp_sha,
        "hostname_sha256": hostname_sha256,
        "sftp_container_id": sftp_container_id,
        "sftp_image_id": sftp_image_id,
        "image_revision": sftp_sha,
        "sftp_port": sftp_port,
        "sftp_started_at": sftp_started_at,
        "runtime_identity_sha256": runtime_identity,
        "host_key_fingerprint": host_key_fingerprint,
        "state": "running",
        "health_status": "healthy",
        "ingress_closed": True,
        "restart_disabled": True,
        "restart_policy_disabled": True,
        "secure_deposit_mode": "ro",
        "secure_deposit_source": "/dev/sdc",
        "external_established_connection_count": 0,
        "ready_at": sftp_ready_at,
        "ingress_gate": {
            "ipv4_input": True,
            "ipv4_docker_user": True,
            "ipv6_input": True,
            "ipv6_docker_user": True,
        },
        "published_transport": {
            "protocol": "tcp",
            "container_port": 2222,
            "host_port": sftp_port,
            "binding_count": 2,
            "binding_sha256": "1" * 64,
            "listener_count": 2,
            "established_connection_count_before": 0,
            "established_connection_count_after": 0,
            "external_established_connection_count": 0,
            "ssh_v2_identification_validated": True,
            "connection_closed_before_authentication": True,
            "raw_identification_serialized": False,
        },
        "secure_deposit": {
            "source_matches_dev_sdc": True,
            "source_device_sha256": hashlib.sha256(b"/dev/sdc").hexdigest(),
            "autonomous_mountpoint": True,
            "host_read_only": True,
            "namespace_autonomous_mountpoint": True,
            "namespace_read_only": True,
            "device_id": 3145729,
        },
        "host_key": {
            "algorithm": "ssh-ed25519",
            "fingerprint": host_key_fingerprint,
            "fingerprint_sha256": hashlib.sha256(
                host_key_fingerprint.encode("ascii")
            ).hexdigest(),
            "present": True,
            "nonempty": True,
            "regular_file": True,
            "symlink": False,
        },
        "credentials_used": False,
        "authentication_attempted": False,
        "sftp_subsystem_requested": False,
        "content_serialized": False,
        "raw_network_data_serialized": False,
        "raw_identification_serialized": False,
    }
    audit_events = (
        ("created", "deposit.link.created", "2026-07-22T19:57:40Z"),
        ("auth_success", "deposit.sftp.auth.success", "2026-07-22T19:57:45Z"),
        ("revoked", "deposit.link.revoked", "2026-07-22T19:57:50Z"),
        (
            "auth_failed_inactive",
            "deposit.sftp.auth.failed",
            "2026-07-22T19:57:55Z",
        ),
    )
    sftp_ledger = {
        "schema_version": 1,
        "kind": "agentium-release-a-sftp-postgres-ledger",
        "result": "passed",
        "live_sha": live_sha,
        "release_a_sha": release_sha,
        "sftp_sha": sftp_sha,
        "deployment_id": deployment.name,
        "hostname_sha256": hostname_sha256,
        "workspace_id_sha256": "2" * 64,
        "link_id_sha256": "3" * 64,
        "access_id_sha256": "4" * 64,
        "credential_fingerprint_sha256": "5" * 64,
        "sftp_container_id": sftp_container_id,
        "sftp_image_id": sftp_image_id,
        "sftp_port": sftp_port,
        "runtime_identity_sha256": runtime_identity,
        "link_status": "revoked",
        "auth_failed_reason": "inactive_or_expired",
        "remaining_active_link_count": 0,
        "active_sftp_session_count": 0,
        "deposit_file_delta_count": 0,
        "audits": {
            name: {
                "event_type": event_type,
                "event_id_sha256": f"{index + 6:x}" * 64,
                "event_digest_sha256": f"{index + 10:x}" * 64,
                "count": 1,
                "occurred_at": occurred_at,
            }
            for index, (name, event_type, occurred_at) in enumerate(audit_events)
        },
        "binding_sha256": "e" * 64,
        "collected_at": "2026-07-22T19:58:00Z",
    }
    attestation_receipt = {
        "schema_version": 4,
        "kind": "agentium-release-a-verification-receipt",
        "result": "passed",
        "environment": "production",
        "release_a_sha": release_sha,
        "sftp_release_sha": sftp_sha,
        "hostname_sha256": hostname_sha256,
        "attestation_sha256": hashlib.sha256(attestation.read_bytes()).hexdigest(),
        "evidence_sha256": "f" * 64,
        "verified_at": "2026-07-22T19:58:10Z",
        "fresh_until": "2026-07-23T19:58:10Z",
    }
    artifacts = {
        "release-a-verification-receipt.json": attestation_receipt,
        "release-a-final-evidence-receipt.json": final_evidence_receipt,
        "release-a-manifest-verification-receipt.json": {"result": "passed"},
        "release-a-preconditions-receipt.json": {"result": "passed"},
        "release-a-preconditions-evidence-receipt.json": (
            preconditions_evidence_payload
        ),
        "release-a-candidate-oci-receipt.json": candidate_receipt,
        "sftp-validation-runtime-ready.json": runtime_ready,
        "sftp-postgres-ledger-receipt.json": sftp_ledger,
        "release-a-runtime-oci-receipt.json": {
            "schema_version": 1,
            "kind": "agentium-release-a-runtime-oci-receipt",
            "result": "passed",
            "deployment_id": deployment.name,
            "release_a_sha": release_sha,
            "docker_engine_id": engine_id,
            "candidate_oci_receipt_sha256": candidate_receipt_sha256,
            "containers": [
                {
                    "service": service,
                    "container_id": f"{index:x}" * 64,
                    "image_ref": image_ref,
                    "image_id": f"sha256:{index + 3:x}{'0' * 63}",
                    "image_revision": release_sha,
                    "state": "running",
                    "health_status": health,
                }
                for index, (service, image_ref, health) in enumerate(
                    (
                        ("agentium-backend", "agentium-backend:release-a", "healthy"),
                        ("agentium-frontend", "agentium-frontend:release-a", "healthy"),
                        ("agentium-worker-cpu", "agentium-worker:release-a", "not_configured"),
                    ),
                    start=1,
                )
            ],
            "backend_build_info": {
                "service": "backend",
                "revision": release_sha,
                "revision_verified": True,
                "version": "release-a-test",
            },
            "verified_at": "2026-07-22T19:59:00Z",
        },
    }
    digests: dict[str, str] = {}
    for name, payload in artifacts.items():
        path = deployment / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.chmod(0o600)
        digests[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    completion = {
        "schema_version": 3,
        "kind": "agentium-release-a-transaction-receipt",
        "result": "passed",
        "deployment_id": deployment.name,
        "release_a_sha": release_sha,
        "release_a_attestation_receipt_sha256": digests[
            "release-a-verification-receipt.json"
        ],
        "final_evidence_receipt_sha256": digests[
            "release-a-final-evidence-receipt.json"
        ],
        "manifest_receipt_sha256": digests[
            "release-a-manifest-verification-receipt.json"
        ],
        "preconditions_receipt_sha256": digests[
            "release-a-preconditions-receipt.json"
        ],
        "preconditions_evidence_receipt_sha256": digests[
            "release-a-preconditions-evidence-receipt.json"
        ],
        "runtime_oci_receipt_sha256": digests[
            "release-a-runtime-oci-receipt.json"
        ],
        "sftp_runtime_ready_receipt_sha256": digests[
            "sftp-validation-runtime-ready.json"
        ],
        "sftp_postgres_ledger_receipt_sha256": digests[
            "sftp-postgres-ledger-receipt.json"
        ],
        "completed_at": "2026-07-22T20:00:00Z",
    }
    completion_path = deployment / "release-a-transaction-receipt.json"
    completion_path.write_text(json.dumps(completion), encoding="utf-8")
    completion_path.chmod(0o600)
    forward_authorization = deployment / "release-a-forward-open-authorization.json"
    forward_authorization.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "agentium-release-a-terminal-gate-authorization",
                "deployment_id": deployment.name,
                "release_a_sha": release_sha,
                "purpose": "forward-terminal-open",
                "terminal_phase": "completed",
                "receipt_name": "release-a-transaction-receipt.json",
                "receipt_sha256": hashlib.sha256(completion_path.read_bytes()).hexdigest(),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    forward_authorization.chmod(0o600)
    forward_marker = deployment / "release-a-forward-open-reconciled"
    forward_marker.write_text(
        " ".join(
            (
                "format=2",
                "direction=forward",
                f"deployment_id={deployment.name}",
                f"release_a_sha={release_sha}",
                "terminal_phase=completed",
                "receipt_sha256=" + hashlib.sha256(completion_path.read_bytes()).hexdigest(),
                "authorization_sha256="
                + hashlib.sha256(forward_authorization.read_bytes()).hexdigest(),
            )
        )
        + "\n",
        encoding="ascii",
    )
    forward_marker.chmod(0o600)
    metadata = deployment / "metadata.tsv"
    metadata.write_text(
        "\n".join(
            (
                "format\t2",
                f"deployment_id\t{deployment.name}",
                "branch\tdemo/agentic",
                f"live_sha\t{live_sha}",
                f"release_a_sha\t{release_sha}",
                f"candidate_sha\t{release_sha}",
                f"sftp_release_sha\t{sftp_sha}",
                f"sftp_image_id\tsha256:{'1' * 64}",
                f"docker_engine_id\t{engine_id}",
                f"env_manifest_sha256\t{'2' * 64}",
                f"manifest_sha256\t{'3' * 64}",
                f"review_policy_sha256\t{'4' * 64}",
                f"preconditions_sha256\t{'5' * 64}",
                f"evidence_authority_keyring_sha256\t{keyring_sha256}",
                f"manifest_receipt_sha256\t{completion['manifest_receipt_sha256']}",
                f"preconditions_receipt_sha256\t{completion['preconditions_receipt_sha256']}",
                f"preconditions_evidence_receipt_sha256\t{completion['preconditions_evidence_receipt_sha256']}",
                "created_at\t2026-07-22T19:57:00Z",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    metadata.chmod(0o600)
    runtime_state = deployment / "runtime-state.tsv"
    keycloak_container_id = "8" * 64
    keycloak_image_id = f"sha256:{'2' * 64}"
    keycloak_contract_sha256 = "a" * 64
    keycloak_port = 8081
    runtime_state.write_text(
        "\n".join(
            (
                "format\t1",
                f"container\tagentium-sftp\ttrue\t{sftp_image_id}\tunless-stopped\t0",
                f"container\tagentium-kc\ttrue\t{keycloak_image_id}\tunless-stopped\t0",
                "\t".join(
                    (
                        "keycloak_contract",
                        "agentium-kc",
                        keycloak_container_id,
                        keycloak_image_id,
                        keycloak_contract_sha256,
                        str(keycloak_port),
                    )
                ),
            )
        )
        + "\n",
        encoding="ascii",
    )
    runtime_state.chmod(0o600)
    phase = deployment / "phase"
    phase.write_text("completed\n", encoding="ascii")
    phase.chmod(0o600)

    def run_verifier(
        *, live: bool = False, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        arguments = [
            "python3",
            "-I",
            "-",
            str(root),
            release_sha,
            engine_id,
            str(source_repo),
            hostname,
        ]
        if live:
            arguments.append("verify-live")
        return subprocess.run(
            arguments,
            input=verifier,
            text=True,
            capture_output=True,
            env=env,
        )

    passed = run_verifier()
    assert passed.returncode == 0, passed.stderr

    original_completion = completion_path.read_bytes()
    original_marker = forward_marker.read_bytes()
    original_authorization = forward_authorization.read_bytes()

    substituted_authorization = json.loads(original_authorization)
    substituted_authorization["purpose"] = "rollback-terminal-open"
    forward_authorization.write_text(
        json.dumps(substituted_authorization, separators=(",", ":"), sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    forward_authorization.chmod(0o600)
    refused_authorization_content = run_verifier()
    assert refused_authorization_content.returncode != 0
    assert "forward terminal authorization differs" in refused_authorization_content.stderr
    forward_authorization.write_bytes(original_authorization)
    forward_authorization.chmod(0o600)

    forward_authorization.chmod(0o644)
    refused_authorization_mode = run_verifier()
    assert refused_authorization_mode.returncode != 0
    assert "unsafe Release A artifact" in refused_authorization_mode.stderr
    forward_authorization.chmod(0o600)

    authorization_target = deployment / "authorization-substitution.json"
    authorization_target.write_bytes(original_authorization)
    authorization_target.chmod(0o600)
    forward_authorization.unlink()
    forward_authorization.symlink_to(authorization_target)
    refused_authorization_symlink = run_verifier()
    assert refused_authorization_symlink.returncode != 0
    assert "unsafe Release A artifact" in refused_authorization_symlink.stderr
    forward_authorization.unlink()
    forward_authorization.write_bytes(original_authorization)
    forward_authorization.chmod(0o600)
    authorization_target.unlink()

    marker_with_wrong_authorization_digest = original_marker.decode("ascii").replace(
        hashlib.sha256(original_authorization).hexdigest(), "0" * 64
    )
    assert marker_with_wrong_authorization_digest != original_marker.decode("ascii")
    forward_marker.write_text(
        marker_with_wrong_authorization_digest,
        encoding="ascii",
    )
    forward_marker.chmod(0o600)
    refused_authorization_digest = run_verifier()
    assert refused_authorization_digest.returncode != 0
    assert "forward-open terminal marker differs" in refused_authorization_digest.stderr
    forward_marker.write_bytes(original_marker)
    forward_marker.chmod(0o600)

    if tampered_helper_name == "agentium_release_a_evidence_bundle.py":
        sftp_invalidation = deployment / "sftp-runtime-identity-invalidation.json"
        sftp_invalidation.write_text("{}\n", encoding="utf-8")
        sftp_invalidation.chmod(0o600)
        refused_invalidated_completion = run_verifier()
        assert refused_invalidated_completion.returncode != 0
        assert (
            "SFTP runtime identity was invalidated"
            in refused_invalidated_completion.stderr
        )
        phase.write_text("opening_forward\n", encoding="ascii")
        phase.chmod(0o600)
        refused_invalidated_nonterminal_phase = run_verifier()
        assert refused_invalidated_nonterminal_phase.returncode != 0
        assert (
            "SFTP runtime identity was invalidated"
            in refused_invalidated_nonterminal_phase.stderr
        )
        phase.write_text("completed\n", encoding="ascii")
        phase.chmod(0o600)
        sftp_invalidation.unlink()
        invalidation_target = deployment / "sftp-invalidation-substitution.json"
        invalidation_target.write_text("{}\n", encoding="utf-8")
        invalidation_target.chmod(0o600)
        sftp_invalidation.symlink_to(invalidation_target)
        refused_invalidated_symlink = run_verifier()
        assert refused_invalidated_symlink.returncode != 0
        assert "SFTP runtime identity was invalidated" in refused_invalidated_symlink.stderr
        sftp_invalidation.unlink()
        invalidation_target.unlink()

        original_runtime_state = runtime_state.read_bytes()
        keycloak_contract_line = original_runtime_state.decode("ascii").splitlines()[-1]
        runtime_state.write_bytes(
            original_runtime_state + (keycloak_contract_line + "\n").encode("ascii")
        )
        runtime_state.chmod(0o600)
        refused_duplicate_keycloak_contract = run_verifier()
        assert refused_duplicate_keycloak_contract.returncode != 0
        assert (
            "historical Keycloak runtime state cardinality differs"
            in refused_duplicate_keycloak_contract.stderr
        )
        runtime_state.write_bytes(
            original_runtime_state.replace(
                keycloak_contract_sha256.encode("ascii"), b"not-a-sha256"
            )
        )
        runtime_state.chmod(0o600)
        refused_malformed_keycloak_contract = run_verifier()
        assert refused_malformed_keycloak_contract.returncode != 0
        assert (
            "historical Keycloak control-plane contract differs"
            in refused_malformed_keycloak_contract.stderr
        )
        runtime_state.write_bytes(original_runtime_state)
        runtime_state.chmod(0o600)

        runtime_receipt = artifacts["release-a-runtime-oci-receipt.json"]
        assert isinstance(runtime_receipt, dict)
        runtime_containers = runtime_receipt["containers"]
        assert isinstance(runtime_containers, list)
        live_containers: dict[str, dict[str, object]] = {}
        live_images: dict[str, dict[str, object]] = {}
        for expected in runtime_containers:
            assert isinstance(expected, dict)
            service = str(expected["service"])
            health_status = str(expected["health_status"])
            state: dict[str, object] = {"Running": True, "Paused": False}
            if health_status != "not_configured":
                state["Health"] = {"Status": health_status}
            live_containers[service] = {
                "Id": expected["container_id"],
                "Image": expected["image_id"],
                "State": state,
                "Config": {
                    "Labels": {"org.opencontainers.image.revision": release_sha}
                },
                "HostConfig": {},
                "NetworkSettings": {},
            }
            live_images[str(expected["image_id"])] = {
                "Config": {
                    "Labels": {"org.opencontainers.image.revision": release_sha}
                }
            }
        live_containers["agentium-sftp"] = {
            "Id": sftp_container_id,
            "Image": sftp_image_id,
            "State": {
                "Running": True,
                "Paused": False,
                "StartedAt": sftp_started_at,
                "Health": {"Status": "healthy"},
            },
            "HostConfig": {
                "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0}
            },
            "Config": {},
            "NetworkSettings": {},
        }
        live_images[sftp_image_id] = {
            "Config": {"Labels": {"org.opencontainers.image.revision": sftp_sha}}
        }
        keycloak_binding = [
            {"HostIp": "127.0.0.1", "HostPort": str(keycloak_port)}
        ]
        live_containers["agentium-kc"] = {
            "Id": keycloak_container_id,
            "Image": keycloak_image_id,
            "State": {
                "Running": True,
                "Paused": False,
                "Restarting": False,
                "Dead": False,
                "OOMKilled": False,
                "Health": {"Status": "healthy"},
            },
            "HostConfig": {
                "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
                "PortBindings": {"8080/tcp": deepcopy(keycloak_binding)},
            },
            "Config": {},
            "NetworkSettings": {
                "Ports": {
                    "8080/tcp": deepcopy(keycloak_binding),
                    "8443/tcp": None,
                    "9000/tcp": [],
                }
            },
        }
        fake_docker_state = {
            "containers": live_containers,
            "images": live_images,
            "build_info": {
                "agentium-backend": runtime_receipt["backend_build_info"],
                "agentium-frontend": {
                    "service": "frontend",
                    "revision": release_sha,
                    "revision_verified": True,
                    "version": "release-a-test",
                },
            },
        }
        fake_bin = tmp_path / "fake-bin"
        fake_bin.mkdir()
        fake_docker = fake_bin / "docker"
        fake_docker.write_text(
            """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state = json.loads(Path(os.environ["AGENTIUM_TEST_DOCKER_STATE"]).read_text())
arguments = sys.argv[1:]
if arguments[:3] == ["inspect", "--type", "container"] and len(arguments) == 4:
    print(json.dumps([state["containers"][arguments[3]]]))
elif arguments[:2] == ["image", "inspect"] and len(arguments) == 3:
    print(json.dumps([state["images"][arguments[2]]]))
elif arguments[:1] == ["exec"] and len(arguments) >= 2:
    print(json.dumps(state["build_info"][arguments[1]]))
else:
    raise SystemExit(f"unexpected fake docker command: {arguments!r}")
""",
            encoding="utf-8",
        )
        fake_docker.chmod(0o700)
        fake_docker_state_path = tmp_path / "fake-docker-state.json"

        def run_live(state: dict[str, object]) -> subprocess.CompletedProcess[str]:
            fake_docker_state_path.write_text(json.dumps(state), encoding="utf-8")
            return run_verifier(
                live=True,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                    "AGENTIUM_TEST_DOCKER_STATE": str(fake_docker_state_path),
                },
            )

        accepted_live = run_live(fake_docker_state)
        assert accepted_live.returncode == 0, accepted_live.stderr

        live_tamper_cases = (
            (
                "container identity",
                ("Id", "7" * 64),
                "historical control-plane contract",
            ),
            (
                "image identity",
                ("Image", f"sha256:{'7' * 64}"),
                "historical control-plane contract",
            ),
            (
                "health",
                ("State.Health.Status", "unhealthy"),
                "historical control-plane contract",
            ),
            (
                "restart policy",
                ("HostConfig.RestartPolicy.Name", "always"),
                "historical control-plane contract",
            ),
            (
                "configured publication",
                ("HostConfig.PortBindings.8080/tcp.0.HostIp", "0.0.0.0"),
                "configured binding is not the attested loopback endpoint",
            ),
            (
                "effective publication",
                ("NetworkSettings.Ports.8080/tcp.0.HostPort", "8082"),
                "effective binding is not the attested loopback endpoint",
            ),
            (
                "additional effective publication",
                (
                    "NetworkSettings.Ports.8443/tcp",
                    [{"HostIp": "127.0.0.1", "HostPort": "8443"}],
                ),
                "effective contains another published endpoint",
            ),
            (
                "unexpected null exposed port",
                ("NetworkSettings.Ports.9443/tcp", None),
                "effective exposed-port inventory differs",
            ),
        )
        for label, (path, value), expected_error in live_tamper_cases:
            tampered_state = deepcopy(fake_docker_state)
            cursor: object = tampered_state["containers"]["agentium-kc"]
            for part in path.split("."):
                if part.isdigit():
                    assert isinstance(cursor, list)
                    cursor = cursor[int(part)]
                elif part == path.split(".")[-1]:
                    assert isinstance(cursor, dict)
                    cursor[part] = value
                else:
                    assert isinstance(cursor, dict)
                    cursor = cursor[part]
            refused_live = run_live(tampered_state)
            assert refused_live.returncode != 0, label
            assert expected_error in refused_live.stderr, label

    def rebind_terminal_authorization_and_marker() -> None:
        authorization_payload = json.loads(original_authorization)
        authorization_payload["receipt_sha256"] = hashlib.sha256(
            completion_path.read_bytes()
        ).hexdigest()
        forward_authorization.write_text(
            json.dumps(authorization_payload, separators=(",", ":"), sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        forward_authorization.chmod(0o600)
        forward_marker.write_text(
            " ".join(
                (
                    "format=2",
                    "direction=forward",
                    f"deployment_id={deployment.name}",
                    f"release_a_sha={release_sha}",
                    "terminal_phase=completed",
                    "receipt_sha256="
                    + hashlib.sha256(completion_path.read_bytes()).hexdigest(),
                    "authorization_sha256="
                    + hashlib.sha256(forward_authorization.read_bytes()).hexdigest(),
                )
            )
            + "\n",
            encoding="ascii",
        )
        forward_marker.chmod(0o600)
    completion_v2 = dict(completion)
    completion_v2["schema_version"] = 2
    completion_path.write_text(json.dumps(completion_v2), encoding="utf-8")
    completion_path.chmod(0o600)
    refused_v2 = run_verifier()
    assert refused_v2.returncode != 0
    assert "completion receipt differs" in refused_v2.stderr
    completion_path.write_bytes(original_completion)
    completion_path.chmod(0o600)

    attestation_receipt_path = deployment / "release-a-verification-receipt.json"
    original_attestation_receipt = attestation_receipt_path.read_bytes()
    downgraded_attestation_receipt = dict(attestation_receipt)
    downgraded_attestation_receipt["schema_version"] = 3
    attestation_receipt_path.write_text(
        json.dumps(downgraded_attestation_receipt), encoding="utf-8"
    )
    attestation_receipt_path.chmod(0o600)
    rebound_completion = dict(completion)
    rebound_completion["release_a_attestation_receipt_sha256"] = hashlib.sha256(
        attestation_receipt_path.read_bytes()
    ).hexdigest()
    completion_path.write_text(json.dumps(rebound_completion), encoding="utf-8")
    completion_path.chmod(0o600)
    rebind_terminal_authorization_and_marker()
    refused_attestation_v3 = run_verifier()
    assert refused_attestation_v3.returncode != 0
    assert "attestation receipt schema differs" in refused_attestation_v3.stderr
    attestation_receipt_path.write_bytes(original_attestation_receipt)
    attestation_receipt_path.chmod(0o600)
    completion_path.write_bytes(original_completion)
    completion_path.chmod(0o600)
    forward_authorization.write_bytes(original_authorization)
    forward_authorization.chmod(0o600)
    forward_marker.write_bytes(original_marker)
    forward_marker.chmod(0o600)

    sftp_receipt_path = deployment / sftp_receipt_name
    original_sftp_receipt = sftp_receipt_path.read_bytes()
    substituted_sftp_receipt = json.loads(original_sftp_receipt)
    mutation_target = substituted_sftp_receipt
    for key in sftp_mutation_path[:-1]:
        mutation_target = mutation_target[key]
    mutation_target[sftp_mutation_path[-1]] = sftp_mutation_value
    sftp_receipt_path.write_text(
        json.dumps(substituted_sftp_receipt), encoding="utf-8"
    )
    sftp_receipt_path.chmod(0o600)
    rebound_completion = dict(completion)
    rebound_completion[sftp_completion_key] = hashlib.sha256(
        sftp_receipt_path.read_bytes()
    ).hexdigest()
    completion_path.write_text(json.dumps(rebound_completion), encoding="utf-8")
    completion_path.chmod(0o600)
    rebind_terminal_authorization_and_marker()
    refused_sftp_receipt = run_verifier()
    assert refused_sftp_receipt.returncode != 0
    assert expected_sftp_error in refused_sftp_receipt.stderr
    sftp_receipt_path.write_bytes(original_sftp_receipt)
    sftp_receipt_path.chmod(0o600)
    completion_path.write_bytes(original_completion)
    completion_path.chmod(0o600)
    forward_authorization.write_bytes(original_authorization)
    forward_authorization.chmod(0o600)
    forward_marker.write_bytes(original_marker)
    forward_marker.chmod(0o600)

    forward_marker.write_text("format=1 substituted\n", encoding="ascii")
    forward_marker.chmod(0o600)
    refused_marker = run_verifier()
    assert refused_marker.returncode != 0
    assert "forward-open terminal marker differs" in refused_marker.stderr
    forward_marker.write_bytes(original_marker)
    forward_marker.chmod(0o600)

    evidence = deployment / "release-a-final-evidence-receipt.json"
    original_evidence = evidence.read_bytes()
    evidence.write_text(json.dumps({"release_a_sha": "b" * 40}), encoding="utf-8")
    evidence.chmod(0o600)
    refused = run_verifier()
    assert refused.returncode != 0
    assert "binding differs" in refused.stderr

    evidence.write_bytes(original_evidence)
    evidence.chmod(0o600)

    original_keyring = keyring.read_bytes()
    keyring.write_text(json.dumps({"authorities": []}), encoding="utf-8")
    keyring.chmod(0o600)
    refused_keyring = run_verifier()
    assert refused_keyring.returncode != 0
    assert "versioned Release A authority keyring differs" in refused_keyring.stderr
    keyring.write_bytes(original_keyring)
    keyring.chmod(0o600)

    original_binding_manifest = binding_manifest_path.read_bytes()
    binding_manifest_path.write_text(
        json.dumps({**binding_manifest, "reference_count": 34}), encoding="utf-8"
    )
    binding_manifest_path.chmod(0o600)
    refused_manifest = run_verifier()
    assert refused_manifest.returncode != 0
    assert "binding manifest digest differs" in refused_manifest.stderr
    binding_manifest_path.write_bytes(original_binding_manifest)
    binding_manifest_path.chmod(0o600)

    original_proof = proof.read_bytes()
    proof.write_bytes(b"substituted-frozen-evidence")
    proof.chmod(0o600)
    refused_frozen_evidence = run_verifier()
    assert refused_frozen_evidence.returncode != 0
    assert "frozen evidence helper refused" in refused_frozen_evidence.stderr
    proof.write_bytes(original_proof)
    proof.chmod(0o600)

    frozen_dependency = deployment / tampered_helper_name
    original_dependency = frozen_dependency.read_bytes()
    frozen_dependency.write_text("VALUE = 'substituted'\n", encoding="utf-8")
    frozen_dependency.chmod(0o700)
    refused_dependency = run_verifier()
    assert refused_dependency.returncode != 0
    assert "versioned Release A helper differs" in refused_dependency.stderr
    frozen_dependency.write_bytes(original_dependency)
    frozen_dependency.chmod(0o700)

    runtime = deployment / "release-a-runtime-oci-receipt.json"
    runtime_payload = json.loads(runtime.read_text(encoding="utf-8"))
    runtime_payload["backend_build_info"]["revision"] = "b" * 40
    runtime.write_text(json.dumps(runtime_payload), encoding="utf-8")
    runtime.chmod(0o600)
    refused_runtime = run_verifier()
    assert refused_runtime.returncode != 0
    assert "binding differs" in refused_runtime.stderr


def test_release_a_manifest_v3_is_an_independent_mandatory_revalidated_trust_gate() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    ensure_manifest = _shell_function(script, "ensure_release_a_manifest_gate")
    freeze = _shell_function(script, "freeze_release_a_manifest_artifact")
    verify = _shell_function(script, "run_release_a_manifest_verification")
    recorded = _shell_function(script, "assert_recorded_release_a_manifest_gate")
    receipt = _shell_function(script, "assert_release_a_manifest_receipt_contract")
    reverify = _shell_function(script, "assert_release_a_manifest_reverification")
    initialize = _shell_function(script, "initialize_metadata")
    set_phase = _shell_function(script, "set_phase")
    apply_preflight = _shell_function(script, "apply_preflight_checks")
    dispatch = script.rsplit('case "$MODE" in', 1)[1]
    preflight = dispatch.split("preflight)", 1)[1].split("\n\t;;", 1)[0]
    startup = script.rsplit("ensure_runtime_env_bundle", 1)[1]

    for option in (
        "--release-a-manifest",
        "--release-a-manifest-sha256",
        "--release-a-review-policy",
        "--release-a-review-policy-sha256",
    ):
        assert option in script
    assert "manifeste, revue Release A et leurs SHA-256 explicites sont obligatoires" in (
        ensure_manifest
    )
    assert "O_NOFOLLOW" in freeze
    assert "before.st_nlink != 1" in freeze
    assert "mode not in {0o400, 0o600}" in freeze
    assert "resolved_repository in resolved_source.parents" in freeze
    assert "hashlib.sha256(content).hexdigest() != expected" in freeze
    assert 'durable_publish_file "$temporary" "$target"' in freeze
    assert '"$RELEASE_A_MANIFEST_HELPER" verify' in verify
    assert '--repository "$REPO_DIR"' in verify
    assert '--release-a-sha "$release_a_sha"' in verify
    assert '--review-policy "$FROZEN_RELEASE_A_REVIEW_POLICY"' in verify
    assert '--manifest "$FROZEN_RELEASE_A_MANIFEST"' in verify
    assert "agentium-release-a-diff-verification-v7" in receipt
    assert "agentium-release-a-diff-manifest-v7" in receipt
    assert "agentium-release-a-semantic-review-v1" in receipt
    assert 'review.get("approval") != "approved"' in receipt
    assert "assert_release_a_manifest_receipt_contract" in recorded
    assert "assert_release_a_manifest_reverification" in recorded
    assert "stable_keys" in reverify
    assert "verified_at" not in reverify.split("stable_keys =", 1)[1].split("}", 1)[0]
    assert "release_a_manifest_sha256" in initialize
    assert "release_a_review_policy_sha256" in initialize
    assert "release_a_manifest_receipt_sha256" in initialize
    assert "printf 'format\\t5\\n'" in initialize
    assert preflight.index("preflight_checks") < preflight.index("ensure_release_a_manifest_gate")
    assert preflight.index("ensure_release_a_manifest_gate") < preflight.index(
        "ensure_release_a_gate"
    )
    assert preflight.index("ensure_release_a_gate") < preflight.index("initialize_metadata")
    assert startup.index("assert_recorded_release_a_manifest_gate") < startup.index(
        "assert_recorded_release_a_gate"
    )
    assert set_phase.index("assert_recorded_release_a_manifest_gate") < set_phase.index(
        'atomic_text "$PHASE_FILE"'
    )
    assert apply_preflight.index("assert_recorded_release_a_manifest_gate") < (
        apply_preflight.index("assert_storage_capacity_and_layout")
    )


def test_workspace_targets_are_resolved_by_canonical_markers_before_metadata() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    render = _shell_function(script, "render_workspace_target_gate")
    contract = _shell_function(script, "assert_workspace_target_gate_contract")
    ensure = _shell_function(script, "ensure_workspace_target_gate")
    frozen = _shell_function(script, "assert_frozen_workspace_target_gate")
    recorded = _shell_function(script, "assert_recorded_workspace_target_gate")
    initialize = _shell_function(script, "initialize_metadata")
    dispatch = script.rsplit('case "$MODE" in', 1)[1]
    preflight = dispatch.split("preflight)", 1)[1].split("\n\t;;", 1)[0]

    assert 'WORKSPACE_TARGETS="$DEPLOY_DIR/workspace-targets.json"' in script
    assert "BEGIN TRANSACTION READ ONLY" in render
    assert "SELECT id," in render and "slug," in render
    assert "WHERE is_active IS TRUE AND deleted_at IS NULL" in render
    assert "showcase_seed" in render
    assert 'row["family"] == "andritz"' in render
    assert 'row["family"] == "sentinel_ci"' in render
    assert 'row["profile"] == "sentinel_government_v1"' in render
    assert 'row["assistant"] == "vigie_executive"' in render
    assert 'row["family"] == "generic"' in render
    assert 'row["profile"] == "octocity_institutional_v1"' in render
    assert 'row["assistant"] == "octave_executive"' in render
    assert 'sorted(target["workspace_id"] for target in selected.values()) != expected_ids' in render
    assert 'len({target["workspace_id"] for target in selected.values()}) != 4' in render
    assert 'len({target["workspace_slug"] for target in selected.values()}) != 4' in render
    assert 'selected["showcase"]["workspace_slug"]' in render
    assert '"profile": "agentium-workspace-target-gate-v2"' in render
    assert '"schema_version": 2' in render
    assert 'payload.get("operator_workspace_ids") != expected_ids' in contract
    assert "sorted(resolved_ids) != expected_ids" in contract
    assert '"workspace_slug",' in contract
    assert "len(set(resolved_slugs)) != 4" in contract
    assert 'durable_publish_file "$temporary" "$WORKSPACE_TARGETS"' in ensure
    assert 'cmp -s "$temporary" "$WORKSPACE_TARGETS"' in ensure
    assert "metadata workspace_targets_sha256" in frozen
    assert "assert_frozen_workspace_target_gate" in recorded
    assert "workspace_targets_sha256" in initialize
    assert preflight.index("ensure_release_a_gate") < preflight.index(
        "ensure_workspace_target_gate"
    )
    assert preflight.index("ensure_workspace_target_gate") < preflight.index("initialize_metadata")


def test_workspace_target_gate_is_rechecked_before_mutation_and_scopes_backfill() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    apply_preflight = _shell_function(script, "apply_preflight_checks")
    capture = _shell_function(script, "capture_workspace_app_backfill_analysis")
    apply = _shell_function(script, "apply_workspace_app_backfill")
    migrate = _shell_function(script, "migrate_candidate")
    startup = script.rsplit("resolve_runtime_paths", 1)[1]

    assert apply_preflight.index("assert_recorded_workspace_target_gate") < apply_preflight.index(
        "assert_storage_capacity_and_layout"
    )
    assert capture.index("assert_recorded_workspace_target_gate") < capture.index(
        "workspace_app_backfill_args"
    )
    assert apply.index("assert_recorded_workspace_target_gate") < apply.index(
        "workspace_app_backfill_args"
    )
    assert migrate.index("assert_recorded_workspace_target_gate") < migrate.index(
        "open_candidate_migration_boundary"
    )
    assert 'p.get("requested_workspace_ids") == expected' in capture
    assert (
        'sorted(item.get("workspace_id") for item in p.get("workspaces", [])) == expected'
        in capture
    )
    assert (
        'all(change.get("workspace_id") in expected for change in p.get("changes", []))' in capture
    )
    assert 'post.get("requested_workspace_ids") == workspace_ids' in apply
    assert 'all(change.get("workspace_id") in workspace_ids' in apply
    assert "assert_frozen_workspace_target_gate" in startup
    assert "assert_recorded_workspace_target_gate" not in startup


def test_release_b_cannot_replace_the_release_a_gate_that_authorizes_it(tmp_path: Path) -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    trust_root = _shell_function(script, "assert_release_a_helper_trust_root")
    repository = tmp_path / "repo"
    helper = repository / "scripts" / "agentium_release_a_attestation.py"
    helper.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    helper.write_text("trusted gate\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "scripts"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "release a"], check=True)
    release_a_sha = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
    ).strip()

    (repository / "README").write_text("candidate\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "safe candidate"], check=True)
    same_gate_sha = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
    ).strip()

    helper.write_text("candidate-controlled gate\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "scripts"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "unsafe candidate"], check=True)
    changed_gate_sha = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
    ).strip()

    harness = f"""
set -Eeuo pipefail
die() {{ printf '%s\\n' "$*" >&2; exit 1; }}
REPO_DIR="$1"
EXPECTED_SHA="$2"
assert_release_a_helper_trust_root() {{
{trust_root}
}}
assert_release_a_helper_trust_root "$3"
"""
    accepted = subprocess.run(
        ["bash", "-c", harness, "bash", str(repository), same_gate_sha, release_a_sha],
        check=False,
        capture_output=True,
        text=True,
    )
    rejected = subprocess.run(
        ["bash", "-c", harness, "bash", str(repository), changed_gate_sha, release_a_sha],
        check=False,
        capture_output=True,
        text=True,
    )

    assert accepted.returncode == 0, accepted.stderr
    assert rejected.returncode != 0
    assert "trust root refusée" in rejected.stderr


def test_release_b_cannot_replace_the_release_a_manifest_helper(tmp_path: Path) -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    trust_root = _shell_function(script, "assert_release_a_manifest_helper_trust_root")
    repository = tmp_path / "repo"
    helper = repository / "scripts" / "agentium_release_a_manifest.py"
    helper.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    helper.write_text("trusted manifest gate\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "scripts"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "release a"], check=True)
    release_a_sha = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
    ).strip()

    (repository / "README").write_text("candidate\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "safe candidate"], check=True)
    same_gate_sha = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
    ).strip()

    helper.write_text("candidate-controlled manifest gate\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "scripts"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "unsafe candidate"], check=True)
    changed_gate_sha = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
    ).strip()

    harness = f"""
set -Eeuo pipefail
die() {{ printf '%s\\n' "$*" >&2; exit 1; }}
REPO_DIR="$1"
EXPECTED_SHA="$2"
assert_release_a_manifest_helper_trust_root() {{
{trust_root}
}}
assert_release_a_manifest_helper_trust_root "$3"
"""
    accepted = subprocess.run(
        ["bash", "-c", harness, "bash", str(repository), same_gate_sha, release_a_sha],
        check=False,
        capture_output=True,
        text=True,
    )
    rejected = subprocess.run(
        ["bash", "-c", harness, "bash", str(repository), changed_gate_sha, release_a_sha],
        check=False,
        capture_output=True,
        text=True,
    )

    assert accepted.returncode == 0, accepted.stderr
    assert rejected.returncode != 0
    assert "trust root refusée" in rejected.stderr


def test_preflight_cannot_rewind_an_advanced_or_terminal_transaction() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    dispatch = script.rsplit('case "$MODE" in', 1)[1]
    preflight = dispatch.split("preflight)", 1)[1].split("\n\t;;", 1)[0]

    assert '"$preflight_phase" == "new"' in preflight
    assert '"$preflight_phase" == "preflight_ok"' in preflight
    assert "Preflight interdit sur une transaction déjà avancée ou terminale" in preflight
    assert preflight.count("set_phase preflight_ok") == 1


def test_prepare_and_apply_refuse_new_state_before_backup_or_build() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    prepare = _shell_function(script, "prepare_impl")

    refusal = '[[ "$current" != "new" ]]'
    assert refusal in prepare
    assert prepare.index(refusal) < prepare.index("preflight_checks")
    assert prepare.index(refusal) < prepare.index("create_backup preparation")
    assert prepare.index(refusal) < prepare.index("build_candidate_in_worktree")


def test_postgresql_inventory_v2_binds_only_post_canary_captures_to_ledger() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    capture = _shell_function(script, "capture_candidate_database_inventory")
    refresh = _shell_function(script, "refresh_and_build_validation")
    finalize = _shell_function(script, "finalize_deployment")

    assert "agentium-postgresql-row-inventory-v2" in capture
    assert 'binding.get("provided") is (mode == "controlled")' in capture
    assert "run_candidate_with_readonly_inputs" in capture
    assert '--readonly-input "$DEPLOY_DIR/proofs/chat-ledger.json" chat-ledger.json' in capture
    assert "--ledger /safe-inputs/chat-ledger.json" in capture
    assert 'capture_candidate_database_inventory "$DATABASE_CANARY_BASELINE"' in script
    assert (
        'capture_candidate_database_inventory "$DATABASE_POST_CANARY_INVENTORY" controlled'
        in refresh
    )
    assert (
        'capture_candidate_database_inventory "$DATABASE_FINAL_CANARY_INVENTORY" controlled'
        in refresh
    )
    assert (
        'capture_candidate_database_inventory "$DATABASE_OPENING_RECAPTURE" controlled' in finalize
    )
    assert "agentium-controlled-canary-postgresql-v2" in script
    assert 'durable_replace_file "$temporary" "$output"' in capture


def test_postgresql_backups_have_a_durable_ready_marker_before_phase_advance() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    create = _shell_function(script, "create_backup")
    verify = _shell_function(script, "verify_backup")
    quiesce = _shell_function(script, "quiesce_all_writers")
    migrate = _shell_function(script, "migrate_candidate")
    resume = _shell_function(script, "reestablish_persisted_phase_boundary")

    assert 'durable_publish_file "$temporary" "$backup"' in create
    assert 'atomic_text "$backup.sha256"' in create
    assert 'atomic_text "$backup.ready"' in create
    assert create.index('durable_publish_file "$temporary" "$backup"') < create.index(
        'atomic_text "$backup.ready"'
    )
    assert 'ready="$backup.ready"' in verify
    assert "docker exec -i agentium-pg pg_restore --list" in verify
    assert quiesce.index("create_backup quiesced") < quiesce.index("set_phase quiesced")
    assert 'verify_backup "$DEPLOY_DIR/postgres-quiesced.dump"' in migrate
    assert 'verify_backup "$DEPLOY_DIR/postgres-quiesced.dump"' in resume


def test_workspace_app_backfill_publishes_each_authoritative_report_once() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    apply = _shell_function(script, "apply_workspace_app_backfill")
    analyze = _shell_function(script, "analyze_workspace_app_backfill")
    publish_post = _shell_function(script, "publish_or_verify_workspace_app_post")

    assert 'capture_workspace_app_backfill_analysis "$recovery"' in apply
    assert 'analyze_workspace_app_backfill "$WORKSPACE_APP_POST"' not in apply
    assert apply.count("publish_or_verify_workspace_app_post") == 1
    assert 'capture_workspace_app_backfill_analysis "$temporary"' in analyze
    assert 'assert_private_state_file "$output"' in analyze
    assert 'cmp -s "$temporary" "$output"' in analyze
    assert 'durable_publish_file "$temporary" "$output"' in analyze
    assert 'durable_publish_file "$temporary" "$WORKSPACE_APP_POST"' in publish_post
    assert 'cmp -s "$temporary" "$WORKSPACE_APP_POST"' in publish_post


def test_workspace_app_dry_run_replay_accepts_only_the_identical_report(
    tmp_path: Path,
) -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    analyze = _shell_function(script, "analyze_workspace_app_backfill")
    harness = f"""
set -Eeuo pipefail
DEPLOY_DIR="$1"
PAYLOAD="$2"
ACTION="$3"
die() {{ printf '%s\\n' "$*" >&2; exit 1; }}
assert_private_state_file() {{
    [[ -f "$1" && ! -L "$1" ]]
}}
durable_publish_file() {{ mv -- "$1" "$2"; chmod 0600 "$2"; }}
capture_workspace_app_backfill_analysis() {{
    (umask 077; printf '%s\\n' "$PAYLOAD" >"$1")
}}
analyze_workspace_app_backfill() {{
{analyze}
}}
output="$DEPLOY_DIR/workspace-app-backfill-dry-run.json"
analyze_workspace_app_backfill "$output"
if [[ "$ACTION" == "replay" ]]; then analyze_workspace_app_backfill "$output"; fi
"""
    accepted = subprocess.run(
        ["bash", "-c", harness, "bash", str(tmp_path), '{"stable":true}', "replay"],
        check=False,
        capture_output=True,
        text=True,
    )
    rejected = subprocess.run(
        ["bash", "-c", harness, "bash", str(tmp_path), '{"stable":false}', "verify"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert accepted.returncode == 0, accepted.stderr
    assert rejected.returncode != 0
    assert "durable divergente" in rejected.stderr


def test_preflight_reuses_only_a_valid_atomically_published_storage_baseline() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    ensure = _shell_function(script, "ensure_storage_baseline")
    validate = _shell_function(script, "assert_storage_baseline_contract")
    dispatch = script.rsplit('case "$MODE" in', 1)[1]
    preflight = dispatch.split("preflight)", 1)[1].split("\n\t;;", 1)[0]

    assert '[[ -e "$STORAGE_BASELINE" || -L "$STORAGE_BASELINE" ]]' in ensure
    assert ensure.index("assert_storage_baseline_contract") < ensure.index("return")
    assert 'snapshot_storage "$STORAGE_BASELINE"' in ensure
    assert ensure.rindex("assert_storage_baseline_contract") > ensure.index(
        'snapshot_storage "$STORAGE_BASELINE"'
    )
    assert 'assert_private_state_file "$STORAGE_BASELINE"' in validate
    assert "agentium-storage-attestation-v3" in validate
    assert preflight.index("initialize_metadata") < preflight.index("ensure_storage_baseline")
    assert preflight.index("ensure_storage_baseline") < preflight.index("set_phase preflight_ok")
    assert "Baseline stockage orpheline" not in preflight


def test_candidate_checkout_has_a_durable_replayable_a_to_b_boundary() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    ensure = _shell_function(script, "ensure_candidate_checkout_intent")
    validate = _shell_function(script, "assert_candidate_checkout_intent")
    quiesce = _shell_function(script, "quiesce_all_writers")
    apply = _shell_function(script, "apply_impl")

    assert 'durable_publish_file "$temporary" "$CANDIDATE_CHECKOUT_INTENT"' in ensure
    for field in ("deployment_id", "previous_sha", "candidate_sha", "checkout_authorized"):
        assert field in ensure + validate
    assert quiesce.index("ensure_candidate_checkout_intent") < quiesce.index(
        'git reset --hard "$EXPECTED_SHA"'
    )
    assert quiesce.index('git reset --hard "$EXPECTED_SHA"') < quiesce.index("set_phase quiesced")
    assert '"$current" == "maintenance_closed"' in apply
    assert '"$checkout_sha" == "$EXPECTED_SHA"' in apply
    assert apply.index('"$checkout_sha" == "$EXPECTED_SHA"') < apply.index(
        "assert_candidate_checkout_intent"
    )


def test_candidate_checkout_intent_is_idempotent_and_transaction_bound(
    tmp_path: Path,
) -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    ensure = _shell_function(script, "ensure_candidate_checkout_intent")
    validate = _shell_function(script, "assert_candidate_checkout_intent")
    previous = "a" * 40
    candidate = "b" * 40
    harness = f"""
set -Eeuo pipefail
DEPLOY_DIR="$1"
DEPLOYMENT_ID="release-boundary-test"
EXPECTED_SHA="$2"
PREVIOUS_SHA="$3"
CANDIDATE_CHECKOUT_INTENT="$DEPLOY_DIR/candidate-checkout.intent"
metadata() {{ [[ "$1" == "previous_sha" ]]; printf '%s\\n' "$PREVIOUS_SHA"; }}
assert_private_state_file() {{ [[ -f "$1" && ! -L "$1" ]]; }}
durable_publish_file() {{ chmod 0600 "$1"; mv -- "$1" "$2"; }}
assert_candidate_checkout_intent() {{
{validate}
}}
ensure_candidate_checkout_intent() {{
{ensure}
}}
ensure_candidate_checkout_intent
ensure_candidate_checkout_intent
"""
    accepted = subprocess.run(
        ["bash", "-c", harness, "bash", str(tmp_path), candidate, previous],
        check=False,
        capture_output=True,
        text=True,
    )
    assert accepted.returncode == 0, accepted.stderr

    intent = tmp_path / "candidate-checkout.intent"
    intent.write_text(intent.read_text(encoding="utf-8").replace(candidate, "c" * 40))
    rejected = subprocess.run(
        ["bash", "-c", harness, "bash", str(tmp_path), candidate, previous],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "differs from this transaction" in rejected.stderr


def test_migration_contract_separates_data_stability_from_exact_revision_change() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    fingerprint = _shell_function(script, "capture_sql_database_fingerprint")
    migration = _shell_function(script, "assert_additive_migration_contract")

    assert "tablename NOT IN ('alembic_version'" in fingerprint
    assert '"$source_revision" == "064_run_dispatch_outbox"' in migration
    assert '"$target_revision" == "076_decision_scenario_lineage"' in migration
    assert '"revision_transition_exact"' in migration


def test_preflight_requires_three_rw_filesystems_and_explicit_capacity() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")

    assert 'root_device="$(device_id /)"' in script
    assert 'data_device="$(device_id "$DATA_ROOT")"' in script
    assert 'secure_device="$(device_id "$SECURE_DEPOSIT_PATH")"' in script
    assert 'root_device" != "$data_device' in script
    assert 'assert_rw_mount "$path"' in script
    assert 'assert_inode_margin "$path"' in script
    assert "42949672960" in script  # 40 GiB root margin
    assert "68719476736" in script  # 64 GiB data/deposit margin
    assert 'secure_required=$(( $(total_bytes "$SECURE_DEPOSIT_PATH") / 10 ))' in script
    assert 'docker_root="$(docker info --format' in script
    assert 'pg_source="$(docker inspect' in script
    assert '"$(privileged_device_id "$docker_root")" == "$root_device"' in script
    assert '"$(privileged_device_id "$pg_source")" == "$root_device"' in script


def test_public_gate_and_sftp_are_fail_closed_before_other_writers_stop() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    quiesce = script.split("quiesce_all_writers() {", 1)[1].split("\n}\n\nmigrate_candidate()", 1)[
        0
    ]
    sftp = script.split("quiesce_sftp() {", 1)[1].split("\n}\n\nassert_rabbitmq_empty()", 1)[0]

    assert "nginx -T" in script
    assert "agentium-deploy-maintenance.conf" in script
    assert "return 503" in script
    assert quiesce.index("gate enter") < quiesce.index("quiesce_sftp")
    assert quiesce.index("quiesce_sftp") < quiesce.index("agentium-backend agentium-worker-cpu")
    assert "docker pause agentium-sftp" in sftp
    assert "enter_sftp_ingress_gate" in sftp
    assert sftp.index("enter_sftp_ingress_gate") < sftp.index("docker pause agentium-sftp")
    assert sftp.index("docker pause agentium-sftp") < sftp.index(
        "sftp_established_connection_count"
    )
    assert sftp.index("sftp_open_deposit_fd_count") < sftp.index(
        "docker stop --time 30 agentium-sftp"
    )
    assert "DOCKER-USER" in script
    assert "--ctorigdstport" in script
    assert "--ctstate NEW" in script
    assert "SFTP_GATE_COMMENT" in script
    assert "! -i lo" in _shell_function(script, "sftp_gate_rule")
    assert "assert_no_foreign_sftp_ingress_gate" in script
    assert '[[ "$own_count" == "0" ]]' in script
    assert '"$own_count" == "2"' not in script
    assert '$1 != "TIME-WAIT" && $4 ~' in script
    assert 'assert_tcp_listener_loopback_only "$sftp_port"' not in script
    assert "RabbitMQ contient encore des messages" in script
    assert "pid<>pg_backend_pid()" in script
    assert "même idle" in script


def test_sftp_firewall_partial_failure_is_monotone_and_forces_ro_fallback(
    tmp_path: Path,
) -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    enter = _shell_function(script, "enter_sftp_ingress_gate")
    fallback = _shell_function(script, "sftp_fail_closed_fallback")

    assert "leave_sftp_ingress_gate" not in enter
    assert "sftp_fail_closed_fallback" in enter
    assert "bootstrap_stop_sftp_writers" in fallback
    assert "container_restart_policy agentium-sftp" in fallback
    assert "systemctl is-active --quiet agentium-sftp.service" in fallback
    assert '== *,ro,*' in fallback

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ("iptables", "ip6tables"):
        executable = fake_bin / name
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
        executable.chmod(0o755)
    state = tmp_path / "rules"
    state.mkdir()
    log = tmp_path / "events.log"
    harness = f"""
set -Eeuo pipefail
STATE="$1"
LOG="$2"
sftp_host_port() {{ printf '%s\n' 2222; }}
sftp_gate_rule() {{
    local action="$1" tool="$2" chain="$3" key="$STATE/$tool-$chain"
    case "$action" in
    -C) [[ -e "$key" ]] ;;
    -I)
        if [[ "$tool:$chain" == ip6tables:DOCKER-USER ]]; then return 42; fi
        : >"$key"
        printf 'INSERT %s %s\n' "$tool" "$chain" >>"$LOG"
        ;;
    -D)
        printf 'DELETE %s %s\n' "$tool" "$chain" >>"$LOG"
        rm -f "$key"
        ;;
    esac
}}
sftp_ingress_gate_is_closed() {{ return 1; }}
sftp_fail_closed_fallback() {{ printf 'FALLBACK\n' >>"$LOG"; return 0; }}
die() {{ printf '%s\n' "$*" >&2; return 1; }}
enter_sftp_ingress_gate() {{
{enter}
}}
enter_sftp_ingress_gate
"""
    environment = dict(os.environ)
    environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
    result = subprocess.run(
        ["bash", "-c", harness, "bash", str(state), str(log)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode != 0
    events = log.read_text(encoding="utf-8").splitlines()
    assert events[-1] == "FALLBACK"
    assert not any(event.startswith("DELETE") for event in events)
    assert (state / "iptables-INPUT").exists()
    assert (state / "iptables-DOCKER-USER").exists()
    assert (state / "ip6tables-INPUT").exists()


def test_sigkill_opening_resume_bootstrap_recloses_before_early_validation(
    tmp_path: Path,
) -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    bootstrap = _shell_function(script, "bootstrap_opening_reclosure")
    stop_all = _shell_function(script, "bootstrap_stop_all_writers")
    stop_sftp = _shell_function(script, "bootstrap_stop_sftp_writers")
    startup = script.split(
        "unset AGENTIUM_QDRANT_EFFECTIVE_API_KEY", 1
    )[1].split("\non_error() {", 1)[0]

    assert startup.index("trap 'bootstrap_on_error $?' ERR") < startup.index(
        "assert_local_docker_socket"
    )
    assert startup.index("trap 'bootstrap_on_exit $?' EXIT") < startup.index(
        "assert_local_docker_socket"
    )
    assert startup.index("trap 'exit 143' TERM") < startup.index(
        "assert_local_docker_socket"
    )
    assert startup.index("bootstrap_opening_reclosure\n") < startup.index(
        "assert_local_docker_socket"
    )
    assert startup.index("bootstrap_opening_reclosure\n") < startup.index(
        "validate_operator_inputs"
    )
    assert startup.index("validate_operator_inputs") < startup.index(
        "assert_local_docker_socket"
    )
    assert "bootstrap_close_sftp_ingress_monotone" in bootstrap
    assert "bootstrap_stop_all_writers" in bootstrap
    writer_inventory = (
        "agentium-backend agentium-worker-cpu agentium-p4-maintenance "
        "agentium-livekit agentium-livekit-agent agentium-kc"
    )
    assert writer_inventory in stop_all
    assert stop_all.index("bootstrap_stop_sftp_writers") < stop_all.index(
        writer_inventory
    )
    assert "docker update --restart=no" in stop_all
    assert "docker stop --time 15" in stop_all
    assert "systemctl stop agentium-backend.service" in stop_all
    assert "docker update --restart=no agentium-sftp" in stop_sftp
    assert "docker stop --time 15 agentium-sftp" in stop_sftp
    assert "systemctl stop agentium-sftp.service" in stop_sftp
    assert "bootstrap_secure_deposit_read_only" in stop_sftp

    deployment = tmp_path / "deployment"
    deployment.mkdir()
    phase = deployment / "phase"
    log = tmp_path / "bootstrap.log"
    harness = f"""
set -Eeuo pipefail
DATA_ROOT=/srv/agentium-data
STATE_ROOT=/srv/agentium-data/deployments
DEPLOY_DIR="$1"
DEPLOYMENT_ID=release-b-bootstrap-test
PHASE_FILE="$DEPLOY_DIR/phase"
BOOTSTRAP_OPENING_ACTIVE=0
BOOTSTRAP_OPENING_SEALED=0
LOG="$2"
stat() {{ printf '600:%s:1\n' "$(id -u)"; }}
bootstrap_close_sftp_ingress_monotone() {{ printf 'firewall\n' >>"$LOG"; }}
bootstrap_stop_all_writers() {{ printf 'stop-all-writers\n' >>"$LOG"; }}
bootstrap_opening_reclosure() {{
{bootstrap}
}}
bootstrap_opening_reclosure
printf '%s:%s\n' "$BOOTSTRAP_OPENING_ACTIVE" "$BOOTSTRAP_OPENING_SEALED" >>"$LOG"
"""
    for persisted_phase in ("opening_forward", "rollback_opening"):
        phase.write_text(f"{persisted_phase}\n", encoding="ascii")
        phase.chmod(0o600)
        log.unlink(missing_ok=True)
        result = subprocess.run(
            ["bash", "-c", harness, "bash", str(deployment), str(log)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert log.read_text(encoding="utf-8").splitlines() == [
            "firewall",
            "stop-all-writers",
            "1:1",
        ]


def test_sftp_ingress_gate_survives_validation_and_is_removed_only_on_release() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    finalize = _shell_function(script, "finalize_deployment")
    release = _shell_function(script, "release_sftp_ingress_with_attestation")
    deposit_release = _shell_function(script, "remount_secure_deposit_after_sftp_proof")
    ingress_release = _shell_function(script, "open_sftp_ingress_after_attestation")
    recovery = _shell_function(script, "recover_pre_migration_failure")
    rollback_reopen = _shell_function(script, "reconcile_rollback_opening")
    rollback_release = _shell_function(
        script, "release_rollback_sftp_ingress_with_attestation"
    )

    assert finalize.index("restore_auxiliary_runtime_state") < finalize.index(
        "release_sftp_ingress_with_attestation"
    )
    assert finalize.index("release_sftp_ingress_with_attestation") < finalize.index(
        "remount_secure_deposit_after_sftp_proof"
    )
    assert finalize.index("remount_secure_deposit_after_sftp_proof") < finalize.index(
        "open_sftp_ingress_after_attestation"
    )
    assert finalize.index("open_sftp_ingress_after_attestation") < finalize.index(
        "restore_sftp_restart_policy"
    )
    assert finalize.index("restore_sftp_restart_policy") < finalize.index("gate exit")
    assert release.index("docker-protocol") < release.index("host-banner")
    assert release.index("host-banner") < release.index('"passed:${runtime_sha}')
    assert "leave_sftp_ingress_gate" not in release
    assert deposit_release.index("assert_sftp_opening_intent_contract") < deposit_release.index(
        "set_secure_deposit_mode rw"
    )
    assert "leave_sftp_ingress_gate" not in deposit_release
    assert "set_secure_deposit_mode rw" not in ingress_release
    assert "leave_sftp_ingress_gate" in ingress_release
    assert "assert_sftp_opening_intent_contract" in release
    assert '--validation-proof "$DEPLOY_DIR/validation.json"' in release
    assert '--closed-proof "$SFTP_CLOSED_AFTER"' in release
    assert recovery.index("invalidate_quiesced_artifacts") < recovery.index(
        "leave_sftp_ingress_gate"
    )
    assert recovery.index("leave_sftp_ingress_gate") < recovery.index('"$MAINTENANCE_HELPER" exit')
    assert rollback_reopen.index("restore_auxiliary_runtime_state") < rollback_reopen.index(
        "release_rollback_sftp_ingress_with_attestation"
    )
    assert rollback_reopen.index(
        "release_rollback_sftp_ingress_with_attestation"
    ) < rollback_reopen.index("gate exit")
    assert "rollback-continuity" in rollback_release
    assert "set_secure_deposit_mode rw" not in rollback_release
    assert "leave_sftp_ingress_gate" not in rollback_release


def test_release_b_gate_uses_the_real_helper_with_canonical_opening_phases(
    tmp_path: Path,
) -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    gate_body = _shell_function(script, "gate")
    deployment = tmp_path / "deployment"
    deployment.mkdir()
    helper = deployment / "agentium-maintenance-gate.sh"
    helper.write_bytes(MAINTENANCE_GATE.read_bytes())
    helper.chmod(0o700)
    deployment_id = "release-b-gate-functional"
    (deployment / "metadata.tsv").write_text(
        f"deployment_id\t{deployment_id}\n" f"candidate_sha\t{'a' * 40}\n",
        encoding="ascii",
    )
    phase_file = deployment / "phase"
    gate_dir = tmp_path / "gate"
    gate_dir.mkdir()
    marker = gate_dir / "deploy-maintenance"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text('#!/bin/sh\nexec "$@"\n', encoding="ascii")
    fake_sudo.chmod(0o755)
    fake_nginx = fake_bin / "nginx"
    fake_nginx.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
    fake_nginx.chmod(0o755)
    harness = f"""
set -Eeuo pipefail
die() {{ printf 'XX  %s\\n' "$*" >&2; exit 1; }}
phase() {{ cat "$PHASE_FILE"; }}
gate() {{
{gate_body}
}}
gate exit
"""
    environment = dict(os.environ)
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "AGENTIUM_MAINTENANCE_DIR": str(gate_dir),
            "REPO_DIR": str(tmp_path),
            "DEPLOY_DIR": str(deployment),
            "DEPLOYMENT_ID": deployment_id,
            "PHASE_FILE": str(phase_file),
            "MAINTENANCE_HELPER": str(helper),
        }
    )

    # The third pass is a simulated resume: the reconciler has durably restored
    # the marker and must be able to traverse the exact same helper contract.
    for phase_name in ("opening_forward", "rollback_opening", "opening_forward"):
        phase_file.write_text(f"{phase_name}\n", encoding="ascii")
        marker.write_text(f"deployment_id\t{deployment_id}\n", encoding="ascii")
        result = subprocess.run(
            ["bash", "-c", harness],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        assert result.returncode == 0, result.stderr
        assert not marker.exists()

    phase_file.write_text("opened\n", encoding="ascii")
    marker.write_text(f"deployment_id\t{deployment_id}\n", encoding="ascii")
    terminal = subprocess.run(
        ["bash", "-c", harness],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert terminal.returncode != 0
    assert "Phase non autorisée" in terminal.stderr
    assert marker.exists()


def test_rollback_closed_proof_is_captured_after_a_301_second_auxiliary_delay() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    reconcile = _shell_function(script, "reconcile_rollback_opening")
    harness = f"""
set -Eeuo pipefail
clock=0
captured=-1
EXPECTED_SHA={'b' * 40}
DEPLOY_DIR=/private/release-b-functional
die() {{ printf 'XX  %s\\n' "$*" >&2; exit 1; }}
phase() {{ printf '%s\\n' rollback_opening; }}
git() {{ printf '%s\\n' {'a' * 40}; }}
metadata() {{
  case "$1" in
    previous_sha) printf '%s\\n' {'a' * 40} ;;
    previous_database_revision) printf '%s\\n' revision-a ;;
    sftp_release_sha) printf '%s\\n' {'c' * 40} ;;
  esac
}}
current_database_revision() {{ printf '%s\\n' revision-a; }}
for name in seal_public_opening_boundary_fail_closed assert_rollback_image_override_contract \
  restore_previous_backend_container restore_previous_worker_without_scheduler \
  attest_previous_qdrant_admin_ready restore_identity_runtime_state \
  assert_systemd_qdrant_admin_contract restore_systemd_backend_state \
  restore_systemd_backend_unit_file_state assert_previous_runtime_images_without_sftp \
  remount_secure_deposit_after_rollback_sftp_proof restore_previous_worker_scheduler \
  leave_systemd_backend_ingress_gate leave_livekit_ingress_gate \
  restore_realtime_restart_policies restore_application_restart_policies \
  assert_previous_sftp_runtime_image assert_sftp_rollback_opening_intent_contract \
  assert_sftp_rollback_continuity_receipt open_rollback_sftp_ingress_after_attestation \
  restore_sftp_restart_policy assert_legacy_sftp_systemd_safe; do
  eval "$name() {{ :; }}"
done
restore_auxiliary_runtime_state() {{ clock=$((clock + 301)); }}
capture_sftp_rollback_closed_boundary() {{ captured=$clock; printf 'captured=%s\\n' "$captured"; }}
restore_sftp_runtime_state() {{ clock=$((clock + 1)); }}
release_rollback_sftp_ingress_with_attestation() {{
  age=$((clock - captured))
  printf 'proof-age=%s\\n' "$age"
  (( age <= 300 ))
}}
historical_runtime_state() {{ printf '%s\\n' running; }}
gate() {{ [[ "$1" == status ]] && printf '%s\\n' open || :; }}
set_phase() {{ printf 'terminal=%s\\n' "$1"; }}
reconcile_rollback_opening() {{
{reconcile}
}}
reconcile_rollback_opening
"""
    result = subprocess.run(
        ["bash", "-c", harness], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "captured=301",
        "proof-age=1",
        "terminal=rolled_back",
    ]


def test_all_release_b_opening_crash_boundaries_reclose_or_resume_fail_closed(
    tmp_path: Path,
) -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    on_error = _shell_function(script, "on_error")
    on_exit = _shell_function(script, "on_process_exit")
    startup = _shell_function(script, "reconcile_interrupted_opening_at_startup")
    sealer = _shell_function(script, "seal_public_opening_boundary_fail_closed")
    finalize = _shell_function(script, "finalize_deployment")
    rollback = _shell_function(script, "reconcile_rollback_opening")

    assert "opening_forward | rollback_opening" in on_error
    assert 'seal_public_opening_boundary_fail_closed "$phase"' in on_error
    assert "opening_forward | rollback_opening" in on_exit
    assert 'seal_public_opening_boundary_fail_closed "$persisted_phase"' in on_exit
    assert "trap - ERR EXIT HUP INT TERM" in on_exit
    assert "opening_forward | rollback_opening" in startup
    assert 'seal_public_opening_boundary_fail_closed "$persisted_phase"' in startup
    assert script.rindex("reconcile_interrupted_opening_at_startup") < script.rindex(
        "reconcile_rehearsal_residue"
    )
    assert sealer.index("gate enter") < sealer.index("enter_sftp_ingress_gate")
    assert sealer.index("enter_sftp_ingress_gate") < sealer.index(
        "requiesce_opened_writers_for_reconcile"
    )
    assert sealer.index("requiesce_opened_writers_for_reconcile") < sealer.index(
        "secure_deposit_mode"
    )
    assert "trap 'exit 129' HUP" in script
    assert "trap 'exit 130' INT" in script
    assert "trap 'exit 143' TERM" in script

    for body, intent, remount, ingress, restart, terminal in (
        (
            finalize,
            "set_phase opening_forward",
            "remount_secure_deposit_after_sftp_proof",
            "open_sftp_ingress_after_attestation",
            "restore_sftp_restart_policy",
            "set_phase opened",
        ),
        (
            rollback,
            "release_rollback_sftp_ingress_with_attestation",
            "remount_secure_deposit_after_rollback_sftp_proof",
            "open_rollback_sftp_ingress_after_attestation",
            "restore_sftp_restart_policy",
            "set_phase rolled_back",
        ),
    ):
        assert body.index(intent) < body.index(remount) < body.index(ingress)
        assert body.index(ingress) < body.index(restart) < body.index("gate exit")
        assert body.index("gate exit") < body.index(terminal)

    exit_harness = f"""
set -Eeuo pipefail
PHASE_FILE="$1"
OPENING_BOUNDARY_SEALED=0
REHEARSAL_ACTIVE=0
REHEARSAL_INTENT="$2/rehearsal"
seal_public_opening_boundary_fail_closed() {{ printf 'sealed:%s\\n' "$1"; }}
cleanup_current_candidate_oneoffs() {{ :; }}
cleanup_current_candidate_migration_boundary() {{ :; }}
cleanup_current_live_writer_audit_boundary() {{ :; }}
cleanup_current_rehearsal() {{ :; }}
on_process_exit() {{
{on_exit}
}}
on_process_exit "$3"
    """
    for phase_name in ("opening_forward", "rollback_opening"):
        phase_file = tmp_path / f"phase-{phase_name}"
        phase_file.write_text(f"{phase_name}\n", encoding="ascii")
        for _boundary, exit_code in (
            ("intent", 1),
            ("rw", 129),
            ("ingress", 130),
            ("restart-policy", 143),
        ):
            with subprocess.Popen(
                [
                    "bash",
                    "-c",
                    exit_harness,
                    "bash",
                    str(phase_file),
                    str(tmp_path),
                    str(exit_code),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ) as process:
                stdout, stderr = process.communicate()
            assert process.returncode == exit_code, stderr
            assert stdout.strip() == f"sealed:{phase_name}"

    error_harness = f"""
set -Eeuo pipefail
PHASE_FILE="$1"
STAGE=fault-injection
ROLLBACK_ACTIVE=0
OPENING_BOUNDARY_SEALED=0
seal_public_opening_boundary_fail_closed() {{ printf 'sealed:%s\\n' "$1"; }}
on_error() {{
{on_error}
}}
on_error 73 9001
"""
    startup_harness = f"""
set -Eeuo pipefail
PHASE_FILE="$1"
phase() {{ cat "$PHASE_FILE"; }}
die() {{ printf 'XX  %s\\n' "$*" >&2; exit 1; }}
seal_public_opening_boundary_fail_closed() {{ printf 'startup-sealed:%s\\n' "$1"; }}
reconcile_interrupted_opening_at_startup() {{
{startup}
}}
reconcile_interrupted_opening_at_startup
"""
    for phase_name in ("opening_forward", "rollback_opening"):
        phase_file = tmp_path / f"phase-direct-{phase_name}"
        phase_file.write_text(f"{phase_name}\n", encoding="ascii")
        error_result = subprocess.run(
            ["bash", "-c", error_harness, "bash", str(phase_file)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert error_result.returncode == 73
        assert error_result.stdout.strip() == f"sealed:{phase_name}"
        startup_result = subprocess.run(
            ["bash", "-c", startup_harness, "bash", str(phase_file)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert startup_result.returncode == 0, startup_result.stderr
        assert startup_result.stdout.strip() == f"startup-sealed:{phase_name}"


def test_apply_stays_closed_until_a_fresh_tenant_validation_artifact() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    apply = script.split("apply_impl() {", 1)[1].split("\n}\n\nverify_validation_artifact()", 1)[0]
    finalize = _shell_function(script, "finalize_deployment")

    assert "set_phase validation_pending" in script
    assert "gate exit" not in apply
    assert "--validation-artifact est obligatoire" in script
    for check in ("provenance", "showcase", "andritz", "sentinel", "octocity"):
        assert f"--{check}" in script
    assert "--storage-before" in script
    assert 'expected_artifact="$deploy_real/validation.json"' in script
    assert 'artifact_real" == "$expected_artifact' in script
    assert '"$VALIDATION_HELPER" verify' in script
    assert finalize.index("verify_validation_artifact") < finalize.index("gate exit")
    assert finalize.index("gate exit") < finalize.index("set_phase completed")


def test_candidate_reopen_is_pinned_to_exact_canary_image_ids() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    compose = _shell_function(script, "compose")
    provenance = _shell_function(script, "candidate_provenance_rows")
    capture = _shell_function(script, "capture_candidate_image_override")
    freeze = _shell_function(script, "freeze_candidate_image_override")
    override_rows = _shell_function(script, "candidate_override_rows")
    backend = _shell_function(script, "restore_candidate_backend_writer")
    worker = _shell_function(script, "restore_candidate_worker_with_scheduler")
    auxiliary = _shell_function(script, "restore_auxiliary_runtime_state")
    runtime = _shell_function(script, "assert_all_candidate_runtime_images")
    finalize = _shell_function(script, "finalize_deployment")
    reconcile = _shell_function(script, "reconcile_opening_forward")

    assert 'CANDIDATE_IMAGE_OVERRIDE="$DEPLOY_DIR/compose.agentium.candidate-images.yml"' in (
        script
    )
    assert 'PROVENANCE_FILE="$DEPLOY_DIR/proofs/provenance.json"' in script
    assert 'set(payload) != expected_top' in provenance
    assert 'payload.get("outcome") != "passed"' in provenance
    assert 'row.get("revision") != expected_sha' in provenance
    assert "candidate provenance changed while read" in provenance
    assert 'durable_publish_file "$temporary" "$CANDIDATE_IMAGE_OVERRIDE"' in capture
    assert "assert_candidate_provenance_matches_override" in freeze
    assert 're.fullmatch(r"    image: (sha256:[0-9a-f]{64})"' in override_rows
    assert '"agentium-backend", "agentium-frontend", "agentium-worker-cpu"' in override_rows
    assert 'AGENTIUM_COMPOSE_CANDIDATE_IMAGE_OVERRIDE="$CANDIDATE_IMAGE_OVERRIDE"' in (
        compose
    )
    assert 'arguments.extend(["-f", candidate_override])' in compose
    for body in (backend, worker):
        assert "assert_candidate_tags_match_provenance" in body
        assert "AGENTIUM_PIN_CANDIDATE_IMAGES=1" in body
        assert "assert_candidate_container_image" in body
    assert "AGENTIUM_PIN_CANDIDATE_IMAGES=1" in auxiliary
    assert "assert_candidate_served_build_info agentium-backend" in runtime
    assert "assert_candidate_served_build_info agentium-frontend" in runtime
    assert finalize.index("verify_validation_artifact") < finalize.index(
        "freeze_candidate_image_override"
    )
    assert finalize.index("freeze_candidate_image_override") < finalize.index(
        "set_phase opening_forward"
    )
    assert finalize.rindex("assert_all_candidate_runtime_images") < finalize.index(
        "gate exit"
    )
    assert reconcile.index("assert_candidate_image_override_contract") < reconcile.index(
        "restore_candidate_backend_writer"
    )
    assert reconcile.rindex("assert_all_candidate_runtime_images") < reconcile.index(
        "gate exit"
    )


def test_rollback_reopen_is_pinned_and_sftp_is_attested_before_any_public_gate() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    prepare = _shell_function(script, "prepare_impl")
    compose = _shell_function(script, "compose")
    backend = _shell_function(script, "restore_previous_backend_container")
    worker = _shell_function(script, "restore_previous_worker_scheduler")
    auxiliary = _shell_function(script, "restore_auxiliary_runtime_state")
    complete = _shell_function(script, "complete_rollback_after_restore")
    reopen = _shell_function(script, "reconcile_rollback_opening")
    sftp_release = _shell_function(
        script, "release_rollback_sftp_ingress_with_attestation"
    )

    assert 'ROLLBACK_IMAGE_OVERRIDE="$DEPLOY_DIR/compose.agentium.rollback-images.yml"' in script
    assert "capture_rollback_image_override" in prepare
    assert 'AGENTIUM_COMPOSE_ROLLBACK_IMAGE_OVERRIDE="$ROLLBACK_IMAGE_OVERRIDE"' in compose
    assert 'arguments.extend(["-f", rollback_override])' in compose
    for body in (backend, worker):
        assert "AGENTIUM_PIN_ROLLBACK_IMAGES=1" in body
        assert "assert_previous_container_image" in body
    assert '"$current_phase" == "rollback_opening"' in auxiliary
    assert "AGENTIUM_PIN_ROLLBACK_IMAGES=1" in auxiliary
    assert "Restauration P4 interdite hors frontière OCI" in auxiliary
    assert 'AGENTIUM_SAFE_ROLLBACK_IMAGE_OVERRIDE_FILE="$ROLLBACK_IMAGE_OVERRIDE"' in complete
    assert reopen.index("assert_rollback_image_override_contract") < reopen.index(
        "restore_previous_backend_container"
    )
    assert reopen.index("restore_auxiliary_runtime_state") < reopen.index(
        "capture_sftp_rollback_closed_boundary"
    )
    assert reopen.index("assert_previous_runtime_images_without_sftp") < reopen.index(
        "capture_sftp_rollback_closed_boundary"
    )
    assert reopen.index("capture_sftp_rollback_closed_boundary") < reopen.index(
        "restore_sftp_runtime_state"
    )
    assert reopen.index("restore_sftp_runtime_state") < reopen.index(
        "release_rollback_sftp_ingress_with_attestation"
    )
    assert reopen.index("release_rollback_sftp_ingress_with_attestation") < reopen.index(
        "remount_secure_deposit_after_rollback_sftp_proof"
    )
    assert reopen.index("remount_secure_deposit_after_rollback_sftp_proof") < reopen.index(
        "open_rollback_sftp_ingress_after_attestation"
    )
    assert reopen.index("open_rollback_sftp_ingress_after_attestation") < reopen.index(
        "restore_sftp_restart_policy"
    )
    assert reopen.rindex("assert_previous_runtime_images_without_sftp") < reopen.index(
        "open_rollback_sftp_ingress_after_attestation"
    )
    assert "rollback-continuity" in sftp_release
    assert "set_secure_deposit_mode rw" not in sftp_release
    assert "leave_sftp_ingress_gate" not in sftp_release


def test_candidate_provenance_parser_rejects_substituted_or_unsafe_images(
    tmp_path: Path,
) -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    verifier = _embedded_python(_shell_function(script, "candidate_provenance_rows"))
    sha = "a" * 40
    deployment_id = "release-b-test"
    services = (
        ("agentium-backend", "1"),
        ("agentium-frontend", "2"),
        ("agentium-worker-cpu", "3"),
    )
    payload = {
        "schema_version": 1,
        "kind": "vm_fallback_provenance",
        "trust_boundary": "direct_operator_vm_fallback",
        "promotion_ceiling": "runner_verified",
        "commit_sha": sha,
        "branch": "demo/agentic",
        "deployment_id": deployment_id,
        "collected_at": "2026-07-22T20:00:00Z",
        "outcome": "passed",
        "vm": {
            "repo_head": sha,
            "branch": "demo/agentic",
            "origin_head": sha,
            "clean": True,
            "dirty_entry_count": 0,
        },
        "database_heads": ["076_decision_scenario_lineage"],
        "services": [
            {
                "service": service,
                "running": True,
                "image_id": f"sha256:{digit * 64}",
                "revision": sha,
            }
            for service, digit in services
        ],
        "build_info": {
            name: {
                "service": name,
                "revision": sha,
                "revision_verified": True,
                "version": "test",
            }
            for name in ("backend", "frontend")
        },
        "maintenance": {},
        "writer_exclusion": {},
        "checks": {
            "all": {"passed": True, "expected": "passed", "observed": "passed"}
        },
    }
    proof = tmp_path / "provenance.json"

    def write(value: dict) -> None:
        proof.write_text(json.dumps(value), encoding="utf-8")
        proof.chmod(0o600)

    def verify() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                "-I",
                "-",
                str(proof),
                sha,
                "demo/agentic",
                deployment_id,
            ],
            input=verifier,
            text=True,
            capture_output=True,
        )

    write(payload)
    passed = verify()
    assert passed.returncode == 0, passed.stderr
    assert passed.stdout.splitlines() == [
        f"{service}\tsha256:{digit * 64}" for service, digit in services
    ]

    substituted = deepcopy(payload)
    substituted["services"][0]["revision"] = "b" * 40
    write(substituted)
    assert verify().returncode != 0

    aliased = deepcopy(payload)
    aliased["services"][1]["image_id"] = aliased["services"][0]["image_id"]
    write(aliased)
    assert verify().returncode != 0

    write(payload)
    proof.chmod(0o644)
    assert verify().returncode != 0


def test_public_recovery_drains_and_stops_every_writer_before_secure_deposit_ro() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    boundary = _shell_function(script, "requiesce_opened_writers_for_reconcile")
    sealer = _shell_function(script, "seal_public_opening_boundary_fail_closed")
    forward = _shell_function(script, "reconcile_opening_forward")
    rollback = _shell_function(script, "reconcile_rollback_opening")

    assert boundary.index("wait_for_existing_writer_connections_to_drain") < boundary.index(
        "quiesce_sftp"
    )
    assert boundary.index("quiesce_sftp") < boundary.index("quiesce_identity_writer")
    assert boundary.index("quiesce_identity_writer") < boundary.index(
        "agentium-livekit-agent agentium-livekit agentium-p4-maintenance agentium-backend agentium-worker-cpu"
    )
    assert boundary.index("agentium-backend agentium-worker-cpu") < boundary.index(
        "assert_rabbitmq_empty"
    )
    assert boundary.index("assert_rabbitmq_empty") < boundary.index(
        "assert_postgres_quiescent"
    )
    assert boundary.index("assert_postgres_quiescent") < boundary.index(
        "set_secure_deposit_mode ro"
    )
    assert sealer.index("enter_sftp_ingress_gate") < sealer.index(
        "requiesce_opened_writers_for_reconcile"
    )
    for body, phase_name, restore in (
        (forward, "opening_forward", "restore_candidate_backend_writer"),
        (rollback, "rollback_opening", "restore_previous_backend_container"),
    ):
        assert body.index(f"seal_public_opening_boundary_fail_closed {phase_name}") < body.index(
            restore
        )
        assert "set_secure_deposit_mode ro" not in body


def test_prepare_isolated_from_live_checkout_and_freezes_candidate_control_plane() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    build = script.split("build_candidate_in_worktree() {", 1)[1].split("\n}\n\nprepare_impl()", 1)[
        0
    ]
    quiesce = script.split("quiesce_all_writers() {", 1)[1].split("\n}\n\nmigrate_candidate()", 1)[
        0
    ]

    assert 'BUILD_WORKTREE="$DATA_ROOT/deploy-builds/$DEPLOYMENT_ID"' in script
    assert 'git worktree add --detach "$BUILD_WORKTREE" "$EXPECTED_SHA"' in build
    assert 'bash "$FROZEN_DEPLOYER" --build-only' in build
    assert "git reset --hard" not in build
    assert quiesce.index("rehearse_candidate_database") < quiesce.index(
        'git reset --hard "$EXPECTED_SHA"'
    )
    for frozen in (
        "FROZEN_ORCHESTRATOR",
        "FROZEN_DEPLOYER",
        "FROZEN_NGINX_SITE",
        "FROZEN_NGINX_SNIPPET",
        "FROZEN_SYSTEMD_UNIT",
        "SFTP_BOUNDARY_HELPER",
    ):
        assert frozen in script
    assert 'exec "$FROZEN_ORCHESTRATOR"' in script


def test_runtime_environment_is_frozen_digest_bound_and_used_by_every_stateful_path() -> None:
    safe = SAFE_DEPLOY.read_text(encoding="utf-8")
    vm = VM_DEPLOY.read_text(encoding="utf-8")
    runner = (ROOT / "scripts" / "run-agentium-safe-canaries.sh").read_text(encoding="utf-8")

    assert 'ENV_BUNDLE_DIR="$DEPLOY_DIR/runtime-env"' in safe
    assert 'ENV_FILE="$FROZEN_COMPOSE_ENV"' in safe
    assert 'FROZEN_SYSTEMD_ENV="$("$ENV_BUNDLE_HELPER" role-path' in safe
    assert "assert_recorded_env_bundle_identity" in safe
    assert (
        safe.rindex("assert_recorded_env_bundle_identity")
        < safe.rindex("resolve_runtime_paths")
        < safe.rindex('case "$MODE" in')
    )
    assert 'recorded" == "$ENV_MANIFEST_SHA256"' in safe
    assert 'local env_file="$REPO_DIR/backend/.env"' not in safe
    assert "adopt_systemd_unit_while_stopped" in _shell_function(safe, "quiesce_all_writers")
    assert "assert_systemd_env_dropin_contract" in _shell_function(
        safe, "reestablish_persisted_phase_boundary"
    )
    recovery = _shell_function(safe, "recover_pre_migration_failure")
    rollback_reconcile = _shell_function(safe, "reconcile_rollback_opening")
    assert "restore_previous_systemd_env_dropin" in recovery
    assert "restore_previous_systemd_env_dropin" not in rollback_reconcile
    assert "previous_systemd_runtime_supports_frozen_dotenv" in recovery
    assert "assert_systemd_env_dropin_contract" not in recovery
    assert "assert_systemd_env_dropin_contract" not in rollback_reconcile

    assert 'ENV_FILE="$SAFE_ENV_BUNDLE_DIR/compose.effective.env"' in vm
    assert "Le deployer state-changing doit être la copie candidate figée" in vm
    assert "expected_env_helper_blob" in vm
    assert "Bundle env figé invalide avant Compose" in vm

    assert 'ENV_FILE="$ENV_BUNDLE_DIR/compose.effective.env"' in runner
    assert 'ENV_FILE="$REPO_DIR/docker/env/agentium.vm.env"' not in runner
    assert "ENV_HELPER_BLOB" in runner
    assert "Bundle env figé invalide avant lecture" in runner


def test_python_runtime_cannot_fall_back_to_a_live_dotenv_after_capture() -> None:
    config = (ROOT / "backend" / "app" / "core" / "config.py").read_text(encoding="utf-8")
    compose = (ROOT / "docker" / "compose.agentium.yml").read_text(encoding="utf-8")
    unit = LEGACY_BACKEND_UNIT.read_text(encoding="utf-8")

    assert 'os.environ.get("AGENTIUM_DISABLE_DOTENV", "0")' in config
    assert "Settings(_env_file=_settings_env_file())" in config
    assert 'return None if mode == "1" else ".env"' in config
    # migrate, backend, worker, beat, P4 and SFTP are the six Python services.
    assert compose.count('AGENTIUM_DISABLE_DOTENV: "1"') == 6
    assert "Environment=AGENTIUM_DISABLE_DOTENV=1" in unit


def test_legacy_and_realtime_writers_are_stopped_before_exact_quiesced_dump() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    quiesce = script.split("quiesce_all_writers() {", 1)[1].split("\n}\n\nmigrate_candidate()", 1)[
        0
    ]

    assert "assert_systemd_unit_contract" in script
    assert "/etc/systemd/system/agentium-backend.service" in script
    assert "--host 127.0.0.1" in script
    assert quiesce.index("systemctl stop agentium-backend.service") < quiesce.index(
        "create_backup quiesced"
    )
    assert quiesce.index("agentium-livekit-agent agentium-livekit") < quiesce.index(
        "create_backup quiesced"
    )
    assert 'assert_no_tcp_listener 8000 "Backend systemd"' in quiesce
    assert 'assert_no_tcp_listener 7881 "LiveKit"' in quiesce
    assert "curl --noproxy '*'" in script
    assert quiesce.index("create_backup quiesced") < quiesce.index(
        'rehearse_candidate_database "$DEPLOY_DIR/postgres-quiesced.dump"'
    )


def test_validation_runtime_is_read_only_scheduler_free_and_tenant_separated() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    activate = script.split("activate_candidate() {", 1)[1].split(
        "\n}\n\nverify_storage_after_activation()", 1
    )[0]
    finalize = _shell_function(script, "finalize_deployment")
    deposit_release = _shell_function(script, "remount_secure_deposit_after_sftp_proof")

    assert "AGENTIUM_CELERY_BEAT=0" in activate
    assert "--defer-auxiliary-start" in activate
    assert "assert_worker_scheduler_mode 0" in activate
    assert "assert_rabbitmq_empty candidate" in activate
    assert activate.index("assert_worker_scheduler_mode 0") < activate.index("set_phase activated")
    assert activate.index("assert_rabbitmq_empty candidate") < activate.index("set_phase activated")
    assert activate.index("run_live_binding_audit") < activate.index("set_phase activated")
    assert "set_secure_deposit_mode ro" in script
    assert finalize.index("assert_rabbitmq_empty validation") < finalize.index(
        "remount_secure_deposit_after_sftp_proof"
    )
    assert "set_secure_deposit_mode rw" in deposit_release
    assert "leave_sftp_ingress_gate" not in deposit_release
    assert finalize.index("remount_secure_deposit_after_sftp_proof") < finalize.index(
        "open_sftp_ingress_after_attestation"
    )
    assert finalize.index("open_sftp_ingress_after_attestation") < finalize.index("gate exit")
    for tenant in ("andritz", "sentinel", "octocity"):
        assert f'"$DEPLOY_DIR/proofs/{tenant}.json"' in script


def test_preflight_rejects_every_required_container_if_already_paused() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    preflight = script.split("preflight_checks() {", 1)[1].split("\n}\n\ninitialize_metadata()", 1)[
        0
    ]

    assert "agentium-pg qdrant agentium-minio agentium-rabbitmq" in preflight
    assert "agentium-backend agentium-frontend agentium-worker-cpu agentium-sftp" in preflight
    assert "{{.State.Paused}}" in preflight
    assert "Conteneur requis déjà pausé avant preflight" in preflight


def test_database_rehearsal_is_private_crash_reconciled_and_passwordless() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    rehearsal = _shell_function(script, "rehearse_candidate_database")
    cleanup = _shell_function(script, "cleanup_current_rehearsal")
    reconcile = _shell_function(script, "reconcile_rehearsal_residue")
    process_exit = _shell_function(script, "on_process_exit")

    assert "write_rehearsal_intent" in rehearsal
    assert "REHEARSAL_ACTIVE=1" in rehearsal
    assert rehearsal.count("--network none") >= 5
    assert "POSTGRES_HOST_AUTH_METHOD=trust" in rehearsal
    assert "POSTGRES_PASSWORD" not in rehearsal
    assert "postgresql://rehearsal@/rehearsal?host=/run/rehearsal-pg" in rehearsal
    assert "test -S /run/rehearsal-pg/.s.PGSQL.5432" in rehearsal
    assert "ai.papai.agentium.rehearsal.deployment_id=$DEPLOYMENT_ID" in rehearsal
    assert "cleanup_current_rehearsal" in rehearsal
    assert "validate_rehearsal_intent" in cleanup
    assert "docker rm -f" in cleanup
    assert "aucune suppression automatique" in reconcile
    assert "cleanup_current_rehearsal" in process_exit
    assert "trap 'on_process_exit $?' EXIT" in script
    assert "trap 'exit 129' HUP" in script
    assert "trap 'exit 130' INT" in script
    assert "trap 'exit 143' TERM" in script


def test_candidate_oneoffs_are_labeled_reconciled_and_absent_before_open() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    database_tool = _shell_function(script, "run_candidate_database_tool")
    offline_tool = _shell_function(script, "run_candidate_offline_with_readonly_inputs")
    live_writer = _shell_function(script, "run_candidate_live_writer_audit_tool")
    cleanup = _shell_function(script, "cleanup_current_candidate_oneoffs")
    finalize = _shell_function(script, "finalize_deployment")

    for runner in (database_tool, offline_tool, live_writer):
        assert "ai.papai.agentium.safe-deploy.oneoff=1" in runner
        assert "ai.papai.agentium.safe-deploy.deployment_id=$DEPLOYMENT_ID" in runner
        assert "ai.papai.agentium.safe-deploy.candidate_sha=$EXPECTED_SHA" in runner
    assert "docker rm -f" in cleanup
    assert "assert_no_candidate_oneoff_residue" in finalize


def test_candidate_alembic_uses_a_postgresql_only_crash_safe_boundary() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    opened = _shell_function(script, "open_candidate_migration_boundary")
    migration = _shell_function(script, "run_candidate_migration")
    run = _shell_function(script, "run_candidate_database_tool")
    allowed = _shell_function(script, "assert_candidate_database_tool_command")
    parse_inputs = _shell_function(script, "parse_candidate_readonly_inputs")
    identity = _shell_function(script, "assert_candidate_migration_network_identity")
    active = _shell_function(script, "assert_candidate_migration_boundary_active")
    cleanup = _shell_function(script, "cleanup_current_candidate_migration_boundary")
    reconcile = _shell_function(script, "reconcile_candidate_migration_boundary")
    process_exit = _shell_function(script, "on_process_exit")
    migrate = _shell_function(script, "migrate_candidate")
    finalize = _shell_function(script, "finalize_deployment")
    startup = script.rsplit("resolve_runtime_paths", 1)[1]

    assert "docker network create --driver bridge --internal" in opened
    assert "ai.papai.agentium.safe-deploy.migration-network=1" in opened
    assert 'docker network connect --alias agentium-pg "$MIGRATION_NETWORK" agentium-pg' in opened
    assert "{{.Internal}}" in identity
    assert '== "true"' in identity
    assert "{{.Driver}}" in identity
    assert '== "bridge"' in identity
    assert '[[ "$name" == "agentium-pg" ]]' in active
    assert '[[ "$total" -eq 1 && "$postgres" -eq 1 ]]' in active

    assert "docker run --rm --read-only" in run
    assert '--network "$MIGRATION_NETWORK"' in run
    assert "compose" not in run
    assert "env_file" not in run
    assert "--cap-drop ALL" in run
    assert "--security-opt no-new-privileges:true" in run
    assert "--pids-limit 256" in run
    assert "dst=/run/secrets/agentium-database-url,readonly" in run
    assert "--env AGENTIUM_DISABLE_DOTENV=1" in run
    assert "--env DATABASE_URL" not in run
    assert "-e DATABASE_URL" not in run
    assert 'DATABASE_URL="$(cat "$secret")"' in run
    assert "AGENTIUM_OBJECT_STORE_PATH" not in run
    assert "AGENTIUM_SECURE_DEPOSIT_PATH" not in run
    assert "AGENTIUM_FAISS_PATH" not in run
    assert "QDRANT" not in run
    secret_contract = _shell_function(script, "assert_candidate_migration_secret_contract")
    assert "or parsed.query" in secret_contract
    assert "or parsed.fragment" in secret_contract
    for command in ("alembic:upgrade:head", "alembic:current", "alembic:heads"):
        assert command in allowed
    assert 'run_candidate_database_tool "$@"' in migration
    assert 'dst=/safe-inputs/$target,readonly' in parse_inputs
    assert '[[ "$source" == "$DEPLOY_DIR"/*' in parse_inputs
    assert '== "600:$(id -u):1"' in parse_inputs

    assert migrate.count("open_candidate_migration_boundary") == 1
    assert migrate.count("run_candidate_migration alembic") == 3
    assert migrate.index("run_candidate_migration alembic upgrade head") < migrate.index(
        "run_candidate_migration alembic current"
    ) < migrate.index("run_candidate_migration alembic heads")
    assert migrate.index("run_candidate_migration alembic heads") < migrate.index(
        "cleanup_current_candidate_migration_boundary"
    )
    assert 'durable_replace_file "$current_temporary"' in migrate
    assert 'durable_replace_file "$heads_temporary"' in migrate

    assert "assert_candidate_migration_network_identity" in cleanup
    assert '[[ "$name" == "agentium-pg" ]]' in cleanup
    assert 'docker network disconnect "$MIGRATION_NETWORK" agentium-pg' in cleanup
    assert 'docker network rm "$MIGRATION_NETWORK"' in cleanup
    assert "remove_candidate_migration_secret" in cleanup
    assert "aucune suppression automatique" in reconcile
    assert "cleanup_current_candidate_migration_boundary" in process_exit
    assert "reconcile_candidate_migration_boundary" in startup
    assert "assert_no_candidate_migration_boundary_residue" in finalize


def test_live_writer_audit_has_only_postgresql_livekit_and_minimal_secrets() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    wrapper = _shell_function(script, "run_candidate_live_writer_audit")
    write_secret = _shell_function(script, "write_live_writer_audit_secret")
    opened = _shell_function(script, "open_live_writer_audit_boundary")
    identity = _shell_function(script, "assert_live_writer_audit_network_identity")
    active = _shell_function(script, "assert_live_writer_audit_boundary_active")
    run = _shell_function(script, "run_candidate_live_writer_audit_tool")
    command = _shell_function(script, "run_candidate_live_writer_audit_command")
    cleanup = _shell_function(script, "cleanup_current_live_writer_audit_boundary")
    reconcile = _shell_function(script, "reconcile_live_writer_audit_boundary")
    process_exit = _shell_function(script, "on_process_exit")
    finalize = _shell_function(script, "finalize_deployment")
    startup = script.rsplit("resolve_runtime_paths", 1)[1]

    assert 'run_candidate_live_writer_audit_command "$@"' in wrapper
    assert "compose" not in wrapper + run + command
    assert "agentium-net" not in wrapper + run + command + opened
    assert "docker network create --driver bridge --internal" in opened
    assert 'docker network connect --alias agentium-pg "$LIVE_WRITER_AUDIT_NETWORK" agentium-pg' in opened
    assert (
        'docker network connect --alias agentium-livekit "$LIVE_WRITER_AUDIT_NETWORK" agentium-livekit'
        in opened
    )
    assert "{{.Internal}}" in identity
    assert '== "true"' in identity
    assert "agentium-pg" in active
    assert "agentium-livekit" in active
    assert '[[ "$total" -eq 2 && "$postgres" -eq 1 && "$livekit" -eq 1 ]]' in active

    for required in (
        '"DATABASE_URL"',
        '"LIVEKIT_API_KEY"',
        '"LIVEKIT_API_SECRET"',
        '"LIVEKIT_ENABLED"',
        '"LIVEKIT_INTERNAL_URL"',
        '"LIVEKIT_URL"',
    ):
        assert required in write_secret
    assert 'api_key != compose.get("LIVEKIT_API_KEY")' in write_secret
    assert 'api_secret != compose.get("LIVEKIT_API_SECRET")' in write_secret
    assert 'database.hostname != "agentium-pg"' in write_secret
    assert "or database.query" in write_secret
    assert "or database.fragment" in write_secret
    assert 'internal.hostname != "agentium-livekit"' in write_secret
    for forbidden in ("OBJECT_STORE", "QDRANT", "MINIO", "SFTP", "CELERY", "OPENAI"):
        assert forbidden not in write_secret + run

    assert "docker run --rm --read-only" in run
    assert '--network "$LIVE_WRITER_AUDIT_NETWORK"' in run
    assert "dst=/run/secrets/live-writer-audit.json,readonly" in run
    assert "--cap-drop ALL" in run
    assert "--security-opt no-new-privileges:true" in run
    assert 'set(payload) != expected' in run
    assert '"AGENTIUM_DISABLE_DOTENV": "1"' in run
    assert 'os.execvpe(sys.argv[1], sys.argv[1:], environment)' in run
    assert "open_live_writer_audit_boundary" in command
    assert "cleanup_current_candidate_oneoffs" in command
    assert "cleanup_current_live_writer_audit_boundary" in command

    assert 'docker network disconnect "$LIVE_WRITER_AUDIT_NETWORK" agentium-livekit' in cleanup
    assert 'docker network disconnect "$LIVE_WRITER_AUDIT_NETWORK" agentium-pg' in cleanup
    assert 'docker network rm "$LIVE_WRITER_AUDIT_NETWORK"' in cleanup
    assert "remove_live_writer_audit_secret" in cleanup
    assert "aucune suppression automatique" in reconcile
    assert "cleanup_current_live_writer_audit_boundary" in process_exit
    assert "reconcile_live_writer_audit_boundary" in startup
    assert "assert_no_live_writer_audit_boundary_residue" in finalize
    assert "compose --profile tools" not in script


def test_candidate_database_tool_allowlist_accepts_only_the_expected_entrypoints() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    allowlist = _shell_function(script, "assert_candidate_database_tool_command")
    harness = f"""
set -Eeuo pipefail
assert_candidate_database_tool_command() {{
{allowlist}
}}
assert_candidate_database_tool_command "$@"
"""
    accepted = (
        ("alembic", "upgrade", "head"),
        ("alembic", "current"),
        ("alembic", "heads"),
        (
            "python",
            "-m",
            "scripts.backfill_workspace_app_installations",
            "--workspace-id",
            "00000000-0000-0000-0000-000000000000",
        ),
        (
            "python",
            "-m",
            "scripts.audit_persisted_system_bindings",
            "--workspace",
            "andritz",
        ),
        (
            "python",
            "-m",
            "scripts.audit_post_canary_database",
            "snapshot",
        ),
    )
    rejected = (
        ("python", "scripts/audit_livekit_quiescence.py"),
        ("python", "-m", "scripts.audit_post_canary_database", "compare"),
        ("alembic", "downgrade", "base"),
        ("sh", "-c", "true"),
    )
    for command in accepted:
        result = subprocess.run(
            ["bash", "-c", harness, "bash", *command], capture_output=True, text=True
        )
        assert result.returncode == 0, (command, result.stderr)
    for command in rejected:
        result = subprocess.run(
            ["bash", "-c", harness, "bash", *command], capture_output=True, text=True
        )
        assert result.returncode == 64, (command, result.stderr)


def test_failed_partial_activation_is_requiesced_without_touching_frontend_or_phase() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    handler = script.split("on_error() {", 1)[1].split("\n}\ntrap", 1)[0]
    requiesce = script.split("requiesce_partial_candidate() {", 1)[1].split(
        "\n}\n\ninvalidate_quiesced_artifacts()", 1
    )[0]

    assert "migrated)" in handler
    assert "requiesce_partial_candidate" in handler
    assert "enter_sftp_ingress_gate" in requiesce
    assert "systemctl stop agentium-backend.service" in requiesce
    assert "agentium-livekit-agent agentium-livekit agentium-sftp" in requiesce
    assert "agentium-p4-maintenance agentium-backend agentium-worker-cpu" in requiesce
    assert "agentium-frontend" not in requiesce
    assert "set_secure_deposit_mode ro" in requiesce
    assert "set_phase" not in requiesce
    assert '[[ "$(phase)" == "migrated" ]]' in requiesce


def test_recovery_quarantines_stale_quiesced_evidence_before_reopening() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    recovery = script.split("recover_pre_migration_failure() {", 1)[1].split(
        "\n}\n\nhistorical_runtime_state()", 1
    )[0]
    invalidation = script.split("invalidate_quiesced_artifacts() {", 1)[1].split(
        "\n}\n\nrestore_systemd_backend_state()", 1
    )[0]

    assert "postgres-quiesced.dump" in invalidation
    assert '"$STORAGE_QUIESCED"' in invalidation
    assert "rehearsal-quiesced-bindings.json" in invalidation
    assert recovery.index("invalidate_quiesced_artifacts") < recovery.index(
        '"$MAINTENANCE_HELPER" exit'
    )
    assert "set_secure_deposit_mode rw" in recovery


def test_expected_storage_devices_are_explicit_and_propagated_to_attestation() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")

    assert 'EXPECTED_DATA_SOURCE="/dev/sdb"' in script
    assert 'EXPECTED_SECURE_SOURCE="/dev/sdc"' in script
    assert "AGENTIUM_SAFE_EXPECTED_DATA_SOURCE" not in script
    assert "AGENTIUM_SAFE_EXPECTED_SECURE_SOURCE" not in script
    assert 'data_source" == "$EXPECTED_DATA_SOURCE' in script
    assert 'secure_source" == "$EXPECTED_SECURE_SOURCE' in script
    assert '--expected-data-source "$EXPECTED_DATA_SOURCE"' in script
    assert '--expected-secure-deposit-source "$EXPECTED_SECURE_SOURCE"' in script


def test_capacity_and_freshness_overrides_can_only_make_preflight_stricter() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")

    assert "MIN_ROOT_FREE_BYTES >= 42949672960" in script
    assert "MIN_DATA_FREE_BYTES >= 68719476736" in script
    assert "MIN_SECURE_FREE_BYTES >= 68719476736" in script
    assert "PREPARATION_MAX_AGE_SECONDS <= 3600" in script
    assert "RELEASE_A_ATTESTATION_MAX_AGE_HOURS=24" in script


def test_rollback_v3_preserves_sftp_and_p4_independently() -> None:
    script = VM_DEPLOY.read_text(encoding="utf-8")
    record = _shell_function(script, "record_rollback_state")
    rollback = _shell_function(script, "rollback_from_state")
    override = _shell_function(script, "ensure_rollback_image_override")

    assert "format\\t3" in record
    assert 'format_version != "3"' in override
    assert "compose.agentium.rollback-images.yml" in script
    assert "agentium-sftp agentium-p4-maintenance" in record
    assert "container_state\\t%s\\tabsent\\t-" in record
    assert "container_state\\t%s\\t%s\\t%s" in record
    assert rollback.index(
        "agentium-sftp agentium-p4-maintenance agentium-backend agentium-frontend agentium-worker-cpu"
    ) < rollback.index('git reset --hard "$previous_sha"')
    assert '[[ "$svc" == "agentium-sftp" ]] && profile_args=(--profile sftp)' in rollback
    assert 'docker tag "$rollback_ref" "$image_ref"' in rollback
    assert 'ensure_rollback_image_override "$state_file"' in rollback
    assert 'create --no-build --force-recreate "$svc"' in rollback
    assert 'docker rm -f "$svc"' in rollback


def test_database_rollback_is_explicit_and_forbidden_after_public_reopen() -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    rollback = _shell_function(script, "rollback_impl")
    boundary = _shell_function(script, "establish_rollback_restore_boundary")
    complete = _shell_function(script, "complete_rollback_after_restore")
    reopen = _shell_function(script, "reconcile_rollback_opening")

    assert '[[ "$ROLLBACK_CONFIRMATION" == "$DEPLOYMENT_ID" ]]' in rollback
    assert "Rollback DB automatique interdit après l'intention forward" in rollback
    # Earlier occurrences of ``complete`` are the idempotent resume branches.
    # The destructive main path must establish its durable boundary before the
    # one restore and only then complete/reopen.
    assert (
        rollback.index("establish_rollback_restore_boundary")
        < rollback.index("force_restore_previous_database")
        < rollback.rindex("complete_rollback_after_restore")
    )
    assert boundary.index("gate enter") < boundary.index("quiesce_sftp")
    assert boundary.index("quiesce_sftp") < boundary.index("set_secure_deposit_mode ro")
    assert complete.index("--rollback-state") < complete.index("storage-rollback-comparison.json")
    assert complete.index("set_phase rollback_opening") < complete.index(
        "reconcile_rollback_opening"
    )
    assert reopen.index("restore_auxiliary_runtime_state") < reopen.index("gate exit")


def test_secure_deposit_manifest_digest_detects_equal_size_replacement(tmp_path: Path) -> None:
    module = _storage_module()
    root = tmp_path / "deposit"
    root.mkdir()
    target = root / "private-name.pdf"
    target.write_bytes(b"first")
    first = module._secure_deposit_aggregate(root)

    target.write_bytes(b"other")
    second = module._secure_deposit_aggregate(root)

    assert first["files"] == second["files"] == 1
    assert first["bytes"] == second["bytes"] == 5
    assert first["manifest_sha256"] != second["manifest_sha256"]
    assert "private-name.pdf" not in str(first)


def test_storage_comparison_covers_logical_qdrant_and_deposit_invariants() -> None:
    module = _storage_module()
    object_entries = []
    object_store = {
        "algorithm": "sha256-merkle-v1",
        "entry_fields": ["path_sha256", "size", "content_sha256"],
        "entries": object_entries,
        "files": 0,
        "bytes": 0,
        "content_manifest_sha256": module._canonical_json_sha256(object_entries),
    }
    qdrant_collection = {
        "collection_id_sha256": "e" * 64,
        "status": "green",
        "optimizer_status_sha256": module._canonical_json_sha256("ok"),
        "points_count": 3,
        "vectors_count": 3,
        "indexed_vectors_count": 3,
        "segments_count": 1,
        "config_sha256": module._canonical_json_sha256({"vectors": {"size": 3}}),
        "payload_schema_sha256": module._canonical_json_sha256({}),
        "points_count_exact": 3,
        "point_manifest_sha256": module._canonical_json_sha256("opaque-points"),
    }
    qdrant_core = {
        "point_manifest_algorithm": module.QDRANT_POINT_MANIFEST_ALGORITHM,
        "point_manifest_fields": module.QDRANT_POINT_MANIFEST_FIELDS,
        "read_consistency": module.QDRANT_READ_CONSISTENCY,
        "points_count_exact": 3,
        "collections": [qdrant_collection],
        "aliases": [],
    }
    base = {
        "schema_version": 1,
        "profile": module.SNAPSHOT_PROFILE,
        "secure_deposit": {
            "files": 2,
            "bytes": 9,
            "partial_files": 0,
            "manifest_sha256": "a" * 64,
        },
        "object_store": object_store,
        "faiss": {
            **object_store,
            "source_id_sha256": module._identifier_sha256("/srv/agentium-data/faiss"),
            "device_id": 2,
            "inode": 42,
        },
        "object_store_bindings": {
            "backend": {
                "backend": "local",
                "local_path_id_sha256": "b" * 64,
                "s3_bucket_id_sha256": None,
                "s3_endpoint_id_sha256": None,
            },
            "worker_cpu": {
                "backend": "local",
                "local_path_id_sha256": "b" * 64,
                "s3_bucket_id_sha256": None,
                "s3_endpoint_id_sha256": None,
            },
        },
        "minio": module._minio_inventory_from_rows([], bucket="private"),
        "qdrant": {
            **qdrant_core,
            "inventory_sha256": module._canonical_json_sha256(qdrant_core),
        },
        "container_mounts": {"qdrant": []},
        "mounts": {
            "data": {
                "source": "/dev/sdb",
                "normalized_source": "/dev/sdb",
                "expected_source": "/dev/sdb",
                "source_matches_expected": True,
                "target": "/srv",
                "fstype": "ext4",
                "device_id": 2,
            },
            "secure_deposit": {
                "source": "/dev/sdc",
                "normalized_source": "/dev/sdc",
                "expected_source": "/dev/sdc",
                "source_matches_expected": True,
                "target": "/deposit",
                "fstype": "ext4",
                "device_id": 3,
            },
        },
    }
    assert module.compare_snapshots(base, base)["result"] == "passed"

    changed_core = deepcopy(qdrant_core)
    changed_core["collections"][0]["points_count"] = 4
    changed = {
        **base,
        "qdrant": {
            **changed_core,
            "inventory_sha256": module._canonical_json_sha256(changed_core),
        },
    }
    result = module.compare_snapshots(base, changed)
    assert result["result"] == "failed"
    assert "qdrant.collections" in result["failed_checks"]
