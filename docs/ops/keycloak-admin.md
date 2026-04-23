# Keycloak master-realm admin — runbook

## Context

The Keycloak container on `omnirag-demo` is started with
`KC_BOOTSTRAP_ADMIN_USERNAME=admin` / `KC_BOOTSTRAP_ADMIN_PASSWORD=admin`.
That bootstrap user is only inserted **on the first boot against an
empty PostgreSQL schema**. Because our DB volume (`agentium_pgdata`)
is persistent, those defaults stay in the DB forever unless we
actively rotate them.

Agentium's prod backend never uses `admin/admin` at runtime — it
uses `client_credentials` through the `core-resource-server`
confidential client (realm `papai-org`). The master-realm admin is
only used for:

- logging into `https://agentium.papai.ai/kc/admin/master/console/`
- running `backend/keycloak/bootstrap-smtp.sh` after a realm rebuild
- running `backend/scripts/seed_keycloak_users.sh` after a realm rebuild
- any `kcadm.sh`-level maintenance by an operator

All of those now **require** `KC_ADMIN` + `KC_ADMIN_PASSWORD` (no
defaults) so a misconfigured env fails loudly.

## Current admins

| user        | scope         | notes                                              |
| ----------- | ------------- | -------------------------------------------------- |
| `admin`     | master realm  | **bootstrap** — disabled after rotation (below)    |
| `tib-admin` | master realm  | operator, password in the team's secret manager    |

## Rotation

The rotation script is `deploy/rotate-keycloak-admin.sh`. It runs in
two independent steps so a failure on step 2 doesn't lock us out.

### Step 1 — create and verify the new admin

```bash
# On the VM:
scp deploy/rotate-keycloak-admin.sh omnirag-demo:/tmp/
ssh omnirag-demo 'chmod +x /tmp/rotate-keycloak-admin.sh'
ssh omnirag-demo env \
  NEW_ADMIN_USER=tib-admin \
  NEW_ADMIN_PASSWORD='<from-secret-manager>' \
  /tmp/rotate-keycloak-admin.sh
```

The script:

1. Authenticates with the **bootstrap** admin (`BOOT_ADMIN=admin` /
   `BOOT_PASSWORD=admin` by default — overridable).
2. Creates or locates the new user in realm `master`, sets a
   non-temporary password, and grants the `admin` role.
3. Verifies the new admin can obtain a token via
   `/realms/master/protocol/openid-connect/token`.

If step 3 fails, the script exits non-zero **before** touching the
bootstrap user. You can still log in as `admin/admin` and investigate.

### Visual check

Open `https://agentium.papai.ai/kc/admin/master/console/` in an
incognito window and log in with the new credentials. Everything
should look identical to the bootstrap admin's view.

### Step 2 — disable the bootstrap user

Only after step 1 and the visual check:

```bash
ssh omnirag-demo env \
  NEW_ADMIN_USER=tib-admin \
  NEW_ADMIN_PASSWORD='<from-secret-manager>' \
  /tmp/rotate-keycloak-admin.sh --disable-bootstrap
```

Step 2 uses the **new** admin's token to `PUT users/<bootstrap-id> -d '{"enabled":false}'`.
The row stays in the DB (so no replication surprises) but
`admin/admin` logins will be rejected.

### Rollback

If the new admin is ever lost and the bootstrap user has been
disabled:

```bash
# 1. Create a temporary admin using a freshly-started KC container
#    with --import-realm and a different DB (painful).
# 2. OR: reset the enabled flag directly in PG:
docker exec -it agentium-pg \
  psql -U agentium -d keycloak \
  -c "UPDATE user_entity SET enabled = true WHERE username = 'admin';"
# Then log in, rotate, disable again.
```

## Wiring infra to the new admin

After rotation, every script that used to default to `admin/admin`
now requires explicit env vars:

- `backend/keycloak/bootstrap-smtp.sh` — needs `KC_ADMIN` + `KC_ADMIN_PASSWORD`
- `backend/scripts/seed_keycloak_users.sh` — needs `KC_ADMIN_USER` + `KC_ADMIN_PASS`
- `deploy/rotate-keycloak-admin.sh` — if you ever re-run it, pass
  `BOOT_ADMIN=tib-admin` and `BOOT_PASSWORD=...` explicitly

The operator secret-file convention on the VM is:

```
/etc/agentium/kc-admin.env   (mode 600, owner root)
  KC_ADMIN=tib-admin
  KC_ADMIN_PASSWORD=<from-secret-manager>
```

Then any script that needs admin creds just runs with:

```bash
set -a; source /etc/agentium/kc-admin.env; set +a
./path/to/script.sh
```

## What we did NOT change

- The `KC_BOOTSTRAP_ADMIN_*` env vars in
  `backend/keycloak/keycloak.env` remain `admin`. That file is the
  Docker env applied when the container starts — but bootstrap only
  inserts if the DB is empty, which will never happen again for this
  cluster. We keep the file matching the initial install for
  reproducibility; a rotated cluster is independent of it.
- `run.sh` and `docker/test_env_files/keycloak.env` remain with
  `admin/admin`: those are **local dev only** (spawning a disposable
  KC container against a fresh DB), so strong creds aren't worth the
  friction. If you spin up a dev env that will be exposed, rotate
  using the same script.

## Related

- `docs/ops/email-deliverability.md` — where `SMTP_USER` /
  `SMTP_PASSWORD` get wired in alongside `KC_ADMIN` / `KC_ADMIN_PASSWORD`.
- `deploy/redeploy-keycloak.sh` — recreates the container; does not
  touch the DB, so the rotated admin survives.
