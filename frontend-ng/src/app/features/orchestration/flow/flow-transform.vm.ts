/**
 * Tabular transform nodes — pure view-model helpers.
 *
 * A transform node is an ordinary `task` node bound to a seeded transform
 * Skill. Two engines exist today and they share everything that matters: the
 * authored program, the output name and the pinned inputs live under
 * `config.params` and are versioned with the flow, exactly like a Python
 * recipe's script.
 *
 *  - `sql_transform_v1` — a read-only duckdb statement, answered inline.
 *  - `polars_transform_v1` — an author-written `transform(inputs)` function,
 *    run on a managed venv interpreter by the worker plane.
 *
 * One workshop authors both, so the differences are described as data here
 * (`TRANSFORM_ENGINES`) rather than branched in the component: the engine
 * decides the editor language, the dictionary keys and the preview transport,
 * and nothing else.
 *
 * This module mirrors — never replaces — the backend rules in
 * `app/services/tabular_transforms.py` and `app/services/tabular_polars.py`:
 * the server validates and refuses, the client only pre-reads the bag and
 * projects statuses so the workshop can fail fast and speak the dictionary.
 *
 * Angular-free on purpose so `run-unit.mjs` can exercise it in plain Node.
 */
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import type { TabularColumn } from '@app/shared/ui/data-table.vm';

export const SQL_TRANSFORM_SKILL_SLUG = 'sql_transform_v1';
export const POLARS_TRANSFORM_SKILL_SLUG = 'polars_transform_v1';

/** Mirror of `settings.tabular_sql_max_chars`. */
export const SQL_MAX_CHARS = 20_000;
/** Mirror of `settings.recipe_execution_max_code_bytes`. */
export const TRANSFORM_MAX_CODE_CHARS = 200_000;

/** The starter statement, so a dropped node runs before it is edited. */
export const SQL_TRANSFORM_DEFAULT_SQL = `-- 'input' is the first connected (or pinned) dataset.
SELECT *
FROM input
LIMIT 100
`;

/** Mirror of `tabular_polars.POLARS_DEFAULT_CODE`. */
export const POLARS_TRANSFORM_DEFAULT_CODE = `import polars as pl


def transform(inputs: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """'inputs' maps every addressable source name to an eager frame."""
    return inputs["input"]
`;

/** Mirror of `settings.tabular_polars_default_timeout_s`. */
export const POLARS_TIMEOUT_DEFAULT_S = 180;
export const POLARS_TIMEOUT_MAX_S = 600;

export type TransformEngine = 'sql' | 'polars';

export interface TransformSourcePin {
  /** Name the program addresses this dataset by. */
  view?: string;
  /** Pin by slug (follows the latest ready version) or by exact id. */
  dataset_slug?: string;
  dataset_id?: string;
}

export interface TransformParams {
  /** The authored program: a statement for SQL, a script for Polars. */
  program: string;
  output_name: string;
  sources: TransformSourcePin[];
  /** Polars only: extra libraries the venv must carry. */
  requirements_text: string;
  /** Polars only: the run's own time budget. */
  timeout_s: number;
}

/** One addressable table, as the preview endpoints describe it. */
export interface TransformSourceCatalogEntry {
  view: string;
  aliases: string[];
  dataset_id: string;
  name: string;
  rows: number;
  columns: TabularColumn[];
}

/**
 * Everything that differs between two engines, in one place.
 *
 * `copy` holds dictionary KEYS, not sentences: the workshop is one component
 * speaking two vocabularies, and a missing key must fail the i18n parity check
 * at build time rather than render an engine's label in the other's words.
 */
export interface TransformEngineDescriptor {
  engine: TransformEngine;
  skillSlug: string;
  /** `config.params` field the authored program lives in. */
  programField: 'sql' | 'code';
  /** `ck-code-editor` language. */
  language: 'sql' | 'python';
  defaultProgram: string;
  /** True when the engine needs a venv, hence a libraries panel. */
  managedEnvironment: boolean;
  copy: {
    section: string;
    hint: string;
    open: string;
    openAria: string;
    program: string;
    title: string;
    close: string;
    editorLabel: string;
    editorEngine: string;
    editorAria: string;
    editorPlaceholder: string;
    run: string;
    sourcesHint: string;
    resultEmpty: string;
  };
}

export const TRANSFORM_ENGINES: Readonly<
  Record<TransformEngine, TransformEngineDescriptor>
> = {
  sql: {
    engine: 'sql',
    skillSlug: SQL_TRANSFORM_SKILL_SLUG,
    programField: 'sql',
    language: 'sql',
    defaultProgram: SQL_TRANSFORM_DEFAULT_SQL,
    managedEnvironment: false,
    copy: {
      section: 'flow.inspector.section.transform',
      hint: 'flow.transform.inspector.hint',
      open: 'flow.transform.inspector.open',
      openAria: 'flow.transform.inspector.open.aria',
      program: 'flow.transform.inspector.statement',
      title: 'flow.transform.workshop.title',
      close: 'flow.transform.workshop.close',
      editorLabel: 'flow.transform.editor.label',
      editorEngine: 'flow.transform.editor.engine',
      editorAria: 'flow.transform.editor.aria',
      editorPlaceholder: 'flow.transform.editor.placeholder',
      run: 'flow.transform.run',
      sourcesHint: 'flow.transform.sources.hint',
      resultEmpty: 'flow.transform.result.empty',
    },
  },
  polars: {
    engine: 'polars',
    skillSlug: POLARS_TRANSFORM_SKILL_SLUG,
    programField: 'code',
    language: 'python',
    defaultProgram: POLARS_TRANSFORM_DEFAULT_CODE,
    managedEnvironment: true,
    copy: {
      section: 'flow.inspector.section.transform.polars',
      hint: 'flow.transform.polars.inspector.hint',
      open: 'flow.transform.polars.inspector.open',
      openAria: 'flow.transform.polars.inspector.open.aria',
      program: 'flow.transform.polars.inspector.script',
      title: 'flow.transform.polars.workshop.title',
      close: 'flow.transform.polars.workshop.close',
      editorLabel: 'flow.transform.polars.editor.label',
      editorEngine: 'flow.transform.polars.editor.engine',
      editorAria: 'flow.transform.polars.editor.aria',
      editorPlaceholder: 'flow.transform.polars.editor.placeholder',
      run: 'flow.transform.polars.run',
      sourcesHint: 'flow.transform.polars.sources.hint',
      resultEmpty: 'flow.transform.polars.result.empty',
    },
  },
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** Which engine a node runs on, or `null` when it is not a transform node. */
export function transformEngineOf(
  node: CanonicalFlowNode | null | undefined,
): TransformEngine | null {
  if (!node || (node.kind ?? 'task') !== 'task') return null;
  const config = isRecord(node.config) ? node.config : {};
  const slug = config['skill_slug'];
  for (const descriptor of Object.values(TRANSFORM_ENGINES)) {
    if (slug === descriptor.skillSlug) return descriptor.engine;
  }
  return null;
}

/** True when the node is a `task` bound to any transform Skill. */
export function isTransformNode(node: CanonicalFlowNode | null | undefined): boolean {
  return transformEngineOf(node) !== null;
}

/** True when the node is a `task` bound to the SQL transform Skill. */
export function isSqlTransformNode(node: CanonicalFlowNode | null | undefined): boolean {
  return transformEngineOf(node) === 'sql';
}

/** True when the node is a `task` bound to the Polars transform Skill. */
export function isPolarsTransformNode(
  node: CanonicalFlowNode | null | undefined,
): boolean {
  return transformEngineOf(node) === 'polars';
}

/** The `config.params` bag a freshly dropped node carries. */
export function transformDefaultParams(
  engine: TransformEngine,
): Record<string, unknown> {
  const descriptor = TRANSFORM_ENGINES[engine];
  const params: Record<string, unknown> = {
    [descriptor.programField]: descriptor.defaultProgram,
    output_name: '',
    sources: [],
  };
  if (descriptor.managedEnvironment) {
    params['requirements_text'] = '';
    params['timeout_s'] = POLARS_TIMEOUT_DEFAULT_S;
  }
  return params;
}

/** Normalise one pin, dropping the entries that reference nothing. */
function readSourcePin(value: unknown): TransformSourcePin | null {
  if (!isRecord(value)) return null;
  const pin: TransformSourcePin = {};
  const view = value['view'];
  if (typeof view === 'string' && view.trim()) pin.view = view.trim();
  const id = value['dataset_id'];
  if (typeof id === 'string' && id.trim()) pin.dataset_id = id.trim();
  const slug = value['dataset_slug'] ?? value['slug'];
  if (typeof slug === 'string' && slug.trim()) pin.dataset_slug = slug.trim();
  return pin.dataset_id || pin.dataset_slug ? pin : null;
}

export function clampTransformTimeout(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return POLARS_TIMEOUT_DEFAULT_S;
  return Math.min(Math.round(parsed), POLARS_TIMEOUT_MAX_S);
}

/** Read the transform params off a node, with defaults for anything unset. */
export function readTransformParams(
  node: CanonicalFlowNode | null | undefined,
  engine?: TransformEngine | null,
): TransformParams {
  const resolved = engine ?? transformEngineOf(node) ?? 'sql';
  const descriptor = TRANSFORM_ENGINES[resolved];
  const config = node && isRecord(node.config) ? node.config : {};
  const params = isRecord(config['params']) ? config['params'] : {};
  const program = params[descriptor.programField];
  const sources = Array.isArray(params['sources'])
    ? params['sources']
        .map(readSourcePin)
        .filter((pin): pin is TransformSourcePin => pin !== null)
    : [];
  return {
    program: typeof program === 'string' ? program : descriptor.defaultProgram,
    output_name:
      typeof params['output_name'] === 'string' ? params['output_name'].trim() : '',
    sources,
    requirements_text:
      typeof params['requirements_text'] === 'string' ? params['requirements_text'] : '',
    timeout_s: clampTransformTimeout(params['timeout_s']),
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

/** One-line summary of the authored program for the inspector. */
export function programSummary(program: string, engine: TransformEngine): string {
  const comment = engine === 'sql' ? '--' : '#';
  const line = program
    .split(/\r?\n/)
    .map((raw) => raw.trim())
    .find((raw) => raw.length > 0 && !raw.startsWith(comment));
  return (line ?? '').replace(/\s+/g, ' ').slice(0, 80);
}

/** Backwards-compatible alias kept for the SQL call sites. */
export function sqlSummary(sql: string): string {
  return programSummary(sql, 'sql');
}

/** Line count of the authored program (empty program → 0). */
export function programLineCount(program: string): number {
  if (!program.trim()) return 0;
  return program.replace(/\n$/, '').split('\n').length;
}

export interface TransformFailure {
  /** Dictionary key for the human sentence. */
  key: string;
  /** The engine's own words, when they are the actionable part. */
  detail?: string;
}

/**
 * Client-side pre-check, kept deliberately narrower than the server's: only
 * the refusals an author hits by habit are worth blocking a round-trip for
 * (an empty editor, a trailing second statement, a missing entry point).
 * Everything else — forbidden keywords, unsafe functions, engine errors — is
 * the server's call, and its coded answer is what the workshop renders.
 */
export function preflightProgram(
  program: string,
  engine: TransformEngine,
): TransformFailure | null {
  const text = program.trim();
  if (engine === 'polars') {
    if (!text) return { key: 'flow.transform.error.POLARS_CODE_REQUIRED' };
    if (text.length > TRANSFORM_MAX_CODE_CHARS) {
      return { key: 'flow.transform.error.POLARS_CODE_TOO_LARGE' };
    }
    if (!/^[ \t]*def[ \t]+transform[ \t]*\(/m.test(text)) {
      return { key: 'flow.transform.error.POLARS_TRANSFORM_MISSING' };
    }
    return null;
  }
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

/** Backwards-compatible alias kept for the SQL call sites. */
export function preflightSql(sql: string): TransformFailure | null {
  return preflightProgram(sql, 'sql');
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
  'POLARS_CODE_REQUIRED',
  'POLARS_CODE_TOO_LARGE',
  'POLARS_EXECUTION_DISABLED',
  'POLARS_ENV_NOT_READY',
  'POLARS_SCRIPT_RAISED',
  'POLARS_TRANSFORM_MISSING',
  'POLARS_RESULT_NOT_TABULAR',
  'POLARS_RESULT_UNWRITABLE',
  'POLARS_RESULT_MISSING',
  'POLARS_RESULT_TOO_LARGE',
  'POLARS_HARNESS_ERROR',
  'POLARS_TIMEOUT',
  'TRANSFORM_NO_INPUT',
  'TRANSFORM_WORKSPACE_REQUIRED',
  'DATASET_NOT_FOUND',
  'DATASET_NOT_READY',
  'TABULAR_DISABLED',
];

/** Refusals whose own words ARE the information the author needs. */
const VERBATIM_DETAIL_CODES: readonly string[] = [
  'SQL_EXECUTION_FAILED',
  'POLARS_SCRIPT_RAISED',
  'POLARS_HARNESS_ERROR',
  'POLARS_RESULT_NOT_TABULAR',
  'POLARS_ENV_NOT_READY',
];

/**
 * Project a backend refusal into a translated sentence plus its detail.
 *
 * Coded refusals get a sentence the author can act on; a few keep the engine's
 * own line, because "Referenced column 'churn' not found" or
 * "KeyError: 'arpu_v2'" IS the information. An unrecognised code degrades to a
 * generic sentence with the server's message as the detail rather than showing
 * a raw code.
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
      detail: VERBATIM_DETAIL_CODES.includes(normalized) ? detail : undefined,
    };
  }
  return { key: 'flow.transform.error.unknown', detail };
}

/**
 * Split a worker-side execution error into its code and its detail.
 *
 * The Polars plane settles a `RecipeExecution` row whose `error` is
 * `"CODE: the author's own last line"`, because a queued run has no HTTP
 * response to carry a structured payload. Parsing it here keeps the workshop's
 * rendering identical whether the refusal came back inline or through a row.
 */
export function transformFailureFromExecution(
  error: string | null | undefined,
): TransformFailure {
  const text = (error ?? '').trim();
  if (!text) return { key: 'flow.transform.error.unknown' };
  const separator = text.indexOf(':');
  const code = separator > 0 ? text.slice(0, separator).trim() : text;
  const detail = separator > 0 ? text.slice(separator + 1).trim() : '';
  return transformFailure(code, detail || text);
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

/** A ready-to-run starter program over one source, for the empty state. */
export function starterProgramFor(
  source: TransformSourceCatalogEntry,
  engine: TransformEngine,
): string {
  const columns = source.columns.slice(0, 6).map((column) => column.name);
  if (engine === 'polars') {
    const projection = columns.length
      ? columns.map((name) => `"${name}"`).join(', ')
      : 'pl.all()';
    return [
      'import polars as pl',
      '',
      '',
      'def transform(inputs: dict[str, pl.DataFrame]) -> pl.DataFrame:',
      `    frame = inputs["${source.view}"]`,
      `    return frame.select(${projection})`,
      '',
    ].join('\n');
  }
  const projection = columns.length ? columns.join(',\n  ') : '*';
  return `SELECT\n  ${projection}\nFROM ${source.view}\nLIMIT 100\n`;
}

/** Backwards-compatible alias kept for the SQL call sites. */
export function starterSqlFor(source: TransformSourceCatalogEntry): string {
  return starterProgramFor(source, 'sql');
}

/** Default output name derived from the node label, so a run is never unnamed. */
export function defaultOutputName(label: string | undefined, fallback: string): string {
  const cleaned = (label ?? '').trim();
  return cleaned || fallback;
}

/**
 * One line per declared library, comments and blanks dropped — what the author
 * is about to install, so an accidental `-r requirements.txt` is visible before
 * the env is fingerprinted. Mirrors `previewRequirements` in the recipe vm.
 */
export function requirementLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && !line.startsWith('#'));
}
