# Release d82ffeba — assistant object context

Published `demo/agentic` revision:
`d82ffeba9ce2dd380e372a8c7bbd20f45ef39116`

## Change

- The side-panel pilot follows the canonical System, Run and SkillInvocation route, including the focused node.
- Each turn snapshots its object context; network retry reuses that exact context.
- The server validates object references, resolves a Run to its System, applies existing visibility controls and derives pilot scope.
- Conversation scope, recent turns and object references resume after reload per workspace; workspace reset clears pinning.
- `inspect_system` includes dispatch readiness and explicitly reports unchecked Systems without a dispatch surface.

## Local gates

| Gate | Result |
|---|---|
| `check:i18n` | Passed |
| `check:nav-links --fail-closed` | Passed |
| `check:ui-chrome` | Passed |
| Frontend unit tests | 1,557 passed |
| Frontend production build | Passed |
| Backend targeted tests | 31 passed |

Backend tests ran in an isolated Python 3.11 environment without changing `poetry.lock`.

## Images

All three images were built on `omnirag-demo` at immutable tag `d82ffeba9ce2`:

- backend: `sha256:c7fa4ee11471774ce579cbf8150c3be0c11d85682edea5153c8394f1ed21d34c`
- worker: `sha256:95e0968c445bb1e0d8d92e0431d2544a37398704c25d233c84bd5ef7f9268739`
- frontend: `sha256:114b44da456e23aaa8e36100d110649985e5e5025063a92975b9015663c9c288`

Build and runtime evidence directory on the VM:
`/srv/agentium-data/fluidity-deployments/2026-09-18-d82ffeba9ce2`.

## Deployment

- Previous live revision: `6f6d10c04c62bc6b916da0724a49b379a4e0620d`
- Rollback image tag: `6f6d10c04c62`
- Storage check: passed
- Migration: none
- Workspace flag change: none
- NAWA theme change: none

Final runtime verification:

- backend revision: `d82ffeba9ce2dd380e372a8c7bbd20f45ef39116`
- `revision_verified`: `true`
- frontend HTTP: `200`
- backend exception matches in the inspected window: `0`
- backend and frontend containers: healthy

## Protected runner

Carakai source and SHA marker were advanced to `d82ffeba9ce2dd380e372a8c7bbd20f45ef39116`.
Iteration canaries passed: **10 passed, 2 intentional local-contract skips, 0 failed**.

Machine-readable results are retained under [canaries](./canaries/).

## Remaining

The authenticated browser hard-reload specifically exercising the new object-context chip is still to be performed by a human operator. No SPARK-089 correction/comparison or F4–F6 qualification is claimed by this release.
