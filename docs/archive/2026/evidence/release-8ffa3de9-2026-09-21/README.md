# Release 8ffa3de9 — automation-first draft

Published `demo/agentic` revision:
`8ffa3de92b75314fabf8be4d138de2ba03c82ed6`

## Change

Porte 0 of the automation-first roadmap is live:

- Créer opens with **Nouvelle automation** as the primary composer.
- The prompt creates a canonical System **draft**, not a second workflow object.
- The generated graph is `Trigger → Agent → Output`.
- The Trigger declares a transcript input and prefills the draft-run editor.
- The Agent binds the production LLM Skill without asking for JSON.
- The Flow opens directly after creation.
- Automation mode exposes four palette primitives only: Trigger, Agent, Condition, Output.
- Automation mode hides Simulate, Debug, Replay and Versions from the toolbar; Run remains primary.
- Capability, Knowledge and registry concepts remain outside the first run.

## Why this stays Agentium

The automation is a System draft projection. It reuses:

- canonical System creation;
- System draft and revision hashing;
- the draft-test Run admission path;
- Skill catalog binding;
- Flow validation;
- publication as a separate later verb.

No second execution engine or persistence model was added.

## Local gates

| Gate | Result |
|---|---|
| i18n | Passed |
| Navigation links | Passed |
| UI chrome | Passed |
| Frontend unit tests | 1,564 passed |
| Frontend production build | Passed |
| Backend flow-safety suite | 18 passed |

The backend contract test proves that the generated automation:

1. is accepted as a draft System;
2. preserves `variant: automation_v1`;
3. creates a SystemFlowDraft;
4. is admitted through `create_draft_test_run`;
5. carries the transcript and selected ingress without publication.

## Images

All three images were built on `omnirag-demo` at immutable tag `8ffa3de92b75`:

- backend: `sha256:f6e3bc6affb6a70e3ba0610bef4b4f31b3ff5e7ad99eb5a9997a65e61977ed94`
- worker: `sha256:4fe943f62da0a0617b820db3734126de7644728fba700fe19deea58b714d4c1c`
- frontend: `sha256:e93742ad96f9e918f52b3e7e43fb05f877ba774a6c51e9287f0d159d155c613f`

VM evidence directory:
`/srv/agentium-data/automation-first-deployments/2026-09-21-8ffa3de92b75`.

## Deployment

- Previous live revision: `1b4142496f70d88ba34b56147be2a09baa872488`
- Rollback tag: `1b4142496f70`
- Storage check: passed
- Migration: none
- Workspace flag and NAWA theme: unchanged
- Public revision verified: `8ffa3de92b75314fabf8be4d138de2ba03c82ed6`
- Frontend HTTP: `200`
- Backend exception matches in inspected startup window: `0`

## Protected runner

Carakai source and SHA marker were advanced to
`8ffa3de92b75314fabf8be4d138de2ba03c82ed6`.
Iteration canaries passed: **10 passed, 2 intentional local-contract skips,
0 failed**. Machine-readable results are under [canaries](./canaries/).

## Remaining acceptance

The decisive human test is still open:

> A process owner enters `SPARK-365 meeting minutes`, pastes a transcript, clicks Run, and obtains a draft without seeing Capability, System, Skill, JSON or publication.

That live SPARK-365 session must be recorded with the generated System URL and Run URL.
