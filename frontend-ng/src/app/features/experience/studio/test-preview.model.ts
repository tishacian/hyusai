/**
 * "Preview on a test" (plan lot 4, US34): check what a page would show
 * against one identified Run of the bound System, instead of a document with
 * no data. Pure, so the rules are unit-tested.
 */
import type { Run } from '@app/core/canonical-api.service';
import {
  runtimeDataBinding,
  selectRuntimeRunData,
  type ExperienceNode,
  type ExperiencePage,
} from '../runtime/model';

export interface BoundOutput {
  componentId: string;
  label: string;
  type: string;
  bindingKey: string;
  selector: string;
  nodeId?: string;
}

function nodeBindingKey(node: ExperienceNode): string {
  const direct = node.props?.['bindingKey'];
  if (typeof direct === 'string' && direct) return direct;
  const query = node.props?.['queryBinding'];
  if (query && typeof query === 'object' && typeof (query as Record<string, unknown>)['bindingKey'] === 'string') {
    return (query as Record<string, string>)['bindingKey'];
  }
  return '';
}

/** Every component of the page that shows a System output, and from which binding. */
export function boundOutputs(page: ExperiencePage | null | undefined): BoundOutput[] {
  if (!page) return [];
  const byId = new Map(page.components.filter((node) => node.id).map((node) => [node.id!, node]));
  const out: BoundOutput[] = [];
  const actions = page.components.filter(node => node.type === 'form' || node.type === 'action_button');
  const implicitTypes = new Set(['result', 'runtime_status', 'evidence', 'history']);
  for (const node of page.components) {
    let binding = runtimeDataBinding(node);
    if (!binding && implicitTypes.has(node.type)) {
      // Older wizard documents use the runtime's sourceComponentId or preceding
      // form convention. Read it without rewriting the user's draft. Multiple
      // actions need an explicit source; a preview must not guess between them.
      const explicit = typeof node.props?.['sourceComponentId'] === 'string' ? node.props['sourceComponentId'] : null;
      const solePrevious = actions.length === 1 && page.components.indexOf(actions[0]) < page.components.indexOf(node)
        ? actions[0].id : undefined;
      const componentId = explicit || solePrevious;
      if (componentId) binding = { source: 'run-output', componentId, selector: '', input: {} };
    }
    if (!binding || !node.id) continue;
    const bindingKey = binding.source === 'system-binding'
      ? binding.bindingKey ?? ''
      : nodeBindingKey(byId.get(binding.componentId ?? '') ?? ({} as ExperienceNode));
    if (!bindingKey) continue;
    out.push({
      componentId: node.id,
      label: outputLabel(node),
      type: node.type,
      bindingKey,
      selector: binding.selector,
      ...(binding.nodeId ? { nodeId: binding.nodeId } : {}),
    });
  }
  return out;
}

export type OutputCheck = 'present' | 'missing';

/** A selector the Run does not carry is an incompatibility, never an example value. */
export function checkOutput(output: BoundOutput, run: Run): { state: OutputCheck; value: unknown } {
  const value = selectRuntimeRunData(run, { selector: output.selector, nodeId: output.nodeId });
  return { state: value === undefined || value === null ? 'missing' : 'present', value };
}

/**
 * What the Run is worth as a preview source:
 * - `review`: it waits for a human decision, so its result is not accepted;
 * - `failed` / `running`: no usable result;
 * - `completed`: a finished result.
 */
export type RunStanding = 'completed' | 'review' | 'running' | 'failed';

export function runStanding(run: Pick<Run, 'status'>): RunStanding {
  if (run.status === 'completed') return 'completed';
  if (run.status === 'hitl_pending' || run.status === 'debug_pending') return 'review';
  if (run.status === 'pending' || run.status === 'running') return 'running';
  return 'failed';
}

/** A test of a draft or of another version does not prove the bound version. */
export function runVersionMatches(run: Pick<Run, 'flow_version_id'>, publishedVersionId: string): boolean | null {
  if (!run.flow_version_id) return null;
  return run.flow_version_id === publishedVersionId;
}

export function previewValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  return text.length > 120 ? `${text.slice(0, 117)}…` : text;
}

/** A component’s business heading takes precedence over its implementation id. */
export function outputLabel(node: ExperienceNode): string {
  for (const key of ['title', 'label', 'caption']) {
    const value = node.props?.[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (value && typeof value === 'object' && typeof (value as Record<string, unknown>)['fallback'] === 'string') {
      const fallback = String((value as Record<string, unknown>)['fallback']).trim();
      if (fallback) return fallback;
    }
  }
  return '';
}

/** Never flatten structured evidence into a truncated JSON sentence. */
export function previewShape(value: unknown): 'scalar' | 'list' | 'record' {
  if (Array.isArray(value)) return 'list';
  return value !== null && typeof value === 'object' ? 'record' : 'scalar';
}
