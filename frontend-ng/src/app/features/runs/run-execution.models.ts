import type { ActivityLink, ActivityMeasurements } from '../observability/activities/activity.models';
export interface ExecutionGraphNode { id: string; kind: string; label: string; }
export interface ExecutionGraphEdge { id: string; source: string; target: string; kind: string; label: string | null; }
export interface ExecutionNode { node_id: string; status: string; waiting_reason: string | null; counts: Record<string, number>; passages_total: number; coverage: string; }
export interface ExecutionPhase { id: string; phase: string; started_at: string | null; finished_at: string | null; coverage: string; }
export interface ExecutionItem {
  intervals?: ExecutionPhase[]; passage_intervals?: ExecutionPhase[];
  id: string; passage_id: string | null; node_id: string | null; source: string; native_id: string; activity_id: string | null;
  runtime?: string | null; placement?: string | null;
  status: string; native_status: string; relation: string | null; attempt_index: number | null; iteration: number | null; branch: string | null;
  started_at: string | null; finished_at: string | null; duration_ms: number | null;
  measurements: Omit<ActivityMeasurements, 'cost_basis'> & { cost_amount?: number | null; currency?: string | null; infrastructure_cost_usd?: number | null; cost_basis?: string | null; placement?: string | null; engine?: string | null }; resource_coverage?: string; coverage: string; links: ActivityLink[]; waiting_reason: string | null;
}
export interface RunExecutionView {
  schema_version: number;
  run: { id: string; status: string; native_status: string; system_id: string | null; started_at: string | null; finished_at: string | null; flow_version_id: string | null; flow_sha256: string | null; trigger: string | null };
  graph: { available: boolean; nodes: ExecutionGraphNode[]; edges: ExecutionGraphEdge[] };
  nodes: ExecutionNode[]; items: ExecutionItem[]; total: number; limit: number; offset: number; has_more: boolean;
  snapshot_cursor: string; read_version: string;
  coverage: { correlation: string; graph: string; timeline: string }; capabilities: { read_only: true; live?: boolean };
}
/** Static layout only. A cycle is rendered, never interpreted as an execution order. */
export function executionGraphLayout(nodes: ExecutionGraphNode[], edges: ExecutionGraphEdge[]): Array<ExecutionGraphNode & { position: { x: number; y: number } }> {
  const known = new Set(nodes.map(node => node.id));
  const ranks = new Map<string, number>(); const remaining = new Set(known);
  for (let round = 0; round < nodes.length && remaining.size; round++) {
    let advanced = false;
    for (const node of nodes) {
      if (!remaining.has(node.id)) continue;
      const parents = edges.filter(edge => edge.target === node.id && known.has(edge.source) && edge.source !== node.id).map(edge => edge.source);
      if (parents.every(parent => ranks.has(parent))) { ranks.set(node.id, parents.length ? Math.max(...parents.map(parent => ranks.get(parent)!)) + 1 : 0); remaining.delete(node.id); advanced = true; }
    }
    if (!advanced) break;
  }
  let cycleRank = Math.max(-1, ...ranks.values()) + 1;
  for (const id of remaining) ranks.set(id, cycleRank++);
  const slots = new Map<number, number>();
  return nodes.map(node => { const rank = ranks.get(node.id) || 0; const slot = slots.get(rank) || 0; slots.set(rank, slot + 1); return { ...node, position: { x: 30 + rank * 270, y: 40 + slot * 140 } }; });
}
/** Intervals come exclusively from persisted dates; missing dates are not invented. */
export function executionInterval(item: Pick<ExecutionItem, 'started_at' | 'finished_at'>, from: string | null, until: string | null): { left: number; width: number } | null {
  const start = Date.parse(item.started_at || ''); const end = Date.parse(item.finished_at || '');
  const minimum = Date.parse(from || ''); const maximum = Date.parse(until || '');
  if (![start, end, minimum, maximum].every(Number.isFinite) || end < start || maximum <= minimum) return null;
  return { left: Math.max(0, (start - minimum) / (maximum - minimum) * 100), width: Math.max(.5, (end - start) / (maximum - minimum) * 100) };
}

/** Shared passage wait/review intervals appear once; every attempt retains its own execution interval. */
export function executionTimeline(items: ExecutionItem[]): Array<{ id: string; item: ExecutionItem; phase: ExecutionPhase }> {
  const seen = new Set<string>(); const result: Array<{ id: string; item: ExecutionItem; phase: ExecutionPhase }> = [];
  for (const item of items) {
    const own = item.intervals?.length ? item.intervals : [{ id: item.id, phase: 'execution', started_at: item.started_at, finished_at: item.finished_at, coverage: item.coverage }];
    const waits = (item.passage_intervals || []).filter(phase => phase.phase !== 'execution');
    for (const phase of [...own, ...waits]) if (!seen.has(phase.id)) { seen.add(phase.id); result.push({ id: phase.id, item, phase }); }
  }
  return result;
}
