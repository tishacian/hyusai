# Evaluation suites and comparisons

The Run comparison panel saves reviewed cases, executes the reference and draft through Flow Workbench, and retains each canonical Run. An absent assertion means **unevaluated**. A completed Run alone is not a passing test.

## API

- `POST /evaluation/suites`: System, name, cases, collection IDs, `reviewed: true`. Creates an immutable revision; it never updates an older suite.
- `GET /evaluation/suites?system_id=…`: visible suite revisions.
- `POST /evaluation/campaigns/preflight`: inspect the immutable baseline and current draft, qualified reachable prefix, bound corpus/model identities and planned Run count; no Run, job or draft mutation.
- `POST /evaluation/campaigns`: suite ID, completed or human-boundary baseline Run ID, expected draft revision, idempotency request key and optional ingress selection. `execution_mode=qualified_prefix` requires the returned `preflight_sha256`; `repeat_count` is 1 or 2.
- `GET /evaluation/campaigns/{id}`: persistent baseline/candidate Run references, server assertion verdicts and comparison limits.
- `POST /evaluation/generations`: System, collection IDs, question count, language, request key, token/call limits. Creates a durable WorkspaceJob.
- `GET /evaluation/generations/{id}`: proposal or report, method, SDK version, coverage and provider usage.
- `POST /evaluation/campaigns/{id}/raget`: evaluate the completed recorded outputs against reviewed text references. Giskard does not execute the System again.

Suite cases accept `id`, `input_ref`, assertions (`id`, `path`, `operator`, `value`), optional reference Run, and optional reviewed `question`, `reference_answer`, `reference_context`, `answer_path` for RAGET. Operators are `equals`, `contains`, `not_contains`, `exists`. Missing paths fail an assertion. Explicit null differs from missing; zero differs from false. No arbitrary expression executes.

## Authority and reproducibility

The endpoints retain Flow Workbench's existing owner/admin authorization. Source Run visibility is checked for baseline, referenced examples, results and lists. Collections must belong to the workspace and remain accessible.

Baseline replay copies the preserved Flow and execution contract, including authored Skill executors. It does not recompile the baseline against the current Skill catalogue. The candidate is compiled from the current server draft under its revision lock. Both are run with the existing canonical runner.

Legacy comparison retains its original read-only gate. The explicit `qualified_prefix` mode traverses only the selected ingress and stops at a human boundary. It permits qualified AgentLoops with frozen read-tool allowlists and server-reviewed isolated DataOps/ML adapters. Dataset construction, visual preparation, scoring and typed evaluation produce campaign-bound artifacts; business receipts, arbitrary scripts, unknown executors and reachable subflows remain refused. A declared `effect: read`, an authored alias or a caller dry-run flag cannot override the server check.

Qualified campaigns validate and compile a separate projected graph, preserving required incoming assets and scoped source requirements. An unfinished disconnected draft node is excluded, while errors within the selected path and executable dependencies outside it remain blocking. Ordinary preview/publication validation is unchanged. `projections` in the preflight/campaign snapshot records source and projected hashes, retained/excluded nodes, assets, human boundaries, candidate draft revision and baseline Run identity. Runs store the projected graph/hash and the source hash in their execution evidence. Frozen baseline bindings are filtered and revalidated, never recompiled from the current Skill catalog. Strict flows may include an inert output declaration after the human boundary; the runtime still closes the QA Run before it and prohibits resume. No draft or published version is rewritten.

The canonical runtime rechecks the campaign binding before each invocation. HITL and AgentLoop `ask_human` terminate the campaign Run as **cancelled**, with an explicit `human_gate` termination and a system-rejected decision. No human approval is impersonated; campaign Runs cannot resume across that boundary. A membrane-held output is unavailable to output evaluation.

Suite schema v2 adds `expected_termination`, `output_selector` (Skill, optional node and dictionary path), `trajectory_assertions`, family/tags/severity and `answer_format`. Trajectory operators are required/forbidden tools, partial ordering, call ceiling, human boundary and no business effects, evaluated against canonical invocations/checkpoints. Outputs and trajectories are separate from the Judge's `quality_status`; technical completion is not a quality verdict. With no authored checks, the result stays unevaluated. `answer_path` is relative to the selected output and applies only to RAGET. `answer_format=json` explicitly evaluates a serialized structured output without changing object assertions.

The suite remains capped at 20 cases. Twelve cases and two repetitions create 48 canonical Runs, retaining all attempts and alternating version dispatch order. No best-attempt selection or automatic publication gate is introduced. Warnings and regressions support human review.

The collection fingerprint is its ledger state, not a byte snapshot of all Qdrant points. Comparison therefore reports limited comparability. A changed or unavailable collection suppresses improved/regressed conclusions. External model revisions and live retrieval remain stated limitations. Execution cost, evaluation cost and generation cost are separate; unavailable cost stays null.

## Giskard worker

Build the existing Python 3.12 worker image with `INSTALL_GISKARD_RAGET=true` to install the optional `giskard[llm]>=2.15,<3` requirement. Version 3 removed the RAGET API used here; do not upgrade across that boundary without migrating the adapter. The API image does not install it.

Each operation starts a disposable Python interpreter. Provider credentials arrive over stdin, not command arguments or job metadata. The subprocess inherits no provider environment keys. Model globals cannot survive between workspaces. Provider stderr is not exposed in an API error.

The initial adapter supports the configured OpenAI route and configured embedding model. It applies model/action and collection membrane controls, bounds calls, reserved tokens and elapsed time, and records observed usage. Policies requiring unsupported source filtering still fail before a provider call. Each live Giskard provider attempt also requests the shared workspace/app budget admission in the parent process, before the subprocess may dispatch; usage and unknown/failed attempts retain their ledger state. No trusted workspace identity is accepted from the child. Other providers remain unavailable in this adapter.

Generation examines at most 100 Qdrant chunks per collection and 8,000 characters per chunk. Its report records coverage and a hash of the actual sampled content. Generated references remain proposals. Saving a reviewed suite keeps its generation job provenance; references do not silently become exact-match assertions.

RAGET evaluation requires unique reviewed questions and an explicit selected text output or JSON serialization. Human-boundary outputs are read from the retained successful invocation, without pretending that the whole Run completed. Its answer function only returns already recorded outputs; it cannot rerun a tool or System. Reports keep canonical Run identifiers in case metadata.

## Verification

Backend tests cover frozen baselines, no-oracle outcomes, regression detection, idempotency, draft conflict, explicit review, effect rejection, collection drift, withdrawn Run access, unavailable dispatch and subprocess credential isolation. Run `pytest app/tests/api/test_evaluation_campaigns.py app/tests/services/test_giskard_adapter.py` from `backend`.

Giskard 2.19.2 was installed successfully in an isolated Python 3.12 environment. `backend/scripts/qualify_giskard_raget.py` passed real QATestset, KnowledgeBase, evaluate and RAGReport serialization on three synthetic cases with explicit mocked model calls, preserving case Run references. No provider credentials were loaded. Live provider generation/evaluation and the optional worker image build remain NOT RUN. This SDK qualification does not demonstrate model quality.

The 31 targeted backend tests also cover measured invocation-ledger cost coverage, worker failure cancellation and explicit retries, RAGET request idempotency, frozen model routing, embedding allowlists and withdrawn source access. `execution_cost` is null for absent or partial measurements; a measured zero remains zero. `execution_cost_coverage` and measurement counts describe this distinction.

Generation and RAGET requests require a stable `request_key`. Model/provider and embedding selection are recorded at enqueue; changed routing is rejected before execution. Reads recheck the current membrane, including source and embedding permissions.


## Isolated artifact domain

Migration `145_evaluation_isolation` adds nullable campaign ownership to Runs, datasets, RecipeExecutions and MLPredictions, plus an authoritative Run binding. Null retains existing business semantics. Dataset allocation uses a distinct campaign/case/side/repetition/node namespace, avoiding business version collisions. Input and settlement checks refuse cross-campaign artifacts and writing a QA result into a business reservation.

Dataset and RecipeExecution lists default to business traffic; explicit `traffic=evaluation` or `all` allows inspection, and a jobs query by Run retains its QA lineage. ML production monitoring, shadow staging, model prediction counters and production feedback exclude campaign samples. Input-retention policy applies normally: even a prediction without its input/dataset reference retains campaign ownership. QA artifacts remain inspectable by their explicit IDs.

Preflight requires bound collection identities in the reviewed suite and captures collection ledger fingerprints, pinned model versions, artifact URI and signature/metadata hashes. Runtime rechecks the model identity. PostgreSQL and retrieval remain live reads; differing recorded source snapshots suppress pair comparison. A changed corpus suppresses campaign improvement/regression conclusions. This is bounded reproducibility, not a frozen external data/model environment.

For a concrete 12-case proposal and post-deployment recipe, see [Luma agent QA campaigns](luma-agent-qa-campaigns.md). The proposal has no fabricated human review or calibrated confidence. Separate human calibration must be completed before activating a confidence profile.
