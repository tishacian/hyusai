# Skills Runtime — Slug → Module Mapping

Agentium composes Systems from canonical Skills. A Skill is a stable
slug (e.g. `llm_rag_answer_v1`) that the Skills Registry maps to a
Python wrapper; the wrapper then delegates to the real implementation.

The registry lives at
`backend/app/services/skills_registry/wrappers.py` and exposes a
tri-state status via `GET /skills/runtime-health`:

- `bound` — wrapper exists **and** the implementation module imports.
- `stub`  — wrapper exists but only returns a placeholder payload
  (feature not shipped yet or waiting for a third-party credential).
- `unbound` — no wrapper registered at all; `run_engine` falls through
  to `_unimplemented` and records an error outcome.

---

## Canonical mapping

| Skill slug                 | Status | Runtime module                                       | Notes                                                                 |
|----------------------------|--------|------------------------------------------------------|-----------------------------------------------------------------------|
| `llm_rag_answer_v1`        | bound  | `app.services.rag.rag_service`                       | RAG answer with prompt_type + rag_mode_override + model overrides.     |
| `semantic_search_v1`       | bound  | `app.services.rag.pipeline_retrieval`                | Retrieval without synthesis (used by drill-downs).                     |
| `document_ingestion_v1`    | bound  | `app.services.rag.document_service`                  | Canonical ingestion pipeline used by `/documents/*`.                   |
| `eval_radar_v1`            | bound  | `app.services.evaluation.judge`                      | LLM-as-judge composite radar.                                          |
| `claim_audit_v1`           | bound  | `app.services.evaluation.judge`                      | Claim-level faithfulness audit.                                        |
| `intelligence_batch_v1`    | bound  | `app.services.intelligence.batch`                    | News / RSS harvest and reranking.                                      |
| `sharepoint_ingestion_v1`  | stub   | —                                                    | Wire once SharePoint credentials are provisioned.                      |
| `voice_transcribe_v1`      | stub   | —                                                    | Browser records → backend Whisper; wire endpoint later.                |
| `voice_tts_v1`             | stub   | —                                                    | TTS queue; stubbed on backend, used client-side today.                 |
| `audit_log_v1`             | bound  | (self-contained)                                     | Writes a structured log line to the workspace audit stream.            |
| `ollama_llm_v1`            | bound  | `app.services.model_clients.ollama_client`           | Local Ollama chat completion.                                          |
| `azure_llm_v1`             | bound  | `app.services.model_clients.openai_client`           | Azure OpenAI / OpenAI chat completion.                                 |
| `chain_naive_v1`           | bound  | `app.services.rag.chains.naive`                      | Naïve chain migrated from `src/customchain_naive.py`.                   |
| `chain_hybrid_v1`          | bound  | `app.services.rag.chains.hybrid`                     | HAH / hybrid chain migrated from `src/customchain.py`.                  |
| `chain_mixed_hah_v1`       | bound  | `app.services.rag.chains.mixed_hah`                  | CHAH chain migrated from `src/customchainmixedhah.py`.                  |

---

## Legacy custom chains

The three Streamlit-era modules `customchain.py`, `customchain_naive.py`
and `customchainmixedhah.py` used to live under `src/`. They have been
ported into `backend/app/services/rag/chains/` and exposed as canonical
skills (`chain_*_v1`). The archived originals live under
`archive/customchains/` for reference; new work goes into the canonical
modules.

When the Run engine needs HAH or CHAH behaviour it either:

1. Picks `llm_rag_answer_v1` with `rag_mode_override=HAH|CHAH`, which
   routes the RAG service through the appropriate chain, or
2. Invokes the chain skill directly (`chain_hybrid_v1` /
   `chain_mixed_hah_v1`) for operators who want the raw chain semantics
   without the RAG service wrapper.

Both entry points pass through the system-level defaults
(`default_prompt_type`, `default_model`, `retrieval_mode_default`)
injected by `run_engine/engine.py`.

---

## Context propagation

Every skill call receives a `ctx` dictionary with:

- `system_id`, `capability_id`, `workspace_id`, `workspace_slug`
- `input` — the original run input payload
- `default_prompt_type`, `default_model`, `retrieval_mode_default`
  (populated from the active System when set)

Wrappers read `payload.*` first (per-run overrides), then fall back to
`ctx.*` (system defaults). This is the reason
`llm_rag_answer_v1`'s body looks like:

```python
prompt_type=payload.get("prompt_type") or ctx.get("default_prompt_type")
```

Keep that precedence any time you add a new wrapper.
