/**
 * Tabular transform nodes — pure view-model helpers.
 *
 * A transform node is an ordinary `task` node bound to a seeded transform
 * Skill (`sql_transform_v1` today, Polars and dbt next); the statement, the
 * output name and the pinned inputs live under `config.params` and are
 * versioned with the flow, exactly like a Python recipe's script.
 *
 * This module mirrors — never replaces — the backend rules in
 * `app/services/tabular_transforms.py`: the server validates and refuses, the
 * client only pre-reads the bag and projects statuses so the workshop can fail
 * fast and speak the dictionary.
 *
 * Angular-free on purpose so `run-unit.mjs` can exercise it in plain Node.
 */
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import type { TabularColumn } from '@app/shared/ui/data-table.vm';

export const SQL_TRANSFORM_SKILL_SLUG = 'sql_transform_v1';

/** Mirror of `settings.tabular_sql_max_chars`. */
export const SQL_MAX_CHARS = 20_000;

/** The starter statement, so a dropped node runs before it is edited. */
export const SQL_TRANSFORM_DEFAULT_SQL = `-- 'input' is the first connected (or pinned) dataset.
SELECT *
FROM input
LIMIT 100
`;

export interface SqlTransformSourcePin {
  /** Name the statement addresses this dataset by. */
  view?: string;
  /** Pin by slug (follows the latest ready version) or by exact id. */
  dataset_slug?: string;
  dataset_id?: string;
}

export interface SqlTransformParams {
  sql: string;
  output_name: string;
  sources: SqlTransformSourcePin[];
}

/** One addressable table, as `/datasets/sql-preview` describes it. */
export interface TransformSourceCatalogEntry {
  view: string;
  aliases: string[];
  dataset_id: string;
  name: string;
  rows: number;
  columns: TabularColumn[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** True when the node is a `task` bound to the SQL transform Skill. */
export function isSqlTransformNode(node: CanonicalFlowNode | null | undefined): boolean {
  if (!node || (node.kind ?? 'task') !== 'task') return false;
  const config = isRecord(node.config) ? node.config : {};
  return config['skill_slug'] === SQL_TRANSFORM_SKILL_SLUG;
}

export function sqlTransformDefaultParams(): SqlTransformParams {
  return { sql: SQL_TRANSFORM_DEFAULT_SQL, output_name: '', sources: [] };
}

/** Normalise one pin, dropping the entries that reference nothing. */
function readSourcePin(value: unknown): SqlTransformSourcePin | null {
  if (!isRecord(value)) return null;
  const pin: SqlTransformSourcePin = {};
  const view = value['view'];
  if (typeof view === 'string' && view.trim()) pin.view = view.trim();
  const id = value['dataset_id'];
  if (typeof id === 'string' && id.trim()) pin.dataset_id = id.trim();
  const slug = value['dataset_slug'] ?? value['slug'];
  if (typeof slug === 'string' && slug.trim()) pin.dataset_slug = slug.trim();
  return pin.dataset_id || pin.dataset_slug ? pin : null;
}

/** Read the transform params off a node, with defaults for anything unset. */
export function readSqlTransformParams(
  node: CanonicalFlowNode | null | undefined,
): SqlTransformParams {
  const defaults = sqlTransformDefaultParams();
  const config = node && isRecord(node.config) ? node.config : {};
  const params = isRecord(config['params']) ? config['params'] : {};
  const sources = Array.isArray(params['sources'])
    ? params['sources']
        .map(readSourcePin)
        .filter((pin): pin is SqlTransformSourcePin => pin !== null)
    : defaults.sources;
  return {
    sql: typeof params['sql'] === 'string' ? params['sql'] : defaults.sql,
    output_name:
      typeof params['output_name'] === 'string' ? params['output_name'].trim() : '',
    sources,
  };
}

/**
 * A duckdb-safe view name derived from a dataset name — the client mirror of
 * `tabular_transforms.view_name_for`, used to pre-fill a pin's view so the
 * author sees the name they will type before the first preview call.
 */
export function transformViewName(label: string, taken: readonly string[] = []): string {
  const ascii = label
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase();
  let candidate = ascii.replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 62);
  if (!candidate || !/^[a-z_]/.test(candidate)) candidate = `t_${candidate}`.slice(0, 62);
  if (!taken.includes(candidate)) return candidate;
  for (let suffix = 2; suffix < 100; suffix += 1) {
    const alternative = `${candidate}_${suffix}`.slice(0, 63);
    if (!taken.includes(alternative)) return alternative;
  }
  return `input_${Math.random().toString(36).slice(2, 8)}`;
}

/** One-line summary of the statement for the inspector (first SQL line). */
export function sqlSummary(sql: string): string {
  const line = sql
    .split(/\r?\n/)
    .map((raw) => raw.trim())
    .find((raw) => raw.length > 0 && !raw.startsWith('--'));
  return (line ?? '').replace(/\s+/g, ' ').slice(0, 80);
}

/** Line count of the authored statement (empty statement → 0). */
export function sqlLineCount(sql: string): number {
  if (!sql.trim()) return 0;
  return sql.replace(/\n$/, '').split('\n').length;
}

/**
 * Client-side pre-check, kept deliberately narrower than the server's: only
 * the two refusals an author hits by habit (an empty editor, a trailing
 * second statement) are worth blocking a round-trip for. Everything else —
 * forbidden keywords, unsafe functions, engine errors — is the server's call,
 * and its coded answer is what the workshop renders.
 */
export function preflightSql(sql: string): TransformFailure | null {
  const text = sql.trim();
  if (!text) return { key: 'flow.transform.error.SQL_EMPTY' };
  if (text.length > SQL_MAX_CHARS) return { key: 'flow.transform.error.SQL_TOO_LONG' };
  const scrubbed = text
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/--[^\n]*/g, ' ')
    .replace(/'(?:''|[^'])*'/g, "''");
  if (scrubbed.split(';').filter((part) => part.trim()).length > 1) {
    return { key: 'flow.transform.error.SQL_MULTIPLE_STATEMENTS' };
  }
  return null;
}

/** The refusal codes the workshop translates; anything else falls back. */
export const TRANSFORM_ERROR_CODES: readonly string[] = [
  'SQL_EMPTY',
  'SQL_TOO_LONG',
  'SQL_MULTIPLE_STATEMENTS',
  'SQL_FORBIDDEN_KEYWORD',
  'SQL_NOT_READ_ONLY',
  'SQL_FORBIDDEN_FUNCTION',
  'SQL_EXECUTION_FAILED',
  'SQL_RESULT_TOO_LARGE',
  'SQL_NO_COLUMNS',
  'TRANSFORM_NO_INPUT',
  'TRANSFORM_WORKSPACE_REQUIRED',
  'DATASET_NOT_FOUND',
  'DATASET_NOT_READY',
  'TABULAR_DISABLED',
];

export interface TransformFailure {
  /** Dictionary key for the human sentence. */
  key: string;
  /** The engine's own words, when they are the actionable part. */
  detail?: string;
}

/**
 * Project a backend refusal into a translated sentence plus its detail.
 *
 * Coded refusals get a sentence the author can act on; `SQL_EXECUTION_FAILED`
 * keeps the engine line, because "Referenced column 'churn' not found" IS the
 * information. An unrecognised code degrades to a generic sentence with the
 * server's message as the detail rather than showing a raw code.
 */
export function transformFailure(
  code: string | null | undefined,
  message?: string | null,
): TransformFailure {
  const normalized = (code ?? '').trim().toUpperCase();
  const detail = (message ?? '').trim() || undefined;
  if (normalized && TRANSFORM_ERROR_CODES.includes(normalized)) {
    return {
      key: `flow.transform.error.${normalized}`,
      detail: normalized === 'SQL_EXECUTION_FAILED' ? detail : undefined,
    };
  }
  return { key: 'flow.transform.error.unknown', detail };
}

/**
 * Editor completion schema: every name the statement can address mapped to its
 * columns. Aliases (`input`, `input_1`) are included so completing on `input.`
 * offers the same columns as completing on the dataset's own view name.
 */
export function editorSqlSchema(
  sources: readonly TransformSourceCatalogEntry[],
): Record<string, string[]> {
  const schema: Record<string, string[]> = {};
  for (const source of sources) {
    const columns = source.columns.map((column) => column.name);
    schema[source.view] = columns;
    for (const alias of source.aliases) schema[alias] = columns;
  }
  return schema;
}

/** A ready-to-run starter statement over one source, for the empty state. */
export function starterSqlFor(source: TransformSourceCatalogEntry): string {
  const columns = source.columns.slice(0, 6).map((column) => column.name);
  const projection = columns.length ? columns.join(',\n  ') : '*';
  return `SELECT\n  ${projection}\nFROM ${source.view}\nLIMIT 100\n`;
}

/** Default output name derived from the node label, so a run is never unnamed. */
export function defaultOutputName(label: string | undefined, fallback: string): string {
  const cleaned = (label ?? '').trim();
  return cleaned || fallback;
}
