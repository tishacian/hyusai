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
  for (const node of page.components) {
    const binding = runtimeDataBinding(node);
    if (!binding || !node.id) continue;
    const bindingKey = binding.source === 'system-binding'
      ? binding.bindingKey ?? ''
      : nodeBindingKey(byId.get(binding.componentId ?? '') ?? ({} as ExperienceNode));
    if (!bindingKey) continue;
    out.push({
      componentId: node.id,
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
