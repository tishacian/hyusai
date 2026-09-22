# Release d4a75119 — Porte 1, Run and Publish

Published `demo/agentic` revision:
`d4a75119faa4a50ced08a959505023dc2fac3db5`

## Change

Automation mode now has two primary verbs:

- **Run**
- **Publish**

In `automation_v1`:

- Run is visible directly instead of being hidden behind the Operate disclosure.
- The button and dialog both say **Run**, not “Test draft”.
- Runtime-mode jargon is hidden from the compact control bar.
- Manual Save is hidden; the existing draft autosave and save-state pill remain active.
- Operate and More disclosures are hidden.
- Draft revision and hash labels are removed from the primary bar.
- Publish remains the second labelled verb and opens the existing explicit review.

The normal Flow Builder keeps its full toolbar and technical controls.

## Local gates

- i18n: passed
- Navigation links: passed
- UI chrome: passed
- Frontend unit tests: 1,566 passed
- Frontend production build: passed

The new UI contract proves:

- Run is not hidden behind Operate in automation mode;
- Save, Operate and More are removed from that mode;
- Publish remains available;
- compact Run labels resolve to “Run” in FR and EN;
- runtime, revision and hash labels stay out of the primary bar.

## Images

All three images were built on `omnirag-demo` at immutable tag `d4a75119faa4`:

- backend: `sha256:1dcc834432d5712052ff36b09a3e51188ffc8ebce7925eca2dda31d3b103f627`
- worker: `sha256:d93609072f22e6a83ed385fe59538363d75e9896192cbe5501d2ce05c11736c9`
- frontend: `sha256:a8efaf74239e3e3e7df15cef36ca7a20d3e1066ffaa001f93a78ea4338ffb459`

VM evidence directory:
`/srv/agentium-data/automation-first-deployments/2026-09-22-d4a75119faa4`.

## Deployment

- Previous live revision: `ce842f7a21222ae17d6ef4d30f5de37468205c9e`
- Rollback tag: `ce842f7a2122`
- Storage check: passed
- Migration: none
- Workspace flag and NAWA theme: unchanged
- Public revision verified: `d4a75119faa4a50ced08a959505023dc2fac3db5`
- Frontend HTTP: `200`
- Backend exception matches in inspected startup window: `0`

## Protected runner

Carakai source and SHA marker were advanced to
`d4a75119faa4a50ced08a959505023dc2fac3db5`.
Iteration canaries passed: **10 passed, 2 intentional local-contract skips,
0 failed**. Machine-readable results are under [canaries](./canaries/).

## Remaining acceptance

Hard reload and confirm visually that an automation draft shows only:

1. Run;
2. Publish;
3. canvas controls;
4. the save-state pill.

The SPARK-365 System and Run URLs should also be archived to close the Porte 0
acceptance record.
