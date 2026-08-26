import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import {
  DBT_MAX_MODELS,
  DBT_TRANSFORM_DEFAULT_MODELS,
  DBT_TRANSFORM_DEFAULT_TESTS_YML,
  DBT_TRANSFORM_SKILL_SLUG,
  POLARS_TRANSFORM_DEFAULT_CODE,
  POLARS_TRANSFORM_SKILL_SLUG,
  SQL_MAX_CHARS,
  SQL_TRANSFORM_DEFAULT_SQL,
  SQL_TRANSFORM_SKILL_SLUG,
  TRANSFORM_ENGINES,
  TRANSFORM_ERROR_CODES,
  addDbtModel,
  clampTransformTimeout,
  dbtNodePassed,
  dbtReportFrom,
  defaultOutputName,
  editorSqlSchema,
  fileWrite,
  isDbtTransformNode,
  isPolarsTransformNode,
  isSqlTransformNode,
  isTransformNode,
  modelIndexOf,
  preflightProgram,
  preflightSql,
  preflightTransform,
  programLineCount,
  programSummary,
  publishDbtModel,
  publishedProgram,
  readTransformParams,
  removeDbtModel,
  renameDbtModel,
  requirementLines,
  starterProgramFor,
  starterSqlFor,
  transformDefaultParams,
  transformEngineOf,
  transformErrorPosition,
  transformChecklist,
  transformFailure,
  transformFailureFromExecution,
  transformFiles,
  transformViewName,
  type TransformParams,
  type TransformSourceCatalogEntry,
} from './flow-transform.vm';
import { FLOW_EN, FLOW_FR } from '@app/core/i18n/flow.dict';

function sqlNode(config: Record<string, unknown> = {}): CanonicalFlowNode {
  return {
    id: 'task.sql',
    type: 'skill',
    kind: 'task',
    label: 'Churn features',
    config: { skill_slug: SQL_TRANSFORM_SKILL_SLUG, ...config },
  };
}

function source(
  view: string,
  columns: string[],
  aliases: string[] = [],
): TransformSourceCatalogEntry {
  return {
    view,
    aliases,
    dataset_id: `ds-${view}`,
    name: view,
    rows: 1200,
    columns: columns.map((name) => ({ name, kind: 'string' as const })),
  };
}

test('isSqlTransformNode matches only task nodes bound to the transform skill', () => {
  assert.equal(isSqlTransformNode(sqlNode()), true);
  assert.equal(isSqlTransformNode(null), false);
  assert.equal(isSqlTransformNode(undefined), false);
  assert.equal(
    isSqlTransformNode({ id: 'a', type: 'skill', kind: 'task', config: { skill_slug: 'x' } }),
    false,
  );
  assert.equal(
    isSqlTransformNode({
      id: 'a',
      type: 'skill',
      kind: 'source',
      config: { skill_slug: SQL_TRANSFORM_SKILL_SLUG },
    }),
    false,
    'a source node bound to the skill is not an authorable transform',
  );
});

test('reading the params falls back to the runnable starter statement', () => {
  const params = readTransformParams(sqlNode());
  assert.equal(params.program, SQL_TRANSFORM_DEFAULT_SQL);
  assert.equal(params.output_name, '');
  assert.deepEqual(params.sources, []);
});

test('reading the params keeps only pins that reference a dataset', () => {
  const params = readTransformParams(
    sqlNode({
      params: {
        sql: 'SELECT 1',
        output_name: '  churn features  ',
        sources: [
          { view: ' customers ', dataset_slug: 'customers' },
          { view: 'orphan' },
          { dataset_id: 'ds-1' },
          'nope',
          null,
        ],
      },
    }),
  );
  assert.equal(params.program, 'SELECT 1');
  assert.equal(params.output_name, 'churn features');
  assert.deepEqual(params.sources, [
    { view: 'customers', dataset_slug: 'customers' },
    { dataset_id: 'ds-1' },
  ]);
});

test('a legacy slug key on a pin is still resolved', () => {
  const params = readTransformParams(
    sqlNode({ params: { sources: [{ slug: 'usage-daily' }] } }),
  );
  assert.deepEqual(params.sources, [{ dataset_slug: 'usage-daily' }]);
});

test('view names are duckdb-safe, accent-free and never collide', () => {
  assert.equal(transformViewName('Clients résiliés'), 'clients_resilies');
  assert.equal(transformViewName('2024 usage'), 't_2024_usage');
  assert.equal(transformViewName('customers', ['customers']), 'customers_2');
  assert.equal(transformViewName('customers', ['customers', 'customers_2']), 'customers_3');
});

test('the inspector summary skips the engine\'s own comment syntax', () => {
  assert.equal(
    programSummary('-- churn features\n\n  SELECT   a,\n b FROM input\n', 'sql'),
    'SELECT a,',
  );
  assert.equal(programSummary('   \n-- only a comment\n', 'sql'), '');
  assert.equal(
    programSummary('# churn features\nimport polars as pl\n', 'polars'),
    'import polars as pl',
  );
  // A SQL comment marker is a valid Python operator, so the engine decides.
  assert.equal(programSummary('-- x\n', 'polars'), '-- x');
});

test('the line count ignores a single trailing newline', () => {
  assert.equal(programLineCount(''), 0);
  assert.equal(programLineCount('   '), 0);
  assert.equal(programLineCount('SELECT 1\n'), 1);
  assert.equal(programLineCount('SELECT 1\nFROM input\n'), 2);
});

test('the preflight only blocks the two refusals an author hits by habit', () => {
  assert.deepEqual(preflightSql('  '), { key: 'flow.transform.error.SQL_EMPTY' });
  assert.deepEqual(preflightSql('SELECT 1; SELECT 2'), {
    key: 'flow.transform.error.SQL_MULTIPLE_STATEMENTS',
  });
  assert.deepEqual(preflightSql(`SELECT ${'x'.repeat(SQL_MAX_CHARS)}`), {
    key: 'flow.transform.error.SQL_TOO_LONG',
  });
  assert.equal(preflightSql('SELECT * FROM input;'), null, 'one trailing ; is fine');
  assert.equal(
    preflightSql("SELECT * FROM input WHERE label = 'a;b'"),
    null,
    'a semicolon inside a literal is not a second statement',
  );
  assert.equal(
    preflightSql('DROP TABLE input'),
    null,
    'the forbidden-keyword verdict stays the server’s to give',
  );
});

test('a coded refusal becomes a translated sentence, engine words kept where they help', () => {
  assert.deepEqual(transformFailure('SQL_FORBIDDEN_KEYWORD', "'DROP' is not allowed"), {
    key: 'flow.transform.error.SQL_FORBIDDEN_KEYWORD',
    detail: undefined,
  });
  assert.deepEqual(
    transformFailure('sql_execution_failed', 'Referenced column "churn" not found'),
    {
      key: 'flow.transform.error.SQL_EXECUTION_FAILED',
      detail: 'Referenced column "churn" not found',
    },
  );
  assert.deepEqual(transformFailure('SOMETHING_NEW', 'boom'), {
    key: 'flow.transform.error.unknown',
    detail: 'boom',
  });
  assert.deepEqual(transformFailure(null, null), {
    key: 'flow.transform.error.unknown',
    detail: undefined,
  });
});

test('a refusal that names a place carries it, so the cursor can go there', () => {
  // The coordinate is what turns "Referenced column not found" from a sentence
  // to read into a place to look. Without it the author counts lines by hand.
  assert.deepEqual(
    transformFailure('SQL_EXECUTION_FAILED', 'Referenced column "nosuchcol" not found', {
      line: 3,
      column: 3,
      excerpt: '  nosuchcol',
    }),
    {
      key: 'flow.transform.error.SQL_EXECUTION_FAILED',
      detail: 'Referenced column "nosuchcol" not found',
      position: { line: 3, column: 3 },
    },
  );
  // A refusal with no place stays as it was: no `position` key at all, rather
  // than one pointing at line 1, which would move the caret for no reason.
  assert.ok(!('position' in transformFailure('SQL_RESULT_TOO_LARGE', 'too many rows')));
});

test('a coordinate is validated before it is used to move a caret', () => {
  assert.deepEqual(transformErrorPosition({ line: 4, column: 9 }), { line: 4, column: 9 });
  // A line without a column is still usable: the start of the line is a place.
  assert.deepEqual(transformErrorPosition({ line: 2 }), { line: 2, column: 1 });
  // Everything else would either throw on use or silently jump to the top of
  // the document, which reads as the editor losing the author's place.
  assert.equal(transformErrorPosition({ line: 0, column: 1 }), null);
  assert.equal(transformErrorPosition({ line: '3', column: 1 }), null);
  assert.equal(transformErrorPosition({ column: 4 }), null);
  assert.equal(transformErrorPosition(null), null);
  assert.equal(transformErrorPosition('3:4'), null);
  assert.deepEqual(transformErrorPosition({ line: 2.7, column: 5.9 }), { line: 2, column: 5 });
});

test('every refusal code the workshop claims has FR and EN copy', () => {
  for (const code of [...TRANSFORM_ERROR_CODES, 'unknown']) {
    const key = `flow.transform.error.${code}`;
    assert.ok(FLOW_FR[key as keyof typeof FLOW_FR], `missing FR copy for ${key}`);
    assert.ok(FLOW_EN[key as keyof typeof FLOW_EN], `missing EN copy for ${key}`);
  }
});

test('the completion schema exposes every name the statement can address', () => {
  const schema = editorSqlSchema([
    source('customers', ['id', 'churn'], ['input', 'input_1']),
    source('usage', ['id', 'minutes'], ['input_2']),
  ]);
  assert.deepEqual(schema['customers'], ['id', 'churn']);
  assert.deepEqual(schema['input'], ['id', 'churn'], 'the alias completes like the view');
  assert.deepEqual(schema['input_1'], ['id', 'churn']);
  assert.deepEqual(schema['input_2'], ['id', 'minutes']);
});

test('the starter statement projects real columns, capped so it stays readable', () => {
  const wide = source('customers', ['a', 'b', 'c', 'd', 'e', 'f', 'g']);
  assert.equal(starterSqlFor(wide), 'SELECT\n  a,\n  b,\n  c,\n  d,\n  e,\n  f\nFROM customers\nLIMIT 100\n');
  assert.equal(starterSqlFor(source('empty', [])), 'SELECT\n  *\nFROM empty\nLIMIT 100\n');
});

test('the output name falls back to the node label, then to the caller default', () => {
  assert.equal(defaultOutputName('  Churn features ', 'sql result'), 'Churn features');
  assert.equal(defaultOutputName('', 'sql result'), 'sql result');
  assert.equal(defaultOutputName(undefined, 'sql result'), 'sql result');
});

// ---------------------------------------------------------------------------
// Polars engine
// ---------------------------------------------------------------------------

function polarsNode(config: Record<string, unknown> = {}): CanonicalFlowNode {
  return {
    id: 'task.polars',
    type: 'skill',
    kind: 'task',
    label: 'Churn features',
    config: { skill_slug: POLARS_TRANSFORM_SKILL_SLUG, ...config },
  };
}

test('the engine is read off the bound skill, and only for authorable nodes', () => {
  assert.equal(transformEngineOf(sqlNode()), 'sql');
  assert.equal(transformEngineOf(polarsNode()), 'polars');
  assert.equal(transformEngineOf(null), null);
  assert.equal(isTransformNode(polarsNode()), true);
  assert.equal(isPolarsTransformNode(polarsNode()), true);
  assert.equal(isPolarsTransformNode(sqlNode()), false);
  assert.equal(isSqlTransformNode(polarsNode()), false);
});

test('a dropped Polars node carries a runnable script and its environment', () => {
  const params = transformDefaultParams('polars');
  assert.equal(params['code'], POLARS_TRANSFORM_DEFAULT_CODE);
  assert.equal(params['requirements_text'], '');
  assert.equal(params['timeout_s'], 180);
  // SQL needs no venv, so it must NOT carry environment params.
  assert.equal('requirements_text' in transformDefaultParams('sql'), false);
});

test('the program is read from the engine\'s own params field', () => {
  const params = readTransformParams(
    polarsNode({
      params: {
        code: 'def transform(inputs):\n    return inputs["input"]\n',
        // A stale SQL statement on a Polars node must never be read as code.
        sql: 'SELECT 1',
        requirements_text: 'scikit-learn==1.5.0',
        timeout_s: 9000,
      },
    }),
  );
  assert.match(params.program, /^def transform/);
  assert.equal(params.requirements_text, 'scikit-learn==1.5.0');
  assert.equal(params.timeout_s, 600, 'the client mirrors the server ceiling');
});

test('the timeout clamps to the platform window', () => {
  assert.equal(clampTransformTimeout(undefined), 180);
  assert.equal(clampTransformTimeout('nope'), 180);
  assert.equal(clampTransformTimeout(0), 180);
  assert.equal(clampTransformTimeout(-5), 180);
  assert.equal(clampTransformTimeout('45'), 45);
  assert.equal(clampTransformTimeout(10_000), 600);
});

test('the Python preflight blocks an empty editor and a missing entry point', () => {
  assert.deepEqual(preflightProgram('  ', 'polars'), {
    key: 'flow.transform.error.POLARS_CODE_REQUIRED',
  });
  assert.deepEqual(preflightProgram('frame = 1\n', 'polars'), {
    key: 'flow.transform.error.POLARS_TRANSFORM_MISSING',
  });
  assert.equal(
    preflightProgram('def transform(inputs):\n    return inputs["input"]\n', 'polars'),
    null,
  );
  assert.equal(
    preflightProgram('  def transform (inputs):\n    pass\n', 'polars'),
    null,
    'spacing is Python\'s business, not a refusal',
  );
  // A statement with two semicolons is a SQL refusal, never a Python one.
  assert.equal(preflightProgram('def transform(i):\n    a = 1; b = 2\n', 'polars'), null);
});

test('a worker-side refusal parses back into its code and the author\'s words', () => {
  assert.deepEqual(
    transformFailureFromExecution("POLARS_SCRIPT_RAISED: KeyError: 'arpu_v2'"),
    {
      key: 'flow.transform.error.POLARS_SCRIPT_RAISED',
      detail: "KeyError: 'arpu_v2'",
    },
  );
  assert.deepEqual(transformFailureFromExecution('POLARS_TIMEOUT: exceeded 180s'), {
    key: 'flow.transform.error.POLARS_TIMEOUT',
    detail: undefined,
  });
  assert.deepEqual(transformFailureFromExecution(''), {
    key: 'flow.transform.error.unknown',
  });
  assert.deepEqual(transformFailureFromExecution('something odd'), {
    key: 'flow.transform.error.unknown',
    detail: 'something odd',
  });
});

test('the Polars starter script addresses the source by its real name', () => {
  const starter = starterProgramFor(source('subscribers', ['msisdn', 'arpu']), 'polars');
  assert.match(starter, /import polars as pl/);
  assert.match(starter, /def transform\(inputs: dict\[str, pl\.DataFrame\]\) -> pl\.DataFrame:/);
  assert.match(starter, /inputs\["subscribers"\]/);
  assert.match(starter, /frame\.select\("msisdn", "arpu"\)/);
  // No columns known yet: still runnable rather than a syntax error.
  assert.match(starterProgramFor(source('empty', []), 'polars'), /pl\.all\(\)/);
});

test('declared libraries drop blanks and comments', () => {
  assert.deepEqual(
    requirementLines('  scikit-learn==1.5.0 \n\n# a note\nstatsmodels\n'),
    ['scikit-learn==1.5.0', 'statsmodels'],
  );
  assert.deepEqual(requirementLines(''), []);
});

// ---------------------------------------------------------------------------
// dbt engine — a project of models, gated by its own data tests
// ---------------------------------------------------------------------------

function dbtNode(config: Record<string, unknown> = {}): CanonicalFlowNode {
  return {
    id: 'task.dbt',
    type: 'skill',
    kind: 'task',
    label: 'Churn marts',
    config: { skill_slug: DBT_TRANSFORM_SKILL_SLUG, ...config },
  };
}

function project(
  models: Array<{ name: string; sql: string }>,
  output_model = models.at(-1)?.name ?? '',
): TransformParams {
  return readTransformParams(
    dbtNode({ params: { models, output_model, tests_yml: 'version: 2\n' } }),
  );
}

test('a dropped dbt node carries a staging model, a mart and a tests file', () => {
  const params = transformDefaultParams('dbt');
  assert.deepEqual(params['models'], DBT_TRANSFORM_DEFAULT_MODELS.map((m) => ({ ...m })));
  assert.equal(params['tests_yml'], DBT_TRANSFORM_DEFAULT_TESTS_YML);
  assert.equal(params['output_model'], 'mart_output');
  assert.equal(params['timeout_s'], 300, 'a project compiles before its first model runs');
  assert.equal(transformEngineOf(dbtNode()), 'dbt');
  assert.equal(isDbtTransformNode(dbtNode()), true);
  assert.equal(isDbtTransformNode(sqlNode()), false);
  assert.equal(isTransformNode(dbtNode()), true);
});

test('a dbt node with no chosen mart still publishes its last model', () => {
  const params = readTransformParams(
    dbtNode({ params: { models: [{ name: 'a', sql: 'select 1' }, { name: 'b', sql: 'select 2' }] } }),
  );
  assert.equal(params.output_model, 'b', 'mirrors resolve_output_model on the server');
  assert.equal(publishedProgram(params, 'dbt'), 'select 2');
  // An explicit choice wins over the positional default.
  assert.equal(publishedProgram(project([{ name: 'a', sql: 'select 1' }, { name: 'b', sql: 'select 2' }], 'a'), 'dbt'), 'select 1');
});

test('the file list is the project: models first, the tests gate last', () => {
  const params = project([
    { name: 'stg', sql: 'select 1' },
    { name: 'mart', sql: 'select 2' },
  ]);
  const files = transformFiles(params, 'dbt');
  assert.deepEqual(
    files.map((file) => [file.id, file.name, file.language, file.kind]),
    [
      ['models.0', 'stg.sql', 'sql', 'model'],
      ['models.1', 'mart.sql', 'sql', 'model'],
      ['tests_yml', 'schema.yml', 'yaml', 'tests'],
    ],
  );
  assert.equal(files[1].published, true, 'the mart is badged, not the staging model');
  assert.equal(files[0].published, false);
  // A single-statement engine yields exactly one file, so one editor serves all.
  const single = transformFiles(readTransformParams(sqlNode()), 'sql');
  assert.equal(single.length, 1);
  assert.equal(single[0].name, 'transform.sql');
  assert.equal(transformFiles(readTransformParams(polarsNode()), 'polars')[0].name, 'transform.py');
});

test('editing a file writes to the params path that file lives in', () => {
  const params = project([
    { name: 'stg', sql: 'select 1' },
    { name: 'mart', sql: 'select 2' },
  ]);
  assert.deepEqual(fileWrite(params, 'dbt', 'models.0', 'select 9'), {
    path: 'params.models',
    value: [
      { name: 'stg', sql: 'select 9' },
      { name: 'mart', sql: 'select 2' },
    ],
  });
  assert.deepEqual(fileWrite(params, 'dbt', 'tests_yml', 'version: 2\n'), {
    path: 'params.tests_yml',
    value: 'version: 2\n',
  });
  assert.equal(
    fileWrite(params, 'dbt', 'models.7', 'select 9'),
    null,
    'a stale file id writes nothing rather than growing the project',
  );
  // A single-file engine writes the field its descriptor owns.
  assert.deepEqual(fileWrite(readTransformParams(sqlNode()), 'sql', 'sql', 'SELECT 2'), {
    path: 'params.sql',
    value: 'SELECT 2',
  });
  assert.equal(modelIndexOf('models.3'), 3);
  assert.equal(modelIndexOf('tests_yml'), null);
});

test('renaming a model follows its refs and its publication', () => {
  const params = project([
    { name: 'stg_input', sql: "select * from {{ source('inputs', 'input') }}" },
    { name: 'mart', sql: "select * from {{ ref('stg_input') }}\nunion all\nselect * from {{ ref( \"stg_input\" ) }}" },
  ]);
  const patch = renameDbtModel(params, 0, ' stg_subscribers ');
  const models = patch['models'] as Array<{ name: string; sql: string }>;
  assert.equal(models[0].name, 'stg_subscribers');
  assert.match(models[1].sql, /ref\('stg_subscribers'\)/);
  assert.match(models[1].sql, /ref\( "stg_subscribers" \)/, 'both quote styles move');
  assert.doesNotMatch(models[1].sql, /stg_input/);
  assert.equal(patch['output_model'], 'mart', 'renaming a staging model changes nothing else');
  // Renaming the published model hands the publication over with it.
  assert.equal(renameDbtModel(params, 1, 'mart_churn')['output_model'], 'mart_churn');
  // A no-op rename writes nothing at all.
  assert.deepEqual(renameDbtModel(params, 0, 'stg_input'), {});
  assert.deepEqual(renameDbtModel(params, 0, '   '), {});
});

test('adding a model chains it onto the published one', () => {
  const params = project([{ name: 'stg', sql: 'select 1' }]);
  const models = addDbtModel(params)['models'] as Array<{ name: string; sql: string }>;
  assert.equal(models.length, 2);
  assert.equal(models[1].name, 'new_model');
  assert.match(models[1].sql, /from \{\{ ref\('stg'\) \}\}/, 'the new model reads the old mart');
  // Names never collide, so `ref()` is never ambiguous.
  const twice = addDbtModel(project(models))['models'] as Array<{ name: string }>;
  assert.equal(twice[2].name, 'new_model_2');
});

test('deleting a model hands the publication over, and the last one is kept', () => {
  const params = project([
    { name: 'stg', sql: 'select 1' },
    { name: 'mart', sql: "select * from {{ ref('stg') }}" },
  ]);
  const patch = removeDbtModel(params, 1);
  assert.deepEqual(patch['models'], [{ name: 'stg', sql: 'select 1' }]);
  assert.equal(patch['output_model'], 'stg', 'something is always published');
  // Deleting a model a survivor still refs leaves the ref dangling ON PURPOSE:
  // the build refusal is more honest than a silent re-point.
  const upstream = removeDbtModel(params, 0);
  assert.match(
    (upstream['models'] as Array<{ sql: string }>)[0].sql,
    /ref\('stg'\)/,
  );
  assert.deepEqual(
    removeDbtModel(project([{ name: 'only', sql: 'select 1' }]), 0),
    {},
    'a project cannot become empty',
  );
});

test('publishing another model is the only field it touches', () => {
  const params = project([
    { name: 'stg', sql: 'select 1' },
    { name: 'mart', sql: 'select 2' },
  ]);
  assert.deepEqual(publishDbtModel(params, 'stg'), { output_model: 'stg' });
  assert.deepEqual(
    publishDbtModel(params, 'ghost'),
    {},
    'a model that is not in the project cannot be published',
  );
});

test('the dbt preflight refuses the project shapes dbt could not compile', () => {
  assert.deepEqual(preflightTransform(project([{ name: 'a', sql: '  ' }]), 'dbt'), {
    key: 'flow.transform.error.DBT_MODELS_REQUIRED',
  });
  assert.deepEqual(
    preflightTransform(project([{ name: 'Stg Input', sql: 'select 1' }]), 'dbt'),
    { key: 'flow.transform.error.DBT_MODEL_NAME_INVALID', detail: 'Stg Input' },
  );
  assert.deepEqual(
    preflightTransform(
      project([
        { name: 'stg', sql: 'select 1' },
        { name: 'stg', sql: 'select 2' },
      ]),
      'dbt',
    ),
    { key: 'flow.transform.error.DBT_MODEL_NAME_DUPLICATE', detail: 'stg' },
  );
  assert.deepEqual(
    preflightTransform(
      project([
        { name: 'stg', sql: 'select 1' },
        { name: 'mart', sql: '   ' },
      ]),
      'dbt',
    ),
    { key: 'flow.transform.error.DBT_MODEL_EMPTY', detail: 'mart' },
  );
  assert.deepEqual(
    preflightTransform(project([{ name: 'stg', sql: 'select 1' }], 'ghost'), 'dbt'),
    { key: 'flow.transform.error.DBT_OUTPUT_MODEL_MISSING', detail: 'ghost' },
  );
  const tooMany = Array.from({ length: DBT_MAX_MODELS + 1 }, (_v, i) => ({
    name: `m_${i}`,
    sql: 'select 1',
  }));
  assert.deepEqual(preflightTransform(project(tooMany), 'dbt'), {
    key: 'flow.transform.error.DBT_TOO_MANY_MODELS',
  });
  assert.equal(
    preflightTransform(
      project([
        { name: 'stg_input', sql: "select * from {{ source('inputs', 'input') }}" },
        { name: 'mart_output', sql: "select * from {{ ref('stg_input') }}" },
      ]),
      'dbt',
    ),
    null,
  );
  // A broken ref, an unknown column, a shadowed source: still the server's call.
  assert.equal(
    preflightTransform(project([{ name: 'stg', sql: "select * from {{ ref('gone') }}" }]), 'dbt'),
    null,
  );
});

test('the dbt starter teaches source(), not the bare relation', () => {
  const starter = starterProgramFor(source('subscribers', ['msisdn', 'arpu']), 'dbt');
  assert.match(starter, /from \{\{ source\('inputs', 'subscribers'\) \}\}/);
  assert.match(starter, /select\n {2}msisdn,\n {2}arpu/);
  assert.doesNotMatch(starter, /LIMIT/, 'a dbt model materialises, it does not sample');
});

test('the build verdict is read off the row on success and on refusal alike', () => {
  const report = dbtReportFrom({
    kind: 'dbt_failed',
    dbt: {
      nodes: [
        { kind: 'model', name: 'stg_input', status: 'success', failures: 0, duration_ms: 12 },
        { kind: 'test', name: 'not_null_mart_msisdn', status: 'fail', failures: 37 },
      ],
      models_total: 1,
      tests_total: 1,
      tests_failed: 1,
      selected: 'mart_output',
    },
  });
  assert.ok(report);
  assert.equal(report.tests_failed, 1);
  assert.equal(report.selected, 'mart_output');
  assert.equal(dbtNodePassed(report.nodes[0]), true);
  assert.equal(dbtNodePassed(report.nodes[1]), false);
  assert.equal(report.nodes[1].failures, 37, 'how many rows refused IS the answer');
  // A Polars row carries no verdict, and that must not read as a failed build.
  assert.equal(dbtReportFrom({ kind: 'polars_preview', row_count: 3 }), null);
  assert.equal(dbtReportFrom(null), null);
});

test('a worker-side dbt refusal parses back into its code and its words', () => {
  assert.deepEqual(
    transformFailureFromExecution(
      'DBT_TESTS_FAILED: not_null_mart_output_msisdn (37 rows)',
    ),
    {
      key: 'flow.transform.error.DBT_TESTS_FAILED',
      detail: 'not_null_mart_output_msisdn (37 rows)',
    },
  );
  assert.deepEqual(
    transformFailureFromExecution('DBT_BUILD_FAILED: Referenced column "churn" not found'),
    {
      key: 'flow.transform.error.DBT_BUILD_FAILED',
      detail: 'Referenced column "churn" not found',
    },
  );
});

test('every engine label the workshop renders has FR and EN copy', () => {
  for (const descriptor of Object.values(TRANSFORM_ENGINES)) {
    for (const key of Object.values(descriptor.copy)) {
      assert.ok(FLOW_FR[key as keyof typeof FLOW_FR], `missing FR copy for ${key}`);
      assert.ok(FLOW_EN[key as keyof typeof FLOW_EN], `missing EN copy for ${key}`);
    }
  }
  for (const key of [
    'flow.transform.phase.queued',
    'flow.transform.phase.env_building',
    'flow.transform.phase.running',
    'flow.transform.run.cancel',
    'flow.transform.stdout',
    'flow.transform.tab.environment',
    'flow.transform.environment.hint',
    'flow.transform.environment.requirements',
    'flow.transform.environment.requirements.placeholder',
    'flow.transform.environment.count',
    'flow.transform.environment.timeout',
    'flow.transform.error.POLARS_CANCELLED',
    'flow.transform.error.DBT_CANCELLED',
    'flow.transform.files.aria',
    'flow.transform.files.add',
    'flow.transform.files.remove',
    'flow.transform.files.publish',
    'flow.transform.files.publish.hint',
    'flow.transform.files.published',
    'flow.transform.files.published.hint',
    'flow.transform.files.rename.aria',
    'flow.transform.files.tests.label',
    'flow.transform.dbt.build.passed',
    'flow.transform.dbt.build.refused',
    'flow.transform.dbt.build.failures',
  ]) {
    assert.ok(FLOW_FR[key as keyof typeof FLOW_FR], `missing FR copy for ${key}`);
    assert.ok(FLOW_EN[key as keyof typeof FLOW_EN], `missing EN copy for ${key}`);
  }
});

test('a preview says which phase it is in, and skips one it will never enter', () => {
  const states = (engine: 'sql' | 'polars' | 'dbt', phase: string | null) =>
    transformChecklist(engine, phase).map((step) => `${step.phase}:${step.state}`);

  // duckdb runs in the worker, so SQL has no environment to build. A line that
  // will never tick reads as a step that is stuck.
  assert.deepEqual(states('sql', 'queued'), ['queued:active', 'running:todo']);
  assert.deepEqual(states('sql', 'running'), ['queued:done', 'running:active']);
  // Polars and dbt do, and the first run in a workspace spends most of its wait
  // there — which is the whole reason the phase is shown rather than a spinner.
  assert.deepEqual(states('polars', 'env_building'), [
    'queued:done',
    'env_building:active',
    'running:todo',
  ]);
  assert.deepEqual(states('dbt', 'running'), [
    'queued:done',
    'env_building:done',
    'running:active',
  ]);
  // A terminal status, or none at all, is past every phase: the result or the
  // refusal below says how it went.
  for (const phase of ['succeeded', 'failed', 'cancelled', null, '']) {
    assert.deepEqual(states('polars', phase), [
      'queued:done',
      'env_building:done',
      'running:done',
    ]);
  }
  for (const { key } of transformChecklist('dbt', 'queued')) {
    assert.ok(FLOW_FR[key as keyof typeof FLOW_FR], `missing FR copy for ${key}`);
    assert.ok(FLOW_EN[key as keyof typeof FLOW_EN], `missing EN copy for ${key}`);
  }
});
