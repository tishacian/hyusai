# Agentium release process — `demo/agentic` → VM `omnirag-demo`

> Scope: the **iteration release loop** — shipping a pushed commit of
> `demo/agentic` to the demo VM. Milestone releases (signed attestations,
> SFTP/infra changes, storage moves) go through the full orchestrator instead:
> [`ops/agentium-safe-vm-deployment.md`](./ops/agentium-safe-vm-deployment.md).
> A release is an explicit GO: nothing here authorizes a commit, push, or
> deployment by itself.

---

## 0. The one principle

**`origin/demo/agentic` is the single source of truth.** The VM runs only
pushed commits, built on the VM itself (no external registry), addressed by
immutable image tags. At any moment you must be able to answer *"which commit
is live?"* with a SHA — `/api/v1/build-info` is that answer.

A land on `origin/demo/agentic` (including an AgentLoop / Flow Builder slice)
is not a VM switch. The iteration loop below is the only path; there is no
sidecar deploy for a `cursor/…` or `feat/…` branch.

```
local gates ──push──> origin/demo/agentic ──fetch+ff──> VM worktree ──docker build──> images:<sha12> ──up──> live
```

## 1. The machines

| Machine | Role |
|---|---|
| Your laptop | Development and the pre-push gates. Never builds release artifacts |
| `omnirag-demo` (SSH alias) | Build node **and** runtime. Build worktree `/srv/agentium-data/worktrees/demo-agentic`, deploy script inside it, Docker Compose stack, PostgreSQL |
| carakai (protected runner) | Runs the iteration canaries against the live URL after the switch |

Two paths on the VM, don't confuse them:

- `/srv/agentium-data/worktrees/demo-agentic` — the **build worktree**. This is
  what you advance and build from.
- `/home/ubuntu/omnirag` — the historical checkout, still the **mount anchor**
  for live containers (FAISS, secure deposit, Keycloak files). Never delete or
  reset it casually.

## 2. Pre-flight (local)

All green before pushing:

```bash
cd frontend-ng && npm run check:i18n && npm run check:ui-chrome && npm run test:unit && npm run build:prod
cd backend && pytest app/tests/...        # scoped to the slice being shipped
git status                                # clean tree, closed file list staged
git push origin demo/agentic
```

Record the SHA: `git rev-parse HEAD` (40-hex, call it `<sha40>`; its 12-char
prefix is `<sha12>`).

## 3. Advance the VM build worktree

The worktree is root-administered and its tracking refs are **not** the ones
you fetch — always merge `FETCH_HEAD`, and always with `--ff-only`:

A Cloud Agent without a key accepted by `ubuntu@217.182.104.99` cannot
run this section. Authorize the agent's pubkey (or inject the operator
key as an environment secret) first. `Permission denied (publickey)` is
a hard stop — never `rsync`/`scp` the tree to skip it.

```bash
ssh omnirag-demo
sudo git -C /srv/agentium-data/worktrees/demo-agentic fetch origin demo/agentic
sudo git -C /srv/agentium-data/worktrees/demo-agentic merge --ff-only FETCH_HEAD
sudo git -C /srv/agentium-data/worktrees/demo-agentic status --porcelain   # must be empty
```

(`sudo -u ubuntu git …` fails on this worktree — use plain `sudo`.)

## 4. Build the three images

Built on the VM, from the worktree, tagged with the **immutable 12-hex** SHA
prefix (the deploy script rejects anything else). All four build-args are
mandatory. The moving tag `demo-agentic` is the rollback pointer — do **not**
move it during the release.

```bash
cd /srv/agentium-data/worktrees/demo-agentic
for svc in backend worker frontend; do
  sudo docker build -f docker/Dockerfile.agentium-$svc \
    --build-arg AGENTIUM_IMAGE_REVISION=<sha40> \
    --build-arg PIP_INDEX_URL=https://pypi.org/simple \
    --build-arg USER_UID=1000 --build-arg USER_GID=1000 \
    -t agentium-$svc:<sha12> .
done
```

Build all three even for a frontend-only change: the single tag drives the
whole stack at switch time.

## 5. Migrations — only if the slice contains one

If `backend/alembic/versions/` gained a file, take a checksummed dump first,
then migrate. If not, skip to §6.

```bash
# Window directory for this release's evidence (named after the slice,
# e.g. experience-deployments, flow-publication-deployments)
D=/srv/agentium-data/<slice>-deployments/$(date +%F)-<sha12>
sudo mkdir -p "$D"

# Dump from inside the pg container, then copy out and checksum
sudo docker exec agentium-pg pg_dump -U agentium -d agentium -Fc -f /tmp/pre-<sha12>.dump
sudo docker cp agentium-pg:/tmp/pre-<sha12>.dump "$D/"
sudo sha256sum "$D/pre-<sha12>.dump" | sudo tee "$D/pre-<sha12>.dump.sha256"
sudo touch "$D/.ready"

# Migrate (runs the storage gate first, then the one-off agentium-migrate)
DEPLOY=/srv/agentium-data/worktrees/demo-agentic/scripts/agentium-vm-deploy.sh
sudo env AGENTIUM_IMAGE_TAG=<sha12> "$DEPLOY" migrate
```

Verify the Alembic head advanced to the expected revision before switching.

### 5b. Once the data/ML plane is deployed, that dump is no longer a backup

From revision `096_tabular_data_plane` on, Postgres stops being the whole state.
A `tabular_datasets` row names a Parquet object by `storage_key` and an
`ml_models` row names an MLflow model directory by `model_uri`, both living in
the MinIO bucket. Restoring the dump above and nothing else gives back a registry
of dangling URIs: `/predict` answers `ML_ARTIFACT_MISSING`, dataset previews
fail, and the failure is silent until someone clicks.

So from that revision on, replace the block above with:

```bash
DUMP=/srv/agentium-data/worktrees/demo-agentic/scripts/agentium-data-plane-dump.sh
sudo "$DUMP" <sha12> <slice>
```

It takes the same `pg_dump`, adds a dump of the `mlflow` registry database,
mirrors out the `tabular/` and `ml/` prefixes of every workspace the registry
actually references, checksums each part, and then verifies that every artifact
the registry names is present in the window. `.ready` appears only if that check
passed — so `.ready`, not the directory, is what says the window can be restored
from. It also runs safely against a pre-096 database, where it reports that there
is no plane and skips the mirror rather than writing an empty `objects/` that
would look like a failed mirror.

Do not substitute `mc mirror` of the whole `workspaces/` prefix: knowledge
collections are an order of magnitude larger and are rebuilt from their sources,
not restored.

**One provisioning step this slice adds:** a `mlflow` database on the same
instance, backing the MLflow Model Registry.

```bash
docker exec agentium-pg psql -U agentium -d postgres \
  -c "SELECT 1 FROM pg_database WHERE datname='mlflow'" -At \
  || docker exec agentium-pg createdb -U agentium mlflow
```

The backend creates it on first use if the role may, so this is belt-and-braces —
but doing it here means a permissions problem fails the deploy loudly instead of
the first training run logging a warning and carrying on without a registry.
There is still **no MLflow server**: the client writes straight to that database,
which is the only kind of store an MLflow registry works against. Details, and
what the registry buys that `ml_models` cannot, are in
[`ops/agentium-data-plane-provisioning.md`](ops/agentium-data-plane-provisioning.md).

## 6. Switch

```bash
DEPLOY=/srv/agentium-data/worktrees/demo-agentic/scripts/agentium-vm-deploy.sh
sudo env AGENTIUM_IMAGE_TAG=<sha12> "$DEPLOY" storage-check
sudo env AGENTIUM_IMAGE_TAG=<sha12> "$DEPLOY" up
```

`up` recreates exactly `agentium-backend`, `agentium-worker-cpu`,
`agentium-frontend`, `agentium-p4-maintenance`, `agentium-beat` — with
`--no-build --pull never`, so the images from §4 must exist at the tag.
Infrastructure containers (pg, Keycloak, Qdrant, MinIO, RabbitMQ, SFTP,
LiveKit) are never touched by this path.

## 7. Verify — the release is not done until this passes

```bash
sudo docker ps --format '{{.Names}}\t{{.Status}}' | sort      # app containers healthy
curl -sk https://localhost/api/v1/build-info -H "Host: agentium.papai.ai"
#   -> "revision": "<sha40>", "revision_verified": true
curl -sk -o /dev/null -w '%{http_code}\n' https://localhost/ -H "Host: agentium.papai.ai"   # 200
sudo docker logs agentium-backend --since 5m 2>&1 | grep -icE 'traceback|exception'          # 0
```

`build-info` only answers over HTTPS through nginx — plain `:8000` on the host
is not published.

Then the canaries — they run on the **protected runner host** (root, from its
reviewed source checkout), not on the VM:

```bash
scripts/run-iteration-canaries.sh <sha40>
# runs e2e specs 11 (System360), 12 (protected runner), 16 (Experience Work), 17 (Experience Studio)
# against https://agentium.papai.ai, asserting the deployed SHA
```

Finish with a manual smoke in a **hard-reloaded** browser tab (see §10).

## 8. Feature flags — if the slice ships one

Workspace flags live in `workspaces.settings.features.*`. The column is
`json`, not `jsonb` — cast both ways or the UPDATE fails:

```sql
UPDATE workspaces
SET settings = jsonb_set(COALESCE(settings, '{}'::json)::jsonb,
                         '{features,<flag_name>}', 'true', true)::json;
```

## 9. Rollback

Images are immutable per iteration, the database is not. Two cases:

- **No migration in the slice**: point the stack back at the previous tag.

  ```bash
  sudo env AGENTIUM_IMAGE_TAG=<previous sha12> "$DEPLOY" up
  ```

- **Migration already applied**: do not restore the dump onto a base that has
  taken writes — fix forward (revert commit, new release), or disable the
  feature flag. The dump is a disaster artifact, not an undo button.

Keep the previous `<sha12>` in the release note you write afterwards; it is
the rollback address.

## 10. Traps that have actually bitten

- **Stale tabs after a switch.** A browser tab loaded before the deploy keeps
  the old JS bundle against the new API. Payload-shape rejections come back as
  bare 422s; the Studio now surfaces "This tab was opened before an update —
  reload it". Always hard-reload (Cmd+Shift+R) before QA-ing a release.
- **Tag length.** `AGENTIUM_IMAGE_TAG` must be `demo-agentic` or exactly
  12 hex chars. An 8-char prefix is rejected by the deploy script.
- **Worktree refs.** `merge --ff-only origin/demo/agentic` reports "Already up
  to date" while the worktree is behind — the clone's tracking ref doesn't
  move. Fetch then merge `FETCH_HEAD` (§3).
- **Env file path.** `AGENTIUM_ENV_FILE=./env/agentium.vm.env` is relative to
  `docker/`. The deploy script wires the frozen effective env itself; never
  source the env file into your shell.
- **`settings` is `json`.** `jsonb_set` without the double cast fails (§8).
- **Host checkout SHA ≠ running code.** Only `build-info` from the running
  container proves what is live; the worktree SHA proves nothing about
  containers.

## 11. Never

- Never `rsync`/`scp` code to the VM; never build from a dirty worktree.
- Never `--profile infra` in a routine release (it recreates pg/Keycloak/Qdrant).
- Never touch `agentium-sftp` or LiveKit outside the orchestrated procedures.
- Never `docker volume prune` on the VM.
- Never move the `demo-agentic` tag as part of an iteration release.
- Never force-push `demo/agentic`.

## 12. After the release

Write the iteration down in `docs/ops/agentium-safe-vm-deployment.md` (that
file doubles as the deployment journal): SHA released, images built, dump
location if any, canary result, rollback address. If the release changed the
operator surface, update the affected runbooks in the same commit.

Nawa **PR to PO** desk (`/work/pr-to-po?workspace=nawa&lang=en`) — present to
Fayçal from the operator-desk playbook, not from the UI:

- English handout: [`docs/ops/nawa-pr-to-po-live-demo-playbook.md`](./ops/nawa-pr-to-po-live-demo-playbook.md)
  and the illustrated Word
  [`docs/ops/nawa-pr-to-po-live-demo-playbook.docx`](./ops/nawa-pr-to-po-live-demo-playbook.docx)
- Presenter card (FR):
  [`docs/ops/nawa-pr-to-po-live-demo-presenter-fr.md`](./ops/nawa-pr-to-po-live-demo-presenter-fr.md)

The four proofs stay in those docs. The desk is an operator screen (no numbered
beats). Rebuild the Word with
`docs/ops/build-nawa-pr-to-po-playbook.py` after a label or figure change.
Always hard-reload before the talk.
