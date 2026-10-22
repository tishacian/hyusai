/** Provider-call accounting. Missing measurements stay unknown; currencies never merge. */
export type UsageTraffic = 'all' | 'business' | 'evaluation' | 'preview' | 'ingestion';
export interface UsageFilters {
  window?: '24h' | '7d' | '30d' | '90d'; as_of?: string; system_id?: string; run_id?: string;
  provider?: string; model?: string; purpose?: string; traffic?: UsageTraffic;
  status?: string; limit?: number; offset?: number;
  run_scope?: 'direct' | 'tree';
}
export interface UsageCoverage { mode: string; complete: boolean; scanned: number; limit: number; }
export interface UsageCost { currency: string; known_amount: number | string | null; known_calls: number; unknown_calls: number; basis: string; }
export interface UsageGroup {
  provider: string; model: string; purpose: string; calls: number; total_tokens: number | null;
  known_amount: number | string | null; currency: string | null;
  system_id?: string | null; traffic?: string;
}
export interface UsageSummary {
  counts: { calls: number; dispatched: number; completed: number; failed: number; unknown: number; blocked: number };
  tokens: { input: number | null; output: number | null; total: number | null; cached_input: number | null;
    cache_write: number | null; reasoning: number | null; known_calls: number; unknown_calls: number };
  costs: UsageCost[]; groups: UsageGroup[]; coverage: UsageCoverage;
}
export interface UsageCall {
  id: string; run_id: string | null; system_id: string | null; root_system_id: string | null;
  invocation_id: string | null; job_id: string | null; campaign_id: string | null; evaluation_id: string | null;
  purpose: string; traffic: string; provider: string; model: string; returned_model: string | null;
  status: string; started_at: string; completed_at: string | null; latency_ms: number | null;
  input_tokens: number | null; output_tokens: number | null; total_tokens: number | null;
  cached_input_tokens: number | null; cache_write_tokens: number | null; reasoning_tokens: number | null;
  amount: number | string | null; currency: string | null; cost_basis: string | null;
  tariff_snapshot?: Pick<UsageTariff, 'id' | 'revision' | 'version' | 'provider' | 'model' | 'currency' | 'provenance'> & { rates: Partial<Record<UsageRateKey, string>> } | null;
  usage_coverage: string | Record<string, unknown> | null; diagnostic: string | Record<string, unknown> | null;
}
export interface UsageCallPage { items: UsageCall[]; total: number | null; limit: number; offset: number; coverage: UsageCoverage; }
export interface UsageSeries { buckets: Array<UsageSummary & { date: string }>; timezone: string; }
export interface UsageReadiness { ready: boolean; code: string | null; missing_transports: string[]; coverage_started_at?: string | null; }
export interface UsageBudget {
  id: string; scope: 'workspace' | 'system'; system_id: string | null; revision: number; enabled: boolean;
  timezone: string; max_tokens: number | null; currency_limits: Record<string, string | number>; activated_at: string | null;
  reconciliation_required?: boolean;
  current_period: { start: string; end: string; consumed_tokens: number; reserved_tokens: number;
    amounts: Array<{ currency: string; consumed: number | string; reserved: number | string; limit: number | string | null }> };
  history?: Array<{ revision: number; at: string; actor: string; changes: Record<string, unknown> }>;
}
export interface UsageBudgetWrite {
  scope: 'workspace' | 'system'; system_id?: string; enabled: boolean; timezone: string;
  max_tokens: number | null; currency_limits: Record<string, string>; expected_revision: number;
}
export interface UsageBudgetPage { items: UsageBudget[]; can_manage: boolean; readiness: UsageReadiness; }
export type UsageRateKey = 'input_per_million' | 'output_per_million' | 'cached_input_per_million' | 'cache_write_per_million';
export interface UsageTariffProvenance {
  reference: string; observed_on: string;
  conversion?: { source_currency: string; source_rates: Partial<Record<UsageRateKey, string>>; rate: string;
    reference: string; observed_on: string; convention?: 'target_per_source'; rounding?: 'half_even_12dp' } | null;
}
export interface UsageTariff {
  id: string; provider: string; model: string; currency: string; version?: number; revision?: number;
  input_per_million: number | string; output_per_million: number | string;
  cached_input_per_million?: number | string | null; cache_write_per_million?: number | string | null;
  created_at?: string; effective_at?: string; provenance?: UsageTariffProvenance | null;
}
export interface UsageTariffWrite {
  provider: string; model: string; currency: string; input_per_million: string; output_per_million: string;
  cached_input_per_million?: string; cache_write_per_million?: string; provenance?: UsageTariffProvenance;
}
export interface UsageTariffPage { items: UsageTariff[]; can_manage: boolean; }
export interface UsageSystemOption { id: string; name: string; }
