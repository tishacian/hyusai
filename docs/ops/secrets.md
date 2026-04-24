# Agentium — secrets runbook

Where every secret lives, how it gets rotated, and what breaks if you
mess it up. Agnostic of the vault you actually use — the convention
is "one record per secret, tagged `agentium-prod` or `agentium-dev`".

## Scope

This document covers the **prod `omnirag-demo`** VM (`agentium.papai.ai`).
Dev laptops use local `.env` files checked against `docker/test_env_files/`
with placeholders — never production secrets.

## Secret inventory

| Name | Where it's used | Storage on VM | Rotation cadence | Procedure |
| ---- | --------------- | ------------- | ---------------- | --------- |
| **Keycloak master admin** (`tib-admin`) | `kcadm.sh` login, `bootstrap-smtp.sh`, realm imports | Not persisted on VM | 180 j | `deploy/rotate-keycloak-admin.sh` |
| **Keycloak DB password** (`KC_DB_PASSWORD`) | Keycloak ↔ Postgres | `docker inspect agentium-kc` env | 180 j | Section *PG rotation* below |
| **Postgres `agentium` password** (`POSTGRES_PASSWORD`) | Backend + Keycloak (shared user) | `docker inspect agentium-pg` env + `backend/.env` `DATABASE_URL` | 180 j | Section *PG rotation* below |
| **SMTP** (`noreply@datategy.net`) | Keycloak realm SMTP (password reset), backend notifications | `backend/.env` + Keycloak realm config | 180 j or on staff change | OVH Manager → Email → change password → update `backend/.env` + realm |
| **OpenAI API key** | Backend LLM calls, judge service, voice API | `backend/.env` (`OPENAI_API_KEY`) | 90 j or on abuse alert | `platform.openai.com/api-keys` → rotate → update `backend/.env` → restart |
| **Fernet key** (`SHAREPOINT_CONNECTOR_FERNET_KEY`) | Encrypt SharePoint session captures at rest | `backend/.env` | **Never rotate** — rotation invalidates every stored session, forcing operators to re-capture OTP. Only regenerate if a key compromise is suspected. | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| **JWT signing keys** (Keycloak realm) | Token signing for `papai-org` realm | Keycloak DB | On suspected compromise | Admin console → Realm settings → Keys → Re-generate + Archive old |

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
└── fernet/
    └── sharepoint-key     (value + generated_at + "DO NOT ROTATE LIGHTLY")
```

Each record carries a `rotated_at` date. Anyone looking at the vault
3 months after the fact should be able to answer "is this stale?" in
one glance.

## Postgres password rotation procedure

**Risk.** 30 s of downtime on backend + Keycloak while containers
reconnect. No data loss. **Never attempt without** the current PG
password in hand, or a fallback plan via `docker exec agentium-pg
psql -U postgres` (the super-user login remains valid under
`POSTGRES_USER=postgres`'s default password from the initial volume
bootstrap).

1. **Generate the new password** locally (or in your vault's password
   generator). 24+ chars, alphanumeric + symbols that don't break a
   URL (avoid `#`, `@`, `:` which collide with `DATABASE_URL`
   parsing unless URL-encoded).
2. **Apply on the DB :**

   ```bash
   ssh omnirag-demo
   docker exec -i agentium-pg psql -U agentium -d agentium <<SQL
   ALTER USER agentium WITH PASSWORD '<new>';
   SQL
   ```

3. **Update `backend/.env` on the VM :**

   ```bash
   sudo sed -i "s|DATABASE_URL=postgresql://agentium:[^@]*@|DATABASE_URL=postgresql://agentium:<new>@|" /home/ubuntu/omnirag/backend/.env
   ```

4. **Update Keycloak env** (inject the new password on next redeploy) :

   ```bash
   cd /home/ubuntu/omnirag/deploy
   sudo KC_DB_PASSWORD='<new>' ./redeploy-keycloak.sh
   ```

   The redeploy script filters `KC_BOOTSTRAP_ADMIN_*` automatically
   since Vague E / E0, so the new container won't carry stale creds.

5. **Restart the backend :**

   ```bash
   sudo systemctl restart agentium-backend
   ```

6. **Verify :**

   ```bash
   curl -s -o /dev/null -w '%{http_code}' https://agentium.papai.ai/api/v1/health
   curl -s -o /dev/null -w '%{http_code}' https://agentium.papai.ai/kc/health/ready
   ```

7. **Record in the vault :** update `agentium-prod/postgres/agentium-pw`
   `value` + `rotated_at`.

**Rollback.** If the backend fails to connect : the previous value is
still in the vault's history. Revert step 3, restart backend. Step 2's
change is instantaneous and non-reversible without the old password,
so **never commit step 2 before step 1 has produced a value you've
saved to the vault**.

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

**Current state on `omnirag-demo` (2026-04-24) :** the secret is
**unset** — admin API is intentionally disabled in prod until a
first client actually needs backend-driven signup. Enabling it is
a 3-step task :

1. Admin console → Clients → `core-resource-server` → Credentials
   tab → "Regenerate secret". Copy the value.
2. `sudo sed -i '$a KEYCLOAK_CLIENT_SECRET=<value>'
   /home/ubuntu/omnirag/backend/.env` (or edit by hand).
3. `sudo systemctl restart agentium-backend`.

Rotate it every 180 j like the other creds, or immediately on
suspected leak. The old secret is invalidated the moment the new
one is generated — there is no parallel-validity window in
Keycloak. Coordinate with a backend bounce.

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
- `deploy/rotate-keycloak-admin.sh` — master admin CLI
- `deploy/redeploy-keycloak.sh` — rebuilds `agentium-kc` with current env
  (filters out `KC_BOOTSTRAP_ADMIN_*` since Vague E / E0)
- `backend/keycloak/keycloak.env` + `docker/test_env_files/keycloak.env`
  — dev placeholders, never populated with real creds in-repo
