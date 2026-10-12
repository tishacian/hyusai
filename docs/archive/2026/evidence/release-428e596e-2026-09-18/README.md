# Release 428e596e — resizable chat panel

Published `demo/agentic` revision:
`428e596e2e8965840655c1047c09d3ab07bd1876`

## Change

The quick chat panel now has a continuous resize control on its left edge.
Drag expands or narrows the panel; keyboard users can focus the control and use
Left/Right to resize, `Home` for maximum width and `End` for the 360 px floor.
The chosen width persists locally and is disabled for full-screen or narrow
viewport modes. This is a general side-panel capability enabled for the chat
overlay only.

## Local gates

| Gate | Result |
|---|---|
| `check:i18n` | Passed |
| `check:nav-links --fail-closed` | Passed |
| `check:ui-chrome` | Passed |
| Frontend unit tests | 1,558 passed |
| Frontend production build | Passed |

## Images

All three images were built on `omnirag-demo` at immutable tag `428e596e2e89`:

- backend: `sha256:f83dd3f132ee2e2bb28f7ade29e0a2b08fbf736bfa37cd1e3af164538a5c3dba`
- worker: `sha256:d488e43bef82517347baaac95d4c933e8fc832bce4f3ffd4cb057c9835255591`
- frontend: `sha256:7b53ceb7baa1392458ef6313c48af99f30092bf4cde66839d5f3764e8c2a5836`

Build and runtime evidence directory on the VM:
`/srv/agentium-data/chat-resize-deployments/2026-09-18-428e596e2e89`.

## Deployment

- Previous live revision: `d82ffeba9ce2dd380e372a8c7bbd20f45ef39116`
- Rollback image tag: `d82ffeba9ce2`
- Storage check: passed
- Migration: none
- Workspace flag change: none
- NAWA theme change: none

Final runtime verification:

- backend revision: `428e596e2e8965840655c1047c09d3ab07bd1876`
- `revision_verified`: `true`
- frontend HTTP: `200`
- backend exception matches in the inspected startup window: `0`
- frontend container: healthy

## Protected runner

Carakai source and SHA marker were advanced to `428e596e2e8965840655c1047c09d3ab07bd1876`.
Iteration canaries passed: **10 passed, 2 intentional local-contract skips, 0 failed**.
Machine-readable results and captures are under [canaries](./canaries/).

## Remaining

The operator should hard-reload and confirm the drag feel on the actual
desktop, then test keyboard resize, persistence after reload, narrow/full-screen
modes and light/dark themes.
