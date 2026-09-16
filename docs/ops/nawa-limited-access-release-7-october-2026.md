# Nawa Limited Access Release

Regenerate the Word twin:

```
python docs/ops/build_nawa_limited_access_release.py
```

The builder starts from `nawa-limited-access-release-template.docx` (style shell:
Aptos, navy tables, footer) and writes
`nawa-limited-access-release-7-october-2026.docx`.


**Client assessment baseline available 7 October 2026**

Nawa is the white-label of Agentium. From 7 October 2026 it will be available
for a limited client assessment in a controlled, versioned environment. The
assessment is for the intended end users — data scientists and AI engineers —
so they can operate the product unattended across the declared functional
envelope. Nawa does not receive a parallel feature set. Every Agentium
capability included in the release is inherited by Nawa by transitivity, under
the same contracts. This protects production systems, proprietary assets and
unrelated environments, and it gives both parties a stable and reproducible
basis for review.

## Purpose of the controlled release

The objective is not a single representative agent and not a guided replay of
one System. The 7 October baseline is reached when a data scientist or AI
engineer can use Nawa in complete autonomy across the Agentium functional
scope included in the release: Work, Create / Studio, Systems, Flows, Runs,
Decisions, Data & Models, evaluation, identity and audit.

The release brings those existing product families into one consistent
configuration. It does not expand the agreed functional scope. It does not
open Marketplace listing, cluster portability or factory-scale rollout.

## Why access before 7 October is not relevant

| Reason | Assessment impact |
| --- | --- |
| Moving product baseline | Agentium is still aligning the families that Nawa will inherit. Observations made now may not correspond to the released configuration. |
| Incomplete autonomy context | End users would still need a guided session. Findings would describe a presenter-led path, not unattended use of the envelope. |
| Incomplete inheritance | A capability that is not yet consistently enforced on Agentium is not yet a Nawa capability, even if a seeded example exists. |
| Limited reproducibility | Changes made during consolidation could prevent either party from reproducing an observation raised against an earlier build. |
| Disproportionate review effort | Reviewing an intermediate configuration would require the client to reassess the same areas after the controlled release is established. |

The proposed timing does not reduce the client’s ability to perform due
diligence. It ensures that the review applies to the version intended to serve
as the assessment baseline.

## Product roadmap — Agentium capabilities inherited by Nawa

The roadmap below is the Agentium product plan for 16 September–7 October
2026. Each row is a generic platform capability. Nawa receives it by
transitivity when that capability is in the controlled release. It is not a
Nawa-only build and it is not scoped to one System.

| Agentium capability | Inherited Nawa outcome |
| --- | --- |
| Work | Published Experiences are launched from `/work`. The operator does not need a presenter URL. |
| Create / Studio | A published System can be bound, released and deployed through the same authoring path. |
| System / Flow | The published Flow is the executable contract. Drafts are not selectable; versions do not float in silence. |
| Run | Execution is a canonical Run with recoverable evidence, not a chat transcript. |
| Decision | Accept / reject is an explicit human act. It records an opinion; it does not by itself apply a write. |
| Skills, connectors and patterns | The governed catalogue is the one presented in the environment. Sealed writes stay sealed. |
| Model routing | Routing and fallback are workspace policy, applied to every in-envelope System. |
| Data & Models | Dataset → model version → evaluation → published Skill is a product loop, not a seeded demo only. |
| Evaluation and observability | Evaluation and prompt-regression evidence refer to the same released configuration as the Run. |
| Identity, mandates and approvals | Identity, permitted actions and the approval path are the same contracts on every inherited System. |
| Audit and operational telemetry | Execution events, traces and operating signals belong to the Run ledger. |
| Impact / Hypervisor | Displayed measures are measured, declared or missing. Missing is not shown as zero. Unattested financial totals are not the baseline. |
| Deployment artefacts | The handover pack matches the versioned Compose configuration of the release. Kubernetes / Marketplace packaging is outside this envelope. |

Release principle: one Agentium product envelope, inherited by Nawa, operable
without a guided session.

## Weekly product sequence — 16 September to 7 October 2026

The following activities consolidate, standardise and consistently enforce
existing Agentium capabilities so that Nawa can inherit them. They do not
introduce additional functional scope.

| Week | Agentium product work (inherited by Nawa) |
| --- | --- |
| 16–21 September — Envelope | Freeze the 7 October capability map. Apply the honesty contract (measured / declared / missing / sealed) across Work, Create, Systems, Runs, Decisions and Impact. Align lexicon and navigation so the same families are discoverable without a presenter. |
| 22–28 September — Operate | Make the generic operate loop autonomous: launch an Experience, execute its System, open the Run evidence from the Work result, record a Decision. Align evaluation evidence with that Run. Any in-envelope System must follow this loop, not only a hero path. |
| 29 September–5 October — Build and Data & Models | Make the generic build loop autonomous: bind a published System in Studio, pass ready-check, cut an immutable Release, deploy Pilot or In-service. Make the data loop autonomous: dataset, model version, evaluation, published Skill, model-routing policy. |
| 6–7 October — Autonomy cut | Unattended dry-run of the declared envelope by data-scientist / AI-engineer profiles. Open limited access only for the families that passed. A family that still requires Datategy is labelled as such or left out of the envelope. |

## Release consolidation in progress

| Consolidation area | Release activity |
| --- | --- |
| Work and Experience runtime | Consolidate the launcher, certified renderer pin and deployment records so published Experiences are operable from Work. |
| Create / Studio and System binding | Standardise bind → ready-check → immutable Release → Pilot / In-service. |
| Orchestration and execution lifecycle | Consolidate the supported build, execution, recovery and completion paths in one release configuration. |
| Versioning, replay and traceability | Standardise version identification, execution snapshots, replay behaviour and Run lineage. |
| Connector, skill and pattern catalogues | Curate the approved components presented in the controlled environment. |
| Model routing policies | Apply the supported routing and fallback policies as workspace policy, not per demo. |
| Data & Models | Align datasets, model versions, champion designation and published Skills with the released configuration. |
| Evaluation and prompt regression | Align evaluation results and regression evidence with the released configuration. |
| Identity, mandates and approvals | Standardise the identity, permitted actions and approval path used across the envelope. |
| Audit and operational telemetry | Consolidate execution events, traces and operating signals for the inherited Systems. |
| Governance records | Align governance information with the configuration included in the release. |
| Deployment and handover artefacts | Harmonise the configuration and handover artefacts associated with the reference environment. |

## Capabilities presented on 7 October

The session is designed so that a data scientist or AI engineer can operate
the inherited Agentium families together, rather than watching multiple
disconnected demonstrations. The walkthrough is not limited to one System.

| Demonstrated capability | What will be shown |
| --- | --- |
| Work | Launch of a published Experience chosen by the operator, not only a presenter bookmark. |
| System / Flow configuration | The published Flow, approved components and released configuration. |
| Orchestration and execution | Execution of the System and visibility of its main processing steps as a Run. |
| Version, snapshot and replay | Identification of the executed version, Run history and controlled replay. |
| Create / Studio | Binding a published System and the Release / deploy path used for the envelope. |
| Data & Models | Dataset, model versions, evaluation evidence and a Skill consumed by a System. |
| Connectors, skills and patterns | The governed catalogue components used in the environment, including sealed writes. |
| Model routing | Application of the configured routing and fallback policy. |
| Evaluation evidence | Evaluation results and prompt-regression evidence bound to the same configuration. |
| Identity and approvals | Identity, permitted actions, mandate and the applicable approval point. |
| Traceability and audit | Execution trace, relevant operational telemetry and audit events. |
| Decision | An explicit human accept / reject, recorded as opinion, not as an automatic apply. |
| Impact | Measures shown as measured, declared or missing. No unattested financial total. |
| Deployment and handover | The configuration and handover artefacts available for the released envelope. |

## Outside the 7 October envelope

These items remain Agentium product work. They are not inherited by Nawa in
this limited access release.

| Out of envelope | Why it is not in the 7 October baseline |
| --- | --- |
| Azure Marketplace listing | A commercial listing is not a condition of unattended product use on the current environment. |
| Kubernetes / Helm portability | The reference environment is the versioned Compose configuration. Cluster packaging is a later product increment. |
| Unsealed external writes | Connectors that are sealed in the release stay sealed. A write is not implied by a Decision. |
| Hypervisor as attested financial ROI | Impact may show measured, declared or missing values. It does not certify economic totals. |
| Adoption journey for business users | The 7 October end users are data scientists and AI engineers. Business-user adoption chrome is a separate acceptance. |
| Factory-scale agent count | The release is the product envelope, not a volume of agents. |

## Limited environment

- The declared Agentium envelope on the Nawa workspace, in an isolated assessment environment.
- Controlled test scenarios and non-production data.
- Role-restricted, time-limited access for agreed data-scientist and AI-engineer participants.
- No access to production systems, unrelated customer environments or unrestricted administrative functions.
- No penetration testing, source-code review or destructive testing unless separately agreed in writing.

The assessment scope can be agreed before 7 October so that the session
addresses the client’s priority questions while remaining anchored to the same
controlled release.
