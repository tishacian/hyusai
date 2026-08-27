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
 *  - `dbt_transform_v1` — several models linked by `ref()` plus a `schema.yml`
 *    of data tests, built by dbt-duckdb on the same managed plane.
 *
 * One workshop authors all three, so the differences are described as data here
 * (`TRANSFORM_ENGINES`) rather than branched in the component: the engine
 * decides the editor language, the dictionary keys and the preview transport,
 * and nothing else. Even the number of files is data — a program is always a
 * list of `TransformFile`, of length one for the single-statement engines.
 *
 * This module mirrors — never replaces — the backend rules in
 * `app/services/tabular_transforms.py`, `app/services/tabular_polars.py` and
 * `app/services/tabular_dbt.py`: the server validates and refuses, the client
 * only pre-reads the bag and projects statuses so the workshop can fail fast
 * and speak the dictionary.
 *
 * Angular-free on purpose so `run-unit.mjs` can exercise it in plain Node.
 */
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import type { TabularColumn } from '@app/shared/ui/data-table.vm';

export const SQL_TRANSFORM_SKILL_SLUG = 'sql_transform_v1';
export const POLARS_TRANSFORM_SKILL_SLUG = 'polars_transform_v1';
export const DBT_TRANSFORM_SKILL_SLUG = 'dbt_transform_v1';

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

/** Mirror of `tabular_dbt.DBT_DEFAULT_MODELS`. */
export const DBT_TRANSFORM_DEFAULT_MODELS: readonly TransformModel[] = [
  {
    name: 'stg_input',
    sql: `-- Staging: rename and cast, one row per source row.
select *
from {{ source('inputs', 'input') }}
`,
  },
  {
    name: 'mart_output',
    sql: `-- Mart: what this node publishes.
select *
from {{ ref('stg_input') }}
`,
  },
];

/** Mirror of `tabular_dbt.DBT_DEFAULT_TESTS_YML`. */
export const DBT_TRANSFORM_DEFAULT_TESTS_YML = `version: 2

models:
  - name: mart_output
    description: The dataset this node publishes.
    # Declare a test and the node refuses to publish a result that fails it.
    # columns:
    #   - name: msisdn
    #     tests: [not_null, unique]
`;

/** The file the dbt tests live in, as dbt itself names it. */
export const DBT_TESTS_FILE_NAME = 'schema.yml';

/** Mirror of `settings.tabular_polars_default_timeout_s`. */
export const POLARS_TIMEOUT_DEFAULT_S = 180;
/** Mirror of `settings.tabular_polars_requirement`: the imposed engine the
 *  environment panel reads out, since a Polars node cannot add libraries. */
export const POLARS_PINNED_REQUIREMENT = 'polars==1.44.0';
/** Mirror of `settings.tabular_dbt_default_timeout_s`: a project compiles
 *  before its first model runs, so it gets a longer default than a script. */
export const DBT_TIMEOUT_DEFAULT_S = 300;
export const TRANSFORM_TIMEOUT_MAX_S = 600;
/** Kept for the call sites that predate the third engine. */
export const POLARS_TIMEOUT_MAX_S = TRANSFORM_TIMEOUT_MAX_S;

/** Mirror of `settings.tabular_dbt_max_models`. */
export const DBT_MAX_MODELS = 12;
/** Mirror of `tabular_dbt._MODEL_NAME_RE`: a model name is a relation name. */
export const DBT_MODEL_NAME_RE = /^[a-z][a-z0-9_]{0,62}$/;

export type TransformEngine = 'sql' | 'polars' | 'dbt';

export interface TransformSourcePin {
  /** Name the program addresses this dataset by. */
  view?: string;
  /** Pin by slug (follows the latest ready version) or by exact id. */
  dataset_slug?: string;
  dataset_id?: string;
}

/** One dbt model file: its relation name and the select it materializes. */
export interface TransformModel {
  name: string;
  sql: string;
}

export interface TransformParams {
  /** The authored program of a single-file engine: a statement, or a script. */
  program: string;
  output_name: string;
  sources: TransformSourcePin[];
  /** Managed engines only: extra libraries the venv must carry. */
  requirements_text: string;
  /** Managed engines only: the run's own time budget. */
  timeout_s: number;
  /** dbt only: the model tree. */
  models: TransformModel[];
  /** dbt only: the `schema.yml` where data tests are declared. */
  tests_yml: string;
  /** dbt only: which model is published as the dataset. */
  output_model: string;
  /**
   * dbt only: other models materialized as sibling datasets of the run.
   *
   * The published model feeds the node's port; these are the staging table
   * worth inspecting or the KPI mart a dashboard reads. Never contains the
   * published model itself.
   */
  output_models: string[];
}

/** Editor language of one file. */
export type TransformFileLanguage = 'sql' | 'python' | 'yaml';

/**
 * One editable file of a transform node.
 *
 * A single-statement engine has exactly one, whose `path` is the params field
 * it is stored under; a dbt node has one per model plus the tests file. The
 * workshop only ever edits `TransformFile`s, which is what lets one editor
 * serve a statement, a script and a project without branching.
 */
export interface TransformFile {
  /** Stable identity for the rail and for `track`. */
  id: string;
  /** What the author reads, and what dbt writes on disk. */
  name: string;
  language: TransformFileLanguage;
  content: string;
  kind: 'program' | 'model' | 'tests';
  /** True for the dbt model this node publishes. */
  published?: boolean;
  /** True for a dbt model also materialized as its own dataset. */
  materialized?: boolean;
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
  programField: 'sql' | 'code' | 'models';
  /** Default `ck-code-editor` language; a multi-file engine overrides it per file. */
  language: TransformFileLanguage;
  defaultProgram: string;
  /** Registered icon name — the engine's identity, in the palette and the head. */
  icon: string;
  /** True when the engine needs a venv, hence an environment panel. */
  managedEnvironment: boolean;
  /**
   * True when the author may add libraries on top of the platform pin.
   *
   * A dbt project legitimately carries packages (dbt-utils and friends); a
   * Polars script gets exactly the pinned engine and nothing else — the
   * environment is imposed, so its panel reads the pin instead of editing it.
   */
  editableEnvironment: boolean;
  /** True when the node carries a file tree rather than one program. */
  multiFile: boolean;
  /** Seconds a run gets when the node declares nothing. */
  defaultTimeoutS: number;
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
    icon: 'database',
    managedEnvironment: false,
    editableEnvironment: false,
    multiFile: false,
    defaultTimeoutS: POLARS_TIMEOUT_DEFAULT_S,
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
    icon: 'code',
    managedEnvironment: true,
    editableEnvironment: false,
    multiFile: false,
    defaultTimeoutS: POLARS_TIMEOUT_DEFAULT_S,
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
  dbt: {
    engine: 'dbt',
    skillSlug: DBT_TRANSFORM_SKILL_SLUG,
    programField: 'models',
    language: 'sql',
    defaultProgram: DBT_TRANSFORM_DEFAULT_MODELS[0].sql,
    icon: 'layers',
    managedEnvironment: true,
    editableEnvironment: true,
    multiFile: true,
    defaultTimeoutS: DBT_TIMEOUT_DEFAULT_S,
    copy: {
      section: 'flow.inspector.section.transform.dbt',
      hint: 'flow.transform.dbt.inspector.hint',
      open: 'flow.transform.dbt.inspector.open',
      openAria: 'flow.transform.dbt.inspector.open.aria',
      program: 'flow.transform.dbt.inspector.project',
      title: 'flow.transform.dbt.workshop.title',
      close: 'flow.transform.dbt.workshop.close',
      editorLabel: 'flow.transform.dbt.editor.label',
      editorEngine: 'flow.transform.dbt.editor.engine',
      editorAria: 'flow.transform.dbt.editor.aria',
      editorPlaceholder: 'flow.transform.dbt.editor.placeholder',
      run: 'flow.transform.dbt.run',
      sourcesHint: 'flow.transform.dbt.sources.hint',
      resultEmpty: 'flow.transform.dbt.result.empty',
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

/** True when the node is a `task` bound to the dbt transform Skill. */
export function isDbtTransformNode(
  node: CanonicalFlowNode | null | undefined,
): boolean {
  return transformEngineOf(node) === 'dbt';
}

/** The `config.params` bag a freshly dropped node carries. */
export function transformDefaultParams(
  engine: TransformEngine,
): Record<string, unknown> {
  const descriptor = TRANSFORM_ENGINES[engine];
  const params: Record<string, unknown> =
    engine === 'dbt'
      ? {
          models: DBT_TRANSFORM_DEFAULT_MODELS.map((model) => ({ ...model })),
          tests_yml: DBT_TRANSFORM_DEFAULT_TESTS_YML,
          output_model: DBT_TRANSFORM_DEFAULT_MODELS.at(-1)?.name ?? '',
          output_models: [],
          output_name: '',
          sources: [],
        }
      : {
          [descriptor.programField]: descriptor.defaultProgram,
          output_name: '',
          sources: [],
        };
  if (descriptor.managedEnvironment) {
    params['requirements_text'] = '';
    params['timeout_s'] = descriptor.defaultTimeoutS;
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

export function clampTransformTimeout(
  value: unknown,
  engine: TransformEngine = 'polars',
): number {
  const fallback = TRANSFORM_ENGINES[engine].defaultTimeoutS;
  const parsed = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return Math.min(Math.round(parsed), TRANSFORM_TIMEOUT_MAX_S);
}

/** Normalise one dbt model entry, dropping the rows that carry nothing. */
function readModel(value: unknown): TransformModel | null {
  if (!isRecord(value)) return null;
  const name = typeof value['name'] === 'string' ? value['name'].trim() : '';
  const sql = typeof value['sql'] === 'string' ? value['sql'] : '';
  if (!name && !sql.trim()) return null;
  return { name, sql };
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
  const models = Array.isArray(params['models'])
    ? params['models'].map(readModel).filter((m): m is TransformModel => m !== null)
    : [];
  const effectiveModels =
    resolved === 'dbt' && models.length === 0
      ? DBT_TRANSFORM_DEFAULT_MODELS.map((model) => ({ ...model }))
      : models;
  const requestedOutput =
    typeof params['output_model'] === 'string' ? params['output_model'].trim() : '';
  const primary =
    requestedOutput || (resolved === 'dbt' ? (effectiveModels.at(-1)?.name ?? '') : '');
  const requestedExtras = Array.isArray(params['output_models'])
    ? params['output_models']
        .map((entry) => (typeof entry === 'string' ? entry.trim() : ''))
        .filter((entry, at, all) => Boolean(entry) && all.indexOf(entry) === at)
        .filter((entry) => entry !== primary)
    : [];
  return {
    program:
      typeof program === 'string'
        ? program
        : resolved === 'dbt'
          ? (effectiveModels.at(-1)?.sql ?? descriptor.defaultProgram)
          : descriptor.defaultProgram,
    output_name:
      typeof params['output_name'] === 'string' ? params['output_name'].trim() : '',
    sources,
    requirements_text:
      typeof params['requirements_text'] === 'string' ? params['requirements_text'] : '',
    timeout_s: clampTransformTimeout(params['timeout_s'], resolved),
    models: effectiveModels,
    tests_yml:
      typeof params['tests_yml'] === 'string'
        ? params['tests_yml']
        : resolved === 'dbt'
          ? DBT_TRANSFORM_DEFAULT_TESTS_YML
          : '',
    // Mirrors `resolve_output_model`: the last model reads as the mart, so a
    // node that never chose one still publishes something.
    output_model: primary,
    output_models: requestedExtras,
  };
}

/**
 * The files the workshop edits, for any engine.
 *
 * Single-statement engines yield one file named after their field; a dbt node
 * yields one per model — flagged with which one is published — plus the tests
 * file, always last so the gate reads as the end of the project.
 */
export function transformFiles(
  params: TransformParams,
  engine: TransformEngine,
): TransformFile[] {
  if (engine !== 'dbt') {
    const descriptor = TRANSFORM_ENGINES[engine];
    return [
      {
        id: descriptor.programField,
        name: engine === 'sql' ? 'transform.sql' : 'transform.py',
        language: descriptor.language,
        content: params.program,
        kind: 'program',
      },
    ];
  }
  const files: TransformFile[] = params.models.map((model, index) => ({
    id: `models.${index}`,
    name: `${model.name || 'model'}.sql`,
    language: 'sql',
    content: model.sql,
    kind: 'model',
    published: model.name === params.output_model,
    materialized: params.output_models.includes(model.name),
  }));
  files.push({
    id: 'tests_yml',
    name: DBT_TESTS_FILE_NAME,
    language: 'yaml',
    content: params.tests_yml,
    kind: 'tests',
  });
  return files;
}

/** The text the inspector summarises: for dbt, the model that gets published. */
export function publishedProgram(
  params: TransformParams,
  engine: TransformEngine,
): string {
  if (engine !== 'dbt') return params.program;
  const published =
    params.models.find((model) => model.name === params.output_model) ??
    params.models.at(-1);
  return published?.sql ?? '';
}

/** A model name free of collisions, for the "add model" gesture. */
export function nextModelName(
  taken: readonly string[],
  base = 'new_model',
): string {
  if (!taken.includes(base)) return base;
  for (let suffix = 2; suffix < 100; suffix += 1) {
    const candidate = `${base}_${suffix}`;
    if (!taken.includes(candidate)) return candidate;
  }
  return `model_${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * The `config.params` patch one workshop gesture implies.
 *
 * dbt gestures are never a single-field write: renaming a model has to follow
 * the `ref()` calls that address it and the `output_model` that publishes it,
 * and deleting one has to hand the publication over. Returning the whole patch
 * keeps that a SINGLE store write, so the author undoes a rename once.
 */
export type TransformParamsPatch = Record<string, unknown>;

/** The params path a file's content is stored under, and the value to write. */
export function fileWrite(
  params: TransformParams,
  engine: TransformEngine,
  fileId: string,
  content: string,
): { path: string; value: unknown } | null {
  if (engine !== 'dbt') {
    return { path: `params.${TRANSFORM_ENGINES[engine].programField}`, value: content };
  }
  if (fileId === 'tests_yml') return { path: 'params.tests_yml', value: content };
  const index = modelIndexOf(fileId);
  if (index === null || index >= params.models.length) return null;
  return {
    path: 'params.models',
    value: params.models.map((model, at) =>
      at === index ? { ...model, sql: content } : { ...model },
    ),
  };
}

/** The model a `models.N` file id addresses, or `null` for anything else. */
export function modelIndexOf(fileId: string): number | null {
  const match = /^models\.(\d+)$/.exec(fileId);
  if (!match) return null;
  return Number(match[1]);
}

/** `{{ ref('from') }}` → `{{ ref('to') }}`, in every model of the project. */
function retargetRefs(sql: string, from: string, to: string): string {
  if (!from || from === to) return sql;
  const quoted = from.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return sql.replace(
    new RegExp(`(ref\\s*\\(\\s*)(['"])${quoted}\\2(\\s*\\))`, 'g'),
    (_match, open: string, quote: string, close: string) =>
      `${open}${quote}${to}${quote}${close}`,
  );
}

/**
 * Rename one model, following its `ref()`s and the publication.
 *
 * The refs move because a dbt project that renames a model without them is
 * broken on the next build, and an author who has to fix that by hand learns
 * that the file rail lies about being a project view.
 */
export function renameDbtModel(
  params: TransformParams,
  index: number,
  requested: string,
): TransformParamsPatch {
  const previous = params.models[index]?.name ?? '';
  const name = requested.trim();
  if (!name || name === previous) return {};
  const models = params.models.map((model, at) =>
    at === index
      ? { name, sql: model.sql }
      : { name: model.name, sql: retargetRefs(model.sql, previous, name) },
  );
  return {
    models,
    output_model: params.output_model === previous ? name : params.output_model,
    output_models: params.output_models.map((entry) =>
      entry === previous ? name : entry,
    ),
  };
}

/** Append an empty model that already selects from the published one. */
export function addDbtModel(params: TransformParams): TransformParamsPatch {
  const taken = params.models.map((model) => model.name);
  const name = nextModelName(taken);
  const upstream = params.output_model || params.models.at(-1)?.name || '';
  const sql = upstream
    ? `select *\nfrom {{ ref('${upstream}') }}\n`
    : `select *\nfrom {{ source('inputs', 'input') }}\n`;
  return { models: [...params.models.map((model) => ({ ...model })), { name, sql }] };
}

/**
 * Drop one model, handing the publication to the last one left.
 *
 * The refs of the deleted model are NOT rewritten: a dangling `ref()` is what
 * makes the build refuse, and that refusal is more honest than silently
 * re-pointing the author's model at something they did not choose.
 */
export function removeDbtModel(
  params: TransformParams,
  index: number,
): TransformParamsPatch {
  if (params.models.length <= 1 || index < 0 || index >= params.models.length) {
    return {};
  }
  const removed = params.models[index].name;
  const models = params.models
    .filter((_model, at) => at !== index)
    .map((model) => ({ ...model }));
  const publication =
    params.output_model === removed
      ? (models.at(-1)?.name ?? '')
      : params.output_model;
  return {
    models,
    output_model: publication,
    output_models: params.output_models.filter(
      (entry) => entry !== removed && entry !== publication,
    ),
  };
}

/** Publish another model as the node's dataset. */
export function publishDbtModel(
  params: TransformParams,
  name: string,
): TransformParamsPatch {
  if (!params.models.some((model) => model.name === name)) return {};
  return {
    output_model: name,
    // The port's model is not an extra: promoting one that was ticked as a
    // sibling dataset absorbs the tick rather than versioning it twice.
    output_models: params.output_models.filter((entry) => entry !== name),
  };
}

/** Tick or untick one model as a sibling dataset of the run. */
export function toggleDbtMaterialize(
  params: TransformParams,
  name: string,
): TransformParamsPatch {
  if (!params.models.some((model) => model.name === name)) return {};
  if (name === params.output_model) return {};
  return {
    output_models: params.output_models.includes(name)
      ? params.output_models.filter((entry) => entry !== name)
      : [...params.output_models, name],
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
  const comment = engine === 'polars' ? '#' : '--';
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
  /**
   * Where in the statement the engine stopped, when it says.
   *
   * duckdb reports a line and a caret column for every parser, binder, catalog
   * and conversion error. Carrying it here is what lets the workshop put the
   * cursor on the offending token instead of leaving the author to count lines
   * under a sentence that names a column but not its place.
   */
  position?: { line: number; column: number };
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

/**
 * Client-side pre-check of a whole node, whatever its shape.
 *
 * For dbt this is the only place a preflight can live: a project is refused for
 * what its file *set* looks like — a duplicate relation name, a published model
 * that is not in the tree — not for the contents of the file being edited.
 */
export function preflightTransform(
  params: TransformParams,
  engine: TransformEngine,
): TransformFailure | null {
  if (engine !== 'dbt') return preflightProgram(params.program, engine);
  const written = params.models.filter((model) => model.sql.trim());
  if (written.length === 0) {
    return { key: 'flow.transform.error.DBT_MODELS_REQUIRED' };
  }
  if (params.models.length > DBT_MAX_MODELS) {
    return { key: 'flow.transform.error.DBT_TOO_MANY_MODELS' };
  }
  const seen = new Set<string>();
  for (const model of params.models) {
    if (!model.name && !model.sql.trim()) continue;
    if (!DBT_MODEL_NAME_RE.test(model.name)) {
      return {
        key: 'flow.transform.error.DBT_MODEL_NAME_INVALID',
        detail: model.name || undefined,
      };
    }
    if (seen.has(model.name)) {
      return {
        key: 'flow.transform.error.DBT_MODEL_NAME_DUPLICATE',
        detail: model.name,
      };
    }
    seen.add(model.name);
    if (!model.sql.trim()) {
      return { key: 'flow.transform.error.DBT_MODEL_EMPTY', detail: model.name };
    }
  }
  if (params.output_model && !seen.has(params.output_model)) {
    return {
      key: 'flow.transform.error.DBT_OUTPUT_MODEL_MISSING',
      detail: params.output_model,
    };
  }
  for (const extra of params.output_models) {
    if (!seen.has(extra)) {
      return {
        key: 'flow.transform.error.DBT_OUTPUT_MODEL_MISSING',
        detail: extra,
      };
    }
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
  'DBT_MODELS_REQUIRED',
  'DBT_MODEL_NAME_INVALID',
  'DBT_MODEL_NAME_DUPLICATE',
  'DBT_MODEL_EMPTY',
  'DBT_MODEL_TOO_LARGE',
  'DBT_MODEL_SHADOWS_SOURCE',
  'DBT_TOO_MANY_MODELS',
  'DBT_TESTS_TOO_LARGE',
  'DBT_OUTPUT_MODEL_MISSING',
  'DBT_EXECUTION_DISABLED',
  'DBT_BUILD_FAILED',
  'DBT_TESTS_FAILED',
  'DBT_RESULT_NO_COLUMNS',
  'DBT_RESULT_UNWRITABLE',
  'DBT_RESULT_MISSING',
  'DBT_RESULT_TOO_LARGE',
  'DBT_HARNESS_ERROR',
  'DBT_TIMEOUT',
  'TRANSFORM_NO_INPUT',
  'TRANSFORM_WORKSPACE_REQUIRED',
  'DATASET_NOT_FOUND',
  'DATASET_NOT_READY',
  'TABULAR_DISABLED',
];

/**
 * The phases a preview passes through, in order.
 *
 * These are `RecipeExecution` statuses, which is why they are named the way the
 * backend names them. `env_building` is the one that matters to a reader: a
 * first Polars or dbt run in a workspace builds a venv, which takes far longer
 * than the query itself, and a reader who is not told that concludes the engine
 * is slow rather than that it is warming up.
 */
export const TRANSFORM_PHASES: readonly string[] = ['queued', 'env_building', 'running'];

/** One line of the preview check-list. */
export interface TransformPhase {
  phase: string;
  key: string;
  state: 'done' | 'active' | 'todo';
}

/**
 * A preview's phases as a check-list, with what is behind it ticked off.
 *
 * SQL never builds an environment — duckdb runs in the worker — so that line is
 * dropped for it rather than sitting there permanently un-ticked, which would
 * read as a step that is stuck.
 *
 * A phase the row reports that is not one of these (a terminal status, on the
 * poll that settles it) ticks the whole list: the run is past all of them, and
 * the result or the refusal below says how it went.
 */
export function transformChecklist(
  engine: TransformEngine,
  phase: string | null | undefined,
): TransformPhase[] {
  const phases = TRANSFORM_PHASES.filter(
    (name) => name !== 'env_building' || engine !== 'sql',
  );
  const current = (phase ?? '').trim();
  const at = phases.includes(current) ? phases.indexOf(current) : phases.length;
  return phases.map((name, index) => ({
    phase: name,
    key: `flow.transform.phase.${name}`,
    state: index < at ? 'done' : index === at ? 'active' : 'todo',
  }));
}

/** Refusals whose own words ARE the information the author needs. */
const VERBATIM_DETAIL_CODES: readonly string[] = [
  'SQL_EXECUTION_FAILED',
  'POLARS_SCRIPT_RAISED',
  'POLARS_HARNESS_ERROR',
  'POLARS_RESULT_NOT_TABULAR',
  'POLARS_ENV_NOT_READY',
  'DBT_BUILD_FAILED',
  'DBT_TESTS_FAILED',
  'DBT_HARNESS_ERROR',
  'DBT_MODEL_NAME_INVALID',
  'DBT_MODEL_NAME_DUPLICATE',
  'DBT_MODEL_SHADOWS_SOURCE',
  'DBT_OUTPUT_MODEL_MISSING',
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
  position?: unknown,
): TransformFailure {
  const normalized = (code ?? '').trim().toUpperCase();
  const detail = (message ?? '').trim() || undefined;
  const at = transformErrorPosition(position);
  if (normalized && TRANSFORM_ERROR_CODES.includes(normalized)) {
    return {
      key: `flow.transform.error.${normalized}`,
      detail: VERBATIM_DETAIL_CODES.includes(normalized) ? detail : undefined,
      ...(at ? { position: at } : {}),
    };
  }
  return { key: 'flow.transform.error.unknown', detail, ...(at ? { position: at } : {}) };
}

/**
 * The `{line, column}` an engine reported, or nothing if it reported no place.
 *
 * Validated rather than trusted: a coordinate is used to move a cursor, and a
 * zero or a string would either throw or silently jump to the top of the
 * document, which reads as the editor losing the author's place.
 */
export function transformErrorPosition(
  raw: unknown,
): { line: number; column: number } | null {
  if (!raw || typeof raw !== 'object') return null;
  const { line, column } = raw as { line?: unknown; column?: unknown };
  if (typeof line !== 'number' || !Number.isFinite(line) || line < 1) return null;
  const at = typeof column === 'number' && Number.isFinite(column) && column >= 1 ? column : 1;
  return { line: Math.floor(line), column: Math.floor(at) };
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
  if (engine === 'dbt') {
    const projection = columns.length ? columns.join(',\n  ') : '*';
    // `source()` rather than the bare relation: a dbt project's whole value is
    // that its inputs are declared, so the starter teaches the idiom.
    return `select\n  ${projection}\nfrom {{ source('inputs', '${source.view}') }}\n`;
  }
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

/** One dbt node's verdict, as the harness summary describes it. */
export interface DbtNodeResult {
  kind: 'model' | 'test';
  name: string;
  status: string;
  failures: number;
  duration_ms?: number;
  message?: string;
}

export interface DbtReport {
  nodes: DbtNodeResult[];
  models_total: number;
  tests_total: number;
  tests_failed: number;
  selected: string;
}

/**
 * Read the dbt verdict off an execution's `output_json`.
 *
 * Present on a success (`dbt_preview`, `dbt_transform`) AND on a refusal
 * (`dbt_failed`), because the whole point of the engine is that a build which
 * failed its data tests still has something to show: which test, how many rows.
 */
export function dbtReportFrom(output: unknown): DbtReport | null {
  if (!isRecord(output)) return null;
  const raw = output['dbt'];
  if (!isRecord(raw)) return null;
  const nodes = Array.isArray(raw['nodes']) ? raw['nodes'] : [];
  return {
    nodes: nodes.filter(isRecord).map((node) => ({
      kind: node['kind'] === 'test' ? 'test' : 'model',
      name: typeof node['name'] === 'string' ? node['name'] : '',
      status: typeof node['status'] === 'string' ? node['status'] : '',
      failures: Number(node['failures'] ?? 0) || 0,
      duration_ms: Number(node['duration_ms'] ?? 0) || 0,
      message: typeof node['message'] === 'string' ? node['message'] : '',
    })),
    models_total: Number(raw['models_total'] ?? 0) || 0,
    tests_total: Number(raw['tests_total'] ?? 0) || 0,
    tests_failed: Number(raw['tests_failed'] ?? 0) || 0,
    selected: typeof raw['selected'] === 'string' ? raw['selected'] : '',
  };
}

/** True when a dbt node result counts as passing. */
export function dbtNodePassed(node: DbtNodeResult): boolean {
  return node.status === 'pass' || node.status === 'success';
}
