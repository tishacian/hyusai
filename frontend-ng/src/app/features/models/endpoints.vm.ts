export type EndpointScope = 'workspace' | 'system' | 'platform';
export interface UsageWindow {
  requests: number; rows: number; errors: number; error_rate: number | null;
  p50_ms: number | null; p95_ms: number | null;
  quantile_method: 'histogram_upper_bound'; latency_observations: number; latency_overflow: number;
  measured_cost_usd: number | null; measured_cost_per_1000_rows_usd: number | null;
  measured_requests: number; unknown_cost_requests: number; tariff_cost_usd: number | null; tariff_cost_per_1000_rows_usd: number | null; tariff_requests: number;
  from: string; until: string; as_of: string | null;
}
export interface Endpoint {
  id: string; name: string; workspace_id: string; system_id: string | null;
  version: number; served_id: string; served_version: number; skill_slug: string | null;
  monitor_badge: 'ok' | 'watch' | 'alert' | null;
  keys: {id: string; name: string; created_at: string; last_used_at: string | null; expires_at: string | null}[];
  metrics: Record<'24h' | '7d', UsageWindow>;
  last_audit: {event: string; at: string} | null;
}
export interface MLAlert {
  id: string; model_id: string; workspace_id: string; event: string; state: string;
  created_at: string; acknowledged_at: string | null;
}
export interface MLChannel {
  id: string; name: string; kind: 'email' | 'webhook'; enabled: boolean;
  destination_email: string | null; webhook_url_ref: string | null; signing_key_ref: string | null;
}
export interface EndpointsFeatures {enabled: boolean; alerts_enabled: boolean; can_manage_channels: boolean; scopes: EndpointScope[]}

export function measuredCost(window: UsageWindow): {value: number | null; partial: boolean} {
  return {value: window.measured_cost_per_1000_rows_usd, partial: window.unknown_cost_requests > 0};
}
export function latencyUpperBound(value: number | null): string {
  return value === null ? '—' : `≤ ${value.toLocaleString()} ms`;
}
