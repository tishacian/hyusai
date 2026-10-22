/** Read-only projections of authorized invocation evidence onto Flow nodes.
 * Never recover outputs from checkpoints, a Skill name or a different Run.
 */
import type { Run, SkillInvocation } from '@app/core/canonical-api.service';
import type { NodeRunSummary } from './flow-node-run.vm';

export interface FlowObservationRun extends Run {
  result_held?: boolean;
  flow_evidence?: { flow_version_id?: string | null; flow_snapshot_sha256?: string | null };
}

export type FlowObservationOutputState = 'available' | 'held' | 'missing' | 'pending' | 'failed';
export interface FlowObservedAttempt {
  id: string;
  nodeId: string;
  passageId: string | null;
  attemptIndex: number | null;
  iteration: number | null;
  skillSlug: string | null;
  status: string;
  startedAt: string | null;
  completedAt: string | null;
  latencyMs: number | null;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  outputState: FlowObservationOutputState;
  invocation: SkillInvocation;
}

export interface FlowNodeObservation {
  nodeId: string;
  status: string;
  attempts: FlowObservedAttempt[];
  preferredAttemptId: string | null;
  /** One invocation's duration, never the sum of overlapping attempts. */
  latencyMs: number | null;
}

export interface FlowObservationIdentity {
  flowSha256?: string | null;
  dirty?: boolean;
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}
function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}
function nonnegative(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}
function integer(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
}
function timestamp(value: unknown): number | null {
  const raw = text(value);
  if (!raw) return null;
  const valueMs = Date.parse(raw);
  return Number.isFinite(valueMs) ? valueMs : null;
}
function hash(value: unknown): string | null {
  return typeof value === 'string' && /^[a-f0-9]{64}$/i.test(value) ? value.toLowerCase() : null;
}

/** Snapshot-evidence hashes use a different algorithm on historical servers.
 * Only canonical flow_sha256 establishes equality with the builder hash.
 */
export function observationFlowMatch(
  run: FlowObservationRun | null,
  current: FlowObservationIdentity,
): 'same' | 'different' | 'unknown' {
  if (!run) return 'unknown';
  if (current.dirty) return 'different';
  const actual = hash(run.flow_sha256), expected = hash(current.flowSha256);
  return actual && expected ? actual === expected ? 'same' : 'different' : 'unknown';
}

export function observationRunVersion(run: FlowObservationRun): string | null {
  return text(run.flow_version_id) ?? text(run.flow_evidence?.flow_version_id);
}

export function observationRunIngress(run: FlowObservationRun): string | null {
  const execution = record(run.input_ref?.['execution']);
  const ingress = record(execution?.['ingress']);
  return text(execution?.['ingress_id']) ?? text(ingress?.['node_id']) ?? text(ingress?.['id']);
}

/** The API lists recent readable Runs. Do not call this list complete history. */
export function recentObservationRuns(runs: Run[], systemId: string): FlowObservationRun[] {
  const unique = new Map<string, FlowObservationRun>();
  for (const run of runs) {
    if (run?.system_id === systemId && text(run.id) && !unique.has(run.id)) unique.set(run.id, run);
  }
  return [...unique.values()].sort((a, b) => {
    const left = timestamp(a.started_at) ?? timestamp(a.completed_at) ?? -Infinity;
    const right = timestamp(b.started_at) ?? timestamp(b.completed_at) ?? -Infinity;
    return right - left || a.id.localeCompare(b.id);
  }).slice(0, 100);
}

export function defaultObservationRun(runs: FlowObservationRun[], flowSha256?: string | null): string | null {
  const completed = runs.filter(run => run.status === 'completed');
  const business = completed.filter(run => !['node_preview', 'builder_preview', 'golden_preview'].includes(run.execution_surface ?? ''));
  const pool = business.length ? business : completed.length ? completed : runs;
  const expected = hash(flowSha256);
  return (expected ? pool.find(run => hash(run.flow_sha256) === expected) : null)?.id ?? pool[0]?.id ?? null;
}

/** Defend against older/malformed held projections without retaining payloads
 * in an output viewer or pinned window. Raw decision traces can contain output.
 */
export function protectObservationRun(run: FlowObservationRun): FlowObservationRun {
  if (!run.result_held) return run;
  return {
    ...run, input_ref: {}, output_ref: {}, checkpoints: [], hitl: undefined, debug: undefined,
    skill_invocations: (run.skill_invocations ?? []).map(invocation => {
      const trace = invocation.trace ?? {};
      const safeTrace = Object.fromEntries(['node_id', 'passage_id', 'membrane_attempt_index', 'membrane_attempt_kind', 'iteration']
        .filter(key => Object.hasOwn(trace, key)).map(key => [key, trace[key]]));
      return { ...invocation, input_ref: {}, output_ref: {}, trace: safeTrace, metrics: {} };
    }),
  };
}

function latestAttempt(attempts: FlowObservedAttempt[]): FlowObservedAttempt | null {
  if (attempts.length === 1) return attempts[0];
  // Unknown timestamps or a tied instant cannot establish which retry/passage
  // is last. Keep all attempts and ask for a deliberate choice instead.
  const dated = attempts.map(attempt => ({ attempt, time: timestamp(attempt.startedAt) }));
  if (dated.some(item => item.time === null)) return null;
  const maximum = Math.max(...dated.map(item => item.time!));
  const latest = dated.filter(item => item.time === maximum);
  return latest.length === 1 ? latest[0].attempt : null;
}

export function observeFlowNodes(rawRun: FlowObservationRun | null): Record<string, FlowNodeObservation> {
  if (!rawRun) return {};
  const run = protectObservationRun(rawRun);
  const nodes: Record<string, FlowNodeObservation> = Object.create(null);
  const seen = new Set<string>();
  for (const invocation of run.skill_invocations ?? []) {
    const id = text(invocation.id), trace = record(invocation.trace), nodeId = text(trace?.['node_id']);
    if (!id || !nodeId || seen.has(id)) continue;
    seen.add(id);
    const status = text(invocation.status) ?? 'unknown';
    const pending = status === 'running' || status === 'pending';
    const failed = status === 'failed' || status === 'cancelled';
    const output = !run.result_held && !pending ? record(invocation.output_ref) : null;
    const attempt: FlowObservedAttempt = {
      id, nodeId, passageId: text(trace?.['passage_id']),
      attemptIndex: integer(trace?.['membrane_attempt_index']), iteration: integer(trace?.['iteration']),
      skillSlug: text(invocation.skill_slug), status,
      startedAt: text(invocation.started_at), completedAt: text(invocation.completed_at) ?? text(invocation.ended_at),
      latencyMs: nonnegative(invocation.latency_ms),
      input: run.result_held ? null : record(invocation.input_ref), output,
      outputState: run.result_held ? 'held' : pending ? 'pending' : failed ? 'failed' : output !== null ? 'available' : 'missing',
      invocation,
    };
    nodes[nodeId] ??= { nodeId, status: 'unknown', attempts: [], preferredAttemptId: null, latencyMs: null };
    nodes[nodeId].attempts.push(attempt);
  }
  for (const node of Object.values(nodes)) {
    node.attempts.sort((a, b) => (timestamp(a.startedAt) ?? Infinity) - (timestamp(b.startedAt) ?? Infinity) || a.id.localeCompare(b.id));
    const latest = latestAttempt(node.attempts);
    node.preferredAttemptId = latest?.id ?? null;
    node.status = run.hitl?.node_id === node.nodeId && run.status === 'hitl_pending'
      ? 'hitl_pending' : run.debug?.node_id === node.nodeId && run.status === 'debug_pending'
        ? 'debug_pending' : latest?.status ?? 'unknown';
    node.latencyMs = node.attempts.length === 1 ? latest?.latencyMs ?? null : null;
  }
  return nodes;
}

export function observationNodeSummaries(nodes: Record<string, FlowNodeObservation>): Record<string, NodeRunSummary> {
  return Object.fromEntries(Object.values(nodes).map(node => [node.nodeId, {
    nodeId: node.nodeId, status: node.status,
    ...(node.latencyMs !== null ? { latencyMs: node.latencyMs } : {}),
  }]));
}

/** A completed, readable invocation, not any historical success of the Skill. */
export function hasObservedNodeResult(run: FlowObservationRun, nodeId: string): boolean {
  return !run.result_held && (observeFlowNodes(run)[nodeId]?.attempts ?? []).some(attempt => attempt.outputState === 'available');
}
