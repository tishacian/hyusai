# Demo Walkthrough — Vendor Document Validation Agent

**Duration:** 5 minutes  
**URL:** http://217.182.104.99:8000  
**Last QA:** 2026-04-09  
**Status:** All steps validated ✓

---

## Key Messages

1. This is a **simplified illustration** of platform capabilities — not a final product
2. What you see as a single agent is actually an **orchestrated execution of multiple steps** under the hood
3. The platform is both the **Agent interface (facade)** and the **Orchestrator (engine)**

---

## Step-by-Step Flow

### Step 1 — Agent Creation (~45s)

**What to show:** Define the agent's identity, type, system prompt, and capabilities.

**Talking points:**
- The platform lets you **configure agents declaratively** — name, type, system prompt
- "Vendor Compliance Agent" pre-configured for procurement validation
- Capabilities are modular: **RAG Retrieval**, **Document Parsing**, External APIs
- Read aloud the info banner: *"What you see as a single agent is actually an orchestrated execution of multiple steps under the hood"*

**QA status:** Layout OK, form fields editable, capabilities checkboxes work, orchestration message visible.

---

### Step 2 — Model Selection (~30s)

**What to show:** LLM provider selection, model picker, temperature control.

**Talking points:**
- **Multi-provider architecture** — OpenAI selected, but Anthropic and self-hosted (Ollama, vLLM) are supported
- GPT-4o selected at temperature 0.3 (deterministic for compliance)
- LLM-as-a-Service layer: multi-provider routing, SSE streaming, structured output, token tracking
- "The platform isn't locked into a single vendor — this is **model-agnostic by design**"

**QA status:** OpenAI card selected with checkmark, model dropdown works, temperature slider visible, all 5 capability tags shown.

---

### Step 3 — Knowledge Upload (~45s)

**What to show:** Document upload zone, pre-loaded knowledge base, RAG pipeline diagram.

**Talking points:**
- Knowledge base is **pre-loaded** with 2 reference documents (Vendor Qualification Policy, ISO 9001 Checklist) — both marked "Indexed"
- Drag & drop zone accepts PDF, DOCX, TXT, Markdown
- **[LIVE ACTION]** Upload 1-2 real vendor documents during the demo to show live ingestion
- RAG pipeline: Parse → Chunk → Embed → **FAISS Index** → Hybrid Retrieval (BM25 + vector)

**QA status:** Upload zone responsive, pre-loaded docs display correctly with "Indexed" badges, pipeline flow visible. Upload API functional (tested via curl).

---

### Step 4 — Rules & Tools (~30s)

**What to show:** Compliance rules with severity classification, available tools.

**Talking points:**
- 5 validation rules with **severity classification**:
  - CRITICAL: Trade License, Insurance Certificate (blocks approval)
  - MAJOR: Financial Statements, Regulatory Certifications (requires remediation)
  - MINOR: NDA (advisory)
- 2 tools: Knowledge Search (hybrid BM25 + vector), Compliance Engine (rule-based validation)
- "These rules drive the agent's decision-making — **not hardcoded logic, but configurable policies**"

**QA status:** All 5 rules displayed with correct severity badges (red/amber/blue), 2 tool cards visible.

---

### Step 5 — Governance & Audit (~30s)

**What to show:** Access control, audit trail, execution tracing.

**Talking points:**
- **Access Control**: Role-based (Admin/Auditor/User) via OIDC/SSO (Keycloak)
- **Audit Trail**: Every agent execution is logged — currently shows event count
- **Execution Tracing**: Every pipeline step captured with timing via real-time SSE
- "Governance isn't an afterthought — it's **built into the platform from day one**"

**QA status:** 3 governance cards display correctly, audit API returns event count, "No events yet" message shown before first execution.

---

### Step 6 — Execution (~2min)

**What to show:** Live agent interaction with inline orchestration pipeline.

**Pre-configured suggestions:**
1. **TechCorp Solutions (Dubai)** — Partial compliance (missing financials + NDA)
2. **GreenBuild Materials (Berlin)** — Fully compliant
3. **General question** — "What documents are required for vendor qualification?"

**Recommended flow:**
1. Click suggestion 1 (TechCorp — partial compliance) — shows the most interesting validation
2. Watch the **inline tool call cards** appear in real time:
   - QueryRewriter → Router → DocumentIngestion → KnowledgeRetriever → ComplianceEngine → ReportGenerator
   - Each card shows component name, model, duration in ms
3. Read through the **structured compliance report**:
   - Summary of Findings
   - Document Status and Severity (per-document breakdown)
   - Compliance Verdict: "Partial Compliance"
   - Recommended Next Steps
4. Optionally send suggestion 2 (GreenBuild — fully compliant) to contrast

**Talking points during streaming:**
- "Watch how each orchestration step fires in sequence — **this is the pipeline running live**"
- "The agent retrieves from the knowledge base we loaded earlier — **5 relevant chunks found**"
- "The report cites specific policy requirements — this is **grounded in your data, not hallucinated**"
- "Total pipeline execution: under 10 seconds for a full compliance analysis"

**QA status:** Suggestion cards clickable and working. SSE stream delivers tool_call cards inline. Markdown renders correctly (bold, bullets, headers). Input re-enabled after completion. Audit event logged automatically.

---

## API Endpoints Validated

| Endpoint | Method | Status | Response |
|----------|--------|--------|----------|
| `/health` | GET | 200 | `{"status":"healthy","app":"AI Orchestration Platform"}` |
| `/api/v1/health` | GET | 200 | `{"status":"healthy","service":"AI Orchestration Platform"}` |
| `/api/v1/agents` | GET | 200 | 1 agent: procurement (active) |
| `/api/v1/audit/summary` | GET | 200 | Event count, governance active |
| `/api/v1/documents/stats` | GET | 200 | 10 chunks indexed |
| `/api/v1/chat/stream` | POST | 200 | SSE stream with decision_step + text chunks |
| `/api/v1/documents/upload` | POST | 200 | File ingestion functional |
| `/docs` | GET | 200 | Swagger UI accessible |

---

## White-Label Compliance

- **Frontend:** No mention of papAI or DATATEGY — verified via grep
- **Backend responses:** App name = "AI Orchestration Platform"
- **Sample data:** Clean — no brand references
- **Known residual:** 2 references in `backend/app/configuration/` (unused config files, not exposed to users)

---

## Known Limitations (Acceptable for Demo)

- File upload accepts files but parsing quality depends on format (PDF best, DOCX partial)
- Temperature slider on Step 2 is visual only (backend uses 0.3 hardcoded for compliance)
- Sidebar nav links (Knowledge Base, Access & Roles, Audit Logs) are decorative — not wired
- Session persistence not implemented (refresh = reset)
- Reranker disabled (torch dependency skipped for lightweight deployment)

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Server down | SSH to VM: `bash /home/ubuntu/omnirag/run.sh` |
| Blank page | Check: `curl http://217.182.104.99:8000/health` |
| Chat error | Check logs: `tail -50 /home/ubuntu/omnirag/server.log` |
| OpenAI error | Verify key: `grep OPENAI_API_KEY /home/ubuntu/omnirag/backend/.env` |
| Slow response | Normal — GPT-4o takes 5-8s for full compliance report |
