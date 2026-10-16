export type ActivityScope = 'workspace' | 'system' | 'platform';
export interface ActivityFeatures { enabled: boolean; execution_view_enabled?: boolean; activity_series_enabled?: boolean; scopes: ActivityScope[]; kinds: string[]; statuses: string[]; }
export interface ActivityLink { rel: string; href: string; }
export interface ActivityMeasurements {
  duration_ms: number | null;
  provider_cost_usd: number | null;
  cost_known: boolean;
  cost_basis?: 'infrastructure_allocation' | 'provider_tariff' | 'provider_measured' | 'catalogue_calculated' | 'unknown' | null;
  cost_amount?: number | null; currency?: string | null; infrastructure_cost_usd?: number | null;
  cpu_seconds?: number | null;
  allocated_core_hours?: number | null;
  core_hours?: number | null;
  reserved_core_hours?: number | null;
  cpu_cores?: number | null;
  memory_mb?: number | null;
  resource_basis?: string;
  peak_memory_bytes?: number | null;
  spill_bytes?: number | null;
  input_rows?: number | null;
  output_rows?: number | null;
}
export interface Activity {
  id: string; kind: string; native_id: string; workspace_id: string;
  system_id: string | null; run_id: string | null; parent_activity_id: string | null;
  status: string; native_status: string; version: number;
  created_at: string; started_at: string | null; finished_at: string | null; updated_at: string;
  progress: number | Record<string, unknown> | null;
  measurements: ActivityMeasurements;
  links: ActivityLink[]; capabilities: { cancel: boolean };
  coverage?: Record<string, string | boolean | null>;
}
export interface ActivityEvent {
  id: string; cursor: string; sequence: number; activity_id: string;
  version: number; kind: string; status: string; occurred_at: string;
}
export interface ActivityCommand {
  id: string; activity_id: string; action: string; status: string;
  created_at: string; error_code: string | null;
}
export interface ActivityDetail extends Activity {
  attempts: Activity[]; evidence: ActivityLink[]; events: ActivityEvent[];
  attempts_has_more?: boolean;
  related_activities?: Activity[];
  related_has_more?: boolean;
  commands?: ActivityCommand[];
}
export interface ActivityPage {
  items: Activity[]; total: number; has_more: boolean; offset: number; limit: number;
  aggregates: { total: number; by_status: Record<string, number>; by_kind: Record<string, number> };
  snapshot_cursor: string;
}
export interface ActivityEventPage { items: ActivityEvent[]; next_cursor: string; has_more: boolean; }
export interface ActivityFilters { system_id?: string; kind?: string; status?: string; since?: string; until?: string; run_id?: string; limit?: number; offset?: number; }
export interface PlatformOverview {
  generated_at: string;
  resources?: { active: number; reserved_cpu: number; reserved_memory_mb: number; unreconciled: number;
    limits: { slots: number; cpu: number; memory_mb: number } };
  aggregates: ActivityPage['aggregates'];
  workspaces: { workspace_id: string; aggregates: ActivityPage['aggregates'] }[];
}

/** Native evidence remains inside this application; never render a provider URL as trusted navigation. */
export function activityLink(link: ActivityLink): string | null {
  if (!link.href.startsWith('/') || link.href.startsWith('//') || /[\\\u0000-\u0020]/.test(link.href)) return null;
  try {
    const url = new URL(link.href, 'https://agentium.invalid');
    return url.origin === 'https://agentium.invalid' ? url.pathname + url.search + url.hash : null;
  } catch { return null; }
}

export function activityQuery(filters: ActivityFilters): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  }
  return params.toString();
}

export function mergeActivityEvents(current: ActivityEvent[], incoming: ActivityEvent[], capacity = 200): ActivityEvent[] {
  const unique = new Map(current.map(event => [event.id, event]));
  for (const event of incoming) unique.set(event.id, event);
  return [...unique.values()].sort((a, b) => a.sequence - b.sequence).slice(-capacity);
}

export function commandIsPending(command: ActivityCommand): boolean {
  return ['requested', 'accepted', 'queued', 'running', 'dispatch_pending'].includes(command.status);
}
