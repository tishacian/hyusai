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
  api_key_set?: boolean;
  credential_source?: 'workspace' | 'env' | string | null;
}

export interface ProvidersResponse {
  providers?: ModelProvider[];
}

export interface RoutingPrimary {
  provider?: string | null;
  model?: string | null;
}

export const MODEL_TIERS = ['fast', 'balanced', 'strong'] as const;
export type ModelTier = (typeof MODEL_TIERS)[number];

export interface RoutingSystem {
  id?: string;
  name?: string;
  default_model?: string | null;
  status?: string;
}

export type EffectiveSystemTier = ModelTier | 'pinned' | 'default';

export interface RoutingResponse {
  /** New contract: `{ provider, model }`. Legacy: plain string. */
  primary?: RoutingPrimary | string | null;
  /** Legacy single fallback string. */
  fallback?: string | null;
  fallback_chain?: string[];
  default_provider?: string | null;
  default_model?: string | null;
  ollama_default_model?: string | null;
  source?: 'workspace' | 'global' | string | null;
  /** `{fast,balanced,strong}` → `provider:model`. Empty = fall through. */
  tiers?: Partial<Record<ModelTier, string>> | Record<string, string>;
  tier_names?: string[];
  registered_clients?: string[];
  local_serving?: string[];
  systems?: RoutingSystem[];
}

export interface CredentialStatus {
  key: string;
  api_key_set?: boolean;
  endpoint?: string;
  api_version?: string;
  deployment?: string;
}

export interface AttachedServingNode {
  name: string;
  base_url: string;
  token_set?: boolean;
}

export interface PortalConfigResponse {
  routing?: RoutingResponse;
  cloud_credentials?: CredentialStatus[];
  serving_nodes?: AttachedServingNode[];
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

export function isModelTier(value: unknown): value is ModelTier {
  return typeof value === 'string' && (MODEL_TIERS as readonly string[]).includes(value);
}

/** Split `provider:model` / `provider/model`; bare names stay as the model. */
export function parseProviderModelSpec(
  spec: string | null | undefined,
): { provider: string; model: string } | null {
  const raw = (spec || '').trim();
  if (!raw) return null;
  for (const sep of [':', '/'] as const) {
    if (!raw.includes(sep)) continue;
    const head = raw.slice(0, raw.indexOf(sep)).trim();
    const model = raw.slice(raw.indexOf(sep) + 1).trim();
    if (!head || !model) continue;
    if (sep === ':' && head.includes('/')) continue;
    return { provider: head, model };
  }
  return { provider: '', model: raw };
}

export function formatProviderModelSpec(provider: string, model: string): string {
  const p = provider.trim();
  const m = model.trim();
  if (p && m) return `${p}:${m}`;
  return m || p;
}

export function routingTiers(route: RoutingResponse | null | undefined): Record<ModelTier, string> {
  const raw = route?.tiers && typeof route.tiers === 'object' ? route.tiers : {};
  return {
    fast: String(raw['fast'] || '').trim(),
    balanced: String(raw['balanced'] || '').trim(),
    strong: String(raw['strong'] || '').trim(),
  };
}

/**
 * What a System would actually serve: a pin beats every tier; otherwise the
 * workspace default (no per-System tier — the planner picks one per turn).
 */
export function effectiveSystemTier(
  system: RoutingSystem | null | undefined,
  route: RoutingResponse | null | undefined,
): EffectiveSystemTier {
  const pin = String(system?.default_model || '').trim();
  if (pin) {
    const tiers = routingTiers(route);
    const pinNorm = pin.toLowerCase();
    for (const tier of MODEL_TIERS) {
      const spec = tiers[tier];
      if (!spec) continue;
      if (spec.toLowerCase() === pinNorm) return tier;
      const parsed = parseProviderModelSpec(spec);
      if (parsed && parsed.model.toLowerCase() === pinNorm) return tier;
    }
    return 'pinned';
  }
  return 'default';
}

/** Suggestions for the tier editor: registered clients, local serving, live models. */
export function routableModelOptions(
  route: RoutingResponse | null | undefined,
  providers: ModelProvider[] = [],
): string[] {
  const out = new Set<string>();
  for (const key of route?.registered_clients ?? []) {
    if (key) out.add(String(key));
  }
  for (const key of route?.local_serving ?? []) {
    if (key) out.add(String(key));
  }
  for (const p of providers) {
    const provider = (p.key || '').toString();
    if (provider) out.add(provider);
    for (const model of p.models ?? []) {
      if (provider && model) out.add(`${provider}:${model}`);
      else if (model) out.add(String(model));
    }
  }
  const tiers = routingTiers(route);
  for (const spec of Object.values(tiers)) {
    if (spec) out.add(spec);
  }
  return [...out].sort((a, b) => a.localeCompare(b));
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
