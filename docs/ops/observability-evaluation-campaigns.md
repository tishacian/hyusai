# Evaluation suites and comparisons

The Run comparison panel saves reviewed cases, executes the reference and draft through Flow Workbench, and retains each canonical Run. An absent assertion means **unevaluated**. A completed Run alone is not a passing test.

## API

- `POST /evaluation/suites`: System, name, cases, collection IDs, `reviewed: true`. Creates an immutable revision; it never updates an older suite.
- `GET /evaluation/suites?system_id=…`: visible suite revisions.
- `POST /evaluation/campaigns`: suite ID, completed baseline Run ID, expected draft revision, idempotency request key and optional ingress selection.
- `GET /evaluation/campaigns/{id}`: persistent baseline/candidate Run references, server assertion verdicts and comparison limits.
- `POST /evaluation/generations`: System, collection IDs, question count, language, request key, token/call limits. Creates a durable WorkspaceJob.
- `GET /evaluation/generations/{id}`: proposal or report, method, SDK version, coverage and provider usage.
- `POST /evaluation/campaigns/{id}/raget`: evaluate the completed recorded outputs against reviewed text references. Giskard does not execute the System again.

Suite cases accept `id`, `input_ref`, assertions (`id`, `path`, `operator`, `value`), optional reference Run, and optional reviewed `question`, `reference_answer`, `reference_context`, `answer_path` for RAGET. Operators are `equals`, `contains`, `not_contains`, `exists`. Missing paths fail an assertion. Explicit null differs from missing; zero differs from false. No arbitrary expression executes.

## Authority and reproducibility

The endpoints retain Flow Workbench's existing owner/admin authorization. Source Run visibility is checked for baseline, referenced examples, results and lists. Collections must belong to the workspace and remain accessible.

Baseline replay copies the preserved Flow and execution contract, including authored Skill executors. It does not recompile the baseline against the current Skill catalogue. The candidate is compiled from the current server draft under its revision lock. Both are run with the existing canonical runner.

Replay currently accepts authored prompt executors and an explicit small set of built-in read-only Skills. Unknown executors, AgentLoops, subflows and effects are rejected until individually qualified. A declared `effect: read` cannot override the server check.

The collection fingerprint is its ledger state, not a byte snapshot of all Qdrant points. Comparison therefore reports limited comparability. A changed or unavailable collection suppresses improved/regressed conclusions. External model revisions and live retrieval remain stated limitations. Execution cost, evaluation cost and generation cost are separate; unavailable cost stays null.

## Giskard worker

Build the existing Python 3.12 worker image with `INSTALL_GISKARD_RAGET=true` to install the optional `giskard[llm]>=2.15,<3` requirement. Version 3 removed the RAGET API used here; do not upgrade across that boundary without migrating the adapter. The API image does not install it.

Each operation starts a disposable Python interpreter. Provider credentials arrive over stdin, not command arguments or job metadata. The subprocess inherits no provider environment keys. Model globals cannot survive between workspaces. Provider stderr is not exposed in an API error.

The initial adapter supports the configured OpenAI route and configured embedding model. It applies model/action and collection membrane controls, bounds calls, reserved tokens and elapsed time, and records observed usage. Policies requiring unsupported source filtering or monetary reservations fail before a provider call. Other providers remain unavailable in this adapter.

Generation examines at most 100 Qdrant chunks per collection and 8,000 characters per chunk. Its report records coverage and a hash of the actual sampled content. Generated references remain proposals. Saving a reviewed suite keeps its generation job provenance; references do not silently become exact-match assertions.

RAGET evaluation requires unique reviewed questions and an explicit path to a text output. Its answer function only returns already recorded outputs; it cannot rerun a tool or System. Reports keep canonical Run identifiers in case metadata.

## Verification

Backend tests cover frozen baselines, no-oracle outcomes, regression detection, idempotency, draft conflict, explicit review, effect rejection, collection drift, withdrawn Run access, unavailable dispatch and subprocess credential isolation. Run `pytest app/tests/api/test_evaluation_campaigns.py app/tests/services/test_giskard_adapter.py` from `backend`.

Giskard 2.19.2 was installed successfully in an isolated Python 3.12 environment. `backend/scripts/qualify_giskard_raget.py` passed real QATestset, KnowledgeBase, evaluate and RAGReport serialization on three synthetic cases with explicit mocked model calls, preserving case Run references. No provider credentials were loaded. Live provider generation/evaluation and the optional worker image build remain NOT RUN. This SDK qualification does not demonstrate model quality.

The 31 targeted backend tests also cover measured invocation-ledger cost coverage, worker failure cancellation and explicit retries, RAGET request idempotency, frozen model routing, embedding allowlists and withdrawn source access. `execution_cost` is null for absent or partial measurements; a measured zero remains zero. `execution_cost_coverage` and measurement counts describe this distinction.

Generation and RAGET requests require a stable `request_key`. Model/provider and embedding selection are recorded at enqueue; changed routing is rejected before execution. Reads recheck the current membrane, including source and embedding permissions.
