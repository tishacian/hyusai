export const SOURCE_OLD_AFTER_DAYS = 90;
export interface ContextDates {
  updated_at?: string | null;
  data_refs?: ReadonlyArray<string>;
  source_dates?: ReadonlyArray<{ ref: string; updated_at: string | null }>;
}

/** Version numbers count edits; only recorded timestamps establish age. */
export function contextFreshness(context: ContextDates, now = Date.now()): 'old' | 'recent' | 'unknown' {
  const sources = context.source_dates ?? [];
  const missing = (context.data_refs ?? []).filter(ref => !sources.some(source => source.ref === ref));
  const dates = [context.updated_at, ...sources.map(source => source.updated_at), ...missing.map(() => null)];
  const timestamps = dates.map(date => date ? Date.parse(date) : NaN);
  if (timestamps.some(at => Number.isFinite(at) && now - at > SOURCE_OLD_AFTER_DAYS * 86_400_000)) return 'old';
  if (timestamps.some(at => !Number.isFinite(at) || at > now)) return 'unknown';
  return 'recent';
}
