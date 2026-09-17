# Mandate deployment — 17 September 2026

Initial runtime: `e2294c37e79a17457fc078ae09c4201b3e4eaad5`, from pushed `demo/agentic`.

Three immutable images built on omnirag-demo. Migration 108 applied after the verified data-plane backup at `/srv/agentium-data/mandate-deployments/2026-09-17-e2294c37e79a` (`.ready`, PostgreSQL, MLflow registry and retained tabular/ML/BRD objects). No infrastructure, workspace flag, client policy or NAWA theme changes.

Local gates: 476 backend tests, 1,553 frontend tests, i18n (8,368 keys), navigation, chrome, production build. The 48 local screenshots in the [mandate report](../../reports/mandate-experience/README.md) use synthetic API fixtures; they are not live execution proof.

## Real qualification

[Retained synthetic System and editor](https://agentium.papai.ai/systems/141db166-2d4d-42df-bee3-6b65e556ca46?workspace=agentium-showcase&lens=build&facet=context).

The [live result](live-mandate.json) verifies draft isolation, stale-write rejection (409), policy-only semantic diff, canonical publication and unchanged applied policy on the previous Run.

- [Strict DAG without policy: completed](https://agentium.papai.ai/runs/7a93aa0b-0ac2-4448-8c14-ae7b49187617).
- [USD 0.20 limit: stopped because cost is unmeasured](https://agentium.papai.ai/runs/e4b1fceb-6401-4097-a6e3-07052506a87e). The recorded policy remains unchanged after a later publication.
- [30-second limit: completed](https://agentium.papai.ai/runs/48624aca-504d-4450-b6c8-85a66b4fb05f). No model calls or external effects in this source-to-sink Flow.

The initial overlay fixture selected the legacy sequential executor and failed with `no_skills_bound` (Run `c0dc85e9-07dc-42f7-9c5c-d03c30d543a1`). The test was corrected to use the canonical strict DAG; the failed Run remains retained.

## Findings before final qualification

Carakai: 9 passes, 2 intentional exclusions, 1 failure. System360 still required the replaced governance perspective component. A follow-up updates it to check the visible mandate and coverage, while retaining API honesty, rights, identity and navigation checks.

Live qualification also found that the stopped cost Run was shown as an ordinary recorded policy event. Follow-up classifies a postcheck Decision as blocked only when its persisted hard-abort rationale matches the Run's actual terminal error. It does not infer a stop from a breach alone.

The initial runtime is superseded by the follow-up release. Previous pre-migration image tag: `e30230aea3f5`. Because new immutable contracts have been published, do not roll back to an older worker that cannot read their frozen policy. Do not restore the backup over newer writes.
