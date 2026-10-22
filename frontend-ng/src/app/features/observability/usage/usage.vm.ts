import type { UsageBudget, UsageBudgetWrite, UsageFilters, UsageGroup, UsageSeries, UsageSummary, UsageTraffic } from './usage.models';

export const USAGE_TRAFFIC: UsageTraffic[] = ['all', 'business', 'evaluation', 'preview', 'ingestion'];
export function usageQuery(filters: UsageFilters): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value));
  }
  return query.toString();
}
export function usageNumber(value: unknown, locale = 'fr'): string {
  return typeof value === 'number' && Number.isFinite(value) ? new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(value) : '—';
}
export function usageAmount(value: unknown, currency: string | null, locale = 'fr'): string {
  if (value === null || value === undefined || value === '' || !currency) return '—';
  const amount = Number(value);
  if (!Number.isFinite(amount)) return '—';
  try { return new Intl.NumberFormat(locale, { style: 'currency', currency, minimumFractionDigits: 2, maximumFractionDigits: 6 }).format(amount); }
  catch { return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 6 }).format(amount)} ${currency}`; }
}
export function usageCostCoverage(summary: UsageSummary): { known: number; total: number } {
  return { known: summary.costs.reduce((sum, cost) => sum + cost.known_calls, 0), total: summary.counts.dispatched };
}
export function usageChartMaximum(values: Array<number | null>): number {
  const max = Math.max(0, ...values.filter((value): value is number => value !== null && Number.isFinite(value)));
  if (!max) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(max));
  return ([1, 2, 5, 10].find(step => step * magnitude >= max) || 10) * magnitude;
}
/** A chart gap represents absent measurement, including a bucket containing only unknown calls. */
export function usageSeriesValues(series: UsageSeries, metric: string): Array<{ date: string; value: number | null }> {
  return series.buckets.map(bucket => {
    if (metric === 'calls') return { date: bucket.date, value: bucket.counts.dispatched };
    if (metric === 'tokens') return { date: bucket.date, value: bucket.tokens.known_calls ? bucket.tokens.total : null };
    const cost = bucket.costs.find(item => item.currency === metric);
    return { date: bucket.date, value: cost && cost.known_calls && cost.known_amount !== null ? Number(cost.known_amount) : null };
  });
}
export function budgetAvailable(limit: unknown, consumed: unknown, reserved: unknown): number | null {
  if (limit === null || limit === undefined || limit === '') return null;
  const values = [limit, consumed, reserved].map(Number);
  return values.every(Number.isFinite) ? values[0] - values[1] - values[2] : null;
}
export function budgetPercent(limit: unknown, consumed: unknown, reserved: unknown): number {
  const cap = Number(limit), spent = Number(consumed), held = Number(reserved);
  return cap > 0 && [cap, spent, held].every(Number.isFinite) ? Math.max(0, Math.min(100, (spent + held) / cap * 100)) : 0;
}
export interface BudgetDraft { scope: 'workspace' | 'system'; systemId: string; timezone: string; tokenLimit: string; currencies: Array<{ currency: string; limit: string }>; }
export function budgetDraft(budget?: UsageBudget): BudgetDraft {
  return { scope: budget?.scope || 'workspace', systemId: budget?.system_id || '', timezone: budget?.timezone || 'UTC',
    tokenLimit: budget?.max_tokens == null ? '' : String(budget.max_tokens),
    currencies: Object.entries(budget?.currency_limits || {}).map(([currency, limit]) => ({ currency, limit: String(limit) })) };
}
/** No implicit activation and no invented limit. A blank limit is intentionally unconfigured. */
export function validateBudgetDraft(draft: BudgetDraft, enabled: boolean, revision: number): { body?: UsageBudgetWrite; error?: string } {
  if (draft.scope === 'system' && !draft.systemId) return { error: 'system_required' };
  try { new Intl.DateTimeFormat('en', { timeZone: draft.timezone }).format(); } catch { return { error: 'timezone_invalid' }; }
  const tokens = String(draft.tokenLimit ?? '').trim() ? Number(draft.tokenLimit) : null;
  if (tokens !== null && (!Number.isSafeInteger(tokens) || tokens < 0)) return { error: 'limit_invalid' };
  const currency_limits: Record<string, string> = {};
  for (const row of draft.currencies) {
    const currency = row.currency.trim().toUpperCase();
    const limit = String(row.limit ?? '').trim().replace(',', '.');
    if (!/^[A-Z]{3}$/.test(currency) || !/^\d+(\.\d+)?$/.test(limit) || !Number.isFinite(Number(limit))) return { error: 'limit_invalid' };
    if (currency in currency_limits) return { error: 'currency_duplicate' };
    currency_limits[currency] = limit;
  }
  if (tokens === null && !Object.keys(currency_limits).length) return { error: 'limit_required' };
  return { body: { scope: draft.scope, ...(draft.scope === 'system' ? { system_id: draft.systemId } : {}), enabled,
    timezone: draft.timezone, max_tokens: tokens, currency_limits, expected_revision: revision } };
}
export function diagnosticCode(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value && typeof value === 'object') {
    const row = value as Record<string, unknown>;
    return typeof row['code'] === 'string' ? row['code'] : typeof row['reason'] === 'string' ? row['reason'] : '';
  }
  return '';
}
export type UsageDimension = 'provider' | 'model' | 'purpose' | 'system_id' | 'traffic';
export function usageBreakdown(groups: UsageGroup[], dimension: UsageDimension): Array<{ key: string; calls: number; tokens: number | null; costs: Array<{ currency: string; amount: number }> }> {
  const result = new Map<string, { key: string; calls: number; tokens: number | null; costs: Map<string, number> }>();
  for (const group of groups) {
    const key = (dimension === 'model' ? [group.provider, group.model].filter(Boolean).join(' / ') : group[dimension]) || '';
    const row = result.get(key) || { key, calls: 0, tokens: null, costs: new Map<string, number>() };
    row.calls += group.calls;
    if (group.total_tokens !== null) row.tokens = (row.tokens ?? 0) + group.total_tokens;
    if (group.currency && group.known_amount !== null && Number.isFinite(Number(group.known_amount))) row.costs.set(group.currency, (row.costs.get(group.currency) || 0) + Number(group.known_amount));
    result.set(key, row);
  }
  return [...result.values()].sort((a, b) => b.calls - a.calls || a.key.localeCompare(b.key)).map(row => ({ ...row, costs: [...row.costs].map(([currency, amount]) => ({ currency, amount })) }));
}
