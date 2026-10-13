"""scripts/agentium-vm-build.sh: the VM build of one release, replacing the
untracked /tmp/deploy-reorg.sh. It must build every image the Compose stack
tags with the release, prove each image's revision, enforce the budgets with
the LiveKit sidecar required, and advance the worktree only by fast-forward."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
BUILD = ROOT / "scripts" / "agentium-vm-build.sh"
BUDGET = ROOT / "scripts" / "agentium-image-budget.sh"
SCRIPT = BUILD.read_text(encoding="utf-8")
CODE = "\n".join(line for line in SCRIPT.splitlines() if not line.lstrip().startswith("#"))
TAGGED = re.compile(r"^\s*image:\s*agentium-([a-z0-9-]+):\$\{AGENTIUM_IMAGE_TAG\b", re.M)


def _script_images() -> list[str]:
    match = re.search(r"^readonly IMAGES=\(([^)]*)\)$", SCRIPT, re.M)
    assert match is not None
    return match.group(1).split()


def _compose_images() -> set[str]:
    names = set()
    for path in sorted((ROOT / "docker").glob("compose.agentium*.yml")):
        names.update(TAGGED.findall(path.read_text(encoding="utf-8")))
    return names


def test_builds_every_image_compose_tags_with_the_release() -> None:
    images = _script_images()
    assert len(images) == len(set(images))
    assert "livekit-agent" in images
    assert set(images) == _compose_images()
    for name in images:
        assert (ROOT / "docker" / f"Dockerfile.agentium-{name}").is_file(), name


def test_every_image_carries_and_is_checked_for_its_revision() -> None:
    for name in _script_images():
        dockerfile = (ROOT / "docker" / f"Dockerfile.agentium-{name}").read_text(encoding="utf-8")
        assert (
            'LABEL org.opencontainers.image.revision="${AGENTIUM_IMAGE_REVISION}"' in dockerfile
        ), name
    assert '--build-arg AGENTIUM_IMAGE_REVISION="$SHA"' in SCRIPT
    assert '{{index .Config.Labels "org.opencontainers.image.revision"}}' in SCRIPT
    assert '[[ "$revision" == "$SHA" ]] || fail' in SCRIPT


def test_python_images_keep_the_qualified_build_arguments() -> None:
    assert re.search(
        r"^readonly DEFAULT_PYTHON_BASE_IMAGE=python:3\.12-slim@sha256:[0-9a-f]{64}$", SCRIPT, re.M
    )
    assert '[[ "$BASE" =~ @sha256:[0-9a-f]{64}$ ]]' in SCRIPT
    assert "backend | worker | ml-ts | ml-deep | hub-fetch)" in SCRIPT
    for arg in (
        "PYTHON_BASE_IMAGE=",
        "PIP_INDEX_URL=https://pypi.org/simple",
        "USER_UID=1000",
        "USER_GID=1000",
    ):
        assert f"--build-arg {arg}" in SCRIPT, arg
    assert "backend) args+=(--build-arg INSTALL_HF_RAG=1)" in SCRIPT
    assert (
        "worker) args+=(--build-arg INSTALL_HF_RAG=1 --build-arg INSTALL_GISKARD_RAGET=true)"
        in SCRIPT
    )


def test_budgets_are_enforced_with_the_sidecar_required() -> None:
    budgets = dict(
        re.findall(r'^: "\$\{AGENTIUM_IMAGE_BUDGET_MB_([A-Z_]+):=(\d+)\}"$', SCRIPT, re.M)
    )
    assert budgets == {
        "BACKEND": "1400",
        "WORKER": "1760",
        "FRONTEND": "40",
        "ML_TS": "1240",
        "LIVEKIT_AGENT": "110",
    }
    for name in budgets:
        assert (
            f"AGENTIUM_IMAGE_BUDGET_MB_{name}"
            in SCRIPT.split("export ", 1)[1].split("\nAGENTIUM_IMAGE_REQUIRE", 1)[0]
        )
    assert re.search(
        r'^AGENTIUM_IMAGE_REQUIRE_LIVEKIT_AGENT=1 scripts/agentium-image-budget\.sh "\$SHA12" </dev/null \|\|$',
        SCRIPT,
        re.M,
    )


def test_worktree_advances_by_fast_forward_under_a_lock() -> None:
    assert "set -euo pipefail" in SCRIPT
    assert 'exec 9>"$LOCK"' in SCRIPT and "flock -n 9 ||" in SCRIPT
    assert re.search(r"^\[\[ \"\$SHA\" =~ \^\[0-9a-f\]\{40\}\$ \]\]", SCRIPT, re.M)
    assert 'sudo -n git -C "$R" fetch -q origin "$BRANCH"' in SCRIPT
    assert 'git -C "$R" merge-base --is-ancestor "$SHA" FETCH_HEAD' in SCRIPT
    assert 'sudo -n git -C "$R" merge -q --ff-only "$SHA"' in SCRIPT
    assert 'sudo -n chmod -R a+rX "$R"' in SCRIPT
    assert 'git -C "$R" status --porcelain' in SCRIPT
    for forbidden in ("reset", "checkout", "--force", "clean -", "stash", "rsync", "scp "):
        assert forbidden not in CODE, forbidden
    for line in CODE.splitlines():
        if "sudo" in line:
            assert "sudo -n " in line, line


def test_reads_no_runtime_env_or_secret() -> None:
    for forbidden in (
        ".env",
        "ENV_FILE",
        "runtime-env",
        "PASSWORD",
        "TOKEN",
        "SECRET",
        "OPENBAO",
        "--secret",
    ):
        assert forbidden not in CODE, forbidden
    assert "agentium-vm-deploy.sh" not in CODE


def _fake_docker(tmp_path: Path, present: list[str]) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        '[ "$1 $2" = "image inspect" ] || exit 2\n'
        "shift 2\n"
        '[ "$1" = --format ] && shift 2\n'
        "[ $# -eq 1 ] || exit 1\n"
        'for image in $FAKE_IMAGES; do [ "$image" = "$1" ] && { echo 104857600; exit 0; }; done\n'
        "exit 1\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "FAKE_IMAGES": " ".join(f"agentium-{name}:abc123def456" for name in present),
    }


@pytest.mark.parametrize(
    ("require", "present", "rc", "verdict"),
    [
        (None, ["backend", "worker", "frontend"], 0, "not built (optional)"),
        ("1", ["backend", "worker", "frontend"], 1, "missing"),
        ("1", ["backend", "worker", "frontend", "livekit-agent"], 0, "unbounded"),
    ],
)
def test_budget_requires_the_sidecar_only_when_asked(
    tmp_path: Path, require: str | None, present: list[str], rc: int, verdict: str
) -> None:
    env = _fake_docker(tmp_path, present)
    if require is not None:
        env["AGENTIUM_IMAGE_REQUIRE_LIVEKIT_AGENT"] = require
    result = subprocess.run(
        ["bash", str(BUDGET), "abc123def456"], check=False, capture_output=True, text=True, env=env
    )
    assert result.returncode == rc, result.stdout + result.stderr
    assert "agentium-livekit-agent:abc123def456\t" in result.stdout
    sidecar = next(
        line for line in result.stdout.splitlines() if line.startswith("agentium-livekit-agent:")
    )
    assert sidecar.endswith(verdict)
    assert "agentium-ml-ts:abc123def456\t-\t-\tnot built (optional)" in result.stdout


def test_budget_over_limit_fails_for_the_sidecar(tmp_path: Path) -> None:
    env = _fake_docker(tmp_path, ["backend", "worker", "frontend", "livekit-agent"])
    env["AGENTIUM_IMAGE_REQUIRE_LIVEKIT_AGENT"] = "1"
    env["AGENTIUM_IMAGE_BUDGET_MB_LIVEKIT_AGENT"] = "99"
    result = subprocess.run(
        ["bash", str(BUDGET), "abc123def456"], check=False, capture_output=True, text=True, env=env
    )
    assert result.returncode == 1
    assert "agentium-livekit-agent:abc123def456\t100\t99\tOVER" in result.stdout
