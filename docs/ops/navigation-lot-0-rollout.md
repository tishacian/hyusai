# Agentium navigation Lot 0 — rollout and proof

This runbook closes the gap between the generic container deployment and the
Lot 0 runtime contract. `scripts/deploy-vm.sh` rebuilds and verifies the three
application images; it intentionally does not mutate host Nginx, run workspace
seeds, rotate user credentials, or execute authenticated browser tests.

## Preconditions

- the platform credential found in Git history has been rotated by its owner;
- the candidate is committed and pushed to `origin/demo/agentic`;
- its full 40-character SHA has been captured before opening the VM session;
- the local backend/frontend gates in
  `docs/agentium-navigation-lot-0-baseline.md` are green;
- `/home/ubuntu/omnirag` has no tracked VM-only changes;
- no Alembic migration is required by this Lot 0 candidate.

Do not copy application files into containers and do not edit the VM checkout
manually. The pushed commit remains the only application source of truth.

## 1. Deploy exactly the validated application SHA

```bash
git fetch origin demo/agentic
EXPECTED_SHA="$(git rev-parse HEAD)"
test "${#EXPECTED_SHA}" = 40
test "$(git rev-parse origin/demo/agentic)" = "$EXPECTED_SHA"

ssh omnirag-demo bash -s -- "$EXPECTED_SHA" <<'REMOTE'
  set -euo pipefail
  expected_sha="$1"
  test "${#expected_sha}" = 40
  cd /home/ubuntu/omnirag
  dirty=$(git status --porcelain | grep -vE "uvicorn\.log|\.pyc$" || true)
  test -z "$dirty" || { printf "%s\n" "$dirty" >&2; exit 1; }
  previous_sha=$(git rev-parse HEAD)
  git fetch origin demo/agentic
  test "$(git rev-parse origin/demo/agentic)" = "$expected_sha"
  git reset --hard "$expected_sha"
  bash scripts/deploy-vm.sh \
    --branch demo/agentic \
    --sha "$expected_sha" \
    --previous-sha "$previous_sha"
REMOTE
```

The explicit fetch/reset bootstraps the new deployment script itself; invoking
the old VM copy directly would not yet know the SHA pin or OCI-label contract.
The deploy script fetches once more, refuses a moved remote branch, then builds
and audits only `EXPECTED_SHA`; its post-build audit performs no network fetch.
It also prints an immutable rollback state path under
`~/.local/state/agentium/deployments/<EXPECTED_SHA>.tsv`. Preserve that path.

## 2. Install the host ingress transactionally

The VM currently uses the container-frontend topology. The transaction below
creates one no-clobber backup per candidate SHA, reuses that original backup on
a retry, verifies the installed bytes, and automatically restores/reloads the
old edge if either `nginx -t` or the candidate reload fails.

```bash
ssh omnirag-demo bash -s -- "$EXPECTED_SHA" <<'REMOTE'
  set -euo pipefail
  expected_sha="$1"
  cd /home/ubuntu/omnirag
  test "$(git rev-parse HEAD)" = "$expected_sha"
  candidate="$PWD/deploy/nginx/agentium-container-frontend.conf"
  active=/etc/nginx/sites-enabled/agentium
  state_dir="$HOME/.local/state/agentium/ingress"
  state_file="$state_dir/${expected_sha}.path"
  mkdir -p "$state_dir"
  chmod 0700 "$state_dir"
  sudo install -d -m 0755 /var/backups/agentium

  if test -f "$state_file"; then
    backup=$(cat "$state_file")
    sudo test -f "$backup"
  else
    backup="/var/backups/agentium/nginx.before-${expected_sha}-$(date -u +%Y%m%dT%H%M%SZ)"
    sudo test ! -e "$backup"
    sudo cp --preserve=mode,ownership,timestamps "$active" "$backup"
    tmp=$(mktemp "$state_dir/.${expected_sha}.XXXXXX")
    printf '%s\n' "$backup" > "$tmp"
    chmod 0600 "$tmp"
    if ! ln "$tmp" "$state_file"; then
      rm -f "$tmp"
      exit 1
    fi
    rm -f "$tmp"
  fi

  restore_on_error() {
    rc=$?
    trap - EXIT
    if test "$rc" -ne 0; then
      set +e
      sudo install -m 0644 "$backup" "$active"
      sudo nginx -t
      sudo systemctl reload nginx
      set -e
    fi
    exit "$rc"
  }
  trap restore_on_error EXIT

  sudo install -m 0644 "$candidate" "$active"
  sudo cmp -s "$candidate" "$active"
  sudo nginx -t
  sudo systemctl reload nginx
  sudo cmp -s "$candidate" "$active"
  sudo nginx -T 2>&1 | tee "$state_dir/${expected_sha}.nginx-T.txt" >/dev/null
  sha256sum "$candidate"
  sudo sha256sum "$active"
  printf 'ingress rollback: %s\n' "$backup"
  trap - EXIT
REMOTE
```

No Keycloak restart is required. The host config is installed explicitly even
though the rebuilt frontend image contains the same SPA guard: otherwise the
public dotpath check could pass through the inner proxy while the authoritative
edge remains stale. `cmp`, both SHA-256 lines and the retained `nginx -T`
snapshot prove that the active edge is the candidate file.

## 3. Apply the idempotent Octocity seed

Existing memberships are preserved. The default empty
`OCTOCITY_OWNER_EMAILS` deliberately skips owner auto-provisioning.
Capture the four seed-owned System IDs before and after the mutation so an
application rollback can pause only rows created by this rollout.

```bash
ssh omnirag-demo bash -s -- "$EXPECTED_SHA" <<'REMOTE'
  set -euo pipefail
  expected_sha="$1"
  cd /home/ubuntu/omnirag
  test "$(git rev-parse HEAD)" = "$expected_sha"
  backend_image=$(docker inspect --format '{{.Image}}' agentium-backend)
  backend_revision=$(docker image inspect \
    --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
    "$backend_image")
  test "$backend_revision" = "$expected_sha"
  state_dir="$HOME/.local/state/agentium/octocity/${expected_sha}"
  mkdir -p "$state_dir"
  chmod 0700 "$state_dir"
  if test ! -f "$state_dir/before.ids"; then
    tmp=$(mktemp "$state_dir/.before.XXXXXX")
    docker exec -w /app/backend agentium-backend \
      python -m app.cli.seed_octocity_mission_room --list-seeded-system-ids \
      | sort > "$tmp"
    if ! ln "$tmp" "$state_dir/before.ids"; then
      rm -f "$tmp"
      exit 1
    fi
    rm -f "$tmp"
  fi
  docker exec -w /app/backend agentium-backend \
    python -m app.cli.seed_octocity_mission_room
  after_tmp=$(mktemp "$state_dir/.after.XXXXXX")
  docker exec -w /app/backend agentium-backend \
    python -m app.cli.seed_octocity_mission_room --list-seeded-system-ids \
    | sort > "$after_tmp"
  mv "$after_tmp" "$state_dir/after.ids"
  comm -13 "$state_dir/before.ids" "$state_dir/after.ids" \
    > "$state_dir/created.ids"
  printf 'seed-created Systems: '
  wc -l < "$state_dir/created.ids"
REMOTE
```

For the idempotence proof, run the seed once more, write a fresh sorted listing
to `after-second.ids`, and require both `cmp after.ids after-second.ids` and the
map fixture counts in the backend contract to stay unchanged. The authenticated
live contract below proves that all seven Octocity navigation items resolve to
active, Octocity-owned Systems.

## 4. Run unauthenticated runtime proofs

```bash
ssh omnirag-demo bash -s -- "$EXPECTED_SHA" <<'REMOTE'
  set -euo pipefail
  cd /home/ubuntu/omnirag
  bash scripts/deploy-vm.sh \
    --check-only --branch demo/agentic --sha "$1"
  current=$(docker exec -w /app/backend agentium-backend alembic current \
    | awk '{ print $1 }' | sort -u)
  heads=$(docker exec -w /app/backend agentium-backend alembic heads \
    | awk '{ print $1 }' | sort -u)
  test -n "$current"
  test "$current" = "$heads"
  printf 'Alembic current=heads: %s\n' "$current"
REMOTE

set -euo pipefail
for uri in /.env /.git/config /assets/.secret; do
  test "$(curl -sS -o /dev/null -w '%{http_code}' \
    "https://agentium.papai.ai$uri")" = 404
done

test "$(curl -sS -o /dev/null -w '%{http_code}' \
  https://agentium.papai.ai/systems)" = 200
test "$(curl -sS -o /dev/null -w '%{http_code}' \
  https://agentium.papai.ai/api/v1/health)" = 200
test "$(curl -sS -o /dev/null -w '%{http_code}' \
  https://agentium.papai.ai/kc/realms/papai-org/.well-known/openid-configuration)" = 200

# Forwarded-header spoofing must not change the public issuer.
issuer=$(curl -sS \
  -H 'Forwarded: host=attacker.invalid;proto=http' \
  -H 'X-Forwarded-Host: attacker.invalid' \
  -H 'X-Forwarded-Proto: http' \
  https://agentium.papai.ai/kc/realms/papai-org/.well-known/openid-configuration \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["issuer"])')
test "$issuer" = 'https://agentium.papai.ai/kc/realms/papai-org'

# Every browser-session cookie returned by the public OIDC authorization edge
# must carry Secure. This endpoint is read-only and does not authenticate.
headers=$(mktemp)
trap 'rm -f "$headers"' EXIT
curl -sS -D "$headers" -o /dev/null \
  'https://agentium.papai.ai/kc/realms/papai-org/protocol/openid-connect/auth?client_id=core-service&redirect_uri=https%3A%2F%2Fagentium.papai.ai%2Fauth%2Fcallback&response_type=code&scope=openid'
awk 'tolower($0) ~ /^set-cookie:/ {
       seen=1
       line=tolower($0)
       if (line !~ /;[[:space:]]*secure(;|[[:space:]]*$)/) bad=1
     }
     END { exit !(seen && !bad) }' "$headers"
rm -f "$headers"
trap - EXIT
```

Record both Alembic outputs; `current` must name the same head as `heads` (the
candidate adds no migration). The issuer and cookie checks exercise the active
Keycloak edge, not only the static Nginx source.

## 5. Run the ten authenticated live contracts

Inject the rotated credential at execution time. Never add it to a command
file, shell history shared with the project, Playwright config, screenshot, or
report. The tenth contract is opt-in and consumes an already provisioned
non-admin member; it never creates an account or changes workspace membership.

Run the command from an interactive Bash shell. The prompts below keep both
passwords out of shell history and disable command tracing inside a subshell;
all credential variables disappear when that subshell exits. Set
`E2E_LIVE_NON_ADMIN=1` in the parent shell only when the dedicated business
account is available.

The eight `E2E_*_WORKSPACE_{ID,SLUG}` variables must come from the current
transaction's private, SHA-bound `workspace-targets.json`. Do not infer them
from workspace names or reuse values from an earlier deployment. The safe VM
runner validates that file and injects these variables automatically.

```bash
(
  set +x
  IFS= read -r -p "Agentium owner username: " E2E_USERNAME
  IFS= read -r -s -p "Agentium owner password: " E2E_PASSWORD
  printf '\n'
  export E2E_USERNAME E2E_PASSWORD

  if [[ "${E2E_LIVE_NON_ADMIN:-0}" == "1" ]]; then
    IFS= read -r -p "Agentium business username: " E2E_BUSINESS_USERNAME
    IFS= read -r -s -p "Agentium business password: " E2E_BUSINESS_PASSWORD
    printf '\n'
    export E2E_BUSINESS_USERNAME E2E_BUSINESS_PASSWORD
  fi

  cd frontend-ng
  PATH="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" \
  E2E_LIVE_CONTRACT=1 \
  E2E_LIVE_FORCE_REFRESH=1 \
  E2E_LIVE_ALL_WORKSPACES=1 \
  E2E_LIVE_NON_ADMIN="${E2E_LIVE_NON_ADMIN:-0}" \
  E2E_SHOWCASE_WORKSPACE_ID="$E2E_SHOWCASE_WORKSPACE_ID" \
  E2E_SHOWCASE_WORKSPACE_SLUG="$E2E_SHOWCASE_WORKSPACE_SLUG" \
  E2E_ANDRITZ_WORKSPACE_ID="$E2E_ANDRITZ_WORKSPACE_ID" \
  E2E_ANDRITZ_WORKSPACE_SLUG="$E2E_ANDRITZ_WORKSPACE_SLUG" \
  E2E_SENTINEL_WORKSPACE_ID="$E2E_SENTINEL_WORKSPACE_ID" \
  E2E_SENTINEL_WORKSPACE_SLUG="$E2E_SENTINEL_WORKSPACE_SLUG" \
  E2E_OCTOCITY_WORKSPACE_ID="$E2E_OCTOCITY_WORKSPACE_ID" \
  E2E_OCTOCITY_WORKSPACE_SLUG="$E2E_OCTOCITY_WORKSPACE_SLUG" \
  E2E_CHROMIUM_EXECUTABLE="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    ./node_modules/.bin/playwright test \
      e2e/tests/09-live-workspace-contract.spec.ts \
      --project=chromium --reporter=list
)
```

The suite proves the three Andritz applications and workspace headers, forced
refresh, IAM/System baseline, pseudonymous canonical navigation telemetry,
Showcase standard shell, Sentinel/Octocity immersive shells with seven active
bindings, and the same three-link mini-shell without preview for a real
non-admin member. Omit `E2E_LIVE_NON_ADMIN` and both `E2E_BUSINESS_*` variables
when that optional account is unavailable; the first nine contracts remain
unchanged.

## 6. Record the deployed baseline

### Immutable execution record — 2026-07-15

- pre-Lot 0 reference: `397fbeb452289f5c5f02d7d5bdd81b057e624540`;
- initial Lot 0 application rollout: `a5b6082dd4a13633db8ed945b13714b12d60708c`;
- final deployed application SHA after the telemetry hotfix:
  `1df8b79d63ea7eb62fbba3391f7283b40f94181f`;
- Alembic `current=heads`: `056_andritz_chat_asset_binding`;
- backend, frontend and worker OCI revision labels: `3/3` equal to the final
  application SHA; VM checkout clean and `deploy-vm.sh --check-only` green;
- application rollback state:
  `/home/ubuntu/.local/state/agentium/deployments/1df8b79d63ea7eb62fbba3391f7283b40f94181f.tsv`;
- ingress candidate/active SHA-256:
  `aec9a9a8f930ca2a490ab8d5c80d4656d93f4c86665213f4533ec8419921aae3`;
- ingress rollback backup:
  `/var/backups/agentium/nginx.before-1df8b79d63ea7eb62fbba3391f7283b40f94181f-20260714T224747Z`;
- final seed state:
  `/home/ubuntu/.local/state/agentium/octocity/1df8b79d63ea7eb62fbba3391f7283b40f94181f`;
- initial rollout seed: one seed-owned System before, four after, three
  created; final hotfix seed: four before/after, zero new seed-owned IDs,
  second execution `systems_created: 0` and identical sorted IDs;
- Octocity runtime: `7/7` navigation bindings active, four bound OCTAVE
  Systems, no Sentinel/AYA token in the payload;
- public probes: `/.env=404`, `/.git/config=404`,
  `/assets/.secret=404`, `/systems=200`, `/api/v1/health=200`, OIDC discovery
  `200`, canonical issuer under spoofed proxy headers and public OIDC cookies
  carrying `Secure`;
- authenticated live result: `9 passed, 1 skipped` on the final SHA. The
  optional non-admin contract was not executed because no dedicated business
  credential was injected; no non-admin proof is claimed;
- the temporary owner secret was removed from the macOS Keychain immediately
  after the final run.

The commit containing this record is documentation-only, post-deployment and
must not be confused with the executed application revision. It is intentionally
not deployed; VM and OCI provenance remain pinned to
`1df8b79d63ea7eb62fbba3391f7283b40f94181f`.

## Rollback

The ingress transaction restores automatically on install/test/reload failure.
For a later ingress-only regression, use the immutable path recorded for the
candidate SHA and fail closed if it is missing:

```bash
ssh omnirag-demo bash -s -- "$EXPECTED_SHA" <<'REMOTE'
  set -euo pipefail
  state="$HOME/.local/state/agentium/ingress/${1}.path"
  test -f "$state"
  backup=$(cat "$state")
  sudo test -f "$backup"
  sudo install -m 0644 "$backup" /etc/nginx/sites-enabled/agentium
  sudo nginx -t
  sudo systemctl reload nginx
REMOTE
```

For an application regression, pause only the OCTAVE Systems whose IDs were
absent before this rollout, then restore the exact image IDs and Git SHA saved
before the build. Run the pause while the candidate backend (which contains the
targeted rollback CLI) is still active:

```bash
ssh omnirag-demo bash -s -- "$EXPECTED_SHA" <<'REMOTE'
  set -euo pipefail
  expected_sha="$1"
  created="$HOME/.local/state/agentium/octocity/${expected_sha}/created.ids"
  rollback_state="$HOME/.local/state/agentium/deployments/${expected_sha}.tsv"
  test -f "$created"
  test -f "$rollback_state"
  cd /home/ubuntu/omnirag
  test "$(git rev-parse HEAD)" = "$expected_sha"
  backend_image=$(docker inspect --format '{{.Image}}' agentium-backend)
  backend_revision=$(docker image inspect \
    --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
    "$backend_image")
  rollback_backend_image=$(awk -F '\t' \
    '$1 == "service" && $2 == "agentium-backend" { print $3 }' \
    "$rollback_state")
  [[ "$rollback_backend_image" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    echo "Invalid backend rollback image" >&2
    exit 1
  }

  if test "$backend_revision" = "$expected_sha"; then
    args=()
    while IFS= read -r system_id; do
      test -n "$system_id" || continue
      case "$system_id" in
        *[!0-9a-f-]*) echo "Invalid System id" >&2; exit 1 ;;
      esac
      args+=(--system-id "$system_id")
    done < "$created"
    if test "${#args[@]}" -gt 0; then
      docker exec -w /app/backend agentium-backend \
        python -m app.cli.seed_octocity_mission_room \
        --pause-seeded-systems "${args[@]}"
    fi
  elif test "$backend_image" = "$rollback_backend_image"; then
    echo "Backend already restored; seed pause was completed before image swap"
  else
    echo "Backend is neither candidate nor recorded rollback image" >&2
    exit 1
  fi

  bash scripts/deploy-vm.sh \
    --branch demo/agentic --rollback-state "$rollback_state"
REMOTE
```

The pause command is replay-safe: it accepts the complete set when every row is
already paused, but rejects any missing/foreign ID or mixed state before making
a partial mutation. Before the first data mutation, the runbook requires both
the checkout and backend image label to match the candidate SHA. The deploy
script requires that checkout and accepts a service only if it still carries
the candidate label or already uses its exact recorded rollback image.

If the pause succeeds but Compose or a healthcheck interrupts the image
rollback, keep the candidate checkout and rerun only the final
`deploy-vm.sh --rollback-state ...` command. The script accepts each service
only when it is still on the candidate SHA or already on its exact recorded
rollback image, and keeps the candidate checkout until every restored service
is healthy; any third state is rejected.

This rollback intentionally preserves the Octocity map fixture, memberships,
collections and audit history; it pauses only newly created active Systems.
That retained data is the accepted forward-only part of this seed. The image
rollback retags the recorded immutable image IDs, recreates the selected
services without a build, resets the checkout to the recorded previous SHA,
waits for backend/frontend health, and audits code/image IDs. Do not use
`docker cp`, an in-container edit, or a dirty VM checkout.
