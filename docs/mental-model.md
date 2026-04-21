# Agentium — Mental Model

> Operating system for intelligent systems. Transform business objectives
> into measurable outcomes through composable, observable and adaptive
> AI systems.

This document is the single source of truth for the product's mental
model. The UI, the API and the runtime all share the same vocabulary —
any divergence is a bug.

---

## 1. Vision

Agentium is not an agent builder. It is an **operating system for
intelligent systems**, modelled as a closed feedback loop:

```
Objective → Capability → System → Run → Outcome → Decision → Adaptation
```

The loop is visible in the product at all times. Hypervisor shows the
current balance sheet, Steering lets the operator shape behaviour,
Builder composes Systems from Capabilities and Skills, the Runs browser
shows the execution log, and the Decisions feed captures recommendations
and what-if outcomes.

---

## 2. Canonical entities

| Entity          | Purpose                                                   | API                              |
|-----------------|-----------------------------------------------------------|----------------------------------|
| Capability      | Universal / industry / client outcome blueprint           | `GET /capabilities`              |
| Skill           | Atomic certified unit (RAG answer, classify, extract, …)  | `GET /skills`                    |
| System          | Composed execution graph bound to a Capability            | `GET /systems/{id}`              |
| Context         | Data refs + memory refs + permissions for a System        | `GET /contexts/{id}`             |
| Control policy  | Hard limits (cost / latency / HITL / allowed models)      | `GET /control-plane/policies`    |
| Adaptive policy | Triggers + allowed adaptations (moderate / aggressive)    | `GET /control-plane/adaptive`    |
| Run             | Single execution (skill trail, outcome, cost, confidence) | `GET /runs/{id}`                 |
| Decision        | Recommendation, what-if, adaptive action, manual choice   | `GET /hypervisor/decisions/{id}` |

Legacy aliases (`/agents`, `/traces/traces`) are deprecated and stamped
with `X-Deprecated` response headers.

---

## 3. Per-system configuration

A System carries its own canonical defaults that the Run engine applies
to every Skill invocation:

- `default_prompt_type` — reasoning template (`auto`, `summarization`,
  `comparison`, `multi_hop`, `complex_reasoning`, …).
- `default_model` — LLM slug override for RAG / generative skills.
- `retrieval_mode_default` — `auto`, `fast`, `rich`, `HAH`, `CHAH`.

The chat-panel and the Builder expose these as editable fields; per-run
overrides live on the `ChatRequest` payload (`prompt_type`,
`rag_mode_override`).

---

## 4. Steering & Hypervisor

### Levers (canonical four)

| Lever            | Range       | Effect on projection                          |
|------------------|-------------|-----------------------------------------------|
| resource         | lean → deep | +cost, +value                                 |
| velocity         | thorough → rapid | −latency, −value (slight)                |
| autonomy         | HITL → full | −cost (fewer HITL loops), +risk               |
| risk_tolerance   | cautious → bold | +value ceiling                            |

Hypervisor drives them globally (`POST /hypervisor/what-if`), Steering
drives them scoped to a portfolio or capability (`POST
/control-plane/simulate`). Operators commit via `POST
/control-plane/policies` (ControlPolicy) or `POST
/control-plane/adaptive` (AdaptivePolicy).

### Decision stream

`GET /hypervisor/decisions?status=…&limit=…&offset=…` is paginated.
Each decision carries a rationale, an impact estimate, and a status
(`open` / `accepted` / `rejected` / `applied`). The Hypervisor cockpit
renders the feed with a status filter + a drawer that fetches
`GET /hypervisor/decisions/{id}` for full detail.

---

## 5. Runtime implementation

- Backend is **FastAPI + SQLAlchemy + Alembic**. Canonical routers are
  mounted under `/api/v1/{capabilities|skills|systems|runs|contexts|
  control-plane|hypervisor|reasoning}`. Legacy routers (`/agents`,
  `/traces`) are mounted with a `legacy alias` tag and emit
  `X-Deprecated`.
- Frontend is **Angular 20 zoneless** with signals + computed state.
  The cockpit shell centralises navigation, command palette (`⌘K`),
  semantic zoom (`⌘Z` / `⇧⌘Z`) and theme.
- Skill runtime is documented in
  [`docs/skills-runtime.md`](./skills-runtime.md) — read that file for
  the mapping between canonical skill slugs and Python modules.

---

## 6. Where the UI lives

| Concept              | Frontend route                    |
|----------------------|-----------------------------------|
| Balance sheet        | `/hypervisor`                     |
| What-if levers       | `/hypervisor` (bottom panel)      |
| Decisions feed       | `/hypervisor` (bottom panel)      |
| Steering             | `/steering`                       |
| Contexts             | `/steering/contexts`              |
| Capabilities         | `/capabilities`                   |
| Skills               | `/skills`                         |
| Systems list         | `/systems`                        |
| System detail        | `/systems/:id`                    |
| System builder       | `/systems/new`                    |
| Runs list            | `/runs`                           |
| Run detail           | `/runs/:runId`                    |
| Observability        | `/observability`                  |
| Governance (audit)   | `/governance/audit`               |
| Governance (access)  | `/governance/access`              |

---

## 7. Invariants

- Every Run belongs to one System. Every System belongs to one
  Capability (or none, for `capability: null` sandboxes).
- Every Decision references one scope (`portfolio` / `capability` /
  `system` / `run`). `target_id` is nullable only when scope is
  `portfolio`.
- Per-system defaults (`default_prompt_type`, `default_model`,
  `retrieval_mode_default`) always win over workspace defaults when set,
  and always lose against per-query overrides.
- Adaptive policies carry a `scope` + `target_id` so the Steering
  cockpit can filter them to the currently-focused capability/system.
