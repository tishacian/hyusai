# Observability task force — implementation and release evidence

Branch: `codex/observability-task-force`. Base: `71efe1aee1792d437182623ad04184b3942b4194`. Local qualification: 15 September 2026. Not deployed.

## Implemented journey

Quality opens recorded evaluations through an interactive score curve and dimension heatmap. Both share the selected evaluation and its exact Run link. Missing scores interrupt the curve. System and period filters also apply to aggregates and the review queue.

Run investigation keeps the execution state separate from the evaluation state, links a selected claim to examined excerpts, and shows recorded invocation intervals. Source access is checked again when evidence is read. The interface explains missing or withdrawn evidence.

An authorized author can inspect a correction, review its diff and apply it to a draft under revision control. The override belongs to that Flow node; it does not change the shared Skill or a published version. Reviewed suites and baseline/candidate comparisons persist server-side and retain canonical Run references. Publication remains explicit through the existing Flow route.

The optional Giskard worker adapter generates proposed test cases and evaluates recorded outputs. Its method and costs remain distinct from native controls and execution. See [campaign operations](observability-evaluation-campaigns.md).

## Visual delivery

[Paper and illustrated journey](../ui/observability/README.md) includes six principal views, unavailable/mobile/dark variants and the chart dashboard. Local application captures use synthetic API fixtures; they are not production evaluation results.

The charts use Cockpit tokens. No NAWA theme change is included.

## Verified locally

- Backend regression selection: 162 tests passed, covering evaluation truth, Run/source authorization, corrections, comparisons, model adapters, frozen contracts, assistant authorization, publication and streaming.
- Frontend suite: 1,456 tests passed.
- Production build passed with existing bundle budget and CommonJS warnings.
- `check:i18n`, `check:nav-links --fail-closed`, `check:ui-chrome` and `git diff --check` passed.
- Additive migration chain has one head: `105_evaluation_corrections`, after `104_evaluation_campaigns`.
- Visual fixture results are recorded in [visual-report.json](../ui/observability/screenshots/visual-report.json).

## Release qualification still required

- A real provider-backed NorthForge comparison, PIH missing-field case, unavailable-judge recovery and human approval journey; five successful repetitions and one unprepared case.
- The optional worker image build and live Giskard generation/report under workspace policy and budget.
- Integration canaries, including `23-observability-evidence-canary.spec.ts`, on the actual candidate SHA.
- Keyboard, zoom and accessibility acceptance beyond the current component checks, and the planned user sessions. Neither user comprehension nor adoption is established by unit tests.

## Bounded capabilities

Document-scope correction is rejected where the executor cannot guarantee narrowing. The supported correction changes an authored prompt template at one draft node.

Corpus comparability uses the collection ledger, not an immutable snapshot of Qdrant. Changed evidence prevents an unqualified before/after conclusion. Unknown or effectful executors are rejected by the comparison runner.

The Giskard adapter initially supports the configured OpenAI route. Unsupported providers or policies return an unavailable result. Historical evaluations retain their original limitations; no evidence or score is invented retroactively.

The legacy detailed Quality sections remain accessible. The new graphs do not certify economic value, human approval or broad quality beyond their selected evaluations.

## Candidate release procedure

1. Publish the reviewed branch and integrate the candidate into `demo/agentic` after the release decision.
2. Build immutable SHA images on `omnirag-demo`, including the optional Giskard worker only after its dependency gate passes.
3. Apply additive migrations through the normal deployment path; retain compatible rollback images.
4. Run existing canaries from carakai plus the observability evidence canary. Verify the deployed SHA and open real Run evidence manually.
5. Attach live captures and measured journey results before declaring OBS-0–OBS-4 accepted.

Activation remains the product owner's decision. This implementation does not claim task-force closure or successful live acceptance.
