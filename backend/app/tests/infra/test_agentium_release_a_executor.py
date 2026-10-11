"""Executable and structural gates for the one-time Release A executor."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
EXECUTOR = ROOT / "scripts" / "deploy-agentium-release-a-safe.sh"
GATE = ROOT / "scripts" / "agentium-maintenance-gate.sh"
COMPOSE = ROOT / "docker" / "compose.agentium.yml"
AUDIT_COMPOSE = ROOT / "docker" / "compose.agentium.audit-readonly.yml"


def _function(script: str, name: str) -> str:
    marker = f"{name}() {{"
    start = script.index(marker)
    depth = 0
    lines: list[str] = []
    for line in script[start:].splitlines():
        lines.append(line)
        depth += line.count("{") - line.count("}")
        if depth == 0:
            return "\n".join(lines)
    raise AssertionError(f"unterminated function {name}")


def _python_heredoc(function: str) -> str:
    marker = "<<'PY'\n"
    start = function.index(marker) + len(marker)
    end = function.index("\nPY", start)
    return function[start:end]


def _private_json_file(path: Path, payload: object) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"
    path.write_bytes(body)
    path.chmod(0o600)
    return body


def _write_fake_oci_docker(tmp_path: Path, release_sha: str) -> Path:
    docker = tmp_path / "docker"
    docker.write_text(
        f"""#!/usr/bin/env python3
import json,os,sys
release_sha={release_sha!r}
refs={{
    "agentium-backend":"agentium-backend:release-a",
    "agentium-frontend":"agentium-frontend:release-a",
    "agentium-worker-cpu":"agentium-worker:release-a",
}}
image_ids={{
    "agentium-backend":"sha256:"+"a"*64,
    "agentium-frontend":"sha256:"+"b"*64,
    "agentium-worker-cpu":"sha256:"+"c"*64,
}}
container_ids={{
    "agentium-backend":"1"*64,
    "agentium-frontend":"2"*64,
    "agentium-worker-cpu":"3"*64,
}}
args=sys.argv[1:]
if args[:2]==["info","--format"]:
    print("engine-release-a")
elif args[:2]==["image","inspect"]:
    target=args[2]
    service=next(name for name in refs if target in {{refs[name],image_ids[name]}})
    image_id=image_ids[service]
    if os.environ.get("SUBSTITUTE_TAG")==service and target==refs[service]: image_id="sha256:"+"d"*64
    print(json.dumps([{{"Id":image_id,"RepoTags":[refs[service]],"Config":{{"Labels":{{"org.opencontainers.image.revision":release_sha}}}}}}]))
elif args[:3]==["inspect","--type","container"]:
    service=args[3]
    container_id=container_ids[service]
    if os.environ.get("SUBSTITUTE_CONTAINER")==service: container_id="9"*64
    state={{"Running":True,"Paused":False,"Restarting":False,"Dead":False}}
    if service in {{"agentium-backend","agentium-frontend"}}: state["Health"]={{"Status":"healthy"}}
    print(json.dumps([{{"Id":container_id,"Image":image_ids[service],"Config":{{"Image":refs[service],"Labels":{{"org.opencontainers.image.revision":release_sha}}}},"State":state}}]))
else:
    raise SystemExit("unexpected fake docker command: "+repr(args))
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return docker


def _candidate_oci_payload(release_sha: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "agentium-release-a-candidate-oci-receipt",
        "result": "passed",
        "deployment_id": "release-a-functional",
        "release_a_sha": release_sha,
        "docker_engine_id": "engine-release-a",
        "images": [
            {
                "service": "agentium-backend",
                "image_ref": "agentium-backend:release-a",
                "image_id": "sha256:" + "a" * 64,
                "revision": release_sha,
            },
            {
                "service": "agentium-frontend",
                "image_ref": "agentium-frontend:release-a",
                "image_id": "sha256:" + "b" * 64,
                "revision": release_sha,
            },
            {
                "service": "agentium-worker-cpu",
                "image_ref": "agentium-worker:release-a",
                "image_id": "sha256:" + "c" * 64,
                "revision": release_sha,
            },
        ],
        "captured_at": "2026-07-22T12:00:00Z",
    }


def _write_fake_minio_mc(tmp_path: Path) -> Path:
    mc = tmp_path / "mc"
    mc.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state_path = Path(os.environ["FAKE_MINIO_STATE"])
state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
args = sys.argv[1:]


def save():
    state_path.write_text(json.dumps(state, separators=(",", ":"), sort_keys=True), encoding="utf-8")


def fail(message, code=1):
    print(message, file=sys.stderr)
    raise SystemExit(code)


if args[:2] == ["alias", "set"]:
    if len(args) != 6:
        fail("alias credentials missing", 96)
    alias = args[2]
    access_key, secret_key = args[4:6]
    if alias == "agentium":
        if (access_key, secret_key) != (
            os.environ["MINIO_ROOT_USER"],
            os.environ["MINIO_ROOT_PASSWORD"],
        ):
            fail("root credentials differ")
    elif alias == "agentium-app":
        if (access_key, secret_key) != (
            os.environ["MINIO_APP_ACCESS_KEY"],
            state.get("user_secret"),
        ):
            fail("application credentials differ")
    else:
        fail("unknown alias")
elif args[:2] == ["mb", "--ignore-existing"]:
    pass
elif args[:2] == ["version", "enable"]:
    state["versioning"] = True
    save()
elif args[:3] == ["admin", "user", "info"]:
    if state.get("user_secret") is None or args[4] != os.environ["MINIO_APP_ACCESS_KEY"]:
        fail("user missing")
    payload = {
        "status": "success",
        "accessKey": os.environ["MINIO_APP_ACCESS_KEY"],
        "userStatus": "enabled",
        "memberOf": [
            {"name": group, "policies": ["foreign-policy"]}
            for group in state.get("groups", [])
        ],
    }
    if state.get("user_policy"):
        payload["policyName"] = state["user_policy"]
    print(json.dumps(payload, separators=(",", ":")))
elif args[:3] == ["admin", "user", "add"]:
    if state.get("user_secret") is not None:
        fail("user already exists")
    credentials = args[4:6]
    if credentials[:1] != [os.environ["MINIO_APP_ACCESS_KEY"]] or len(credentials) != 2:
        fail("new user credentials missing")
    state["user_secret"] = credentials[1]
    state["user_policy"] = ""
    save()
elif args[:3] == ["admin", "policy", "info"]:
    if state.get("policy_document") is None:
        fail("policy missing")
    output = Path(args[args.index("--policy-file") + 1])
    output.write_text(state["policy_document"], encoding="utf-8")
elif args[:3] == ["admin", "policy", "create"]:
    if state.get("policy_document") is not None:
        fail("policy already exists")
    state["policy_document"] = Path(args[5]).read_text(encoding="utf-8")
    save()
    if os.environ.get("FAKE_MINIO_CRASH_AFTER_POLICY_CREATE") == "1" and not state.get(
        "crash_injected"
    ):
        state["crash_injected"] = True
        save()
        fail("injected crash after policy create", 91)
elif args[:3] == ["admin", "policy", "attach"]:
    if args[4] != os.environ["MINIO_APP_POLICY"] or args[6] != os.environ["MINIO_APP_ACCESS_KEY"]:
        fail("policy attachment identity differs")
    state["user_policy"] = args[4]
    save()
elif args[:3] == ["version", "info", "--json"]:
    print('{"status":"Enabled"}' if state.get("versioning") else '{"status":"Suspended"}')
elif args[:2] == ["ls", "--versions"]:
    if state.get("probe") is not None:
        print("probe-version")
elif args[:1] == ["pipe"]:
    content = sys.stdin.read()
    if args[1].startswith("agentium-app/") and state.get("user_policy") != os.environ["MINIO_APP_POLICY"]:
        fail("application policy missing")
    state["probe"] = content
    save()
elif args[:1] == ["cat"]:
    if state.get("probe") is None:
        fail("probe missing")
    sys.stdout.write(state["probe"])
elif args[:1] == ["ls"]:
    if state.get("user_policy") != os.environ["MINIO_APP_POLICY"]:
        fail("list denied")
elif args[:1] == ["rm"] and "--force" not in args:
    fail("AccessDenied")
elif args[:2] == ["version", "suspend"]:
    fail("AccessDenied")
elif args[:3] == ["rm", "--force", "--versions"]:
    state.pop("probe", None)
    save()
elif args[:1] == ["stat"]:
    if state.get("probe") is None:
        fail("not found")
else:
    fail("unexpected fake mc command: " + repr(args))
""",
        encoding="utf-8",
    )
    mc.chmod(0o755)
    return mc


def _minio_bootstrap_command(tmp_path: Path) -> str:
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    command = compose["services"]["agentium-minio-init"]["command"][0]
    return command.replace("$$", "$").replace("/tmp/", f"{tmp_path}/")


def test_executor_and_gate_are_valid_bash_and_help_is_non_mutating() -> None:
    for script in (EXECUTOR, GATE):
        syntax = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert syntax.returncode == 0, syntax.stderr
    help_result = subprocess.run(["bash", str(EXECUTOR), "--help"], capture_output=True, text=True)
    assert help_result.returncode == 0
    assert "preflight" in help_result.stdout
    assert "finalize" in help_result.stdout


def test_terminal_gate_requires_lock_and_receipt_bound_authorization() -> None:
    gate = GATE.read_text(encoding="utf-8")
    executor = EXECUTOR.read_text(encoding="utf-8")
    assert "AGENTIUM_SAFE_GATE_LOCK_FD=9" in executor
    assert 'AGENTIUM_SAFE_GATE_AUTHORIZATION="$authorization"' in executor
    assert "assert_terminal_gate_authorization" in gate
    assert "terminal gate authorization identity/digest differs" in gate
    assert "deployment parent was not already exclusively locked" in gate


def test_executor_generated_terminal_authorization_is_accepted_by_actual_gate(
    tmp_path: Path,
) -> None:
    deployment_id = "release-a-generator-contract"
    release_sha = "a" * 40
    live_sha = "b" * 40
    generator = _function(
        EXECUTOR.read_text(encoding="utf-8"), "terminal_gate_authorization_contract"
    )

    for purpose, terminal_phase, receipt_name, authorization_name in (
        (
            "forward-terminal-open",
            "completed",
            "release-a-transaction-receipt.json",
            "release-a-forward-open-authorization.json",
        ),
        (
            "rollback-terminal-open",
            "rolled_back",
            "release-a-rollback-receipt.json",
            "release-a-rollback-open-authorization.json",
        ),
    ):
        direction = purpose.removesuffix("-terminal-open")
        root = tmp_path / direction
        deployment_parent = root / "deployments"
        deployment_parent.mkdir(mode=0o700, parents=True)
        deployment = deployment_parent / deployment_id
        deployment.mkdir(mode=0o700)

        frozen_gate = deployment / GATE.name
        frozen_gate.write_bytes(GATE.read_bytes())
        frozen_gate.chmod(0o700)
        metadata = deployment / "metadata.tsv"
        metadata.write_text(
            (
                f"deployment_id\t{deployment_id}\n"
                f"live_sha\t{live_sha}\n"
                f"release_a_sha\t{release_sha}\n"
            ),
            encoding="utf-8",
        )
        metadata.chmod(0o600)
        phase = deployment / "phase"
        phase.write_text(f"{terminal_phase}\n", encoding="utf-8")
        phase.chmod(0o600)

        if direction == "forward":
            receipt_payload = {
                "schema_version": 3,
                "kind": "agentium-release-a-transaction-receipt",
                "result": "passed",
                "deployment_id": deployment_id,
                "release_a_sha": release_sha,
                "release_a_attestation_receipt_sha256": "1" * 64,
                "final_evidence_receipt_sha256": "2" * 64,
                "manifest_receipt_sha256": "3" * 64,
                "preconditions_receipt_sha256": "4" * 64,
                "preconditions_evidence_receipt_sha256": "5" * 64,
                "runtime_oci_receipt_sha256": "6" * 64,
                "sftp_runtime_ready_receipt_sha256": "7" * 64,
                "sftp_postgres_ledger_receipt_sha256": "8" * 64,
                "completed_at": "2026-07-23T10:00:00Z",
            }
        else:
            receipt_payload = {
                "schema_version": 2,
                "kind": "agentium-release-a-rollback-receipt",
                "result": "passed",
                "deployment_id": deployment_id,
                "restored_sha": live_sha,
                "rollback_state_sha256": "9" * 64,
                "runtime_state_sha256": "c" * 64,
                "completed_at": "2026-07-23T10:00:00Z",
            }
        receipt = deployment / receipt_name
        receipt_body = _private_json_file(receipt, receipt_payload)
        authorization = deployment / authorization_name

        generator_harness = root / "generate-terminal-authorization.sh"
        generator_harness.write_text(
            "\n".join(
                (
                    "#!/usr/bin/env bash",
                    "set -Eeuo pipefail",
                    'DEPLOY_DIR="$1"; DIRECTION="$2"',
                    f'DEPLOYMENT_ID="{deployment_id}"',
                    f'RELEASE_A_SHA="{release_sha}"',
                    'COMPLETION_RECEIPT="$DEPLOY_DIR/release-a-transaction-receipt.json"',
                    'ROLLBACK_COMPLETION_RECEIPT="$DEPLOY_DIR/release-a-rollback-receipt.json"',
                    'FORWARD_OPEN_AUTHORIZATION="$DEPLOY_DIR/release-a-forward-open-authorization.json"',
                    'ROLLBACK_OPEN_AUTHORIZATION="$DEPLOY_DIR/release-a-rollback-open-authorization.json"',
                    'die(){ printf "%s\\n" "$*" >&2; exit 1; }',
                    'assert_private(){ [[ -f "$1" && ! -L "$1" ]] || die "unsafe private file"; }',
                    'durable_replace(){ mv "$1" "$2"; }',
                    generator,
                    'case "$DIRECTION" in',
                    'forward) terminal_gate_authorization_contract write forward "$FORWARD_OPEN_AUTHORIZATION" "$COMPLETION_RECEIPT" forward-terminal-open completed ;;',
                    'rollback) terminal_gate_authorization_contract write rollback "$ROLLBACK_OPEN_AUTHORIZATION" "$ROLLBACK_COMPLETION_RECEIPT" rollback-terminal-open rolled_back ;;',
                    '*) die "unsupported terminal direction" ;;',
                    "esac",
                )
            ),
            encoding="utf-8",
        )
        generator_harness.chmod(0o700)
        generated = subprocess.run(
            ["bash", str(generator_harness), str(deployment), direction],
            capture_output=True,
            text=True,
        )
        assert generated.returncode == 0, generated.stderr
        assert authorization.is_file()

        maintenance = root / "maintenance"
        maintenance.mkdir()
        marker = maintenance / "deploy-maintenance"
        marker.write_text(f"deployment_id\t{deployment_id}\n", encoding="utf-8")
        fake_bin = root / "bin"
        fake_bin.mkdir()
        fake_sudo = fake_bin / "sudo"
        fake_sudo.write_text('#!/usr/bin/env bash\nexec "$@"\n', encoding="utf-8")
        fake_sudo.chmod(0o700)
        nginx_calls = root / "nginx.calls"
        fake_nginx = fake_bin / "nginx"
        fake_nginx.write_text(
            "#!/usr/bin/env bash\n"
            'printf \'%s\\n\' "$*" >>"$AGENTIUM_TEST_NGINX_CALLS"\n',
            encoding="utf-8",
        )
        fake_nginx.chmod(0o700)
        environment = {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "AGENTIUM_SAFE_DEPLOY_ORCHESTRATED": "1",
            "AGENTIUM_SAFE_DEPLOYMENT_DIR": str(deployment),
            "AGENTIUM_SAFE_DEPLOYMENT_ID": deployment_id,
            "AGENTIUM_SAFE_GATE_PURPOSE": purpose,
            "AGENTIUM_SAFE_GATE_AUTHORIZATION": str(authorization),
            "AGENTIUM_MAINTENANCE_DIR": str(maintenance),
            "AGENTIUM_TEST_NGINX_CALLS": str(nginx_calls),
        }

        no_lock = subprocess.run(
            ["bash", str(frozen_gate), "exit"],
            capture_output=True,
            text=True,
            env=environment,
        )
        assert no_lock.returncode != 0
        assert marker.exists()
        assert not nginx_calls.exists()

        def invoke_with_locked_parent() -> subprocess.CompletedProcess[str]:
            descriptor = os.open(deployment_parent, os.O_RDONLY)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked_environment = {
                    **environment,
                    "AGENTIUM_SAFE_GATE_LOCK_FD": str(descriptor),
                }
                return subprocess.run(
                    ["bash", str(frozen_gate), "exit"],
                    capture_output=True,
                    text=True,
                    env=locked_environment,
                    pass_fds=(descriptor,),
                )
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

        tampered_payload = {**receipt_payload, "completed_at": "2026-07-23T10:00:01Z"}
        _private_json_file(receipt, tampered_payload)
        tampered = invoke_with_locked_parent()
        assert tampered.returncode != 0
        assert "terminal gate authorization identity/digest differs" in tampered.stderr
        assert marker.exists()
        assert not nginx_calls.exists()

        receipt.write_bytes(receipt_body)
        receipt.chmod(0o600)
        accepted = invoke_with_locked_parent()
        assert accepted.returncode == 0, accepted.stderr
        assert not marker.exists()
        assert nginx_calls.read_text(encoding="utf-8") == "-t\n"


def test_status_path_is_read_only_before_lock_or_reconciliation() -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    status = script.index('if [[ "$MODE" == status ]]')
    first_mutating_boundary = script.index("ensure_private_child_dir()")
    assert status < first_mutating_boundary
    status_block = script[status:first_mutating_boundary]
    assert "stage_helpers" not in status_block
    assert "reconcile_postgres_rehearsal" not in status_block
    assert "os.mkdir" not in status_block
    assert "flock" not in status_block


def test_journal_is_nofollow_owner_private_and_locked_by_directory_identity() -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    private_dir = _function(script, "ensure_private_child_dir")
    assert "follow_symlinks=False" in private_dir
    assert 'getattr(os,"O_NOFOLLOW",0)' in private_dir
    assert "row.st_uid!=os.geteuid()" in private_dir
    assert "stat.S_IMODE(row.st_mode)!=0o700" in private_dir
    assert "row.st_dev!=opened.st_dev" in private_dir
    assert 'exec 9<"$STATE_ROOT"' in script
    assert "stat -Lc '%d:%i' \"/proc/$$/fd/9\"" in script
    assert 'exec 9>"$STATE_ROOT' not in script


def test_executor_rejects_noncanonical_branch_before_any_state_access(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "bash",
            str(EXECUTOR),
            "status",
            "--live-sha",
            "a" * 40,
            "--release-a-sha",
            "b" * 40,
            "--deployment-id",
            "release-a-test",
            "--candidate-repo",
            str(tmp_path),
            "--branch",
            "codex/not-the-dedicated-release",
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "AGENTIUM_RELEASE_A_STATE_DIR": str(tmp_path / "state")},
    )
    assert result.returncode != 0
    assert "branche dédiée" in result.stderr
    assert not (tmp_path / "state").exists()


def test_executor_is_safety_only_and_orders_durable_boundaries() -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    gate = GATE.read_text(encoding="utf-8")
    apply = _function(script, "apply_impl")
    reconcile = _function(script, "reconcile_closed_adoption")
    finalize = _function(script, "finalize_impl")
    forward = _function(script, "reconcile_forward_open")
    forward_commit = _function(script, "commit_forward_opening")
    forward_terminal = _function(script, "reconcile_forward_committed_open")
    forward_physical = _function(script, "open_forward_terminal_from_validated_boundary")

    assert "alembic upgrade" not in script
    assert "seed" not in reconcile.lower()
    assert "backfill" not in reconcile.lower()
    assert apply.index("disable_writer_restarts") < apply.index("install_gate_closed")
    assert apply.index("install_gate_closed") < apply.index("enter_writer_ingress_gates")
    assert apply.index("enter_writer_ingress_gates") < apply.index("stop_writers")
    assert apply.index("stop_writers") < apply.index("set_phase closing_intent")
    assert reconcile.index("ensure_postgres_backup_and_restore_rehearsal") < reconcile.index(
        'git -C "$LIVE_REPO" reset --hard'
    )
    assert reconcile.index("verify_candidate_storage_contract") < reconcile.index(
        'git -C "$LIVE_REPO" reset --hard'
    )
    assert reconcile.index("write_checkout_intent") < reconcile.index(
        'git -C "$LIVE_REPO" reset --hard'
    )
    assert finalize.index("set_phase opening_forward") < finalize.rindex("reconcile_forward_open")
    assert forward_commit.index("publish_completion_receipt") < forward_commit.index(
        "set_phase completed"
    )
    assert "gate exit" not in forward
    assert "remove_systemd_boot_guard" not in forward
    assert forward_physical.index("gate exit") < forward_physical.index(
        "remove_systemd_boot_guard"
    )
    assert "forward-terminal-open:completed" in gate
    assert "rollback-terminal-open:rolled_back" in gate
    assert forward_physical.index("restore_restart_policies_after_open") < (
        forward_physical.index("remove_systemd_boot_guard")
    )
    assert forward_terminal.index("validate_forward_terminal_boundary") < (
        forward_terminal.index("open_forward_terminal_from_validated_boundary")
    )
    assert forward.index("install_gate_closed") < forward.index("assert_attestation_receipt")
    rollback_open = _function(script, "reconcile_rollback_open")
    assert rollback_open.index("install_gate_closed") < rollback_open.index(
        "validate_rollback_opening_boundary"
    )


def test_sftp_lifecycle_is_a_fail_closed_gate_and_preserves_the_attested_process() -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    arm = _function(script, "arm_sftp_canary_impl")
    active = _function(script, "record_sftp_active_impl")
    final = _function(script, "record_sftp_final_impl")
    finalize = _function(script, "finalize_impl")
    forward = _function(script, "reconcile_forward_open")
    terminal = _function(script, "reconcile_forward_committed_open")
    start = _function(script, "start_runtime_services_without_restart")
    preserve = _function(script, "stop_writers_preserving_attested_sftp")
    control = _function(script, "assert_sftp_canary_control_plane")
    control_start = _function(script, "start_sftp_canary_control_plane")
    control_stop = _function(script, "stop_sftp_canary_control_plane")

    assert "validation_pending" in arm
    assert "stop_writers\n" in arm
    assert arm.index("stop_writers") < arm.index("docker start agentium-sftp")
    assert arm.rindex("capture_sftp_runtime_ready") < arm.rindex(
        "set_phase sftp_canary_pending"
    )
    assert arm.index('[[ -e "$SFTP_RUNTIME_READY"') < arm.index("stop_writers")
    recovery = arm[arm.index('[[ -e "$SFTP_RUNTIME_READY"') : arm.index("stop_writers")]
    assert recovery.index("assert_sftp_runtime_ready_live") < recovery.index(
        "set_phase sftp_canary_pending"
    ) < recovery.index("start_sftp_canary_control_plane")
    assert arm.rindex("set_phase sftp_canary_pending") < arm.rindex(
        "start_sftp_canary_control_plane"
    )
    assert "sftp_canary_pending" in active
    assert "start_sftp_canary_control_plane" in active
    assert active.index("copy_private_once") < active.rindex(
        "capture_sftp_postgres_inventory active"
    )
    assert active.rindex("capture_sftp_postgres_inventory active") < active.index(
        "set_phase sftp_canary_active_recorded"
    )
    assert "sftp_canary_active_recorded" in final
    assert final.rindex("capture_sftp_postgres_inventory revoked") < final.rindex(
        "capture_sftp_postgres_receipt"
    )
    assert final.rindex("capture_sftp_postgres_receipt") < final.index(
        "stop_sftp_canary_control_plane"
    )
    assert final.index("stop_sftp_canary_control_plane") < final.index(
        "set_phase sftp_canary_recorded"
    )
    assert 'rows[0].get("HostIp")!="127.0.0.1"' in control
    assert 'environment.get("STARTUP_RECONCILIATION")!="disabled"' in control
    assert 'row.get("RW") is not False' in control
    assert "agentium-worker-cpu agentium-p4-maintenance" in control
    assert control_start.index("docker start") < control_start.index(
        "assert_sftp_canary_control_plane"
    )
    assert control_stop.index("stop_container_without_sigkill") < control_stop.index(
        "assert_sftp_runtime_ready_live"
    )
    assert "sftp_canary_recorded" in finalize
    assert "validation_pending" not in finalize
    assert finalize.index("assert_sftp_runtime_ready_live") < finalize.index("copy_private_once")
    assert finalize.index("assert_attestation_receipt") < finalize.index(
        "set_phase opening_forward"
    )
    assert "stop_writers_preserving_attested_sftp" in forward
    assert "stop_writers_preserving_attested_sftp" in terminal
    assert "stop_writers\n" not in forward
    assert "stop_writers\n" not in terminal
    assert "docker pause agentium-sftp" in preserve
    assert "docker unpause agentium-sftp" in preserve
    assert "stop_container_without_sigkill agentium-sftp" not in preserve
    assert "assert_sftp_runtime_identity_live" in preserve
    assert '"$service" == agentium-sftp' in start
    assert start.index("assert_sftp_runtime_identity_live") < start.index("continue")


def test_keycloak_canary_control_plane_is_pinned_before_start_and_after_stop() -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    record = _function(script, "record_runtime_state")
    validation = _function(script, "start_validation_runtime_under_gates")
    start = _function(script, "start_sftp_canary_control_plane")
    live = _function(script, "assert_sftp_canary_control_plane")
    stop = _function(script, "stop_sftp_canary_control_plane")
    stopped = _function(script, "assert_sftp_canary_control_plane_stopped")

    assert '"$service" == agentium-kc' in record
    assert "keycloak_control_plane_contract snapshot any" in record
    assert "agentium-kc agentium-sftp" not in validation
    assert start.index("keycloak_control_plane_contract verify any") < start.index(
        'docker start "$keycloak_id"'
    )
    assert "keycloak_control_plane_contract verify running" in live
    assert ".well-known/openid-configuration" in live
    assert "keycloak_control_plane_contract verify stopped" in stop
    assert "keycloak_control_plane_contract verify stopped" in stopped


def test_keycloak_control_plane_contract_rejects_security_substitution(tmp_path: Path) -> None:
    code = _python_heredoc(
        _function(EXECUTOR.read_text(encoding="utf-8"), "keycloak_control_plane_contract")
    ).replace("json.load(os.fdopen(3))", "json.load(sys.stdin)")
    live_repo = tmp_path / "omnirag"
    theme = live_repo / "backend/keycloak/themes/agentium"
    theme.mkdir(parents=True)
    (theme / "theme.properties").write_text("parent=keycloak\n", encoding="utf-8")
    realm = live_repo / "backend/keycloak/realm-export.json"
    realm.write_text('{"realm":"papai-org"}\n', encoding="utf-8")
    network_id = "c" * 64
    port_row = [{"HostIp": "127.0.0.1", "HostPort": "8080"}]
    kc: dict[str, object] = {
        "Id": "a" * 64,
        "Name": "/agentium-kc",
        "Image": "sha256:" + "b" * 64,
        "Config": {
            "Image": "quay.io/keycloak/keycloak:26.1.4",
            "Cmd": ["start-dev"],
            "Entrypoint": ["/opt/keycloak/bin/kc.sh"],
            "User": "1000",
            "WorkingDir": "/opt/keycloak",
            "Env": [
                "KC_DB=postgres",
                "KC_DB_URL=jdbc:postgresql://agentium-pg:5432/agentium",
                "KC_DB_USERNAME=agentium",
                "KC_DB_PASSWORD=not-a-placeholder",
                "KC_HTTP_ENABLED=true",
                "KC_HTTP_RELATIVE_PATH=/kc",
                "KC_HOSTNAME=https://agentium.papai.ai/kc",
                "KC_HOSTNAME_STRICT=false",
                "KC_PROXY_HEADERS=xforwarded",
                "KC_HEALTH_ENABLED=true",
                "KC_RUN_IN_CONTAINER=true",
            ],
            "Labels": {
                "com.docker.compose.service": "agentium-kc",
                "com.docker.compose.oneoff": "False",
                "com.docker.compose.container-number": "1",
                "com.docker.compose.project": "agentium",
            },
            "Healthcheck": {
                "Test": [
                    "CMD-SHELL",
                    "wget -qO- http://127.0.0.1:8080/kc/realms/papai-org",
                ],
                "Interval": 15_000_000_000,
                "Timeout": 5_000_000_000,
                "Retries": 10,
                "StartPeriod": 60_000_000_000,
            },
        },
        "HostConfig": {
            "PortBindings": {"8080/tcp": port_row},
            "NetworkMode": "agentium-net",
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "Privileged": False,
            "ReadonlyRootfs": False,
            "PidMode": "",
            "IpcMode": "private",
            "Devices": None,
            "CapAdd": None,
            "CapDrop": None,
            "SecurityOpt": None,
        },
        "State": {
            "Running": True,
            "Paused": False,
            "Restarting": False,
            "Dead": False,
            "OOMKilled": False,
            "Pid": 1234,
            "Health": {"Status": "healthy"},
        },
        "Mounts": [
            {
                "Destination": "/opt/keycloak/themes/agentium",
                "Source": str(theme),
                "Type": "bind",
                "RW": False,
            },
            {
                "Destination": "/opt/keycloak/data/import/realm.json",
                "Source": str(realm),
                "Type": "bind",
                "RW": False,
            },
        ],
        "NetworkSettings": {
            "Ports": {
                "8080/tcp": port_row,
                "8443/tcp": None,
                "9000/tcp": [],
            },
            "Networks": {
                "agentium-net": {"NetworkID": network_id, "Aliases": ["agentium-kc"]}
            },
        },
    }
    pg = {
        "Name": "/agentium-pg",
        "NetworkSettings": {"Networks": {"agentium-net": {"NetworkID": network_id}}},
    }
    rows = [kc, pg]

    def invoke(payload: list[dict[str, object]], *arguments: str):
        return subprocess.run(
            [sys.executable, "-I", "-c", code, *arguments],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )

    snapshot = invoke(rows, "snapshot", "running", str(live_repo), "", "", "", "")
    assert snapshot.returncode == 0, snapshot.stderr
    expected = snapshot.stdout.strip().split("\t")[2:]
    assert len(expected) == 4
    verified = invoke(rows, "verify", "running", str(live_repo), *expected)
    assert verified.returncode == 0, verified.stderr

    def mutated() -> list[dict[str, object]]:
        return json.loads(json.dumps(rows))

    candidates = []
    candidate = mutated()
    candidate[0]["HostConfig"]["PortBindings"]["8080/tcp"][0]["HostIp"] = "0.0.0.0"
    candidates.append(candidate)
    candidate = mutated()
    candidate[0]["HostConfig"]["PortBindings"]["8443/tcp"] = [
        {"HostIp": "127.0.0.1", "HostPort": "8443"}
    ]
    candidates.append(candidate)
    candidate = mutated()
    candidate[0]["NetworkSettings"]["Ports"]["8443/tcp"] = [
        {"HostIp": "127.0.0.1", "HostPort": "8443"}
    ]
    candidates.append(candidate)
    candidate = mutated()
    candidate[0]["Config"]["Healthcheck"] = {"Test": ["CMD", "true"]}
    candidates.append(candidate)
    candidate = mutated()
    candidate[0]["Mounts"][0]["RW"] = True
    candidates.append(candidate)
    candidate = mutated()
    candidate[0]["Config"]["Env"].append("KC_DB_URL=jdbc:postgresql://evil/db")
    candidates.append(candidate)
    candidate = mutated()
    candidate[0]["NetworkSettings"]["Networks"]["evil"] = {
        "NetworkID": "d" * 64,
        "Aliases": ["agentium-kc"],
    }
    candidates.append(candidate)
    candidate = mutated()
    candidate[0]["HostConfig"]["RestartPolicy"] = {
        "Name": "always",
        "MaximumRetryCount": 0,
    }
    candidates.append(candidate)
    candidate = mutated()
    candidate[0]["Id"] = "d" * 64
    candidates.append(candidate)

    for candidate in candidates:
        refused = invoke(candidate, "verify", "running", str(live_repo), *expected)
        assert refused.returncode != 0


def test_release_a_phase_machine_is_closed_and_cannot_skip_sftp_gates(
    tmp_path: Path,
) -> None:
    body = _function(EXECUTOR.read_text(encoding="utf-8"), "set_phase")
    expected_transitions = (
        "new:preflight_ok",
        "preflight_ok:prepared",
        "prepared:closing_intent",
        "closing_intent:maintenance_closed",
        "maintenance_closed:adopting",
        "adopting:validation_pending",
        "validation_pending:sftp_canary_pending",
        "sftp_canary_pending:sftp_canary_active_recorded",
        "sftp_canary_active_recorded:sftp_canary_recorded",
        "sftp_canary_recorded:opening_forward",
        "opening_forward:completed",
    )
    for transition in expected_transitions:
        assert transition in body

    phase_path = tmp_path / "phase"
    harness = tmp_path / "phase-harness.sh"
    harness.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -Eeuo pipefail",
                'PHASE_FILE="$1"; DEPLOY_DIR="$(dirname "$PHASE_FILE")"; next="$2"',
                'phase(){ [[ -s "$PHASE_FILE" ]] && cat "$PHASE_FILE" || printf "new\\n"; }',
                'assert_private(){ [[ -f "$1" && ! -L "$1" ]]; }',
                'atomic_text(){ printf "%s\\n" "$2" >"$1"; chmod 600 "$1"; }',
                'die(){ printf "%s\\n" "$*" >&2; exit 23; }',
                body,
                'set_phase "$next"',
            ]
        ),
        encoding="utf-8",
    )
    harness.chmod(0o700)

    for transition in expected_transitions:
        _current, target = transition.split(":", 1)
        result = subprocess.run(
            ["bash", str(harness), str(phase_path), target],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert phase_path.read_text(encoding="utf-8").strip() == target

    phase_path.unlink()
    refused = subprocess.run(
        ["bash", str(harness), str(phase_path), "completed"],
        capture_output=True,
        text=True,
    )
    assert refused.returncode == 23
    assert "new -> completed" in refused.stderr
    assert not phase_path.exists()


def test_sftp_arm_recovers_sigkill_after_receipt_without_restarting_process(
    tmp_path: Path,
) -> None:
    arm = _function(EXECUTOR.read_text(encoding="utf-8"), "arm_sftp_canary_impl")
    harness = tmp_path / "arm-fault-harness.sh"
    phase_path = tmp_path / "phase"
    receipt_path = tmp_path / "sftp-validation-runtime-ready.json"
    log_path = tmp_path / "log"
    phase_path.write_text("validation_pending\n", encoding="utf-8")
    harness.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -Eeuo pipefail",
                'ROOT="$1"; FAULT="$2"',
                'PHASE_FILE="$ROOT/phase"; SFTP_RUNTIME_READY="$ROOT/sftp-validation-runtime-ready.json"; LOG="$ROOT/log"',
                'RUNTIME_STATE="$ROOT/runtime-state"; printf "container\\tagentium-sftp\\ttrue\\tsha256:%s\\n" "$(printf a%.0s {1..64})" >"$RUNTIME_STATE"',
                'phase(){ cat "$PHASE_FILE"; }',
                'set_phase(){ printf "%s\\n" "$1" >"$PHASE_FILE"; printf "phase-%s\\n" "$1" >>"$LOG"; }',
                'metadata(){ printf "sha256:%s\\n" "$(printf a%.0s {1..64})"; }',
                'assert_metadata(){ :; }; assert_candidate_worktree(){ :; }; assert_remote_release_a(){ :; }',
                'disable_writer_restarts(){ :; }; install_gate_closed(){ :; }; enter_writer_ingress_gates(){ :; }',
                'assert_writer_ingress_gates(){ :; }; assert_secure_mode_in_namespaces(){ :; }; set_secure_mode(){ :; }',
                'stop_writers(){ printf "stop-writers\\n" >>"$LOG"; }',
                'assert_sftp_canary_control_plane_stopped(){ :; }',
                'start_sftp_canary_control_plane(){ printf "control-start\\n" >>"$LOG"; }',
                'assert_sftp_runtime_ready_live(){ [[ -f "$SFTP_RUNTIME_READY" ]]; printf "assert-ready\\n" >>"$LOG"; }',
                'capture_sftp_runtime_ready(){ printf "receipt\\n" >"$SFTP_RUNTIME_READY"; printf "capture-ready\\n" >>"$LOG"; [[ "$FAULT" != kill ]] || kill -KILL "$$"; }',
                'docker(){ case "$*" in *"{{.State.Running}}:{{if"*) printf "true:healthy:no:0\\n";; *"{{if .State.Health}}"*) printf "healthy\\n";; *"{{.Image}}"*) printf "sha256:%s\\n" "$(printf a%.0s {1..64})";; *" start "*|start\\ *) printf "docker-start\\n" >>"$LOG";; esac; }',
                'ok(){ :; }; die(){ printf "%s\\n" "$*" >&2; exit 1; }',
                arm,
                "arm_sftp_canary_impl",
            ]
        ),
        encoding="utf-8",
    )
    harness.chmod(0o700)

    killed = subprocess.run(
        ["bash", str(harness), str(tmp_path), "kill"], capture_output=True, text=True
    )
    assert killed.returncode < 0
    assert phase_path.read_text(encoding="utf-8").strip() == "validation_pending"
    assert receipt_path.exists()

    resumed = subprocess.run(
        ["bash", str(harness), str(tmp_path), "resume"], capture_output=True, text=True
    )
    assert resumed.returncode == 0, resumed.stderr
    assert phase_path.read_text(encoding="utf-8").strip() == "sftp_canary_pending"
    rows = log_path.read_text(encoding="utf-8").splitlines()
    assert rows.count("stop-writers") == 1
    assert rows.count("capture-ready") == 1
    assert rows.count("assert-ready") == 1
    assert rows.count("control-start") == 1


def test_completed_forward_replay_revalidates_rw_boundary_and_exact_sftp_process() -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    identity = _function(script, "assert_sftp_runtime_identity_live")
    reclose = _function(script, "reclose_attested_sftp_to_read_only")
    replay = _function(script, "reconcile_forward_committed_open")
    validate = _function(script, "validate_forward_terminal_boundary")
    physical = _function(script, "open_forward_terminal_from_validated_boundary")
    fd_count = _function(script, "sftp_open_deposit_fd_count")

    assert "verify-runtime-identity-live" in identity
    assert '--expected-secure-mode "$mode"' in identity
    assert '--expected-restart "$restart"' in identity
    assert "--allow-paused" in identity
    assert reclose.index("docker pause agentium-sftp") < reclose.index(
        "set_secure_mode ro"
    ) < reclose.rindex("docker unpause agentium-sftp")
    assert 'assert_sftp_runtime_identity_live rw disabled 1' in reclose
    assert replay.index("stop_writers_preserving_attested_sftp") < replay.index(
        "reclose_attested_sftp_to_read_only"
    ) < replay.index("validate_forward_terminal_boundary")
    assert replay.index("validate_forward_terminal_boundary") < replay.index(
        "start_runtime_services_without_restart"
    ) < replay.index("set_secure_mode rw")
    assert replay.index("set_secure_mode rw") < replay.index(
        "assert_sftp_runtime_identity_live rw disabled"
    ) < replay.index("open_forward_terminal_from_validated_boundary")
    assert 'cmp -s "$POSTGRES_INVENTORY_OPENING"' in validate
    assert '--before "$STORAGE_OPENING"' in validate
    assert physical.index("assert_sftp_runtime_identity_live rw disabled") < physical.index(
        "gate exit"
    )
    assert physical.index("restore_restart_policies_after_open") < physical.index(
        "publish_open_reconciled_marker"
    ) < physical.index("assert_sftp_process_identity_stable")
    assert "FORWARD_OPEN_AUTHORIZATION" in replay
    assert replay.index("assert_terminal_gate_authorization") < replay.index(
        "start_runtime_services_without_restart"
    )
    assert 'stat -Lc %d "$SECURE_DEPOSIT"' in fd_count
    assert 'readlink "/proc/$pid/fd/$fd"' not in fd_count


def test_restart_and_transport_gates_cover_ipv4_ipv6_and_docker_user() -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    ingress = _function(script, "enter_writer_ingress_gates")
    assert "iptables ip6tables" in ingress
    assert "INPUT DOCKER-USER" in ingress
    assert "writer_bindings" in ingress
    disable = _function(script, "disable_writer_restarts")
    stop = _function(script, "stop_writers")
    for service in ("agentium-sftp", "agentium-livekit", "agentium-worker-cpu"):
        assert service in stop
    assert "docker update --restart=no" in disable


def test_executor_drains_business_writers_without_sigkill() -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    stop = _function(script, "stop_writers")
    drain = _function(script, "wait_for_existing_writer_connections_to_drain")
    sftp = _function(script, "quiesce_sftp_before_stop")
    graceful = _function(script, "stop_container_without_sigkill")
    audit = _function(script, "audit_live_writers_before_stop")

    assert stop.index("wait_for_existing_writer_connections_to_drain") < stop.index(
        "audit_live_writers_before_stop"
    )
    assert stop.index("audit_live_writers_before_stop") < stop.index("quiesce_sftp_before_stop")
    assert "state established" in drain
    assert "docker pause agentium-sftp" in sftp
    assert "sftp_open_deposit_fd_count" in sftp
    assert "docker kill --signal TERM" in graceful
    assert "docker stop" not in script
    assert "compose_audit run" in audit
    assert "audit_livekit_quiescence.py" in audit
    assert "verify_live_writer_proof" in audit
    assert audit.index("compose_audit run") < audit.index(
        'durable_replace "$temporary" "$LIVE_WRITER_PROOF"'
    )
    assert "return" not in audit.split("compose_audit run", 1)[0]
    audit_compose = AUDIT_COMPOSE.read_text(encoding="utf-8")
    assert "read_only: true" in audit_compose
    assert "no-new-privileges:true" in audit_compose
    assert "/tmp:rw,noexec,nosuid,nodev,size=64m" in audit_compose


def test_executor_uses_hermetic_process_environment_and_private_sources() -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    compose = _function(script, "compose")
    prepare = _function(script, "prepare_impl")
    private_source = _function(script, "assert_private_source")

    assert "COMPOSE_CLEAN_PATH=/usr/local/sbin:" in script
    assert 'export PATH="$COMPOSE_CLEAN_PATH"' in script
    assert "export PYTHONDONTWRITEBYTECODE=1" in script
    assert "unset PYTHONBREAKPOINT PYTHONHOME PYTHONINSPECT PYTHONOPTIMIZE" in script
    assert "assert_python_runtime" in script
    assert "sys.flags.optimize" in script
    assert "DOCKER_HOST" in script and "DOCKER_CONTEXT" in script
    assert 'env -i PATH="$COMPOSE_CLEAN_PATH" HOME="$DEPLOY_HOME"' in compose
    assert 'DOCKER_CONFIG="$DEPLOY_HOME/.docker"' in compose
    assert 'DOCKER_HOST="$DOCKER_LOCAL_HOST"' in compose
    assert 'env -i PATH="$COMPOSE_CLEAN_PATH"' in prepare
    assert '"400:$(id -u):1"' in private_source
    assert '"600:$(id -u):1"' in private_source


def test_executor_binds_evidence_bytes_before_mutation_and_before_opening() -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    preflight = _function(script, "preflight_impl")
    apply = _function(script, "apply_impl")
    finalize = _function(script, "finalize_impl")
    assertion = _function(script, "assert_attestation_receipt")

    assert "verify-preconditions" in preflight
    assert apply.index("revalidate_preconditions_evidence") < apply.index("disable_writer_restarts")
    assert "verify-final" in finalize
    assert finalize.index("verify-final") < finalize.index("set_phase opening_forward")
    assert "final evidence attestation digest differs" in assertion
    assert "preconditions evidence input digest differs" in assertion
    assert "verify-final-frozen" in assertion
    assert "stage_git_file config/agentium/release-a-evidence-authorities.v1.json" in script
    assert "--evidence-authority-keyring" not in script
    assert (
        '--expected-authority-keyring-sha256 "$(metadata evidence_authority_keyring_sha256)"'
        in script
    )


def test_preplanted_manifest_receipt_is_freshly_reverified_and_rejected(
    tmp_path: Path,
) -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    verifier = _function(script, "verify_manifest_receipt")
    preflight = _function(script, "preflight_impl")
    assert preflight.index("verify_manifest_receipt") < preflight.index(
        'if [[ ! -e "$PRECONDITIONS_RECEIPT" ]]'
    )

    release_sha = "c" * 40
    stable = {
        "profile": "agentium-release-a-diff-verification-v7",
        "result": "passed",
        "base_sha": "a" * 40,
        "release_a_sha": release_sha,
        "manifest_sha256": "d" * 64,
        "review_policy_sha256": "e" * 64,
        "verified_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    helper = tmp_path / "manifest-helper"
    helper.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        f"print(json.dumps({stable!r},separators=(',',':'),sort_keys=True))\n",
        encoding="utf-8",
    )
    helper.chmod(0o700)
    receipt = tmp_path / "release-a-manifest-verification-receipt.json"
    forged = {**stable, "manifest_sha256": "f" * 64}
    _private_json_file(receipt, forged)
    harness = "\n".join(
        [
            "set -Eeuo pipefail",
            "umask 077",
            f"DEPLOY_DIR={str(tmp_path)!r}",
            f"MANIFEST_RECEIPT={str(receipt)!r}",
            f"FROZEN_MANIFEST_HELPER={str(helper)!r}",
            f"CANDIDATE_REPO={str(tmp_path)!r}",
            f"RELEASE_A_SHA={release_sha!r}",
            f"FROZEN_REVIEW={str(tmp_path / 'review.json')!r}",
            f"FROZEN_MANIFEST={str(tmp_path / 'manifest.json')!r}",
            'assert_private(){ [[ -f "$1" && ! -L "$1" ]]; }',
            'die(){ printf "%s\\n" "$*" >&2; exit 1; }',
            verifier,
            "verify_manifest_receipt",
        ]
    )
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True)
    assert result.returncode != 0
    assert "does not match a fresh semantic verification" in result.stderr


def test_sigkill_and_reboot_reconcile_only_after_terminal_commit(tmp_path: Path) -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    cases = (
        (
            "forward",
            "opening_forward",
            "completed",
            "commit_forward_opening",
            "open_forward_terminal_from_validated_boundary",
            "reconcile_forward_committed_open",
            "COMPLETION_RECEIPT",
            "FORWARD_OPEN_RECONCILED",
        ),
        (
            "rollback",
            "rollback_opening",
            "rolled_back",
            "commit_rollback_opening",
            "reconcile_rollback_committed_open",
            "reconcile_rollback_committed_open",
            "ROLLBACK_COMPLETION_RECEIPT",
            "ROLLBACK_OPEN_RECONCILED",
        ),
    )
    for (
        direction,
        initial_phase,
        terminal_phase,
        commit_name,
        direct_open_name,
        reconcile_name,
        receipt_variable,
        marker_variable,
    ) in cases:
        root = tmp_path / direction
        root.mkdir()
        (root / "phase").write_text(initial_phase, encoding="utf-8")
        (root / "gate").write_text("closed", encoding="utf-8")
        commit = _function(script, commit_name)
        direct_open = _function(script, direct_open_name)
        reconcile = _function(script, reconcile_name)
        harness_path = root / "fault-harness.sh"
        harness_path.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "set -Eeuo pipefail",
                    'ROOT="$1"; FAULT="$2"; ACTION="$3"',
                    'LOG="$ROOT/log"; STATE="$ROOT/phase"; GATE_STATE="$ROOT/gate"',
                    'DEPLOYMENT_ID="release-a-fault"; RELEASE_A_SHA="' + "a" * 40 + '"',
                    f'{receipt_variable}="$ROOT/receipt"',
                    f'{marker_variable}="$ROOT/marker"',
                    'FORWARD_OPEN_AUTHORIZATION="$ROOT/forward-authorization"',
                    'ROLLBACK_OPEN_AUTHORIZATION="$ROOT/rollback-authorization"',
                    "OPENING_FAIL_CLOSED_ARMED=0; OPENING_TERMINAL_SYNCED=0",
                    'phase(){ cat "$STATE"; }',
                    'set_phase(){ printf "%s" "$1" >"$STATE"; printf "phase-%s\\n" "$1" >>"$LOG"; }',
                    'assert_systemd_boot_guards(){ printf "guards-present\\n" >>"$LOG"; }',
                    'publish_completion_receipt(){ : >"$COMPLETION_RECEIPT"; chmod 600 "$COMPLETION_RECEIPT"; printf "receipt-forward\\n" >>"$LOG"; }',
                    'publish_rollback_receipt(){ : >"$ROLLBACK_COMPLETION_RECEIPT"; chmod 600 "$ROLLBACK_COMPLETION_RECEIPT"; printf "receipt-rollback\\n" >>"$LOG"; }',
                    'assert_completion_receipt(){ [[ -f "$COMPLETION_RECEIPT" ]]; }',
                    'assert_rollback_receipt(){ [[ -f "$ROLLBACK_COMPLETION_RECEIPT" ]]; }',
                    'assert_open_reconciled_marker(){ [[ -f "$2" ]]; }',
                    'publish_open_reconciled_marker(){ : >"$2"; chmod 600 "$2"; printf "marker-%s\\n" "$1" >>"$LOG"; }',
                    'publish_terminal_gate_authorization(){ : >"$2"; chmod 600 "$2"; printf "authorization-%s\\n" "$1" >>"$LOG"; }',
                    'assert_terminal_gate_authorization(){ [[ -f "$2" ]]; }',
                    'disable_writer_restarts(){ printf "restarts-disabled\\n" >>"$LOG"; }',
                    'install_gate_closed(){ printf "closed" >"$GATE_STATE"; printf "gate-closed\\n" >>"$LOG"; }',
                    'enter_writer_ingress_gates(){ printf "ingress-closed\\n" >>"$LOG"; }',
                    'stop_writers(){ printf "writers-stopped\\n" >>"$LOG"; }',
                    'stop_writers_preserving_attested_sftp(){ printf "writers-stopped-sftp-preserved\\n" >>"$LOG"; }',
                    'reclose_attested_sftp_to_read_only(){ printf "secure-ro\\n" >>"$LOG"; }',
                    'validate_forward_terminal_boundary(){ printf "forward-boundary-revalidated\\n" >>"$LOG"; }',
                    'set_secure_mode(){ printf "secure-%s\\n" "$1" >>"$LOG"; }',
                    "assert_secure_mode_in_namespaces(){ :; }",
                    "assert_writer_ingress_gates(){ :; }",
                    "assert_writer_ingress_gates_absent(){ :; }",
                    "assert_sftp_runtime_identity_live(){ :; }",
                    "assert_sftp_process_identity_stable(){ :; }",
                    "assert_restart_policies_restored(){ :; }",
                    "assert_systemd_boot_guards_absent(){ :; }",
                    "assert_forward_terminal_open_state(){ :; }",
                    "assert_rollback_terminal_open_state(){ :; }",
                    'sftp_open_deposit_fd_count(){ printf "0\\n"; }',
                    'start_runtime_services_without_restart(){ printf "runtime-started-no-restart\\n" >>"$LOG"; }',
                    "activate_qdrant_write_runtime(){ :; }",
                    "assert_runtime_oci_receipt(){ :; }",
                    "assert_stateful_runtime_identity(){ :; }",
                    "assert_nginx_unique_edge_topology(){ :; }",
                    "validate_rollback_opening_boundary(){ :; }",
                    'gate(){ if [[ "$1" == status ]]; then cat "$GATE_STATE"; else printf "open" >"$GATE_STATE"; printf "gate-exit\\n" >>"$LOG"; [[ "$FAULT" != kill ]] || kill -KILL "$$"; fi; }',
                    'leave_writer_ingress_gates(){ printf "ingress-open\\n" >>"$LOG"; }',
                    'restore_restart_policies_after_open(){ printf "restarts-restored\\n" >>"$LOG"; }',
                    'remove_systemd_boot_guard(){ printf "guard-removed-%s\\n" "$1" >>"$LOG"; }',
                    'die(){ printf "%s\\n" "$*" >&2; exit 1; }',
                    "ok(){ :; }",
                    commit,
                    direct_open if direct_open_name != reconcile_name else "",
                    reconcile,
                    f'if [[ "$ACTION" == commit ]]; then {commit_name}; {direct_open_name}; else {reconcile_name}; fi',
                ]
            ),
            encoding="utf-8",
        )
        harness_path.chmod(0o700)

        killed = subprocess.run(
            ["bash", str(harness_path), str(root), "kill", "commit"],
            capture_output=True,
            text=True,
        )
        assert killed.returncode < 0
        assert (root / "phase").read_text(encoding="utf-8") == terminal_phase
        assert (root / "receipt").exists()
        assert not (root / "marker").exists()
        first_log = (root / "log").read_text(encoding="utf-8").splitlines()
        assert (
            first_log.index(f"receipt-{direction}")
            < first_log.index(f"phase-{terminal_phase}")
            < first_log.index("gate-exit")
        )
        assert not any(row.startswith("guard-removed-") for row in first_log)
        assert "restarts-restored" not in first_log

        resumed = subprocess.run(
            ["bash", str(harness_path), str(root), "resume", "resume"],
            capture_output=True,
            text=True,
        )
        assert resumed.returncode == 0, resumed.stderr
        assert (root / "marker").exists()
        final_log = (root / "log").read_text(encoding="utf-8").splitlines()
        last_close = len(final_log) - 1 - final_log[::-1].index("gate-closed")
        last_exit = len(final_log) - 1 - final_log[::-1].index("gate-exit")
        last_restore = len(final_log) - 1 - final_log[::-1].index("restarts-restored")
        last_marker = len(final_log) - 1 - final_log[::-1].index(f"marker-{direction}")
        assert last_close < last_exit < last_restore < last_marker
        assert any(row.startswith("guard-removed-") for row in final_log[last_restore:])

        # A marker is a durable statement to reconcile, not permission to
        # return without checking the physical gate. Simulate a TERM after the
        # marker followed by the fail-closed trap and require a real reopen.
        (root / "gate").write_text("closed", encoding="utf-8")
        replayed_marker = subprocess.run(
            ["bash", str(harness_path), str(root), "resume", "resume"],
            capture_output=True,
            text=True,
        )
        assert replayed_marker.returncode == 0, replayed_marker.stderr
        replay_log = (root / "log").read_text(encoding="utf-8").splitlines()
        assert replay_log[-1] == f"marker-{direction}"
        assert replay_log.count("gate-exit") >= 3
        if direction == "forward":
            assert "forward-boundary-revalidated" not in replay_log


def test_every_release_a_opening_failure_recloses_all_writer_ingress() -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    trap_body = _function(script, "release_a_fail_closed_trap")
    forward = _function(script, "reconcile_forward_open")
    forward_terminal = _function(script, "reconcile_forward_committed_open")
    forward_physical = _function(script, "open_forward_terminal_from_validated_boundary")
    forward_commit = _function(script, "commit_forward_opening")
    rollback = _function(script, "reconcile_rollback_open")
    rollback_terminal = _function(script, "reconcile_rollback_committed_open")
    rollback_commit = _function(script, "commit_rollback_opening")
    for operation in (
        "disable_writer_restarts",
        "install_gate_closed",
        "enter_writer_ingress_gates",
        "stop_writers",
        "set_secure_mode ro",
        "assert_secure_mode_in_namespaces ro",
        "assert_writer_ingress_gates",
    ):
        assert operation in trap_body
    assert "trap - ERR EXIT HUP INT TERM" in trap_body
    assert "OPENING_TERMINAL_SYNCED" in trap_body
    for boundary in (
        "start_runtime_services_without_restart",
        "activate_qdrant_write_runtime",
        "capture_runtime_oci_receipt",
        "capture_opening_boundary",
        "commit_forward_opening",
        "open_forward_terminal_from_validated_boundary",
    ):
        assert forward.index("OPENING_FAIL_CLOSED_ARMED=1") < forward.index(boundary)
    assert forward_commit.index("publish_completion_receipt") < forward_commit.index(
        "set_phase completed"
    )
    for boundary in (
        "gate exit",
        "leave_writer_ingress_gates",
        "restore_restart_policies_after_open",
        "remove_systemd_boot_guard",
        "publish_open_reconciled_marker",
    ):
        assert forward_physical.index("OPENING_FAIL_CLOSED_ARMED=1") < (
            forward_physical.index(boundary)
        )
        assert forward_physical.index(boundary) < forward_physical.rindex(
            "OPENING_FAIL_CLOSED_ARMED=0"
        )
    assert forward_terminal.index("reclose_attested_sftp_to_read_only") < (
        forward_terminal.index("validate_forward_terminal_boundary")
    ) < forward_terminal.index("open_forward_terminal_from_validated_boundary")
    for boundary in (
        "start_runtime_services_without_restart",
        "commit_rollback_opening",
        "reconcile_rollback_committed_open",
    ):
        assert rollback.index("OPENING_FAIL_CLOSED_ARMED=1") < rollback.index(boundary)
    assert rollback_commit.index("publish_rollback_receipt") < rollback_commit.index(
        "set_phase rolled_back"
    )
    for boundary in (
        "gate exit",
        "leave_writer_ingress_gates",
        "restore_restart_policies_after_open",
        "remove_systemd_boot_guard",
        "publish_open_reconciled_marker",
    ):
        assert rollback_terminal.index("OPENING_FAIL_CLOSED_ARMED=1") < (
            rollback_terminal.index(boundary)
        )
        assert rollback_terminal.index(boundary) < rollback_terminal.rindex(
            "OPENING_FAIL_CLOSED_ARMED=0"
        )

    harness = "\n".join(
        [
            "OPENING_FAIL_CLOSED_ARMED=1",
            "OPENING_TERMINAL_SYNCED=0",
            "OPENING_FAIL_CLOSED_RUNNING=0",
            "disable_writer_restarts(){ echo restart; }",
            "install_gate_closed(){ echo http; }",
            "enter_writer_ingress_gates(){ echo ingress; }",
            "stop_writers(){ echo writers; }",
            "set_secure_mode(){ echo secure-$1; }",
            "assert_secure_mode_in_namespaces(){ echo namespace-$1; }",
            "assert_writer_ingress_gates(){ echo verified; }",
            trap_body,
            "release_a_fail_closed_trap 42 999",
        ]
    )
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True)
    assert result.returncode == 42
    assert result.stdout.splitlines() == [
        "restart",
        "http",
        "ingress",
        "writers",
        "secure-ro",
        "namespace-ro",
        "verified",
    ]

    preserved_harness = "\n".join(
        [
            "OPENING_FAIL_CLOSED_ARMED=1",
            "OPENING_TERMINAL_SYNCED=0",
            "OPENING_FAIL_CLOSED_RUNNING=0",
            'SFTP_RUNTIME_READY="$(mktemp)"',
            "phase(){ echo completed; }",
            "disable_writer_restarts(){ echo restart; }",
            "install_gate_closed(){ echo http; }",
            "enter_writer_ingress_gates(){ echo ingress; }",
            "stop_writers(){ echo destroyed-sftp; }",
            "stop_writers_preserving_attested_sftp(){ echo preserved-sftp; }",
            "set_secure_mode(){ echo secure-$1; }",
            "assert_secure_mode_in_namespaces(){ echo namespace-$1; }",
            "assert_writer_ingress_gates(){ echo verified; }",
            trap_body,
            "release_a_fail_closed_trap 42 1000",
        ]
    )
    preserved = subprocess.run(
        ["bash", "-c", preserved_harness], capture_output=True, text=True
    )
    assert preserved.returncode == 42
    assert "preserved-sftp" in preserved.stdout
    assert "destroyed-sftp" not in preserved.stdout


def test_preexisting_completion_and_rollback_receipts_are_never_trusted_by_mode_only() -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    completion = _function(script, "publish_completion_receipt")
    rollback = _function(script, "publish_rollback_receipt")
    assert "assert_completion_receipt; return" in completion
    assert completion.rstrip().endswith("assert_completion_receipt\n}")
    assert "assert_rollback_receipt; return" in rollback
    assert rollback.rstrip().endswith("assert_rollback_receipt\n}")
    completion_assertion = _function(script, "assert_completion_receipt")
    rollback_assertion = _function(script, "assert_rollback_receipt")
    assert "completion receipt binding differs" in completion_assertion
    assert "completion receipt chronology differs" in completion_assertion
    assert "rollback receipt state binding differs" in rollback_assertion


def test_preexisting_completion_receipt_is_byte_bound_and_strict_json(
    tmp_path: Path,
) -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    code = _python_heredoc(_function(script, "assert_completion_receipt"))
    deployment_id = "release-a-functional"
    release_sha = "a" * 40
    start = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=6)

    def stamp(offset: int) -> str:
        return (start + timedelta(minutes=offset)).isoformat().replace("+00:00", "Z")

    runtime_binding = {
        "live_sha": "b" * 40,
        "sftp_sha": "c" * 40,
        "hostname_sha256": hashlib.sha256(b"agentium.papai.ai").hexdigest(),
        "sftp_container_id": "d" * 64,
        "sftp_image_id": "sha256:" + "e" * 64,
        "sftp_port": 2223,
        "runtime_identity_sha256": hashlib.sha256(b"runtime").hexdigest(),
    }
    payloads = [
        {"verified_at": stamp(2)},
        {"verified_at": stamp(3)},
        {"manifest": "passed"},
        {"preconditions": "passed"},
        {"preconditions_evidence": "passed"},
        {"verified_at": stamp(4)},
        {
            "schema_version": 1,
            "kind": "agentium-release-a-sftp-runtime-ready",
            "result": "passed",
            "deployment_id": deployment_id,
            "release_a_sha": release_sha,
            "ready_at": stamp(0),
            **runtime_binding,
        },
        {
            "schema_version": 1,
            "kind": "agentium-release-a-sftp-postgres-ledger",
            "result": "passed",
            "deployment_id": deployment_id,
            "release_a_sha": release_sha,
            "collected_at": stamp(1),
            **runtime_binding,
        },
    ]
    paths = [tmp_path / f"bound-{index}.json" for index in range(len(payloads))]
    bodies = [
        _private_json_file(path, payload) for path, payload in zip(paths, payloads, strict=True)
    ]
    keys = (
        "release_a_attestation_receipt_sha256",
        "final_evidence_receipt_sha256",
        "manifest_receipt_sha256",
        "preconditions_receipt_sha256",
        "preconditions_evidence_receipt_sha256",
        "runtime_oci_receipt_sha256",
        "sftp_runtime_ready_receipt_sha256",
        "sftp_postgres_ledger_receipt_sha256",
    )
    receipt = {
        "schema_version": 3,
        "kind": "agentium-release-a-transaction-receipt",
        "result": "passed",
        "deployment_id": deployment_id,
        "release_a_sha": release_sha,
        "completed_at": stamp(5),
        **{key: hashlib.sha256(body).hexdigest() for key, body in zip(keys, bodies, strict=True)},
    }
    receipt_path = tmp_path / "completion.json"
    valid_body = _private_json_file(receipt_path, receipt)
    command = [
        sys.executable,
        "-I",
        "-c",
        code,
        str(receipt_path),
        deployment_id,
        release_sha,
        *(str(path) for path in paths),
    ]
    valid = subprocess.run(command, capture_output=True, text=True)
    assert valid.returncode == 0, valid.stderr

    receipt_path.write_bytes(
        valid_body.replace(b'"result":"passed"', b'"result":"passed","result":"passed"', 1)
    )
    duplicate = subprocess.run(command, capture_output=True, text=True)
    assert duplicate.returncode != 0
    assert "invalid completion receipt JSON" in duplicate.stderr


def test_preexisting_rollback_receipt_is_byte_bound_and_strict_json(
    tmp_path: Path,
) -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    code = _python_heredoc(_function(script, "assert_rollback_receipt"))
    deployment_id = "release-a-functional"
    live_sha = "b" * 40
    rollback_path = tmp_path / "rollback-state"
    runtime_path = tmp_path / "runtime-state"
    rollback_body = b"rollback-state\n"
    runtime_body = b"runtime-state\n"
    for path, body in ((rollback_path, rollback_body), (runtime_path, runtime_body)):
        path.write_bytes(body)
        path.chmod(0o600)
    receipt = {
        "schema_version": 2,
        "kind": "agentium-release-a-rollback-receipt",
        "result": "passed",
        "deployment_id": deployment_id,
        "restored_sha": live_sha,
        "rollback_state_sha256": hashlib.sha256(rollback_body).hexdigest(),
        "runtime_state_sha256": hashlib.sha256(runtime_body).hexdigest(),
        "completed_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    receipt_path = tmp_path / "rollback-receipt.json"
    valid_body = _private_json_file(receipt_path, receipt)
    command = [
        sys.executable,
        "-I",
        "-c",
        code,
        str(receipt_path),
        str(rollback_path),
        str(runtime_path),
        deployment_id,
        live_sha,
    ]
    valid = subprocess.run(command, capture_output=True, text=True)
    assert valid.returncode == 0, valid.stderr

    receipt_path.write_bytes(
        valid_body.replace(b'"result":"passed"', b'"result":"passed","result":"passed"', 1)
    )
    duplicate = subprocess.run(command, capture_output=True, text=True)
    assert duplicate.returncode != 0
    assert "rollback receipt is invalid JSON" in duplicate.stderr


def test_executor_pins_local_docker_engine_and_unique_nginx_edge() -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    edge = _function(script, "assert_nginx_unique_edge_topology")
    assert "DOCKER_LOCAL_HOST=unix:///var/run/docker.sock" in script
    assert "docker info --format '{{.ID}}'" in script
    assert "docker_engine_id" in script
    assert "real_ip_header" in edge and "proxy_protocol" in edge
    assert "duplicate Agentium server_name" in edge
    assert "protected upstream outside canonical site" in edge


def test_release_a_pins_candidate_and_runtime_oci_before_every_opening_boundary() -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    prepare = _function(script, "prepare_impl")
    activate = _function(script, "activate_candidate")
    compose_opened = _function(script, "compose_opened")
    candidate_override = _function(script, "candidate_image_override_contract")
    qdrant_activation = _function(script, "activate_qdrant_write_runtime")
    forward = _function(script, "reconcile_forward_open")
    forward_physical = _function(script, "open_forward_terminal_from_validated_boundary")
    completion = _function(script, "publish_completion_receipt")

    assert prepare.index('bash "$FROZEN_DEPLOYER" --build-only') < prepare.index(
        "capture_candidate_oci_receipt"
    )
    assert prepare.index("capture_candidate_oci_receipt") < prepare.rindex("set_phase prepared")
    assert prepare.index("capture_candidate_oci_receipt") < prepare.rindex(
        "ensure_candidate_image_override"
    )
    assert activate.index("ensure_candidate_image_override") < activate.index(
        'bash "$FROZEN_DEPLOYER" --activate-only'
    )
    assert 'AGENTIUM_SAFE_CANDIDATE_IMAGE_OVERRIDE_FILE="$CANDIDATE_IMAGE_OVERRIDE"' in activate
    assert '-f "$CANDIDATE_IMAGE_OVERRIDE"' in compose_opened
    assert '"agentium-p4-maintenance": rows["agentium-worker-cpu"]' in candidate_override
    assert qdrant_activation.index("assert_candidate_image_override") < qdrant_activation.index(
        "compose_opened up"
    )
    assert forward.index("activate_qdrant_write_runtime") < forward.index(
        "capture_runtime_oci_receipt"
    )
    assert forward.index("capture_runtime_oci_receipt") < forward.index("capture_opening_boundary")
    assert forward.rindex("assert_runtime_oci_receipt") < forward.index("commit_forward_opening")
    assert forward_physical.index("assert_runtime_oci_receipt") < (
        forward_physical.index("gate exit")
    )
    assert '"schema_version":3' in completion
    assert "sftp_runtime_ready_receipt_sha256" in completion
    assert "sftp_postgres_ledger_receipt_sha256" in completion
    assert '"runtime_oci_receipt_sha256"' in completion
    assert completion.index('assert_private "$RUNTIME_OCI_RECEIPT"') < completion.index(
        'python3 -I - "$temporary"'
    )


def test_candidate_image_override_is_exactly_derived_from_release_a_receipt(
    tmp_path: Path,
) -> None:
    release_sha = "d" * 40
    receipt = tmp_path / "candidate.json"
    receipt.write_text(json.dumps(_candidate_oci_payload(release_sha)), encoding="utf-8")
    override = tmp_path / "candidate-images.yml"
    code = _python_heredoc(
        _function(
            EXECUTOR.read_text(encoding="utf-8"),
            "candidate_image_override_contract",
        )
    )
    arguments = [
        sys.executable,
        "-I",
        "-c",
        code,
        str(receipt),
        str(override),
        "release-a-functional",
        release_sha,
        "engine-release-a",
        "write",
    ]
    written = subprocess.run(arguments, capture_output=True, text=True)
    assert written.returncode == 0, written.stderr
    expected = (
        "services:\n"
        f"  agentium-backend:\n    image: sha256:{'a' * 64}\n"
        f"  agentium-frontend:\n    image: sha256:{'b' * 64}\n"
        f"  agentium-worker-cpu:\n    image: sha256:{'c' * 64}\n"
        f"  agentium-p4-maintenance:\n    image: sha256:{'c' * 64}\n"
    )
    assert override.read_text(encoding="ascii") == expected
    assert override.stat().st_mode & 0o777 == 0o600

    verified = subprocess.run([*arguments[:-1], "verify"], capture_output=True, text=True)
    assert verified.returncode == 0, verified.stderr
    override.write_text(expected.replace("a" * 64, "f" * 64), encoding="ascii")
    override.chmod(0o600)
    refused = subprocess.run([*arguments[:-1], "verify"], capture_output=True, text=True)
    assert refused.returncode != 0
    assert "differs from OCI receipt" in refused.stderr


def test_release_a_oci_receipts_fail_closed_on_tag_or_runtime_substitution() -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    candidate = _function(script, "assert_candidate_oci_receipt")
    runtime_capture = _function(script, "capture_runtime_oci_receipt")
    runtime = _function(script, "assert_runtime_oci_receipt")

    assert 'image.get("Id")!=row["image_id"]' in candidate
    assert "candidate OCI tag substituted" in candidate
    assert 'labels.get("org.opencontainers.image.revision")!=release_sha' in candidate
    assert "candidate OCI revision substituted" in candidate
    assert 'expected_ref not in (image.get("RepoTags") or [])' in candidate

    assert 'image_id!=row["image_id"]' in runtime_capture
    assert 'config.get("Image")!=row["image_ref"]' in runtime_capture
    assert "runtime OCI image substituted" in runtime_capture
    assert 'state.get("Running") is not True' in runtime_capture
    assert 'health_status not in {"healthy","not_configured"}' in runtime_capture
    assert 'payload.get("revision")!=release_sha' in runtime_capture
    assert "backend build-info substituted" in runtime_capture

    assert 'str(container.get("Id","")).lower()!=row["container_id"]' in runtime
    assert "runtime OCI container substituted" in runtime
    assert 'receipt.get("candidate_oci_receipt_sha256")' in runtime
    assert "engine!=engine_id" in runtime
    assert 'build_info!=receipt.get("backend_build_info")' in runtime


def test_candidate_oci_verifier_functionally_rejects_a_retagged_image(
    tmp_path: Path,
) -> None:
    release_sha = "e" * 40
    _write_fake_oci_docker(tmp_path, release_sha)
    receipt = tmp_path / "candidate.json"
    receipt.write_text(json.dumps(_candidate_oci_payload(release_sha)), encoding="utf-8")
    code = _python_heredoc(
        _function(EXECUTOR.read_text(encoding="utf-8"), "assert_candidate_oci_receipt")
    )
    command = [
        sys.executable,
        "-I",
        "-c",
        code,
        str(receipt),
        "release-a-functional",
        release_sha,
        "engine-release-a",
        "release-a",
    ]
    environment = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}

    valid = subprocess.run(command, capture_output=True, text=True, env=environment)
    assert valid.returncode == 0, valid.stderr

    substituted = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env={**environment, "SUBSTITUTE_TAG": "agentium-frontend"},
    )
    assert substituted.returncode != 0
    assert "candidate OCI tag substituted" in substituted.stderr


def test_runtime_oci_verifier_functionally_rejects_container_substitution(
    tmp_path: Path,
) -> None:
    release_sha = "f" * 40
    _write_fake_oci_docker(tmp_path, release_sha)
    candidate = tmp_path / "candidate.json"
    candidate_bytes = (
        json.dumps(_candidate_oci_payload(release_sha), separators=(",", ":")) + "\n"
    ).encode()
    candidate.write_bytes(candidate_bytes)
    build_info = {
        "service": "backend",
        "revision": release_sha,
        "revision_verified": True,
        "version": "functional-test",
    }
    runtime = tmp_path / "runtime.json"
    runtime.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "agentium-release-a-runtime-oci-receipt",
                "result": "passed",
                "deployment_id": "release-a-functional",
                "release_a_sha": release_sha,
                "docker_engine_id": "engine-release-a",
                "candidate_oci_receipt_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
                "containers": [
                    {
                        "service": "agentium-backend",
                        "container_id": "1" * 64,
                        "image_ref": "agentium-backend:release-a",
                        "image_id": "sha256:" + "a" * 64,
                        "image_revision": release_sha,
                        "state": "running",
                        "health_status": "healthy",
                    },
                    {
                        "service": "agentium-frontend",
                        "container_id": "2" * 64,
                        "image_ref": "agentium-frontend:release-a",
                        "image_id": "sha256:" + "b" * 64,
                        "image_revision": release_sha,
                        "state": "running",
                        "health_status": "healthy",
                    },
                    {
                        "service": "agentium-worker-cpu",
                        "container_id": "3" * 64,
                        "image_ref": "agentium-worker:release-a",
                        "image_id": "sha256:" + "c" * 64,
                        "image_revision": release_sha,
                        "state": "running",
                        "health_status": "not_configured",
                    },
                ],
                "backend_build_info": build_info,
                "verified_at": "2026-07-22T12:01:00Z",
            }
        ),
        encoding="utf-8",
    )

    code = _python_heredoc(
        _function(EXECUTOR.read_text(encoding="utf-8"), "assert_runtime_oci_receipt")
    )
    command = [
        sys.executable,
        "-I",
        "-c",
        code,
        str(candidate),
        str(runtime),
        "release-a-functional",
        release_sha,
        "engine-release-a",
        "1",
    ]
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "SUBSTITUTE_CONTAINER": "agentium-worker-cpu",
    }
    # The runtime identity check happens before the backend HTTP probe, so a
    # substituted container fails without requiring any listening test socket.
    substituted = subprocess.run(command, capture_output=True, text=True, env=environment)
    assert substituted.returncode != 0
    assert "runtime OCI container substituted" in substituted.stderr


def test_rollback_replays_immutable_state_and_host_bytecode_is_never_ignored() -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    rollback = _function(script, "rollback_impl")
    deployer = (ROOT / "scripts" / "deploy-vm.sh").read_text(encoding="utf-8")
    assert rollback.index("set_phase rollback_restoring") < rollback.index(
        'bash "$FROZEN_DEPLOYER"'
    )
    assert 'if [[ "$(git -C "$LIVE_REPO" rev-parse HEAD)" == "$RELEASE_A_SHA"' not in rollback
    assert 'env -i PATH="$COMPOSE_CLEAN_PATH"' in rollback
    assert "grep -vE 'uvicorn\\.log|\\.pyc$'" not in script
    assert "grep -vE 'uvicorn\\.log|\\.pyc$'" not in deployer
    assert "assert_no_host_python_bytecode" in deployer


def test_executor_uses_v2_postgresql_row_state_inventory_at_every_boundary() -> None:
    script = EXECUTOR.read_text(encoding="utf-8")
    capture = _function(script, "capture_postgres_inventory")
    verify = _function(script, "verify_postgres_inventory_v2")
    compare = _function(script, "compare_postgres_inventory_v2")
    opening = _function(script, "capture_opening_boundary")
    rollback_open = _function(script, "reconcile_rollback_open")
    rollback_validation = _function(script, "validate_rollback_opening_boundary")

    assert "agentium-release-a-postgres-inventory-v1" not in script
    assert "scripts.audit_post_canary_database snapshot" in capture
    assert "compose_audit run" in capture
    assert 'p.get("schema_version")!=2' in verify
    assert 'p.get("content_serialized") is not False' in verify
    assert 'binding.get("provided") is not False' in verify
    assert "business_inventory_sha256" in compare
    assert "capture_sftp_postgres_inventory revoked" in opening
    assert 'cmp -s "$SFTP_POSTGRES_FINAL" "$pg_temporary"' in opening
    assert "validate_rollback_opening_boundary" in rollback_open
    assert "compare_postgres_inventory_v2" in rollback_validation


def test_executor_attests_every_business_storage_mount_to_physical_device() -> None:
    capacity = _function(EXECUTOR.read_text(encoding="utf-8"), "assert_capacity_and_mounts")
    for contract in (
        "qdrant:/qdrant/storage:/dev/sdb",
        "qdrant:/qdrant/snapshots:/dev/sdb",
        "agentium-minio:/data:/dev/sdb",
        "agentium-backend:/data/object_store:/dev/sdb",
        "agentium-backend:/data/secure_deposit:/dev/sdc",
        "agentium-backend:/data/faiss_db:/dev/sda1",
        "agentium-worker-cpu:/data/object_store:/dev/sdb",
        "agentium-p4-maintenance:/data/object_store:/dev/sdb",
        "agentium-sftp:/data/secure_deposit:/dev/sdc",
    ):
        assert contract in capacity
    assert 'mounted_source="${mounted_source%%[*}"' in capacity


def test_rabbit_bootstrap_never_passes_password_as_an_argument_and_probes_io() -> None:
    body = _function(EXECUTOR.read_text(encoding="utf-8"), "bootstrap_rabbitmq")
    assert "AGENTIUM_RABBITMQ_PASSWORD" not in body.split("<<'PY'", 1)[0]
    assert '"configure": ".*"' in body
    assert "rabbitmq-publish.json" in body
    assert "rabbitmq-get.json" in body
    assert "clear_permissions -p / guest" in body
    assert "--netrc-file" in body


def test_minio_bootstrap_is_versioned_and_uses_no_delete_app_policy() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    assert 'mc version enable "agentium/$$MINIO_BUCKET"' in compose
    assert '"s3:GetObject","s3:PutObject"' in compose
    assert "s3:DeleteObject" not in compose
    assert "mc version suspend" in compose
    assert "mc rm" in compose
    assert "mc pipe" in compose
    assert "AccessDenied|access denied" in compose
    assert "mc rm --force --versions" in compose
    assert "mc stat" in compose
    assert (
        compose.count('mc ls --versions "agentium/$$MINIO_BUCKET/$$MINIO_RELEASE_A_PROBE_KEY"') == 2
    )
    assert "read_minio_user_contract" in compose
    assert 'mc admin user info agentium "$$MINIO_APP_ACCESS_KEY" --json' in compose
    assert '*\'"memberOf":[]\'*) ;; *\'"memberOf":\'*) fail' in compose
    assert "tr -d '[:space:]' < /tmp/agentium-app-policy.json" in compose
    assert "tr -d '[:space:]' < /tmp/agentium-app-policy.actual.json" in compose
    assert '[ "$$actual_policy" = "$$expected_policy" ] || fail' in compose
    assert '--policy-file /tmp/agentium-app-policy.actual.json' in compose
    assert 'true::true|true:"$$MINIO_APP_POLICY":true' in compose
    assert '[ "$$(read_minio_user_contract)" = "$$MINIO_APP_POLICY" ] || fail' in compose
    assert (
        'mc admin user add agentium "$$MINIO_APP_ACCESS_KEY" "$$MINIO_APP_SECRET_KEY" '
        ">/dev/null"
    ) in compose
    assert (
        'mc alias set agentium-app http://agentium-minio:9000 "$$MINIO_APP_ACCESS_KEY" '
        '"$$MINIO_APP_SECRET_KEY" >/dev/null'
    ) in compose
    assert '! mc admin policy info agentium "$$MINIO_APP_POLICY"' not in compose


def test_minio_proof_is_recomputed_and_exactly_compared_on_replay() -> None:
    body = _function(EXECUTOR.read_text(encoding="utf-8"), "adopt_stateful_security")
    run = body.index("agentium-minio-init")
    expected = body.index("Rebuild the expected content on every replay")
    compare = body.index('cmp -s "$temporary" "$MINIO_PROOF"')
    assert run < expected < compare
    assert '[[ -e "$MINIO_PROOF" || -L "$MINIO_PROOF" ]]' in body
    assert 'die "Preuve MinIO rejouée divergente"' in body


def test_minio_bootstrap_resumes_after_policy_create_and_rejects_drift(
    tmp_path: Path,
) -> None:
    _write_fake_minio_mc(tmp_path)
    state_path = tmp_path / "minio-state.json"
    command = _minio_bootstrap_command(tmp_path)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FAKE_MINIO_STATE": str(state_path),
        "MINIO_ROOT_USER": "release-a-root",
        "MINIO_ROOT_PASSWORD": "root-secret-not-logged",
        "MINIO_BUCKET": "agentium-artifacts",
        "MINIO_APP_ACCESS_KEY": "agentium-ra-functional",
        "MINIO_APP_SECRET_KEY": "application-secret-not-logged",
        "MINIO_RELEASE_A_PROBE_KEY": ".agentium-release-a-functional",
        "MINIO_APP_POLICY": "agentium-release-a-functional-policy",
        "FAKE_MINIO_CRASH_AFTER_POLICY_CREATE": "1",
    }

    crashed = subprocess.run(
        ["/bin/sh", "-c", command],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert crashed.returncode == 91
    interrupted = json.loads(state_path.read_text(encoding="utf-8"))
    assert interrupted["user_policy"] == ""
    assert interrupted["policy_document"]
    for secret in (environment["MINIO_ROOT_PASSWORD"], environment["MINIO_APP_SECRET_KEY"]):
        assert secret not in crashed.stdout
        assert secret not in crashed.stderr

    environment.pop("FAKE_MINIO_CRASH_AFTER_POLICY_CREATE")
    resumed = subprocess.run(
        ["/bin/sh", "-c", command],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert resumed.returncode == 0, resumed.stderr
    completed = json.loads(state_path.read_text(encoding="utf-8"))
    assert completed["user_policy"] == environment["MINIO_APP_POLICY"]
    assert "probe" not in completed

    replayed = subprocess.run(
        ["/bin/sh", "-c", command],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert replayed.returncode == 0, replayed.stderr
    assert json.loads(state_path.read_text(encoding="utf-8")) == completed

    tampered_policy = {**completed, "policy_document": completed["policy_document"].replace(
        '"s3:PutObject"', '"s3:*"'
    )}
    state_path.write_text(
        json.dumps(tampered_policy, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    rejected_policy = subprocess.run(
        ["/bin/sh", "-c", command],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert rejected_policy.returncode != 0
    assert json.loads(state_path.read_text(encoding="utf-8")) == tampered_policy

    state_path.write_text(
        json.dumps(completed, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    wrong_secret_environment = {**environment, "MINIO_APP_SECRET_KEY": "wrong-secret-not-logged"}
    rejected_secret = subprocess.run(
        ["/bin/sh", "-c", command],
        env=wrong_secret_environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert rejected_secret.returncode != 0
    assert wrong_secret_environment["MINIO_APP_SECRET_KEY"] not in rejected_secret.stdout
    assert wrong_secret_environment["MINIO_APP_SECRET_KEY"] not in rejected_secret.stderr
    assert json.loads(state_path.read_text(encoding="utf-8")) == completed

    grouped_user = {**completed, "groups": ["foreign-admins"]}
    state_path.write_text(
        json.dumps(grouped_user, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    rejected_group = subprocess.run(
        ["/bin/sh", "-c", command],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert rejected_group.returncode != 0
    assert json.loads(state_path.read_text(encoding="utf-8")) == grouped_user

    extra_policy = {
        **completed,
        "user_policy": f"{environment['MINIO_APP_POLICY']},foreign-policy",
    }
    state_path.write_text(
        json.dumps(extra_policy, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    rejected_extra_policy = subprocess.run(
        ["/bin/sh", "-c", command],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert rejected_extra_policy.returncode != 0
    assert json.loads(state_path.read_text(encoding="utf-8")) == extra_policy

    impossible_policy_only = {"policy_document": completed["policy_document"]}
    state_path.write_text(
        json.dumps(impossible_policy_only, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    rejected_impossible_state = subprocess.run(
        ["/bin/sh", "-c", command],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert rejected_impossible_state.returncode != 0
    assert json.loads(state_path.read_text(encoding="utf-8")) == impossible_policy_only


def test_qdrant_probe_never_deletes_an_ambiguous_surviving_collection() -> None:
    body = _function(EXECUTOR.read_text(encoding="utf-8"), "verify_qdrant_keys")
    collision = body.index("Qdrant probe collision/ambiguous interrupted probe")
    create = body.index('request("PUT","/collections/"+name')
    assert collision < create
    prefix = body[:create]
    assert 'request("DELETE","/collections/"+name' not in prefix
