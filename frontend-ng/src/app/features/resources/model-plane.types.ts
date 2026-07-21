/** Contracts for `/api/v1/models/*` (model plane). Tolerate partial/legacy shapes. */

export type ProviderStatus = 'active' | 'configured' | 'unreachable' | 'available' | string;

export interface ModelProvider {
  key: string;
  label?: string;
  kind?: 'local' | 'cloud' | string;
  status: ProviderStatus;
  models: string[];
  latency_ms?: number | null;
  notes?: string | null;
  error?: string | null;
}

export interface ProvidersResponse {
  providers?: ModelProvider[];
}

export interface RoutingPrimary {
  provider?: string | null;
  model?: string | null;
}

export interface RoutingResponse {
  /** New contract: `{ provider, model }`. Legacy: plain string. */
  primary?: RoutingPrimary | string | null;
  /** Legacy single fallback string. */
  fallback?: string | null;
  fallback_chain?: string[];
  default_provider?: string | null;
  default_model?: string | null;
  systems?: Array<{
    id?: string;
    name?: string;
    default_model?: string | null;
  }>;
}

export type DistributionWindow = '7d' | '30d';

export interface DistributionBucket {
  key?: string;
  provider?: string;
  model?: string;
  /** Backend uses ``invocations``; tolerate legacy ``count``. */
  count?: number;
  invocations?: number;
  cost?: number;
  latency_ms?: number | null;
  avg_latency_ms?: number | null;
  share?: number;
}

export interface DistributionResponse {
  window?: string;
  by_provider?: DistributionBucket[];
  by_model?: DistributionBucket[];
  /** Alternate keys some backends may use. */
  providers?: DistributionBucket[];
  models?: DistributionBucket[];
  totals?: {
    invocations?: number;
    cost?: number;
    avg_latency_ms?: number | null;
  };
}

export interface GpuDevice {
  index?: number;
  name?: string;
  memory_total_mb?: number;
  memory_used_mb?: number;
  utilization?: number;
}

export interface GpuInfo {
  available?: boolean;
  count?: number;
  memory_total_mb?: number | null;
  memory_used_mb?: number | null;
  utilization?: number | null;
  devices?: GpuDevice[];
  notes?: string | null;
  /** Raw portal keys (pre-normalize). */
  total_count?: number;
  gpus?: unknown[];
}

export interface ServingInstance {
  id: string;
  name?: string;
  /** Portal / API field. */
  provider?: string;
  /** UI alias (normalized by backend or set by FE). */
  engine?: string;
  model?: string;
  status?: string;
  port?: number | null;
}

export interface ServingNode {
  key?: string;
  name?: string;
  base_url?: string;
  status?: string;
  gpu?: GpuInfo | null;
  instances?: ServingInstance[];
  notes?: string | null;
  error?: string | null;
  empty?: boolean;
}

export interface NodesResponse {
  nodes?: ServingNode[];
  empty?: boolean;
  message?: string | null;
}

export function nodeKey(node: ServingNode): string {
  return (node.key || node.name || '').toString();
}

export function providerLabel(p: ModelProvider): string {
  return (p.label || p.key || 'provider').toString();
}

export function routingPrimaryLabel(route: RoutingResponse | null | undefined): string {
  if (!route) return '—';
  const primary = route.primary;
  if (typeof primary === 'string' && primary.trim()) return primary;
  if (primary && typeof primary === 'object') {
    const provider = primary.provider || route.default_provider;
    const model = primary.model || route.default_model;
    if (provider && model) return `${provider}:${model}`;
    return (provider || model || '—').toString();
  }
  if (route.default_provider && route.default_model) {
    return `${route.default_provider}:${route.default_model}`;
  }
  return (route.default_provider || route.default_model || '—').toString();
}

export function routingFallbackLabel(route: RoutingResponse | null | undefined): string {
  if (!route) return '—';
  if (typeof route.fallback === 'string' && route.fallback.trim()) return route.fallback;
  const chain = route.fallback_chain;
  if (Array.isArray(chain) && chain.length) return chain.join(' → ');
  return '—';
}

export function distCount(b: DistributionBucket): number {
  return b.count ?? b.invocations ?? 0;
}

export function distLatency(b: DistributionBucket): number | null | undefined {
  return b.latency_ms ?? b.avg_latency_ms;
}

export function instanceEngine(inst: ServingInstance): string {
  return (inst.engine || inst.provider || '').toString();
}
