# Client360 generalized app — ops runbook

Operator checklist after product phases 1–5. **Does not authorize** commit,
push, VM deploy, live promote/sync, or changing production `scope_mode`.
Those steps need an explicit operator GO.

Companion data model: [docs/client360-installed-base-collection.md](../client360-installed-base-collection.md).

| Field | Value |
| --- | --- |
| Workspace | `andritz` |
| Collection | `andritz-client360-installed-base` |
| Promote script | `cd backend && python -m scripts.promote_client360_installed_base …` |
| Default engine scope | `workspace.settings.client360_pdr_scope.scope_mode` = `pilot` |

## Assumed product limits

- No mail open/reply tracking → manual status + follow-up reminders only.
- Campaign / part forecasts are **deterministic estimates** (periodicity + last
  purchase), shown with an explicit disclaimer — not ML.
- Campaign send stays human-gated.
- Wear-parts mapping gate stays on even when `scope_mode=all` (anti-noise).

## 1. Promote allowlisted Installed_base_SPL files

Allowlist (basename, case-insensitive) under `Installed_base_SPL/`:

| File | Notes |
| --- | --- |
| `Liste Projets _ Clients.xlsx` | Project↔customer registry — promote first; ≤60 Mo exception |
| `Liste Sales Orders D800 MNT SPL 2011_2026 VA05.xlsx` | Client-level sales; ≤60 Mo exception |
| `Installed base - Machine.xlsx` | Installed park |
| `Installed base - SPC.xlsx` | Heavy (~56 Mo) — optional promote; sync only with `--include-spc` or `--scope all` |
| `Histo_Achat_Pieces_Machines_Montbonnot.xlsx` | Already promoted (vault); ≤60 Mo; sync via `--include-purchase-history` |
| `Family - Opportunity.xlsx`, `Sales_By_Country.xlsx`, `Materials_Consumptions.xlsx` | Existing Phase‑1 feeds |

```bash
cd backend
# Inspect what would promote
python -m scripts.promote_client360_installed_base --workspace andritz --dry-run --promote

# Vault promote (no adapter sync)
python -m scripts.promote_client360_installed_base --workspace andritz --promote
```

Order: registry → sales orders → machine → (optional) SPC. Wait for
`document_ingest_index` before syncing.

## 2. Sync adapter → Client360DataSource

Sync flags (script CLI ≡ API body on `POST /api/v1/client360/sources/sync-from-collection`):

| Flag | Effect |
| --- | --- |
| `include_spc` / `--include-spc` | Sync Installed base SPC (deferred otherwise) |
| `scope=all` / `--scope all` | Also enables SPC + purchase_history |
| `include_purchase_history` / `--include-purchase-history` | Sync Histo_Achat (`other` / `purchase_history`) |

Registry (`project_registry`) syncs whenever present (small file). Prefer
explicit flags over jumping straight to `--scope all` on first cut.

```bash
# Dry-run full enrichments
python -m scripts.promote_client360_installed_base \
  --workspace andritz --sync --dry-run \
  --include-spc --include-purchase-history

# Real sync (same flags)
python -m scripts.promote_client360_installed_base \
  --workspace andritz --sync \
  --include-spc --include-purchase-history
```

API equivalent:

```json
POST /api/v1/client360/sources/sync-from-collection
{
  "collection_slug": "andritz-client360-installed-base",
  "dry_run": false,
  "include_spc": true,
  "include_purchase_history": true
}
```

## 3. Engine `scope_mode` — pilot first, then all

`scope_mode` is a **workspace setting**, not a promote/sync flag:

- `pilot` (default) — country/customer pilot gate on.
- `all` — skips that gate; wear-parts mapping still applies.

```bash
# Keep pilot for first engine dry-run / run
PATCH /api/v1/auth/workspaces/andritz
{ "settings": { "client360_pdr_scope": { "scope_mode": "pilot" } } }

# After volume looks sane, flip demo to all (operator GO)
PATCH /api/v1/auth/workspaces/andritz
{ "settings": { "client360_pdr_scope": { "scope_mode": "all" } } }
```

## 4. Engine re-run after sync

```bash
POST /api/v1/client360/engines/opportunities/run
{ "dry_run": true }

# After dry-run counts look right
POST /api/v1/client360/engines/opportunities/run
{ "dry_run": false }
```

UI: Client360 → **Données** → Dry-run moteur / Calculer.

Re-run after any material sync or `scope_mode` change.

## 5. Smoke checks

| Check | How |
| --- | --- |
| Annuaire | `GET /api/v1/client360/customers` — non-empty list, country facets |
| Fiche | `GET /api/v1/client360/customers/{id}` — projects / machines / purchases / next_due when feeds synced |
| Chat intents | `POST /api/v1/client360/chat` — try `customer_audit`, `forecast`, `opportunity_detail`, `navigation` phrasing |
| Campaign expected value | `GET /api/v1/client360/campaigns/{id}/stats` — `expected_value` + disclaimer « estimation déterministe… » |
| Mail prompt settings | `GET /api/v1/client360/mail-settings` — `system_prompt`, `system_prompt_source` (`default`\|`workspace`); UI **Mail & suivi** override/reset |

## 6. Deploy reminder (operator only)

This runbook does **not** deploy. When ready:

1. Commit Client360 product + this ops doc.
2. Push to the target branch (usually `demo/agentic`).
3. Deploy with full SHA:

```bash
bash scripts/deploy-vm.sh --sha <full_sha>
```

If backend and frontend OCI images diverge (or you only need one side):

```bash
# Backend + worker only
bash scripts/deploy-vm.sh --sha <full_sha> --no-frontend

# Explicit service set
bash scripts/deploy-vm.sh --sha <full_sha> --services "agentium-backend agentium-worker-cpu"
# or frontend-only when UI alone changed
bash scripts/deploy-vm.sh --sha <full_sha> --services "agentium-frontend"
```

Two-phase when needed: `--build-only` then `--activate-only` on the same SHA
(see [agentium-safe-vm-deployment.md](./agentium-safe-vm-deployment.md)). Never
hotfix with `docker cp` / in-container edits.

## Operator cheat-sheet (copy/paste)

```bash
cd backend

# 1) Promote vault (registry + sales orders + machine; SPC if deposited)
python -m scripts.promote_client360_installed_base --workspace andritz --dry-run --promote
python -m scripts.promote_client360_installed_base --workspace andritz --promote

# 2) Sync (dry-run → real); Histo_Achat already in vault
python -m scripts.promote_client360_installed_base \
  --workspace andritz --sync --dry-run \
  --include-spc --include-purchase-history
python -m scripts.promote_client360_installed_base \
  --workspace andritz --sync \
  --include-spc --include-purchase-history

# 3) Engine under scope_mode=pilot (workspace setting), dry-run then real
#    POST …/engines/opportunities/run  {"dry_run": true|false}

# 4) Smoke: GET …/customers, chat intents, campaign stats, mail-settings

# 5) Only after GO: flip scope_mode=all, engine re-run, then
#    commit → push → bash scripts/deploy-vm.sh --sha <full_sha>
```
