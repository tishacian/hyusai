import type { HypervisorBlockRef, HypervisorNamedView } from './hypervisor-v2-views';
import type { HypervisorSeriesResponse } from './hypervisor-v2-series';

export const ACTIVITY_METRICS = ['statuses', 'calls', 'costs', 'duration'] as const;
export type ActivityMetric = typeof ACTIVITY_METRICS[number];
export const SCENARIO_FIELDS = ['manual_minutes', 'assisted_minutes', 'hourly_cost', 'unit_budget', 'monthly_volume'] as const;
export type ScenarioField = typeof SCENARIO_FIELDS[number];

export interface ExecutionActivity {
  window: string;
  from: string;
  to: string;
  limited: boolean;
  limit: number;
  counts: { attempts: number; completed: number; failed: number; cancelled: number; pending: number; invocations: number };
  buckets: { date: string; attempts: number; completed: number; failed: number; cancelled: number; pending: number }[];
  costs: { state: string; by_currency: Record<string, string>; priced_invocations: number; unpriced_invocations: number };
  median_technical_seconds: number | null;
  technical_sample_count: number;
  runs: { id: string; system_id: string; status: string; started_at: string; technical_seconds: number | null }[];
}

/** User-entered assumptions only. A missing value never becomes zero. */
export function financialScenario(settings: Record<string, unknown>) {
  const required = SCENARIO_FIELDS.filter(field => field !== 'monthly_volume');
  for (const key of required) {
    const value = settings[key];
    const maximum = key.endsWith('minutes') ? 1440 : 1000000;
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > maximum) return null;
  }
  const currency = settings['currency'];
  if (typeof currency !== 'string' || !/^[A-Z]{3}$/.test(currency)) return null;
  const volume = settings['monthly_volume'];
  if (volume != null && (typeof volume !== 'number' || !Number.isInteger(volume) || volume < 0 || volume > 1000000)) return null;
  const savedMinutes = (settings['manual_minutes'] as number) - (settings['assisted_minutes'] as number);
  const hourly = settings['hourly_cost'] as number;
  const budget = settings['unit_budget'] as number;
  const capacity = savedMinutes / 60 * hourly;
  const net = capacity - budget;
  return {
    currency, savedMinutes, capacity, net,
    roi: budget > 0 ? net / budget : null,
    breakEvenMinutes: hourly > 0 ? budget / hourly * 60 : null,
    monthlyNet: typeof volume === 'number' ? net * volume : null,
  };
}

export function activityMetrics(block: HypervisorBlockRef): readonly ActivityMetric[] {
  const raw = block.settings['metrics'];
  return Array.isArray(raw)
    ? ACTIVITY_METRICS.filter(metric => raw.includes(metric))
    : ACTIVITY_METRICS;
}

export function scopedSeries(raw: HypervisorSeriesResponse, view: HypervisorNamedView | null): HypervisorSeriesResponse {
  return view?.system_id ? { ...raw, systems: raw.systems.filter(system => system.system_id === view.system_id) } : raw;
}

/** Legacy headline fields share a band; all bands follow the saved block order. */
export function summarySections(view: HypervisorNamedView | null): string[] {
  const sections: string[] = [];
  const add = (type: string) => { if (!sections.includes(type)) sections.push(type); };
  for (const block of view?.strata.comprendre ?? []) {
    if (['monument', 'provenance', 'unites', 'couverture', 'signal', 'decisions'].includes(block.type)) add('command');
    else if (block.type === 'rivers') { add('rivers'); add('pair'); }
    else if (block.type === 'hors_denominateur') add('pair');
    else if (['activity', 'financial_scenario', 'cadran', 'sankey'].includes(block.type)) add(block.type);
  }
  return sections;
}
