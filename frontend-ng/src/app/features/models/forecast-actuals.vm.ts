/** Measurements of forecasts issued before their target time, separate from backtests. */
export interface ForecastActualMetrics {
  count: number; mae: number | null; rmse: number | null; smape: number | null;
  interval_count: number; nominal_coverage?: number | null; coverage: number | null; mean_interval_width: number | null; anomalies: number;
}
export interface ForecastActualsReport {
  status: 'unconfigured' | 'insufficient' | 'ok' | 'watch' | 'alert' | 'unavailable';
  dataset: {id: string; name: string; slug?: string; version: number; sha256: string; associated_at?: string; follow_latest?: boolean; minimum_version?: number} | null;
  overall: ForecastActualMetrics;
  by_series: Array<ForecastActualMetrics & {series: string}>;
  by_horizon: Array<ForecastActualMetrics & {horizon: number}>;
  anomalies: Array<{series: string; timestamp: string; horizon: number; actual: number; pred: number; lower_bound: number; upper_bound: number; prediction_id: string}>;
  window: {calls: number; retained_points: number; matched: number; excluded_late: number; excluded_future: number; duplicates: number; limit_calls: number; limit_points: number; truncated: boolean};
  policy: {selection: string; timestamp_semantics: string};
  can_configure: boolean;
  reason?: string;
}
export function actualMetric(value: number | null | undefined, locale: string, ratio = false): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat(locale, ratio ? {style: 'percent', maximumFractionDigits: 1} : {maximumFractionDigits: 3}).format(value);
}
export function actualStatus(status: string | undefined): string {
  return 'models.actuals.status.' + (['unconfigured','insufficient','ok','watch','alert','unavailable'].includes(status ?? '') ? status : 'unavailable');
}
export function actualReason(code?: string): string {
  const known = ['unconfigured','dataset_unavailable','dataset_too_large','columns_missing','invalid_value','duplicate_timestamp','series_collision','no_matches','history_conflict','history_unavailable','future_history','forbidden','unsupported','changed'];
  const aliases: Record<string,string> = {not_found:'dataset_unavailable', unavailable:'dataset_unavailable', too_large:'dataset_too_large', columns:'columns_missing', empty:'invalid_value', date:'invalid_value', numeric:'invalid_value', series:'invalid_value', duplicate:'duplicate_timestamp', too_many_series:'dataset_too_large', binding_changed:'changed', changed:'changed'};
  const raw = (code ?? '').replace(/^ML_(?:TS_ACTUALS|FORECAST_ACTUALS)_/, '').toLowerCase();
  const key = aliases[raw] ?? raw;
  return 'models.actuals.reason.' + (known.includes(key) ? key : 'unavailable');
}
