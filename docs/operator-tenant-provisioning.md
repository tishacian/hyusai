# Operator — Provision a new tenant

Runbook for onboarding a new customer tenant on Agentium. Two personas
interact with the stack during onboarding:

- **Operator** (you). Has Keycloak `master` admin access and shell
  access to the VM hosting the stack.
- **Tenant owner** (the customer). Will receive the invitation email,
  set their password, and become the workspace owner.

This playbook assumes the deployment topology documented in
[`docs/vague-d-plan.md`](./vague-d-plan.md) (Keycloak + backend +
frontend on one VM, reverse-proxy terminating TLS).

---

## 0. Prerequisites checklist

- [ ] Keycloak container is healthy — `docker compose ps keycloak` shows
      `running`, and `GET ${KEYCLOAK_URL}/realms/agentium/.well-known/openid-configuration`
      returns 200.
- [ ] Backend container is healthy — `GET ${BACKEND_URL}/api/v1/health`
      returns 200.
- [ ] Realm `agentium` is loaded with the `agentium-backend` resource
      server and the `agentium-frontend` public client (see
      [`backend/keycloak/realm-export.json`](../backend/keycloak/realm-export.json)).
- [ ] SMTP is configured on the realm so invitation emails are actually
      delivered (Keycloak admin UI → Realm settings → Email).

---

## 1. Self-service onboarding (recommended)

This is the happy path once you have at least one tenant with an
admin who can invite teammates.

1. **Tenant owner** hits the frontend (`https://agentium.papai.ai`).
2. Signs up via `/auth/signup` — this calls `POST /api/v1/auth/signup`
   which provisions a new Keycloak user and a local `User` row.
3. After the email is verified, the tenant owner creates a workspace
   via `POST /api/v1/auth/workspaces` (cockpit surface: the workspace
   picker in the title bar). They become `owner` of that workspace.
4. From **Workspace → Members** they `Invite teammate` by email. The
   backend auto-provisions the invitee in Keycloak with
   `UPDATE_PASSWORD` + `VERIFY_EMAIL` required actions and Keycloak
   sends the onboarding email.
5. The teammate clicks the link, sets a password, logs in, and sees
   the invited workspace listed in their switcher.

No operator intervention required — this is the intended mode.

---

## 2. Operator-driven onboarding (VIP / pre-sales)

For enterprise POCs where you want to hand the customer pre-created
credentials on a plate:

### 2.1 Create the Keycloak user

```bash
# Get an admin token (assuming the resource-server client has admin API access)
TOKEN=$(curl -sS \
  -d "grant_type=client_credentials" \
  -d "client_id=agentium-backend" \
  -d "client_secret=${KC_CLIENT_SECRET}" \
  "${KEYCLOAK_URL}/realms/agentium/protocol/openid-connect/token" \
  | jq -r .access_token)

curl -sS -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "${KEYCLOAK_URL}/admin/realms/agentium/users" \
  -d '{
    "username": "owner@customer.com",
    "email":    "owner@customer.com",
    "enabled":  true,
    "emailVerified": false,
    "firstName": "Customer",
    "lastName":  "Owner",
    "requiredActions": ["UPDATE_PASSWORD", "VERIFY_EMAIL"]
  }'
```

### 2.2 Trigger the onboarding email

Grab the new user id from the `Location` header of the previous call,
then:

```bash
curl -sS -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "${KEYCLOAK_URL}/admin/realms/agentium/users/${KC_USER_ID}/execute-actions-email" \
  -d '["UPDATE_PASSWORD", "VERIFY_EMAIL"]'
```

The customer receives an email with a single-use link to set their
password. They log in and land on the onboarding flow, same as
self-service.

### 2.3 Pre-create the workspace (optional)

If you want the workspace to already exist on day 1 (e.g. branded
slug, pre-populated presets, demo data), log in once on the customer's
behalf after they set their password, or ask them to create it
themselves from the cockpit. The backend does **not** let an operator
create a workspace on behalf of someone else without logging in as
that user — this is intentional to preserve the "owner = real human"
invariant.

---

## 3. Revoking / offboarding

- **Remove teammate from a workspace**: the owner or an admin clicks
  `Remove` in `Workspace → Members`. This deletes the `WorkspaceMember`
  row; the underlying `User` and Keycloak account are untouched so
  they keep access to their other workspaces.
- **Disable a tenant entirely**: from Keycloak admin UI, toggle
  `Enabled: false` on every `User` associated to that tenant. Optional:
  also disable the workspace rows in the backend DB
  (`UPDATE workspaces SET is_active = false WHERE id = …`).

---

## 4. Isolation smoke test

After onboarding a new tenant, run the automated isolation test on the
VM to confirm nothing leaks:

```bash
BACKEND_URL=https://agentium.papai.ai \
KEYCLOAK_URL=https://auth.agentium.papai.ai \
CLIENT_SECRET=${KC_CLIENT_SECRET} \
ALICE_USER=owner@new-tenant.com ALICE_PASS=... \
BOB_USER=admin@agentium.local   BOB_PASS=... \
./backend/scripts/test_tenant_isolation.sh
```

A successful run prints `N pass / 0 fail`. Any failure is a blocker —
investigate before handing the tenant their login.

---

## 5. Backup & restore

- Keycloak realm state is persisted in the `keycloak-db` volume. Back
  it up with the standard Postgres dump cadence.
- Agentium application data lives in the backend's Postgres; every
  tenant's data is scoped by `workspace_id` so a single logical DB
  holds all tenants. Row-level backups are out of scope for D1.
- To move a tenant between environments: dump only that tenant's rows
  via `workspace_id` filters (see `docs/vague-d-plan.md` for the model
  inventory) and replay the Keycloak user representations.

---

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Invitation email never arrives | SMTP mis-configured on the realm | Keycloak → Realm settings → Email, click "Test connection". |
| Customer can log in but sees no workspace | They haven't been added as a member yet | Either they create one (`POST /auth/workspaces`) or an admin invites them into an existing one. |
| Isolation test fails on `systems` | A new endpoint was added without `get_current_workspace` | Grep `@router\.` in the file and add the dependency. |
| `create_system` returns 403 | Token has no `workspace_id` claim | Confirm the `X-Workspace-Slug` header is set, or that the user is a member of the targeted workspace. |
