import type { CanonicalFlowNode, NodePort } from '@app/core/flow-serializer.service';
import { validatePrepParams } from './prep-fields';
import type { TabularColumn, TabularColumnStats, TabularRow } from '@app/shared/ui/data-table.vm';

export type PrepOperation = 'prepare' | 'join' | 'union' | 'aggregate' | 'pivot' | 'unpivot' | 'split' | 'sample';
export type PrepAction = 'bin' | 'select_columns' | 'drop_columns' | 'rename_columns' | 'select' | 'drop' | 'rename' | 'cast' | 'fill_null' | 'drop_null' | 'filter' | 'derive' | 'sort' | 'deduplicate' | 'trim' | 'upper' | 'lower' | 'replace' | 'date_format' | 'hash' | 'move_columns' | 'copy_column' | 'concat_columns' | 'normalize_column_names' | 'add_column' | 'parse_date' | 'format_date' | 'from_epoch' | 'parse_number' | 'to_boolean' | 'drop_nulls' | 'fill_nulls' | 'filter_rows' | 'filter_range' | 'filter_expression' | 'flag_rows' | 'text_transform' | 'replace_values' | 'split_column' | 'extract_regex' | 'count_occurrences' | 'substring' | 'pad' | 'length' | 'negate_boolean' | 'bin_numeric' | 'formula' | 'conditional_column' | 'map_values' | 'window' | 'mask' | 'dedup' | 'round' | 'math' | 'extract_date_parts' | 'date_diff' | 'date_add' | 'truncate_date' | 'convert_timezone' | 'scale';
export interface PrepStep { id?: string; enabled?: boolean; comment?: string; action: PrepAction; params: Record<string, unknown>; }
export interface PrepOutput { port: string; name: string; append_version_of?: string | null; }
export interface DataPrepSpec { version: 1; operation: PrepOperation; steps: PrepStep[]; params: Record<string, unknown>; outputs: PrepOutput[]; seed: number; }
export interface DatasetRef { dataset_id: string; dataset_slug?: string; upstream?: {spec: unknown; inputs: Record<string, DatasetRef>; outputs?: PrepOutput[]; output_port?: string}; }
export interface PrepDraft { spec: DataPrepSpec; inputs: Record<string, DatasetRef>; placement?: string; timeout_s?: number | null; }
export interface PrepCatalog { feature?: {enabled:boolean;placements?:string[]}; step_definitions?: import('./prep-fields').PrepStepDefinition[]; functions?: Array<{name:string; label_key?:string}>; version: number; operations: PrepOperation[]; steps: PrepAction[]; placements: string[]; spec_schema: Record<string, unknown>; }
export interface PrepCompilation { sources?: Array<{port:string;dataset_id:string}>; sql_export?: string; sql_export_allowed?: boolean; sql_export_by_port?: Record<string,string>; sql: string; fingerprint: string; schema: TabularColumn[]; columns: string[]; ports: string[]; }
export interface PrepPreview { output_schema?:TabularColumn[];stats_scope?:'sample'; rows: TabularRow[]; schema: TabularColumn[]; sample: true; sample_metadata?: Record<string, unknown>;
  sample_info?: {rows: number; of_rows: number; version: unknown}; stats?: Record<string, TabularColumnStats>; duration_ms?: number;
  step_schemas?: Array<{id: string; index: number; enabled: boolean; schema: TabularColumn[]; schema_diff?: {added?: string[]; removed?: string[]; changed?: string[]}}>;
  warnings?: Array<string | {code: string; step_id?: string}>; counters?: Record<string, unknown>; counts?: Record<string, number>;
}
export interface PrepExecution { id: string; status: string; stage?: string; error?: string | null; output_json?: Record<string, unknown> | null; output?: Record<string, unknown>; }
export const PREP_OPERATIONS: PrepOperation[] = ['prepare', 'join', 'union', 'aggregate', 'unpivot', 'split', 'sample'];
export const PREP_ACTIONS: PrepAction[] = ['bin', 'select_columns', 'drop_columns', 'rename_columns', 'select', 'drop', 'rename', 'cast', 'fill_null', 'drop_null', 'filter', 'derive', 'sort', 'deduplicate', 'trim', 'upper', 'lower', 'replace', 'date_format', 'hash', 'move_columns', 'copy_column', 'concat_columns', 'normalize_column_names', 'add_column', 'parse_date', 'format_date', 'from_epoch', 'parse_number', 'to_boolean', 'drop_nulls', 'fill_nulls', 'filter_rows', 'filter_range', 'filter_expression', 'flag_rows', 'text_transform', 'replace_values', 'split_column', 'extract_regex', 'count_occurrences', 'substring', 'pad', 'length', 'negate_boolean', 'bin_numeric', 'formula', 'conditional_column', 'map_values', 'window', 'mask', 'dedup', 'round', 'math', 'extract_date_parts', 'date_diff', 'date_add', 'truncate_date', 'convert_timezone', 'scale'];
export const PREVIEW_ROW_LIMIT = 100;

export function newPrepDraft(): PrepDraft {
  return { spec: { version: 1, operation: 'prepare', params: {}, steps: [], outputs: [{ port: 'out', name: '' }], seed: 42 }, inputs: {} };
}
export function prepInputPorts(operation: PrepOperation): string[] {
  return operation === 'join' ? ['left', 'right'] : operation === 'union' ? ['in_1', 'in_2'] : ['in'];
}
export function prepDraftPorts(draft: PrepDraft): string[] {
  return draft.spec.operation === 'union' ? [...new Set(['in_1', 'in_2', ...Object.keys(draft.inputs)])].sort((a,b) => Number(a.slice(3))-Number(b.slice(3))) : prepInputPorts(draft.spec.operation);
}
export function changePrepOperation(draft: PrepDraft, operation: PrepOperation): PrepDraft {
  const next = structuredClone(draft);
  const oldPorts = Object.keys(next.inputs);
  const ports = prepInputPorts(operation);
  next.inputs = Object.fromEntries(ports.flatMap((port, index) => {
    const reference = next.inputs[port] ?? next.inputs[oldPorts[index]];
    return reference ? [[port, reference]] : [];
  }));
  const params: Partial<Record<PrepOperation, Record<string, unknown>>> = {
    join: { how: 'left', keys: [{ left: '', right: '' }] }, aggregate: { group_by: [], aggregates: [{ column: null, function: 'count', name: 'count' }] },
    union: { distinct: false }, pivot: { group_by: [], column: '', values: [], value_column: '', function: 'sum' },
    unpivot: { columns: [], name_column: 'variable', value_column: 'value' }, sample: { keys: [], rows: 100 }, split: { keys: [], ratios: [.8, .2] },
  };
  next.spec = { ...next.spec, steps: operation === 'prepare' ? next.spec.steps : [], operation, params: params[operation] ?? {}, outputs: operation === 'split'
    ? [{ port: 'train', name: '' }, { port: 'test', name: '' }]
    : [{ port: 'out', name: draft.spec.outputs[0]?.name ?? '' }] };
  return next;
}
export function movePrepStep(draft: PrepDraft, index: number, direction: -1 | 1): PrepDraft {
  const next = structuredClone(draft), target = index + direction;
  if (index < 0 || target < 0 || index >= next.spec.steps.length || target >= next.spec.steps.length) return next;
  [next.spec.steps[index], next.spec.steps[target]] = [next.spec.steps[target], next.spec.steps[index]];
  return next;
}
/** Column choices track each operation and the ordered steps, never inferred row values. */
export function prepColumnsBefore(draft: PrepDraft, left: string[], right: string[], index: number): string[] {
  const params = draft.spec.params;
  let columns = [...left];
  if (draft.spec.operation === 'join') {
    const keys = (params['keys'] ?? []) as Array<{right: string}>;
    for (const name of right.filter(name => !keys.some(key => key.right === name))) columns.push(columns.includes(name) ? name + '_right' : name);
  } else if (draft.spec.operation === 'aggregate') {
    columns = [...((params['group_by'] ?? []) as string[]), ...((params['aggregates'] ?? []) as Array<{name: string}>).map(a => a.name)];
  } else if (draft.spec.operation === 'pivot') {
    columns = [...((params['group_by'] ?? []) as string[]), ...((params['values'] ?? []) as unknown[]).map(String)];
  } else if (draft.spec.operation === 'unpivot') {
    columns = [...columns.filter(name => !((params['columns'] ?? []) as string[]).includes(name)), String(params['name_column'] ?? 'variable'), String(params['value_column'] ?? 'value')];
  }
  for (const step of draft.spec.steps.slice(0, index)) {
    if (step.enabled === false) continue;
    const p = step.params, action = step.action;
    const selector = p['columns'];
    const selected: string[] = Array.isArray(selector) ? selector : selector && typeof selector === 'object' ? (Array.isArray((selector as Record<string,unknown>)['names']) ? (selector as {names:string[]}).names : [...columns]) : [];
    const output = p['output'] ?? p['name'];
    if (action === 'rename' || action === 'rename_columns') {const mapping=Array.isArray(p['mapping'])?Object.fromEntries((p['mapping'] as Array<{from:string;to:string}>).map(row=>[row.from,row.to])):(p['mapping']??{}) as Record<string,string>;columns=columns.map(c=>mapping[c]??c);}
    else if (action === 'select' || action === 'select_columns') columns = selected;
    else if (action === 'drop' || action === 'drop_columns') columns = columns.filter(c => !selected.includes(c));
    else if (action === 'move_columns') {
      const rest = columns.filter(c => !selected.includes(c));
      const at = p['position'] === 'start' ? 0 : p['position'] === 'end' ? rest.length : rest.indexOf(String(p['anchor'])) + (p['position'] === 'after' ? 1 : 0);
      columns = [...rest.slice(0,at), ...selected, ...rest.slice(at)];
    } else if (action === 'normalize_column_names') {
      const used = new Set<string>();
      columns = columns.map(name => {
        let value = p['style'] === 'lower' ? name.toLowerCase() : p['style'] === 'papai' ? name.replace(/[$ ,;{}()\n\t=]/g, '_') : name.normalize('NFKD').replace(/[^\x00-\x7F]/g, '').replace(/[^a-zA-Z0-9]+/g, '_').replace(/^_+|_+$/g, '').toLowerCase();
        value ||= 'column'; if (/^[0-9]/.test(value)) value = '_' + value;
        const base = value; let n = 2; while (used.has(value.toLowerCase()) && p['dedupe'] === 'suffix') value = base + '_' + n++;
        used.add(value.toLowerCase()); return value;
      });
    } else if (action === 'split_column') columns.push(...((p['outputs'] ?? []) as string[]));
    else if (action === 'extract_regex') columns.push(...((p['outputs'] ?? []) as Array<{name: string}>).map(o => o.name));
    else if (action === 'extract_date_parts') columns.push(...((p['parts'] ?? []) as string[]).map(part => String(p['naming'] ?? '{column}_{part}').replaceAll('{column}', String(p['column'])).replaceAll('{part}', part)));
    else if (action === 'scale' && p['output_suffix']) columns.push(...selected.map(c => c + p['output_suffix']));
    else if (typeof output === 'string' && output) {
      const legacy = ['fill_null','trim','upper','lower','replace','date_format'].includes(action);
      if (legacy && p['name']) columns = columns.map(c => c === p['column'] ? output : c);
      else if (!columns.includes(output)) columns.push(output);
    }
  }
  return [...new Set(columns.filter(Boolean))];
}
export function prepRequest(draft: PrepDraft): PrepDraft {
  if (draft.spec.operation === 'union' && prepDraftPorts(draft).length > 16) throw new Error('dataops.error.ports');
  if (draft.spec.outputs.length > 8 || !draft.spec.outputs.length || new Set(draft.spec.outputs.map(output => output.port)).size !== draft.spec.outputs.length) throw new Error('dataops.error.ports');
  if (!draft.spec.outputs.every(output => output.name.trim() && output.name.length <= 200) || new Set(draft.spec.outputs.map(o => o.name)).size !== draft.spec.outputs.length) throw new Error('dataops.error.output_name');
  if (!prepDraftPorts(draft).every(port => draft.inputs[port]?.dataset_id)) throw new Error('dataops.error.inputs');
  if (!draft.spec.outputs.every(o => /^[a-z][a-z0-9_]{0,63}$/.test(o.port)) || (draft.spec.operation !== 'split' && (draft.spec.outputs.length !== 1 || draft.spec.outputs[0].port !== 'out'))) throw new Error('dataops.error.ports');
  if (!Number.isInteger(draft.spec.seed) || draft.spec.seed < 0 || draft.spec.seed > 2147483647 || draft.spec.steps.length > 200 || (draft.spec.operation !== 'prepare' && draft.spec.steps.length)) throw new Error('dataops.error.parameters');
  if (!validatePrepParams(draft.spec.operation,draft.spec.params) || draft.spec.steps.some(step => !PREP_ACTIONS.includes(step.action) || !validatePrepParams(step.action,step.params))) throw new Error('dataops.error.parameters');
  if (draft.spec.operation === 'split') {
    const ratios = draft.spec.params['ratios'];
    if (draft.spec.outputs.length < 2 || !Array.isArray(ratios) || ratios.length !== draft.spec.outputs.length || ratios.some(n => typeof n !== 'number' || !Number.isFinite(n) || n <= 0) || Math.abs(ratios.reduce((a,b) => a+b,0)-1) > 1e-9) throw new Error('dataops.error.ratios');
  }
  const serialized = JSON.stringify(draft.spec, (_key,value) => { if (typeof value === 'number' && !Number.isFinite(value) || value === undefined) throw new Error('dataops.error.parameters'); return value; });
  if (new TextEncoder().encode(serialized).length > 256000) throw new Error('dataops.error.parameters');
  return structuredClone(draft);
}
export function prepDraftFromNode(node: CanonicalFlowNode): PrepDraft {
  const config = (node.config ?? {}) as Record<string, unknown>;
  const params = config['params'] as Record<string, unknown> | undefined;
  if (params?.['spec']) {
    const spec = params['spec'] as {version: 1; operation: PrepOperation; params: Record<string, unknown>};
    const inner = {...spec.params};
    const steps = ((inner['steps'] ?? []) as Array<PrepStep & {kind?: PrepAction}>).map(step => ({...step, action: step.kind ?? step.action}));
    delete inner['steps'];
    const pins = (params['sources'] ?? []) as Array<{port: string; dataset_id?: string; dataset_slug?: string}>;
    const inputs = Object.fromEntries((node.inputs ?? []).map(port => [port.name, {dataset_id: ''}]));
    for (const pin of pins) inputs[pin.port] = {dataset_id: pin.dataset_id ?? '', ...(pin.dataset_slug ? {dataset_slug: pin.dataset_slug} : {})};
    return structuredClone({spec: {version: spec.version, operation: spec.operation, params: inner, steps, outputs: (params['outputs'] ?? [{port: 'out', name: ''}]) as PrepOutput[], seed: Number(inner['seed'] ?? 42)}, inputs, placement: String(params['placement'] ?? 'auto'), timeout_s: params['timeout_s'] as number | null ?? null});
  }
  return structuredClone((config['data_prep'] ?? params?.['data_prep']) as PrepDraft | undefined ?? newPrepDraft());
}
export function prepNodePatch(node: CanonicalFlowNode, draft: PrepDraft): Partial<CanonicalFlowNode> {
  const inputs: NodePort[] = prepDraftPorts(draft).map(name => ({ name, schema: 'object', required: true }));
  const outputs: NodePort[] = draft.spec.outputs.map(output => ({ name: output.port, schema: 'object' }));
  const config = structuredClone(node.config ?? {}) as Record<string, unknown>;
  delete config['inputs_map'];
  const params = config['params'];
  if (params && typeof params === 'object' && !Array.isArray(params)) {
    delete (params as Record<string, unknown>)['inputs_map'];
    delete (params as Record<string, unknown>)['data_prep'];
  }
  if (params && typeof params === 'object' && 'spec' in params) {
    delete config['data_prep'];
    config['params'] = {...params, ...canonicalPrepParams(draft)};
  } else config['data_prep'] = structuredClone(draft);
  return { config, inputs, outputs };
}
/** New Flow nodes use the plan's wire contract; legacy readers remain lossless. */
export function canonicalPrepParams(draft: PrepDraft): Record<string, unknown> {
  const params = structuredClone(draft.spec.params);
  if (draft.spec.operation === 'prepare') params['steps'] = draft.spec.steps.map(step => ({
    id: step.id ?? crypto.randomUUID(), kind: step.action, enabled: step.enabled !== false, comment: step.comment ?? '', params: structuredClone(step.params),
  }));
  if (draft.spec.operation === 'sample' || draft.spec.operation === 'split') params['seed'] = draft.spec.seed;
  return {spec: {version: 1, operation: draft.spec.operation, params},
    outputs: structuredClone(draft.spec.outputs), sources: Object.entries(draft.inputs).flatMap<Record<string,string>>(([port, ref]) =>
      ref.dataset_id ? [{port, dataset_id: ref.dataset_id}] : ref.dataset_slug ? [{port, dataset_slug: ref.dataset_slug}] : []),
    placement: draft.placement ?? 'auto', timeout_s: draft.timeout_s ?? null};
}
export function boundedPreview(preview: PrepPreview): PrepPreview {
  return { ...preview, rows: preview.rows.slice(0, PREVIEW_ROW_LIMIT), schema: preview.schema.slice(0, 100) };
}
export function executionDatasets(execution: PrepExecution | null): string[] {
  const output = execution?.output_json ?? execution?.output ?? {};
  const refs = output['outputs'] ?? output['datasets'] ?? [];
  const values = Array.isArray(refs) ? refs : refs && typeof refs === 'object' ? Object.values(refs) : [];
  return values.flatMap(value => value && typeof value === 'object' && typeof (value as Record<string, unknown>)['dataset_id'] === 'string' ? [(value as {dataset_id: string}).dataset_id] : []);
}

export type QuestionType = 'boolean' | 'choice' | 'multi_choice' | 'score' | 'probability';
export interface TypedQuestion {
  key: string; question: string; type: QuestionType; choices: string[]; required: boolean; requires_evidence: boolean;
  minimum?: number | null; maximum?: number | null; acceptable_values?: Array<string | boolean> | null; accept_minimum?: number | null; accept_maximum?: number | null;
}
export interface TypedJudgeDraft {
  rubric_id: string; rubric_version: string; questions: TypedQuestion[];
  budget: { max_calls: number; max_tokens: number; max_cost_usd: number; max_output_tokens: number; timeout_s: number; max_prompt_bytes: number; };
  tariff: { provider: string; model: string; input_per_million: number; output_per_million: number; currency: 'USD'; reference: string; };
  run_evidence?: { sources: Array<{ id: string; skill_slug: string; node_id?: string | null; paths: string[]; required: true }>; native_refs: Array<{kind: 'document_set' | 'dataset' | 'model'; id: string}> };
}
export const JUDGE_BUDGET_LIMITS = {
  max_calls: {min:1,max:10000,step:1}, max_tokens: {min:1,max:100000000,step:1},
  max_cost_usd: {min:0,max:10000,step:'any'}, max_output_tokens: {min:64,max:8192,step:1},
  timeout_s: {min:1,max:120,step:1}, max_prompt_bytes: {min:1024,max:128000,step:1},
} as const;
export function validateJudgeDraft(draft: TypedJudgeDraft): string[] {
  const errors = validateQuestions(draft.questions);
  if (draft.run_evidence) {
    const {sources, native_refs} = draft.run_evidence;
    if (!sources.length || sources.length > 16 || new Set(sources.map(source => source.id)).size !== sources.length
      || sources.some(source => !/^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$/.test(source.id) || !/^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,159}$/.test(source.skill_slug)
        || !source.paths.length || source.paths.length > 32 || new Set(source.paths).size !== source.paths.length || source.paths.some(path => !path.startsWith('/') || path === '/' || path.length > 500 || /~(?![01])/.test(path))
        || source.node_id != null && (!source.node_id.trim() || source.node_id.length > 160))
      || native_refs.length > 32 || native_refs.some(ref => !ref.id.trim() || ref.id.length > 36)
      || new Set(native_refs.map(ref => `${ref.kind}:${ref.id}`)).size !== native_refs.length) errors.push('dataops.error.judge_run_evidence');
  }
  for (const key of Object.keys(JUDGE_BUDGET_LIMITS) as Array<keyof typeof JUDGE_BUDGET_LIMITS>) {
    const value = draft.budget[key], limits = JUDGE_BUDGET_LIMITS[key];
    if (!Number.isFinite(value) || (key === 'max_cost_usd' ? value <= 0 : value < limits.min) || value > limits.max || limits.step === 1 && !Number.isInteger(value)) errors.push('dataops.error.judge_budget');
  }
  if ([draft.tariff.input_per_million,draft.tariff.output_per_million].some(value => !Number.isFinite(value) || value < 0 || value > 1000)) errors.push('dataops.error.judge_tariff');
  if (!draft.rubric_id.trim() || draft.rubric_id.length > 160 || !draft.rubric_version.trim() || draft.rubric_version.length > 60 || !draft.tariff.provider.trim() || draft.tariff.provider.length > 100 || !draft.tariff.model.trim() || draft.tariff.model.length > 200 || !draft.tariff.reference.trim() || draft.tariff.reference.length > 300) errors.push('dataops.error.judge_identity');
  return [...new Set(errors)];
}
export function newQuestion(key: string): TypedQuestion { return { key, question: '', type: 'boolean', choices: [], required: true, requires_evidence: true }; }
export function newJudgeDraft(): TypedJudgeDraft {
  return { rubric_id: '', rubric_version: '1', questions: [newQuestion('question_1')],
    budget: { max_calls: 1, max_tokens: 10000, max_cost_usd: 1, max_output_tokens: 2048, timeout_s: 45, max_prompt_bytes: 32000 },
    tariff: { provider: '', model: '', input_per_million: 0, output_per_million: 0, currency: 'USD', reference: '' } };
}
export function judgeDraftFromNode(node: CanonicalFlowNode): TypedJudgeDraft {
  const config = node.config as Record<string, unknown> | undefined;
  const params = config?.['params'] as Record<string, unknown> | undefined;
  const draft = structuredClone((config?.['typed_evaluation'] ?? params?.['typed_evaluation']) as TypedJudgeDraft | undefined ?? newJudgeDraft());
  if (draft.run_evidence) draft.run_evidence.native_refs ??= [];
  return draft;
}
export function judgeNodePatch(node: CanonicalFlowNode, draft: TypedJudgeDraft): Partial<CanonicalFlowNode> {
  const config = structuredClone(node.config ?? {}) as Record<string, unknown>;
  const params = config['params'];
  if (params && typeof params === 'object' && !Array.isArray(params)) delete (params as Record<string, unknown>)['typed_evaluation'];
  config['typed_evaluation'] = structuredClone(draft);
  return {config};
}
export function changeQuestionType(question: TypedQuestion, type: QuestionType): TypedQuestion {
  return { key: question.key, question: question.question, type, required: question.required, requires_evidence: question.requires_evidence,
    choices: type === 'choice' || type === 'multi_choice' ? (question.choices.length >= 2 ? [...question.choices] : ['', '']) : [],
    ...(type === 'score' ? { minimum: 0, maximum: 100 } : {}) };
}
export function validateQuestions(questions: TypedQuestion[]): string[] {
  const errors: string[] = [];
  if (!questions.length || questions.length > 32 || !questions.some(q => q.required)) errors.push('dataops.error.questions');
  if (new Set(questions.map(q => q.key)).size !== questions.length) errors.push('dataops.error.keys');
  for (const q of questions) {
    if (!/^[a-zA-Z][a-zA-Z0-9_]{0,63}$/.test(q.key) || (!q.question.trim() || q.question.length > 2000)) errors.push('dataops.error.question');
    if ((q.type === 'choice' || q.type === 'multi_choice') && (q.choices.length < 2 || q.choices.length > 100 || q.choices.some(c => !c.trim() || c.length > 120) || new Set(q.choices).size !== q.choices.length)) errors.push('dataops.error.choices');
    if (q.type === 'score' && (q.minimum == null || q.maximum == null || !Number.isFinite(q.minimum) || !Number.isFinite(q.maximum) || q.minimum > q.maximum)) errors.push('dataops.error.bounds');
    if (q.type === 'score' || q.type === 'probability') {
      const low = q.type === 'probability' ? 0 : q.minimum, high = q.type === 'probability' ? 1 : q.maximum;
      if ([q.accept_minimum, q.accept_maximum].some(n => n != null && (!Number.isFinite(n) || low == null || high == null || n < low || n > high)) || q.accept_minimum != null && q.accept_maximum != null && q.accept_minimum > q.accept_maximum) errors.push('dataops.error.bounds');
    }
    if (q.acceptable_values != null && (q.type !== 'multi_choice' && !q.acceptable_values.length || q.acceptable_values.some(v => q.type === 'boolean' ? typeof v !== 'boolean' : typeof v !== 'string' || !q.choices.includes(v)))) errors.push('dataops.error.choices');
  }
  return [...new Set(errors)];
}
export interface TypedAnswer { status: 'answered' | 'abstained' | 'invalid'; value: unknown; reason: string | null; explanation: string; confidence: number | null; evidence: Array<{ kind?: 'text'|'image'; evidence_id: string; start?: number; end?: number; quote?: string; image_sha256?:string; region?:number[]|null; description?:string }>; }
export interface TypedEvaluationResult { schema_version: 2; evaluation_id: string; questions?: TypedQuestion[]; answers: Record<string, TypedAnswer>; status: string; disposition: string; quality_status: string; reason?: string | null; response_diagnostic?: {category: string; question_index?: number}; confidence: number | null; coverage: Record<string, number | string>; calibration?: {scope: string}; cost?: { amount: number | null; currency: string; measurement_coverage: string }; }
const JUDGE_RESPONSE_CATEGORIES = ['response_size_or_type', 'json', 'schema', 'abstention', 'answer_state', 'evidence_required', 'evidence_scope', 'image_citation', 'evidence_kind', 'evidence_span', 'evidence_quote', 'validation'] as const;
/** A returned evaluation is distinct from the transport status of its call. */
export function typedJudgeOutcome(result: TypedEvaluationResult | null): {label: string; state: 'completed'|'partial'|'failed'} | null {
  if (!result) return null;
  if (result.status === 'failed') return {label: 'dataops.judge.failure.title', state: 'failed'};
  if (result.quality_status === 'failed') return {label: 'dataops.judge.criteria_failed', state: 'failed'};
  if (result.quality_status === 'passed') return {label: 'dataops.status.passed', state: 'completed'};
  return {label: 'dataops.status.unassessed', state: 'partial'};
}
export function typedJudgeFailure(result: TypedEvaluationResult | null): {message: string; action: string; question: string | null} | null {
  if (result?.status !== 'failed') return null;
  let message = 'unavailable', action = 'review';
  const reason = result.reason;
  if (reason === 'JUDGE_RESPONSE_INVALID') {
    const category = result.response_diagnostic?.category;
    message = JUDGE_RESPONSE_CATEGORIES.some(value => value === category) ? category! : 'validation';
    action = ['evidence_required', 'evidence_scope', 'image_citation', 'evidence_kind', 'evidence_span', 'evidence_quote'].includes(message) ? 'evidence' : 'configuration';
  } else if (reason === 'JUDGE_OUTPUT_TRUNCATED') { message = 'truncated'; action = 'response_limit'; }
  else if (reason === 'JUDGE_TIMEOUT') { message = 'timeout'; action = 'retry'; }
  else if (reason === 'JUDGE_PROVIDER_UNAVAILABLE') { message = 'temporarily_unavailable'; action = 'retry'; }
  else if (reason === 'JUDGE_ACCESS_REVOKED') { message = 'access'; action = 'access'; }
  else if (['JUDGE_BUDGET_EXHAUSTED', 'JUDGE_MEASURED_BUDGET_EXCEEDED', 'SERVICE_BUDGET_EXHAUSTED'].includes(reason ?? '')) { message = 'budget'; action = 'budget'; }
  const index = reason === 'JUDGE_RESPONSE_INVALID' ? result.response_diagnostic?.question_index : undefined;
  const question = Number.isInteger(index) && index! >= 0 && Array.isArray(result.questions) ? result.questions[index!]?.question : null;
  return {message: 'dataops.judge.failure.' + message, action: 'dataops.judge.recovery.' + action, question: typeof question === 'string' && question.trim() ? question.slice(0, 2000) : null};
}
export function typedResult(value: unknown): TypedEvaluationResult | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  if (row['schema_version'] !== 2 || typeof row['evaluation_id'] !== 'string' || !row['answers'] || typeof row['answers'] !== 'object' || Array.isArray(row['answers']) || !row['coverage'] || typeof row['coverage'] !== 'object' || Array.isArray(row['coverage'])) return null;
  const number = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
  const digest = (v: unknown) => typeof v === 'string' && /^[0-9a-f]{64}$/.test(v);
  const valid = Object.values(row['answers']).every(answer => answer && typeof answer === 'object' && ['answered', 'abstained', 'invalid'].includes(answer.status) && Array.isArray(answer.evidence)
    && answer.evidence.every((proof: Record<string, unknown>) => {
      if (!proof || typeof proof['evidence_id'] !== 'string') return false;
      if (proof['kind'] === 'image') {
        const region = proof['region'];
        return typeof proof['description'] === 'string' && !!proof['description'].trim() && digest(proof['image_sha256']) && (region == null || Array.isArray(region) && region.length === 4 && region.every(n => number(n) && n >= 0 && n <= 1) && region[0] < region[2] && region[1] < region[3]);
      }
      return (proof['kind'] == null || proof['kind'] === 'text') && typeof proof['quote'] === 'string' && !!proof['quote'] && number(proof['start']) && number(proof['end']) && Number.isInteger(proof['start']) && Number.isInteger(proof['end']) && proof['start'] >= 0 && proof['end'] > proof['start'];
    }));
  if (!valid) return null;
  const calibration = row['calibration'] as Record<string, unknown> | undefined;
  const profile = calibration?.['profile_ref'] as Record<string, unknown> | undefined;
  const calibrated = row['confidence_reason'] === 'qualified_family_empirical_bound' && digest(calibration?.['qualification_digest']) && digest(profile?.['digest']);
  const confidence = (n: unknown) => calibrated && number(n) && n >= 0 && n <= 1 ? n : null;
  return {...row, confidence: confidence(row['confidence']), answers: Object.fromEntries(Object.entries(row['answers']).map(([key,answer]) => [key, {...answer, confidence: confidence(answer.confidence)}]))} as unknown as TypedEvaluationResult;
}
