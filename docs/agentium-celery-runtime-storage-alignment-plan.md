# Agentium alignment plan — Celery runtime, Docker unification, storage layer

<!-- markdownlint-disable MD013 -->

Working note for aligning the current `demo/agentic` Agentium platform with the
target architecture in `docs/image.png`, while selectively reusing Enzo's latest
work on `origin/feat/omnirag-2.0-full-http`.

## Executive read

Do **not** cherry-pick `origin/feat/omnirag-2.0-full-http` as a whole. It is a
useful OmniRAG 2.0 backend line, but it still lives mostly in the legacy
`connections/`, `src/`, `configurations/` runtime. The deployed Agentium VM uses
`backend/app.main:app` via `deploy/agentium-backend.service`.

The right move is to port selected concepts into the canonical Agentium runtime:

1. make Docker run the same FastAPI app as the VM;
2. make Celery/RabbitMQ the async execution plane for heavyweight work;
3. make object storage the source of truth for uploaded/generated knowledge
   assets;
4. keep PostgreSQL as the relational ledger, Qdrant as the vector index, and
   SSE as the live UI protocol;
5. wrap legacy OmniRAG/RAG functions as Agentium skills and worker tasks rather
   than exposing a second API surface.

## Current split to resolve

### Runtime split

- VM/systemd source of truth:
  - `WorkingDirectory=/home/ubuntu/omnirag/backend`
  - `ExecStart=/home/ubuntu/omnirag/venv/bin/uvicorn app.main:app`
  - source: `deploy/agentium-backend.service`
- Docker source of truth today:
  - `docker/Dockerfile.fastapi` runs `python run_fastapi.py`
  - `run_fastapi.py` imports `connections.fastapi.main`
  - `connections.fastapi.api.api` exposes only legacy health/db/flow/sharepoint

This means Docker and the VM do not run the same product.

### Async split

Current Agentium async work is split between:

- FastAPI `BackgroundTasks` and in-process run engine for `/runs`;
- in-memory SSE event bus for live run events;
- legacy `connections/celery/tasks.py` for old OmniRAG ingest/sharepoint flows.

Target architecture wants RabbitMQ + Celery Workers as the execution plane for
long-running operations.

### Storage split

Current Agentium document upload path still uses local temp files and local
`uploads/` persistence in `backend/app/api/v1/endpoints/documents.py`.

Target architecture wants a storage layer with:

- PostgreSQL for relational entities and run ledger;
- Qdrant for vector search;
- MinIO/object storage for raw documents, derived markdown, expert-capture
  proposals, generated artifacts and replayable assets.

## Target runtime shape

```text
Angular SPA
  | REST + SSE
  v
Agentium FastAPI API (backend/app.main)
  | auth / tenancy
  +--> Keycloak
  | relational ledger
  +--> PostgreSQL
  | object assets
  +--> StorageService -> MinIO/S3 or local dev filesystem
  | vector index
  +--> VectorDBFactory -> Qdrant
  | async jobs
  +--> RabbitMQ -> Celery workers
                  | parse/chunk/embed/index
                  | RAG retrieval / HAH scoring
                  | run-node execution
                  | eval / recommendations / knowledge capture ingestion
  | live events
  +--> SSE streams backed by event bus + persisted checkpoints
  | model providers
  +--> Embedding gateway / TEI / OpenAI
  +--> LLMaaS / OpenAI-compatible providers
```

## Alignment phases

### Phase 0 — Freeze runtime ownership

Goal: prevent new work from extending the wrong backend.

Tasks:

- Declare `backend/app.main:app` as the only product API for Agentium.
- Mark `connections.fastapi` as legacy/worker-support code, not a second public
  runtime.
- Add a short note in `docs/mental-model.md` and deployment docs that Docker must
  converge on `backend/app`, not `connections.fastapi`.
- Keep `connections/celery` code temporarily available for worker migration.

Acceptance:

- New API endpoints are added only under `backend/app/api/v1/endpoints`.
- No new Angular call points target `connections.fastapi` routes.

### Phase 1 — Unify Docker runtime with VM runtime

Goal: `docker compose up fastapi` and the VM systemd service run the same app.

Tasks:

- Replace Docker FastAPI command with `uvicorn app.main:app` from `backend/`.
- Add or update a dedicated `docker/Dockerfile.agentium-backend` if changing the
  old `docker/Dockerfile.fastapi` risks breaking legacy flows.
- Align env files with `backend/.env.example` and `app.core.config.Settings`.
- Decide whether Docker static serving uses Angular dev server, nginx, or
  FastAPI static fallback. Do not mix Streamlit as the primary Agentium frontend.
- Add a compose profile:
  - `agentium-api`
  - `agentium-worker`
  - `infra` (`db`, `broker`, `qdrant`, `minio`, `keycloak`)

Acceptance:

- `docker compose --profile agentium up` serves the same `/api/v1/openapi.json`
  routes as the VM.
- `/api/v1/health`, `/api/v1/auth/*`, `/api/v1/runs`, `/api/v1/chat/stream`,
  `/api/v1/documents/*` are available in Docker.
- Legacy `connections.fastapi` is either removed from the runtime path or put
  behind an explicit `legacy-omnirag` profile.

### Phase 2 — Introduce an Agentium Celery app

Goal: add Celery without leaking legacy payloads into the public API.

Tasks:

- Create `backend/app/workers/celery_app.py` using Agentium settings.
- Use RabbitMQ as broker.
- Use either PostgreSQL result backend or a small `agentium_jobs` table, but do
  not make Celery result payloads the product source of truth.
- Create a task envelope:

```json
{
  "job_id": "uuid",
  "workspace_id": "uuid",
  "actor_id": "uuid-or-null",
  "kind": "document_ingest | vector_reindex | run_node | eval_run | knowledge_capture_ingest",
  "input_ref": {},
  "trace_ref": {}
}
```

- Add a `Job`/`Task` ledger or reuse existing `Task` model if it already covers:
  status, progress, logs, workspace_id, run_id, resource refs, error.
- Add progress publication:
  - persisted progress in PostgreSQL;
  - optional live publish to the existing run event bus;
  - SSE endpoint reads from persisted state on reconnect.

Acceptance:

- FastAPI request returns quickly with `job_id` or `run_id`.
- Worker progress is visible in `/tasks` or `/runs`.
- Worker failure never leaves a document/run stuck in `running` without an error.

### Phase 3 — Move document ingest to worker tasks

Goal: parse/chunk/embed/index is no longer done in the FastAPI request process.

Tasks:

- Keep `/api/v1/documents/upload` as the user-facing route.
- Change upload flow to:
  1. store raw file in object storage;
  2. create `DocumentAsset`/metadata row in PostgreSQL;
  3. enqueue `document_ingest`;
  4. stream/poll progress;
  5. worker parses, chunks, embeds, indexes into Qdrant and updates rows.
- Make `DocumentService` callable from both API and worker, but ensure the heavy
  path is worker-owned.
- Persist chunk metadata in PostgreSQL enough to rebuild BM25 and explain
  citations. Qdrant remains search index, not the only metadata store.
- Add idempotency:
  - content hash per raw object;
  - deterministic chunk ids;
  - replace/update mode per collection.

Acceptance:

- Uploading a large PDF does not block the API worker.
- Re-running ingest on the same file does not duplicate chunks unexpectedly.
- Qdrant and PostgreSQL agree on document/chunk counts.

### Phase 4 — Build a storage layer abstraction

Goal: replace ad hoc local files with a storage service that supports MinIO/S3
and local dev.

Tasks:

- Add `backend/app/services/storage/` with:
  - `StorageService.put_file`
  - `StorageService.get_file`
  - `StorageService.copy`
  - `StorageService.list`
  - `StorageService.signed_url` where supported
- Backends:
  - local filesystem for tests/dev;
  - MinIO/S3 for Docker/VM.
- Standardize object keys:

```text
workspaces/{workspace_id}/uploads/{document_id}/original/{filename}
workspaces/{workspace_id}/documents/{document_id}/derived/{name}.md
workspaces/{workspace_id}/knowledge-capture/{session_id}/proposal.md
workspaces/{workspace_id}/runs/{run_id}/artifacts/{artifact_id}
```

- Move `knowledge_capture` accepted proposals through the same storage + ingest
  path as uploaded docs.
- Keep secrets and endpoint config in `backend/.env`, not in code.

Acceptance:

- No production code writes business assets directly under repo-local `uploads/`.
- Tests can run with a temp local storage root.
- MinIO can be swapped for S3-compatible storage without API changes.

### Phase 5 — Port RAG full-http gains into Agentium contracts

Goal: reuse Enzo's HTTP task boundaries and Qdrant work without importing the
legacy API shape.

Tasks:

- Port create-vector-store concepts into an Agentium endpoint/task:
  - `POST /api/v1/knowledge-bases/{id}/reindex`
  - worker task `vector_reindex`
- Port query pipeline concepts into Agentium:
  - internal task/skill `rag_retrieve_context_v1`
  - optional worker-backed retrieval for heavy HAH/CHAH;
  - keep `/chat/stream` and `/runs/{id}/stream` as the public UI contract.
- Preserve Agentium entities:
  - Workspace
  - System
  - SkillInvocation
  - Run
  - EvaluationScore
  - Decision
- Do not expose legacy `/flow_operations/*` as the primary product API.

Acceptance:

- HAH/CHAH retrieval can run via worker for heavy workloads.
- Chat and Runs still produce canonical Run ledger rows and SSE events.
- Existing Angular surfaces need no knowledge of Celery payload internals.

### Phase 6 — External embeddings and LLMaaS adapters

Goal: match the diagram's Emb-aaS and LLMaaS boxes.

Tasks:

- Add an embedding provider interface:
  - OpenAI embeddings;
  - local sentence-transformers fallback;
  - TEI/Embaas HTTP provider.
- Add health checks and dimension discovery per embedding provider.
- Add LLMaaS provider behind existing model router/provider layer:
  - OpenAI-compatible HTTP endpoint;
  - per-workspace provider config;
  - cost/latency instrumentation.
- Keep streaming token support through the existing `token_sink` and SSE bus.

Acceptance:

- A workspace can select `embedding_provider=tei` without changing ingest code.
- LLM provider failure is surfaced as a Run/SkillInvocation error.

### Phase 7 — Verification and deploy path

Tests:

- Unit tests:
  - storage local backend;
  - task envelope validation;
  - idempotent document ingest;
  - worker error handling.
- Integration:
  - Docker compose infra + backend + worker;
  - upload -> job -> Qdrant -> search;
  - accepted knowledge capture proposal -> ingest -> retrievable answer.
- E2E:
  - Angular upload and status;
  - chat with sources;
  - run stream receives structural events and `token_delta`.

VM rollout:

- Keep `/home/ubuntu/omnirag/backend` and `agentium-backend` service as API.
- Add `agentium-worker` systemd service only after Docker worker path is green.
- Run Alembic before worker restart.
- Deploy frontend assets to `/var/www/agentium`.

## Enzo branch review — cherry-pick candidates

Reference branch: `origin/feat/omnirag-2.0-full-http`.

Latest Enzo commits checked:

| Commit | Subject | Value | Recommendation |
| --- | --- | --- | --- |
| `5a1a769` | `ENH: omnirag 2.0 full-http` | Big consolidation: HTTP endpoints for collections/files/tasks/query, config split, OpenAI service, streaming query tests, dev env split. | **Port selectively.** Too broad for direct cherry-pick. Extract API/task boundaries, models, tests, and config ideas. |
| `6d20c86` | `ENH: qdrant but it's great` | Strong Qdrant direction, qdrant client config, reduced local vector-store complexity, integration tests. | **Port concepts/tests.** Current Agentium already has Qdrant; reuse missing tests and config hardening. |
| `7e7185c` | `ENH: replace vdb options by qdrant` | Simplifies vector DB options by making Qdrant the main backend. | **Partial.** Good for prod defaults, but keep FAISS/local for tests/dev unless product decides Qdrant-only. |
| `33cad8f` | `TST: add integration test for qdrant service using qdrant-client` | Useful test coverage around real Qdrant. | **Cherry-pick or rewrite into `backend/app/tests/integration`.** |
| `b773a3f` | `ENH: add qdrant service to docker-compose` | Adds Qdrant service and env wiring. | **Already mostly present.** Compare image/version/env only. |
| `5b8e918` | `ENH: add create vs and query llm pipeline task and endpoints` | Adds Celery tasks for `create_vector_store`, `query_llm_pipeline`, and FastAPI endpoints. | **Port as worker task designs, not routes.** Public API should stay Agentium. |
| `0db411b` | `ENH: add create vector store payload` | Good typed payload split for chunking/embedding/retrieval config. | **Port schemas.** Map to Agentium presets/knowledge-base config. |
| `0ea06df` | `TST: unit + integration test for ingest documents service` | Valuable regression suite for ingest. | **Rewrite against `DocumentService` + StorageService.** |
| `3cfc258` | `ENH: create and return kb uuid at fastapi level directly` | Good UX: create KB row immediately and return id before async work completes. | **Port directly in spirit.** Agentium upload should return document/job ids immediately. |
| `a0c1345` | `MAINT: upgrade version for rabbitmq and postgres` | RabbitMQ 4.2, Postgres 18 in compose. | **Be conservative.** Current Docker uses RabbitMQ 4.1 / Postgres 17. Upgrade only after CI confirms compatibility. |
| `0266ae2` | `FIX: use ingested folder instead of extracted assets` | Correct separation of original vs derived content. | **Port.** Aligns with storage object key plan. |
| `1a2f0a5` | `FIX: enforce target dir in pdf markdown loader` | Prevents parser output from leaking into wrong location. | **Port/check.** Relevant once storage-derived markdown is canonical. |
| `867a51c` | `ENH: add spacy base en sm model for tokenization for pptx ingestion` | Better Office/PPTX ingestion tokenization. | **Optional.** Useful but may increase image weight. Gate behind worker image. |
| `49569a2` | `ENH: update deprecated TRANSFORMERS_CACHE env var to HF_HOME` | Modern HF cache env. | **Port.** Low risk for worker images. |
| `d1e9261` | `ENH: explicit volume name for rabbit mq` | Persistent RabbitMQ data volume. | **Port.** Low risk, useful for Docker. |
| `99da077` | `ENH: ingest service with fs` | Introduces fsspec/papai unified storage, object layout constants, ingest via storage. | **High-value port, but adapt.** Use Agentium `StorageService`; avoid hard-coded workspace uuid. |
| `29de540` | `ENH: update docker with pip index + fix celery-cpu image not built before init issue` | Better Docker build reproducibility and init dependency ordering. | **Port selectively.** Keep private index safeguards only where required. |

## What not to port directly

- Legacy public routes under `connections.fastapi.api.endpoints.*`.
- Streamlit frontend as the primary product UI.
- Hard-coded `WORKSPACE_UUID` from `connections/storage/__init__.py`.
- Legacy `connections.models` package shape; map payloads into `backend/app`
  schemas/services.
- Direct Celery progress callback to external core endpoint
  `/api/private/v1/jobs/py-status`; Agentium should own progress in its DB/SSE.
- Full Qdrant-only removal of FAISS/local until tests and dev workflows are
  adjusted.

## Proposed cherry-pick order

Prefer small ports over Git cherry-pick when files moved between runtimes.

1. Storage groundwork:
   - read `99da077`, `0266ae2`, `1a2f0a5`;
   - implement Agentium `StorageService`;
   - add tests.
2. Worker groundwork:
   - read `5b8e918`, `3cfc258`, `d1e9261`;
   - implement Agentium Celery app + job ledger;
   - wire document ingest task.
3. Qdrant hardening:
   - read `6d20c86`, `7e7185c`, `33cad8f`;
   - port tests/config improvements;
   - keep Qdrant as prod default.
4. Docker unification:
   - read `5a1a769`, `29de540`, `a0c1345`;
   - make compose run `backend/app`;
   - add worker service and profile.
5. RAG pipeline:
   - read `0db411b`, `5b8e918`;
   - map payloads to Agentium presets and skills;
   - workerize heavy HAH/CHAH retrieval.

## Key risks

- **Runtime ambiguity**: Docker and VM serving different FastAPI apps creates
  false positives in tests and deploys.
- **Tenant isolation**: legacy storage constants and payloads are not
  workspace-safe as-is.
- **Progress semantics**: Celery task state is not enough for Agentium UX; the
  cockpit needs persisted Run/SkillInvocation/Job state.
- **SSE reconnection**: live-only event bus is not enough for long jobs. Persist
  checkpoints and replay snapshots on reconnect.
- **Image size**: OCR, spaCy, sentence-transformers and local models belong in
  worker images, not necessarily in the API image.
- **Migration blast radius**: moving uploads to object storage requires a
  compatibility plan for existing local `uploads/` files on the VM.

## Near-term implementation checklist

- [ ] Add `StorageService` abstraction with local backend tests.
- [ ] Add Docker profile that runs `backend/app.main:app`.
- [ ] Add `backend/app/workers/celery_app.py`.
- [ ] Add `agentium-worker` compose service using RabbitMQ.
- [ ] Add `Job` ledger or extend existing `Task` model for worker progress.
- [ ] Convert document upload to enqueue `document_ingest`.
- [ ] Store raw uploads and expert-capture accepted proposals in object storage.
- [ ] Worker indexes chunks into Qdrant and records chunk metadata.
- [ ] Add SSE/poll endpoint for job progress.
- [ ] Port Qdrant integration tests from Enzo branch into `backend/app/tests`.
- [ ] Add VM runbook section for `agentium-worker` once compose path is green.

