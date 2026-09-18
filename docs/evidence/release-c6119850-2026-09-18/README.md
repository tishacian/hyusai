# Release c6119850 — hidden conversation rail honored

Published `demo/agentic` revision:
`c6119850dd100ca5f26f13a1af51619ed554ce53`

## Fix

The conversation panel styled `.chat-history-panel` as `display: flex`, which
overrode the native `hidden` attribute. A selector with matching specificity now
sets `.chat-history-panel[hidden] { display: none; }`. Clicking hide therefore
removes the full conversation column and leaves only the 38 px reopen rail.

## Verification

- i18n: passed
- UI chrome: passed
- Frontend unit tests: 1,560 passed
- Frontend production build: passed
- Storage check: passed
- Public revision: `c6119850dd100ca5f26f13a1af51619ed554ce53`, verified
- Frontend HTTP: `200`
- Backend exception matches in inspected startup window: `0`
- Carakai canaries: 10 passed, 2 intentional local-contract skips

No migration, workspace flag, or NAWA theme change. Rollback tag:
`f313a03a39f8`.
