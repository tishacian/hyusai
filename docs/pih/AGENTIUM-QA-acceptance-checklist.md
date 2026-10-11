# Agentium System — QA Acceptance & Delivery Qualification Checklist ("recette")

A reusable recipe a QA uses to **qualify** (pass/fail, sign-off) a delivered Agentium system before go-live.
Engagement example: PIH / PowerMind AI Service Desk (the 39 use cases, the 4 POC systems). Reusable for any Agentium delivery.
Aligned with the existing QA practice (`outputs/019edc68-andritz-qa/`): Feature → Test → Execution evidence → Defect → Exit criteria, with coverage audits (scope · events · config · permissions · frontend action/API · taxonomy · execution safety).

> Confidential — internal. A delivery is **qualified** only when every **must-pass** gate (★) is green, **0 open Critical/High defects**, and the **sovereignty egress** check is clean.

---

## 0. How to use
- Each item is a **gate** with: *what to verify · pass criteria · evidence to attach*.
- Status per item: ☐ Pass / ☐ Fail / ☐ Blocked / ☐ N/A (justify N/A).
- Evidence = a **run ID**, an **audit/ledger export**, a **golden report**, a **screenshot**, or a **coverage audit JSON** — never "looks fine".
- Severity of defects: **Critical** (data loss / security / sovereignty breach / out-of-mandate action), **High** (core flow broken / wrong result), **Medium** (degraded), **Low** (cosmetic).
- Final qualification = §8 exit criteria + sign-off.

## 1. Entry criteria — the delivery package (no QA starts without it)
- ☐ **System manifest**: systems, flows, skills, capabilities, connectors, mandates/policies, KB/scopes (versioned).
- ☐ **Spec & traceability**: business requirements / use-case list (e.g. the 39) → flows; acceptance criteria per flow.
- ☐ **Environments**: an isolated **staging/sandbox** (own workspace slug) with **synthetic identities/data**; connectors pointing to **sandbox tenants**.
- ☐ **Test data & golden set**: representative corpus + a `*_golden.json` evaluation batch.
- ☐ **Runbooks & docs**: operational runbook, API reference, rollback/cutover plan, config inventory.
- ☐ **Build/version pinned**: image/commit recorded; migrations applied.

## 2. Test execution safety (do-no-harm) ★
- ☐ QA runs in **staging/sandbox only**; **no mutation of production** directory, mailboxes, ITSM, ERP.
- ☐ Privileged write-actions tested in **simulate / dry-run** first; a single real write only against a **sandbox** account.
- ☐ Connectors use **sandbox credentials**; no production secrets in test config.
- ☐ Static/read-only coverage audits do not call live backend/VM/SFTP/vector/object-store (per existing audit safety model).
- ☐ Synthetic PII only; test data purged after run.

---

## 3. Qualification dimensions (the checklist)

### A. Scope & functional coverage ★
- ☐ Every spec'd feature / use case has **≥1 test + execution evidence** (scope-coverage audit = 100%, 0 missing fields).
- ☐ Each flow produces the **expected business outcome** on the happy path (acceptance criteria met).
- ☐ Brownfield: each migrated legacy use case (e.g. PIH **39/39**) reaches **parity or better** vs legacy (side-by-side).

### B. Flow correctness & branches ★
- ☐ Every flow's **branches** execute: Main · **Rejected · Missed-approval · Failed** (maps 1:1 to the spec's "agents per flow").
- ☐ HITL gates trigger correctly; **approval reminders / escalation** fire (e.g. up to N reminders); timeouts handled.
- ☐ **Idempotency**: re-running a completed flow does not double-apply side-effects.
- ☐ Error paths create a ticket / assign to a human as specified (no silent failure).

### C. Skills & tool-calling
- ☐ Each **skill** returns correct output on valid input; **graceful, typed errors** on invalid input.
- ☐ External tool-calls handle timeout / rate-limit / partial failure; retries bounded.
- ☐ No unintended side-effects in dry-run mode.

### D. Conversational / RAG quality (if applicable) ★
- ☐ Answers are **grounded & cited**: every `[n]` maps to a real source (`sources[n-1]`); strict mode refuses ungrounded answers.
- ☐ **Hallucination / unsupported-claim rate** below threshold on the golden set.
- ☐ **Deflection** works (answerable → answered, not ticketed); escalation on low confidence.
- ☐ **Golden batch ≥ target** (matched-sources, no forbidden/missing-evidence); anti-overfit (live path never reads golden data).

### E. Robustness — stateful runs, replay, resubmission ★
- ☐ Kill mid-run → **resume from checkpoint**, no corruption.
- ☐ **Replay** of a past run reproduces the decision (or emits a **discrepancy report** if inputs changed).
- ☐ **Resubmission with overrides** works; parent-child lineage intact.
- ☐ Concurrency: parallel runs do not interfere; no race on shared state.

### F. Security & identity ★
- ☐ **RBAC**: role × action matrix enforced; negative tests (denied actions actually denied).
- ☐ **ABAC**: attribute conditions enforced (scope/entity/time).
- ☐ **Distinct agent identity**: an agent cannot exceed the principal who mandated it.
- ☐ **Multi-tenant / multi-entity isolation**: no cross-workspace/entity data leak (vector, relational, object store).
- ☐ Secrets handling: no secrets in logs/exports; rotation works.
- ☐ Permission-coverage audit = all roles & sensitive endpoints tested.

### G. Governance, mandates & audit ★
- ☐ Every **privileged action** appears in the **tool-calling ledger** (timestamped, costed, attributed).
- ☐ **Mandate / control-policy guardrails** enforced: out-of-mandate action is **blocked by construction** (caps, scope, duration); revocation is immediate.
- ☐ **Decision trail** explains each decision; **audit log is tamper-evident and exportable** (JSON/CSV).
- ☐ Event-coverage audit: all emitted events/SSE chunk types behave (session/text/decision_step/retrieval/sources/error/eval_pending).

### H. Evaluation & quality gates
- ☐ **Auto-scoring** runs on outputs; **thresholds gate** auto-resolution vs human review.
- ☐ **Review queue** populated for low-confidence/sensitive items.
- ☐ **Drift / non-regression**: a change must prove it does ≥ baseline on the golden set before rollout (dress-rehearsal); **rollback** on regression.

### I. Human-in-the-loop (HITL)
- ☐ Approvals routed to the right approver(s); multi-level chain respected.
- ☐ **Autonomy tiers** honoured (autonomous / approve-then-act / recommend-only).
- ☐ Reviewer can amend / reject / request changes; corrections are reinjected.

### J. Connectors & integration ★
- ☐ Each connector (AD/Entra · M365 Graph/Exchange · SuccessFactors · Oracle · ITSM · Teams/email · SharePoint/SFTP): **auth + happy path + error/rate-limit + data mapping** validated.
- ☐ Field mapping correct (no truncation / encoding loss); idempotent writes.
- ☐ Frontend-API coverage audit: every UI action maps to a working API call (incl. loading/empty/error states).

### K. Data & knowledge
- ☐ Ingestion (upload/SFTP/SharePoint/deposit) works for all required formats; OCR/VLM where needed.
- ☐ **KB isolation** per workspace/scope; dedup; structured **facts queryable**.
- ☐ Data **residency** respected (data stays in boundary).

### L. Performance, capacity & cost
- ☐ **Latency vs SLA** per retrieval/answer profile (fast/balanced/deep) met under nominal load.
- ☐ **Generation/token budget** caps enforced; cost per answer within target.
- ☐ **Load/concurrency** test at target volumes (multi-entity, peak); graceful degradation, **priority/QoS** honoured.

### M. Observability & analytics ★
- ☐ KPI dashboards correct & live: **MTTR · deflection % · automation effectiveness · CSAT · ROI · SLA compliance**.
- ☐ Numbers reconcile with the run ledger (spot-check).
- ☐ Run visibility (status, traces) + alerting on failures.

### N. Sovereignty & deployment ★
- ☐ Deploys **on-prem / private / air-gap**; models served inside the boundary.
- ☐ **Egress check**: no phone-home / no unexpected outbound calls (network capture clean).
- ☐ Offline metering/licensing reconciles without external calls (if applicable).

### O. Migration acceptance (brownfield) ★
- ☐ Each legacy use case **assessed → migrated → validated**; parity report signed.
- ☐ Cutover & **rollback** rehearsed; no orphaned legacy automation.

### P. UAT / business acceptance ★
- ☐ Business users validate **outcomes vs business requirements & KPIs** (not just technical pass).
- ☐ Sign-off per value stream (answer/deflect · request→fulfil · identity lifecycle · proactive→prevent).

### Q. Documentation & enablement
- ☐ Operational runbook, API reference, architecture diagram, config inventory delivered & accurate.
- ☐ Knowledge-transfer / AI-Academy session done; client can author/extend flows (CoE readiness).

### R. Go-live readiness & hypercare ★
- ☐ Go/No-Go checklist complete; rollback tested; on-call & escalation defined.
- ☐ **Hypercare plan** (≥30 days) in place; defect SLAs agreed.

---

## 4. Test taxonomy (levels & methods)
| Level | What | Method |
|---|---|---|
| Skill / unit | one skill / tool-call | fixtures, mocked connectors |
| Flow | a single flow incl. branches | scenario tests, dry-run + simulate |
| Integration | connector ↔ system | sandbox tenants |
| End-to-end | full value stream incl. HITL | staging, synthetic identities |
| Regression / golden | RAG & decision quality | `*_golden.json` batch, anti-overfit |
| Replay regression | reproducibility | replay past runs, discrepancy report |
| Non-functional | perf / load / security / sovereignty | load test, egress capture, pentest-lite |
| UAT | business acceptance | business users vs KPIs |

## 5. Defect management
- Register every defect: id · severity · dimension · flow/skill · steps · evidence · status.
- Re-test on fix; link the closing **run ID / audit export**.

## 6. Coverage audits to attach (static, read-only)
Scope · Event · Config (every flag/profile/policy/threshold/mandate tested at its set value) · Permission · Frontend-action · Frontend-API · Test-taxonomy · Test-execution-safety · Execution-progress.

---

## 7. Qualification matrix (template the QA fills)
| Feature / use case | System / flow | Dimension(s) | Tests | Evidence (run ID / export) | Status | Defects | Owner |
|---|---|---|---|---|---|---|---|
| … | … | A,B,F,G… | n | … | Pass/Fail | … | … |

Roll-up: `feature_count`, `test_count`, `execution_evidence_count`, `defect_count`, `open_defect_count`, `open_critical_high_defect_count` (must be **0**).

## 8. Exit criteria & sign-off ★
- ☐ 100% of **must-pass (★)** gates green.
- ☐ Scope coverage = 100% of spec'd features (0 missing fields); brownfield 39/39 at parity.
- ☐ **0 open Critical/High** defects.
- ☐ Golden set ≥ target; replay reproducible; sovereignty egress clean; isolation verified.
- ☐ KPI dashboards reconcile; UAT signed.

**Sign-off (RACI):** QA Lead (accountable) · Governance Officer (security/mandates/audit) · Business Owner (UAT/KPIs) · Datategy Delivery Lead (build) · Client IT Owner (operate). Qualification is granted only when all five sign.
