# Release f864a985 — product shell default and governed automation blocks

Date: 2026-09-22. Branch `demo/agentic`.

| | |
|---|---|
| SHA | `f864a98514603a1f0b81b18d740cc48fe5e5c28a` |
| Image tag | `f864a9851460` |
| Rollback | `6e97f5598d56` |
| build-info | `revision_verified: true`, HTTP 200, backend healthy, 0 startup exception matches |

## Gates

- Frontend: `check:i18n`, `check:nav-links`, `check:ui-chrome`, `test:unit`, `build:prod` — exit 0.
- Backend, scoped: `test_workspace_features`, `test_system_perspective_api`, the two Work validation tests — 23 passed.
- Carakai `run-iteration-canaries.sh`: 10 passed, 2 skipped.

No Alembic migration. `demo-agentic` was not moved.

## Visual QA on Nawa, account thibaud.ishacian@datategy.net

- `/` stays on the IT Service Desk (`/nawa/itsd`). The business home is unchanged.
- `/hypervisor` renders the V2 ledger (“What the portfolio returned this quarter”), with unconfigured cost and value left blank.
- The rail reads Impact, Create, Monitor, Improve, Administer.
- Automation `df04a96a-2eba-418c-9844-d0a10e878db4`: palette is Trigger, Agent, Decision, Human gate, Retrieve, SAP write, Output. The bar is Run and Publish.
- `GET /work/pr-to-po/validations` returns 200 and an empty list. The page falls back to the app home because that release is an assistant, not an approval pattern, and the queue is empty.
