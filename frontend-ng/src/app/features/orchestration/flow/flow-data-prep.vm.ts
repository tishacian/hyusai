import type { CanonicalFlow, CanonicalFlowNode } from '@app/core/flow-serializer.service';
import { canonicalPrepParams, prepDraftFromNode, prepDraftPorts, type DatasetRef, type PrepAction, type PrepDraft, type PrepStep, type PrepPreview } from '@app/features/data/dataops.models';
import { prepStepDefaults } from '@app/features/data/prep-fields';
import type { NodeRunSummary } from './flow-node-run.vm';

export const PREP_HISTORY_LIMIT = 50;
export const PREP_WRITE_DEBOUNCE = 400;
export const PREP_STEP_GROUPS: Record<string, PrepAction[]> = {
  columns: ['select_columns','drop_columns','rename_columns','move_columns','copy_column','concat_columns','normalize_column_names','add_column'],
  types: ['cast','parse_date','format_date','from_epoch','parse_number','to_boolean'],
  missing: ['drop_nulls','fill_nulls'], rows: ['filter_rows','filter_range','filter_expression','flag_rows','sort','deduplicate'],
  text: ['text_transform','replace_values','split_column','extract_regex','count_occurrences','substring','pad','length'],
  numeric: ['round','math','bin','scale','negate_boolean'],
  dates: ['extract_date_parts','date_diff','date_add','truncate_date','convert_timezone'],
  compute: ['formula','conditional_column','map_values','window'], privacy: ['hash','mask'],
};
export function isPrepNode(node: CanonicalFlowNode | null | undefined): boolean { return (node?.config as Record<string,unknown> | undefined)?.['skill_slug'] === 'data_prep_v1'; }
export function newPrepStep(action: PrepAction, column?: string): PrepStep {
  const params = prepStepDefaults(action);
  if(column){
    if(action==='rename_columns')params['mapping']={[column]:column};
    else if(action==='filter_rows')params['conditions']=[{column,op:'eq',value:''}];
    else if(['select_columns','drop_columns','text_transform','cast','hash','sort','deduplicate','drop_nulls','fill_nulls','scale','math','round','mask'].includes(action))params['columns']=[column];
    else params['column']=column;
  }
  return {id: crypto.randomUUID(), action, enabled: true, comment: '', params};
}
export function editablePrepDraft(draft: PrepDraft): PrepDraft {
  const result = structuredClone(draft);
  result.spec.steps = result.spec.steps.map(step => ({...step, id: step.id ?? crypto.randomUUID(), enabled: step.enabled !== false, comment: step.comment ?? ''}));
  result.spec.params = prepOperationParams(result);
  return result;
}
export function prepOperationParams(draft: PrepDraft): Record<string, unknown> {
  const p = structuredClone(draft.spec.params), op = draft.spec.operation;
  if (op === 'join') { if (!p['on']) p['on'] = ((p['keys'] ?? []) as Array<object>).map(key => ({...key,op:'eq'})); delete p['keys']; }
  if (op === 'aggregate') { if (!p['aggregations']) p['aggregations'] = ((p['aggregates'] ?? []) as Array<Record<string,unknown>>).map(a => ({op: a['function'] === 'count' && !a['column'] ? 'count_rows' : ({avg:'mean',stddev_samp:'std'} as Record<string,string>)[String(a['function'])] ?? a['function'], ...(a['column'] ? {column:a['column']} : {}),output:a['name']})); delete p['aggregates']; }
  if (op === 'union') { p['mode'] ??= 'by_name'; p['allow_missing'] ??= true; }
  if (op === 'unpivot') { p['value_columns'] ??= p['columns'] ?? []; delete p['columns']; }
  if (op === 'split' || op === 'sample') { p['method'] ??= 'random'; p['stratify_by'] ??= p['stratify'] ?? []; delete p['stratify']; }
  if (op === 'split') { p['key'] ??= p['keys']; delete p['keys'];if(p['key']===undefined||Array.isArray(p['key'])&&!p['key'].length)delete p['key']; p['outputs'] ??= draft.spec.outputs.map((out,n) => ({port:out.port,ratio:((p['ratios'] ?? []) as number[])[n] ?? 1/draft.spec.outputs.length})); delete p['ratios']; }
  if (op === 'sample') { if (p['fraction'] === undefined) p['n'] ??= p['rows'] ?? 100; delete p['rows'];if(p['keys']!==undefined)p['key']??=p['keys'];delete p['keys'];if(Array.isArray(p['key'])&&!p['key'].length)delete p['key']; }
  return p;
}
export class PrepHistory {
  private past: PrepDraft[] = []; private future: PrepDraft[] = [];
  get canUndo(): boolean { return this.past.length > 0; }
  get canRedo(): boolean { return this.future.length > 0; }
  record(before: PrepDraft, after: PrepDraft): void {
    if (JSON.stringify(before) === JSON.stringify(after)) return;
    this.past = [...this.past, structuredClone(before)].slice(-PREP_HISTORY_LIMIT); this.future = [];
  }
  undo(current: PrepDraft): PrepDraft { const last = this.past.pop(); if (!last) return current; this.future.push(structuredClone(current)); return last; }
  redo(current: PrepDraft): PrepDraft { const next = this.future.pop(); if (!next) return current; this.past.push(structuredClone(current)); return next; }
}
export interface PrepInputState { port: string; origin: 'pin'|'test'|'upstream'|'unavailable'; ref?: DatasetRef; nodeId?: string; }
/** Resolve the explicitly selected output of every edge; never pick split's first output. */
export function prepInputStates(node: CanonicalFlowNode, graph: Pick<CanonicalFlow, 'nodes'|'edges'>, runs: Record<string, NodeRunSummary> = {}, seen: string[] = []): PrepInputState[] {
  if (seen.includes(node.id) || seen.length >= 10) throw new Error('DATAPREP_UPSTREAM_DEPTH');
  const draft = prepDraftFromNode(node);
  return prepDraftPorts(draft).map(port => {
    const pin = draft.inputs[port];
    if (pin?.dataset_id || pin?.dataset_slug) return {port, origin: 'pin', ref: pin};
    const candidates = graph.edges.filter(edge => edge.to === node.id && (edge.to_port ?? 'in') === port && (!edge.kind || edge.kind === 'data'));
    if (candidates.length !== 1) return {port, origin: 'unavailable'};
    const edge = candidates[0], source = graph.nodes.find(row => row.id === edge.from);
    if (!source) return {port, origin: 'unavailable'};
    const sourcePorts = source.outputs?.map(output => output.name) ?? [];
    const fromPort = edge.from_port ?? (sourcePorts.length === 1 ? sourcePorts[0] : 'out');
    if (!edge.from_port && isPrepNode(source) && prepDraftFromNode(source).spec.operation === 'split') return {port, origin: 'unavailable'};
    const run = runs[source.id], result = run?.data?.outputs?.[fromPort];
    const datasetId = typeof result === 'string' ? result : result?.dataset_id;
    if (run && ['succeeded','completed'].includes(run.status) && datasetId) return {port, origin: 'test', ref: {dataset_id: datasetId}, nodeId: source.id};
    if (run && ['succeeded','completed'].includes(run.status) && run.data?.dataset_id && sourcePorts.length <= 1) return {port, origin: 'test', ref: {dataset_id: run.data.dataset_id}, nodeId: source.id};
    if (isPrepNode(source)) {
      const inputs = prepInputStates(source, graph, runs, [...seen,node.id]);
      if (inputs.every(input => input.ref)) {
        const upstream = prepDraftFromNode(source), params = canonicalPrepParams(upstream);
        return {port, origin: 'upstream', nodeId: source.id, ref: {dataset_id: '', upstream: {spec: params['spec'], output_port: fromPort, inputs: Object.fromEntries(inputs.map(input => [input.port,input.ref!])), outputs: upstream.spec.outputs}}};
      }
    }
    return {port, origin: 'unavailable', nodeId: source.id};
  });
}
export function prepSummary(node: CanonicalFlowNode): {key: string; count: number} {
  const draft = prepDraftFromNode(node);
  return draft.spec.operation === 'prepare' ? {key: 'dataops.summary.steps', count: draft.spec.steps.filter(step => step.enabled !== false).length}
    : draft.spec.operation === 'split' ? {key: 'dataops.summary.outputs', count: draft.spec.outputs.length}
    : draft.spec.operation === 'join' ? {key: 'dataops.summary.keys', count: ((draft.spec.params['on'] ?? draft.spec.params['keys'] ?? []) as unknown[]).length}
    : {key: 'dataops.summary.inputs', count: prepDraftPorts(draft).length};
}
export function saltedPrep(draft: PrepDraft): boolean { return draft.spec.steps.some(step => step.enabled !== false && step.action === 'hash' && (step.params['salt'] !== 'none' || !!step.params['salt_secret_ref'])); }
export function prepError(error: unknown): {code: string; stepId?: string} {
  const response = error as {error?: {detail?: {code?: string; step_id?: string; errors?: Array<{code?: string; step_id?: string}>}}; message?: string};
  const detail = response?.error?.detail, first = detail?.errors?.[0];
  return {code: first?.code ?? detail?.code ?? response?.message ?? 'DATAPREP_REQUEST_FAILED', stepId: first?.step_id ?? detail?.step_id};
}

/** A deliberate dataset pin replaces the data edge on that input port. */
export function prepPinnedEdges(edges: CanonicalFlow['edges'], nodeId:string, draft:PrepDraft):CanonicalFlow['edges'] {
  return edges.filter(edge=>edge.to!==nodeId||!!edge.kind&&edge.kind!=='data'||!(draft.inputs[edge.to_port??'in']?.dataset_id||draft.inputs[edge.to_port??'in']?.dataset_slug));
}

export function prepPreviewOutputRows(result:PrepPreview, port='out'):number|null {
 const value=(result.counters?.['outputs'] as Record<string,unknown>|undefined)?.[port];
 return typeof value==='number'&&Number.isFinite(value)&&value>=0?value:null;
}
