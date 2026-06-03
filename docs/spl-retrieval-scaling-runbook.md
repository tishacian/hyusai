# SPL Retrieval Scaling Runbook

This runbook validates that SPL dense retrieval stays fast, scoped, and
budget-aware in production.

## Goal

For `andritz-notices-techniques-spl-pilot`, Quick Ask must never run a global
hybrid, HAH, or C-HAH retrieval over the full chunk lake. The backend must infer
scope internally, answer catalogue questions from SQL inventory/diagnostics, and
offer deep retrieval asynchronously when fast retrieval is intentionally bounded.

## RAGGER / HAH Alignment

The RAGGER paper frames HAH-RAG as hyper-layered, asynchronous hybrid search:
specialized sparse/dense layers run in parallel, results are fused/reranked, and
the design target is lower latency and energy cost without losing factuality.

For SPL production this maps to the following invariants:

- `CorpusPlanner` is the pre-retrieval layer. It classifies intent and infers
  system scope from SQL ledger, facts, summaries, source names, project codes,
  extensions, source kind, archive name, and status.
- Catalogue questions are not RAG questions. They terminate in
  inventory/diagnostics SQL and do not query Qdrant.
- Dense unscoped SPL Quick Ask is bounded. It may return a scoped/partial answer
  plus deep refinement, but it must not fan out over the whole lake.
- HAH/C-HAH in fast mode are not disabled as research concepts; they are routed
  through the planner and only become full layered/composite retrieval in a
  candidate subspace or `deep` job.
- Sparse retrieval is externalized. OpenSearch is the production BM25 backend;
  runtime BM25 warmup from Qdrant is a legacy opt-in path and must never run on
  dense SPL.
- All layers have budgets and deadlines. At deadline, the system returns what
  arrived and can queue Deep Retrieval; no retriever blocks the chat stream.
- The UI discloses the inferred scope after the answer. It must never ask the
  user to choose a scope before searching.

Code anchors:

- Planner and dense policy: `backend/app/services/rag/corpus_planner.py`
- Coarse-to-fine context: `backend/app/services/rag/context.py`
- HAH/C-HAH deadlines/fusion: `backend/app/services/rag/pipeline_retrieval.py`
- Sparse adapters: `backend/app/services/rag/sparse_backends.py`
- Runtime BM25 guardrail: `backend/app/services/rag/document_service.py`
- Chat budget/deep jobs: `backend/app/api/v1/endpoints/chat.py`
- Knowledge diagnostics/graph/inventory: `backend/app/api/v1/endpoints/documents.py`
- UI disclosure: `frontend-ng/src/app/features/chat/chat-panel.component.ts`

## Read-Only Guardrail Probe

Default mode is read-only: it logs in, fetches collection diagnostics, previews
retrieval plans, and performs offline artifact dry-runs only.

```bash
AGENTIUM_HOST=https://agentium.papai.ai \
AGENTIUM_EMAIL=... \
AGENTIUM_PASSWORD=... \
WORKSPACE_SLUG=andritz \
python3 scripts/probe_spl_retrieval_scaling.py
```

Or reuse an existing bearer token:

```bash
AGENTIUM_BASE_URL=https://agentium.papai.ai \
AGENTIUM_TOKEN=... \
WORKSPACE_SLUG=andritz \
python3 scripts/probe_spl_retrieval_scaling.py
```

Expected required checks:

- `diagnostics_http_200`
- `collection_is_dense`
- `scoped_inventory_filter_applied` with `project_code=ACJ100`
- `catalogue_policy_safe` with `dense_policy=catalogue_inventory`
- `catalogue_scoped_policy_safe` with `dense_policy=catalogue_inventory`
- `catalogue_scoped_filter_visible`
- `quick_auto_policy_safe`
- `quick_hybrid_policy_safe`
- `quick_hah_policy_safe`
- `quick_chah_policy_safe`
- every Quick plan has `candidate_pool_k <= 20`
- every Quick plan has `user_scope_required=false`
- every dense Quick plan has `global_chunk_search_allowed=false`
- every dense Quick plan disables HAH/C-HAH fan-out in `fast`
- artifact dry-runs return `status=dry_run`

The default probe writes:

```text
/private/tmp/spl-retrieval-scaling-probe.json
```

The scoped catalogue check can be pointed at another inferred project code:

```bash
PROBE_SCOPE_PROJECT_CODE=ACJ100 \
PROBE_SCOPED_CATALOGUE_QUERY="Quels fichiers ACJ100 as-tu dans cette collection ?" \
python3 scripts/probe_spl_retrieval_scaling.py
```

## UX Latency Probe

This mode sends real non-streaming chat requests and persists normal chat Runs.
It measures backend completion latency and metadata, but it does not prove the
browser/SSE stream path by itself.

```bash
AGENTIUM_HOST=https://agentium.papai.ai \
AGENTIUM_EMAIL=... \
AGENTIUM_PASSWORD=... \
WORKSPACE_SLUG=andritz \
python3 scripts/probe_spl_retrieval_scaling.py --run-chat
```

Acceptance:

- each Quick Ask returns HTTP 200
- each Quick Ask completes under `8s`
- `latency_budget.candidate_pool_k <= 20`
- response metadata exposes `dense_policy`, `retrieval_scope`, and
  `scope_confidence`
- no `CHAT_STREAM_TIMEOUT` is observed in the UI or logs for the same query

## Stream UX Probe

This mode sends real SSE `/chat/stream` requests and persists normal chat Runs.
It is the closest probe to the original SPL timeout failure.

```bash
AGENTIUM_BASE_URL=https://agentium.papai.ai \
AGENTIUM_TOKEN=... \
WORKSPACE_SLUG=andritz \
python3 scripts/probe_spl_retrieval_scaling.py --run-stream
```

Acceptance:

- each stream returns HTTP 200
- first SSE event arrives under `8s`
- retrieval event, when present, arrives under `8s`
- first text token arrives under `8s`
- no `CHAT_STREAM_TIMEOUT` event is emitted
- stream reaches `data: [DONE]` before `PROBE_STREAM_BUDGET_SECONDS`
- retrieval details expose `dense_policy` and bounded `latency_budget` when
  the stream includes a retrieval phase

Use a tighter stream budget when validating Quick Ask UX:

```bash
PROBE_STREAM_BUDGET_SECONDS=30 \
python3 scripts/probe_spl_retrieval_scaling.py --run-stream
```

## Deep Retrieval Probe

This queues one `rag_deep_retrieval` WorkerJob. It mutates only the worker job
ledger.

```bash
AGENTIUM_HOST=https://agentium.papai.ai \
AGENTIUM_EMAIL=... \
AGENTIUM_PASSWORD=... \
WORKSPACE_SLUG=andritz \
python3 scripts/probe_spl_retrieval_scaling.py --create-deep-job
```

Acceptance:

- response has `kind=rag_deep_retrieval`
- response has a `/documents/jobs/{job_id}` `poll_url`
- job can be polled until `completed`, `failed`, or a clear non-blocking error
- chat remains usable while the job runs

## Manual Artifact Jobs

For SPL, artifact jobs are manual-only. They must not auto-run during Quick Ask.

Useful jobs:

- `summary_index_rebuild`
- `sparse_index_rebuild`
- `qdrant_sparse_reindex`

Dry-run from API:

```bash
curl -sS -X POST \
  "$AGENTIUM_HOST/api/v1/documents/collections/andritz-notices-techniques-spl-pilot/retrieval-artifact-jobs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Workspace-Slug: andritz" \
  -H "Content-Type: application/json" \
  -d '{"kind":"summary_index_rebuild","dry_run":true}'
```

## Failure Policy

If the probe fails:

- catalogue queries must be fixed before any SPL demo;
- Quick plans with `candidate_pool_k > 20` are P0 regressions;
- `global_chunk_search_allowed=true` on SPL Quick Ask is a P0 regression;
- HAH/C-HAH enabled in `fast` without an inferred filter is a P0 regression;
- missing deep job polling is P1 unless Quick Ask is timing out, then P0.

Never ask the user to choose a scope before searching. The system may disclose
the inferred scope after the answer, but scope selection is backend policy.
