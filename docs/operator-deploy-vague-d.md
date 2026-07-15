# Operator runbook — Deploy Vague D on the VM

Mirror of the C11 deploy procedure, extended with the new surfaces
introduced by Vague D (chat workspace, streaming tokens, i18n, light
theme, multi-tenant hardening, integration tests). Target host:
`agentium.papai.ai` (same topology as C11: FastAPI via uvicorn behind
nginx; SPA served by FastAPI catch-all from `frontend/`).

> **TL;DR** — build the SPA locally (or in CI), rsync `dist/` to the
> VM's `frontend/` directory, bounce uvicorn, then run
> `backend/scripts/smoke_vague_d.sh` from your laptop pointing at the
> public URL. All four tiers of the smoke must pass before announcing
> the deploy.

## 0. Pre-flight (once per deploy)

- [ ] Local `main` is clean and fast-forwarded to the latest D7 commit.
- [ ] `docs/vague-d-plan.md` shows every D0-D6 task as `COMPLETED`.
- [ ] Backend tests pass locally:
      ```bash
      cd backend && python -m pytest app/tests/services/ -q
      ```
- [ ] Frontend type-check is clean:
      ```bash
      cd frontend-ng && npx tsc --noEmit
      ```
- [ ] Keycloak realm export on the VM contains the demo users
      (`alice@acme.test`, `bob@globex.test`) — see
      `backend/keycloak/realm-export.json`.

## 1. Build the SPA

Locally (or in CI — the VM's Node is too old):

```bash
cd frontend-ng
npm ci
npx ng build -c production
# ⇒ dist/frontend-ng/browser/
```

Sanity-check the bundle **before** shipping it:

```bash
ls dist/frontend-ng/browser/ | wc -l      # expect ~30-60 files
grep -l 'data-theme="light"' dist/frontend-ng/browser/*.css  # D4 tokens
grep -l 'Rechercher'          dist/frontend-ng/browser/*.js   # D3 FR dict
grep -l 'chat-workspace'       dist/frontend-ng/browser/*.js  # D0 chunk
```

All three greps must return at least one file.

## 2. Push to the VM

```bash
# From the repo root
rsync -az --delete \
  frontend-ng/dist/frontend-ng/browser/ \
  deploy@agentium.papai.ai:/srv/agentium/frontend/

# Push backend changes (run the canonical migration script)
ssh deploy@agentium.papai.ai <<'SSH'
  set -euo pipefail
  cd /srv/agentium/omnirag
  git fetch origin main
  git reset --hard origin/main
  source .venv/bin/activate
  pip install -q -r backend/requirements.txt
  alembic -c backend/alembic.ini upgrade head     # picks up 010_context_ephemeral
SSH
```

## 3. Bounce uvicorn

The VM uses a plain `systemd` unit. If you renamed it, adjust the
service name below.

```bash
ssh deploy@agentium.papai.ai 'sudo systemctl restart agentium-backend'
ssh deploy@agentium.papai.ai 'sudo systemctl status agentium-backend --no-pager'
```

Fallback (no systemd) — same pattern as C11:

```bash
ssh deploy@agentium.papai.ai <<'SSH'
  pkill -f 'uvicorn app.main:app' || true
  cd /srv/agentium/omnirag/backend
  nohup .venv/bin/uvicorn app.main:app \
    --host 0.0.0.0 --port 8000 \
    >/var/log/agentium/uvicorn.log 2>&1 &
SSH
```

## 4. Smoke — Vague D

From your laptop, pointing at the public URL. The four tiers are:

1. **Tier 1** — canonical routes + 401 on all gated endpoints (D1).
2. **Tier 2** — authenticated workspace / members / audit / settings
   calls succeed for Alice (D1).
3. **Tier 3** — the shipped JS+CSS contains FR+EN dictionaries (D3),
   light-theme tokens (D4), and the `/chat` chunk (D0). Requires
   `FRONTEND_DIST=…` pointing at the deployed `dist/` directory (or a
   local copy).
4. **Tier 4** — opt-in: schedule a run and verify SSE delivers
   `token_delta` frames (D2). Only useful when a seeded system calls
   `azure_llm_v1` or `llm_rag_answer_v1`.

```bash
BACKEND_URL=https://agentium.papai.ai \
KEYCLOAK_URL=https://auth.agentium.papai.ai \
REALM=agentium \
CLIENT_ID=agentium-backend \
ALICE_USER=alice@acme.test \
ALICE_PASS=alice-demo \
ALICE_WS_SLUG=acme \
FRONTEND_DIST=/tmp/agentium-dist \
SMOKE_RUN_SSE=1 \
  ./backend/scripts/smoke_vague_d.sh
```

If `FRONTEND_DIST` is unset, Tier 3 is skipped — still acceptable for
a quick API-only smoke.

### 4.bis — Tenant isolation (D1)

Run after Tier 2 passes:

```bash
BACKEND_URL=https://agentium.papai.ai \
KEYCLOAK_URL=https://auth.agentium.papai.ai \
  ./backend/scripts/test_tenant_isolation.sh
```

## 5. Manual UI walkthrough (≤ 3 min)

Only the checks the headless smoke cannot cover:

- [ ] Log in as Alice on `https://agentium.papai.ai`.
- [ ] Title-bar chat icon → overlay opens (D0).
- [ ] `⌘J` toggles overlay (D0).
- [ ] Command palette (`⌘K`) shows "Ask a question…", "Chat with a
      system…", "Drop files and ask…" (D0).
- [ ] Navigate to `/chat` → full-screen workspace renders (D0).
- [ ] Language switcher in the account menu: FR ↔ EN swap updates the
      title bar, side rail, and chat eyebrow live (D3).
- [ ] Theme switcher (`dark` / `light` / `system`): toggle to `light`
      — no white-on-white buttons, popovers still cast a soft shadow,
      signal buttons keep APCA-legible text (D4).
- [ ] Launch any run — the terminal shows a `token_delta` typewriter
      effect if the underlying skill streams (D2).

## 6. Rollback

If any tier fails and cannot be patched live:

```bash
# SPA
rsync -az --delete \
  backups/frontend-$(date -d 'yesterday' +%F)/ \
  deploy@agentium.papai.ai:/srv/agentium/frontend/

# Backend
ssh deploy@agentium.papai.ai <<'SSH'
  cd /srv/agentium/omnirag
  git reset --hard <previous-sha>
  source .venv/bin/activate
  alembic -c backend/alembic.ini downgrade 009       # undo 010_context_ephemeral
  sudo systemctl restart agentium-backend
SSH
```

## 7. Sign-off

Update `docs/vague-d-plan.md` — replace the D7 row's status with
`COMPLETED` and append a dated deploy line to the "Journal" section at
the bottom of the plan.
