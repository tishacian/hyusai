/** Read-only presentation of retained execution output. No model calls, data
 * lookup or inference of a business result from a current node configuration. */
import type { Run } from '@app/core/canonical-api.service';
import type { TabularColumn, TabularColumnKind, TabularRow } from '@app/shared/ui/data-table.vm';
import { projectTimeseries, type TimeseriesMapping, type TimeseriesProjection } from '../../experience/runtime/timeseries';

export type FlowResultPresentation = 'auto' | 'chart' | 'table' | 'metric' | 'document' | 'decisions';
export interface FlowResultDatasetPreview {
  dataset_id?: string;
  rows: unknown[];
  columns?: unknown[];
  schema?: unknown;
  total_rows?: number | null;
  returned_rows?: number;
  truncated?: boolean;
  provenance?: Record<string, unknown>;
}
export interface FlowResultTable {
  rows: TabularRow[];
  columns: TabularColumn[];
  total: number | null;
  omitted: number;
  truncated: boolean;
}
export interface FlowResultFact { key: string; value: string | number | boolean; }
export interface FlowResultDocument { title: string | null; text: string; source: string | null; }
export interface FlowResultPrediction {
  task: 'classification' | 'regression' | 'clustering';
  value: string | number;
  unit: string | null;
  target: string | null;
  positiveLabel: string | null;
  capturedAt: string | null;
}
export interface FlowResultProjection {
  empty: boolean;
  chart: TimeseriesProjection | null;
  table: FlowResultTable | null;
  prediction: FlowResultPrediction | null;
  facts: FlowResultFact[];
  documents: FlowResultDocument[];
  documentTruncated: boolean;
  structured: string;
  structuredTruncated: boolean;
  frequency?: string;
}

export const FLOW_RESULT_ROW_LIMIT = 50;
export const FLOW_RESULT_COLUMN_LIMIT = 16;
const DOCUMENT_LIMIT = 12;
const TEXT_LIMIT = 12_000;
const STRUCTURED_LIMIT = 18_000;
const record = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
const text = (value: unknown, limit = 240): string | null =>
  typeof value === 'string' && value.trim() ? value.trim().slice(0, limit) : null;
const count = (value: unknown): number | null =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
const numeric = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const has = (value: Record<string, unknown>, key: string): boolean => Object.hasOwn(value, key);

function outputRows(value: unknown): unknown[] | null {
  if (Array.isArray(value)) return value;
  const item = record(value);
  if (!item) return null;
  for (const key of ['rows', 'predictions', 'forecast', 'results']) {
    if (Array.isArray(item[key])) return item[key] as unknown[];
  }
  return null;
}

/** Only documented native/Work column shapes become a chart automatically.
 * Custom tables need an explicit mapping; a date-looking id is not a series. */
export function flowResultTimeseriesMapping(rows: unknown[], mapping?: unknown): TimeseriesMapping | null {
  const explicit = record(mapping);
  if (explicit && text(explicit['time']) && text(explicit['value'])) {
    return {
      time: text(explicit['time'], 128)!, value: text(explicit['value'], 128)!,
      actual: text(explicit['actual'], 128) ?? 'actual', lower: text(explicit['lower'], 128) ?? 'lower',
      upper: text(explicit['upper'], 128) ?? 'upper', series: text(explicit['series'], 128) ?? '',
    };
  }
  const samples = rows.slice(0, 50).map(record).filter((item): item is Record<string, unknown> => !!item);
  if (samples.some(item => has(item, 'timestamp') && has(item, 'pred'))) {
    return { time: 'timestamp', value: 'pred', actual: 'actual', lower: 'lower_bound', upper: 'upper_bound', series: samples.some(item => has(item, 'series')) ? 'series' : '' };
  }
  if (samples.some(item => has(item, 'ds') && (has(item, 'forecast') || has(item, 'actual')))) {
    return { time: 'ds', value: 'forecast', actual: 'actual', lower: 'lower', upper: 'upper', series: samples.some(item => has(item, 'series')) ? 'series' : '' };
  }
  return null;
}

function inferredColumn(name: string, rows: TabularRow[], declared?: Record<string, unknown> | null): TabularColumn {
  const kinds: TabularColumnKind[] = ['integer', 'float', 'boolean', 'datetime', 'string', 'other'];
  const requested = declared?.['kind'];
  let kind = kinds.includes(requested as TabularColumnKind) ? requested as TabularColumnKind : 'other' as TabularColumnKind;
  const values = rows.map(item => item[name]).filter(value => value !== null && value !== undefined);
  if (kind === 'other' && values.length) {
    if (values.every(value => typeof value === 'boolean')) kind = 'boolean';
    else if (values.every(numeric)) kind = values.every(Number.isInteger) ? 'integer' : 'float';
    else if (values.every(value => typeof value === 'string')) kind = 'string';
  }
  const dtype = text(declared?.['dtype'], 60);
  return { name, kind, ...(dtype ? { dtype } : {}) };
}

/** An exact, bounded window. A missing total stays unknown; preview length
 * never becomes a fabricated dataset row count. */
export function flowResultTable(rows: unknown[] | null, preview?: FlowResultDatasetPreview | null): FlowResultTable | null {
  if (!rows) return null;
  const clean = rows.slice(0, FLOW_RESULT_ROW_LIMIT).map(record).filter((item): item is TabularRow => !!item);
  const schema = record(preview?.schema);
  const declared = preview?.columns ?? (Array.isArray(preview?.schema) ? preview.schema : Array.isArray(schema?.['columns']) ? schema['columns'] : []);
  const hints = new Map<string, Record<string, unknown> | null>();
  for (const value of declared.slice(0, FLOW_RESULT_COLUMN_LIMIT)) {
    const item = record(value), name = text(typeof value === 'string' ? value : item?.['name'], 160);
    if (name) hints.set(name, item);
  }
  const names = [...new Set([...hints.keys(), ...clean.flatMap(item => Object.keys(item))])];
  const visible = names.slice(0, FLOW_RESULT_COLUMN_LIMIT);
  const columns = visible.map(name => inferredColumn(name, clean, hints.get(name)));
  let cellsTruncated = false;
  const cell = (value: unknown): unknown => {
    if (typeof value === 'string') {
      cellsTruncated ||= value.length > 1_000;
      return value.length > 1_000 ? value.slice(0, 1_000) + '…' : value;
    }
    if (value !== null && typeof value === 'object') {
      const detail = flowResultStructured(value);
      cellsTruncated ||= detail.truncated || detail.text.length > 1_000;
      return detail.text.length > 1_000 ? detail.text.slice(0, 1_000) + '…' : detail.text;
    }
    return value;
  };
  const window = clean.map(item => Object.fromEntries(visible.map(name => [name, cell(item[name])])));
  const total = preview ? count(preview.total_rows) : rows.length;
  const omitted = Math.max(0, rows.length - FLOW_RESULT_ROW_LIMIT) + Math.min(rows.length, FLOW_RESULT_ROW_LIMIT) - clean.length;
  return {
    rows: window, columns, total, omitted,
    truncated: !!preview?.truncated || omitted > 0 || cellsTruncated || names.length > FLOW_RESULT_COLUMN_LIMIT || total !== null && total > window.length,
  };
}

function prediction(value: unknown): FlowResultPrediction | null {
  const wrapper = record(value);
  const item = record(wrapper?.['model_advice']) ?? wrapper;
  if (!item || item['schema_version'] !== 1 || item['status'] !== 'ready') return null;
  const task = item['task'];
  let valueShown: string | number;
  if (task === 'classification' && item['unit'] === 'probability' && numeric(item['score']) && item['score'] >= 0 && item['score'] <= 1) valueShown = item['score'];
  else if (task === 'regression' && numeric(item['value'])) valueShown = item['value'];
  else if (task === 'clustering' && (typeof item['value'] === 'string' || numeric(item['value']))) valueShown = String(item['value']).slice(0, 240);
  else return null;
  return {
    task, value: valueShown, unit: text(item['unit'], 60), target: text(item['target']),
    positiveLabel: text(item['positive_label']), capturedAt: text(item['captured_at'], 100),
  };
}

function documents(value: unknown): { items: FlowResultDocument[]; truncated: boolean } {
  if (typeof value === 'string') return { items: [{ title: null, text: value.slice(0, TEXT_LIMIT), source: null }], truncated: value.length > TEXT_LIMIT };
  const item = record(value);
  if (!item) return { items: [], truncated: false };
  const items: FlowResultDocument[] = [];
  let truncated = false;
  for (const key of ['answer', 'summary', 'text', 'content']) {
    if (typeof item[key] !== 'string' || !item[key]) continue;
    const value = item[key] as string;
    items.push({ title: key, text: value.slice(0, TEXT_LIMIT), source: null });
    truncated ||= value.length > TEXT_LIMIT;
    break;
  }
  const source = ['citations', 'evidence', 'hits', 'documents', 'sources'].map(key => item[key]).find(Array.isArray);
  if (Array.isArray(source)) {
    for (const entry of source.slice(0, DOCUMENT_LIMIT)) {
      const doc = record(entry);
      if (!doc) continue;
      const passage = [doc['quote'], doc['snippet'], doc['text'], doc['content']].find(value => typeof value === 'string' && value.trim());
      if (typeof passage !== 'string') continue;
      items.push({
        title: text(doc['title']) ?? text(doc['filename']) ?? text(doc['document_name']),
        text: passage.slice(0, TEXT_LIMIT),
        source: text(doc['source']) ?? text(doc['document_id']) ?? text(doc['evidence_id']),
      });
      truncated ||= passage.length > TEXT_LIMIT;
    }
    truncated ||= source.length > DOCUMENT_LIMIT;
  }
  return { items, truncated };
}

/** Bounded fallback preserves scalar zero/false and does not interpret HTML.
 * Depth/entry limits also protect the UI from very wide or recursive objects. */
export function flowResultStructured(value: unknown): { text: string; truncated: boolean } {
  let remaining = 1_000, truncated = false;
  const seen = new WeakSet<object>();
  const shorten = (entry: unknown, depth: number): unknown => {
    if (--remaining < 0 || depth > 6) { truncated = true; return '…'; }
    if (typeof entry === 'string') { if (entry.length > TEXT_LIMIT) truncated = true; return entry.slice(0, TEXT_LIMIT); }
    if (!entry || typeof entry !== 'object') return entry;
    if (seen.has(entry)) { truncated = true; return '…'; }
    seen.add(entry);
    if (Array.isArray(entry)) {
      if (entry.length > 50) truncated = true;
      return entry.slice(0, 50).map(item => shorten(item, depth + 1));
    }
    const entries = Object.entries(entry);
    if (entries.length > 40) truncated = true;
    return Object.fromEntries(entries.slice(0, 40).map(([key, item]) => [key, shorten(item, depth + 1)]));
  };
  let result = '';
  try { result = JSON.stringify(shorten(value, 0), null, 2) ?? ''; } catch { truncated = true; }
  if (result.length > STRUCTURED_LIMIT) truncated = true;
  return { text: result.slice(0, STRUCTURED_LIMIT), truncated };
}

export function projectFlowResult(value: unknown, preview?: FlowResultDatasetPreview | null, mapping?: unknown): FlowResultProjection {
  const item = record(value);
  const rows = preview?.rows ?? outputRows(value);
  const selectedMapping = rows ? flowResultTimeseriesMapping(rows, mapping) : null;
  const candidate = selectedMapping && rows ? projectTimeseries(rows, selectedMapping) : null;
  const chart = candidate?.groups.length ? candidate : null;
  const table = flowResultTable(rows, preview);
  const doc = documents(value), structured = flowResultStructured(value);
  const scalarFact = (entry: unknown) => numeric(entry) || typeof entry === 'boolean' || typeof entry === 'string' && entry.length <= 120;
  const facts: FlowResultFact[] = item ? Object.entries(item).filter(([key, entry]) =>
    !['id', 'dataset_id', 'model_id', 'run_id', 'schema_version', 'status', 'captured_at', 'answer', 'summary', 'text', 'content'].includes(key)
      && scalarFact(entry),
  ).slice(0, 12).map(([key, entry]) => ({ key, value: entry as string | number | boolean })) : [];
  const metrics = record(item?.['metrics']);
  if (metrics) {
    for (const [key, entry] of Object.entries(metrics)) {
      if (facts.length >= 12) break;
      if (scalarFact(entry)) facts.push({ key: `metrics.${key}`, value: entry as string | number | boolean });
    }
  }
  if (!item && (numeric(value) || typeof value === 'boolean')) facts.push({ key: 'value', value });
  const meta = record(item?.['forecast']);
  return {
    empty: value === null || value === undefined || item !== null && Object.keys(item).length === 0 && !rows?.length,
    chart, table, prediction: prediction(value), facts, documents: doc.items,
    documentTruncated: doc.truncated, structured: structured.text, structuredTruncated: structured.truncated,
    frequency: text(meta?.['frequency'], 30) ?? text(item?.['frequency'], 30) ?? undefined,
  };
}

/** Keep every recorded decision/action of this node, never a neighbouring
 * AgentLoop's choices. Missing node correlation does not imply a match. */
export function flowNodeDecisionRun(run: Run | null, nodeId: string | null, invocationId?: string | null): Run | null {
  if (!run || !nodeId) return null;
  const calls = (run.skill_invocations ?? []).filter(call => record(call.trace)?.['node_id'] === nodeId);
  if (invocationId) {
    const selected = calls.find(call => call.id === invocationId);
    if (!selected || !(record(selected.trace)?.['membrane_attempt_kind'] === 'agent_loop_decide' || selected.skill_slug === 'decide_next_v1')) return null;
    const trace = record(selected.trace)!;
    const passage = text(trace['passage_id'], 200), turn = count(trace['membrane_attempt_index']);
    const attributed = !!passage && turn !== null && turn > 0;
    // Keep the actual action associated with this decision when the runtime
    // proves the same node, passage and turn. Later decisions are never shown
    // below the provenance of this selected invocation.
    const actions = attributed ? calls.filter(call => {
      const action = record(call.trace);
      return action?.['membrane_attempt_kind'] === 'agent_loop_act'
        && action['passage_id'] === passage && action['membrane_attempt_index'] === turn;
    }) : [];
    return {
      ...run, skill_invocations: [selected, ...actions],
      checkpoints: attributed ? (run.checkpoints ?? []).filter(checkpoint => checkpoint['node_id'] === nodeId
        && checkpoint['passage_id'] === passage && checkpoint['turn'] === turn) : [],
    };
  }
  if (!calls.some(call => record(call.trace)?.['membrane_attempt_kind'] === 'agent_loop_decide' || call.skill_slug === 'decide_next_v1')) return null;
  return { ...run, skill_invocations: calls, checkpoints: (run.checkpoints ?? []).filter(checkpoint => checkpoint['node_id'] === nodeId) };
}

export function flowResultSupports(view: FlowResultProjection, presentation: FlowResultPresentation, decisions: boolean): boolean {
  if (presentation === 'auto') return !view.empty || !!view.table || decisions;
  if (presentation === 'chart') return !!view.chart;
  if (presentation === 'table') return !!view.table?.columns.length;
  if (presentation === 'metric') return !!view.prediction || view.facts.length > 0;
  if (presentation === 'document') return view.documents.length > 0;
  return decisions;
}
