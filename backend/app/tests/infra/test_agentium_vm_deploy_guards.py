"""Guardrails of scripts/agentium-vm-deploy.sh carried over from the retired
safe chain: dump before migrate, optional maintenance gate, build-info proof
after up, deployment journal and a configurable frozen env bundle."""

from __future__ import annotations

import hashlib
import re
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
LAUNCHER = ROOT / "scripts" / "agentium-vm-deploy.sh"
GATE = ROOT / "scripts" / "agentium-maintenance-gate.sh"
RELEASE_A = ROOT / "scripts" / "deploy-agentium-release-a-safe.sh"
BASE_COMPOSE = ROOT / "docker" / "compose.agentium.yml"
VM_OVERLAY = ROOT / "docker" / "compose.agentium.vm-runtime.yml"
SCRIPT = LAUNCHER.read_text(encoding="utf-8")
DEFAULT_D = "/srv/agentium-data/runtime-env/2026-10-12"


def _shell_function(name: str) -> str:
    marker = f"\n{name}() {{\n"
    assert marker in SCRIPT, name
    body = SCRIPT.split(marker, 1)[1].split("\n}\n", 1)[0]
    return f"{name}() {{\n{body}\n}}\n"


def _shell_case(name: str) -> str:
    match = re.search(rf"^{re.escape(name)}\)\n(.*?)\n\t;;", SCRIPT, re.M | re.S)
    assert match is not None, name
    return match.group(1)


def _executable(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _run(tmp_path: Path, prelude: str, functions: list[str], call: str, env=None):
    harness = tmp_path / "harness.sh"
    harness.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f"COMPOSE_CLEAN_PATH={shlex.quote(str(tmp_path / 'bin'))}:/usr/bin:/bin\n"
        "COMPOSE_CLEAN_HOME=/tmp\nDOCKER_SOCKET=unix:///var/run/docker.sock\n"
        + prelude
        + _shell_function("fail")
        + _shell_function("clean_exec")
        + _shell_function("readonly_docker")
        + "".join(_shell_function(name) for name in functions)
        + call
        + "\n",
        encoding="utf-8",
    )
    return subprocess.run(
        ["bash", str(harness)], check=False, capture_output=True, text=True, env=env
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, DEFAULT_D),
        (
            "/srv/agentium-data/release-a-deployments/release-a-2026-07-27-omnirag-demo",
            "/srv/agentium-data/release-a-deployments/release-a-2026-07-27-omnirag-demo",
        ),
        ("/srv/agentium-data/../etc", None),
        ("/home/ubuntu/agentium-env", None),
        ("/srv/agentium-data", None),
        ("/srv/agentium-data/runtime-env/", None),
        ("relative/env", None),
    ],
)
def test_runtime_env_dir_is_configurable_but_confined_to_the_data_disk(
    tmp_path: Path, value: str | None, expected: str | None
) -> None:
    (tmp_path / "bin").mkdir()
    env = {"PATH": "/usr/bin:/bin"}
    if value is not None:
        env["AGENTIUM_RUNTIME_ENV_DIR"] = value
    result = _run(
        tmp_path,
        f"DATA_ROOT=/srv/agentium-data\nDEFAULT_RUNTIME_ENV_DIR={DEFAULT_D}\n",
        ["runtime_env_dir"],
        "runtime_env_dir",
        env=env,
    )
    if expected is None:
        assert result.returncode != 0
        assert "AGENTIUM_RUNTIME_ENV_DIR" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected
    assert 'D="$(runtime_env_dir)"\nreadonly D\n' in SCRIPT
    assert f'DEFAULT_RUNTIME_ENV_DIR="$DATA_ROOT/{DEFAULT_D.split("/", 3)[3]}"' in SCRIPT


def _fake_backup_tools(tmp_path: Path, mode: str) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    dump = {"ok": "printf 'PGDMP-archive'", "empty": ":", "dump-fails": "exit 1"}
    restore = "exit 1" if mode == "unreadable" else "cat >/dev/null"
    _executable(
        bin_dir / "docker",
        'shift 2\ncase "$*" in\n'
        f"  'exec agentium-pg sh -c '*) {dump.get(mode, dump['ok'])} ;;\n"
        f"  'exec -i agentium-pg pg_restore --list') {restore} ;;\n"
        "  *) exit 99 ;;\nesac\n",
    )
    _executable(bin_dir / "sha256sum", 'shift\nshasum -a 256 "$@"\n')
    _executable(bin_dir / "stat", 'for v do :; done\nwc -c <"$v" | tr -d " "\n')


@pytest.mark.parametrize("mode", ["ok", "empty", "dump-fails", "unreadable"])
def test_migrate_backup_publishes_only_a_verified_dump(tmp_path: Path, mode: str) -> None:
    _fake_backup_tools(tmp_path, mode)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    result = _run(
        tmp_path,
        f"RUN_DIR={shlex.quote(str(run_dir))}\n",
        ["backup_database"],
        'backup_database\nprintf "%s\\n" "$BACKUP"',
    )
    dump = run_dir / "postgres-pre-migrate.dump"
    if mode != "ok":
        assert result.returncode != 0
        assert "migrate not started" in result.stderr
        assert not dump.exists() and not Path(f"{dump}.ready").exists()
        return
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(dump)
    body = dump.read_bytes()
    assert body == b"PGDMP-archive"
    assert Path(f"{dump}.ready").read_text(encoding="utf-8") == (
        f"format\t1\nsha256\t{hashlib.sha256(body).hexdigest()}\nbytes\t{len(body)}\n"
    )
    assert dump.stat().st_mode & 0o077 == 0


def test_migrate_dumps_before_migrating_and_journals_the_outcome() -> None:
    steps = [line.strip() for line in _shell_case("migrate").splitlines()]
    assert steps[:5] == [
        "storage_check",
        "start_run migrate",
        "gate_enter",
        "backup_database",
        'journal_append migrate - "$BACKUP" started',
    ]
    assert steps[5] == "compose run --rm --no-deps --pull never agentium-migrate || {"
    assert 'journal_append migrate - "$BACKUP" failed' in steps
    assert steps[-2:] == ['journal_append migrate - "$BACKUP" passed', "gate_leave"]


def test_up_requires_verified_build_info_before_reopening_the_gate() -> None:
    steps = [line.strip() for line in _shell_case("up").splitlines()]
    assert steps[:3] == ["storage_check", "start_run up", "gate_enter"]
    assert steps[3].startswith("compose up -d --no-build --no-deps --pull never ")
    assert steps[4] == "verify_build_info || {"
    assert steps[5] == "journal_append up - - failed"
    assert "AGENTIUM_IMAGE_TAG=$PREVIOUS_TAG" in steps[6]
    passed = steps.index('journal_append up "$REVISION" - passed')
    assert steps[passed + 1] == "gate_leave"
    assert any(step.startswith("catalog >/dev/null ||") for step in steps[passed:])


@pytest.mark.parametrize(
    ("payload", "tag", "accepted"),
    [
        ('{"revision":"0123456789ab' + "c" * 28 + '","revision_verified":true}', "0123456789ab", True),
        ('{"revision":"0123456789ab' + "c" * 28 + '","revision_verified":false}', "0123456789ab", False),
        ('{"revision":"' + "f" * 40 + '","revision_verified":true}', "0123456789ab", False),
        ('{"revision":"unknown","revision_verified":true}', "0123456789ab", False),
        ("not json", "0123456789ab", False),
    ],
)
def test_build_info_must_report_the_tag_with_a_verified_revision(
    tmp_path: Path, payload: str, tag: str, accepted: bool
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(bin_dir / "docker", f"printf '%s\\n' {shlex.quote(payload)}\n")
    python3 = subprocess.run(
        ["/usr/bin/env", "which", "python3"], check=True, capture_output=True, text=True
    ).stdout.strip()
    _executable(bin_dir / "python3", f'exec {shlex.quote(python3)} "$@"\n')
    result = _run(
        tmp_path,
        f"TAG={tag}\nR=/nonexistent\nBUILD_INFO_ATTEMPTS=2\nAGENTIUM_BUILD_INFO_INTERVAL=0\n",
        ["verify_build_info"],
        'verify_build_info && printf "%s\\n" "$REVISION"',
    )
    assert (result.returncode == 0) is accepted, result.stderr
    if accepted:
        assert result.stdout.strip() == "0123456789ab" + "c" * 28


def test_journal_records_tag_previous_tag_and_revision(tmp_path: Path) -> None:
    (tmp_path / "bin").mkdir()
    journal = tmp_path / "journal.tsv"
    result = _run(
        tmp_path,
        f"JOURNAL={shlex.quote(str(journal))}\nRUN_ID=20261012T150000Z-up\n"
        "TAG=0123456789ab\nPREVIOUS_TAG=ba9876543210\n",
        ["journal_append"],
        "journal_append up " + "a" * 40 + " - passed\njournal_append up - - failed",
    )
    assert result.returncode == 0, result.stderr
    rows = [line.split("\t") for line in journal.read_text(encoding="utf-8").splitlines()]
    assert rows[0] == [
        "recorded_at", "run_id", "command", "tag", "previous_tag", "revision", "backup", "result",
    ]
    assert rows[1][1:] == [
        "20261012T150000Z-up", "up", "0123456789ab", "ba9876543210", "a" * 40, "-", "passed",
    ]
    assert rows[2][-1] == "failed" and len(rows) == 3


def test_start_run_keeps_deployment_state_on_the_data_disk() -> None:
    body = _shell_function("start_run")
    assert 'assert_protected_data_path "$DEPLOYMENTS_ROOT"' in body
    assert "install -d -m 0700" in body
    assert 'readonly DEPLOYMENTS_ROOT="$DATA_ROOT/deployments"' in SCRIPT
    assert 'readonly JOURNAL="$DEPLOYMENTS_ROOT/journal.tsv"' in SCRIPT


def test_gate_is_opt_in_and_driven_through_the_frozen_helper() -> None:
    assert 'GATE="${AGENTIUM_GATE:-0}"' in SCRIPT
    assert 'fail "AGENTIUM_GATE must be 0 or 1"' in SCRIPT
    enter = _shell_function("gate_enter")
    assert enter.splitlines()[2].strip() == '[ "$GATE" = 1 ] || return 0'
    assert '"$MAINTENANCE_GATE" "$RUN_DIR/agentium-maintenance-gate.sh"' in enter
    assert "candidate_sha" in enter and "gate enter" in enter
    gate = _shell_function("gate")
    assert "AGENTIUM_SAFE_GATE_PURPOSE=launcher-open" in gate
    assert 'bash "$RUN_DIR/agentium-maintenance-gate.sh" "$mode"' in gate
    assert "launcher-open:launcher |" in GATE.read_text(encoding="utf-8")
    assert "gate-exit|journal|" in SCRIPT


def _merged_service(name: str) -> dict:
    base = yaml.safe_load(BASE_COMPOSE.read_text(encoding="utf-8"))["services"][name]
    overlay = yaml.safe_load(VM_OVERLAY.read_text(encoding="utf-8"))["services"].get(name, {})
    return {**base, **overlay}


def test_containers_release_a_parks_at_restart_no_come_back_after_a_reboot() -> None:
    """Release A sets restart=no on these only inside its transaction; at rest
    the VM render must bring every one of them back after a reboot."""
    body = RELEASE_A.read_text(encoding="utf-8").split("\ndisable_writer_restarts() {\n", 1)[1]
    parked = re.search(r"for service in ([^;]+); do", body).group(1).split()
    assert {"agentium-kc", "agentium-livekit", "agentium-livekit-agent"} <= set(parked)
    for service in parked:
        assert _merged_service(service)["restart"] == "unless-stopped", service
    overlay = yaml.safe_load(VM_OVERLAY.read_text(encoding="utf-8"))["services"]
    for service in ("agentium-kc", "agentium-livekit", "agentium-livekit-agent"):
        assert overlay[service] == {"restart": "unless-stopped"}


def test_keycloak_is_recreated_only_through_the_worktree_compose() -> None:
    kc = _merged_service("agentium-kc")
    assert kc["ports"] and all(port.startswith("127.0.0.1:") for port in kc["ports"])
    assert kc["healthcheck"]["test"][0] == "CMD-SHELL" and "/kc/realms/" in kc["healthcheck"]["test"][1]
    assert kc["networks"] == ["agentium-net"]
    assert kc["restart"] == "unless-stopped"
    assert sorted(kc["volumes"]) == [
        "../backend/keycloak/realm-export.json:/opt/keycloak/data/import/realm.json:ro",
        "../backend/keycloak/themes/agentium:/opt/keycloak/themes/agentium:ro",
    ]
    assert re.fullmatch(
        r"\s*storage_check\s*\n\s*compose --profile infra up -d --no-build --no-deps --pull never "
        r"--force-recreate --wait --wait-timeout 300 agentium-kc",
        _shell_case("keycloak-up"),
    )
    assert "|sftp-up|keycloak-up|" in SCRIPT
    assert not (ROOT / "deploy" / "redeploy-keycloak.sh").exists()
    for script in (*ROOT.joinpath("deploy").rglob("*.sh"), *ROOT.joinpath("scripts").rglob("*.sh")):
        text = script.read_text(encoding="utf-8")
        assert "docker run" not in text or not re.search(r"agentium-kc|keycloak/keycloak", text), script
    for doc in (*ROOT.joinpath("docs", "ops").glob("*.md"), ROOT / "docs" / "vm-deploy-chat-runbook.md"):
        assert "redeploy-keycloak.sh" not in doc.read_text(encoding="utf-8"), doc


def test_livekit_sidecar_is_built_from_the_repo_and_recreated_through_the_worktree_compose() -> None:
    """agentium-livekit-agent was a hand-made container from a retired checkout
    that no command recreated, so an OpenAI key rotation never reached it."""
    agent = _merged_service("agentium-livekit-agent")
    assert agent["image"] == "agentium-livekit-agent:${AGENTIUM_IMAGE_TAG:-local}"
    assert agent["build"]["context"] == ".."
    assert agent["build"]["dockerfile"] == "./docker/Dockerfile.agentium-livekit-agent"
    assert (ROOT / "livekit-agent" / "src" / "agent.mjs").is_file()
    assert (ROOT / "livekit-agent" / "package-lock.json").is_file()
    assert agent["profiles"] == ["realtime"]
    assert agent["restart"] == "unless-stopped"
    assert agent["networks"] == ["agentium-net"]
    assert not {"volumes", "ports", "env_file"} & set(agent)
    assert agent["environment"]["OPENAI_API_KEY"] == "${OPENAI_API_KEY:-}"
    assert "127.0.0.1:8090/healthz" in agent["healthcheck"]["test"][1]

    server = _merged_service("agentium-livekit")
    assert server["restart"] == "unless-stopped"
    assert server["volumes"] == [
        "./livekit/agentium-livekit.yaml:/etc/livekit/agentium-livekit.yaml:ro"
    ]
    assert 'readonly R=/srv/agentium-data/worktrees/demo-agentic\nreadonly W="$R/docker"\n' in SCRIPT
    assert '--env-file "$D/runtime-env/compose.effective.env"' in _shell_function("compose")

    assert re.fullmatch(
        r"\s*storage_check\s*\n\s*compose --profile realtime up -d --no-build --no-deps --pull never "
        r"--wait --wait-timeout 300 agentium-livekit agentium-livekit-agent",
        _shell_case("livekit-up"),
    )
    assert "|keycloak-up|livekit-up|" in SCRIPT
    for script in (*ROOT.joinpath("deploy").rglob("*.sh"), *ROOT.joinpath("scripts").rglob("*.sh")):
        text = script.read_text(encoding="utf-8")
        assert "docker run" not in text or "livekit" not in text, script


def test_missing_keycloak_client_secret_log_points_at_the_frozen_bundle() -> None:
    auth = (ROOT / "backend" / "app" / "api" / "v1" / "endpoints" / "auth.py").read_text(encoding="utf-8")
    assert "backend/.env" not in auth
    assert '"AGENTIUM_ENV_FILE (source-001.env of the frozen runtime env "' in auth


def test_secrets_runbook_rotates_through_the_frozen_bundle() -> None:
    doc = (ROOT / "docs" / "ops" / "secrets.md").read_text(encoding="utf-8")
    assert "/home/ubuntu/omnirag" not in doc
    assert "backend/.env" not in doc
    assert not re.search(r"systemctl\b.*agentium-backend", doc)
    assert f"B={DEFAULT_D}/runtime-env\n" in doc
    commands = set(re.findall(r"^\s*(?:[A-Z_]+=\S+ )*deploy ([a-z][a-z-]*)", doc, re.M))
    assert {"up", "keycloak-up", "sftp-up", "livekit-up", "ps"} <= commands
    usage = re.search(r"usage: \$0 \{([^}]*)\}", SCRIPT)
    assert usage is not None and commands <= set(usage.group(1).split("|"))
