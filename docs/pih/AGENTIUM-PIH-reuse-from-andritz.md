# Reusing the Andritz blocks to POC the two PIH systems — fast

Companion to `AGENTIUM-PIH-systems-synthesis.md`. Analyses the two systems already built for the **Andritz workspace** — (A) **Expert Knowledge Capture** and (B) **Chat / RAG search over a large KB (OmniRAG)** — and maps the concrete, reusable blocks to stand up the two priority PIH POCs:

- **POC #1 — Sovereign Conversational Service Desk & Knowledge Deflection** (RAG chat over KB, fed/maintained by capture).
- **POC #2 — Proactive Operations & Root-Cause Analysis (FA-RAG / AIOps)** (reuses the retrieval-precision + facts blocks).

> **TL;DR** — the platform ("Agentium"/OmniRAG) is **generic and workspace-multitenant**; *Andritz is a workspace slug + config + data + a handful of baked-in vocab constants*, not bespoke logic. Both PIH POCs are dominated by **workspace provisioning + KnowledgeGuide policy + data/vocab authoring**, not new engineering. The capture→publish→re-index loop is already closed end-to-end.

All paths under `/Users/thibaudishacian/Developer/DATATEGY/papAI/omnirag` (branch `demo/agentic`).

---

## A. System A — Expert Knowledge Capture (feeds & maintains the KB)

**Pipeline:** context anchoring → gap analysis → interview plan (AI / provided / free / co-build) → voice/text session with per-turn evaluation → RAG-grounded quality oracle → structuring → human review (accept/amend/reject) → **publish → re-ingest into the KB** → append-only audit ledger.

**Reusable backend (client-agnostic):**
- `backend/app/services/knowledge_capture.py` — the whole capture engine (`build_knowledge_gaps`, `build_interview_plan`, `append_turn`, `evaluate_expert_answer`, `process_conversation_step`, `structure_capture_payload`, `review_proposal`, `publish_proposal_to_knowledge`).
- `backend/app/services/capture_knowledge_oracle.py` — RAG-grounded gap scoring + numeric/claim contradiction detection.
- `backend/app/services/capture_report_templates.py` — knowledge-sheet templating (`default` is generic; `andritz_knowledge_v1`/`industrial_v1` are opt-in).
- `backend/app/services/voice_runtime.py` / `voice_session_gateway.py` — STT/TTS abstraction (cascade today; realtime gated).
- Closed loop: `publish_proposal_to_knowledge` → `DocumentService.ingest_document(..., source_type="expert_fiche")` → structured facts land in `KnowledgeDocumentFact` / `KnowledgeTableFact` (queryable, RCA-grade).

**Models:** `models/expert_capture.py` (`ExpertCaptureSession`, append-only `ExpertCaptureEvent`, `KnowledgeUpdateProposal`), `models/knowledge_guide.py` (versioned `KnowledgeGuide`), `models/knowledge_collection.py`, `models/knowledge_document_fact.py` / `knowledge_table_fact.py` (`semantic_type, subject, predicate, value_numeric, unit, evidence_locator, confidence`).

**API:** `api/v1/endpoints/knowledge_capture.py` (`/api/v1/knowledge-capture/*` — plans, sessions, turns, conversation-step, events/amend, multi-pin documents, proposals/review/publish, quality-backlog). `knowledge.py` (`/knowledge/guides`, `/knowledge/document-query`, `/knowledge/table-query`).

**Frontend (Angular, no Andritz hardcoding):** `frontend-ng/.../knowledge/knowledge-capture.component.ts` (capture cockpit: dashboard → prep → plan → session w/ MediaRecorder + live transcript + multi-pin doc tray → review → publish) and `knowledge-view.component.ts` (knowledge-guide markdown editor + versioning). System-scoped entry `/systems/:id/capture`.

**Connectors / ingestion:** upload + batch, **secure deposit** (`services/secure_deposit*.py`), **SFTP**, **SharePoint** (`services/connectors/sharepoint_otp/`), formats PDF/DOCX/PPTX/XLSX/CSV/TXT/HTML/images, OCR/VLM (PaddleOCR / Tesseract / OpenAI Vision).

---

## B. System B — Chat / RAG search over large KB (OmniRAG)

**Answer pipeline (orchestrator `services/rag/context.py::retrieve_rag_context`), in order:** indexing → storage (Qdrant named dense+sparse, workspace-scoped `{slug}__{name}`) → profile resolution → history-augmented query → guides+policy → **corpus planning / scope inference / decomposition gate** → mode select (dense vs hybrid) → **multi-source retrieval (dense + BM25/sparse)** → comparative sub-queries (A vs B) → **RRF fusion** (+ adaptive weights) → dedupe → policy rerank + required-terms filter → **cross-encoder rerank** → similarity threshold → **MMR diversity** (optional) → **contextual compression** → parent-context append → table/document evidence prepend → **decision trace** → generation with **deterministic budget** → **grounded citations**.

**Reusable backend (client-agnostic):** `services/rag/{context,pipeline_retrieval,mode_selector,retrieval_profiles,fusion_weights,generation_budget,cross_encoder_stage,mmr_stage,knowledge_scopes,decision_trace,comparative_retrieval,retrieval_policy,sparse_backends,bm25_store,corpus_planner,project_inventory,source_facets}.py`; `services/retrieval/{hybrid,ensemble,rrf,bm25,flash_reranker,contextual_compression,retrieval_plan}.py`; `services/vector_db/{factory,qdrant_db,...}.py`; `services/worker_deep_retrieval.py` (async Deep Search); `services/rag/rag_service.py` (programmatic facade).

**Large-KB scaling (the SPL runbook → `corpus_planner.py`):** intent-classify + scope inference (SQL ledger / pg_trgm facts / offline summaries) without asking the user; catalogue queries answered from inventory SQL (never hit Qdrant); dense-unscoped guardrail (pool hard-capped, deep recommended); per-profile budgets/deadlines; facets (`source_facets.py`, `project_inventory.py`); alias-swap reindex; OpenSearch BM25 in prod.

**Chat API + UI:** `api/v1/endpoints/chat.py` — `POST /chat/stream` (SSE; `chunk_type` ∈ session/text/decision_step/retrieval/sources/error/eval_pending), `/chat/completion`, `/chat/deep-retrieval-jobs`, `/chat/retrieval-plan-preview`. Citation contract: numbered `[1..N]` ↔ `sources[n-1]` (≤8 citable, ≤3 passages/doc). Frontend `frontend-ng/.../features/chat/chat-panel.component.ts` + `core/sse.service.ts` (fetch-POST streaming, renders citations, deep-search & eval polling).

**Evaluation harness:** `services/rag/retrieval_golden.py` + `offline_eval.py`; golden batches in `resources/retrieval_golden/` (8× `andritz_spl_*.json` = data; **`showcase_notices.json` = client-neutral template**); scripts `golden_flag_ab.py`, `run_retrieval_golden_live.py`, `probe_spl_retrieval_scaling.py`.

---

## C. Reuse map — what lifts vs what is Andritz-specific

| Block | Reuse status |
|---|---|
| Ingestion backbone (`DocumentService`, `worker_ingest`, `document_parser/`, `ocr`, `embedding/`, `vector_db/`) | **Lift as-is** |
| Capture engine (`knowledge_capture`, `capture_knowledge_oracle`, voice runtime, default report template) | **Lift as-is** |
| OmniRAG retrieval engine (`context` + all `services/rag/*` + `services/retrieval/*`) | **Lift as-is** |
| Large-KB planner (`corpus_planner`, `project_inventory`, `source_facets` mechanics) | **Lift as-is** |
| Chat API `/chat/stream` + SSE contract + Angular `chat-panel` | **Lift as-is** (rebrand system prompt strings) |
| Capture cockpit + knowledge-guide editor (Angular) | **Lift as-is** |
| Connectors (upload, secure deposit, SFTP, SharePoint) | **Lift as-is** |
| Eval harness *code* | **Lift as-is** |
| Workspace, contexts, scopes, collections, KnowledgeGuides | **Re-create as PIH data** |
| `KnowledgeGuide` policy JSON (```agentium-retrieval-policy```: protected terms, aliases, source families) | **Author for PIH** (replaces ~all "code" tuning) |
| Golden eval set | **Author `pih_*.json`** (copy `showcase_notices.json`) |
| Slug allowlists in `core/config.py` (`*_enabled_workspace_slugs="andritz"`) | **Add `pih`** (small but required) |
| Baked-in vocab constants — `source_facets.DEFAULT_SOURCE_FAMILY_FACETS`, `lexical_retrieval._FAMILY_TERMS`, `chat_grounding._ANDRITZ_FACT_TERMS`, `procurement_agent._AndritzContactBoilerplateStreamFilter` + Andritz lines in `SYSTEM_PROMPT` | **Override / rebrand for PIH** (the real porting work) |

---

## D. POC plan — the two PIH systems in ~days each

### POC #1 — Conversational Service Desk & Knowledge Deflection
Reuses **System B end-to-end** + **System A** to build/maintain the KB.
1. Provision a `pih` workspace; add `pih` to the config slug allowlists; run migrations; seed skills/capabilities.
2. Ingest the PIH KB (policies, SOPs, the existing knowledgebase behind use cases #18/#19) via upload/SFTP/SharePoint → Qdrant collection; define a `knowledge_scope`.
3. Author a PIH `KnowledgeGuide` policy JSON (protected terms, aliases, source families); override the four vocab constants in §C.
4. Reuse `/chat/stream` + `chat-panel` unchanged; set `grounding_mode=balanced` (deflection) and rebrand the system prompt; strip the Andritz boilerplate filter.
5. Stand up the KB via the capture cockpit for any tacit/expert content (closed loop already publishes into the same collection).
6. Seed `pih_*.json` golden set; tune profiles/flags with `run_retrieval_golden_live.py` / `golden_flag_ab.py`.
- **Showcases:** sovereign grounded RAG + citations + evaluation. **KPIs:** deflection %, MTTR, grounded-answer %, CSAT.
- **Gap to package:** a thin "deflection" UX wrapper (Q → cited answer → *escalate to ticket via* `itsm.create_ticket`); the retrieval + capture primitives already exist.

### POC #2 — Proactive Operations & RCA (FA-RAG)
Reuses the **precision-oriented subset** of System B + the **structured facts** from System A.
1. Ingest ITSM ticket history + runbooks/KB into a PIH collection; structured facts land in `KnowledgeDocumentFact`/`KnowledgeTableFact`.
2. Retrieval for RCA: `corpus_planner` scope inference (per machine/asset/category), `comparative_retrieval` (failing vs healthy unit), `retrieval_policy` required-terms + cross-project guard (no evidence bleed across assets), `cross_encoder_stage` for precision, `decision_trace` for auditable evidence chains, `worker_deep_retrieval` for deep passes; `grounding_mode=strict`.
3. Query structured facts via `/knowledge/document-query` & `/table-query`; cluster recurring incidents / trends for the proactive layer.
4. Wrap with the RCA reasoning (Datategy's FA-RAG / Big GCVAE line) over these grounded, cited passages + facts.
- **Showcases:** owned RCA innovation, source-anchored verifiable answers, proactive prevention. **KPIs:** recurring-incident reduction %, RCA recommendation acceptance, MTTR↓.
- **Gap to package:** an **RCA egress/agent** over the facts + `kc.proposal.published` events (the data contract — `recommended_ingestion`, `evidence_locator`, `confidence`, `open_questions` — is already RCA-shaped); the retrieval/grounding/facts substrate is reused as-is.

---

## E. Real engineering gaps (small, shared by both POCs)
1. **Workspace bootstrap script** — no turnkey "new client" provisioner yet; assemble from `systems/bootstrap.py` + `scripts/setup_andritz_notices_spl.py` patterns.
2. **Config externalization** — move the `*_enabled_workspace_slugs` allowlists from defaults to env/`workspace.settings` so `pih` gates voice/deposit/IAM.
3. **Vocab constants → policy** — the four baked-in Andritz term sets (§C) should be overridden for PIH (ideally migrated into KnowledgeGuide policy).
4. **RCA egress connector/agent** (POC #2 only) — the only genuinely new component.
5. *(Optional)* near-live STT — capture works today in text + cascade TTS; realtime transcription is a known Phase-0 gap.

**Bottom line:** both PIH POCs are ~80% assembly + config over the Andritz-built engine. The only true new code is (POC #1) a deflection-to-ticket wrapper and (POC #2) an RCA egress agent; everything else — ingestion, capture, hybrid retrieval, fusion/rerank/compression, large-KB planning, grounded chat + citations, evaluation — lifts as-is.
