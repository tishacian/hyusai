"""The operator batch uses an immutable candidate and an isolated network."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
REVISION = "a" * 40
IMAGE_SHA = "b" * 64


@pytest.fixture()
def bench(tmp_path):
    config = tmp_path / "private"
    reports = tmp_path / "reports"
    config.mkdir(mode=0o700)
    reports.mkdir(mode=0o700)
    path = config / "postgresql.json"
    path.write_text(
        json.dumps(
            {
                "source_revision": REVISION,
                "runner_image_sha256": IMAGE_SHA,
                "credentials": {"password": "never-print-this-bench-secret"},
            }
        )
    )
    path.chmod(0o600)
    docker = tmp_path / "docker"
    docker.write_text("""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if args[:2] == ['image', 'inspect']:
    print(os.environ['TEST_REVISION'])
elif args[:2] == ['network', 'inspect']:
    print(os.environ.get('TEST_NETWORK', 'bridge connector-certification'))
elif args[0] == 'run':
    with open(os.environ['TEST_CALLS'], 'a') as handle:
        handle.write(json.dumps(args) + '\\n')
    sys.exit(int(os.environ.get('TEST_RUN_EXIT', '0')))
elif args[:2] == ['rm', '-f']:
    pass
else:
    sys.exit(3)
""")
    docker.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "AGENTIUM_CONNECTOR_RUNNER_IMAGE": f"sha256:{IMAGE_SHA}",
        "CONNECTOR_CERT_CONFIG_DIR": str(config),
        "CONNECTOR_CERT_REPORT_DIR": str(reports),
        "CONNECTOR_CERT_NETWORK": "isolated-bench",
        "TEST_REVISION": REVISION,
        "TEST_CALLS": str(tmp_path / "calls"),
    }
    return path, env


def invoke(bench, **env):
    return subprocess.run(
        ["bash", str(ROOT / "scripts/agentium-connector-certification.sh")],
        env={**bench[1], **env},
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "reference", [f"sha256:{IMAGE_SHA}", f"registry.example/runner@sha256:{IMAGE_SHA}"]
)
def test_unpublished_local_image_and_registry_digest_remain_immutable(bench, reference):
    result = invoke(bench, AGENTIUM_CONNECTOR_RUNNER_IMAGE=reference)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in Path(bench[1]["TEST_CALLS"]).read_text().splitlines()]
    assert len(calls) == 1
    args = calls[0]
    assert "--pull=never" in args and "--read-only" in args
    assert args[args.index("--network") + 1] == "isolated-bench"
    assert "never-print-this-bench-secret" not in result.stdout + result.stderr + json.dumps(args)


@pytest.mark.parametrize(
    "fault",
    ["mutable_tag", "revision", "image_sha", "permissions", "symlink", "host_network", "overlap"],
)
def test_preflight_refuses_untrusted_identity_or_isolation_before_starting_container(bench, fault):
    path, env = bench
    if fault == "mutable_tag":
        env["AGENTIUM_CONNECTOR_RUNNER_IMAGE"] = "agentium-connector-runner:latest"
    elif fault in {"revision", "image_sha"}:
        data = json.loads(path.read_text())
        data["source_revision" if fault == "revision" else "runner_image_sha256"] = "c" * (
            40 if fault == "revision" else 64
        )
        path.write_text(json.dumps(data))
    elif fault == "permissions":
        path.chmod(0o640)
    elif fault == "symlink":
        real = path.with_suffix(".private")
        path.rename(real)
        path.symlink_to(real)
    elif fault == "host_network":
        env["TEST_NETWORK"] = "host connector-certification"
    else:
        env["CONNECTOR_CERT_REPORT_DIR"] = str(path.parent / ".")
    result = invoke(bench)
    assert result.returncode == 2
    assert not Path(env["TEST_CALLS"]).exists()
    assert "never-print-this-bench-secret" not in result.stdout + result.stderr


def test_missing_live_scenarios_preserve_nonzero_status(bench):
    result = invoke(bench, TEST_RUN_EXIT="2")
    assert result.returncode == 2
