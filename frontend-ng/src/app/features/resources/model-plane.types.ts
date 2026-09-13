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
  configured?: boolean;
  runtime_available?: boolean;
  endpoint?: string | null;
  deployment?: string | null;
  api_version?: string | null;
}

export interface ProvidersResponse {
  providers?: ModelProvider[];
  can_configure?: boolean;
}

/**
 * Readiness of the workspace's *active* provider/model selection, as answered
 * by `GET /api/v1/models/readiness`. One selection, one verdict — the endpoint
 * deliberately does not enumerate the catalog, so a surface that only needs to
 * say "your model is ready / needs setup / is down" pays for nothing more.
 */
export type ModelReadinessStatus = 'ready' | 'needs_setup' | 'unavailable';

/**
 * Why the selection is in that state. `ready` is the only non-failure member;
 * the rest mirror `app/services/model_plane/errors.py` and are shared with the
 * nested chat-stream error below, which is the same classification observed
 * mid-turn rather than at rest.
 */
export type ModelReadinessReason =
  | 'ready'
  | 'provider_not_configured'
  | 'provider_unreachable'
  | 'credentials_invalid'
  | 'model_missing'
  | 'rate_limited'
  | 'timeout'
  | 'generation_failed';

export interface ModelReadiness {
  provider: string;
  model: string;
  source: string;
  status: ModelReadinessStatus;
  reason: ModelReadinessReason;
  /** Provider-neutral copy, safe to render verbatim. */
  message: string;
  retryable: boolean;
  provider_status?: ProviderStatus;
}

export interface ModelSetupResponse {
  readiness: ModelReadiness;
  routing: RoutingResponse;
  provider: {
    key: string;
    api_key_set: boolean;
  };
}

/** The failure classifications a chat stream can report (never `ready`). */
export type ChatStreamErrorCode = Exclude<ModelReadinessReason, 'ready'>;

/**
 * The nested `error` object on a `chunk_type: "error"` SSE chunk. The chunk
 * keeps its legacy top-level `code`/`content`/`recoverable` fields for older
 * clients; this object is the structured half the UI renders from.
 */
export interface ChatStreamError {
  code: ChatStreamErrorCode;
  message: string;
  retryable: boolean;
  /** True when the fix is configuration, not waiting — drives the CTA. */
  needsSetup: boolean;
}

const CHAT_STREAM_ERROR_CODES: ReadonlySet<string> = new Set<ChatStreamErrorCode>([
  'provider_unreachable',
  'credentials_invalid',
  'model_missing',
  'rate_limited',
  'timeout',
  'generation_failed',
]);

/**
 * Codes an operator fixes in provider settings rather than by retrying. The
 * readiness endpoint says this with `status: 'needs_setup'`; a stream chunk
 * carries no status, so the code alone has to answer it.
 */
const SETUP_ERROR_CODES: ReadonlySet<string> = new Set<ChatStreamErrorCode>([
  'credentials_invalid',
  'model_missing',
]);

export function isChatStreamErrorCode(value: unknown): value is ChatStreamErrorCode {
  return typeof value === 'string' && CHAT_STREAM_ERROR_CODES.has(value);
}

/**
 * Dictionary key for a failure reason.
 *
 * Unknown, absent and `ready` reasons all collapse to the neutral line, which
 * is what keeps an unrecognised backend string from reaching the screen: the
 * UI can only ever render copy it shipped.
 */
export function failureCopyKey(reason: ModelReadinessReason | null | undefined): string {
  if (!reason || reason === 'ready') return 'chat.failure.generic';
  return `chat.failure.${reason}`;
}

export function readinessNeedsSetup(readiness: ModelReadiness | null): boolean {
  return readiness?.status === 'needs_setup';
}

/**
 * Read the structured failure out of an SSE error chunk.
 *
 * Returns `null` for anything that is not a recognised provider failure, so the
 * caller falls back to neutral copy. Nothing is lifted from the raw exception
 * path: `message` is taken only from the backend's classified, provider-neutral
 * string, never from `content`, a URL, or `String(error)`.
 */
export function parseChatStreamError(chunk: unknown): ChatStreamError | null {
  if (!chunk || typeof chunk !== 'object') return null;
  const nested = (chunk as Record<string, unknown>)['error'];
  if (!nested || typeof nested !== 'object') return null;
  const record = nested as Record<string, unknown>;
  const code = record['code'];
  if (!isChatStreamErrorCode(code)) return null;
  const message = typeof record['message'] === 'string' ? record['message'].trim() : '';
  return {
    code,
    message,
    retryable: record['retryable'] === true,
    needsSetup: SETUP_ERROR_CODES.has(code),
  };
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
  source?: 'workspace' | 'global' | string | null;
  model_usage?: Array<{ system_id: string; system_name: string; node_id: string; provider: string; model: string; source: string }>;
  systems?: Array<{
    id?: string;
    name?: string;
    default_model?: string | null;
  }>;
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
  can_configure?: boolean;
  runtime_providers?: string[];
}

export type DistributionWindow = '7d' | '30d';

export interface DistributionBucket {
  key?: string;
  provider?: string;
  model?: string;
  /** Backend uses ``invocations``; tolerate legacy ``count``. */
  count?: number;
  invocations?: number;
  cost?: number | null;
  currency?: string | null;
  latency_ms?: number | null;
  avg_latency_ms?: number | null;
  share?: number;
  cost_source?: string | null;
  cost_state?: string | null;
  run_ids?: string[];
  invocation_ids?: string[];
  evidence?: Array<{ run_id: string; invocation_id: string }>;
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
