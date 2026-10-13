# Agentium — secrets runbook

Where every secret lives, how it gets rotated, and what breaks if you
mess it up. Agnostic of the vault you actually use — the convention
is "one record per secret, tagged `agentium-prod` or `agentium-dev`".

## Scope

This document covers the **prod `omnirag-demo`** VM (`agentium.papai.ai`).
Dev laptops use local `.env` files checked against `docker/test_env_files/`
with placeholders — never production secrets.

## Runtime env bundle on the VM

The backend, its workers, the SFTP server, the Hub worker, Keycloak,
LiveKit and its realtime STT sidecar (`agentium-livekit-agent`) are
containers created by `scripts/agentium-vm-deploy.sh` from the
frozen env bundle named by its `DEFAULT_RUNTIME_ENV_DIR`, currently
`/srv/agentium-data/runtime-env/2026-10-12`. Its files sit in
`runtime-env/`, root-owned, `0600`. A container reads its environment
once, at creation: editing a file changes nothing until the matching
`agentium-vm-deploy.sh` command recreates the container, and a
`docker restart` keeps the old environment.

`compose.effective.env` is the `--env-file` of every Compose call. It only
feeds interpolation; its `AGENTIUM_*ENV_FILE` keys name the file each
service loads. On 2026-10-13:

| File | Named by | Read by |
| ---- | -------- | ------- |
| `source-001.env` | `AGENTIUM_ENV_FILE` | `agentium-backend`, `agentium-migrate`, `agentium-worker-cpu`, `agentium-worker-recipes`, `agentium-worker-ml-ts(-serve)`, `agentium-worker-ml-deep(-serve)`, `agentium-beat`, `agentium-p4-maintenance`, `agentium-sftp` |
| `huggingface-worker.env` | `AGENTIUM_HUB_ENV_FILE` | `agentium-hub-fetch` |
| `source-003.env` | `AGENTIUM_KEYCLOAK_ENV_FILE` | `agentium-kc` (`KC_*` settings only) |
| `source-002.env` | `AGENTIUM_QDRANT_ENV_FILE` | `qdrant` (API keys) |
| `openbao-{backend,worker,hub-fetch}.env` | `agentium-vm-deploy.sh` | AppRole of backend/migrate, cpu/recipes workers, Hub worker |
| `compose.effective.env` | `--env-file` | Interpolation only: `AGENTIUM_POSTGRES_PASSWORD` → `agentium-pg`, `OPENAI_API_KEY` → `agentium-livekit-agent`, `LIVEKIT_*` keys → `agentium-livekit`, paths |
| `source-000.env` | — | Nothing: the Compose env the bundle was frozen from (provenance) |
| `source-004.env` | — | Nothing: frozen env of the retired systemd backend (`DATABASE_URL` on `localhost`), kept for provenance |

`compose.effective.env`, `source-000.env` and `source-004.env` repeat
`DATABASE_URL` and `KEYCLOAK_CLIENT_SECRET` without any container reading
them there. Update them in the same edit anyway: the bundle contract of
`scripts/agentium_runtime_env_bundle.py` requires every PostgreSQL
password copy to agree, and an inert copy left on an old value is the one
somebody carries into the next bundle. `derived-from.json` records the
digest of `compose.effective.env` at derivation time; nothing re-verifies
it after an edit.

`DATABASE_URL` and `KEYCLOAK_CLIENT_SECRET` cannot move to OpenBao: the
backend reads them as plain settings at start-up, while OpenBao
(`SECRET_REGISTRY_DEFAULT_BACKEND=openbao`) only resolves the `secret://`
references of the secret registry, which needs the database first.

**Shell setup**, used by the procedures below:

```bash
ssh omnirag-demo
B=/srv/agentium-data/runtime-env/2026-10-12/runtime-env
sudo grep -E '^AGENTIUM_[A-Z_]*ENV_FILE=' "$B/compose.effective.env"   # paths only
TAG=$(docker inspect --format '{{.Config.Image}}' agentium-backend); TAG=${TAG##*:}
deploy() {
  sudo env AGENTIUM_IMAGE_TAG="$TAG" \
    AGENTIUM_ML_TS=1 AGENTIUM_ML_DEEP=1 AGENTIUM_HUGGINGFACE=1 AGENTIUM_OPENBAO=1 \
    /srv/agentium-data/worktrees/demo-agentic/scripts/agentium-vm-deploy.sh "$@"
}
```

`TAG` is the deployed `<sha12>`: `up` fails closed without a tag and, given
the running one, swaps no image. It recreates only the services whose
rendered configuration changed, so an edited env file recreates exactly
the services that load it. Keep the four flags as deployed: dropping one
removes its overlay, and `up` would recreate the backend without it.

**Checking that the copies agree.** This prints one line per copy with a
group letter, never a value or a digest. `pg` is the PostgreSQL `agentium`
password (URL-decoded from each `DATABASE_URL`, plus
`AGENTIUM_POSTGRES_PASSWORD` and `KC_DB_PASSWORD`), `kc` the Keycloak
client secret, `ai` the OpenAI API key. Pass a backup directory before `"$B"` to tell the old
value (`A`) from the new one (`B`):

```bash
sudo python3 - "$B" <<'PY'
import hashlib, pathlib, sys, urllib.parse
password = lambda url: urllib.parse.unquote(urllib.parse.urlsplit(url).password or "")
keys = {"DATABASE_URL": ("pg", password), "AGENTIUM_POSTGRES_PASSWORD": ("pg", str),
        "KC_DB_PASSWORD": ("pg", str), "KEYCLOAK_CLIENT_SECRET": ("kc", str),
        "OPENAI_API_KEY": ("ai", str)}
groups = {}
for directory in sys.argv[1:]:
    for path in sorted(pathlib.Path(directory).glob("*.env")):
        for line in path.read_text().splitlines():
            key, _, value = line.partition("=")
            if key in keys:
                kind, extract = keys[key]
                seen = groups.setdefault(kind, {})
                digest = hashlib.sha256(extract(value.strip().strip("'\"")).encode()).digest()
                print(kind, seen.setdefault(digest, chr(65 + len(seen))), f"{path}:{key}")
PY
```

On 2026-10-13 all nine `pg` copies, all four `kc` copies and all four
`ai` copies printed `A`, and every running container matched the bundle.

## Secret inventory

| Name | Where it's used | Storage on VM | Rotation cadence | Procedure |
| ---- | --------------- | ------------- | ---------------- | --------- |
| **Keycloak master admin** (`tib-admin`) | `kcadm.sh` login, `bootstrap-smtp.sh`, realm imports | Not persisted on VM | 180 j | `deploy/rotate-keycloak-admin.sh` |
| **Keycloak DB password** (`KC_DB_PASSWORD`) | Keycloak ↔ Postgres | `AGENTIUM_KEYCLOAK_ENV_FILE` (`source-003.env`); same value as the Postgres `agentium` password | 180 j | Section *PG rotation* below |
| **Postgres `agentium` password** (`POSTGRES_PASSWORD`) | Backend, workers, SFTP, Hub worker + Keycloak (shared user) | Database (authority) + bundle copies: `DATABASE_URL`, `AGENTIUM_POSTGRES_PASSWORD`, `KC_DB_PASSWORD` | 180 j | Section *PG rotation* below |
| **Keycloak client secret** (`KEYCLOAK_CLIENT_SECRET`) | Backend admin API as `core-resource-server` | `AGENTIUM_ENV_FILE` (`source-001.env`) | 180 j | Section *Keycloak client_secret* below |
| **SMTP** (`noreply@datategy.net`) | Keycloak realm SMTP (password reset), backend notifications | `AGENTIUM_ENV_FILE` (`SMTP_USER`, `SMTP_PASSWORD`) + Keycloak realm config | 180 j or on staff change | OVH Manager → Email → change password → update `AGENTIUM_ENV_FILE` (and its inert copies) + realm → `deploy up` |
| **OpenAI API key** | Backend LLM calls, judge service, voice API, realtime STT sidecar | `AGENTIUM_ENV_FILE` + `compose.effective.env` (`OPENAI_API_KEY`) | 90 j or on abuse alert | Section *OpenAI API key* below: `deploy up` for the backend and workers, `deploy livekit-up` for `agentium-livekit-agent`, which gets the key by interpolation from `compose.effective.env` |
| **Fernet key** (`SHAREPOINT_CONNECTOR_FERNET_KEY`) | Encrypt SharePoint session captures at rest | `AGENTIUM_ENV_FILE` | **Never rotate** — rotation invalidates every stored session, forcing operators to re-capture OTP. Only regenerate if a key compromise is suspected. | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| **JWT signing keys** (Keycloak realm) | Token signing for `papai-org` realm | Keycloak DB | On suspected compromise | Admin console → Realm settings → Keys → Re-generate + Archive old |
| **Secret registry key** (`SECRET_REGISTRY_FERNET_KEY`) | Encrypts `db`-backend secrets of the registry (connector tokens, SMTP, flow secrets) | Runtime env bundle | **Never rotate in place** — every `secret_versions.ciphertext` depends on it. Falls back to `CONNECTOR_SECRETS_FERNET_KEY` when unset. | Generate like the Fernet key above; see [agentium-secret-registry.md](../agentium-secret-registry.md) |
| **OpenBao unseal key** (`openbao-unseal.key`) | Static auto-unseal of `agentium-openbao` (`AGENTIUM_OPENBAO=1`) | `<deployment>/runtime-env/` (0400) | Never — snapshots are sealed with it | Created by `agentium-vm-deploy.sh openbao-prepare`; copy off-VM to the vault |
| **OpenBao recovery key** (`openbao-recovery.env`) | `bao operator generate-root` for reconfiguration and restore | `<deployment>/runtime-env/` (0600) | On suspected compromise | Created by `openbao-init`; copy off-VM to the vault |
| **OpenBao AppRole credentials** (`openbao-{backend,worker,hub-fetch,snapshot}.env`) | Backend/migrate, workers, Hub downloader (read-only on `<scope>/<owner>/nodes/*`: serving-node and HF tokens), snapshot cron | `<deployment>/runtime-env/` (0600) | 180 j | Regenerate root token, `agentium_openbao_bootstrap.py configure` |

Application secrets (connector tokens, API keys, SMTP passwords of
connectors, flow secrets) no longer belong in `.env`: they live in the
**secret registry** and configurations hold `secret://…` references. See
[agentium-secret-registry.md](../agentium-secret-registry.md) for the model,
the connector migration script and OpenBao operations (deploy order,
snapshot/restore, unseal key limitation).

## Vault conventions

Whatever you use (1Password, Bitwarden, Vault, a pass-store under
git-crypt), stick to this shape so anyone can locate a secret without
a screenshare :

```text
agentium-prod/
├── keycloak/
│   ├── master-admin       (username + password + URL + rotated_at)
│   ├── db-password        (value + rotated_at)
│   └── realm-smtp-pw      (value + rotated_at)
├── postgres/
│   └── agentium-pw        (value + rotated_at + "shared with Keycloak")
├── openai/
│   └── api-key            (value + rotated_at + usage_limit_usd)
├── smtp-ovh/
│   └── noreply-pw         (value + rotated_at)
├── fernet/
│   ├── sharepoint-key     (value + generated_at + "DO NOT ROTATE LIGHTLY")
│   └── secret-registry    (value + generated_at + "DO NOT ROTATE LIGHTLY")
└── openbao/
    ├── unseal-key         (value + generated_at + "required to restore snapshots")
    └── recovery-key       (value + generated_at)
```

The OpenBao unseal and recovery keys sit on the VM next to the raft data
(single-host limitation, no external KMS). The vault copy is what makes a
restore possible after losing the VM; keep it apart from the snapshots.

Each record carries a `rotated_at` date. Anyone looking at the vault
3 months after the fact should be able to answer "is this stale?" in
one glance.

## Postgres password rotation procedure

**Risk.** One role, `agentium` (superuser), serves the backend, every
worker, the SFTP server, the Hub worker and Keycloak. PostgreSQL checks
the password only when a connection opens: once it changes, open
connections keep working, but every new one from a container that still
carries the old value fails (the backend pool recycles its connections
every 5 min). Keep that window short: edit the bundle first (nothing
reads it until a recreate), change the password in the database, then
recreate every client right away. No data loss. While
`COLLECTION_ACCESS_SIGNING_KEY` is unset (the case on 2026-10-13), the
retrieval-identity signing key is derived from `DATABASE_URL`: an identity
signed before the switch no longer verifies after it, so rerun the deep
retrievals in flight. Lost both passwords? `docker exec -it agentium-pg
psql -U agentium -d agentium` goes through the container's Unix socket,
which `pg_hba.conf` trusts (`local all all trust`); there is no
`postgres` role.

1. **Generate the new password** in your vault's password generator and
   save it there before anything else. Use 32+ characters from
   `[A-Za-z0-9]`: such a value needs no URL-encoding in `DATABASE_URL`
   and contains nothing Compose interpolates or dotenv parses. If you keep
   other characters, percent-encode them inside each `DATABASE_URL` only
   (`@` → `%40`, `:` → `%3A`, `/` → `%2F`, `%` → `%25`) and put the raw
   value in `AGENTIUM_POSTGRES_PASSWORD` and `KC_DB_PASSWORD`; never use
   `$`, quotes, `#` or whitespace.
2. **Back up the bundle copies** (shell setup from *Runtime env bundle on
   the VM*):

   ```bash
   BACKUP=/root/pg-rotation-$(date +%F)
   sudo install -d -m 0700 "$BACKUP"
   sudo cp -p "$B"/{source-001.env,huggingface-worker.env,source-003.env,compose.effective.env,source-000.env,source-004.env} "$BACKUP"/
   ```

3. **Edit every copy with `sudoedit`** (never `sed`, `echo` or a heredoc
   carrying the value):

   ```bash
   sudoedit "$B/source-001.env" "$B/huggingface-worker.env" "$B/source-003.env" \
     "$B/compose.effective.env" "$B/source-000.env" "$B/source-004.env"
   ```

   | File | Keys | Read by |
   | ---- | ---- | ------- |
   | `source-001.env` | `DATABASE_URL`, `AGENTIUM_POSTGRES_PASSWORD` | Backend, migrate, workers, beat, p4-maintenance, SFTP |
   | `huggingface-worker.env` | `DATABASE_URL` | Hub worker |
   | `source-003.env` | `KC_DB_PASSWORD` | Keycloak |
   | `compose.effective.env` | `AGENTIUM_POSTGRES_PASSWORD`, `DATABASE_URL` | `agentium-pg` interpolation (only initialises an empty volume); nothing |
   | `source-000.env` | `DATABASE_URL`, `AGENTIUM_POSTGRES_PASSWORD` | Nothing (provenance) |
   | `source-004.env` | `DATABASE_URL` (on `localhost`) | Nothing (provenance) |

   Only the password segment of each URL changes
   (`postgresql://agentium:<new>@…`). Then run the copy check with
   `"$BACKUP" "$B"`: all nine `pg` lines under `$B` must share one
   letter, different from the backup's.

4. **Change it in the database.** psql's `\password` prompts twice and
   sends only a SCRAM verifier: the value never reaches the shell
   history, `ps` or the server log.

   ```bash
   docker exec -it agentium-pg psql -U agentium -d agentium -c '\password agentium'
   ```

5. **Recreate every client right away:**

   ```bash
   deploy up            # backend, cpu/recipes/ML workers, beat, p4-maintenance, Hub worker
   deploy keycloak-up   # agentium-kc
   deploy sftp-up       # agentium-sftp
   ```

   `up` recreates the services whose environment changed (the frontend
   and OpenBao stay as they are), waits for the backend's build-info to
   report `$TAG` with `revision_verified`, and records the run in the
   deployment journal. `keycloak-up` runs the storage check, then
   `compose --profile infra up --force-recreate --wait agentium-kc`: same
   `127.0.0.1` port binding, healthcheck, `agentium-net` network,
   read-only theme/realm mounts and `unless-stopped` policy as every
   other Compose render, and it returns only once the healthcheck
   passes. (It replaces the `deploy/redeploy-keycloak` script, retired
   on 2026-10-13: it recreated the container with `docker run`,
   published `0.0.0.0:8080` and dropped the healthcheck.) `sftp-up`
   recreates the SFTP server from its digest-pinned image: it sits
   outside `up`, yet opens a database session for every login.
   `agentium-migrate` is a one-off container that reads the new file at
   its next run; `agentium-pg` is not recreated.

6. **Verify** (each command prints a status, never a credential):

   ```bash
   curl -s https://agentium.papai.ai/api/v1/health/ready \
     | python3 -c 'import json, sys; print(json.load(sys.stdin)["checks"]["database"])'   # {'status': 'ok'}
   curl -s https://agentium.papai.ai/api/v1/build-info   # revision starts with $TAG, "revision_verified": true
   curl -s -o /dev/null -w '%{http_code}\n' https://agentium.papai.ai/kc/realms/papai-org   # 200
   docker logs --since 10m agentium-pg 2>&1 | grep -c 'password authentication failed'   # 0
   deploy ps   # every client above shows a fresh "Up" time
   ```

   `/api/v1/health/ready` runs a `select 1` through the freshly created
   pool. A non-zero count means a client still carries the old value:
   rerun the copy check.

7. **Record in the vault :** update `agentium-prod/postgres/agentium-pw`
   and `agentium-prod/keycloak/db-password` (same value) `value` +
   `rotated_at`.

**Rollback.** A client failing after step 5 almost always means one copy
is wrong (a typo, an unencoded character): rerun the copy check, fix the
copy that differs with `sudoedit`, and rerun the command that recreates
its reader (`up`, `keycloak-up` or `sftp-up`). To return to the previous
password: `sudo sh -c 'cp -p "$1"/*.env "$2"/' _ "$BACKUP" "$B"` (the
glob has to expand as root), set the previous value from
the vault's history with step 4's `\password`, then rerun the three
commands of step 5. Step 4 is instantaneous and cannot be undone without
a password in hand, so **never run step 4 before step 1 has saved the
new value to the vault**; the trusted socket login of the Risk paragraph
is the last resort.

## Keycloak client_secret (`core-resource-server`)

The backend **can** authenticate to Keycloak's admin REST API as
`core-resource-server` (confidential client) via
`client_credentials` grant to perform administrative operations on
behalf of the end user :

- Signup endpoint (`POST /auth/signup`) — creates a user in the realm.
- Programmatic password reset (`POST /auth/reset-password`) — sends
  the Keycloak-native reset email without the user having to click
  "Forgot password ?" on the login screen.
- User management (promote to workspace admin, etc.).

These paths all route through ``_get_admin_token`` in
`backend/app/api/v1/endpoints/auth.py`, which is **guarded by a
`settings.keycloak_client_secret` presence check**: if the env var
is unset, the admin token request is skipped and the endpoint
returns 503 with a clear log line. Login, token refresh, token
validation, and the realm-native "Forgot password ?" link on the
Keycloak page all keep working **without** this secret (they use
the public validation flow and the realm SMTP config directly).

The backend authenticates as `KEYCLOAK_RESOURCE_SERVER_ID`
(`core-resource-server`); `KEYCLOAK_CLIENT_ID` (`core-service`) is the
public login client and has no secret.

**Current state on `omnirag-demo` (2026-10-13) :** the secret is
**set** in `AGENTIUM_ENV_FILE` (`source-001.env`), so the admin API is
enabled. `compose.effective.env`, `source-000.env` and `source-004.env`
hold inert copies of the same value (the `kc` lines of the copy check).

Rotate it every 180 j like the other creds, or immediately on
suspected leak. The old secret is invalidated the moment the new
one is generated — there is no parallel-validity window in
Keycloak — so run steps 2 to 4 together:

1. **Back up the copies** (shell setup from *Runtime env bundle on the
   VM*):

   ```bash
   BACKUP=/root/kc-client-rotation-$(date +%F)
   sudo install -d -m 0700 "$BACKUP"
   sudo cp -p "$B"/{source-001.env,compose.effective.env,source-000.env,source-004.env} "$BACKUP"/
   ```

2. Admin console → Clients → `core-resource-server` → Credentials
   tab → "Regenerate secret". Paste the value straight into the vault.
   From here on, backend admin calls answer 503 until step 4.
3. **Edit the copies with `sudoedit`** (never `sed` or `echo`):

   ```bash
   sudoedit "$B/source-001.env" "$B/compose.effective.env" "$B/source-000.env" "$B/source-004.env"
   ```

   Set `KEYCLOAK_CLIENT_SECRET=<value>`: `source-001.env` is the copy the
   backend reads, the other three are the inert copies. Run the copy check
   with `"$BACKUP" "$B"`: all four `kc` lines under `$B` must share one
   letter, different from the backup's.
4. **Recreate the backend:** `deploy up`. It recreates every
   `AGENTIUM_ENV_FILE` service (only the backend calls the admin API) and
   proves build-info. `agentium-sftp` carries the variable too but never
   calls the admin API; it picks the new value up at its next `sftp-up`.
5. **Verify:** the health and build-info checks of the Postgres
   procedure's step 6, then exercise one admin path (e.g.
   `POST /auth/reset-password` for a test account) and check that
   `docker logs --since 10m agentium-backend 2>&1 | grep -cE 'Admin token request returned|Failed to get admin token|client_secret not configured'`
   prints `0`.
6. **Record in the vault:** `rotated_at`.

**Rollback.** Keycloak keeps no previous secret: the one replaced in
step 2 is gone for good. If the backend still fails, its copy in
`source-001.env` is wrong: fix it and rerun `deploy up`. Regenerating
again and repeating steps 3 and 4 is the only other way out; the backup
only protects the rest of those files from a bad edit.

## OpenAI API key

The backend and its workers read `OPENAI_API_KEY` from
`AGENTIUM_ENV_FILE` (`source-001.env`); the realtime STT sidecar
`agentium-livekit-agent` gets it by interpolation from
`compose.effective.env`. `source-000.env` and `source-004.env` hold inert
copies (the four `ai` lines of the copy check). OpenAI keeps the old key
valid until it is revoked, so recreate every reader first and revoke last:

1. **Create a new key** at `platform.openai.com/api-keys` and paste it
   straight into the vault.
2. **Back up the copies** (shell setup from *Runtime env bundle on the
   VM*):

   ```bash
   BACKUP=/root/openai-rotation-$(date +%F)
   sudo install -d -m 0700 "$BACKUP"
   sudo cp -p "$B"/{source-001.env,compose.effective.env,source-000.env,source-004.env} "$BACKUP"/
   ```

3. **Edit the copies with `sudoedit`** (never `sed` or `echo`), then run
   the copy check with `"$BACKUP" "$B"`: the four `ai` lines under `$B`
   must share one letter, different from the backup's.

   ```bash
   sudoedit "$B/source-001.env" "$B/compose.effective.env" "$B/source-000.env" "$B/source-004.env"
   ```

4. **Recreate the readers:**

   ```bash
   deploy up   # backend and workers
   docker exec agentium-livekit-agent node -e "fetch('http://127.0.0.1:8090/healthz').then(r=>r.json()).then(b=>console.log(b.active_sessions))"   # 0, else wait for the call to end
   LK=$(docker inspect --format '{{.Config.Image}}' agentium-livekit-agent)
   TAG="${LK##*:}" deploy livekit-up   # the sidecar keeps its image, takes the new key
   ```

   `livekit-up` runs the storage check, then
   `compose --profile realtime up --wait` on `agentium-livekit` and
   `agentium-livekit-agent`: Compose recreates only the one whose rendered
   configuration changed (here the sidecar) and returns once it is
   healthy. A recreated sidecar drops its live sessions, hence the
   `active_sessions` check. `TAG` is the sidecar's own `<sha12>` so its
   image does not change; shipping new sidecar code is a release step
   (deploy runbook).
5. **Verify:** the health and build-info checks of the Postgres
   procedure's step 6, and
   `docker inspect -f '{{.State.Health.Status}} {{.HostConfig.RestartPolicy.Name}}' agentium-livekit-agent`
   prints `healthy unless-stopped`.
6. **Revoke the old key** in the OpenAI dashboard, then record
   `rotated_at` in the vault.

**Rollback.** Until step 6 the old key still works: copy the backup back
(`sudo sh -c 'cp -p "$1"/*.env "$2"/' _ "$BACKUP" "$B"`) and rerun step 4.

## DKIM / SPF / DMARC

Separate runbook at [`email-deliverability.md`](./email-deliverability.md).
The DKIM private key lives **inside OVH's infra** (they sign the
outbound mail on your behalf) — we don't store any material in the
vault; only the selector name + activation date, for auditability.

## Secret rotation schedule

| Quarter | Action |
| ------- | ------ |
| Q1 | Rotate `tib-admin`, SMTP password, PG password |
| Q2 | Rotate OpenAI API key, re-check DKIM signature alignment |
| Q3 | Rotate `tib-admin`, SMTP password, PG password |
| Q4 | Rotate OpenAI API key, re-check SPF/DMARC records |

Any security incident (suspected leak, stolen laptop, departed staff
with access) triggers an immediate out-of-schedule rotation of
whatever the person could have seen.

## When a secret leaks

1. **Rotate first, investigate second.** Always. Every minute a leaked
   secret stays valid is an uncapped risk.
2. Check the corresponding service's audit log for anomalous usage
   since the suspected leak time (Keycloak events, OpenAI dashboard
   usage graph, Postgres `pg_stat_activity`, etc.).
3. File a `Decision` in the Hypervisor (`kind="security_incident"`)
   so the leak is tracked against the audit trail the same way any
   other ops event is.
4. Update this document's *rotated_at* line for the relevant secret
   and note the rotation reason (e.g. "post-leak 2026-04-24").

## References

- [`keycloak-admin.md`](./keycloak-admin.md) — master admin rotation
- [`email-deliverability.md`](./email-deliverability.md) — SMTP, DKIM, DMARC
- [`../agentium-secret-registry.md`](../agentium-secret-registry.md) — secret
  registry, flow `secret` node, connector migration, OpenBao
- `deploy/rotate-keycloak-admin.sh` — master admin CLI
- `scripts/agentium-vm-deploy.sh up` / `keycloak-up` / `sftp-up` /
  `livekit-up` — recreate the application services, `agentium-kc`,
  `agentium-sftp` and LiveKit with its sidecar through the worktree
  Compose with the frozen bundle
- `scripts/agentium_runtime_env_bundle.py` — bundle contract (which copies
  must agree)
- `backend/keycloak/keycloak.env` + `docker/test_env_files/keycloak.env`
  — dev placeholders, never populated with real creds in-repo
