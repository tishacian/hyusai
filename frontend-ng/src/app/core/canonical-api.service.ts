import { Injectable, inject } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Observable, catchError, map, of } from 'rxjs';
import { ApiService } from './api.service';
import type { ObjectLens } from './navigation.catalog';
import type { ObjectPerspectiveResponse } from '@app/shared/cockpit/object-perspective.models';

/** Canonical mental-model types — kept flat and permissive so the UI can
 *  degrade gracefully when any field is missing (e.g. before a run
 *  completes or while the runtime engine is still being wired in). */
export interface Capability {
  id: string;
  slug: string;
  name: string;
  description?: string;
  tier?: 'universal' | 'industry' | 'client';
  industry?: string | null;
  input_unit?: string;
  output_unit?: string;
  skill_ids?: string[];
  pricing?: { unit: string; unit_price: number; currency: string };
  value_per_outcome?: number | null;
  confidence_threshold?: number | null;
  sla?: Record<string, unknown>;
  roi_model?: Record<string, unknown>;
  is_seeded?: 'Y' | 'N';
}

export interface Skill {
  id: string;
  slug: string;
  version?: string;
  name: string;
  description?: string;
  type?: string;
  provider?: string;
  certification_level?: 'basic' | 'production' | 'enterprise';
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  execution?: {
    mode?: 'sync' | 'async' | 'stream';
    timeout_ms?: number;
    retryable?: boolean;
    idempotent?: boolean;
  };
  pricing?: { unit: string; unit_price: number; currency: string };
  metrics?: {
    calls?: number;
    avg_latency_ms?: number;
    total_cost?: number;
    success_rate?: number;
  };
  is_seeded?: 'Y' | 'N';
  runtime_status?: 'bound' | 'stub' | 'unbound' | 'catalog_only';
}

export interface Outcome {
  decision?: string | null;
  confidence?: number | null;
  value_estimated?: number | null;
  cost_internal?: number | null;
  revenue_allocated?: number | null;
  efficiency?: number | null;
  currency?: string;
  value_source?: 'auto' | 'operator' | 'unset';
  operator_value_note?: string | null;
  baseline_eligible?: boolean;
  baseline_ineligible_reason?: string | null;
}

export interface SkillInvocation {
  id?: string;
  run_id?: string;
  system_id?: string | null;
  capability_id?: string | null;
  skill_slug?: string;
  skill_id?: string;
  status?: 'completed' | 'failed' | 'pending' | 'running' | 'cancelled';
  latency_ms?: number;
  cost?: number;
  input_ref?: Record<string, unknown>;
  output_ref?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
  trace?: Record<string, unknown>;
  started_at?: string;
  completed_at?: string;
  ended_at?: string;
  error?: string | null;
}

export interface RetrievalDecisionTrace {
  version?: number;
  trace_id?: string;
  summary?: string;
  query_type?: string;
  latency_profile?: string | null;
  retrieval_profile?: string | null;
  selected_route?: string;
  route_reason?: string;
  tradeoff?: string;
  collection_scope?: Record<string, unknown>;
  layers?: Array<Record<string, unknown>>;
  quality_controls?: Record<string, unknown>;
  fallbacks?: Array<Record<string, unknown>>;
  deep_search?: Record<string, unknown>;
  answer_shaping?: Record<string, unknown>;
  timings?: Record<string, unknown>;
  candidate_counts?: Record<string, unknown>;
  selected_sources?: Array<Record<string, unknown>>;
  trace_source?: string;
}

export interface RunHitlPayload {
  node_id?: string;
  prompt?: string;
  decision_id?: string;
  decision_status?: string | null;
  decision_title?: string | null;
  /** ISO timestamp when the gate auto-resolves (TTL). */
  expires_at?: string | null;
  expiry_action?: 'reject' | 'approve' | 'escalate' | string | null;
  seconds_remaining?: number | null;
  /** Transactions buffered into run_inbox while paused. */
  inbox_count?: number;
  correlation_key?: string | null;
  memory?: {
    correlation_key?: string;
    version?: number;
    event_count?: number;
    last_event_kind?: string | null;
    updated_at?: string | null;
  } | null;
}

export interface RunDebugPayload {
  node_id?: string;
  debug_mode?: 'step' | 'breakpoints' | null;
  breakpoints?: string[];
  ctx_snapshot?: Record<string, unknown>;
  last_output?: Record<string, unknown>;
}

export interface Run {
  id: string;
  system_id: string;
  capability_id?: string | null;
  status:
    | 'pending'
    | 'running'
    | 'completed'
    | 'failed'
    | 'cancelled'
    | 'hitl_pending'
    | 'debug_pending';
  started_at?: string;
  completed_at?: string;
  ended_at?: string;
  duration_ms?: number;
  outcome?: Outcome;
  checkpoints?: Array<Record<string, unknown>>;
  retries?: number;
  error?: string | null;
  trigger?: string;
  input_ref?: Record<string, unknown>;
  output_ref?: Record<string, unknown>;
  skill_invocations?: SkillInvocation[];
  /** Populated when status === 'hitl_pending' — contains the pending
   * Decision reference plus the prompt to surface in the Terminal.
   */
  hitl?: RunHitlPayload;
  /** Populated when status === 'debug_pending' — walker ctx snapshot,
   * the node that tripped the breakpoint, and the current breakpoint set
   * so the step debugger UI can render without another request.
   */
  debug?: RunDebugPayload;
}

export interface SystemHealthRow {
  id: string;
  name: string;
  status?: string;
  capability_id?: string | null;
  surface?: string | null;
  system_type?: string | null;
  route?: string;
  runs_total: number;
  runs_completed: number;
  runs_failed: number;
  avg_latency_ms?: number | null;
  latest_run_id?: string | null;
  latest_run_status?: string | null;
  latest_run_at?: string | null;
}

export interface JobHealthRow {
  id: string;
  kind: string;
  title: string;
  status: string;
  stage?: string;
  progress?: number;
  error?: string | null;
  system_id?: string | null;
  run_id?: string | null;
  route?: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ObservabilityAlert {
  id: string;
  kind: string;
  tone: 'pos' | 'neg' | 'warn' | 'info' | string;
  label: string;
  route: string;
  timestamp?: string | null;
}

export interface ActivityTimelineItem {
  id: string;
  kind: string;
  tone: 'pos' | 'neg' | 'warn' | 'info' | string;
  label: string;
  route: string;
  timestamp?: string | null;
  meta?: Record<string, unknown>;
}

export interface WorkspaceOverview {
  window: string;
  since: string;
  generated_at: string;
  workspace: { id: string; slug?: string; name?: string };
  summary: {
    active_systems: number;
    runs_total: number;
    runs_completed: number;
    runs_failed: number;
    runs_running: number;
    avg_latency_ms?: number | null;
    p95_latency_ms?: number | null;
    jobs_total: number;
    jobs_active: number;
    jobs_failed: number;
    evaluations_total: number;
    alerts_total: number;
    retrieval_traces_total?: number;
    retrieval_traces_missing?: number;
    sparse_timeouts?: number;
    sparse_fallbacks?: number;
    cross_encoder_issues?: number;
    deep_recommended?: number;
    deep_launched?: number;
  };
  retrieval_decisions?: {
    total?: number;
    missing?: number;
    routes?: Array<{ route: string; count: number }>;
    query_types?: Array<{ query_type: string; count: number }>;
    quality?: Record<string, number>;
  };
  systems: SystemHealthRow[];
  jobs: JobHealthRow[];
  evaluations: {
    total: number;
    avg_composite?: number | null;
    avg_hallucination_rate?: number | null;
    breaches: number;
    latest?: Record<string, unknown> | null;
    thresholds?: Record<string, unknown>;
  };
  alerts: ObservabilityAlert[];
  timeline: ActivityTimelineItem[];
}

export interface Context {
  id: string;
  system_id?: string | null;
  name: string;
  version?: number;
  data_refs?: string[];
  memory_refs?: string[];
  history_refs?: string[];
  environment_state?: Record<string, unknown>;
  business_constraints?: Record<string, unknown>;
  permissions?: Record<string, unknown>;
  /**
   * Ephemeral drop-and-ask session context (Vague D / D0). When true, the
   * backend auto-purges the row past `ttl_expires_at`.
   */
  ephemeral?: boolean;
  /** Absolute expiration (ISO 8601) for ephemeral contexts. */
  ttl_expires_at?: string | null;
  /** Only honoured by `POST /contexts` when `ephemeral=true`. */
  ttl_hours?: number;
  created_at?: string;
}

export type SystemStatus = 'draft' | 'active' | 'paused' | 'retired';

export type ExecutionMode =
  | 'real_time_decision'
  | 'batch_processing'
  | 'event_driven_automation'
  | 'continuous_monitoring'
  | 'human_augmented';

export interface System {
  id: string;
  workspace_id?: string | null;
  name: string;
  objective?: string;
  capability_id?: string | null;
  skill_ids?: string[];
  settings?: Record<string, unknown>;
  context_id?: string | null;
  control_policy_id?: string | null;
  adaptive_policy_id?: string | null;
  flow?: Record<string, unknown>;
  flow_definition?: Record<string, unknown>;
  /** Canonical digest of the persisted flow used as the optimistic-write
   * precondition by Flow Builder saves. */
  flow_sha256?: string;
  status?: SystemStatus;
  /** Canonical execution taxonomy — see schemas/canonical.ExecutionMode. */
  execution_mode?: ExecutionMode;
  execution_profile?: Record<string, unknown>;
  // Canonical per-system defaults consumed by the run engine / RAG wrappers.
  default_prompt_type?: string | null;
  default_model?: string | null;
  retrieval_mode_default?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface FlowManifestField {
  key: string;
  source: string;
  type?: string;
  required?: boolean;
  description?: string | null;
  enum?: string[] | null;
  current_value?: unknown;
}

export interface FlowManifestUnit {
  id: string;
  label: string;
  kind: string;
  node_type?: string;
  unit_type?: string;
  description?: string | null;
  runtime_ref?: string | null;
  skill_slug?: string | null;
  skill_id?: string | null;
  runtime_status?: 'bound' | 'stub' | 'unbound' | 'catalog_only' | 'manifest_only';
  operational?: boolean;
  prompt_contract?: Record<string, unknown> | null;
  editable_fields?: FlowManifestField[];
  parameter_count?: number;
  position?: { x?: number; y?: number };
  implementation?: {
    source?: string;
    execution?: Record<string, unknown>;
    input_schema?: Record<string, unknown>;
    output_schema?: Record<string, unknown>;
  };
}

export interface FlowRuntimeManifest {
  system_id: string;
  system_name: string;
  variant?: string | null;
  schema_version?: number | null;
  source?: string | null;
  runtime_mode?: 'chat_runtime' | 'run_engine_dag' | string;
  operational_sync?: boolean;
  live_surface?: string | null;
  runtime_contract?: Record<string, unknown>;
  prompt_contract?: Record<string, unknown>;
  effective_config?: Record<string, unknown>;
  latest_retrieval_decision?: {
    run_id?: string;
    status?: string;
    started_at?: string | null;
    trace?: RetrievalDecisionTrace;
  } | null;
  unit_catalog?: FlowManifestUnit[];
  summary?: {
    nodes?: number;
    edges?: number;
    operational_units?: number;
    runtime_refs?: number;
    skill_units?: number;
    editable_parameters?: number;
  };
  sync_controls?: {
    chat_reads_flow_overrides?: boolean;
    flow_definition_persists_on_save?: boolean;
    versioned?: boolean;
    runtime_note?: string;
  };
}

/** Structured validation diagnostic for a flow graph. Mirrors
 *  ``FlowValidationIssue`` from ``flow-serializer.service.ts`` and the
 *  backend ``services.chains.dag_validator.ValidationIssue`` shape so a
 *  server-side 400 can be spliced into the same issues strip without
 *  translation. The two enumerations stay in lockstep — when the
 *  backend adds a new ``code``, mirror it in both places. */
export interface FlowValidationIssue {
  level: 'error' | 'warn';
  code: string;
  message: string;
  node_id?: string | null;
  edge_index?: number | null;
}

/** Summary row returned by ``GET /systems/{id}/versions`` — drops the
 *  heavyweight ``flow_definition`` so the listing stays snappy even at
 *  the 500-row rolling window ceiling (decision 2026-04-24). Fetch
 *  the full payload through ``getSystemVersion`` when previewing or
 *  confirming a rollback. */
export interface SystemVersionSummary {
  id: string;
  system_id: string;
  version_number: number;
  message?: string | null;
  rolled_back_from_id?: string | null;
  created_at: string;
  created_by: string;
  node_count: number;
  edge_count: number;
}

export interface SystemVersionFull extends Omit<SystemVersionSummary, 'node_count' | 'edge_count'> {
  workspace_id: string | null;
  flow_definition: Record<string, unknown>;
}

export interface SystemVersionList {
  total: number;
  limit: number;
  offset: number;
  versions: SystemVersionSummary[];
}

export interface SystemRollbackResult {
  system: System;
  new_version: SystemVersionFull;
}

/** Export envelope shape — mirrors ``services.chains.export_service``.
 *  The UI keeps it as an opaque ``Record<string, unknown>`` for upload
 *  but validates the top-level keys before shipping it to the import
 *  endpoint (Vague E / E3.4). */
export interface SystemExportEnvelope {
  kind: 'agentium.system.export';
  schema_version: number;
  exported_at: string;
  exported_by: string;
  source: { workspace_id: string | null; system_id: string };
  system: {
    name: string;
    objective: string;
    flow_definition: Record<string, unknown>;
    skill_slugs: string[];
    execution_mode: string;
    execution_profile: Record<string, unknown>;
    coordination_pattern: string;
    default_prompt_type: string | null;
    default_model: string | null;
    retrieval_mode_default: string | null;
  };
}

export interface SystemImportReport {
  resolved_skills: { slug: string; skill_id: string }[];
  unresolved_skills: string[];
  task_node_rebinds: {
    node_id: string | null;
    slug: string;
    skill_id: string | null;
  }[];
  source?: { workspace_id?: string | null; system_id?: string };
}

export type SystemImportResult =
  | {
      ok: true;
      system: System;
      import_report: SystemImportReport;
      validation_warnings: FlowValidationIssue[];
    }
  | {
      ok: false;
      reason: 'invalid_envelope' | 'flow_invalid' | 'network';
      message: string;
      issues: FlowValidationIssue[];
    };

/** Discriminated union returned by ``saveSystemFlow``. ``ok=true`` means
 *  the PATCH landed (warnings may still be present). ``invalid`` carries
 *  structured DAG errors, ``explicit_intent_required`` means an active flow
 *  replacement needs a deliberate retry, and ``conflict`` means the caller's
 *  optimistic flow precondition was missing or stale. ``network`` remains the
 *  fallback for transport failures and unrecognised HTTP responses. */
export type SaveSystemFlowResult =
  | {
      ok: true;
      system: System;
      warnings: FlowValidationIssue[];
      new_version: SystemVersionSummary | null;
    }
  | {
      ok: false;
      reason: 'invalid' | 'explicit_intent_required' | 'conflict' | 'network';
      message: string;
      issues: FlowValidationIssue[];
    };

export interface ImpactAggregate {
  scope?: 'portfolio' | 'capability' | 'system';
  period?: string;
  runs_count?: number;
  capabilities_count?: number;
  total_cost?: number | null;
  estimated_value?: number | null;
  total_revenue?: number | null;
  roi?: number | null;
  avg_confidence?: number | null;
  avg_efficiency?: number | null;
  measurement_states?: Partial<Record<
    'total_cost' | 'estimated_value' | 'total_revenue',
    'available' | 'not_measured'
  >>;
}

export interface CapabilityRow extends ImpactAggregate {
  capability_id: string;
  slug?: string;
  name?: string;
  tier?: string;
  trend?: Array<{ t: string; value: number; cost: number }>;
}

export interface HypervisorSignal {
  id: string;
  tone: 'pos' | 'neg' | 'warn' | 'neutral';
  kind: string;
  system_id?: string;
  timestamp?: string | null;
  label: string;
}

export interface HypervisorBalance {
  period: string;
  portfolio: ImpactAggregate;
  capabilities: CapabilityRow[];
  signals: HypervisorSignal[];
}

export type PortfolioEvidenceState =
  | 'available'
  | 'not_measured'
  | 'not_configured'
  | 'restricted'
  | 'unavailable';

export interface PortfolioValueLoopFact<T> {
  state: PortfolioEvidenceState;
  value: T | null;
  source: string;
  sample_count: number;
}

export interface PortfolioValueLoop {
  schema_version: 1;
  scope: 'portfolio';
  state: PortfolioEvidenceState;
  systems: Array<{
    system_id: string;
    capability_id: string | null;
    name: string;
    scenario_count: number;
    open_count: number;
    measured_count: number;
    scenario_state: PortfolioEvidenceState;
    actuator_state: 'available' | 'not_configured';
  }>;
  status_counts: Record<string, number>;
  observed_value_delta: PortfolioValueLoopFact<number>;
  outcomes: {
    state: PortfolioEvidenceState;
    observed_value_delta: PortfolioValueLoopFact<number>;
    measured_scenarios: PortfolioValueLoopFact<number>;
    forecast_verdict_counts: PortfolioValueLoopFact<Record<string, number>>;
  };
  risks: {
    state: PortfolioEvidenceState;
    count: number | null;
    source: string;
    items: Array<{
      kind: string;
      system_id: string;
      scenario_id: string;
      state: 'available';
      source: string;
      detail: string | null;
    }>;
  };
  arbitrations: {
    state: PortfolioEvidenceState;
    source: string;
    items: Array<{
      id: string;
      scenario_id: string;
      system_id: string;
      status: string;
      title: string;
      created_at: string | null;
    }>;
  };
  scenarios: {
    state: PortfolioEvidenceState;
    source: string;
    items: Array<{
      id: string;
      system_id: string;
      capability_id: string | null;
      status: string;
      objective: string;
      created_at: string | null;
      decision: { id: string; status: string; title: string } | null;
      decision_state: 'available' | 'not_configured' | 'restricted';
      outcome: {
        state: 'available' | 'not_measured';
        measurement_id: string | null;
        delta: Record<string, number> | null;
        forecast_delta: Record<string, number> | null;
        assumption_verdict: string;
      };
    }>;
  };
  simulation_is_measurement: false;
}

export interface Recommendation {
  id: string;
  scope: string;
  target_id?: string | null;
  title: string;
  rationale: Record<string, unknown>;
  impact_estimate: Record<string, unknown>;
  status?: 'pending' | 'approved' | 'rejected' | 'applied';
  created_at?: string;
}

export interface ProactiveRecommendationGenerateResponse {
  window_days: number;
  evaluations_scanned: number;
  candidates: number;
  created: Recommendation[];
  skipped: Array<{ fingerprint: string; decision_id?: string; reason: string }>;
  preview: Array<{
    title: string;
    rationale: Record<string, unknown>;
    impact_estimate: Record<string, number>;
  }>;
}

export interface WhatIfResult {
  scope: string;
  target_id?: string | null;
  base: ImpactAggregate;
  projected: {
    total_cost: number | null;
    estimated_value: number | null;
    roi: number | null;
    latency_index: number;
  };
}

export interface ValueLoopSimulation {
  id: string;
  scenario_id: string;
  system_id: string;
  status: 'available';
  evidence_type: 'simulation';
  model: string;
  assumptions: Record<string, unknown>;
  projected_outcome: Record<string, unknown>;
  recommended_action: {
    actuator?: string;
    patch?: Record<string, unknown>;
  };
  provenance: Record<string, unknown>;
  confidence: number;
  generated_at: string | null;
}

export interface ValueLoopActionExecution {
  id: string;
  scenario_id: string;
  system_id: string;
  simulation_id: string;
  actuator: string;
  status: 'succeeded';
  changed_fields: string[];
  executed_by: string;
  executed_at: string | null;
}

export interface ValueLoopMeasurement {
  id: string;
  scenario_id: string;
  system_id: string;
  action_execution_id: string;
  simulation_id: string;
  source_run_id: string | null;
  status: 'measured' | 'not_measured';
  reason: string | null;
  evidence_type: 'run' | null;
  baseline_outcome: Record<string, unknown>;
  observed_outcome: Record<string, unknown> | null;
  delta: Record<string, number> | null;
  forecast_delta: Record<string, number> | null;
  assumption_verdict: 'confirmed' | 'partially_confirmed' | 'not_confirmed' | 'not_evaluable';
  assumption_evaluation: Record<string, unknown>;
  measured_at: string | null;
}

export interface ValueScenario {
  id: string;
  workspace_id: string;
  system_id: string;
  source_run_id: string;
  status: 'decision_proposed' | 'simulated' | 'approved' | 'acted' | 'measured';
  objective: string;
  baseline_outcome: Record<string, unknown>;
  approved_simulation_id: string | null;
  approved_simulation_content_sha256: string | null;
  approved_by: string | null;
  approved_at: string | null;
  acted_at: string | null;
  measured_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  decision: {
    id: string;
    status: string;
    title: string;
    rationale: Record<string, unknown>;
  } | null;
  decision_state?: 'available' | 'not_configured' | 'restricted';
  simulations: ValueLoopSimulation[];
  action: ValueLoopActionExecution | null;
  measurements: ValueLoopMeasurement[];
}

export interface SystemValueLoop {
  schema_version: 1;
  system_id: string;
  actuator: 'control_policy.guardrails.patch.v1';
  items: ValueScenario[];
}

// ---- Evaluation loop (Vague E / E1) ---------------------------------------

/** Threshold config persisted on `EvaluationPreset`. Mirrors
 *  `DEFAULT_EVAL_CONFIG` in `backend/app/services/evaluation_preset_service.py`. */
export interface EvaluationPresetConfig {
  enabled?: boolean;
  composite_min?: number;
  hallucination_max?: number;
  dimension_min?: Record<string, number>;
  sample_rate?: number;
}

export interface EvaluationPresetResponse {
  defaults: EvaluationPresetConfig;
  workspace: {
    id: string | null;
    name: string | null;
    config: EvaluationPresetConfig | null;
  };
  effective: EvaluationPresetConfig;
}

export interface ReviewQueueItem {
  decision: {
    id: string;
    kind: string;
    status: 'proposed' | 'accepted' | 'rejected' | 'applied';
    title: string;
    rationale: Record<string, unknown>;
    created_at: string | null;
    approved_by: string | null;
    approved_at: string | null;
  };
  run: {
    id: string;
    system_id: string | null;
    capability_id: string | null;
    status: string | null;
    decision: string | null;
    confidence: number | null;
    started_at: string | null;
    completed_at: string | null;
    evaluation_scores: {
      composite_score?: number;
      hallucination_rate?: number;
      scores?: Record<string, number>;
      threshold_breach?: boolean;
      question_type?: string | null;
      failed_components?: string[];
      topic?: string | null;
      reasons?: Array<{
        metric: string;
        observed: number;
        threshold: number;
        direction: 'above' | 'below';
      }>;
      evaluation_id?: string;
    } | null;
    input_ref: Record<string, unknown> | null;
    output_ref: Record<string, unknown> | null;
  } | null;
}

export interface EvaluationReviewQueueResponse {
  items: ReviewQueueItem[];
  count: number;
}

export interface ActiveSuggestion {
  version?: number;
  source?: 'llm' | 'fallback' | string;
  action_type?: 'rerun_with_overrides' | string;
  title?: string;
  rationale?: string;
  overrides?: Record<string, unknown>;
  expected_effect?: string;
  confidence?: number;
}

export interface EvaluationTrendBucket {
  bucket: string;
  count: number;
  avg_composite: number;
  avg_hallucination: number;
}

export interface EvaluationTrendResponse {
  since: string;
  group_by: 'day' | 'capability' | 'system';
  thresholds: { composite_min: number; hallucination_max: number };
  totals: { runs_evaluated: number; breaches: number; breach_rate: number };
  series: EvaluationTrendBucket[];
}

export interface EvaluationComponentHealthItem {
  component: string;
  label: string;
  evaluated: number;
  breaches: number;
  breach_rate: number;
  avg_composite: number;
  avg_hallucination: number;
  question_types: Record<string, { count: number; breaches: number }>;
}

export interface EvaluationComponentHealthResponse {
  since: string;
  thresholds: { composite_min: number; hallucination_max: number };
  totals: { evaluations: number; breaches: number };
  components: EvaluationComponentHealthItem[];
  taxonomy: {
    components: Record<string, string>;
    question_types: Record<string, string>;
    question_type_components: Record<string, string[]>;
  };
}

export interface CanonicalAnswerRow {
  id: string;
  workspace_id: string;
  question: string;
  answer: string;
  source_decision_id?: string | null;
  source_feedback_id?: string | null;
  source_run_id?: string | null;
  similarity_threshold: number;
  hit_count: number;
  created_by: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CanonicalAnswerListResponse {
  total: number;
  limit: number;
  offset: number;
  items: CanonicalAnswerRow[];
}

/**
 * Shape returned by ``GET /evaluation/by-run/{run_id}`` — consumed by
 * the chat panel polling loop after it receives the SSE
 * ``eval_pending`` chunk. ``status`` drives the client state machine:
 * pending → keep polling; skipped → stop silently; completed → stop
 * and optionally render a breach toast.
 */
export interface RunReplayResult {
  run_id: string;
  parent_run_id: string;
  status: string;
  trigger: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  replay_overrides: Record<string, unknown>;
  response_preview: string;
  eval_pending: boolean;
}

export interface ActiveSuggestionApplyResult extends DecisionDetail {
  replay?: RunReplayResult;
}

export interface RunReplayListResponse {
  parent_run_id: string;
  items: Array<Run & {
    replay_overrides: Record<string, unknown>;
    evaluation_scores: Record<string, unknown> | null;
  }>;
}

export interface EvaluationByRunResponse {
  status: 'pending' | 'skipped' | 'completed';
  run_id: string;
  breach?: boolean;
  composite_score?: number;
  hallucination_rate?: number;
  scores?: Record<string, number>;
  reasons?: Array<{ metric: string; [k: string]: unknown }>;
  evaluation_id?: string | null;
  decision_id?: string | null;
  reason?: string;
}

@Injectable({ providedIn: 'root' })
export class CanonicalApiService {
  private readonly api = inject(ApiService);

  // ---- Capabilities --------------------------------------------------------
  private unwrap<T>(raw: T[] | { [key: string]: T[] } | null | undefined, key: string): T[] {
    if (!raw) return [];
    if (Array.isArray(raw)) return raw;
    return ((raw as Record<string, T[]>)[key] ?? []) as T[];
  }

  listCapabilities(): Observable<Capability[]> {
    return this.api
      .get<Capability[] | { capabilities: Capability[] }>('/capabilities')
      .pipe(
        map((r) => this.unwrap<Capability>(r, 'capabilities')),
        catchError(() => of([] as Capability[])),
      );
  }

  catalog(): Observable<Capability[]> {
    return this.api
      .get<Capability[] | { capabilities: Capability[] }>('/capabilities/catalog')
      .pipe(
        map((r) => this.unwrap<Capability>(r, 'capabilities')),
        catchError(() => of([] as Capability[])),
      );
  }

  getCapability(id: string): Observable<Capability | null> {
    return this.api.get<Capability>(`/capabilities/${id}`).pipe(catchError(() => of(null)));
  }

  getCapabilityPerspective(
    id: string,
    lens: ObjectLens,
    window = '30d',
  ): Observable<ObjectPerspectiveResponse> {
    return this.api
      .get<ObjectPerspectiveResponse>(
        `/capabilities/${encodeURIComponent(id)}/perspective`,
        { lens, window },
      );
  }

  // ---- Skills --------------------------------------------------------------
  listSkills(): Observable<Skill[]> {
    return this.api
      .get<Skill[] | { skills: Skill[] }>('/skills')
      .pipe(
        map((r) => this.unwrap<Skill>(r, 'skills')),
        catchError(() => of([] as Skill[])),
      );
  }

  getSkill(slug: string): Observable<Skill | null> {
    return this.api.get<Skill>(`/skills/${encodeURIComponent(slug)}`).pipe(catchError(() => of(null)));
  }

  // ---- Systems -------------------------------------------------------------
  listSystems(options?: { workspaceSlug?: string | null; capability_id?: string }): Observable<System[]> {
    const params = options?.capability_id ? { capability_id: options.capability_id } : undefined;
    return this.api
      .get<System[] | { systems: System[] }>('/systems', params, {
        workspaceSlug: options?.workspaceSlug,
      })
      .pipe(
        map((r) => this.unwrap<System>(r, 'systems')),
        catchError(() => of([] as System[])),
      );
  }

  getSystem(id: string): Observable<System | null> {
    return this.api.get<System>(`/systems/${id}`).pipe(catchError(() => of(null)));
  }

  /** Strict counterpart used by mutation-sensitive editors: unlike
   * ``getSystem``, transport and HTTP errors propagate to the subscriber. */
  getSystemStrict(id: string): Observable<System> {
    return this.api.get<System>(`/systems/${id}`);
  }

  getSystemValueLoop(id: string): Observable<SystemValueLoop> {
    return this.api
      .get<SystemValueLoop>(`/systems/${encodeURIComponent(id)}/value-loop`);
  }

  createValueScenario(
    systemId: string,
    body: {
      source_run_id: string;
      objective: string;
      title: string;
      rationale?: Record<string, unknown>;
    },
    idempotencyKey: string,
  ): Observable<ValueScenario> {
    return this.api.post<ValueScenario>(
      `/systems/${encodeURIComponent(systemId)}/value-loop/scenarios`,
      body,
      { headers: { 'Idempotency-Key': idempotencyKey } },
    );
  }

  simulateValueScenario(
    systemId: string,
    scenarioId: string,
    recommendedPatch: Record<string, number>,
    idempotencyKey: string,
  ): Observable<ValueLoopSimulation> {
    return this.api.post<ValueLoopSimulation>(
      `/systems/${encodeURIComponent(systemId)}/value-loop/scenarios/${encodeURIComponent(scenarioId)}/simulate`,
      { recommended_patch: recommendedPatch },
      { headers: { 'Idempotency-Key': idempotencyKey } },
    );
  }

  approveValueScenario(
    systemId: string,
    scenarioId: string,
    simulationId: string,
    idempotencyKey: string,
  ): Observable<ValueScenario> {
    return this.api.post<ValueScenario>(
      `/systems/${encodeURIComponent(systemId)}/value-loop/scenarios/${encodeURIComponent(scenarioId)}/approve`,
      { simulation_id: simulationId },
      { headers: { 'Idempotency-Key': idempotencyKey } },
    );
  }

  actOnValueScenario(
    systemId: string,
    scenarioId: string,
    actuator: string,
    patch: Record<string, number>,
    idempotencyKey: string,
  ): Observable<ValueLoopActionExecution> {
    return this.api.post<ValueLoopActionExecution>(
      `/systems/${encodeURIComponent(systemId)}/value-loop/scenarios/${encodeURIComponent(scenarioId)}/act`,
      { actuator, patch },
      { headers: { 'Idempotency-Key': idempotencyKey } },
    );
  }

  measureValueScenario(
    systemId: string,
    scenarioId: string,
    sourceRunId: string | null,
    idempotencyKey: string,
  ): Observable<ValueLoopMeasurement> {
    return this.api.post<ValueLoopMeasurement>(
      `/systems/${encodeURIComponent(systemId)}/value-loop/scenarios/${encodeURIComponent(scenarioId)}/measure`,
      { source_run_id: sourceRunId },
      { headers: { 'Idempotency-Key': idempotencyKey } },
    );
  }

  getSystemFlowManifest(id: string): Observable<FlowRuntimeManifest | null> {
    return this.api
      .get<FlowRuntimeManifest>(`/systems/${id}/flow-manifest`)
      .pipe(catchError(() => of(null)));
  }

  createSystem(
    body: Partial<System>,
    opts?: { flow_write_intent?: 'replace_active_flow' },
  ): Observable<System | null> {
    const query = opts?.flow_write_intent
      ? `?flow_write_intent=${encodeURIComponent(opts.flow_write_intent)}`
      : '';
    return this.api.post<System>(`/systems${query}`, body).pipe(catchError(() => of(null)));
  }

  updateSystem(
    id: string,
    body: Partial<System>,
    opts?: {
      expected_flow_sha256?: string;
      flow_write_intent?: 'replace_active_flow';
    },
  ): Observable<System | null> {
    const params: Record<string, string> = {};
    if (opts?.expected_flow_sha256) {
      params['expected_flow_sha256'] = opts.expected_flow_sha256;
    }
    if (opts?.flow_write_intent) params['flow_write_intent'] = opts.flow_write_intent;
    const qs = new URLSearchParams(params).toString();
    const url = `/systems/${id}${qs ? `?${qs}` : ''}`;
    return this.api.patch<System>(url, body).pipe(catchError(() => of(null)));
  }

  deleteSystem(id: string): Observable<boolean> {
    return this.api.delete<void>(`/systems/${id}`).pipe(
      map(() => true),
      catchError(() => of(false)),
    );
  }

  // ---- Custom chain versioning (Vague E / E3) ----------------------------
  // Purpose-built save-with-errors wrapper. Unlike ``updateSystem`` which
  // swallows every failure into ``null``, this one surfaces the structured
  // 400 payload emitted by the DAG validator so the editor can pipe server
  // issues into its validation strip exactly the way client-side issues
  // are displayed.
  saveSystemFlow(
    id: string,
    flow_definition: Record<string, unknown>,
    opts?: {
      version_message?: string;
      expected_flow_sha256?: string;
      flow_write_intent?: 'replace_active_flow';
    },
  ): Observable<SaveSystemFlowResult> {
    const params: Record<string, string> = {};
    if (opts?.version_message) params['version_message'] = opts.version_message;
    if (opts?.expected_flow_sha256) {
      params['expected_flow_sha256'] = opts.expected_flow_sha256;
    }
    if (opts?.flow_write_intent) params['flow_write_intent'] = opts.flow_write_intent;
    let url = `/systems/${id}`;
    const qs = new URLSearchParams(params).toString();
    if (qs) url = `${url}?${qs}`;
    return this.api
      .patch<System & { validation_warnings?: FlowValidationIssue[]; new_version?: SystemVersionSummary }>(url, {
        flow_definition,
      })
      .pipe(
        map((system) => ({
          ok: true as const,
          system: system as System,
          warnings: (system as { validation_warnings?: FlowValidationIssue[] }).validation_warnings ?? [],
          new_version:
            (system as { new_version?: SystemVersionSummary }).new_version ?? null,
        })),
        catchError((err: HttpErrorResponse) => {
          const detail = (err.error?.detail ?? err.error) as {
            error?: string;
            message?: string;
            issues?: FlowValidationIssue[];
          } | undefined;
          if (err?.status === 409) {
            if (detail?.error === 'active_flow_replace_intent_required') {
              return of<SaveSystemFlowResult>({
                ok: false,
                reason: 'explicit_intent_required',
                message:
                  detail.message ??
                  'Replacing an active flow requires explicit confirmation.',
                issues: detail.issues ?? [],
              });
            }
            if (
              detail?.error === 'flow_precondition_missing' ||
              detail?.error === 'flow_precondition_stale'
            ) {
              return of<SaveSystemFlowResult>({
                ok: false,
                reason: 'conflict',
                message:
                  detail.message ??
                  'The flow changed since it was loaded. Reload it before saving.',
                issues: detail.issues ?? [],
              });
            }
          }
          if (err?.status === 400) {
            if (detail?.error === 'flow_invalid' || Array.isArray(detail?.issues)) {
              return of<SaveSystemFlowResult>({
                ok: false,
                reason: 'invalid',
                message: detail?.message ?? 'Flow definition has structural errors.',
                issues: detail?.issues ?? [],
              });
            }
          }
          return of<SaveSystemFlowResult>({
            ok: false,
            reason: 'network',
            message: err?.statusText || err?.message || 'Unknown backend error.',
            issues: [],
          });
        }),
      );
  }

  listSystemVersions(
    id: string,
    params?: { limit?: number; offset?: number },
  ): Observable<SystemVersionList> {
    const q: Record<string, string> = {};
    if (params?.limit != null) q['limit'] = String(params.limit);
    if (params?.offset != null) q['offset'] = String(params.offset);
    return this.api
      .get<SystemVersionList>(`/systems/${id}/versions`, q)
      .pipe(
        catchError(() =>
          of<SystemVersionList>({ total: 0, limit: 0, offset: 0, versions: [] }),
        ),
      );
  }

  getSystemVersion(id: string, versionNumber: number): Observable<SystemVersionFull | null> {
    return this.api
      .get<SystemVersionFull>(`/systems/${id}/versions/${versionNumber}`)
      .pipe(catchError(() => of(null)));
  }

  rollbackSystemVersion(
    id: string,
    versionNumber: number,
    message?: string,
    opts?: {
      expected_flow_sha256?: string;
      flow_write_intent?: 'replace_active_flow';
    },
  ): Observable<SystemRollbackResult | null> {
    const params: Record<string, string> = {};
    if (opts?.expected_flow_sha256) {
      params['expected_flow_sha256'] = opts.expected_flow_sha256;
    }
    if (opts?.flow_write_intent) params['flow_write_intent'] = opts.flow_write_intent;
    const qs = new URLSearchParams(params).toString();
    return this.api
      .post<SystemRollbackResult>(
        `/systems/${id}/versions/${versionNumber}/rollback${qs ? `?${qs}` : ''}`,
        { message: message ?? null },
      )
      .pipe(catchError(() => of(null)));
  }

  /** Fetch the portable JSON envelope for a system (Vague E / E3.4). */
  exportSystem(id: string): Observable<SystemExportEnvelope | null> {
    return this.api
      .get<SystemExportEnvelope>(`/systems/${id}/export`)
      .pipe(catchError(() => of(null)));
  }

  /** Import a system from an envelope. Mirrors the ``saveSystemFlow``
   *  discriminated-union pattern so the UI can distinguish a malformed
   *  envelope, a structurally-invalid flow, and a network failure. */
  importSystem(
    envelope: Record<string, unknown>,
    targetName?: string | null,
  ): Observable<SystemImportResult> {
    return this.api
      .post<System & {
        import_report: SystemImportReport;
        validation_warnings?: FlowValidationIssue[];
      }>('/systems/import', {
        envelope,
        target_name: targetName ?? null,
      })
      .pipe(
        map((res) => {
          if (!res) {
            return {
              ok: false,
              reason: 'network',
              message: 'Empty backend response.',
              issues: [],
            } satisfies SystemImportResult;
          }
          const { import_report, validation_warnings, ...rest } = res;
          return {
            ok: true,
            system: rest as System,
            import_report,
            validation_warnings: validation_warnings ?? [],
          } satisfies SystemImportResult;
        }),
        catchError((err: HttpErrorResponse | unknown) => {
          if (err instanceof HttpErrorResponse && err.status === 400) {
            const detail = (err.error?.detail ?? err.error) as {
              error?: string;
              message?: string;
              issues?: FlowValidationIssue[];
            } | undefined;
            if (detail?.error === 'flow_invalid') {
              return of<SystemImportResult>({
                ok: false,
                reason: 'flow_invalid',
                message: detail.message ?? 'Imported flow has structural errors.',
                issues: detail.issues ?? [],
              });
            }
            if (detail?.error === 'invalid_envelope') {
              return of<SystemImportResult>({
                ok: false,
                reason: 'invalid_envelope',
                message: detail.message ?? 'Envelope is malformed.',
                issues: [],
              });
            }
          }
          return of<SystemImportResult>({
            ok: false,
            reason: 'network',
            message:
              (err as HttpErrorResponse)?.statusText ||
              (err as Error)?.message ||
              'Unknown backend error.',
            issues: [],
          });
        }),
      );
  }

  // ---- Contexts ------------------------------------------------------------
  listContexts(params?: { system_id?: string }): Observable<Context[]> {
    const p: Record<string, string> = {};
    if (params?.system_id) p['system_id'] = params.system_id;
    return this.api
      .get<Context[] | { contexts: Context[] }>('/contexts', p)
      .pipe(
        map((r) => this.unwrap<Context>(r, 'contexts')),
        catchError(() => of([] as Context[])),
      );
  }

  getContext(id: string): Observable<Context | null> {
    return this.api.get<Context>(`/contexts/${id}`).pipe(catchError(() => of(null)));
  }

  createContext(
    body: Partial<Context>,
    options?: { workspaceSlug?: string | null },
  ): Observable<Context | null> {
    return this.api.post<Context>('/contexts', body, options).pipe(catchError(() => of(null)));
  }

  updateContext(
    id: string,
    body: Partial<Context>,
    options?: { workspaceSlug?: string | null },
  ): Observable<Context | null> {
    return this.api.patch<Context>(`/contexts/${id}`, body, options).pipe(catchError(() => of(null)));
  }

  deleteContext(id: string): Observable<boolean> {
    return this.api.delete<void>(`/contexts/${id}`).pipe(
      map(() => true),
      catchError(() => of(false)),
    );
  }

  /**
   * Promote an ephemeral drop-and-ask Context to permanent. Idempotent on
   * already-permanent contexts. See Vague D / D0 plan.
   */
  persistContext(
    id: string,
    options?: { workspaceSlug?: string | null },
  ): Observable<Context | null> {
    return this.api
      .post<Context>(`/contexts/${id}/persist`, {}, options)
      .pipe(catchError(() => of(null)));
  }

  // ---- Runs ----------------------------------------------------------------
  triggerRun(systemId: string, payload?: Record<string, unknown>): Observable<Run | null> {
    return this.api
      .post<Run>(`/systems/${systemId}/runs`, payload ?? {})
      .pipe(catchError(() => of(null)));
  }

  /**
   * Replay a finished run: the backend copies its input and its flow snapshot,
   * so the graph re-executes as it stood then, not as it stands today.
   */
  rerunRun(id: string): Observable<Run | null> {
    return this.api.post<Run>(`/runs/${id}/rerun`, {}).pipe(catchError(() => of(null)));
  }

  listRuns(params?: { system_id?: string; capability_id?: string }): Observable<Run[]> {
    const p: Record<string, string> = {};
    if (params?.system_id) p['system_id'] = params.system_id;
    if (params?.capability_id) p['capability_id'] = params.capability_id;
    return this.api
      .get<Run[] | { runs: Run[] }>('/runs', p)
      .pipe(
        map((r) => this.unwrap<Run>(r, 'runs')),
        catchError(() => of([] as Run[])),
      );
  }

  getRun(id: string): Observable<Run | null> {
    return this.api.get<Run & { invocations?: SkillInvocation[] }>(`/runs/${id}`).pipe(
      map((r) => {
        if (!r) return null;
        // Backend returns `invocations`; UI expects `skill_invocations`.
        return {
          ...r,
          skill_invocations: r.skill_invocations ?? r.invocations ?? [],
        } as Run;
      }),
      catchError(() => of(null)),
    );
  }

  getRunPerspective(
    id: string,
    lens: ObjectLens,
    window = '30d',
  ): Observable<ObjectPerspectiveResponse> {
    return this.api
      .get<ObjectPerspectiveResponse>(
        `/runs/${encodeURIComponent(id)}/perspective`,
        { lens, window },
      );
  }

  getSkillInvocation(runId: string, invocationId: string): Observable<SkillInvocation | null> {
    return this.api
      .get<SkillInvocation>(
        `/runs/${encodeURIComponent(runId)}/invocations/${encodeURIComponent(invocationId)}`,
      )
      .pipe(catchError(() => of(null)));
  }

  getSkillInvocationPerspective(
    runId: string,
    invocationId: string,
    lens: ObjectLens,
    window = '30d',
  ): Observable<ObjectPerspectiveResponse> {
    return this.api
      .get<ObjectPerspectiveResponse>(
        `/runs/${encodeURIComponent(runId)}/invocations/${encodeURIComponent(invocationId)}/perspective`,
        { lens, window },
      );
  }

  workspaceOverview(window = '24h'): Observable<WorkspaceOverview | null> {
    return this.api
      .get<WorkspaceOverview>('/observability/workspace-overview', { window })
      .pipe(catchError(() => of(null)));
  }

  /**
   * Resolve a pending HITL checkpoint on a Run. The backend transitions
   * the linked Decision via the canonical state machine and then resumes
   * the DAG walker in the background.
   */
  resolveRunHitl(
    runId: string,
    body: { action: 'accept' | 'reject'; actor?: string; note?: string },
  ): Observable<Run | null> {
    return this.api
      .post<Run>(`/runs/${runId}/hitl`, body)
      .pipe(catchError(() => of(null)));
  }

  /**
   * Advance or halt a Run paused in the step debugger.
   *
   * Actions:
   *   * ``step``     — let the walker settle one more non-meta node.
   *   * ``continue`` — run until a breakpoint fires or the DAG ends.
   *   * ``stop``     — cancel the Run with ``debugger_stopped`` outcome.
   *
   * Optional ``breakpoints`` replaces the server-side breakpoint set
   * before resume (handy when the operator toggles flags from the UI).
   */
  stepRun(
    runId: string,
    body: { action: 'step' | 'continue' | 'stop'; breakpoints?: string[] },
  ): Observable<Run | null> {
    return this.api
      .post<Run>(`/runs/${runId}/step`, body)
      .pipe(catchError(() => of(null)));
  }

  /**
   * Trigger a Run against a System with an attached debugger config.
   * The backend stores ``_debug`` inside ``input_ref`` so the walker
   * picks it up on the first tick without needing a new API column.
   */
  triggerRunDebug(
    systemId: string,
    options: {
      mode: 'step' | 'breakpoints';
      breakpoints?: string[];
      payload?: Record<string, unknown>;
    },
  ): Observable<Run | null> {
    const body: Record<string, unknown> = { ...(options.payload || {}) };
    body['_debug'] = {
      mode: options.mode,
      breakpoints: options.breakpoints ?? [],
    };
    return this.triggerRun(systemId, body);
  }

  // ---- Impact / Hypervisor -------------------------------------------------
  impactPortfolio(period = 'qtd'): Observable<ImpactAggregate | null> {
    return this.api
      .get<ImpactAggregate>('/impact/portfolio', { period })
      .pipe(catchError(() => of(null)));
  }

  impactByCapability(period = 'qtd'): Observable<CapabilityRow[]> {
    return this.api
      .get<{ items: CapabilityRow[] }>('/impact/by-capability', { period })
      .pipe(
        map((r) => r?.items ?? []),
        catchError(() => of([] as CapabilityRow[])),
      );
  }

  impactBySystem(period = 'qtd'): Observable<Array<ImpactAggregate & { system_id: string; name?: string; status?: string }>> {
    return this.api
      .get<{ items: Array<ImpactAggregate & { system_id: string; name?: string; status?: string }> }>(
        '/impact/by-system',
        { period },
      )
      .pipe(
        map((r) => r?.items ?? []),
        catchError(() => of([])),
      );
  }

  hypervisorBalanceSheet(period = 'qtd'): Observable<HypervisorBalance | null> {
    return this.api
      .get<HypervisorBalance>('/hypervisor/balance-sheet', { period })
      .pipe(catchError(() => of(null)));
  }

  hypervisorValueLoop(): Observable<PortfolioValueLoop> {
    return this.api.get<PortfolioValueLoop>('/hypervisor/value-loop');
  }

  hypervisorRecommendations(): Observable<Recommendation[]> {
    return this.api
      .get<{ items: Recommendation[] }>('/hypervisor/recommendations')
      .pipe(
        map((r) => r?.items ?? []),
        catchError(() => of([] as Recommendation[])),
      );
  }

  generateProactiveRecommendations(
    body: {
      since_days?: number;
      min_evaluations?: number;
      min_breaches?: number;
      min_breach_rate?: number;
      dry_run?: boolean;
    } = {},
  ): Observable<ProactiveRecommendationGenerateResponse | null> {
    return this.api
      .post<ProactiveRecommendationGenerateResponse>('/hypervisor/recommendations/generate', body)
      .pipe(catchError(() => of(null)));
  }

  hypervisorWhatIf(body: {
    scope: string;
    target_id?: string | null;
    levers: Record<string, unknown>;
  }): Observable<WhatIfResult | null> {
    return this.api
      .post<WhatIfResult>('/hypervisor/what-if', body)
      .pipe(catchError(() => of(null)));
  }

  listDecisions(
    params: { status?: string; scope?: string; kind?: string; limit?: number; offset?: number } = {},
  ): Observable<{ items: DecisionRow[]; total: number; limit: number; offset: number }> {
    const p: Record<string, string | number> = {};
    if (params.status) p['status'] = params.status;
    if (params.scope) p['scope'] = params.scope;
    if (params.kind) p['kind'] = params.kind;
    if (params.limit != null) p['limit'] = params.limit;
    if (params.offset != null) p['offset'] = params.offset;
    return this.api
      .get<{ items: DecisionRow[]; total: number; limit: number; offset: number }>(
        '/hypervisor/decisions',
        p as Record<string, string>,
      )
      .pipe(
        catchError(() =>
          of({ items: [] as DecisionRow[], total: 0, limit: params.limit ?? 50, offset: params.offset ?? 0 }),
        ),
      );
  }

  createDecision(body: {
    scope: string;
    target_id?: string | null;
    kind: string;
    title: string;
    status?: 'proposed' | 'accepted' | 'rejected' | 'applied';
    rationale?: Record<string, unknown>;
    impact_estimate?: Record<string, unknown>;
    notes?: string;
  }): Observable<DecisionDetail | null> {
    return this.api
      .post<DecisionDetail>('/hypervisor/decisions', body)
      .pipe(catchError(() => of(null)));
  }

  getDecision(id: string): Observable<DecisionDetail | null> {
    return this.api
      .get<DecisionDetail>(`/hypervisor/decisions/${id}`)
      .pipe(catchError(() => of(null)));
  }

  acceptDecision(
    id: string,
    body: {
      note?: string;
      actor?: string;
      feedback_label?: 'false_positive' | 'true_breach' | 'correct_with_fix';
      feedback_corrected_output?: Record<string, unknown>;
    } = {},
  ): Observable<DecisionDetail | null> {
    return this.api
      .post<DecisionDetail>(`/hypervisor/decisions/${id}/accept`, body)
      .pipe(catchError(() => of(null)));
  }

  rejectDecision(
    id: string,
    body: {
      note?: string;
      actor?: string;
      feedback_label?: 'false_positive' | 'true_breach' | 'correct_with_fix';
      feedback_corrected_output?: Record<string, unknown>;
    } = {},
  ): Observable<DecisionDetail | null> {
    return this.api
      .post<DecisionDetail>(`/hypervisor/decisions/${id}/reject`, body)
      .pipe(catchError(() => of(null)));
  }

  /**
   * Replay a settled run with operator overrides applied — E1.5.2.
   *
   * Returns the new run id and a short response preview so the UI can
   * confirm the replay landed before the eval polling kicks in.
   * Front-end keeps it simple: we always POST and trust the backend
   * to validate the override keys.
   */
  replayRun(
    runId: string,
    body: {
      overrides?: Record<string, unknown>;
      actor?: string;
      source_decision_id?: string;
      source_feedback_id?: string;
    } = {},
  ): Observable<RunReplayResult | null> {
    return this.api
      .post<RunReplayResult>(`/runs/${runId}/replay`, body)
      .pipe(catchError(() => of(null)));
  }

  listRunReplays(runId: string): Observable<RunReplayListResponse | null> {
    return this.api
      .get<RunReplayListResponse>(`/runs/${runId}/replays`)
      .pipe(catchError(() => of(null)));
  }

  applyDecision(
    id: string,
    body: { actor?: string; enact?: boolean; patch?: Record<string, unknown> } = { enact: true },
  ): Observable<DecisionDetail | null> {
    return this.api
      .post<DecisionDetail>(`/hypervisor/decisions/${id}/apply`, body)
      .pipe(catchError(() => of(null)));
  }

  applyActiveSuggestion(
    id: string,
    body: { actor?: string } = {},
  ): Observable<ActiveSuggestionApplyResult | null> {
    return this.api
      .post<ActiveSuggestionApplyResult>(
        `/hypervisor/decisions/${id}/apply-active-suggestion`,
        body,
      )
      .pipe(catchError(() => of(null)));
  }

  // ---- Evaluation loop (Vague E / E1) -------------------------------------
  // Review queue and threshold presets. The backend already has a legacy
  // `/evaluation/score` manual endpoint (wired into the chat fact-check
  // button); these are additive, see `backend/app/api/v1/endpoints/evaluation.py`.
  getEvaluationReviewQueue(
    params: {
      status?: 'proposed' | 'accepted' | 'rejected' | 'applied' | 'all';
      component?: string;
      limit?: number;
    } = {},
  ): Observable<EvaluationReviewQueueResponse | null> {
    const q: Record<string, string> = {};
    if (params.status) q['status'] = params.status;
    if (params.component) q['component'] = params.component;
    if (params.limit != null) q['limit'] = String(params.limit);
    return this.api
      .get<EvaluationReviewQueueResponse>('/evaluation/review-queue', q)
      .pipe(catchError(() => of(null)));
  }

  getEvaluationPresets(
    params: { capability_id?: string; system_id?: string } = {},
  ): Observable<EvaluationPresetResponse | null> {
    const q: Record<string, string> = {};
    if (params.capability_id) q['capability_id'] = params.capability_id;
    if (params.system_id) q['system_id'] = params.system_id;
    return this.api
      .get<EvaluationPresetResponse>('/evaluation/presets', q)
      .pipe(catchError(() => of(null)));
  }

  updateEvaluationPreset(body: Partial<EvaluationPresetConfig> & { name?: string }): Observable<{
    id: string;
    name: string;
    config: EvaluationPresetConfig;
    updated_at: string | null;
  } | null> {
    return this.api
      .put<{
        id: string;
        name: string;
        config: EvaluationPresetConfig;
        updated_at: string | null;
      }>('/evaluation/presets', body)
      .pipe(catchError(() => of(null)));
  }

  getEvaluationTrend(
    params: { since?: string; group_by?: 'day' | 'capability' | 'system' } = {},
  ): Observable<EvaluationTrendResponse | null> {
    const q: Record<string, string> = {};
    if (params.since) q['since'] = params.since;
    if (params.group_by) q['group_by'] = params.group_by;
    return this.api
      .get<EvaluationTrendResponse>('/evaluation/trend', q)
      .pipe(catchError(() => of(null)));
  }

  getEvaluationComponentHealth(
    params: { since?: string } = {},
  ): Observable<EvaluationComponentHealthResponse | null> {
    const q: Record<string, string> = {};
    if (params.since) q['since'] = params.since;
    return this.api
      .get<EvaluationComponentHealthResponse>('/evaluation/component-health', q)
      .pipe(catchError(() => of(null)));
  }

  listCanonicalAnswers(
    params: { limit?: number; offset?: number } = {},
  ): Observable<CanonicalAnswerListResponse | null> {
    const q: Record<string, string> = {};
    if (params.limit != null) q['limit'] = String(params.limit);
    if (params.offset != null) q['offset'] = String(params.offset);
    return this.api
      .get<CanonicalAnswerListResponse>('/evaluation/canonical-answers', q)
      .pipe(catchError(() => of(null)));
  }

  deleteCanonicalAnswer(id: string): Observable<boolean> {
    return this.api.delete<void>(`/evaluation/canonical-answers/${id}`).pipe(
      map(() => true),
      catchError(() => of(false)),
    );
  }

  /**
   * Polled by the chat panel after a reply streams back, so a
   * threshold breach can be surfaced as a toast within a few seconds
   * of the judge finishing. Returns ``null`` on network error so the
   * caller just stops polling rather than crashing the panel.
   */
  getEvaluationByRun(
    runId: string,
    options?: { workspaceSlug?: string | null },
  ): Observable<EvaluationByRunResponse | null> {
    return this.api
      .get<EvaluationByRunResponse>(
        `/evaluation/by-run/${encodeURIComponent(runId)}`,
        undefined,
        options,
      )
      .pipe(catchError(() => of(null)));
  }

  overrideRunOutcome(
    runId: string,
    body: { value: number; note?: string },
  ): Observable<RunDetail | null> {
    return this.api
      .patch<RunDetail>(`/runs/${runId}/outcome`, body)
      .pipe(catchError(() => of(null)));
  }

  // ---- Control plane ------------------------------------------------------
  controlPolicies(params?: { scope?: string; target_id?: string }): Observable<ControlPolicy[]> {
    const p: Record<string, string> = {};
    if (params?.scope) p['scope'] = params.scope;
    if (params?.target_id) p['target_id'] = params.target_id;
    return this.api
      .get<{ policies: ControlPolicy[] }>('/control-plane/policies', p)
      .pipe(
        map((r) => r?.policies ?? []),
        catchError(() => of([] as ControlPolicy[])),
      );
  }

  createControlPolicy(body: Partial<ControlPolicy>): Observable<ControlPolicy | null> {
    return this.api
      .post<ControlPolicy>('/control-plane/policies', body)
      .pipe(catchError(() => of(null)));
  }

  adaptivePolicies(params?: { scope?: string; target_id?: string }): Observable<AdaptivePolicy[]> {
    const p: Record<string, string> = {};
    if (params?.scope) p['scope'] = params.scope;
    if (params?.target_id) p['target_id'] = params.target_id;
    return this.api
      .get<{ policies: AdaptivePolicy[] }>('/control-plane/adaptive', p)
      .pipe(
        map((r) => r?.policies ?? []),
        catchError(() => of([] as AdaptivePolicy[])),
      );
  }

  createAdaptivePolicy(body: Partial<AdaptivePolicy>): Observable<AdaptivePolicy | null> {
    return this.api
      .post<AdaptivePolicy>('/control-plane/adaptive', body)
      .pipe(catchError(() => of(null)));
  }

  updateAdaptivePolicy(id: string, body: Partial<AdaptivePolicy>): Observable<AdaptivePolicy | null> {
    return this.api
      .patch<AdaptivePolicy>(`/control-plane/adaptive/${id}`, body)
      .pipe(catchError(() => of(null)));
  }

  toggleAdaptivePolicy(id: string, enabled?: boolean): Observable<AdaptivePolicy | null> {
    const body = enabled === undefined ? {} : { enabled };
    return this.api
      .post<AdaptivePolicy>(`/control-plane/adaptive/${id}/toggle`, body)
      .pipe(catchError(() => of(null)));
  }

  deleteAdaptivePolicy(id: string): Observable<boolean> {
    return this.api
      .delete<void>(`/control-plane/adaptive/${id}`)
      .pipe(
        map(() => true),
        catchError(() => of(false)),
      );
  }

  simulate(body: {
    scope: string;
    target_id?: string | null;
    levers: { resource?: number; velocity?: number; autonomy?: number; risk_tolerance?: number };
  }): Observable<SimulateResult | null> {
    return this.api
      .post<SimulateResult>('/control-plane/simulate', body)
      .pipe(catchError(() => of(null)));
  }
}

// ---- Control plane types (appended here so they stay with the service) ----
export interface ControlPolicy {
  id: string;
  name: string;
  scope: 'workspace' | 'capability' | 'system' | string;
  target_id?: string | null;
  max_cost_per_decision?: number | null;
  max_latency_ms?: number | null;
  mandatory_hitl_if_confidence_below?: number | null;
  allowed_models?: string[];
  allowed_skills?: string[];
  extra?: Record<string, unknown>;
}

export interface AdaptivePolicy {
  id: string;
  name: string;
  enabled: boolean;
  adaptation_level: 'conservative' | 'moderate' | 'aggressive' | string;
  scope?: 'workspace' | 'portfolio' | 'capability' | 'system' | string | null;
  target_id?: string | null;
  triggers?: Record<string, unknown>;
  allowed_actions?: string[];
  constraints?: Record<string, unknown>;
}

export interface DecisionRow {
  id: string;
  scope: string;
  target_id?: string | null;
  kind: string;
  status: string;
  title: string;
  created_at?: string | null;
  approved_by?: string | null;
  applied_at?: string | null;
}

export interface DecisionDetail extends DecisionRow {
  rationale?: Record<string, unknown>;
  impact_estimate?: Record<string, unknown>;
  notes?: string;
  approved_at?: string | null;
  applied_by?: string | null;
  applied_patch?: Record<string, unknown>;
}

export interface RunOutcome {
  decision?: string | null;
  confidence?: number | null;
  value_estimated?: number | null;
  cost_internal?: number | null;
  revenue_allocated?: number | null;
  efficiency?: number | null;
  value_source?: 'auto' | 'operator' | 'unset';
  operator_value_note?: string | null;
}

export interface RunDetail {
  id: string;
  system_id?: string | null;
  capability_id?: string | null;
  status: string;
  trigger?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
  outcome: RunOutcome;
  retries?: number;
  error?: string | null;
  invocations?: Array<Record<string, unknown>>;
}

export interface SimulateResult {
  scope: string;
  target_id?: string | null;
  base: ImpactAggregate;
  projected: {
    total_cost: number | null;
    estimated_value: number | null;
    roi: number | null;
    latency_index: number;
    risk_index: number;
  };
}
