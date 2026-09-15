#!/usr/bin/env bash
# Light iteration gate — runs on carakai (protected runner host) as root.
#
# Executes the protected runtime canaries and the flag-aware Experience
# Work/Studio canaries from the reviewed source checkout against the deployed
# SHA, WITHOUT the orchestrator and WITHOUT signing tokens. This is
# the per-iteration smoke gate; the signed 7-token attestation stays reserved
# for milestones (scripts/agentium_protected_runner_orchestrator.py).
#
# Credentials are read from the root-only files /root/.attestation-username
# and /root/.attestation-password into the process environment and are never
# written to disk (fixes the cleartext E2E_PASSWORD that the ad-hoc
# /tmp/rb-job/job.env persisted during the 30/07 manual run).
#
# Usage: run-iteration-canaries.sh <deployed 40-hex sha>
set -Eeuo pipefail
umask 077
IFS=$' \t\n'

SOURCE_ROOT=/opt/agentium-protected-runner/repos/omnirag
BROWSERS_ROOT=/opt/agentium-protected-runner/browsers
PYTHON_SITE=/opt/agentium-protected-runner/python-site-asyncssh-2.23.0
USERNAME_FILE=/root/.attestation-username
PASSWORD_FILE=/root/.attestation-password
SHOWCASE_WORKSPACE_ID=e2ed9e40-5fa6-4e32-8948-3e1220134fd3
SHOWCASE_WORKSPACE_SLUG=agentium-showcase
SFTP_HOST_KEY_SHA256='SHA256:zm4vcBu3WcD6WFDLHBN1+dhEK/t0412S2FC2N59cr54'

SHA="${1:-}"
case "$SHA" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) echo "usage: $0 <deployed 40-hex sha>" >&2; exit 2 ;;
esac
[ "$(id -u)" -eq 0 ] || { echo "root is required (credential files are root-only)" >&2; exit 1; }
for f in "$USERNAME_FILE" "$PASSWORD_FILE"; do
  [ -f "$f" ] && [ ! -L "$f" ] || { echo "$f is unavailable" >&2; exit 1; }
  [ "$(stat -c '%U:%a' "$f")" = "root:600" ] || { echo "$f must be root-owned mode 600" >&2; exit 1; }
done
[ -d "$SOURCE_ROOT/frontend-ng" ] || { echo "reviewed source checkout is unavailable" >&2; exit 1; }

RUN_ID="iteration-canaries-$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d "/tmp/${RUN_ID}.XXXXXX")"
mkdir -p "$WORK/evidence" "$WORK/playwright-output"

export CI_COMMIT_SHA="$SHA"
export CI_COMMIT_REF_NAME="iteration-gate"
export CI_COMMIT_REF_PROTECTED=false
export E2E_BASE_URL="https://agentium.papai.ai"
export E2E_DEPLOYMENT_ID="$RUN_ID"
export E2E_EVIDENCE_CLASS=acceptance
export E2E_EXPECTED_SHA="$SHA"
export E2E_EXPERIENCE_CANARY=1
export E2E_EXPERIENCE_EVIDENCE="$WORK/experience.json"
export E2E_FORMAL_RELEASE_ELIGIBLE=false
export E2E_LOT6_CANARY=1
export E2E_HYPERVISOR_V2_CANARY=1
export E2E_LOT6_RUNNER_ATTESTATION="$WORK/system360-runner.json"
export E2E_LOT6_BEHAVIOR_ATTESTATION="$WORK/system360-behavior.json"
export E2E_PRINCIPAL_CLASS=operator_personal_admin
export E2E_PROTECTED_EVIDENCE_DIR="$WORK/evidence"
export E2E_PROTECTED_RUNNER_CANARIES=1
export E2E_SAFE_CONTENT_FREE=1
export E2E_SFTP_HOST=agentium.papai.ai
export E2E_SFTP_HOST_KEY_SHA256="$SFTP_HOST_KEY_SHA256"
export E2E_SFTP_PORT=2222
export E2E_SHOWCASE_WORKSPACE_ID="$SHOWCASE_WORKSPACE_ID"
export E2E_SHOWCASE_WORKSPACE_SLUG="$SHOWCASE_WORKSPACE_SLUG"
export E2E_SOURCE_ROOT="$SOURCE_ROOT"
export E2E_PLAYWRIGHT_OUTPUT_DIR="$WORK/playwright-output"
export E2E_PLAYWRIGHT_RUNTIME_ATTESTATION="$WORK/playwright-runtime.json"
export E2E_PYTHON_SITE="$PYTHON_SITE"
export E2E_USERNAME="$(/bin/cat "$USERNAME_FILE")"
export E2E_PASSWORD="$(/bin/cat "$PASSWORD_FILE")"
export PLAYWRIGHT_BROWSERS_PATH="$BROWSERS_ROOT"
export PLAYWRIGHT_JUNIT_OUTPUT_DIR="$WORK"
export PLAYWRIGHT_JUNIT_OUTPUT_NAME="$WORK/playwright-junit.xml"
trap 'unset E2E_USERNAME E2E_PASSWORD' EXIT

# The Lot 6 spec refuses to run without a SHA-bound Playwright runtime proof.
# Reuse the reviewed producer bytes from the source checkout to build it —
# same input the orchestrated run attests, produced here without orchestration.
/usr/bin/python3 - "$SOURCE_ROOT" "$SHA" "$WORK" <<'PY'
import importlib.util
import sys
from pathlib import Path

source_root = Path(sys.argv[1])
tested_sha = sys.argv[2]
work = Path(sys.argv[3])
spec = importlib.util.spec_from_file_location(
    "agentium_protected_runner_orchestrator",
    source_root / "scripts" / "agentium_protected_runner_orchestrator.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
source_root = module._safe_iteration_source_root(source_root, tested_sha)
produced = module._playwright_runtime_attestation(work, source_root, tested_sha)
assert produced == work / "playwright-runtime.json", produced
PY

cd "$SOURCE_ROOT/frontend-ng"
./node_modules/.bin/playwright test \
  e2e/tests/11-system360-canary.spec.ts \
  e2e/tests/12-protected-runner-canaries.spec.ts \
  e2e/tests/16-experience-work-canary.spec.ts \
  e2e/tests/17-experience-studio-canary.spec.ts \
  e2e/tests/20-hypervisor-v2-canary.spec.ts \
  e2e/tests/23-observability-evidence-canary.spec.ts \
  --project=chromium \
  --reporter=list \
  --output="$E2E_PLAYWRIGHT_OUTPUT_DIR"

echo "iteration canaries passed for $SHA — artifacts: $WORK"
