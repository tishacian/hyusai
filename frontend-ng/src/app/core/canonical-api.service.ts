import { Injectable, inject } from '@angular/core';
import { Observable, catchError, map, of } from 'rxjs';
import { ApiService } from './api.service';

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
}

export interface SkillInvocation {
  id?: string;
  skill_slug?: string;
  skill_id?: string;
  status?: 'completed' | 'failed' | 'pending' | 'running';
  latency_ms?: number;
  cost?: number;
  started_at?: string;
  ended_at?: string;
  error?: string | null;
}

export interface RunHitlPayload {
  node_id?: string;
  prompt?: string;
  decision_id?: string;
  decision_status?: string | null;
  decision_title?: string | null;
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
  ended_at?: string;
  duration_ms?: number;
  outcome?: Outcome;
  checkpoints?: Array<Record<string, unknown>>;
  retries?: number;
  error?: string | null;
  trigger?: string;
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

export interface System {
  id: string;
  name: string;
  objective?: string;
  capability_id?: string | null;
  skill_ids?: string[];
  context_id?: string | null;
  control_policy_id?: string | null;
  adaptive_policy_id?: string | null;
  flow?: Record<string, unknown>;
  flow_definition?: Record<string, unknown>;
  status?: 'draft' | 'active' | 'paused' | 'archived';
  /** Canonical execution taxonomy — see schemas/canonical.ExecutionMode. */
  execution_mode?:
    | 'real_time_decision'
    | 'batch_processing'
    | 'event_driven_automation'
    | 'continuous_monitoring'
    | 'human_augmented';
  execution_profile?: Record<string, unknown>;
  // Canonical per-system defaults consumed by the run engine / RAG wrappers.
  default_prompt_type?: string | null;
  default_model?: string | null;
  retrieval_mode_default?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface ImpactAggregate {
  scope?: 'portfolio' | 'capability' | 'system';
  period?: string;
  runs_count?: number;
  total_cost?: number;
  estimated_value?: number;
  total_revenue?: number;
  roi?: number | null;
  avg_confidence?: number | null;
  avg_efficiency?: number | null;
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

export interface Recommendation {
  id: string;
  scope: string;
  target_id?: string | null;
  title: string;
  rationale: Record<string, unknown>;
  impact_estimate: Record<string, number>;
  status?: 'pending' | 'approved' | 'rejected' | 'applied';
  created_at?: string;
}

export interface WhatIfResult {
  scope: string;
  target_id?: string | null;
  base: ImpactAggregate;
  projected: {
    total_cost: number;
    estimated_value: number;
    roi: number | null;
    latency_index: number;
  };
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

  // ---- Skills --------------------------------------------------------------
  listSkills(): Observable<Skill[]> {
    return this.api
      .get<Skill[] | { skills: Skill[] }>('/skills')
      .pipe(
        map((r) => this.unwrap<Skill>(r, 'skills')),
        catchError(() => of([] as Skill[])),
      );
  }

  getSkill(id: string): Observable<Skill | null> {
    return this.api.get<Skill>(`/skills/${id}`).pipe(catchError(() => of(null)));
  }

  // ---- Systems -------------------------------------------------------------
  listSystems(): Observable<System[]> {
    return this.api
      .get<System[] | { systems: System[] }>('/systems')
      .pipe(
        map((r) => this.unwrap<System>(r, 'systems')),
        catchError(() => of([] as System[])),
      );
  }

  getSystem(id: string): Observable<System | null> {
    return this.api.get<System>(`/systems/${id}`).pipe(catchError(() => of(null)));
  }

  createSystem(body: Partial<System>): Observable<System | null> {
    return this.api.post<System>('/systems', body).pipe(catchError(() => of(null)));
  }

  updateSystem(id: string, body: Partial<System>): Observable<System | null> {
    return this.api.patch<System>(`/systems/${id}`, body).pipe(catchError(() => of(null)));
  }

  deleteSystem(id: string): Observable<boolean> {
    return this.api.delete<void>(`/systems/${id}`).pipe(
      map(() => true),
      catchError(() => of(false)),
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

  createContext(body: Partial<Context>): Observable<Context | null> {
    return this.api.post<Context>('/contexts', body).pipe(catchError(() => of(null)));
  }

  updateContext(id: string, body: Partial<Context>): Observable<Context | null> {
    return this.api.patch<Context>(`/contexts/${id}`, body).pipe(catchError(() => of(null)));
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
  persistContext(id: string): Observable<Context | null> {
    return this.api
      .post<Context>(`/contexts/${id}/persist`, {})
      .pipe(catchError(() => of(null)));
  }

  // ---- Runs ----------------------------------------------------------------
  triggerRun(systemId: string, payload?: Record<string, unknown>): Observable<Run | null> {
    return this.api
      .post<Run>(`/systems/${systemId}/runs`, payload ?? {})
      .pipe(catchError(() => of(null)));
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

  hypervisorRecommendations(): Observable<Recommendation[]> {
    return this.api
      .get<{ items: Recommendation[] }>('/hypervisor/recommendations')
      .pipe(
        map((r) => r?.items ?? []),
        catchError(() => of([] as Recommendation[])),
      );
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

  acceptDecision(id: string, body: { note?: string; actor?: string } = {}): Observable<DecisionDetail | null> {
    return this.api
      .post<DecisionDetail>(`/hypervisor/decisions/${id}/accept`, body)
      .pipe(catchError(() => of(null)));
  }

  rejectDecision(id: string, body: { note?: string; actor?: string } = {}): Observable<DecisionDetail | null> {
    return this.api
      .post<DecisionDetail>(`/hypervisor/decisions/${id}/reject`, body)
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

  // ---- Evaluation loop (Vague E / E1) -------------------------------------
  // Review queue and threshold presets. The backend already has a legacy
  // `/evaluation/score` manual endpoint (wired into the chat fact-check
  // button); these are additive, see `backend/app/api/v1/endpoints/evaluation.py`.
  getEvaluationReviewQueue(
    params: { status?: 'proposed' | 'accepted' | 'rejected' | 'applied' | 'all'; limit?: number } = {},
  ): Observable<EvaluationReviewQueueResponse | null> {
    const q: Record<string, string> = {};
    if (params.status) q['status'] = params.status;
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
  impact_estimate?: Record<string, number>;
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
    total_cost: number;
    estimated_value: number;
    roi: number | null;
    latency_index: number;
    risk_index: number;
  };
}
