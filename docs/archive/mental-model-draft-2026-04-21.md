# Agentium — Mental Model

## 1. Vision

Agentium is not an agent builder.

Agentium is an **operating system for intelligent systems**, designed to transform business objectives into measurable outcomes through orchestrated, observable and optimizable AI systems.

It is the **agentic counterpart of papAI**:
- papAI = orchestration of data, models and workflows
- Agentium = orchestration of intelligence, reasoning and decision systems

Agentium is designed as a **standalone product**, but shares the same architectural philosophy as papAI to enable a future convergence into a unified platform.

---

## 2. Core Paradigm Shift

### From Tools to Systems

Traditional platforms:
- Build workflows
- Configure models
- Execute pipelines

Agentium:
- Defines objectives
- Composes capabilities
- Runs autonomous systems
- Measures value

---

### From Features to Value Loops

Agentium is built around a **closed-loop system**:

Objective → System → Execution → Measurement → Optimization

This loop is the **core mental model** and must be visible in the product at all times.

---

## 3. Core Concepts (Product Language)

Agentium introduces a structured, layered vocabulary:

### System (central concept)

A System is a self-contained unit that:
- Receives an objective
- Uses capabilities
- Executes tasks
- Produces measurable outcomes

```
System = Objective + Flow + Skills + Knowledge + Runs + Impact
```

---

### Capability

A Capability is a **business-level function**:
- “Contract Risk Detection”
- “Document Understanding”
- “Delay Prediction”

Capabilities are what the business buys and understands.

---

### Skill

A Skill is a **cognitive primitive**:
- Typed input/output
- Cost
- Latency
- Metrics
- Version

Examples:
- OCR
- NER
- Classification
- Scoring
- LLM reasoning

Skills are the **atomic units of intelligence**.

---

### Flow

A Flow is a **composition of Skills**.

It represents how intelligence is structured, but is abstracted from most users.

---

### Run

A Run is a **real execution instance** of a System.

---

### Impact

Impact is the **measured value produced**:
- Time saved
- Cost reduction
- Risk avoided
- Revenue generated

---

## 4. Layered Abstraction Model

Agentium is built on progressive disclosure:

### Layer 1 — Business (default)
- Systems
- Capabilities
- Impact (ROI)

### Layer 2 — Operational
- Runs
- Performance
- Errors
- Usage

### Layer 3 — Technical
- Skills
- Flows
- Models
- Tools

The UI must **never force complexity**, but always allow access to it.

---

## 5. UX Principles

### 5.1 Objective-First

The entry point is always:

> “What do you want to achieve?”

Not:
- Create agent
- Configure workflow

---

### 5.2 System-Centric UX

The UI revolves around Systems, not features.

Users interact with:
- Systems
- Runs
- Impact

Not:
- nodes
- prompts
- pipelines

---

### 5.3 Continuous Canvas

The interface should feel like a **continuous system surface**, not a set of pages.

- No fragmentation
- Context preserved
- Zoom-based navigation

---

### 5.4 Progressive Complexity

- Default = simple
- Advanced = available

Pattern:
- hover → insight
- click → expand
- focus → deep dive

---

### 5.5 Visible Intelligence

Agents are not black boxes.

Minimal “thinking stream”:

- Retrieving knowledge
- Running analysis
- Generating output

No technical overload.

---

### 5.6 System as a Living Entity

Each system has:
- Status (Live / Idle / Error)
- Recent activity
- Evolution over time

This creates trust and engagement.

---

## 6. Value as First-Class Citizen

### Metrics are Product, not Logs

Agentium surfaces:

#### Business level
- ROI
- Time saved
- Cost per task

#### Operational level
- Latency
- Success rate
- Cost/run

#### Technical level
- Model metrics
- Token usage

---

### Pricing Model

Agentium is priced on **Capabilities**, not tokens.

```
Price = Volume × Capability Unit Price
```

Example:
- 0.20€ per contract analyzed

---

### ROI Loop

Every run contributes to:

- cost tracking
- value estimation
- ROI computation

---

## 7. Hypervisor — Strategic Layer

The Hypervisor is not a dashboard.

It is a **decision cockpit**.

---

### Functions

- Aggregate ROI across systems
- Compare capabilities
- Suggest optimizations
- Enable actions

---

### Decision Loop

Observe → Understand → Decide → Act → Measure

---

### Example

```
Capability: Contract Risk Detection

Cost: 3k€
Value: 25k€
ROI: +733%

→ Recommendation: Scale usage
→ Action: Increase budget
```

---

## 8. Capability Catalog

Structured in 3 layers:

### Universal
- Document understanding
- Risk detection
- Forecasting

### Industry
- Fraud detection
- Maintenance prediction

### Client-specific
- Custom business logic

---

## 9. Skill Certification

Each skill is evaluated on:

- Quality
- Performance
- Safety
- Business impact

---

### Certification Levels

- Basic
- Production-ready
- Enterprise-certified

---

This creates:
- trust
- marketplace potential
- differentiation

---

## 10. Strategic Positioning

Agentium sits between:

- n8n (automation)
- Dify (AI builder)
- Dataiku (data platform)

But defines a new category:

> **Skill-based Agentic Operating System**

---

## 11. Relationship with papAI

### Today
- Agentium = standalone agentic platform
- papAI = orchestration & data platform

### Tomorrow
- Unified platform:
  - papAI → data + ML + orchestration
  - Agentium → intelligence + systems + ROI

---

## 12. Core Differentiators

1. Objective-driven UX  
2. Skill-based architecture  
3. Capability-based pricing  
4. Built-in ROI measurement  
5. Closed-loop optimization  
6. Hypervisor decision layer  

---

## 13. Final Positioning

Agentium is not:
- a workflow builder
- an LLM interface
- an agent playground

Agentium is:

> **a system that turns business objectives into measurable, governed, and continuously optimized outcomes**

---

## 14. Key Product Statement

> You don’t build agents.  
> You compose intelligence into systems that generate measurable value.

---

## 15. API & Data Model

Agentium’s internal architecture is designed to reflect its conceptual model.

### Core Objects

#### System

```
System {
  id
  name
  objective
  capabilities[]
  flow_id
  status
  roi_metrics
  created_at
}
```

---

#### Capability

```
Capability {
  id
  name
  description
  input_schema
  output_schema
  skill_ids[]
  pricing_unit
  roi_model
}
```

---

#### Skill

```
Skill {
  id
  name
  type
  version
  input_schema
  output_schema
  cost_per_call
  latency
  metrics
  certification_level
}
```

---

#### Flow

```
Flow {
  id
  name
  skill_graph
  execution_mode
}
```

---

#### Run

```
Run {
  id
  system_id
  input_payload
  output_payload
  cost
  latency
  success
  timestamp
}
```

---

#### Impact

```
Impact {
  system_id
  total_cost
  total_value
  roi
  time_saved
  error_reduction
}
```

---

### API Structure

#### Core (internal)

```
/systems
/capabilities
/skills
/flows
/runs
/impact
```

---

#### Business-facing (external)

```
/analyze-contract
/predict-delay
/process-document
```

---

### Design Principles

- Core vocabulary is **stable and versioned**
- External endpoints are **business-oriented and flexible**
- All objects are **traceable and auditable**

---

## 16. UX Mapping (Concept → Screens)

Agentium’s UI directly reflects its mental model.

---

### Systems

**Screen:** Systems List / System Detail

- List of Systems with:
  - Status
  - ROI
  - Last run
- Entry point for most users

---

### System Detail

Tabs or layered views:

- Overview → business KPIs
- Design → flow + skills
- Runs → execution history
- Intelligence → metrics
- Settings → governance

---

### Capability Catalog

**Screen:** Capability Marketplace

- Browse by:
  - Universal
  - Industry
  - Client
- Each capability shows:
  - Description
  - ROI potential
  - Required inputs

---

### Skill Registry

**Screen:** Skill Library

- Visible in advanced mode
- Includes:
  - Certification
  - Performance metrics
  - Versioning

---

### Runs

**Screen:** Execution Timeline

- Each run shows:
  - Status
  - Cost
  - Output
  - Steps executed

---

### Hypervisor

**Screen:** Strategic Cockpit

- Portfolio view:
  - ROI per capability
  - Cost vs value
- Recommendations:
  - Scale / stop / optimize
- Actions:
  - Allocate budget
  - Deploy systems

---

### UX Principles Applied

- Same concept names across all screens
- Progressive disclosure:
  - Business → Operational → Technical
- Real-time feedback wherever possible

---

## 17. Migration Strategy — papAI ↔ Agentium

Agentium is designed to converge with papAI without breaking existing paradigms.

---

### Mapping Concepts

| papAI | Agentium |
|------|----------|
| Workflow | Flow |
| Model | Skill |
| Dataset | Knowledge |
| Pipeline | System |
| Endpoint | Capability |
| Job | Run |

---

### Phase 1 — Coexistence

- Agentium runs as standalone
- papAI handles:
  - Data
  - ML
  - Orchestration
- Agentium handles:
  - Agents
  - Capabilities
  - ROI

---

### Phase 2 — Interoperability

- Systems can call papAI workflows
- papAI workflows can call Agentium systems
- Shared:
  - Authentication
  - Governance
  - Logging

---

### Phase 3 — Convergence

Unified platform:

```
papAI = Data + ML + Orchestration
Agentium = Intelligence + Systems + ROI
```

---

### Technical Convergence

- Shared object model (System / Skill / Capability)
- Unified catalog
- Unified monitoring (Hypervisor)

---

### Strategic Goal

> Create a single platform where:
- Data is processed
- Intelligence is composed
- Value is measured
- Decisions are made

---

### Key Constraint

- Never break existing papAI workflows
- Always provide mapping layers

---

### Final Outcome

A unified system where:

> papAI manages computation  
> Agentium manages intelligence  
> Hypervisor manages decisions

---

## 18. Execution & Runtime Model

Agentium’s conceptual model must be grounded in a concrete execution model to ensure scalability, reliability and alignment with papAI orchestration.

---

### 18.1 Runtime Philosophy

Agentium does not execute isolated calls.

It executes **Systems as continuous intelligent processes**.

Each System follows an execution loop:

```
Plan → Act → Observe → Evaluate → Adapt
```

---

### 18.2 System Execution Lifecycle

#### 1. Initialization

- Objective is defined
- Required capabilities are resolved
- Flow is compiled into executable graph
- Dependencies (skills, knowledge, tools) are validated

---

#### 2. Planning Phase

The system determines:
- Which skills to invoke
- In what order or structure
- With what context

This can be:
- Static (predefined flow)
- Dynamic (LLM-driven planning)

---

#### 3. Execution Phase

- Skills are invoked according to the flow
- Each skill execution produces:
  - output
  - cost
  - latency
  - status

Execution modes:
- Sequential
- Parallel
- Conditional
- Event-driven

---

#### 4. Observation Phase

System collects:
- intermediate outputs
- errors
- metrics

This feeds:
- monitoring
- explainability
- adaptation

---

#### 5. Evaluation Phase

System evaluates:
- quality of output
- success criteria
- guardrails compliance

Possible outcomes:
- success
- retry
- fallback
- escalation (HITL)

---

#### 6. Adaptation Phase

System can:
- adjust flow
- switch skills
- re-run steps
- trigger alternative paths

---

### 18.3 Skill Execution Contract

Each skill follows a strict contract:

```
SkillExecution {
  input
  output
  status
  cost
  latency
  metrics
}
```

---

### Guarantees

- Deterministic I/O schema
- Measurable execution
- Traceability per invocation

---

### 18.4 Orchestration Layer

Agentium delegates heavy orchestration to an execution layer:

- papAI workflows (Spark, batch, pipelines)
- Async workers (Celery, queues)
- Event-driven triggers

---

### Integration Pattern

```
Agentium System
    ↓
Flow Execution Engine
    ↓
Skill Calls / papAI Workflows / External APIs
```

---

### 18.5 Error Handling & Resilience

Agentium must handle:

- transient failures → retry
- deterministic failures → fallback
- critical failures → escalation

---

### Retry Strategy

- exponential backoff
- max attempts
- alternative skill selection

---

### 18.6 Checkpointing

To support long-running systems:

- intermediate states are persisted
- system can resume from checkpoint
- partial recomputation is possible

---

### Example

```
Run interrupted at step 3
→ Resume from step 3
→ No full recompute
```

---

### 18.7 Multi-Agent Coordination

Agentium supports multiple coordination patterns:

---

#### Sequential

```
Agent A → Agent B → Agent C
```

---

#### Parallel

```
Agent A
   ↘
    → Merge → Output
   ↗
Agent B
```

---

#### Hierarchical

```
Supervisor Agent
   ├── Worker Agent 1
   ├── Worker Agent 2
```

---

#### Federated

```
System A ↔ System B ↔ System C
```

---

### 18.8 Performance & Scaling

Agentium must support:

- horizontal scaling of runs
- parallel skill execution
- distributed processing via papAI

---

### Optimization Levers

- caching skill outputs
- batching requests
- adaptive routing (model / skill selection)

---

### 18.9 Observability

Execution is fully observable:

- per run
- per skill
- per system

---

### Metrics Collected

- cost
- latency
- success rate
- retries
- drift indicators

---

### 18.10 Alignment with papAI

papAI acts as:

- compute layer
- data layer
- orchestration backbone

Agentium acts as:

- reasoning layer
- system abstraction
- ROI layer

---

### Final Model

```
Agentium (System Intelligence)
        ↓
papAI (Execution & Data)
        ↓
Infrastructure (Compute, Storage, APIs)
```

---

### Key Insight

Agentium does not replace orchestration.

It **elevates orchestration into intelligent, adaptive and value-driven systems**.

---

## 19. Concrete Runtime Definitions

This section turns the execution model into an explicit product and engineering specification.

---

### 19.1 Runtime Orchestration Modes

Agentium supports three native execution modes.

#### Synchronous Runtime

Used for short, bounded, request-response interactions.

Characteristics:
- single request lifecycle
- immediate response expected
- low orchestration depth
- no long blocking human step
- strict timeout and SLA

Typical use cases:
- short RAG answer
- classification
- lightweight scoring
- contract clause extraction on a single file

Contract:
- a `Run` is still created
- execution must complete within the sync SLA
- no unbounded planning loop is allowed

---

#### Asynchronous Runtime

Used for long-running, batch, high-cost, or resumable systems.

Characteristics:
- durable run state
- worker-based execution
- resumable from checkpoints
- retry and fallback support
- optional HITL pauses

Typical use cases:
- batch document analysis
- narration pipelines
- translation review flows
- multi-agent investigations

Contract:
- every async execution has a persistent `run_id`
- state transitions are auditable
- partial recomputation must be possible

---

#### Event-Driven Runtime

Used for reactive systems triggered by external or internal events.

Characteristics:
- event subscription or webhook trigger
- automatic run creation
- correlation between source event and execution
- replay-safe and idempotent behavior

Typical triggers:
- new file in SFTP
- new document in GED or SharePoint
- webhook from CRM or ERP
- threshold exceeded in Hypervisor
- model drift alert

Contract:
- each event produces a correlated `Run`
- duplicate events must not create duplicate side effects
- replay must be supported when possible

---

### 19.2 Canonical Agent Loop

Every adaptive system follows the same runtime loop:

```text
Plan → Act → Observe → Evaluate → Adapt
```

#### Plan

The system turns an objective into an executable strategy.

Produces:
- selected capability
- selected skills
- execution ordering
- resource budget
- stopping conditions

Planning can be:
- static
- dynamic
- hybrid

---

#### Act

The system invokes skills, tools, APIs, knowledge retrieval, or sub-systems.

Each action must emit:
- input reference
- output
- status
- latency
- cost
- metrics

---

#### Observe

The system captures execution evidence.

Observed signals:
- intermediate outputs
- confidence
- errors
- cost progression
- time progression
- guardrail flags

---

#### Evaluate

The system compares observed results with success criteria.

Possible decisions:
- continue
- retry
- fallback
- escalate
- finish

---

#### Adapt

The system updates its execution strategy.

Possible adaptations:
- switch skill
- change model
- alter flow path
- reduce cost tier
- invoke HITL

---

### 19.3 Skill Invocation Contract

A Skill is not a loose tool call. It is a typed, metered and versioned execution primitive.

#### Skill Definition Contract

```json
{
  "skill_id": "ocr_layout_v2",
  "version": "2.1.0",
  "type": "perception.v1",
  "input_schema": {},
  "output_schema": {},
  "execution": {
    "mode": "sync",
    "timeout_ms": 15000,
    "retryable": true,
    "idempotent": true
  },
  "pricing": {
    "unit": "page",
    "base_cost": 0.01
  },
  "metrics": {
    "quality": ["confidence", "accuracy"],
    "operational": ["latency_ms", "cost"]
  },
  "certification_level": "production-ready"
}
```

---

#### Skill Execution Record

```json
{
  "invocation_id": "inv_123",
  "skill_id": "ocr_layout_v2",
  "system_id": "sys_contract_risk",
  "run_id": "run_456",
  "input_ref": "blob://doc_001/page_3",
  "output": {},
  "status": "success",
  "cost": 0.01,
  "latency_ms": 928,
  "metrics": {
    "confidence": 0.94
  },
  "trace": {
    "started_at": "...",
    "ended_at": "...",
    "attempt": 1
  }
}
```

---

#### Mandatory Guarantees

Every production skill must guarantee:
- typed input/output
- explicit version
- measurable cost
- measurable latency
- auditable execution
- standard status model
- retry policy declaration

---

### 19.4 Error Handling and Retry Grammar

Failures are part of the runtime. Agentium standardizes them.

#### Failure Classes

##### Transient Failure
- timeout
- temporary API outage
- rate limit

Policy:
- automatic retry
- exponential backoff
- jitter
- max attempts

---

##### Deterministic Failure
- invalid schema
- unsupported input
- corrupted document

Policy:
- no blind retry
- fail fast
- optional alternative path

---

##### Quality Failure
- low confidence
- incomplete output
- weak retrieval
- guardrail soft fail

Policy:
- retry with alternative skill or model
- evaluator pass
- optional human review

---

##### Critical Failure
- safety breach
- severe compliance issue
- hard guardrail failure

Policy:
- stop immediately
- alert
- escalation

---

#### Canonical Retry Policy

```yaml
RetryPolicy:
  transient:
    max_attempts: 3
    strategy: exponential_backoff
    jitter: true
  quality:
    max_attempts: 1
    allow_fallback: true
  deterministic:
    retry: false
  critical:
    retry: false
    escalate: true
```

---

### 19.5 Checkpointing Model

Checkpointing is mandatory for long-running or high-cost systems.

#### What is checkpointed
- current step
- completed skill list
- partial outputs
- accumulated cost
- accumulated latency
- execution context
- chosen flow path

---

#### Checkpoint Record

```json
{
  "checkpoint_id": "cp_789",
  "run_id": "run_456",
  "step": "risk_scoring",
  "state": {
    "completed_skills": ["ocr_layout_v2", "clause_extraction_v1"],
    "partial_outputs": {},
    "cost_so_far": 0.11
  },
  "resume_token": "..."
}
```

---

#### Resume Rules
- resume from last valid checkpoint
- avoid full recomputation by default
- preserve cost traceability
- preserve skill version traceability

---

### 19.6 Multi-Agent Coordination Patterns

Agentium supports a limited but explicit set of coordination patterns.

#### Sequential Pattern

```text
Agent A → Agent B → Agent C
```

Use when:
- steps are strictly dependent
- output must be progressively refined

---

#### Parallel Pattern

```text
           → Agent B →
Agent A →                 → Merge
           → Agent C →
```

Use when:
- multiple sources or analyses can run independently
- merge logic is well defined

---

#### Router Pattern

```text
Input → Router Agent → Legal Agent | Finance Agent | Technical Agent
```

Use when:
- different domains require different systems or skills
- knowledge bases are separated
- cost-aware routing matters

---

#### Hierarchical Pattern

```text
Supervisor Agent
 ├── Worker Agent 1
 ├── Worker Agent 2
 └── Worker Agent 3
```

Use when:
- one lead agent plans and coordinates
- workers are specialized
- evaluation and synthesis are centralized

---

#### Evaluator Pattern

```text
Producer Agent → Evaluator Agent → Accept | Retry | Escalate
```

Use when:
- output quality is critical
- a second pass is required before publication

---

#### HITL Pattern

```text
System → Human Review → Resume System
```

Use when:
- confidence is low
- decision risk is high
- regulatory validation is required

---

### 19.7 Runtime-to-Pricing Consistency

The runtime and pricing model must remain aligned.

#### Internal Cost Model

Internal runtime cost is computed from:
- skill invocations
- retries
- tool calls
- orchestration overhead
- storage and checkpointing
- optional HITL

```math
Internal\ Cost = \sum SkillInvocations + \sum ToolCalls + Orchestration + Retries + HITL
```

---

#### External Pricing Model

The client is not charged on raw runtime complexity.

The client buys a Capability unit:
- per contract analyzed
- per document processed
- per prediction generated
- per dossier reviewed

```math
Capability\ Revenue = Volume \times UnitPrice
```

---

#### ROI Model

```math
ROI = \frac{ValueGenerated - InternalCost}{InternalCost}
```

---

#### Product Rule

- client buys a **Capability**
- runtime executes a **System**
- system invokes **Skills**
- Hypervisor pilots **Impact**

This is the non-negotiable chain of coherence.

---

### 19.8 Canonical Objects for Execution and Pricing

#### System

```yaml
System:
  id: sys_contract_risk
  objective: Detect contract risk
  capability: contract_risk_detection
  execution_mode: async
  coordination_pattern: hierarchical
  pricing_mode: per_capability_unit
  roi_model: legal_review_time_saved
```

---

#### Run

```yaml
Run:
  id: run_2026_001
  system_id: sys_contract_risk
  status: completed
  checkpoints: 4
  retries: 1
  cost_internal: 0.14
  revenue_allocated: 0.20
  impact:
    time_saved_minutes: 18
    confidence: 0.92
```

---

#### Hypervisor View

```yaml
HypervisorView:
  capability: contract_risk_detection
  volume_month: 12000
  total_cost: 1680
  total_revenue: 2400
  estimated_value: 84000
  roi: 49.0
  recommendation: Scale usage and allocate premium model only for low-confidence cases
```

---


### 19.9 Operational Recommendation

The recommended operating model is:
- sync for bounded interactions
- durable async for production systems
- event-driven for reactive automation
- hierarchical coordination as default multi-agent pattern
- strict skill contracts in all production flows
- retry + fallback + escalation as standard resilience grammar
- capability-based pricing in customer-facing packaging
- Hypervisor as the strategic surface where runtime metrics become financial and operational decisions

---

## 20. Execution Modes

Execution Modes make runtime behavior explicit at product level.

They are not only technical settings. They define:
- user expectation
- orchestration semantics
- resilience behavior
- pricing behavior
- observability level

Every System must declare one primary execution mode.

---

### 20.1 Real-Time Decision Mode

Used when the system must return a result immediately.

Characteristics:
- synchronous request-response
- bounded execution graph
- low latency SLA
- no blocking HITL step
- deterministic surface behavior

Typical use cases:
- instant contract risk preview
- interactive document Q&A
- real-time recommendation
- lightweight scoring

Product behavior:
- user sees immediate result
- run is created in background for traceability
- cost is attached to a single decision event

Pricing logic:
- priced per decision or per analyzed item
- retry budget must remain bounded

---

### 20.2 Batch Processing Mode

Used when the system processes many inputs or long-running workloads.

Characteristics:
- asynchronous execution
- resumable state
- checkpointing enabled
- parallelism possible
- delayed but traceable results

Typical use cases:
- document batches
- nightly classification jobs
- large-scale translation or narration
- portfolio-wide risk analysis

Product behavior:
- system exposes queue state, progress and partial outputs
- user interacts through Runs and execution history
- failures are isolated per item or sub-run when possible

Pricing logic:
- priced per processed business unit
- internal runtime cost amortized over volume

---

### 20.3 Event-Driven Automation Mode

Used when a System reacts automatically to business events.

Characteristics:
- triggered by event, webhook, file arrival or threshold crossing
- no manual start required
- idempotent execution required
- correlation between event and run mandatory

Typical use cases:
- new contract uploaded
- drift threshold exceeded
- SFTP arrival
- new ticket or CRM event

Product behavior:
- users configure triggers, not manual runs
- Hypervisor can subscribe to strategic thresholds
- replay-safe execution is required

Pricing logic:
- priced per event successfully processed or per downstream business unit

---

### 20.4 Continuous Monitoring Mode

Used when a System continuously observes signals and decides whether to act.

Characteristics:
- persistent observation layer
- threshold or anomaly based triggering
- low-cost observation loop
- adaptive escalation logic

Typical use cases:
- KPI surveillance
- fraud or anomaly monitoring
- SLA monitoring
- capability health supervision

Product behavior:
- users monitor state, alerts and triggered runs
- Hypervisor consumes outputs directly

Pricing logic:
- subscription or bundled monitoring fee + triggered capability execution costs

---

### 20.5 Human-Augmented Mode

Used when the system is autonomous by default but requires structured human validation on sensitive steps.

Characteristics:
- system pauses on explicit review states
- HITL is part of normal execution semantics
- review outcomes are typed and auditable

Typical use cases:
- compliance review
- translation validation
- legal clause confirmation
- high-risk decision approval

Product behavior:
- review queue and approval UI are first-class
- resume token is mandatory after review

Pricing logic:
- priced on capability execution
- optional HITL surcharge or premium workflow pricing

---

### 20.6 Execution Mode Contract

```yaml
ExecutionMode:
  name: real_time_decision | batch_processing | event_driven_automation | continuous_monitoring | human_augmented
  trigger_type: manual | api | cron | event | threshold | review_resume
  sla_profile:
    latency_target_ms: 5000
    max_runtime_s: 30
  durability:
    checkpointing: true
    replay_safe: true
  pricing_profile:
    unit: decision
    retry_budget: bounded
```

---

### 20.7 Product Rule

Execution Mode must be visible in:
- System settings
- Run records
- pricing configuration
- Hypervisor

It is a first-class concept, not a hidden technical parameter.

---

## 21. Adaptive Systems

Agentium systems are not static pipelines.

An Adaptive System is a System that can change its execution behavior within governed boundaries based on:
- observed quality
- observed cost
- observed latency
- observed context
- observed risk

---

### 21.1 Adaptation Levels

#### Level 0 — Static
- fixed flow
- no runtime adaptation

#### Level 1 — Controlled Adaptation
- limited routing choices
- bounded fallbacks
- deterministic adaptation rules

#### Level 2 — Dynamic Adaptation
- planner can choose between multiple skills or flows
- evaluator can request retries or alternate paths
- cost-aware routing is enabled

#### Level 3 — Self-Optimizing
- system learns preferred execution patterns over time
- optimization policies are updated from historical performance
- always under governance constraints

---

### 21.2 Adaptation Inputs

Adaptation can use:
- confidence score
- cost budget remaining
- latency budget remaining
- skill health
- drift signals
- business priority
- review history

---

### 21.3 Adaptation Outputs

An adaptive decision may:
- switch skill
- switch model tier
- switch knowledge source
- re-plan flow
- invoke evaluator
- escalate to HITL
- stop execution

---

### 21.4 Adaptive Policy Contract

```yaml
AdaptivePolicy:
  enabled: true
  adaptation_level: controlled
  triggers:
    - low_confidence
    - high_cost
    - guardrail_soft_fail
  allowed_actions:
    - switch_skill
    - fallback_model
    - hitl_escalation
  constraints:
    max_extra_cost: 0.05
    max_retry_count: 1
    forbidden_actions:
      - bypass_guardrails
```

---

### 21.5 Governance Rule

Adaptive behavior must always be:
- bounded
- explainable
- auditable
- priced

No adaptive behavior may silently bypass:
- guardrails
- compliance checks
- pricing limits
- human review rules

---

### 21.6 Product Positioning

This is where Agentium becomes more than a workflow platform.

Agentium does not only run systems.
It runs **governed adaptive systems**.

---

## 22. Capability Execution Contract

A Capability is the business-level execution object exposed to customers, delivery teams and the Hypervisor.

If a Skill is the atomic execution primitive, a Capability is the atomic business promise.

---

### 22.1 Definition

A Capability Execution is:
- a business-scoped execution unit
- backed by one or more Systems
- composed of one or more Skills
- priced on a business unit
- evaluated on business and operational metrics

Examples:
- one contract analyzed
- one document processed
- one prediction generated
- one compliance review completed

---

### 22.2 Capability Contract

```yaml
Capability:
  id: cap_contract_risk_detection
  name: Contract Risk Detection
  description: Detects and explains contractual risks in uploaded agreements
  input_unit: contract
  output_unit: risk_report
  system_ids:
    - sys_contract_risk
  skill_ids:
    - ocr_layout_v2
    - clause_extraction_v1
    - risk_scoring_v3
  pricing:
    unit: contract
    unit_price: 0.20
  sla:
    mode: async
    target_completion_minutes: 5
  roi_model: legal_review_time_saved
```

---

### 22.3 Capability Execution Record

```yaml
CapabilityExecution:
  id: ce_001
  capability_id: cap_contract_risk_detection
  system_id: sys_contract_risk
  run_id: run_2026_001
  business_unit_count: 1
  status: completed
  revenue: 0.20
  internal_cost: 0.14
  quality:
    confidence: 0.92
    success_rate: 1.0
  impact:
    time_saved_minutes: 18
    estimated_value: 24.0
```

---

### 22.4 Capability Guarantees

Every Capability must define:
- input business unit
- output business unit
- customer-facing SLA
- pricing unit
- ROI model
- linked Systems
- linked Skills

A Capability cannot exist without runtime traceability to:
- Run
- Skill executions
- cost
- value estimate

---

### 22.5 Capability Metrics

#### Business Metrics
- volume
- revenue
- estimated value
- ROI
- time saved

#### Operational Metrics
- average completion time
- success rate
- fallback rate
- human review rate

#### Technical Metrics
- internal cost
- latency by step
- skill drift

---

### 22.6 Capability as Pricing Object

The customer does not buy Skills.
The customer buys Capabilities.

This is the core pricing rule of Agentium.

Skills explain internal cost.
Capabilities explain external value.

---

## 23. Hypervisor Decision Model

The Hypervisor must evolve from a reporting layer into a real strategic operating layer.

It must not only show metrics.
It must support decisions.

---

### 23.1 Decision Model Structure

The Hypervisor operates on five levels:

1. Observe
2. Interpret
3. Recommend
4. Decide
5. Act

---

### 23.2 Observe

The Hypervisor ingests:
- run metrics
- capability metrics
- system metrics
- cost metrics
- value metrics
- drift and risk signals

---

### 23.3 Interpret

The Hypervisor computes portfolio-level views:
- ROI by capability
- cost vs value by system
- trend evolution
- failure concentrations
- adoption concentration

---

### 23.4 Recommend

The Hypervisor generates strategic recommendations such as:
- scale a capability
- reduce a model tier
- move to HITL for low-confidence cases
- stop low-value systems
- allocate more budget to high-margin capabilities

Recommendations must always be backed by:
- observed evidence
- expected impact
- confidence level

---

### 23.5 Decide

A decision object is created when a strategic action is taken.

```yaml
Decision:
  id: dec_001
  scope: capability
  target_id: cap_contract_risk_detection
  recommendation: scale_usage
  rationale:
    roi: 49.0
    confidence: high
    trend: increasing
  approved_by: cfo_or_ops_lead
  timestamp: 2026-04-21T10:00:00Z
```

---

### 23.6 Act

The Hypervisor must support direct actions such as:
- increase budget
- reduce budget
- change execution mode
- enforce HITL threshold
- deploy upgraded System version
- pause capability

A COMEX tool is only truly used when decisions can be enacted from the same interface.

---

### 23.7 Decision Layers

#### Executive Layer
- portfolio ROI
- top and bottom capabilities
- budget allocation
- strategic recommendations

#### Operational Layer
- run health
- error clusters
- throughput
- review queues

#### Builder Layer
- skill performance
- system adaptation behavior
- fallback and retry analysis

Same object model, different abstraction depth.

---

### 23.8 What-If Simulation

The Hypervisor should support simulated decisions before action.

Examples:
- what if we scale this capability to all business units?
- what if we switch to a cheaper model for low-risk cases?
- what if we increase HITL threshold?

```yaml
WhatIfScenario:
  target: cap_contract_risk_detection
  change: increase_volume_2x
  expected_cost: 3360
  expected_value: 168000
  expected_roi: 49.0
```

---

### 23.9 Hypervisor Product Rule

The Hypervisor is not a passive BI layer.
It is a **decision cockpit for AI capability allocation**.

Its core unit is not the chart.
Its core unit is the **recommended and actionable decision**.

---

### 23.10 Final Strategic Model

```text
Skills → Systems → Capabilities → Hypervisor Decisions
```


This is the full business-operational chain of Agentium.

---

## 24. Agent Economics & Decision Units

Agentium introduces a critical layer that does not exist explicitly in most agentic platforms: the economic model of intelligence execution.

Agentium systems are not only technical systems.
They are **decision-producing economic entities**.

---

### 24.1 Core Concept — Decision Unit

A Capability Execution is not only a task.
It is a **Decision Unit**.

A Decision Unit is defined as:

```
Decision Unit =
- input (business context)
- decision produced
- cost
- time
- confidence
- impact (value)
```

Example:

```
1 contract → risk score → cost 0.18€ → value 12€ → confidence 0.92
```

---

### 24.2 Why Decision Units Matter

Traditional AI evaluates:
- model accuracy
- system performance

Agentium evaluates:
- economic output of decisions

Because in practice:
- AI agents act as decision-makers in economic systems citeturn0search10
- and must be evaluated on their impact, not just their intelligence

The key shift is:

> From “How smart is the system?”
> To “Does the decision generate more value than it costs?” citeturn0search5

---

### 24.3 Agent Efficiency Function

Agentium defines a normalized efficiency function:

```math
AgentEfficiency = \frac{Value \times Confidence}{Cost \times Time}
```

This enables:
- comparison across systems
- optimization over time
- routing decisions based on efficiency

---

### 24.4 Capability Portfolio Model

An organization does not deploy isolated agents.

It manages a **portfolio of capabilities**.

Each capability is evaluated as:
- an investment
- with cost
- with return
- with risk

The Hypervisor therefore acts as:
- capital allocation layer
- performance optimizer
- risk controller

---

### 24.5 Strategic Implication

Agentium shifts the paradigm from:

- AI as tooling

To:

- AI as a system of **decision production and value generation**

---

### 24.6 Product Rule

Every Capability must expose:
- cost per unit
- value per unit
- confidence
- efficiency score

No capability is valid without measurable economics.

---

## 25. Control Plane — Governance Layer

Agentium introduces a Control Plane that governs all systems.

The Control Plane is the layer that ensures that intelligence remains:
- safe
- bounded
- aligned
- economically viable

---

### 25.1 Definition

```
Control Plane = Policies + Constraints + Budget + Permissions + Safety + Routing Rules
```

---

### 25.2 Control Policy Example

```yaml
ControlPolicy:
  max_cost_per_decision: 0.25
  max_latency_ms: 5000
  mandatory_hitl_if_confidence_below: 0.85
  allowed_models:
    - mistral_local
    - azure_gpt4
```

---

### 25.3 Role of Control Plane

The Control Plane enforces:
- pricing boundaries
- compliance constraints
- execution constraints
- model governance
- safety rules

---

### 25.4 Strategic Importance

Without a Control Plane:
- agent systems drift
- costs explode
- risks accumulate

With a Control Plane:
- systems are enterprise-ready
- decisions are governed
- execution is predictable

---

## 26. Context Layer — First-Class Object

Agentium systems are context-dependent.

Lack of context is one of the main causes of agent failure.

---

### 26.1 Definition

Context is a first-class object:

```
Context =
- data
- documents
- memory
- history
- environment state
- business constraints
```

---

### 26.2 Updated System Definition

```
System = Objective + Capabilities + Context + Flow + Skills + Runs + Impact
```

---

### 26.3 Context Role

Context enables:
- better decisions
- better reasoning
- better consistency
- better personalization

---

### 26.4 Context Governance

Context must be:
- permissioned
- versioned
- auditable

---

### 26.5 Strategic Impact

Agentium does not only orchestrate skills.

It orchestrates **contextualized intelligence**.

---

## 27. Final Strategic Model (Extended)

```text
Context → Skills → Systems → Capabilities → Decision Units → Hypervisor Decisions
```

---

### Final Positioning Reinforcement

Agentium is not an agent platform.

It is:

> A system for producing, measuring and optimizing decisions at scale

---

### Ultimate Product Statement

> We don’t deploy agents.
> We control how decisions are produced, governed and optimized.

---

## 28. Deployment Modes — Enterprise & On-Prem Compatibility

Agentium must support both:
- **economic / ROI-driven usage (Hypervisor-first)**
- **technical / execution-driven usage (builder-first)**

This duality is critical because many enterprise use cases:
- start as technical problems
- operate in regulated or air-gapped environments
- require on-prem or sovereign deployments

Agentium must therefore support two entry modes.

---

### 28.1 Dual Entry Model

#### Executive Mode (default)
- Objective-driven
- ROI-first
- Hypervisor as homepage

#### Technical Mode (builder-first)
- System-first
- Flow / Skills visible
- Execution-first approach

---

### 28.2 On-Prem / Local Deployment Model

Agentium must be deployable:
- fully on-prem
- hybrid (on-prem + cloud LLM)
- sovereign cloud

Key requirements:
- no external dependency mandatory
- local LLM compatibility (vLLM, Ollama, etc.)
- local vector DB (Qdrant)
- local storage (MinIO / S3 compatible)

---

### 28.3 Product Rule

> Economic layer is optional for entry, but mandatory for scale.

Meaning:
- technical users can ignore ROI initially
- Hypervisor progressively becomes central as usage grows

---

### Strategic Insight

Many agentic AI failures come from lack of governance and infrastructure readiness citeturn0search0.

Agentium solves this by allowing:
- technical adoption first
- economic governance later

---

## 29. UX Wireframes (Concrete, Not Conceptual)

---

### 29.1 Run View — Decision Unit Visible

```
---------------------------------
RUN DETAIL
---------------------------------
Status: Completed
System: Contract Risk Detection

Decision (Unit of Value)
---------------------------------
Input: Contract #123
Outcome: Risk = High
Cost: 0.18€
Value: 12€
Confidence: 0.92
Efficiency: 20.4

Execution Trace
---------------------------------
[Step 1] OCR → OK
[Step 2] Extraction → OK
[Step 3] Scoring → OK
```

---

### 29.2 Hypervisor Homepage (C-Level)

```
---------------------------------
AI BALANCE SHEET
---------------------------------

Net Value: 142k€
ROI: +640%

Top Capabilities
---------------------------------
Contract Risk Detection → +120k€
Fraud Detection → +80k€

Liabilities
---------------------------------
Total Cost: 12k€
Risk: Medium
HITL Load: 18%

Actions
---------------------------------
[Scale Capability]
[Reduce Cost]
[Adjust Confidence Threshold]
```

---

### 29.3 Control Plane (Pilot Interface)

```
---------------------------------
SYSTEM CONTROL
---------------------------------
Cost Limit: [-----|----] 0.25€
Latency: [----|---] 5000ms
Confidence Threshold: [---|----] 0.85

Impact Preview
---------------------------------
Cost: +12%
Latency: -18%
ROI: +9%
```

---

## 30. UX Naming Strategy

“Decision Unit” is internally precise but can be too technical and cold for end users.

Agentium must separate **internal rigor** from **external clarity**.

---

### 30.1 Naming Duality

#### Internal (Engineering / Data Model)
- Decision Unit

#### UI (Product / User-facing)
- Outcome
- Decision
- Unit of Value

---

### 30.2 Recommended Default

- Primary UI label: **Outcome**
- Secondary (contextual): Decision

Example in UI:

```
Outcome
-----------------
Risk = High
Cost: 0.18€
Value: 12€
Confidence: 0.92
```

---

### 30.3 Product Rule

- Never expose “Decision Unit” directly in UI
- Always expose business-readable terms
- Keep semantic consistency across all screens

---

### 30.4 Strategic Insight

Naming is not cosmetic.

It defines:
- cognitive load
- adoption speed
- perceived product maturity

“Outcome” anchors the system in **business value**, not technical abstraction.

---

## 31. Real-Time Feedback & System Responsiveness

Real-time feedback is not a UX enhancement.
It is a **core product requirement**.

---

### 31.1 Why It Matters

Without real-time feedback:
- the system feels static
- decisions feel disconnected from impact
- the platform behaves like a dashboard

With real-time feedback:
- the system feels alive
- users understand cause → effect instantly
- decision-making becomes intuitive

---

### 31.2 Core Interaction Pattern

```
User action (slider / constraint change)
        ↓
Immediate recalculation
        ↓
Live UI update
        ↓
Updated ROI / cost / recommendation
```

---

### 31.3 Example — Control Plane

```
User adjusts:
Cost Limit → 0.20€

System reacts instantly:
- Cost ↓
- Confidence ↓ slightly
- ROI ↑
- Recommendation updated
```

---

### 31.4 Mandatory UI Behaviors

- No page reload
- Sub-second feedback (<300ms target for perception)
- Progressive update (numbers animate, not jump)
- Visual highlighting of changes

---

### 31.5 Impact Preview as Standard

Every decision must show its impact before being applied.

```
Impact Preview
--------------
Cost: -12%
Latency: +5%
ROI: +8%
Risk: +3%
```

---

### 31.6 Product Rule

> Every user action must produce a visible and immediate system reaction

---

### 31.7 Strategic Consequence

Without this:
- Agentium = dashboard

With this:
- Agentium = **interactive decision system**

---

### 31.8 Key Warning

If real-time feedback is not implemented:

- you lose the “wow effect”
- you lose trust in the system
- you lose differentiation

---

### Final Insight

The perception of intelligence does not come from models.

It comes from:

> how fast and clearly the system reacts to user decisions



## 31. UI Feedback & System Perception

Agentium must feel like a **living system**.

---

### 31.1 Real-Time Feedback

Every interaction should produce visible feedback.

Example:

User changes slider →
- cost updates instantly
- ROI recalculates
- recommendation updates

---

### 31.2 Animation Principles

- micro-animations on change
- progressive updates
- no full page reload

---

### 31.3 Goal

Create perception that:

> “The system reacts to my decisions in real time.”

---

## 32. UX Pitfalls to Avoid

---

### ❌ Pitfall 1 — Hiding Core Concepts

- Balance Sheet hidden in tabs
- Control Plane buried in settings

❗ Rules:
- Balance Sheet = homepage
- Control Plane = visible in system view

---

### ❌ Pitfall 2 — Over-Technical UX

- too many metrics
- internal jargon
- low signal-to-noise

❗ Rules:
Always prioritize:
- cost
- value
- ROI

---

### ❌ Pitfall 3 — Static UI

- no feedback
- no adaptation
- no perception of intelligence

❗ Rule:
UI must reflect system behavior dynamically

---

## 33. Final Product Completeness Check

Agentium now includes:

- Execution Model
- Runtime Model
- Adaptive Systems
- Capability Model
- Decision Unit Model
- Economic Model
- Control Plane
- Hypervisor
- UX Model
- Deployment Model (cloud + on-prem)

---

### Final Positioning (Updated)

Agentium is:

> A platform to design, run and govern intelligent systems
> across both technical and economic dimensions

---

### Final Insight

Agentium succeeds because it allows:
- engineers to build systems
- operators to run them
- executives to optimize them

In one unified model

---

## 34. Builder Onboarding Mode (Adoption First Strategy)

Agentium must explicitly support a **Builder Onboarding Mode** where ROI is not the primary entry point.

---

### 34.1 Why This Mode Is Required

Enterprise reality:
- most AI adoption starts with experimentation
- ROI is unclear at the beginning
- teams need to “build first, measure later”

Studies show that unclear business value and technical readiness are among the main blockers to adoption citeturn0search2.

---

### 34.2 Builder Onboarding Mode Definition

Builder Mode is:
- system-first
- execution-first
- ROI-light (initially hidden or optional)

User journey:
```
Create System → Run → Observe → Iterate → Discover Value → Activate ROI layer
```

---

### 34.3 UX Behavior

In Builder Mode:
- focus on Runs, Flow, Skills
- show cost optionally, not ROI
- no Balance Sheet by default
- Hypervisor progressively introduced

---

### 34.4 Transition to Economic Mode

At maturity threshold (usage / volume / stability):
- system prompts user:
  “Do you want to track value and ROI?”

Then:
- Decision Units activated
- Hypervisor becomes visible
- Balance Sheet unlocked

---

### 34.5 Product Rule

> Adoption starts with execution. Scaling requires economics.

---

## 35. Convergence UX — Builder ↔ Hypervisor

Agentium must unify builder and executive views without breaking cognitive flow.

---

### 35.1 Problem

- Builder view = detailed, technical
- Hypervisor view = aggregated, strategic

Most platforms split them completely → cognitive break.

---

### 35.2 Solution — Zoom-Based Continuum

Agentium uses a continuous zoom model:

```
Skill → Flow → System → Capability → Portfolio
```

---

### 35.3 UX Mechanism

- Zoom in → technical detail (skills, steps)
- Zoom out → aggregated value (ROI, impact)

Same object, different abstraction level.

---

### 35.4 Shared Object Model

Both views rely on the same objects:
- Run
- Outcome (Decision Unit)
- Capability

No duplication, no translation layer.

---

### 35.5 Key Principle

> Change perspective, not interface

---

### 35.6 Product Rule

- Builder and Hypervisor must never be separate apps
- Only abstraction level changes

---

## 36. Control Plane as “AI Steering Wheel”

The Control Plane can become a major visual and conceptual differentiator.

---

### 36.1 Concept

Instead of a configuration panel,
Control Plane becomes a **steering interface for AI systems**.

---

### 36.2 Core Metaphor

```
AI System = Vehicle
User = Driver
Control Plane = Steering Wheel
```

---

### 36.3 Steering Wheel Dimensions

Each axis controls a system trade-off:

- Cost ↔ Quality
- Speed ↔ Accuracy
- Automation ↔ Control (HITL)
- Risk ↔ Performance

---

### 36.4 UI Representation

Option 1 — Radial Control
- circular UI
- each axis adjustable
- central equilibrium point

Option 2 — Multi-Slider Panel
- simpler implementation
- linear controls

---

### 36.5 Real-Time Interaction

Every steering action:
- updates cost
- updates ROI
- updates system behavior

---

### 36.6 Impact Visualization

```
Steering Change → Immediate Simulation → Outcome Projection
```

---

### 36.7 Strategic Advantage

Transforms Control Plane from:
- technical settings

Into:
- **decision-making interface**

---

### 36.8 Product Rule

> The user must feel they are piloting intelligence, not configuring software

---

## 37. Final UX Integration — Adoption to Mastery

Agentium UX must support the full maturity curve:

---

### Phase 1 — Builder
- focus: execution
- no ROI pressure
- fast iteration

---

### Phase 2 — Operator
- focus: performance
- cost awareness
- run monitoring

---

### Phase 3 — Executive
- focus: ROI
- portfolio optimization
- strategic decisions

---

### Unified Model

```text
Build → Run → Measure → Optimize → Allocate
```

---

### Final Strategic Insight

Agentium wins because it does not force users into a single mental model.

It adapts to:
- builders (execution)
- operators (performance)
- executives (value)


while keeping a single coherent system.

---

## 38. Soft Transition UX — Builder → Hypervisor

Agentium must not impose a hard switch between Builder and Hypervisor views.

---

### 38.1 Principle

> ROI must emerge progressively, not be imposed.

Agentic systems adoption typically starts from execution and only later converges toward measurable value citeturn0search1.

---

### 38.2 Progressive Reveal Model

Instead of a mode switch, introduce a gradual layering:

#### Stage 1 — Builder (No ROI)
- Runs
- Skills
- Flow
- Basic cost (optional)

#### Stage 2 — Operator (Cost Awareness)
- Cost per run
- Success rate
- Latency

#### Stage 3 — Value Discovery
- Estimated value appears
- “Outcome” block enriched

#### Stage 4 — Hypervisor Activation
- ROI visible
- Balance Sheet appears
- Recommendations enabled

---

### 38.3 UX Mechanism

- ROI appears inline (not via navigation)
- No dedicated “switch mode” button
- System suggests activation (“Track value?”)

---

### 38.4 Product Rule

- No abrupt UX transition
- Always additive, never disruptive

---

### Strategic Insight

Users adopt agentic systems through intent and experimentation before governance and ROI layers become critical citeturn0search3.

---

## 39. Visualizing the Zoom — Skill → Portfolio

Agentium must materialize abstraction levels without overwhelming non-technical users.

---

### 39.1 Problem

Zoom abstraction risks:
- loss of context
- cognitive overload
- disorientation

---

### 39.2 Solution — Semantic Zoom

Instead of geometric zoom, Agentium uses **semantic zoom**:

```
Skill → Flow → System → Capability → Portfolio
```

Each level changes representation, not just scale.

---

### 39.3 UI Patterns

#### Breadcrumb Continuum

```
[Portfolio] > [Capability] > [System] > [Run] > [Skill]
```

- always visible
- clickable
- preserves context

---

#### Card Transformation

- Skill = node / atomic block
- System = structured graph
- Capability = KPI card
- Portfolio = balance sheet

Same object → different representation

---

#### Focus Mode

- click object → isolates it
- dim others
- reduces cognitive load

---

### 39.4 Product Rule

> Never zoom into technical detail without preserving business context

---

### Strategic Insight

Agentic UX is shifting from static interfaces to adaptive, context-driven systems that reshape themselves based on user intent citeturn0search7.

---

## 40. Steering Wheel Scope — Global vs Local

The Control Plane must exist at multiple levels.

---

### 40.1 Problem

- Global only → too abstract
- Local only → no strategic control

---

### 40.2 Solution — Multi-Level Steering Model

#### Global Steering (System / Portfolio)
- budget allocation
- global cost constraints
- model policy
- risk level

Used by:
- C-level
- Ops

---

#### Capability-Level Steering
- pricing optimization
- model tier routing
- HITL thresholds

Used by:
- product / delivery

---

#### Run-Level Steering
- retry decisions
- override execution
- manual validation

Used by:
- operators

---

### 40.3 UX Representation

- Global: Hypervisor cockpit
- Capability: inline control panel
- Run: contextual action panel

---

### 40.4 Product Rule

> Steering must exist at all levels, but be visible only where relevant

---

### 40.5 Default Behavior

- start with global steering (simple)
- progressively expose local controls

---

### Strategic Insight

Effective agentic systems require balancing autonomy and control across layers, not centralizing everything in a single control point citeturn0search5.

---

## 41. Final UX Maturity Model (Extended)

Agentium must support three progressive UX dimensions:

---

### Dimension 1 — Abstraction

Skill → System → Capability → Portfolio

---

### Dimension 2 — Value Visibility

Cost → Performance → Value → ROI → Allocation

---

### Dimension 3 — Control

Local → Capability → System → Portfolio

---

### Final Model

```text
Execute → Observe → Understand → Value → Control → Optimize
```

---

### Ultimate Insight

The power of Agentium comes from aligning:
- abstraction
- value visibility
- control

into a single coherent experience.