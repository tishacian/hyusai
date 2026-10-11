import hashlib
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]

# Store only one-way fingerprints of values removed from current executable
# defaults. Git history still requires credential rotation. Candidate values
# are never included in assertion output.
COMPROMISED_CREDENTIAL_LENGTH = 20
COMPROMISED_CREDENTIAL_SHA256 = (
    "bc4a9a87e5a3e3e314fa4c74c1ea0a333dd7ddf7bf10201f8b048596ed67c695"
)
CREDENTIAL_LIKE_RUN = re.compile(rb"[A-Za-z0-9_-]{20,}")

COMPROMISED_IDENTITY_LENGTH = 29
COMPROMISED_IDENTITY_SHA256 = (
    "252d7597abd44c37334d36ea33724ae11a940184f287a7d0a897e9e087a11290"
)
EMAIL_LIKE_VALUE = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+")

OPERATOR_SCRIPT_PREFIXES = ("backend/scripts/", "scripts/")
OPERATOR_SCRIPT_SUFFIXES = (".js", ".mjs", ".py", ".sh", ".ts")
LIVE_AUTH_CONTRACT_PATHS = (
    "frontend-ng/e2e/tests/09-live-workspace-contract.spec.ts",
)

# Empty fallbacks remain acceptable when the script validates them before any
# network call. Non-empty identity or password defaults are not.
NONEMPTY_AUTH_DEFAULTS = (
    re.compile(
        rb"process\.env\.AGENTIUM_(?:EMAIL|PASSWORD)\s*\|\|\s*"
        rb"(['\"])[^'\"]+\1"
    ),
    re.compile(
        rb"process\.env\[['\"]E2E_(?:USERNAME|PASSWORD|BUSINESS_USERNAME|"
        rb"BUSINESS_PASSWORD)['\"]\]\s*(?:\?\?|\|\|)\s*"
        rb"(['\"])[^'\"]+\1"
    ),
    re.compile(
        rb"os\.environ\.get\(\s*(['\"])AGENTIUM_(?:EMAIL|PASSWORD)\1\s*,\s*"
        rb"(['\"])[^'\"]+\2\s*\)"
    ),
    re.compile(rb"\$\{AGENTIUM_(?:EMAIL|PASSWORD):-[^}]+\}"),
    re.compile(
        rb"add_argument\(\s*(['\"])--owner-email\1"
        rb"[^)]{0,240}?default\s*=",
    ),
)


def _candidate_paths() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=REPO_ROOT,
    )
    return [REPO_ROOT / raw.decode() for raw in output.split(b"\0") if raw]


def test_compromised_platform_credential_is_absent_from_tracked_content() -> None:
    hits: list[str] = []

    for path in _candidate_paths():
        try:
            data = path.read_bytes()
        except OSError:
            continue

        for run in CREDENTIAL_LIKE_RUN.finditer(data):
            token = run.group()
            for offset in range(len(token) - COMPROMISED_CREDENTIAL_LENGTH + 1):
                candidate = token[
                    offset : offset + COMPROMISED_CREDENTIAL_LENGTH
                ]
                digest = hashlib.sha256(candidate).hexdigest()
                if digest == COMPROMISED_CREDENTIAL_SHA256:
                    hits.append(str(path.relative_to(REPO_ROOT)))
                    break
            if hits and hits[-1] == str(path.relative_to(REPO_ROOT)):
                break

    assert not hits, "Compromised credential fingerprint found in: " + ", ".join(
        sorted(set(hits))
    )


def test_operator_scripts_have_no_real_agentium_credential_defaults() -> None:
    hits: list[str] = []

    for path in _candidate_paths():
        relative_path = str(path.relative_to(REPO_ROOT))
        if not (
            relative_path.startswith(OPERATOR_SCRIPT_PREFIXES)
            or relative_path in LIVE_AUTH_CONTRACT_PATHS
        ):
            continue
        if not relative_path.endswith(OPERATOR_SCRIPT_SUFFIXES):
            continue

        try:
            data = path.read_bytes()
        except OSError:
            continue

        if any(pattern.search(data) for pattern in NONEMPTY_AUTH_DEFAULTS):
            hits.append(relative_path)

    assert not hits, "Real Agentium credential defaults found in: " + ", ".join(
        sorted(hits)
    )


def test_populated_docker_runtime_env_files_cannot_be_tracked() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text()
    assert "docker/env/*.env" in gitignore.splitlines()

    tracked = subprocess.check_output(
        ["git", "ls-files", "docker/env/*.env"],
        cwd=REPO_ROOT,
        text=True,
    ).splitlines()
    assert not tracked, "Populated Docker runtime env files are tracked: " + ", ".join(
        tracked
    )


def test_personal_identity_is_absent_from_non_test_executable_content() -> None:
    hits: list[str] = []

    for path in _candidate_paths():
        relative_path = str(path.relative_to(REPO_ROOT))
        if not relative_path.endswith(OPERATOR_SCRIPT_SUFFIXES):
            continue
        if "/tests/" in f"/{relative_path}" or relative_path.startswith("tests/"):
            continue

        try:
            data = path.read_bytes()
        except OSError:
            continue

        for candidate in EMAIL_LIKE_VALUE.findall(data):
            if len(candidate) != COMPROMISED_IDENTITY_LENGTH:
                continue
            if hashlib.sha256(candidate).hexdigest() == COMPROMISED_IDENTITY_SHA256:
                hits.append(relative_path)
                break

    assert not hits, "Personal identity embedded in executable content: " + ", ".join(
        sorted(hits)
    )


def test_showcase_seed_rejects_a_missing_or_empty_owner_identity() -> None:
    seed = (REPO_ROOT / "backend/scripts/seed_showcase_workspace.py").read_text()

    assert 'raise argparse.ArgumentTypeError("--owner-email must not be empty")' in seed
    owner_argument = seed[seed.index('"--owner-email"') :]
    owner_argument = owner_argument[: owner_argument.index(")")]
    assert "required=True" in owner_argument
    assert "type=_non_empty_owner_email" in owner_argument
