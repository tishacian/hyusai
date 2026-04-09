# Post-Demo Roadmap — Product Solidification

> Everything identified as out-of-scope for the 5-minute demo, organized by priority and effort.
> This document is the bridge between "we showed it works" and "we deliver it for real."

---

## 1. Procurement Agent — Complete Use Case 4 (Vendor Document Validation)

The demo covers 5/10 steps from the proposal. Here's what's missing and what it takes to add each.

### 1.1 Document Ingestion — OCR & Multi-format (Steps 2-3)

**What the demo does**: RAG on pre-uploaded text/PDF knowledge base.

**What production needs**:
- Azure Document Intelligence (or Tesseract fallback) for OCR on scanned documents
- Multi-format handling: PDF, DOCX, images (JPG/PNG of certificates), Excel
- Automatic document type classification (Trade License vs. Insurance vs. Financial Statement)
- Confidence scoring on classification

**Effort**: Medium (2-3 weeks). Azure Doc Intelligence has good Python SDK. Classification can be a fine-tuned classifier or LLM-based.

### 1.2 Data Extraction (Step 4)

**What the demo does**: Nothing — relies on LLM to interpret documents holistically.

**What production needs**:
- Structured field extraction: expiry dates, issuing authority, license numbers, amounts
- Date validation (expired vs. valid, upcoming expiry warnings)
- Entity normalization (company name matching across documents)
- Extracted data stored in structured DB for audit

**Effort**: Medium-High (3-4 weeks). Combination of Azure Document Intelligence custom models + LLM extraction + validation rules.

### 1.3 Automated Classification (Step 3)

**What the demo does**: Manual — user tells the agent what documents are present.

**What production needs**:
- Automatic document type detection from uploaded files
- Category mapping to checklist items
- Handling of ambiguous or multi-purpose documents
- Confidence threshold with human escalation for uncertain classifications

**Effort**: Medium (2 weeks). LLM-based classification with few-shot examples + fallback to manual review.

### 1.4 Human-in-the-Loop Reviewer Workflow (Step 8)

**What the demo does**: Nothing — output is final.

**What production needs**:
- Reviewer queue: compliance officers see flagged submissions
- Approve / Reject / Request Additional Info actions
- Status tracking (Pending Review -> Approved / Rejected)
- Notification system (email/Teams/Slack)
- Reviewer comments and decision audit trail

**Effort**: High (4-6 weeks). Requires task queue (Celery), notification service, reviewer UI, role-based access.

### 1.5 ERP & M365 Integration (proposal scope)

**What the demo does**: Standalone — no external systems.

**What production needs**:
- SAP/Oracle Procurement module integration for vendor master data
- SharePoint/OneDrive for document storage
- Teams notifications for escalations
- Outlook for email triggers
- Power Automate or Logic Apps for workflow orchestration

**Effort**: Very High (6-10 weeks per integration). Each integration is a mini-project with auth, mapping, error handling, rate limiting.

---

## 2. Platform Backend — Production Hardening

### 2.1 Database: SQLite → PostgreSQL

**Demo**: SQLite (single file, zero config).
**Production**: PostgreSQL with proper connection pooling (asyncpg), migrations (Alembic), backup strategy.

The `feat/keycloak` branch already has a PostgreSQL docker-compose block. The `develop` branch uses PostgreSQL.

**Effort**: Low (1-2 days). Alembic migrations already exist; change connection string.

### 2.2 Missing SQLAlchemy Models (`app/models/`)

The `omnirag-a*/` tree is missing its `app/models/` directory. For demo we create minimal stubs. For production:
- User model (with Keycloak sync)
- Session / Conversation model
- Message model (with metadata, tokens, cost tracking)
- Agent Configuration model (versioned)
- Knowledge Base model (from `feat/create-vector-store-api`)
- Audit Log model
- Trace / Execution Step model

**Effort**: Medium (1-2 weeks). Schema design + Alembic migrations + CRUD services.

### 2.3 Async Task Processing

**Demo**: Synchronous processing (fast enough for single user).
**Production**: Celery + RabbitMQ (or Redis) for:
- Document parsing and embedding (can take minutes for large files)
- Batch validation runs
- Scheduled compliance checks
- Report generation

The `develop` branch already has Celery + RabbitMQ wiring.

**Effort**: Medium (2-3 weeks). Celery is already in the codebase, needs task definitions and status tracking.

### 2.4 Vector Store: FAISS → Managed Store

**Demo**: FAISS (in-memory, local file persistence).
**Production options**:
- Qdrant (Docker, `feat/qdrant` branch has config) — best for self-hosted
- Chroma (already supported in `omnirag-a*/`)
- Azure AI Search (if Azure-first deployment)
- Weaviate, Pinecone (managed SaaS)

The `omnirag-a*/` VectorDB factory pattern already supports plugging in new backends.

**Effort**: Low-Medium (1 week). Factory pattern exists, just add the chosen provider.

### 2.5 Metadata Indexing & Filtering

The `feat/metadata-indexing` branch has rich metadata extraction:
- Per-format extractors (PDF, DOCX, CSV, JSON...)
- `MetadataStorageMode` (INPLACE vs REFERENCE)
- FAISS subset index with caching for `meta_filter`

This enables filtered retrieval (e.g., "search only in documents uploaded in the last 6 months" or "only Insurance Certificates").

**Effort**: Medium (2 weeks). Branch exists but is heavily coupled to the older codebase — needs careful port.

### 2.6 Multi-Provider LLM Routing

**Demo**: OpenAI GPT-4o only.
**Production**: The `src/llm/` SDK from `demo/monolith-llmaas-cloud` already supports 20+ providers. To activate:
- Policy-driven routing (cost, latency, data residency, capability)
- Fallback chains (GPT-4o → Claude → local model)
- Per-agent model assignment (from agent config)
- Usage metering and cost tracking per model

The `CustomLLMChain` in `demo/monolith-llmaas-cloud` already has basic routing logic.

**Effort**: Medium (2-3 weeks). SDK exists, needs routing policy engine + config UI.

---

## 3. Authentication & Governance — Enterprise Grade

### 3.1 Keycloak Full Integration

**Demo**: Visual only (show Keycloak admin console, mention SSO).
**Production**: Full OIDC integration:
- JWT token validation in FastAPI middleware
- Role-based access control (Admin, Agent Builder, Reviewer, Auditor, User)
- Workspace isolation (multi-tenant)
- SSO with client's IdP (Azure AD, Okta, LDAP)

The `feat/keycloak` branch has realm export + Docker config. Missing: FastAPI middleware, token validation, role extraction.

**Effort**: Medium (2-3 weeks). Standard Keycloak OIDC integration + RBAC middleware.

### 3.2 Audit System — Production Grade

**Demo**: Simple SQLite event log.
**Production**:
- Structured audit events with correlation IDs
- Immutable audit trail (append-only, signed entries)
- Export to SIEM (Splunk, ELK, Azure Sentinel)
- Compliance reporting (who accessed what, when, from where)
- Data retention policies
- GDPR-relevant: data access logs, deletion audit

**Effort**: Medium-High (3-4 weeks). Logging framework + export adapters + retention jobs.

### 3.3 Guardrails & Safety

**Demo**: Not implemented (mentioned conceptually).
**Production** (from WEBAPPFACTORY mockups):
- Input filters: PII detection, prompt injection blocking, jailbreak prevention
- Output filters: factuality checks, citation requirements, hallucination detection
- Human-in-the-loop triggers: low confidence escalation, sensitive topic routing
- Stop conditions: max iterations, token budget, cost limit, timeout
- Per-agent guardrail configuration

**Effort**: High (4-6 weeks). Requires separate guardrail evaluation pipeline. Can leverage existing LLM-as-judge patterns.

---

## 4. Frontend — Next.js Platform Build

### 4.1 Recommended Stack

- **Next.js** App Router + TypeScript
- **Tailwind CSS** with WEBAPPFACTORY design tokens (Instrument Sans, JetBrains Mono, color palette)
- **Vercel AI SDK** (`ai` npm package) for SSE streaming, `useChat` / `useCompletion` hooks
- **Zustand** for client state management
- MIT license, no vendor lock-in

### 4.2 Pages to Implement (from WEBAPPFACTORY mockups)

Priority order for post-demo:

**P0 — Core agent workflow:**
- `agents-list` — agent inventory with status, model, last activity
- `agent-builder` — full configuration (Model & Prompt, Knowledge, Tools, Guardrails, Orchestration, Memory)
- `agent-detail` — test playground with chat, tool calls, RAG explanation
- `agent-detail-traces` — execution trace timeline
- `agent-detail-settings` — agent parameters, stop conditions

**P1 — Knowledge & data:**
- `catalog-overview` — data catalog landing
- `catalog-documents` — document management, upload, metadata
- Knowledge base management (from `agent-builder.html` Context Providers pattern)

**P2 — Governance:**
- `governance-access-roles` — RBAC management
- `governance-audit-logs` — audit trail viewer
- `governance-usage-costs` — usage metering, cost tracking per agent/model
- `governance-settings` — platform configuration

**P3 — AI Services & orchestration:**
- `ai-services-list` — deployed model inventory
- `ai-services-detail` — model configuration, metrics, logs
- `workflows-list` — workflow orchestration (multi-agent)

**P4 — Apps & deployment:**
- `apps-list` — deployed agent applications
- `app-builder` — agent-to-app packaging
- `app-preview` — live preview before deployment
- `app-monitoring` — production monitoring, health checks

**P5 — Advanced (R&D):**
- `agent-detail-memory` — memory architecture explorer (short-term, long-term, decay)
- `agent-detail-evaluations` — evaluation campaigns, benchmark results
- `agent-qa-traces` — detailed QA trace with retrieval steps, quality gates

### 4.3 Why Not Fork (Dify, Open WebUI, etc.)

- Dify = its own platform (wrapping it contradicts positioning)
- Open WebUI = Svelte (not React), chat-only, its own backend
- AgentLabs = uncertain maintenance
- We have 80+ pages of UI spec (WEBAPPFACTORY mockups) — we don't need someone else's design vision

---

## 5. Full Agent Portfolio (Proposal Phase 1)

The proposal includes 5 agents with 10 use cases total. The demo covers 1 agent, 1 use case.

### 5.1 Procurement Agent — 2 additional use cases

- **UC3: Vendor Qualification Scoring** — automated scoring based on weighted criteria (financial health, certifications, history)
- **UC5: Contract Clause Extraction** — extract key terms, obligations, penalties from vendor contracts

### 5.2 HR Agent — 2 use cases

- **UC1: Resume Screening** — automated CV parsing, skill matching, shortlisting
- **UC2: Employee Onboarding Assistant** — guided onboarding Q&A, policy lookup, form completion

### 5.3 Finance Agent — 2 use cases

- **UC6: Invoice Validation** — match invoices to POs, flag discrepancies, extract line items
- **UC7: Budget Compliance Check** — validate expenses against budget categories and thresholds

### 5.4 Legal Agent — 2 use cases

- **UC8: Contract Review** — identify risk clauses, compare to standard templates, suggest amendments
- **UC9: Regulatory Compliance Monitoring** — monitor regulatory changes, map to internal policies

### 5.5 Admin Agent — 1 use case

- **UC10: Internal Knowledge Q&A** — general-purpose enterprise assistant grounded on internal documentation

### 5.6 Multi-Agent Orchestration

The proposal envisions agents collaborating:
- Procurement Agent flags a missing certificate → Legal Agent checks regulatory requirement → Admin Agent notifies the vendor
- This requires the orchestrator layer to support inter-agent communication, shared context, and workflow routing

**Effort**: Very High (multi-month). Each agent is 4-8 weeks; orchestration layer is additional 4-6 weeks.

---

## 6. Infrastructure & Deployment

### 6.1 Production Architecture

- Docker Compose → Kubernetes (for scale)
- PostgreSQL (managed: Azure Database for PostgreSQL or RDS)
- Redis (caching, session store, Celery broker)
- Qdrant or Azure AI Search (vector store)
- Keycloak (OIDC/SSO)
- Monitoring: Prometheus + Grafana, or Azure Monitor
- Logging: ELK stack or Azure Log Analytics
- CI/CD: GitHub Actions → Docker build → K8s deploy

### 6.2 Azure-Specific (proposal alignment)

- Azure OpenAI Service (GPT-4o, embeddings)
- Azure Document Intelligence (OCR)
- Azure Blob Storage (documents)
- Azure Container Apps or AKS (compute)
- Azure Monitor + Application Insights (observability)
- Azure Key Vault (secrets management)
- Compass API + JAIS (Arabic language model, proposal-specific)

### 6.3 Performance & Scale

- Load testing with realistic document volumes
- Embedding pipeline optimization (batch processing, GPU acceleration)
- Response latency SLAs (< 3s for chat, < 30s for full validation)
- Concurrent user support (WebSocket pools, connection limits)
- Document volume targets (from proposal: thousands of vendor documents)

---

## 7. Branches to Revisit

Code that was identified during the audit but not cherry-picked for the demo:

| Branch | What it has | When to use it |
|---|---|---|
| `feat/qdrant` | Qdrant config + Docker service | When migrating from FAISS to managed vector store |
| `feat/metadata-indexing` | Per-format metadata extraction + filtered retrieval | When adding filtered search (by date, type, source) |
| `feat/create-vector-store-api` | Rich ChunkingParams + EmbeddingParams models | When building the Knowledge Base management UI |
| `feat/keycloak` (full) | OIDC realm + middleware | When implementing real authentication |
| `develop` | Celery + RabbitMQ + PostgreSQL | When adding async processing and scaling |

---

## 8. Quality & Testing

### 8.1 Evaluation Framework

- RAG quality metrics: precision, recall, MRR, NDCG on retrieval
- LLM output quality: factuality, relevance, coherence scoring (LLM-as-judge)
- Agent-level evaluation: task completion rate, decision accuracy, trace quality
- Regression suite for prompt changes
- Benchmarking infrastructure (from `benchmarking--*` branches)

### 8.2 Safety & Compliance Testing

- Hallucination resistance testing
- Prompt injection / jailbreak resistance
- PII leakage detection
- Bias evaluation
- From WEBAPPFACTORY mockups: "Phare-LLM Safety" scoring concept (hallucination resistance, harm resistance, jailbreak resistance, bias score)

---

## Priority Summary

| Priority | Item | Effort | Impact |
|---|---|---|---|
| **P0** | PostgreSQL + proper models | 1-2 weeks | Foundation for everything |
| **P0** | Keycloak full OIDC | 2-3 weeks | Enterprise requirement |
| **P0** | Next.js frontend (core pages) | 4-6 weeks | Product face |
| **P1** | OCR + multi-format ingestion | 2-3 weeks | Real-world document handling |
| **P1** | HITL reviewer workflow | 4-6 weeks | Enterprise compliance |
| **P1** | Async processing (Celery) | 2-3 weeks | Scale + reliability |
| **P2** | Managed vector store | 1 week | Production infrastructure |
| **P2** | Multi-provider LLM routing | 2-3 weeks | Cost optimization + resilience |
| **P2** | Guardrails pipeline | 4-6 weeks | Enterprise safety |
| **P3** | Additional agents (HR, Finance, Legal, Admin) | 4-8 weeks each | Full proposal delivery |
| **P3** | Multi-agent orchestration | 4-6 weeks | Platform differentiation |
| **P3** | ERP/M365 integrations | 6-10 weeks each | Client ecosystem |
