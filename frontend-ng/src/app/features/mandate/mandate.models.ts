/** Read projections of the canonical control policy and persisted Run evidence. */
export type MandateMode = 'compat' | 'shadow' | 'enforce';
export interface MandateSpec {
  version?: number;
  enforcement_mode?: MandateMode;
  inbound?: { collection_allowlist?: string[]; reference_type_filters?: string[]; reject_cross_project_sources?: boolean };
  outbound?: { expert_review_required?: boolean; gate_if_confidence_below?: number | null };
  capabilities?: { allowed_skills?: string[]; allowed_models?: string[]; allowed_actions?: string[]; allowed_delegations?: Array<string | {system_id: string; input_contract?: unknown; output_contract?: unknown; branches?: unknown}> };
  provenance?: { require_citations?: boolean; object_store_prefix?: string | null };
  valves?: { max_cost_per_decision?: number | null; max_latency_ms?: number | null; token_budget?: number | null; hard_abort?: boolean; mandatory_hitl_if_confidence_below?: number | null; circuit_breaker?: Record<string, unknown> | null };
}
export interface SystemMandate {
  system_id: string;
  system_name: string;
  reference_labels?: { skills?: Record<string, string>; delegations?: Record<string, string> };
  configuration: { configured_facets?: string[]; state: 'explicit' | 'derived' | 'not_configured' | 'invalid'; policy_id: string | null; policy_revision: string | null; version: number | null; mode: MandateMode | null; spec: MandateSpec | null; policy_binding?: 'frozen' | 'legacy_current' | 'invalid'; published_version_id?: string | null; published_version_number?: number | null; policy_snapshot_sha256?: string | null };
  permissions: { can_edit: boolean };
  editing_supported?: boolean;
  recent_runs_limit?: number;
  limitations: string[];
  recent_runs: Array<{run_id: string; status: string; started_at: string | null; evidence_state: 'recorded' | 'not_recorded'; event_count: number; recorded_mode?: MandateMode | null; recorded_version?: number | null; facets?: Record<string, {event_count:number;breach_count:number;state:'recorded'|'breached'|'not_recorded'}>}>;
}
export interface MandateEvent {
  id: string;
  kind: string;
  facet: string;
  status: 'recorded' | 'blocked' | 'observed' | 'awaiting_human' | 'approved' | 'rejected';
  at: string | null;
  node_id: string | null;
  invocation_id: string | null;
  decision_id: string | null;
  child_run_id?: string | null;
  rule: string | null;
  details: Record<string, unknown>;
}
export interface RunMandate {
  run_id: string;
  system_id: string;
  status: string;
  applied: {state: 'recorded' | 'not_recorded'; policy_id: string | null; revision: string | null; snapshot_at: string | null; mode: MandateMode | null; version: number | null; spec: MandateSpec | null; policy_binding?: 'frozen' | 'legacy_first_start' | 'legacy_identity_only' | 'invalid' | null; not_recorded_reason?: 'frozen_mandate_invalid' | 'mandate_start_identity_mismatch' | null};
  events: MandateEvent[];
  counts: {recorded_events: number; blocked: number; awaiting_human: number};
  limitations: string[];
}

export type MandateLane = 'sources' | 'operations' | 'review';
export function mandateLane(event: MandateEvent): MandateLane {
  if (event.facet === 'inbound') return 'sources';
  if (['outbound', 'provenance', 'human'].includes(event.facet)) return 'review';
  return 'operations';
}

/** An observed violation never becomes an actual stop; a stored mode is not proof of a check. */
export function mandateRunSummary(run: RunMandate): 'blocked' | 'awaiting_human' | 'recorded' | 'not_recorded' {
  if (run.events.some(event => event.status === 'blocked' || event.status === 'rejected')) return 'blocked';
  if (run.status === 'hitl_pending' && run.events.some(event => event.status === 'awaiting_human')) return 'awaiting_human';
  return run.events.length ? 'recorded' : 'not_recorded';
}

export function mandateInitialEvent(events: MandateEvent[], requestedId: string | null): MandateEvent | null {
  return events.find(event => event.id === requestedId)
    ?? events.find(event => ['blocked', 'awaiting_human', 'rejected'].includes(event.status))
    ?? events[0] ?? null;
}

/** Missing history and a recorded absence of policy convey different evidence. */
export function mandateSnapshotNote(run: RunMandate): string | null {
  if (run.applied.not_recorded_reason) return `mandate.limitation.${run.applied.not_recorded_reason}`;
  if (run.limitations.includes('no_policy_at_first_start')) return 'mandate.limitation.no_policy_at_first_start';
  if (!run.applied.spec) return 'mandate.run.snapshot_missing_hint';
  if (run.applied.policy_binding === 'legacy_first_start') return 'mandate.limitation.legacy_first_start';
  return null;
}

/** Resolver defaults in a derived compatibility spec do not establish a human gate. */
export function mandateReviewConfigured(configuration: SystemMandate['configuration']): boolean {
  if (configuration.state !== 'explicit') return false;
  const facets = configuration.configured_facets || [];
  return (facets.includes('outbound') && (configuration.spec?.outbound?.expert_review_required === true || configuration.spec?.outbound?.gate_if_confidence_below != null))
    || (facets.includes('valves') && configuration.spec?.valves?.mandatory_hitl_if_confidence_below != null);
}

export interface MandateOption { id: string; label: string; }
export interface MandateDelegationOption {
  system_id: string;
  label: string;
  input_contract?: Record<string, unknown>;
  output_contract?: Record<string, unknown>;
  branches: string[];
}
export interface MandateValidation {
  valid: boolean;
  checks: Array<{code: string; status: 'passed' | 'failed' | 'not_run'; field?: string; reason_code?: string; message?: string; details?: Record<string, unknown>}>;
}
export interface MandateDraftState {
  system_id: string;
  permissions: {can_edit: boolean};
  draft: {
    revision: number;
    flow_sha256: string;
    spec: MandateSpec | null;
    base_published_version_id: string | null;
    snapshot_sha256: string;
    policy_binding: 'frozen' | 'legacy_current' | 'not_configured';
    spec_is_seed?: boolean;
  };
  published: {
    version_id: string | null;
    version_number: number | null;
    spec: MandateSpec | null;
    policy_revision: string | null;
    snapshot_sha256: string | null;
    policy_binding: 'frozen' | 'legacy';
  };
  options: {
    collections: MandateOption[];
    skills: MandateOption[];
    models: MandateOption[];
    delegations: MandateDelegationOption[];
  };
  validation: MandateValidation;
  no_op?: boolean;
}
