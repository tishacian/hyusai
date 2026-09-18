# Release f313a03a — collapsible conversation history

Published `demo/agentic` revision:
`f313a03a39f842c5da3ff86dcb9ac22c42edc1ec`

## Change

- The conversation list has a “hide” control beside “new chat”.
- When hidden, a 38 px rail keeps the conversation count and a control to reopen the list.
- The preference is persisted locally.
- Hiding and showing the list does not change the active conversation.
- Embedded compact chat surfaces remain without a history rail.

## Local gates

- i18n: passed
- UI chrome: passed
- Frontend unit tests: 1,559 passed
- Frontend production build: passed

## Deployment

- Previous live revision: `701cecc2e587139bd290b5166c8d3f658ea75b2e`
- Rollback tag: `701cecc2e587`
- Storage check: passed
- Migration: none
- Workspace flag and NAWA theme: unchanged
- Public revision verified: `f313a03a39f842c5da3ff86dcb9ac22c42edc1ec`
- Frontend HTTP: `200`
- Backend exception matches in inspected startup window: `0`

Images built on `omnirag-demo` at `f313a03a39f8`:

- backend `sha256:1fdf5efc4e17f850622fc7a5a6d8bf050eef0dcbe81d392ea92c57f764f94057`
- worker `sha256:1dec11370eeb8b15e6ef7eb0416a4630d0e3304f25e9313217c3060b9d6bfce6`
- frontend `sha256:dd5f7d8ebeabd987a8f83772623dd60fb1606cff11b450d7f651373603a27e23`

Carakai canaries: **10 passed, 2 intentional local-contract skips, 0 failed**.
