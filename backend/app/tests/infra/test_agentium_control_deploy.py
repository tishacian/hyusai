"""Exercise automatic selection and the deployment gate without touching a VM."""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
from copy import deepcopy

import pytest

from app.tests.infra.test_agentium_vm_deploy_guards import ROOT, _run, _shell_case, _shell_function

HELPER = ROOT / "scripts/agentium_control_runtime.py"
SPEC = importlib.util.spec_from_file_location("control_runtime", HELPER)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)
IMAGE = "sha256:" + "a" * 64
REVISION = "b" * 40
PRIVATE = "fixture-private-value-never-printed"


def _render(environment=None):
    return {
        "services": {
            name: {"environment": dict(environment or {})}
            for name in ("agentium-backend", *runtime.SERVICES)
        }
    }


def _containers():
    return [
        {
            "Name": "/" + name,
            "Image": IMAGE,
            "State": {"Running": True, "Restarting": False, "Paused": False},
            "Config": {
                "Hostname": "control-worker-local",
                "Cmd": command,
                "Labels": {"org.opencontainers.image.revision": REVISION},
                "Env": [
                    "CELERY_APP=" + runtime.APP,
                    "CELERY_CONTROL_QUEUE=control",
                    "CELERY_QUEUES=control",
                    "CELERY_CONCURRENCY=1",
                    "CELERY_BEAT=0",
                    "AGENTIUM_DISABLE_DOTENV=1",
                    "DATABASE_PASSWORD=" + PRIVATE,
                ],
            },
        }
        for name, command in runtime.COMMANDS.items()
    ]


@pytest.mark.parametrize("flag", runtime.FLAGS)
def test_each_effective_feature_requires_control(flag):
    assert runtime.required(_render({flag: "true"})) is True
    assert runtime.required(_render({flag: "false"})) is False


@pytest.mark.parametrize("flag", runtime.FLAGS)
def test_unknown_flag_values_fail_without_echoing_environment(flag):
    result = subprocess.run(
        [sys.executable, str(HELPER), "required"],
        input=json.dumps(_render({flag: PRIVATE})),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 1
    assert PRIVATE not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "stopped",
        "restarting",
        "paused",
        "stale_image",
        "stale_revision",
        "wrong_queue",
        "wrong_command",
        "unsafe_hostname",
    ],
)
def test_control_runtime_refuses_partial_stale_or_misdirected_processes(mutation):
    rows = deepcopy(_containers())
    if mutation == "missing":
        rows.pop()
    elif mutation in {"stopped", "restarting", "paused"}:
        field = {"stopped": "Running", "restarting": "Restarting", "paused": "Paused"}[mutation]
        rows[1]["State"][field] = mutation != "stopped"
    elif mutation == "stale_image":
        rows[1]["Image"] = "sha256:" + "c" * 64
    elif mutation == "stale_revision":
        rows[0]["Config"]["Labels"]["org.opencontainers.image.revision"] = "c" * 40
    elif mutation == "wrong_queue":
        rows[0]["Config"]["Env"].append("CELERY_QUEUES=cpu,control")
    elif mutation == "wrong_command":
        rows[1]["Config"]["Cmd"] = ["python", "-m", "celery", "-A", "other", "beat"]
    else:
        rows[0]["Config"]["Hostname"] = "one,celery@another-worker"
    result = subprocess.run(
        [sys.executable, str(HELPER), "runtime", "--image", IMAGE, "--revision", REVISION],
        input=json.dumps(rows),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 1
    assert PRIVATE not in result.stdout + result.stderr


def _tools(
    tmp_path, *, existing="", ps_failure=False, containers=None, scheduler_ok=True, worker_ok=True
):
    binary = tmp_path / "bin"
    binary.mkdir()
    (binary / "python3").symlink_to(sys.executable)
    log = tmp_path / "docker-calls.jsonl"
    docker = binary / "docker"
    docker.write_text(
        f"#!{sys.executable}\nimport sys,json\na=sys.argv[3:]\n"
        f"with open({str(log)!r},'a') as f: f.write(json.dumps(a)+'\\n')\n"
        f"if a[0]=='ps':\n print({existing!r}); sys.exit({int(ps_failure)})\n"
        f"elif a[:2]==['image','inspect']: print({IMAGE!r})\n"
        f"elif a[0]=='inspect': print({json.dumps(containers or _containers())!r})\n"
        f"elif a[:2]==['exec','agentium-scheduler-control']: sys.exit({int(not scheduler_ok)})\n"
        f"elif a[:2]==['exec','agentium-worker-control']: sys.exit({int(not worker_ok)})\n"
        "else: sys.exit(99)\n"
    )
    docker.chmod(0o755)
    return log


def _prelude(mode="auto"):
    return (
        f"CONTROL_HELPER={shlex.quote(str(HELPER))}\nW=/frozen/docker\n"
        f"EXECUTION_CONTROL={mode}\nCONTROL_ALL=(agentium-worker-control agentium-scheduler-control)\n"
        "CONTROL_SERVICES=()\nCONTROL_PROFILE=()\nCONTROL_OVERLAY=()\n"
    )


@pytest.mark.parametrize(
    ("mode", "active", "existing", "selected", "allowed"),
    [
        ("auto", False, "", False, True),
        ("auto", True, "", True, True),
        ("auto", False, "agentium-worker-control", True, True),
        ("auto", False, "agentium-scheduler-control", True, True),
        ("1", False, "", True, True),
        ("0", False, "", False, True),
        ("0", True, "", False, False),
        ("0", False, "agentium-worker-control", False, False),
    ],
)
def test_auto_retains_control_for_flags_or_existing_containers_and_refuses_unsafe_disable(
    tmp_path, mode, active, existing, selected, allowed
):
    log = _tools(tmp_path, existing=existing)
    document = json.dumps(_render({"EXECUTION_CONTROL_ENABLED": str(active).lower()}))
    prelude = _prelude(mode) + f"compose() {{ printf '%s\\n' {shlex.quote(document)}; }}\n"
    result = _run(
        tmp_path,
        prelude,
        ["configure_control"],
        'configure_control\nprintf "%s\\n" "${CONTROL_SERVICES[*]}" "${CONTROL_PROFILE[*]}" "${CONTROL_OVERLAY[*]}"',
        env={"PATH": "/usr/bin:/bin", "EXECUTION_CONTROL_ENABLED": "true"},
    )
    assert (result.returncode == 0) is allowed, result.stderr
    if allowed:
        assert ("agentium-worker-control agentium-scheduler-control" in result.stdout) is selected
        assert ("--profile execution-control" in result.stdout) is selected
        assert ("compose.agentium.execution.yml" in result.stdout) is selected
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert "--all" in calls[0]  # stopped containers also require drainage capacity


def test_docker_read_failure_is_not_treated_as_absent_control(tmp_path):
    _tools(tmp_path, ps_failure=True)
    result = _run(
        tmp_path,
        _prelude() + f"compose() {{ printf '%s' {shlex.quote(json.dumps(_render()))}; }}\n",
        ["configure_control"],
        "configure_control",
    )
    assert result.returncode != 0
    assert "Cannot inspect existing execution control capacity" in result.stderr


@pytest.mark.parametrize("service", runtime.SERVICES)
def test_diverging_control_flags_refuse_deployment_without_exposing_environment(tmp_path, service):
    _tools(tmp_path)
    document = _render({"ACTIVITY_OBSERVABILITY_ENABLED": "true", "DATABASE_PASSWORD": PRIVATE})
    document["services"][service]["environment"]["ACTIVITY_OBSERVABILITY_ENABLED"] = "false"
    result = _run(
        tmp_path,
        _prelude() + f"compose() {{ printf '%s' {shlex.quote(json.dumps(document))}; }}\n",
        ["configure_control"],
        "configure_control",
    )
    assert result.returncode != 0
    assert "flags must match" in result.stderr
    assert PRIVATE not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("scheduler_ok", "worker_ok", "accepted"),
    [
        (True, True, True),
        (False, True, False),
        (True, False, False),
    ],
)
def test_runtime_gate_requires_scheduler_pid_and_targeted_worker_ping(
    tmp_path, scheduler_ok, worker_ok, accepted
):
    log = _tools(tmp_path, scheduler_ok=scheduler_ok, worker_ok=worker_ok)
    result = _run(
        tmp_path,
        _prelude()
        + f'CONTROL_SERVICES=("${{CONTROL_ALL[@]}}")\nTAG=bbbbbbbbbbbb\nREVISION={REVISION}\nBUILD_INFO_ATTEMPTS=1\nAGENTIUM_BUILD_INFO_INTERVAL=0\n',
        ["verify_control_runtime"],
        "verify_control_runtime",
    )
    assert (result.returncode == 0) is accepted, result.stderr
    assert PRIVATE not in result.stdout + result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    if scheduler_ok:
        ping = next(args for args in calls if args[:2] == ["exec", "agentium-worker-control"])
        assert ping[ping.index("--destination") + 1] == "celery@control-worker-local"
        assert ping[-2:] == ["--timeout", "3"]


@pytest.mark.parametrize("ready", [True, False])
def test_real_up_case_recreates_both_and_keeps_gate_closed_until_control_ready(tmp_path, ready):
    (tmp_path / "bin").mkdir()
    prelude = _prelude() + (
        'CONTROL_SERVICES=("${CONTROL_ALL[@]}")\n'
        "ML_TS_SERVICES=()\nML_DEEP_SERVICES=()\nCONNECTORS_SERVICES=()\nHUGGINGFACE_SERVICES=()\nOPENBAO_SERVICES=()\n"
        "TAG=bbbbbbbbbbbb\nPREVIOUS_TAG=aaaaaaaaaaaa\n"
        "storage_check() { :; }\nconnector_image_check() { :; }\nstart_run() { :; }\n"
        "gate_enter() { echo closed; }\ngate_leave() { echo reopened; }\n"
        'compose() { printf "compose %s\\n" "$*"; }\ncatalog() { :; }\n'
        f"verify_build_info() {{ REVISION={REVISION}; }}\n"
        f"verify_control_runtime() {{ return {int(not ready)}; }}\n"
        'journal_append() { printf "journal %s\\n" "$*"; }\n'
    )
    result = _run(tmp_path, prelude, [], _shell_case("up"))
    assert (result.returncode == 0) is ready
    up = next(line for line in result.stdout.splitlines() if line.startswith("compose "))
    assert up.endswith("agentium-worker-control agentium-scheduler-control")
    assert "--no-deps --pull never" in up
    assert ("reopened" in result.stdout) is ready
    assert (" failed" in result.stdout) is not ready


@pytest.mark.parametrize(("active", "override"), [(True, False), (False, False), (True, True)])
def test_real_compose_wrapper_renders_frozen_environment_and_optional_control(
    tmp_path, active, override
):
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose required")
    binary = tmp_path / "bin"
    binary.mkdir()
    (binary / "docker").symlink_to(docker)
    runtime_dir = tmp_path / "frozen"
    (runtime_dir / "runtime-env").mkdir(parents=True)
    application = runtime_dir / "runtime-env/application.env"
    application.write_text(
        f"EXECUTION_CONTROL_ENABLED={str(active).lower()}\nEXECUTION_CANARY_WORKSPACES=*\nDATABASE_PASSWORD={PRIVATE}\n"
    )
    effective = runtime_dir / "runtime-env/compose.effective.env"
    effective.write_text(f"AGENTIUM_ENV_FILE={application}\n")
    (runtime_dir / "compose.agentium.opened.yml").write_text(
        "services:\n  agentium-backend:\n    environment:\n      ACTIVITY_OBSERVABILITY_ENABLED: 'true'\n"
        if override
        else "services: {}\n"
    )
    prelude = _prelude() + (
        f"W={shlex.quote(str(ROOT / 'docker'))}\nD={shlex.quote(str(runtime_dir))}\n"
        "TAG=bbbbbbbbbbbb\nADMIN=fixture-qdrant\nWORKERS=8\n"
        "CONNECTORS_ENV=()\nOPENBAO_ENV=()\nCONNECTORS_OVERLAY=()\nHUGGINGFACE_OVERLAY=()\nOPENBAO_OVERLAY=()\n"
    )
    if active:
        prelude += 'CONTROL_PROFILE=(--profile execution-control)\nCONTROL_OVERLAY=(-f "$W/compose.agentium.execution.yml")\n'
    result = _run(
        tmp_path,
        prelude,
        ["compose"],
        "compose config --format json",
        env={
            **os.environ,
            "AGENTIUM_ENV_FILE": "/invalid/ambient.env",
            "COMPOSE_FILE": "/invalid.yml",
        },
    )
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    assert all((name in services) is active for name in runtime.SERVICES)
    if active:
        for name in runtime.SERVICES:
            assert services[name]["image"] == "agentium-worker:bbbbbbbbbbbb"
            assert services[name]["environment"]["DATABASE_PASSWORD"] == PRIVATE
            assert services[name]["environment"]["EXECUTION_CONTROL_ENABLED"] == "true"
            assert not services[name].get("volumes")
        assert services["agentium-backend"]["environment"]["EXECUTION_CONTROL_ENABLED"] == "true"
        if override:
            with pytest.raises(ValueError, match="flags differ"):
                runtime.aligned({"services": services})
        else:
            assert runtime.aligned({"services": services})


def test_control_has_no_vault_or_storage_attachment_and_cannot_start_a_general_beat():
    # The runtime gate validates the actual commands against the same committed
    # Compose definitions; it must not reject the production overlay itself.
    import yaml

    services = yaml.safe_load((ROOT / "docker/compose.agentium.execution.yml").read_text())[
        "services"
    ]
    for name, command in runtime.COMMANDS.items():
        assert services[name]["command"] == command
        assert services[name]["environment"]["CELERY_BEAT"] == "0"
        assert not services[name].get("volumes")
        assert not any("openbao" in entry for entry in services[name]["env_file"])
    storage = _shell_function("storage_check")
    assert '"${CONTROL_ALL[@]}"' not in storage  # storage inventory remains exact
