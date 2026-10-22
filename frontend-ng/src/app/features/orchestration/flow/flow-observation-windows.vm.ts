/** In-memory observation cards. These are views of retained evidence, never
 * canonical Flow nodes, cached results across identities or execution steps. */
import type { Run, SkillInvocation } from '@app/core/canonical-api.service';
import { observationRunVersion, type FlowObservedAttempt } from './flow-observation.vm';
import { projectFlowResult, type FlowResultDatasetPreview, type FlowResultPresentation } from './flow-result.vm';

export const MAX_OBSERVATION_PINS = 4;
const MAX_CANVAS_COORDINATE = 100_000;
const PRESENTATIONS: readonly FlowResultPresentation[] = ['auto', 'chart', 'table', 'metric', 'document', 'decisions'];

export interface FlowObservationPin {
  id: string;
  run: Run;
  nodeId: string;
  title: string;
  attempt: FlowObservedAttempt;
  presentation: FlowResultPresentation;
  position: { x: number; y: number };
  mode: 'output' | 'input';
  datasetPreview?: FlowResultDatasetPreview | null;
  selectedSeriesName?: string | null;
}

export type FlowObservationPinInput = Omit<FlowObservationPin, 'id'>;
export interface FlowObservationPinAppend {
  pins: FlowObservationPin[];
  outcome: 'added' | 'duplicate' | 'limit';
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

function identity(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function validPosition(value: FlowObservationPin['position']): boolean {
  return !!value && [value.x, value.y].every(coordinate => typeof coordinate === 'number'
    && Number.isFinite(coordinate) && Math.abs(coordinate) <= MAX_CANVAS_COORDINATE);
}

function belongsToNode(invocation: SkillInvocation, run: Run, nodeId: string): boolean {
  return identity(invocation.id)
    && record(invocation.trace)?.['node_id'] === nodeId
    && (!invocation.run_id || invocation.run_id === run.id)
    && (!invocation.system_id || invocation.system_id === run.system_id);
}

/** Only the metadata needed to explain a policy stop is retained. In
 * particular no checkpoint.state or node_outputs can enter a pinned card. */
function policyStops(run: Run, nodeId: string): Array<Record<string, unknown>> {
  const fields = ['kind', 'node_id', 'passage_id', 'turn', 'skill', 'reason'] as const;
  return (run.checkpoints ?? []).filter(checkpoint => checkpoint['kind'] === 'agent_loop_policy_block'
    && checkpoint['node_id'] === nodeId).map(checkpoint => Object.fromEntries(fields.flatMap(key => {
      const value = checkpoint[key];
      return typeof value === 'string' || typeof value === 'number' ? [[key, value]] : [];
    })));
}

/** A pin needs the current node's authorized invocation evidence and Run
 * provenance. Other nodes, root payloads and checkpoint snapshots are omitted. */
function retainedRun(run: Run, nodeId: string): Run {
  return {
    id: run.id,
    system_id: run.system_id,
    status: run.status,
    started_at: run.started_at,
    completed_at: run.completed_at,
    ended_at: run.ended_at,
    duration_ms: run.duration_ms,
    trigger: run.trigger,
    flow_version_id: observationRunVersion(run),
    flow_sha256: run.flow_sha256,
    source_flow_sha256: run.source_flow_sha256,
    execution_surface: run.execution_surface,
    runtime_mode: run.runtime_mode,
    skill_invocations: (run.skill_invocations ?? []).filter(invocation => belongsToNode(invocation, run, nodeId)),
    checkpoints: policyStops(run, nodeId),
  };
}

function freezeTree<T>(value: T, seen = new WeakSet<object>()): T {
  if (value === null || typeof value !== 'object' || seen.has(value)) return value;
  seen.add(value);
  for (const child of Object.values(value)) freezeTree(child, seen);
  return Object.freeze(value);
}

/** The server-authorized attempt remains the sole source of input/output.
 * Missing evidence, a held result or a mismatched identity cannot be pinned. */
export function snapshotObservationPin(input: FlowObservationPinInput): FlowObservationPin | null {
  const { run, attempt, nodeId, mode, presentation } = input;
  const held = (run as Run & { result_held?: unknown }).result_held;
  if (!identity(run.id) || !identity(run.system_id) || !identity(nodeId) || !identity(attempt.id)
    || attempt.nodeId !== nodeId || (held !== undefined && held !== false)
    || attempt.outputState === 'held' || !validPosition(input.position)
    || !PRESENTATIONS.includes(presentation) || !['input', 'output'].includes(mode)) return null;
  if (!(run.skill_invocations ?? []).some(invocation => invocation.id === attempt.id
    && belongsToNode(invocation, run, nodeId))) return null;
  if (!belongsToNode(attempt.invocation, run, nodeId) || attempt.invocation.id !== attempt.id) return null;
  const value = mode === 'input' ? attempt.input : attempt.output;
  if (!record(value) || (mode === 'output' && !['available', 'failed'].includes(attempt.outputState))) return null;
  const chart = ['auto', 'chart'].includes(presentation)
    ? projectFlowResult(value, mode === 'output' ? input.datasetPreview : null).chart : null;
  const selectedSeriesName = chart?.groups.find(group => group.name === input.selectedSeriesName)?.name
    ?? chart?.groups[0]?.name ?? null;
  try {
    const id = `observation:${[run.id, nodeId, attempt.id, mode, presentation, selectedSeriesName ?? ''].map(encodeURIComponent).join(':')}`;
    return freezeTree(structuredClone({
      ...input,
      id,
      title: input.title.trim() || nodeId,
      run: retainedRun(run, nodeId),
      datasetPreview: mode === 'output' ? input.datasetPreview ?? null : null,
      selectedSeriesName,
    }));
  } catch {
    // Browser/API payloads are JSON. An uncloneable value is not evidence that
    // can be retained faithfully, so do not manufacture a partial snapshot.
    return null;
  }
}

export function appendObservationPin(pins: readonly FlowObservationPin[], pin: FlowObservationPin): FlowObservationPinAppend {
  if (pins.some(existing => existing.id === pin.id)) return { pins: [...pins], outcome: 'duplicate' };
  if (pins.length >= MAX_OBSERVATION_PINS) return { pins: [...pins], outcome: 'limit' };
  return { pins: [...pins, pin], outcome: 'added' };
}

export function moveObservationPin(
  pins: readonly FlowObservationPin[], id: string, position: FlowObservationPin['position'],
): FlowObservationPin[] {
  if (!validPosition(position)) return [...pins];
  return pins.map(pin => pin.id === id ? Object.freeze({ ...pin, position: Object.freeze({ ...position }) }) : pin);
}

export function removeObservationPin(pins: readonly FlowObservationPin[], id: string): FlowObservationPin[] {
  return pins.filter(pin => pin.id !== id);
}

/** A series switch changes presentation only; it cannot replace retained data. */
export function selectObservationPinSeries(pin: FlowObservationPin, name: string | null): FlowObservationPin {
  if (name === null || !['auto', 'chart'].includes(pin.presentation)) return pin;
  const chart = projectFlowResult(observationPinValue(pin), pin.mode === 'output' ? pin.datasetPreview : null).chart;
  if (!chart?.groups.some(group => group.name === name) || pin.selectedSeriesName === name) return pin;
  return Object.freeze({ ...pin, selectedSeriesName: name });
}

export function observationPinValue(pin: FlowObservationPin): Record<string, unknown> | null {
  return pin.mode === 'input' ? pin.attempt.input : pin.attempt.output;
}
